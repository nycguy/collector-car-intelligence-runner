from __future__ import annotations
import csv, hashlib, json, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TRANSACTION_COLUMNS = ['transaction_id', 'listing_id', 'physical_vehicle_id', 'vehicle_variant_id', 'source_id', 'source_name', 'source_url', 'auction_start_date', 'auction_end_date', 'sale_status', 'sale_price', 'currency', 'buyer_premium_included', 'price_usd', 'mileage_at_sale', 'condition_grade', 'title_status', 'location', 'seller_type', 'evidence_url', 'evidence_capture_date', 'data_quality_score', 'duplicate_group_id', 'repeat_sale_group_id', 'exclusion_flag', 'exclusion_reason', 'notes', 'legacy_transaction_id', 'legacy_listing_id', 'source_title_status_assertion', 'title_evidence_status', 'source_outcome_assertion', 'outcome_verification_status', 'data_use_status', 'identity_method', 'vin', 'physical_identity_status', 'source_variant_id', 'variant_normalization_status', 'investment_eligibility_status', 'reconciliation_status', 'legacy_duplicate_group_id', 'source_data_quality_score_assertion']

def _retry(operation: Callable[[], Any], attempts: int = 3) -> Any:
    last = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Google Sheets operation failed after {attempts} attempts") from last

def _service():
    from googleapiclient.discovery import build
    import google.auth
    credentials, project = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets", "v4", credentials=credentials, cache_discovery=False), project

def _values(service, spreadsheet_id: str, sheet: str, cell_range: str) -> list[list[Any]]:
    result = _retry(lambda: service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{sheet}'!{cell_range}", valueRenderOption="UNFORMATTED_VALUE").execute())
    return result.get("values", [])

def retrieve_transactions(spreadsheet_id: str, sheet: str = "Auction Transactions", cell_range: str = "A1:AQ") -> tuple[Path, dict]:
    service, project = _service()
    rows = _values(service, spreadsheet_id, sheet, cell_range)
    if not rows or rows[0] != TRANSACTION_COLUMNS:
        raise ValueError("production sheet schema does not match the approved transaction contract")
    data = rows[1:]
    if any(len(row) > len(TRANSACTION_COLUMNS) for row in data):
        raise ValueError("production row exceeds schema width")
    if len(data) != 28058:
        raise ValueError(f"unexpected production row count: {len(data)}")
    fd, name = tempfile.mkstemp(prefix="cci-production-", suffix=".csv")
    os.close(fd)
    path = Path(name)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRANSACTION_COLUMNS)
        writer.writeheader()
        for row in data:
            padded = list(row) + [""] * (len(TRANSACTION_COLUMNS) - len(row))
            writer.writerow(dict(zip(TRANSACTION_COLUMNS, padded[:len(TRANSACTION_COLUMNS)])))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, {"project": project, "sheet": sheet, "range": cell_range, "row_count": len(data), "input_sha256": digest}

def _ensure_sheet(service, spreadsheet_id: str, title: str) -> int:
    meta = _retry(lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute())
    for item in meta.get("sheets", []):
        if item["properties"]["title"] == title:
            return int(item["properties"]["sheetId"])
    reply = _retry(lambda: service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests":[{"addSheet":{"properties":{"title":title}}}]}).execute())
    return int(reply["replies"][0]["addSheet"]["properties"]["sheetId"])

def _write_rows(service, spreadsheet_id: str, title: str, rows: list[list[Any]]) -> dict:
    _ensure_sheet(service, spreadsheet_id, title)
    _retry(lambda: service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range=f"'{title}'!A:Z", body={}).execute())
    _retry(lambda: service.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=f"'{title}'!A1", valueInputOption="RAW", body={"values": rows}).execute())
    check = _values(service, spreadsheet_id, title, f"A1:Z{len(rows)}")
    expected = [list(map(lambda x: "" if x is None else x, row)) for row in rows]
    got = [row[:len(rows[0])] for row in check]
    if got != expected:
        raise RuntimeError(f"publication readback failed for {title}")
    return {"sheet": title, "row_count": len(check), "readback_verified": True}

def publish_metrics(spreadsheet_id: str, metrics: dict, output_sheet: str = "Sprint 25 Runner Output") -> dict:
    allowed = {"Sprint 25 Auth Test", "Sprint 25 Runner Output", "Sprint 26 Summary"}
    if output_sheet not in allowed:
        raise ValueError("output tab is not authorized")
    service, _ = _service()
    now = datetime.now(timezone.utc).isoformat()
    rows = [["execution_id","published_at_utc","metric","value"], *[[metrics.get("execution_id",""),now,k,json.dumps(v, separators=(",",":"))] for k,v in sorted(metrics.items())]]
    result = _write_rows(service, spreadsheet_id, output_sheet, rows)
    result.update({"status":"VERIFIED","input_sha256":metrics.get("input_sha256")})
    return result

def publish_sprint26(spreadsheet_id: str, metrics: dict) -> dict:
    service, _ = _service()
    now = datetime.now(timezone.utc).isoformat()
    summary_rows = [["execution_id","published_at_utc","metric","value"], *[[metrics.get("execution_id",""),now,k,json.dumps(v, separators=(",",":"))] for k,v in sorted(metrics.items()) if k not in {"valuation_evidence","five_year_forecasts","model_opportunities","individual_purchase_opportunities"}]]
    outputs = {"Sprint 26 Summary": summary_rows}
    outputs["Eligibility Diagnostics"] = [["reason","count"], *[[k,v] for k,v in sorted(metrics.get("eligibility_reason_counts", {}).items())]]
    outputs["Valuation Evidence"] = _records_rows(metrics.get("valuation_evidence", []))
    outputs["Five-Year Forecasts"] = _records_rows(metrics.get("five_year_forecasts", []))
    outputs["Model Opportunities"] = _records_rows(metrics.get("model_opportunities", []))
    outputs["Individual Purchase Opportunities"] = _records_rows(metrics.get("individual_purchase_opportunities", []))
    results = [_write_rows(service, spreadsheet_id, title, rows) for title, rows in outputs.items()]
    return {"status":"VERIFIED","tabs":results,"input_sha256":metrics.get("input_sha256"),"readback_verified":all(x["readback_verified"] for x in results)}

def _records_rows(records: list[dict]) -> list[list[Any]]:
    if not records:
        return [["status","no_records"]]
    keys = sorted({key for record in records for key in record})
    return [keys] + [[record.get(key) for key in keys] for record in records]
