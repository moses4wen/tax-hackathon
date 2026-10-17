"""Additive §20 legal reasoning endpoints; does not mutate the legacy graph or runs.

Synthetic cases only. Case facts remain the authority for legacy fields. The supplement
stores immutable input/result snapshots and exposes a replay-verifiable export.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .legal_reasoning import ENGINE_VERSION, EXTRA_FIELDS, LAW_AS_OF, _record, assess, verify
from .storage import connect, get_case

router = APIRouter(tags=["Fachprüfung §20 V2"])
PAGE = Path(__file__).resolve().parent / "static" / "fachpruefung.html"
FIELDS = {field[0] for field in EXTRA_FIELDS}


class ReviewRequest(BaseModel):
    extra_facts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    as_of: str = LAW_AS_OF


def _ensure_table(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS legal_assessment_runs (
        id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        engine_version TEXT NOT NULL,
        fact_hash TEXT NOT NULL,
        result_hash TEXT NOT NULL,
        report_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(case_id) REFERENCES cases(id)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_legal_assessment_case ON legal_assessment_runs(case_id,created_at DESC)")


def _get_document(c, case_id: str, run_id: str) -> dict:
    _ensure_table(c)
    row = c.execute("SELECT * FROM legal_assessment_runs WHERE id=? AND case_id=?", (run_id, case_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Fachprüfung nicht gefunden.")
    document = json.loads(row["report_json"])
    audit = verify(document)
    current = get_case(c, case_id)
    current_facts = {fact["key"]: _record(fact) for fact in current["facts"]}
    matches = all(document.get("facts", {}).get(key) == value for key, value in current_facts.items())
    return {"run_id": run_id, "case_id": case_id, "created_at": row["created_at"],
            "report": document, "verification": audit, "current_case_facts_match": matches}


@router.get("/fachpruefung", include_in_schema=False)
def fachpruefung_page():
    return FileResponse(PAGE, media_type="text/html")


@router.get("/api/fachpruefung/schema")
def get_schema():
    return {"engine_version": ENGINE_VERSION, "law_as_of": LAW_AS_OF,
            "fields": [{"key": k, "label": label, "type": typ, "group": group,
                        **({"choices": choices} if choices else {})}
                       for k, label, typ, group, choices in EXTRA_FIELDS],
            "notice": "Nur synthetische Fälle. Erforderliche Nachweisreferenzen werden nicht auf Echtheit geprüft."}


@router.post("/api/cases/{case_id}/fachpruefung")
def run_legal_review(case_id: str, body: ReviewRequest):
    if len(body.extra_facts) > len(FIELDS) or not set(body.extra_facts) <= FIELDS:
        raise HTTPException(status_code=422, detail="Unbekanntes oder zu umfangreiches Zusatzfeld.")
    with connect() as c:
        case = get_case(c, case_id)
        if not case["synthetic"]:
            raise HTTPException(status_code=403, detail="Reale Fälle sind für die Fachprüfung V2 gesperrt.")
        if case.get("context_id") != "demo-2026":
            raise HTTPException(status_code=422, detail="Historischer Rechtskontext benötigt eigene Regelversion.")
        facts = {item["key"]: item for item in case["facts"]}
        facts.update(body.extra_facts)
        try:
            report = assess(facts, as_of=body.as_of)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err)) from err
        _ensure_table(c)
        run_id = "legal_" + uuid.uuid4().hex[:16]
        time = datetime.now(timezone.utc).isoformat()
        c.execute("""INSERT INTO legal_assessment_runs(
            id,case_id,engine_version,fact_hash,result_hash,report_json,created_at)
            VALUES(?,?,?,?,?,?,?)""",
            (run_id, case_id, ENGINE_VERSION, report["facts_hash"], report["result_hash"],
             json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")), time))
        return {"run_id": run_id, "case_id": case_id, "created_at": time,
                "report": report, "verification": verify(report), "current_case_facts_match": True}


@router.get("/api/cases/{case_id}/fachpruefung/latest")
def last_legal_review(case_id: str):
    with connect() as c:
        get_case(c, case_id)
        _ensure_table(c)
        row = c.execute("""SELECT id FROM legal_assessment_runs WHERE case_id=?
                           ORDER BY created_at DESC, rowid DESC LIMIT 1""", (case_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Noch keine ausführliche Fachprüfung.")
        return _get_document(c, case_id, row["id"])


@router.get("/api/cases/{case_id}/fachpruefung/{run_id}")
def get_legal_review(case_id: str, run_id: str):
    with connect() as c:
        return _get_document(c, case_id, run_id)


@router.get("/api/cases/{case_id}/fachpruefung/{run_id}/export")
def export_legal_review(case_id: str, run_id: str):
    with connect() as c:
        obj = _get_document(c, case_id, run_id)
        return Response(json.dumps(obj, ensure_ascii=False, indent=2), media_type="application/json; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="fachpruefung-{run_id}.json"',
                                 "Cache-Control": "no-store"})
