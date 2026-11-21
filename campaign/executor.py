"""Run the existing valuation engine without publishing private observations."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .analysis.sprint22 import reconcile_transactions, valuation_rebuild, backtest_status

REQUIRED_COLUMNS = {
    'transaction_id', 'vehicle_variant_id', 'source_id', 'auction_end_date',
    'sale_status', 'price_usd', 'title_status', 'exclusion_flag',
    'variant_normalization_status',
}
# Existing IDs are retained for reconciliation. Only explicit mappings enter
# this exploratory engine; broad make/model/year mappings remain quarantined.
VERIFIED_MAPPING = {'mapped_explicit_variant_alias'}
CANONICAL_STATUS = VERIFIED_MAPPING | {'existing_variant_id', 'mapped_make_model_year'}
BASELINE = {'input_row_count':28058, 'supported_current_valuations':302,
            'supported_24m_returns':34, 'supported_60m_returns':7,
            'qualified_model_opportunities':0}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(input_path: str, output_dir: str, snapshot_id: str,
            as_of: str = '2026-11-20') -> dict:
    source = Path(input_path)
    raw = pd.read_csv(source, dtype=str, keep_default_na=False)
    missing = sorted(REQUIRED_COLUMNS - set(raw.columns))
    if missing:
        raise ValueError(f'snapshot missing required columns: {missing}')
    if raw.empty:
        raise ValueError('snapshot contains no rows')
    ids = raw.transaction_id.str.strip()
    if ids.eq('').any() or ids.duplicated().any():
        raise ValueError('blank or duplicate transaction_id detected')
    normalized = raw.variant_normalization_status.str.strip().str.lower()
    # Never let the legacy prefix stripper upgrade an unsupported assignment.
    mapped = normalized.isin(VERIFIED_MAPPING) & raw.vehicle_variant_id.str.strip().ne('')
    candidate = raw.copy()
    candidate.loc[~mapped, 'vehicle_variant_id'] = ''
    clean = raw.title_status.str.strip().str.lower().eq('clean')
    not_excluded = raw.exclusion_flag.str.strip().str.lower().isin({'', 'false', '0'})
    dates = pd.to_datetime(raw.auction_end_date, errors='coerce')
    prices = pd.to_numeric(raw.price_usd, errors='coerce')
    valid = clean & not_excluded & dates.notna() & dates.le(pd.Timestamp(as_of)) & prices.gt(0) & prices.lt(float('inf'))
    candidate.loc[~valid, 'sale_status'] = 'ineligible'
    reconciled = reconcile_transactions(candidate, as_of=as_of)
    values = valuation_rebuild(reconciled, as_of=as_of, min_observations=5)
    counts = {'current':0, '24m':0, '60m':0, 'historical_screen':0}
    if not values.empty:
        counts = {
            'current':int(values.current_comparable_sales.ge(5).sum()),
            '24m':int(values.supported_24m.sum()),
            '60m':int(values.supported_60m.sum()),
            # Legacy engine expresses returns in percent units, so use 5, not .05.
            'historical_screen':int((values.supported_24m & values.return_24m_pct.le(5)).sum()),
        }
    known_canonical = normalized.isin(CANONICAL_STATUS) & raw.vehicle_variant_id.str.strip().ne('')
    metrics = {
        'status':'SUCCEEDED', 'execution_scope':'exploratory_valuation',
        'snapshot_id':snapshot_id, 'analysis_date':as_of,
        'extracted_at_utc':datetime.now(timezone.utc).isoformat(),
        'input_row_count':len(raw), 'input_sha256':sha256_file(source),
        'canonical_assignment_rows':int(known_canonical.sum()),
        'provisional_or_noncanonical_rows':int((~known_canonical).sum()),
        'comparable_eligible_rows':int(reconciled.comparable_sale_eligible.sum()),
        'valuation_engine_executed':True,
        'valuation_engine':'cci.sprint22.valuation_rebuild',
        'valuation_engine_source_blob':'783524f5be7f5a73524ad4ea6b87332c449e6566',
        'valuation_cohort_rows':len(values), 'minimum_comparables':5,
        'exploratory_unadjusted_counts':counts,
        'supported_current_valuations':None, 'supported_24m_returns':None,
        'supported_60m_returns':None,
        'qualified_model_opportunities':0, 'individual_purchase_opportunities':0,
        'model_ranking_status':'blocked_adjustments_and_forecast_unvalidated',
        'individual_ranking_status':'no_active_listing_population',
        'analytical_acceptance':False,
        'acceptance_blockers':['condition_and_specification_adjustment_not_implemented',
                               'verified_variant_crosswalk_incomplete',
                               'five_year_forecast_not_validated'],
        'backtesting':backtest_status(reconciled),
        'baseline_reference_only':BASELINE,
        'baseline_comparison_status':'not_comparable_unadjusted_exploratory_method',
        'raw_rows_written_to_artifacts':False,
    }
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    return metrics
