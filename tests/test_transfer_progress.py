"""Large, synthetic previews, progress and transactional cancellation."""
import gc
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from app import db, study_transfer as transfer
from test_study_transfer import fixture, cow_bytes


class TransferProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db_patch = patch.object(db, 'DB_PATH', self.root/'test.sqlite3')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()

    def test_spooled_cow_preserves_source_curves_duplicates_and_import(self):
        path = self.root/'sample.cow'
        path.write_bytes(cow_bytes())
        original = transfer.read_breeze(path)
        progress = []
        rows, errors = transfer.scan_folder(self.root, lambda *p: progress.append(p), spool=True)
        self.assertFalse(errors)
        self.assertEqual(progress[-1][1:3], (1, 1))
        row = rows[0]
        self.assertEqual(row.maneuvers, [])
        self.assertIsNone(row.session['source_json'])
        self.assertEqual(transfer._study_dict(row), transfer._study_dict(original))
        result = transfer.import_studies(rows)
        self.assertEqual(result['imported'], 1)
        again, errors = transfer.scan_folder(self.root, spool=True)
        self.assertEqual(again[0].duplicate_id, result['session_ids'][row.uid])
        self.assertEqual(transfer.import_studies(again)['skipped'], 1)
        stored = row.path
        del row, rows
        gc.collect()
        self.assertFalse(stored.exists())

    def test_scan_14000_files_reports_counts_and_uses_one_connection(self):
        # Real enumeration and spool writes, synthetic reader: this measures the
        # batch path independently of proprietary COW contents or USB hardware.
        count = 14000
        for i in range(count):
            (self.root/f'{i:05}.cow').touch()
        def read(path):
            study = fixture('visit:'+path.stem, 'patient:'+path.stem)
            study.maneuvers = []
            return study
        updates = []
        with patch.object(transfer, 'read_breeze', side_effect=read), \
                patch.object(db, 'connect', wraps=db.connect) as connect:
            rows, errors = transfer.scan_folder(self.root, lambda *p: updates.append(p), spool=True)
            self.assertEqual(connect.call_count, 1)
        self.assertFalse(errors)
        self.assertEqual(len(rows), count)
        self.assertEqual(updates[-1][1:3], (count, count))
        self.assertEqual(len({r.uid for r in rows}), count)
        self.assertTrue(all(isinstance(r, transfer.StoredStudy) for r in rows))

    def test_cancel_during_writes_rolls_back_the_entire_batch(self):
        studies = [fixture('one', 'A'), fixture('two', 'B')]
        stop = False
        def progress(stage, done, total, name):
            nonlocal stop
            if stage == 'Importando estudios' and done == 1:
                stop = True
        with self.assertRaises(transfer.TransferCancelled):
            transfer.import_studies(studies, progress=progress, cancelled=lambda: stop)
        with db.connect() as conn:
            for table in ('patients', 'sessions', 'maneuvers'):
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], 0)

    def test_cancel_scan_does_not_return_a_partial_preview(self):
        (self.root/'test.cow').touch()
        with self.assertRaises(transfer.TransferCancelled):
            transfer.scan_folder(self.root, cancelled=lambda: True, spool=True)

    def test_duplicate_and_replacement_queries_use_indexes(self):
        with db.connect() as conn:
            for query, values in (
                ('SELECT id FROM sessions WHERE patient_id=? AND created_at=?', (1, '2024-01-01')),
                ('DELETE FROM maneuvers WHERE session_id=?', (1,)),
                ('DELETE FROM respiratory_measurements WHERE session_id=?', (1,)),
            ):
                plan = ' '.join(str(tuple(row)) for row in conn.execute('EXPLAIN QUERY PLAN '+query, values))
                self.assertIn('INDEX', plan)
                self.assertNotIn('SCAN ', plan)


class TransferProgressUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt = QApplication.instance() or QApplication([])

    def pump_until(self, predicate, timeout=30):
        end = monotonic()+timeout
        while not predicate() and monotonic() < end:
            self.qt.processEvents()
            sleep(.001)
        self.assertTrue(predicate())

    def test_large_table_yields_to_event_loop_and_preserves_duplicate_defaults(self):
        from PySide6.QtCore import QTimer, Qt
        from app.transfer_dialog import TransferDialog
        dialog = TransferDialog()
        try:
            rows = [fixture(str(i), str(i)) for i in range(14000)]
            rows[1].duplicate_id = 42
            ticks = []
            timer = QTimer()
            timer.timeout.connect(lambda: ticks.append(dialog.fill_index))
            timer.start(0)
            dialog.scanned((rows, []))
            self.assertTrue(dialog.rendering)
            self.assertFalse(dialog.action.isEnabled())
            self.pump_until(lambda: not dialog.rendering)
            timer.stop()
            self.assertGreater(len(ticks), 2)
            self.assertTrue(any(0 < i < len(rows) for i in ticks))
            self.assertEqual(dialog.table.rowCount(), 14000)
            self.assertEqual(dialog.table.item(1, 0).checkState(), Qt.Unchecked)
            self.assertEqual(dialog.table.item(0, 0).checkState(), Qt.Checked)
            self.assertTrue(dialog.action.isEnabled())
        finally:
            dialog.fill_timer.stop()
            dialog.rendering = False
            dialog.close()

    def test_real_worker_progress_and_cancel_leave_dialog_usable(self):
        from app.transfer_dialog import TransferDialog
        dialog = TransferDialog()
        try:
            def work(progress, cancelled):
                for i in range(500):
                    transfer._checkpoint(progress, cancelled, 'Leyendo', i, 500, 'archivo.cow')
                    sleep(.005)
                return ([], [])
            dialog.start_task(work, dialog.scanned, reporting=True)
            self.pump_until(lambda: 'archivo.cow' in dialog.status.text())
            self.assertEqual(dialog.progress_bar.maximum(), 500)
            dialog.cancel_button.click()
            self.pump_until(lambda: dialog.task is None)
            self.assertIn('cancelada', dialog.status.text())
            self.assertTrue(dialog.folder_button.isEnabled())
            self.assertFalse(dialog.action.isEnabled())
        finally:
            if dialog.task:
                dialog.task.requestInterruption()
                dialog.task.wait(5000)
                self.qt.processEvents()
            dialog.close()

    def test_import_completion_does_not_select_previously_unselected_rows(self):
        from PySide6.QtCore import Qt
        from app.transfer_dialog import TransferDialog
        dialog = TransferDialog()
        try:
            rows = [fixture('one', 'A'), fixture('two', 'B')]
            dialog.scanned((rows, []))
            dialog.table.item(1, 0).setCheckState(Qt.Unchecked)
            dialog.imported(dict(imported=1, replaced=0, skipped=0, backup=None,
                                 session_ids={'one': 12}))
            self.assertEqual(dialog.table.item(0, 0).checkState(), Qt.Unchecked)
            self.assertEqual(dialog.table.item(1, 0).checkState(), Qt.Unchecked)
            self.assertTrue(dialog.changed)
            self.assertIn('Importados: 1', dialog.status.text())
        finally:
            dialog.close()
