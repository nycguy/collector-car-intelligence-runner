"""Sprint 28 evidence recovery and historical endpoint diagnostics.

This module deliberately separates source-reported assertions from documentary
verification and source labels from canonical variant assignments.  It may
increase research coverage, but it must not manufacture strict comparables.
"""
from __future__ import annotations

from typing import Any
import re
import pandas as pd

UNKNOWN = {"", "unknown", "review", "not stated", "pending"}
ADVERSE = ("salvage", "rebuilt", "flood", "total loss", "total-loss", "branded")
COMPLETED = {"sold", "completed", "sale", "sold_pending_title"}
STRICT = {"existing_variant_id", "mapped_explicit_variant_alias", "verified_crosswalk"}
DOCUMENTARY = {"title_document_reviewed", "documentary_title_verification", "dmv_title_verified"}


def _norm(v: Any) -> str:
    return str(v if v is not None else "").strip().lower()


def _series(df: pd.DataFrame, key: str) -> pd.Series:
    return df.get(key, pd.Series("", index=df.index)).fillna("").astype(str)


def _adverse(s: pd.Series) -> pd.Series:
    return s.map(lambda x: any(term in _norm(x) for term in ADVERSE))


def _title_class(row: pd.Series) -> str:
    title = _norm(row.get("title_status"))
    evidence = _norm(row.get("title_evidence_status"))
    assertion = _norm(row.get("source_title_status_assertion"))
    if any(term in title or term in evidence or term in assertion for term in ADVERSE):
        return "adverse"
    if evidence in DOCUMENTARY:
        return "verified_documentary_clean"
    if title in UNKNOWN or evidence in UNKNOWN:
        return "unknown"
    if title == "clean" and (evidence.startswith("manual_source_page") or assertion == "clean"):
        return "source_reported_clean"
    if title == "clean":
        return "clean_unclassified"
    return "conflicting_or_unresolved"


def _variant_class(row: pd.Series) -> str:
    status = _norm(row.get("variant_normalization_status"))
    source_variant = _norm(row.get("source_variant_id"))
    canonical = _norm(row.get("vehicle_variant_id"))
    if status in STRICT and canonical:
        return "strict_canonical"
    if status == "mapped_make_model_year" and canonical:
        return "legacy_make_model_year"
    if source_variant.startswith("provisional_"):
        # This is a deterministic source-label recovery only.  It is not a
        # canonical trim/generation assignment and cannot enter strict values.
        return "deterministic_source_label_review"
    if status in {"normalized_from_source", "provisional_unmapped"}:
        return "source_label_review"
    if status == "ambiguous_unresolved":
        return "ambiguous_unresolved"
    return "missing_or_unclassified"


def _endpoint_rows(df: pd.DataFrame, as_of: str = "2026-11-20") -> list[dict[str, Any]]:
    cutoff = pd.Timestamp(as_of)
    windows = {
        "current_6m": (cutoff - pd.DateOffset(months=6), cutoff),
        "prior24_6m": (cutoff - pd.DateOffset(months=30), cutoff - pd.DateOffset(months=24)),
        "prior60_6m": (cutoff - pd.DateOffset(months=66), cutoff - pd.DateOffset(months=60)),
    }
    rows: list[dict[str, Any]] = []
    if df.empty:
        return rows
    for cohort, group in df.groupby("_cohort", dropna=False):
        if not cohort:
            continue
        item: dict[str, Any] = {"cohort_id": str(cohort), "evidence_population": "market_evidence"}
        endpoint_groups = {}
        for name, (lo, hi) in windows.items():
            x = group[group["_date"].between(lo, hi, inclusive="both")]
            endpoint_groups[name] = x
            prices = pd.to_numeric(x["_price"], errors="coerce").dropna()
            item[f"{name}_rows"] = int(len(x))
            item[f"{name}_valid_prices"] = int(prices.gt(0).sum())
            item[f"{name}_median_usd"] = float(prices[prices.gt(0)].median()) if prices.gt(0).any() else None
            item[f"{name}_start"] = lo.date().isoformat()
            item[f"{name}_end"] = hi.date().isoformat()
        item["validated_24m_endpoint_pair"] = bool(item["current_6m_rows"] >= 5 and item["prior24_6m_rows"] >= 5)
        item["validated_60m_endpoint_pair"] = bool(item["current_6m_rows"] >= 5 and item["prior60_6m_rows"] >= 5)
        if item["validated_24m_endpoint_pair"]:
            item["return_24m_pct_exploratory"] = round((item["current_6m_median_usd"] / item["prior24_6m_median_usd"] - 1) * 100, 4) if item["prior24_6m_median_usd"] else None
        else:
            item["return_24m_pct_exploratory"] = None
        if item["validated_60m_endpoint_pair"]:
            item["return_60m_pct_exploratory"] = round((item["current_6m_median_usd"] / item["prior60_6m_median_usd"] - 1) * 100, 4) if item["prior60_6m_median_usd"] else None
        else:
            item["return_60m_pct_exploratory"] = None
        rows.append(item)
    return rows


def analyze(frame: pd.DataFrame, as_of: str = "2026-11-20", min_comparables: int = 5) -> dict[str, Any]:
    if frame.empty:
        raise ValueError("empty production input")
    df = frame.copy()
    df["_status"] = _series(df, "sale_status").map(_norm)
    df["_title_class"] = df.apply(_title_class, axis=1)
    df["_variant_class"] = df.apply(_variant_class, axis=1)
    df["_price"] = pd.to_numeric(_series(df, "price_usd"), errors="coerce")
    df["_date"] = pd.to_datetime(_series(df, "auction_end_date"), errors="coerce")
    df["_cohort"] = _series(df, "source_variant_id").where(_series(df, "source_variant_id").str.strip().ne(""), _series(df, "vehicle_variant_id"))
    df["_adverse"] = _adverse(_series(df, "title_status")) | _adverse(_series(df, "title_evidence_status"))
    df["_market"] = (
        df["_status"].isin(COMPLETED) & df["_price"].gt(0) & df["_date"].notna() &
        df["_date"].le(pd.Timestamp(as_of)) & ~df["_adverse"] & df["_cohort"].str.strip().ne("") &
        _series(df, "source_url").str.strip().ne("")
    )
    df["_strict"] = df["_market"] & df["_variant_class"].eq("strict_canonical") & df["_title_class"].eq("verified_documentary_clean")
    endpoint_rows = _endpoint_rows(df[df["_market"]], as_of)
    strict_endpoints = _endpoint_rows(df[df["_strict"]], as_of)
    source_label_rows = df[df["_market"] & df["_variant_class"].eq("deterministic_source_label_review")]
    title_counts = df.loc[df["_market"], "_title_class"].value_counts().sort_index().to_dict()
    variant_counts = df.loc[df["_market"], "_variant_class"].value_counts().sort_index().to_dict()
    cluster = (source_label_rows.groupby(["source_name", "source_variant_id"], dropna=False)
               .size().reset_index(name="rows").sort_values("rows", ascending=False).head(250).to_dict("records"))
    source_priority = (df[df["_market"]].groupby("source_name", dropna=False)
                       .agg(market_rows=("transaction_id", "size"), strict_rows=("_strict", "sum"),
                            source_label_review_rows=("_variant_class", lambda s: int((s == "deterministic_source_label_review").sum())))
                       .reset_index())
    source_priority["strict_conversion_gap"] = source_priority["market_rows"] - source_priority["strict_rows"]
    source_priority["priority_reason"] = "prioritize source-label review only after page evidence and canonical crosswalk are available"
    source_priority = source_priority.sort_values(["source_label_review_rows", "market_rows"], ascending=False).to_dict("records")
    legacy = [
        {"legacy_population": "Sprint 26 current valuations", "legacy_rows": 302, "reproducible_strict_rows": 0, "status": "quarantined_pending_transaction_lineage"},
        {"legacy_population": "Sprint 26 supported 24m returns", "legacy_rows": 34, "reproducible_strict_rows": 0, "status": "quarantined_pending_leakage_safe_endpoints"},
        {"legacy_population": "Sprint 26 supported 60m returns", "legacy_rows": 7, "reproducible_strict_rows": 0, "status": "quarantined_pending_leakage_safe_endpoints"},
        {"legacy_population": "Sprint 28 market endpoint pairs", "legacy_rows": sum(x["validated_24m_endpoint_pair"] for x in endpoint_rows), "reproducible_strict_rows": sum(x["validated_24m_endpoint_pair"] for x in strict_endpoints), "status": "diagnostic_not_official_return"},
        {"legacy_population": "Sprint 28 market 60m endpoint pairs", "legacy_rows": sum(x["validated_60m_endpoint_pair"] for x in endpoint_rows), "reproducible_strict_rows": sum(x["validated_60m_endpoint_pair"] for x in strict_endpoints), "status": "diagnostic_not_official_return"},
    ]
    summary = {
        "input_row_count": int(len(df)),
        "market_evidence_rows": int(df["_market"].sum()),
        "verified_documentary_clean_rows": int((df["_market"] & df["_title_class"].eq("verified_documentary_clean")).sum()),
        "source_reported_clean_rows": int((df["_market"] & df["_title_class"].eq("source_reported_clean")).sum()),
        "unknown_title_rows": int((df["_market"] & df["_title_class"].eq("unknown")).sum()),
        "adverse_title_rows_excluded": int((~df["_market"] & df["_adverse"]).sum()),
        "strict_validated_rows": int(df["_strict"].sum()),
        "deterministic_source_label_review_rows": int(len(source_label_rows)),
        "new_strict_variant_assignments": 0,
        "new_verified_title_evidence": 0,
        "market_24m_endpoint_pairs": sum(x["validated_24m_endpoint_pair"] for x in endpoint_rows),
        "market_60m_endpoint_pairs": sum(x["validated_60m_endpoint_pair"] for x in endpoint_rows),
        "strict_24m_endpoint_pairs": sum(x["validated_24m_endpoint_pair"] for x in strict_endpoints),
        "strict_60m_endpoint_pairs": sum(x["validated_60m_endpoint_pair"] for x in strict_endpoints),
        "supported_current_valuations": 0,
        "supported_24m_returns": 0,
        "supported_60m_returns": 0,
        "qualified_model_opportunities": 0,
        "individual_purchase_opportunities": 0,
        "analytical_acceptance": False,
        "official_return_status": "blocked_no_documentary_clean_strict_endpoint_pairs",
        "investment_rule_24m_max_pct": 5.0,
    }
    return {"summary": summary, "title_counts": [{"title_evidence_class": k, "rows": int(v)} for k, v in title_counts.items()],
            "variant_counts": [{"variant_recovery_class": k, "rows": int(v)} for k, v in variant_counts.items()],
            "source_label_clusters": cluster, "source_priority": source_priority,
            "endpoint_diagnostics": endpoint_rows, "strict_endpoint_diagnostics": strict_endpoints,
            "legacy_reconciliation": legacy,
            "row_audit": df[["transaction_id", "source_url", "_title_class", "_variant_class", "_market", "_strict"]].rename(columns={"_title_class":"title_evidence_class", "_variant_class":"variant_recovery_class", "_market":"market_evidence", "_strict":"strict_validated"}).to_dict("records")}
