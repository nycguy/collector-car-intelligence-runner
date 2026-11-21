import unittest
from unittest.mock import patch
from campaign.google_sheets import TRANSACTION_COLUMNS

class SheetsContractTests(unittest.TestCase):
    def test_contract_is_explicit_and_minimal(self):
        self.assertEqual(TRANSACTION_COLUMNS[0], "transaction_id")
        self.assertIn("title_status", TRANSACTION_COLUMNS)
        self.assertEqual(len(TRANSACTION_COLUMNS), 17)

    @patch("campaign.google_sheets._service")
    def test_schema_rejects_wrong_header(self, factory):
        class Values:
            def get(self, **kwargs): return self
            def execute(self): return {"values": [["wrong"]]}
        class Sheets:
            def values(self): return Values()
        class Service:
            def spreadsheets(self): return Sheets()
        factory.return_value = (Service(), "project")
        from campaign.google_sheets import retrieve_transactions
        with self.assertRaises(ValueError):
            retrieve_transactions("id")

if __name__ == "__main__":
    unittest.main()
