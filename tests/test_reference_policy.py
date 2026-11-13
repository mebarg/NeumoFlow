"""Equation selection, independent numerical oracle, and historical continuity."""
import csv
import json
from zipfile import ZipFile, ZIP_DEFLATED
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import db, gli_global
from app.reference_policy import (GLOBAL, GLI2012, NONE, RECOMMENDED, LEGACY, SETTING,
                                  SUPPORTED, snapshot, reference_description, study_policy)
from app.reference_values import gli2012_for_maneuver
from app.study_transfer import import_studies, export_studies, read_package, validate, TransferError
from test_study_transfer import fixture


class ReferencePolicyTests(unittest.TestCase):
    def test_global_matches_independent_rspiro_oracle_for_both_sexes_and_five_ages(self):
        path=Path(__file__).parent/'fixtures/gli_2022_oracle.csv'
        with path.open() as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),30)
        for row in rows:
            for key,prefix in (('fvc','fvc'),('fev1','fev1'),('fev1_fvc','fev1fvc')):
                with self.subTest(sex=row['sex'],age=row['age'],height=row['height'],key=key):
                    result=gli_global.reference(row['sex'],float(row['age']),float(row['height']),key,float(row[prefix+'_measured']))
                    for field,suffix in (('predicted','pred'),('lln','lln'),('zscore','zscore'),('percent','pctpred')):
                        self.assertAlmostEqual(result[field],float(row[prefix+'_'+suffix+'_2022']),places=10)

    def test_global_age_boundaries_no_extrapolation_and_fractional_age(self):
        for age in (3.,3.125,45.23,95.):
            self.assertTrue(all(math.isfinite(v) for v in gli_global.reference('M',age,170.,'fvc',3.).values()))
        for age in (2.999,95.001,float('nan')):
            self.assertIsNone(gli_global.reference('M',age,170.,'fvc',3.))
        self.assertIsNone(gli_global.reference('M',45.,170.,'fef2575',3.))
        self.assertIsNone(gli_global.reference('',45.,170.,'fvc',3.))
        # Interpolation is between adjacent published spline rows, not an age jump.
        a=gli_global.lms('F',40.,165.,'fvc');b=gli_global.lms('F',40.25,165.,'fvc')
        middle=gli_global.lms('F',40.125,165.,'fvc')
        self.assertTrue(min(a[1],b[1]) <= middle[1] <= max(a[1],b[1]))

    def test_mixed_equations_use_complete_model_per_parameter_and_global_needs_no_ethnicity(self):
        s=fixture();s.session['source_json']=json.dumps({'origin':'native','reference_policy':snapshot(RECOMMENDED,'caucasian')})
        values=s.maneuvers[0]
        mixed=gli2012_for_maneuver(s.patient,s.session,values)
        legacy=gli2012_for_maneuver(s.patient,{**s.session,'source_json':None},values)
        self.assertNotEqual(mixed['fvc']['predicted'],legacy['fvc']['predicted'])
        self.assertEqual(mixed['fef2575'],legacy['fef2575'])
        self.assertEqual(mixed['fvc']['equation'],GLOBAL)
        s.session['source_json']=json.dumps({'reference_policy':snapshot(RECOMMENDED,'')})
        result=gli2012_for_maneuver(s.patient,s.session,values)
        self.assertIsNotNone(result['fvc'])
        self.assertIsNone(result['fef2575'])
        disabled={**RECOMMENDED,'fev1':NONE}
        s.session['source_json']=json.dumps({'reference_policy':snapshot(disabled,'caucasian')})
        self.assertIsNone(gli2012_for_maneuver(s.patient,s.session,values)['fev1'])

    def test_new_study_freezes_selection_and_ethnicity_and_legacy_is_not_rewritten(self):
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'):
            db.init_db();pid=db.create_patient('Synthetic','Reference',ethnicity='caucasian')
            old=db.create_session(pid,height_cm=165.)
            # A study from before this feature has no saved policy.
            with db.connect() as c:c.execute('UPDATE sessions SET source_json=NULL WHERE id=?',(old,))
            db.set_setting(SETTING,json.dumps(RECOMMENDED))
            new=db.create_session(pid,height_cm=165.)
            db.set_setting(SETTING,json.dumps({k:NONE for k in LEGACY}))
            latest=db.create_session(pid,height_cm=165.)
            self.assertEqual(study_policy(db.get_session(new))['parameters'],RECOMMENDED)
            self.assertEqual(study_policy(db.get_session(new))['ethnicity'],'caucasian')
            self.assertEqual(study_policy(db.get_session(latest))['parameters'],{k:NONE for k in LEGACY})
            self.assertIsNone(db.get_session(old)['source_json'])
            # Round-trip keeps the study policy, independent of destination settings.
            study=fixture();study.session['source_json']=db.get_session(new)['source_json']
            import_studies([study]);sid=next(r['id'] for r in db.list_sessions_for_patient(db.get_patient_by_dni('SYNTHETIC')['id']))
            package=Path(tmp)/'roundtrip.espiro';export_studies(package,[sid])
            with ZipFile(package) as archive:
                self.assertEqual(json.loads(archive.read('manifest.json'))['version'],3)
            restored=read_package(package)[0]
            self.assertEqual(restored.session,study.session)
            self.assertEqual(gli2012_for_maneuver(restored.patient,restored.session,restored.maneuvers[0]),
                             gli2012_for_maneuver(study.patient,study.session,study.maneuvers[0]))

    def test_version_one_packages_remain_readable(self):
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'):
            db.init_db();s=fixture();import_studies([s])
            pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            package=Path(tmp)/'new.espiro';export_studies(package,[sid])
            with ZipFile(package) as archive:
                entries={name:archive.read(name) for name in archive.namelist()}
            manifest=json.loads(entries['manifest.json']);manifest['version']=1
            entries['manifest.json']=json.dumps(manifest).encode()
            old=Path(tmp)/'old.espiro'
            with ZipFile(old,'w',ZIP_DEFLATED) as archive:
                for name,data in entries.items():archive.writestr(name,data)
            self.assertEqual(read_package(old)[0].session,s.session)

    def test_incompatible_parameter_and_unknown_version_rejected(self):
        for policy in ({'version':99,'parameters':RECOMMENDED,'ethnicity':''},
                       {'version':2,'parameters':{**RECOMMENDED,'fef2575':GLOBAL},'ethnicity':''}):
            s=fixture();s.session['source_json']=json.dumps({'reference_policy':policy})
            with self.assertRaises(TransferError):validate(s)

    def test_breeze_original_references_take_priority_over_native_configuration(self):
        s=fixture();s.session['source_json']=json.dumps({'origin':'breeze','predicted':{'fvc':4.},
            'standard_deviation':{'fvc':.5},'reference_policy':snapshot(RECOMMENDED,'caucasian')})
        result=gli2012_for_maneuver(s.patient,s.session,{'fvc':3.})
        self.assertEqual(result['fvc']['predicted'],4.)
        self.assertEqual(result['fvc']['zscore'],-2.)

    def test_selectors_persist_without_modifying_open_study_and_report_identifies_mixed_models(self):
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        qt=QApplication.instance() or QApplication([])
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'),patch.object(QThread,'start'):
            db.init_db();s=fixture();s.session['source_json']=json.dumps({'origin':'native','reference_policy':snapshot(RECOMMENDED,'caucasian')})
            import_studies([s]);pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            window=MainWindow()
            try:
                window.current_patient_id=pid;window.load_study(sid)
                before=[window.summary_table.item(r,1).text() for r in range(5)]
                for key,combo in window.reference_combos.items():
                    self.assertEqual([combo.itemData(i) for i in range(combo.count())],list(SUPPORTED[key]))
                window.set_reference_selection(RECOMMENDED)
                self.assertEqual(json.loads(db.get_setting(SETTING)),RECOMMENDED)
                window.reference_combos['fev1'].setCurrentIndex(window.reference_combos['fev1'].findData(NONE))
                self.assertEqual(json.loads(db.get_setting(SETTING))['fev1'],NONE)
                window.load_study(sid)
                self.assertEqual(before,[window.summary_table.item(r,1).text() for r in range(5)])
                payload=window._report_payload()
                self.assertEqual(payload['reference_label'],'Por parámetro')
                self.assertIn('FVC: GLI Global 2022',payload['reference_note'])
                self.assertIn('FEF 25–75: GLI-2012',payload['reference_note'])
                self.assertEqual(payload['summary_rows'][0][4],window.summary_table.item(0,4).text())
                if os.environ.get('REFERENCE_REPORT_IMAGE'):
                    from PySide6.QtGui import QImage, QPainter
                    from app.report import SpirometryReportRenderer
                    window.resize(1300,900);window.show();qt.processEvents()
                    window.stack.setCurrentWidget(window.summary_page);qt.processEvents()
                    payload=window._report_payload()
                    image=QImage(1190,1684,QImage.Format_ARGB32);image.fill(0xffffffff)
                    painter=QPainter(image)
                    SpirometryReportRenderer(payload).render(painter,image.rect());painter.end()
                    image.save(os.environ['REFERENCE_REPORT_IMAGE'])
                if os.environ.get('REFERENCE_UI_IMAGE'):
                    window.resize(1300,900);window.stack.setCurrentWidget(window.settings_page);window.show();qt.processEvents()
                    window.grab().save(os.environ['REFERENCE_UI_IMAGE'])
            finally:window.close()


if __name__=='__main__':unittest.main()
