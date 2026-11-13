import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QThread
from PySide6.QtGui import QPalette, QImage, QPainter
from PySide6.QtWidgets import QApplication
from app import db, spirometry
from app.cpfs_signal import FlowSample
from app.main_window import MainWindow
from app.report import SpirometryReportRenderer


class ResultDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_light_summary_and_persisted_optional_low_reference_colors(self):
        # Known reference limits test display policy, not the clinical equations.
        limits={'fvc':3.,'fev1':2.,'fev1_fvc':.7,'fef2575':1.}
        def references(patient,session,params):
            return {key:None if params.get(key) is None else
                    {'lln':limit,'predicted':limit*1.2,'percent':80.,'zscore':-2.}
                    for key,limit in limits.items()}
        with TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'), \
                patch.object(QThread,'start'),patch('app.main_window.gli2012_for_maneuver',side_effect=references), \
                patch('app.main_window.gli2012_predicted',return_value={k:v*1.2 for k,v in limits.items()}):
            w=MainWindow()
            try:
                patient=db.create_patient('Prueba','Colores',dni='123')
                study=db.create_session(patient)
                samples=[FlowSample(i*.01,i%128,10000 if i<200 else 0,0,1. if i<200 else 0.)
                         for i in range(450)]
                params=spirometry.calcular_parametros(samples)
                key=db.save_maneuver(study,params,samples,review_status='accepted',phase='pre')
                post={**params,'fvc':4.,'fev1':2.,'fev1_fvc':.5,'fef2575':2.}
                db.save_maneuver(study,post,samples,review_status='accepted',phase='post')
                w.current_patient_id=patient
                w.load_study(study)
                self.assertEqual(w.summary_table.palette().color(QPalette.Base).name(),'#ffffff')
                self.assertEqual(w.summary_table.palette().color(QPalette.Text).name(),'#1f2937')
                row=next(i for i in range(w.maneuver_table.rowCount())
                         if w.maneuver_table.item(i,0).text()==str(key))
                self.assertFalse(w.fvc_red_values.isChecked())
                self.assertEqual(w.maneuver_table.item(row,4).foreground().color().name(),'#1f2937')
                w.fvc_red_values.setChecked(True)
                self.assertEqual(db.get_setting('fvc_red_abnormal'),'1')
                # Actual, % predicted and z are marked together on affected metrics.
                for col in (4,5,6,7,8,9,10,11):
                    self.assertEqual(w.maneuver_table.item(row,col).foreground().color().name(),'#b91c1c')
                # Equal to the limit is not below it.
                self.assertEqual(w.maneuver_table.item(row,12).foreground().color().name(),'#1f2937')
                self.assertEqual(w.summary_table.item(0,2).foreground().color().name(),'#b91c1c')
                self.assertEqual(w.summary_table.item(0,5).foreground().color().name(),'#1f2937')
                self.assertEqual(w.summary_table.item(1,5).foreground().color().name(),'#1f2937')
                self.assertEqual(w.summary_table.item(4,2).foreground().color().name(),'#1f2937')
                payload=w._report_payload()
                self.assertTrue(payload['summary_red_cells'][0][2])
                self.assertFalse(payload['summary_red_cells'][0][5])
                def render_table(payload):
                    image=QImage(920,180,QImage.Format_ARGB32)
                    image.fill(0xffffffff)
                    painter=QPainter(image)
                    renderer=SpirometryReportRenderer(payload)
                    renderer.scale=1.
                    renderer._draw_summary_table(painter,10.,10.,900.)
                    painter.end()
                    return image
                def red_pixels(image):
                    return sum(image.pixelColor(x,y).red()>120 and image.pixelColor(x,y).green()<80
                               and image.pixelColor(x,y).blue()<80
                               for y in range(image.height()) for x in range(image.width()))
                printed=render_table(payload)
                self.assertGreater(red_pixels(printed),0)
                # Text red must not turn the following cell borders red.
                self.assertEqual(printed.pixelColor(310,32).name(),'#000000')
                restored=MainWindow()
                try:
                    self.assertTrue(restored.fvc_red_values.isChecked())
                finally:
                    restored.close()
                with patch('app.main_window.gli2012_for_maneuver',return_value=None):
                    w.refresh_study_summary()
                    self.assertEqual(w.maneuver_table.item(row,4).foreground().color().name(),'#1f2937')
                w.fvc_red_values.setChecked(False)
                self.assertEqual(w.summary_table.item(0,2).foreground().color().name(),'#1f2937')
                self.assertEqual(db.get_setting('fvc_red_abnormal'),'0')
                monochrome=w._report_payload()
                self.assertFalse(any(any(row) for row in monochrome['summary_red_cells']))
                self.assertEqual(red_pixels(render_table(monochrome)),0)
            finally:
                w.close()


if __name__=='__main__':unittest.main()
