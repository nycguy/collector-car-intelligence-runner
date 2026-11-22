import csv
import json
import tempfile
import unittest
from pathlib import Path
from campaign.executor import execute, REQUIRED_COLUMNS
from campaign.controller import next_sprint, validate_continuation
from campaign.safety import disclosure_scan


def row(identifier, date, price, **changes):
    item = dict.fromkeys(REQUIRED_COLUMNS, '')
    item.update(transaction_id=identifier, vehicle_variant_id='synthetic_variant',
                source_id='test', auction_end_date=date, sale_status='sold',
                price_usd=str(price), title_status='clean', exclusion_flag='FALSE',
                variant_normalization_status='mapped_explicit_variant_alias')
    item.update(changes)
    return item


class RunnerTests(unittest.TestCase):
    def run_rows(self, rows):
        with tempfile.TemporaryDirectory() as folder:
            src = Path(folder)/'input.csv'
            with src.open('w', newline='') as handle:
                writer=csv.DictWriter(handle,fieldnames=sorted(REQUIRED_COLUMNS))
                writer.writeheader()
                writer.writerows(rows)
            result=execute(str(src), str(Path(folder)/'out'), 'synthetic-test')
            artifact=(Path(folder)/'out'/'metrics.json').read_text()
            self.assertNotIn('synthetic_variant', artifact)
            self.assertNotIn('private-test-id', artifact)
            return result

    def test_existing_engine_computes_endpoint_returns_without_qualifying(self):
        rows=[row(f'private-test-id-now{i}','2026-08-01',104) for i in range(5)]
        rows += [row(f'old{i}','2024-08-01',100) for i in range(5)]
        rows += [row(f'older{i}','2021-08-01',120) for i in range(5)]
        result=self.run_rows(rows)
        self.assertEqual(result['exploratory_unadjusted_counts'],
                         {'current':1,'24m':1,'60m':1,'historical_screen':1})
        self.assertTrue(result['valuation_engine_executed'])
        self.assertFalse(result['analytical_acceptance'])
        self.assertEqual(result['supported_24m_returns'],1)
        self.assertEqual(result['qualified_model_opportunities'],0)

    def test_five_percent_limit_is_not_relaxed(self):
        rows=[row(f'n{i}','2026-08-01',106) for i in range(5)]
        rows += [row(f'o{i}','2024-08-01',100) for i in range(5)]
        self.assertEqual(self.run_rows(rows)['exploratory_unadjusted_counts']['historical_screen'],0)

    def test_exclusions_future_dates_and_unknown_mapping_remain_quarantined(self):
        changes=[{'title_status':'unknown'}, {'title_status':'rebuilt'},
                 {'title_status':'clean; salvage history'}, {'exclusion_flag':'TRUE'},
                 {'variant_normalization_status':'provisional'},
                 {'variant_normalization_status':'mapped_make_model_year'},
                 {'vehicle_variant_id':''}, {'auction_end_date':'2027-01-01'},
                 {'auction_end_date':'bad'}, {'sale_status':'unsold'}, {'price_usd':'inf'}]
        result=self.run_rows([row(str(i),'2026-08-01',100,**change) for i,change in enumerate(changes)])
        self.assertEqual(result['comparable_eligible_rows'],1)
        self.assertEqual(result['valuation_cohort_rows'],1)

    def test_duplicates_fail_closed(self):
        with self.assertRaises(ValueError):
            self.run_rows([row('same','2026-08-01',100)]*2)

    def test_controller_rejects_count_only_or_auth_only_success(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'state.json'
            p.write_text(json.dumps({'state':'BLOCKED','latest_completed_sprint':23}))
            self.assertIsNone(next_sprint(str(p)))
        metrics={'status':'SUCCEEDED','raw_rows_written_to_artifacts':False,
                 'publication':{'readback_verified':True}}
        self.assertFalse(validate_continuation(metrics,'VERIFIED')[0])
        metrics.update(valuation_engine_executed=True, analytical_acceptance=True)
        self.assertTrue(validate_continuation(metrics,'VERIFIED')[0])

    def test_disclosure_scan(self):
        self.assertEqual(disclosure_scan('.'),[])
