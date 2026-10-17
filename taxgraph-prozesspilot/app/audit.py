"""Database-free verification of an exported execution, including deterministic replay.

Local hashes prove consistency, not authenticity against an administrator who can
rewrite the entire package. The verifier never trusts the exported verdict.
"""
from __future__ import annotations

from .model import EXECUTOR_VERSION, evaluate_guard, graph_checksum, sha256

CHECKS = ("graph_integrity", "event_chain_integrity", "facts_integrity", "result_integrity",
          "context_integrity", "execution_integrity")


def _require(condition: bool) -> None:
    # Verification must also work when Python is run with -O.
    if not condition:
        raise ValueError("Prüfpfad stimmt nicht mit seiner Ausführung überein.")


def source_snapshot(run: dict) -> dict | None:
    events = run.get("events", [])
    if events and events[0].get("event_type") == "RUN_STARTED":
        return events[0].get("detail", {}).get("legal_sources")
    return None


def _replay(run: dict, graph: dict, start: dict) -> bool:
    # Imported lazily to keep storage -> verifier -> executor dependencies acyclic.
    from .engine import _build_recommendation, resolve, valuation

    events = iter(run["events"][1:])
    nodes = {n["id"]: n for n in graph["nodes"]}
    review_record = start["review_record"]
    review = review_record["decision"] if review_record else "pending"
    facts = run["facts_snapshot"]
    path, chosen, decisions, legal_ids = [], [], [], []
    val = None

    def read(kind):
        event = next(events)
        _require(event["event_type"] == kind)
        return {k: v for k, v in event["detail"].items() if k != "actor"}

    current = "START"
    for _ in range(len(nodes)):
        node = nodes[current]
        path.append(current)
        legal_ids.extend(node.get("legal_refs", []))
        _require(read("NODE_ENTERED") == {"node_id": current, "title": node["title"],
                                        "kind": node["kind"], "legal_refs": node.get("legal_refs", [])})
        if node["kind"] == "TERMINAL":
            break
        eligible, signals = "always", {}
        if node["kind"] in ("DECISION", "HUMAN_GATE"):
            expected = resolve(node["signal"], facts, review)
            expected.update(node_id=current, node_title=node["title"], signal=node["signal"],
                            legal_refs=node.get("legal_refs", []))
            if node["kind"] == "HUMAN_GATE":
                expected["review_record"] = review_record
            _require(read("SIGNAL_EVALUATED") == expected)
            decisions.append(expected)
            eligible = expected["outcome"]
            signals = {node["signal"]: eligible}
        if node.get("handler") == "valuation":
            val = valuation(facts)
            _require(read("CALCULATION") == val)
        outgoing = sorted((e for e in graph["edges"] if e["source"] == current), key=lambda e: e["id"])
        candidates = [{"edge_id": e["id"], "source": current, "target": e["target"],
                       "outcome": e["outcome"], "guard": e["guard"],
                       "guard_result": evaluate_guard(e["guard"], signals)} for e in outgoing]
        _require(read("GUARDS_EVALUATED") == {"expected": eligible, "candidates": candidates})
        matching = [e for e, candidate in zip(outgoing, candidates) if candidate["guard_result"]]
        _require(len(matching) == 1)
        edge = matching[0]
        _require(read("EDGE_SELECTED") == {"edge_id": edge["id"], "from": current, "to": edge["target"],
                                          "label": edge.get("label"), "guidance": edge.get("guidance"),
                                          "pitfalls": edge.get("pitfalls"), "outcome": eligible})
        chosen.append(edge["id"])
        current = edge["target"]
    else:
        return False
    result = run["result"]
    expected_result = _build_recommendation(current, path, facts, decisions, val, review,
                                             start["legal_sources"], legal_ids)
    expected_result.update(selected_edges=chosen, run_id=run["id"], graph_version=run["graph_version"],
                           case_title=result["case_title"], case_description=result["case_description"])
    _require(result == expected_result)
    _require(read("RECOMMENDATION") == {"status": result["status"], "title": result["title"],
                                       "result_hash": sha256(result),
                                       "legal_source_ids": [r["id"] for r in result["legal_sources"]]})
    _require(read("RUN_FINISHED") == {"terminal": current, "executed_nodes": len(path),
                                     "status": result["status"], "finished_at": run["finished_at"]})
    _require(next(events, None) is None)
    return True


def verify_execution(run: dict, graph: dict) -> dict:
    verdict = {key: False for key in CHECKS}
    verdict.update(run_id=run.get("id"), event_count=0, broken_sequences=[], last_hash="0" * 64,
                   limitations="Lokale Konsistenzprüfung ohne externen Signaturanker; kein Nachweis der Belegechtheit oder fachlichen Qualifikation.")
    try:
        verdict["graph_integrity"] = (graph_checksum(graph) == run["graph_hash"] == graph["meta"]["checksum"]
                                       and graph["meta"]["id"] == run["graph_version"]
                                       and graph["meta"]["status"] == "published")
    except (KeyError, TypeError, ValueError):
        pass
    try:
        events = run["events"]
        verdict["event_count"] = len(events)
        previous = "0" * 64
        for seq, event in enumerate(events, 1):
            record = {k: event[k] for k in ("run_id", "seq", "event_type", "detail", "at", "prev_hash")}
            if (event["run_id"] != run["id"] or event["seq"] != seq or event["prev_hash"] != previous
                    or sha256(record) != event["event_hash"]):
                verdict["broken_sequences"].append(seq)
            previous = event["event_hash"]
        verdict["last_hash"] = previous
        verdict["event_chain_integrity"] = bool(events) and not verdict["broken_sequences"]
        start = events[0]["detail"] if events and events[0]["event_type"] == "RUN_STARTED" else {}
        verdict["facts_integrity"] = sha256(run["facts_snapshot"]) == run["facts_hash"] == start.get("facts_hash")
        result_events = [e for e in events if e["event_type"] == "RECOMMENDATION"]
        verdict["result_integrity"] = (len(result_events) == 1 and
                                       result_events[0]["detail"].get("result_hash") == sha256(run["result"]))
        refs = {r for n in graph["nodes"] for r in n.get("legal_refs", [])}
        review = start.get("review_record")
        review_valid = (review is None or (review["case_id"] == run["case_id"]
                        and review["graph_version"] == run["graph_version"]
                        and review["facts_hash"] == run["facts_hash"]
                        and review["decision"] in ("approved", "rejected")
                        and len(review["reviewer"].strip()) >= 3 and len(review["note"].strip()) >= 12
                        and bool(review["id"]) and bool(review["created_at"])))
        sources = start.get("legal_sources", {})
        verdict["context_integrity"] = (start.get("executor_version") == EXECUTOR_VERSION
            and "review_record" in start and review_valid and set(sources) == refs
            and all(isinstance(sources[r].get("label"), str) and isinstance(sources[r].get("url"), str) for r in refs)
            and all(bool(e["detail"].get("actor")) and bool(e["at"]) for e in events))
        header_valid = (start.get("case_id") == run["case_id"]
            and start.get("graph_version") == run["graph_version"]
            and start.get("graph_checksum") == run["graph_hash"]
            and start.get("started_at") == run["started_at"]
            and run["status"] == run["result"]["status"])
        if header_valid and all(verdict[key] for key in CHECKS if key != "execution_integrity"):
            verdict["execution_integrity"] = _replay(run, graph, start)
    except (KeyError, TypeError, ValueError, IndexError, StopIteration, AttributeError):
        pass
    verdict["valid"] = all(verdict[key] for key in CHECKS)
    return verdict


def verify_document(document: dict) -> dict:
    verdict = verify_execution(document["run"], document["graph"])
    # The envelope must expose the same frozen sources as the hashed start event.
    if document.get("legal_sources") != source_snapshot(document["run"]):
        verdict["context_integrity"] = verdict["valid"] = False
    return verdict
