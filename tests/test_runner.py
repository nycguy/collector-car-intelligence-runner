import csv,json,tempfile,unittest
from pathlib import Path
from campaign.executor import execute
from campaign.controller import next_sprint,validate_continuation
from campaign.safety import disclosure_scan
FIELDS=["transaction_id","vehicle_variant_id","source_id","auction_end_date","sale_status","price_usd","title_status"]
class RunnerTests(unittest.TestCase):
 def test_aggregate_execution(self):
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/"input.csv"; out=Path(d)/"out"
   with src.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=FIELDS); w.writeheader(); w.writerow(dict(zip(FIELDS,["t1","v1","s1","2024-01-01","sold","10000","clean"]))); w.writerow(dict(zip(FIELDS,["t2","","s1","2024-01-02","sold","9000","clean"])))
   m=execute(str(src),str(out),"test-snapshot")
   self.assertEqual(m["input_row_count"],2); self.assertEqual(m["canonical_assignment_rows"],1); self.assertFalse(m["raw_rows_written_to_artifacts"])
 def test_controller_gates(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"state.json"; p.write_text(json.dumps({"state":"BLOCKED","latest_completed_sprint":23})); self.assertIsNone(next_sprint(str(p)))
  self.assertTrue(validate_continuation({"status":"SUCCEEDED","raw_rows_written_to_artifacts":False},"VERIFIED")[0])
 def test_disclosure_scan(self): self.assertEqual(disclosure_scan("."),[])
if __name__=="__main__": unittest.main()
