"""German Web UI + documented JSON API for the auditable process graph."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import execute
from .audit import source_snapshot
from .model import APP_VERSION, FACT_FIELDS, HANDLER_FACTS, LEGAL, SIGNAL_FACTS, sha256, validate_graph
from .storage import (activity, add_review, connect, create_case, get_case, get_run, graph_info,
                      graph_provenance, graph_revisions, init_db, list_graphs, load_graph, make_draft, now, publish_draft,
                      save_draft, save_facts, verify_run)

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("APP_ENV", "local") == "production" and len(os.getenv("APP_PASSWORD", "")) < 16:
        raise RuntimeError("APP_ENV=production erfordert APP_PASSWORD mit mindestens 16 Zeichen.")
    init_db()
    yield


app = FastAPI(title="ProzessPilot §20 UmwStG", description="Auditierbarer deutscher Steuer-Prozessgraph (synthetisches MVP)",
              version=APP_VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")


@app.middleware("http")
async def security(request: Request, call_next):
    if request.headers.get("content-length"):
        try:
            if int(request.headers["content-length"]) > 2_000_000:
                return JSONResponse({"detail": "Anfrage zu groß (max. 2 MB)."}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Ungültige Anfrage."}, status_code=400)
    password = os.environ.get("APP_PASSWORD", "")
    if password and request.url.path != "/api/health":
        # HTTP Basic is for private hackathon demos behind HTTPS, not identity assurance.
        import base64
        import binascii
        header = request.headers.get("authorization", "")
        authorized = False
        if header.startswith("Basic "):
            try:
                user, pwd = base64.b64decode(header[6:], validate=True).decode("utf-8").split(":", 1)
                authorized = secrets.compare_digest(user, os.environ.get("APP_USER", "admin")) and secrets.compare_digest(pwd, password)
            except (ValueError, UnicodeDecodeError, binascii.Error):
                pass
        if not authorized:
            return JSONResponse({"detail": "Authentifizierung erforderlich."}, status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="ProzessPilot"'})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(KeyError)
async def key_error(_: Request, exc: KeyError):
    return JSONResponse({"detail": str(exc).strip("'\"")}, status_code=404)


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(RuntimeError)
async def runtime_error(_: Request, exc: RuntimeError):
    return JSONResponse({"detail": str(exc)}, status_code=409)


class NewCase(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=3000)
    facts: list[dict] | None = None


class FactsUpdate(BaseModel):
    facts: list[dict]
    actor: str = Field(default="Benutzer", max_length=160)


class RunRequest(BaseModel):
    graph_version: str = "umwstg20-v1"


class ReviewRequest(BaseModel):
    run_id: str
    reviewer: str = Field(min_length=3, max_length=160)
    decision: str
    note: str = Field(min_length=12, max_length=3000)


class ActorRequest(BaseModel):
    actor: str = Field(default="Benutzer", min_length=2, max_length=160)


class DraftSaveRequest(BaseModel):
    actor: str = Field(default="Benutzer", min_length=2, max_length=160)
    reason: str = Field(default="Bearbeitung des Graphentwurfs", min_length=5, max_length=1000)
    graph: dict[str, Any]


class PublishRequest(BaseModel):
    actor: str = Field(min_length=3, max_length=160)
    confirm_expert_review: bool = False


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/api/health")
def health():
    with connect() as c:
        count = c.execute("SELECT count(*) FROM graph_versions WHERE status='published'").fetchone()[0]
    return {"status": "ok", "service": "ProzessPilot", "published_graphs": count, "time": now()}


@app.get("/api/config")
def config():
    return {"name": "ProzessPilot", "locale": "de-DE", "version": APP_VERSION, "synthetic_only": os.environ.get("ALLOW_REAL_CASES") != "1",
            "auth_enabled": bool(os.environ.get("APP_PASSWORD")), "legal_sources": LEGAL,
            "fact_fields": FACT_FIELDS, "signal_facts": SIGNAL_FACTS, "handler_facts": HANDLER_FACTS,
            "warning": "Demonstrator: keine Steuerberatung und keine geprüfte TaxGraph-API-Anbindung."}


@app.get("/api/graphs")
def graphs():
    with connect() as c: return {"graphs": list_graphs(c)}


@app.get("/api/graphs/{version_id}")
def get_graph(version_id: str):
    with connect() as c: return load_graph(c, version_id)


@app.get("/api/graphs/{version_id}/export")
def export_graph(version_id: str):
    with connect() as c:
        obj=load_graph(c, version_id)
        doc={"format": "ProzessPilot-Graph-1", "exported_at": now(),
             "meta": obj["meta"], "graph": {k: obj[k] for k in ("label", "nodes", "edges")},
             "revisions": graph_revisions(c, version_id)}
    filename=f"prozessgraph-{version_id}.json"
    return Response(content=json.dumps(doc,ensure_ascii=False,indent=2),media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.post("/api/graphs/{version_id}/draft")
def draft(version_id: str, args: ActorRequest):
    with connect() as c: return make_draft(c, version_id, args.actor)


@app.put("/api/graphs/{version_id}")
def edit_graph(version_id: str, args: DraftSaveRequest):
    with connect() as c: return save_draft(c, version_id, args.graph, args.actor, args.reason)


@app.get("/api/graphs/{version_id}/revisions")
def graph_history(version_id: str):
    with connect() as c: return {"revisions": graph_revisions(c, version_id)}


@app.get("/api/graphs/{version_id}/provenance")
def graph_element_history(version_id: str):
    with connect() as c: return graph_provenance(c, version_id)


@app.post("/api/graphs/{version_id}/publish")
def publish(version_id: str, args: PublishRequest):
    if not args.confirm_expert_review:
        raise ValueError("Bitte die strukturelle Prüfung bestätigen. Es erfolgt keine automatische Rechtsprüfung.")
    with connect() as c: return publish_draft(c, version_id, args.actor)


@app.post("/api/graphs/validate")
def graph_validate(graph: dict):
    errors = validate_graph(graph)
    return {"valid": not errors, "errors": errors,
            "node_count": len(graph["nodes"]) if isinstance(graph.get("nodes"), list) else 0,
            "edge_count": len(graph["edges"]) if isinstance(graph.get("edges"), list) else 0}


@app.get("/api/cases")
def cases():
    with connect() as c:
        rows = c.execute("SELECT * FROM cases ORDER BY created_at DESC, id ASC").fetchall()
        result = []
        for r in rows:
            v = dict(r)
            v["synthetic"] = bool(v["synthetic"])
            latest = c.execute("SELECT id,status,finished_at FROM runs WHERE case_id=? ORDER BY started_at DESC,rowid DESC LIMIT 1", (r["id"],)).fetchone()
            v["latest_run"] = dict(latest) if latest else None
            result.append(v)
    return {"cases": result}


@app.post("/api/cases", status_code=201)
def new_case(args: NewCase):
    with connect() as c:
        cid = create_case(c, args.title, args.description, facts=args.facts, synthetic=True)
        return get_case(c, cid)


@app.get("/api/cases/{case_id}")
def case_get(case_id: str):
    with connect() as c: return get_case(c, case_id)


@app.put("/api/cases/{case_id}/facts")
def case_update(case_id: str, args: FactsUpdate):
    with connect() as c: return save_facts(c, case_id, args.facts, args.actor)


@app.get("/api/cases/{case_id}/runs")
def case_runs(case_id: str):
    with connect() as c:
        get_case(c, case_id)
        runs = [dict(r) for r in c.execute("SELECT id,status,graph_version,started_at,finished_at FROM runs WHERE case_id=? ORDER BY started_at DESC,rowid DESC", (case_id,))]
    return {"runs": runs}


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str, args: RunRequest):
    with connect() as c:
        result = execute(c, case_id, args.graph_version)
        activity(c, "case", case_id, "RUN_EXECUTED", "Graph-Executor",
                 {"run_id": result["run_id"], "graph_version": args.graph_version, "status": result["result"]["status"]})
        return {**result, "audit": verify_run(c, result["run_id"])}


@app.post("/api/cases/{case_id}/review")
def review_case(case_id: str, args: ReviewRequest):
    with connect() as c:
        run = get_run(c, args.run_id, include_events=False)
        if run["case_id"] != case_id:
            raise ValueError("Prüflauf gehört nicht zu diesem Fall.")
        if run["status"] != "FREIGABE_OFFEN":
            raise ValueError("Nur ein vollständig geprüfter Lauf mit ausstehender Freigabe kann freigegeben werden.")
        if not verify_run(c, args.run_id)["valid"]:
            raise ValueError("Integrität des Prüflaufs nicht bestätigt. Erneut ausführen und prüfen.")
        current_facts = {x["key"]: x for x in get_case(c, case_id)["facts"]}
        if sha256(current_facts) != run["facts_hash"]:
            raise ValueError("Fakten wurden nach dem Prüflauf verändert. Erneut ausführen.")
        rev = add_review(c, case_id, run["graph_version"], args.reviewer, args.decision, args.note, run["facts_hash"])
        return {"review": rev, "message": "Freigabeentscheidung dokumentiert. Neuen Prüflauf starten, um sie im Graph abzubilden."}


@app.get("/api/runs/{run_id}")
def run_get(run_id: str):
    with connect() as c:
        run = get_run(c, run_id)
        run["verification"] = verify_run(c, run_id)
        return run


@app.get("/api/runs/{run_id}/audit")
def run_audit(run_id: str):
    with connect() as c:
        run = get_run(c, run_id)
        obj = load_graph(c, run["graph_version"], check=False)
        audit = {"format": "ProzessPilot-Audit-1", "exported_at": now(),
                 "run": run, "graph": obj, "graph_revisions": graph_revisions(c, run["graph_version"]),
                 "graph_provenance": graph_provenance(c, run["graph_version"]),
                 "integrity": verify_run(c, run_id),
                 "legal_sources": source_snapshot(run), "notice": "Fiktiver Demonstrator. Prüfpfad ≠ Rechtsgutachten; kein extern verankertes Signatursystem."}
    filename = "pruefpfad-" + run_id + ".json"
    return Response(content=json.dumps(audit, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.get("/api/audit/activity")
def activities():
    with connect() as c:
        rows = c.execute("SELECT * FROM activity_events ORDER BY id DESC LIMIT 150").fetchall()
        return {"activity": [{**dict(r), "detail": json.loads(r["detail_json"])} for r in rows]}


@app.get("/api/audit/activity/verify")
def activity_verify():
    from .model import sha256
    with connect() as c:
        prev = "0" * 64
        broken = []
        rows = c.execute("SELECT * FROM activity_events ORDER BY id").fetchall()
        for r in rows:
            record = {"entity_kind": r["entity_kind"], "entity_id": r["entity_id"], "kind": r["kind"],
                      "actor": r["actor"], "detail": json.loads(r["detail_json"]),
                      "at": r["at"], "prev_hash": r["prev_hash"]}
            if r["prev_hash"] != prev or sha256(record) != r["event_hash"]:
                broken.append(r["id"])
            prev = r["event_hash"]
        return {"valid": not broken, "events_checked": len(rows), "broken_events": broken, "last_hash": prev,
                "note": "Integritätsprüfung gegen lokal gespeicherte Hashes, nicht gegen externen Trust-Anker."}
