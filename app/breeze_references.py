"""Original Breeze reference values and derived standardized residuals.

Type 1 is Predicted and type 5 StandardDeviation in the verified COW profile.
No catalog matching, formula substitution, new BTPS correction or LLN inference.
"""
import base64
import hashlib
import json
import math
from functools import lru_cache

from app.breeze_cow import CowFormatError, read_cow_bytes

METRIC_FIELDS = {'fvc': 'FVC', 'fev1': 'FEV1', 'fev1_fvc': 'FEV1FVC',
                 'fef2575': 'FEF2575', 'pef': 'FEFMax'}
METHOD = 'breeze-exported-mean-sd-v1'
REFERENCE_NOTE = ('Z calculado por la aplicación: (medido − predicho) / DE exportada por Breeze. '
                  '«–» si no hay DE válida. Referencias originales, sin sustituir por GLI; límites históricos no recuperados.')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def positive(value):
    return finite(value) and value > 0


def reference_records(records):
    """Return means and SD in application units; ambiguous records stay absent."""
    results = []
    for kind in (1, 5):
        rows = [r for r in records if r.get('EffortTypeID') == kind]
        values = {}
        if len(rows) == 1:
            for key, field in METRIC_FIELDS.items():
                value = rows[0].get(field)
                if positive(value):
                    values[key] = value / 100 if key == 'fev1_fvc' else value
        results.append(values)
    return tuple(results)


@lru_cache(maxsize=8)
def _metadata(source_json):
    source = json.loads(source_json or '{}')
    if source.get('origin') != 'breeze':
        return None
    predicted = source.get('predicted') or {}
    patient = source.get('patient') or {}
    visit = source.get('visit') or {}
    patient = patient if isinstance(patient, dict) else {}
    visit = visit if isinstance(visit, dict) else {}
    sd = source.get('standard_deviation')
    if sd is None:
        # Older imports retain the exact original COW. Read it once per source,
        # without database writes, reimporting, or using today's catalog.
        sd = {}
        encoded = source.get('original_cow_base64')
        digest = source.get('sha256')
        if isinstance(encoded, str) and len(encoded) <= 90*1024*1024 and isinstance(digest, str):
            try:
                raw = base64.b64decode(encoded, validate=True)
                if hashlib.sha256(raw).hexdigest() == digest:
                    cow = read_cow_bytes(raw)
                    means, deviations = reference_records(cow.fvl_records)
                    if (cow.visit.get('VisitDateTime') == visit.get('VisitDateTime') and
                            cow.patient.get('PatientIDNum') == patient.get('PatientIDNum')):
                        sd = {key: value for key, value in deviations.items()
                              if positive(predicted.get(key)) and positive(means.get(key)) and
                              math.isclose(means[key], predicted[key], rel_tol=1e-12, abs_tol=1e-12)}
            except (ValueError, CowFormatError):
                pass  # Keep unavailable rather than infer or replace a reference.
    return predicted, sd if isinstance(sd, dict) else {}, bool(patient.get('SyringeFlag'))


def references(source_json, measured, no_btps=False):
    metadata = _metadata(source_json)
    if metadata is None:
        return None
    predicted, deviations, syringe = metadata
    out = {}
    for key, mean in predicted.items():
        if key not in METRIC_FIELDS or not positive(mean):
            continue
        value, sd = measured.get(key), deviations.get(key)
        z = None
        if not (no_btps or syringe) and finite(value) and positive(sd):
            calculated = (value-mean)/sd
            if finite(calculated):
                z = calculated
        percent = value/mean*100 if finite(value) else None
        out[key] = {'predicted': mean, 'percent': percent if finite(percent) else None,
                    'zscore': z, 'lln': None, 'standard_deviation': sd if positive(sd) else None,
                    'zscore_method': METHOD if z is not None else None}
    return out or None
