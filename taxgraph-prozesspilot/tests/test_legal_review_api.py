"""Run in the original repository after apply_completion.py has patched app.server.

Covers the real FastAPI/SQLite integration; does not call TaxGraph or external services.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.server import app
from app.storage import connect
from app.legal_reasoning import EXTRA_FIELDS
from test_legal_reasoning import sample


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'legal_v2.sqlite3'))
    monkeypatch.delenv('APP_PASSWORD',raising=False)
    with TestClient(app) as instance:
        yield instance


def a_case(client):
    return next(x['id'] for x in client.get('/api/cases').json()['cases']
                if x['title'].startswith('Musterfall A'))


def extra():
    data=sample()
    return {k:data[k] for k in {f[0] for f in EXTRA_FIELDS} if k in data}


def test_fachpruefung_route_and_schema(client):
    assert client.get('/fachpruefung').status_code == 200
    assert 'Fachprüfung' in client.get('/fachpruefung').text
    response=client.get('/api/fachpruefung/schema')
    assert response.status_code==200
    assert any(f['key']=='tax_transfer_date' for f in response.json()['fields'])
    assert client.get('/assets/fachpruefung.js').status_code==200


def test_api_can_extend_original_case_and_preserve_legacy_runs(client):
    case_id=a_case(client)
    original=client.get(f'/api/cases/{case_id}/runs').json()['runs']
    response=client.post(f'/api/cases/{case_id}/fachpruefung',json={'extra_facts':extra()})
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload['report']['selected']['overall']=='READY_FOR_EXPERT_REVIEW'
    assert payload['verification']['valid']
    assert payload['report']['professional_approval']=='PENDING_NOT_SUPPORTED_BY_AUTOMATION'
    assert client.get(f'/api/cases/{case_id}/runs').json()['runs']==original
    run_id=payload['run_id']
    assert client.get(f'/api/cases/{case_id}/fachpruefung/latest').json()['run_id']==run_id
    assert client.get(f'/api/cases/{case_id}/fachpruefung/{run_id}').json()['verification']['valid']
    exported=client.get(f'/api/cases/{case_id}/fachpruefung/{run_id}/export')
    assert exported.status_code==200
    assert exported.json()['report']['result_hash']==payload['report']['result_hash']


def test_missing_extra_evidence_not_promoted(client):
    case_id=a_case(client)
    response=client.post(f'/api/cases/{case_id}/fachpruefung',json={'extra_facts':{}})
    assert response.status_code==200
    assert response.json()['report']['selected']['overall']=='EVIDENCE_REQUIRED'


def test_api_rejects_unrecognized_or_invalid_fields(client):
    case_id=a_case(client)
    assert client.post(f'/api/cases/{case_id}/fachpruefung',json={'extra_facts':{'unknown':{'value':1}}}).status_code==422
    bad=extra();bad['tax_transfer_date']={'value':'not-a-date','verification':'confirmed','evidence_ref':'D'}
    assert client.post(f'/api/cases/{case_id}/fachpruefung',json={'extra_facts':bad}).status_code==422


def test_postrun_tamper_is_detected(client):
    case_id=a_case(client)
    res=client.post(f'/api/cases/{case_id}/fachpruefung',json={'extra_facts':extra()}).json()
    run_id=res['run_id']
    with connect() as c:
        row=c.execute('SELECT report_json FROM legal_assessment_runs WHERE id=?',(run_id,)).fetchone()
        obj=json.loads(row[0]);obj['consequences'][1]['new_share_cost_basis_preliminary']=999999
        c.execute('UPDATE legal_assessment_runs SET report_json=? WHERE id=?',(json.dumps(obj),run_id))
    latest=client.get(f'/api/cases/{case_id}/fachpruefung/{run_id}').json()
    assert not latest['verification']['valid']


def test_legacy_fact_edit_marks_saved_report_stale(client):
    case_id=a_case(client)
    saved=client.post(f'/api/cases/{case_id}/fachpruefung',json={'extra_facts':extra()}).json()
    assert saved['current_case_facts_match']
    current=client.get(f'/api/cases/{case_id}').json()
    for fact in current['facts']:
        if fact['key']=='planned_disposal':
            fact['value']=True
    assert client.put(f'/api/cases/{case_id}/facts',json={'facts':current['facts']}).status_code==200
    prior=client.get(f'/api/cases/{case_id}/fachpruefung/{saved["run_id"]}').json()
    assert prior['verification']['valid']
    assert prior['current_case_facts_match'] is False
