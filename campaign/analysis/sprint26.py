"""Sprint 26 analytical reconciliation and evidence-supported outputs.

This module keeps raw observations in memory only. It produces aggregate
diagnostics plus evidence-linked cohort rows for private workbook publication.
"""
from __future__ import annotations
from typing import Any
import math
import pandas as pd

COMPLETED = {"sold", "completed", "sale", "sold_pending_title"}
UNSUCCESSFUL = {"unsold", "no_sale", "no sale", "reserve_not_met", "reserve not met"}
ASKING = {"asking", "for_sale", "for sale", "active", "listing"}
ADVERSE_TITLE_TERMS = ("salvage", "rebuilt", "flood", "total loss", "total-loss", "branded")
UNKNOWN_TITLES = {"", "unknown", "review", "not stated", "pending"}

def _norm(v: Any) -> str:
    return str(v if v is not None else "").strip().lower()

def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")

def _median_iqr(values: pd.Series) -> tuple[float | None, float | None, float | None]:
    x = _num(values).dropna()
    if x.empty:
        return None, None, None
    q1, med, q3 = x.quantile([.25, .5, .75])
    return float(med), float(q1), float(q3)

def _stage(count: int, total: int) -> dict[str, int | float]:
    return {"rows": int(count), "failed": int(total-count), "rate": round(count/total, 6) if total else 0.0}

def _variant_status(frame: pd.DataFrame) -> pd.Series:
    variant = frame.get("vehicle_variant_id", pd.Series("", index=frame.index)).fillna("").astype(str).str.strip()
    status = frame.get("variant_normalization_status", pd.Series("", index=frame.index)).map(_norm)
    accepted = {"mapped_explicit_variant_alias", "existing_variant_id", "verified_crosswalk"}
    return variant.ne("") & status.isin(accepted)

def _title_adverse(title: pd.Series) -> pd.Series:
    return title.map(lambda x: any(term in _norm(x) for term in ADVERSE_TITLE_TERMS))

def analyze(frame: pd.DataFrame, as_of: str = "2026-11-20", min_comparables: int = 5) -> dict[str, Any]:
    df = frame.copy()
    total = len(df)
    if total == 0:
        raise ValueError("empty production input")
    df["_status"] = df.get("sale_status", pd.Series("", index=df.index)).map(_norm)
    df["_title"] = df.get("title_status", pd.Series("", index=df.index)).map(_norm)
    df["_price"] = _num(df.get("price_usd", pd.Series(index=df.index, dtype=float)))
    df["_date"] = pd.to_datetime(df.get("auction_end_date", pd.Series(index=df.index)), errors="coerce")
    df["_mileage"] = _num(df.get("mileage_at_sale", pd.Series(index=df.index, dtype=float)))
    df["_variant"] = df.get("vehicle_variant_id", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    df["_canonical"] = _variant_status(df)
    df["_duplicate"] = df.get("duplicate_group_id", pd.Series("", index=df.index)).fillna("").astype(str).str.strip().ne("")
    df["_adverse_title"] = _title_adverse(df["_title"])
    df["_unknown_title"] = df["_title"].isin(UNKNOWN_TITLES)
    df["_completed"] = df["_status"].isin(COMPLETED)
    df["_valid_date"] = df["_date"].notna() & df["_date"].le(pd.Timestamp(as_of))
    df["_valid_price"] = df["_price"].gt(0) & df["_price"].lt(float("inf"))
    df["_clean_title"] = ~df["_adverse_title"] & ~df["_unknown_title"]
    df["_eligible"] = df["_completed"] & df["_valid_price"] & df["_valid_date"] & df["_clean_title"] & df["_canonical"]
    reasons = pd.Series("eligible", index=df.index, dtype="object")
    checks = [
        (~df["_completed"], "not_completed_sale"),
        (~df["_valid_price"], "missing_or_invalid_price"),
        (~df["_valid_date"], "missing_or_future_transaction_date"),
        (df["_adverse_title"], "adverse_title"),
        (df["_unknown_title"], "title_status_unverified"),
        (~df["_canonical"], "missing_verified_variant_assignment"),
    ]
    for mask, reason in checks:
        reasons.loc[(reasons == "eligible") & mask] = reason
    df["eligibility_reason"] = reasons
    df["analysis_class"] = "enrichment_required"
    df.loc[df["_eligible"], "analysis_class"] = "eligible_for_limited_descriptive_analysis"
    df.loc[df["_eligible"] & df["_mileage"].notna(), "analysis_class"] = "eligible_for_adjusted_valuation_candidate"
    funnel = {
        "input_rows": total,
        "completed_sale": _stage(int(df["_completed"].sum()), total),
        "valid_positive_price": _stage(int((df["_completed"] & df["_valid_price"]).sum()), total),
        "valid_transaction_date": _stage(int((df["_completed"] & df["_valid_price"] & df["_valid_date"]).sum()), total),
        "clean_verified_title": _stage(int((df["_completed"] & df["_valid_price"] & df["_valid_date"] & df["_clean_title"]).sum()), total),
        "verified_variant_assignment": _stage(int((df["_completed"] & df["_valid_price"] & df["_valid_date"] & df["_clean_title"] & df["_canonical"]).sum()), total),
        "comparable_sale_eligible": _stage(int(df["_eligible"].sum()), total),
        "duplicate_group_rows": int(df["_duplicate"].sum()),
        "repeat_sale_group_rows": int(df.get("repeat_sale_group_id", pd.Series("", index=df.index)).fillna("").astype(str).str.strip().ne("").sum()),
    }
    cutoff = pd.Timestamp(as_of)
    windows = {
        "current": (cutoff - pd.DateOffset(months=6), cutoff),
        "prior24": (cutoff - pd.DateOffset(months=30), cutoff - pd.DateOffset(months=24)),
        "prior60": (cutoff - pd.DateOffset(months=66), cutoff - pd.DateOffset(months=60)),
    }
    cohorts = []
    x = df[df["_eligible"]].copy()
    for cohort, g in x.groupby("_variant", dropna=False):
        endpoint = {}
        for name, (lo, hi) in windows.items():
            endpoint[name] = g[g["_date"].between(lo, hi, inclusive="both")].copy()
        def adjusted_median(v: pd.DataFrame) -> float | None:
            if v.empty:
                return None
            med_miles = v["_mileage"].median()
            adjusted = v["_price"].copy()
            known = v["_mileage"].notna() & med_miles.notna()
            factor = 1 + ((v.loc[known, "_mileage"] - med_miles) / 1000 * 0.0005).clip(-.25, .25)
            adjusted.loc[known] = adjusted.loc[known] * factor
            trimmed = adjusted.sort_values()
            if len(trimmed) >= 8:
                trimmed = trimmed.iloc[1:-1]
            return float(trimmed.median())
        cur = adjusted_median(endpoint["current"])
        p24 = adjusted_median(endpoint["prior24"])
        p60 = adjusted_median(endpoint["prior60"])
        support24 = len(endpoint["current"]) >= min_comparables and len(endpoint["prior24"]) >= min_comparables
        support60 = len(endpoint["current"]) >= min_comparables and len(endpoint["prior60"]) >= min_comparables
        r24 = (cur / p24 - 1) * 100 if support24 and p24 else None
        r60 = (cur / p60 - 1) * 100 if support60 and p60 else None
        _, q1, q3 = _median_iqr(endpoint["current"]["_price"])
        cohorts.append({
            "vehicle_variant_id": cohort, "valuation_date": as_of,
            "current_value_usd": cur, "current_comparables": len(endpoint["current"]),
            "prior24_value_usd": p24, "prior24_comparables": len(endpoint["prior24"]),
            "prior60_value_usd": p60, "prior60_comparables": len(endpoint["prior60"]),
            "return_24m_pct": r24, "return_60m_pct": r60,
            "supported_24m": bool(support24), "supported_60m": bool(support60),
            "confidence": "supported" if len(endpoint["current"]) >= min_comparables else "insufficient_evidence",
            "current_iqr_low_usd": q1, "current_iqr_high_usd": q3,
            "adjustment_model_version": "s26_bounded_mileage_trimmed_median_v1",
            "supporting_transaction_ids": ",".join(endpoint["current"].get("transaction_id", pd.Series(dtype=str)).astype(str).head(50)),
            "supporting_source_urls": ",".join(endpoint["current"].get("source_url", pd.Series(dtype=str)).astype(str).dropna().head(50)),
        })
    valuation = pd.DataFrame(cohorts)
    if valuation.empty:
        valuation = pd.DataFrame(columns=["vehicle_variant_id","supported_24m","supported_60m"])
    supported_current = int((valuation.get("current_comparables", pd.Series(dtype=int)) >= min_comparables).sum())
    supported24 = valuation[valuation.get("supported_24m", pd.Series(dtype=bool)) == True]
    supported60 = valuation[valuation.get("supported_60m", pd.Series(dtype=bool)) == True]
    forecasts = []
    for row in valuation.to_dict("records"):
        if row.get("current_value_usd") is None or not row.get("supported_60m"):
            continue
        annual = (1 + row["return_60m_pct"]/100) ** (1/5) - 1 if row.get("return_60m_pct") is not None and row["return_60m_pct"] > -100 else 0
        base = annual * 100
        forecasts.append({
            "vehicle_variant_id": row["vehicle_variant_id"], "forecast_model_version": "s26_judgment_scenario_v1",
            "method_status": "judgment_based_not_backtest_validated",
            "bear_5y_appreciation_pct": round((base-10)*5, 2),
            "base_5y_appreciation_pct": round(base*5, 2),
            "bull_5y_appreciation_pct": round((base+10)*5, 2),
            "probability_at_least_30pct": None,
            "downside_risk_pct": round(max(0, 10-base), 2),
            "max_recommended_purchase_price_usd": round(row["current_value_usd"] * .85, 2),
            "assumptions": "60-month annualized historical endpoint; +/-10 percentage-point scenario spread; transaction and holding costs not estimated without listing evidence.",
        })
    forecasts_df = pd.DataFrame(forecasts)
    eligible_model = valuation[
        valuation.get("supported_24m", pd.Series(dtype=bool)).eq(True)
        & valuation.get("return_24m_pct", pd.Series(dtype=float)).le(5)
        & valuation.get("supported_60m", pd.Series(dtype=bool)).eq(True)
        & valuation.get("return_60m_pct", pd.Series(dtype=float)).lt(0)
    ] if not valuation.empty else valuation
    model_opportunities = eligible_model.copy()
    if not model_opportunities.empty:
        model_opportunities["qualification_status"] = "blocked_no_verified_individual_purchase_population"
    return {
        "funnel": funnel,
        "row_audit": df[["transaction_id","eligibility_reason","analysis_class"]].to_dict("records"),
        "valuation": valuation.to_dict("records"),
        "forecasts": forecasts_df.to_dict("records"),
        "model_opportunities": model_opportunities.to_dict("records"),
        "individual_opportunities": [],
        "summary": {
            "input_row_count": total,
            "canonical_assignment_rows": int(df["_canonical"].sum()),
            "provisional_or_noncanonical_rows": int((~df["_canonical"]).sum()),
            "comparable_eligible_rows": int(df["_eligible"].sum()),
            "supported_current_valuations": supported_current,
            "supported_24m_returns": int(len(supported24)),
            "supported_60m_returns": int(len(supported60)),
            "qualified_model_opportunities": 0,
            "individual_purchase_opportunities": 0,
            "backtesting_status": "not_validated_no_leakage_safe_oos_pairs",
            "analytical_acceptance": False,
        },
    }
