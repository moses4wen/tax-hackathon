"""Curated mapping of Ludwig's 2026-10-17 §20 procedural graph v3.

Not a live MCP import or a legal certification. Original remote IDs preserved.
The existing V2 legal assessment is authoritative for detailed §20 analysis.
"""
from __future__ import annotations

SOURCE = {
    "server": "https://34-38-10-198.sslip.io/#graphs",
    "graph": "einbringung_par20_umwstg",
    "version": "v3",
    "author": "ludwig",
    "node_count_observed": 17,
    "verification": "visible UI only; full edges/graph JSON not obtained",
}
MAPPING = [
    ("start", "START", "ENTRY", "SCOPE"),
    ("c_anwendungsbereich", "ELIGIBILITY", "CHECK", "ELIGIBILITY"),
    ("c_persoenlich", "PERSONAL", "CHECK", "PERSONAL"),
    ("c_gegenstand", "ASSET", "CHECK", "ASSET,ESSENTIAL"),
    ("c_neue_anteile", "SHARES", "CHECK", "SHARES"),
    ("c_antrag", "APPLICATION", "CHECK", "APPLICATION"),
    ("c_kst_sicher", "CORPTAX", "CHECK", "CORPTAX"),
    ("c_passivueberhang", "BALANCE", "CHECK", "BALANCE"),
    ("c_besteuerungsrecht", "SHARE_TAX_RIGHT", "CHECK", "SHARE_TAX_RIGHT"),
    ("c_sonstige_gegenleistung", "CONSIDERATION_LIMIT", "CHECK", "CONSIDERATION_LIMIT"),
    ("c_grenze_gegenleistung", "CONSIDERATION_LIMIT", "CHECK", "CONSIDERATION_LIMIT"),
    ("c_rueckwirkung", "RETROACTIVE", "CHECK", "RETROACTIVE"),
    ("c_aufstockung", "BALANCE", "CHECK", "BALANCE,SELECTED_VALUE"),
    ("r_nicht20", "ELIGIBILITY", "RESULT", "ELIGIBILITY"),
    ("r_gemeiner_wert", "VALUATION_GEMEINER_WERT", "RESULT", "SELECTED_VALUE"),
    ("r_stichtag", "RETROACTIVE", "RESULT", "RETROACTIVE"),
    ("r_buchwert", "VALUATION_BUCHWERT", "RESULT", "SELECTED_VALUE,GMBH,CONTRIBUTOR,SPERRFRIST"),
]
# Deliberately separate share tax right (§1(4)) from asset tax right (§20(2)).
MANDATORY_DISTINCTIONS = [
    {"external": "c_besteuerungsrecht", "rule": "SHARE_TAX_RIGHT", "field": "german_tax_right_received_shares",
     "not_equivalent_to": "TAXRIGHT", "law": "§ 1 Abs. 4 UmwStG"},
    {"external": None, "rule": "TAXRIGHT", "field": "german_tax_right",
     "not_equivalent_to": "SHARE_TAX_RIGHT", "law": "§ 20 Abs. 2 Satz 2 Nr. 3 UmwStG"},
]
OPEN_GAPS = [
    "External edge metadata not verified; no automatic graph replacement.",
    "Passivüberhang/Aufstockung needs a reviewed and tested numerical rule; no positive shortcut.",
    "§20(6) effective dates depend on transaction type; never use an unconditional eight-month check.",
    "Narrative results require split legal consequences by entity and year.",
]


def catalog() -> dict:
    return {
        "source": SOURCE,
        "mapping": [{"external_id": ext, "local_rule": local, "external_kind": kind,
                     "v2_dependency": target.split(",")} for ext, local, kind, target in MAPPING],
        "mandatory_distinctions": MANDATORY_DISTINCTIONS,
        "open_gaps": OPEN_GAPS,
        "status": "REVIEW_REQUIRED",
        "notice": "Fachlich zu prüfen; kein automatischer MCP-Import und keine Änderung veröffentlichter Graphen.",
    }
