import pandas as pd

from campaign.analysis.sprint34 import recover_identity, summarize, vertical_slice


def rows():
    return pd.DataFrame([
        {"transaction_id": "1", "listing_id": "l1", "source_id": "bat", "source_variant_id": "HONDA-S2000-AP1-20-MT", "source_url": "https://bringatrailer.com/listing/2000-honda-s2000-1/", "sale_status": "sold", "price_usd": 30000, "auction_end_date": "2026-01-01", "mileage_at_sale": 40000, "vin": "JHMAP1140YT000001", "title_status": "clean"},
        {"transaction_id": "2", "listing_id": "l2", "source_id": "bat", "source_variant_id": "honda_s2000", "source_url": "https://bringatrailer.com/listing/2006-honda-s2000-2/", "sale_status": "sold", "price_usd": 35000, "auction_end_date": "2026-02-01", "mileage_at_sale": 30000, "vin": "", "title_status": "clean"},
        {"transaction_id": "3", "listing_id": "l3", "source_id": "bat", "source_variant_id": "porsche_944_turbo", "source_url": "https://bringatrailer.com/listing/1986-porsche-944-turbo-3/", "sale_status": "sold", "price_usd": 25000, "auction_end_date": "2026-03-01", "mileage_at_sale": 50000, "vin": "", "title_status": "clean"},
        {"transaction_id": "4", "listing_id": "l4", "source_id": "bat", "source_variant_id": "dodge_viper_gen1", "source_url": "https://bringatrailer.com/listing/1994-dodge-viper-rt-10-4/", "sale_status": "sold", "price_usd": 50000, "auction_end_date": "2026-04-01", "mileage_at_sale": 10000, "vin": "", "title_status": "clean"},
        {"transaction_id": "5", "listing_id": "l5", "source_id": "bat", "source_variant_id": "acura_nsx_na1_30_manual", "source_url": "https://bringatrailer.com/listing/1991-acura-nsx-5/", "sale_status": "sold", "price_usd": 80000, "auction_end_date": "2026-05-01", "mileage_at_sale": 60000, "vin": "", "title_status": "clean"},
        {"transaction_id": "6", "listing_id": "l6", "source_id": "bat", "source_variant_id": "bmw_m3_e30", "source_url": "https://bringatrailer.com/listing/1990-bmw-m3-6/", "sale_status": "sold", "price_usd": 90000, "auction_end_date": "2026-06-01", "mileage_at_sale": 70000, "vin": "", "title_status": "clean"},
    ])


def test_priority_separation_and_conservative_unknowns():
    out = recover_identity(rows())
    assert out.loc[0, "canonical_variant_id"] == "honda_s2000_ap1"
    assert out.loc[1, "classification"] == "PROVISIONAL_VARIANT"
    assert out.loc[2, "canonical_variant_id"] == "porsche_944_turbo"
    assert out.loc[3, "canonical_variant_id"] == "dodge_viper_gen1_rt10"
    assert out.loc[5, "canonical_variant_id"] == "bmw_e30_m3"


def test_repeat_sales_are_flagged_without_collapse():
    frame = rows()
    frame.loc[1, "vin"] = frame.loc[0, "vin"]
    out = recover_identity(frame)
    assert len(out) == len(frame)
    assert out["repeat_sale_observation"].sum() == 2


def test_summary_and_vertical_slice_are_reproducible():
    first = summarize(rows())
    second = summarize(rows())
    assert first == second
    assert len(vertical_slice(rows())) == 5
    assert first["verified_canonical_variants"] == 5
