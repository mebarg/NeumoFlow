import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from app import db
from app.charts import CurveWidget
from app.main_window import MainWindow


class StableAxesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_empty_axes_and_in_range_curves_never_change_the_viewport(self):
        for mode,expected in [('volume_time',(0.,10.,-5.5,5.5)),
                              ('flow_volume',(-5.5,5.5,-12.,12.))]:
            chart=CurveWidget(mode)
            try:
                chart.configure_study_axes(5.)
                self.assertEqual(chart.study_axis_limits(),expected)
                for curve in [[(0.,0.,0.)],[(0.,0.,0.),(1.,0.,0.),(2.,-3.,-4.)],
                              [(0.,0.,0.),(2.,-3.,-4.),(5.,4.,9.),(9.9,4.,0.)],[]]:
                    chart.set_curve(curve)
                    self.assertEqual(chart.study_axis_limits(),expected)
                # Rendering an empty configured plot must draw axes without min([]).
                self.assertFalse(chart.grab().isNull())
            finally:
                chart.close()

    def test_overflow_expands_in_steps_without_shrinking_or_clipping_data(self):
        chart=CurveWidget('volume_time')
        flow=CurveWidget('flow_volume')
        try:
            for c in (chart,flow):
                c.configure_study_axes(5.)
                c.set_curve([(0.,0.,0.),(10.01,-7.,-13.),(11.,8.,15.)])
            time_limits=chart.study_axis_limits()
            flow_limits=flow.study_axis_limits()
            self.assertEqual(time_limits[:2],(0.,20.))
            self.assertLessEqual(time_limits[2],-7.)
            self.assertGreaterEqual(time_limits[3],8.)
            self.assertEqual(flow_limits[:2],time_limits[2:])
            self.assertEqual(flow_limits[2:],(-16.,16.))
            for c in (chart,flow):
                before=c.study_axis_limits()
                c.set_curve([(0.,0.,0.),(1.,1.,1.)])
                self.assertEqual(c.study_axis_limits(),before)
                c.set_curves([])
                self.assertEqual(c.study_axis_limits(),before)
            chart.configure_study_axes(3.)
            self.assertEqual(chart.study_axis_limits()[:2],(0.,10.))
            self.assertAlmostEqual(chart.study_axis_limits()[2],-3.3)
            self.assertAlmostEqual(chart.study_axis_limits()[3],3.3)
        finally:
            chart.close();flow.close()

    def test_study_uses_predicted_fvc_and_handles_missing_reference(self):
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'),patch.object(QThread,'start'):
            w=MainWindow()
            try:
                patient=db.create_patient('Prueba','Ejes')
                study=db.create_session(patient)
                w.current_patient_id=patient
                with patch('app.main_window.gli2012_predicted',return_value={'fvc':5.6}):
                    w.load_study(study)
                self.assertAlmostEqual(w.volume_time_chart.study_axis_limits()[3],6.16)
                self.assertEqual(w.volume_time_chart.study_axis_limits()[:2],(0.,10.))
                with patch('app.main_window.gli2012_predicted',return_value=None):
                    w.load_study(study)
                self.assertAlmostEqual(w.volume_time_chart.study_axis_limits()[3],6.6)
                # Summary/print retain their own automatic view; calibration is separate.
                self.assertIsNone(w.summary_volume_time_chart.study_axis_limits())
                self.assertIsNone(w.calibration_chart.study_axis_limits())
            finally:
                w.close()


if __name__=='__main__':unittest.main()
