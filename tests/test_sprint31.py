import pandas as pd

from campaign.analysis.sprint31 import MODEL_VERSION, analyze, estimate_value, fit_model, prepare_transactions


def _rows():
    rows = []
    for year, variant, trans, mult in [(1991, "NSX-NA1", "5-speed manual", 1.0), (1991, "NSX-NA1", "automatic", 0.82), (2002, "NSX-NA2", "6-speed manual", 1.35)]:
        for i, date in enumerate(pd.date_range("2021-01-01", "2026-11-20", periods=24)):
            rows.append({"transaction_id": f"{variant}-{trans}-{i}", "vehicle_variant_id": variant, "source_variant_id": variant, "source_name": "test", "source_url": f"https://example/{i}", "sale_status": "completed", "price_usd": 70000 * mult * (1 + 0.015 * i), "auction_end_date": date.date().isoformat(), "mileage_at_sale": 40000 + 1000 * i, "model_year": year, "transmission": trans, "condition_grade": "excellent", "title_status": "clean", "title_evidence_status": "source_reported_clean", "engine": "3.0" if year == 1991 else "3.2", "body_style": "coupe", "trim": "base", "generation": "NA1" if year == 1991 else "NA2", "modifications": "stock"})
    return pd.DataFrame(rows)


def test_different_vins_and_historical_dates():
    result = analyze(_rows())
    nsx = next(x for x in result["valuations"] if x["model_variant"] == "NSX-NA1")
    assert nsx["value_2021_usd"] and nsx["value_2026_usd"]
    assert nsx["model_version"] == MODEL_VERSION


def test_configuration_and_sparse_handling():
    raw = _rows()
    frame = prepare_transactions(raw)
    fit = fit_model(frame)
    manual = estimate_value(fit, "NSX-NA1", "2026-11-20", {"mileage": 49000, "model_year": 1991, "transmission": "5-speed manual", "_condition": "excellent"})
    auto = estimate_value(fit, "NSX-NA1", "2026-11-20", {"mileage": 49000, "model_year": 1991, "transmission": "automatic", "_condition": "excellent"})
    assert manual["estimated_value_usd"] > auto["estimated_value_usd"]
    assert estimate_value(fit, "missing", "2026-11-20")["status"] == "UNSUPPORTED"


def test_gate_and_repeat_sale_evidence():
    result = analyze(_rows())
    assert result["nsx"][0]["screening_result"] == "FAIL"
    assert result["summary"]["historical_gate_enforced"] is True

