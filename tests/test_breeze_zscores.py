"""Reference calculation and display with synthetic data only."""
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import db
from app.breeze_references import references, reference_records, REFERENCE_NOTE
from app.reference_values import gli2012_for_maneuver
from app.study_transfer import read_breeze, import_studies, export_studies, read_package, validate, TransferError
from test_study_transfer import cow_bytes, fixture


def clinical_cow():
    raw = cow_bytes().replace(b'SyringeFlag\0'+struct.pack('<I', 1),
                              b'SyringeFlag\0'+struct.pack('<I', 0))
    dt = struct.pack('<8H', 2024, 6, 17, 10, 23, 45, 0, 0)
    for kind, values in ((1, (4., 3., 80., 2., 6.)), (5, (.5, .4, 5., .2, 0.))):
        raw += (b'FVLData\0PatientIDNum\0SYNTHETIC\0VisitDateTime\0'+dt+
                b'EffortTypeID\0'+bytes([kind]))
        for name, value in zip(('FVC', 'FEV1', 'FEV1FVC', 'FEF2575', 'FEFMax'), values):
            raw += name.encode()+b'\0'+struct.pack('<d', value)
        raw += b'%LastField%\0'
    return raw


class BreezeZscoreTests(unittest.TestCase):
    def source(self):
        return {'origin': 'breeze', 'predicted': {'fvc': 4., 'fev1_fvc': .8},
                'standard_deviation': {'fvc': .5, 'fev1_fvc': .05}}

    def test_signed_residual_ratio_units_and_no_inferred_lln(self):
        means, sd = reference_records([{'EffortTypeID': 1, 'FEV1FVC': 80.},
                                      {'EffortTypeID': 5, 'FEV1FVC': 5.}])
        source = self.source();source['predicted'].update(means);source['standard_deviation'].update(sd)
        r = references(json.dumps(source), {'fvc': 3., 'fev1_fvc': .7})
        self.assertEqual(r['fvc']['zscore'], -2.)
        self.assertAlmostEqual(r['fev1_fvc']['zscore'], -2.)
        self.assertIsNone(r['fvc']['lln'])
        self.assertEqual(references(json.dumps(source), {'fvc': 4.})['fvc']['zscore'], 0.)
        self.assertEqual(references(json.dumps(source), {'fvc': 5.})['fvc']['zscore'], 2.)

    def test_missing_invalid_sd_missing_measurement_and_syringe_stay_blank(self):
        for sd in (None, 0., -.5, float('nan'), float('inf')):
            s=self.source();s['standard_deviation']['fvc']=sd
            self.assertIsNone(references(json.dumps(s), {'fvc': 3.})['fvc']['zscore'])
        s=self.source()
        self.assertIsNone(references(json.dumps(s), {})['fvc']['zscore'])
        self.assertIsNone(references(json.dumps(s), {'fvc': 3.}, no_btps=True)['fvc']['zscore'])
        s['patient']={'SyringeFlag': 1}
        self.assertIsNone(references(json.dumps(s), {'fvc': 3.})['fvc']['zscore'])
        self.assertEqual(reference_records([{'EffortTypeID':1,'FVC':4.}]*2)[0], {})

    def test_new_and_existing_imports_use_identical_preserved_references(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.cow';path.write_bytes(clinical_cow())
            study=read_breeze(path);source=json.loads(study.session['source_json'])
            self.assertEqual(source['standard_deviation']['fev1_fvc'], .05)
            new=gli2012_for_maneuver(study.patient, study.session, {'fvc':3.,'fev1_fvc':.7})
            source.pop('standard_deviation');source.pop('zscore_method')
            study.session['source_json']=json.dumps(source)
            old=gli2012_for_maneuver(study.patient, study.session, {'fvc':3.,'fev1_fvc':.7})
            self.assertEqual(new, old)
            self.assertEqual(path.read_bytes(), clinical_cow())
            source['sha256']='0'*64
            self.assertIsNone(references(json.dumps(source), {'fvc':3.})['fvc']['zscore'])

    def test_roundtrip_preserves_sd_and_rejects_invalid_metadata(self):
        with TemporaryDirectory() as tmp, patch.object(db, 'DB_PATH', Path(tmp)/'test.db'):
            db.init_db();p=Path(tmp)/'test.cow';p.write_bytes(clinical_cow());s=read_breeze(p)
            import_studies([s]);pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            out=Path(tmp)/'out.espiro';export_studies(out,[sid]);restored=read_package(out)[0]
            self.assertEqual(restored.session, s.session)
            self.assertEqual(restored.maneuvers, s.maneuvers)
            source=json.loads(s.session['source_json']);source['standard_deviation']['fvc']=-.5
            s.session['source_json']=json.dumps(source)
            with self.assertRaises(TransferError):validate(s)

    def test_display_and_report_use_same_pre_post_scores(self):
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage, QPainter
        from app.main_window import MainWindow
        from app.report import SpirometryReportRenderer
        qt=QApplication.instance() or QApplication([])
        with TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.db'), patch.object(QThread,'start'):
            db.init_db();s=fixture();s.session['source_json']=json.dumps(self.source())
            s.maneuvers[0].update(fvc=3.,fev1=2.1,fev1_fvc=.7)
            post=copy.deepcopy(s.maneuvers[0]);post.update(phase='post',fvc=4.5,fev1=3.6,fev1_fvc=.8)
            s.maneuvers.append(post);import_studies([s]);pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            window=MainWindow()
            try:
                window.current_patient_id=pid;window.load_study(sid)
                self.assertEqual(window.summary_table.item(0,4).text(), '-2.00')
                self.assertEqual(window.summary_table.item(0,7).text(), '1.00')
                self.assertEqual(window.summary_table.item(1,4).text(), '-')
                for row in range(window.maneuver_table.rowCount()):
                    if window.maneuver_table.item(row,1).text()=='Predicho':
                        self.assertEqual(window.maneuver_table.item(row,9).text(), '-')
                payload=window._report_payload()
                self.assertEqual(payload['summary_rows'][0][4], '-2.00')
                self.assertEqual(payload['reference_label'], 'Breeze original')
                self.assertEqual(payload['zscore_threshold_label'], 'z = −1.645')
                self.assertEqual(payload['reference_note'], REFERENCE_NOTE)
                self.assertFalse(window.summary_reference_note.isHidden())
                image=QImage(1190,1684,QImage.Format_ARGB32);image.fill(0xffffffff)
                painter=QPainter(image)
                SpirometryReportRenderer(payload).render(painter,image.rect())
                painter.end()
                if os.environ.get('ZSCORE_REVIEW_IMAGE'):
                    image.save(os.environ['ZSCORE_REVIEW_IMAGE'])
            finally:
                window.close()
