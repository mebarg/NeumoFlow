"""Read tagged binary Breeze COW records without recalculating clinical values.

Observed profile: DBTools export in 6.2 format from Breeze 6.4.1, signature
510. The producer version does not identify the export format. Source-curve
payloads are decoded separately by breeze_source. The observed encrypted
6.4.1 profile is supported without an external crypto executable.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import hashlib
import math
from pathlib import Path
import struct


class CowFormatError(ValueError):
    pass


END = b'%LastField%\x00'
PATIENT_TEXT = set('PatientIDNum PatientLastName PatientFirstName PatientMidName UserData'.split())
VISIT_FLOAT = set('Age ArmSpan BarPress BSA Height Humidity PackaDay PackYears QuitYears Temperature Weight YearsSmoke BMI LeanBodyMass'.split())
VISIT_BYTE = set('CoughID DyspneaID PrePost TobaccoID WheezeID ReviewStatusID LastPFProtocolStageIndex TestingStage'.split())
VISIT_BOOL = set('DLCOTest BloodTest DynamicTest FRCTest FVLTest MipMepTest MVVTest NICOTest SBN2Test StaticTest SVCTest ExFVLTest P100Test Posted Trend CCMCanopyTest CCMVentTest CCMStandardTest BikeTest TreadmillTest PlethTest CopyToQueryDB DeltaCO2Test'.split())
VISIT_TEXT = set('PatientGUID PatientIDNum Account VisitAuxData VisitAuxData2 VisitAuxData3 VisitAuxData4 Comments Diagnosis DTXName Illness Medication OccuExpos Room UserData PostComm SiteGUID SiteName PFProtocolGUID PFProtocolName PFConsult QRSPTCode QRSPTLotNumber CalibrationWorkstationGUID WorkstationName'.split())
FVL_DOUBLE = set('EffortCDUs ExpTime FEF10 FEF2001200 FEF25 FEF2575 FEF40 FEF50 FEF50FIF50 FEF60 FEF70 FEF75 FEF7585 FEF80 FEF85 FEF90 FEFMax FET2575 FEV05 FEV05FVC FEV1 FEV10 FEV1FVC FEV1SVC FEV2 FEV2FVC FEV3 FEV3FVC FEV6 FEV6FVC FEV7 FIF25 FIF2575 FIF50 FIF75 FIFMax FIV1 FIV1FIVC FIVC FVC FVCMeanTr MMET PAlvPeak ToFEFMax VolExtrap VolPAlvPk FEV1FEV6 FEFMaxFVC FEFMaxFEV6 FEV05FEV6 FEV2FEV6 FEV3FEV6 PEF VMax60 VMax70 VMax80 MP30 FEF50FVC FEF75FVC'.split())
FVL_BLOBS = set('FVLExpiratorySourceData FVLInspiratorySourceData FVLTidalSourceData'.split())
VISIT_EXTRA_TEXT = {'OrderID', 'PatVisitGUID', 'ReportFileName'} | {
    f'VisitAuxData{i}' for i in range(5, 21)
} | {f'{phase}{test}ATSCodes' for phase in ('Pre', 'Post')
     for test in ('FVL', 'DLCO', 'Pleth', 'FRC')}
# Only four zero bytes have been corroborated in the supplied profile.
# Preserve them as opaque bytes, without assigning Boolean semantics.
VISIT_OPAQUE_ZERO = {'StrapRawTest', 'StrapTGVTest', 'FOTTest'} | {
    f'ExportPending{target}{suffix}' for target in ('HIS', 'HL7', 'GDT', 'PDF')
    for suffix in ('', 'ThisSession')}


class Reader:
    def __init__(self, data, offset=0):
        self.data, self.offset = data, offset

    def take(self, size):
        if size < 0 or self.offset + size > len(self.data):
            raise CowFormatError(f'Registro truncado en byte {self.offset}')
        result = self.data[self.offset:self.offset+size]
        self.offset += size
        return result

    def text(self):
        end = self.data.find(b'\0', self.offset)
        if end < 0:
            raise CowFormatError(f'Texto sin terminador en byte {self.offset}')
        value = self.take(end-self.offset+1)[:-1]
        try:
            return value.decode('cp1252')
        except UnicodeDecodeError as exc:
            raise CowFormatError('Texto COW con codificación no reconocida') from exc

    def number(self, code):
        value = struct.unpack('<'+code, self.take(struct.calcsize('<'+code)))[0]
        if isinstance(value, float) and not math.isfinite(value):
            raise CowFormatError('Valor numérico no finito en registro COW')
        return value

    def date(self):
        # Eight little-endian uint16 values: Y, M, D, h, m, s, then two
        # reserved values. This is not Windows SYSTEMTIME (day-of-week absent).
        y, mo, d, h, mi, sec, r1, r2 = struct.unpack('<8H', self.take(16))
        if not any((y, mo, d, h, mi, sec, r1, r2)):
            return None
        try:
            return datetime(y, mo, d, h, mi, sec).isoformat(timespec='seconds')
        except ValueError as exc:
            raise CowFormatError('Fecha inválida en registro COW') from exc

    def record(self, name):
        fields = {}
        while self.offset < len(self.data):
            key = self.text()
            if key == "%LastField%":
                return fields
            if not key or key in fields:
                raise CowFormatError(f'Campo vacío o duplicado en {name}: {key!r}')
            if name == 'Patient':
                kind = ('text' if key in PATIENT_TEXT else 'date' if key == 'Birthday' else
                        'B' if key in ('RaceListID', 'SexListID') else 'I' if key == 'SyringeFlag' else None)
            elif name == 'PatVisit':
                kind = ('text' if key in VISIT_TEXT else 'f' if key in VISIT_FLOAT else
                        'B' if key in VISIT_BYTE else 'I' if key in VISIT_BOOL else
                        'date' if key in ('VisitDateTime', 'CalibrationDateTime') else None)
            elif name == 'PFProtocolStage':
                kind = ('text' if key in ('PFProtocolGUID', 'PFProtocolName', 'PFProtocolStageLabel', 'PFProtocolStageComment') else
                        'B' if key in ('PFProtocolStageIndex', 'PFProtocolStageBreaths') else
                        'd' if key == 'PFProtocolStageDosage' else None)
            else:
                kind = ('d' if key in FVL_DOUBLE else 'blob' if key in FVL_BLOBS else
                        'text' if key in ('PatientIDNum', 'FVLATSCodes') else
                        'date' if key in ('VisitDateTime', 'EffortTime') else
                        'B' if key in ('EffortTypeID', 'PFProtocolStageIndex') else
                        'I' if key in ('PatVisitID', 'EffortArtificial', 'EffortSelected', 'EffortRpLp', 'EffortManual') else None)
            if kind is None:
                if ((name == 'Patient' and key == 'OrderID') or
                        (name == 'PatVisit' and key in VISIT_EXTRA_TEXT)):
                    kind = 'text'
                elif ((name == 'PatVisit' and key in VISIT_OPAQUE_ZERO) or
                      (name == 'FVLData' and key == 'JaegerEffort')):
                    value = self.take(4)
                    if value != bytes(4):
                        raise CowFormatError(f'Campo adicional fuera del perfil validado: {name}.{key}')
                    fields[key] = value
                    continue
                else:
                    raise CowFormatError(f'Campo no reconocido en {name}: {key!r}, byte {self.offset}')
            fields[key] = (self.text() if kind == 'text' else self.date() if kind == 'date' else
                           self.take(self.number('I')) if kind == 'blob' else self.number(kind))
        raise CowFormatError(f"Registro {name} sin cierre")


@dataclass
class CowStudy:
    path: Path
    sha256: str
    version: str
    patient: dict
    visit: dict
    fvl_records: list
    sections: dict
    protocol_stages: list

    @property
    def curve_records(self):
        return [r for r in self.fvl_records if any(r.get(key) for key in FVL_BLOBS)]


def read_cow(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise CowFormatError('El archivo COW supera el límite de lectura de 64 MiB')
    return read_cow_bytes(path.read_bytes(), path)


def read_cow_bytes(data, path='<COW conservado>'):
    """Parse a preserved COW in memory, without creating temporary files."""
    path = Path(path)
    if len(data) > 64 * 1024 * 1024:
        raise CowFormatError('El archivo COW supera el límite de lectura de 64 MiB')
    if data.startswith(b"~Encrypted~\0"):
        from app.breeze_crypto import decrypt_cow
        payload, version = decrypt_cow(data), '6.4.1'
    else:
        header = Reader(data)
        if header.text().strip() != '510':
            raise CowFormatError('Firma COW no reconocida (se esperaba 510)')
        version = header.text()
        if not version.startswith('6.') or data[144:152] != b'Patient\0':
            raise CowFormatError('Cabecera COW no reconocida')
        payload = data[144:]
    if not payload.endswith((END, b'%LastTable%\0')):
        raise CowFormatError('Archivo COW incompleto: falta el cierre del último registro')
    records, counts = {}, Counter()
    reader = Reader(payload)
    while reader.offset < len(payload):
        name = reader.text()
        if name == '%LastTable%' and reader.offset == len(payload):
            break
        if not name or not name.isascii() or not name.isalnum():
            raise CowFormatError('Nombre de registro COW no reconocido')
        counts[name] += 1
        if name in ('Patient', 'PatVisit', 'FVLData', 'PFProtocolStage'):
            records.setdefault(name, []).append(reader.record(name))
        else:
            # Other test modalities and device calibration are inventoried only.
            end = payload.find(END, reader.offset)
            if end < 0:
                raise CowFormatError(f'Registro {name} sin cierre')
            reader.take(end + len(END) - reader.offset)
    if len(records.get('Patient', [])) != 1 or len(records.get('PatVisit', [])) != 1:
        raise CowFormatError('Se esperaba exactamente un paciente y una visita')
    patient, visit = records['Patient'][0], records['PatVisit'][0]
    if not patient.get('PatientIDNum') or not visit.get('VisitDateTime'):
        raise CowFormatError('Falta el identificador del paciente o la fecha de visita')
    if patient.get('PatientIDNum') != visit.get('PatientIDNum'):
        raise CowFormatError('Identificador del paciente inconsistente entre registros')
    for record in records.get('FVLData', []):
        if record.get('PatientIDNum') != patient.get('PatientIDNum') or record.get('VisitDateTime') != visit.get('VisitDateTime'):
            raise CowFormatError('Maniobra vinculada a otro paciente o visita')
    return CowStudy(path, hashlib.sha256(data).hexdigest(), version, patient, visit,
                    records.get('FVLData', []), dict(counts), records.get('PFProtocolStage', []))
