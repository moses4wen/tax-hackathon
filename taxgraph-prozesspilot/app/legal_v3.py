"""Version-pinned functional legal assessor (historical V2 remains unchanged); multi-entity supplement for the synthetic §20 UmwStG case.

Not an assessment of real clients.  Legal rules are explicit, deterministic and versioned;
unknown or conflicted facts never satisfy an assessment.  Per-asset AfA, final taxes,
§17 eligibility and complex §22 replacement events intentionally require expert review.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Mapping
from .valuation import valuation_inputs, allocate, amount as parse_amount

ENGINE_VERSION = "3.0.0-functional-demo"
LAW_AS_OF = "2026-10-17"
SUPPORTED_YEARS = {2025, 2026}

SOURCES = {
    "ESTG16": ("§ 16 EStG", "https://www.gesetze-im-internet.de/estg/__16.html"),
    "ESTG4": ("§ 4 EStG", "https://www.gesetze-im-internet.de/estg/__4.html"),
    "ESTG17": ("§ 17 EStG", "https://www.gesetze-im-internet.de/estg/__17.html"),
    "ESTG34": ("§ 34 EStG", "https://www.gesetze-im-internet.de/estg/__34.html"),
    "UMWG152": ("§ 152 UmwG", "https://www.gesetze-im-internet.de/umwg_1995/__152.html"),
    "UMWSTG1": ("§ 1 Abs. 3/4 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__1.html"),
    "UMWSTG20_1": ("§ 20 Abs. 1 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__20.html"),
    "UMWSTG20_2": ("§ 20 Abs. 2 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__20.html"),
    "UMWSTG20_3": ("§ 20 Abs. 3 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__20.html"),
    "UMWSTG20_4": ("§ 20 Abs. 4 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__20.html"),
    "UMWSTG20_5": ("§ 20 Abs. 5 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__20.html"),
    "UMWSTG20_6": ("§ 20 Abs. 6 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__20.html"),
    "UMWSTG22_1": ("§ 22 Abs. 1 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__22.html"),
    "UMWSTG22_3": ("§ 22 Abs. 3 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__22.html"),
    "UMWSTG23": ("§ 23 UmwStG", "https://www.gesetze-im-internet.de/umwstg_2006/__23.html"),
    "KSTG27": ("§ 27 KStG", "https://www.gesetze-im-internet.de/kstg_1977/__27.html"),
    "BMF2025": ("BMF-Umwandlungssteuererlass 02.01.2025", "https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Koerperschaftsteuer_Umwandlungssteuer/2025-01-02-umwStE.pdf?__blob=publicationFile"),
}

# These are supplemental facts. Existing 12 original case facts are inherited by the API.
EXTRA_FIELDS = [
    ("transaction_type", "Rechtsform der Übertragung", "choice", "Struktur", ["ausgliederung", "einzelrechtsnachfolge", "andere"]),
    ("registered_merchant", "Einzelkaufmann im Handelsregister eingetragen", "bool", "Struktur", None),
    ("registration_effective", "Ausgliederung tatsächlich im Handelsregister eingetragen", "bool", "Struktur", None),
    ("register_entry_date", "Tatsächlicher Tag der Eintragung der Ausgliederung", "date", "Struktur", None),
    ("liabilities_not_exceed_assets", "Verbindlichkeiten überschreiten Vermögen nicht (§ 152 UmwG)", "bool", "Struktur", None),
    ("recipient_eu_eea", "Sitz und Geschäftsleitung der Übernehmerin in EU/EWR (§ 1 Abs. 4)", "bool", "Struktur", None),
    ("contributor_eu_eea", "Einbringender EU/EWR-ansässig ohne abkommensrechtliche Drittstaatenansässigkeit", "bool", "Struktur", None),
    ("german_tax_right_received_shares", "Deutsches Besteuerungsrecht an erhaltenen Anteilen nicht beschränkt", "bool", "Struktur", None),
    ("retroactive_requested", "Steuerliche Rückwirkung beantragt", "bool", "Stichtag", None),
    ("tax_transfer_date", "Gewünschter steuerlicher Übertragungsstichtag", "date", "Stichtag", None),
    ("register_filing_date", "Anmeldung zum Handelsregister (§ 20 Abs. 6)", "date", "Stichtag", None),
    ("contract_date", "Abschluss Einbringungsvertrag", "date", "Stichtag", None),
    ("economic_transfer_date", "Übergang wirtschaftliches Eigentum", "date", "Stichtag", None),
    ("profit_method", "Bisherige Gewinnermittlung", "choice", "Bilanz & Wert", ["bilanz", "eur"]),
    ("valuation_choice", "Beantragter Wertansatz", "choice", "Bilanz & Wert", ["buchwert", "zwischenwert", "gemeiner_wert"]),
    ("intermediate_value", "Zwischenwert (€)", "money", "Bilanz & Wert", None),
    ("transfer_costs", "Kosten des Vermögensübergangs (€)", "money", "Bilanz & Wert", None),
    ("withdrawals", "Buchwert Entnahmen nach Stichtag (§ 20 Abs. 5) (€)", "money", "Bilanz & Wert", None),
    ("contributions", "Wert Einlagen nach Stichtag (§ 20 Abs. 5) (€)", "money", "Bilanz & Wert", None),
    ("capital_reserve_contribution", "Zuführung zur Kapitalrücklage, falls belegt (€)", "money", "Bilanz & Wert", None),
    ("event_type", "Sperrfrist-Ereignis", "choice", "§ 22 Lifecycle", ["keines", "anteilsverkauf", "ersatzereignis", "nachweis_versaeumt"]),
    ("event_date", "Datum des Sperrfrist-Ereignisses", "date", "§ 22 Lifecycle", None),
    ("disposal_fraction", "Veräußerter Anteil (0–1)", "fraction", "§ 22 Lifecycle", None),
    ("share_sale_proceeds", "Veräußerungserlös der Anteile (€)", "money", "§ 22 Lifecycle", None),
    ("share_sale_costs", "Kosten der Anteilsveräußerung (€)", "money", "§ 22 Lifecycle", None),
    ("section17_applies", "§ 17 EStG-Anwendungsbereich fachlich bestätigt", "bool", "§ 22 Lifecycle", None),
]
EXTRA_FIELDS += [
    ("recipient_formed_eu_eea", "Gruendung der Uebernehmerin nach EU/EWR-Recht", "bool", "Struktur", None),
    ("individual_business", "Natuerliche Person / Einzelunternehmen (MVP-Geltungsbereich)", "bool", "Struktur", None),
    ("tax_liabilities", "Steuerliche Passivposten ohne Eigenkapital (EUR)", "money", "Aufstockung", None),
    ("asset_schedule", "Vollstaendiger Anlagenspiegel (JSON)", "schedule", "Aufstockung", None),
    ("use_actual_transfer_date", "Tatsaechlichen Stichtag statt unzulaessiger Rueckwirkung verwenden", "bool", "Stichtag", None),
    ("contains_real_estate", "Grundstuecke im eingebrachten Vermoegen", "bool", "Weitere Rechtsfolgen", None),
]



def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _num(v: Any) -> Decimal:
    if isinstance(v, bool) or isinstance(v, (dict, list)):
        raise ValueError("Wert muss eine endliche Zahl sein.")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError):
        raise ValueError("Wert muss eine Zahl sein.") from None
    if not d.is_finite() or abs(d) >= Decimal("1000000000000"):
        raise ValueError("Wert außerhalb des zulässigen Zahlenbereichs.")
    return d


def _cents(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _euros(d: Decimal | None) -> float | None:
    return None if d is None else float(_cents(d))


def _add_years(day: date, years: int) -> date:
    y = day.year + years
    return date(y, day.month, min(day.day, calendar.monthrange(y, day.month)[1]))


def _add_months(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + day.month - 1 + months, 12)
    m += 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def _all(*statuses: str) -> str:
    if "CONFLICTED" in statuses:
        return "CONFLICTED"
    if "NOT_SATISFIED" in statuses:
        return "NOT_SATISFIED"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "SATISFIED"


def _logical_or(*statuses: str) -> str:
    if "SATISFIED" in statuses:
        return "SATISFIED"
    if "CONFLICTED" in statuses:
        return "CONFLICTED"
    if "UNKNOWN" in statuses:
        return "UNKNOWN"
    return "NOT_SATISFIED"


def _bool_status(value: Any, state: str) -> str:
    if state != "CONFIRMED":
        return state if state == "CONFLICTED" else "UNKNOWN"
    if not isinstance(value, bool):
        raise ValueError("Bestätigte Ja/Nein-Angabe hat keinen Boolean-Wert.")
    return "SATISFIED" if value else "NOT_SATISFIED"


def _record(value: Any) -> dict:
    if not isinstance(value, dict):
        return {"value": None, "verification": "unknown", "evidence_ref": ""}
    verification = value.get("verification", "unknown")
    if verification not in {"unknown", "reported", "confirmed"}:
        raise ValueError("Ungültiger Nachweisstatus.")
    evidence = value.get("evidence_ref") or ""
    if not isinstance(evidence, str) or len(evidence) > 500:
        raise ValueError("Nachweisreferenz ungültig.")
    observations = value.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 10:
        raise ValueError("Beobachtungen ungültig.")
    if observations:
        # Conservative: even agreeing additional observations require reconciliation.
        return {"value": value.get("value"), "verification": verification, "evidence_ref": evidence, "observations": observations}
    return {"value": value.get("value"), "verification": verification, "evidence_ref": evidence.strip()}


def _state(rec: dict) -> str:
    if rec.get("observations") or rec["verification"] == "conflicted":
        return "CONFLICTED"
    if rec["verification"] == "confirmed" and rec["evidence_ref"] and rec["value"] is not None:
        return "CONFIRMED"
    return "UNKNOWN"


class Graph:
    """Materialized proof graph. Typed edges carry actual semantic dependencies."""
    def __init__(self, facts: Mapping[str, dict]):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.assessments: list[dict] = []
        self.events: list[dict] = []
        for law_id, (title, url) in SOURCES.items():
            self.node("LAW:" + law_id, "LegalProvision", title, {"url": url, "law_as_of": LAW_AS_OF})
        for key in sorted(facts):
            f = facts[key]
            self.node("FACT:" + key, "Fact", key, f)
            if f["evidence_ref"]:
                evidence_id = "EVIDENCE:" + key
                self.node(evidence_id, "Evidence", f["evidence_ref"], {"reference": f["evidence_ref"]})
                self.edge(evidence_id, "FACT:" + key, "SUPPORTS" if _state(f) == "CONFIRMED" else "ALLEGES")

    def node(self, node_id: str, kind: str, label: str, data: dict | None = None) -> str:
        if node_id in self.nodes:
            raise ValueError("Doppelte Graph-ID: " + node_id)
        self.nodes[node_id] = {"id": node_id, "kind": kind, "label": label, "data": data or {}}
        return node_id

    def edge(self, source: str, target: str, relation: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("Graph-Endpunkt fehlt.")
        eid = f"{source}|{relation}|{target}"
        if eid in self.edges:
            return
        self.edges[eid] = {"id": eid, "source": source, "target": target, "relation": relation}

    def test(self, code: str, label: str, status: str, reason: str, *, fields: tuple[str, ...] = (),
             legal: tuple[str, ...] = (), depends: tuple[str, ...] = ()) -> str:
        check_id = "TEST:" + code
        assessment_id = "ASSESS:" + code
        self.node(check_id, "LegalTest", label, {"legal_ids": list(legal), "input_fields": list(fields)})
        self.node(assessment_id, "Assessment", label, {"status": status, "reason": reason})
        for field in fields:
            if "FACT:" + field in self.nodes:
                self.edge("FACT:" + field, check_id, "INPUT_TO")
        for law in legal:
            self.edge("LAW:" + law, check_id, "GOVERNS")
        for d in depends:
            self.edge("ASSESS:" + d, check_id, "INPUT_TO")
        self.edge(check_id, assessment_id, "EVALUATES")
        item = {"code": code, "label": label, "status": status, "reason": reason,
                "legal_ids": list(legal), "fact_keys": list(fields), "dependencies": list(depends)}
        self.assessments.append(item)
        self.events.append({"kind": "ASSESSMENT_EVALUATED", "assessment": item})
        return code

    def output(self, kind: str, code: str, label: str, data: dict, *, legal: tuple[str, ...] = (),
               depends: tuple[str, ...] = ()) -> None:
        identifier = kind.upper() + ":" + code
        self.node(identifier, kind, label, data)
        for law in legal:
            self.edge("LAW:" + law, identifier, "GOVERNS")
        for d in depends:
            if "ASSESS:" + d in self.nodes:
                self.edge("ASSESS:" + d, identifier, "TRIGGERS")
            elif "DECISION:" + d in self.nodes:
                self.edge("DECISION:" + d, identifier, "TRIGGERS")
        self.events.append({"kind": kind.upper() + "_DERIVED", "code": code, "data": data})

    def export(self) -> dict:
        return {"schema": "LegalReasoningGraph-2", "nodes": [self.nodes[k] for k in sorted(self.nodes)],
                "edges": [self.edges[k] for k in sorted(self.edges)]}


def assess(raw_facts: Mapping[str, Any], *, as_of: str = LAW_AS_OF) -> dict:
    """Run deterministic reasoning; return a reproducible, tamper-checkable record.

    All case facts use {value,verification,evidence_ref}. As-of is a deterministic
    simulation date, not a fact which can be used to certify legal effectiveness.
    """
    if not isinstance(raw_facts, Mapping) or len(raw_facts) > 100:
        raise ValueError("Maximal 100 Tatsachen erlaubt.")
    try:
        today = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        raise ValueError("as_of muss ISO-Datum sein.") from None
    f = {str(key): _record(value) for key, value in raw_facts.items()}
    g = Graph(f)

    def read(key: str, typ: str = "bool") -> tuple[Any, str]:
        r = f.get(key, {"value": None, "verification": "unknown", "evidence_ref": ""})
        state = _state(r)
        if state != "CONFIRMED":
            return None, state
        val = r["value"]
        if typ == "bool":
            if not isinstance(val, bool):
                raise ValueError(f"{key}: Ja/Nein erwartet.")
        elif typ == "date":
            try:
                val = date.fromisoformat(val)
            except (ValueError, TypeError):
                raise ValueError(f"{key}: Datum YYYY-MM-DD erwartet.") from None
        elif typ in ("money", "signed_money"):
            val = parse_amount(val)
            if typ == "money" and val < 0:
                raise ValueError(f"{key}: Betrag muss >= 0 sein.")
        elif typ == "fraction":
            val = _num(val)
            if val <= 0 or val > 1:
                raise ValueError(f"{key}: Anteil muss > 0 und <= 1 sein.")
        elif typ == "choice":
            if not isinstance(val, str) or len(val) > 100:
                raise ValueError(f"{key}: Auswahl ungültig.")
        return val, state

    def test_bool(code: str, label: str, key: str, law: tuple[str, ...]) -> str:
        value, state = read(key)
        outcome = _bool_status(value, state)
        g.test(code, label, outcome, f"{key}: {outcome}", fields=(key,), legal=law)
        return outcome

    trans, trans_state = read("transaction_type", "choice")
    trans_status = "UNKNOWN" if trans_state == "UNKNOWN" else "CONFLICTED" if trans_state == "CONFLICTED" else (
        "SATISFIED" if trans in ("ausgliederung", "einzelrechtsnachfolge") else "NOT_SATISFIED")
    g.test("TRANSACTION", "Zivilrechtliche Transaktionsart", trans_status,
           "§ 1 Abs. 3 Nr. 2 für Ausgliederung, Nr. 4 für Einzelrechtsnachfolge; andere Vorgänge manuell prüfen.",
           fields=("transaction_type",), legal=("UMWSTG1", "UMWG152"))

    if trans == "ausgliederung":
        merchant = test_bool("MERCHANT", "e.K. im Handelsregister", "registered_merchant", ("UMWG152",))
        solvency = test_bool("CIVIL_SOLVENCY", "Keine Überschuldung im Sinn des § 152 UmwG", "liabilities_not_exceed_assets", ("UMWG152",))
        registered, registered_state = read("registration_effective")
        entry, entry_state = read("register_entry_date", "date")
        filing, filing_state = read("register_filing_date", "date")
        if "CONFLICTED" in (registered_state, entry_state, filing_state):
            reg_status = "CONFLICTED"
        elif registered_state == "CONFIRMED" and registered is False:
            reg_status = "NOT_SATISFIED"
        elif registered_state != "CONFIRMED" or entry is None or filing is None:
            reg_status = "UNKNOWN"
        elif entry < filing:
            reg_status = "NOT_SATISFIED"
        else:
            reg_status = "SATISFIED"
        g.test("CIVIL_EFFECT", "Ausgliederung wirksam eingetragen", reg_status,
               "§ 152 UmwG in Verbindung mit Registereintragung. Anmeldung und Eintragung sind getrennte Ereignisse; Eintragung nicht vor Anmeldung.",
               fields=("registration_effective", "register_entry_date", "register_filing_date"),
               legal=("UMWG152",))
        civil = _all(merchant, solvency, reg_status)
        civil_deps = ("MERCHANT", "CIVIL_SOLVENCY", "CIVIL_EFFECT")
        civil_fields = ("registered_merchant", "liabilities_not_exceed_assets", "registration_effective", "register_entry_date")
    elif trans == "einzelrechtsnachfolge":
        civil = "SATISFIED"  # This ONLY means §152 UmwG is not the selected branch.
        civil_deps = ()
        civil_fields = ("transaction_type",)
    else:
        civil, civil_deps, civil_fields = "UNKNOWN", (), ("transaction_type",)
    g.test("CIVIL", "Zivilrechtlicher Grundpfad", _all(trans_status, civil),
           "Ausgliederung benötigt Handelsregister-Eintragung und § 152-Vermögensrelation; bei Einzelrechtsnachfolge gesonderte Formpflichten offen.",
           fields=civil_fields, legal=("UMWG152", "UMWSTG1"), depends=("TRANSACTION",) + civil_deps)

    asset, asset_state = read("asset_type", "choice")
    asset_status = asset_state if asset_state == "CONFLICTED" else "UNKNOWN" if asset_state == "UNKNOWN" else (
        "SATISFIED" if asset in ("betrieb", "teilbetrieb", "mitunternehmeranteil") else "NOT_SATISFIED")
    g.test("ASSET", "Betrieb, Teilbetrieb oder Mitunternehmeranteil", asset_status,
           "Nur qualifizierte Einbringungsgegenstände gem. § 20 Abs. 1.", fields=("asset_type",), legal=("UMWSTG20_1",))
    receiver = test_bool("RECEIVER", "Kapitalgesellschaft/Genossenschaft", "receiving_company", ("UMWSTG20_1",))
    shares = test_bool("SHARES", "Neue Gesellschaftsanteile", "new_shares", ("UMWSTG20_1",))
    essential = test_bool("ESSENTIAL", "Funktional wesentliche Betriebsgrundlagen übertragen", "essential_assets", ("UMWSTG20_1", "BMF2025"))
    entity_eu = test_bool("ENTITY_EU_EEA", "Übernehmerin mit Sitz/Geschäftsleitung EU/EWR", "recipient_eu_eea", ("UMWSTG1",))
    person_eu = test_bool("PERSON_EU_EEA", "Einbringender EU/EWR und nicht abkommensrechtlich Drittstaat", "contributor_eu_eea", ("UMWSTG1",))
    german_right = test_bool("SHARE_TAX_RIGHT", "Deutsches Besteuerungsrecht an neuen Anteilen erhalten", "german_tax_right_received_shares", ("UMWSTG1",))
    formed = test_bool("ENTITY_FORMED", "EU/EWR-Gruendungsrecht", "recipient_formed_eu_eea", ("UMWSTG1",))
    domain = test_bool("DEMO_SCOPE", "Natuerliche Person / Einzelunternehmen", "individual_business", ("UMWSTG20_1",))
    personal = _all(entity_eu, formed, _logical_or(person_eu, german_right))
    g.test("PERSONAL", "Persönlicher Anwendungsbereich § 1 Abs. 4", personal,
           "Übernehmerin EU/EWR plus alternativ begünstigter Einbringender oder unverändertes deutsches Besteuerungsrecht an Anteilen.",
           legal=("UMWSTG1",), depends=("ENTITY_EU_EEA", "ENTITY_FORMED", "PERSON_EU_EEA", "SHARE_TAX_RIGHT"))
    eligibility = _all(domain, trans_status, civil, asset_status, receiver, shares, essential, personal)
    g.test("ELIGIBILITY", "§ 20 Abs. 1 i.V.m. § 1 Abs. 3/4", eligibility,
           "Kumulatives Ergebnis aus zivilrechtlichem Pfad, qualifiziertem Vermögen, neuen Anteilen und persönlichem Anwendungsbereich.",
           legal=("UMWSTG1", "UMWSTG20_1"), depends=("DEMO_SCOPE", "TRANSACTION", "CIVIL", "ASSET", "RECEIVER", "SHARES", "ESSENTIAL", "PERSONAL"))

    retro_request, retro_state = read("retroactive_requested")
    requested_day, day_state = read("tax_transfer_date", "date")
    actual_key = "register_entry_date" if trans == "ausgliederung" else "economic_transfer_date"
    actual_day, actual_state = read(actual_key, "date")
    fallback, fallback_state = read("use_actual_transfer_date")
    stichtag = requested_day
    references = ("register_filing_date",) if trans == "ausgliederung" else ("contract_date", "economic_transfer_date")
    limits = [read(key, "date") for key in references]
    if "CONFLICTED" in (retro_state, day_state, actual_state, *(state for _, state in limits)):
        requested_retro = "CONFLICTED"
    elif requested_day is None or actual_day is None or retro_state != "CONFIRMED":
        requested_retro = "UNKNOWN"
    elif retro_request is False:
        requested_retro = "SATISFIED" if requested_day == actual_day else "NOT_SATISFIED"
    elif any(day is None for day, _ in limits):
        requested_retro = "UNKNOWN"
    else:
        requested_retro = "SATISFIED" if requested_day <= actual_day and all(
            requested_day <= day <= _add_months(requested_day, 8) for day, _ in limits) else "NOT_SATISFIED"
    g.test("RETROACTIVE_REQUEST", "Beantragte Rueckwirkung", requested_retro,
           "UmwG: Registeranmeldung; Einzelrechtsnachfolge: Vertrag UND wirtschaftlicher Uebergang.",
           fields=("retroactive_requested", "tax_transfer_date", actual_key) + references,
           legal=("UMWSTG20_5", "UMWSTG20_6"), depends=("TRANSACTION",))
    retro = requested_retro
    if requested_retro == "NOT_SATISFIED" and fallback is True and fallback_state == "CONFIRMED" and actual_state == "CONFIRMED":
        stichtag, retro = actual_day, "SATISFIED"
    legal_date = "CONFLICTED" if day_state == "CONFLICTED" else "UNKNOWN" if stichtag is None else (
        "SATISFIED" if stichtag.year in SUPPORTED_YEARS else "UNKNOWN")
    g.test("LAW_VERSION", "Zeitliche Rechtsfassung", legal_date,
           "Unterstuetzter Stichtag 2025/2026; andere Normfassungen nicht automatisch bestaetigt.",
           fields=("tax_transfer_date", actual_key), legal=("UMWSTG1", "BMF2025"))
    g.test("RETROACTIVE", "Wirksamer steuerlicher Stichtag", _all(retro, legal_date),
           "Tatsaechlicher Stichtag nur nach ausdruecklicher, belegter Auswahl; Originalangabe bleibt erhalten.",
           fields=("use_actual_transfer_date", actual_key), legal=("UMWSTG20_5", "UMWSTG20_6"),
           depends=("RETROACTIVE_REQUEST", "LAW_VERSION"))
    retro = _all(retro, legal_date)
    effective_date = {"requested": requested_day.isoformat() if requested_day else None,
                      "effective": stichtag.isoformat() if stichtag else None,
                      "fallback_applied": stichtag != requested_day,
                      "request_status": requested_retro}

    corp = test_bool("CORPTAX", "Spätere Körperschaftsteuerverstrickung", "future_corporate_tax", ("UMWSTG20_2",))
    inputs = valuation_inputs(f)
    balance = inputs["balance"]
    g.test("BALANCE", "Buchwert netto nicht negativ", balance, "Numerische Bilanzrelation; Gegenangaben fuehren zu Konflikt.", fields=("book_value", "assets_ge_liabilities"), legal=("UMWSTG20_2",))
    taxright = test_bool("TAXRIGHT", "Deutsches Besteuerungsrecht des Betriebsvermögens", "german_tax_right", ("UMWSTG20_2",))
    application = test_bool("APPLICATION", "Fristgerechter Antrag auf niedrigeren Wertansatz", "application_timely", ("UMWSTG20_2",))

    book, book_state = read("book_value", "signed_money")
    fair, fair_state = read("fair_value", "money")
    consideration, consideration_state = read("other_consideration", "money")
    transfer_cost, tc_state = read("transfer_costs", "money")
    withdrawal, withdrawal_state = read("withdrawals", "money")
    contribution, contribution_state = read("contributions", "money")
    val_choice, val_state = read("valuation_choice", "choice")
    inter, inter_state = read("intermediate_value", "money")
    profit, profit_state = read("profit_method", "choice")
    reserve, reserve_state = read("capital_reserve_contribution", "money")

    numbers_status = inputs["status"]
    adjusted = book - withdrawal + contribution if all(x is not None for x in (book, withdrawal, contribution)) else None
    minimum = _num(inputs["minimum_net_value"]) if inputs["minimum_net_value"] is not None else None
    allowed = _num(inputs["allowed_consideration"]) if inputs["allowed_consideration"] is not None else None
    cons_state = inputs["consideration_status"]
    capacity = inputs["capacity_status"]
    balance_resolved = "CONFLICTED" if balance == "CONFLICTED" else capacity
    g.test("VALUATION_INPUTS", "Wertabstimmung und Anlagenspiegel", numbers_status, inputs["note"],
           fields=("book_value", "fair_value", "withdrawals", "contributions", "tax_liabilities", "asset_schedule"),
           legal=("UMWSTG20_2", "UMWSTG20_5", "BMF2025"))
    g.test("CONSIDERATION_LIMIT", "Grenze sonstiger Gegenleistungen", cons_state,
           "Ueberschreitung erzwingt gegebenenfalls anteiligen Zwischenwert; nicht pauschal gemeiner Wert (UmwStE 20.19a).",
           fields=("book_value", "other_consideration"), legal=("UMWSTG20_2", "BMF2025"), depends=("VALUATION_INPUTS",))
    g.test("AUFSTOCKUNG", "Ausgleich des Passivueberhangs / Mindestwert", balance_resolved,
           inputs["note"], fields=("book_value", "fair_value", "asset_schedule", "tax_liabilities"),
           legal=("UMWSTG20_2", "BMF2025"), depends=("BALANCE", "VALUATION_INPUTS", "CONSIDERATION_LIMIT"))
    book_eligible = _all(eligibility, legal_date, retro, corp, balance_resolved, taxright, application, numbers_status)
    if profit != "bilanz" or profit_state != "CONFIRMED":
        book_eligible = _all(book_eligible, "UNKNOWN")
    g.test("LOW_VALUE", "Niedriger Wertansatz inklusive Pflichtaufstockung", book_eligible,
           "Einheitlicher Mindestwert; keine Umgehung von Kapazitaet, Nachweisen oder Besteuerungsrechten.",
           legal=("UMWSTG20_2", "BMF2025"), depends=("ELIGIBILITY", "LAW_VERSION", "RETROACTIVE", "CORPTAX", "AUFSTOCKUNG", "TAXRIGHT", "APPLICATION"))

    baseline: dict = {"entity": "Einbringender", "year": stichtag.year if stichtag else None,
                      "legal_ids": ["ESTG16", "ESTG4"], "type": "REFERENCE_ONLY", "gain": None}
    if book is not None and fair is not None and transfer_cost is not None and withdrawal == 0 and contribution == 0:
        baseline["gain"] = _euros(fair - book - transfer_cost)
        baseline["type"] = "SIMPLIFIED_GROSS_GAIN"
    g.output("TaxConsequence", "BASELINE", "Schritt 0: Normalbesteuerung ohne UmwStG", baseline,
             legal=("ESTG16", "ESTG4"), depends=("VALUATION_INPUTS",))
    if profit_state == "CONFIRMED" and profit == "eur":
        g.output("Obligation", "ACCRUAL_SWITCH", "Wechsel § 4 Abs. 3 auf § 4 Abs. 1 prüfen",
                 {"subject": "Einbringender", "status": "REVIEW_REQUIRED", "note": "Übergangsgewinn und Schlussbilanz gesondert ermitteln."},
                 legal=("ESTG4",), depends=("ELIGIBILITY",))

    valuation_options: list[dict] = []
    scenario_values: dict[str, Decimal | None] = {
        "buchwert": minimum,
        "zwischenwert": inter,
        "gemeiner_wert": fair,
    }
    for choice in ("buchwert", "zwischenwert", "gemeiner_wert"):
        selected = scenario_values[choice]
        status = _all(eligibility, legal_date, retro, numbers_status)
        if choice != "gemeiner_wert":
            status = _all(status, book_eligible)
        if choice == "zwischenwert":
            if inter_state == "CONFLICTED":
                status = "CONFLICTED"
            elif inter is None or minimum is None or fair is None:
                status = _all(status, "UNKNOWN")
            elif not (minimum <= inter <= fair and book < inter):
                status = _all(status, "NOT_SATISFIED")
        if choice == "gemeiner_wert" and selected is None:
            status = _all(status, "UNKNOWN")
        if selected is not None and consideration is not None and selected < consideration:
            status = _all(status, "NOT_SATISFIED")
        # Nonzero post-effective-date adjustments require reconciling individual asset values.
        calculations_supported = withdrawal == 0 and contribution == 0
        if not calculations_supported and status == "SATISFIED":
            status = "UNKNOWN"
        option: dict = {"mode": choice, "status": status, "transferred_tax_value": _euros(selected),
                        "valuation_gain_preliminary": None, "new_share_cost_basis_preliminary": None,
                        "warnings": []}
        if selected is not None and book is not None and transfer_cost is not None and tc_state == "CONFIRMED" and calculations_supported:
            option["valuation_gain_preliminary"] = _euros(selected - book - transfer_cost)
            if consideration is not None:
                option["new_share_cost_basis_preliminary"] = _euros(selected - consideration)
        if transfer_cost is None:
            option["warnings"].append("Vermögensübergangskosten fehlen; Veräußerungsgewinn nicht bezifferbar.")
        if not calculations_supported:
            option["warnings"].append("Entnahmen/Einlagen ungleich null: Wertansatz und Anteils-AK müssen individuell abgestimmt werden.")
        if choice != "gemeiner_wert" and status != "SATISFIED":
            option["warnings"].append("Niedriger Wertansatz derzeit nicht nachgewiesen.")
        valuation_options.append(option)
        decision_dependencies = (("LOW_VALUE", "VALUATION_INPUTS", "LAW_VERSION", "RETROACTIVE") if choice != "gemeiner_wert"
                                 else ("ELIGIBILITY", "VALUATION_INPUTS", "LAW_VERSION", "RETROACTIVE"))
        g.output("Decision", "VALUATION_" + choice.upper(), "Wertansatz " + choice, option,
                 legal=("UMWSTG20_2", "UMWSTG20_3"), depends=decision_dependencies)

    if val_state == "CONFLICTED":
        selected_status = "CONFLICTED"
    elif val_choice not in scenario_values:
        selected_status = "UNKNOWN"
    else:
        selected_status = next(o["status"] for o in valuation_options if o["mode"] == val_choice)
    g.test("SELECTED_VALUE", "Ausgewählter Wertansatz anwendbar", selected_status,
           "Nur erfüllte, belegte Variante darf als vorläufige steuerliche Berechnung behandelt werden.",
           fields=("valuation_choice", "intermediate_value"), legal=("UMWSTG20_2",),
           depends=("LOW_VALUE", "VALUATION_INPUTS") if val_choice in ("buchwert", "zwischenwert")
           else ("ELIGIBILITY", "VALUATION_INPUTS", "LAW_VERSION", "RETROACTIVE"))
    selected_option = next((o for o in valuation_options if o["mode"] == val_choice), None)
    valuation = scenario_values.get(val_choice)
    requested_mode = val_choice
    effective_mode = ("gemeiner_wert" if valuation is not None and fair is not None and valuation == fair
                      else "zwischenwert" if valuation is not None and book is not None and valuation > book else val_choice)
    allocation = inputs["asset_allocation"]
    if selected_status == "SATISFIED" and valuation is not None and f.get("asset_schedule", {}).get("verification") == "confirmed":
        liabilities, liability_state = read("tax_liabilities", "money")
        if liabilities is not None:
            allocation_status, allocation = allocate(f["asset_schedule"]["value"], liabilities, book, fair, valuation)
            if allocation_status != "SATISFIED":
                raise ValueError("Anlagenspiegel fuer ausgewaehlten Wert nicht abstimmbar.")
    val_choice = effective_mode
    tax_year = stichtag.year if stichtag else None

    gmbh: dict = {"entity": "Übernehmende GmbH", "year": tax_year, "tax_basis": None,
                  "afa_treatment": "REVIEW_REQUIRED", "steuerliches_einlagekonto": "REVIEW_REQUIRED",
                  "capital_reserve_reported": _euros(reserve), "tax_loss_carryovers_transferable": False}
    contributor: dict = {"entity": "Einbringender", "year": tax_year, "gross_gain_preliminary": None,
                         "new_share_cost_basis_preliminary": None,
                         "section16_4_34": "REVIEW_REQUIRED"}
    if selected_status == "SATISFIED" and selected_option is not None:
        gmbh["tax_basis"] = selected_option["transferred_tax_value"]
        gmbh["afa_treatment"] = {
            "buchwert": "§ 23 Abs. 1: Rechtsnachfolge, AfA-Fortführung einzelwirtschaftsgutbezogen",
            "zwischenwert": "§ 23 Abs. 3: angepasste AfA-Bemessungsgrundlagen je Wirtschaftsgut",
            "gemeiner_wert": "§ 23 Abs. 4: Einzelrechtsnachfolge = fiktive Neuanschaffung; Ausgliederung nach UmwG = § 23 Abs. 3 entsprechend",
        }[val_choice]
        contributor["gross_gain_preliminary"] = selected_option["valuation_gain_preliminary"]
        contributor["new_share_cost_basis_preliminary"] = selected_option["new_share_cost_basis_preliminary"]
        contributor["section16_4_34"] = "POTENTIALLY_APPLICABLE_SUBJECT_TO_EXPERT_CHECK" if val_choice == "gemeiner_wert" else "NOT_APPLICABLE_TO_LOW_VALUATION"
    g.output("TaxConsequence", "GMBH", "Schritt 4: Übernehmende GmbH", gmbh,
             legal=("UMWSTG23", "KSTG27"), depends=("SELECTED_VALUE",))
    g.output("TaxConsequence", "CONTRIBUTOR", "Schritt 5: Einbringender", contributor,
             legal=("UMWSTG20_3", "UMWSTG20_4", "ESTG16", "ESTG34"), depends=("SELECTED_VALUE",))

    # § 22 Abs. 3: deadlines follow anniversary and the next 31 May. Never assume filing.
    obligations: list[dict] = []
    if stichtag and selected_status == "SATISFIED" and val_choice != "gemeiner_wert":
        for year in range(1, 8):
            anniv = _add_years(stichtag, year)
            deadline_year = anniv.year if anniv < date(anniv.year, 5, 31) else anniv.year + 1
            deadline = date(deadline_year, 5, 31)
            ob = {"period": year, "reference_date": anniv.isoformat(), "deadline": deadline.isoformat(),
                  "filing_state": "UNKNOWN", "due_relative_to_as_of": "OVERDUE_UNVERIFIED" if deadline < today else "UPCOMING_OR_TODAY"}
            obligations.append(ob)
            g.output("Obligation", "PROOF_" + str(year), f"§ 22-Nachweis Zeitjahr {year}", ob,
                     legal=("UMWSTG22_3", "BMF2025"), depends=("SELECTED_VALUE",))

    event_type, ev_state = read("event_type", "choice")
    event_date, ed_state = read("event_date", "date")
    fraction, frac_state = read("disposal_fraction", "fraction")
    proceeds, proceeds_state = read("share_sale_proceeds", "money")
    costs, sale_costs_state = read("share_sale_costs", "money")
    sec17, sec17_state = read("section17_applies")
    sperrfrist = {"mode": event_type, "status": "NOT_ASSESSED", "event_year": event_date.year if event_date else None,
                  "completed_time_years": None, "einbringungsgewinn_I": None,
                  "additional_share_acquisition_costs": None, "share_sale_gain_preliminary": None,
                  "retroactive_tax_year": tax_year, "fraction": _euros(fraction), "expert_review": True}
    if selected_status == "SATISFIED" and val_choice == "gemeiner_wert":
        sperrfrist["status"] = "NOT_APPLICABLE_FAIR_VALUE"
    elif selected_status != "SATISFIED":
        sperrfrist["status"] = "BLOCKED_BY_VALUATION"
    elif ev_state == "CONFLICTED":
        sperrfrist["status"] = "CONFLICTED"
    elif event_type is None:
        sperrfrist["status"] = "UNKNOWN_EVENT"
    elif event_type == "keines":
        sperrfrist["status"] = "MONITORING_REQUIRED"
    elif event_type == "anteilsverkauf":
        if ed_state == "CONFLICTED" or frac_state == "CONFLICTED":
            sperrfrist["status"] = "CONFLICTED"
        elif event_date is None or fraction is None or stichtag is None:
            sperrfrist["status"] = "MISSING_EVENT_FACTS"
        elif event_date < stichtag:
            sperrfrist["status"] = "INVALID_EVENT_DATE"
        elif event_date >= _add_years(stichtag, 7):
            sperrfrist["status"] = "OUTSIDE_SEVEN_YEARS"
        elif fair is None or valuation is None or transfer_cost is None or tc_state != "CONFIRMED":
            sperrfrist["status"] = "MISSING_FINANCIAL_FACTS"
        else:
            completed = sum(_add_years(stichtag, n) <= event_date for n in range(1, 8))
            base = max(Decimal(0), fair - transfer_cost - valuation)
            amount = _cents(base * Decimal(7-completed) / Decimal(7) * fraction)
            sperrfrist.update(status="EGI_PRELIMINARY", completed_time_years=completed,
                               einbringungsgewinn_I=_euros(amount), additional_share_acquisition_costs=_euros(amount))
            # This is a *basis illustration*; no final ESt calculation or §17 determination.
            if proceeds is not None and costs is not None and selected_option and selected_option["new_share_cost_basis_preliminary"] is not None:
                original_ak = _num(selected_option["new_share_cost_basis_preliminary"])
                sperrfrist["share_sale_gain_preliminary"] = _euros(proceeds - costs - original_ak * fraction - amount)
            if sec17 is not True or sec17_state != "CONFIRMED":
                sperrfrist["share_sale_gain_note"] = "§ 17 EStG-Anwendbarkeit nicht bestätigt; nur rechnerische Illustration."
    else:
        sperrfrist["status"] = "MANUAL_EVENT_CLASSIFICATION"
    g.test("SPERRFRIST_EVENT", "§ 22 Abs. 1: Tatsächliches Ereignis", (
        "UNKNOWN" if sperrfrist["status"] in ("UNKNOWN_EVENT", "MISSING_EVENT_FACTS", "BLOCKED_BY_VALUATION", "MISSING_FINANCIAL_FACTS") else
        "CONFLICTED" if sperrfrist["status"] == "CONFLICTED" else
        "NOT_SATISFIED" if sperrfrist["status"] in ("INVALID_EVENT_DATE",) else "SATISFIED"),
        "Veräußerung innerhalb von sieben Zeitjahren: Rückwirkung und jährliche Siebtel; Ersatzveräußerungen und Nachweisfiktionen manuell prüfen.",
        fields=("event_type", "event_date", "disposal_fraction", "share_sale_proceeds", "share_sale_costs", "section17_applies"),
        legal=("UMWSTG22_1", "UMWSTG22_3"), depends=("SELECTED_VALUE",))
    g.output("TaxConsequence", "SPERRFRIST", "Schritt 6: § 22 Lifecycle", sperrfrist,
             legal=("UMWSTG22_1", "UMWSTG22_3", "UMWSTG20_3", "ESTG17"), depends=("SPERRFRIST_EVENT",))

    open_checks = [a for a in g.assessments if a["status"] in ("UNKNOWN", "CONFLICTED")]
    failed_checks = [a for a in g.assessments if a["status"] == "NOT_SATISFIED"]
    warnings = [
        "Nur synthetischer Lehrfall. Keine steuerliche Freigabe und keine Rechtsberatung.",
        "Automatische Werte sind vorläufig; § 16 EStG/§ 34 EStG/§ 17 EStG erfordern gesonderte steuerliche Subsumtion.",
        "AfA benötigt Wirtschaftsgut-Einzelwerte und Nutzungsdauern; § 27 KStG benötigt Kapital-/Einlagekonto-Abstimmung.",
        "§ 22 Ersatzveräußerungen, Nachweisfiktion, Ketteneinbringung und § 23 Abs. 2 Erhöhungsbetrag benötigen Fachentscheidung.",
        "Umsatzsteuer (§ 1 Abs. 1a UStG), ggf. GrESt und Gesellschafts-/Arbeitsrecht sind nicht abschließend geprüft.",
        "Hash-Werte schützen lokale Konsistenz, nicht vor einem privilegierten Datenbankadministrator.",
    ]
    if day_state == "CONFIRMED" and stichtag and stichtag.year not in SUPPORTED_YEARS:
        warnings.insert(0, "Nicht unterstützte historische Rechtsfassung: keine Freigabe.")
    if retro_request is False:
        warnings.append("Ohne beantragte steuerliche Rückwirkung muss der steuerliche Stichtag mit dem tatsächlichen Vermögensübergang übereinstimmen.")
    planned, _planned_state = read("planned_disposal")
    if planned is True:
        warnings.append("Im Ausgangsfall ist ein späterer Anteilverkauf geplant. Die aktuelle Ereignisprüfung ersetzt keine Prüfung des konkreten Verkaufs.")
    if any(x is not None and x < 0 for x in (withdrawal, contribution)):
        raise ValueError("Entnahmen und Einlagen müssen positiv angegeben werden.")
    overall = ("READY_FOR_EXPERT_REVIEW" if selected_status == "SATISFIED" else
               "INELIGIBLE_SELECTED_PATH" if selected_status == "NOT_SATISFIED" else
               "CONFLICTED_EVIDENCE" if selected_status == "CONFLICTED" else "EVIDENCE_REQUIRED")
    graph = g.export()
    result: dict = {
        "schema": "ProzessPilot-Legal-3", "engine_version": ENGINE_VERSION, "engine_file_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "law_as_of": LAW_AS_OF,
        "evaluation_date": today.isoformat(), "facts": f,
        "assessments": g.assessments, "events": g.events, "graph": graph,
        "baseline": baseline, "valuation_options": valuation_options,
        "selected": {"mode": requested_mode, "effective_mode": effective_mode, "status": selected_status, "overall": overall},
        "consequences": [gmbh, contributor], "sperrfrist": sperrfrist,
        "proof_obligations": obligations, "open_checks": open_checks, "failed_checks": failed_checks,
        "warnings": warnings,
        "source_urls": {key: {"title": v[0], "url": v[1]} for key, v in SOURCES.items()},
        "professional_approval": "PENDING_NOT_SUPPORTED_BY_AUTOMATION",
        "effective_date": effective_date,
        "minimum_valuation": inputs,
        "asset_allocation": allocation,
        "valuation_handler_sha256": hashlib.sha256(Path(__file__).with_name("valuation.py").read_bytes()).hexdigest(),
        "manual_topics": [
            {"topic": "Grunderwerbsteuer", "status": "REVIEW_REQUIRED" if not (f.get("contains_real_estate", {}).get("value") is False and _state(f["contains_real_estate"]) == "CONFIRMED") else "NOT_INDICATED", "automatic_tax": None},
            {"topic": "KStG27", "status": "RECONCILIATION_REQUIRED", "automatic_tax": None},
            {"topic": "Umsatzsteuer / Arbeitsrecht", "status": "OUTSIDE_AUTOMATED_SCOPE", "automatic_tax": None},
        ],
    }
    result["graph_hash"] = _hash(graph)
    result["facts_hash"] = _hash(f)
    result["result_hash"] = _hash(result)
    return result


def verify(record: Mapping[str, Any]) -> dict:
    """Integrity + deterministic replay, not independent legal review."""
    if not isinstance(record, Mapping):
        return {"valid": False, "reason": "Kein Dokument"}
    try:
        saved = dict(record)
        stored_hash = saved.pop("result_hash")
        integrity = (stored_hash == _hash(saved) and
                     saved["graph_hash"] == _hash(saved["graph"]) and
                     saved["facts_hash"] == _hash(saved["facts"]))
        replay = assess(saved["facts"], as_of=saved["evaluation_date"])
        deterministic = replay == dict(record)
        return {"valid": integrity and deterministic, "integrity": integrity,
                "deterministic_replay": deterministic,
                "external_trust_anchor": False}
    except (ValueError, KeyError, TypeError):
        return {"valid": False, "reason": "Export nicht reproduzierbar"}
