"""POST is a persistent, shared acquisition stage; previous PRE remains reviewable."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PySide6.QtCore import QThread,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app import db
from app.main_window import MainWindow
from app.study_transfer import export_studies,read_package,import_studies


class StudyPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.qt=QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(db,'DB_PATH',Path(self.tmp.name)/'study.db');p.start();self.addCleanup(p.stop)
        p=patch.object(QThread,'start');p.start();self.addCleanup(p.stop)
        db.init_db();self.pid=db.create_patient('Paciente','Etapas',dni='PHASE',sex='F',birth_date='1980-01-01',ethnicity='caucasian')
        self.sid=db.create_session(self.pid,height_cm=165.)
        self.mid=db.save_maneuver(self.sid,dict(fvc=3.,fev1=2.5,fev1_fvc=2.5/3,pef=5.,vol_curve=[(0.,0.,0.),(1.,3.,5.)]),[])
        self.w=MainWindow();self.addCleanup(self.w.close);self.w.current_patient_id=self.pid;self.w.load_study(self.sid)

    def test_post_disables_pre_in_all_views_and_preserves_pre_review(self):
        w=self.w;before=json.loads(db.get_session(self.sid)['source_json'])
        self.assertEqual(w.current_phase,'pre');self.assertFalse(db.post_phase_started(self.sid))
        # Programmatic changes during a capture cannot change its stage.
        w.capture_active=True;w.phase_selector.setCurrentIndex(w.phase_selector.findData('post'))
        self.assertEqual(w.current_phase,'pre');self.assertFalse(db.post_phase_started(self.sid));w.capture_active=False
        w.phase_selector.setCurrentIndex(w.phase_selector.findData('post'))
        self.assertTrue(db.post_phase_started(self.sid));self.assertEqual(w.current_phase,'post')
        w.phase_selector.setCurrentIndex(w.phase_selector.findData('pre'));self.assertEqual(w.current_phase,'post')
        QTest.keyClick(w.phase_selector,Qt.Key_Left);self.assertEqual(w.phase_selector.currentData(),'post')
        for page in (w.svc_page,w.mvv_page):
            self.assertFalse(page.phase.model().item(page.phase.findData('pre')).isEnabled())
            page.phase.setCurrentIndex(page.phase.findData('pre'))
            self.assertEqual(page.phase.currentData(),'post');self.assertEqual(w.current_phase,'post')
        after=json.loads(db.get_session(self.sid)['source_json']);self.assertEqual(after.pop('workflow'),{'post_started':True})
        self.assertEqual(before,after)
        row=w._row_for_maneuver(self.mid);self.assertFalse(w.maneuver_table.isRowHidden(row))
        w.maneuver_table.item(row,2).setCheckState(Qt.Unchecked)
        self.assertEqual(db.list_maneuvers_for_session(self.sid)[0]['review_status'],'excluded')
        w.load_study(self.sid);self.assertEqual(w.current_phase,'post')

    def test_switch_from_svc_or_mvv_is_shared_and_a_new_study_starts_pre(self):
        for kind in ('svc','mvv'):
            sid=db.create_session(self.pid,height_cm=165.);self.w.load_study(sid)
            self.assertEqual(self.w.phase_selector.currentData(),'pre')
            page=getattr(self.w,kind+'_page');page.phase.setCurrentIndex(page.phase.findData('post'))
            self.assertEqual(self.w.phase_selector.currentData(),'post')
            self.assertEqual(self.w.svc_page.phase.currentData(),'post')
            self.assertEqual(self.w.mvv_page.phase.currentData(),'post')
            self.assertTrue(db.post_phase_started(sid))

    def test_old_post_results_even_excluded_lock_pre_and_deleting_them_does_not_unlock(self):
        post=db.save_maneuver(self.sid,dict(fvc=3.,fev1=2.5),[],review_status='excluded',phase='post')
        # A later PRE row from an old/imported file must not reset the acquisition stage.
        db.save_maneuver(self.sid,dict(fvc=3.,fev1=2.5),[],phase='pre')
        self.w.load_study(self.sid);self.assertEqual(self.w.current_phase,'post')
        db.delete_maneuver(post);self.w.load_study(self.sid)
        self.assertEqual(self.w.phase_selector.currentData(),'post')
        other=db.create_session(self.pid,height_cm=165.)
        mid=db.save_respiratory_measurement(other,'mvv','post',dict(measurement_type='mvv',mvv=None),[])
        self.w.load_study(other);self.assertEqual(self.w.current_phase,'post')
        db.delete_respiratory_measurement(mid);self.assertTrue(db.post_phase_started(other))

    def test_stage_survives_export_import_without_a_post_maneuver(self):
        self.w.set_study_phase('post')
        target=Path(self.tmp.name)/'phase.espiro';export_studies(target,[self.sid]);studies=read_package(target)
        with patch.object(db,'DB_PATH',Path(self.tmp.name)/'destination.db'):
            db.init_db();import_studies(studies);pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            self.assertTrue(db.post_phase_started(sid))
            self.assertTrue(all(m['phase']=='pre' for m in db.list_maneuvers_for_session(sid)))

    def test_capture_start_rechecks_post_stage_before_saving_a_new_fvc(self):
        w=self.w;w.set_study_phase('post');w.current_phase='pre';w.device_ready=True
        with patch.object(w.worker,'start_capture'),patch.object(w,'measurement_environment',return_value={}):
            w.start_maneuver();self.assertEqual(w.current_phase,'post')
            w.measurement_finished([],dict(fvc=3.,fev1=2.5,fev1_fvc=2.5/3,pef=5.,vol_curve=[(0.,0.,0.),(1.,3.,5.)]))
            w.capture_closed()
        self.assertEqual(db.list_maneuvers_for_session(self.sid)[-1]['phase'],'post')
