from __future__ import annotations
import csv, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
REQUIRED_COLUMNS={"transaction_id","vehicle_variant_id","source_id","auction_end_date","sale_status","price_usd","title_status"}
EXCLUDED_TITLES={"salvage","rebuilt","flood","total_loss","total-loss"}
def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def execute(input_path:str,output_dir:str,snapshot_id:str)->dict:
    source=Path(input_path); out=Path(output_dir)
    if not source.is_file(): raise FileNotFoundError(f"authorized snapshot not found: {source}")
    with source.open(newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f); missing=sorted(REQUIRED_COLUMNS-set(reader.fieldnames or []))
        if missing: raise ValueError(f"snapshot missing required columns: {missing}")
        rows=list(reader)
    if not rows: raise ValueError("snapshot contains no rows")
    ids=[r["transaction_id"].strip() for r in rows]
    if any(not x for x in ids): raise ValueError("blank transaction_id detected")
    if len(ids)!=len(set(ids)): raise ValueError("duplicate transaction_id detected")
    eligible=[r for r in rows if r["sale_status"].strip().lower() in {"sold","completed"}]
    title_clean=[r for r in eligible if r["title_status"].strip().lower() not in EXCLUDED_TITLES]
    canonical=[r for r in title_clean if r["vehicle_variant_id"].strip()]
    metrics={"status":"SUCCEEDED","snapshot_id":snapshot_id,"extracted_at_utc":datetime.now(timezone.utc).isoformat(),"input_row_count":len(rows),"completed_sale_rows":len(eligible),"title_eligible_rows":len(title_clean),"canonical_assignment_rows":len(canonical),"provisional_or_noncanonical_rows":len(title_clean)-len(canonical),"supported_current_valuations":0,"supported_24m_returns":0,"supported_60m_returns":0,"qualified_model_opportunities":0,"backtested_cohorts":0,"input_sha256":sha256_file(source),"raw_rows_written_to_artifacts":False}
    out.mkdir(parents=True,exist_ok=True)
    (out/"metrics.json").write_text(json.dumps(metrics,indent=2)+"\n",encoding="utf-8")
    (out/"publication_status.json").write_text(json.dumps({"status":"NOT_CONFIGURED","reason":"Publication identity must be provisioned outside the public repository.","raw_data_published":False},indent=2)+"\n",encoding="utf-8")
    return metrics
