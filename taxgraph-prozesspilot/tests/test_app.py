"""API integration tests; use isolated temporary SQLite for every test."""
import copy
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server import app
from app.storage import connect


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    with TestClient(app) as c:
        yield c


def cases_by_letter(client):
    cases=client.get('/api/cases').json()['cases']
    return {x['title'].split(' · ')[0][-1]:x['id'] for x in cases}


def execute(client, case, version='umwstg20-v1'):
    r=client.post(f'/api/cases/{case}/run',json={'graph_version':version})
    assert r.status_code==200, r.text
    return r.json()


def test_home_and_graph(client):
    assert client.get('/').status_code == 200
    assert 'Prozessbibliothek' in client.get('/').text
    assert 'Einbringungsprüfung' in client.get('/studio').text
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/api/health').json()['status']=='ok'
    graph=client.get('/api/graphs/umwstg20-v1').json()
    assert len(graph['nodes'])==19 and len(graph['edges'])==35
    assert all('guard' in e for e in graph['edges'])
    assert client.post('/api/graphs/validate',json={k:graph[k] for k in ('label','nodes','edges')}).json()['valid']


def test_four_seed_scenarios_and_audit(client):
    cases=cases_by_letter(client)
    expectations={'A':'FREIGABE_OFFEN','B':'ANWENDUNGSBEREICH_OFFEN','C':'NACHWEISE_FEHLEN','D':'FREIGABE_OFFEN'}
    for letter,status in expectations.items():
        r=execute(client,cases[letter])
        assert r['result']['status']==status
        run_id=r['run_id']
        ver=client.get(f'/api/runs/{run_id}').json()['verification']
        assert ver['graph_integrity'] and ver['event_chain_integrity'] and ver['facts_integrity'] and ver['result_integrity']
        exported=client.get(f'/api/runs/{run_id}/audit')
        assert exported.status_code==200
        j=exported.json()
        assert j['run']['graph_version']=='umwstg20-v1'
        assert len(j['graph']['edges'])==35
        assert len(j['run']['events'])>15
    run=client.get(f'/api/cases/{cases["D"]}/runs').json()['runs'][0]
    warnings=client.get(f'/api/runs/{run["id"]}').json()['result']['warnings']
    assert any('Einbringungsgewinn I' in w for w in warnings)


def test_other_consideration_threshold_is_deterministic(client):
    case_id=cases_by_letter(client)['A']
    obj=client.get(f'/api/cases/{case_id}').json()
    for fact in obj['facts']:
        if fact['key']=='other_consideration':
            fact['value']=110000.0
            fact['evidence_ref']='SYNTHETISCH: andere Gegenleistung 110000'
    result=client.put(f'/api/cases/{case_id}/facts',json={'facts':obj['facts']}).json()
    assert result['id']==case_id
    r=execute(client,case_id)
    assert r['result']['status']=='BUCHWERT_NICHT_GESICHERT'
    sigs=[e['detail'] for e in client.get(f'/api/runs/{r["run_id"]}').json()['events'] if e['event_type']=='SIGNAL_EVALUATED']
    consideration=next(x for x in sigs if x['signal']=='other_consideration_ok')
    assert consideration['calculation']['allowed']==100000
    assert consideration['outcome']=='no'


def test_review_is_human_gated_and_case_hash_bound(client):
    case_id=cases_by_letter(client)['A']
    first=execute(client,case_id)
    assert first['result']['status']=='FREIGABE_OFFEN'
    bad=client.post(f'/api/cases/{case_id}/review',json={'run_id':first['run_id'],'reviewer':'AB',
        'decision':'approved','note':'Testfreigabe fuer Demo.'})
    assert bad.status_code==422
    approved=client.post(f'/api/cases/{case_id}/review',json={'run_id':first['run_id'],'reviewer':'Demo Reviewer',
        'decision':'approved','note':'Fiktive Unterlagen in der Demo fachlich geprueft.'})
    assert approved.status_code==200,approved.text
    second=execute(client,case_id)
    assert second['result']['status']=='FREIGEGEBEN_IM_PROTOTYP'
    c=client.get(f'/api/cases/{case_id}').json()
    for fact in c['facts']:
        if fact['key']=='planned_disposal':
            fact['value']=True
    assert client.put(f'/api/cases/{case_id}/facts',json={'facts':c['facts']}).status_code==200
    third=execute(client,case_id)
    assert third['result']['status']=='FREIGABE_OFFEN'
    assert any('Einbringungsgewinn I' in w for w in third['result']['warnings'])


def test_graph_edit_is_copy_on_write_and_guard_validated(client):
    orig=client.get('/api/graphs/umwstg20-v1').json()
    assert client.put('/api/graphs/umwstg20-v1',json={'graph':orig,'actor':'Tester'}).status_code==422
    draft=client.post('/api/graphs/umwstg20-v1/draft',json={'actor':'Demo Builder'}).json()
    did=draft['meta']['id']
    assert draft['meta']['status']=='draft'
    new={k:copy.deepcopy(draft[k]) for k in ('label','nodes','edges')}
    new['label']='Prototyp Spezialgraph'
    new['nodes'][0]['description']='Neue Beschreibung im Entwurf'
    invalid=copy.deepcopy(new)
    invalid['edges'][0]['guard']={'operator':'always'}
    assert client.put(f'/api/graphs/{did}',json={'graph':invalid,'actor':'Demo Builder'}).status_code==422
    assert client.put(f'/api/graphs/{did}',json={'graph':new,'actor':'Demo Builder'}).status_code==200
    published=client.post(f'/api/graphs/{did}/publish',json={'actor':'Demo Reviewer','confirm_expert_review':True})
    assert published.status_code==200,published.text
    assert published.json()['meta']['checksum']!=orig['meta']['checksum']
    assert client.put(f'/api/graphs/{did}',json={'graph':new,'actor':'Demo Builder'}).status_code==422
    assert client.get('/api/graphs/umwstg20-v1').json()['meta']['checksum']==orig['meta']['checksum']
    case=cases_by_letter(client)['A']
    new_run=execute(client,case,did)
    assert new_run['audit']['graph_integrity']


def test_corruption_is_detected(client):
    case=cases_by_letter(client)['B']
    run=execute(client,case)
    with connect() as c:
        c.execute("UPDATE run_events SET detail_json=? WHERE run_id=? AND seq=2", ('{"forged":true}',run['run_id']))
    check=client.get(f'/api/runs/{run["run_id"]}').json()['verification']
    assert not check['event_chain_integrity']
    assert 2 in check['broken_sequences']


def test_no_unverified_fact_promoted(client):
    case=cases_by_letter(client)['C']
    run=execute(client,case)
    assert run['result']['status']=='NACHWEISE_FEHLEN'
    assert any('Neue Gesellschaftsanteile' in item for item in run['result']['missing_evidence'])
    # Even value=True fails when verification=reported.
    raw=client.get(f'/api/cases/{case}').json()
    fact=next(x for x in raw['facts'] if x['key']=='new_shares')
    assert fact['value'] is True and fact['verification']=='reported'
    fact['verification']='confirmed'
    save=client.put(f'/api/cases/{case}/facts',json={'facts':raw['facts']})
    assert save.status_code==422 # no evidence reference


def test_authentication_when_password_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'protected.sqlite3'))
    # Shared password remains a local-demo gate; production requires named accounts.
    monkeypatch.setenv('APP_ENV','local')
    monkeypatch.setenv('APP_USER','admin')
    monkeypatch.setenv('APP_PASSWORD','super-secret-long-demo-password')
    with TestClient(app) as c:
        assert c.get('/').status_code==401
        assert c.get('/api/health',auth=('admin','wrong')).status_code==200  # public health endpoint for Docker
        assert c.get('/api/cases',auth=('admin','wrong')).status_code==401
        assert c.get('/api/cases',auth=('admin','super-secret-long-demo-password')).status_code==200


def test_graph_revisions_are_auditable_and_exportable(client):
    draft=client.post('/api/graphs/umwstg20-v1/draft',json={'actor':'Process Architect'}).json()
    vid=draft['meta']['id']
    graph={k:copy.deepcopy(draft[k]) for k in ('label','nodes','edges')}
    graph['nodes'][0]['description']='Strukturierte Erstaufnahme beim Klienten'
    r=client.put(f'/api/graphs/{vid}',json={'actor':'Process Architect','reason':'Transparenz bei der Erstaufnahme verbessern','graph':graph})
    assert r.status_code==200,r.text
    history=client.get(f'/api/graphs/{vid}/revisions').json()['revisions']
    assert [v['revision'] for v in history]==[2,1]
    assert history[0]['diff']['nodes']['changed']==[graph['nodes'][0]['id']]
    assert 'Transparenz' in history[0]['reason']
    published=client.post(f'/api/graphs/{vid}/publish',json={'actor':'Expert Review','confirm_expert_review':True})
    assert published.status_code==200
    data=client.get(f'/api/graphs/{vid}/export').json()
    assert data['graph']['label']==graph['label']
    assert len(data['revisions'])==2
    assert len(data['graph']['nodes'])==19


def test_result_tampering_and_graph_tampering_detected(client):
    cid=cases_by_letter(client)['A']
    run=execute(client,cid)
    rid=run['run_id']
    with connect() as c:
        c.execute("UPDATE runs SET result_json=? WHERE id=?", ('{"forged":true}',rid))
    verification=client.get(f'/api/runs/{rid}').json()['verification']
    assert verification['event_chain_integrity']
    assert not verification['result_integrity']
    with connect() as c:
        c.execute("UPDATE graph_nodes SET data=? WHERE version_id=? AND node_id=?",('{"id":"START","kind":"ACTION"}', 'umwstg20-v1','START'))
    audit=client.get(f'/api/runs/{rid}').json()
    assert audit['verification']['graph_integrity'] is False


def test_modified_graph_cannot_claim_approval_without_mandatory_positive_checks(client):
    draft=client.post('/api/graphs/umwstg20-v1/draft',json={'actor':'Demo Tester'}).json()
    vid=draft['meta']['id']
    graph={k:copy.deepcopy(draft[k]) for k in ('label','nodes','edges')}
    # Unsafe editing proposal: continue to later checks even though a core
    # §20 prerequisite has explicitly failed. Runtime must reject approval.
    for e in graph['edges']:
        if e['id']=='E_ESSENTIAL_NO': e['target']='CORPTAX'
    saved=client.put(f'/api/graphs/{vid}',json={'actor':'Demo Tester','reason':'Sicherheitstest bei Fehlrouting','graph':graph})
    assert saved.status_code==200,saved.text
    assert client.post(f'/api/graphs/{vid}/publish',json={'actor':'Demo Reviewer','confirm_expert_review':True}).status_code==200
    result=execute(client,cases_by_letter(client)['B'],vid)
    assert result['result']['status']=='PRUEFPFAD_UNVOLLSTAENDIG'
    assert 'ESSENTIAL' in result['result']['path']
    assert result['audit']['result_integrity']


def test_approval_terminal_cannot_bypass_human_gate(client):
    obj=client.get('/api/graphs/umwstg20-v1').json()
    graph={k:copy.deepcopy(obj[k]) for k in ('label','nodes','edges')}
    for e in graph['edges']:
        if e['id']=='E_VALUATION': e['target']='APPROVED'
    r=client.post('/api/graphs/validate',json=graph).json()
    assert not r['valid']
    assert any('Nur nach fachlicher Freigabeprüfung' in x for x in r['errors'])


def test_reject_review_halts_positive_recommendation(client):
    cid=cases_by_letter(client)['A']
    run=execute(client,cid)
    resp=client.post(f'/api/cases/{cid}/review',json={'run_id':run['run_id'],'reviewer':'Tax Specialist',
          'decision':'rejected','note':'Pflichtunterlagen für Bewertung noch nicht gesichert.'})
    assert resp.status_code==200,resp.text
    next_run=execute(client,cid)
    assert next_run['result']['status']=='FREIGABE_ABGELEHNT'
