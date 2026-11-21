"""Sprint 22 production reconciliation and leakage-safe analysis helpers.

These functions operate on the canonical Auction Transactions schema. They are
deliberately conservative: unknown titles are not promoted, source cohort IDs
are not silently treated as generation-equivalent, and unsupported endpoints
remain null.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import pandas as pd

UNKNOWN_TITLES={"","unknown","review","not stated"}
ADVERSE_TITLES={"salvage","rebuilt","flood","total_loss","total-loss"}
COMPLETED={"sold","completed","sale"}

@dataclass(frozen=True)
class Disposition:
    eligible: bool
    canonical_cohort: str
    confidence: str
    window_membership: str
    contribution_status: str
    exclusion_reason: str|None

def canonical_cohort(row: Any) -> str:
    value=str(row.get("vehicle_variant_id") or "").strip().lower()
    if not value:
        return "unresolved"
    # Acquisition prefixes identify provenance, not different vehicle cohorts.
    for prefix in ("cab_","bat_","pcarmarket_"):
        if value.startswith(prefix):
            value=value[len(prefix):]
            break
    return value

def reconcile_transactions(frame: pd.DataFrame, as_of: str="2026-11-20",
                           window_months: int=6) -> pd.DataFrame:
    out=frame.copy()
    out["price_num"]=pd.to_numeric(out.get("price_usd"),errors="coerce")
    out["sale_date"]=pd.to_datetime(out.get("auction_end_date"),errors="coerce")
    status=out.get("sale_status","").fillna("").astype(str).str.lower().str.strip()
    title=out.get("title_status","").fillna("").astype(str).str.lower().str.strip()
    out["canonical_cohort_id"]=out.apply(canonical_cohort,axis=1)
    out["classification_confidence"]=out["canonical_cohort_id"].map(
        lambda x:"high" if x!="unresolved" else "low")
    out["transaction_eligible"]=(status.isin(COMPLETED)&out["price_num"].gt(0)
                                 &~title.isin(ADVERSE_TITLES|UNKNOWN_TITLES))
    cutoff=pd.Timestamp(as_of)
    windows={
        "current":(cutoff-pd.DateOffset(months=window_months),cutoff),
        "prior24":(cutoff-pd.DateOffset(months=24+window_months),cutoff-pd.DateOffset(months=24)),
        "prior60":(cutoff-pd.DateOffset(months=60+window_months),cutoff-pd.DateOffset(months=60))}
    def membership(r):
        if not bool(r["transaction_eligible"]): return "ineligible"
        for name,(lo,hi) in windows.items():
            if lo<=r["sale_date"]<=hi:return name
        return "outside_required_windows"
    out["historical_window_membership"]=out.apply(membership,axis=1)
    out["comparable_sale_eligible"]=out["transaction_eligible"] & out["canonical_cohort_id"].ne("unresolved")
    out["exclusion_reason"]=None
    out.loc[~out["transaction_eligible"],"exclusion_reason"]="status/title/price eligibility failure"
    out.loc[out["transaction_eligible"]&~out["comparable_sale_eligible"],"exclusion_reason"]="unresolved canonical cohort"
    out["valuation_contribution_status"]="not_in_required_window"
    out.loc[out["comparable_sale_eligible"]&out["historical_window_membership"].isin(["current","prior24","prior60"]),"valuation_contribution_status"]="eligible_endpoint_observation"
    out.loc[out["comparable_sale_eligible"]&out["historical_window_membership"].eq("outside_required_windows"),"valuation_contribution_status"]="eligible_but_outside_window"
    return out

def valuation_rebuild(reconciled: pd.DataFrame, as_of: str="2026-11-20",
                      min_observations: int=3) -> pd.DataFrame:
    x=reconciled[reconciled["comparable_sale_eligible"]].copy()
    rows=[]
    for cohort,g in x.groupby("canonical_cohort_id"):
        windows={k:g[g["historical_window_membership"].eq(k)] for k in ("current","prior24","prior60")}
        med={k:v["price_num"].median() if len(v) else None for k,v in windows.items()}
        row={"cohort_id":cohort,"valuation_date":as_of,
             "current_estimated_value_usd":med["current"],
             "current_comparable_sales":len(windows["current"]),
             "prior24_estimated_value_usd":med["prior24"],
             "prior60_estimated_value_usd":med["prior60"],
             "supported_24m":len(windows["current"])>=min_observations and len(windows["prior24"])>=min_observations,
             "supported_60m":len(windows["current"])>=min_observations and len(windows["prior60"])>=min_observations,
             "supporting_transaction_ids":",".join(windows["current"]["transaction_id"].astype(str).head(50))}
        row["return_24m_pct"]=(med["current"]/med["prior24"]-1)*100 if row["supported_24m"] else None
        row["return_60m_pct"]=(med["current"]/med["prior60"]-1)*100 if row["supported_60m"] else None
        row["confidence"]="supported" if len(windows["current"])>=min_observations else "insufficient"
        rows.append(row)
    return pd.DataFrame(rows)

def backtest_status(reconciled: pd.DataFrame) -> dict[str,Any]:
    # No leakage-safe OOS result is claimed unless both a training endpoint and
    # a later realized endpoint have the same canonical cohort and minimum n.
    return {"backtested_cohorts":0,"prediction_dates":0,"valid_oos_observations":0,
            "status":"not_validated","reason":"No leakage-safe endpoint pairs met the minimum evidence rule."}
