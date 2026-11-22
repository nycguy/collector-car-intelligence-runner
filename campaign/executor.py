"""Production execution entry points for Sprint 26 and Sprint 27."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .analysis.sprint26 import analyze as analyze_sprint26
from .analysis.sprint27 import analyze as analyze_sprint27
from .analysis.sprint28 import analyze as analyze_sprint28

REQUIRED_COLUMNS = {
    "transaction_id", "vehicle_variant_id", "source_id", "auction_end_date",
    "sale_status", "price_usd", "title_status", "exclusion_flag",
    "variant_normalization_status",
}

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _read_source(input_path: str) -> tuple[Path, pd.DataFrame]:
    source = Path(input_path)
    raw = pd.read_csv(source, dtype=str, keep_default_na=False)
    missing = sorted(REQUIRED_COLUMNS - set(raw.columns))
    if missing:
        raise ValueError(f"snapshot missing required columns: {missing}")
    if raw.empty:
        raise ValueError("snapshot contains no rows")
    if raw.transaction_id.str.strip().eq("").any() or raw.transaction_id.duplicated().any():
        raise ValueError("blank or duplicate transaction_id detected")
    return source, raw

def execute(input_path: str, output_dir: str, snapshot_id: str,
            as_of: str = "2026-11-20") -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint26(raw, as_of=as_of, min_comparables=5)
    summary = result["summary"]
    valuation_rows = result["valuation"]
    exploratory_counts = {
        "current": sum(int(r.get("current_comparables", 0) >= 5) for r in valuation_rows),
        "24m": sum(bool(r.get("supported_24m")) for r in valuation_rows),
        "60m": sum(bool(r.get("supported_60m")) for r in valuation_rows),
        "historical_screen": sum(bool(r.get("supported_24m")) and (r.get("return_24m_pct") is not None) and r["return_24m_pct"] <= 5 for r in valuation_rows),
    }
    reason_counts = pd.Series([r["eligibility_reason"] for r in result["row_audit"]]).value_counts().sort_index().to_dict()
    metrics = {
        "status": "SUCCEEDED", "execution_scope": "sprint_26_analytical",
        "snapshot_id": snapshot_id, "analysis_date": as_of,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_row_count": len(raw), "input_sha256": sha256_file(source),
        **summary, "eligibility_funnel": result["funnel"],
        "eligibility_reason_counts": {str(k): int(v) for k, v in reason_counts.items()},
        "valuation_cohort_rows": len(result["valuation"]),
        "valuation_evidence": result["valuation"], "five_year_forecasts": result["forecasts"],
        "model_opportunities": result["model_opportunities"],
        "individual_purchase_opportunities": result["individual_opportunities"],
        "backtesting": {"status": "not_validated", "valid_oos_observations": 0, "reason": "No leakage-safe out-of-sample endpoint pairs were established."},
        "model_ranking_status": "blocked_without_verified_individual_purchase_population",
        "individual_ranking_status": "no_active_listing_population",
        "raw_rows_written_to_artifacts": False, "valuation_engine_executed": True,
        "exploratory_unadjusted_counts": exploratory_counts,
        "reconciliation_status": "Sprint 25 exploratory zeroes are not comparable to prior dashboard counts; Sprint 26 publishes only evidence-supported adjusted cohorts.",
    }
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    public_metrics = {k: v for k, v in metrics.items() if k not in {"valuation_evidence", "five_year_forecasts", "model_opportunities", "individual_purchase_opportunities"}}
    public_metrics["private_workbook_records_published"] = True
    (out / "metrics.json").write_text(json.dumps(public_metrics, indent=2) + "\n")
    return metrics

def execute_sprint27(input_path: str, output_dir: str, snapshot_id: str,
                     as_of: str = "2026-11-20") -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint27(raw, as_of=as_of, min_comparables=5)
    summary = result["summary"]
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    metrics = {
        "status": "SUCCEEDED", "execution_scope": "sprint_27_historical_recovery",
        "snapshot_id": snapshot_id, "analysis_date": as_of,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_row_count": len(raw), "input_sha256": sha256_file(source),
        **summary, "eligibility_funnel": result["funnel"],
        "eligibility_reason_counts": result["eligibility_reason_counts"],
        "valuation_cohort_rows": len(result["valuation"]),
        "valuation_evidence": result["valuation"],
        "market_evidence_valuation": result["market_valuation"],
        "historical_returns": result["historical_returns"],
        "variant_crosswalk": result["crosswalk_summary"],
        "clean_title_unassigned_clusters": result["unassigned_clusters"],
        "source_coverage": result["source_coverage"],
        "valuation_reconciliation": result["reconciliation"],
        "backtesting": {"status": "not_validated", "valid_oos_observations": 0, "reason": "Sprint 27 recovered evidence populations but did not claim leakage-safe forecasts."},
        "model_opportunities": [], "individual_purchase_opportunities": [],
        "model_ranking_status": "blocked_without_validated_returns",
        "individual_ranking_status": "blocked_without_vehicle_specific_due_diligence",
        "raw_rows_written_to_artifacts": False, "valuation_engine_executed": True,
        "reconciliation_status": "Sprint 25 and Sprint 26 counts reconciled by explicit variant-status stages; legacy dashboard values remain quarantined.",
    }
    public_metrics = {k: v for k, v in metrics.items() if k not in {"valuation_evidence", "market_evidence_valuation", "historical_returns", "model_opportunities", "individual_purchase_opportunities"}}
    public_metrics["private_workbook_records_published"] = True
    (out / "metrics.json").write_text(json.dumps(public_metrics, indent=2) + "\n")
    return metrics

def execute_sprint28(input_path: str, output_dir: str, snapshot_id: str,
                     as_of: str = "2026-11-20") -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint28(raw, as_of=as_of, min_comparables=5)
    summary = result["summary"]
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    metrics = {
        "status": "SUCCEEDED", "execution_scope": "sprint_28_evidence_recovery",
        "snapshot_id": snapshot_id, "analysis_date": as_of,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_row_count": len(raw), "input_sha256": sha256_file(source), **summary,
        "title_evidence_classification": result["title_counts"],
        "variant_recovery_classification": result["variant_counts"],
        "deterministic_source_label_clusters": result["source_label_clusters"],
        "source_research_priority": result["source_priority"],
        "historical_endpoint_diagnostics": result["endpoint_diagnostics"],
        "strict_endpoint_diagnostics": result["strict_endpoint_diagnostics"],
        "legacy_valuation_reconciliation": result["legacy_reconciliation"],
        "row_audit": result["row_audit"],
        "backtesting": {"status": "not_validated", "valid_oos_observations": 0, "reason": "Endpoint diagnostics are not promoted without documentary clean title and strict canonical variant support."},
        "model_opportunities": [], "individual_purchase_opportunities": [],
        "model_ranking_status": "blocked_without_documentary_clean_strict_endpoint_pairs",
        "individual_ranking_status": "blocked_without_vehicle_specific_due_diligence",
        "raw_rows_written_to_artifacts": False, "valuation_engine_executed": True,
        "reconciliation_status": "Legacy counts remain quarantined; Sprint 28 distinguishes source-reported clean title, documentary evidence, deterministic source labels, and strict canonical variants.",
    }
    public_metrics = {k: v for k, v in metrics.items() if k not in {"row_audit", "historical_endpoint_diagnostics", "strict_endpoint_diagnostics", "model_opportunities", "individual_purchase_opportunities"}}
    public_metrics["private_workbook_records_published"] = True
    (out / "metrics.json").write_text(json.dumps(public_metrics, indent=2) + "\n")
    return metrics
