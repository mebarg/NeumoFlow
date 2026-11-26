"""Synthetic artifacts and saved operator decisions; no patient data or USB."""
from copy import deepcopy
import json
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QDialog
from app import db, spirometry
from app.cpfs_signal import FlowSample
from app.fvc_quality import (annotate, assessment, apply_decisions, metric_eligible,
                             plot_regions, quality_text, validate_quality)
from app.history import fvc_summary, patient_history
from app.study_transfer import export_studies, read_package, validate, TransferError


def curve_params(artifact=None, at=.4, t_zero=0.):
    points = [(0., 0., 4.)]
    volume = 0.
    for i in range(400):
        t = i*.01
        flow = 4*math.exp(-t)
        if artifact == 'cough' and at <= t < at+.08:
            flow *= .10
        if artifact == 'glottic' and at <= t < at+.36:
            flow = .001
        volume += flow*.01
        points.append(((i+1)*.01, volume, flow))
    return annotate(dict(fvc=volume, fev1=2.5, pef=4., fef2575=2.,
        vol_curve=points, acq_curve=points, inicio_idx=0, t_zero=t_zero,
        inicio_aceptable=True, fev1_tiempo_cubierto=True, meseta_eofe=True,
        duracion=4., calidad_errores=[]))


def record(params):
    return dict(fvc=params['fvc'], fev1=params['fev1'], fef2575=params['fef2575'],
                pef=params['pef'], processing_json=json.dumps(params))


class FvcQualityTests(unittest.TestCase):
    def test_smooth_curve_has_no_events_and_timing_is_from_saved_t0(self):
        self.assertEqual(curve_params()['quality_events'], [])
        params = curve_params('cough', .4, .04)
        self.assertTrue(params['quality_events'])
        for event in params['quality_events']:
            self.assertAlmostEqual(event['start_t0'], event['start']-.04)
            self.assertEqual(event['decision'], 'pending')
        self.assertIn('Posible tos', quality_text(params))
        self.assertEqual(assessment(params)['fev1']['state'], 'review')
        self.assertEqual(assessment(params)['fvc']['state'], 'clear')

    def test_late_cough_does_not_invalidate_fev1_but_flow_indices_wait_for_review(self):
        params = curve_params('cough', 1.2)
        self.assertTrue(params['quality_events'])
        self.assertTrue(all(e['start_t0'] > 1 for e in params['quality_events']))
        for metric in ('fev1', 'fvc'):
            self.assertTrue(metric_eligible(record(params), metric))
        for metric in ('pef', 'fef2575'):
            self.assertFalse(metric_eligible(record(params), metric))

    def test_confirm_and_dismiss_early_cough_separates_fev1_and_fvc(self):
        original = curve_params('cough')
        confirmed = apply_decisions(original, {e['id']:'confirmed' for e in original['quality_events']}, '2026-01-01')
        self.assertEqual(assessment(confirmed)['fev1']['state'], 'unusable')
        self.assertEqual(assessment(confirmed)['fvc']['state'], 'clear')
        self.assertFalse(metric_eligible(record(confirmed), 'fev1'))
        self.assertTrue(metric_eligible(record(confirmed), 'fvc'))
        dismissed = apply_decisions(confirmed, {e['id']:'dismissed' for e in original['quality_events']}, '2026-01-02')
        self.assertTrue(metric_eligible(record(dismissed), 'fev1'))
        self.assertEqual(dismissed['calidad_errores'], [])
        self.assertEqual(plot_regions(dismissed), [])
        self.assertEqual(len(dismissed['quality_reviews']), 2)
        self.assertTrue(all(e['decision']=='pending' for e in original['quality_events']))

    def test_glottic_closure_early_affects_both_and_late_only_fvc(self):
        for at in (.3, 1.3):
            params = curve_params('glottic', at)
            self.assertTrue(any(e['kind']=='glottic' for e in params['quality_events']))
            params = apply_decisions(params, {e['id']:'confirmed' if e['kind']=='glottic' else 'dismissed'
                                              for e in params['quality_events']}, 'now')
            states = assessment(params)
            self.assertEqual(states['fvc']['state'], 'unusable')
            self.assertEqual(states['fev1']['state'], 'unusable' if at < 1 else 'clear')

    def test_final_plateau_does_not_block_fev1_and_bad_start_blocks_both(self):
        params = curve_params()
        params['meseta_eofe'] = False
        self.assertTrue(metric_eligible(record(params), 'fev1'))
        self.assertFalse(metric_eligible(record(params), 'fvc'))
        params['inicio_aceptable'] = False
        self.assertFalse(metric_eligible(record(params), 'fev1'))

    def test_summary_uses_only_eligible_value_for_each_metric_and_legacy_stays_original(self):
        suspect = curve_params('cough')
        suspect['fvc'] = 5.
        suspect['fev1'] = 4.
        clean = curve_params()
        clean['fvc'] = 3.
        clean['fev1'] = 2.
        result = fvc_summary([record(suspect), record(clean)])
        self.assertEqual(result['fvc'], 5.)
        self.assertEqual(result['fev1'], 2.)
        self.assertAlmostEqual(result['fev1_fvc'], .4)
        legacy = dict(fvc=6., fev1=4., pef=5., fef2575=3., processing_json='{"origin":"breeze"}')
        self.assertEqual(fvc_summary([legacy])['fvc'], 6.)
        with self.assertRaises(ValueError):
            annotate({'origin':'breeze'})

    def test_selected_regions_use_acquisition_offset_and_do_not_change_curves(self):
        params = curve_params('cough')
        original = deepcopy(params['vol_curve'])
        params['inicio_idx'] = 200
        params['acq_curve'] = [(t+2, v-1, f) for t, v, f in original]
        vt = plot_regions(params)
        fv = plot_regions(params, acquisition=True)
        self.assertEqual(len(vt), len(fv))
        self.assertAlmostEqual(fv[0]['points'][0][0]-vt[0]['points'][0][0], 2.)
        self.assertEqual(params['vol_curve'], original)

    def test_signal_pipeline_saves_quality_without_altering_constant_flow_metrics(self):
        samples = [FlowSample(i*.01, i%128, 10000 if f>0 else 0, 0, f)
                   for i, f in enumerate([0.]*100+[4.]*200+[0.]*250)]
        params = spirometry.calcular_parametros(samples)
        self.assertEqual(params['quality_version'], 1)
        self.assertFalse(params['cierre_glotico'])
        self.assertEqual(params['quality_events'], [])
        self.assertAlmostEqual(params['fvc'], 8.)
        self.assertAlmostEqual(params['fev1'], 4.)

    def test_interpretation_requires_three_eligible_values_per_metric(self):
        from test_interpretation import records, PATIENT, SESSION, refs
        from app.interpretation import generate_report
        rows = records()+records()[:1]
        for row in rows:
            params = json.loads(row['processing_json'])
            params.update(duracion=4., calidad_errores=[])
            row['processing_json'] = json.dumps(annotate(params))
        suspect = curve_params('cough')
        suspect['environment'] = json.loads(rows[0]['processing_json'])['environment']
        rows[0]['processing_json'] = json.dumps(suspect)
        rows[0]['quality_errors_json'] = json.dumps(suspect['calidad_errores'])
        text = generate_report(PATIENT, SESSION, rows, references=refs)
        self.assertIn('FEV1: 3, FVC: 4', text)
        self.assertNotIn('Interpretación del patrón no emitida', text)
        text = generate_report(PATIENT, SESSION, rows[:3], references=refs)
        self.assertIn('Interpretación del patrón no emitida', text)

    def test_invalid_review_and_event_metadata_are_rejected(self):
        params = curve_params('cough')
        validate_quality(params)
        with self.assertRaises(ValueError):
            apply_decisions(params, {}, 'now')
        bad = deepcopy(params)
        bad['quality_events'][0]['start_t0'] += 1
        with self.assertRaises(ValueError):
            validate_quality(bad)


class QualityReviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def test_operator_review_persists_reopens_and_export_preserves_original_measurements(self):
        from app.main_window import MainWindow
        from app.quality_dialog import QualityReviewDialog
        with TemporaryDirectory() as tmp, patch.object(db, 'DB_PATH', Path(tmp)/'db.sqlite'), patch.object(QThread,'start'):
            w = MainWindow()
            try:
                patient = db.create_patient('Prueba', 'Calidad', no_btps=True)
                session = db.create_session(patient)
                params = curve_params('cough')
                key = db.save_maneuver(session, params, [])
                before = dict(db.list_maneuvers_for_session(session)[0])
                w.current_patient_id = patient
                w.load_study(session)
                w.resize(1366,690)
                w.show()
                w.maneuver_table.selectRow(w._row_for_maneuver(key))
                self.qt.processEvents()
                from PySide6.QtWidgets import QPushButton
                self.assertFalse(any(button.text().startswith('Revisar calidad')
                                     for button in w.findChildren(QPushButton)))
                self.assertTrue(w.volume_time_chart.quality_regions)
                self.assertIsNone(w._summary_best_values([before])['fev1'])
                dialog = QualityReviewDialog(params, w)
                try:
                    for choice in dialog.selectors.values():
                        choice.setCurrentIndex(choice.findData('dismissed'))
                    self.assertIn('Sin alertas automáticas', dialog.evaluation.text())
                    db.review_maneuver_quality(key, params, dialog.decisions())
                finally:
                    dialog.close()
                after = dict(db.list_maneuvers_for_session(session)[0])
                for field in ('fvc','fev1','pef','fef2575','samples_json','accepted','review_status'):
                    self.assertEqual(before[field], after[field])
                self.assertEqual(json.loads(after['processing_json'])['vol_curve'], json.loads(before['processing_json'])['vol_curve'])
                w.load_study(session)
                w.maneuver_table.selectRow(w._row_for_maneuver(key))
                self.assertEqual(w.volume_time_chart.quality_regions, [])
                self.assertEqual(patient_history(patient)[0]['values']['fev1'], params['fev1'])
                path = Path(tmp)/'quality.espiro'
                export_studies(path, [session])
                studies = read_package(path)
                self.assertEqual(json.loads(studies[0].maneuvers[0]['processing_json'])['quality_reviews'][0]['after'],
                                 {e['id']:'dismissed' for e in params['quality_events']})
                bad = deepcopy(studies[0])
                payload = json.loads(bad.maneuvers[0]['processing_json'])
                payload['quality_events'][0]['decision'] = 'bad'
                bad.maneuvers[0]['processing_json'] = json.dumps(payload)
                with self.assertRaises(TransferError):
                    validate(bad)
                payload['quality_events'][0]['decision'] = 'dismissed'
                payload['vol_curve'] = [[]]
                bad.maneuvers[0]['processing_json'] = json.dumps(payload)
                with self.assertRaises(TransferError):
                    validate(bad)
                with self.assertRaises(ValueError):
                    db.review_maneuver_quality(key, params, {e['id']:'confirmed' for e in params['quality_events']})
                def confirm_dialog(dialog):
                    for choice in dialog.selectors.values():
                        choice.setCurrentIndex(choice.findData('confirmed'))
                    return QDialog.Accepted
                with patch.object(QualityReviewDialog, 'exec', confirm_dialog):
                    w.review_selected_quality()
                latest = dict(db.list_maneuvers_for_session(session)[0])
                self.assertIsNone(w._summary_best_values([latest])['fev1'])
                self.assertEqual(w._summary_best_values([latest])['fvc'], params['fvc'])
                self.assertTrue(all(r['confirmed'] for r in w.volume_time_chart.quality_regions))
            finally:
                w.close()
