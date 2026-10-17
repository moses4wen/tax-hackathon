"""SQLite persistence, immutable published graph versions, audit chains."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import (CONTEXT_FIELDS, CURRENT_CONTEXT, FACT_FIELDS, FACT_INDEX, canonical,
                    seed_graph, sha256, graph_checksum, validate_graph)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def uid(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:12]


def db_path() -> Path:
    p = Path(os.environ.get("DATABASE_PATH", "./data/prozesspilot.sqlite3")).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def init_db() -> None:
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS graph_versions (
              id TEXT PRIMARY KEY, slug TEXT NOT NULL, version INTEGER NOT NULL,
              label TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','published')),
              checksum TEXT, created_at TEXT NOT NULL, created_by TEXT NOT NULL,
              approved_at TEXT, approved_by TEXT, UNIQUE(slug, version)
            );
            CREATE TABLE IF NOT EXISTS graph_nodes (
              version_id TEXT NOT NULL, node_id TEXT NOT NULL, data TEXT NOT NULL,
              PRIMARY KEY(version_id,node_id),
              FOREIGN KEY(version_id) REFERENCES graph_versions(id)
            );
            CREATE TABLE IF NOT EXISTS graph_edges (
              version_id TEXT NOT NULL, edge_id TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
              data TEXT NOT NULL, PRIMARY KEY(version_id,edge_id),
              FOREIGN KEY(version_id,source) REFERENCES graph_nodes(version_id,node_id),
              FOREIGN KEY(version_id,target) REFERENCES graph_nodes(version_id,node_id)
            );
            CREATE TABLE IF NOT EXISTS graph_revision_log (
              version_id TEXT NOT NULL, revision INTEGER NOT NULL, actor TEXT NOT NULL,
              reason TEXT NOT NULL, graph_json TEXT NOT NULL, checksum TEXT NOT NULL,
              diff_json TEXT NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(version_id,revision),
              FOREIGN KEY(version_id) REFERENCES graph_versions(id)
            );
            CREATE TABLE IF NOT EXISTS cases (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
              synthetic INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS case_facts (
              case_id TEXT NOT NULL, fact_key TEXT NOT NULL, value_json TEXT NOT NULL,
              verification TEXT NOT NULL CHECK(verification IN ('unknown','reported','confirmed')),
              evidence_ref TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
              PRIMARY KEY(case_id,fact_key), FOREIGN KEY(case_id) REFERENCES cases(id)
            );
            CREATE TABLE IF NOT EXISTS case_reviews (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL, graph_version TEXT NOT NULL,
              facts_hash TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('approved','rejected')),
              reviewer TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(case_id) REFERENCES cases(id),
              FOREIGN KEY(graph_version) REFERENCES graph_versions(id)
            );
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL, graph_version TEXT NOT NULL,
              graph_hash TEXT NOT NULL, facts_snapshot TEXT NOT NULL, facts_hash TEXT NOT NULL,
              result_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL, started_at TEXT NOT NULL,
              finished_at TEXT, FOREIGN KEY(case_id) REFERENCES cases(id),
              FOREIGN KEY(graph_version) REFERENCES graph_versions(id)
            );
            CREATE TABLE IF NOT EXISTS run_events (
              run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_type TEXT NOT NULL,
              detail_json TEXT NOT NULL, at TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
              PRIMARY KEY(run_id,seq), FOREIGN KEY(run_id) REFERENCES runs(id)
            );
            CREATE TABLE IF NOT EXISTS activity_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, entity_kind TEXT NOT NULL, entity_id TEXT NOT NULL,
              kind TEXT NOT NULL, actor TEXT NOT NULL, detail_json TEXT NOT NULL,
              at TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runs_case ON runs(case_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_activity_entity ON activity_events(entity_kind,entity_id);
        """)
        # Additive, idempotent migration. Existing snapshots and hashes are untouched.
        if "context_id" not in {r[1] for r in c.execute("PRAGMA table_info(cases)")}:
            c.execute("ALTER TABLE cases ADD COLUMN context_id TEXT NOT NULL DEFAULT 'demo-2026'")
        if "observations_json" not in {r[1] for r in c.execute("PRAGMA table_info(case_facts)")}:
            c.execute("ALTER TABLE case_facts ADD COLUMN observations_json TEXT NOT NULL DEFAULT '[]'")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS orgs (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS app_users (
              username TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id),
              role TEXT NOT NULL CHECK(role IN ('viewer','editor','reviewer')),
              password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        """)
        c.execute("INSERT OR IGNORE INTO orgs VALUES('demo','Demo Organisation',?)", (now(),))
        for table in ("graph_versions", "cases"):
            if "org_id" not in {r[1] for r in c.execute("PRAGMA table_info(" + table + ")")}:
                c.execute("ALTER TABLE " + table + " ADD COLUMN org_id TEXT NOT NULL DEFAULT 'demo'")
        c.execute("CREATE INDEX IF NOT EXISTS idx_graph_org ON graph_versions(org_id,status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_case_org ON cases(org_id)")
        first = c.execute("SELECT id FROM graph_versions LIMIT 1").fetchone()
        if not first:
            graph = seed_graph()
            assert not validate_graph(graph), validate_graph(graph)
            write_graph(c, "umwstg20-v1", "umwstg20", 1, graph, "published", "Systemdemo", "Fiktives Referenzmodell; keine fachliche Rechtsfreigabe")
            seed_cases(c)


def write_graph(c: sqlite3.Connection, version_id: str, slug: str, version: int, graph: dict,
                status: str, actor: str, note: str = "", *, org_id: str = "demo") -> dict:
    errors = validate_graph(graph)
    if errors:
        raise ValueError("; ".join(errors))
    checksum = graph_checksum(graph) if status == "published" else None
    time = now()
    c.execute("""INSERT INTO graph_versions(id,slug,version,label,status,checksum,created_at,created_by,approved_at,approved_by,org_id)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (version_id, slug, version, graph.get("label", slug), status, checksum, time, actor,
               time if status == "published" else None, actor if status == "published" else None, org_id))
    insert_graph_parts(c, version_id, graph)
    record_graph_revision(c, version_id, graph, actor, note or "Initiale Graphversion", {"initial": True})
    activity(c, "graph", version_id, "GRAPH_CREATED" if status == "draft" else "GRAPH_PUBLISHED",
             actor, {"version": version, "status": status, "checksum": checksum, "note": note})
    return graph_info(c, version_id)


def insert_graph_parts(c: sqlite3.Connection, version_id: str, graph: dict) -> None:
    for n in graph["nodes"]:
        c.execute("INSERT INTO graph_nodes(version_id,node_id,data) VALUES(?,?,?)",
                  (version_id, n["id"], canonical(n)))
    for e in graph["edges"]:
        c.execute("INSERT INTO graph_edges(version_id,edge_id,source,target,data) VALUES(?,?,?,?,?)",
                  (version_id, e["id"], e["source"], e["target"], canonical(e)))


def graph_diff(before: dict, after: dict) -> dict:
    def part(k: str):
        old = {e["id"]: e for e in before[k]}
        new = {e["id"]: e for e in after[k]}
        return {"added": sorted(new.keys() - old.keys()), "deleted": sorted(old.keys() - new.keys()),
                "changed": sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}
    return {"label_changed": before.get("label") != after.get("label"),
            "nodes": part("nodes"), "edges": part("edges")}


def record_graph_revision(c: sqlite3.Connection, version_id: str, graph: dict,
                          actor: str, reason: str, diff: dict) -> int:
    row = c.execute("SELECT COALESCE(MAX(revision),0)+1 FROM graph_revision_log WHERE version_id=?", (version_id,)).fetchone()
    revision = row[0]
    c.execute("""INSERT INTO graph_revision_log(version_id,revision,actor,reason,graph_json,checksum,diff_json,created_at)
                 VALUES(?,?,?,?,?,?,?,?)""", (version_id, revision, actor, reason[:1000],
                                                 canonical(graph), graph_checksum(graph), canonical(diff), now()))
    return revision


def graph_revisions(c: sqlite3.Connection, version_id: str) -> list[dict]:
    graph_info(c, version_id)
    return [{**{k: r[k] for k in ("revision", "actor", "reason", "checksum", "created_at")},
             "diff": json.loads(r["diff_json"])} for r in
            c.execute("SELECT * FROM graph_revision_log WHERE version_id=? ORDER BY revision DESC", (version_id,))]


def graph_provenance(c: sqlite3.Connection, version_id: str) -> dict:
    """Derive element history from real revision snapshots, without invented authors."""
    info = graph_info(c, version_id)
    result = {"graph_version": version_id, "meta": info, "nodes": {}, "edges": {},
              "snapshot_integrity": True,
              "notice": "Autorenschaft innerhalb dieser Version; keine verifizierte Identität und keine eigenständige fachliche Elementfreigabe."}
    previous = {"nodes": {}, "edges": {}}
    for row in c.execute("SELECT * FROM graph_revision_log WHERE version_id=? ORDER BY revision", (version_id,)):
        snapshot = json.loads(row["graph_json"])
        result["snapshot_integrity"] &= graph_checksum(snapshot) == row["checksum"]
        for kind in ("nodes", "edges"):
            current = {item["id"]: item for item in snapshot[kind]}
            for key in previous[kind].keys() | current.keys():
                change = ("created" if key not in previous[kind] else "deleted" if key not in current
                          else "changed" if previous[kind][key] != current[key] else None)
                if change:
                    result[kind].setdefault(key, []).append({"revision": row["revision"], "change": change,
                        "actor": row["actor"], "reason": row["reason"], "at": row["created_at"],
                        "checksum": row["checksum"]})
            previous[kind] = current
    result["available"] = bool(result["nodes"] or result["edges"])
    return result


def graph_info(c: sqlite3.Connection, version_id: str) -> dict:
    row = c.execute("SELECT * FROM graph_versions WHERE id=?", (version_id,)).fetchone()
    if not row:
        raise KeyError("Graphversion nicht gefunden.")
    return dict(row)


def load_graph(c: sqlite3.Connection, version_id: str, *, check: bool = True) -> dict:
    info = graph_info(c, version_id)
    nodes = [json.loads(r["data"]) for r in c.execute("SELECT data FROM graph_nodes WHERE version_id=? ORDER BY node_id", (version_id,))]
    edges = [json.loads(r["data"]) for r in c.execute("SELECT data FROM graph_edges WHERE version_id=? ORDER BY edge_id", (version_id,))]
    graph = {"label": info["label"], "nodes": nodes, "edges": edges}
    if check and info["status"] == "published" and graph_checksum(graph) != info["checksum"]:
        raise RuntimeError("Integritätsfehler: veröffentlichte Graphversion wurde verändert.")
    return {"meta": info, **graph}


def save_draft(c: sqlite3.Connection, version_id: str, graph: dict, actor: str,
               reason: str = "Bearbeitung des Graphentwurfs") -> dict:
    info = graph_info(c, version_id)
    if info["status"] != "draft":
        raise ValueError("Veröffentlichte Graphen sind unveränderlich. Zuerst einen Entwurf anlegen.")
    errors = validate_graph(graph)
    if errors:
        raise ValueError("; ".join(errors))
    old = load_graph(c, version_id, check=False)
    c.execute("DELETE FROM graph_edges WHERE version_id=?", (version_id,))
    c.execute("DELETE FROM graph_nodes WHERE version_id=?", (version_id,))
    c.execute("UPDATE graph_versions SET label=? WHERE id=?", (graph["label"], version_id))
    insert_graph_parts(c, version_id, graph)
    old_graph = {k: old[k] for k in ("label", "nodes", "edges")}
    difference = graph_diff(old_graph, graph)
    rev = record_graph_revision(c, version_id, graph, actor, reason, difference)
    activity(c, "graph", version_id, "GRAPH_DRAFT_CHANGED", actor,
             {"old_hash": graph_checksum(old_graph), "new_hash": graph_checksum(graph),
              "revision": rev, "reason": reason[:1000], "diff": difference,
              "nodes": len(graph["nodes"]), "edges": len(graph["edges"])})
    return load_graph(c, version_id)


def make_draft(c: sqlite3.Connection, source_id: str, actor: str) -> dict:
    source = load_graph(c, source_id)
    slug = source["meta"]["slug"]
    version = c.execute("SELECT COALESCE(MAX(version),0)+1 FROM graph_versions WHERE slug=?", (slug,)).fetchone()[0]
    new_id = uid("g")
    graph = {k:source[k] for k in ("label", "nodes", "edges")}
    write_graph(c, new_id, slug, version, graph, "draft", actor, org_id=source["meta"]["org_id"])
    return load_graph(c, new_id)


def publish_draft(c: sqlite3.Connection, version_id: str, actor: str) -> dict:
    info = graph_info(c, version_id)
    if info["status"] != "draft":
        raise ValueError("Nur Entwürfe können veröffentlicht werden.")
    obj = load_graph(c, version_id, check=False)
    graph = {k:obj[k] for k in ("label", "nodes", "edges")}
    errors = validate_graph(graph)
    if errors: raise ValueError("; ".join(errors))
    checksum = graph_checksum(graph)
    c.execute("UPDATE graph_versions SET status='published',checksum=?,approved_by=?,approved_at=? WHERE id=?",
              (checksum, actor, now(), version_id))
    activity(c, "graph", version_id, "GRAPH_PUBLISHED", actor,
             {"checksum": checksum, "attestation": "Struktur geprüft; keine automatische steuerrechtliche Validierung"})
    return load_graph(c, version_id)


def list_graphs(c: sqlite3.Connection, org_id: str = "demo", *, published_only: bool = False) -> list[dict]:
    query = "SELECT * FROM graph_versions WHERE org_id=?" + (" AND status='published'" if published_only else "") + " ORDER BY version DESC"
    return [dict(row) for row in c.execute(query, (org_id,))]


def default_facts(context_id: str = CURRENT_CONTEXT, *, extended: bool = False) -> list[dict]:
    keys = CONTEXT_FIELDS[context_id] if extended else [f["key"] for f in FACT_FIELDS]
    return [{"key": key, "value": None, "verification": "unknown", "evidence_ref": ""} for key in keys]


def parse_fact(item: dict) -> dict:
    if not isinstance(item, dict):
        raise ValueError("Jede Tatsache muss ein JSON-Objekt sein.")
    key = item.get("key")
    if not isinstance(key, str) or key not in FACT_INDEX:
        raise ValueError(f"Unbekanntes Tatsachenfeld: {key}")
    kind = FACT_INDEX[key]["type"]
    status = item.get("verification", "unknown")
    if status not in ("unknown", "reported", "confirmed"):
        raise ValueError(f"{key}: ungültiger Nachweisstatus")
    value = item.get("value")
    evidence = str(item.get("evidence_ref") or "").strip()[:500]
    if value is None or value == "":
        status, value = "unknown", None
        evidence = ""
    if kind == "boolean" and value is not None and type(value) is not bool:
        raise ValueError(f"{key}: Ja/Nein erwartet")
    if kind == "choice" and value is not None and value not in [x["value"] for x in FACT_INDEX[key]["choices"]]:
        raise ValueError(f"{key}: nicht unterstützte Auswahl")
    if kind == "number" and value is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not -1e12 < value < 1e12:
            raise ValueError(f"{key}: ungültiger Betrag")
        value = round(float(value), 2)
    if kind in ("date", "text") and value is not None:
        if not isinstance(value, str) or len(value) > 180:
            raise ValueError(f"{key}: Text mit höchstens 180 Zeichen erwartet.")
        value = value.strip()
        if kind == "date":
            from datetime import date
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise ValueError(f"{key}: Datum im Format JJJJ-MM-TT erwartet.")
    if status == "confirmed" and not evidence:
        raise ValueError(f"{key}: Für 'bestätigt' ist ein Nachweis oder Aktenvermerk erforderlich.")
    parsed = {"key": key, "value": value, "verification": status, "evidence_ref": evidence}
    observations = item.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 10:
        raise ValueError("Höchstens zehn ergänzende Nachweise je Tatsache sind zulässig.")
    if observations:
        parsed["observations"] = []
        for observation in observations:
            if not isinstance(observation, dict) or observation.get("observations"):
                raise ValueError("Ergänzender Nachweis muss ein einfaches Objekt sein.")
            child = parse_fact({**observation, "key": key, "observations": []})
            parsed["observations"].append({k: child[k] for k in ("value","verification","evidence_ref")})
    return parsed


def create_case(c: sqlite3.Connection, title: str, description: str = "", *, actor: str = "Benutzer",
                facts: list[dict] | None = None, synthetic: bool = True, context_id: str = CURRENT_CONTEXT,
                extended: bool = False, org_id: str = "demo") -> str:
    title = title.strip()
    if not 2 <= len(title) <= 180:
        raise ValueError("Fallbezeichnung muss 2–180 Zeichen enthalten.")
    case_id = uid("fall")
    if context_id not in CONTEXT_FIELDS:
        raise ValueError("Unbekannter rechtlicher Fallkontext.")
    time = now()
    c.execute("INSERT INTO cases(id,title,description,synthetic,created_at,updated_at,context_id,org_id) VALUES(?,?,?,?,?,?,?,?)",
              (case_id, title, description[:3000], int(synthetic), time, time, context_id, org_id))
    fact_list = facts if facts is not None else default_facts(context_id, extended=extended)
    parsed = [parse_fact(item) for item in fact_list]
    if len({f["key"] for f in parsed}) != len(parsed):
        raise ValueError("Doppelte Fakten.")
    provided = {p["key"]: p for p in parsed}
    if not set(provided) <= set(CONTEXT_FIELDS[context_id]):
        raise ValueError("Tatsache gehört nicht zum rechtlichen Fallkontext.")
    for entry in default_facts(context_id, extended=extended or context_id != CURRENT_CONTEXT):
        item = provided.get(entry["key"], entry)
        c.execute("INSERT INTO case_facts(case_id,fact_key,value_json,verification,evidence_ref,updated_at,observations_json) VALUES(?,?,?,?,?,?,?)",
                  (case_id, item["key"], canonical(item["value"]), item["verification"], item["evidence_ref"], time, canonical(item.get("observations",[]))))
    activity(c, "case", case_id, "CASE_CREATED", actor, {"title": title, "synthetic": synthetic})
    return case_id


def get_case(c: sqlite3.Connection, case_id: str) -> dict:
    row = c.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        raise KeyError("Fall nicht gefunden.")
    return {**dict(row), "synthetic": bool(row["synthetic"]),
            "fact_fields": [FACT_INDEX[key] for key in CONTEXT_FIELDS[row["context_id"]]],
            "facts": [
                {"key": r["fact_key"], "value": json.loads(r["value_json"]), "verification": r["verification"], "evidence_ref": r["evidence_ref"],
                 **({"observations":json.loads(r["observations_json"])} if r["observations_json"] != "[]" else {})}
                for r in c.execute("SELECT * FROM case_facts WHERE case_id=? ORDER BY fact_key", (case_id,))
            ]}


def get_facts(c: sqlite3.Connection, case_id: str) -> dict:
    return {i["key"]: i for i in get_case(c, case_id)["facts"]}


def save_facts(c: sqlite3.Connection, case_id: str, entries: list[dict], actor: str) -> dict:
    old = get_facts(c, case_id)
    parsed = [parse_fact(item) for item in entries]
    keys = {e["key"] for e in parsed}
    allowed = set(CONTEXT_FIELDS[get_case(c, case_id)["context_id"]])
    if len(parsed) != len(keys) or not set(old) <= keys or not keys <= allowed:
        raise ValueError("Bitte alle definierten Fakten genau einmal übermitteln.")
    new = {e["key"]: e for e in parsed}
    time = now()
    for key, item in new.items():
        if old.get(key) != item:
            c.execute("""INSERT INTO case_facts(case_id,fact_key,value_json,verification,evidence_ref,updated_at,observations_json)
                         VALUES(?,?,?,?,?,?,?) ON CONFLICT(case_id,fact_key) DO UPDATE SET
                         value_json=excluded.value_json,verification=excluded.verification,evidence_ref=excluded.evidence_ref,
                         updated_at=excluded.updated_at,observations_json=excluded.observations_json""",
                      (case_id,key,canonical(item["value"]),item["verification"],item["evidence_ref"],time,canonical(item.get("observations",[]))))
            activity(c, "case", case_id, "FACT_CHANGED", actor, {"key": key, "before": old.get(key), "after": item})
    c.execute("UPDATE cases SET updated_at=? WHERE id=?", (time, case_id))
    return get_case(c, case_id)


def get_review(c: sqlite3.Connection, case_id: str, version_id: str, facts_hash: str) -> dict | None:
    r = c.execute("SELECT * FROM case_reviews WHERE case_id=? AND graph_version=? AND facts_hash=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                  (case_id, version_id, facts_hash)).fetchone()
    return dict(r) if r else None


def review_status(c: sqlite3.Connection, case_id: str, version_id: str, facts_hash: str) -> str:
    r = get_review(c, case_id, version_id, facts_hash)
    return r["decision"] if r else "pending"


def add_review(c: sqlite3.Connection, case_id: str, version_id: str, reviewer: str,
               decision: str, note: str, facts_hash: str) -> dict:
    if decision not in ("approved", "rejected"):
        raise ValueError("Freigabeentscheidung ungültig.")
    if not 3 <= len(reviewer.strip()) <= 160:
        raise ValueError("Bitte vollständigen Namen oder prüfbares Kürzel angeben.")
    if len(note.strip()) < 12:
        raise ValueError("Eine kurze fachliche Begründung (mindestens 12 Zeichen) ist erforderlich.")
    graph_info(c, version_id)
    case = get_case(c, case_id)
    if not case["synthetic"] and not os.environ.get("ALLOW_REAL_CASES") == "1":
        raise ValueError("Dieses MVP erlaubt standardmäßig nur synthetische Fälle.")
    record = {"id": uid("rev"), "case_id": case_id, "graph_version": version_id, "facts_hash": facts_hash,
              "decision": decision, "reviewer": reviewer.strip(), "note": note.strip()[:3000], "created_at": now()}
    c.execute("INSERT INTO case_reviews VALUES(:id,:case_id,:graph_version,:facts_hash,:decision,:reviewer,:note,:created_at)", record)
    activity(c, "case", case_id, "EXPERT_REVIEW", reviewer,
             {"decision": decision, "version_id": version_id, "facts_hash": facts_hash, "note": note})
    return record


def activity(c: sqlite3.Connection, entity_kind: str, entity_id: str, kind: str, actor: str, detail: Any) -> None:
    last = c.execute("SELECT event_hash FROM activity_events ORDER BY id DESC LIMIT 1").fetchone()
    previous = last[0] if last else "0" * 64
    time = now()
    record = {"entity_kind": entity_kind, "entity_id": entity_id, "kind": kind, "actor": actor,
              "detail": detail, "at": time, "prev_hash": previous}
    digest = sha256(record)
    c.execute("INSERT INTO activity_events(entity_kind,entity_id,kind,actor,detail_json,at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
              (entity_kind, entity_id, kind, actor, canonical(detail), time, previous, digest))


def append_run_event(c: sqlite3.Connection, run_id: str, event_type: str, detail: Any) -> None:
    detail = {"actor": "Graph-Executor", **detail}
    last = c.execute("SELECT seq,event_hash FROM run_events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
    seq = last["seq"] + 1 if last else 1
    prev = last["event_hash"] if last else "0" * 64
    at = now()
    record = {"run_id": run_id, "seq": seq, "event_type": event_type, "detail": detail, "at": at, "prev_hash": prev}
    digest = sha256(record)
    c.execute("INSERT INTO run_events(run_id,seq,event_type,detail_json,at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
              (run_id, seq, event_type, canonical(detail), at, prev, digest))


def get_run(c: sqlite3.Connection, run_id: str, *, include_events: bool = True) -> dict:
    row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise KeyError("Prüflauf nicht gefunden.")
    value = dict(row)
    value["facts_snapshot"] = json.loads(value["facts_snapshot"])
    value["result"] = json.loads(value.pop("result_json"))
    if include_events:
        value["events"] = [{**dict(r), "detail": json.loads(r["detail_json"])} for r in
                           c.execute("SELECT * FROM run_events WHERE run_id=? ORDER BY seq", (run_id,))]
        for item in value["events"]: item.pop("detail_json", None)
    return value


def verify_run(c: sqlite3.Connection, run_id: str) -> dict:
    from .audit import verify_execution
    run = get_run(c, run_id)
    original_graph = load_graph(c, run["graph_version"], check=False)
    return verify_execution(run, original_graph)


def seed_cases(c: sqlite3.Connection, *, org_id: str = "demo") -> None:
    sample = {
        "asset_type": "betrieb", "receiving_company": True, "new_shares": True, "essential_assets": True,
        "future_corporate_tax": True, "assets_ge_liabilities": True, "german_tax_right": True,
        "book_value": 100000, "other_consideration": 0, "fair_value": 400000,
        "application_timely": True, "planned_disposal": False,
    }
    def filled(mods: dict, reported: set[str] | None = None) -> list[dict]:
        vals = {**sample, **mods}
        entries = []
        for key in (f["key"] for f in FACT_FIELDS):
            value = vals[key]
            status = "unknown" if value is None else "reported" if key in (reported or set()) else "confirmed"
            entries.append({"key": key, "value": value, "verification": status,
                            "evidence_ref": f"SYNTHETISCH: Fallannahme / Musterbeleg {key}" if status == "confirmed" else ""})
        return entries
    create_case(c, "Musterfall A · Buchwertprüfung", "Fiktive Ausgliederung Mustermann Handwerk e. K. in eine GmbH; Buchwert 100.000 €, gemeiner Wert 400.000 €.", actor="Systemdemo", org_id=org_id, facts=filled({}))
    create_case(c, "Musterfall B · Betriebsgrundlage fehlt", "Variante mit zurückbehaltener wesentlicher Betriebsgrundlage; § 20 Anwendungsbereich fraglich.", actor="Systemdemo", org_id=org_id, facts=filled({"essential_assets": False}))
    create_case(c, "Musterfall C · Nachweis fehlt", "Unklar, ob neue GmbH-Anteile als Gegenleistung zugeteilt werden.", actor="Systemdemo", org_id=org_id, facts=filled({"new_shares": True}, reported={"new_shares"}))
    create_case(c, "Musterfall D · Veräußerungsrisiko", "Innerhalb von zwei Jahren ist ein Anteilverkauf geplant; gesondertes § 22 Risiko.", actor="Systemdemo", org_id=org_id, facts=filled({"planned_disposal": True}))
