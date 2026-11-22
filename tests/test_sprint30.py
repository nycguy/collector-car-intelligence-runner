import pandas as pd
from campaign.analysis.sprint30 import analyze

def row(i, date, price, variant="test_variant", title="clean"):
    return {"transaction_id":i,"vehicle_variant_id":variant,"source_variant_id":variant,
            "variant_normalization_status":"existing_variant_id","source_id":"bat",
            "source_url":f"https://example.test/{i}","sale_status":"sold",
            "price_usd":str(price),"auction_end_date":date,"title_status":title,
            "title_evidence_status":"manual_source_page_claim",
            "source_title_status_assertion":title,"mileage_at_sale":"50000"}

def result(past, current):
    rows=[row(f"p{i}","2024-06-01",past) for i in range(3)]
    rows += [row(f"c{i}","2026-06-01",current) for i in range(3)]
    return analyze(pd.DataFrame(rows), min_comparables=3)["summary"]

def test_30_percent_appreciation_fails():
    assert result(100,130)["fail_24m_gate"] == 1

def test_5_01_percent_appreciation_fails():
    assert result(100,105.01)["fail_24m_gate"] == 1

def test_exactly_5_percent_passes():
    assert result(100,105)["pass_24m_gate"] == 1

def test_negative_appreciation_passes():
    assert result(100,90)["pass_24m_gate"] == 1

def test_missing_endpoint_is_unverified():
    rows=[row(str(i),"2026-06-01",100) for i in range(3)]
    r=analyze(pd.DataFrame(rows), min_comparables=3)["summary"]
    assert r["unverified_24m_gate"] == 1

def test_known_adverse_title_excluded():
    rows=[row(str(i),"2026-06-01",100,title="salvage") for i in range(3)]
    r=analyze(pd.DataFrame(rows), min_comparables=3)["summary"]
    assert r["market_evidence_rows"] == 0

def test_unverified_not_qualified():
    rows=[row(str(i),"2026-06-01",100) for i in range(3)]
    r=analyze(pd.DataFrame(rows), min_comparables=3)
    assert not r["qualified_model_opportunities"]
