"""Sprint 27 historical evidence recovery and eligibility reconciliation.

Separates descriptive market evidence from strict clean-title valuation evidence.
Unknown titles remain unknown. Adverse titles never enter either population.
"""
from __future__ import annotations
from typing import Any
import math
import pandas as pd

COMPLETED = {"sold", "completed", "sale", "sold_pending_title"}
UNKNOWN_TITLES = {"", "unknown", "review", "not stated", "pending"}
ADVERSE_TITLE_TERMS = ("salvage", "rebuilt", "flood", "total loss", "total-loss", "branded")
STRICT_VARIANT_STATUS = {"existing_variant_id", "mapped_explicit_variant_alias", "verified_crosswalk"}
SPRINT25_VARIANT_STATUS = STRICT_VARIANT_STATUS | {"mapped_make_model_year"}

def _norm(value: Any) -> str:
    return str(value if value is not None else "").strip().lower()

def _series(df: pd.DataFrame, key: str) -> pd.Series:
    return df.get(key, pd.Series("", index=df.index)).fillna("").astype(str)

def _stage(count: int, total: int) -> dict[str, int | float]:
    return {"rows": int(count), "failed": int(total - count), "rate": round(count / total, 6) if total else 0.0}

def _adverse(series: pd.Series) -> pd.Series:
    return series.map(lambda value: any(term in _norm(value) for term in ADVERSE_TITLE_TERMS))

def _variant_stage(row: pd.Series) -> str:
    status = _norm(row.get("variant_normalization_status"))
    source_variant = _norm(row.get("source_variant_id"))
    variant = _norm(row.get("vehicle_variant_id"))
    if not variant and not source_variant:
        return "missing_variant"
    if status in STRICT_VARIANT_STATUS and variant:
        return "strict_verified"
    if status == "mapped_make_model_year" and variant:
        return "sprint25_make_model_year"
    if status == "normalized_from_source" and (source_variant or variant):
        return "source_normalized"
    if status == "provisional_unmapped" and (source_variant or variant):
        return "source_provisional"
    if status == "ambiguous_unresolved":
        return "ambiguous_unresolved"
    return "unclassified"

def _canonical_id(row: pd.Series) -> str:
    source_variant = str(row.get("source_variant_id") or "").strip()
    variant = str(row.get("vehicle_variant_id") or "").strip()
    return source_variant or variant

def _variant_confidence(stage: str) -> str:
    return {
        "strict_verified": "high",
        "sprint25_make_model_year": "medium",
        "source_normalized": "low",
        "source_provisional": "exploratory",
        "ambiguous_unresolved": "unresolved",
    }.get(stage, "unresolved")

def _median_iqr(values: pd.Series) -> tuple[float | None, float | None, float | None]:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return None, None, None
    q1, med, q3 = x.quantile([0.25, 0.5, 0.75])
    return float(med), float(q1), float(q3)

def _adjusted_median(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    prices = pd.to_numeric(frame["_price"], errors="coerce")
    miles = pd.to_numeric(frame["_mileage"], errors="coerce")
    valid = prices.gt(0) & prices.notna()
    prices = prices[valid].copy()
    miles = miles[valid]
    if prices.empty:
        return None
    target = miles.median() if miles.notna().any() else None
    if target is not None:
        known = miles.notna()
        factor = 1 + ((miles[known] - target) / 1000 * 0.0005).clip(-0.25, 0.25)
        prices.loc[known] = prices.loc[known] * factor
    prices = prices.sort_values()
    if len(prices) >= 8:
        prices = prices.iloc[1:-1]
    return float(prices.median())

def _valuation_rows(frame: pd.DataFrame, as_of: str, min_comparables: int, evidence_tier: str) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    cutoff = pd.Timestamp(as_of)
    windows = {
        "current": (cutoff - pd.DateOffset(months=6), cutoff),
        "prior24": (cutoff - pd.DateOffset(months=30), cutoff - pd.DateOffset(months=24)),
        "prior60": (cutoff - pd.DateOffset(months=66), cutoff - pd.DateOffset(months=60)),
    }
    rows: list[dict[str, Any]] = []
    for cohort, group in frame.groupby("_canonical_id", dropna=False):
        if not cohort:
            continue
        endpoint = {name: group[group["_date"].between(lo, hi, inclusive="both")] for name, (lo, hi) in windows.items()}
        current = _adjusted_median(endpoint["current"])
        prior24 = _adjusted_median(endpoint["prior24"])
        prior60 = _adjusted_median(endpoint["prior60"])
        support24 = len(endpoint["current"]) >= min_comparables and len(endpoint["prior24"]) >= min_comparables
        support60 = len(endpoint["current"]) >= min_comparables and len(endpoint["prior60"]) >= min_comparables
        r24 = (current / prior24 - 1) * 100 if support24 and prior24 else None
        r60 = (current / prior60 - 1) * 100 if support60 and prior60 else None
        _, q1, q3 = _median_iqr(endpoint["current"]["_price"])
        rows.append({
            "vehicle_variant_id": str(cohort),
            "valuation_date": as_of,
            "evidence_tier": evidence_tier,
            "current_value_usd": current,
            "current_comparables": int(len(endpoint["current"])),
            "prior24_value_usd": prior24,
            "prior24_comparables": int(len(endpoint["prior24"])),
            "prior60_value_usd": prior60,
            "prior60_comparables": int(len(endpoint["prior60"])),
            "return_24m_pct": r24,
            "return_60m_pct": r60,
            "supported_24m": bool(support24),
            "supported_60m": bool(support60),
            "confidence": "validated" if evidence_tier == "validated_clean_title" and support24 else "exploratory" if current is not None else "insufficient_evidence",
            "current_iqr_low_usd": q1,
            "current_iqr_high_usd": q3,
            "adjustment_model_version": "s27_bounded_mileage_trimmed_median_v1",
            "supporting_transaction_ids": ",".join(endpoint["current"]["transaction_id"].astype(str).head(50)),
            "supporting_source_urls": ",".join(endpoint["current"]["source_url"].astype(str).head(50)),
        })
    return rows

def analyze(frame: pd.DataFrame, as_of: str = "2026-11-20", min_comparables: int = 5) -> dict[str, Any]:
    if frame.empty:
        raise ValueError("empty production input")
    df = frame.copy()
    total = len(df)
    df["_status"] = _series(df, "sale_status").map(_norm)
    df["_title"] = _series(df, "title_status").map(_norm)
    df["_price"] = pd.to_numeric(df.get("price_usd", pd.Series(index=df.index)), errors="coerce")
    df["_date"] = pd.to_datetime(df.get("auction_end_date", pd.Series(index=df.index)), errors="coerce")
    df["_mileage"] = pd.to_numeric(df.get("mileage_at_sale", pd.Series(index=df.index)), errors="coerce")
    df["_title_unknown"] = df["_title"].isin(UNKNOWN_TITLES)
    df["_title_adverse"] = _adverse(df["_title"])
    df["_title_class"] = "verified_clean_or_other"
    df.loc[df["_title_unknown"], "_title_class"] = "unknown"
    df.loc[df["_title_adverse"], "_title_class"] = "adverse"
    df["_completed"] = df["_status"].isin(COMPLETED)
    df["_valid_price"] = df["_price"].gt(0) & df["_price"].lt(float("inf"))
    df["_valid_date"] = df["_date"].notna() & df["_date"].le(pd.Timestamp(as_of))
    df["_variant_stage"] = df.apply(_variant_stage, axis=1)
    df["_canonical_id"] = df.apply(_canonical_id, axis=1)
    df["_variant_strict"] = df["_variant_stage"].eq("strict_verified")
    df["_variant_sprint25"] = df["_variant_stage"].isin(SPRINT25_VARIANT_STATUS and {"strict_verified", "sprint25_make_model_year"})
    df["_market_evidence"] = (
        df["_completed"] & df["_valid_price"] & df["_valid_date"] &
        ~df["_title_adverse"] & df["_canonical_id"].ne("") &
        _series(df, "source_url").str.strip().ne("")
    )
    df["_validated_clean"] = df["_market_evidence"] & df["_title_class"].eq("verified_clean_or_other") & df["_variant_strict"]
    df["_clean_unassigned"] = df["_market_evidence"] & df["_title_class"].eq("verified_clean_or_other") & ~df["_variant_strict"]
    reasons = pd.Series("eligible_market_evidence", index=df.index, dtype="object")
    checks = [
        (~df["_completed"], "not_completed_sale"),
        (~df["_valid_price"], "missing_or_invalid_price"),
        (~df["_valid_date"], "missing_or_future_transaction_date"),
        (df["_title_adverse"], "adverse_title"),
        (df["_title_unknown"], "title_status_unverified_market_only"),
        (df["_canonical_id"].eq(""), "missing_variant_cohort"),
    ]
    for mask, reason in checks:
        reasons.loc[(reasons == "eligible_market_evidence") & mask] = reason
    df["market_evidence_reason"] = reasons
    df["validated_eligibility_reason"] = "validated_clean_title_variant"
    df.loc[~df["_validated_clean"], "validated_eligibility_reason"] = "not_validated_clean_title_variant"
    df["analysis_class"] = "excluded"
    df.loc[df["_market_evidence"], "analysis_class"] = "historical_market_evidence"
    df.loc[df["_market_evidence"] & df["_title_unknown"], "analysis_class"] = "historical_market_evidence_unknown_title"
    df.loc[df["_validated_clean"], "analysis_class"] = "validated_clean_title_valuation"
    df.loc[df["_clean_unassigned"], "analysis_class"] = "clean_title_variant_reconciliation_required"

    strict = df[df["_validated_clean"]].copy()
    market = df[df["_market_evidence"]].copy()
    validated_values = _valuation_rows(strict, as_of, min_comparables, "validated_clean_title")
    market_values = _valuation_rows(market, as_of, min_comparables, "exploratory_market_evidence")
    validated_df = pd.DataFrame(validated_values)
    supported_current = int(sum(r["current_comparables"] >= min_comparables for r in validated_values))
    supported24 = [r for r in validated_values if r["supported_24m"]]
    supported60 = [r for r in validated_values if r["supported_60m"]]
    historical_returns = [
        r for r in validated_values
        if r["supported_24m"] or r["supported_60m"]
    ]
    reasons = df["market_evidence_reason"].value_counts().sort_index().to_dict()

    crosswalk_summary = (
        df.groupby(["_variant_stage", "_title_class"], dropna=False)
        .size().reset_index(name="rows")
        .rename(columns={"_variant_stage": "crosswalk_stage", "_title_class": "title_class"})
        .to_dict("records")
    )
    unassigned = df[df["_clean_unassigned"]].copy()
    cluster = (
        unassigned.groupby(["source_name", "source_variant_id", "vehicle_variant_id"], dropna=False)
        .agg(rows=("transaction_id", "size"), first_source_url=("source_url", "first"))
        .reset_index().sort_values(["rows", "source_variant_id"], ascending=[False, True]).head(200)
        .to_dict("records")
    )
    source_coverage = (
        df.groupby(["source_name", "_title_class", "_variant_stage"], dropna=False)
        .size().reset_index(name="rows")
        .rename(columns={"_title_class": "title_class", "_variant_stage": "crosswalk_stage"})
        .sort_values(["source_name", "rows"], ascending=[True, False])
        .to_dict("records")
    )
    reconciliation = [
        {"population": "Sprint 25 canonical assignment rows", "rows": int(df["_variant_sprint25"].sum()), "status": "legacy_definition"},
        {"population": "Sprint 26 strict canonical assignment rows", "rows": int(df["_variant_strict"].sum()), "status": "strict_definition"},
        {"population": "Sprint 25 minus Sprint 26 mapped_make_model_year rows", "rows": int((df["_variant_stage"] == "sprint25_make_model_year").sum()), "status": "definition_delta"},
        {"population": "Sprint 26 comparable-eligible rows", "rows": int(df["_validated_clean"].sum()), "status": "clean_title_and_strict_variant"},
        {"population": "Sprint 26 legacy dashboard current valuations", "rows": 302, "status": "quarantined_not_reproduced"},
        {"population": "Sprint 26 legacy dashboard supported 24m returns", "rows": 34, "status": "quarantined_not_reproduced"},
        {"population": "Sprint 26 legacy dashboard supported 60m returns", "rows": 7, "status": "quarantined_not_reproduced"},
        {"population": "Sprint 27 validated current valuations", "rows": supported_current, "status": "recalculated"},
        {"population": "Sprint 27 validated 24m returns", "rows": len(supported24), "status": "recalculated"},
        {"population": "Sprint 27 validated 60m returns", "rows": len(supported60), "status": "recalculated"},
    ]
    funnel = {
        "input_rows": total,
        "completed_sale": _stage(int(df["_completed"].sum()), total),
        "valid_positive_price": _stage(int((df["_completed"] & df["_valid_price"]).sum()), total),
        "valid_transaction_date": _stage(int((df["_completed"] & df["_valid_price"] & df["_valid_date"]).sum()), total),
        "historical_market_evidence": _stage(int(df["_market_evidence"].sum()), total),
        "unknown_title_market_evidence": _stage(int((df["_market_evidence"] & df["_title_unknown"]).sum()), total),
        "verified_clean_title": _stage(int((df["_market_evidence"] & df["_title_class"].eq("verified_clean_or_other")).sum()), total),
        "strict_variant_assignment": _stage(int((df["_market_evidence"] & df["_variant_strict"]).sum()), total),
        "validated_clean_title_valuation": _stage(int(df["_validated_clean"].sum()), total),
        "clean_title_variant_reconciliation_required": _stage(int(df["_clean_unassigned"].sum()), total),
        "historical_return_eligible_cohorts": len(historical_returns),
        "repeat_sale_group_rows": int(_series(df, "repeat_sale_group_id").str.strip().ne("").sum()),
        "duplicate_transaction_ids": int(df["transaction_id"].duplicated().sum()),
    }
    return {
        "funnel": funnel,
        "row_audit": df[["transaction_id", "market_evidence_reason", "validated_eligibility_reason", "analysis_class", "_variant_stage", "_title_class"]].rename(columns={"_variant_stage": "crosswalk_stage", "_title_class": "title_class"}).to_dict("records"),
        "valuation": validated_values,
        "market_valuation": market_values,
        "historical_returns": historical_returns,
        "crosswalk_summary": crosswalk_summary,
        "unassigned_clusters": cluster,
        "source_coverage": source_coverage,
        "reconciliation": reconciliation,
        "summary": {
            "input_row_count": total,
            "historical_market_evidence_rows": int(df["_market_evidence"].sum()),
            "historical_market_evidence_unknown_title_rows": int((df["_market_evidence"] & df["_title_unknown"]).sum()),
            "verified_clean_title_rows": int((df["_market_evidence"] & df["_title_class"].eq("verified_clean_or_other")).sum()),
            "strict_variant_assignment_rows": int((df["_market_evidence"] & df["_variant_strict"]).sum()),
            "sprint25_canonical_assignment_rows": int(df["_variant_sprint25"].sum()),
            "clean_title_unassigned_rows": int(df["_clean_unassigned"].sum()),
            "comparable_eligible_rows": int(df["_validated_clean"].sum()),
            "supported_current_valuations": supported_current,
            "supported_24m_returns": len(supported24),
            "supported_60m_returns": len(supported60),
            "qualified_model_opportunities": 0,
            "individual_purchase_opportunities": 0,
            "backtesting_status": "not_validated_no_leakage_safe_oos_pairs",
            "analytical_acceptance": False,
            "historical_appreciation_rule_pct": 5.0,
            "investment_population_status": "blocked_until_validated_returns_and_individual_due_diligence",
        },
        "eligibility_reason_counts": {str(k): int(v) for k, v in reasons.items()},
    }
