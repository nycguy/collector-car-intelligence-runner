"""Conservative Sprint 34 identity recovery and validation layer.

The production input is an approved 43-column transaction export.  This module
keeps observed values intact and adds inferred identity fields plus explicit
confidence and review status.  It never turns a broad family label into a
configuration-specific variant without a source signal.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd


COMPLETED = {"sold", "completed", "sale", "sold_pending_title"}
ADVERSE = ("salvage", "rebuilt", "flood", "total loss", "total-loss", "branded")


def _s(row: pd.Series, *names: str) -> str:
    for name in names:
        value = row.get(name, "")
        if pd.notna(value) and str(value).strip():
            return str(value).strip()
    return ""


def _year(text: str) -> int | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    return int(m.group(1)) if m else None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")


def classify_row(row: pd.Series) -> dict[str, Any]:
    observed_variant = _s(row, "source_variant_id", "vehicle_variant_id")
    key = _normalize_key(observed_variant)
    url = _s(row, "source_url", "evidence_url").lower()
    notes = _s(row, "notes").lower()
    text = " ".join((key, url, notes))
    model_year = _year(text)
    manufacturer = model = generation = engine = transmission = body_style = trim = ""
    canonical = ""
    reasons: list[str] = []

    if "bmw_m3_e30" in key or ("bmw" in text and "e30" in text and "m3" in text):
        manufacturer, model, generation = "BMW", "M3", "E30"
        canonical = "bmw_e30_m3"
        body_style, transmission = "coupe", "manual"
        reasons.append("explicit_e30_m3_source_label")
    elif "honda_s2000_ap1" in key or "s2000_ap1" in text:
        manufacturer, model, generation = "Honda", "S2000", "AP1"
        canonical = "honda_s2000_ap1"
        engine, transmission, body_style = "2.0L F20C", "manual", "roadster"
        reasons.append("explicit_ap1_source_label")
    elif "honda_s2000_ap2" in key or "s2000_ap2" in text:
        manufacturer, model, generation = "Honda", "S2000", "AP2"
        canonical = "honda_s2000_ap2"
        engine, transmission, body_style = "2.2L F22C1", "manual", "roadster"
        reasons.append("explicit_ap2_source_label")
    elif "honda_s2000" in key or "s2000" in text:
        manufacturer, model = "Honda", "S2000"
        canonical = "honda_s2000_unresolved"
        reasons.append("s2000_generation_unresolved")
    elif "porsche_944_turbo" in key or "944_turbo" in text:
        manufacturer, model, generation = "Porsche", "944", "Turbo"
        canonical = "porsche_944_turbo"
        engine, body_style = "2.5L turbo", "coupe"
        reasons.append("explicit_944_turbo_source_label")
    elif "porsche_944" in key or "944" in text:
        manufacturer, model = "Porsche", "944"
        canonical = "porsche_944_unresolved"
        reasons.append("944_configuration_unresolved")
    elif "dodge_viper_gen1_rt10" in key or ("viper" in text and "rt_10" in text and model_year and model_year <= 1996):
        manufacturer, model, generation = "Dodge", "Viper RT/10", "Gen 1"
        canonical = "dodge_viper_gen1_rt10"
        body_style = "roadster"
        reasons.append("explicit_gen1_rt10_source_label")
    elif "dodge_viper_gen1" in key or ("viper" in text and "rt_10" in text):
        manufacturer, model, generation = "Dodge", "Viper RT/10", "Gen 1"
        canonical = "dodge_viper_gen1_rt10"
        body_style = "roadster"
        reasons.append("gen1_rt10_alias_normalized")
    elif "acura_nsx_na1_30_auto" in key or ("nsx" in text and "auto" in text and model_year and model_year <= 2001):
        manufacturer, model, generation = "Acura", "NSX", "NA1"
        canonical = "acura_nsx_na1_30_auto"
        engine, transmission = "3.0L C30A", "automatic"
        reasons.append("explicit_na1_30_automatic_label")
    elif "acura_nsx_na1_30_manual" in key or "nsx_na1_30_manual" in text:
        manufacturer, model, generation = "Acura", "NSX", "NA1"
        canonical = "acura_nsx_na1_30_manual"
        engine, transmission = "3.0L C30A", "manual"
        reasons.append("explicit_na1_30_manual_label")
    elif "acura_nsx_na2" in key or ("nsx" in text and model_year and model_year >= 2002):
        manufacturer, model, generation = "Acura", "NSX", "NA2"
        canonical = "acura_nsx_na2_unresolved"
        reasons.append("na2_body_or_transmission_unresolved")
    elif "acura_nsx" in key or "nsx" in text:
        manufacturer, model = "Acura", "NSX"
        canonical = "acura_nsx_unresolved"
        reasons.append("nsx_configuration_unresolved")
    else:
        reasons.append("no_priority_identity_rule")

    status = str(_s(row, "sale_status")).lower()
    source_url_ok = bool(_s(row, "source_url", "evidence_url"))
    adverse = any(term in (f"{_s(row, 'title_status')} {_s(row, 'exclusion_reason')}".lower()) for term in ADVERSE)
    if not canonical:
        classification = "UNCLASSIFIED"
        confidence = "none"
    elif canonical.endswith("_unresolved") or "unresolved" in reasons[0]:
        classification = "PROVISIONAL_VARIANT"
        confidence = "medium" if source_url_ok else "low"
    elif source_url_ok and status in COMPLETED and not adverse:
        classification = "VERIFIED_CANONICAL"
        confidence = "high"
    else:
        classification = "HIGH_CONFIDENCE_INFERRED"
        confidence = "medium"

    return {
        "observed_variant_id": observed_variant,
        "inferred_manufacturer": manufacturer or None,
        "inferred_model": model or None,
        "inferred_generation": generation or None,
        "inferred_model_year": model_year,
        "inferred_engine": engine or None,
        "inferred_transmission": transmission or None,
        "inferred_body_style": body_style or None,
        "inferred_trim": trim or None,
        "canonical_variant_id": canonical or None,
        "classification": classification,
        "classification_confidence": confidence,
        "derivation_method": ";".join(reasons),
        "adverse_title_or_loss_signal": adverse,
    }


def recover_identity(frame: pd.DataFrame) -> pd.DataFrame:
    """Add identity, lineage, deduplication, and gate fields without collapsing rows."""
    out = frame.copy()
    inferred = pd.DataFrame([classify_row(row) for _, row in out.iterrows()], index=out.index)
    for col in inferred.columns:
        out[col] = inferred[col]
    out["identity_source_preserved"] = out.apply(lambda r: bool(_s(r, "source_url", "evidence_url")), axis=1)
    out["duplicate_transaction_key"] = out.apply(lambda r: "|".join(filter(None, [_s(r, "source_id"), _s(r, "listing_id"), _s(r, "auction_end_date"), _s(r, "price_usd")])), axis=1)
    out["duplicate_record_flag"] = out["duplicate_transaction_key"].duplicated(keep=False)
    vin = out.get("vin", pd.Series("", index=out.index)).fillna("").astype(str).str.upper().str.strip()
    physical = out.get("physical_vehicle_id", pd.Series("", index=out.index)).fillna("").astype(str).str.strip()
    out["repeat_sale_group_id_recovered"] = vin.where(vin.ne(""), physical).where(lambda x: x.ne(""), None)
    out["repeat_sale_observation"] = out["repeat_sale_group_id_recovered"].notna() & out["repeat_sale_group_id_recovered"].duplicated(keep=False)
    out["identity_quality_gate"] = out.apply(
        lambda r: "ELIGIBLE" if r["classification"] in {"VERIFIED_CANONICAL", "HIGH_CONFIDENCE_INFERRED"}
        and str(r.get("sale_status", "")).lower() in COMPLETED
        and not bool(r["adverse_title_or_loss_signal"])
        and pd.to_numeric(r.get("price_usd"), errors="coerce") > 0 else "REVIEW",
        axis=1,
    )
    return out


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    out = recover_identity(frame)
    return {
        "input_rows": int(len(out)),
        "usable_manufacturer": int(out["inferred_manufacturer"].notna().sum()),
        "usable_model": int(out["inferred_model"].notna().sum()),
        "verified_canonical_variants": int(out.loc[out["classification"] == "VERIFIED_CANONICAL", "canonical_variant_id"].nunique()),
        "high_confidence_inferred_variants": int(out.loc[out["classification"] == "HIGH_CONFIDENCE_INFERRED", "canonical_variant_id"].nunique()),
        "provisional_variants": int(out.loc[out["classification"] == "PROVISIONAL_VARIANT", "canonical_variant_id"].nunique()),
        "unclassified_rows": int((out["classification"] == "UNCLASSIFIED").sum()),
        "duplicate_rows_flagged": int(out["duplicate_record_flag"].sum()),
        "repeat_sale_observations": int(out["repeat_sale_observation"].sum()),
        "mileage_complete": int(pd.to_numeric(out.get("mileage_at_sale"), errors="coerce").notna().sum()),
        "vin_complete": int(out.get("vin", pd.Series(index=out.index)).fillna("").astype(str).str.strip().ne("").sum()),
        "eligible_identity_rows": int((out["identity_quality_gate"] == "ELIGIBLE").sum()),
    }


def vertical_slice(frame: pd.DataFrame) -> pd.DataFrame:
    out = recover_identity(frame)
    families = {"bmw_e30_m3", "honda_s2000_ap1", "honda_s2000_ap2", "porsche_944_turbo", "acura_nsx_na1_30_manual", "acura_nsx_na1_30_auto", "dodge_viper_gen1_rt10"}
    return out[out["canonical_variant_id"].isin(families)].copy()
