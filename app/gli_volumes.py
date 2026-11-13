"""Hall et al. GLI 2021 VC, IC, ERV; European ancestry, ages 5–80.

Numerical data provenance: docs/gli-volumes-sources.md. No extrapolation.
"""
import json
import math
from pathlib import Path
from functools import lru_cache

# M intercept, linear age, log(height cm), S intercept, linear age, L.
COEFFICIENTS={
 ('M','svc'):(-10.134371,-.003532,2.307980,-2.1367411,.0009367,.8611),
 ('F','svc'):(-9.230600,-.005517,2.116822,-2.220260,.002956,1.038),
 ('M','ic'):(-10.121688,.001265,2.188801,-1.856546,.002008,1.146),
 ('F','ic'):(-9.4438787,-.0002484,2.0312769,-1.775276,.002673,.9726),
 ('M','erv'):(-17.328650,-.006288,3.478116,-1.307616,.009177,.5517),
 ('F','erv'):(-14.145513,-.009573,2.871446,-1.54992,.01409,.5326),
}


@lru_cache(maxsize=1)
def _tables():
 return json.loads((Path(__file__).parent/'data/gli_volumes_2021.json').read_text())['tables']


def reference(sex,age,height,key,value,ethnicity):
 if (ethnicity!='caucasian' or (sex,key) not in COEFFICIENTS or
     not isinstance(age,(int,float)) or not math.isfinite(age) or not 5<=age<=80 or
     not isinstance(height,(int,float)) or not math.isfinite(height) or height<=0 or
     not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):return None
 rows=_tables()[{'svc':'VC','ic':'IC','erv':'ERV'}[key]+'.'+sex]
 pos=(age-5)*4;lo=min(int(pos),len(rows)-1);hi=min(lo+1,len(rows)-1);f=pos-lo
 spline=rows[lo][1]*(1-f)+rows[hi][1]*f
 a,b,c,d,e,l=COEFFICIENTS[(sex,key)]
 m=math.exp(a+b*age+c*math.log(height)+spline)
 s=math.exp(d+e*age)
 return {'predicted':m,'percent':value/m*100,'zscore':((value/m)**l-1)/(l*s),
         'lln':m*(1-1.645*l*s)**(1/l),'equation':'gli-volumes2021-v1'}
