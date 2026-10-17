import copy

from test_app import client, cases_by_letter, execute


def test_element_provenance_uses_revision_snapshots_and_version_review(client):
    draft = client.post('/api/graphs/umwstg20-v1/draft',json={'actor':'Demo Modellierung'}).json()
    vid = draft['meta']['id']
    graph = {key:copy.deepcopy(draft[key]) for key in ('label','nodes','edges')}
    edge = next(e for e in graph['edges'] if e['id']=='E_SCOPE_YES')
    edge['guidance'] = 'Synthetische Änderung für die Kantenprüfung.'
    assert client.put(f'/api/graphs/{vid}',json={'graph':graph,'actor':'Demo Änderung','reason':'Fachliche Anleitung präzisieren'}).status_code == 200
    assert client.post(f'/api/graphs/{vid}/publish',json={'actor':'Demo Strukturprüfung','confirm_expert_review':True}).status_code == 200
    provenance = client.get(f'/api/graphs/{vid}/provenance').json()
    assert provenance['snapshot_integrity'] and provenance['available']
    actor = client.get('/api/config').json()['identity']['username']
    assert [r['actor'] for r in provenance['edges']['E_SCOPE_YES']] == [actor, actor]
    assert [r['change'] for r in provenance['edges']['E_SCOPE_YES']] == ['created','changed']
    assert len(provenance['edges']['E_SCOPE_NO']) == 1
    assert provenance['meta']['approved_by'] == actor
    assert client.get('/api/graphs/umwstg20-v1/provenance').json()['edges']['E_SCOPE_YES'][0]['actor'] == 'Systemdemo'
    run = execute(client,cases_by_letter(client)['A'],vid)
    audit = client.get(f'/api/runs/{run["run_id"]}/audit').json()
    assert audit['graph_provenance'] == provenance
    assert audit['integrity']['valid']
