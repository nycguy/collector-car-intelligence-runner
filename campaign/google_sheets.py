from __future__ import annotations
import csv, hashlib, json, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TRANSACTION_COLUMNS = ["transaction_id","listing_id","physical_vehicle_id","vehicle_variant_id","source_id","source_name","source_url","auction_start_date","auction_end_date","sale_status","sale_price","currency","buyer_premium_included","price_usd","mileage_at_sale","condition_grade","title_status"]

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

def retrieve_transactions(spreadsheet_id: str, sheet: str = "Auction Transactions", cell_range: str = "A1:Q28059") -> tuple[Path, dict]:
    service, project = _service()
    rows = _values(service, spreadsheet_id, sheet, cell_range)
    if not rows or rows[0][:len(TRANSACTION_COLUMNS)] != TRANSACTION_COLUMNS:
        raise ValueError("production sheet schema does not match the approved transaction contract")
    data = rows[1:]
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
            writer.writerow(dict(zip(TRANSACTION_COLUMNS, padded[:len(TRANSACTION_COLUMNS)]))))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, {"project": project, "sheet": sheet, "range": cell_range, "row_count": len(data), "input_sha256": digest}

def _ensure_sheet(service, spreadsheet_id: str, title: str) -> int:
    meta = _retry(lambda: service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute())
    for item in meta.get("sheets", []):
        if item["properties"]["title"] == title:
            return int(item["properties"]["sheetId"])
    reply = _retry(lambda: service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests":[{"addSheet":{"properties":{"title":title}}}]}).execute())
    return int(reply["replies"][0]["addSheet"]["properties"]["sheetId"])

def publish_metrics(spreadsheet_id: str, metrics: dict, output_sheet: str = "Sprint 25 Runner Output") -> dict:
    service, _ = _service()
    _ensure_sheet(service, spreadsheet_id, output_sheet)
    now = datetime.now(timezone.utc).isoformat()
    rows = [["execution_id","published_at_utc","metric","value"], *[[metrics.get("execution_id",""),now,k,json.dumps(v, separators=(",",":"))] for k,v in sorted(metrics.items())]]
    _retry(lambda: service.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=f"'{output_sheet}'!A1", valueInputOption="RAW", body={"values":rows}).execute())
    check = _values(service, spreadsheet_id, output_sheet, f"A1:D{len(rows)}")
    expected_hash = json.dumps(metrics.get("input_sha256"), separators=(",",":"))
    hash_rows = [row for row in check[1:] if len(row) >= 4 and row[2] == "input_sha256"]
    if len(check) != len(rows) or check[0] != rows[0] or check[1][0] != metrics.get("execution_id","") or not hash_rows or hash_rows[0][3] != expected_hash:
        raise RuntimeError("publication readback failed")
    return {"status":"VERIFIED","sheet":output_sheet,"row_count":len(check),"input_sha256":metrics.get("input_sha256"),"readback_verified":True}
