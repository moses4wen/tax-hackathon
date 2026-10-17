"""Publication-time semantic regression cases, independent expected outcomes.

Synthetic figures; no network or assertion of professional legal approval.
"""
from copy import deepcopy
from .functional_graph import run


def confirmed(value):
    return {'value': value, 'verification': 'confirmed', 'evidence_ref': 'SYNTHETISCH: Testannahme'}


def sample(negative=False):
    values = {
        'asset_type': 'betrieb', 'receiving_company': True, 'new_shares': True,
        'essential_assets': True, 'future_corporate_tax': True, 'assets_ge_liabilities': True,
        'german_tax_right': True, 'book_value': 100000, 'fair_value': 400000,
        'other_consideration': 0, 'application_timely': True, 'planned_disposal': False,
        'transaction_type': 'ausgliederung', 'registered_merchant': True,
        'liabilities_not_exceed_assets': True, 'registration_effective': True,
        'register_entry_date': '2026-02-01', 'recipient_eu_eea': True,
        'recipient_formed_eu_eea': True, 'individual_business': True,
        'contributor_eu_eea': True, 'german_tax_right_received_shares': True,
        'retroactive_requested': True, 'tax_transfer_date': '2025-12-31',
        'register_filing_date': '2026-01-01', 'profit_method': 'bilanz',
        'valuation_choice': 'buchwert', 'transfer_costs': 0, 'withdrawals': 0,
        'contributions': 0, 'event_type': 'keines', 'contains_real_estate': False,
    }
    if negative:
        values.update(book_value=-200000, fair_value=1000000, assets_ge_liabilities=False,
                      tax_liabilities=500000,
                      asset_schedule=[{'id': 'Maschine', 'book': 300000, 'fair': 1500000,
                                       'kind': 'linear', 'original_cost': 600000, 'annual_rate': .1}])
    return {k: confirmed(v) for k, v in values.items()}


def check_definition(definition):
    """Hard gate: editable edges must preserve the reviewed path semantics."""
    cases = []
    normal = sample()
    cases.append(('Buchwert', normal, 'READY_FOR_EXPERT_REVIEW', 'r_buchwert', 0))
    negative = sample(True)
    enabled = definition['policy']['enable_aufstockung']
    cases.append(('Passivueberhang', negative, 'READY_FOR_EXPERT_REVIEW' if enabled else 'MODEL_REVIEW_REQUIRED',
                  'r_buchwert' if enabled else 'l_unknown', 200000 if enabled else None))
    missing = deepcopy(normal); missing['new_shares']['verification'] = 'reported'
    cases.append(('Nachweis fehlt', missing, 'EVIDENCE_REQUIRED', 'l_unknown', None))
    conflict = deepcopy(normal); conflict['new_shares']['observations'] = [confirmed(False)]
    cases.append(('Gegenbeleg', conflict, 'CONFLICTED_EVIDENCE', 'l_conflicted', None))
    no_application = deepcopy(normal); no_application['application_timely'] = confirmed(False)
    cases.append(('Antrag fehlt', no_application, 'FAIR_VALUE_ALTERNATIVE', 'r_gemeiner_wert', None))
    fair = deepcopy(no_application); fair['valuation_choice'] = confirmed('gemeiner_wert')
    cases.append(('Gemeiner Wert gewaehlt', fair, 'READY_FOR_EXPERT_REVIEW', 'r_gemeiner_wert', 300000))
    late = deepcopy(normal); late['register_filing_date'] = confirmed('2026-09-01'); late['register_entry_date'] = confirmed('2026-09-10')
    cases.append(('Stichtag unzulaessig', late, 'DATE_CORRECTION_REQUIRED', 'r_stichtag', None))
    late2 = deepcopy(late); late2['use_actual_transfer_date'] = confirmed(True)
    cases.append(('Stichtag korrigiert', late2, 'READY_FOR_EXPERT_REVIEW', 'r_buchwert', 0))
    cap = deepcopy(normal); cap.update(book_value=confirmed(3000000), fair_value=confirmed(5000000), other_consideration=confirmed(1000000))
    cases.append(('UmwStE 20.19a', cap, 'READY_FOR_EXPERT_REVIEW' if enabled else 'MODEL_REVIEW_REQUIRED',
                  'r_buchwert' if enabled else 'l_unknown', 100000 if enabled else None))
    failures = []
    for name, facts, overall, terminal, gain in cases:
        try:
            result = run(definition, facts)
            if result['overall'] != overall or result['terminal'] != terminal:
                failures.append({'case': name, 'expected': [overall, terminal], 'actual': [result['overall'], result['terminal']]})
            if gain is not None and result['report']['consequences'][1]['gross_gain_preliminary'] != gain:
                failures.append({'case': name, 'expected_gain': gain})
        except (ValueError, KeyError, TypeError) as exc:
            failures.append({'case': name, 'error': type(exc).__name__})
    return failures
