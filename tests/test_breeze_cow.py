"""Synthetic tagged records; no patient export is included in fixtures."""
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from app.breeze_cow import CowFormatError, END, read_cow


def text(value):
    return value.encode('cp1252') + b'\0'


def field(name, value):
    return text(name) + value


def record(name, *fields):
    return text(name) + b''.join(fields) + END


def source(patient_id='SYNTHETIC', blob=b'opaque\0'+END+b'FVC\0payload'):
    date = struct.pack('<8H', 2024, 6, 17, 10, 23, 45, 0, 0)
    return ((b'  510\0'+text('6.4.1')).ljust(144, b'\0') +
        record('Patient', field('PatientIDNum', text('SYNTHETIC')),
               field('PatientLastName', text('Muñoz')), field('PatientFirstName', text('Prueba')),
               field('SexListID', b'\x02'), field('Birthday', struct.pack('<8H', 1980, 2, 15, 0, 0, 0, 0, 0))) +
        record('PatVisit', field('PatientIDNum', text(patient_id)), field('VisitDateTime', date),
               field('Height', struct.pack('<f', 165.)), field('PFConsult', text('FVC: texto original.')))+
        record('PFProtocolStage', field('PFProtocolStageIndex', b'\x03'),
               field('PFProtocolStageLabel', text('Post'))) +
        record('FVLData', field('PatientIDNum', text('SYNTHETIC')), field('VisitDateTime', date),
               field('EffortTypeID', b'\x00'), field('PFProtocolStageIndex', b'\x03'),
               field('FVC', struct.pack('<d', 3.1234567)), field('FEV1FVC', struct.pack('<d', 79.35)),
               field('FVLExpiratorySourceData', struct.pack('<I', len(blob)) + blob)))


class BreezeCowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'synthetic.cow'

    def test_reads_exact_values_and_does_not_parse_tags_inside_curve_blob(self):
        raw = source()
        self.path.write_bytes(raw)
        result = read_cow(self.path)
        self.assertEqual(result.version, '6.4.1')
        self.assertEqual(result.patient['PatientLastName'], 'Muñoz')
        self.assertEqual(result.patient['Birthday'], '1980-02-15T00:00:00')
        self.assertEqual(result.visit['VisitDateTime'], '2024-06-17T10:23:45')
        self.assertEqual(result.visit['Height'], 165.)
        self.assertEqual(result.fvl_records[0]['FVC'], 3.1234567)
        self.assertEqual(result.fvl_records[0]['FEV1FVC'], 79.35)
        self.assertEqual(result.protocol_stages[0]['PFProtocolStageLabel'], 'Post')
        self.assertEqual(len(result.curve_records), 1)
        self.assertEqual(result.fvl_records[0]['FVLExpiratorySourceData'], b'opaque\0'+END+b'FVC\0payload')
        self.assertEqual(self.path.read_bytes(), raw)

    def test_truncated_encrypted_export_gets_specific_error(self):
        self.path.write_bytes(b'~Encrypted~\x00510\0\0\x006.4.1\0encrypted')
        with self.assertRaisesRegex(CowFormatError, 'COW cifrado truncado'):
            read_cow(self.path)

    def test_rejects_truncation_mismatched_patient_and_nonfinite_results(self):
        for raw in (source()[:-4], source('OTHER'),
                    source().replace(struct.pack('<d', 3.1234567), struct.pack('<d', float('nan')))):
            with self.subTest(size=len(raw)):
                self.path.write_bytes(raw)
                with self.assertRaises(CowFormatError):
                    read_cow(self.path)

    def test_rejects_unknown_fields_instead_of_guessing_their_binary_type(self):
        raw = source().replace(text('Height'), text('UnexpectedField'))
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(CowFormatError, 'Campo no reconocido'):
            read_cow(self.path)
