import json
import shutil
import subprocess

import pytest

from test_app import client, cases_by_letter, execute


def test_edge_auditor_projects_actual_backend_events_without_re_evaluation(client,tmp_path):
    if not shutil.which('node'):
        pytest.skip('Node.js für die JavaScript-Prüfung nicht verfügbar.')
    documents = {}
    for letter,cid in cases_by_letter(client).items():
        rid = execute(client,cid)['run_id']
        documents[letter] = client.get(f'/api/runs/{rid}/audit').json()
    file=tmp_path/'executions.json'
    file.write_text(json.dumps(documents),encoding='utf-8')
    result=subprocess.run(['node','tests/audit-data.test.cjs',str(file)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_historical_run_and_provenance_remain_pinned_after_new_version(client):
    cid=cases_by_letter(client)['C']
    rid=execute(client,cid)['run_id']
    before=client.get(f'/api/runs/{rid}/audit').json()
    facts=client.get(f'/api/cases/{cid}').json()['facts']
    shares=next(f for f in facts if f['key']=='new_shares')
    shares.update(verification='confirmed',evidence_ref='SYNTHETISCH: später nachgereichter Nachweis')
    assert client.put(f'/api/cases/{cid}/facts',json={'facts':facts}).status_code==200
    draft=client.post('/api/graphs/umwstg20-v1/draft',json={'actor':'Demo Nachfolgeversion'}).json()
    assert client.post(f'/api/graphs/{draft["meta"]["id"]}/publish',json={'actor':'Demo Veröffentlichung','confirm_expert_review':True}).status_code==200
    execute(client,cid,draft['meta']['id'])
    after=client.get(f'/api/runs/{rid}/audit').json()
    for key in ('run','graph','legal_sources','graph_provenance'):
        assert before[key]==after[key]
    assert after['run']['result']['status']=='NACHWEISE_FEHLEN'
    assert after['integrity']['valid']
