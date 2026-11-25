"""Runtime-reference factors and single application across metrics/live/export."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import struct
import unittest
from unittest.mock import patch
from test_support import working_directory

from app.cpfs_environment import measurement_environment, annotate_sample
from app.cpfs_signal import FlowSample, FlowProcessor, StreamSession
from app import spirometry as sp
from app.workers import MeasurementWorker


class EnvironmentTests(unittest.TestCase):
    def patient(self):
        return measurement_environment('patient',22.,764.,86.,30.)

    def test_matches_two_independently_read_runtime_doubles(self):
        e=self.patient()
        self.assertAlmostEqual(e['factor_negative'],1.094826814309005,places=14)
        self.assertAlmostEqual(e['factor_positive'],1.054795494464003,places=14)
        # Density/composition distinguishes this from a single ATPS multiplier.
        self.assertNotEqual(e['factor_positive'],sp.btps_factor(30.,764.,100.))

    def test_syringe_neutral_and_patient_requires_current_conditions(self):
        e=measurement_environment('syringe')
        self.assertEqual((e['factor_negative'],e['factor_positive']),(1.,1.))
        for values in [(None,764.,86.,30.),(22.,0.,86.,30.),
                       (float('nan'),764.,86.,30.),(22.,764.,101.,30.)]:
            with self.assertRaises(ValueError):measurement_environment('patient',*values)
        with self.assertRaises(ValueError):measurement_environment('invalid')

    def test_signed_flow_raw_preserved_idempotent_and_context_frozen(self):
        e=self.patient()
        samples=[FlowSample(i*.01,i,100,0,f) for i,f in enumerate([-2.,0.,4.])]
        for s in samples:
            s.daily_factor=1.1
            annotate_sample(s,e)
            annotate_sample(s,e)
        self.assertEqual([s.base_flow for s in samples],[-2.,0.,4.])
        self.assertEqual(samples[0],(0.,0,100,0))
        self.assertEqual(sp.flujos_de_muestras(samples),
                         [-2*1.1*e['factor_negative'],0.,4*1.1*e['factor_positive']])
        with self.assertRaises(ValueError):annotate_sample(samples[0],measurement_environment('syringe'))
        worker=MeasurementWorker(e)
        e['conditions']['temperature_C']=25.
        self.assertEqual(samples[0].environment['conditions']['temperature_C'],22.)
        self.assertEqual(worker.environment['conditions']['temperature_C'],22.)

    def test_live_final_and_cli_export_apply_once(self):
        e=self.patient()
        samples=[FlowSample(i*.01,i%128,10000 if i<200 else 0,0,4. if i<200 else 0.)
                 for i in range(450)]
        for s in samples:annotate_sample(s,e)
        p=sp.calcular_parametros(samples)
        factor=e['factor_positive']
        self.assertAlmostEqual(p['fvc'],8*factor,places=11)
        self.assertAlmostEqual(p['fev1'],4*factor,places=11)
        self.assertEqual(p['environment'],e)
        curve=sp.calcular_curva_parcial(samples)
        self.assertAlmostEqual(max(v for t,v,f in curve),p['fvc'],places=11)
        with tempfile.TemporaryDirectory() as tmp, working_directory(tmp), \
                patch.object(sp,'guardar_curvas_html'),patch.object(sp,'curva_ascii'), \
                contextlib.redirect_stdout(io.StringIO()):
            sp.mostrar_resultados(samples)
            saved=json.loads(next(Path(tmp).glob('*.processing.json')).read_text())
            self.assertEqual(saved['environment'],e)
            self.assertAlmostEqual(saved['fvc'],p['fvc'])
            lines=next(Path(tmp).glob('*.csv')).read_text().splitlines()
            self.assertAlmostEqual(float(lines[1].split(',')[2]),4*factor,places=5)

    def test_usb_measurement_callback_already_has_environment(self):
        payload=b''.join(struct.pack('<BHHB',i%128,32768+2000,32768+100,255)
                         for i in range(30))
        class Device:
            _cpfs_session=StreamSession(FlowProcessor())
            def read(self,*args,**kwargs):return payload
        env=self.patient()
        seen=[]
        def callback(s):
            self.assertEqual(s.environment,env)
            self.assertAlmostEqual(sp.flujos_de_muestras([s])[0],
                                   s.base_flow*s.daily_factor*env['factor_positive'])
            seen.append(s)
        with contextlib.redirect_stdout(io.StringIO()):
            data=sp.medir(Device(),on_sample=callback,should_stop=lambda:bool(seen),environment=env)
        self.assertEqual(len(data),30)
        self.assertEqual(data,seen)


if __name__=='__main__':unittest.main()
