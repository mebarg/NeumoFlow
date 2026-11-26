"""Provisional FVC quality checks and explicit operator review, not ATS grading.

Artifact rules are engineering heuristics. A flag is a suspicion, not a diagnosis.
Timing is relative to the saved back-extrapolated T0; raw curves are never changed.
"""
from copy import deepcopy
from functools import lru_cache
import json
import math

VERSION = 1
LABELS = {'cough': 'tos', 'glottic': 'cierre glótico', 'interruption': 'interrupción'}
STATES = {'clear': 'Sin alertas automáticas', 'review': 'Revisar',
          'unusable': 'No utilizable', 'unknown': 'Sin evaluación separada'}


def processing(record):
    data = dict(record)
    value = data.get('processing_json')
    if value is not None:
        try:
            data = json.loads(value or '{}')
        except (ValueError, TypeError):
            return {}
    return data if isinstance(data, dict) else {}


def event_label(event):
    noun = LABELS.get(event.get('kind'), 'artefacto')
    state = event.get('decision', 'pending')
    if state == 'confirmed':
        return noun.capitalize() + ' confirmada por operador' if event.get('kind') != 'glottic' else 'Cierre glótico confirmado por operador'
    if state == 'dismissed':
        return noun.capitalize() + ' descartada por operador' if event.get('kind') != 'glottic' else 'Cierre glótico descartado por operador'
    return 'Posible ' + noun


def detect_events(params):
    curve = params.get('vol_curve') or []
    if len(curve) < 3:
        return []
    dt = curve[1][0] - curve[0][0]
    if not math.isfinite(dt) or dt <= 0:
        return []
    # Exclude trailing rest: stopping normally must not itself imply glottic closure.
    last = max((i for i, point in enumerate(curve) if point[2] > 0), default=0)
    points = curve[1:last+1]
    if not points:
        return []
    flows = [p[2] for p in points]
    peak = max(flows)
    short = max(1, round(.15/dt))
    persistent = max(1, round(.30/dt))
    drop = max(.50, peak*.20)
    near_zero = max(.10, peak*.05)
    t_zero = params.get('t_zero', 0.)
    events = []

    def add(kind, start, end):
        start = max(0, start)
        end = min(len(points)-1, end)
        lo = max(0., points[start][0]-dt)
        hi = points[end][0]
        previous = next((e for e in reversed(events) if e['kind'] == kind), None)
        if previous and lo <= previous['end']+.15:
            previous['end'] = max(previous['end'], hi)
            previous['end_t0'] = previous['end']-t_zero
            return
        events.append(dict(kind=kind, start=lo, end=hi, start_t0=lo-t_zero,
                           end_t0=hi-t_zero, decision='pending'))

    for i in range(short, len(flows)-2*short):
        before = max(flows[i-short:i])
        low = min(flows[i:i+short])
        after = max(flows[i+short:i+2*short])
        if before-low >= drop and after-low >= drop:
            onset = next(j for j in range(i, i+short) if before-flows[j] >= drop)
            add('cough', onset, i+2*short-1)
    for i in range(short, len(flows)-persistent):
        before = max(flows[i-short:i])
        if before >= drop and before-flows[i] >= drop and max(flows[i:i+persistent]) <= near_zero:
            add('glottic', i, i+persistent-1)
    start = None
    for i, flow in enumerate(flows):
        if flow <= 0 and start is None:
            start = i
        if flow > 0 and start is not None:
            if (i-start)*dt >= .20-1e-9:
                # A glottic suspicion already describes this interval.
                lo, hi = points[start][0]-dt, points[i][0]
                if not any(e['kind']=='glottic' and e['start'] <= hi and e['end'] >= lo for e in events):
                    add('interruption', start, i-1)
            start = None
    events.sort(key=lambda e: (e['start'], e['kind']))
    for i, event in enumerate(events):
        event['id'] = f'{event["kind"]}-{i+1}'
    return events


def annotate(params):
    result = deepcopy(params)
    if result.get('origin') == 'breeze':
        raise ValueError('Se conserva la calidad original de los estudios importados de Breeze.')
    result['quality_version'] = VERSION
    result['quality_events'] = detect_events(result)
    result['tos_detectada'] = any(e['kind']=='cough' for e in result['quality_events'])
    result['cierre_glotico'] = any(e['kind']=='glottic' for e in result['quality_events'])
    result['quality_base_errors'] = [e for e in result.get('calidad_errores', [])
        if e not in ('Tos', 'Cierre glotico', 'Espiracion interrumpida')
        and not e.startswith(('Posible tos', 'Posible cierre glótico', 'Posible interrupción'))]
    result['calidad_errores'] = errors(result)
    return result


def errors(params):
    return list(params.get('quality_base_errors', [])) + [event_label(e)
        for e in params.get('quality_events', []) if e.get('decision') != 'dismissed']


def assessment(params):
    if params.get('quality_version') != VERSION or params.get('origin') == 'breeze':
        return {key: dict(state='unknown', reasons=[]) for key in ('fev1', 'fvc')}
    result = {key: dict(state='clear', reasons=[]) for key in ('fev1', 'fvc')}

    def issue(keys, text, state='review'):
        for key in keys:
            result[key]['reasons'].append(text)
            if result[key]['state'] != 'unusable':
                result[key]['state'] = state

    if not params.get('inicio_aceptable', False):
        issue(('fev1', 'fvc'), 'Inicio pendiente de revisión (BEV)')
    if not params.get('fev1_tiempo_cubierto', False):
        issue(('fev1',), 'Registro sin cobertura de un segundo desde T0', 'unusable')
    if not params.get('meseta_eofe', False):
        issue(('fvc',), 'Final sin meseta: revisar otros criterios de fin espiratorio')
    if params.get('duracion', 0.) < .5:
        issue(('fev1', 'fvc'), 'Esfuerzo menor de 0,5 s')
    for event in params.get('quality_events', []):
        decision = event.get('decision', 'pending')
        if decision == 'dismissed':
            continue
        early = event['start_t0'] < 1. and event['end_t0'] > 0.
        keys = (['fev1'] if early else []) if event['kind'] == 'cough' else (['fvc', 'fev1'] if early else ['fvc'])
        issue(keys, event_label(event), 'unusable' if decision == 'confirmed' else 'review')
    return result


def _eligibility(params):
    states = assessment(params)
    allowed = {key: states[key]['state'] in ('clear', 'unknown') for key in states}
    active = any(e.get('decision') != 'dismissed' for e in params.get('quality_events', []))
    allowed['pef'] = allowed['fef2575'] = not active and all(allowed.values())
    return allowed


@lru_cache(maxsize=32)
def _saved_eligibility(raw):
    return _eligibility(processing({'processing_json': raw}))


def metric_eligible(record, key):
    if key not in ('fev1', 'fvc', 'pef', 'fef2575'):
        return True
    data = dict(record)
    raw = data.get('processing_json')
    if isinstance(raw, str):
        # Old/imported curves can contain large source blobs. No new quality
        # metadata means their historical selection policy is unchanged.
        if '"quality_version"' not in raw:
            return True
        return _saved_eligibility(raw).get(key, True)
    return _eligibility(data).get(key, True)


def quality_text(params):
    if params.get('quality_version') != VERSION:
        return '; '.join(params.get('calidad_errores', [])) or 'Sin alertas registradas'
    states = assessment(params)
    text = ' · '.join(key.upper()+': '+STATES[states[key]['state']] for key in ('fev1', 'fvc'))
    pending = [event_label(e) for e in params.get('quality_events', []) if e.get('decision') != 'dismissed']
    return text + (' · '+'; '.join(pending) if pending else '')


def apply_decisions(params, decisions, reviewed_at):
    result = deepcopy(params)
    if result.get('origin') == 'breeze' or result.get('quality_version') != VERSION:
        raise ValueError('Esta maniobra no tiene evaluación de artefactos revisable.')
    events = {e['id']: e for e in result.get('quality_events', [])}
    if set(decisions) != set(events) or any(d not in ('pending','confirmed','dismissed') for d in decisions.values()):
        raise ValueError('Decisiones de calidad inválidas.')
    before = {key: e.get('decision', 'pending') for key, e in events.items()}
    for key, decision in decisions.items():
        events[key]['decision'] = decision
    result.setdefault('quality_reviews', []).append(dict(at=reviewed_at, before=before, after=dict(decisions)))
    result['calidad_errores'] = errors(result)
    return result


def plot_regions(params, acquisition=False):
    if params.get('quality_version') != VERSION:
        return []
    curve = (params.get('acq_curve') if acquisition else params.get('vol_curve')) or params.get('vol_curve') or []
    offset = params.get('inicio_idx', 0)*.01 if acquisition and params.get('acq_curve') else 0.
    regions = []
    for event in params.get('quality_events', []):
        if event.get('decision') == 'dismissed':
            continue
        points = [p for p in curve if event['start']+offset <= p[0] <= event['end']+offset]
        if points:
            regions.append(dict(points=points, label=event_label(event)+f" ({event['start_t0']:.2f} s desde T0)",
                                confirmed=event.get('decision') == 'confirmed'))
    return regions


def validate_quality(params):
    if type(params.get('quality_version')) is not int or params['quality_version'] != VERSION:
        raise ValueError('Versión de evaluación de calidad no compatible.')
    events = params.get('quality_events')
    if not isinstance(events, list) or len(events) > 1000:
        raise ValueError('Lista de eventos de calidad inválida.')
    ids = set()
    t0 = params.get('t_zero', 0.)
    if type(t0) not in (int, float) or not math.isfinite(t0):
        raise ValueError('Tiempo cero de calidad inválido.')
    curve = params.get('vol_curve') or []
    for event in events:
        if not isinstance(event, dict) or event.get('kind') not in LABELS or event.get('decision') not in ('pending','confirmed','dismissed'):
            raise ValueError('Evento de calidad inválido.')
        key = event.get('id')
        if not isinstance(key, str) or not key or key in ids:
            raise ValueError('Identificador de evento de calidad inválido.')
        ids.add(key)
        for name in ('start', 'end', 'start_t0', 'end_t0'):
            value = event.get(name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('Tiempo de evento inválido.')
        if event['start'] < 0 or event['end'] < event['start'] or event['end_t0'] < event['start_t0']:
            raise ValueError('Intervalo de evento inválido.')
        if curve and event['end'] > curve[-1][0]+1e-6:
            raise ValueError('Evento fuera de la curva guardada.')
        if abs(event['start_t0']-(event['start']-t0)) > 1e-6 or abs(event['end_t0']-(event['end']-t0)) > 1e-6:
            raise ValueError('El intervalo de calidad no coincide con el tiempo cero.')
    if not isinstance(params.get('quality_base_errors', []), list) or any(not isinstance(e, str) for e in params.get('quality_base_errors', [])):
        raise ValueError('Alertas base de calidad inválidas.')

    reviews = params.get('quality_reviews', [])
    if not isinstance(reviews, list) or any(not isinstance(review, dict) for review in reviews):
        raise ValueError('Historial de revisiones de calidad inválido.')
