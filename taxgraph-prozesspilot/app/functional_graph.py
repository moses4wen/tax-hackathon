"""Versioned procedural orchestration over ONE version-pinned legal assessor.

The source graph is evidence, not executable authority. Unknown source rules
never become executable Python. Historical V1/V2 executors are unchanged.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .legal_v3 import ENGINE_VERSION, assess, verify as verify_legal, _all

SCHEMA = 'ProzessPilot-Process-3'
SOURCE_URL = 'https://34-38-10-198.sslip.io/#graphs/einbringung_par20_umwstg'
SLUG = 'einbringung_par20_umwstg'
OUTCOMES = ('yes', 'no', 'unknown', 'conflicted')
BINDINGS = {
    'start': [],
    'c_anwendungsbereich': ['DEMO_SCOPE', 'TRANSACTION', 'CIVIL', 'RECEIVER'],
    'c_persoenlich': ['PERSONAL'],
    'c_gegenstand': ['ASSET', 'ESSENTIAL'],
    'c_neue_anteile': ['SHARES'],
    'c_antrag': ['APPLICATION'],
    'c_kst_sicher': ['CORPTAX'],
    'c_passivueberhang': ['BALANCE'],
    'c_besteuerungsrecht': ['SHARE_TAX_RIGHT'],
    'c_sonstige_gegenleistung': ['$other_consideration'],
    'c_grenze_gegenleistung': ['CONSIDERATION_LIMIT'],
    'c_rueckwirkung': ['RETROACTIVE'],
    'c_aufstockung': ['AUFSTOCKUNG'],
    'r_nicht20': [], 'r_gemeiner_wert': [], 'r_stichtag': [], 'r_buchwert': [],
    'l_wertwahl': ['$lower_requested'],
    'l_asset_taxright': ['TAXRIGHT'],
    'l_mindestwert': ['AUFSTOCKUNG'],
    'l_selected': ['SELECTED_VALUE'],
    'l_unknown': [], 'l_conflicted': [], 'l_manual': [],
}
SOURCE_IDS = set(k for k in BINDINGS if not k.startswith('l_'))
TITLES = {
    'start': 'Sachverhalt und Nachweise', 'c_anwendungsbereich': 'Anwendungsbereich',
    'c_persoenlich': 'Persoenlicher Anwendungsbereich', 'c_gegenstand': 'Betrieb und wesentliche Grundlagen',
    'c_neue_anteile': 'Neue Gesellschaftsanteile', 'c_antrag': 'Fristgerechter Bewertungsantrag',
    'c_kst_sicher': 'Spaetere Koerperschaftsteuer', 'c_passivueberhang': 'Kein Passivueberhang?',
    'c_besteuerungsrecht': 'Besteuerungsrecht an erhaltenen Anteilen (gesondert)',
    'c_sonstige_gegenleistung': 'Weitere Gegenleistung?', 'c_grenze_gegenleistung': 'Gegenleistungsgrenze',
    'c_rueckwirkung': 'Zulaessiger Stichtag', 'c_aufstockung': 'Passivueberhang ausgleichen',
    'r_nicht20': 'Andere Einordnung pruefen', 'r_gemeiner_wert': 'Gemeiner Wert / Alternative',
    'r_stichtag': 'Stichtag korrigieren und neu pruefen', 'r_buchwert': 'Wertansatz und Rechtsfolgen',
    'l_wertwahl': 'Niedrigeren Wert beantragt?', 'l_asset_taxright': 'Besteuerungsrecht am Betriebsvermoegen',
    'l_mindestwert': 'Pflicht-Zwischenwert nach UmwStE 20.19a', 'l_selected': 'Gewaehlten Wert vollstaendig absichern',
    'l_unknown': 'Nachweise nachfordern', 'l_conflicted': 'Widerspruch klaeren', 'l_manual': 'Fachentscheidung erforderlich',
}
# Intentional legal corrections are explicit, never represented as the remote author's edits.
NORMALIZATIONS = [
    {'code': 'TAX_RIGHT_SPLIT', 'reason': 'Anteilsbesteuerung in PERSONAL alternativ; Betriebsvermoegen gesondert nach 20(2) Nr.3.'},
    {'code': 'MINIMUM_VALUE', 'reason': 'Gegenleistung oberhalb Grenze nicht pauschal Vollbesteuerung: UmwStE 20.19a.'},
    {'code': 'NO_AUTOMATIC_ELECTION', 'reason': 'Fehlender Antrag zeigt gemeinen Wert als Alternative; keine stille Wertwahl.'},
    {'code': 'EXPLICIT_DATE', 'reason': 'Neuer Stichtag nur durch bestaetigte Eingabe, danach neuer Lauf.'},
    {'code': 'EVIDENCE_STATES', 'reason': 'UNKNOWN und CONFLICTED stoppen; keine Umdeutung als false.'},
]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def default_definition():
    nodes = []
    for key, rules in BINDINGS.items():
        kind = 'ENTRY' if key == 'start' else 'CHECK' if rules else 'RESULT'
        nodes.append({'id': key, 'kind': kind, 'title': TITLES[key], 'rules': rules,
                      'source_node_id': key if key in SOURCE_IDS else None})
    edges = [{'id': 'start:always', 'source': 'start', 'target': 'c_anwendungsbereich', 'outcome': 'always'}]
    branches = {
        'c_anwendungsbereich': ('c_persoenlich', 'r_nicht20'),
        'c_persoenlich': ('c_gegenstand', 'r_nicht20'),
        'c_gegenstand': ('c_neue_anteile', 'r_nicht20'),
        'c_neue_anteile': ('l_wertwahl', 'r_nicht20'),
        'l_wertwahl': ('c_antrag', 'r_gemeiner_wert'),
        'c_antrag': ('c_kst_sicher', 'r_gemeiner_wert'),
        'c_kst_sicher': ('c_passivueberhang', 'r_gemeiner_wert'),
        'c_passivueberhang': ('c_besteuerungsrecht', 'c_aufstockung'),
        'c_aufstockung': ('c_besteuerungsrecht', 'l_manual'),
        # A negative share-tax-right alone is not fatal where PERSONAL used its other alternative.
        'c_besteuerungsrecht': ('l_asset_taxright', 'l_asset_taxright'),
        'l_asset_taxright': ('c_sonstige_gegenleistung', 'r_gemeiner_wert'),
        'c_sonstige_gegenleistung': ('c_grenze_gegenleistung', 'c_rueckwirkung'),
        'c_grenze_gegenleistung': ('c_rueckwirkung', 'l_mindestwert'),
        'l_mindestwert': ('c_rueckwirkung', 'l_manual'),
        'c_rueckwirkung': ('l_selected', 'r_stichtag'),
        'l_selected': ('r_buchwert', 'l_manual'),
    }
    for key, (yes, no) in branches.items():
        for outcome, target in zip(OUTCOMES, (yes, no, 'l_unknown', 'l_conflicted')):
            edges.append({'id': key + ':' + outcome, 'source': key, 'target': target, 'outcome': outcome})
    return {'schema': SCHEMA, 'label': 'Einbringung nach 20 UmwStG - integrierter Prozess',
            'ruleset': ENGINE_VERSION, 'policy': {'enable_aufstockung': True},
            'source': {'url': SOURCE_URL, 'graph_id': SLUG, 'version': 'v3',
                       'verification': 'UI_OBSERVED_NO_FULL_EXPORT', 'complete': False,
                       'raw': None, 'raw_hash': None},
            'normalizations': deepcopy(NORMALIZATIONS), 'nodes': nodes, 'edges': edges}


def validate(definition):
    """Closed rule vocabulary, total branch functions and an acyclic connected graph."""
    if not isinstance(definition, dict) or set(definition) != {'schema','label','ruleset','policy','source','normalizations','nodes','edges'}:
        raise ValueError('Ungueltiges Prozessschema.')
    if definition['schema'] != SCHEMA or definition['ruleset'] != ENGINE_VERSION:
        raise ValueError('Nicht unterstuetzte Prozess-/Regelversion.')
    if not isinstance(definition['label'], str) or not 3 <= len(definition['label']) <= 180:
        raise ValueError('Prozessbezeichnung: 3-180 Zeichen.')
    if not isinstance(definition['policy'], dict) or set(definition['policy']) != {'enable_aufstockung'} or type(definition['policy']['enable_aufstockung']) is not bool:
        raise ValueError('Ungueltige Ausfuehrungsrichtlinie.')
    if len(canonical(definition).encode()) > 1_000_000:
        raise ValueError('Prozessdefinition zu gross.')
    nodes, edges = definition['nodes'], definition['edges']
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) != len(BINDINGS) or len(edges) > 200:
        raise ValueError('Alle bekannten Pruefschritte und begrenzte Kantenliste erforderlich.')
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {'id','kind','title','rules','source_node_id'}:
            raise ValueError('Ungueltiger Knoten.')
        key = node['id']
        if not isinstance(key, str) or key not in BINDINGS or key in by_id or node['rules'] != BINDINGS[key]:
            raise ValueError('Unbekannte, doppelte oder umgebundene Regel.')
        expected = 'ENTRY' if key == 'start' else 'CHECK' if BINDINGS[key] else 'RESULT'
        if node['kind'] != expected or node['source_node_id'] != (key if key in SOURCE_IDS else None):
            raise ValueError('Knotentyp/Herkunft widerspricht Regelbindung.')
        if not isinstance(node['title'], str) or not 2 <= len(node['title']) <= 200:
            raise ValueError('Ungueltiger Knotentitel.')
        by_id[key] = node
    if set(by_id) != set(BINDINGS):
        raise ValueError('Fehlende Pruefschritte.')
    seen, outgoing = set(), {key: [] for key in by_id}
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {'id','source','target','outcome'}:
            raise ValueError('Ungueltige Kante.')
        eid, src, dst = edge['id'], edge['source'], edge['target']
        if not all(isinstance(k, str) for k in (eid,src,dst,edge['outcome'])) or eid in seen or src not in by_id or dst not in by_id:
            raise ValueError('Ungueltige Kanten-ID oder Endpunkte.')
        if edge['outcome'] in ('unknown','conflicted') and dst != 'l_' + edge['outcome']:
            raise ValueError('Fehlende oder widerspruechliche Nachweise duerfen nicht passieren.')
        seen.add(eid); outgoing[src].append(edge)
    for key, node in by_id.items():
        expected = ('always',) if node['kind'] == 'ENTRY' else OUTCOMES if node['kind'] == 'CHECK' else ()
        if sorted(e['outcome'] for e in outgoing[key]) != sorted(expected):
            raise ValueError('Genau eine Kante je moeglichem Ausgang erforderlich: ' + key)
    visiting, visited = set(), set()
    def walk(key):
        if key in visiting: raise ValueError('Zyklischer Prozess nicht unterstuetzt.')
        if key in visited: return
        visiting.add(key)
        for edge in outgoing[key]: walk(edge['target'])
        visiting.remove(key); visited.add(key)
    walk('start')
    if visited != set(by_id): raise ValueError('Unerreichbare Pruefschritte.')
    source = definition['source']
    if not isinstance(source, dict) or set(source) != {'url','graph_id','version','verification','complete','raw','raw_hash'}:
        raise ValueError('Quellsnapshot ungueltig.')
    if source['url'] != SOURCE_URL or source['graph_id'] != SLUG or source['version'] != 'v3':
        raise ValueError('Diese Regelversion unterstuetzt nur den freigegebenen v3-Quelltyp.')
    if source['raw'] is not None:
        validate_source(source['raw'])
        if source['raw_hash'] != digest(source['raw']) or source['complete'] is not True or source['verification'] != 'FULL_EXPORT_IMPORTED_REVIEW_REQUIRED':
            raise ValueError('Inkonsistente Quellherkunft.')
    elif source['complete'] is not False or source['raw_hash'] is not None or source['verification'] != 'UI_OBSERVED_NO_FULL_EXPORT':
        raise ValueError('Vollstaendigkeit ohne Quelldaten darf nicht behauptet werden.')
    if definition['normalizations'] != NORMALIZATIONS:
        raise ValueError('Normkorrekturen duerfen nicht stillschweigend entfernt werden.')
    return definition


def validate_source(raw):
    """A source may be stored without executing its free-text instructions."""
    if not isinstance(raw, dict) or not isinstance(raw.get('nodes'), list) or not isinstance(raw.get('edges'), list):
        raise ValueError('Quell-JSON benoetigt nodes und edges.')
    if len(raw['nodes']) != 17 or not 1 <= len(raw['edges']) <= 150 or len(canonical(raw).encode()) > 600_000:
        raise ValueError('Nicht unterstuetzter Quellumfang.')
    forbidden = {'authorization','x-api-key','api_key','password','token','secret'}
    def inspect(value):
        if isinstance(value, dict):
            if forbidden & {str(key).lower() for key in value}: raise ValueError('Keine Zugangsdaten im Quellexport.')
            for v in value.values(): inspect(v)
        elif isinstance(value, list):
            for v in value: inspect(v)
        elif isinstance(value, str) and value.startswith('Bearer '): raise ValueError('Keine Zugangsdaten.')
    inspect(raw)
    ids = [n.get('id') for n in raw['nodes'] if isinstance(n, dict)]
    if len(ids) != 17 or any(not isinstance(x, str) for x in ids) or set(ids) != SOURCE_IDS:
        raise ValueError('Quellknoten passen nicht zur expliziten Regelzuordnung.')
    seen = set()
    for edge in raw['edges']:
        if not isinstance(edge, dict) or not isinstance(edge.get('id'), str) or edge['id'] in seen:
            raise ValueError('Eindeutige Quellkanten-ID erforderlich.')
        if not isinstance(edge.get('source'), str) or not isinstance(edge.get('target'), str) or edge['source'] not in SOURCE_IDS or edge['target'] not in SOURCE_IDS:
            raise ValueError('Unbekannte Quellkanten-Endpunkte.')
        seen.add(edge['id'])
    adjacency = {key: [] for key in SOURCE_IDS}
    for edge in raw['edges']:
        adjacency[edge['source']].append(edge['target'])
    for key, targets in adjacency.items():
        expected = 1 if key == 'start' else 0 if key.startswith('r_') else 2
        if len(targets) != expected:
            raise ValueError('Quellgraph hat unvollstaendige Verzweigungen: ' + key)
    visiting, visited = set(), set()
    def reach(key):
        if key in visiting: raise ValueError('Quellgraph enthaelt einen Zyklus.')
        if key in visited: return
        visiting.add(key)
        for target in adjacency[key]: reach(target)
        visiting.remove(key); visited.add(key)
    reach('start')
    if visited != SOURCE_IDS: raise ValueError('Quellgraph enthaelt unerreichbare Knoten.')
    version = str(raw.get('version', raw.get('v', ''))).removeprefix('v')
    identity = raw.get('id',raw.get('name',raw.get('slug')))
    if version != '3' or identity != SLUG:
        raise ValueError('Quell-ID und Version muessen explizit zur Integration passen.')


def import_source(raw, definition=None):
    validate_source(raw)
    output = deepcopy(definition or default_definition())
    output['source'].update(raw=deepcopy(raw), raw_hash=digest(raw), complete=True,
                            verification='FULL_EXPORT_IMPORTED_REVIEW_REQUIRED')
    validate(output)
    return output


def coverage(definition):
    source = definition['source']
    pairs = {(e['source'],e['target']) for e in definition['edges']}
    return {'source_nodes': 17, 'bound_source_nodes': len(SOURCE_IDS),
            'source_edges_available': source['complete'],
            'source_edges': [] if source['raw'] is None else [
                {'id': e['id'], 'source': e['source'], 'target': e['target'],
                 'disposition': 'DIRECT_ENDPOINT_MATCH_REVIEW_GUARD' if (e['source'],e['target']) in pairs else 'NORMALIZED_REVIEW_REQUIRED'}
                for e in source['raw']['edges']],
            'local_nodes': len(definition['nodes']), 'local_edges': len(definition['edges']),
            'notice': 'Knotenzuordnung ist keine Behauptung identischer externer Kanten. Normalisierungen separat pruefen.'}


def run(definition, facts, *, as_of='2026-10-17'):
    validate(definition)
    report = assess(facts, as_of=as_of)
    assessments = {a['code']: a for a in report['assessments']}
    nodes = {n['id']: n for n in definition['nodes']}
    outgoing = {key: [e for e in definition['edges'] if e['source'] == key] for key in nodes}
    events, path = [], []
    def event(kind, detail):
        value = {'seq': len(events)+1, 'kind': kind, 'detail': detail,
                 'prev_hash': events[-1]['hash'] if events else '0'*64}
        events.append({**value,'hash':digest(value)})
    event('RULESET_EVALUATED', {'version': ENGINE_VERSION, 'result_hash':report['result_hash'],
                              'definition_hash':digest(definition)})
    current = 'start'
    for _ in range(len(nodes)):
        node = nodes[current]; path.append(current)
        event('NODE_ENTERED', {'node_id':current, 'source_node_id':node['source_node_id'], 'rules':node['rules']})
        if node['kind'] == 'RESULT': break
        statuses, evidence = [], []
        for rule in node['rules']:
            if rule.startswith('$'):
                key = 'other_consideration' if rule == '$other_consideration' else 'valuation_choice'
                f = report['facts'].get(key,{})
                if f.get('observations'): status = 'CONFLICTED'
                elif f.get('verification') != 'confirmed' or not f.get('evidence_ref') or f.get('value') is None: status = 'UNKNOWN'
                else:
                    truth = f['value'] > 0 if key == 'other_consideration' else f['value'] in ('buchwert','zwischenwert')
                    status = 'SATISFIED' if truth else 'NOT_SATISFIED'
                evidence.append({'rule':rule,'fact_key':key,'fact':f,'status':status})
            else:
                assessment = assessments[rule]; status = assessment['status']; evidence.append(assessment)
            statuses.append(status)
        status = _all(*statuses)
        if current in ('c_aufstockung','l_mindestwert') and not definition['policy']['enable_aufstockung']:
            status='UNKNOWN'; evidence.append({'policy':'enable_aufstockung','value':False,'reason':'Noch nicht fachlich in dieser Prozessversion aktiviert.'})
        outcome = 'always' if node['kind']=='ENTRY' else {'SATISFIED':'yes','NOT_SATISFIED':'no','UNKNOWN':'unknown','CONFLICTED':'conflicted'}[status]
        candidates = [{**edge,'guard_result':edge['outcome']==outcome} for edge in outgoing[current]]
        selected = [e for e in candidates if e['guard_result']]
        if len(selected)!=1: raise ValueError('Nicht eindeutiger Prozessuebergang.')
        event('CHECK_EVALUATED',{'node_id':current,'outcome':outcome,'evidence':evidence,'candidates':candidates})
        event('EDGE_SELECTED',{'edge_id':selected[0]['id'],'source':current,'target':selected[0]['target']})
        current=selected[0]['target']
    else: raise ValueError('Prozess erreichte kein Ergebnis.')
    disposition = {'r_nicht20':'OTHER_CLASSIFICATION','r_gemeiner_wert':'FAIR_VALUE_ALTERNATIVE',
                   'r_stichtag':'DATE_CORRECTION_REQUIRED','r_buchwert':'ASSESSMENT_COMPLETE',
                   'l_unknown':'EVIDENCE_REQUIRED','l_conflicted':'CONFLICTED_EVIDENCE','l_manual':'MANUAL_REVIEW'}[current]
    required = {'c_anwendungsbereich','c_persoenlich','c_gegenstand','c_neue_anteile','l_wertwahl'}
    if current == 'r_buchwert':
        required |= {'c_antrag','c_kst_sicher','c_passivueberhang','l_asset_taxright','c_sonstige_gegenleistung','c_rueckwirkung','l_selected'}
        if report['minimum_valuation']['balance']=='NOT_SATISFIED': required.add('c_aufstockung')
        if report['minimum_valuation']['consideration_status']=='NOT_SATISFIED': required.add('l_mindestwert')
    ready = report['selected']['status']=='SATISFIED' and required <= set(path) and (
        current == 'r_buchwert' or current=='r_gemeiner_wert' and report['selected']['effective_mode']=='gemeiner_wert')
    overall = 'READY_FOR_EXPERT_REVIEW' if ready else disposition
    if current == 'l_unknown' and not definition['policy']['enable_aufstockung'] and any(n in path for n in ('c_aufstockung','l_mindestwert')):
        overall = 'MODEL_REVIEW_REQUIRED'
    if current=='r_buchwert' and not ready: overall='INCOMPLETE_OR_INELIGIBLE_PATH'
    event('SAFETY_GATE',{'ready':ready,'missing_steps':sorted(required-set(path)), 'legal_status':report['selected']['status'], 'overall':overall})
    handoff = {
        'r_nicht20': {'status':'MANUAL_CLASSIFICATION', 'topics':['6 Abs.6 EStG / Tausch','16 EStG / Betriebsveraesserung','21 UmwStG / Anteilstausch'], 'automatic_tax':None},
        'r_gemeiner_wert': {'status':'VALUE_ELECTION_OR_REVIEW', 'topics':['20 Abs.2/3 UmwStG','16 Abs.4 und 34 EStG nur gesondert pruefen'], 'automatic_tax':None},
        'r_stichtag': {'status':'NEW_CONFIRMED_INPUT_REQUIRED', 'topics':['20 Abs.5/6 UmwStG','Tatsaechlichen Vermoegensuebergang belegen','Neuen Prueflauf erzeugen'], 'automatic_tax':None},
        'r_buchwert': {'status':'ENTITY_AND_YEAR_CONSEQUENCES', 'topics':['20 Abs.3/4 UmwStG','22 UmwStG / sieben Jahre','23 UmwStG / Wirtschaftsgueter','27 KStG / gesonderte Abstimmung','GrESt bei Grundstuecken gesondert'], 'automatic_tax':None},
    }.get(current, {'status':'MANUAL_RESOLUTION', 'topics':['Nachweis-, Widerspruchs- oder Modellklaerung'], 'automatic_tax':None})
    result = {'schema':'ProzessPilot-FunctionalRun-3','definition':deepcopy(definition),
              'definition_hash':digest(definition),'report':report,'events':events,'path':path,
              'terminal':current,'overall':overall,'handoff':handoff,'coverage':coverage(definition),
              'executor_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'notice':'Technische Pruefung, keine steuerliche Freigabe; Reviewerentscheidung separat.'}
    result['hash']=digest(result)
    return result


def verify(document):
    try:
        saved=deepcopy(document); expected=saved.pop('hash')
        integrity=expected==digest(saved) and document['definition_hash']==digest(document['definition'])
        legal=verify_legal(document['report'])
        replay=run(document['definition'],document['report']['facts'],as_of=document['report']['evaluation_date'])
        deterministic=replay==document
        return {'valid':integrity and legal['valid'] and deterministic,'integrity':integrity,
                'deterministic_replay':deterministic,'external_trust_anchor':False}
    except (ValueError,KeyError,TypeError,RecursionError):
        return {'valid':False,'integrity':False,'deterministic_replay':False,'external_trust_anchor':False}
