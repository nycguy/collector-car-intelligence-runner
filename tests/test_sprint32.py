import pandas as pd

from campaign.analysis.sprint32 import analyze
from campaign.analysis.sprint31 import fit_model, prepare_transactions, estimate_value

def _rows():
    rows = []
    for variant, base, start in [("BMW E30 M3", 50000, "2021-01-01"), ("Honda S2000 AP1", 30000, "2021-01-01")]:
        for i, date in enumerate(pd.date_range(start, "2026-11-20", periods=30)):
            rows.append({
                "transaction_id": f"{variant}-{i}", "vehicle_variant_id": variant,
                "source_variant_id": variant, "source_name": "test",
                "source_url": f"https://example/{variant}/{i}", "sale_status": "completed",
                "price_usd": base * (1 + i * 0.002), "auction_end_date": date.date().isoformat(),
                "mileage_at_sale": 40000 + i * 500, "model_year": 1991,
                "transmission": "5-speed manual", "condition_grade": "excellent",
                "title_status": "clean", "title_evidence_status": "source_reported_clean",
                "engine": "stock", "body_style": "coupe", "trim": "base",
                "generation": "period", "modifications": "stock"
            })
    return pd.DataFrame(rows)

def test_time_origin_is_persisted_and_used_for_reference():
    frame = prepare_transactions(_rows())
    fit = fit_model(frame)
    assert fit.time_origin == frame["_date"].min()
    result = estimate_value(fit, "BMW E30 M3", "2024-11-20", {"mileage": 49000, "model_year": 1991})
    assert result["time_origin"] == "2021-01-01"

def test_different_vin_comparables_and_gate_are_reproducible():
    raw = _rows()
    a = analyze(raw)
    b = analyze(raw)
    assert a["model_metadata"]["data_snapshot_sha256"] == b["model_metadata"]["data_snapshot_sha256"]
    assert a["summary"]["historical_gate_enforced"] is True
    assert all(x["screening_result"] in {"PASS", "FAIL", "UNVERIFIED"} for x in a["valuations"])

def test_invalid_viper_classification_is_canonicalized():
    raw = _rows()
    raw.loc[0, "source_variant_id"] = "Dodge Viper RT/10 NA1"
    result = analyze(raw)
    assert any(x["model_variant"] == "dodge_viper_gen1_rt10" for x in result["valuations"])
