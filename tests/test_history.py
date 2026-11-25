"""Synthetic longitudinal history: same summaries, no writes, patient isolation."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app import db
from app.history import patient_history, fvc_summary
from test_support import loaded_pdf


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(db,'DB_PATH',Path(self.tmp.name)/'test.db');p.start();self.addCleanup(p.stop)
        db.init_db();self.pid=db.create_patient('Paciente','Sintético',birth_date='1980-01-01',sex='F',ethnicity='caucasian')

    def visit(self,when):
        sid=db.create_session(self.pid,height_cm=165.)
        with db.connect() as c:c.execute('UPDATE sessions SET created_at=? WHERE id=?',(when,sid))
        return sid

    def maneuver(self,sid,fvc,fev1,phase='pre',status='accepted',pef=6.,fef=3.):
        return db.save_maneuver(sid,dict(fvc=fvc,fev1=fev1,pef=pef,fef2575=fef),[],phase=phase,review_status=status)

    def test_chronological_summary_separates_phases_and_ignores_pending_and_excluded(self):
        latest=self.visit('2024-01-01T11:00:00');oldest=self.visit('2020-01-01T10:00:00')
        empty=self.visit('2022-01-01T10:00:00')
        self.maneuver(oldest,3.,2.5);self.maneuver(oldest,3.5,2.4)
        self.maneuver(oldest,9.,8.,status='excluded');self.maneuver(oldest,8.,7.,status='pending')
        self.maneuver(oldest,4.,3.,phase='post');self.maneuver(latest,None,2.8)
        other=db.create_patient('Otro','Paciente',dni='OTHER');sid=db.create_session(other);self.maneuver(sid,10.,9.)
        rows=patient_history(self.pid)
        self.assertEqual([(r['session_id'],r['phase']) for r in rows],[(oldest,'pre'),(oldest,'post'),(empty,''),(latest,'pre')])
        values=rows[0]['values'];self.assertEqual(values['fvc'],3.5);self.assertEqual(values['fev1'],2.5)
        self.assertAlmostEqual(values['fev1_fvc'],2.5/3.5)
        self.assertEqual(rows[1]['values']['fvc'],4.)
        self.assertTrue(all(value is None for value in rows[2]['values'].values()))
        self.assertIsNone(rows[3]['values']['fvc']);self.assertIsNone(rows[3]['values']['fev1_fvc'])

    def test_original_references_stay_read_only_and_same_day_visits_do_not_collapse(self):
        a=self.visit('2024-01-01T10:00:00');b=self.visit('2024-01-01T11:00:00')
        metadata=json.dumps({'origin':'breeze','predicted':{'fvc':4.},'standard_deviation':{'fvc':.5}})
        with db.connect() as c:c.execute('UPDATE sessions SET source_json=? WHERE id=?',(metadata,a))
        self.maneuver(a,3.,2.);self.maneuver(b,3.1,2.1)
        before=[dict(s) for s in db.list_sessions_for_patient(self.pid)]
        rows=patient_history(self.pid)
        self.assertEqual([r['session_id'] for r in rows],[a,b]);self.assertEqual(rows[0]['reference'],'Breeze original')
        self.assertEqual(rows[0]['origin'],'Breeze');self.assertEqual(rows[0]['values']['fvc'],3.)
        self.assertEqual(before,[dict(s) for s in db.list_sessions_for_patient(self.pid)])
        self.assertEqual(db.get_session(a)['source_json'],metadata)

    def test_svc_ic_erv_mvv_use_included_measurements_and_incomplete_results_stay_missing(self):
        sid=self.visit('2024-01-01T10:00:00')
        for svc,ic,erv,included in [(4.,2.,2.,True),(3.8,1.8,2.,True),(9.,5.,4.,False)]:
            mid=db.save_respiratory_measurement(sid,'svc','pre',dict(measurement_type="svc",svc=svc,ic=ic,erv=erv),[])
            if included:db.include_respiratory_measurement(mid,True)
        mid=db.save_respiratory_measurement(sid,'mvv','post',dict(measurement_type="mvv",mvv=None,mvv_estimate=100.),[])
        db.include_respiratory_measurement(mid,True)
        rows=patient_history(self.pid)
        self.assertEqual(rows[0]['values']['svc'],4.);self.assertAlmostEqual(rows[0]['values']['ic'],1.9)
        self.assertEqual(rows[0]['values']['erv'],2.);self.assertIsNone(rows[1]['values']['mvv'])
        self.assertEqual(patient_history(-1),[])

    def test_ui_tab_chart_filters_point_selection_navigation_and_summary_match(self):
        from PySide6.QtCore import QThread, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        from app import spirometry
        qt=QApplication.instance() or QApplication([])
        a=self.visit('2020-01-01T10:00:00');self.maneuver(a,3.5,2.5);self.maneuver(a,4.,3.,phase='post')
        self.visit('2021-01-01T10:00:00')
        b=self.visit('2024-01-01T10:00:00');self.maneuver(b,3.,2.)
        with patch.object(QThread,'start'),patch.object(spirometry,'open_device',side_effect=AssertionError('History opened USB')):
            w=MainWindow()
            try:
                w.current_patient_id=self.pid;w.show_patient_detail();w.patient_history_tabs.setCurrentIndex(1)
                w.resize(1024,768);w.show();qt.processEvents()
                page=w.history_page
                self.assertEqual(w.page_caption.text(),'Pacientes / Tendencia')
                self.assertLessEqual(w.minimumSizeHint().width(),1024);self.assertLessEqual(w.minimumSizeHint().height(),768)
                self.assertEqual(page.table.rowCount(),4)
                chart=page.charts[0];self.assertEqual(len(chart.targets),3)
                position,record=next((position,record) for position,record in chart.targets if record['session_id']==b)
                QTest.mouseClick(chart,Qt.LeftButton,pos=position.toPoint());qt.processEvents()
                self.assertEqual(page.table.currentRow(),3)
                self.assertTrue(page.open_button.isEnabled())
                page.post.setChecked(False);qt.processEvents()
                self.assertTrue(page.table.isRowHidden(1));self.assertEqual(len(chart.targets),2)
                page.select_point(a,'pre');page.open_button.click()
                self.assertEqual(w.current_session_id,a)
                self.assertEqual(w.summary_table.item(0,2).text(),page.table.item(0,3).text())
                self.assertEqual(w.summary_table.item(1,2).text(),page.table.item(0,4).text())
                w.show_patient_detail();self.assertEqual(w.patient_history_tabs.currentIndex(),1)
                other=db.create_patient('Otro','Vacío',dni='EMPTY');w.current_patient_id=other;w.show_patient_detail()
                self.assertEqual(w.patient_history_tabs.currentIndex(),0);self.assertEqual(page.records,[])
                self.assertFalse(page.open_button.isEnabled())
            finally:w.close()

    def test_mixed_timezone_dates_sort_as_instants_without_combining_visits(self):
        a=self.visit('2024-01-01T10:00:00-03:00')
        b=self.visit('2024-01-01T12:00:00+00:00')
        c=self.visit('2024-01-02T10:00:00')
        self.assertEqual([r['session_id'] for r in patient_history(self.pid)],[b,a,c])

    def test_plot_checkboxes_default_to_all_sync_phases_and_do_not_modify_studies(self):
        from PySide6.QtCore import QThread, Qt
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        qt=QApplication.instance() or QApplication([])
        a=self.visit('2020-01-01T10:00:00');b=self.visit('2024-01-01T10:00:00')
        self.maneuver(a,3.,2.);self.maneuver(a,3.5,2.5,phase='post');self.maneuver(b,4.,3.)
        before={sid:[dict(m) for m in db.list_maneuvers_for_session(sid)] for sid in (a,b)}
        with patch.object(QThread,'start'):
            w=MainWindow()
            try:
                w.current_patient_id=self.pid;w.show_patient_detail();w.patient_history_tabs.setCurrentIndex(1)
                w.resize(1024,768);w.show();qt.processEvents();page=w.history_page
                self.assertEqual(page.selected_studies,{a,b})
                self.assertTrue(all(page.table.item(row,0).checkState()==Qt.Checked for row in range(3)))
                page.table.item(0,0).setCheckState(Qt.Unchecked);qt.processEvents()
                self.assertEqual(page.selected_studies,{b})
                self.assertEqual(page.table.item(1,0).checkState(),Qt.Unchecked)
                self.assertFalse(page.table.isRowHidden(0))
                for chart in page.charts:
                    self.assertEqual({r['session_id'] for _,r in chart.targets},{b})
                page.post.setChecked(False)
                self.assertTrue(page.table.isRowHidden(1))
                # Restoring from either phase restores the study, without changing PRE/POST filters.
                page.table.item(1,0).setCheckState(Qt.Checked);qt.processEvents()
                self.assertEqual(page.table.item(0,0).checkState(),Qt.Checked)
                self.assertEqual(page.selected_studies,{a,b})
                self.assertTrue(all(r['phase']=='pre' for _,r in page.charts[0].targets))
                for row in (0,2):page.table.item(row,0).setCheckState(Qt.Unchecked)
                qt.processEvents()
                self.assertEqual(page.selected_studies,set())
                self.assertTrue(all(chart.targets==[] for chart in page.charts))
                self.assertEqual(before,{sid:[dict(m) for m in db.list_maneuvers_for_session(sid)] for sid in (a,b)})
                w.show_patient_detail();qt.processEvents()
                self.assertEqual(page.selected_studies,{a,b})
            finally:w.close()

    def test_date_axis_uses_only_actual_plotted_visits_not_midpoints_or_missing_values(self):
        from datetime import datetime
        from PySide6.QtCore import QThread, Qt
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        qt=QApplication.instance() or QApplication([])
        dates=('2019-03-27T14:53:38','2020-07-31T14:14:19','2022-04-08T15:03:24','2023-04-28T14:55:30')
        ids=[self.visit(date) for date in dates]
        for sid in (ids[0],ids[2],ids[3]):self.maneuver(sid,3.,2.)
        with patch.object(QThread,'start'):
            w=MainWindow()
            try:
                w.current_patient_id=self.pid;w.show_patient_detail();w.patient_history_tabs.setCurrentIndex(1)
                w.resize(1600,900);w.show();qt.processEvents();page=w.history_page
                expected={datetime.fromisoformat(date).timestamp() for i,date in enumerate(dates) if i!=1}
                for chart in page.charts:
                    self.assertEqual({stamp for stamp,_ in chart.date_labels},expected)
                    self.assertNotIn('12/04/21',{text for _,text in chart.date_labels})
                page.table.item(1,0).setCheckState(Qt.Unchecked);qt.processEvents()
                self.assertEqual({stamp for stamp,_ in page.charts[0].date_labels},expected)
                page.table.item(0,0).setCheckState(Qt.Unchecked);qt.processEvents()
                expected.remove(datetime.fromisoformat(dates[0]).timestamp())
                self.assertEqual({stamp for stamp,_ in page.charts[0].date_labels},expected)
                page.table.item(2,0).setCheckState(Qt.Unchecked);qt.processEvents()
                self.assertEqual(len(page.charts[0].date_labels),1)
                page.table.item(3,0).setCheckState(Qt.Unchecked);qt.processEvents()
                self.assertEqual(page.charts[0].date_labels,[])
            finally:w.close()

    def test_history_pdf_uses_selected_studies_phases_graphs_and_configured_patient_header(self):
        from PySide6.QtCore import QThread, Qt
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        qt=QApplication.instance() or QApplication([])
        ids=[self.visit(date) for date in ('2019-03-12T10:30:00','2021-03-12T10:30:00','2023-03-12T10:30:00')]
        for sid in ids:
            self.maneuver(sid,3.,2.);self.maneuver(sid,3.5,2.5,phase='post')
        db.set_setting('report_header_html','<p style="font-size:18pt; text-align:center;">Centro de Pruebas NeumoFlow</p>')
        db.set_setting('report_logo_path',str(Path('app/data/brand/neumoflow.png').resolve()))
        before=[dict(s) for s in db.list_sessions_for_patient(self.pid)]
        with patch.object(QThread,'start'):
            w=MainWindow()
            try:
                w.current_patient_id=self.pid;w.show_patient_detail();page=w.history_page
                page.table.item(2,0).setCheckState(Qt.Unchecked);page.post.setChecked(False)
                page.selectors[0].setCurrentIndex(page.selectors[0].findData('fev1_fvc'))
                payload=w._history_report_payload()
                self.assertEqual({r['session_id'] for r in payload['records']},{ids[0],ids[2]})
                self.assertEqual({r['phase'] for r in payload['records']},{'pre'})
                self.assertEqual(payload['chart_keys'],['fev1_fvc','fvc','pef'])
                self.assertIn('Centro de Pruebas',payload['header_html'])
                self.assertEqual(payload['patient']['id'],self.pid)
                # Export does not need a current study, and does not alter the live chart's hit targets.
                w.current_session_id=None
                old_targets=list(page.charts[0].targets)
                output=Path(self.tmp.name)/'trend.pdf';self.assertTrue(w.export_history_pdf(output))
                self.assertEqual(old_targets,page.charts[0].targets)
                with loaded_pdf(output) as doc:
                    text='\n'.join(doc.getAllText(i).text() for i in range(doc.pageCount()))
                    self.assertGreater(doc.pagePointSize(0).width(),doc.pagePointSize(0).height())
                    for value in ('Centro de Pruebas NeumoFlow','Sintético Paciente','01/01/1980','12/03/2019','12/03/2023','Femenino','FEV1/FVC'):
                        self.assertIn(value,text)
                    self.assertNotIn('12/03/2021',text);self.assertNotIn('POST',text)
                for row in (0,4):page.table.item(row,0).setCheckState(Qt.Unchecked)
                self.assertFalse(page.pdf_button.isEnabled());self.assertFalse(page.print_button.isEnabled())
                self.assertIsNone(w._history_report_payload())
                self.assertFalse(w.export_history_pdf(Path(self.tmp.name)/'empty.pdf'))
                self.assertEqual(before,[dict(s) for s in db.list_sessions_for_patient(self.pid)])
            finally:w.close()

    def test_long_history_pdf_paginates_with_patient_and_custom_header_on_each_paper(self):
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        from app.main_window import MainWindow
        qt=QApplication.instance() or QApplication([])
        for year in range(1990,2020):
            sid=self.visit(f'{year}-04-17T10:30:00')
            self.maneuver(sid,3.,2.);self.maneuver(sid,3.5,2.5,phase='post')
        db.set_setting('report_header_html','<p>Encabezado de seguimiento</p>')
        db.set_setting('report_margin_left_mm','18');db.set_setting('report_margin_right_mm','15')
        with patch.object(QThread,'start'):
            w=MainWindow()
            try:
                w.current_patient_id=self.pid;w.show_patient_detail()
                for paper in ('A4','Letter','Legal'):
                    db.set_setting('report_paper_size',paper)
                    output=Path(self.tmp.name)/f'trend-{paper}.pdf';w.export_history_pdf(output)
                    with loaded_pdf(output) as doc:
                        self.assertGreater(doc.pageCount(),1)
                        texts=[doc.getAllText(i).text() for i in range(doc.pageCount())]
                        for text in texts:
                            self.assertIn('Encabezado de seguimiento',text);self.assertIn('Sintético Paciente',text)
                            self.assertIn('01/01/1980',text)
                        text='\n'.join(texts)
                        for year in range(1990,2020):self.assertIn(f'17/04/{year}',text)
                        self.assertIn('Evolución',texts[-1])
            finally:w.close()
