import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campaign.production import run


class ProductionTests(unittest.TestCase):
    def test_auth_test_reads_writes_readback_and_removes_input_without_valuation(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'private.csv'
            source.write_text('private input')
            env={'CCI_SPREADSHEET_ID':'test','CCI_MODE':'auth-test',
                 'CCI_OUTPUT_DIR':folder,'GITHUB_RUN_ID':'123'}
            evidence={'row_count':28058,'input_sha256':'abc','project':'test-project'}
            with patch.dict('os.environ',env), \
                 patch('campaign.production.retrieve_transactions',return_value=(source,evidence)), \
                 patch('campaign.production.execute') as engine, \
                 patch('campaign.production.publish_metrics',return_value={'status':'VERIFIED','readback_verified':True}) as publish:
                result=run()
                engine.assert_not_called()
                self.assertEqual(publish.call_args.args[2],'Sprint 25 Auth Test')
                self.assertFalse(source.exists())
                self.assertFalse(result['analytical_acceptance'])
                self.assertTrue(json.loads((Path(folder)/'publication_status.json').read_text())['readback_verified'])

    def test_input_removed_on_publication_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'private.csv'
            source.write_text('private input')
            with patch.dict('os.environ',{'CCI_SPREADSHEET_ID':'test','CCI_MODE':'auth-test','CCI_OUTPUT_DIR':folder}), \
                 patch('campaign.production.retrieve_transactions',return_value=(source,{'row_count':28058,'input_sha256':'abc','project':'test'})), \
                 patch('campaign.production.publish_metrics',side_effect=RuntimeError('readback failed')):
                with self.assertRaises(RuntimeError): run()
                self.assertFalse(source.exists())
