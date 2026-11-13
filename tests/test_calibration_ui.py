import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QThread, Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTextEdit
from app import db, spirometry
from app.cpfs_signal import FlowSample
from app.main_window import MainWindow


class CalibrationSessionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_auto_report_preview_cancel_and_edit_preserve_existing_notes(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'):
            window=MainWindow()
            try:
                patient=db.create_patient('Jeringa','Informe',no_btps=True)
                session=db.create_session(patient,notes='Observación manual.')
                window.current_patient_id=patient
                window.current_session_id=session
                window.show_summary()
                def cancel(dialog):
                    editor=dialog.findChild(QTextEdit)
                    self.assertIn('BORRADOR',editor.toPlainText())
                    self.assertIn('jeringa',editor.toPlainText())
                    return QDialog.Rejected
                with patch('app.main_window.QDialog.exec',new=cancel):
                    window.preview_auto_report()
                self.assertEqual(db.get_session(session)['notes'],'Observación manual.')
                def accept(dialog):
                    dialog.findChild(QTextEdit).setPlainText('Texto revisado por el profesional.')
                    return QDialog.Accepted
                with patch('app.main_window.QDialog.exec',new=accept):
                    window.preview_auto_report()
                expected='Observación manual.\n\nTexto revisado por el profesional.'
                self.assertEqual(db.get_session(session)['notes'],expected)
                window.show_summary()
                self.assertEqual(window.summary_report_input.toPlainText(),expected)
                self.assertEqual(window._report_payload()['report_text'],expected)
            finally:
                window.close()

    def test_busy_usb_shows_actionable_message_for_measurement_and_calibration(self):
        trace='Traceback (most recent call last):\nusb.core.USBError: [Errno 16] Resource busy'
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'):
            window=MainWindow()
            try:
                with patch('app.main_window.QMessageBox.critical') as dialog:
                    window.measurement_failed(trace)
                    window.calibration_failed(trace)
                self.assertEqual(dialog.call_count,2)
                for call in dialog.call_args_list:
                    message=call.args[2]
                    self.assertIn('espirómetro está ocupado',message)
                    self.assertIn('Dispositivos → USB',message)
                    self.assertIn('otra aplicación',message)
                    self.assertNotIn('Traceback',message)
                # Other failures must not be mislabeled as a busy USB device.
                unknown='RuntimeError: Cero inestable'
                self.assertEqual(window._device_error_message(unknown),unknown)
            finally:
                window.close()

    def test_usb_access_denied_explains_exclusive_use_without_showing_traceback(self):
        trace='Traceback (most recent call last):\nusb.core.USBError: [Errno 13] Access denied (insufficient permissions)'
        message=MainWindow._device_error_message(trace)
        self.assertIn('otra instancia',message)
        self.assertIn('Python',message)
        self.assertIn('controlador USB',message)
        self.assertNotIn('Traceback',message)

    def test_unstable_zero_explains_how_to_retry_without_showing_traceback(self):
        trace=('Traceback (most recent call last):\n'
               'RuntimeError: Cero inestable o fuera de rango: variación Lo ≥0.025 V. '
               'Medias Lo=-0.00370695 V, Hi=-0.00051576 V')
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'):
            window=MainWindow()
            try:
                with patch('app.main_window.QMessageBox.warning') as dialog:
                    window.measurement_failed(trace)
                    self.assertEqual(window.status_label.text(),'Repetir puesta a cero')
                    window.calibration_failed(trace)
                    self.assertEqual(window.calibration_status_label.text(),'Repetir puesta a cero')
                self.assertEqual(dialog.call_count,2)
                for call, action in zip(dialog.call_args_list,['Flujo cero','Iniciar calibracion']):
                    self.assertEqual(call.args[1],'Puesta a cero incompleta')
                    message=call.args[2]
                    self.assertIn('sensor apoyado e inmóvil',message)
                    self.assertIn(action,message)
                    self.assertNotIn('Traceback',message)
                    self.assertNotIn('Medias Lo',message)
            finally:
                window.close()

    def test_space_starts_and_stops_once_and_only_on_study_screen(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'), \
                patch.object(QThread,'start'):
            window=MainWindow()
            try:
                window.current_patient_id=db.create_patient('Jeringa','Tecla',no_btps=True)
                window.load_study(db.create_session(window.current_patient_id))
                window.show()
                window.activateWindow()
                window.phase_selector.setFocus()
                self.qt.processEvents()
                worker=window.worker
                # Space during zero preparation must not start a capture.
                QTest.keyClick(window.phase_selector,Qt.Key_Space)
                self.assertFalse(window.capture_active)
                window.study_device_ready()
                with patch.object(worker,'start_capture',wraps=worker.start_capture) as start, \
                        patch.object(worker,'stop',wraps=worker.stop) as stop:
                    QTest.keyPress(window.phase_selector,Qt.Key_Space)
                    self.assertTrue(window.capture_active)
                    repeat=QKeyEvent(QEvent.KeyPress,Qt.Key_Space,Qt.NoModifier,' ',True,1)
                    QApplication.sendEvent(window.phase_selector,repeat)
                    QTest.keyRelease(window.phase_selector,Qt.Key_Space)
                    start.assert_called_once()
                    stop.assert_not_called()
                    # Also works when the action button itself has focus; no double click.
                    window.maneuver_button.setFocus()
                    QTest.keyClick(window.maneuver_button,Qt.Key_Space)
                    stop.assert_called_once()
                    self.assertFalse(window.maneuver_button.isEnabled())
                    QTest.keyClick(window.phase_selector,Qt.Key_Space)
                    stop.assert_called_once()
                window.capture_closed()
                window.show_new_patient()
                self.assertFalse(window.maneuver_space_shortcut.isEnabled())
                window.last_name_input.setFocus()
                QTest.keyClicks(window.last_name_input,'Dos palabras')
                self.assertEqual(window.last_name_input.text(),'Dos palabras')
                self.assertFalse(window.capture_active)
            finally:
                window.close()

    def test_enter_study_prepares_once_capture_clock_starts_at_zero_and_zero_button_repeats(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'), \
                patch.object(QThread,'start') as thread_start:
            window=MainWindow()
            try:
                patient=db.create_patient('Jeringa','Banco',no_btps=True)
                study=db.create_session(patient)
                window.current_patient_id=patient
                window.load_study(study)
                thread_start.assert_called_once()
                worker=window.worker
                self.assertFalse(window.device_ready)
                self.assertFalse(window.maneuver_button.isEnabled())
                worker.ready.emit()
                self.qt.processEvents()
                self.assertTrue(window.device_ready)
                self.assertTrue(window.maneuver_button.isEnabled())
                window.start_maneuver()
                self.assertIs(window.worker,worker)
                self.assertTrue(window.capture_active)
                worker.capture_started.emit()
                self.qt.processEvents()
                self.assertTrue(window.elapsed_timer.isActive())
                flat=spirometry.calcular_curva_parcial([FlowSample(i*.01,i%128,0,0,0.) for i in range(50)])
                worker.progress.emit(flat)
                self.qt.processEvents()
                self.assertEqual(window.volume_time_chart.curves[-1],flat)
                worker.capture_closed.emit()
                self.qt.processEvents()
                self.assertFalse(window.capture_active)
                self.assertFalse(window.elapsed_timer.isActive())
                self.assertTrue(window.zero_button.isEnabled())
                window.start_maneuver()
                self.assertIs(window.worker,worker)
                thread_start.assert_called_once()
                window.capture_closed()
                with patch.object(worker,'zero') as zero:
                    window.repeat_zero()
                    zero.assert_called_once()
                self.assertFalse(window.device_ready)
                self.assertFalse(window.maneuver_button.isEnabled())
                window.show_patients()
                self.assertTrue(worker.shutdown_requested.is_set())
            finally:
                window.close()

    def test_real_qthread_reuses_connection_and_releases_when_leaving_study(self):
        import struct
        import time
        from app.cpfs_signal import FlowProcessor, StreamSession
        class Device:
            count=0
            def read(self,*args,**kwargs):
                time.sleep(.005)
                start=self.count
                self.count+=10
                return b''.join(struct.pack('<BHHB',i%128,32768,32768,255)
                                for i in range(start,start+10))
        dev=Device()
        def initialize(device):
            device._cpfs_session=StreamSession(FlowProcessor())
            return 2000
        def until(condition):
            deadline=time.monotonic()+3
            while not condition() and time.monotonic()<deadline:
                self.qt.processEvents()
                time.sleep(.005)
            self.assertTrue(condition(),'Worker/GUI did not reach expected state')
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'), \
                patch.object(spirometry,'open_device',return_value=dev) as opened, \
                patch.object(spirometry,'inicializar',side_effect=initialize) as zero, \
                patch.object(spirometry,'send_bytes'),patch.object(spirometry,'flush'), \
                patch.object(spirometry.usb.util,'release_interface') as release, \
                patch.object(spirometry.usb.util,'dispose_resources'), \
                patch('app.main_window.QMessageBox.critical') as error:
            window=MainWindow()
            try:
                patient=db.create_patient('Jeringa','Hilo',no_btps=True)
                window.current_patient_id=patient
                window.load_study(db.create_session(patient))
                until(lambda:window.device_ready)
                for _ in range(2):
                    window.start_maneuver()
                    until(lambda:bool(window.volume_time_chart.curves) and window.elapsed_timer.isActive())
                    curve=window.volume_time_chart.curves[-1]
                    self.assertEqual(curve[0],(0.,0.,0.))
                    self.assertTrue(all(v==0 for t,v,f in curve))
                    window.toggle_maneuver()
                    until(lambda:not window.capture_active)
                opened.assert_called_once()
                zero.assert_called_once()
                window.repeat_zero()
                until(lambda:window.device_ready)
                self.assertEqual(zero.call_count,2)
                window.show_patients()
                until(lambda:window.worker is None)
                release.assert_called_once_with(dev,0)
                error.assert_not_called()
            finally:
                window.close()

    def test_start_new_session_clears_old_strokes_without_changing_factors(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, 'DB_PATH', Path(tmp)/'test.sqlite3'):
            window = MainWindow()
            try:
                window.calibration_strokes = [{'direction': 'push', 'vol_modelo': 3.,
                    'pico': 1., 'duracion': 3., 'curva': [(0., 0., 0.), (3., 3., 1.)]}]
                window.live_calibration_curve = [(0., 0., 0.)]
                window.refresh_calibration_table()
                window.calibration_save_button.setEnabled(True)
                factors = spirometry.FACTOR_ESP, spirometry.FACTOR_INS
                with patch.object(QThread, 'start'):
                    window.start_calibration_session()
                self.assertEqual(window.calibration_strokes, [])
                self.assertEqual(window.live_calibration_curve, [])
                self.assertEqual(window.calibration_table.rowCount(), 0)
                self.assertEqual(window.calibration_chart.curves, [])
                self.assertFalse(window.calibration_save_button.isEnabled())
                self.assertEqual((spirometry.FACTOR_ESP, spirometry.FACTOR_INS), factors)
                # An extra Start while acquisition is active must not clear new data.
                window.calibration_strokes.append({'marker': 'new-session'})
                window.start_calibration_session()
                self.assertEqual(len(window.calibration_strokes), 1)
            finally:
                window.close()

    def test_reopen_study_uses_recorded_curve_without_reprocessing_raw(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(db, 'DB_PATH', Path(tmp)/'test.sqlite3'):
            window = MainWindow()
            try:
                window.calibration_pressure_input.setText('0')
                self.assertIsNone(window._calibration_inputs())
                window.calibration_pressure_input.setText('764')
                patient = db.create_patient('Prueba', 'Persistencia')
                session = db.create_session(patient)
                data = [FlowSample(i*.01, i%128, 10000 if i<200 else 0, 0, 4. if i<200 else 0.)
                        for i in range(450)]
                params = spirometry.calcular_parametros(data)
                key = db.save_maneuver(session, params, data)
                # Legacy results retain their metrics but have no verified curve.
                with db.connect() as con:
                    con.execute("INSERT INTO maneuvers(session_id,created_at,fvc,fev1,samples_json) "
                                "VALUES (?, '2026-10-19T00:00:00', 4.2, 3.1, '[]')", (session,))
                window.current_patient_id = patient
                with patch.object(QThread, 'start'), patch.object(spirometry, 'calcular_curva_parcial', side_effect=AssertionError('raw reprocessed')):
                    window.load_study(session)
                self.assertEqual(window.maneuver_curves[key], [list(x) for x in params['acq_curve']])
                self.assertEqual(len(window.maneuver_selected), 2)
            finally:
                window.close()

    def test_patient_flag_persists_and_measurements_reuse_daily_calibration(self):
        from datetime import datetime
        daily={'fecha':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
               'temperatura_C':22.,'presion_mmHg':764.,'humedad_pct':86.,
               'factor_esp':1.01,'factor_ins':.99}
        with tempfile.TemporaryDirectory() as tmp, patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'), \
                patch.object(spirometry,'_cal',daily):
            window=MainWindow()
            try:
                patient=db.create_patient('Paciente','Normal',dni='1')
                syringe=db.create_patient('Jeringa','Prueba',dni='2',no_btps=True)
                self.assertFalse(db.get_patient(patient)['no_btps'])
                self.assertTrue(db.get_patient(syringe)['no_btps'])
                window.current_patient_id=patient
                env=window.measurement_environment()
                self.assertEqual(env['conditions_source'],'daily_calibration')
                self.assertEqual(env['conditions']['temperature_C'],22.)
                self.assertAlmostEqual(env['factor_positive'],1.054795494464003,places=14)
                window.current_session_id=db.create_session(patient)
                with patch.object(QThread,'start'):
                    window._device_requested=True
                    window.ensure_study_device()
                window.study_device_ready()
                window.start_maneuver()
                self.assertEqual(window.worker.environment,env)
                window.capture_closed()
                # A later calibration feeds subsequent studies, without editing each study.
                daily['temperatura_C']=24.
                self.assertEqual(window.measurement_environment()['conditions']['temperature_C'],24.)
                self.assertEqual(env['conditions']['temperature_C'],22.)
                daily['fecha']='2000-01-01 12:00:00'
                old_env=window.measurement_environment()
                self.assertFalse(old_env['calibration_is_today'])
                self.assertIn('recomendable',old_env['calibration_notice'])
                with patch.object(QThread,'start'), patch('app.main_window.QMessageBox.warning') as warning:
                    window.start_maneuver()
                    warning.assert_called_once()
                    self.assertEqual(window.worker.environment,old_env)
                    window.capture_closed()
                    # Subsequent maneuvers in this study continue without repeated dialogs.
                    window.start_maneuver()
                    warning.assert_called_once()
                    window.capture_closed()
                window.current_patient_id=syringe
                self.assertEqual(window.measurement_environment()['factor_positive'],1.)
                db.update_patient(syringe,'Jeringa','Prueba','2','','','',no_btps=False)
                self.assertFalse(db.get_patient(syringe)['no_btps'])
                # Save/edit the actual patient form, not a per-study switch.
                window.show_new_patient()
                window.last_name_input.setText('Banco')
                window.first_name_input.setText('Jeringa')
                window.dni_input.setText('3')
                window.birth_date_input.setText('01/01/1970')
                window.patient_no_btps.setChecked(True)
                window.save_patient()
                self.assertTrue(db.get_patient_by_dni('3')['no_btps'])
                window.show_patients()
                row=next(i for i in range(window.patient_table.rowCount())
                         if window.patient_table.item(i,0).text()==str(db.get_patient_by_dni('3')['id']))
                window.patient_table.selectRow(row)
                window.edit_selected_patient()
                self.assertTrue(window.patient_no_btps.isChecked())
            finally:
                window.close()
