import pandas as pd
from campaign.analysis.sprint28 import analyze

def row(i, *, title="clean", title_evidence="manual_source_page_claim", status="existing_variant_id", variant="v1"):
    return {"transaction_id": i, "vehicle_variant_id": variant, "source_variant_id": variant,
            "variant_normalization_status": status, "source_id": "bat", "source_name": "Bring a Trailer",
            "source_url": f"https://example.test/{i}", "sale_status": "sold", "price_usd": "10000",
            "auction_end_date": "2026-10-01", "title_status": title,
            "title_evidence_status": title_evidence, "source_title_status_assertion": title,
            "mileage_at_sale": "50000"}

def test_source_reported_clean_is_not_documentary():
    result = analyze(pd.DataFrame([row("a")]))
    assert result["summary"]["source_reported_clean_rows"] == 1
    assert result["summary"]["verified_documentary_clean_rows"] == 0
    assert result["summary"]["strict_validated_rows"] == 0

def test_provisional_source_label_is_review_only():
    result = analyze(pd.DataFrame([row("a", status="provisional_unmapped", variant="provisional_carsandbids_bmw_bmw_330i_sedan_2017")]))
    assert result["summary"]["deterministic_source_label_review_rows"] == 1
    assert result["summary"]["new_strict_variant_assignments"] == 0

def test_adverse_evidence_is_excluded():
    result = analyze(pd.DataFrame([row("a", title="flood", title_evidence="manual_source_page_claim")]))
    assert result["summary"]["market_evidence_rows"] == 0

def test_endpoint_windows_are_explicit():
    rows = [row(str(i), variant="v1") for i in range(5)]
    for i in range(5, 10):
        r = row(str(i), variant="v1"); r["auction_end_date"] = "2024-11-20"; rows.append(r)
    result = analyze(pd.DataFrame(rows))
    endpoint = result["endpoint_diagnostics"][0]
    assert endpoint["current_6m_start"] == "2026-05-20"
    assert endpoint["prior24_6m_start"] == "2024-05-20"
    assert endpoint["validated_24m_endpoint_pair"] is True
