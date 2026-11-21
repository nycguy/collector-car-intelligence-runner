from __future__ import annotations
import json, os
from pathlib import Path
from .executor import execute
from .google_sheets import retrieve_transactions, publish_metrics

def run() -> dict:
    spreadsheet_id = os.environ["CCI_SPREADSHEET_ID"]
    snapshot_id = os.environ.get("CCI_SNAPSHOT_ID") or f"github-actions-{os.environ.get('GITHUB_RUN_ID','local')}"
    output_dir = os.environ.get("CCI_OUTPUT_DIR", "run-output")
    input_path, evidence = retrieve_transactions(
        spreadsheet_id,
        os.environ.get("CCI_TRANSACTION_SHEET", "Auction Transactions"),
        os.environ.get("CCI_TRANSACTION_RANGE", "A1:Q28059"),
    )
    try:
        metrics = execute(str(input_path), output_dir, snapshot_id)
        metrics.update({
            "execution_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "input_snapshot_id": snapshot_id,
            "production_source": "google-sheets",
            "input_row_count": evidence["row_count"],
            "input_sha256": evidence["input_sha256"],
        })
        publication = publish_metrics(spreadsheet_id, metrics, os.environ.get("CCI_OUTPUT_SHEET", "Sprint 25 Runner Output"))
        metrics["publication"] = publication
        Path(output_dir).mkdir(exist_ok=True)
        Path(output_dir, "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        return metrics
    finally:
        input_path.unlink(missing_ok=True)

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
