"""Pure valuation rules for the bounded synthetic section-20 workflow.

Sources: section 20(2)-(5) UmwStG; UmwStE 2025 paragraphs 20.18, 20.19,
20.19a (official worked examples), 23.14-23.15. Amounts are NET unless named
asset_book/asset_fair. Nonzero withdrawals, pensions, hidden losses and foreign
special cases are deliberately not silently reduced to this simple model.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN

D = Decimal
CENT = D('0.01')


def amount(value):
    if isinstance(value, bool):
        raise ValueError('Boolean ist kein Geldbetrag.')
    try:
        result = D(str(value))
    except (ValueError, InvalidOperation, TypeError):
        raise ValueError('Endlicher Geldbetrag erforderlich.') from None
    if not result.is_finite() or abs(result) >= D('1e12') or result != result.quantize(CENT):
        raise ValueError('Geldbetrag: endlich, kleiner 1e12, maximal zwei Nachkommastellen.')
    return result


def combine(*states):
    for state in ('CONFLICTED', 'NOT_SATISFIED', 'UNKNOWN'):
        if state in states:
            return state
    return 'SATISFIED'


def fact(facts, key, kind='money', signed=False):
    rec = facts.get(key, {})
    if rec.get('observations') or rec.get('verification') == 'conflicted':
        return None, 'CONFLICTED'
    if rec.get('verification') != 'confirmed' or not rec.get('evidence_ref') or rec.get('value') is None:
        return None, 'UNKNOWN'
    value = rec['value']
    if kind == 'money':
        value = amount(value)
        if value < 0 and not signed:
            raise ValueError(key + ': nichtnegativer Betrag erforderlich.')
    return value, 'SATISFIED'


def valuation_inputs(facts):
    """Minimum required NET tax value, plus proof of asset-by-asset capacity.

    For a negative opening balance the demonstrator supports no additional
    consideration and requires a complete reconciled asset schedule. There is
    no fabricated override of the original balance assertion.
    """
    keys = ('book_value', 'fair_value', 'other_consideration', 'withdrawals', 'contributions')
    items = {k: fact(facts, k, signed=k == 'book_value') for k in keys}
    B, F, C, W, I = (items[k][0] for k in keys)
    state = combine(*(items[k][1] for k in keys))
    out = {'status': state, 'balance': 'UNKNOWN', 'consideration_status': 'UNKNOWN',
           'capacity_status': 'UNKNOWN', 'minimum_net_value': None, 'minimum_uplift': None,
           'allowed_consideration': None, 'excess_consideration': None,
           'asset_allocation': [], 'note': 'Bestaetigte Werte und Nachweise erforderlich.'}
    if state != 'SATISFIED':
        out['balance'] = 'CONFLICTED' if state == 'CONFLICTED' else 'UNKNOWN'
        return out
    balance = 'SATISFIED' if B >= 0 else 'NOT_SATISFIED'
    asserted, asserted_state = fact(facts, 'assets_ge_liabilities', kind='bool')
    if asserted_state == 'CONFLICTED' or (asserted_state == 'SATISFIED' and (type(asserted) is not bool or asserted != (B >= 0))):
        balance = 'CONFLICTED'
    out['balance'] = balance
    if F < B or C > F:
        out.update(status='NOT_SATISFIED', note='Gemeiner Nettowert oder Gegenleistung unplausibel.')
        return out
    if W or I:
        out.update(status='UNKNOWN', note='Entnahmen/Einlagen: individuelle Vermoegensabstimmung erforderlich.')
        return out
    if B < 0 and C:
        out.update(status='UNKNOWN', note='Passivueberhang zusammen mit sonstiger Gegenleistung: Fachklaerung.')
        return out
    allowed = max(B / 4, min(D(500000), B)) if B >= 0 else D(0)
    # A fractional cent must never be rounded upwards to admit excess payment.
    allowed = allowed.quantize(CENT, rounding=ROUND_DOWN)
    excess = max(D(0), C - allowed)
    base_min = B
    if excess:
        if F <= 0:
            out.update(status='NOT_SATISFIED', note='Kein positiver gemeiner Wert fuer Quotierung.')
            return out
        base_min = (1 - excess / F) * B + excess
    minimum = max(D(0), base_min, C).quantize(CENT, rounding=ROUND_CEILING)
    uplift = minimum - B
    out.update(allowed_consideration=float(allowed), excess_consideration=float(excess),
               consideration_status='SATISFIED' if C <= allowed else 'NOT_SATISFIED',
               minimum_net_value=float(minimum), minimum_uplift=float(uplift),
               capacity_status='SATISFIED' if minimum <= F else 'NOT_SATISFIED',
               note='Mindestansatz nach UmwStE 20.19/20.19a; keine abschliessende Steuerfestsetzung.')
    schedule, schedule_state = fact(facts, 'asset_schedule', kind='schedule')
    liabilities, liabilities_state = fact(facts, 'tax_liabilities')
    if schedule_state == 'CONFLICTED' or liabilities_state == 'CONFLICTED':
        out['capacity_status'] = 'CONFLICTED'
    elif schedule is not None:
        if liabilities_state != 'SATISFIED':
            out['capacity_status'] = 'UNKNOWN'
        else:
            validation, rows = allocate(schedule, liabilities, B, F, minimum)
            out['capacity_status'] = validation
            out['asset_allocation'] = rows
    elif B < 0:
        out.update(capacity_status='UNKNOWN', note='Negativer Buchwert: vollstaendiger Anlagenspiegel und Passiva benoetigt.')
    return out


def allocate(schedule, liabilities, book, fair, chosen):
    """Proportional positive hidden reserves with deterministic cent allocation.

    Hidden losses, debt revaluation, pensions and special asset restrictions
    require a different reviewed handler. Unknown is not a negative tax result.
    """
    if not isinstance(schedule, list) or not 1 <= len(schedule) <= 150:
        raise ValueError('Anlagenspiegel: 1 bis 150 Eintraege erforderlich.')
    rows, ids = [], set()
    for row in schedule:
        if not isinstance(row, dict) or set(row) - {'id', 'book', 'fair', 'kind', 'original_cost', 'annual_rate'}:
            raise ValueError('Ungueltiger Anlagenspiegel-Eintrag.')
        key = row.get('id')
        if not isinstance(key, str) or not 1 <= len(key) <= 80 or key in ids:
            raise ValueError('Eindeutige Wirtschaftsgut-ID erforderlich.')
        ids.add(key)
        b, f = amount(row.get('book')), amount(row.get('fair'))
        if b < 0 or f < 0:
            raise ValueError('Aktivposten muessen nichtnegativ sein.')
        if f < b or row.get('kind') in ('pension', 'special'):
            return 'UNKNOWN', []
        rows.append({'id': key, 'book': b, 'fair': f, 'kind': row.get('kind', 'other'),
                     'original_cost': row.get('original_cost'), 'annual_rate': row.get('annual_rate')})
    if sum(r['book'] for r in rows) - liabilities != book or sum(r['fair'] for r in rows) - liabilities != fair:
        return 'CONFLICTED', []
    uplift = chosen - book
    capacity = fair - book
    if uplift < 0 or uplift > capacity:
        return 'NOT_SATISFIED', []
    rows.sort(key=lambda r: r['id'])
    for row in rows:
        row['uplift'] = ((row['fair'] - row['book']) * uplift / capacity).quantize(CENT, rounding=ROUND_DOWN) if capacity else D(0)
    remaining = uplift - sum(r['uplift'] for r in rows)
    for row in rows:
        addition = min(remaining, row['fair'] - row['book'] - row['uplift'])
        row['uplift'] += addition
        remaining -= addition
    output = []
    for row in rows:
        tax_value = row['book'] + row['uplift']
        entry = {'id': row['id'], 'asset_book': float(row['book']), 'asset_fair': float(row['fair']),
                 'uplift': float(row['uplift']), 'asset_tax_value': float(tax_value),
                 'kind': row['kind'], 'afa_status': 'EXPERT_REVIEW', 'annual_afa': None}
        # Bounded implementation of section 23(3) no.1: original base plus uplift,
        # same annual rate, capped at remaining volume. Not a full-year schedule.
        if row['kind'] == 'linear' and row['original_cost'] is not None and row['annual_rate'] is not None:
            cost, rate = amount(row['original_cost']), D(str(row['annual_rate']))
            if not rate.is_finite() or not D(0) < rate <= 1 or cost < row['book']:
                raise ValueError('AfA-Grundlage oder Satz unplausibel.')
            entry.update(afa_status='ANNUAL_ILLUSTRATION_NO_PRORATION',
                         annual_afa=float(min(tax_value, (cost + row['uplift']) * rate).quantize(CENT, rounding=ROUND_DOWN)))
        output.append(entry)
    return 'SATISFIED', output
