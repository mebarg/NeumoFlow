"""Independent GLI calculator cases, compatibility formulas and frozen study policy."""
import csv
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app import db, gli_volumes, mvv_reference
from app.reference_policy import (FVC_PARAMETERS, RECOMMENDED, NONE, VOLUMES, FVC_REFERENCE,
    ITS, POLGAR, ZAPLETAL, snapshot, study_policy, configured_selection, SETTING)
from app.reference_values import respiratory_references, gli2012_for_maneuver
from app.study_transfer import import_studies, export_studies, read_package
from test_study_transfer import fixture


class RespiratoryReferenceTests(unittest.TestCase):
    def test_matches_147_independent_gli_web_calculator_cases(self):
        with (Path(__file__).parent/'fixtures/gli_volumes_2021_oracle.csv').open() as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),147)
        for row in rows:
            for key,prefix in [('svc','vc'),('ic','ic'),('erv','erv')]:
                with self.subTest(row=row,key=key):
                    ref=gli_volumes.reference(row['sex'],float(row['age']),float(row['height']),key,1.,'caucasian')
                    for field,suffix in [('predicted','predicted'),('lln','lln')]:
                        self.assertAlmostEqual(ref[field],float(row[prefix+'_'+suffix]),delta=.000501)
                    at_mean=gli_volumes.reference(row['sex'],float(row['age']),float(row['height']),key,ref['predicted'],'caucasian')
                    at_lln=gli_volumes.reference(row['sex'],float(row['age']),float(row['height']),key,ref['lln'],'caucasian')
                    self.assertAlmostEqual(at_mean['zscore'],0.,places=12)
                    self.assertAlmostEqual(at_lln['zscore'],-1.645,places=12)

    def test_published_supplement_examples_and_population_limits(self):
        for sex,height,expected in [('M',175.,[4.66,5.,5.37,4.89]),('F',165.,[3.63,3.84,4.06,3.51])]:
            for age,pred in zip([15.,20.,40.,60.],expected):
                self.assertAlmostEqual(gli_volumes.reference(sex,age,height,'svc',3.,'caucasian')['predicted'],pred,delta=.01)
        for age in [5.,40.125,80.]:
            self.assertIsNotNone(gli_volumes.reference('M',age,170.,'ic',2.,'caucasian'))
        for age in [4.999,80.001,None,float('nan')]:
            self.assertIsNone(gli_volumes.reference('M',age,170.,'svc',3.,'caucasian'))
        for ethnicity in ['',None,'african_american']:
            self.assertIsNone(gli_volumes.reference('F',40.,165.,'svc',3.,ethnicity))

    def test_mvv_exact_catalog_formulas_and_no_unverified_distribution(self):
        for eq,age,height in [(POLGAR,12.,150.),(ZAPLETAL,15.,160.),(ITS,40.,175.)]:
            for sex in ['M','F']:
                expected={POLGAR:1.276*height-99.5,ZAPLETAL:10**(-1.9178+3.0388*math.log10(height))/1000,
                    ITS:(3.39*height/2.54-1.26*age-21.4) if sex=='M' else (2.05*height/2.54-.57*age-5.5)}[eq]
                ref=mvv_reference.reference(eq,sex,age,height,100.)
                self.assertAlmostEqual(ref['predicted'],expected)
                self.assertAlmostEqual(ref['percent'],10000/expected)
                self.assertIsNone(ref['lln']);self.assertIsNone(ref['zscore'])
        for eq,age,height in [(POLGAR,18.,160.),(POLGAR,6.,160.),(ZAPLETAL,19.,170.),(ZAPLETAL,15.,190.),(ITS,17.,170.),(ITS,None,170.)]:
            self.assertIsNone(mvv_reference.reference(eq,'M',age,height,100.))

    def test_proxy_uses_saved_fvc_without_borrowing_its_distribution(self):
        s=fixture();selection={**RECOMMENDED,'svc':FVC_REFERENCE,'ic':VOLUMES,'erv':VOLUMES,'mvv':ITS}
        s.session['source_json']=json.dumps({'reference_policy':snapshot(selection,'caucasian')})
        ref=respiratory_references(s.patient,s.session,dict(svc=3.,ic=2.,erv=1.,mvv=100.))
        fvc=gli2012_for_maneuver(s.patient,s.session,dict(fvc=3.))['fvc']
        self.assertEqual(ref['svc']['predicted'],fvc['predicted'])
        self.assertEqual(ref['svc']['percent'],fvc['percent'])
        self.assertIsNone(ref['svc']['lln']);self.assertIsNone(ref['svc']['zscore'])
        self.assertIsNotNone(ref['ic']['zscore']);self.assertIsNone(ref['mvv']['zscore'])
        self.assertEqual(respiratory_references({**s.patient,'no_btps':1},s.session,dict(svc=3.)),{})

    def test_version_one_policy_and_settings_keep_auxiliary_parameters_disabled(self):
        original={k:RECOMMENDED[k] for k in FVC_PARAMETERS}
        s=fixture();s.session['source_json']=json.dumps({'reference_policy':{'version':1,'parameters':original,'ethnicity':'caucasian'}})
        before=s.session['source_json']
        self.assertEqual(study_policy(s.session)['parameters'],RECOMMENDED)
        self.assertEqual(configured_selection(json.dumps(original)),RECOMMENDED)
        self.assertEqual(s.session['source_json'],before)
        self.assertIsNone(respiratory_references(s.patient,s.session,dict(svc=3.))['svc'])

    def test_auxiliary_policy_roundtrip_and_configuration_do_not_rewrite_open_study(self):
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'):
            db.init_db();s=fixture();policy=snapshot({**RECOMMENDED,'svc':VOLUMES,'ic':VOLUMES,'erv':VOLUMES,'mvv':ITS},'caucasian')
            s.session['source_json']=json.dumps({'reference_policy':policy});import_studies([s])
            pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            db.set_setting(SETTING,json.dumps(RECOMMENDED))
            self.assertEqual(study_policy(db.get_session(sid)),policy)
            target=Path(tmp)/'refs.espiro';export_studies(target,[sid]);restored=read_package(target)[0]
            self.assertEqual(restored.session['source_json'],s.session['source_json'])
            values=dict(svc=3.,ic=2.,erv=1.,mvv=100.)
            self.assertEqual(respiratory_references(restored.patient,restored.session,values),respiratory_references(s.patient,s.session,values))

    def test_ui_summary_report_and_presets_keep_the_same_references(self):
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        from test_respiratory_measurements import svc_curve, curve_for
        from app.respiratory_measurements import analyze_curve
        qt=QApplication.instance() or QApplication([])
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'),patch.object(QThread,'start'):
            db.init_db();s=fixture();selection={**RECOMMENDED,'svc':VOLUMES,'ic':VOLUMES,'erv':VOLUMES,'mvv':ITS}
            s.session['source_json']=json.dumps({'reference_policy':snapshot(selection,'caucasian')})
            import_studies([s]);pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            curve,marker=svc_curve();svc=analyze_curve(curve,'svc',marker);svc['svc']=1.
            mvv=analyze_curve(curve_for([(.5,-2.),(.5,2.)]*12),'mvv',0.)
            for kind,result in [('svc',svc),('mvv',mvv)]:
                mid=db.save_respiratory_measurement(sid,kind,'pre',result,[]);db.include_respiratory_measurement(mid,True)
            w=MainWindow()
            try:
                w.current_patient_id=pid;w.load_study(sid);w.fvc_red_values.setChecked(True);w.refresh_summary_page()
                refs=respiratory_references(s.patient,s.session,dict(svc=1.,mvv=mvv['mvv']))
                self.assertEqual(w.svc_page.table.item(0,8).text(),f"{refs['svc']['predicted']:.2f}")
                self.assertEqual(w.svc_page.table.item(0,10).text(),f"{refs['svc']['zscore']:.2f}")
                self.assertEqual(w.mvv_page.table.item(0,9).text(),'–')
                rows={w.summary_table.item(i,0).text():i for i in range(w.summary_table.rowCount())}
                row=rows['SVC (L)'];mvrow=rows['MVV (L/min)']
                self.assertEqual(w.summary_table.item(row,1).text(),f"{refs['svc']['predicted']:.2f}")
                self.assertEqual(w.summary_table.item(row,4).text(),w.svc_page.table.item(0,10).text())
                self.assertEqual(w.summary_table.item(row,2).foreground().color().name(),'#b91c1c')
                self.assertEqual(w.summary_table.item(mvrow,4).text(),'-')
                self.assertEqual(w.summary_table.item(mvrow,2).foreground().color().name(),'#1f2937')
                payload=w._report_payload()
                self.assertEqual(payload['summary_rows'][row][4],w.summary_table.item(row,4).text())
                self.assertIn('SVC: GLI 2021',payload['reference_note'])
                self.assertIn('sin LIN/z verificados',payload['reference_note'])
                w.set_reference_selection(selection)
                w.set_reference_selection({k:RECOMMENDED[k] for k in FVC_PARAMETERS})
                self.assertEqual(json.loads(db.get_setting(SETTING))['svc'],VOLUMES)
                self.assertEqual(study_policy(db.get_session(sid))['parameters'],selection)
            finally:w.close()
