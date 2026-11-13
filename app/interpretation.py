"""Local, deterministic draft; no network or patient data sent to a service.

Interpretive reference: ERS/ATS 2022, doi:10.1183/13993003.01499-2021.
Repeatability reference: ATS/ERS 2019, doi:10.1164/rccm.201908-1590ST.
This module does not certify curve acceptability or diagnose disease.
"""
from datetime import datetime
import json
import math

from app.reference_values import age_years, gli2012_for_maneuver
from app.reference_policy import reference_description, study_policy

VERSION = 'spirometry-draft-v1'


def _finite(value):
    return isinstance(value,(int,float)) and math.isfinite(value)


def _read_json(value, fallback):
    try:
        return json.loads(value) if isinstance(value,str) else value if value is not None else fallback
    except (ValueError,TypeError):
        return fallback


def _phase(records, patient, session, references):
    issues=[]
    fvc=sorted((r['fvc'] for r in records if _finite(r.get('fvc')) and r['fvc']>0),reverse=True)
    fev1=sorted((r['fev1'] for r in records if _finite(r.get('fev1')) and r['fev1']>0),reverse=True)
    values={'fvc':fvc[0] if fvc else None,'fev1':fev1[0] if fev1 else None}
    values['fev1_fvc']=values['fev1']/values['fvc'] if fvc and fev1 else None
    if len(records)<3:
        issues.append('menos de tres maniobras seleccionadas')
    if len(fvc)!=len(records) or len(fev1)!=len(records) or not records:
        issues.append('valores FVC/FEV1 ausentes o inválidos')
    if values['fev1_fvc'] is not None and values['fev1_fvc']>1+1e-9:
        issues.append('FEV1 mayor que FVC; revisar la adquisición')
    try:
        date=datetime.fromisoformat(session['created_at']).date()
        age=age_years(patient.get('birth_date'),date)
    except (ValueError,TypeError,KeyError):
        age=None
    if age is None:
        issues.append('edad no disponible para evaluar repetibilidad')
    for key,ordered in [('FVC',fvc),('FEV1',fev1)]:
        if len(ordered)>=2 and age is not None:
            limit=.150 if age>6 else max(.100,.10*ordered[0])
            if ordered[0]-ordered[1]>limit+1e-12:
                issues.append(f'{key} no repetible entre los dos mejores valores')
    environments=[]
    for record in records:
        flags=_read_json(record.get('quality_errors_json'),None)
        processing=_read_json(record.get('processing_json'),{})
        if not isinstance(processing,dict):
            processing={}
        if not isinstance(flags,list) or flags:
            issues.append('alertas de calidad o control de calidad no disponible')
        if any(processing.get(k) is not True for k in ('inicio_aceptable','fev1_tiempo_cubierto','meseta_eofe')):
            issues.append('inicio, cobertura de FEV1 o final espiratorio pendientes de revisión')
        env=processing.get('environment') or {}
        if not isinstance(env,dict):
            env={}
        if (env.get('mode')!='patient' or env.get('status')!='patient_directional_engineering'
                or any(not _finite(env.get(k)) or env[k]<=0 for k in ('factor_positive','factor_negative'))):
            issues.append('corrección ambiental de la adquisición no documentada')
        environments.append(env)
    signature=lambda e:json.dumps({k:e.get(k) for k in ('model','conditions','calibration_date','calibration_factors')},sort_keys=True)
    if len({signature(e) for e in environments})>1:
        issues.append('condiciones de adquisición distintas entre maniobras')
    try:
        refs=references(patient,session,values) or {}
    except (ValueError,TypeError,OverflowError,ZeroDivisionError):
        refs={}
    for key in ('fvc','fev1','fev1_fvc'):
        reference=refs.get(key) or {}
        if not _finite(reference.get('lln')) or not _finite(reference.get('predicted')) or reference.get('predicted',0)<=0:
            imported = _read_json(session.get('source_json'), {}).get('origin') == 'breeze'
            issues.append('límites normales históricos de Breeze no recuperados' if imported else
                          'referencias GLI incompletas; revisar edad, sexo y talla')
            break
    return values,refs,list(dict.fromkeys(issues)),environments[0] if environments else {}


def _pattern(values,refs):
    low_ratio=values['fev1_fvc']<refs['fev1_fvc']['lln']
    low_fvc=values['fvc']<refs['fvc']['lln']
    if low_ratio:
        text='Hallazgos compatibles con alteración ventilatoria obstructiva.'
        if low_fvc:
            text+=' FVC también reducida: puede existir atrapamiento aéreo o restricción asociada; no se confirma un patrón mixto sin medir TLC.'
        return text
    if low_fvc:
        return ('FVC reducida con cociente FEV1/FVC conservado. Puede corresponder a restricción, '
                'un patrón inespecífico o una maniobra incompleta. Para confirmar restricción se requieren volúmenes pulmonares (TLC).')
    if values['fev1']<refs['fev1']['lln']:
        return 'FEV1 reducido con FVC y cociente conservados; revisar curvas, esfuerzo y contexto clínico.'
    return 'FVC, FEV1 y cociente FEV1/FVC dentro de los límites de las referencias seleccionadas.'


def generate_report(patient, session, maneuvers, references=gli2012_for_maneuver):
    patient,session=dict(patient),dict(session)
    lines=['BORRADOR DE INTERPRETACIÓN AUTOMÁTICA',
           'Requiere revisión profesional de curvas, calidad y contexto clínico antes de usarlo como informe.',
           'Referencia: GLI-2012 configurada en la aplicación.']
    if _read_json(session.get('source_json'), {}).get('origin') == 'breeze':
        lines[-1] = 'Referencia: predichos originales de Breeze; z-scores calculados con la desviación exportada cuando está disponible. Límites normales no recuperados.'
    elif study_policy(session) is not None:
        lines[-1] = reference_description(session)
    if patient.get('no_btps'):
        return '\n'.join(lines+['Estudio de jeringa sin corrección BTPS: no corresponde una interpretación clínica.'])
    phases={}
    selected=[dict(m) for m in maneuvers if m['review_status']=='accepted']
    for phase in ('pre','post'):
        records=[m for m in selected if m['phase']==phase]
        if not records:
            continue
        values,refs,issues,env=_phase(records,patient,session,references)
        phases[phase]=(values,refs,issues,env)
        lines+=['',f'{phase.upper()}: {len(records)} maniobras seleccionadas.']
        if all(_finite(values[k]) for k in ('fvc','fev1','fev1_fvc')):
            lines.append(f"FVC {values['fvc']:.2f} L; FEV1 {values['fev1']:.2f} L; FEV1/FVC {values['fev1_fvc']*100:.1f}%.")
        if len(records)>=2:
            for key in ('fvc','fev1'):
                ordered=sorted((m[key] for m in records if _finite(m.get(key))),reverse=True)
                if len(ordered)>=2:
                    lines.append(f'Diferencia entre los dos mejores {key.upper()}: {(ordered[0]-ordered[1])*1000:.0f} mL.')
        if issues:
            lines.append('Interpretación del patrón no emitida: '+'; '.join(issues)+'.')
        else:
            lines.append(_pattern(values,refs))
            lines.append('Las comprobaciones automáticas no sustituyen la revisión visual ni acreditan calidad ATS/ERS.')
        if env.get('calibration_date'):
            lines.append('Calibración usada: '+str(env['calibration_date'])+'.')
        if env.get('calibration_notice'):
            lines.append('La calibración no era del día de la adquisición; revisar su vigencia.')
    if not phases:
        lines+=['','No hay maniobras seleccionadas para interpretar.']
    if 'pre' in phases and 'post' in phases:
        pre,refs,pre_issues,pre_env=phases['pre']
        post,_,post_issues,post_env=phases['post']
        lines+=['','Comparación PRE/POST:']
        if pre_issues or post_issues:
            lines.append('Respuesta broncodilatadora no evaluada: revisar primero la calidad y las referencias de ambas fases.')
        elif any(pre_env.get(k)!=post_env.get(k) for k in ('model','conditions','calibration_date','calibration_factors')):
            lines.append('Respuesta broncodilatadora no evaluada: las condiciones de adquisición PRE/POST no coinciden.')
        else:
            changes={k:100*(post[k]-pre[k])/refs[k]['predicted'] for k in ('fev1','fvc')}
            lines.append('; '.join(f"Δ{k.upper()} {(post[k]-pre[k])*1000:+.0f} mL ({changes[k]:+.2f}% del predicho)" for k in changes)+'.')
            positive=any(v>10+1e-12 for v in changes.values())
            lines.append('Respuesta significativa según criterio ERS/ATS 2022 (>10% del predicho en FEV1 o FVC).'
                         if positive else 'No alcanza el criterio ERS/ATS 2022 de respuesta significativa (>10% del predicho en FEV1 o FVC).')
            lines.append('Aplicable si POST corresponde a una prueba tras broncodilatador con protocolo adecuado; no establece por sí sola asma ni EPOC.')
    lines+=['','Texto orientativo generado por reglas locales; revisar también la validación del equipo y de la corrección ambiental.',
            'Criterios: ERS/ATS 2022 (interpretación) y ATS/ERS 2019 (repetibilidad). '+VERSION+'.']
    return '\n'.join(lines)
