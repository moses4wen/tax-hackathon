"""Golden cases and failure/edge tests for the additive deterministic tax engine."""
from copy import deepcopy

import pytest

from app.legal_reasoning import assess, verify


def confirmed(value, ref='SYNTHETISCH: Prüfannahme'):
    return {'value': value, 'verification': 'confirmed', 'evidence_ref': ref}


def sample():
    return {k:confirmed(v) for k,v in {
        'asset_type':'betrieb','receiving_company':True,'new_shares':True,
        'essential_assets':True,'future_corporate_tax':True,'assets_ge_liabilities':True,
        'german_tax_right':True,'book_value':100000,'fair_value':400000,
        'other_consideration':0,'application_timely':True,
        'transaction_type':'ausgliederung','registered_merchant':True,
        'liabilities_not_exceed_assets':True,'registration_effective':True,
        'register_entry_date':'2026-02-01','recipient_eu_eea':True,
        'contributor_eu_eea':True,'german_tax_right_received_shares':True,
        'retroactive_requested':True,'tax_transfer_date':'2025-12-31',
        'register_filing_date':'2026-01-01','profit_method':'bilanz',
        'valuation_choice':'buchwert','intermediate_value':250000,
        'transfer_costs':0,'withdrawals':0,'contributions':0,
        'event_type':'keines',
    }.items()}


def test_mustermann_book_value_complete():
    r=assess(sample())
    assert r['selected']=={'mode':'buchwert','status':'SATISFIED','overall':'READY_FOR_EXPERT_REVIEW'}
    assert r['baseline']['gain']==300000
    assert r['consequences'][0]['tax_basis']==100000
    assert r['consequences'][1]['gross_gain_preliminary']==0
    assert r['consequences'][1]['new_share_cost_basis_preliminary']==100000
    assert r['proof_obligations'][0]['reference_date']=='2026-12-31'
    assert r['proof_obligations'][0]['deadline']=='2027-05-31'
    assert r['proof_obligations'][-1]['deadline']=='2033-05-31'
    assert len(r['graph']['nodes'])>70 and len(r['graph']['edges'])>100
    assert verify(r)['valid']
    assert any(x['kind']=='TaxConsequence' for x in r['graph']['nodes'])
    assert any(x['relation']=='GOVERNS' for x in r['graph']['edges'])
    assert any(x['relation']=='SUPPORTS' for x in r['graph']['edges'])


def test_three_scenarios_and_fair_without_low_value_application():
    f=sample()
    r=assess(f)
    a={o['mode']:o for o in r['valuation_options']}
    assert a['zwischenwert']['valuation_gain_preliminary']==150000
    assert a['gemeiner_wert']['valuation_gain_preliminary']==300000
    f['application_timely']=confirmed(False)
    f['future_corporate_tax']=confirmed(False)
    f['valuation_choice']=confirmed('gemeiner_wert')
    r2=assess(f)
    assert r2['selected']['status']=='SATISFIED'
    assert r2['valuation_options'][0]['status']=='NOT_SATISFIED'
    assert r2['consequences'][0]['tax_basis']==400000
    assert r2['sperrfrist']['status']=='NOT_APPLICABLE_FAIR_VALUE'


def test_other_consideration_cap_enforced_and_traceable():
    f=sample();f['other_consideration']=confirmed(110000)
    r=assess(f)
    assert r['selected']['status']=='NOT_SATISFIED'
    check=next(x for x in r['assessments'] if x['code']=='CONSIDERATION_LIMIT')
    assert check['status']=='NOT_SATISFIED'
    assert 'other_consideration' in check['fact_keys']
    f['other_consideration']=confirmed(100000)
    assert assess(f)['selected']['status']=='SATISFIED'


def test_missing_evidence_stops_positive_decision():
    f=sample();f['registered_merchant']={'value':True,'verification':'reported','evidence_ref':''}
    r=assess(f)
    assert r['selected']['status']=='UNKNOWN'
    assert r['consequences'][0]['tax_basis'] is None
    f['registered_merchant']={'value':True,'verification':'confirmed','evidence_ref':''}
    assert assess(f)['selected']['status']=='UNKNOWN'


def test_conflicting_observation_is_never_pass():
    f=sample();f['new_shares']['observations']=[{'value':False,'verification':'confirmed','evidence_ref':'Demo Gegenbeleg'}]
    r=assess(f)
    assert r['selected']['status']=='CONFLICTED'
    assert r['selected']['overall']=='CONFLICTED_EVIDENCE'


def test_retroactive_date_beyond_eight_months_fails():
    f=sample();f['register_filing_date']=confirmed('2026-09-01')
    r=assess(f)
    assert next(x for x in r['assessments'] if x['code']=='RETROACTIVE')['status']=='NOT_SATISFIED'
    assert r['selected']['status']=='NOT_SATISFIED'


def test_einzelrechtsnachfolge_has_two_date_checks():
    f=sample();f['transaction_type']=confirmed('einzelrechtsnachfolge')
    f['contract_date']=confirmed('2026-01-01')
    f['economic_transfer_date']=confirmed('2026-02-01')
    assert assess(f)['selected']['status']=='SATISFIED'
    f['economic_transfer_date']=confirmed('2026-09-01')
    assert assess(f)['selected']['status']=='NOT_SATISFIED'


def test_personal_scope_alternative_tax_right():
    f=sample();f['contributor_eu_eea']=confirmed(False)
    assert assess(f)['selected']['status']=='SATISFIED'
    f['german_tax_right_received_shares']=confirmed(False)
    assert assess(f)['selected']['status']=='NOT_SATISFIED'
    f['recipient_eu_eea']={'value':True,'verification':'unknown','evidence_ref':''}
    assert assess(f)['selected']['status']=='NOT_SATISFIED'


def test_sperrfrist_sale_partial_full_years_and_retro_year():
    f=sample();f.update({
        'event_type':confirmed('anteilsverkauf'),'event_date':confirmed('2028-12-30'),
        'disposal_fraction':confirmed(1),'share_sale_proceeds':confirmed(500000),
        'share_sale_costs':confirmed(0),'section17_applies':confirmed(True),
    })
    r=assess(f);s=r['sperrfrist']
    assert s['status']=='EGI_PRELIMINARY'
    assert s['completed_time_years']==2
    assert s['einbringungsgewinn_I']==214285.71
    assert s['retroactive_tax_year']==2025
    assert s['share_sale_gain_preliminary']==185714.29
    f['disposal_fraction']=confirmed(.5)
    half=assess(f)['sperrfrist']
    assert half['einbringungsgewinn_I']==107142.85
    assert half['additional_share_acquisition_costs']==107142.85


def test_sperrfrist_anniversary_exact_boundary():
    f=sample();f.update({'event_type':confirmed('anteilsverkauf'),
                         'event_date':confirmed('2032-12-31'),'disposal_fraction':confirmed(1)})
    assert assess(f)['sperrfrist']['status']=='OUTSIDE_SEVEN_YEARS'
    f['event_date']=confirmed('2032-12-30')
    assert assess(f)['sperrfrist']['einbringungsgewinn_I']==42857.14


def test_replacement_events_not_automatically_taxed():
    f=sample();f.update({'event_type':confirmed('ersatzereignis'), 'event_date':confirmed('2028-04-01')})
    assert assess(f)['sperrfrist']['status']=='MANUAL_EVENT_CLASSIFICATION'


def test_nonzero_withdrawals_blocks_unsupported_tax_computation():
    f=sample();f['withdrawals']=confirmed(100)
    r=assess(f)
    assert r['selected']['status']=='UNKNOWN'
    assert r['consequences'][0]['tax_basis'] is None


def test_history_outside_supported_year_not_promoted():
    f=sample();f['tax_transfer_date']=confirmed('2020-12-31')
    f['register_filing_date']=confirmed('2021-01-05')
    assert assess(f)['selected']['status']=='UNKNOWN'


def test_integrity_and_replay_detect_tampering():
    r=assess(sample());assert verify(r)['valid']
    r2=deepcopy(r);r2['consequences'][1]['new_share_cost_basis_preliminary']=999999
    assert not verify(r2)['valid']
    r3=deepcopy(r);r3['graph']['nodes'][0]['label']='MANIPULIERT'
    assert not verify(r3)['valid']


def test_date_leapyear_proof_deadline():
    f=sample();f['tax_transfer_date']=confirmed('2026-02-28')
    f['register_filing_date']=confirmed('2026-02-28')
    f['register_entry_date']=confirmed('2026-03-01')
    r=assess(f)
    assert r['proof_obligations'][0]['reference_date']=='2027-02-28'
    assert r['proof_obligations'][0]['deadline']=='2027-05-31'


def test_invalid_fractions_and_money_rejected():
    f=sample();f.update(event_type=confirmed('anteilsverkauf'),event_date=confirmed('2027-02-01'),
                        disposal_fraction=confirmed(1.5))
    with pytest.raises(ValueError,match='Anteil'):
        assess(f)
    f['disposal_fraction']=confirmed(.5);f['book_value']=confirmed('-1')
    with pytest.raises(ValueError,match='Betrag'):
        assess(f)


def test_registration_must_be_effective_and_after_filing():
    f=sample();f['registration_effective']={'value':True,'verification':'reported','evidence_ref':''}
    assert assess(f)['selected']['status']=='UNKNOWN'
    f['registration_effective']=confirmed(False)
    assert assess(f)['selected']['status']=='NOT_SATISFIED'
    f['registration_effective']=confirmed(True)
    f['register_entry_date']=confirmed('2025-12-01')
    assert assess(f)['selected']['status']=='NOT_SATISFIED'


def test_no_retroactive_application_requires_actual_date():
    f=sample();f['retroactive_requested']=confirmed(False)
    assert assess(f)['selected']['status']=='NOT_SATISFIED'
    f['tax_transfer_date']=confirmed('2026-02-01')
    assert assess(f)['selected']['status']=='SATISFIED'
