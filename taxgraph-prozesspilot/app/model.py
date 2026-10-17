"""Domain schema, legal references and graph validation.

All guards are declarative equality checks against approved signals; no eval().
The draft graph editor may change the topology but cannot introduce executable code.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def graph_checksum(graph: dict) -> str:
    """Stable across DB retrieval ordering; graph versions remain content-addressed."""
    return sha256({"label": graph["label"],
                   "nodes": sorted(graph["nodes"], key=lambda n: n["id"]),
                   "edges": sorted(graph["edges"], key=lambda e: e["id"])})


LEGAL = {
    "U20_1": {"label": "§ 20 Abs. 1 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Einbringung eines Betriebs, Teilbetriebs oder Mitunternehmeranteils gegen neue Anteile."},
    "U20_2": {"label": "§ 20 Abs. 2 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Gemeiner Wert als Grundregel; Buchwert- oder Zwischenwertansatz auf Antrag unter gesetzlichen Voraussetzungen."},
    "U20_2_1": {"label": "§ 20 Abs. 2 Satz 2 Nr. 1 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Spaetere Koerperschaftsteuerverstrickung bei der uebernehmenden Koerperschaft."},
    "U20_2_2": {"label": "§ 20 Abs. 2 Satz 2 Nr. 2 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Passivposten uebersteigen Aktivposten nicht; Eigenkapital bleibt unberuecksichtigt."},
    "U20_2_3": {"label": "§ 20 Abs. 2 Satz 2 Nr. 3 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Deutsches Besteuerungsrecht fuer die Veräusserung des eingebrachten Betriebsvermoegens bleibt gewahrt."},
    "U20_2_4": {"label": "§ 20 Abs. 2 Satz 2 Nr. 4 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Begrenzung sonstiger Gegenleistungen neben neuen Gesellschaftsanteilen."},
    "U20_APP": {"label": "§ 20 Abs. 2 Satz 3 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Antrag spaetestens bis zur erstmaligen Abgabe der steuerlichen Schlussbilanz bei dem zustaendigen Finanzamt."},
    "U20_6": {"label": "§ 20 Abs. 6 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__20.html", "summary": "Rueckbeziehung des steuerlichen Uebertragungsstichtags unter unterschiedlichen gesetzlichen Bedingungen."},
    "U22_1": {"label": "§ 22 Abs. 1 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__22.html", "summary": "Moeglicher Einbringungsgewinn I bei bestimmten Anteilsveraeusserungen innerhalb von sieben Jahren."},
    "U22_3": {"label": "§ 22 Abs. 3 UmwStG", "url": "https://www.gesetze-im-internet.de/umwstg_2006/__22.html", "summary": "Jaehrliche Nachweispflicht fuer sieben Jahre; gesetzliche Frist grundsaetzlich 31. Mai."},
    "BMF2025": {"label": "BMF-Umwandlungssteuererlass vom 02.01.2025", "url": "https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Koerperschaftsteuer_Umwandlungssteuer/2025-01-02-umwStE.pdf?__blob=publicationFile", "summary": "Verwaltungsauffassung zur Anwendung des Umwandlungssteuergesetzes."},
}

FACT_FIELDS = [
    {"key": "asset_type", "label": "Art des eingebrachten Vermögens", "section": "Einbringung", "type": "choice", "choices": [
        {"value": "betrieb", "label": "Betrieb"}, {"value": "teilbetrieb", "label": "Teilbetrieb"},
        {"value": "mitunternehmeranteil", "label": "Mitunternehmeranteil"}, {"value": "sonstiges", "label": "Sonstiges"},
    ], "help": "§ 20 Abs. 1: Betrieb, Teilbetrieb oder Mitunternehmeranteil."},
    {"key": "receiving_company", "label": "Übernehmende Einheit ist Kapitalgesellschaft oder Genossenschaft", "section": "Einbringung", "type": "boolean", "help": "Der Empfänger muss grundsätzlich die Rechtsform nach § 20 Abs. 1 erfüllen."},
    {"key": "new_shares", "label": "Neue Gesellschaftsanteile als Gegenleistung", "section": "Einbringung", "type": "boolean", "help": "Bloß bestehende Anteile oder eine reine Darlehensforderung reichen nicht aus."},
    {"key": "essential_assets", "label": "Alle funktional wesentlichen Betriebsgrundlagen übertragen", "section": "Einbringung", "type": "boolean", "help": "Umfang des übertragenen Betriebs anhand von Verträgen und Anlagenverzeichnis prüfen."},
    {"key": "future_corporate_tax", "label": "Spätere Körperschaftsteuerbesteuerung sichergestellt", "section": "Buchwertvoraussetzungen", "type": "boolean", "help": "§ 20 Abs. 2 Satz 2 Nr. 1 UmwStG."},
    {"key": "assets_ge_liabilities", "label": "Passivposten übersteigen Aktivposten nicht", "section": "Buchwertvoraussetzungen", "type": "boolean", "help": "§ 20 Abs. 2 Satz 2 Nr. 2 UmwStG (Eigenkapital nicht mitrechnen)."},
    {"key": "german_tax_right", "label": "Deutsches Besteuerungsrecht bleibt erhalten", "section": "Buchwertvoraussetzungen", "type": "boolean", "help": "§ 20 Abs. 2 Satz 2 Nr. 3 UmwStG."},
    {"key": "book_value", "label": "Buchwert des eingebrachten Betriebsvermögens (€)", "section": "Werte und Antrag", "type": "number", "help": "Für die Wertgrenze bei sonstigen Gegenleistungen; Entnahmen/Einlagen gesondert prüfen."},
    {"key": "other_consideration", "label": "Gemeiner Wert sonstiger Gegenleistungen (€)", "section": "Werte und Antrag", "type": "number", "help": "Zusätzliche Zahlungen, Darlehensforderungen usw. getrennt von neuen Anteilen."},
    {"key": "fair_value", "label": "Gemeiner Wert des eingebrachten Vermögens (€)", "section": "Werte und Antrag", "type": "number", "help": "Nur illustrative Rechengröße; kein vollständiges Bewertungsgutachten."},
    {"key": "application_timely", "label": "Buchwertantrag form- und fristgerecht gestellt", "section": "Werte und Antrag", "type": "boolean", "help": "§ 20 Abs. 2 Satz 3; bei noch offener Abgabe unbedingt gesondert prüfen."},
    {"key": "planned_disposal", "label": "Anteilsveräußerung innerhalb von sieben Jahren geplant", "section": "Nachfolgepflichten", "type": "boolean", "help": "Ein Ja löst einen § 22 Risikohinweis aus, nicht automatisch eine Sofortbesteuerung."},
]
FACT_INDEX = {f["key"]: f for f in FACT_FIELDS}
EXTRA_FACT_FIELDS = [
    {"key":"transaction_type","label":"Zivilrechtliche Einordnung","type":"choice","choices":[{"value":"ausgliederung","label":"Ausgliederung"},{"value":"sachgruendung","label":"Sachgründung"},{"value":"sonstiges","label":"Andere Gestaltung"}]},
    {"key":"effective_date","label":"Steuerlicher Übertragungsstichtag","type":"date"},
    {"key":"registration_date","label":"Anmeldung beim Handelsregister","type":"date"},
    {"key":"date_reviewed","label":"Stichtag und anwendbare Rückwirkung fachlich bestätigt","type":"boolean"},
    {"key":"taxpayer","label":"Betroffene Person (nur fiktiv)","type":"text"},
    {"key":"hidden_reserves","label":"Stille Reserven bei Einbringung (€)","type":"number"},
    {"key":"intermediate_value","label":"Wertansatz laut historischer Lehrfalllösung (€)","type":"number"},
    {"key":"withdrawals","label":"Entnahmen im Rückwirkungszeitraum (€)","type":"number"},
    {"key":"transfer_costs","label":"Kosten des Vermögensübergangs (€)","type":"number"},
    {"key":"sale_date","label":"Datum der tatsächlichen Anteilsveräußerung","type":"date"},
    {"key":"sale_price","label":"Veräußerungspreis der Anteile (€)","type":"number"},
    {"key":"sale_costs","label":"Kosten der Anteilsveräußerung (€)","type":"number"},
]
for field in EXTRA_FACT_FIELDS:
    field.update(section="Rechtskontext und Rechtsfolgen", help="Synthetische Angabe; Nachweis und zeitlichen Rechtskontext beachten.")
FACT_INDEX.update({f["key"]: f for f in EXTRA_FACT_FIELDS})
CURRENT_CONTEXT = "demo-2026"
HISTORICAL_CONTEXT = "wlw-2020-2021"
CONTEXT_FIELDS = {
    CURRENT_CONTEXT: [f["key"] for f in FACT_FIELDS] + ["transaction_type","effective_date","registration_date","date_reviewed","taxpayer"],
    HISTORICAL_CONTEXT: [f["key"] for f in FACT_FIELDS] + [f["key"] for f in EXTRA_FACT_FIELDS],
}
SOURCE_SHA256 = "ad6038abda387bfddf483dfa96f64e37e9bf10b08daca63827f259edea938af1"
# The PDF is a workflow-learning reference, not an executable rule source.
# Do not advertise page links until a source endpoint and legal review exist.
SIGNALS = {
    "eligible_asset_type", "receiving_company", "new_shares", "essential_assets", "future_corporate_tax",
    "assets_ge_liabilities", "german_tax_right", "other_consideration_ok", "application_timely",
    "planned_disposal", "professional_review",
}
SIGNAL_FACTS = {signal: [signal] for signal in SIGNALS if signal in FACT_INDEX}
SIGNAL_FACTS.update(eligible_asset_type=["asset_type"], other_consideration_ok=["book_value", "other_consideration"],
                    professional_review=[])
# Only implemented executor handlers may pass graph publication validation.
HANDLER_FACTS = {"valuation": ["book_value", "fair_value"]}
NODE_KINDS = {"ACTION", "DECISION", "HUMAN_GATE", "TERMINAL"}
EDGE_RELATIONS = {"LEADS_TO", "TRIGGERS", "PROVIDES_INPUT_FOR", "CONVERGES_TO"}
EXECUTOR_VERSION = "1.0.1"
APP_VERSION = "1.1.0"
REASONING_EXECUTOR_VERSION = "1.2.0"


def reasoning_context(graph: dict) -> dict:
    return next((n.get("reasoning_context", {}) for n in graph["nodes"] if n["id"] == "START"), {})


def evaluate_guard(guard: dict, signals: dict[str, str]) -> bool:
    """Evaluate the stored declarative guard, including an explicit unknown signal."""
    if guard == {"operator": "always"}:
        return True
    if (isinstance(guard, dict) and set(guard) == {"operator", "signal", "value"}
            and guard["operator"] == "eq" and isinstance(guard["signal"], str)
            and guard["signal"] in signals):
        return signals[guard["signal"]] == guard["value"]
    raise ValueError("Kantenbedingung enthält kein auswertbares Prüfsignal.")


def _node(i: str, kind: str, title: str, subtitle: str, x: int, y: int, *, signal: str | None = None,
          legal: list[str] | None = None, handler: str | None = None) -> dict:
    return {"id": i, "kind": kind, "title": title, "description": subtitle, "x": x, "y": y,
            "signal": signal, "legal_refs": legal or [], "handler": handler}


def _edge(i: str, a: str, b: str, outcome: str, label: str = "", guidance: str = "", pitfalls: str = "") -> dict:
    return {"id": i, "source": a, "target": b, "outcome": outcome, "label": label or outcome,
            "relation": "LEADS_TO" if outcome == "always" or outcome in ("yes", "approved") else "TRIGGERS",
            "guidance": guidance, "pitfalls": pitfalls}


def seed_graph() -> dict:
    nodes = [
        _node("START", "ACTION", "Sachverhalt erfassen", "Fall und vorhandene Belege aufnehmen", 360, 40),
        _node("SCOPE", "DECISION", "Einbringungsgegenstand", "Betrieb / Teilbetrieb / Mitunternehmeranteil?", 360, 158, signal="eligible_asset_type", legal=["U20_1"]),
        _node("RECEIVER", "DECISION", "Übernehmende Einheit", "Kapitalgesellschaft oder Genossenschaft?", 360, 286, signal="receiving_company", legal=["U20_1"]),
        _node("SHARES", "DECISION", "Neue Anteile", "Werden neue Anteile gewährt?", 360, 414, signal="new_shares", legal=["U20_1"]),
        _node("ESSENTIAL", "DECISION", "Wesentliche Betriebsgrundlagen", "Alle erforderlichen Vermögenswerte übertragen?", 360, 542, signal="essential_assets", legal=["U20_1", "BMF2025"]),
        _node("CORPTAX", "DECISION", "Körperschaftsteuerverstrickung", "§ 20 Abs. 2 Satz 2 Nr. 1", 360, 670, signal="future_corporate_tax", legal=["U20_2_1"]),
        _node("BALANCE", "DECISION", "Aktiva / Passiva", "§ 20 Abs. 2 Satz 2 Nr. 2", 360, 798, signal="assets_ge_liabilities", legal=["U20_2_2"]),
        _node("TAXRIGHT", "DECISION", "Deutsches Besteuerungsrecht", "§ 20 Abs. 2 Satz 2 Nr. 3", 360, 926, signal="german_tax_right", legal=["U20_2_3"]),
        _node("CONSIDERATION", "DECISION", "Sonstige Gegenleistungen", "§ 20 Abs. 2 Satz 2 Nr. 4", 360, 1054, signal="other_consideration_ok", legal=["U20_2_4"]),
        _node("APPLICATION", "DECISION", "Buchwertantrag", "Antrag und gesetzliche Frist", 360, 1182, signal="application_timely", legal=["U20_APP"]),
        _node("VALUATION", "ACTION", "Wertansatz prüfen", "Stille Reserven nur illustrativ berechnen", 360, 1310, handler="valuation", legal=["U20_2"]),
        _node("DISPOSAL", "DECISION", "§ 22: Nachfolgepflichten", "Anteilsveräußerung innerhalb von 7 Jahren?", 360, 1438, signal="planned_disposal", legal=["U22_1", "U22_3"]),
        _node("REVIEW", "HUMAN_GATE", "Fachliche Freigabe", "Freigabe nur durch befugte Fachperson", 360, 1566, signal="professional_review", legal=["U20_2", "U22_3"]),
        _node("MISSING", "TERMINAL", "Belege nachfordern", "Unzureichende Tatsachengrundlage", 785, 315),
        _node("OUTSIDE", "TERMINAL", "Andere Einordnung prüfen", "§ 20 Anwendungsbereich nicht bestätigt", 40, 335),
        _node("BLOCKED", "TERMINAL", "Buchwertansatz nicht bestätigt", "Alternative Bewertung und Beratung", 35, 960),
        _node("PENDING", "TERMINAL", "Fachprüfung erforderlich", "Nur vorläufige Empfehlung", 770, 1590),
        _node("APPROVED", "TERMINAL", "Fachlich freigegeben", "Prüfpfad und Freigabe dokumentiert", 360, 1710),
        _node("REJECTED", "TERMINAL", "Nicht freigegeben", "Erneute fachliche Prüfung", 30, 1580),
    ]
    edges = [_edge("E_START", "START", "SCOPE", "always", "beginnen")]
    for src, next_node, negative, typ in [
        ("SCOPE", "RECEIVER", "OUTSIDE", "Anwendungsbereich"),
        ("RECEIVER", "SHARES", "OUTSIDE", "Empfängerkreis"),
        ("SHARES", "ESSENTIAL", "OUTSIDE", "Neue Anteile"),
        ("ESSENTIAL", "CORPTAX", "OUTSIDE", "Betriebsgrundlagen"),
        ("CORPTAX", "BALANCE", "BLOCKED", "Körperschaftsteuer"),
        ("BALANCE", "TAXRIGHT", "BLOCKED", "Bilanzrelation"),
        ("TAXRIGHT", "CONSIDERATION", "BLOCKED", "Besteuerungsrecht"),
        ("CONSIDERATION", "APPLICATION", "BLOCKED", "Wertgrenze"),
        ("APPLICATION", "VALUATION", "BLOCKED", "Antrag"),
    ]:
        edges += [
            _edge(f"E_{src}_YES", src, next_node, "yes", "Ja · weiter", f"{typ} als erfüllt dokumentieren und nächste Voraussetzung prüfen.", "Nicht bestätigte Tatsachen nicht als erfüllt behandeln."),
            _edge(f"E_{src}_NO", src, negative, "no", "Nein · abklären", f"Auswirkung der nicht erfüllten Voraussetzung {typ} fachlich prüfen.", "Keine endgültige steuerliche Würdigung ohne Fachprüfung."),
            _edge(f"E_{src}_UNKNOWN", src, "MISSING", "unknown", "Unklar · Nachweis", f"Belege für {typ} anfordern und anschließend neu prüfen.", "Fehlende Nachweise sind kein negativer Nachweis."),
        ]
    edges.append(_edge("E_VALUATION", "VALUATION", "DISPOSAL", "always", "weiter"))
    for v, label in [("yes", "Ja · §22 Risiko"), ("no", "Nein · beobachten"), ("unknown", "Unbekannt · abklären")]:
        edges.append(_edge(f"E_DISPOSAL_{v.upper()}", "DISPOSAL", "REVIEW", v, label,
                           "§ 22 Folgen und jährliche Nachweise in die fachliche Freigabe aufnehmen.",
                           "Auch ohne geplanten Verkauf können weitere § 22 Ereignisse relevant sein."))
    for v, dst in [("approved", "APPROVED"), ("rejected", "REJECTED"), ("pending", "PENDING")]:
        edges.append(_edge(f"E_REVIEW_{v.upper()}", "REVIEW", dst, v,
                           {"approved": "Freigegeben", "rejected": "Abgelehnt", "pending": "Freigabe offen"}[v]))
    node_index = {n["id"]: n for n in nodes}
    for e in edges:
        signal = node_index[e["source"]].get("signal")
        e["guard"] = {"operator": "eq", "signal": signal, "value": e["outcome"]} if signal else {"operator": "always"}
    return {"label": "§ 20 UmwStG — Einbringung Einzelunternehmen in GmbH", "nodes": nodes, "edges": edges}


def validate_graph(graph: dict) -> list[str]:
    errors = []
    if not isinstance(graph, dict):
        return ["Graph muss ein JSON-Objekt sein."]
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["Graph benötigt Arrays nodes und edges."]
    if not (2 <= len(nodes) <= 250 and 1 <= len(edges) <= 1250):
        errors.append("Erlaubt sind 2–250 Knoten und 1–1250 Kanten.")
    if not isinstance(graph.get("label"), str) or not (2 <= len(graph["label"].strip()) <= 180):
        errors.append("Graph benötigt eine Bezeichnung mit 2–180 Zeichen.")
    # Reject malformed types before using user-supplied values as dictionary keys.
    for n in nodes:
        if not isinstance(n, dict):
            errors.append("Jeder Knoten muss ein JSON-Objekt sein.")
            continue
        if not isinstance(n.get("id"), str) or not 1 <= len(n["id"].strip()) <= 80:
            errors.append("Jeder Knoten benötigt eine ID mit 1–80 Zeichen.")
        if not isinstance(n.get("kind"), str):
            errors.append("Knotentyp muss Text sein.")
        for key in ("signal", "handler"):
            if n.get(key) is not None and not isinstance(n[key], str):
                errors.append(f"Knotenfeld {key} muss Text oder null sein.")
    for e in edges:
        if not isinstance(e, dict):
            errors.append("Jede Kante muss ein JSON-Objekt sein.")
            continue
        for key in ("id", "source", "target", "outcome", "relation"):
            if not isinstance(e.get(key), str) or not 1 <= len(e[key].strip()) <= 80:
                errors.append(f"Kantenfeld {key} muss Text mit 1–80 Zeichen sein.")
    if errors:
        return errors
    ids = set()
    node_by_id = {}
    for n in nodes:
        if not isinstance(n, dict) or not isinstance(n.get("id"), str):
            errors.append("Jeder Knoten benötigt eine ID."); continue
        nid = n["id"]
        if nid in ids:
            errors.append(f"Doppelte Knoten-ID: {nid}")
        ids.add(nid)
        node_by_id[nid] = n
        if n.get("kind") not in NODE_KINDS:
            errors.append(f"{nid}: Ungültiger Knotentyp.")
        if n.get("kind") in ("DECISION", "HUMAN_GATE") and n.get("signal") not in SIGNALS:
            errors.append(f"{nid}: Signal nicht zulässig.")
        if n.get("kind") == "DECISION" and n.get("signal") == "professional_review":
            errors.append(f"{nid}: Freigabesignal nur in HUMAN_GATE zulässig.")
        if n.get("kind") == "HUMAN_GATE" and n.get("signal") != "professional_review":
            errors.append(f"{nid}: HUMAN_GATE benötigt professional_review.")
        if n.get("kind") in ("ACTION", "TERMINAL") and n.get("signal") is not None:
            errors.append(f"{nid}: Aktionen und Ergebnisse dürfen kein Prüfsignal enthalten.")
        if n.get("handler") is not None and n.get("handler") not in HANDLER_FACTS:
            errors.append(f"{nid}: Handler nicht unterstützt.")
        if n.get("handler") is not None and n.get("kind") != "ACTION":
            errors.append(f"{nid}: Berechnung nur in einem ACTION-Knoten zulässig.")
        if not isinstance(n.get("title"), str) or not (2 <= len(n["title"].strip()) <= 120):
            errors.append(f"{nid}: Titel fehlt oder ist zu lang.")
        if not isinstance(n.get("description"), str) or len(n["description"]) > 1000:
            errors.append(f"{nid}: Beschreibung fehlt oder ist zu lang.")
        if any(type(n.get(axis)) not in (int, float) or not math.isfinite(n.get(axis, 0)) or not 0 <= n.get(axis, 0) <= 5000 for axis in ("x", "y")):
            errors.append(f"{nid}: Ungültige Graph-Koordinaten.")
        if not isinstance(n.get("legal_refs"), list):
            errors.append(f"{nid}: Rechtsquellen müssen eine Liste sein.")
        else:
            for ref in n["legal_refs"]:
                if not isinstance(ref, str) or ref not in LEGAL:
                    errors.append(f"{nid}: Unbekannte Rechtsquelle {ref}.")
    if "START" not in node_by_id or node_by_id["START"].get("kind") != "ACTION":
        errors.append("Ein ACTION-Knoten mit ID START ist erforderlich.")
    if not any(n.get("kind") == "TERMINAL" for n in nodes if isinstance(n, dict)):
        errors.append("Mindestens ein TERMINAL-Knoten ist erforderlich.")
    edge_ids = set()
    outgoing = defaultdict(list)
    adjacency = defaultdict(list)
    for e in edges:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str):
            errors.append("Jede Kante benötigt eine ID."); continue
        eid = e["id"]
        if eid in edge_ids:
            errors.append(f"Doppelte Kanten-ID: {eid}")
        edge_ids.add(eid)
        src, dst = e.get("source"), e.get("target")
        if src not in node_by_id or dst not in node_by_id:
            errors.append(f"{eid}: Quelle/Ziel existiert nicht."); continue
        outgoing[src].append(e)
        adjacency[src].append(dst)
        source_signal = node_by_id[src].get("signal")
        expected_guard = ({"operator": "eq", "signal": source_signal, "value": e.get("outcome")}
                          if source_signal else {"operator": "always"})
        if e.get("guard") != expected_guard:
            errors.append(f"{eid}: Guard muss dem Quellknoten-Signal und Kanten-Ausgang exakt entsprechen.")
        if e.get("outcome") not in ("always", "yes", "no", "unknown", "approved", "pending", "rejected"):
            errors.append(f"{eid}: Ungültige Bedingung.")
        if e.get("relation") not in EDGE_RELATIONS:
            errors.append(f"{eid}: Unbekannter Relationstyp.")
        for attr in ("label", "guidance", "pitfalls"):
            if not isinstance(e.get(attr), str) or len(e[attr]) > 2000:
                errors.append(f"{eid}: {attr} muss Text mit höchstens 2000 Zeichen sein.")
    for n in nodes:
        if not isinstance(n, dict) or "id" not in n: continue
        out = outgoing[n["id"]]
        kind = n.get("kind")
        found = sorted(e.get("outcome") for e in out if isinstance(e.get("outcome"), str))
        expected = {"ACTION": ["always"], "DECISION": ["no", "unknown", "yes"],
                    "HUMAN_GATE": ["approved", "pending", "rejected"], "TERMINAL": []}.get(kind)
        if expected is not None and found != expected:
            errors.append(f"{n['id']}: Erforderliche Ausgänge {expected}; erhalten {found}.")
    if "START" in node_by_id:
        seen = set()
        q = deque(["START"])
        while q:
            nid = q.popleft()
            if nid in seen: continue
            seen.add(nid)
            q.extend(adjacency[nid])
        orphan = ids - seen
        if orphan:
            errors.append("Nicht erreichbar von START: " + ", ".join(sorted(orphan)))
        # Hackathon runtime deliberately supports only DAGs, preventing uncontrolled loops.
        color = {}
        def visit(nid: str) -> bool:
            if color.get(nid) == 1: return True
            if color.get(nid) == 2: return False
            color[nid] = 1
            for dst in adjacency[nid]:
                if visit(dst): return True
            color[nid] = 2
            return False
        if visit("START"):
            errors.append("Zyklen sind in dieser MVP-Ausführung nicht zulässig.")
    # A configurable graph may alter most routing decisions, but never grant a
    # positive finding by bypassing the separate expert approval gate.
    for safe_target, required_source, required_outcome in (
        ("APPROVED", "REVIEW", "approved"),
        ("PENDING", "REVIEW", "pending"),
        ("REJECTED", "REVIEW", "rejected"),
    ):
        if safe_target in node_by_id:
            if node_by_id[safe_target].get("kind") != "TERMINAL":
                errors.append(f"{safe_target}: Muss ein TERMINAL-Knoten sein.")
            incoming = [e for e in edges if isinstance(e, dict) and e.get("target") == safe_target]
            if not incoming or any(e.get("source") != required_source or e.get("outcome") != required_outcome for e in incoming):
                errors.append(f"{safe_target}: Nur nach fachlicher Freigabeprüfung über {required_source} ({required_outcome}) erreichbar.")
    return errors
