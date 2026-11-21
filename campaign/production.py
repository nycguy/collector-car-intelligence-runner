from __future__ import annotations
import json
import os
import time
from pathlib import Path
from .executor import execute
from .google_sheets import retrieve_transactions, publish_metrics


def run() -> dict:
    started = time.monotonic()
    spreadsheet_id = os.environ['CCI_SPREADSHEET_ID']
    mode = os.environ.get('CCI_MODE', 'auth-test')
    if mode not in {'auth-test', 'production'}:
        raise ValueError('unsupported execution mode')
    snapshot_id = os.environ.get('CCI_SNAPSHOT_ID') or f"github-actions-{os.environ.get('GITHUB_RUN_ID','local')}"
    output_dir = Path(os.environ.get('CCI_OUTPUT_DIR', 'run-output'))
    input_path, evidence = retrieve_transactions(spreadsheet_id)
    try:
        metrics = ({'status':'SUCCEEDED', 'execution_scope':'authentication_test',
                    'valuation_engine_executed':False, 'analytical_acceptance':False,
                    'raw_rows_written_to_artifacts':False} if mode == 'auth-test' else
                   execute(str(input_path), str(output_dir), snapshot_id,
                           os.environ.get('CCI_ANALYSIS_DATE', '2026-11-20')))
        metrics.update({
            'execution_id':os.environ.get('GITHUB_RUN_ID','local'),
            'commit_sha':os.environ.get('GITHUB_SHA'),
            'run_url':f"https://github.com/{os.environ.get('GITHUB_REPOSITORY','nycguy/collector-car-intelligence-runner')}/actions/runs/{os.environ.get('GITHUB_RUN_ID','local')}",
            'input_snapshot_id':snapshot_id, 'production_source':'google-sheets',
            'input_row_count':evidence['row_count'], 'input_sha256':evidence['input_sha256'],
            'google_cloud_project':evidence['project'],
            'service_account':os.environ.get('CCI_SERVICE_ACCOUNT'),
            'workload_identity_provider':os.environ.get('CCI_IDENTITY_PROVIDER'),
        })
        title = 'Sprint 25 Auth Test' if mode == 'auth-test' else 'Sprint 25 Runner Output'
        publication = publish_metrics(spreadsheet_id, metrics, title)
        metrics['publication'] = publication
        metrics['execution_duration_seconds'] = round(time.monotonic() - started, 3)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
        (output_dir / 'publication_status.json').write_text(json.dumps(publication, indent=2) + '\n')
        return metrics
    finally:
        input_path.unlink(missing_ok=True)


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
