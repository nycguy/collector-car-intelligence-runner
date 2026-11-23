from __future__ import annotations
import json, os, time
from pathlib import Path
from .executor import execute, execute_sprint27, execute_sprint28, execute_sprint29, execute_sprint30, execute_sprint31, execute_sprint32, execute_sprint34
from .google_sheets import retrieve_transactions, publish_metrics, publish_sprint26, publish_sprint27, publish_sprint28, publish_sprint29, publish_sprint30, publish_sprint31, publish_sprint32

def run() -> dict:
    started = time.monotonic()
    spreadsheet_id = os.environ["CCI_SPREADSHEET_ID"]
    mode = os.environ.get("CCI_MODE", "auth-test")
    allowed = {"auth-test","production","sprint26","sprint27","sprint28","sprint29","sprint30","sprint31","sprint32","sprint34"}
    if mode not in allowed: raise ValueError("unsupported execution mode")
    snapshot_id = os.environ.get("CCI_SNAPSHOT_ID") or f"github-actions-{os.environ.get('GITHUB_RUN_ID','local')}"
    output_dir = Path(os.environ.get("CCI_OUTPUT_DIR", "run-output"))
    input_path, evidence = retrieve_transactions(spreadsheet_id)
    try:
        if mode == "auth-test":
            metrics = {"status":"SUCCEEDED","execution_scope":"authentication_test","valuation_engine_executed":False,"analytical_acceptance":False}
        elif mode == "sprint27": metrics = execute_sprint27(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        elif mode == "sprint28": metrics = execute_sprint28(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        elif mode == "sprint29": metrics = execute_sprint29(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        elif mode == "sprint30": metrics = execute_sprint30(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        elif mode == "sprint31": metrics = execute_sprint31(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        elif mode == "sprint32": metrics = execute_sprint32(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        else: metrics = execute(str(input_path),str(output_dir),snapshot_id,os.environ.get("CCI_ANALYSIS_DATE","2026-11-20"))
        metrics.update({"execution_id":os.environ.get("GITHUB_RUN_ID","local"),"commit_sha":os.environ.get("GITHUB_SHA"),"run_url":f"https://github.com/{os.environ.get('GITHUB_REPOSITORY','nycguy/collector-car-intelligence-runner')}/actions/runs/{os.environ.get('GITHUB_RUN_ID','local')}","input_snapshot_id":snapshot_id,"production_source":"google-sheets","input_row_count":evidence["row_count"],"input_sha256":evidence["input_sha256"],"google_cloud_project":evidence["project"],"service_account":os.environ.get("CCI_SERVICE_ACCOUNT"),"workload_identity_provider":os.environ.get("CCI_IDENTITY_PROVIDER"),"execution_duration_seconds":round(time.monotonic()-started,3)})
        if mode == "auth-test": publication = publish_metrics(spreadsheet_id,metrics,"Sprint 25 Auth Test")
        elif mode == "sprint26": publication = publish_sprint26(spreadsheet_id,metrics)
        elif mode == "sprint27": publication = publish_sprint27(spreadsheet_id,metrics)
        elif mode == "sprint28": publication = publish_sprint28(spreadsheet_id,metrics)
        elif mode == "sprint29": publication = publish_sprint29(spreadsheet_id,metrics)
        elif mode == "sprint30": publication = publish_sprint30(spreadsheet_id,metrics)
        elif mode == "sprint31": publication = publish_sprint31(spreadsheet_id,metrics)
        elif mode == "sprint32": publication = publish_sprint32(spreadsheet_id,metrics)
        elif mode == "sprint34": publication = publish_sprint34(spreadsheet_id,metrics)
        else: publication = publish_metrics(spreadsheet_id,metrics,"Sprint 25 Runner Output")
        metrics["publication"] = publication
        output_dir.mkdir(parents=True,exist_ok=True)
        public_metrics = {k:v for k,v in metrics.items() if k not in {"valuation_evidence","market_evidence_valuation","historical_returns","five_year_forecasts","model_opportunities","individual_purchase_opportunities","investment_watchlist","historical_valuations","forecast_scenarios"}}
        public_metrics["private_workbook_records_published"] = True
        (output_dir/"metrics.json").write_text(json.dumps(public_metrics,indent=2)+"\n")
        (output_dir/"publication_status.json").write_text(json.dumps(publication,indent=2)+"\n")
        return metrics
    finally:
        input_path.unlink(missing_ok=True)

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
