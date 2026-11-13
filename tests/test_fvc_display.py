"""Display-only origin recovery; source blobs and scalar results remain exact."""
import base64
import copy
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app.fvc_display import volume_time_curve
from test_breeze_source import blob


def source(start):
    encoded=base64.b64encode(blob([
        (1,200,0,(round(start*200),round((start+1)*200),round((start+2)*200))),
        (2,1000,0,(-1200,800,1800)),(3,1000,0,(0,2000,0))],markers=(),extra=b'')).decode()
    return dict(origin='breeze',acq_curve=[[start-1.,1.2,-1.],[start,0.,0.],[start+1,2.,2.],[start+2,3.,0.]],
                original_curves={'FVLExpiratorySourceData':encoded},original_results={'ExpTime':1.5,'ToFEFMax':.5})


class FvcDisplayTests(unittest.TestCase):
    def test_imported_offsets_restore_same_verified_origin_and_only_expiratory_branch(self):
        for start in (0.,3.65,19.65):
            processing=source(start);before=copy.deepcopy(processing)
            result=volume_time_curve(processing)
            self.assertAlmostEqual(result[0][0],0.)
            self.assertAlmostEqual(result[0][1],1.)  # Existing segment interpolated at exported zero, not a new BEV.
            self.assertAlmostEqual(result[-1][0],1.5)
            self.assertAlmostEqual(result[-1][1],3.)
            self.assertEqual(processing,before)

    def test_missing_or_conflicting_exported_timings_only_align_first_sample(self):
        for metadata in ({},{'ExpTime':1.5,'ToFEFMax':.1},{'ExpTime':-1,'ToFEFMax':.5}):
            processing=source(20.);processing['original_results']=metadata
            self.assertEqual(volume_time_curve(processing),[[0.,0.,0.],[1.,2.,2.],[2.,3.,0.]])
        for raw in (None,'not base64',base64.b64encode(b'invalid source').decode()):
            processing=source(20.);processing['original_curves']['FVLExpiratorySourceData']=raw
            self.assertEqual(volume_time_curve(processing),[])

    def test_native_expiratory_curve_is_used_instead_of_preparatory_acquisition(self):
        processing=dict(acq_curve=[[0.,3.,-1.],[4.,0.,0.],[5.,3.,3.]],vol_curve=[[0.,0.,0.],[1.,3.,3.]])
        before=copy.deepcopy(processing)
        self.assertEqual(volume_time_curve(processing),processing['vol_curve'])
        self.assertEqual(processing,before)

    def test_existing_imports_main_summary_and_live_display_keep_separate_curves_and_data(self):
        from PySide6.QtCore import QThread,Qt
        from PySide6.QtWidgets import QApplication
        from app import db
        from app.main_window import MainWindow
        from app.study_transfer import import_studies
        from test_study_transfer import fixture
        qt=QApplication.instance() or QApplication([])
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.db'),patch.object(QThread,'start'):
            db.init_db();s=fixture();first=source(20.);second=source(5.)
            s.maneuvers[0]['processing_json']=json.dumps(first)
            m=copy.deepcopy(s.maneuvers[0]);m['created_at']='2024-06-17T10:24:45';m['print_selected']=0;m['processing_json']=json.dumps(second)
            s.maneuvers.append(m);import_studies([s])
            pid=db.list_patients()[0]['id'];sid=db.list_sessions_for_patient(pid)[0]['id']
            before=[dict(row) for row in db.list_maneuvers_for_session(sid)]
            w=MainWindow()
            try:
                w.current_patient_id=pid;w.load_study(sid)
                self.assertEqual(w.flow_volume_chart.curves,[first['acq_curve'],second['acq_curve']])
                expected=volume_time_curve(first)
                self.assertEqual(w.volume_time_chart.curves,[expected,expected])
                self.assertEqual(w.summary_volume_time_chart.curves,[expected])
                self.assertEqual(w.summary_flow_volume_chart.curves,[first['acq_curve']])
                ids=list(w.maneuver_phase);w.maneuver_table.selectRow(w._row_for_maneuver(ids[1]))
                self.assertEqual(w.volume_time_chart.highlighted_curve,1)
                self.assertEqual(w.volume_time_chart.curve_colors,w.flow_volume_chart.curve_colors)
                # A newly acquiring curve still shows flat zero/preparation from capture start.
                w.current_params=None;live=[[0.,0.,0.],[1.,0.,0.],[2.,1.,2.]]
                w.update_live_curve(live)
                self.assertEqual(w.volume_time_chart.curves[-1],live)
                self.assertEqual(w.volume_time_chart.curves[:-1],[expected,expected])
                self.assertEqual(before,[dict(row) for row in db.list_maneuvers_for_session(sid)])
            finally:w.close()
