"""Signed-flow SVC/MVV analysis. Positive flow is expiration.

Preserves the full acquisition and explicit operator marker. Quality checks do
not certify maximality, leaks, or clinical acceptability. No FVC substitutions.
"""
import math
from statistics import mean, median

RATE = 100
DT = 1/RATE
VERSION = 'svc-mvv-v1'


def acquisition_curve(samples):
    from app.spirometry import flujos_de_muestras
    if not samples:
        return []
    times = [s[0] for s in samples]
    flows = flujos_de_muestras(samples)
    if (not all(math.isfinite(v) for v in [*times, *flows]) or
            any(abs(b-a-DT) > 1e-6 for a,b in zip(times,times[1:]))):
        raise ValueError('La captura requiere muestras continuas a 100 Hz.')
    curve,volume = [(0.,0.,flows[0])],0.
    for i,flow in enumerate(flows):
        volume += flow*DT
        curve.append(((i+1)*DT, volume, flow))
    return curve


def phases(curve):
    """Directional phases with 0.02 L/s deadband; pauses keep the same phase."""
    result=[]
    start=0
    sign=0
    for i in range(1,len(curve)):
        flow=curve[i][2]
        direction=1 if flow > .02 else -1 if flow < -.02 else 0
        if direction and direction != sign:
            if sign:
                result.append((sign,start,i-1))
            start=i-1
            sign=direction
    if sign:
        result.append((sign,start,len(curve)-1))
    return [(s,a,b) for s,a,b in result
            if curve[b][0]-curve[a][0] >= .12 and abs(curve[b][1]-curve[a][1]) >= .025]


def tidal_baseline(curve):
    # Complete expirations have a preceding inspiration AND subsequent inspiration.
    cycles=phases(curve)
    ends=[];volumes=[]
    for i,(sign,a,b) in enumerate(cycles):
        if sign==1 and i>0 and i+1<len(cycles) and cycles[i-1][0]==-1 and cycles[i+1][0]==-1:
            ends.append(curve[b][1]);volumes.append(curve[b][1]-curve[a][1])
    last=ends[-3:];vt=median(volumes[-3:]) if volumes else None
    stable=len(last)==3 and max(last)-min(last) <= .15*vt
    return {'tidal_breaths':len(ends),'baseline_stable':stable,
            'baseline_volume':mean(last) if stable else None,
            'vt':mean(volumes[-3:]) if len(volumes)>=3 else None}


def analyze_curve(curve, mode, marker_time=None, direction='evc', target_seconds=12):
    if mode not in ('svc','mvv') or direction not in ('evc','ivc') or target_seconds not in (12,15):
        raise ValueError('Configuración de medición no válida.')
    result={'measurement_type':mode,'algorithm':VERSION,'acq_curve':curve,
            'marker_time':marker_time,'direction':direction,'target_seconds':target_seconds,
            'duration':curve[-1][0] if curve else 0.,'warnings':[], 'svc':None,'ic':None,'erv':None,
            'vt':None,'mvv':None,'mvv_estimate':None,'frequency':None,'expired_volume':None}
    if not curve or marker_time is None:
        result['warnings'].append('No se marcó el comienzo del esfuerzo.' if mode=='svc' else 'No se inició el intervalo MVV.')
        return result
    index=min(range(len(curve)),key=lambda i:abs(curve[i][0]-marker_time))
    baseline=tidal_baseline(curve[:index+1])
    if mode=='svc':
        result.update(baseline)
        segment=curve[index:]
        if len(segment)<2:
            result['warnings'].append('No hay esfuerzo después de la marca.')
            return result
        candidates=[p for p in phases(segment) if p[0]==(1 if direction=='evc' else -1)]
        if not candidates:
            result['warnings'].append('No se detectó el esfuerzo lento seleccionado.')
            return result
        _,a,b=max(candidates,key=lambda p:abs(segment[p[2]][1]-segment[p[1]][1]))
        if direction=='evc':
            low=min(range(a+1),key=lambda i:(segment[i][1],-segment[i][0]))
            high=max(range(low,b+1),key=lambda i:(segment[i][1],segment[i][0]))
        else:
            high=max(range(a+1),key=lambda i:segment[i][1])
            low=min(range(high,b+1),key=lambda i:(segment[i][1],-segment[i][0]))
        vc=segment[high][1]-segment[low][1]
        result.update(svc=vc if vc>.025 else None,effort_start=marker_time,
                      effort_end=segment[b][0],effort_duration=segment[b][0]-segment[a][0])
        if baseline['baseline_stable']:
            level=baseline['baseline_volume']
            if segment[low][1] <= level <= segment[high][1]:
                result.update(ic=level-segment[low][1],erv=segment[high][1]-level)
        else:
            result['warnings'].append('Nivel espiratorio no estable: IC y ERV no informados.')
        endpoint=high if direction=='evc' else low
        end_time=segment[endpoint][0]
        plateau=[p[1] for p in segment if end_time-1 <= p[0] <= end_time]
        result['plateau']=end_time-segment[a][0]>=1 and bool(plateau) and max(plateau)-min(plateau)<.025
        if not result['plateau']:
            result['warnings'].append('No se confirmó meseta de 25 mL en 1 s al final del esfuerzo.')
        if result['effort_duration']>15:
            result['warnings'].append('Esfuerzo lento mayor de 15 s; revisar la maniobra.')
    else:
        segment=[p for p in curve[index:] if p[0] <= marker_time+target_seconds+1e-7]
        elapsed=segment[-1][0]-segment[0][0] if segment else 0.
        expired=sum(max(p[2],0.)*DT for p in segment[1:])
        complete=[(a,b) for sign,a,b in phases(segment) if sign==1 and a>0 and b<len(segment)-1]
        result.update(interval_seconds=elapsed,expired_volume=expired,
                      mvv_estimate=expired*60/elapsed if elapsed>=1 else None,
                      breaths=len(complete),
                      frequency=(len(complete)-1)*60/(segment[complete[-1][1]][0]-segment[complete[0][1]][0]) if len(complete)>=2 else None,
                      vt=mean(segment[b][1]-segment[a][1] for a,b in complete) if complete else None)
        if elapsed < 12-1e-7:
            result['warnings'].append('Intervalo menor de 12 s: MVV incompleta; estimación no incluida en el sumario.')
        elif len(complete)<2:
            result['warnings'].append('Menos de dos ciclos completos; revisar el esfuerzo.')
        else:
            result['mvv']=expired*60/elapsed
    return result


def analyze_samples(samples, mode, marker_time=None, direction='evc', target_seconds=12, environment=None):
    result=analyze_curve(acquisition_curve(samples),mode,marker_time,direction,target_seconds)
    result['environment']=environment
    if samples:
        result['signal']=samples[0].signal_metadata
    return result


def summary(records):
    """Largest SVC/MVV by phase; average IC; ERV/VT from the largest SVC trace."""
    out={}
    for phase in ('pre','post'):
        selected=[r for r in records if r['included'] and r['phase']==phase]
        for mode,key in (('svc','svc'),('mvv','mvv')):
            candidates=[r for r in selected if r['kind']==mode and r['result'].get(key) is not None]
            best=max(candidates,key=lambda r:r['result'][key]) if candidates else None
            if best:
                for metric in (('svc','erv','vt') if mode=='svc' else ('mvv','frequency')):
                    out[(phase,metric)]=best['result'].get(metric)
                # ATS/ERS 2019: IC is the average of the acceptable maneuvers.
                if mode=='svc':
                    ics=[r['result']['ic'] for r in candidates if r['result'].get('ic') is not None]
                    out[(phase,'ic')]=mean(ics) if ics else None
    return out
