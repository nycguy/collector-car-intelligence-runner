import json
from pathlib import Path
def next_sprint(state_path:str):
    state=json.loads(Path(state_path).read_text(encoding="utf-8"))
    if state.get("state")=="BLOCKED": return None
    latest=int(state.get("latest_completed_sprint",23))
    return latest+1 if latest<32 else None
def validate_continuation(metrics:dict,publication_status:str):
    if metrics.get("status")!="SUCCEEDED": return False,"execution did not succeed"
    if metrics.get("raw_rows_written_to_artifacts"): return False,"raw rows would be exposed"
    if publication_status!="VERIFIED": return False,"publication identity/readback not verified"
    return True,"continuation prerequisites satisfied"
