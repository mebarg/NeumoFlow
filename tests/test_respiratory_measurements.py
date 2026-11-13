import copy
import json
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

from app import db
from app.respiratory_measurements import analyze_curve, analyze_samples, acquisition_curve, tidal_baseline, summary
from app.cpfs_signal import FlowSample
from app.study_transfer import import_studies, export_studies, read_package, validate, TransferError
from test_study_transfer import fixture


def curve_for(parts):
    curve=[(0.,0.,0.)];vol=0.
    for seconds,flow in parts:
        for _ in range(round(seconds*100)):
            vol+=flow*.01;curve.append((len(curve)*.01,vol,flow))
    return curve


def svc_curve(drift=0.,ivc=False):
    # Four quiet breaths, plus the beginning of an inspiration to close the last expiration.
    baseline=[]
    for i in range(4):baseline += [(1.,-.5),(1.,.5+drift)]
    baseline += [(.2,-.5)]
    marker=8.2
    # Start the maximal excursion from the tidal end-expiratory level (0 L).
    effort=[(2.,1.05),(1.2,0.),(4.,-1.),(1.2,0.)] if ivc else [(2.,-.95),(4.,1.),(1.2,0.)]
    return curve_for(baseline+effort),marker


class RespiratoryCalculationTests(unittest.TestCase):
    def test_svc_expiratory_and_inspiratory_with_stable_tidal_baseline(self):
        for ivc in (False,True):
            curve,marker=svc_curve(ivc=ivc)
            r=analyze_curve(curve,'svc',marker,'ivc' if ivc else 'evc')
            self.assertTrue(r['baseline_stable'])
            self.assertGreaterEqual(r['tidal_breaths'],3)
            self.assertAlmostEqual(r['svc'],4.,places=9)
            self.assertAlmostEqual(r['ic'],2.,places=9)
            self.assertAlmostEqual(r['erv'],2.,places=9)
            self.assertAlmostEqual(r['vt'],.5,places=9)
            self.assertTrue(r['plateau'])
            self.assertEqual(r['acq_curve'],curve)

    def test_unstable_baseline_suppresses_ic_and_erv_but_not_svc(self):
        curve,marker=svc_curve(drift=.1)
        r=analyze_curve(curve,'svc',marker)
        self.assertFalse(r['baseline_stable'])
        self.assertIsNone(r['ic']);self.assertIsNone(r['erv'])
        self.assertAlmostEqual(r['svc'],4.,places=9)
        self.assertTrue(r['warnings'])

    def test_marker_and_correct_direction_required(self):
        curve,marker=svc_curve()
        self.assertIsNone(analyze_curve(curve,'svc')['svc'])
        self.assertIsNone(analyze_curve(curve_for([(10.,0.)]),'svc',2.)['svc'])
        self.assertIsNone(analyze_curve(curve_for([(2.,-1.)]),'svc',0.,'evc')['svc'])

    def test_mvv_uses_expired_volume_once_and_excludes_preparation(self):
        # 12 complete cycles at 60/min: 1 L exhaled/cycle => 60 L/min, not 120.
        curve=curve_for([(3.,5.)]+[(.5,-2.),(.5,2.)]*12)
        r=analyze_curve(curve,'mvv',3.)
        self.assertAlmostEqual(r['expired_volume'],12.)
        self.assertAlmostEqual(r['interval_seconds'],12.)
        self.assertAlmostEqual(r['mvv'],60.)
        self.assertAlmostEqual(r['vt'],1.)
        self.assertAlmostEqual(r['frequency'],60.)
        short=analyze_curve(curve_for([(.5,-2.),(.5,2.)]*8),'mvv',0.)
        self.assertIsNone(short['mvv']);self.assertAlmostEqual(short['mvv_estimate'],60.)
        self.assertTrue(short['warnings'])
        fifteen=analyze_curve(curve_for([(.5,-2.),(.5,2.)]*18),'mvv',0.,target_seconds=15)
        self.assertAlmostEqual(fifteen['interval_seconds'],15.)
        self.assertAlmostEqual(fifteen['mvv'],60.)

    def test_missing_cycles_and_invalid_or_discontinuous_data(self):
        self.assertIsNone(analyze_curve(curve_for([(12.,1.)]),'mvv',0.)['mvv'])
        samples=[FlowSample(0.,0,0,0,1.),FlowSample(.03,1,0,0,1.)]
        with self.assertRaises(ValueError):acquisition_curve(samples)
        samples[1]=FlowSample(.01,1,0,0,float('nan'))
        with self.assertRaises(ValueError):acquisition_curve(samples)

    def test_summary_largest_vc_and_mvv_average_ic_and_phase_separation(self):
        records=[]
        for phase,svc,ic,include in [('pre',4.,2.,1),('pre',3.8,1.8,1),('post',5.,2.5,1),('pre',9.,4.,0)]:
            records.append(dict(kind='svc',phase=phase,included=include,result={'svc':svc,'ic':ic,'erv':svc-ic,'vt':.5}))
        result=summary(records)
        self.assertEqual(result[('pre','svc')],4.)
        self.assertAlmostEqual(result[('pre','ic')],1.9)
        self.assertEqual(result[('post','svc')],5.)


class RespiratoryPersistenceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([])

    def test_store_reopen_select_export_replace_and_rollback_preserve_separate_measurements(self):
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'):
            db.init_db();s=fixture();import_studies([s]);pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            curve,marker=svc_curve();result=json.loads(json.dumps(analyze_curve(curve,'svc',marker)))
            mid=db.save_respiratory_measurement(sid,'svc','pre',result,[])
            self.assertFalse(db.list_respiratory_measurements(sid)[0]['included'])
            db.include_respiratory_measurement(mid,True)
            before=db.list_respiratory_measurements(sid)[0]
            self.assertEqual(before['result'],result)
            self.assertEqual(len(db.list_maneuvers_for_session(sid)),1)
            archive=Path(tmp)/'test.espiro';export_studies(archive,[sid]);imported=read_package(archive)[0]
            self.assertEqual(json.loads(imported.respiratory[0]['result_json']),result)
            self.assertEqual(import_studies([imported])['skipped'],1)
            self.assertEqual(import_studies([imported],replace=True)['replaced'],1)
            new_sid=db.list_sessions_for_patient(pid)[0]['id']
            self.assertEqual(len(db.list_respiratory_measurements(new_sid)),1)
            self.assertEqual(db.list_respiratory_measurements(new_sid)[0]['result'],result)
            with db.connect() as c:
                c.execute("CREATE TRIGGER fail_respiratory BEFORE INSERT ON respiratory_measurements BEGIN SELECT RAISE(ABORT,'test failure'); END")
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):import_studies([imported],replace=True)
            self.assertEqual(db.list_respiratory_measurements(new_sid)[0]['result'],result)
            self.assertEqual(len(db.list_maneuvers_for_session(new_sid)),1)
            bad=copy.deepcopy(imported)
            r=json.loads(bad.respiratory[0]['result_json']);r['acq_curve']=[[0.,0.,0.],[0.,1.,1.]]
            bad.respiratory[0]['result_json']=json.dumps(r)
            with self.assertRaises(TransferError):validate(bad)

    def test_tabs_capture_routing_review_summary_and_keyboard(self):
        from PySide6.QtCore import QThread,Qt
        from PySide6.QtTest import QTest
        from app.main_window import MainWindow
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'),patch.object(QThread,'start'):
            window=MainWindow()
            try:
                pid=db.create_patient('Synthetic','Respiratory',dni='TEST',birth_date='1980-01-01',sex='M',ethnicity='caucasian')
                sid=db.create_session(pid,height_cm=175.)
                window.current_patient_id=pid;window.load_study(sid)
                window.resize(1300,900);window.show();self.qt.processEvents()
                window.svc_tab.click();self.qt.processEvents()
                self.assertIs(window.stack.currentWidget(),window.svc_page)
                self.assertIs(window.study_tabs.parentWidget(),window.svc_page)
                worker=window.worker;window.device_ready=True;window.svc_page.sync()
                with patch.object(worker,'start_capture') as start,patch.object(worker,'stop') as stop,patch.object(worker,'mark_effort') as mark, \
                     patch.object(window,'measurement_environment',return_value={}):
                    QTest.keyClick(window,Qt.Key_Space);self.qt.processEvents()
                    self.assertTrue(window.capture_active);self.assertIs(window._capture_page,window.svc_page)
                    start.assert_called_once_with({},mode='svc',direction='evc',target_seconds=12)
                    self.assertFalse(window.mvv_tab.isEnabled())
                    window.svc_page.mark.click();mark.assert_called_once()
                    QTest.keyClick(window,Qt.Key_Space);stop.assert_called_once()
                    curve,marker=svc_curve();result=analyze_curve(curve,'svc',marker)
                    window._device_requested=True;window._device_study_id=sid
                    window.study_capture_finished([],result);window.capture_closed()
                self.assertEqual(len(db.list_maneuvers_for_session(sid)),0)
                self.assertEqual(window.svc_page.table.rowCount(),1)
                window.svc_page.table.item(0,2).setCheckState(Qt.Checked)
                window.show_summary();self.qt.processEvents()
                labels=[window.summary_table.item(i,0).text() for i in range(window.summary_table.rowCount())]
                self.assertIn('SVC (L)',labels)
                row=labels.index('SVC (L)');self.assertEqual(window.summary_table.item(row,2).text(),'4.00')
                payload=window._report_payload()
                self.assertEqual(payload['summary_rows'][row][2],'4.00')
                self.assertEqual(len(payload['respiratory_charts']),1)
                self.assertEqual(payload['respiratory_charts'][0]['kind'],'svc')
                window.mvv_tab.click();self.assertIs(window.stack.currentWidget(),window.mvv_page)
                window.mvv_page.option.setCurrentIndex(1)
                window.device_ready=True;window.mvv_page.sync()
                with patch.object(worker,'start_capture') as start,patch.object(window,'measurement_environment',return_value={}):
                    window.start_additional_capture(window.mvv_page)
                    start.assert_called_once_with({},mode='mvv',direction='evc',target_seconds=15)
                window.capture_closed()
                window.svc_page.load();self.assertEqual(window.svc_page.table.rowCount(),1)
                if os.environ.get('RESPIRATORY_UI_IMAGE'):
                    window.svc_tab.click();self.qt.processEvents();window.grab().save(os.environ['RESPIRATORY_UI_IMAGE'])
            finally:window.close()


class RespiratoryWorkerTests(unittest.TestCase):
    def test_mvv_mark_is_sample_clock_based_and_stops_at_exact_interval(self):
        from collections import deque
        from app import spirometry as sp
        from app.cpfs_environment import measurement_environment
        from app.workers import StudySessionWorker
        worker=StudySessionWorker()
        class Session:
            def __init__(self):self.samples=deque();self.count=0
            def feed(self,chunk):
                for _ in range(37):
                    i=self.count
                    sample=FlowSample(i*.01,i%128,0,0,-2. if i%100<50 else 2.)
                    sample.sample_index=i
                    self.samples.append(sample);self.count+=1
        class Device:
            def __init__(self):self._cpfs_session=Session()
            def read(self,*args,**kwargs):
                if self._cpfs_session.count>3000:raise AssertionError('No se detuvo MVV')
                return b'x'
        device=Device();captures=[];marked=[];errors=[]
        worker.ready.connect(lambda:worker.start_capture(measurement_environment('syringe'),mode='mvv',target_seconds=12))
        worker.capture_started.connect(worker.mark_effort)
        worker.effort_marked.connect(marked.append)
        def finish(samples,params):captures.append((samples,params));worker.shutdown()
        worker.finished.connect(finish);worker.failed.connect(errors.append)
        with patch.object(sp,'open_device',return_value=device),patch.object(sp,'inicializar',return_value=0), \
             patch.object(sp,'send_bytes'),patch.object(sp.usb.util,'release_interface'),patch.object(sp.usb.util,'dispose_resources'):
            worker.run()
        self.assertEqual(errors,[])
        self.assertEqual(marked,[.37])
        self.assertEqual(len(captures[0][0]),1237)
        self.assertAlmostEqual(captures[0][1]['interval_seconds'],12.)
        self.assertAlmostEqual(captures[0][1]['mvv'],60.)
        self.assertEqual(captures[0][1]['marker_time'],.37)
