"""Read-only patient history, using the same FVC summary as the study view."""
import json
import math
from datetime import datetime
from app import db
from app.reference_policy import reference_label, reference_description
from app.respiratory_measurements import summary as respiratory_summary

METRICS = {
    'fvc': ('FVC', 'L'), 'fev1': ('FEV1', 'L'), 'fev1_fvc': ('FEV1/FVC', '%'),
    'fef2575': ('FEF 25–75', 'L/s'), 'pef': ('PEF', 'L/s'),
    'svc': ('SVC', 'L'), 'ic': ('IC', 'L'), 'erv': ('ERV', 'L'), 'mvv': ('MVV', 'L/min'),
}


def fvc_summary(maneuvers):
    def best(key):
        values=[m[key] for m in maneuvers if m[key] is not None]
        return max(values) if values else None
    result={key:best(key) for key in ('fvc','fev1','fef2575','pef')}
    result['fev1_fvc']=result['fev1']/result['fvc'] if result['fvc'] and result['fev1'] is not None else None
    return result


def display_value(key, value):
    if value is None or not math.isfinite(value): return '–'
    return f'{value*100:.1f}' if key=='fev1_fvc' else f'{value:.2f}'


def patient_history(patient_id):
    """One chronological row per visit/phase, including empty visits without zeros.

    References and source results are preserved; no new equations or BTPS applied.
    No device is opened, no current study state is changed, and no rows are written.
    """
    rows=[]
    sessions=sorted(db.list_sessions_for_patient(patient_id),key=lambda s:(datetime.fromisoformat(s['created_at']).timestamp(),s['id']))
    for session in sessions:
        maneuvers=[dict(m) for m in db.list_maneuvers_for_session(session['id']) if m['review_status']=='accepted']
        respiratory=db.list_respiratory_measurements(session['id'])
        extra=respiratory_summary(respiratory)
        source=json.loads(session['source_json'] or '{}')
        phases=[phase for phase in ('pre','post') if any(m['phase']==phase for m in maneuvers) or
                any(r['phase']==phase and r['included'] for r in respiratory)] or ['']
        for phase in phases:
            included=[m for m in maneuvers if m['phase']==phase]
            values=fvc_summary(included)
            values.update({key:extra.get((phase,key)) for key in ('svc','ic','erv','mvv')})
            values={key:value if value is not None and math.isfinite(value) else None for key,value in values.items()}
            rows.append(dict(session_id=session['id'],created_at=session['created_at'],phase=phase,
                values=values,reference=reference_label(session),reference_note=reference_description(session),
                origin='Breeze' if source.get('origin')=='breeze' else 'NeumoFlow',
                included_count=len(included)+sum(r['included'] for r in respiratory if r['phase']==phase)))
    return rows
