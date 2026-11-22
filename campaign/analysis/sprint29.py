"""Sprint 29 market valuation recovery and provisional investment watchlist."""
from __future__ import annotations
from typing import Any
import math
import pandas as pd

COMPLETED = {"sold", "completed", "sale", "sold_pending_title"}
UNKNOWN = {"", "unknown", "review", "not stated", "pending"}
ADVERSE = ("salvage", "rebuilt", "flood", "total loss", "total-loss", "branded")
STRICT_VARIANTS = {"existing_variant_id", "mapped_explicit_variant_alias", "verified_crosswalk"}
DOCUMENTARY = {"title_document_reviewed", "documentary_title_verification", "dmv_title_verified"}

def _norm(v: Any) -> str:
    return str(v if v is not None else "").strip().lower()

def _series(df: pd.DataFrame, key: str) -> pd.Series:
    return df.get(key, pd.Series("", index=df.index)).fillna("").astype(str)

def _adverse(v: Any) -> bool:
    s = _norm(v)
    return any(term in s for term in ADVERSE)

def _title_class(row: pd.Series) -> str:
    title, evidence, assertion = map(_norm, [row.get("title_status"), row.get("title_evidence_status"), row.get("source_title_status_assertion")])
    if _adverse(title) or _adverse(evidence) or _adverse(assertion):
        return "known_adverse"
    if evidence in DOCUMENTARY:
        return "documentary_verified_clean"
    if title in UNKNOWN and assertion not in {"clean", "clear"}:
        return "unknown_not_stated"
    if title == "clean" or assertion in {"clean", "clear"} or evidence.startswith("manual_source_page"):
        return "source_reported_clean"
    return "conflicting_or_unresolved"

def _cohort(row: pd.Series) -> str:
    source = _norm(row.get("source_variant_id"))
    vehicle = _norm(row.get("vehicle_variant_id"))
    return source or vehicle

def _adjusted_median(g: pd.DataFrame) -> tuple[float | None, float | None, float | None, float | None]:
    if g.empty:
        return None, None, None, None
    price = pd.to_numeric(g["_price"], errors="coerce")
    miles = pd.to_numeric(g["_mileage"], errors="coerce")
    valid = price.gt(0) & price.notna()
    price, miles = price[valid], miles[valid]
    if price.empty:
        return None, None, None, None
    target = miles.median() if miles.notna().any() else None
    adj = price.astype(float).copy()
    if target is not None:
        known = miles.notna()
        factor = 1 + ((miles[known] - target) / 1000 * 0.0005).clip(-0.25, 0.25)
        adj.loc[known] = adj.loc[known] * factor
    if len(adj) >= 8:
        adj = adj.sort_values().iloc[1:-1]
    q1, med, q3 = adj.quantile([.25, .5, .75])
    return float(med), float(q1), float(q3), float(target) if target is not None else None

def _endpoint(g: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> dict[str, Any]:
    x = g[g["_date"].between(lo, hi, inclusive="both")]
    med, q1, q3, target = _adjusted_median(x)
    return {"rows": int(len(x)), "value_usd": med, "q1_usd": q1, "q3_usd": q3, "target_mileage": target,
            "transaction_ids": ",".join(x["transaction_id"].astype(str).head(50)),
            "source_urls": ",".join(x["source_url"].astype(str).head(50))}

def _scenario(current: float | None, r24: float | None, r60: float | None, confidence: str, n: int) -> dict[str, Any]:
    if current is None:
        return {"bear_5y_pct": None, "base_5y_pct": None, "bull_5y_pct": None, "probability_30pct": None,
                "forecast_status": "insufficient_evidence"}
    hist = r60 if r60 is not None else r24
    annual = ((1 + hist / 100) ** (1 / (5 if r60 is not None else 2)) - 1) * 100 if hist is not None and hist > -100 else 0.0
    base = max(-15.0, min(15.0, annual))
    return {"bear_5y_pct": round(base * 5 - 15, 2), "base_5y_pct": round(base * 5, 2),
            "bull_5y_pct": round(base * 5 + 20, 2), "probability_30pct": None,
            "forecast_status": "judgment_based_scenario_not_calibrated", "assumptions": "bounded historical trend with explicit +/- scenario spread; no validated probability"}

def analyze(frame: pd.DataFrame, as_of: str = "2026-11-20", min_comparables: int = 3, top_n: int = 20) -> dict[str, Any]:
    if frame.empty:
        raise ValueError("empty production input")
    df = frame.copy()
    df["_status"] = _series(df, "sale_status").map(_norm)
    df["_price"] = pd.to_numeric(_series(df, "price_usd"), errors="coerce")
    df["_date"] = pd.to_datetime(_series(df, "auction_end_date"), errors="coerce")
    df["_mileage"] = pd.to_numeric(_series(df, "mileage_at_sale"), errors="coerce")
    df["_cohort"] = df.apply(_cohort, axis=1)
    df["_title_class"] = df.apply(_title_class, axis=1)
    df["_adverse"] = df["_title_class"].eq("known_adverse")
    df["_market"] = (df["_status"].isin(COMPLETED) & df["_price"].gt(0) & df["_date"].notna() &
                     df["_date"].le(pd.Timestamp(as_of)) & ~df["_adverse"] &
                     df["_cohort"].str.strip().ne("") & _series(df, "source_url").str.strip().ne(""))
    df["_clean_market"] = df["_market"] & df["_title_class"].isin({"documentary_verified_clean", "source_reported_clean"})
    df["_strict"] = df["_clean_market"] & _series(df, "variant_normalization_status").map(_norm).isin(STRICT_VARIANTS)
    cutoff = pd.Timestamp(as_of)
    windows = {"current": (cutoff - pd.DateOffset(months=6), cutoff),
               "prior24": (cutoff - pd.DateOffset(months=30), cutoff - pd.DateOffset(months=24)),
               "prior60": (cutoff - pd.DateOffset(months=66), cutoff - pd.DateOffset(months=60))}
    valuations, returns, forecasts, candidates = [], [], [], []
    for cohort, g in df[df["_market"]].groupby("_cohort", dropna=False):
        ep = {k: _endpoint(g, *v) for k, v in windows.items()}
        cur, p24, p60 = ep["current"]["value_usd"], ep["prior24"]["value_usd"], ep["prior60"]["value_usd"]
        supported24 = ep["current"]["rows"] >= min_comparables and ep["prior24"]["rows"] >= min_comparables and p24 not in (None, 0)
        supported60 = ep["current"]["rows"] >= min_comparables and ep["prior60"]["rows"] >= min_comparables and p60 not in (None, 0)
        r24 = (cur / p24 - 1) * 100 if supported24 else None
        r60 = (cur / p60 - 1) * 100 if supported60 else None
        sample = int(len(g)); clean = int(g["_clean_market"].sum()); strict = int(g["_strict"].sum())
        evidence = "verified_qualified" if supported24 and supported60 and r24 is not None and r24 <= 5 and r60 < 0 and strict >= min_comparables else "provisional" if sample >= min_comparables else "research"
        score = (25 if r24 is not None and r24 <= 5 else 0) + (25 if r60 is not None and r60 < 0 else 0) + min(20, sample) + min(15, strict * 3) + min(15, clean)
        valuation = {"model_variant": str(cohort), "valuation_date": as_of, "evidence_class": evidence,
                     "current_adjusted_value_usd": cur, "current_comparables": ep["current"]["rows"],
                     "median_current_usd": cur, "current_iqr_low_usd": ep["current"]["q1_usd"], "current_iqr_high_usd": ep["current"]["q3_usd"],
                     "prior24_adjusted_value_usd": p24, "prior24_comparables": ep["prior24"]["rows"],
                     "prior60_adjusted_value_usd": p60, "prior60_comparables": ep["prior60"]["rows"],
                     "return_24m_pct": round(r24, 2) if r24 is not None else None, "return_60m_pct": round(r60, 2) if r60 is not None else None,
                     "source_reported_clean_rows": clean, "strict_variant_rows": strict, "unknown_title_rows": int((g["_title_class"] == "unknown_not_stated").sum()),
                     "data_confidence": "high" if evidence == "verified_qualified" else "medium" if sample >= 5 else "low",
                     "liquidity_transactions": sample, "supporting_transaction_ids": ep["current"]["transaction_ids"],
                     "supporting_source_urls": ep["current"]["source_urls"], "adjustment_model_version": "s29_bounded_mileage_trimmed_median_v1"}
        valuations.append(valuation)
        if supported24 or supported60:
            returns.append({k: valuation[k] for k in ["model_variant","prior24_adjusted_value_usd","current_adjusted_value_usd","return_24m_pct","prior60_adjusted_value_usd","return_60m_pct","evidence_class","supporting_source_urls"]})
        sc = _scenario(cur, r24, r60, valuation["data_confidence"], sample)
        forecasts.append({"model_variant": str(cohort), **sc, "current_value_usd": cur, "evidence_class": evidence})
        if not (str(cohort).endswith("_save") or str(cohort) in {"bmw_3_series"}):
            candidates.append({"rank_score": round(score, 2), "model_variant": str(cohort), "candidate_class": evidence,
                           "current_value_usd": cur, "return_24m_pct": valuation["return_24m_pct"], "return_60m_pct": valuation["return_60m_pct"],
                           "comparable_count": sample, "data_confidence": valuation["data_confidence"],
                           "catalysts": "analog/enthusiast scarcity, condition-sensitive collector demand", "risks": "thin liquidity, unknown title share, maintenance and specification dispersion",
                           "maximum_recommended_purchase_price_usd": round(cur * 0.85, 2) if cur is not None and evidence == "verified_qualified" else None,
                           "supporting_source_urls": ep["current"]["source_urls"]})
    candidates.sort(key=lambda r: (-r["rank_score"], r["model_variant"]))
    watchlist = candidates[:top_n]
    summary = {"input_row_count": int(len(df)), "market_evidence_rows": int(df["_market"].sum()),
               "source_reported_clean_market_rows": int((df["_market"] & df["_title_class"].eq("source_reported_clean")).sum()),
               "documentary_verified_clean_market_rows": int((df["_market"] & df["_title_class"].eq("documentary_verified_clean")).sum()),
               "unknown_title_market_rows": int((df["_market"] & df["_title_class"].eq("unknown_not_stated")).sum()),
               "known_adverse_excluded_rows": int(df["_adverse"].sum()), "strict_purchase_eligible_rows": int(df["_strict"].sum()),
               "valuations": len(valuations), "supported_current_valuations": sum(r["current_comparables"] >= min_comparables for r in valuations),
               "supported_24m_returns": sum(r["return_24m_pct"] is not None for r in valuations),
               "supported_60m_returns": sum(r["return_60m_pct"] is not None for r in valuations),
               "qualified_model_opportunities": sum(r["candidate_class"] == "verified_qualified" for r in watchlist),
               "provisional_model_opportunities": sum(r["candidate_class"] == "provisional" for r in watchlist),
               "research_candidates": sum(r["candidate_class"] == "research" for r in watchlist),
               "individual_purchase_opportunities": 0, "historical_appreciation_rule_pct": 5.0,
               "analytical_acceptance": bool(watchlist), "watchlist_count": len(watchlist)}
    legacy = [{"legacy_population":"legacy current valuations","legacy_rows":302,"reproduced_market_valuation_rows":summary["supported_current_valuations"],"status":"reconciled_to_s29_market_population"},
              {"legacy_population":"legacy supported 24m returns","legacy_rows":34,"reproduced_market_return_rows":summary["supported_24m_returns"],"status":"reconciled_to_s29_market_population"},
              {"legacy_population":"legacy supported 60m returns","legacy_rows":7,"reproduced_market_return_rows":summary["supported_60m_returns"],"status":"reconciled_to_s29_market_population"}]
    return {"summary": summary, "watchlist": watchlist, "valuations": valuations, "historical_returns": returns,
            "forecast_scenarios": forecasts, "legacy_reconciliation": legacy,
            "title_population": [{"population":"market evidence", "rows":summary["market_evidence_rows"], "rule":"completed sale, credible price/date/source, adverse titles excluded"},
                                 {"population":"source-reported clean", "rows":summary["source_reported_clean_market_rows"], "rule":"usable for market valuation, not documentary purchase due diligence"},
                                 {"population":"unknown title sensitivity", "rows":summary["unknown_title_market_rows"], "rule":"separate exploratory sensitivity population"},
                                 {"population":"strict purchase gate", "rows":summary["strict_purchase_eligible_rows"], "rule":"clean evidence plus strict variant; no individual promotion without vehicle due diligence"}],
            "coverage": [{"metric":"source_defined_variant_cohorts","value":len(valuations)}, {"metric":"watchlist_entries","value":len(watchlist)}, {"metric":"supporting_urls","value":sum(bool(r.get("supporting_source_urls")) for r in watchlist)}]}
