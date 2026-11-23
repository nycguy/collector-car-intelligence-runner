from __future__ import annotations
import csv, hashlib, json, math, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
TRANSACTION_COLUMNS = ['transaction_id','listing_id','physical_vehicle_id','vehicle_variant_id','source_id','source_name','source_url','auction_start_date','auction_end_date','sale_status','sale_price','currency','buyer_premium_included','price_usd','mileage_at_sale','condition_grade','title_status','location','seller_type','evidence_url','evidence_capture_date','data_quality_score','duplicate_group_id','repeat_sale_group_id','exclusion_flag','exclusion_reason','notes','legacy_transaction_id','legacy_listing_id','source_title_status_assertion','title_evidence_status','source_outcome_assertion','outcome_verification_status','data_use_status','identity_method','vin','physical_identity_status','source_variant_id','variant_normalization_status','investment_eligibility_status','reconciliation_status','legacy_duplicate_group_id','source_data_quality_score_assertion']
def _retry(operation: Callable[[], Any], attempts: int = 3) -> Any:
    last=None
    for attempt in range(attempts):
        try: return operation()
        except Exception as exc:
            last=exc
            if attempt+1<attempts: time.sleep(2**attempt)
    raise RuntimeError(f"Google Sheets operation failed after {attempts} attempts") from last
def _service():
    from googleapiclient.discovery import build
    import google.auth
    credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets","v4",credentials=credentials,cache_discovery=False), project
def _values(service, spreadsheet_id: str, sheet: str, cell_range: str) -> list[list[Any]]:
    result=_retry(lambda: service.spreadsheets().values().get(spreadsheetId=spreadsheet_id,range=f"'{sheet}'!{cell_range}",valueRenderOption="UNFORMATTED_VALUE").execute())
    return result.get("values",[])
def retrieve_transactions(spreadsheet_id: str, sheet: str = "Auction Transactions", cell_range: str = "A1:AQ") -> tuple[Path, dict]:
    service, project=_service(); rows=_values(service,spreadsheet_id,sheet,cell_range)
    if not rows or rows[0] != TRANSACTION_COLUMNS: raise ValueError("production sheet schema does not match the approved transaction contract")
    data=rows[1:]
    if any(len(row)>len(TRANSACTION_COLUMNS) for row in data): raise ValueError("production row exceeds schema width")
    if len(data)!=28058: raise ValueError(f"unexpected production row count: {len(data)}")
    fd,name=tempfile.mkstemp(prefix="cci-production-",suffix=".csv"); os.close(fd); path=Path(name)
    with path.open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=TRANSACTION_COLUMNS); writer.writeheader()
        for row in data:
            padded=list(row)+[""]*(len(TRANSACTION_COLUMNS)-len(row)); writer.writerow(dict(zip(TRANSACTION_COLUMNS,padded[:len(TRANSACTION_COLUMNS)])))
    legacy_rows = _values(service, spreadsheet_id, "Adjusted 24-Month Returns", "A1:Q2000")
    legacy_records = []
    if legacy_rows:
        legacy_header = legacy_rows[0]
        if "model_variant" in legacy_header and "screening_result" in legacy_header:
            legacy_records = [dict(zip(legacy_header, row + [""] * (len(legacy_header) - len(row)))) for row in legacy_rows[1:] if any(str(x).strip() for x in row)]
    if not legacy_records:
        crosswalk_rows = _values(service, spreadsheet_id, "Sprint 32 PASS Crosswalk", "A1:H1000")
        if crosswalk_rows and "source_variant" in crosswalk_rows[0]:
            crosswalk_header = crosswalk_rows[0]
            for row in crosswalk_rows[1:]:
                record = dict(zip(crosswalk_header, row + [""] * (len(crosswalk_header) - len(row))))
                if str(record.get("original_screening_result", "")).upper() == "PASS":
                    legacy_records.append({"model_variant": record.get("source_variant", ""), "screening_result": "PASS", "source_urls": ""})
    return path, {"project":project,"sheet":sheet,"range":cell_range,"row_count":len(data),"input_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"sprint32_pass_records":[r for r in legacy_records if str(r.get("screening_result","")).upper()=="PASS"]}
def _ensure_sheet(service, spreadsheet_id: str, title: str) -> int:
    meta=_retry(lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id,fields="sheets.properties").execute())
    for item in meta.get("sheets",[]):
        if item["properties"]["title"]==title: return int(item["properties"]["sheetId"])
    reply=_retry(lambda: service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id,body={"requests":[{"addSheet":{"properties":{"title":title}}}]}).execute())
    return int(reply["replies"][0]["addSheet"]["properties"]["sheetId"])
def _column_letter(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _write_rows(service, spreadsheet_id: str, title: str, rows: list[list[Any]]) -> dict:
    _ensure_sheet(service,spreadsheet_id,title)
    _retry(lambda: service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id,range=f"'{title}'!A:ZZ",body={}).execute())
    _retry(lambda: service.spreadsheets().values().update(spreadsheetId=spreadsheet_id,range=f"'{title}'!A1",valueInputOption="RAW",body={"values":rows}).execute())
    check=_values(service,spreadsheet_id,title,f"A1:{_column_letter(len(rows[0]))}{len(rows)}"); expected=[list(map(lambda x:"" if x is None else x,row)) for row in rows]; got=[(row+[""]*len(rows[0]))[:len(rows[0])] for row in check]
    def _canonical(value: Any) -> Any:
        if isinstance(value, float) and not math.isfinite(value): return None
        if isinstance(value, dict): return {key: _canonical(item) for key, item in value.items()}
        if isinstance(value, list): return [_canonical(item) for item in value]
        return value
    def _cell_equal(a: Any, b: Any) -> bool:
        if a in (None, "") and b in (None, ""): return True
        if isinstance(a, (int, float, bool)) and isinstance(b, (int, float, bool)):
            if isinstance(a, float) and not math.isfinite(a): a = None
            if isinstance(b, float) and not math.isfinite(b): b = None
            return a == b
        sa, sb = str(a).strip(), str(b).strip()
        if sa == sb: return True
        try:
            return _canonical(json.loads(sa)) == _canonical(json.loads(sb))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
    mismatch = None
    if len(got) != len(expected):
        mismatch = {"expected_rows": len(expected), "got_rows": len(got)}
    else:
        for row_index, (actual_row, expected_row) in enumerate(zip(got, expected)):
            for col_index, (actual, expected_value) in enumerate(zip(actual_row, expected_row)):
                if not _cell_equal(actual, expected_value):
                    mismatch = {"row": row_index, "column": col_index, "actual": repr(actual), "expected": repr(expected_value)}
                    break
            if mismatch: break
    if mismatch:
        raise RuntimeError(f"publication readback failed for {title}: {mismatch}")
    return {"sheet":title,"row_count":len(check),"readback_verified":True}
def _records_rows(records: list[dict]) -> list[list[Any]]:
    if not records: return [["status","no_records"]]
    keys=sorted({key for record in records for key in record})
    return [keys]+[[_sheet_value(record.get(key)) for key in keys] for record in records]
def _sheet_value(value: Any) -> Any:
    if value is None: return None
    if isinstance(value, (list, dict)): return json.dumps(value, separators=(",",":"))
    if isinstance(value, float) and not math.isfinite(value): return None
    return value
def publish_metrics(spreadsheet_id: str, metrics: dict, output_sheet: str = "Sprint 25 Runner Output") -> dict:
    allowed={"Sprint 25 Auth Test","Sprint 25 Runner Output","Sprint 26 Summary"}
    if output_sheet not in allowed: raise ValueError("output tab is not authorized")
    service,_=_service(); now=datetime.now(timezone.utc).isoformat()
    rows=[["execution_id","published_at_utc","metric","value"],*[[metrics.get("execution_id",""),now,k,json.dumps(v,separators=(",",":"))] for k,v in sorted(metrics.items())]]
    result=_write_rows(service,spreadsheet_id,output_sheet,rows); result.update({"status":"VERIFIED","input_sha256":metrics.get("input_sha256")}); return result
def publish_sprint26(spreadsheet_id: str, metrics: dict) -> dict:
    service,_=_service(); now=datetime.now(timezone.utc).isoformat()
    summary=[["execution_id","published_at_utc","metric","value"],*[[metrics.get("execution_id",""),now,k,json.dumps(v,separators=(",",":"))] for k,v in sorted(metrics.items()) if k not in {"valuation_evidence","five_year_forecasts","model_opportunities","individual_purchase_opportunities"}]]
    outputs={"Sprint 26 Summary":summary,"Eligibility Diagnostics":[["reason","count"],*[[k,v] for k,v in sorted(metrics.get("eligibility_reason_counts",{}).items())]],"Valuation Evidence":_records_rows(metrics.get("valuation_evidence",[])),"Five-Year Forecasts":_records_rows(metrics.get("five_year_forecasts",[])),"Model Opportunities":_records_rows(metrics.get("model_opportunities",[])),"Individual Purchase Opportunities":_records_rows(metrics.get("individual_purchase_opportunities",[]))}
    results=[_write_rows(service,spreadsheet_id,title,rows) for title,rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}
def publish_sprint27(spreadsheet_id: str, metrics: dict) -> dict:
    service,_=_service(); now=datetime.now(timezone.utc).isoformat()
    summary=[["execution_id","published_at_utc","metric","value"],*[[metrics.get("execution_id",""),now,k,json.dumps(v,separators=(",",":"))] for k,v in sorted(metrics.items()) if k not in {"valuation_evidence","market_evidence_valuation","historical_returns","model_opportunities","individual_purchase_opportunities"}]]
    outputs={"Sprint 27 Summary":summary,"Eligibility Diagnostics":[["reason","count"],*[[k,v] for k,v in sorted(metrics.get("eligibility_reason_counts",{}).items())]],"Title Evidence":[["population","rows","interpretation"],["historical_market_evidence_unknown_title",metrics.get("historical_market_evidence_unknown_title_rows",0),"descriptive market evidence only; title remains unknown"],["verified_clean_title",metrics.get("verified_clean_title_rows",0),"title status not adverse and not unknown"],["adverse_title_excluded",metrics.get("input_row_count",0)-metrics.get("historical_market_evidence_rows",0),"excluded from market evidence"]],"Variant Crosswalk":_records_rows(metrics.get("variant_crosswalk",[])),"Historical Valuation Reconciliation":_records_rows(metrics.get("valuation_reconciliation",[])),"Valuation Evidence":_records_rows(metrics.get("valuation_evidence",[])),"Historical Returns":_records_rows(metrics.get("historical_returns",[])),"Source Coverage":_records_rows(metrics.get("source_coverage",[])),"Data Quality":_records_rows(metrics.get("clean_title_unassigned_clusters",[]))}
    results=[_write_rows(service,spreadsheet_id,title,rows) for title,rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}
def publish_sprint28(spreadsheet_id: str, metrics: dict) -> dict:
    service,_=_service(); now=datetime.now(timezone.utc).isoformat()
    summary=[["execution_id","published_at_utc","metric","value"],*[[metrics.get("execution_id",""),now,k,json.dumps(v,separators=(",",":"))] for k,v in sorted(metrics.items()) if k not in {"row_audit","historical_endpoint_diagnostics","strict_endpoint_diagnostics","model_opportunities","individual_purchase_opportunities"}]]
    outputs={"Sprint 28 Summary":summary,"Sprint 28 Title Evidence":_records_rows(metrics.get("title_evidence_classification",[])),"Sprint 28 Variant Recovery":_records_rows(metrics.get("variant_recovery_classification",[])),"Sprint 28 Endpoint Diagnostics":_records_rows(metrics.get("historical_endpoint_diagnostics",[])),"Sprint 28 Strict Endpoints":_records_rows(metrics.get("strict_endpoint_diagnostics",[])),"Sprint 28 Legacy Reconciliation":_records_rows(metrics.get("legacy_valuation_reconciliation",[])),"Sprint 28 Source Priority":_records_rows(metrics.get("source_research_priority",[])),"Sprint 28 Quality":_records_rows(metrics.get("deterministic_source_label_clusters",[])),"Sprint 28 Row Audit":_records_rows(metrics.get("row_audit",[]))}
    results=[_write_rows(service,spreadsheet_id,title,rows) for title,rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}
def publish_sprint29(spreadsheet_id: str, metrics: dict) -> dict:
    service,_=_service(); now=datetime.now(timezone.utc).isoformat()
    summary=[["execution_id","published_at_utc","metric","value"],*[[metrics.get("execution_id",""),now,k,json.dumps(v,separators=(",",":"))] for k,v in sorted(metrics.items()) if k not in {"investment_watchlist","model_opportunities","historical_valuations","historical_returns","forecast_scenarios"}]]
    outputs={"Investment Watchlist":_records_rows(metrics.get("investment_watchlist",[])),"Model Opportunities":_records_rows(metrics.get("model_opportunities",[])),"Individual Purchase Opportunities":_records_rows(metrics.get("individual_purchase_opportunities",[])),"Historical Valuations":_records_rows(metrics.get("historical_valuations",[])),"Historical Returns":_records_rows(metrics.get("historical_returns",[])),"Forecast Scenarios":_records_rows(metrics.get("forecast_scenarios",[])),"Research Confidence":_records_rows(metrics.get("title_population",[])),"Data Coverage":_records_rows(metrics.get("data_coverage",[])),"Sprint 29 Summary":summary,"Sprint 29 Legacy Reconciliation":_records_rows(metrics.get("legacy_valuation_reconciliation",[]))}
    results=[_write_rows(service,spreadsheet_id,title,rows) for title,rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}

def _fixed_research_rows(records: list[dict]) -> list[list[Any]]:
    keys=["manufacturer","model","generation","model_variant","screening_result","current_adjusted_value_usd","prior24_adjusted_value_usd","prior60_adjusted_value_usd","return_24m_pct","return_60m_pct","comparable_sale_count","data_confidence","research_priority","evidence_gap","supporting_source_urls"]
    return [keys]+[[_sheet_value(record.get(key)) for key in keys] for record in records] if records else [["status","no_records"]]

def publish_sprint30(spreadsheet_id: str, metrics: dict) -> dict:
    service,_=_service(); now=datetime.now(timezone.utc).isoformat()
    excluded={"qualified_model_opportunities","excluded_model_variants","unverified_research_queue","historical_valuations","historical_returns","forecast_scenarios","watchlist_audit","nsx_investigation"}
    summary=[["execution_id","published_at_utc","metric","value"],*[[metrics.get("execution_id",""),now,k,json.dumps(v,separators=(",",":"))] for k,v in sorted(metrics.items()) if k not in excluded]]
    outputs={"Qualified Model Opportunities":_records_rows(metrics.get("qualified_model_opportunities",[])),
             "Excluded Over 5pct":_records_rows(metrics.get("excluded_model_variants",[])),
             "Unverified Research Queue":_fixed_research_rows(metrics.get("unverified_research_queue",[])),
             "Historical Valuations":_records_rows(metrics.get("historical_valuations",[])),
             "Historical Returns":_records_rows(metrics.get("historical_returns",[])),
             "Five-Year Forecasts":_records_rows(metrics.get("forecast_scenarios",[])),
             "Individual Purchase Opportunities":_records_rows(metrics.get("individual_purchase_opportunities",[])),
             "NSX Investigation":_records_rows(metrics.get("nsx_investigation",[])),
             "11-Entry Screening Audit":_records_rows(metrics.get("watchlist_audit",[])),
             "Data Confidence":_records_rows(metrics.get("title_population",[])),
             "Sprint 30 Summary":summary}
    results=[_write_rows(service,spreadsheet_id,title,rows) for title,rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}


def publish_sprint31(spreadsheet_id: str, metrics: dict) -> dict:
    service, _ = _service(); now = datetime.now(timezone.utc).isoformat()
    excluded = {"historical_valuations", "historical_returns", "nsx_valuation_study", "qualified_model_opportunities", "excluded_over_5pct", "unverified_research_queue", "model_validation"}
    summary = [["execution_id", "published_at_utc", "metric", "value"], *[[metrics.get("execution_id", ""), now, k, json.dumps(v, separators=(",", ":"))] for k, v in sorted(metrics.items()) if k not in excluded]]
    outputs = {
        "Sprint 31 Summary": summary,
        "Standardized Historical Valuations": _records_rows(metrics.get("historical_valuations", [])),
        "Adjusted 24-Month Returns": _records_rows(metrics.get("historical_returns", [])),
        "Adjusted 60-Month Returns": _records_rows([r for r in metrics.get("historical_returns", []) if r.get("return_60m_pct") is not None]),
        "Qualified Model Opportunities": _records_rows(metrics.get("qualified_model_opportunities", [])),
        "Excluded Over 5pct": _records_rows(metrics.get("excluded_over_5pct", [])),
        "Unverified Research Queue": _records_rows(metrics.get("unverified_research_queue", [])),
        "NSX Valuation Study": _records_rows(metrics.get("nsx_valuation_study", [])),
        "Model Validation": _records_rows(metrics.get("model_validation", {}).get("folds", [])),
        "Data Confidence": _records_rows([metrics.get("model_metadata", {})]),
    }
    results = [_write_rows(service, spreadsheet_id, title, rows) for title, rows in outputs.items()]
    return {"status": "VERIFIED", "tabs": results, "input_sha256": metrics.get("input_sha256"), "readback_verified": all(x["readback_verified"] for x in results)}


def publish_sprint34(spreadsheet_id: str, metrics: dict) -> dict:
    service, _ = _service()
    summary_keys = [
        "status", "execution_scope", "analysis_date", "input_row_count",
        "input_sha256", "usable_manufacturer", "usable_model",
        "verified_canonical_variants", "high_confidence_inferred_variants",
        "provisional_variants", "unclassified_rows", "duplicate_rows_flagged",
        "repeat_sale_observations", "mileage_complete", "vin_complete",
        "eligible_identity_rows", "vertical_slice_rows", "vertical_slice_variants",
        "validated_pass_records", "provisional_research_records",
        "individual_purchase_opportunities", "historical_gate_status",
        "raw_titles_present", "raw_descriptions_present",
    ]
    summary = {key: metrics.get(key) for key in summary_keys}
    slice_keys = [
        "transaction_id", "source_url", "observed_variant_id",
        "canonical_variant_id", "classification", "classification_confidence",
        "inferred_manufacturer", "inferred_model", "inferred_generation",
        "inferred_model_year", "inferred_engine", "inferred_transmission",
        "identity_quality_gate", "derivation_method",
    ]
    slice_rows = [[key for key in slice_keys]]
    slice_rows.extend([[_sheet_value(record.get(key)) for key in slice_keys] for record in metrics.get("vertical_slice", [])])
    outputs = {
        "Sprint 34 Summary": _records_rows([summary]),
        "Canonical Variant Coverage": _records_rows([summary]),
        "Classification Review Queue": slice_rows if len(slice_rows) > 1 else [["status", "no_vertical_slice_rows"]],
        "Data Quality Audit": _records_rows([summary]),
        "Source Lineage": [["field", "status"], ["source", "Google Sheets Auction Transactions"], ["raw_listing_title", "not_present_in_43_column_contract"], ["raw_description", "not_present_in_43_column_contract"], ["source_url", "present"], ["vin", "present_where_captured"], ["mileage", "present_where_captured"]],
        "Individual Purchase Opportunities": [["status", "none"], ["reason", "vehicle-specific diligence and adjusted purchase valuation not completed"]],
    }
    results = [_write_rows(service, spreadsheet_id, title, rows) for title, rows in outputs.items()]
    return {"status": "VERIFIED", "tabs": results, "readback_verified": all(x["readback_verified"] for x in results), "input_sha256": metrics.get("input_sha256")}

def publish_sprint32(spreadsheet_id: str, metrics: dict) -> dict:
    service, _ = _service(); now = datetime.now(timezone.utc).isoformat()
    excluded = {"historical_valuations", "historical_returns", "nsx_valuation_study", "qualified_model_opportunities", "excluded_over_5pct", "unverified_research_queue", "model_validation", "data_coverage"}
    summary = [["execution_id", "published_at_utc", "metric", "value"], *[
        [metrics.get("execution_id", ""), now, k, json.dumps(v, separators=(",", ":"))]
        for k, v in sorted(metrics.items()) if k not in excluded]]
    outputs = {
        "Investment Dashboard": summary,
        "Qualified Model Opportunities": _records_rows(metrics.get("qualified_model_opportunities", [])),
        "Individual Purchase Opportunities": _records_rows(metrics.get("individual_purchase_opportunities", [])),
        "Excluded Over 5pct": _records_rows(metrics.get("excluded_over_5pct", [])),
        "Unverified Research Queue": _records_rows(metrics.get("unverified_research_queue", [])),
        "Historical Valuations": _records_rows(metrics.get("historical_valuations", [])),
        "Adjusted 24-Month Returns": _records_rows([r for r in metrics.get("historical_returns", []) if r.get("return_24m_pct") is not None]),
        "Adjusted 60-Month Returns": _records_rows([r for r in metrics.get("historical_returns", []) if r.get("return_60m_pct") is not None]),
        "NSX Valuation Study": _records_rows(metrics.get("nsx_valuation_study", [])),
        "Comparable Sales": _records_rows(metrics.get("historical_valuations", [])),
        "Model Backtesting": _records_rows(metrics.get("model_validation", {}).get("folds", [])),
        "Data Coverage": _records_rows([metrics.get("data_coverage", {})]),
        "Research Confidence": _records_rows([metrics.get("model_metadata", {})]),
    }
    results = [_write_rows(service, spreadsheet_id, title, rows) for title, rows in outputs.items()]
    return {"status": "VERIFIED", "tabs": results, "input_sha256": metrics.get("input_sha256"), "readback_verified": all(x["readback_verified"] for x in results)}


def publish_sprint35(spreadsheet_id: str, metrics: dict) -> dict:
    outputs = {
        "Sprint 35 Summary": [["metric","value"], *[[k, _sheet_value(metrics.get(k))] for k in sorted(metrics) if not isinstance(metrics.get(k), (list, dict))]],
        "VIN Quality Audit": _records_rows([metrics.get("vin_quality_audit", {})]),
        "VIN Decode Coverage": _records_rows([metrics.get("vin_decode_coverage", {})]),
        "Canonical Variant Coverage": _records_rows([{"verified_canonical_variants": metrics.get("verified_canonical_variants"), "usable_manufacturer": metrics.get("usable_manufacturer"), "usable_model": metrics.get("usable_model"), "identity_quality_eligible_rows": metrics.get("identity_quality_eligible_rows")}]),
        "Identity Conflicts": _records_rows(metrics.get("identity_conflicts", [])),
        "Sprint 32 PASS Crosswalk": _records_rows(metrics.get("sprint32_pass_crosswalk", [])),
        "Historical Valuations": _records_rows(metrics.get("historical_valuations", [])),
        "Adjusted 24-Month Returns": _records_rows([r for r in metrics.get("historical_returns", []) if r.get("return_24m_pct") is not None]),
        "Adjusted 60-Month Returns": _records_rows([r for r in metrics.get("historical_returns", []) if r.get("return_60m_pct") is not None]),
        "Qualified Model Opportunities": _records_rows(metrics.get("qualified_model_opportunities", [])),
        "Unverified Research Queue": _records_rows(metrics.get("provisional_research_queue", [])),
        "Individual Purchase Opportunities": _records_rows(metrics.get("individual_purchase_opportunities", [])),
        "Investment Dashboard": [["metric","value"],["execution_scope",metrics.get("execution_scope")],["status",metrics.get("status")],["validated_24_month_returns",metrics.get("validated_24_month_returns",0)],["validated_60_month_returns",metrics.get("validated_60_month_returns",0)],["ranking_status",metrics.get("ranking_status")]],
    }
    results = [_write_rows(_service()[0], spreadsheet_id, title, rows) for title, rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}
