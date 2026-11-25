"""Analytical flow integrals and persistence; no USB or patient data."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_support import working_directory

from app import db, spirometry as s
from app.cpfs_signal import FlowSample


def samples(flows, offset=0.):
    return [FlowSample(offset+i*.01, i%128, 10000 if f>0 else -10000 if f<0 else 0, 0, f)
            for i,f in enumerate(flows)]


class MetricsTests(unittest.TestCase):
    def test_acquisition_curve_starts_with_flat_zero_and_keeps_inspiration(self):
        data=samples([0.]*100+[-2.]*100+[0.]*100+[4.]*100+[0.]*200)
        curve=s.calcular_curva_parcial(data)
        self.assertEqual(len(curve),len(data)+1)
        self.assertEqual(curve[0],(0.,0.,0.))
        self.assertEqual(curve[100],(1.,0.,0.))
        self.assertAlmostEqual(curve[200][1],-2.,places=12)
        self.assertAlmostEqual(curve[-1][0],6.,places=12)
        self.assertAlmostEqual(curve[-1][1],2.,places=12)
        flat=s.calcular_curva_parcial(samples([0.]*200))
        self.assertEqual(flat[-1],(2.,0.,0.))
        # Metric timing remains based on expiration, independent of capture rest.
        p=s.calcular_parametros(data)
        self.assertAlmostEqual(p['fvc'],4.,places=12)
        self.assertAlmostEqual(p['fev1'],4.,places=12)

    def test_constant_flow_has_exact_volume_timing_and_no_rest_interruption(self):
        p=s.calcular_parametros(samples([0.]*100+[4.]*200+[0.]*250))
        self.assertAlmostEqual(p['fvc'],8.,places=12)
        self.assertAlmostEqual(p['fev1'],4.,places=12)
        self.assertAlmostEqual(p['fef2575'],4.,places=12)
        self.assertAlmostEqual(p['t_zero'],0.,places=12)
        self.assertAlmostEqual(p['duracion'],2.,places=12)
        self.assertEqual(p['vol_curve'][0][0:2],(0.,0.))
        self.assertFalse(p['flujo_interrumpido'])
        self.assertFalse(p['cierre_glotico'])
        self.assertTrue(p['meseta_eofe'])
        # The live curve must integrate the same calibrated sample intervals.
        curve=s.calcular_curva_parcial(samples([0.]*100+[4.]*200+[0.]*250))
        self.assertAlmostEqual(max(v for _,v,_ in curve),8.,places=12)

    def test_fev1_includes_back_extrapolated_volume(self):
        p=s.calcular_parametros(samples([0.]*100+[.1]*50+[5.]*10+[2.]*200+[0.]*250))
        self.assertAlmostEqual(p['fvc'],4.55,places=12)
        self.assertAlmostEqual(p['t_zero'],.49,places=12)
        self.assertAlmostEqual(p['bev'],.049,places=12)
        # V at t=1.49: .05 L pre-peak + .5 L peak + .89*2 L tail.
        self.assertAlmostEqual(p['fev1'],2.33,places=12)
        shifted=s.calcular_parametros(samples([0.]*100+[.1]*50+[5.]*10+[2.]*200+[0.]*250,offset=12.34))
        for key in ['fvc','fev1','bev','t_zero','duracion']:
            self.assertAlmostEqual(p[key],shifted[key],places=11)

    def test_inspiration_stops_expiration_before_a_second_breath(self):
        p=s.calcular_parametros(samples([3.]*100+[-1.]*50+[2.]*200+[0.]*250))
        self.assertAlmostEqual(p['fvc'],3.,places=12)
        self.assertEqual(p['fin_idx'],99)
        self.assertAlmostEqual(p['duracion'],1.,places=12)

    def test_one_second_coverage_uses_recording_not_end_of_expiratory_flow(self):
        # Recorded Breeze syringe test: fast expiration, small negative rebound,
        # then several seconds of rest. The full first second was captured.
        p=s.calcular_parametros(samples([4.]*80+[-.1]*5+[0.]*400))
        self.assertTrue(p['fev1_tiempo_cubierto'])
        self.assertNotIn('Registro no cubre 1 s desde T0',p['calidad_errores'])
        self.assertAlmostEqual(p['fev1'],3.2,places=12)
        truncated=s.calcular_parametros(samples([4.]*80))
        self.assertFalse(truncated['fev1_tiempo_cubierto'])

    def test_fef_crossings_are_interpolated(self):
        p=s.calcular_parametros(samples([4.]*80+[1.]*120+[0.]*250))
        self.assertAlmostEqual(p['fvc'],4.4,places=12)
        # 25%=1.1 L at .275 s; 75%=3.3 L at .9 s.
        self.assertAlmostEqual(p['fef2575'],2.2/(.9-.275),places=11)

    def test_invalid_timing_or_flow_is_rejected(self):
        data=samples([2.]*200)
        data[20]=FlowSample(.22,20,10000,0,2.)
        with self.assertRaisesRegex(ValueError,'continuas'):
            s.calcular_parametros(data)
        with self.assertRaises(ValueError):
            s.calcular_parametros(samples([float('nan')]*200))

    def test_environment_is_metadata_not_an_implicit_second_gain(self):
        env={'status':'pending_cpfs_validation','applied_factor':1.,'calibration_conditions':{'temperatura_C':22.}}
        p=s.calcular_parametros(samples([4.]*200+[0.]*250),environment=env)
        self.assertAlmostEqual(p['fvc'],8.)
        self.assertEqual(p['environment'],env)
        self.assertEqual(p['metrics_version'],s.METRICS_VERSION)
        with tempfile.TemporaryDirectory() as tmp, patch.object(s,'_btps',1.5), \
                patch.object(s,'guardar_curvas_html'), \
                patch.object(s,'curva_ascii'), working_directory(tmp):
            # Exercise the CLI formatter and its export in an isolated directory.
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                s.mostrar_resultados(samples([4.]*200+[0.]*250))
            lines=output.getvalue().splitlines()
            self.assertTrue(any('FVC' in line and '8.00' in line for line in lines))
            self.assertTrue(any('FEV1' in line and '4.00' in line for line in lines))
            self.assertIn('BTPS pendiente',output.getvalue())
            exported=json.loads(next(Path(tmp).glob('*.processing.json')).read_text())
            self.assertEqual(exported['environment']['applied_factor'],1.)
            self.assertAlmostEqual(exported['fvc'],8.)

    def test_atps_volume_formula_identity_humidity_and_invalid_inputs(self):
        self.assertAlmostEqual(s.btps_factor(37.,764.,100.),1.,places=14)
        self.assertAlmostEqual(s.btps_factor(22.,764.,86.),1.094826814309005,places=14)
        self.assertGreater(s.btps_factor(22.,764.,0.),s.btps_factor(22.,764.,100.))
        self.assertEqual(s.btps_factor(None,None),1.)
        for args in [(22.,40.,86.),(float('nan'),764.,86.),(22.,764.,101.)]:
            with self.assertRaises(ValueError):s.btps_factor(*args)
        self.assertIsNone(s.calcular_resultado_calibracion(
            [{'vol_modelo':3.}], [{'vol_modelo':-3.}], 22., 0., 86.))

    def test_database_migration_preserves_old_results_and_new_processing(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(db,'DB_PATH',Path(tmp)/'test.sqlite3'):
            db.init_db()
            with db.connect() as con:
                # Emulate an existing schema and an old maneuver, without touching user DB.
                con.execute('ALTER TABLE maneuvers DROP COLUMN processing_json')
                con.execute("INSERT INTO maneuvers(session_id,created_at,fvc,fev1,samples_json) VALUES (1,'2026-10-19T00:00:00',4.2,3.1,'[]')")
            db.init_db()
            with db.connect() as con:
                old=con.execute('SELECT * FROM maneuvers WHERE id=1').fetchone()
            self.assertEqual((old['fvc'],old['fev1'],old['processing_json']),(4.2,3.1,None))
            data=samples([4.]*200+[0.]*250)
            p=s.calcular_parametros(data);p['signal']={'model':'test','daily_factor_esp':1.}
            key=db.save_maneuver(1,p,data)
            with db.connect() as con:
                row=con.execute('SELECT * FROM maneuvers WHERE id=?',(key,)).fetchone()
            restored=json.loads(row['processing_json'])
            self.assertEqual(restored['metrics_version'],s.METRICS_VERSION)
            self.assertEqual(restored['signal'],p['signal'])
            self.assertEqual(restored['environment'],p['environment'])
            self.assertEqual(restored['acq_curve'],[list(x) for x in p['acq_curve']])
            self.assertEqual(json.loads(row['samples_json']),[list(x) for x in data])


if __name__=='__main__':unittest.main()
