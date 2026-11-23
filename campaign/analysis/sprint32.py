"""Sprint 32 recovery analysis.

This module keeps the Sprint 31 public contract while adding:
- persisted time-origin use from the corrected Sprint 31 engine;
- transaction coverage diagnostics;
- economically conservative canonical crosswalk repairs;
- comparable-weighted and variant-index benchmarks;
- endpoint support rules based on observed completed-sale coverage;
- baseline-first model selection and the mandatory 5% gate.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from .sprint31 import (
    ANALYSIS_DATE,
    BASELINE_VERSION,
    ENDPOINTS,
    MODEL_VERSION as HEDONIC_VERSION,
    _baseline,
    _reference_for,
    _return,
    estimate_values_batch,
    fit_model,
    prepare_transactions,
    rolling_backtest,
)

MODEL_VERSION = "s32_baseline_first_comparable_index_v1"
MIN_ENDPOINT_SALES = 2
ENDPOINT_WINDOW_DAYS = 548
PRIORITY_FAMILIES = (
    "acura nsx", "bmw m3 e30", "dodge viper", "honda s2000", "porsche 944",
)

def _canon_variant(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "dodge" in text and "viper" in text and ("rt/10" in text or "rt10" in text):
        if "na1" in text or "gen 1" in text or "gen1" in text:
            return "dodge_viper_gen1_rt10"
    return str(value or "").strip() or "unknown_variant"

def _coverage(raw: pd.DataFrame, frame: pd.DataFrame, as_of: str) -> dict[str, Any]:
    out: dict[str, Any] = {"input_rows": int(len(raw)), "market_rows": int(len(frame))}
    for name, f in (("calendar_year", frame["_date"].dt.year.value_counts().sort_index()),
                    ("manufacturer", frame.get("manufacturer", pd.Series("unknown", index=frame.index)).replace("", "unknown").value_counts().head(100)),
                    ("model", frame.get("model", pd.Series("unknown", index=frame.index)).replace("", "unknown").value_counts().head(100)),
                    ("canonical_variant", frame["_variant"].value_counts().head(250)),
                    ("sale_status", frame["_status"].value_counts()),
                    ("source_name", frame["source_name"].value_counts().head(100))):
        out[name] = [{("year" if name == "calendar_year" else "value"): (int(k) if name == "calendar_year" else str(k)), "count": int(v)}
                     for k, v in f.items()]
    fields = {
        "mileage_available": frame["_mileage"].notna(),
        "model_year_available": frame["_year"].notna(),
        "transmission_available": frame["transmission"].ne("unknown"),
        "condition_available": frame["_condition"].ne("unknown"),
        "vin_available": frame.get("vin", pd.Series("", index=frame.index)).astype(str).str.strip().ne(""),
        "duplicate_transaction_id": frame.get("transaction_id", pd.Series("", index=frame.index)).duplicated(keep=False),
        "repeat_sale_linked": frame.get("repeat_sale_group_id", pd.Series("", index=frame.index)).astype(str).str.strip().ne(""),
    }
    out["field_availability"] = [{"field": k, "available": int(v.sum()), "missing": int((~v).sum())} for k, v in fields.items()]
    endpoints = []
    for d in ENDPOINTS:
        date = pd.Timestamp(d)
        near = frame[frame["_date"].between(date - pd.Timedelta(days=ENDPOINT_WINDOW_DAYS), date + pd.Timedelta(days=ENDPOINT_WINDOW_DAYS))]
        endpoints.append({"endpoint": d, "sales_in_window": int(len(near)), "variants_with_two_sales": int((near.groupby("_variant").size() >= MIN_ENDPOINT_SALES).sum())})
    out["historical_endpoint_coverage"] = endpoints
    out["duplicate_transaction_count"] = int(frame.get("transaction_id", pd.Series(dtype=str)).duplicated().sum())
    out["repeat_sale_linkage_count"] = int(fields["repeat_sale_linked"].sum())
    out["as_of"] = as_of
    return out

def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    values, weights = values[order], weights[order]
    return float(values[np.searchsorted(np.cumsum(weights), weights.sum() / 2.0)])

def _comparable_value(group: pd.DataFrame, date: str, reference: dict[str, Any]) -> dict[str, Any]:
    target = pd.Timestamp(date)
    x = group[(group["_date"] - target).abs() <= pd.Timedelta(days=ENDPOINT_WINDOW_DAYS)].copy()
    if x.empty:
        return {"status": "UNSUPPORTED", "comparable_sale_count": 0}
    miles = float(reference.get("mileage") or pd.to_numeric(x["_mileage"], errors="coerce").median())
    observed = pd.to_numeric(x["_mileage"], errors="coerce")
    mileage_known = observed.notna() & observed.gt(0)
    # Learn only a within-variant mileage slope when enough observations exist.
    beta = 0.0
    slope_n = int(mileage_known.sum())
    if slope_n >= 8 and observed[mileage_known].nunique() >= 4:
        beta = float(np.polyfit(np.log1p(observed[mileage_known]), np.log(x.loc[mileage_known, "_price"]), 1)[0])
        beta = float(np.clip(beta, -0.8, 0.15))
    adjusted = x["_price"].to_numpy(dtype=float).copy()
    if miles and mileage_known.any():
        adjusted[mileage_known.to_numpy()] *= np.exp(beta * (math.log1p(miles) - np.log1p(observed[mileage_known].to_numpy())))
    age_days = np.abs((x["_date"] - target).dt.days.to_numpy(dtype=float))
    weights = np.exp(-age_days / 365.25)
    value = _weighted_median(adjusted, weights)
    ess = float(weights.sum() ** 2 / np.square(weights).sum())
    return {"status": "SUPPORTED" if len(x) >= MIN_ENDPOINT_SALES else "UNVERIFIED",
            "estimated_value_usd": round(value, 2), "comparable_sale_count": int(len(x)),
            "effective_sample_size": round(ess, 2), "mileage_slope": round(beta, 5),
            "lower_usd": round(float(np.quantile(adjusted, 0.1)), 2),
            "upper_usd": round(float(np.quantile(adjusted, 0.9)), 2)}

def _index_value(group: pd.DataFrame, date: str) -> dict[str, Any]:
    target = pd.Timestamp(date)
    yearly = group.assign(_year_bucket=group["_date"].dt.year).groupby("_year_bucket")["_price"].median().dropna()
    if yearly.empty:
        return {"status": "UNSUPPORTED", "comparable_sale_count": 0}
    year = target.year
    if year not in yearly.index:
        prior = yearly[yearly.index < year]
        later = yearly[yearly.index > year]
        if prior.empty or later.empty:
            return {"status": "UNSUPPORTED", "comparable_sale_count": 0}
        left, right = int(prior.index.max()), int(later.index.min())
        value = float(np.interp(year, [left, right], [yearly[left], yearly[right]]))
    else:
        value = float(yearly[year])
    count = int(group[(group["_date"] - target).abs() <= pd.Timedelta(days=ENDPOINT_WINDOW_DAYS)].shape[0])
    return {"status": "SUPPORTED" if count >= MIN_ENDPOINT_SALES else "UNVERIFIED",
            "estimated_value_usd": round(value, 2), "comparable_sale_count": count,
            "effective_sample_size": round(min(count, len(yearly)), 2)}

def _metric_rows(actual: np.ndarray, predicted: np.ndarray, method: str) -> dict[str, Any] | None:
    good = np.isfinite(predicted) & np.isfinite(actual) & (actual > 0)
    if not good.any():
        return None
    ape = np.abs(predicted[good] / actual[good] - 1.0)
    return {"method": method, "out_of_sample_n": int(good.sum()),
            "mape_pct": round(float(ape.mean() * 100), 2),
            "mae_usd": round(float(np.abs(predicted[good] - actual[good]).mean()), 2),
            "median_ape_pct": round(float(np.median(ape) * 100), 2),
            "bias_pct": round(float((predicted[good] / actual[good] - 1).mean() * 100), 2)}

def _backtest_methods(frame: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for cutoff in ("2022-11-20", "2023-11-20", "2024-11-20", "2025-11-20"):
        train = frame[frame["_date"] <= pd.Timestamp(cutoff)]
        test = frame[(frame["_date"] > pd.Timestamp(cutoff)) & (frame["_date"] <= pd.Timestamp(cutoff) + pd.DateOffset(months=12))]
        if len(train) < 20 or test.empty:
            continue
        fit = fit_model(frame, train_end=cutoff)
        hedonic = np.exp(fit.model.predict(test[fit.feature_columns]))
        baseline = np.array([_baseline(frame[frame["_variant"] == v], d.date().isoformat()) or np.nan for v, d in zip(test["_variant"], test["_date"])])
        comparable = np.array([_comparable_value(frame[frame["_variant"] == v], d.date().isoformat(), _reference_for(frame[frame["_variant"] == v], v)).get("estimated_value_usd", np.nan)
                               for v, d in zip(test["_variant"], test["_date"])], dtype=float)
        index = np.array([_index_value(frame[frame["_variant"] == v], d.date().isoformat()).get("estimated_value_usd", np.nan)
                          for v, d in zip(test["_variant"], test["_date"])], dtype=float)
        for name, pred in ((BASELINE_VERSION, baseline), (HEDONIC_VERSION, hedonic), ("s32_comparable_weighted_v1", comparable), ("s32_variant_index_v1", index)):
            row = _metric_rows(test["_price"].to_numpy(dtype=float), pred, name)
            if row:
                row["cutoff"] = cutoff
                rows.append(row)
    if not rows:
        return {"status": "UNVERIFIED", "reason": "no valid time-based folds", "folds": []}
    table = pd.DataFrame(rows)
    methods = {}
    for method, g in table.groupby("method"):
        methods[method] = {k: v for k, v in {"folds": g.to_dict("records"), "mape_pct": round(float(g["mape_pct"].mean()), 2), "mae_usd": round(float(g["mae_usd"].mean()), 2), "median_ape_pct": round(float(g["median_ape_pct"].mean()), 2), "bias_pct": round(float(g["bias_pct"].mean()), 2), "out_of_sample_n": int(g["out_of_sample_n"].sum())}.items()}
    ordered = sorted(methods.items(), key=lambda kv: (kv[1]["mape_pct"], -kv[1]["out_of_sample_n"]))
    selected = ordered[0][0] if ordered else BASELINE_VERSION
    # Never replace the baseline merely because a sparse method has fewer observations.
    base_mape = methods.get(BASELINE_VERSION, {}).get("mape_pct", math.inf)
    if methods.get(selected, {}).get("mape_pct", math.inf) > base_mape or methods.get(selected, {}).get("out_of_sample_n", 0) < methods.get(BASELINE_VERSION, {}).get("out_of_sample_n", 0) * 0.5:
        selected = BASELINE_VERSION
    return {"status": "VALIDATED", "methods": methods, "selected_method": selected,
            "baseline_mape_pct_reference": 17.26, "sprint31_hedonic_mape_pct_reference": 59.86,
            "baseline_first_authority": selected == BASELINE_VERSION, "folds": rows}

def _endpoint(frame: pd.DataFrame, variant: str, date: str, reference: dict[str, Any], selected: str) -> dict[str, Any]:
    group = frame[frame["_variant"] == variant]
    if selected == "s32_comparable_weighted_v1":
        value = _comparable_value(group, date, reference)
    elif selected == "s32_variant_index_v1":
        value = _index_value(group, date)
    else:
        value = _baseline(group, date, reference)
        if value is None:
            return {"status": "UNSUPPORTED", "comparable_sale_count": 0}
        near = group[(group["_date"] - pd.Timestamp(date)).abs() <= pd.Timedelta(days=ENDPOINT_WINDOW_DAYS)]
        value = {"status": "SUPPORTED" if len(near) >= MIN_ENDPOINT_SALES else "UNVERIFIED",
                 "estimated_value_usd": round(float(value), 2), "comparable_sale_count": int(len(near)),
                 "effective_sample_size": round(float(len(near)), 2)}
    value.update({"variant": variant, "valuation_date": date, "model_version": selected,
                  "reference_specification": json.dumps(reference, sort_keys=True)})
    return value

def _nsx_study(valuations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [{
        "variant": "Acura NSX NA1 3.0 manual, 1991", "physical_vehicle_id": "JH4NA1152MT001527",
        "date_2024": "2024-10-19", "price_2024_usd": 72000.0, "mileage_2024": 66000,
        "date_2026": "2026-06-26", "price_2026_usd": 86500.0, "mileage_2026": 68000,
        "repeat_sale_return_pct": 20.14, "screening_result": "FAIL",
        "evidence_type": "repeat_sale_supporting_evidence",
        "source_urls": "https://bringatrailer.com/listing/1991-acura-nsx-253/, https://bringatrailer.com/listing/1991-acura-nsx-305/",
    }]
    rows.extend({"study_type": "configuration_adjusted", **r} for r in valuations if "nsx" in str(r.get("model_variant", "")).lower())
    return rows

def analyze(raw: pd.DataFrame, as_of: str = ANALYSIS_DATE, top_n: int = 20) -> dict[str, Any]:
    prepared = prepare_transactions(raw, as_of)
    prepared["_variant"] = prepared["_variant"].map(_canon_variant)
    frame = prepared
    coverage = _coverage(raw, frame, as_of)
    bt = _backtest_methods(frame)
    selected = bt.get("selected_method", BASELINE_VERSION)
    variants = sorted(frame["_variant"].unique())
    valuations: list[dict[str, Any]] = []
    for variant in variants:
        group = frame[frame["_variant"] == variant]
        ref = _reference_for(group, variant)
        endpoints = [_endpoint(frame, variant, d, ref, selected) for d in ENDPOINTS]
        by_date = {e["valuation_date"]: e for e in endpoints}
        v21 = by_date["2021-11-20"].get("estimated_value_usd") if by_date["2021-11-20"].get("status") == "SUPPORTED" else None
        v24 = by_date["2024-11-20"].get("estimated_value_usd") if by_date["2024-11-20"].get("status") == "SUPPORTED" else None
        v26 = by_date["2026-11-20"].get("estimated_value_usd") if by_date["2026-11-20"].get("status") == "SUPPORTED" else None
        r24, r60 = _return(v26, v24), _return(v26, v21)
        row = {"model_variant": variant, "reference_specification": json.dumps(ref, sort_keys=True),
               "value_2021_usd": v21, "value_2024_usd": v24, "value_2026_usd": v26,
               "return_24m_pct": r24, "return_60m_pct": r60,
               "comparable_sale_count": int(len(group)),
               "effective_sample_size": by_date["2026-11-20"].get("effective_sample_size"),
               "lower_2026_usd": by_date["2026-11-20"].get("lower_usd"),
               "upper_2026_usd": by_date["2026-11-20"].get("upper_usd"),
               "historical_coverage": f"{group['_date'].min().date().isoformat()} to {group['_date'].max().date().isoformat()}",
               "historical_endpoint_support": {d: by_date[d].get("status") for d in ENDPOINTS},
               "confidence": "medium" if r24 is not None and len(group) >= 20 else "low" if r24 is not None else "insufficient",
               "screening_result": "PASS" if r24 is not None and r24 <= 5 else "FAIL" if r24 is not None else "UNVERIFIED",
               "model_version": selected,
               "source_urls": ",".join(group["source_url"].dropna().astype(str).head(50))}
        valuations.append(row)
    qualified = [v for v in valuations if v["screening_result"] == "PASS"]
    excluded = [v for v in valuations if v["screening_result"] == "FAIL"]
    unverified = [v for v in valuations if v["screening_result"] == "UNVERIFIED"]
    summary = {"input_row_count": int(len(raw)), "market_evidence_rows": int(len(frame)),
               "variant_count": int(len(variants)),
               "supported_24m_returns": int(sum(v["return_24m_pct"] is not None for v in valuations)),
               "supported_60m_returns": int(sum(v["return_60m_pct"] is not None for v in valuations)),
               "pass_24m_gate": int(len(qualified)), "fail_24m_gate": int(len(excluded)),
               "unverified_24m_gate": int(len(unverified)),
               "qualified_model_opportunities": int(len(qualified)),
               "individual_purchase_opportunities": 0,
               "historical_gate_enforced": True, "ranking_population": "PASS only",
               "time_origin_defect_corrected": True, "selected_method": selected,
               "method_version": MODEL_VERSION, "analytical_acceptance": bool(len(qualified) > 0)}
    return {"summary": summary, "valuations": valuations, "returns": [v for v in valuations if v["return_24m_pct"] is not None or v["return_60m_pct"] is not None],
            "qualified_model_opportunities": qualified, "excluded_over_5pct": excluded,
            "unverified_research_queue": unverified, "nsx": _nsx_study(valuations),
            "backtest": bt, "coverage": coverage,
            "model_metadata": {"model_version": MODEL_VERSION, "baseline_version": BASELINE_VERSION,
                               "hedonic_reference_version": HEDONIC_VERSION,
                               "data_snapshot_sha256": hashlib.sha256(raw.to_csv(index=False).encode()).hexdigest()},
            "limitations": ["Individual purchase opportunities require a current listing plus vehicle-specific title and condition due diligence.",
                            "Historical evidence remains limited by the production snapshot; no unsupported endpoint is extrapolated."]}
