"""Organization-scoped lifecycle of versioned executable process packages.

No network calls or LLM decisions. V1/V2 remain frozen for historical replay;
current process runs use functional_graph -> legal_v3 exactly once.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ConfigDict

from .auth import current, require_role, case_access, capabilities
from .storage import connect, get_case, now, uid
from .model import FACT_FIELDS
from .legal_v3 import EXTRA_FIELDS, ENGINE_VERSION, LAW_AS_OF, _record
from .functional_graph import (default_definition, validate, import_source, coverage,
                               canonical, digest, run, verify)

router = APIRouter(prefix='/api/functional', tags=['Integrated process V3'])
page_router = APIRouter()
CORE = {field['key'] for field in FACT_FIELDS}
EXTRA = {field[0] for field in EXTRA_FIELDS} - CORE


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class NewProcess(StrictBody):
    label: str = Field(min_length=3, max_length=180)


class EditProcess(StrictBody):
    definition: dict[str, Any]
    expected_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=12, max_length=1000)


class SourceImport(StrictBody):
    source: dict[str, Any]
    expected_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=12, max_length=1000)


class PublishProcess(StrictBody):
    expected_hash: str = Field(min_length=64, max_length=64)
    confirm_normalizations: bool
    acknowledge_source_limits: bool
    note: str = Field(min_length=12, max_length=1000)


class InputUpdate(StrictBody):
    extra_facts: dict[str, dict[str, Any]]
    expected_hash: str = Field(min_length=64, max_length=64)


class RunRequest(StrictBody):
    process_id: str = Field(min_length=1, max_length=80)
    expected_inputs_hash: str = Field(min_length=64, max_length=64)
    expected_case_hash: str = Field(min_length=64, max_length=64)
    as_of: str = LAW_AS_OF


class Decision(StrictBody):
    decision: Literal['approved', 'rejected']
    expected_run_hash: str = Field(min_length=64, max_length=64)
    note: str = Field(min_length=12, max_length=2000)


def init_schema(c):
    # Additive migration; historical graph checksums and assessment files are untouched.
    c.executescript('''
      CREATE TABLE IF NOT EXISTS process_packages (
        id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id),
        family_id TEXT NOT NULL, version INTEGER NOT NULL, parent_id TEXT,
        label TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','published')),
        definition_json TEXT NOT NULL, definition_hash TEXT NOT NULL,
        created_at TEXT NOT NULL, created_by TEXT NOT NULL,
        published_at TEXT, published_by TEXT, publication_note TEXT,
        UNIQUE(org_id,family_id,version));
      CREATE TABLE IF NOT EXISTS process_package_events (
        package_id TEXT NOT NULL REFERENCES process_packages(id), seq INTEGER NOT NULL,
        body_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
        PRIMARY KEY(package_id,seq));
      CREATE TABLE IF NOT EXISTS functional_case_inputs (
        case_id TEXT PRIMARY KEY REFERENCES cases(id), data_json TEXT NOT NULL,
        inputs_hash TEXT NOT NULL, updated_at TEXT NOT NULL, actor TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS functional_runs (
        id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES orgs(id),
        case_id TEXT NOT NULL REFERENCES cases(id), package_id TEXT NOT NULL REFERENCES process_packages(id),
        case_hash TEXT NOT NULL, inputs_hash TEXT NOT NULL, definition_hash TEXT NOT NULL,
        document_json TEXT NOT NULL, document_hash TEXT NOT NULL,
        overall TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS functional_reviews (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES functional_runs(id),
        body_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS idx_packages_org ON process_packages(org_id,status);
      CREATE INDEX IF NOT EXISTS idx_functional_case ON functional_runs(case_id,created_at);
    ''')


def append_event(c, package_id, actor, kind, definition, note):
    previous = c.execute('SELECT seq,event_hash FROM process_package_events WHERE package_id=? ORDER BY seq DESC LIMIT 1', (package_id,)).fetchone()
    seq, prev_hash = (previous['seq'] + 1, previous['event_hash']) if previous else (1, '0' * 64)
    body = {'package_id': package_id, 'seq': seq, 'actor': actor, 'kind': kind,
            'at': now(), 'note': note, 'definition': definition, 'definition_hash': digest(definition)}
    event_hash = digest({'body': body, 'prev_hash': prev_hash})
    c.execute('INSERT INTO process_package_events VALUES(?,?,?,?,?)', (package_id, seq, canonical(body), prev_hash, event_hash))


def insert_package(c, org_id, definition, actor, *, family_id=None, parent_id=None, published=False):
    validate(definition)
    family_id = family_id or uid('family')
    version = c.execute('SELECT COALESCE(MAX(version),0)+1 FROM process_packages WHERE org_id=? AND family_id=?', (org_id, family_id)).fetchone()[0]
    package_id, timestamp = uid('process'), now()
    status = 'published' if published else 'draft'
    note = 'Synthetisches Referenzmodell; keine externe Quellen- oder Berufsfreigabe.' if published else None
    c.execute('INSERT INTO process_packages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (package_id, org_id, family_id, version, parent_id, definition['label'], status,
               canonical(definition), digest(definition), timestamp, actor,
               timestamp if published else None, actor if published else None, note))
    append_event(c, package_id, actor, 'REFERENCE_CREATED' if published else 'DRAFT_CREATED', definition, note or 'Neuer unveroeffentlichter Prozessentwurf')
    return package_id


def seed_org(c, org_id):
    if not c.execute('SELECT 1 FROM process_packages WHERE org_id=? LIMIT 1', (org_id,)).fetchone():
        insert_package(c, org_id, default_definition(), 'Systemdemo', published=True)


def initialize():
    with connect() as c:
        init_schema(c)
        for row in c.execute('SELECT id FROM orgs').fetchall():
            seed_org(c, row['id'])


def package(c, request, package_id):
    user = current(request)
    row = c.execute('SELECT * FROM process_packages WHERE id=? AND org_id=?', (package_id, user.org_id)).fetchone()
    if row is None or (user.role == 'viewer' and row['status'] != 'published'):
        raise HTTPException(404, 'Prozess nicht gefunden.')
    obj = dict(row)
    obj['definition'] = json.loads(obj.pop('definition_json'))
    if digest(obj['definition']) != obj['definition_hash']:
        raise HTTPException(409, 'Prozessintegritaet verletzt.')
    obj['coverage'] = coverage(obj['definition'])
    obj['events'] = events(c, package_id)
    if not obj['events'] or obj['events'][-1]['definition_hash'] != obj['definition_hash']:
        raise HTTPException(409, 'Prozessstand stimmt nicht mit der Revisionskette ueberein.')
    return obj


def events(c, package_id):
    result, previous = [], '0' * 64
    for row in c.execute('SELECT * FROM process_package_events WHERE package_id=? ORDER BY seq', (package_id,)):
        body = json.loads(row['body_json'])
        if row['prev_hash'] != previous or row['event_hash'] != digest({'body': body, 'prev_hash': previous}):
            raise HTTPException(409, 'Revisionskette verletzt.')
        result.append({**body, 'prev_hash': previous, 'event_hash': row['event_hash']})
        previous = row['event_hash']
    return result


def inputs(c, case_id):
    row = c.execute('SELECT * FROM functional_case_inputs WHERE case_id=?', (case_id,)).fetchone()
    if row is None:
        return {'extra_facts': {}, 'inputs_hash': digest({})}
    data = json.loads(row['data_json'])
    if digest(data) != row['inputs_hash']:
        raise HTTPException(409, 'Zusatzfaktenintegritaet verletzt.')
    return {'extra_facts': data, 'inputs_hash': row['inputs_hash']}


def match_hash(actual, expected):
    if actual != expected:
        raise HTTPException(409, 'Stand inzwischen geaendert. Neu laden und Aenderungen abgleichen.')


def edit(c, request, process_id, definition, expected_hash, reason):
    old = package(c, request, process_id)
    if old['status'] != 'draft':
        raise HTTPException(409, 'Veroeffentlichte Prozesse sind unveraenderlich; neuen Entwurf anlegen.')
    match_hash(old['definition_hash'], expected_hash)
    validate(definition)
    c.execute('UPDATE process_packages SET label=?,definition_json=?,definition_hash=? WHERE id=?',
              (definition['label'], canonical(definition), digest(definition), process_id))
    append_event(c, process_id, current(request).username, 'DRAFT_UPDATED', definition, reason)
    return package(c, request, process_id)


def get_run(c, request, run_id):
    user = current(request)
    row = c.execute('SELECT * FROM functional_runs WHERE id=? AND org_id=?', (run_id, user.org_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Prueflauf nicht gefunden.')
    obj = dict(row)
    case_access(request, c, row['case_id'])
    obj['document'] = json.loads(obj.pop('document_json'))
    obj['verification'] = verify(obj['document'])
    obj['verification']['stored_hash_matches'] = (row['document_hash'] == obj['document'].get('hash') and row['definition_hash'] == obj['document'].get('definition_hash') and row['overall'] == obj['document'].get('overall'))
    obj['verification']['valid'] &= obj['verification']['stored_hash_matches']
    obj['current_inputs_match'] = (digest(get_case(c, row['case_id'])['facts']) == row['case_hash'] and
                                   inputs(c, row['case_id'])['inputs_hash'] == row['inputs_hash'])
    obj['reviews'], prev = [], '0' * 64
    for review in c.execute('SELECT * FROM functional_reviews WHERE run_id=? ORDER BY rowid', (run_id,)):
        body = json.loads(review['body_json'])
        if review['prev_hash'] != prev or review['event_hash'] != digest({'body': body, 'prev_hash': prev}):
            raise HTTPException(409, 'Freigabekette verletzt.')
        obj['reviews'].append({**body, 'event_hash': review['event_hash']})
        prev = review['event_hash']
    obj['approval_effective'] = (obj['current_inputs_match'] and obj['verification']['valid'] and
                                  bool(obj['reviews']) and obj['reviews'][-1]['decision'] == 'approved')
    return obj


@page_router.get('/prozesse', include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent / 'static' / 'functional.html')


@router.get('/schema')
def schema(request: Request):
    return {'ruleset': ENGINE_VERSION, 'law_as_of': LAW_AS_OF, 'identity': vars(current(request)),
            'capabilities': capabilities(current(request)), 'core_fields': FACT_FIELDS,
            'extra_fields': [{'key': k, 'label': label, 'type': typ, 'group': group, 'choices': choices}
                             for k, label, typ, group, choices in EXTRA_FIELDS],
            'notice': 'Synthetisches Modell 2025/2026. Kein vollstaendig verifizierter Remote-Import, keine Steuerberatung.'}


@router.get('/processes')
def list_processes(request: Request):
    p = current(request)
    with connect() as c:
        rows = c.execute("SELECT id,label,status,version,family_id,parent_id,definition_hash,created_by,published_by FROM process_packages WHERE org_id=?" +
                         (" AND status='published'" if p.role == 'viewer' else '') + ' ORDER BY created_at DESC,rowid DESC', (p.org_id,)).fetchall()
        return {'processes': [dict(row) for row in rows]}


@router.post('/processes', status_code=201)
def new_process(body: NewProcess, request: Request):
    p = require_role(request, 'editor')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        definition = default_definition(); definition['label'] = body.label
        process_id = insert_package(c, p.org_id, definition, p.username)
        return package(c, request, process_id)


@router.get('/processes/{process_id}')
def process_get(process_id: str, request: Request):
    with connect() as c:
        return package(c, request, process_id)


@router.post('/processes/{process_id}/draft', status_code=201)
def new_draft(process_id: str, request: Request):
    p = require_role(request, 'editor', 'reviewer')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = package(c, request, process_id)
        new_id = insert_package(c, p.org_id, old['definition'], p.username, family_id=old['family_id'], parent_id=old['id'])
        return package(c, request, new_id)


@router.put('/processes/{process_id}')
def process_edit(process_id: str, body: EditProcess, request: Request):
    require_role(request, 'editor', 'reviewer')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        return edit(c, request, process_id, body.definition, body.expected_hash, body.reason)


@router.post('/processes/{process_id}/source')
def source_import(process_id: str, body: SourceImport, request: Request):
    require_role(request, 'editor', 'reviewer')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = package(c, request, process_id)
        definition = import_source(body.source, old['definition'])
        return edit(c, request, process_id, definition, body.expected_hash, body.reason)


@router.post('/processes/{process_id}/publish')
def publish(process_id: str, body: PublishProcess, request: Request):
    user = require_role(request, 'reviewer')
    if not body.confirm_normalizations or not body.acknowledge_source_limits:
        raise HTTPException(422, 'Normalisierungen und Quellenbegrenzung ausdruecklich bestaetigen.')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        obj = package(c, request, process_id)
        if obj['status'] != 'draft': raise HTTPException(409, 'Nur Entwuerfe veroeffentlichen.')
        match_hash(obj['definition_hash'], body.expected_hash)
        validate(obj['definition'])
        from .functional_golden import check_definition
        failures = check_definition(obj['definition'])
        if failures:
            raise HTTPException(422, {'message': 'Semantische Regressionstests fehlgeschlagen.', 'failures': failures})
        c.execute("UPDATE process_packages SET status='published',published_at=?,published_by=?,publication_note=? WHERE id=?",
                  (now(), user.username, body.note, process_id))
        append_event(c, process_id, user.username, 'PUBLISHED_WITH_EXPLICIT_LIMITS', obj['definition'], body.note)
        return package(c, request, process_id)


@router.get('/cases/{case_id}/inputs')
def case_inputs(case_id: str, request: Request):
    with connect() as c:
        case_access(request, c, case_id)
        return {**inputs(c, case_id), 'case_hash': digest(get_case(c, case_id)['facts'])}


@router.put('/cases/{case_id}/inputs')
def save_inputs(case_id: str, body: InputUpdate, request: Request):
    user = require_role(request, 'editor', 'reviewer')
    if len(body.extra_facts) > len(EXTRA) or not set(body.extra_facts) <= EXTRA:
        raise HTTPException(422, 'Unbekannte Zusatzfelder oder Ueberschreibung der Fallfakten.')
    if len(canonical(body.extra_facts).encode()) > 100_000:
        raise HTTPException(413, 'Zusatzfakten zu gross.')
    normalized = {key: _record(value) for key, value in body.extra_facts.items()}
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        case_access(request, c, case_id)
        match_hash(inputs(c, case_id)['inputs_hash'], body.expected_hash)
        existing = {f['key']: _record(f) for f in get_case(c, case_id)['facts']}
        if any(key in existing and existing[key] != value for key, value in normalized.items()):
            raise HTTPException(422, 'Zusatzangabe widerspricht vorhandener Fallakte; Fallakte zuerst abstimmen.')
        c.execute('INSERT INTO functional_case_inputs VALUES(?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET data_json=excluded.data_json,inputs_hash=excluded.inputs_hash,updated_at=excluded.updated_at,actor=excluded.actor',
                  (case_id, canonical(normalized), digest(normalized), now(), user.username))
        return {**inputs(c, case_id), 'case_hash': digest(get_case(c, case_id)['facts'])}


@router.post('/cases/{case_id}/runs', status_code=201)
def execute_case(case_id: str, body: RunRequest, request: Request):
    user = require_role(request, 'editor', 'reviewer')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        case_access(request, c, case_id)
        case = get_case(c, case_id)
        if not case['synthetic'] or case.get('context_id') != 'demo-2026':
            raise HTTPException(422, 'Nur synthetische Faelle im unterstuetzten Rechtskontext.')
        pkg = package(c, request, body.process_id)
        if pkg['status'] != 'published': raise HTTPException(409, 'Nur veroeffentlichte Prozessversionen ausfuehren.')
        extra = inputs(c, case_id)
        case_hash = digest(case['facts'])
        match_hash(case_hash, body.expected_case_hash)
        match_hash(extra['inputs_hash'], body.expected_inputs_hash)
        facts = {item['key']: item for item in case['facts']}
        for key, value in extra['extra_facts'].items():
            if key in facts and _record(facts[key]) != value:
                raise HTTPException(409, 'Fallakte und Zusatzangaben widersprechen sich.')
            facts[key] = value
        document = run(pkg['definition'], facts, as_of=body.as_of)
        run_id = uid('integrated')
        c.execute('INSERT INTO functional_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (run_id, user.org_id, case_id, pkg['id'], case_hash, extra['inputs_hash'], pkg['definition_hash'],
                   canonical(document), document['hash'], document['overall'], user.username, now()))
        return get_run(c, request, run_id)


@router.get('/cases/{case_id}/runs')
def case_runs(case_id: str, request: Request):
    with connect() as c:
        case_access(request, c, case_id)
        rows = c.execute('SELECT id,package_id,overall,actor,created_at FROM functional_runs WHERE case_id=? AND org_id=? ORDER BY created_at DESC,rowid DESC', (case_id, current(request).org_id)).fetchall()
        return {'runs': [dict(row) for row in rows]}


@router.get('/runs/{run_id}')
def run_get(run_id: str, request: Request):
    with connect() as c: return get_run(c, request, run_id)


@router.get('/runs/{run_id}/export')
def export(run_id: str, request: Request):
    with connect() as c:
        obj = get_run(c, request, run_id)
        pkg = package(c, request, obj['package_id'])
        obj['process_revisions'] = pkg['events']
    return Response(json.dumps(obj, ensure_ascii=False, indent=2), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="' + run_id + '.json"'})


@router.post('/runs/{run_id}/review')
def review(run_id: str, body: Decision, request: Request):
    user = require_role(request, 'reviewer')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        obj = get_run(c, request, run_id)
        match_hash(obj['document_hash'], body.expected_run_hash)
        if not obj['verification']['valid'] or not obj['current_inputs_match']:
            raise HTTPException(409, 'Historischer, veraenderter oder nicht reproduzierbarer Lauf; neu ausfuehren.')
        if body.decision == 'approved' and obj['overall'] != 'READY_FOR_EXPERT_REVIEW':
            raise HTTPException(422, 'Offene, negative oder unvollstaendige Pruefung nicht freigeben.')
        prev = obj['reviews'][-1]['event_hash'] if obj['reviews'] else '0' * 64
        record = {'run_id': run_id, 'run_hash': obj['document_hash'], 'definition_hash': obj['definition_hash'],
                  'inputs_hash': obj['inputs_hash'], 'case_hash': obj['case_hash'], 'reviewer': user.username,
                  'org_id': user.org_id, 'decision': body.decision, 'note': body.note, 'at': now()}
        c.execute('INSERT INTO functional_reviews VALUES(?,?,?,?,?)',
                  (uid('review'), run_id, canonical(record), prev, digest({'body': record, 'prev_hash': prev})))
        return get_run(c, request, run_id)
