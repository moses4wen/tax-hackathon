"""Functional integration: independent fiscal examples, graph execution and org lifecycle."""
from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from app.functional_graph import default_definition, validate, run, verify, import_source, SOURCE_IDS, SLUG, digest
from app.functional_golden import sample, confirmed, check_definition
from app.legal_v3 import assess, verify as verify_legal
from app.valuation import allocate, amount
from app.server import app
from app.storage import init_db, connect
from app.auth import create_org, create_user


def test_reference_publication_suite():
    graph = default_definition()
    assert check_definition(graph) == []
    graph['policy']['enable_aufstockung'] = False
    assert check_definition(graph) == []


def test_negative_net_assets_and_uniform_allocation():
    result = run(default_definition(), sample(True))
    assert result['overall'] == 'READY_FOR_EXPERT_REVIEW'
    assert 'c_aufstockung' in result['path']
    report = result['report']
    assert report['minimum_valuation']['minimum_net_value'] == 0
    assert report['minimum_valuation']['minimum_uplift'] == 200000
    assert report['selected']['effective_mode'] == 'zwischenwert'
    assert report['consequences'][1]['gross_gain_preliminary'] == 200000
    assert report['consequences'][1]['new_share_cost_basis_preliminary'] == 0
    assert report['asset_allocation'][0]['asset_tax_value'] == 500000
    assert report['asset_allocation'][0]['annual_afa'] == 80000
    assert verify(result)['valid']


@pytest.mark.parametrize('book,expected_value,expected_gain,expected_basis', [(3000000,3100000,100000,2100000),(100000,1000000,900000,0)])
def test_bmf_20_19a_examples(book, expected_value, expected_gain, expected_basis):
    facts = sample(); facts.update(book_value=confirmed(book), fair_value=confirmed(5000000), other_consideration=confirmed(1000000))
    doc = run(default_definition(), facts)
    assert doc['overall'] == 'READY_FOR_EXPERT_REVIEW'
    assert 'l_mindestwert' in doc['path']
    assert doc['report']['minimum_valuation']['minimum_net_value'] == expected_value
    assert doc['report']['consequences'][1]['gross_gain_preliminary'] == expected_gain
    assert doc['report']['consequences'][1]['new_share_cost_basis_preliminary'] == expected_basis


def test_negative_missing_schedule_does_not_pass():
    f = sample(True); del f['asset_schedule']
    r = run(default_definition(), f)
    assert r['overall'] != 'READY_FOR_EXPERT_REVIEW'
    assert r['report']['consequences'][1]['gross_gain_preliminary'] is None


def test_schedule_reconciliation_and_capacity():
    f = sample(True); f['asset_schedule']['value'][0]['fair'] = 600000
    assert run(default_definition(), f)['overall'] != 'READY_FOR_EXPERT_REVIEW'
    state, _ = allocate([{'id':'A','book':100,'fair':120}], amount(50), amount(50), amount(70), amount(71))
    assert state == 'NOT_SATISFIED'


def test_graph_change_does_not_rewrite_old_runs():
    old = default_definition(); old['policy']['enable_aufstockung'] = False
    before = run(old, sample(True)); saved = json.dumps(before,sort_keys=True)
    after = run(default_definition(), sample(True))
    assert before['overall'] == 'MODEL_REVIEW_REQUIRED'
    assert after['overall'] == 'READY_FOR_EXPERT_REVIEW'
    assert before['definition_hash'] != after['definition_hash']
    assert json.dumps(before,sort_keys=True) == saved
    assert verify(before)['valid'] and verify(after)['valid']


def test_actual_date_fallback_is_explicit_and_reproducible():
    f = sample(); f.update(register_filing_date=confirmed('2026-09-01'),register_entry_date=confirmed('2026-09-10'))
    r = run(default_definition(), f)
    assert r['terminal'] == 'r_stichtag'
    f['use_actual_transfer_date'] = confirmed(True)
    r = run(default_definition(), f)
    assert r['overall'] == 'READY_FOR_EXPERT_REVIEW'
    assert r['report']['consequences'][1]['year'] == 2026
    assert r['report']['facts']['tax_transfer_date']['value'] == '2025-12-31'
    assert verify(r)['valid']


def test_missing_application_offers_fair_not_automatic_election():
    f=sample();f['application_timely']=confirmed(False)
    r=run(default_definition(),f)
    assert r['overall']=='FAIR_VALUE_ALTERNATIVE'
    assert r['report']['consequences'][1]['gross_gain_preliminary'] is None
    f['valuation_choice']=confirmed('gemeiner_wert')
    r=run(default_definition(),f)
    assert r['overall']=='READY_FOR_EXPERT_REVIEW'


def test_tax_rights_are_distinct():
    f=sample();f['german_tax_right_received_shares']=confirmed(False)
    assert run(default_definition(),f)['overall']=='READY_FOR_EXPERT_REVIEW'
    f['german_tax_right']=confirmed(False)
    assert run(default_definition(),f)['overall']=='FAIR_VALUE_ALTERNATIVE'


def test_conflict_replays_and_no_evidence_never_passes():
    f=sample();f['new_shares']['observations']=[confirmed(False)]
    r=run(default_definition(),f)
    assert r['overall']=='CONFLICTED_EVIDENCE'
    assert verify(r)['valid']
    f=sample();f['new_shares']['evidence_ref']=''
    assert run(default_definition(),f)['overall']=='EVIDENCE_REQUIRED'


def test_tamper_detection_and_mandatory_path():
    d=default_definition();r=run(d,sample());r['report']['consequences'][1]['gross_gain_preliminary']=777
    assert not verify(r)['valid']
    # A structurally valid graph cannot silently skip the substantive safety gate.
    changed=deepcopy(d)
    edge=next(e for e in changed['edges'] if e['id']=='c_antrag:yes');edge['target']='r_buchwert'
    # May be structurally reachable via another path; publishing still must fail.
    try:
        validate(changed)
        assert check_definition(changed)
    except ValueError:
        pass


@pytest.mark.parametrize('field,value', [('policy',None),('policy',[]),('nodes',{}),('source',[])])
def test_malformed_definitions_rejected(field,value):
    d=default_definition();d[field]=value
    with pytest.raises(ValueError):validate(d)


def test_source_import_keeps_raw_and_never_executes_text():
    branches = {
        'c_anwendungsbereich': ('c_persoenlich','r_nicht20'),
        'c_persoenlich': ('c_gegenstand','r_nicht20'),
        'c_gegenstand': ('c_neue_anteile','r_nicht20'),
        'c_neue_anteile': ('c_antrag','r_nicht20'),
        'c_antrag': ('c_kst_sicher','r_gemeiner_wert'),
        'c_kst_sicher': ('c_passivueberhang','r_gemeiner_wert'),
        'c_passivueberhang': ('c_besteuerungsrecht','c_aufstockung'),
        'c_aufstockung': ('c_besteuerungsrecht','r_gemeiner_wert'),
        'c_besteuerungsrecht': ('c_sonstige_gegenleistung','r_gemeiner_wert'),
        'c_sonstige_gegenleistung': ('c_grenze_gegenleistung','c_rueckwirkung'),
        'c_grenze_gegenleistung': ('c_rueckwirkung','r_gemeiner_wert'),
        'c_rueckwirkung': ('r_buchwert','r_stichtag'),
    }
    # Explicit synthetic fixture, NOT a claimed remote snapshot.
    edges=[{'id':'entry','source':'start','target':'c_anwendungsbereich'}]
    for key,targets in branches.items():
        for i,target in enumerate(targets): edges.append({'id':key+str(i),'source':key,'target':target,'condition':str(i)})
    raw={'id':SLUG,'version':3,'purpose':'SYNTHETIC_TEST_ONLY',
         'nodes':[{'id':k,'text':'UNTRUSTED SOURCE TEXT'} for k in sorted(SOURCE_IDS)], 'edges':edges}
    incomplete=deepcopy(raw);incomplete['edges'].pop()
    with pytest.raises(ValueError):import_source(incomplete)
    definition=import_source(raw)
    assert definition['source']['raw']==raw
    assert definition['source']['raw_hash']==digest(raw)
    assert verify(run(definition,sample()))['valid']
    raw['api_key']='never-store-this'
    with pytest.raises(ValueError):import_source(raw)
    fake=default_definition();fake['source']['complete']=True
    with pytest.raises(ValueError):validate(fake)


@pytest.fixture
def secured(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'functional.sqlite'))
    monkeypatch.delenv('APP_ENV',raising=False);monkeypatch.delenv('APP_PASSWORD',raising=False)
    init_db()
    with connect() as c:
        create_org(c,'other-org','Other Organization')
        for name,org,role in [('reader','demo','viewer'),('author','demo','editor'),('reviewer','demo','reviewer'),('outsider','other-org','reviewer')]:
            create_user(c,name,org,role,'testing-password-123')
    monkeypatch.setenv('APP_ENV','production')
    with TestClient(app) as client:
        yield client


def auth(user):return (user,'testing-password-123')

def setup_case(client,negative=False):
    cases=client.get('/api/cases',auth=auth('author')).json()['cases']
    cid=next(c['id'] for c in cases if 'Musterfall A' in c['title'])
    facts=sample(negative);case=client.get('/api/cases/'+cid,auth=auth('author')).json()
    from app.functional_api import CORE
    core=[{'key':k,**facts[k]} for k in CORE]
    assert client.put('/api/cases/'+cid+'/facts',auth=auth('author'),json={'facts':core}).status_code==200
    old=client.get('/api/functional/cases/'+cid+'/inputs',auth=auth('author')).json()
    resp=client.put('/api/functional/cases/'+cid+'/inputs',auth=auth('author'),json={'extra_facts':{k:v for k,v in facts.items() if k not in CORE},'expected_hash':old['inputs_hash']})
    assert resp.status_code==200,resp.text
    return cid,resp.json()


def test_api_full_lifecycle_and_human_review(secured):
    c=secured;cid,inp=setup_case(c,True)
    proc=c.get('/api/functional/processes',auth=auth('author')).json()['processes'][0]
    response=c.post('/api/functional/cases/'+cid+'/runs',auth=auth('author'),json={'process_id':proc['id'],'expected_case_hash':inp['case_hash'],'expected_inputs_hash':inp['inputs_hash']})
    assert response.status_code==201,response.text
    r=response.json();assert r['overall']=='READY_FOR_EXPERT_REVIEW';assert r['verification']['valid']
    rid=r['id'];body={'decision':'approved','expected_run_hash':r['document_hash'],'note':'Synthetische Testfreigabe durch Reviewer.'}
    assert c.post('/api/functional/runs/'+rid+'/review',auth=auth('author'),json=body).status_code==403
    approved=c.post('/api/functional/runs/'+rid+'/review',auth=auth('reviewer'),json=body)
    assert approved.status_code==200,approved.text
    assert approved.json()['approval_effective']
    exported=c.get('/api/functional/runs/'+rid+'/export',auth=auth('reader')).json()
    assert exported['document']==r['document']
    assert exported['reviews'][0]['reviewer']=='reviewer'
    assert c.get('/api/functional/runs/'+rid,auth=auth('outsider')).status_code==404
    assert c.get('/api/functional/runs/'+rid+'/export',auth=auth('outsider')).status_code==404
    assert c.get('/api/functional/cases/'+cid+'/inputs',auth=auth('outsider')).status_code==404
    extras=c.get('/api/functional/cases/'+cid+'/inputs',auth=auth('author')).json()
    extras['extra_facts']['event_type']=confirmed('ersatzereignis')
    saved=c.put('/api/functional/cases/'+cid+'/inputs',auth=auth('author'),json={'extra_facts':extras['extra_facts'],'expected_hash':extras['inputs_hash']})
    assert saved.status_code==200
    assert not c.get('/api/functional/runs/'+rid,auth=auth('reader')).json()['approval_effective']
    assert c.post('/api/functional/runs/'+rid+'/review',auth=auth('reviewer'),json=body).status_code==409


def test_api_process_permissions_versions_and_learning(secured):
    c=secured;p=c.get('/api/functional/processes',auth=auth('reader')).json()['processes'][0];pid=p['id']
    assert c.post('/api/functional/processes',auth=auth('reviewer'),json={'label':'New process'}).status_code==403
    assert c.post('/api/functional/processes',auth=auth('reader'),json={'label':'New process'}).status_code==403
    assert c.post('/api/functional/processes',auth=auth('author'),json={'label':'New process'}).status_code==201
    draft=c.post('/api/functional/processes/'+pid+'/draft',auth=auth('author')).json()
    did=draft['id']
    assert c.get('/api/functional/processes/'+did,auth=auth('reader')).status_code==404
    assert c.get('/api/functional/processes/'+did,auth=auth('outsider')).status_code==404
    definition=deepcopy(draft['definition']);definition['policy']['enable_aufstockung']=False
    edit={'definition':definition,'expected_hash':draft['definition_hash'],'reason':'Modellgrenze vor Expertenlernen demonstrieren.'}
    saved=c.put('/api/functional/processes/'+did,auth=auth('author'),json=edit)
    assert saved.status_code==200,saved.text
    assert c.put('/api/functional/processes/'+did,auth=auth('author'),json=edit).status_code==409
    saved=saved.json();pub={'expected_hash':saved['definition_hash'],'confirm_normalizations':True,'acknowledge_source_limits':True,'note':'Referenzfaelle und lokale Quellenbegrenzung geprueft.'}
    assert c.post('/api/functional/processes/'+did+'/publish',auth=auth('author'),json=pub).status_code==403
    published=c.post('/api/functional/processes/'+did+'/publish',auth=auth('reviewer'),json=pub)
    assert published.status_code==200,published.text
    assert c.put('/api/functional/processes/'+did,auth=auth('reviewer'),json={**edit,'expected_hash':saved['definition_hash']}).status_code==409
    cid,inp=setup_case(c,True)
    args={'process_id':did,'expected_case_hash':inp['case_hash'],'expected_inputs_hash':inp['inputs_hash']}
    before=c.post('/api/functional/cases/'+cid+'/runs',auth=auth('author'),json=args).json()
    assert before['overall']=='MODEL_REVIEW_REQUIRED'
    new=c.post('/api/functional/processes/'+did+'/draft',auth=auth('reviewer')).json();nid=new['id']
    new['definition']['policy']['enable_aufstockung']=True
    learned=c.put('/api/functional/processes/'+nid,auth=auth('reviewer'),json={'definition':new['definition'],'expected_hash':new['definition_hash'],'reason':'Fachlich bestaetigte Aufstockung nach 20.19 aktivieren.'}).json()
    assert c.post('/api/functional/processes/'+nid+'/publish',auth=auth('reviewer'),json={**pub,'expected_hash':learned['definition_hash']}).status_code==200
    after=c.post('/api/functional/cases/'+cid+'/runs',auth=auth('author'),json={**args,'process_id':nid}).json()
    assert after['overall']=='READY_FOR_EXPERT_REVIEW'
    old=c.get('/api/functional/runs/'+before['id'],auth=auth('reader')).json()
    assert old['document']==before['document'] and old['verification']['valid']


def test_input_override_cross_org_and_csrf_denied(secured):
    c=secured;cid,inp=setup_case(c)
    p=c.get('/api/functional/processes',auth=auth('author')).json()['processes'][0]
    path='/api/functional/cases/'+cid+'/runs'
    args={'process_id':p['id'],'expected_inputs_hash':inp['inputs_hash'],'expected_case_hash':inp['case_hash']}
    assert c.post(path,auth=auth('reader'),json=args).status_code==403
    assert c.post(path,auth=auth('outsider'),json=args).status_code==404
    assert c.post(path,auth=auth('author'),headers={'Origin':'https://evil.example'},json=args).status_code==403
    assert c.post(path,auth=auth('author'),json={**args,'expected_case_hash':'0'*64}).status_code==409
    update={'extra_facts':{'book_value':confirmed(-2)},'expected_hash':inp['inputs_hash']}
    assert c.put('/api/functional/cases/'+cid+'/inputs',auth=auth('author'),json=update).status_code==422


def test_production_without_named_accounts_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'no-accounts.sqlite'))
    monkeypatch.setenv('APP_ENV','production')
    monkeypatch.setenv('APP_PASSWORD','old-shared-password-is-not-an-identity')
    with pytest.raises(RuntimeError,match='Benutzerkonten'):
        with TestClient(app): pass
