"""GLI Global 2022 LMS, ages 3–95. See docs/ecuaciones-referencia.md.

Numerical spline tables are the published GLI workbook data transcribed in pft.
No extrapolation, ethnic adjustment, or substitution of unsupported parameters.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

# M: intercept, log(height in cm), log(age); S: intercept, log(age);
# L: intercept, log(age). Bowerman et al., doi:10.1164/rccm.202205-0963OC.
COEFFICIENTS = {
    ('M', 'fev1'): ((-11.399108, 2.462664, -.011394), (-2.256278, .080729), (1.22703, 0)),
    ('M', 'fvc'): ((-12.629131, 2.727421, .009174), (-2.195595, .068466), (.9346, 0)),
    ('M', 'fev1_fvc'): ((1.022608, -.218592, -.027586), (-2.882025, .068889), (3.8243, -.3328)),
    ('F', 'fev1'): ((-10.901689, 2.385928, -.076386), (-2.364047, .129402), (1.21388, 0)),
    ('F', 'fvc'): ((-12.055901, 2.621579, -.035975), (-2.310148, .120428), (.899, 0)),
    ('F', 'fev1_fvc'): ((.9189568, -.1840671, -.0461306), (-3.171582, .144358), (6.6490, -.9920)),
}


@lru_cache(maxsize=1)
def _tables():
    return json.loads((Path(__file__).parent/'data/gli_global_2022.json').read_text())['tables']


def lms(sex, age, height_cm, key):
    if ((sex, key) not in COEFFICIENTS or age is None or height_cm is None or
            not math.isfinite(age) or not 3 <= age <= 95 or
            not math.isfinite(height_cm) or height_cm <= 0):
        return None
    field = {'fvc': 'FVC', 'fev1': 'FEV1', 'fev1_fvc': 'FEV1FVC'}[key]
    rows = _tables()[field + ('_MALE' if sex == 'M' else '_FEMALE')]
    position = (age-3)*4
    lower = min(int(position), len(rows)-1)
    upper = min(lower+1, len(rows)-1)
    fraction = position-lower
    ms, ss, _ = [rows[lower][i]*(1-fraction)+rows[upper][i]*fraction for i in (1, 2, 3)]
    cm, cs, cl = COEFFICIENTS[(sex, key)]
    a = math.log(age)
    return (cl[0]+cl[1]*a,
            math.exp(cm[0]+cm[1]*math.log(height_cm)+cm[2]*a+ms),
            math.exp(cs[0]+cs[1]*a+ss))


def reference(sex, age, height_cm, key, value):
    if value is None or not math.isfinite(value) or value < 0:
        return None
    coefficients = lms(sex, age, height_cm, key)
    if coefficients is None:
        return None
    l, m, s = coefficients
    z = ((value/m)**l-1)/(l*s) if l != 0 else math.log(value/m)/s if value > 0 else None
    bound = 1-1.645*l*s
    lln = m*bound**(1/l) if l != 0 and bound > 0 else m*math.exp(-1.645*s) if l == 0 else None
    return {'predicted': m, 'percent': value/m*100, 'zscore': z, 'lln': lln}
