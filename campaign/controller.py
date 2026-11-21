import json
from pathlib import Path


def next_sprint(state_path: str):
    state = json.loads(Path(state_path).read_text())
    if state.get('state') == 'BLOCKED':
        return None
    latest = int(state.get('latest_completed_sprint', 23))
    return latest + 1 if latest < 32 else None


def validate_continuation(metrics: dict, publication_status: str):
    if metrics.get('status') != 'SUCCEEDED':
        return False, 'execution did not succeed'
    if metrics.get('raw_rows_written_to_artifacts') is not False:
        return False, 'private-data protection not verified'
    if publication_status != 'VERIFIED' or metrics.get('publication', {}).get('readback_verified') is not True:
        return False, 'publication readback not verified'
    if metrics.get('valuation_engine_executed') is not True or metrics.get('analytical_acceptance') is not True:
        return False, 'full analytical acceptance not demonstrated'
    return True, 'continuation prerequisites satisfied'
