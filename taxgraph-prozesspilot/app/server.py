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

from .legal_review_api import router as legal_review_router
from .auth import authenticate, current, local_principal, require_role, graph_access, case_access, run_access, capabilities
from .procedural_map import catalog as procedural_catalog
from .engine import execute
from .audit import source_snapshot
from .model import APP_VERSION, FACT_FIELDS, HANDLER_FACTS, LEGAL, SIGNAL_FACTS, sha256, validate_graph, seed_graph
from .storage import (activity, add_review, connect, create_case, get_case, get_run, graph_info, write_graph, uid,
                      graph_provenance, graph_revisions, init_db, list_graphs, load_graph, make_draft, now, publish_draft,
                      save_draft, save_facts, verify_run)

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if os.getenv("APP_ENV") == "production":
        with connect() as c:
            if not c.execute("SELECT 1 FROM app_users WHERE active=1 LIMIT 1").fetchone():
                raise RuntimeError("Produktivmodus erfordert Benutzerkonten.")
    yield


app = FastAPI(title="ProzessPilot §20 UmwStG", description="Auditierbarer deutscher Steuer-Prozessgraph (synthetisches MVP)",
              version=APP_VERSION, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.mount("/assets", StaticFiles(directory=str(STATIC)), name="assets")
# Fachpruefung-V2 additive integration
app.include_router(legal_review_router)


@app.middleware("http")
async def security(request: Request, call_next):
    if request.headers.get("content-length"):
        try:
            if int(request.headers["content-length"]) > 2_000_000:
                return JSONResponse({"detail": "Anfrage zu groß (max. 2 MB)."}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Ungültige Anfrage."}, status_code=400)
    production = os.getenv("APP_ENV", "local") == "production"
    identity = authenticate(request.headers.get("authorization", "")) if production else local_principal()
    if production and identity is None and request.url.path != "/api/health":
        return JSONResponse({"detail":"Authentifizierung erforderlich."},status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="ProzessPilot"'})
    # Preserve legacy local-demo password gate to prevent accidental exposure
    # when upgrading an existing APP_PASSWORD deployment.
    legacy_password = os.getenv("APP_PASSWORD", "")
    if not production and legacy_password and request.url.path != "/api/health":
        import base64
        import binascii
        header = request.headers.get("authorization", "")
        allowed = False
        if header.startswith("Basic "):
            try:
                user, pwd = base64.b64decode(header[6:], validate=True).decode("utf-8").split(":", 1)
                allowed = secrets.compare_digest(user, os.getenv("APP_USER", "admin")) and secrets.compare_digest(pwd, legacy_password)
            except (ValueError, UnicodeError, binascii.Error):
                pass
        if not allowed:
            return JSONResponse({"detail":"Authentifizierung erforderlich."},status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="ProzessPilot"'})
    request.state.principal = identity
    if production and request.url.path.startswith("/api") and request.url.path != "/api/health":
        mutating = request.method not in ("GET","HEAD","OPTIONS")
        if (mutating and identity.role == "viewer") or (
            mutating and identity.role != "reviewer" and
            (request.url.path.endswith("/publish") or request.url.path.endswith("/review"))):
            return JSONResponse({"detail":"Für diese Aktion fehlt die Berechtigung."},status_code=403)
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
def config(request: Request):
    return {"name": "ProzessPilot", "locale": "de-DE", "version": APP_VERSION, "synthetic_only": os.environ.get("ALLOW_REAL_CASES") != "1",
            "auth_enabled": os.getenv("APP_ENV") == "production", "identity": vars(current(request)), "capabilities": capabilities(current(request)), "legal_sources": LEGAL,
            "fact_fields": FACT_FIELDS, "signal_facts": SIGNAL_FACTS, "handler_facts": HANDLER_FACTS,
            "warning": "Demonstrator: keine Steuerberatung und keine geprüfte TaxGraph-API-Anbindung."}


@app.get("/api/graphs")
def graphs(request: Request):
    p=current(request)
    with connect() as c: return {"graphs": list_graphs(c,p.org_id,published_only=p.role=="viewer")}


@app.get("/api/graphs/{version_id}")
def get_graph(version_id: str, request: Request):
    with connect() as c:
        graph_access(request,c,version_id)
        return load_graph(c, version_id)


@app.get("/api/graphs/{version_id}/export")
def export_graph(version_id: str, request: Request):
    with connect() as c:
        graph_access(request,c,version_id)
        obj=load_graph(c, version_id)
        doc={"format": "ProzessPilot-Graph-1", "exported_at": now(),
             "meta": obj["meta"], "graph": {k: obj[k] for k in ("label", "nodes", "edges")},
             "revisions": graph_revisions(c, version_id)}
    filename=f"prozessgraph-{version_id}.json"
    return Response(content=json.dumps(doc,ensure_ascii=False,indent=2),media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.post("/api/graphs/{version_id}/draft")
def draft(version_id: str, args: ActorRequest, request: Request):
    require_role(request,"editor","reviewer")
    with connect() as c:
        graph_access(request,c,version_id)
        return make_draft(c, version_id, current(request).username)


@app.put("/api/graphs/{version_id}")
def edit_graph(version_id: str, args: DraftSaveRequest, request: Request):
    require_role(request,"editor","reviewer")
    with connect() as c:
        graph_access(request,c,version_id)
        return save_draft(c, version_id, args.graph, current(request).username, args.reason)


@app.get("/api/graphs/{version_id}/revisions")
def graph_history(version_id: str, request: Request):
    with connect() as c:
        graph_access(request,c,version_id)
        return {"revisions": graph_revisions(c, version_id)}


@app.get("/api/graphs/{version_id}/provenance")
def graph_element_history(version_id: str, request: Request):
    with connect() as c:
        graph_access(request,c,version_id)
        return graph_provenance(c, version_id)


@app.post("/api/graphs/{version_id}/publish")
def publish(version_id: str, args: PublishRequest, request: Request):
    require_role(request,"reviewer")
    if not args.confirm_expert_review:
        raise ValueError("Bitte die strukturelle Prüfung bestätigen. Es erfolgt keine automatische Rechtsprüfung.")
    require_role(request,"reviewer")
    with connect() as c:
        graph_access(request,c,version_id)
        return publish_draft(c, version_id, current(request).username)


@app.post("/api/graphs/validate")
def graph_validate(graph: dict):
    errors = validate_graph(graph)
    return {"valid": not errors, "errors": errors,
            "node_count": len(graph["nodes"]) if isinstance(graph.get("nodes"), list) else 0,
            "edge_count": len(graph["edges"]) if isinstance(graph.get("edges"), list) else 0}


@app.get("/api/cases")
def cases(request: Request):
    with connect() as c:
        rows = c.execute("SELECT * FROM cases WHERE org_id=? ORDER BY created_at DESC, id ASC", (current(request).org_id,)).fetchall()
        result = []
        for r in rows:
            v = dict(r)
            v["synthetic"] = bool(v["synthetic"])
            latest = c.execute("SELECT id,status,finished_at FROM runs WHERE case_id=? ORDER BY started_at DESC,rowid DESC LIMIT 1", (r["id"],)).fetchone()
            v["latest_run"] = dict(latest) if latest else None
            result.append(v)
    return {"cases": result}


@app.post("/api/cases", status_code=201)
def new_case(args: NewCase, request: Request):
    with connect() as c:
        require_role(request,"editor")
        cid = create_case(c, args.title, args.description, facts=args.facts, synthetic=True, actor=current(request).username, org_id=current(request).org_id)
        return get_case(c, cid)


@app.get("/api/cases/{case_id}")
def case_get(case_id: str, request: Request):
    with connect() as c:
        case_access(request,c,case_id)
        return get_case(c, case_id)


@app.put("/api/cases/{case_id}/facts")
def case_update(case_id: str, args: FactsUpdate, request: Request):
    require_role(request,"editor","reviewer")
    with connect() as c:
        case_access(request,c,case_id)
        return save_facts(c, case_id, args.facts, current(request).username)


@app.get("/api/cases/{case_id}/runs")
def case_runs(case_id: str, request: Request):
    with connect() as c:
        case_access(request,c,case_id)
        get_case(c, case_id)
        runs = [dict(r) for r in c.execute("SELECT id,status,graph_version,started_at,finished_at FROM runs WHERE case_id=? ORDER BY started_at DESC,rowid DESC", (case_id,))]
    return {"runs": runs}


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str, args: RunRequest, request: Request):
    with connect() as c:
        require_role(request,"editor","reviewer")
        case_access(request,c,case_id)
        graph_access(request,c,args.graph_version)
        result = execute(c, case_id, args.graph_version)
        activity(c, "case", case_id, "RUN_EXECUTED", "Graph-Executor",
                 {"run_id": result["run_id"], "graph_version": args.graph_version, "status": result["result"]["status"]})
        return {**result, "audit": verify_run(c, result["run_id"])}


@app.post("/api/cases/{case_id}/review")
def review_case(case_id: str, args: ReviewRequest, request: Request):
    with connect() as c:
        require_role(request,"reviewer")
        case_access(request,c,case_id)
        run_access(request,c,args.run_id)
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
        rev = add_review(c, case_id, run["graph_version"], current(request).username, args.decision, args.note, run["facts_hash"])
        return {"review": rev, "message": "Freigabeentscheidung dokumentiert. Neuen Prüflauf starten, um sie im Graph abzubilden."}


@app.get("/api/runs/{run_id}")
def run_get(run_id: str, request: Request):
    with connect() as c:
        run_access(request,c,run_id)
        run = get_run(c, run_id)
        run["verification"] = verify_run(c, run_id)
        return run


@app.get("/api/runs/{run_id}/audit")
def run_audit(run_id: str, request: Request):
    with connect() as c:
        run_access(request,c,run_id)
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
def activities(request: Request):
    require_role(request,"reviewer")
    if os.getenv("APP_ENV") == "production":
        raise HTTPException(403, "Globales Aktivitätsprotokoll ist nicht organisationsisoliert.")
    with connect() as c:
        rows = c.execute("SELECT * FROM activity_events ORDER BY id DESC LIMIT 150").fetchall()
        return {"activity": [{**dict(r), "detail": json.loads(r["detail_json"])} for r in rows]}


@app.get("/api/audit/activity/verify")
def activity_verify(request: Request):
    require_role(request,"reviewer")
    if os.getenv("APP_ENV") == "production":
        raise HTTPException(403, "Globales Aktivitätsprotokoll ist nicht organisationsisoliert.")
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


@app.get("/api/procedural-map")
def procedural_map(request: Request):
    current(request)
    return procedural_catalog()


class NewProcessRequest(BaseModel):
    label: str = Field(min_length=3, max_length=120)


@app.post("/api/processes", status_code=201)
def create_process(body: NewProcessRequest, request: Request):
    identity = require_role(request, "editor")
    graph = seed_graph()
    graph["label"] = body.label.strip()
    with connect() as c:
        slug = "org/" + identity.org_id + "/" + uid("process")
        version_id = uid("g")
        write_graph(c, version_id, slug, 1, graph, "draft", identity.username,
                    "Neuer Prozess auf Basis des geprüften §20-Demo-Templates",
                    org_id=identity.org_id)
        return load_graph(c, version_id)
