"""Versioned equation selection, independent of the global settings after creation."""
import json

FVC_PARAMETERS={'fvc':'FVC','fev1':'FEV1','fev1_fvc':'FEV1/FVC','fef2575':'FEF 25–75','pef':'PEF'}
PARAMETERS={**FVC_PARAMETERS,'svc':'SVC','ic':'IC','erv':'ERV','mvv':'MVV'}
GLI2012='gli2012-v1'
GLOBAL='gli-global2022-v1'
VOLUMES='gli-volumes2021-v1'
FVC_REFERENCE='svc-fvc-reference-v1'
POLGAR='mvv-polgar-breeze-v1'
ZAPLETAL='mvv-zapletal2-breeze-v1'
ITS='mvv-its-breeze-v1'
NONE='none'
EQUATIONS={GLI2012:'GLI-2012',GLOBAL:'GLI Global 2022',NONE:'Sin referencia',
           VOLUMES:'GLI 2021 volúmenes (5–80 años, ascendencia europea)',
           FVC_REFERENCE:'Referencia de FVC (sólo predicho y %)',
           POLGAR:'Polgar (Breeze, 7–17 años; sólo predicho y %)',
           ZAPLETAL:'Zapletal2 (Breeze, 6–18 años; sólo predicho y %)',
           ITS:'ITS (Breeze, adultos; sólo predicho y %)'}
SUPPORTED={k:(GLOBAL,GLI2012,NONE) if k in ('fvc','fev1','fev1_fvc') else
           (GLI2012,NONE) if k=='fef2575' else (NONE,) for k in FVC_PARAMETERS}
SUPPORTED.update(svc=(FVC_REFERENCE,VOLUMES,NONE),ic=(VOLUMES,NONE),erv=(VOLUMES,NONE),mvv=(POLGAR,ZAPLETAL,ITS,NONE))
LEGACY={k:GLI2012 if k in FVC_PARAMETERS and k!='pef' else NONE for k in PARAMETERS}
RECOMMENDED={**LEGACY,'fvc':GLOBAL,'fev1':GLOBAL,'fev1_fvc':GLOBAL}
SETTING='fvc_reference_equations_v1'


def validate_selection(selection,legacy=False):
 expected=set(FVC_PARAMETERS) if legacy else set(PARAMETERS)
 if not isinstance(selection,dict) or set(selection)!=expected or any(eq not in SUPPORTED[key] for key,eq in selection.items()):
  raise ValueError('Selección de ecuaciones inválida o no compatible con el parámetro.')
 return {**{k:NONE for k in PARAMETERS},**selection}


def configured_selection(value):
 if value is None:return dict(LEGACY)
 selection=json.loads(value)
 return validate_selection(selection,legacy=isinstance(selection,dict) and set(selection)==set(FVC_PARAMETERS))


def snapshot(selection,ethnicity):
 return {'version':2,'parameters':validate_selection(selection),'ethnicity':ethnicity or ''}


def validate_policy(policy):
 if (not isinstance(policy,dict) or set(policy)!={'version','parameters','ethnicity'} or
     type(policy['version']) is not int or policy['version'] not in (1,2) or
     policy['ethnicity'] not in ('','caucasian','african_american','northeast_asian','southeast_asian')):
  raise ValueError('Configuración de referencias del estudio no compatible.')
 selection=validate_selection(policy['parameters'],legacy=policy['version']==1)
 return {**policy,'parameters':selection}


def study_policy(session):
 source=json.loads(dict(session).get('source_json') or '{}')
 policy=source.get('reference_policy')
 return validate_policy(policy) if policy is not None else None


def reference_label(session):
 source=json.loads(dict(session).get('source_json') or '{}')
 if source.get('origin')=='breeze':return 'Breeze original'
 policy=study_policy(session)
 if policy is None:return 'GLI-2012'
 used=set(policy['parameters'].values())-{NONE}
 if len(used)==1:
  eq=next(iter(used))
  return 'GLI 2021 volúmenes' if eq==VOLUMES else EQUATIONS[eq]
 return 'Por parámetro' if used else 'Sin referencia'


def reference_description(session):
 policy=study_policy(session)
 if policy is None:return ''
 names={VOLUMES:'GLI 2021 volúmenes',FVC_REFERENCE:'predicho de FVC (sin LIN/z)',POLGAR:'Polgar/Breeze',ZAPLETAL:'Zapletal2/Breeze',ITS:'ITS/Breeze'}
 description='Referencias: '+'; '.join(f'{label}: {names.get(policy["parameters"][key],EQUATIONS[policy["parameters"][key]])}' for key,label in PARAMETERS.items() if
                               key in FVC_PARAMETERS or policy['parameters'][key]!=NONE)+'.'

 if VOLUMES in policy['parameters'].values():
  description+=' GLI 2021 volúmenes: 5–80 años, ascendencia europea.'
 if policy['parameters']['mvv'] in (POLGAR,ZAPLETAL,ITS):
  description+=' MVV/Breeze: sólo predicho y %, sin LIN/z verificados.'
  if policy['parameters']['mvv']==ITS:description+=' Límite superior de edad ITS no confirmado.'
 return description
