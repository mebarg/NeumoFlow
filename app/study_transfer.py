"""Versioned study interchange and read-only Breeze conversion.

.espiro is a ZIP with a checked manifest and one UTF-8 JSON per study. Never
extract members to disk. All selected writes use one SQLite transaction.
"""
import base64
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

from app import db
from app.breeze_cow import read_cow, FVL_BLOBS
from app.breeze_source import decode_source_blob
from app.breeze_references import reference_records, METHOD

FORMAT = 'espirometro.studies'
VERSION = 3
MAX_MEMBER = 128 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
PATIENT_FIELDS = ('transfer_uid', 'last_name', 'first_name', 'dni', 'birth_date', 'sex',
                  'ethnicity', 'height_cm', 'weight_kg', 'created_at', 'no_btps')
SESSION_FIELDS = ('transfer_uid', 'created_at', 'calibration_date', 'height_cm', 'weight_kg', 'notes', 'source_json')
MANEUVER_FIELDS = ('created_at', 'accepted', 'review_status', 'phase', 'print_selected', 'pef', 'fvc',
                   'fev1', 'fev1_fvc', 'fef2575', 'duration', 'bev', 'eofe_ok',
                   'quality_errors_json', 'samples_json', 'processing_json')
RESPIRATORY_FIELDS = ('kind','phase','created_at','included','result_json','samples_json')
METRICS = {'fvc': 'FVC', 'fev1': 'FEV1', 'fev1_fvc': 'FEV1FVC', 'fef2575': 'FEF2575', 'pef': 'FEFMax'}


class TransferError(ValueError):
    pass


@dataclass
class Study:
    patient: dict
    session: dict
    maneuvers: list
    filename: str = ''
    warnings: list = field(default_factory=list)
    duplicate_id: int | None = None
    respiratory: list = field(default_factory=list)

    @property
    def uid(self):
        return self.session['transfer_uid']


def _json(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TransferError('JSON con claves duplicadas')
        result[key] = value
    return result


def _load(data):
    try:
        return json.loads(data, object_pairs_hook=_object,
                          parse_float=_finite_float,
                          parse_constant=lambda value: (_ for _ in ()).throw(TransferError('Número no finito')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise TransferError('JSON inválido en el paquete') from exc


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise TransferError('Número JSON fuera de rango')
    return number


def _numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def _date(value, optional=False):
    if optional and value in ('', None):
        return
    if optional and isinstance(value, str) and len(value) == 10:
        try:
            date.fromisoformat(value)
            return
        except ValueError:
            pass
    if not isinstance(value, str) or 'T' not in value:
        raise TransferError('Fecha de estudio inválida')
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise TransferError('Fecha inválida') from exc


def validate(study):
    """Validate all persisted fields before any database mutation."""
    if not isinstance(study.patient, dict) or not isinstance(study.session, dict) or not isinstance(study.maneuvers, list):
        raise TransferError('Estructura de estudio inválida')
    for record, fields in ((study.patient, PATIENT_FIELDS), (study.session, SESSION_FIELDS)):
        if set(record) != set(fields):
            raise TransferError('Campos de paciente/estudio incompatibles con la versión 1')
        for key, value in record.items():
            if key in ('height_cm', 'weight_kg'):
                if value is not None and (not _numeric(value) or value <= 0):
                    raise TransferError('Antropometría inválida')
            elif key == 'no_btps':
                if type(value) is not int or value not in (0, 1):
                    raise TransferError('Indicador BTPS inválido')
            elif value is not None and not isinstance(value, str):
                raise TransferError(f'Campo de texto inválido: {key}')
        uid = record.get('transfer_uid')
        if not isinstance(uid, str) or not uid or len(uid) > 200:
            raise TransferError('Falta el identificador estable del estudio/paciente')
        _date(record['created_at'])
    if not study.patient['last_name'] or study.patient['first_name'] is None:
        raise TransferError('Falta el nombre del paciente')
    if study.patient['sex'] not in ('', 'F', 'M'):
        raise TransferError('Sexo inválido')
    if study.patient['birth_date']:
        try:
            date.fromisoformat(study.patient['birth_date'])
        except ValueError as exc:
            raise TransferError('Fecha de nacimiento inválida') from exc
    _date(study.session['calibration_date'], optional=True)
    source = _load(study.session['source_json']) if study.session['source_json'] else {}
    if not isinstance(source, dict):
        raise TransferError('Procedencia inválida')
    if "reference_policy" in source:
        from app.reference_policy import validate_policy
        try:
            validate_policy(source["reference_policy"])
        except ValueError as exc:
            raise TransferError(str(exc)) from exc
    if source.get('origin') == 'breeze':
        predicted = source.get('predicted', {})
        if (not isinstance(predicted, dict) or any(key not in METRICS or not _numeric(value) or value <= 0
                                                 for key, value in predicted.items())):
            raise TransferError('Predichos de Breeze inválidos')
        sd = source.get('standard_deviation', {})
        if (not isinstance(sd, dict) or any(key not in METRICS or not _numeric(value) or value < 0
                                          for key, value in sd.items())):
            raise TransferError('Desviaciones de Breeze inválidas')
    if not isinstance(study.respiratory,list) or len(study.respiratory)>10000:
        raise TransferError('Lista de mediciones SVC/MVV inválida')
    for measurement in study.respiratory:
        if not isinstance(measurement,dict) or set(measurement)!=set(RESPIRATORY_FIELDS):
            raise TransferError('Campos de medición SVC/MVV inválidos')
        if measurement['kind'] not in ('svc','mvv') or measurement['phase'] not in ('pre','post'):
            raise TransferError('Tipo de medición SVC/MVV inválido')
        if type(measurement['included']) is not int or measurement['included'] not in (0,1):
            raise TransferError('Inclusión de medición inválida')
        _date(measurement['created_at'])
        result=_load(measurement['result_json'])
        if not isinstance(result,dict) or result.get('measurement_type')!=measurement['kind']:
            raise TransferError('Resultado SVC/MVV inválido')
        for key in ('svc','ic','erv','vt','mvv','mvv_estimate','frequency','duration','interval_seconds'):
            if result.get(key) is not None and (not _numeric(result[key]) or result[key]<0):
                raise TransferError('Resultado numérico SVC/MVV inválido')
        warnings=result.get('warnings',[])
        if not isinstance(warnings,list) or any(not isinstance(w,str) for w in warnings):
            raise TransferError('Advertencias SVC/MVV inválidas')
        marker=result.get('marker_time')
        if marker is not None and (not _numeric(marker) or marker<0 or marker>result.get('duration',0)):
            raise TransferError('Marca de esfuerzo SVC/MVV inválida')
        curve=result.get('acq_curve')
        if (not isinstance(curve,list) or len(curve)>1000000 or any(
                not isinstance(point,list) or len(point)!=3 or not all(_numeric(v) for v in point) for point in curve)):
            raise TransferError('Curva SVC/MVV inválida')
        if any(b[0]<=a[0] for a,b in zip(curve,curve[1:])):
            raise TransferError('Tiempos de curva SVC/MVV inválidos')
        if not isinstance(_load(measurement['samples_json']),list):
            raise TransferError('Muestras SVC/MVV inválidas')
    if len(study.maneuvers) > 10000:
        raise TransferError('Demasiadas maniobras en un estudio')
    for maneuver in study.maneuvers:
        if not isinstance(maneuver, dict) or set(maneuver) != set(MANEUVER_FIELDS):
            raise TransferError('Campos de maniobra incompatibles')
        _date(maneuver['created_at'])
        if maneuver['phase'] not in ('pre', 'post') or maneuver['review_status'] not in ('pending', 'accepted', 'excluded', 'rejected'):
            raise TransferError('Fase o estado de maniobra inválido')
        if any(type(maneuver[k]) is not int or maneuver[k] not in (0, 1) for k in ('accepted', 'print_selected')):
            raise TransferError('Selección de maniobra inválida')
        if maneuver['accepted'] != int(maneuver['review_status'] == 'accepted'):
            raise TransferError('Selección de maniobra inconsistente')
        if maneuver['eofe_ok'] is not None and (type(maneuver['eofe_ok']) is not int or maneuver['eofe_ok'] not in (0, 1)):
            raise TransferError('Calidad de maniobra inválida')
        for key in ('pef', 'fvc', 'fev1', 'fev1_fvc', 'fef2575', 'duration', 'bev'):
            if maneuver[key] is not None and not _numeric(maneuver[key]):
                raise TransferError('Resultado de maniobra no finito o inválido')
        params = _load(maneuver['processing_json'] or '{}')
        errors = _load(maneuver['quality_errors_json'] or '[]')
        samples = _load(maneuver['samples_json'])
        if not isinstance(params, dict) or not isinstance(errors, list) or any(not isinstance(x, str) for x in errors) or not isinstance(samples, list):
            raise TransferError('Procesamiento de maniobra inválido')
        for key in ('acq_curve', 'vol_curve'):
            curve = params.get(key, [])
            if not isinstance(curve, list) or len(curve) > 1000000:
                raise TransferError('Curva inválida o demasiado grande')
            last = -float('inf')
            for point in curve:
                if not isinstance(point, list) or len(point) != 3 or not all(_numeric(x) for x in point) or point[0] < last:
                    raise TransferError('Curva con tiempos o valores inválidos')
                last = point[0]
    return study


def _positive(value):
    return value if value is not None and value > 0 else None


def read_breeze(path):
    cow = read_cow(path)
    p, v = cow.patient, cow.visit
    identity = v.get('PatientGUID') or p['PatientIDNum']
    patient_uid = 'breeze:' + hashlib.sha256(identity.encode()).hexdigest()
    uid = patient_uid + ':' + v['VisitDateTime']
    birthday = (p.get('Birthday') or '')[:10]
    # Do not guess the meaning of source lookup IDs (sex/race); retain them.
    patient = dict(transfer_uid=patient_uid, last_name=p.get('PatientLastName') or '(sin apellido)',
                   first_name=' '.join(filter(None, (p.get('PatientFirstName'), p.get('PatientMidName')))),
                   dni=p['PatientIDNum'].strip() or None, birth_date=birthday, sex='', ethnicity='',
                   height_cm=_positive(v.get('Height')), weight_kg=_positive(v.get('Weight')),
                   created_at=v['VisitDateTime'], no_btps=int(bool(p.get('SyringeFlag'))))
    predicted, standard_deviation = reference_records(cow.fvl_records)
    warnings = ['Se conservan los predichos de Breeze; sexo y etnia requieren revisión en la ficha.']
    raw_source = Path(path).read_bytes()
    source = {'origin': 'breeze', 'producer': cow.version, 'sha256': cow.sha256,
              'original_cow_base64': base64.b64encode(raw_source).decode('ascii'),
              'patient': p, 'visit': v, 'predicted': predicted,
              'standard_deviation': standard_deviation, 'zscore_method': METHOD, 'sections': cow.sections,
              'protocol_stages': cow.protocol_stages}
    # Preserve opaque extension bytes without assigning meanings.
    source['visit'] = {k: ({'opaque_hex': x.hex()} if isinstance(x, bytes) else x) for k, x in v.items()}
    session = dict(transfer_uid=uid, created_at=v['VisitDateTime'], calibration_date=v.get('CalibrationDateTime'),
                   height_cm=patient['height_cm'], weight_kg=patient['weight_kg'],
                   notes=v.get('PFConsult') or v.get('Comments') or '', source_json=_json(source))
    maneuvers = []
    for r in cow.fvl_records:
        if r.get('EffortTypeID') != 0:
            continue
        stage = r.get('PFProtocolStageIndex')
        if stage not in (1, 3):
            raise TransferError(f'Etapa Breeze {stage} no compatible con PRE/POST; no se importó el estudio')
        parts = [decode_source_blob(r[k]).fvl_points() for k in
                 ('FVLInspiratorySourceData', 'FVLExpiratorySourceData') if r.get(k)]
        curve = sorted(dict.fromkeys(point for points in parts for point in points), key=lambda point: point[0])
        # One shared volume translation; do not normalize the branches separately.
        if curve:
            minimum = min(point[1] for point in curve)
            display = [[t, vol-minimum, flow] for t, vol, flow in curve]
        else:
            display = []
            warnings.append('Una maniobra no contiene curvas con tiempo.')
        original = {k: x for k, x in r.items() if k not in FVL_BLOBS and not isinstance(x, bytes)}
        params = {key: r.get(value) for key, value in METRICS.items()}
        if params['fev1_fvc'] is not None:
            params['fev1_fvc'] /= 100
        params.update(duracion=r.get('ExpTime'), bev=r.get('VolExtrap'), origin='breeze',
                      original_results=original, acq_curve=display,
                      original_curves={k: base64.b64encode(r[k]).decode() for k in FVL_BLOBS if r.get(k)},
                      environment={'source': 'Breeze', 'calibration_date': v.get('CalibrationDateTime'),
                                   'conditions': {k: v.get(k) for k in ('Temperature', 'BarPress', 'Humidity')},
                                   'no_btps': bool(p.get('SyringeFlag'))})
        selected = int(bool(r.get('EffortSelected')))
        maneuvers.append(dict(created_at=r.get('EffortTime'), accepted=selected,
            review_status='accepted' if selected else 'excluded', phase='pre' if stage == 1 else 'post',
            print_selected=0, **{k: params[k] for k in METRICS}, duration=params['duracion'], bev=params['bev'],
            eofe_ok=None, quality_errors_json=_json(['Calidad original Breeze' +
                 (': '+r['FVLATSCodes'] if r.get('FVLATSCodes') else ': sin código ATS exportado')]),
            samples_json='[]', processing_json=_json(params)))
    if not maneuvers:
        raise TransferError('La visita no contiene maniobras FVC reales para importar')
    if any(v.get(k) for k in ('DLCOTest', 'PlethTest', 'MVVTest', 'SVCTest', 'FRCTest')):
        warnings.append('Contiene otras pruebas: se importarán solamente las maniobras FVC.')
    if not any(m['accepted'] for m in maneuvers):
        warnings.append('Breeze no seleccionó maniobras: se importan todas, inicialmente sin incluir en el sumario.')
    return validate(Study(patient, session, maneuvers, Path(path).name, list(dict.fromkeys(warnings))))


def _study_dict(study):
    return {'patient': study.patient, 'session': study.session, 'maneuvers': study.maneuvers, 'respiratory':study.respiratory}


def read_package(path):
    try:
        with ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > 10001 or len({i.filename for i in infos}) != len(infos):
                raise TransferError('Paquete con demasiados archivos o nombres duplicados')
            if any(i.file_size > MAX_MEMBER for i in infos) or sum(i.file_size for i in infos) > MAX_TOTAL:
                raise TransferError('El paquete supera el límite de lectura de 512 MiB')
            if 'manifest.json' not in z.namelist() or z.getinfo('manifest.json').file_size > 2*1024*1024:
                raise TransferError('Falta el manifiesto del paquete')
            manifest = _load(z.read('manifest.json'))
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or type(manifest.get('version')) is not int or manifest['version'] not in (1, 2, VERSION):
                raise TransferError('Formato o versión .espiro no compatible')
            entries = manifest.get('studies')
            if not isinstance(entries, list) or not entries or len(entries) > 10000:
                raise TransferError('Lista de estudios inválida')
            studies, names, uids = [], set(), set()
            for entry in entries:
                if not isinstance(entry, dict) or set(entry) != {'file', 'sha256'}:
                    raise TransferError('Entrada de manifiesto inválida')
                name = entry['file']
                if not isinstance(name, str) or not name.startswith('studies/') or '..' in name or '\\' in name or name in names:
                    raise TransferError('Nombre de estudio inválido o repetido')
                names.add(name)
                content = z.read(name)
                if hashlib.sha256(content).hexdigest() != entry['sha256']:
                    raise TransferError('La comprobación de integridad del estudio falló')
                item = _load(content)
                if not isinstance(item, dict) or set(item) not in ({'patient', 'session', 'maneuvers'}, {'patient', 'session', 'maneuvers','respiratory'}):
                    raise TransferError('Contenido de estudio inválido')
                study = validate(Study(**item, filename=Path(path).name))
                if study.uid in uids:
                    raise TransferError('Identificador de estudio repetido dentro del paquete')
                uids.add(study.uid)
                studies.append(study)
            if set(z.namelist()) != names | {'manifest.json'}:
                raise TransferError('El paquete contiene archivos no declarados')
            return studies
    except (BadZipFile, KeyError, RuntimeError, EOFError, OSError, TypeError, RecursionError) as exc:
        raise TransferError('No se pudo leer el paquete .espiro') from exc


def _patient_match(conn, study):
    p = study.patient
    by_uid = conn.execute('SELECT * FROM patients WHERE transfer_uid = ?', (p['transfer_uid'],)).fetchone()
    by_dni = conn.execute('SELECT * FROM patients WHERE dni = ?', (p['dni'],)).fetchone() if p['dni'] else None
    if by_uid and by_dni and by_uid['id'] != by_dni['id']:
        raise TransferError('Conflicto de identidad: el ID y el DNI corresponden a pacientes diferentes')
    if by_uid and (by_uid['dni'] or '') != (p['dni'] or ''):
        raise TransferError('El identificador del paciente coincide pero su DNI cambió; revisá la ficha')
    return by_uid or by_dni


def _duplicate(conn, study):
    patient = _patient_match(conn, study)
    exact = conn.execute('SELECT * FROM sessions WHERE transfer_uid = ?', (study.uid,)).fetchone()
    if exact:
        if not patient or exact['patient_id'] != patient['id']:
            raise TransferError('El estudio coincide con uno de otro paciente')
        return exact['id']
    if patient:
        rows = conn.execute('SELECT id FROM sessions WHERE patient_id = ? AND created_at = ?',
                            (patient['id'], study.session['created_at'])).fetchall()
        if len(rows) > 1:
            raise TransferError('Hay varios estudios del paciente con la misma fecha; revisá los duplicados')
        if rows:
            return rows[0]['id']
    return None


def scan_folder(folder):
    studies, errors, seen = [], [], set()
    paths = sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in ('.cow', '.espiro'))
    for path in paths:
        try:
            found = [read_breeze(path)] if path.suffix.lower() == '.cow' else read_package(path)
            with db.connect() as conn:
                for study in found:
                    study.duplicate_id = _duplicate(conn, study)
                    natural = (study.patient['dni'] or study.patient['transfer_uid'], study.session['created_at'])
                    if study.uid in seen or natural in seen:
                        errors.append((path.name, 'El estudio ya figura en otro archivo de esta carpeta; se muestra una sola vez.'))
                        continue
                    seen.add(study.uid)
                    seen.add(natural)
                    if _patient_match(conn, study):
                        study.warnings.append('Ficha existente: se conservan sus datos personales.')
                    studies.append(study)
        except (ValueError, OSError, sqlite3.Error) as exc:
            errors.append((path.name, str(exc)))
    return studies, errors


def _insert(conn, table, fields, record, extra=None):
    values = {key: record[key] for key in fields}
    values.update(extra or {})
    columns = ','.join(values)
    return conn.execute(f'INSERT INTO {table}({columns}) VALUES ({",".join("?" for _ in values)})',
                        tuple(values.values())).lastrowid


def import_studies(studies, replace=False):
    if not studies:
        raise TransferError('No hay estudios seleccionados')
    for study in studies:
        validate(study)
    if len({s.uid for s in studies}) != len(studies):
        raise TransferError('La selección contiene estudios repetidos')
    if len({(s.patient['dni'] or s.patient['transfer_uid'], s.session['created_at']) for s in studies}) != len(studies):
        raise TransferError('La selección contiene estudios del mismo paciente y fecha repetidos')
    backup, imported, skipped, replaced = None, 0, 0, 0
    with db.connect() as conn:
        # All writers in this process use SQLite; recheck matches under the lock.
        conn.execute('BEGIN IMMEDIATE')
        try:
            duplicates = [_duplicate(conn, s) for s in studies]
            if replace and any(duplicates):
                backup_dir = Path(db.DB_PATH).parent / 'backups'
                backup_dir.mkdir(exist_ok=True)
                backup = backup_dir / ('antes-importar-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
                # Separate read connection avoids backing up from an open write transaction.
                with closing(sqlite3.connect(db.DB_PATH)) as reader, closing(sqlite3.connect(backup)) as destination:
                    reader.backup(destination)
            for study in studies:
                duplicate = _duplicate(conn, study)
                if duplicate and not replace:
                    skipped += 1
                    continue
                patient = _patient_match(conn, study)
                patient_id = patient['id'] if patient else _insert(conn, 'patients', PATIENT_FIELDS, study.patient)
                if duplicate:
                    conn.execute('DELETE FROM respiratory_measurements WHERE session_id = ?', (duplicate,))
                    conn.execute('DELETE FROM maneuvers WHERE session_id = ?', (duplicate,))
                    conn.execute('DELETE FROM sessions WHERE id = ?', (duplicate,))
                    replaced += 1
                session_id = _insert(conn, 'sessions', SESSION_FIELDS, study.session, {'patient_id': patient_id})
                for maneuver in study.maneuvers:
                    _insert(conn, 'maneuvers', MANEUVER_FIELDS, maneuver, {'session_id': session_id})
                for measurement in study.respiratory:
                    _insert(conn,'respiratory_measurements',RESPIRATORY_FIELDS,measurement,{'session_id':session_id})
                imported += 1
        except Exception:
            conn.rollback()
            raise
    return {'imported': imported, 'skipped': skipped, 'replaced': replaced, 'backup': str(backup) if backup else None}


def export_candidates():
    with db.connect() as conn:
        return [dict(row) for row in conn.execute('''SELECT s.id, s.created_at, p.last_name, p.first_name, p.dni,
             COUNT(m.id) AS maneuver_count FROM sessions s JOIN patients p ON p.id=s.patient_id
             LEFT JOIN maneuvers m ON m.session_id=s.id GROUP BY s.id ORDER BY s.created_at DESC''')]


def export_studies(path, session_ids):
    if not session_ids or len(set(session_ids)) != len(session_ids):
        raise TransferError('Seleccioná estudios diferentes para exportar')
    if Path(path).resolve() == Path(db.DB_PATH).resolve():
        raise TransferError('El destino no puede ser la base de datos')
    studies = []
    with db.connect() as conn:
        conn.execute('BEGIN')  # One consistent snapshot, including all patients/curves.
        for session_id in session_ids:
            s = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
            if s is None:
                raise TransferError('Un estudio seleccionado ya no existe')
            p = conn.execute('SELECT * FROM patients WHERE id = ?', (s['patient_id'],)).fetchone()
            patient = {k: p[k] for k in PATIENT_FIELDS}
            session = {k: s[k] for k in SESSION_FIELDS}
            maneuvers = [{k: m[k] for k in MANEUVER_FIELDS} for m in conn.execute(
                'SELECT * FROM maneuvers WHERE session_id = ? ORDER BY created_at,id', (session_id,))]
            respiratory=[{k:m[k] for k in RESPIRATORY_FIELDS} for m in conn.execute(
                'SELECT * FROM respiratory_measurements WHERE session_id=? ORDER BY id',(session_id,))]
            studies.append(validate(Study(patient, session, maneuvers, respiratory=respiratory)))
    manifest = {'format': FORMAT, 'version': VERSION, 'created_at': datetime.now().isoformat(timespec='seconds'), 'studies': []}
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
        with ZipFile(temporary, 'w', ZIP_DEFLATED) as z:
            total = 0
            for i, study in enumerate(studies):
                content = _json(_study_dict(study)).encode('utf-8')
                total += len(content)
                if len(content) > MAX_MEMBER or total > MAX_TOTAL-2*1024*1024 or i >= 10000:
                    raise TransferError('La exportación supera el límite del paquete; seleccioná menos estudios')
                name = f'studies/{i+1:06d}.json'
                z.writestr(name, content)
                manifest['studies'].append({'file': name, 'sha256': hashlib.sha256(content).hexdigest()})
            z.writestr('manifest.json', _json(manifest).encode('utf-8'))
        read_package(temporary)  # Verify before making the artifact visible.
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return len(studies)
