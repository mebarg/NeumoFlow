import gzip
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from app.cpfs_signal import (
    FlowProcessor, FlowSample, RangeMixer, StreamSession, default_table,
    estimate_zero, MODEL_ID, TABLE_SHA256,
)
from app import spirometry

FIXTURE = Path(__file__).parent / "fixtures/wfa_low_flow.json.gz"


class SignalTests(unittest.TestCase):
    def test_recorded_wfa_full_coverage_and_rounding(self):
        fixture = json.loads(gzip.decompress(FIXTURE.read_bytes()))
        count = 0
        for case in fixture['cases']:
            processor = FlowProcessor(fixture['zeroes']['low'], fixture['zeroes']['high'])
            flows = [processor.step(*pair) for pair in case['raw_pairs']]
            flows = flows[case['offset']:case['offset'] + len(case['expected_flow'])]
            self.assertEqual(len(flows), len(case['expected_flow']))
            self.assertLessEqual(max(abs(x-y) for x, y in zip(flows, case['expected_flow'])), 5e-6)
            sign = 1 if '_push_' in case['name'] else -1
            start, end = case['window']
            volume = sum(max(sign*x, 0) for x in flows[start:end+1]) / 100
            self.assertLess(abs(volume - case['reference_volume_L']), 1e-6)
            count += len(flows)
        self.assertEqual(count, 2452)

    def test_table_nodes_midpoints_and_extrapolation(self):
        table = default_table()
        for x, y in zip(table.inputs, table.outputs):
            self.assertEqual(table(x), y)
        for i in range(1024):
            self.assertAlmostEqual(table((table.inputs[i] + table.inputs[i+1])/2),
                                   (table.outputs[i] + table.outputs[i+1])/2, places=14)
        self.assertEqual(table(-11), -11)
        self.assertEqual(table(11), 11)
        self.assertEqual(table(0), 0)

    def test_range_hold_and_release(self):
        # Branch arithmetic checks, not a hardware high-flow validation.
        mix = RangeMixer()
        self.assertEqual(mix.step(8.5, 2, 4), 2)
        self.assertEqual(mix.step(9, 2, 4), 3)
        self.assertEqual(mix.step(9.6, 2, 4), 4)
        for _ in range(9):
            self.assertEqual(mix.step(8, 2, 4), 4)
        self.assertEqual(mix.step(8, 2, 4), 2)
        mix.step(-9.6, -2, -4)
        self.assertEqual(mix.step(-8, -2, -.2), -2)

    def test_chunking_and_queue_keep_filter_history(self):
        raw = [(int(900 * math.sin(i / 25)), int(70 * math.sin(i/25))) for i in range(900)]
        frames = b''.join(struct.pack('<BHHB', i % 128, lo+32768, hi+32768, 255)
                          for i, (lo, hi) in enumerate(raw))
        whole = StreamSession(FlowProcessor())
        whole.feed(frames)
        split = StreamSession(FlowProcessor())
        popped = []
        for i in range(0, len(frames), 29):
            split.feed(frames[i:i+29])
            if i % 3 == 0 and split.samples:
                popped.append(split.samples.popleft())
        popped.extend(split.samples)
        self.assertEqual([s.base_flow for s in whole.samples], [s.base_flow for s in popped])
        self.assertEqual(list(whole.samples), popped)
        self.assertFalse(split.buffer)

    def test_sequence_gap_stops_instead_of_inventing_data(self):
        session = StreamSession(FlowProcessor())
        for seq in [127, 0, 1]:
            session.feed(struct.pack('<BHHB', seq, 32768, 32768, 255))
        with self.assertRaisesRegex(RuntimeError, 'perdieron'):
            session.feed(struct.pack('<BHHB', 3, 32768, 32768, 255))

    def test_sra_echo_and_adc_ff_do_not_create_a_false_first_sample(self):
        # Observed false sample: seq0x41='A', low bytes0d00 -> -32755.
        # The 0xff byte here belongs to the high ADC, not to the delimiter.
        payload = b'SRA\r' + b''.join(struct.pack('<BHHB', seq, 32769, 32767, 255)
                                        for seq in range(30))
        session = StreamSession(FlowProcessor())
        for byte in payload:
            session.feed(bytes([byte]))
        self.assertTrue(session.synchronized)
        self.assertEqual(session.startup_discarded, 4)
        self.assertEqual(bytes(session.startup_prefix), b'SRA\r')
        self.assertEqual(len(session.samples), 30)
        self.assertEqual([s[1] for s in session.samples], list(range(30)))
        self.assertTrue(all(s[2:4] == (1, -1) for s in session.samples))

    def test_in_stream_framing_error_is_not_silently_resynchronized(self):
        session = StreamSession(FlowProcessor())
        session.feed(b''.join(struct.pack('<BHHB', seq, 32768, 32768, 255) for seq in range(3)))
        with self.assertRaisesRegex(RuntimeError, 'Trama USB inválida'):
            session.feed(struct.pack('<BHHB', 3, 32768, 32768, 254))

    def test_zero_requires_stability_and_enough_data(self):
        low, high = estimate_zero([(5, -2)] * 250)
        self.assertGreater(low, 0)
        self.assertLess(high, 0)
        with self.assertRaises(RuntimeError):
            estimate_zero([(0, 0)] * 100)
        with self.assertRaisesRegex(RuntimeError, 'Medias Lo=.*variación pico a pico'):
            estimate_zero([(i*20, 0) for i in range(250)])

    def test_live_and_final_reuse_cached_flow_and_frozen_factors(self):
        session = StreamSession(FlowProcessor(), (1.02, .99))
        session.feed(b''.join(struct.pack('<BHHB', i % 128, 32768+3000, 32768+200, 255)
                              for i in range(300)))
        samples = list(session.samples)
        before = session.processor.filters[0].count
        expected = [s.base_flow*s.daily_factor for s in samples]
        with patch.object(spirometry, 'FACTOR_ESP', 5.):
            spirometry.calcular_curva_parcial(samples, 100)
            spirometry.calcular_parametros(samples, 100)
            self.assertEqual(spirometry.flujos_de_muestras(samples), expected)
        self.assertEqual(session.processor.filters[0].count, before)

    def test_old_calibration_is_preserved_and_not_applied(self):
        old = dict(spirometry._cal)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                legacy = Path(tmp)/'calibracion.json'
                legacy.write_text(json.dumps({'factor_esp': 3., 'factor_ins': 4., 'temperatura_C': 22}))
                new = Path(tmp)/'calibracion_cpfs_v1.json'
                content = legacy.read_bytes()
                with patch.object(spirometry, 'CAL_FILE', str(new)), \
                     patch.object(spirometry, 'CAL_LEGACY_FILE', str(legacy)):
                    spirometry.aplicar_calibracion(spirometry.cargar_calibracion())
                    self.assertEqual((spirometry.FACTOR_ESP, spirometry.FACTOR_INS), (1., 1.))
                    self.assertEqual(spirometry._cal['fecha'], 'pendiente')
                    cal = {'factor_esp': 1.01, 'factor_ins': .99}
                    spirometry.guardar_calibracion(cal)
                    spirometry.aplicar_calibracion(spirometry.cargar_calibracion())
                    self.assertEqual((spirometry.FACTOR_ESP, spirometry.FACTOR_INS), (1.01, .99))
                    self.assertEqual(cal['signal_model'], MODEL_ID)
                    self.assertEqual(cal['table_sha256'], TABLE_SHA256)
                self.assertEqual(legacy.read_bytes(), content)
        finally:
            spirometry.aplicar_calibracion(old)

    def test_calibration_base_is_not_multiplied_twice(self):
        result = spirometry.calcular_resultado_calibracion(
            [{'vol_modelo': 2.9}], [{'vol_modelo': -3.1}], 22, 764, 86)
        self.assertAlmostEqual(2.9 * result['factor_esp'], 3.)
        self.assertAlmostEqual(3.1 * result['factor_ins'], 3.)

    def test_two_strokes_do_not_drop_read_ahead_samples(self):
        raw = [(0, 0)] * 250 + [(2500, 100)] * 250 + [(0, 0)] * 170
        raw += [(-2500, -100)] * 250 + [(0, 0)] * 170
        payload = b''.join(struct.pack('<BHHB', i % 128, lo+32768, hi+32768, 255)
                           for i, (lo, hi) in enumerate(raw))

        class Device:
            def __init__(self):
                self.pos = 0
                self._cpfs_session = StreamSession(FlowProcessor(), (2., 3.))

            def read(self, *args, **kwargs):
                if self.pos >= len(payload):
                    raise spirometry.usb.core.USBTimeoutError("simulated timeout")
                chunk = payload[self.pos:self.pos+503]
                self.pos += len(chunk)
                return chunk

        dev = Device()
        first = spirometry.capturar_golpe_calibracion(dev, timeout_s=1)
        consumed = dev._cpfs_session.count - len(dev._cpfs_session.samples)
        self.assertGreater(len(dev._cpfs_session.samples), 0)
        second = spirometry.capturar_golpe_calibracion(dev, timeout_s=1)
        self.assertEqual(first['direction'], 'push')
        self.assertEqual(second['direction'], 'pull')
        self.assertGreater(dev._cpfs_session.count, consumed)
        # Fixed-profile stroke volumes do not include the stream's daily2x/3x multipliers.
        control = Device()
        control._cpfs_session.daily_factors = (1., 1.)
        plain_first = spirometry.capturar_golpe_calibracion(control, timeout_s=1)
        plain_second = spirometry.capturar_golpe_calibracion(control, timeout_s=1)
        self.assertEqual(first['vol_modelo'], plain_first['vol_modelo'])
        self.assertEqual(second['vol_modelo'], plain_second['vol_modelo'])

    def test_initialization_measures_fresh_zero_before_measurement(self):
        baseline = [(5, -2)] * 256
        movement = [(0, 0)] * 25 + [(3000, 200)] * 80

        class Device:
            def __init__(self):
                self.starts = 0
                self.payload = b''

            def start(self):
                self.starts += 1
                # One armed stream must cover zero and the subsequent movement.
                # The firmware requires SAC before a new SRA after QST.
                if self.starts != 1:
                    raise AssertionError('Unexpected stream restart after digital zero')
                pairs = baseline + movement
                self.payload = b''.join(struct.pack('<BHHB', i % 128, lo+32768, hi+32768, 255)
                                        for i, (lo, hi) in enumerate(pairs))

            def read(self, *args, **kwargs):
                if not self.payload:
                    raise spirometry.usb.core.USBTimeoutError("simulated timeout")
                chunk, self.payload = self.payload[:256], self.payload[256:]
                return chunk

        dev = Device()
        def send(_dev, data, **kwargs):
            if data == b'SRA\r':
                dev.start()
        with patch.object(spirometry, 'cp210x_init'), patch.object(spirometry, 'puesta_a_cero', return_value=2000), \
             patch.object(spirometry, 'cmd'), patch.object(spirometry, 'flush'), \
             patch.object(spirometry, 'send_bytes', side_effect=send):
            threshold = spirometry.inicializar(dev)
            self.assertEqual(threshold, 2000)
            samples = spirometry.medir(dev, should_stop=lambda: not dev.payload)
        self.assertEqual(len(samples), len(movement))
        self.assertGreater(dev._cpfs_session.processor.low_zero, 0.)
        self.assertLess(dev._cpfs_session.processor.high_zero, 0.)
        self.assertEqual(samples[0][0], 0.)
        self.assertTrue(all(hasattr(s, 'base_flow') for s in samples))
        self.assertEqual(dev.starts, 1)
        self.assertEqual(dev._cpfs_session.processor.filters[0].count, len(baseline) + len(movement))

    def test_no_samples_error_instead_of_silent_calibration(self):
        class SilentDevice:
            _cpfs_session = StreamSession(FlowProcessor())
            def read(self, *args, **kwargs):
                raise spirometry.usb.core.USBTimeoutError("simulated timeout")
        with patch.object(spirometry.time, 'monotonic', side_effect=[0., 4.]):
            with self.assertRaisesRegex(RuntimeError, 'No llegan muestras'):
                spirometry.capturar_golpe_calibracion(SilentDevice())


if __name__ == '__main__':
    unittest.main()
