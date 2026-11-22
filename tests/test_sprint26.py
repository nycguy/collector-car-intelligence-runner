import pandas as pd
from campaign.analysis.sprint26 import analyze

def test_sprint26_preserves_exclusion_reasons_and_repeat_sales():
    rows = [
        {"transaction_id":"1","vehicle_variant_id":"v1","variant_normalization_status":"existing_variant_id","sale_status":"sold","price_usd":"10000","auction_end_date":"2026-10-01","title_status":"clean","mileage_at_sale":"50000","source_url":"u1","repeat_sale_group_id":"r1"},
        {"transaction_id":"2","vehicle_variant_id":"","variant_normalization_status":"","sale_status":"sold","price_usd":"10000","auction_end_date":"2026-10-01","title_status":"clean","mileage_at_sale":"50000","source_url":"u2","repeat_sale_group_id":"r1"},
        {"transaction_id":"3","vehicle_variant_id":"v1","variant_normalization_status":"existing_variant_id","sale_status":"unsuccessful","price_usd":"","auction_end_date":"","title_status":"unknown","mileage_at_sale":"","source_url":"u3"},
        {"transaction_id":"4","vehicle_variant_id":"v1","variant_normalization_status":"existing_variant_id","sale_status":"sold","price_usd":"20000","auction_end_date":"2026-10-01","title_status":"salvage","mileage_at_sale":"50000","source_url":"u4"},
    ]
    result = analyze(pd.DataFrame(rows))
    assert result["summary"]["input_row_count"] == 4
    assert result["summary"]["comparable_eligible_rows"] == 1
    reasons = {r["eligibility_reason"] for r in result["row_audit"]}
    assert "missing_verified_variant_assignment" in reasons
    assert "adverse_title" in reasons
    assert result["funnel"]["repeat_sale_group_rows"] == 2

def test_sprint26_does_not_promote_without_individual_listing():
    result = analyze(pd.DataFrame([{
        "transaction_id":"1","vehicle_variant_id":"v1","variant_normalization_status":"existing_variant_id",
        "sale_status":"sold","price_usd":"10000","auction_end_date":"2026-10-01","title_status":"clean"
    }]))
    assert result["individual_opportunities"] == []
    assert result["summary"]["qualified_model_opportunities"] == 0
