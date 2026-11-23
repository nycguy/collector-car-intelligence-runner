import tempfile
import unittest
from pathlib import Path
import pandas as pd
from campaign.analysis.sprint35 import normalize_vin, check_digit_valid, audit_vins, reconstruct_valuations

class Sprint35VinTests(unittest.TestCase):
    def test_normalization_and_check_digit(self):
        self.assertEqual(normalize_vin(" jh4-na1151-nt000919 "), "JH4NA1151NT000919")
        self.assertIs(check_digit_valid("JH4NA1151NT000919"), True)
        self.assertIs(check_digit_valid("JH4NA1151NT000918"), False)
        self.assertIsNone(check_digit_valid("ABC123"))

    def test_audit_preserves_repeats(self):
        frame = pd.DataFrame({"vin":["JH4NA1151NT000919","JH4NA1151NT000919","ABC123"],"vehicle_variant_id":["a","b","a"]})
        audit = audit_vins(frame)
        self.assertEqual(audit["vin_populated_records"], 3)
        self.assertEqual(audit["unique_vins"], 2)
        self.assertEqual(audit["duplicate_vin_values"], 1)
        self.assertEqual(audit["repeated_vins_with_conflicting_source_labels"], 1)

    def test_valuation_gate_requires_three_supported_endpoints(self):
        rows=[]
        for date, price in [("2021-11-20",100),("2024-11-20",90),("2026-11-20",90)]:
            for i in range(5):
                rows.append({"canonical_variant_id":"x","identity_quality_gate":"ELIGIBLE","sale_status":"sold","auction_end_date":date,"price_usd":price})
        result=reconstruct_valuations(pd.DataFrame(rows))
        self.assertEqual(result[0]["screening_result"], "PASS")
        self.assertEqual(result[0]["return_24m_pct"], 0)

if __name__ == "__main__":
    unittest.main()
