"""Sprint 30: mandatory historical-appreciation gate and NSX investigation."""
from __future__ import annotations
from typing import Any
import pandas as pd
from .sprint29 import analyze as analyze_sprint29

NSX_REPEAT_EVIDENCE = [{
    "variant": "Acura NSX NA1 3.0 manual, 1991",
    "physical_vehicle_id": "JH4NA1152MT001527",
    "transmission": "5-speed manual",
    "mileage_2024": 66000,
    "price_2024_usd": 72000.0,
    "date_2024": "2024-10-19",
    "mileage_2026": 68000,
    "price_2026_usd": 86500.0,
    "date_2026": "2026-06-26",
    "return_24m_pct": round((86500/72000-1)*100, 2),
    "screening_result": "FAIL",
    "source_urls": [
        "https://bringatrailer.com/listing/1991-acura-nsx-253/",
        "https://bringatrailer.com/listing/1991-acura-nsx-305/"
    ],
    "evidence_note": "Same chassis, source-reported clean title and 66k/68k miles. Repeat-sale evidence independently verifies appreciation above 5%."
}]

WATCHLIST_AUDIT = [
    ("Dodge Viper Gen 1 RT/10","dodge_viper_gen1"),
    ("Acura NSX 1991-2005","acura_nsx_1991_2005"),
    ("BMW E30 M3","bmw_m3_e30"),
    ("Porsche 996 GT3","porsche_911_996_gt3"),
    ("Mazda RX-7 FD Turbo","mazda_rx7_fd"),
    ("Honda S2000 AP1","honda_s2000"),
    ("Toyota Supra A80 Twin Turbo","toyota_supra_mk4"),
    ("Dodge Viper RT/10 NA1","dodge_viper_rt10_na1"),
    ("Porsche 944 Turbo manual","porsche_944_turbo"),
    ("Porsche 996.2 GT3 manual","porsche_996_2_gt3_manual"),
    ("Acura NSX NA1 automatic","acura_nsx_na1_automatic"),
]

ADDITIONAL_RESEARCH = [
    ("BMW","850CSi","E31"),("Chevrolet","Corvette ZR-1","C4"),
    ("Chevrolet","Camaro IROC-Z","Z28"),("Ford","Mustang SVT Cobra R","SN95"),
    ("Jaguar","XJS V12","X300/X308"),("Mitsubishi","Lancer Evolution IX","CT9A"),
    ("Nissan","300ZX Z32","Z32"),("Subaru","Impreza 22B","GC8"),
    ("Volkswagen","Golf R32","Mk4"),
]

def _gate(r: dict[str, Any]) -> str:
    value = r.get("return_24m_pct")
    if value is None or pd.isna(value):
        return "UNVERIFIED"
    return "PASS" if float(value) <= 5.0 else "FAIL"

def _audit_row(name: str, cohort: str, by_cohort: dict[str, dict[str, Any]]) -> dict[str, Any]:
    # The NA1 suffix is incompatible with the broad source cohort and remains unresolved.
    if cohort == "dodge_viper_rt10_na1":
        return {"candidate": name, "corrected_variant": None, "screening_result": "UNVERIFIED",
                "classification_issue": "incompatible NA1 nomenclature; source crosswalk required",
                "evidence_gap": "no defensible source-defined cohort mapping"}
    r = by_cohort.get(cohort)
    if r is None:
        return {"candidate": name, "corrected_variant": cohort, "screening_result": "UNVERIFIED",
                "classification_issue": "no matching valuation cohort in production snapshot",
                "evidence_gap": "historical endpoint or source-defined variant missing"}
    return {"candidate": name, "corrected_variant": cohort, "screening_result": _gate(r),
            "current_adjusted_value_usd": r.get("current_adjusted_value_usd"),
            "value_2024_usd": r.get("prior24_adjusted_value_usd"),
            "value_2021_usd": r.get("prior60_adjusted_value_usd"),
            "return_24m_pct": r.get("return_24m_pct"),
            "return_60m_pct": r.get("return_60m_pct"),
            "comparable_sale_count": r.get("current_comparables"),
            "confidence": r.get("data_confidence"),
            "supporting_source_urls": r.get("supporting_source_urls"),
            "classification_issue": "broad cohort retained only for diagnostics; generation/gearbox split still required"
                if cohort == "acura_nsx_1991_2005" else ""}

def analyze(frame: pd.DataFrame, as_of: str = "2026-11-20", min_comparables: int = 3, top_n: int = 20) -> dict[str, Any]:
    base = analyze_sprint29(frame, as_of=as_of, min_comparables=min_comparables, top_n=top_n)
    vals = base["valuations"]
    by_cohort = {str(r["model_variant"]): r for r in vals}
    for r in vals:
        r["historical_gate_status"] = _gate(r)
        r["qualification_order"] = "historical_gate_before_forecast_and_ranking"
    qualified = [r for r in vals if r["historical_gate_status"] == "PASS" and r.get("current_adjusted_value_usd") is not None]
    excluded = [r for r in vals if r["historical_gate_status"] == "FAIL"]
    unverified = [r for r in vals if r["historical_gate_status"] == "UNVERIFIED"]
    # A broad NSX family cohort cannot be promoted; the repeat sale independently fails the rule.
    nsx = dict(NSX_REPEAT_EVIDENCE[0])
    audit = [_audit_row(n, c, by_cohort) for n, c in WATCHLIST_AUDIT]
    audit.append({"candidate":"Acura NSX NA1 manual repeat-sale evidence", **nsx})
    additional = [{"manufacturer":m,"model":mo,"generation":g,"screening_result":"UNVERIFIED",
                   "research_priority":"high","evidence_gap":"targeted 2024 and 2026 completed-sale endpoint research required"}
                  for m,mo,g in ADDITIONAL_RESEARCH]
    summary = dict(base["summary"])
    summary.update({
        "supported_24m_returns": sum(r["historical_gate_status"] != "UNVERIFIED" for r in vals),
        "pass_24m_gate": len(qualified),
        "fail_24m_gate": len(excluded),
        "unverified_24m_gate": len(unverified),
        "qualified_model_opportunities": len(qualified),
        "excluded_model_variants": len(excluded),
        "unverified_research_queue": len(unverified) + len(additional),
        "historical_gate_enforced": True,
        "ranking_population": "PASS only",
        "nsx_repeat_sale_result": "FAIL",
        "individual_purchase_opportunities": 0,
        "analytical_acceptance": False if not qualified else bool(qualified),
    })
    for r in qualified:
        r["screening_result"] = "PASS"
        r["candidate_class"] = "qualified_model_opportunity"
    for r in excluded:
        r["screening_result"] = "FAIL"
        r["candidate_class"] = "excluded_over_5pct"
    for r in unverified:
        r["screening_result"] = "UNVERIFIED"
        r["candidate_class"] = "unverified_research_queue"
    return {
        "summary": summary,
        "qualified_model_opportunities": qualified,
        "excluded_model_variants": excluded,
        "unverified_research_queue": unverified + additional,
        "historical_valuations": vals,
        "historical_returns": base["historical_returns"],
        "forecast_scenarios": [r for r in base["forecast_scenarios"] if r.get("model_variant") in {x.get("model_variant") for x in qualified}],
        "individual_purchase_opportunities": [],
        "watchlist_audit": audit,
        "nsx_investigation": NSX_REPEAT_EVIDENCE,
        "title_population": base["title_population"],
        "legacy_valuation_reconciliation": base["legacy_reconciliation"],
        "data_coverage": base["coverage"],
        "method_version": "s30_historical_gate_before_forecast_v1",
        "limitations": [
            "The production snapshot still has sparse time-balanced endpoint coverage.",
            "NSX configurations must be split before a family-level valuation can be treated as investment-grade.",
            "Five-year scenarios remain judgment-based and are not calibrated probabilities.",
            "No individual purchase opportunity is promoted without vehicle-specific due diligence."
        ],
    }
