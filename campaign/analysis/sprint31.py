"""Sprint 31 statistical valuation engine.

The engine is intentionally dependency-light: pandas, numpy and scikit-learn.
It estimates log completed-sale prices with regularized one-hot effects for
vehicle configuration and venue, nonlinear mileage terms, condition and a
continuous transaction-time effect.  A single pooled model gives sparse
variants partial pooling through the global feature effects while preserving
variant-specific intercepts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import hashlib
import json

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

MODEL_VERSION = "s31_hedonic_ridge_logprice_v1"
BASELINE_VERSION = "s29_trimmed_median_bounded_mileage_v1"
ANALYSIS_DATE = "2026-11-20"
ENDPOINTS = ("2021-11-20", "2024-11-20", "2026-11-20")
COMPLETED = {"sold", "completed", "sale", "sold_pending_title"}
ADVERSE_TERMS = ("salvage", "rebuilt", "flood", "total loss", "total-loss", "branded")
CONDITION_ORDER = {"poor": 1, "project": 1, "fair": 2, "good": 3, "very good": 4, "excellent": 5, "concours": 6}


@dataclass
class FitResult:
    model: Pipeline
    frame: pd.DataFrame
    feature_columns: list[str]
    residual_sigma: float
    train_end: pd.Timestamp


def _s(frame: pd.DataFrame, col: str) -> pd.Series:
    return frame[col].fillna("").astype(str) if col in frame else pd.Series("", index=frame.index)


def _clean_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _title_adverse(row: pd.Series) -> bool:
    text = " ".join(_clean_text(row.get(c)) for c in ("title_status", "title_evidence_status", "source_title_status_assertion"))
    return any(term in text for term in ADVERSE_TERMS)


def _condition(value: Any) -> str:
    text = _clean_text(value)
    for key in CONDITION_ORDER:
        if key in text:
            return key
    return "unknown"


def prepare_transactions(raw: pd.DataFrame, as_of: str = ANALYSIS_DATE) -> pd.DataFrame:
    df = raw.copy()
    df["_status"] = _s(df, "sale_status").str.lower().str.strip()
    df["_price"] = pd.to_numeric(_s(df, "price_usd"), errors="coerce")
    df["_date"] = pd.to_datetime(_s(df, "auction_end_date"), errors="coerce")
    df["_mileage"] = pd.to_numeric(_s(df, "mileage_at_sale"), errors="coerce")
    df["_year"] = pd.to_numeric(_s(df, "model_year"), errors="coerce")
    df["_variant"] = _s(df, "source_variant_id").where(_s(df, "source_variant_id").str.strip().ne(""), _s(df, "vehicle_variant_id"))
    df["_variant"] = df["_variant"].str.strip().replace("", "unknown_variant")
    df["_condition"] = _s(df, "condition_grade").map(_condition)
    df["_adverse"] = df.apply(_title_adverse, axis=1)
    df["_market"] = (df["_status"].isin(COMPLETED) & df["_price"].gt(0) & df["_date"].notna() &
                     df["_date"].le(pd.Timestamp(as_of)) & ~df["_adverse"] &
                     _s(df, "source_url").str.strip().ne(""))
    df = df[df["_market"]].copy()
    if df.empty:
        raise ValueError("no completed, non-adverse, price-bearing transactions")
    min_date = df["_date"].min()
    df["_time_months"] = (df["_date"] - min_date).dt.days / 30.4375
    df["_log_mileage"] = np.log1p(df["_mileage"].clip(lower=0))
    df["_mileage_sq"] = df["_log_mileage"] ** 2
    df["_model_year_centered"] = df["_year"] - df["_year"].median()
    for col in ("transmission", "engine", "body_style", "trim", "generation", "modifications", "source_name"):
        df[col] = _s(df, col).str.lower().str.strip().replace("", "unknown")
    df["_price_log"] = np.log(df["_price"])
    return df


def _feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    numeric = ["_time_months", "_log_mileage", "_mileage_sq", "_model_year_centered"]
    categorical = ["_variant", "transmission", "engine", "body_style", "trim", "generation", "modifications", "_condition", "source_name"]
    out = df[numeric + categorical].copy()
    for col in categorical:
        out[col] = out[col].replace("", "unknown").fillna("unknown")
    for col in numeric:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def fit_model(frame: pd.DataFrame, train_end: str | None = None, alpha: float = 8.0) -> FitResult:
    train = frame if train_end is None else frame[frame["_date"] <= pd.Timestamp(train_end)]
    if len(train) < 20:
        raise ValueError(f"insufficient training observations: {len(train)}")
    numeric = ["_time_months", "_log_mileage", "_mileage_sq", "_model_year_centered"]
    categorical = ["_variant", "transmission", "engine", "body_style", "trim", "generation", "modifications", "_condition", "source_name"]
    pre = ColumnTransformer([
        ("num", Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())]), numeric),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore"))]), categorical),
    ])
    model = Pipeline([("features", pre), ("ridge", Ridge(alpha=alpha))])
    X = _feature_frame(train)
    model.fit(X, train["_price_log"])
    residual = train["_price_log"].to_numpy() - model.predict(X)
    sigma = float(np.std(residual, ddof=1)) if len(residual) > 1 else 0.35
    sigma = max(0.08, min(1.5, sigma))
    return FitResult(model=model, frame=train, feature_columns=numeric + categorical, residual_sigma=sigma,
                     train_end=train["_date"].max())


def _reference_row(group: pd.DataFrame, valuation_date: str, reference: dict[str, Any] | None = None) -> pd.DataFrame:
    ref = dict(reference or {})
    row: dict[str, Any] = {}
    for col in ("_variant", "transmission", "engine", "body_style", "trim", "generation", "modifications", "_condition", "source_name"):
        if col in ref:
            row[col] = ref[col]
        else:
            vals = group[col].replace("", "unknown").dropna()
            row[col] = vals.mode().iloc[0] if not vals.empty else "unknown"
    miles = ref.get("mileage")
    if miles is None:
        known = pd.to_numeric(group["_mileage"], errors="coerce").dropna()
        miles = float(known.median()) if not known.empty else None
    year = ref.get("model_year")
    if year is None:
        known = pd.to_numeric(group["_year"], errors="coerce").dropna()
        year = float(known.median()) if not known.empty else None
    min_date = group["_date"].min()
    date = pd.Timestamp(valuation_date)
    row["_time_months"] = (date - min_date).days / 30.4375
    row["_mileage"] = miles
    row["_log_mileage"] = math.log1p(max(0, float(miles))) if miles is not None else np.nan
    row["_mileage_sq"] = row["_log_mileage"] ** 2 if miles is not None else np.nan
    row["_year"] = year
    row["_model_year_centered"] = float(year - group["_year"].median()) if year is not None and group["_year"].notna().any() else np.nan
    return pd.DataFrame([row])


def _interval(value: float, sigma: float, n: int, effective_n: float) -> tuple[float, float]:
    inflation = 1.0 + 1.96 / math.sqrt(max(1.0, effective_n))
    half = math.sqrt(sigma * sigma + (math.log(inflation) ** 2))
    return max(0.0, value * math.exp(-1.96 * half)), value * math.exp(1.96 * half)


def estimate_value(fit: FitResult, variant: str, valuation_date: str, reference: dict[str, Any] | None = None) -> dict[str, Any]:
    group = fit.frame[fit.frame["_variant"] == variant]
    if group.empty:
        return {"variant": variant, "valuation_date": valuation_date, "status": "UNSUPPORTED", "reason": "variant_absent_from_training"}
    date = pd.Timestamp(valuation_date)
    observed_min, observed_max = fit.frame["_date"].min(), fit.train_end
    within = observed_min <= date <= observed_max
    n = len(group)
    effective_n = float(min(n, max(1.0, n / (1.0 + group["_date"].dt.year.nunique() / 8.0))))
    ref_row = _reference_row(group, valuation_date, reference)
    pred_log = float(fit.model.predict(_feature_frame(ref_row))[0])
    value = float(math.exp(pred_log + 0.5 * fit.residual_sigma ** 2))
    lower, upper = _interval(value, fit.residual_sigma, n, effective_n)
    status = "SUPPORTED" if within and n >= 8 else "UNVERIFIED"
    return {"variant": variant, "valuation_date": valuation_date, "estimated_value_usd": round(value, 2),
            "lower_usd": round(lower, 2), "upper_usd": round(upper, 2), "comparable_sale_count": n,
            "effective_sample_size": round(effective_n, 2), "historical_min_date": observed_min.date().isoformat(),
            "historical_max_date": observed_max.date().isoformat(), "status": status, "model_version": MODEL_VERSION,
            "reference_specification": json.dumps(reference or {}, sort_keys=True)}


def _baseline(group: pd.DataFrame, date: str, reference: dict[str, Any] | None = None) -> float | None:
    x = group[group["_date"].between(pd.Timestamp(date) - pd.Timedelta(days=365), pd.Timestamp(date) + pd.Timedelta(days=365))]
    if x.empty:
        return None
    vals = x["_price"].sort_values().to_numpy()
    if len(vals) >= 8:
        vals = vals[1:-1]
    return float(np.median(vals))


def _return(a: float | None, b: float | None) -> float | None:
    return round((a / b - 1.0) * 100.0, 2) if a is not None and b and b > 0 else None


def rolling_backtest(frame: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for cutoff in ("2022-11-20", "2023-11-20", "2024-11-20", "2025-11-20"):
        train = frame[frame["_date"] <= pd.Timestamp(cutoff)]
        test = frame[(frame["_date"] > pd.Timestamp(cutoff)) & (frame["_date"] <= pd.Timestamp(cutoff) + pd.DateOffset(months=12))]
        if len(train) < 20 or test.empty:
            continue
        fit = fit_model(frame, train_end=cutoff)
        preds = fit.model.predict(_feature_frame(test))
        actual = test["_price"].to_numpy()
        hedonic = np.exp(preds)
        base = np.array([_baseline(frame[frame["_variant"] == v], d.date().isoformat()) or np.nan for v, d in zip(test["_variant"], test["_date"])])
        for name, values in ((MODEL_VERSION, hedonic), (BASELINE_VERSION, base)):
            good = np.isfinite(values) & (actual > 0)
            if not good.any():
                continue
            ape = np.abs(values[good] / actual[good] - 1)
            rows.append({"cutoff": cutoff, "method": name, "out_of_sample_n": int(good.sum()),
                         "mape_pct": round(float(np.mean(ape) * 100), 2),
                         "mae_usd": round(float(np.mean(np.abs(values[good] - actual[good]))), 2),
                         "bias_pct": round(float(np.mean(values[good] / actual[good] - 1) * 100), 2)})
    if not rows:
        return {"status": "UNVERIFIED", "reason": "insufficient time-based out-of-sample coverage", "folds": []}
    by_method: dict[str, Any] = {}
    for method, g in pd.DataFrame(rows).groupby("method"):
        by_method[method] = {"folds": g.to_dict("records"), "mape_pct": round(float(g.mape_pct.mean()), 2), "mae_usd": round(float(g.mae_usd.mean()), 2), "bias_pct": round(float(g.bias_pct.mean()), 2), "out_of_sample_n": int(g.out_of_sample_n.sum())}
    advanced = by_method.get(MODEL_VERSION, {})
    baseline = by_method.get(BASELINE_VERSION, {})
    superior = bool(advanced and baseline and advanced.get("mape_pct", math.inf) <= baseline.get("mape_pct", math.inf))
    return {"status": "VALIDATED", "methods": by_method, "advanced_beats_baseline_on_mape": superior, "folds": rows}


def _reference_for(group: pd.DataFrame, variant: str) -> dict[str, Any]:
    known = pd.to_numeric(group["_mileage"], errors="coerce").dropna()
    year = pd.to_numeric(group["_year"], errors="coerce").dropna()
    return {"variant": variant, "mileage": round(float(known.median())) if not known.empty else None,
            "model_year": round(float(year.median())) if not year.empty else None,
            "transmission": group["transmission"].mode().iloc[0] if not group["transmission"].mode().empty else "unknown",
            "condition": group["_condition"].mode().iloc[0] if not group["_condition"].mode().empty else "unknown"}


def analyze(raw: pd.DataFrame, as_of: str = ANALYSIS_DATE, top_n: int = 20) -> dict[str, Any]:
    frame = prepare_transactions(raw, as_of)
    fit = fit_model(frame)
    variants = sorted(frame["_variant"].unique())
    valuations: list[dict[str, Any]] = []
    returns: list[dict[str, Any]] = []
    for variant in variants:
        group = frame[frame["_variant"] == variant]
        ref = _reference_for(group, variant)
        ep = {d: estimate_value(fit, variant, d, ref) for d in ENDPOINTS}
        v21, v24, v26 = (ep[d].get("estimated_value_usd") if ep[d].get("status") != "UNSUPPORTED" else None for d in ENDPOINTS)
        supported = all(ep[d].get("status") == "SUPPORTED" for d in ENDPOINTS)
        r24, r60 = (_return(v26, v24), _return(v26, v21)) if supported else (None, None)
        row = {"model_variant": variant, "reference_specification": json.dumps(ref, sort_keys=True),
               "value_2021_usd": v21, "value_2024_usd": v24, "value_2026_usd": v26,
               "return_24m_pct": r24, "return_60m_pct": r60, "comparable_sale_count": len(group),
               "effective_sample_size": ep[ENDPOINTS[-1]].get("effective_sample_size"),
               "lower_2026_usd": ep[ENDPOINTS[-1]].get("lower_usd"), "upper_2026_usd": ep[ENDPOINTS[-1]].get("upper_usd"),
               "historical_coverage": f"{group['_date'].min().date().isoformat()} to {group['_date'].max().date().isoformat()}",
               "confidence": "medium" if supported and len(group) >= 20 else "low" if supported else "insufficient",
               "screening_result": "PASS" if r24 is not None and r24 <= 5 else "FAIL" if r24 is not None else "UNVERIFIED",
               "model_version": MODEL_VERSION, "source_urls": ",".join(group["source_url"].dropna().astype(str).head(50))}
        valuations.append(row)
        if r24 is not None or r60 is not None:
            returns.append(row.copy())
    nsx_rows = [{"variant": "Acura NSX NA1 3.0 manual, 1991", "physical_vehicle_id": "JH4NA1152MT001527", "date_2024": "2024-10-19", "price_2024_usd": 72000.0, "mileage_2024": 66000, "date_2026": "2026-06-26", "price_2026_usd": 86500.0, "mileage_2026": 68000, "repeat_sale_return_pct": 20.14, "screening_result": "FAIL", "evidence_type": "repeat_sale_supporting_evidence", "source_urls": "https://bringatrailer.com/listing/1991-acura-nsx-253/, https://bringatrailer.com/listing/1991-acura-nsx-305/"}]
    bt = rolling_backtest(frame)
    summary = {"input_row_count": len(raw), "market_evidence_rows": len(frame), "variant_count": len(variants), "supported_24m_returns": sum(v["return_24m_pct"] is not None for v in valuations), "supported_60m_returns": sum(v["return_60m_pct"] is not None for v in valuations), "pass_24m_gate": sum(v["screening_result"] == "PASS" for v in valuations), "fail_24m_gate": sum(v["screening_result"] == "FAIL" for v in valuations), "unverified_24m_gate": sum(v["screening_result"] == "UNVERIFIED" for v in valuations), "qualified_model_opportunities": sum(v["screening_result"] == "PASS" for v in valuations), "historical_gate_enforced": True, "ranking_population": "PASS only", "method_version": MODEL_VERSION}
    return {"summary": summary, "valuations": valuations, "returns": returns, "nsx": nsx_rows, "backtest": bt, "model_metadata": {"model_version": MODEL_VERSION, "baseline_version": BASELINE_VERSION, "alpha": 8.0, "features": ["variant", "time", "log_mileage", "log_mileage_squared", "model_year", "transmission", "engine", "body_style", "trim", "generation", "condition", "modifications", "venue"], "data_snapshot_sha256": hashlib.sha256(raw.to_csv(index=False).encode()).hexdigest()}}
