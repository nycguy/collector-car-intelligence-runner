import pandas as pd
from campaign.analysis.sprint27 import analyze

def row(i, title="clean", status="existing_variant_id", variant="v1", date="2026-10-01"):
    return {
        "transaction_id": i, "vehicle_variant_id": variant, "source_variant_id": variant,
        "variant_normalization_status": status, "source_id": "test", "source_name": "Cars & Bids",
        "source_url": f"https://example.test/{i}", "sale_status": "sold", "price_usd": "10000",
        "auction_end_date": date, "title_status": title, "mileage_at_sale": "50000",
        "repeat_sale_group_id": "", "exclusion_flag": "FALSE"
    }

def test_unknown_title_is_market_evidence_but_not_validated():
    frame = pd.DataFrame([row("unknown", title="review")])
    result = analyze(frame)
    assert result["summary"]["historical_market_evidence_unknown_title_rows"] == 1
    assert result["summary"]["comparable_eligible_rows"] == 0
    assert result["row_audit"][0]["analysis_class"] == "historical_market_evidence_unknown_title"

def test_clean_unassigned_population_is_explicitly_reconciled():
    frame = pd.DataFrame([
        row("strict"),
        row("mapped", status="mapped_make_model_year"),
        row("source", status="normalized_from_source"),
    ])
    result = analyze(frame)
    assert result["summary"]["strict_variant_assignment_rows"] == 1
    assert result["summary"]["sprint25_canonical_assignment_rows"] == 2
    assert result["summary"]["clean_title_unassigned_rows"] == 2
    assert any(x["population"] == "Sprint 25 minus Sprint 26 mapped_make_model_year rows" and x["rows"] == 1
               for x in result["reconciliation"])

def test_adverse_title_is_excluded_from_market_evidence():
    result = analyze(pd.DataFrame([row("bad", title="flood")]))
    assert result["summary"]["historical_market_evidence_rows"] == 0
    assert result["row_audit"][0]["analysis_class"] == "excluded"
