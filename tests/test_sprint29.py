import pandas as pd
from campaign.analysis.sprint29 import analyze

def row(i, *, title="clean", status="existing_variant_id", variant="porsche_911_996_carrera_manual"):
    return {"transaction_id":i,"vehicle_variant_id":variant,"source_variant_id":variant,"variant_normalization_status":status,"source_id":"bat","source_name":"Bring a Trailer","source_url":f"https://example.test/{i}","sale_status":"sold","price_usd":"50000","auction_end_date":"2026-10-01","title_status":title,"title_evidence_status":"manual_source_page_claim","source_title_status_assertion":title,"mileage_at_sale":"50000"}

def test_market_population_accepts_source_reported_clean():
    r=analyze(pd.DataFrame([row("a")]))
    assert r["summary"]["market_evidence_rows"] == 1
    assert r["summary"]["source_reported_clean_market_rows"] == 1

def test_unknown_title_is_separate_sensitivity_population():
    r=analyze(pd.DataFrame([row("a",title="")]))
    assert r["summary"]["market_evidence_rows"] == 1
    assert r["summary"]["unknown_title_market_rows"] == 1

def test_adverse_title_is_excluded():
    r=analyze(pd.DataFrame([row("a",title="salvage")]))
    assert r["summary"]["market_evidence_rows"] == 0
    assert r["summary"]["known_adverse_excluded_rows"] == 1

def test_endpoint_and_five_percent_screen():
    rows=[]
    for i in range(3):
        x=row(str(i)); x["auction_end_date"]="2026-06-01"; rows.append(x)
    for i in range(3,6):
        x=row(str(i)); x["auction_end_date"]="2024-06-01"; x["price_usd"]="48000"; rows.append(x)
    for i in range(6,9):
        x=row(str(i)); x["auction_end_date"]="2021-06-01"; x["price_usd"]="60000"; rows.append(x)
    r=analyze(pd.DataFrame(rows))
    v=r["valuations"][0]
    assert v["return_24m_pct"] is not None and v["return_24m_pct"] <= 5
    assert v["return_60m_pct"] is not None and v["return_60m_pct"] < 0

def test_no_individual_purchase_promotion():
    r=analyze(pd.DataFrame([row("a")]))
    assert r["summary"]["individual_purchase_opportunities"] == 0
