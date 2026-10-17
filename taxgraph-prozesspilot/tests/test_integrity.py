"""Regression checks for independently reviewable execution records."""
import copy
import json
import subprocess
import sys
import sqlite3

import pytest

from test_app import cases_by_letter, client, execute
from app.model import seed_graph, validate_graph
from app.storage import connect


def test_truncated_audit_and_changed_run_metadata_are_detected(client):
    run = execute(client, cases_by_letter(client)['A'])
    rid = run['run_id']
    with connect() as db:
        db.execute('DELETE FROM run_events WHERE run_id=? AND seq=(SELECT max(seq) FROM run_events WHERE run_id=?)', (rid, rid))
    check = client.get(f'/api/runs/{rid}').json()['verification']
    assert not check['execution_integrity']
    run = execute(client, cases_by_letter(client)['A'])
    rid = run['run_id']
    with connect() as db:
        db.execute("UPDATE runs SET status='FREIGEGEBEN_IM_PROTOTYP' WHERE id=?", (rid,))
    assert not client.get(f'/api/runs/{rid}').json()['verification']['execution_integrity']


def test_facts_hash_is_anchored_in_execution_events(client):
    rid = execute(client, cases_by_letter(client)['A'])['run_id']
    from app.model import canonical, sha256
    with connect() as db:
        db.execute('UPDATE runs SET facts_snapshot=?,facts_hash=? WHERE id=?', (canonical({}), sha256({}), rid))
    assert not client.get(f'/api/runs/{rid}').json()['verification']['facts_integrity']


@pytest.mark.parametrize('field,value', [('kind', []), ('id', []), ('signal', {}), ('legal_refs', [{}])])
def test_malformed_graph_is_a_validation_result(client, field, value):
    graph = seed_graph()
    graph['nodes'][0][field] = value
    response = client.post('/api/graphs/validate', json=graph)
    assert response.status_code == 200
    assert not response.json()['valid']


def test_action_cannot_declare_an_ignored_signal(client):
    graph = seed_graph()
    graph['nodes'][0]['signal'] = 'new_shares'
    graph['edges'][0]['guard'] = {'operator': 'eq', 'signal': 'new_shares', 'value': 'always'}
    assert not client.post('/api/graphs/validate', json=graph).json()['valid']


@pytest.mark.parametrize('book,extra,status', [
    (2000000.03, 500000.01, 'BUCHWERT_NICHT_GESICHERT'),
    (2000000.04, 500000.01, 'FREIGABE_OFFEN'),
    (3000000, 750000, 'FREIGABE_OFFEN'),
    (3000000, 750000.01, 'BUCHWERT_NICHT_GESICHERT'),
])
def test_money_boundary_is_not_rounded_up(client, book, extra, status):
    cid = cases_by_letter(client)['A']
    facts = client.get(f'/api/cases/{cid}').json()['facts']
    for fact in facts:
        if fact['key'] in ('book_value', 'other_consideration'):
            fact['value'] = book if fact['key'] == 'book_value' else extra
    assert client.put(f'/api/cases/{cid}/facts', json={'facts': facts}).status_code == 200
    result = execute(client, cid)
    assert result['result']['status'] == status


def test_corrupt_pending_run_cannot_be_approved(client):
    cid = cases_by_letter(client)['A']
    rid = execute(client, cid)['run_id']
    with connect() as db:
        db.execute('DELETE FROM run_events WHERE run_id=? AND seq=2', (rid,))
    response = client.post(f'/api/cases/{cid}/review', json={
        'run_id': rid, 'reviewer': 'Demo Fachperson', 'decision': 'approved',
        'note': 'Synthetische Prüfung zur Korruptionserkennung.'})
    assert response.status_code == 422


def test_approval_and_legal_sources_are_frozen_and_offline_verifiable(client, tmp_path, monkeypatch):
    cid = cases_by_letter(client)['A']
    first = execute(client, cid)
    review = client.post(f'/api/cases/{cid}/review', json={
        'run_id': first['run_id'], 'reviewer': 'Demo Fachperson', 'decision': 'approved',
        'note': 'Synthetische Fachprüfung vollständig dokumentiert.'}).json()['review']
    rid = execute(client, cid)['run_id']
    doc = client.get(f'/api/runs/{rid}/audit').json()
    signal = next(e['detail'] for e in doc['run']['events'] if e['event_type'] == 'SIGNAL_EVALUATED' and e['detail']['signal'] == 'professional_review')
    assert signal['review_record'] == review
    assert all('actor' in event['detail'] for event in doc['run']['events'])
    assert doc['legal_sources'] == doc['run']['events'][0]['detail']['legal_sources']
    from app.model import LEGAL
    monkeypatch.setitem(LEGAL, 'U20_1', {'label': 'Später geänderte Quelle'})
    later = client.get(f'/api/runs/{rid}/audit').json()
    assert later['legal_sources'] == doc['legal_sources']
    assert later['integrity']['context_integrity']
    file = tmp_path / 'audit.json'
    file.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    command = [sys.executable, 'scripts/verify_audit.py', str(file)]
    verified = subprocess.run(command, text=True, capture_output=True)
    assert verified.returncode == 0, verified.stderr + verified.stdout
    doc['run']['events'].pop()
    file.write_text(json.dumps(doc), encoding='utf-8')
    assert subprocess.run(command, capture_output=True).returncode == 1


def test_graph_paths_up_to_validator_limit_execute(client):
    draft = client.post('/api/graphs/umwstg20-v1/draft', json={'actor': 'Demo Test'}).json()
    graph = {key: copy.deepcopy(draft[key]) for key in ('label', 'nodes', 'edges')}
    # A valid 139-node graph used to fail at the executor's unrelated 128-step cap.
    start = next(e for e in graph['edges'] if e['id'] == 'E_START')
    start['target'] = 'EXTRA_0'
    for i in range(120):
        graph['nodes'].append({'id': f'EXTRA_{i}', 'kind': 'ACTION', 'title': 'Zusätzlicher Schritt',
                              'description': 'Synthetischer Pfadtest', 'x': 0, 'y': 0,
                              'signal': None, 'legal_refs': [], 'handler': None})
        graph['edges'].append({'id': f'EXTRA_EDGE_{i}', 'source': f'EXTRA_{i}',
                              'target': f'EXTRA_{i+1}' if i < 119 else 'SCOPE',
                              'outcome': 'always', 'label': 'Weiter', 'relation': 'LEADS_TO',
                              'guard': {'operator': 'always'}, 'guidance': '', 'pitfalls': ''})
    assert not validate_graph(graph)
    vid = draft['meta']['id']
    assert client.put(f'/api/graphs/{vid}', json={'graph': graph}).status_code == 200
    assert client.post(f'/api/graphs/{vid}/publish', json={'actor': 'Demo Test', 'confirm_expert_review': True}).status_code == 200
    assert execute(client, cases_by_letter(client)['A'], vid)['result']['status'] == 'FREIGABE_OFFEN'


def test_rehashed_but_inconsistent_trace_is_detected(client):
    from app.audit import verify_document
    from app.model import sha256
    rid = execute(client, cases_by_letter(client)['A'])['run_id']
    doc = client.get(f'/api/runs/{rid}/audit').json()
    event = next(e for e in doc['run']['events'] if e['event_type'] == 'GUARDS_EVALUATED')
    event['detail']['candidates'][0]['guard_result'] = False
    previous = '0' * 64
    for event in doc['run']['events']:
        event['prev_hash'] = previous
        event['event_hash'] = sha256({k: event[k] for k in ('run_id','seq','event_type','detail','at','prev_hash')})
        previous = event['event_hash']
    verdict = verify_document(doc)
    assert verdict['event_chain_integrity'] and verdict['result_integrity']
    assert not verdict['execution_integrity'] and not verdict['valid']


@pytest.mark.parametrize('field', ['asset_type','receiving_company','new_shares','essential_assets',
    'future_corporate_tax','assets_ge_liabilities','german_tax_right','book_value','other_consideration',
    'application_timely','planned_disposal'])
def test_every_decision_preserves_unknown(client, field):
    cid = cases_by_letter(client)['A']
    facts = client.get(f'/api/cases/{cid}').json()['facts']
    fact = next(f for f in facts if f['key'] == field)
    fact.update(value=None, verification='unknown', evidence_ref='')
    assert client.put(f'/api/cases/{cid}/facts', json={'facts':facts}).status_code == 200
    result = execute(client, cid)
    assert result['result']['status'] == ('FREIGABE_OFFEN' if field == 'planned_disposal' else 'NACHWEISE_FEHLEN')
    doc = client.get(f'/api/runs/{result["run_id"]}/audit').json()
    assert doc['integrity']['valid']
    assert any(e['event_type']=='SIGNAL_EVALUATED' and e['detail']['outcome']=='unknown' for e in doc['run']['events'])


def test_backup_and_startup_preserve_case_and_run(client, tmp_path):
    from app.server import app
    from fastapi.testclient import TestClient
    cid = cases_by_letter(client)['A']
    rid = execute(client, cid)['run_id']
    backup = tmp_path / 'backup.sqlite3'
    result = subprocess.run([sys.executable,'scripts/backup_sqlite.py',str(backup)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(backup) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT count(*) FROM runs WHERE id=?',(rid,)).fetchone()[0] == 1
    with TestClient(app) as restarted:
        assert restarted.get(f'/api/runs/{rid}').json()['verification']['valid']
        assert len(restarted.get('/api/cases').json()['cases']) == 4


@pytest.mark.parametrize('facts', [[{}], [{'key':[]}], [{'key':'does_not_exist'}]])
def test_invalid_facts_do_not_create_partial_cases(client, facts, monkeypatch):
    # Isolate validation under an editor; viewer/reviewer creation is denied by design.
    from app.auth import Principal
    monkeypatch.setattr('app.server.local_principal', lambda role=None: Principal('Validation Author','demo','editor'))
    response = client.post('/api/cases',json={'title':'Ungültiger synthetischer Fall','facts':facts})
    assert response.status_code == 422
    assert len(client.get('/api/cases').json()['cases']) == 4
