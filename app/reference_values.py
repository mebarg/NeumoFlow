from datetime import date, datetime
import json

import pandas
from pyspiro import GLI_2012
from app import gli_global
from app.reference_policy import study_policy, GLI2012, GLOBAL, NONE
from app.breeze_references import references as breeze_references


ETHNICITY_LABELS = {
    "caucasian": ("Caucasico", GLI_2012.Ethnicity.CAUCASIAN.value),
    "african_american": ("Afroamericano", GLI_2012.Ethnicity.AFRICAN_AMERICAN.value),
    "northeast_asian": ("Asiatico noreste", GLI_2012.Ethnicity.NORTHEAST_ASIAN.value),
    "southeast_asian": ("Asiatico sudeste", GLI_2012.Ethnicity.SOUTHEAST_ASIAN.value),
}

_gli = GLI_2012()


def age_years(birth_date, on_date=None):
    if not birth_date:
        return None
    try:
        born = date.fromisoformat(birth_date)
    except ValueError:
        return None
    current = on_date or date.today()
    return (current - born).days / 365.2425


def gli2012_for_maneuver(patient, session, params):
    """Dispatch the saved per-parameter policy; retain the original public API name."""
    # Imported historical results keep their original reference values. Unknown
    # source lookup IDs must not silently select a new GLI sex/ethnicity model.
    source = json.loads(dict(session).get('source_json') or '{}')
    if source.get('origin') == 'breeze':
        return breeze_references(dict(session).get('source_json'), params, bool(dict(patient).get('no_btps')))
    policy = study_policy(session)
    sex = {"F": 0, "M": 1}.get(patient["sex"])
    ethnicity = ETHNICITY_LABELS.get((policy["ethnicity"] if policy else patient["ethnicity"]) or "")
    height_cm = session["height_cm"]
    if sex is None or height_cm is None:
        return None

    try:
        session_date = datetime.fromisoformat(session["created_at"]).date()
    except ValueError:
        session_date = date.today()
    age = age_years(patient["birth_date"], session_date)
    if age is None:
        return None

    values = {
        "fvc": (GLI_2012.Parameters.FVC.value, params.get("fvc")),
        "fev1": (GLI_2012.Parameters.FEV1.value, params.get("fev1")),
        "fef2575": (GLI_2012.Parameters.FEF25_75.value, params.get("fef2575")),
        "fev1_fvc": (GLI_2012.Parameters.FEV1FVC.value, params.get("fev1_fvc")),
    }

    out = {}
    for key, (parameter, measured) in values.items():
        equation = policy["parameters"][key] if policy else GLI2012
        if equation == GLOBAL:
            out[key] = gli_global.reference(patient["sex"], age, height_cm, key, measured)
            if out[key]:
                out[key]["equation"] = equation
            continue
        if measured is None or equation == NONE or ethnicity is None:
            out[key] = None
            continue
        l, predicted, s = _gli.lms(sex, age, height_cm, ethnicity[1], parameter, measured)
        if l is pandas.NA or predicted is pandas.NA or s is pandas.NA:
            out[key] = None
            continue
        out[key] = {
            "equation": GLI2012,
            "predicted": float(predicted),
            "percent": float(_gli.percent(sex, age, height_cm, ethnicity[1], parameter, measured)),
            "zscore": float(_gli.zscore(sex, age, height_cm, ethnicity[1], parameter, measured)),
            "lln": float(_gli.lln(sex, age, height_cm, ethnicity[1], parameter, measured)),
        }
    return out


def gli2012_predicted(patient, session):
    seed = {"fvc": 1.0, "fev1": 1.0, "fef2575": 1.0, "fev1_fvc": 1.0}
    refs = gli2012_for_maneuver(patient, session, seed)
    if not refs:
        return None
    return {key: value["predicted"] for key, value in refs.items() if value}


def respiratory_references(patient,session,values):
    """Only the native study's saved SVC/MVV policy; historical studies stay unchanged."""
    from app import gli_volumes,mvv_reference
    from app.reference_policy import VOLUMES,FVC_REFERENCE,POLGAR,ZAPLETAL,ITS
    policy=study_policy(session)
    if policy is None or bool(dict(patient).get('no_btps')):
        return {}
    try:
        on_date=datetime.fromisoformat(session['created_at']).date()
    except (ValueError,TypeError):
        return {}
    age=age_years(patient['birth_date'],on_date)
    height=session['height_cm'];sex=patient['sex'];out={}
    for key in ('svc','ic','erv','mvv'):
        equation=policy['parameters'][key];value=values.get(key)
        if value is None:out[key]=None;continue
        if equation==VOLUMES:
            out[key]=gli_volumes.reference(sex,age,height,key,value,policy['ethnicity'])
        elif equation==FVC_REFERENCE:
            original=(gli2012_for_maneuver(patient,session,{'fvc':value}) or {}).get('fvc')
            out[key]=None if not original else {**original,'equation':FVC_REFERENCE,'lln':None,'zscore':None,
                'note':'Predicho de FVC aplicado a SVC; no se traslada su distribución ni su LIN/z-score.'}
        elif equation in (POLGAR,ZAPLETAL,ITS):
            out[key]=mvv_reference.reference(equation,sex,age,height,value)
        else:out[key]=None
    return out


def respiratory_predicted(patient,session):
    return {key:ref['predicted'] for key,ref in respiratory_references(
        patient,session,dict(svc=1.,ic=1.,erv=1.,mvv=1.)).items() if ref}
