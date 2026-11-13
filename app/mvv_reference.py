"""Explicit Breeze-catalog compatibility references: predicted value only.

The source expressions and statistic scale are documented in
 docs/referencias-svc-mvv.md. No assumed SD or automatic normality limits.
"""
import math


def reference(equation,sex,age,height,value):
 if (sex not in ('M','F') or any(type(v) not in (int,float) or not math.isfinite(v) for v in (age,height,value))
     or height<=0 or value<0):return None
 if equation=='mvv-polgar-breeze-v1' and 7<=age<18:
  predicted=1.276*height-99.5
 elif equation=='mvv-zapletal2-breeze-v1' and 6<=age<=18 and 107<=height<=182:
  predicted=10**(-1.9178+3.0388*math.log10(height))/1000
 elif equation=='mvv-its-breeze-v1' and age>=18:
  predicted=(3.39*height/2.54-1.26*age-21.4) if sex=='M' else (2.05*height/2.54-.57*age-5.5)
 else:return None
 if predicted<=0:return None
 return {'predicted':predicted,'percent':value/predicted*100,'lln':None,'zscore':None,'equation':equation,
         'note':'Compatibilidad con catálogo Breeze: sólo predicho y porcentaje; sin LIN/z-score verificados.'+
                (' Rango superior de edad ITS no confirmado.' if equation=='mvv-its-breeze-v1' else '')}
