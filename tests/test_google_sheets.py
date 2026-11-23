import copy
import unittest
from unittest.mock import patch
from campaign.google_sheets import TRANSACTION_COLUMNS, retrieve_transactions, publish_metrics


class FakeService:
    def __init__(self, rows=None, corrupt=False):
        self.rows=rows
        self.corrupt=corrupt
        self.range=None
        self.ranges=[]
    def spreadsheets(self): return self
    def values(self): return self
    def get(self, **kwargs):
        self.range=kwargs.get('range')
        self.ranges.append(self.range)
        return self
    def clear(self, **kwargs):
        self.rows=[]
        return self
    def update(self, **kwargs):
        self.rows=copy.deepcopy(kwargs['body']['values'])
        if self.corrupt:
            self.rows[-1][-1]='tampered'
        return self
    def execute(self):
        if self.range is None:
            return {'sheets':[{'properties':{'title':'Sprint 25 Auth Test','sheetId':1}}]}
        return {'values':self.rows}


class SheetsContractTests(unittest.TestCase):
    def test_contract_retains_exclusion_and_normalization_fields(self):
        self.assertEqual(len(TRANSACTION_COLUMNS),43)
        for name in ('title_status','exclusion_flag','variant_normalization_status'):
            self.assertIn(name,TRANSACTION_COLUMNS)

    def test_schema_and_unexpected_population_fail_closed(self):
        for rows in ([['wrong']], [TRANSACTION_COLUMNS],
                     [TRANSACTION_COLUMNS]+[['synthetic']]*28059):
            with patch('campaign.google_sheets._service',return_value=(FakeService(rows),'test-project')):
                with self.assertRaises(ValueError):
                    retrieve_transactions('test')

    def test_retrieval_checks_open_ended_range_and_fingerprint(self):
        service=FakeService([TRANSACTION_COLUMNS]+[['synthetic']]*28058)
        with patch('campaign.google_sheets._service',return_value=(service,'test-project')):
            path,evidence=retrieve_transactions('test')
            try:
                self.assertIn("'Auction Transactions'!A1:AQ",service.ranges)
                self.assertEqual(evidence['row_count'],28058)
                self.assertEqual(len(evidence['input_sha256']),64)
            finally:
                path.unlink()

    def test_every_published_value_is_verified(self):
        metrics={'execution_id':'test','input_sha256':'abc','z_metric':1}
        for corrupt in (False,True):
            with patch('campaign.google_sheets._service',return_value=(FakeService(corrupt=corrupt),'test-project')):
                if corrupt:
                    with self.assertRaises(RuntimeError):
                        publish_metrics('test',metrics,'Sprint 25 Auth Test')
                else:
                    self.assertTrue(publish_metrics('test',metrics,'Sprint 25 Auth Test')['readback_verified'])

    def test_raw_tab_cannot_be_publication_target(self):
        with self.assertRaises(ValueError):
            publish_metrics('test',{},'Auction Transactions')
