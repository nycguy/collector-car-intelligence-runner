"""Production execution entry points for Sprint 26 through Sprint 29."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .analysis.sprint26 import analyze as analyze_sprint26
from .analysis.sprint27 import analyze as analyze_sprint27
from .analysis.sprint28 import analyze as analyze_sprint28
from .analysis.sprint29 import analyze as analyze_sprint29
from .analysis.sprint30 import analyze as analyze_sprint30
from .analysis.sprint31 import analyze as analyze_sprint31
from .analysis.sprint32 import analyze as analyze_sprint32
from .analysis.sprint34 import analyze as analyze_sprint34
from .analysis.sprint35 import analyze as analyze_sprint35
REQUIRED_COLUMNS={"transaction_id","vehicle_variant_id","source_id","auction_end_date","sale_status","price_usd","title_status","exclusion_flag","variant_normalization_status"}
def sha256_file(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _read_source(input_path:str)->tuple[Path,pd.DataFrame]:
    source=Path(input_path); raw=pd.read_csv(source,dtype=str,keep_default_na=False); missing=sorted(REQUIRED_COLUMNS-set(raw.columns))
    if missing: raise ValueError(f"snapshot missing required columns: {missing}")
    if raw.empty: raise ValueError("snapshot contains no rows")
    if raw.transaction_id.str.strip().eq("").any() or raw.transaction_id.duplicated().any(): raise ValueError("blank or duplicate transaction_id detected")
    return source,raw
def _write_public(out:Path,metrics:dict,exclude:set[str])->None:
    out.mkdir(parents=True,exist_ok=True); public={k:v for k,v in metrics.items() if k not in exclude}; public["private_workbook_records_published"]=True
    (out/"metrics.json").write_text(json.dumps(public,indent=2)+"\n")
def execute(input_path:str,output_dir:str,snapshot_id:str,as_of:str="2026-11-20")->dict:
    source,raw=_read_source(input_path); result=analyze_sprint26(raw,as_of=as_of,min_comparables=5); summary=result["summary"]
    metrics={"status":"SUCCEEDED","execution_scope":"sprint_26_analytical","snapshot_id":snapshot_id,"analysis_date":as_of,"extracted_at_utc":datetime.now(timezone.utc).isoformat(),"input_row_count":len(raw),"input_sha256":sha256_file(source),**summary,"valuation_evidence":result["valuation"],"five_year_forecasts":result["forecasts"],"model_opportunities":result["model_opportunities"],"individual_purchase_opportunities":result["individual_opportunities"],"backtesting":{"status":"not_validated","valid_oos_observations":0},"valuation_engine_executed":True,"valuation_cohort_rows":len(result["valuation"]),"exploratory_unadjusted_counts":{"current":sum(int(r.get("current_comparables",0)>=5) for r in result["valuation"]),"24m":sum(bool(r.get("supported_24m")) for r in result["valuation"]),"60m":sum(bool(r.get("supported_60m")) for r in result["valuation"]),"historical_screen":sum(bool(r.get("supported_24m")) and r.get("return_24m_pct") is not None and r["return_24m_pct"]<=5 for r in result["valuation"])}}
    _write_public(Path(output_dir),metrics,{"valuation_evidence","five_year_forecasts","model_opportunities","individual_purchase_opportunities"}); return metrics
def execute_sprint27(input_path:str,output_dir:str,snapshot_id:str,as_of:str="2026-11-20")->dict:
    source,raw=_read_source(input_path); result=analyze_sprint27(raw,as_of=as_of,min_comparables=5); summary=result["summary"]
    metrics={"status":"SUCCEEDED","execution_scope":"sprint_27_historical_recovery","snapshot_id":snapshot_id,"analysis_date":as_of,"extracted_at_utc":datetime.now(timezone.utc).isoformat(),"input_row_count":len(raw),"input_sha256":sha256_file(source),**summary,"eligibility_funnel":result["funnel"],"eligibility_reason_counts":result["eligibility_reason_counts"],"valuation_evidence":result["valuation"],"market_evidence_valuation":result["market_valuation"],"historical_returns":result["historical_returns"],"variant_crosswalk":result["crosswalk_summary"],"clean_title_unassigned_clusters":result["unassigned_clusters"],"source_coverage":result["source_coverage"],"valuation_reconciliation":result["reconciliation"],"model_opportunities":[],"individual_purchase_opportunities":[],"valuation_engine_executed":True}
    _write_public(Path(output_dir),metrics,{"valuation_evidence","market_evidence_valuation","historical_returns","model_opportunities","individual_purchase_opportunities"}); return metrics
def execute_sprint28(input_path:str,output_dir:str,snapshot_id:str,as_of:str="2026-11-20")->dict:
    source,raw=_read_source(input_path); result=analyze_sprint28(raw,as_of=as_of,min_comparables=5); summary=result["summary"]
    metrics={"status":"SUCCEEDED","execution_scope":"sprint_28_evidence_recovery","snapshot_id":snapshot_id,"analysis_date":as_of,"extracted_at_utc":datetime.now(timezone.utc).isoformat(),"input_row_count":len(raw),"input_sha256":sha256_file(source),**summary,"title_evidence_classification":result["title_counts"],"variant_recovery_classification":result["variant_counts"],"deterministic_source_label_clusters":result["source_label_clusters"],"source_research_priority":result["source_priority"],"historical_endpoint_diagnostics":result["endpoint_rows"] if "endpoint_rows" in result else result["endpoint_diagnostics"],"strict_endpoint_diagnostics":result["strict_endpoint_diagnostics"],"legacy_valuation_reconciliation":result["legacy_reconciliation"],"row_audit":result["row_audit"],"model_opportunities":[],"individual_purchase_opportunities":[],"valuation_engine_executed":True}
    _write_public(Path(output_dir),metrics,{"row_audit","historical_endpoint_diagnostics","strict_endpoint_diagnostics","model_opportunities","individual_purchase_opportunities"}); return metrics
def execute_sprint29(input_path:str,output_dir:str,snapshot_id:str,as_of:str="2026-11-20")->dict:
    source,raw=_read_source(input_path); result=analyze_sprint29(raw,as_of=as_of,min_comparables=3,top_n=20); summary=result["summary"]
    metrics={"status":"SUCCEEDED","execution_scope":"sprint_29_market_valuation_and_watchlist","snapshot_id":snapshot_id,"analysis_date":as_of,"extracted_at_utc":datetime.now(timezone.utc).isoformat(),"input_row_count":len(raw),"input_sha256":sha256_file(source),**summary,"investment_watchlist":result["watchlist"],"model_opportunities":result["watchlist"],"individual_purchase_opportunities":[],"historical_valuations":result["valuations"],"historical_returns":result["historical_returns"],"forecast_scenarios":result["forecast_scenarios"],"title_population":result["title_population"],"legacy_valuation_reconciliation":result["legacy_reconciliation"],"data_coverage":result["coverage"],"backtesting":{"status":"not_validated","valid_oos_observations":0,"reason":"judgment scenarios are not statistically calibrated"},"model_ranking_status":"provisional_market_evidence_ranking","individual_ranking_status":"blocked_without_vehicle_specific_due_diligence","valuation_engine_executed":True,"raw_rows_written_to_artifacts":False}
    _write_public(Path(output_dir),metrics,{"investment_watchlist","model_opportunities","historical_valuations","historical_returns","forecast_scenarios"}); return metrics

def execute_sprint30(input_path:str,output_dir:str,snapshot_id:str,as_of:str="2026-11-20")->dict:
    source,raw=_read_source(input_path)
    result=analyze_sprint30(raw,as_of=as_of,min_comparables=3,top_n=20)
    summary=result["summary"]
    metrics={"status":"SUCCEEDED","execution_scope":"sprint_30_historical_appreciation_validation",
             "snapshot_id":snapshot_id,"analysis_date":as_of,"extracted_at_utc":datetime.now(timezone.utc).isoformat(),
             "input_row_count":len(raw),"input_sha256":sha256_file(source),**summary,
             "qualified_model_opportunities":result["qualified_model_opportunities"],
             "excluded_model_variants":result["excluded_model_variants"],
             "unverified_research_queue":result["unverified_research_queue"],
             "historical_valuations":result["historical_valuations"],
             "historical_returns":result["historical_returns"],
             "forecast_scenarios":result["forecast_scenarios"],
             "individual_purchase_opportunities":[],
             "watchlist_audit":result["watchlist_audit"],
             "nsx_investigation":result["nsx_investigation"],
             "title_population":result["title_population"],
             "legacy_valuation_reconciliation":result["legacy_valuation_reconciliation"],
             "data_coverage":result["data_coverage"],
             "limitations":result["limitations"],
             "method_version":result["method_version"],
             "valuation_engine_executed":True,
             "ranking_gate":"historical_24m_before_forecast_before_ranking"}
    _write_public(Path(output_dir),metrics,{"qualified_model_opportunities","excluded_model_variants","unverified_research_queue","historical_valuations","historical_returns","forecast_scenarios","watchlist_audit","nsx_investigation"})
    return metrics


def execute_sprint31(input_path: str, output_dir: str, snapshot_id: str, as_of: str = "2026-11-20") -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint31(raw, as_of=as_of)
    summary = result["summary"]
    metrics = {
        "status": "SUCCEEDED", "execution_scope": "sprint_31_statistical_valuation",
        "snapshot_id": snapshot_id, "analysis_date": as_of,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_row_count": len(raw), "input_sha256": sha256_file(source), **summary,
        "historical_valuations": result["valuations"], "historical_returns": result["returns"],
        "nsx_valuation_study": result["nsx"], "model_validation": result["backtest"],
        "model_metadata": result["model_metadata"], "qualified_model_opportunities": [r for r in result["valuations"] if r.get("screening_result") == "PASS"],
        "excluded_over_5pct": [r for r in result["valuations"] if r.get("screening_result") == "FAIL"],
        "unverified_research_queue": [r for r in result["valuations"] if r.get("screening_result") == "UNVERIFIED"],
        "individual_purchase_opportunities": [], "valuation_engine_executed": True,
        "ranking_gate": "historical_24m_before_ranking", "raw_rows_written_to_artifacts": False,
        "analytical_acceptance": False
    }
    _write_public(Path(output_dir), metrics, {"historical_valuations", "historical_returns", "nsx_valuation_study", "qualified_model_opportunities", "excluded_over_5pct", "unverified_research_queue"})
    return metrics


def execute_sprint34(input_path: str, output_dir: str, snapshot_id: str, as_of: str = "2026-11-20") -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint34(raw)
    summary = result["summary"]
    metrics = {
        "status": "SUCCEEDED", "execution_scope": "sprint_34_identity_recovery",
        "snapshot_id": snapshot_id, "analysis_date": as_of,
        "input_row_count": len(raw), "input_sha256": sha256_file(source), **summary,
        "canonical_variant_rows": result["recovered"].to_dict("records"),
        "vertical_slice": result["vertical_slice"].to_dict("records"),
        "qualified_model_opportunities": [], "individual_purchase_opportunities": [],
        "ranking_status": "blocked_until_canonical_24m_recalculation",
        "raw_rows_written_to_artifacts": False,
        "analytical_acceptance": False,
    }
    _write_public(Path(output_dir), metrics, {"canonical_variant_rows", "vertical_slice"})
    return metrics


def execute_sprint32(input_path: str, output_dir: str, snapshot_id: str, as_of: str = "2026-11-20") -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint32(raw, as_of=as_of)
    summary = result["summary"]
    metrics = {
        "status": "SUCCEEDED", "execution_scope": "sprint_32_valuation_recovery",
        "snapshot_id": snapshot_id, "analysis_date": as_of,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_row_count": len(raw), "input_sha256": sha256_file(source), **summary,
        "qualified_model_opportunities": result["qualified_model_opportunities"],
        "excluded_over_5pct": result["excluded_over_5pct"],
        "unverified_research_queue": result["unverified_research_queue"],
        "historical_valuations": result["valuations"], "historical_returns": result["returns"],
        "nsx_valuation_study": result["nsx"], "model_validation": result["backtest"],
        "data_coverage": result["coverage"], "model_metadata": result["model_metadata"],
        "individual_purchase_opportunities": [], "limitations": result["limitations"],
        "valuation_engine_executed": True, "ranking_gate": "historical_24m_before_forecast_before_ranking",
        "raw_rows_written_to_artifacts": False, "analytical_acceptance": summary["analytical_acceptance"],
    }
    _write_public(Path(output_dir), metrics, {"historical_valuations", "historical_returns", "nsx_valuation_study", "qualified_model_opportunities", "excluded_over_5pct", "unverified_research_queue"})
    return metrics


def execute_sprint35(input_path: str, output_dir: str, snapshot_id: str, as_of: str = "2026-11-20", legacy_pass_records=None) -> dict:
    source, raw = _read_source(input_path)
    result = analyze_sprint35(raw, output_dir=output_dir, legacy_pass_records=legacy_pass_records or [])
    summary = result["summary"]
    metrics = {"status": "SUCCEEDED", "execution_scope": "sprint_35_vin_identity_recovery", "snapshot_id": snapshot_id, "analysis_date": as_of, "extracted_at_utc": datetime.now(timezone.utc).isoformat(), "input_row_count": len(raw), "input_sha256": sha256_file(source), **summary, "vin_quality_audit": result["audit"], "vin_decode_coverage": result["decode_coverage"], "identity_conflicts": result["identity_conflicts"], "historical_valuations": result["valuations"], "historical_returns": [r for r in result["valuations"] if r.get("return_24m_pct") is not None or r.get("return_60m_pct") is not None], "sprint32_pass_crosswalk": result["crosswalk"], "qualified_model_opportunities": result["model_opportunities"], "provisional_research_queue": result["provisional_queue"], "individual_purchase_opportunities": [], "model_backtesting": {"status": "not_recomputed", "reason": "Sprint 35 canonical endpoint reconstruction uses a separate conservative population and explicitly avoids claiming comparable accuracy"}, "valuation_engine_executed": True, "analytical_acceptance": False, "ranking_gate": "historical_24m_before_forecast_before_ranking", "raw_rows_written_to_artifacts": False}
    _write_public(Path(output_dir), metrics, {"recovered_rows", "historical_valuations", "historical_returns", "sprint32_pass_crosswalk", "qualified_model_opportunities", "provisional_research_queue", "identity_conflicts"})
    return metrics
