"""FVC presentation curves, independent of saved clinical results and raw acquisition."""
import base64
import math
from app.breeze_cow import CowFormatError
from app.breeze_source import decode_source_blob


def volume_time_curve(processing):
    """Use the saved expiratory branch and restore its exported display origin.

    This translates stored points, without recalculating an ATS time zero. It
    never integrates signals or recalculates FVC, FEV1, duration, BEV or BTPS.
    Imported source/acquisition blobs remain untouched, including on old studies.
    """
    if processing.get('origin')=='breeze':
        encoded=(processing.get('original_curves') or {}).get('FVLExpiratorySourceData')
        if not isinstance(encoded,str) or len(encoded)>2_000_000:return []
        try:points=decode_source_blob(base64.b64decode(encoded,validate=True)).fvl_points()
        except (ValueError,TypeError,CowFormatError):return []
    else:
        points=processing.get('vol_curve') or processing.get('acq_curve') or []
    if not points:return []
    if any(not isinstance(point,(list,tuple)) or len(point)!=3 or
           any(type(value) not in (int,float) or not math.isfinite(value) for value in point) for point in points):return []
    if any(a[0]>b[0] for a,b in zip(points,points[1:])):return []
    t0,v0,_=points[0]
    if processing.get('origin')=='breeze':
        metadata=processing.get('original_results') or {}
        duration=metadata.get('ExpTime');time_to_peak=metadata.get('ToFEFMax')
        valid=lambda value:type(value) in (int,float) and math.isfinite(value)
        if valid(duration) and valid(time_to_peak) and 0<=time_to_peak<=duration and duration>0:
            peak=max(points,key=lambda point:point[2])
            from_end=points[-1][0]-duration
            from_peak=peak[0]-time_to_peak
            # Both original timings must agree to the source time-channel resolution (1/200 s).
            if points[0][0]<=from_end<=points[-1][0] and abs(from_end-from_peak)<=.005+1e-8:
                t0=from_end
    # Clip the comparison at display t=0, linearly interpolating its existing segment.
    visible=[point for point in points if point[0]>=t0]
    if visible and visible[0][0]>t0:
        before=next((point for point in reversed(points) if point[0]<t0),None)
        if before:
            after=visible[0];ratio=(t0-before[0])/(after[0]-before[0])
            visible.insert(0,(t0,before[1]+ratio*(after[1]-before[1]),before[2]+ratio*(after[2]-before[2])))
    return [[t-t0,v-v0,flow] for t,v,flow in visible]
