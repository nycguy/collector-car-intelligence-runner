"""Sprint 35 VIN audit, free authoritative decode, and conservative identity recovery."""
from __future__ import annotations
import json, re, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import pandas as pd
import requests
from .sprint34 import recover_identity

VIN_ALLOWED = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
PLACEHOLDERS = {"", "N/A", "NA", "UNKNOWN", "UNK", "NONE", "NULL", "0", "VIN",
                "NOT AVAILABLE", "NOTAPPLICABLE", "TBD", "PENDING"}
WEIGHTS = [8,7,6,5,4,3,2,10,0,9,8,7,6,5,4,3,2]

def normalize_vin(value: Any) -> str:
    return re.sub(r"[\s-]+", "", str(value or "").strip().upper())

def check_digit_valid(vin: str) -> bool | None:
    if not VIN_ALLOWED.fullmatch(vin) or "I" in vin or "O" in vin or "Q" in vin:
        return None
    total = 0
    for char, weight in zip(vin, WEIGHTS):
        transliteration = {"A":1,"B":2,"C":3,"D":4,"E":5,"F":6,"G":7,"H":8,"J":1,"K":2,"L":3,"M":4,"N":5,"P":7,"R":9,"S":2,"T":3,"U":4,"V":5,"W":6,"X":7,"Y":8,"Z":9}\n        value = transliteration[char] if char.isalpha() else int(char)
        total += value * weight
    expected = "X" if total % 11 == 10 else str(total % 11)
    return vin[8] == expected

def _placeholder(vin: str) -> bool:
    return vin in PLACEHOLDERS or (len(vin) >= 4 and len(set(vin)) == 1)

def audit_vins(frame: pd.DataFrame) -> dict[str, Any]:
    raw = frame.get("vin", pd.Series("", index=frame.index)).fillna("").astype(str)
    normalized = raw.map(normalize_vin)
    populated = normalized[normalized.ne("")]
    unique = set(populated)
    counts = Counter(populated)
    valid_format = [v for v in unique if VIN_ALLOWED.fullmatch(v)]
    checkable = [v for v in valid_format if check_digit_valid(v) is not None]
    passed = [v for v in checkable if check_digit_valid(v)]
    failed = [v for v in checkable if not check_digit_valid(v)]
    invalid_char = [v for v in unique if len(v) == 17 and not VIN_ALLOWED.fullmatch(v)]
    nonstandard = [v for v in unique if len(v) != 17 and not _placeholder(v)]
    repeated = {v:n for v,n in counts.items() if n > 1}
    row_conflicts = []
    for vin in repeated:
        rows = frame.loc[normalized.eq(vin)]
        labels = sorted(set(rows.get("vehicle_variant_id", pd.Series(dtype=str)).astype(str)))
        if len(labels) > 1:
            row_conflicts.append({"vin": vin, "transaction_count": int(len(rows)), "labels": labels[:20]})
    return {
        "records_total": int(len(frame)),
        "vin_populated_records": int(len(populated)),
        "unique_vins": int(len(unique)),
        "duplicate_vin_values": int(len(repeated)),
        "duplicate_vin_rows": int(sum(repeated.values())),
        "valid_17_character_vins": int(len(valid_format)),
        "invalid_length_values": int(sum(1 for v in unique if len(v) != 17)),
        "placeholder_values": int(sum(1 for v in unique if _placeholder(v))),
        "nonstandard_historical_values": int(len(nonstandard)),
        "invalid_character_values": int(len(invalid_char)),
        "check_digit_pass_values": int(len(passed)),
        "check_digit_fail_values": int(len(failed)),
        "check_digit_not_applicable_values": int(len(nonstandard)),
        "repeated_vins_with_conflicting_source_labels": int(len(row_conflicts)),
        "repeat_sale_observation_rows": int(sum(n for v,n in repeated.items())),
        "classification_note": "Check digits are a North-American validation signal, not a universal authenticity test for all export/import vehicles.",
        "conflict_examples": row_conflicts[:100],
    }

def _decode_batch(vins: list[str]) -> list[dict[str, Any]]:
    if not vins:
        return []
    last_error = None
    for attempt in range(4):
        try:
            response = requests.post(
                "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/",
                data={"format": "json", "data": ";".join(vins)},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            return payload.get("Results", [])
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise last_error

def decode_vins(frame: pd.DataFrame, output_dir: Path, batch_size: int = 50, max_workers: int = 4) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "vin_decode_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    vins = sorted({normalize_vin(v) for v in frame.get("vin", []) if VIN_ALLOWED.fullmatch(normalize_vin(v))})
    pending = [v for v in vins if v not in cache]
    errors = 0
    batches = [pending[start:start + batch_size] for start in range(0, len(pending), batch_size)]

    def run_batch(batch: list[str]) -> tuple[list[str], list[dict[str, Any]], Exception | None]:
        try:
            return batch, _decode_batch(batch), None
        except Exception as exc:
            return batch, [], exc

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_batch, batch) for batch in batches]
        for future in as_completed(futures):
            batch, results, error = future.result()
            if error is not None:
                errors += len(batch)
                for vin in batch:
                    cache.setdefault(vin, {"decoder": "NHTSA_vPIC", "decoder_version": "2026-11-20",
                                           "VIN": vin, "ErrorCode": f"request_error:{type(error).__name__}",
                                           "retryable": True})
                continue
            for result in results:
                vin = normalize_vin(result.get("VIN"))
                if vin:
                    cache[vin] = {"decoder": "NHTSA_vPIC", "decoder_version": "2026-11-20", **result}
            for vin in batch:
                cache.setdefault(vin, {"decoder": "NHTSA_vPIC", "decoder_version": "2026-11-20",
                                       "VIN": vin, "ErrorCode": "not_returned"})
    cache_path.write_text(json.dumps(cache, indent=2, sort_keys=True))
    successful = [r for r in cache.values() if r.get("Make") or r.get("Model")]
    return cache, {
        "format_valid_unique_vins": len(vins),
        "decode_cache_entries": len(cache),
        "successful_decode_entries": len(successful),
        "failed_or_empty_decode_entries": len(cache) - len(successful),
        "request_error_rows": errors,
        "decoder": "NHTSA_vPIC",
        "decoder_version": "2026-11-20",
        "decoder_batch_size": batch_size,
        "decoder_max_workers": max_workers,
    }

def _text(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""

def enrich_identity(frame: pd.DataFrame, decoded: dict[str, dict[str, Any]]) -> pd.DataFrame:
    out = recover_identity(frame)
    vins = out.get("vin", pd.Series("", index=out.index)).map(normalize_vin)
    decoded_make = vins.map(lambda v: _text(decoded.get(v, {}), "Make", "Manufacturer"))
    decoded_model = vins.map(lambda v: _text(decoded.get(v, {}), "Model"))
    decoded_year = vins.map(lambda v: _text(decoded.get(v, {}), "ModelYear"))
    out["vin_decoded_make"] = decoded_make.replace("", pd.NA)
    out["vin_decoded_model"] = decoded_model.replace("", pd.NA)
    out["vin_decoded_model_year"] = decoded_year.replace("", pd.NA)
    out["vin_identity_evidence"] = out.apply(
        lambda r: "cross_validated" if (
            pd.notna(r.get("vin_decoded_make")) and str(r.get("vin_decoded_make")).strip()
            and pd.notna(r.get("inferred_manufacturer")) and str(r.get("inferred_manufacturer")).strip()
            and str(r.get("vin_decoded_make")).lower() == str(r.get("inferred_manufacturer")).lower()
        ) else (
            "directly_decoded" if pd.notna(r.get("vin_decoded_make")) and str(r.get("vin_decoded_make")).strip()
            else "unverified"
        ), axis=1)
    out["recovered_manufacturer"] = out["inferred_manufacturer"].fillna(out["vin_decoded_make"])
    out["recovered_model"] = out["inferred_model"].fillna(out["vin_decoded_model"])
    out["identity_recovery_status"] = out.apply(
        lambda r: "CROSS_VALIDATED" if r["vin_identity_evidence"] == "cross_validated"
        else ("VIN_DECODED_UNRESOLVED_VARIANT" if r["vin_identity_evidence"] == "directly_decoded" else "SOURCE_ONLY_OR_UNVERIFIED"), axis=1)
    return out

def _endpoint_values(group: pd.DataFrame, target: str) -> list[float]:
    dates = pd.to_datetime(group.get("auction_end_date"), errors="coerce")
    target_date = pd.Timestamp(target)
    delta = (dates - target_date).abs().dt.days
    values = pd.to_numeric(group.get("price_usd"), errors="coerce")
    eligible = group.get("sale_status", pd.Series("", index=group.index)).astype(str).str.lower().isin({"sold","completed","sale","sold_pending_title"})
    return values[eligible & delta.le(365)].dropna().tolist()

def reconstruct_valuations(frame: pd.DataFrame) -> list[dict[str, Any]]:
    eligible = frame[(frame.get("canonical_variant_id").notna()) &
                     frame.get("identity_quality_gate", pd.Series("", index=frame.index)).eq("ELIGIBLE")].copy()
    rows = []
    for variant, group in eligible.groupby("canonical_variant_id"):
        endpoints = {date: _endpoint_values(group, date) for date in ("2021-11-20","2024-11-20","2026-11-20")}
        values = {date: (sum(vals)/len(vals) if vals else None) for date, vals in endpoints.items()}
        supported = all(len(endpoints[d]) >= 5 and values[d] is not None for d in endpoints)
        r24 = (values["2026-11-20"] / values["2024-11-20"] - 1) * 100 if supported else None
        r60 = (values["2026-11-20"] / values["2021-11-20"] - 1) * 100 if supported else None
        rows.append({"canonical_variant_id": variant, "value_2021_usd": values["2021-11-20"],
                     "value_2024_usd": values["2024-11-20"], "value_2026_usd": values["2026-11-20"],
                     "return_24m_pct": r24, "return_60m_pct": r60,
                     "screening_result": "PASS" if supported and r24 <= 5 else ("FAIL" if supported else "UNVERIFIED"),
                     "comparable_count_2021": len(endpoints["2021-11-20"]),
                     "comparable_count_2024": len(endpoints["2024-11-20"]),
                     "comparable_count_2026": len(endpoints["2026-11-20"]),
                     "model_version": "s35_canonical_endpoint_v1_unadjusted",
                     "adjustment_status": "not_applied_when_unsupported"})
    return rows

def crosswalk_pass_records(frame: pd.DataFrame, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    urls = {}
    for _, row in frame.iterrows():
        for key in ("source_url","evidence_url"):
            value = str(row.get(key) or "").strip()
            if value: urls.setdefault(value, []).append(row)
    rows = []
    for i, record in enumerate(records, 1):
        variant = str(record.get("model_variant") or "")
        source_urls = [u.strip() for u in str(record.get("source_urls") or "").split(",") if u.strip()]
        matched = [r for _, r in frame.iterrows() if str(r.get("vehicle_variant_id") or "") == variant or str(r.get("source_variant_id") or "") == variant]
        for url in source_urls:
            matched.extend(urls.get(url, []))
        ids = sorted({str(r.get("transaction_id")) for r in matched if str(r.get("transaction_id"))})
        canonical = sorted({str(r.get("canonical_variant_id")) for r in matched if str(r.get("canonical_variant_id"))})
        rows.append({"pass_id": f"sprint32_pass_{i:04d}", "source_variant": variant,
                     "supporting_transaction_count": len(ids), "supporting_transaction_ids": ",".join(ids[:100]),
                     "canonical_variants": ",".join(canonical), "recalculated_status": "UNVERIFIED",
                     "original_screening_result": record.get("screening_result","PASS"),
                     "reason": "canonical endpoint recalculation requires supported three-date evidence" if not canonical else "mapped_to_existing_input_lineage"})
    return rows

def analyze(frame: pd.DataFrame, output_dir: str = "run-output", legacy_pass_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out_dir = Path(output_dir)
    audit = audit_vins(frame)
    decoded, decode_summary = decode_vins(frame, out_dir)
    recovered = enrich_identity(frame, decoded)
    valuations = reconstruct_valuations(recovered)
    crosswalk = crosswalk_pass_records(recovered, legacy_pass_records or [])
    conflicts = audit.get("conflict_examples", [])
    summary = {**audit, **{f"decode_{k}": v for k,v in decode_summary.items()},
               "usable_manufacturer": int(recovered["recovered_manufacturer"].notna().sum()),
               "usable_model": int(recovered["recovered_model"].notna().sum()),
               "verified_canonical_variants": int(recovered.loc[recovered["classification"].eq("VERIFIED_CANONICAL"), "canonical_variant_id"].nunique()),
               "identity_quality_eligible_rows": int(recovered["identity_quality_gate"].eq("ELIGIBLE").sum()),
               "validated_24_month_returns": sum(r["screening_result"] == "PASS" for r in valuations),
               "validated_60_month_returns": sum(r["screening_result"] == "PASS" and r["return_60m_pct"] is not None for r in valuations),
               "original_pass_records": len(crosswalk),
               "pass_records_with_transaction_lineage": sum(r["supporting_transaction_count"] > 0 for r in crosswalk),
               "pass_records_surviving_canonical_validation": 0,
               "individual_purchase_opportunities": 0,
               "ranking_status": "blocked_without_vehicle_specific_current_purchase_evidence"}
    return {"summary": summary, "audit": audit, "decode_coverage": decode_summary,
            "recovered": recovered, "valuations": valuations, "crosswalk": crosswalk,
            "identity_conflicts": conflicts, "model_opportunities": [r for r in valuations if r["screening_result"] == "PASS"],
            "provisional_queue": [r for r in valuations if r["screening_result"] == "UNVERIFIED"]}