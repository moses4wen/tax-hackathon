"""Deterministic, graph-driven §20 UmwStG decision runner.

A graph supplies *all* nodes and transitions. A trusted signal resolver supplies
tri-state facts, without LLM branching or arbitrary code execution.
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_DOWN
from typing import Any

from .model import CURRENT_CONTEXT, EXECUTOR_VERSION, FACT_INDEX, LEGAL, canonical, evaluate_guard, sha256, validate_graph
from .storage import append_run_event, get_case, get_review, load_graph, now, uid


def _money_de(value) -> str:
    return f"{value:,.2f}".translate(str.maketrans({",": ".", ".": ","})) + " €"


def _evidence(facts: dict, key: str) -> dict:
    f = facts[key]
    return {"key": key, "value": f["value"], "verification": f["verification"], "evidence_ref": f["evidence_ref"]}


def _confirmed(facts: dict, key: str) -> Any:
    f = facts[key]
    if f["verification"] != "confirmed" or not f["evidence_ref"]:
        return None
    return f["value"]


def resolve(signal: str, facts: dict, review: str) -> dict:
    """Return stable outcome and underlying evidence. No unverified assertion passes."""
    if signal == "professional_review":
        return {"outcome": review, "reason": "Freigabe ist an Fallfakten und Graphversion gebunden.", "evidence": []}
    if signal == "eligible_asset_type":
        val = _confirmed(facts, "asset_type")
        return {"outcome": "unknown" if val is None else "yes" if val in ("betrieb", "teilbetrieb", "mitunternehmeranteil") else "no",
                "reason": "Qualifizierter Einbringungsgegenstand nach § 20 Abs. 1 erforderlich.",
                "evidence": [_evidence(facts, "asset_type")]}
    if signal == "other_consideration_ok":
        book = _confirmed(facts, "book_value")
        extra = _confirmed(facts, "other_consideration")
        ev = [_evidence(facts, "book_value"), _evidence(facts, "other_consideration")]
        if book is None or extra is None or book < 0 or extra < 0:
            return {"outcome": "unknown", "reason": "Bestätigte Werte für Buchwert und sonstige Gegenleistung erforderlich; negative Werte separat klären.", "evidence": ev}
        # §20(2) Satz 2 Nr.4: either 25% book value OR 500k, at most the book value.
        # The book value must first be professionally adjusted for §20(5) withdrawals/contributions.
        # Confirmed monetary facts are cents. Never round a fractional-cent
        # statutory limit upward and thereby admit an excessive consideration.
        book_decimal = Decimal(str(book))
        limit_a = (book_decimal / 4).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        limit_b = min(Decimal("500000"), book_decimal)
        allowed = max(limit_a, limit_b)
        return {"outcome": "yes" if Decimal(str(extra)) <= allowed else "no",
                "reason": f"Sonstige Gegenleistung {_money_de(extra)}; rechnerische Grenze in vollen Cent nach § 20 Abs. 2 Satz 2 Nr. 4: {_money_de(allowed)} (Alternative a: {_money_de(limit_a)}; b: {_money_de(limit_b)}). Entnahmen/Einlagen gesondert prüfen.",
                "evidence": ev, "calculation": {"book_value": book, "other_consideration": extra, "limit_a": float(limit_a), "limit_b": float(limit_b), "allowed": float(allowed)}}
    if signal not in FACT_INDEX:
        raise RuntimeError(f"Unbekanntes Signal im veröffentlichten Graph: {signal}")
    fact = facts[signal]
    value = _confirmed(facts, signal)
    return {"outcome": "unknown" if value is None else "yes" if value is True else "no",
            "reason": "Bestätigt aus Nachweis/Aktenvermerk." if value is not None else "Nicht bestätigt; automatische positive Würdigung gesperrt.",
            "evidence": [_evidence(facts, signal)]}


def valuation(facts: dict) -> dict:
    book = _confirmed(facts, "book_value")
    fair = _confirmed(facts, "fair_value")
    if book is None or fair is None:
        return {"available": False, "note": "Für den Wertvergleich fehlen bestätigte Werte; kein Steuerbetrag wird berechnet."}
    return {"available": True, "book_value": book, "fair_value": fair,
            "difference": round(fair - book, 2),
            "note": "Rechnerische Wertdifferenz; weder automatisch realisierter Gewinn noch Steuerbelastung. Sonstige Gegenleistungen, Veräußerungskosten und steuerliche Sonderregelungen fachlich prüfen."}


def _build_recommendation(final: str, path: list[str], facts: dict, decisions: list[dict],
                          value_calculation: dict | None, review: str, legal_sources: dict,
                          legal_ids: list[str]) -> dict:
    mapping = {
        "MISSING": ("NACHWEISE_FEHLEN", "Nachweise und Tatsachen ergänzen",
                    "Der Prüflauf wurde gestoppt, weil eine wesentliche Voraussetzung nicht durch bestätigte Angaben belegt ist."),
        "OUTSIDE": ("ANWENDUNGSBEREICH_OFFEN", "Anwendungsbereich des § 20 gesondert prüfen",
                    "Eine der geprüften Voraussetzungen des § 20 Abs. 1 ist nach den bestätigten Eingaben nicht erfüllt. Eine alternative Einordnung ist fachlich erforderlich."),
        "BLOCKED": ("BUCHWERT_NICHT_GESICHERT", "Buchwertansatz nicht bestätigt",
                    "Mindestens eine Voraussetzung für den beantragten Buchwertansatz ist nach den bestätigten Angaben nicht erfüllt. Den gemeinen Wert als gesetzliche Grundregel sowie mögliche andere Wertansätze prüfen."),
        "PENDING": ("FREIGABE_OFFEN", "Buchwertfortführung nach Prüfschema grundsätzlich möglich – Freigabe ausstehend",
                    "Die im begrenzten Prüfschema enthaltenen Voraussetzungen wurden mit bestätigten Demo-Angaben durchlaufen. Eine abschließende rechtliche und steuerliche Würdigung steht aus."),
        "APPROVED": ("FREIGEGEBEN_IM_PROTOTYP", "Freigabe im Prototyp dokumentiert",
                     "Für genau diese Daten- und Graphversion wurde eine benannte menschliche Freigabe dokumentiert. Das System bestätigt keine berufsrechtliche Qualifikation der freigebenden Person."),
        "REJECTED": ("FREIGABE_ABGELEHNT", "Fachliche Freigabe abgelehnt",
                     "Die fachliche Prüfung wurde abgelehnt. Bitte Bewertungsannahmen, Rechtsquellen und Belege korrigieren."),
    }
    status, title, text = mapping.get(final, ("MANUELL_PRUEFEN", "Fachprüfung erforderlich", "Kein abschließendes Ergebnis."))
    # Domain-level safety check independent of the editable topology. Even if a
    # draft is rerouted, a positive recommendation requires every §20 check.
    required = {
        "SCOPE": "eligible_asset_type", "RECEIVER": "receiving_company",
        "SHARES": "new_shares", "ESSENTIAL": "essential_assets",
        "CORPTAX": "future_corporate_tax", "BALANCE": "assets_ge_liabilities",
        "TAXRIGHT": "german_tax_right", "CONSIDERATION": "other_consideration_ok",
        "APPLICATION": "application_timely",
    }
    positives = {d["node_id"]: d for d in decisions if d.get("outcome") == "yes"}
    positive_path_safe = (all(positives.get(node_id, {}).get("signal") == signal for node_id, signal in required.items())
                          and "VALUATION" in path and "DISPOSAL" in path and "REVIEW" in path
                          and path.index("VALUATION") < path.index("DISPOSAL") < path.index("REVIEW"))
    if final in ("PENDING", "APPROVED") and not positive_path_safe:
        status, title, text = ("PRUEFPFAD_UNVOLLSTAENDIG", "Unvollständiger Prüfpfad – keine Freigabe",
                               "Der veröffentlichte Graph erreicht den positiven Abschluss ohne sämtliche erforderlichen § 20 Prüfschritte. Das Ergebnis wird sicherheitshalber gesperrt.")
    missing = []
    checked = []
    for d in decisions:
        if d["outcome"] == "unknown" and d["signal"] != "professional_review":
            req = [x["key"] for x in d["evidence"]]
            missing.extend([FACT_INDEX[k]["label"] for k in req if k in FACT_INDEX])
        if d["outcome"] == "yes": checked.append(d["node_title"])
    warnings = [
        "Nur Prototyp / keine Steuerberatung. §§ 20, 22 UmwStG sind einzelfallbezogen fachlich zu prüfen.",
        "Rechtsstand und Anwendbarkeit zum steuerlichen Übertragungsstichtag einschließlich § 27 UmwStG prüfen.",
        "Handels-/Gesellschaftsrecht, Bilanzierung, Umsatzsteuer, ggf. Grunderwerbsteuer, Arbeitsrecht und UmwG sind nicht abschließend modelliert.",
        "Der Nachweisstatus 'bestätigt' dokumentiert eine Nutzerangabe mit Belegreferenz, keine unabhängige Authentizitätsprüfung.",
    ]
    if status == "PRUEFPFAD_UNVOLLSTAENDIG":
        warnings.insert(0, "Sicherheitskontrolle: Ein positiver Prüfausgang setzt alle definierten § 20 Prüfschritte voraus.")
    if "DISPOSAL" in path:
        if _confirmed(facts, "planned_disposal") is True:
            warnings.insert(0, "Geplante Anteilsveräußerung innerhalb von sieben Jahren: mögliche rückwirkende Besteuerung als Einbringungsgewinn I nach § 22 Abs. 1 gesondert prüfen.")
        if _confirmed(facts, "planned_disposal") is None:
            warnings.insert(0, "Anteilsveräußerungsabsicht ungeklärt; § 22 Risiken gesondert erheben.")
        warnings.append("§ 22 Abs. 3 UmwStG: jährliche Nachweise in den folgenden sieben Jahren (grundsätzlich spätestens 31. Mai) organisatorisch einplanen.")
    if "APPLICATION" in path:
        warnings.append("Buchwertantrag: Frist und Zuständigkeit der erstmaligen steuerlichen Schlussbilanz gesondert kontrollieren.")
    if "SCOPE" in path:
        warnings.append("TaxGraph-Live-Anbindung ist nicht implementiert. Rechtsquellen sind lokal kuratiert und mit amtlichen URLs verlinkt.")
    refs = [{"id": ref, **legal_sources[ref]} for ref in dict.fromkeys(legal_ids)]
    return {"status": status, "title": title, "assessment": text,
            "confirmed_steps": checked, "missing_evidence": list(dict.fromkeys(missing)),
            "warnings": warnings, "valuation": value_calculation, "legal_sources": refs,
            "path": path, "approval": review,
            "recommended_action": ("Bitte fehlende Angaben fachlich nachfordern." if final == "MISSING" else
                                   "Alternative Gestaltung und Bewertung fachlich prüfen." if final in ("OUTSIDE", "BLOCKED") else
                                   "Freigabe durch befugte Steuerberatung dokumentieren." if status == "FREIGABE_OFFEN" else
                                   "Graphstruktur korrigieren und den Fall erneut prüfen." if status == "PRUEFPFAD_UNVOLLSTAENDIG" else
                                   "Fachliche Einordnung und Aktenführung fortsetzen.")}


def execute(c, case_id: str, graph_version: str) -> dict:
    """Persist execution and all transition evaluations in one DB transaction."""
    case = get_case(c, case_id)
    if not case["synthetic"] and __import__("os").environ.get("ALLOW_REAL_CASES") != "1":
        raise ValueError("Reale Mandantendaten in diesem MVP standardmäßig gesperrt.")
    if case["context_id"] != CURRENT_CONTEXT:
        raise ValueError("Für diesen historischen Rechtskontext ist noch kein ausführbares Prüfschema freigegeben. Der aktuelle Demonstrationsgraph darf nicht verwendet werden.")
    if any(fact.get("observations") for fact in case["facts"]):
        raise ValueError("Zusätzliche oder widersprüchliche Beobachtungen erfordern eine fachliche Klärung. Die vorhandene Engine wertet diese noch nicht aus; kein Prüflauf wurde angelegt.")
    obj = load_graph(c, graph_version)
    if obj["meta"]["status"] != "published":
        raise ValueError("Nur veröffentlichte Graphversionen können ausgeführt werden.")
    errors = validate_graph(obj)
    if errors:
        raise ValueError("Graph nicht ausführbar: " + "; ".join(errors))
    facts = {e["key"]: e for e in case["facts"]}
    fh = sha256(facts)
    review_record = get_review(c, case_id, graph_version, fh)
    reviewer = review_record["decision"] if review_record else "pending"
    legal_sources = {ref: dict(LEGAL[ref]) for ref in sorted({r for n in obj["nodes"] for r in n.get("legal_refs", [])})}
    run_id = uid("run")
    started_at = now()
    c.execute("""INSERT INTO runs(id,case_id,graph_version,graph_hash,facts_snapshot,facts_hash,status,started_at)
                 VALUES(?,?,?,?,?,?,?,?)""",
              (run_id, case_id, graph_version, obj["meta"]["checksum"], canonical(facts), fh, "running", started_at))
    append_run_event(c, run_id, "RUN_STARTED", {"graph_version": graph_version,
                                                 "graph_checksum": obj["meta"]["checksum"], "facts_hash": fh,
                                                 "case_id": case_id, "synthetic": case["synthetic"], "started_at": started_at,
                                                 "executor_version": EXECUTOR_VERSION,
                                                 "review_record": review_record, "legal_sources": legal_sources})
    nodes = {n["id"]: n for n in obj["nodes"]}
    outgoing: dict[str, list[dict]] = {n["id"]: [] for n in obj["nodes"]}
    for e in obj["edges"]: outgoing[e["source"]].append(e)
    current = "START"
    path = []
    decisions = []
    selected_edges = []
    val = None
    for i in range(len(nodes)):
        n = nodes[current]
        path.append(current)
        append_run_event(c, run_id, "NODE_ENTERED", {"node_id": current, "title": n["title"],
                                                      "kind": n["kind"], "legal_refs": n.get("legal_refs", [])})
        if n["kind"] == "TERMINAL":
            break
        signal_detail = None
        if n["kind"] in ("DECISION", "HUMAN_GATE"):
            signal_detail = resolve(n["signal"], facts, reviewer)
            signal_detail.update({"node_id": current, "node_title": n["title"], "signal": n["signal"],
                                  "legal_refs": n.get("legal_refs", [])})
            if n["kind"] == "HUMAN_GATE":
                signal_detail["review_record"] = review_record
            decisions.append(signal_detail)
            append_run_event(c, run_id, "SIGNAL_EVALUATED", signal_detail)
        if n.get("handler") == "valuation":
            val = valuation(facts)
            append_run_event(c, run_id, "CALCULATION", val)
        eligible = "always" if signal_detail is None else signal_detail["outcome"]
        signals = {n["signal"]: eligible} if signal_detail else {}
        candidates = [{"edge_id": e["id"], "source": current, "target": e["target"],
                       "outcome": e["outcome"], "guard": e["guard"], "guard_result": evaluate_guard(e["guard"], signals)}
                      for e in sorted(outgoing[current], key=lambda e:e["id"])]
        append_run_event(c, run_id, "GUARDS_EVALUATED", {"expected": eligible, "candidates": candidates})
        passed = {e["edge_id"] for e in candidates if e["guard_result"]}
        matching = [e for e in outgoing[current] if e["id"] in passed]
        if len(matching) != 1:
            raise RuntimeError(f"Graph ist nicht deterministisch an Knoten {current} ({eligible}).")
        edge = matching[0]
        selected_edges.append(edge["id"])
        append_run_event(c, run_id, "EDGE_SELECTED", {"edge_id": edge["id"], "from": current,
                                                       "to": edge["target"], "label": edge.get("label"),
                                                       "guidance": edge.get("guidance"),
                                                       "pitfalls": edge.get("pitfalls"),
                                                       "outcome": eligible})
        current = edge["target"]
    else:
        raise RuntimeError("Maximale Schrittlänge überschritten.")
    final = current
    legal_ids = [ref for nid in path for ref in nodes[nid].get("legal_refs", [])]
    recommendation = _build_recommendation(final, path, facts, decisions, val, reviewer, legal_sources, legal_ids)
    recommendation["selected_edges"] = selected_edges
    recommendation["case_title"] = case["title"]
    recommendation["case_description"] = case["description"]
    recommendation["run_id"] = run_id
    recommendation["graph_version"] = graph_version
    append_run_event(c, run_id, "RECOMMENDATION", {"status": recommendation["status"], "title": recommendation["title"],
                                                     "result_hash": sha256(recommendation),
                                                     "legal_source_ids": [r["id"] for r in recommendation["legal_sources"]]})
    finished_at = now()
    append_run_event(c, run_id, "RUN_FINISHED", {"terminal": final, "executed_nodes": len(path), "status": recommendation["status"], "finished_at": finished_at})
    c.execute("UPDATE runs SET result_json=?,status=?,finished_at=? WHERE id=?",
              (canonical(recommendation), recommendation["status"], finished_at, run_id))
    return {"run_id": run_id, "result": recommendation, "terminal": final}
