"""Session progress feedback: independent metrics, phases, age and live UI updates."""
from copy import deepcopy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QApplication
from app import db
from app.session_quality import session_feedback
from test_fvc_quality import curve_params


def row(fvc=4., fev1=3., phase='pre', artifact=None):
    params = curve_params(artifact)
    params.update(fvc=fvc, fev1=fev1)
    return dict(fvc=fvc, fev1=fev1, phase=phase, review_status='accepted', processing_json=json.dumps(params))


class SessionQualityTests(unittest.TestCase):
    def test_zero_one_two_and_three_produce_correct_progress(self):
        rows=[]
        self.assertEqual(session_feedback(rows,'pre',40)['state'],'empty')
        rows.append(row())
        self.assertFalse(session_feedback(rows,'pre',40)['ready'])
        rows.append(row(3.95,2.95))
        result=session_feedback(rows,'pre',40)
        self.assertFalse(result['ready'])
        self.assertIn('tercera',result['text'])
        rows.append(row(3.9,2.9))
        self.assertTrue(session_feedback(rows,'pre',40)['ready'])

    def test_difference_uses_two_best_and_exact_cutoff_not_last_two(self):
        rows=[row(4.,3.),row(3.85,2.85),row(2.,1.)]
        self.assertTrue(session_feedback(rows,'pre',40)['ready'])
        rows[1]=row(3.849,2.849)
        result=session_feedback(rows,'pre',40)
        self.assertFalse(result['ready'])
        self.assertIn('Mejorar repetibilidad',result['text'])

    def test_counts_and_repetition_are_separate_for_fev1_and_fvc(self):
        rows=[row(),row(3.95,2.95),row(3.9,2.9,artifact='cough')]
        result=session_feedback(rows,'pre',40)
        self.assertEqual(result['metrics']['fvc']['count'],3)
        self.assertEqual(result['metrics']['fev1']['count'],2)
        self.assertFalse(result['ready'])
        rows.append(row(3.85,2.85))
        self.assertTrue(session_feedback(rows,'pre',40)['ready'])

    def test_pre_post_and_excluded_rows_do_not_mix(self):
        rows=[row(),row(3.95,2.95),row(3.9,2.9),row(4.05,3.05,'post')]
        self.assertTrue(session_feedback(rows,'pre',40)['ready'])
        self.assertFalse(session_feedback(rows,'post',40)['ready'])
        rows[2]['review_status']='excluded'
        self.assertFalse(session_feedback(rows,'pre',40)['ready'])

    def test_child_limit_is_100ml_or_ten_percent_of_best_whichever_larger(self):
        rows=[row(2.,1.5),row(1.8,1.35),row(1.,1.)]
        result=session_feedback(rows,'pre',6)
        self.assertTrue(result['ready'])
        self.assertEqual(result['metrics']['fvc']['limit'],.2)
        self.assertAlmostEqual(result['metrics']['fev1']['limit'],.15)
        rows=[row(.8,.7),row(.7,.6),row(.6,.5)]
        self.assertTrue(session_feedback(rows,'pre',5)['ready'])

    def test_missing_age_original_quality_and_safety_limit_never_give_false_green(self):
        rows=[row(),row(3.95,2.95),row(3.9,2.9)]
        self.assertFalse(session_feedback(rows,'pre',None)['ready'])
        self.assertFalse(session_feedback(rows,'pre',-1)['ready'])
        rows[0]['processing_json']='{"origin":"breeze"}'
        self.assertEqual(session_feedback(rows,'pre',40)['state'],'unknown')
        attempts=[row(4+i*.3,3+i*.3) for i in range(8)]
        result=session_feedback(attempts,'pre',40)
        self.assertFalse(result['ready'])
        self.assertIn('evaluar si continuar',result['text'])


class SessionQualityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_banner_updates_after_capture_exclusion_and_phase_with_one_sound(self):
        from app.main_window import MainWindow
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'),patch.object(QThread,'start'):
            w=MainWindow()
            try:
                pid=db.create_patient('Prueba','Sesión',birth_date='1980-01-01',no_btps=True)
                sid=db.create_session(pid)
                for fvc,fev in ((4.,3.),(3.95,2.95)):
                    params=curve_params();params.update(fvc=fvc,fev1=fev)
                    db.save_maneuver(sid,params,[])
                w.current_patient_id=pid;w.load_study(sid)
                w.resize(1366,690);w.show();self.qt.processEvents()
                self.assertEqual(w.session_quality_label.property('state'),'progress')
                with patch('app.main_window.QApplication.beep') as beep:
                    params=curve_params();params.update(fvc=3.9,fev1=2.9)
                    w.measurement_finished([],params)
                    self.assertEqual(w.session_quality_label.property('state'),'ready')
                    beep.assert_called_once()
                    w.refresh_study_summary(notify=True)
                    beep.assert_called_once()
                rows=db.list_maneuvers_for_session(sid)
                w.maneuver_table.item(w._row_for_maneuver(rows[-1]['id']),2).setCheckState(Qt.Unchecked)
                self.assertEqual(w.session_quality_label.property('state'),'progress')
                w.set_study_phase('post')
                self.assertEqual(w.session_quality_label.property('state'),'empty')
                self.assertEqual(w.size().toTuple(),(1366,690))
            finally:w.close()
