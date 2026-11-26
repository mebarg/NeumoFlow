"""Operator feedback for FVC session goals, separate from device status.

Counts are based on available automatic checks, not a certified ATS/ERS grade.
Target: three FEV1 and FVC values; compare the best two independently per phase.
"""
import math
from app.fvc_quality import processing, assessment


def session_feedback(maneuvers, phase, age):
    if type(age) not in (int, float) or not math.isfinite(age) or age < 0:
        age = None
    rows = [dict(m) for m in maneuvers if m['phase'] == phase]
    selected = [m for m in rows if m['review_status'] == 'accepted']
    values = {'fev1': [], 'fvc': []}
    unknown = 0
    alerts = set()
    for row in selected:
        params = processing(row)
        states = assessment(params)
        if any(s['state'] == 'unknown' for s in states.values()):
            unknown += 1
            continue
        for key in values:
            value = row.get(key)
            if states[key]['state'] == 'clear' and type(value) in (int,float) and math.isfinite(value) and value > 0:
                values[key].append(value)
            else:
                alerts.update(states[key]['reasons'])
    metrics = {}
    for key, entries in values.items():
        ordered = sorted(entries, reverse=True)
        limit = (.150 if age > 6 else max(.100, .10*ordered[0])) if age is not None and ordered else None
        difference = ordered[0]-ordered[1] if len(ordered) >= 2 else None
        metrics[key] = dict(count=len(ordered), difference=difference, limit=limit,
                            repeatable=difference is not None and limit is not None and difference <= limit+1e-9)
    counts = ' · '.join(key.upper()+f" {metrics[key]['count']}/3" for key in ('fev1', 'fvc'))
    ready = all(m['count'] >= 3 and m['repeatable'] for m in metrics.values()) and not unknown
    state = 'progress'
    if not selected:
        text = 'Realizá una maniobra · '+counts
        state = 'empty'
    elif age is None:
        text = 'Falta edad para evaluar repetibilidad'
        state = 'unknown'
    elif unknown:
        text = 'Calidad sin evaluación automática completa'
        state = 'unknown'
    elif ready:
        text = 'Objetivo automático alcanzado · '+counts.replace('/3','')
        state = 'ready'
    elif all(m['count'] >= 2 and m['repeatable'] for m in metrics.values()):
        action = 'intentá una tercera' if len(rows) == 2 else 'obtener otro valor sin alertas'
        text = 'Valores repetibles · '+action+' · '+counts
    elif all(m['count'] >= 3 for m in metrics.values()):
        text = 'Mejorar repetibilidad · '+counts
    elif alerts:
        text = 'Repetir / revisar calidad · '+counts
    else:
        text = 'Continuar maniobras · '+counts
    if len(rows) >= 8 and not ready and age is not None and age > 6:
        text = '8 o más intentos: evaluar si continuar · '+counts
    details = [phase.upper()+': objetivo de tres valores por parámetro sin alertas automáticas.']
    for key, data in metrics.items():
        difference = 'sin dos valores' if data['difference'] is None else f"diferencia {data['difference']*1000:.0f} mL"
        limit = '' if data['limit'] is None else f"; límite {data['limit']*1000:.0f} mL"
        details.append(f"{key.upper()}: {data['count']} valores; {difference}{limit}.")
    if unknown:
        details.append(f'{unknown} maniobras conservan calidad original o no tienen evaluación separada.')
    if alerts:
        details.append('Avisos: '+'; '.join(sorted(alerts)))
    details.append('Señal orientativa del sistema. Revisar curvas y esfuerzo; no certifica calidad ATS/ERS. El operador decide si continuar o finalizar.')
    return dict(state=state, ready=ready, text=text, tooltip='\n'.join(details), metrics=metrics)
