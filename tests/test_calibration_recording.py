import csv
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from app.calibration_recording import CalibrationRecording
from app.cpfs_signal import FlowProcessor, StreamSession
from app import spirometry
from app.workers import CalibrationSessionWorker


class RecordingTests(unittest.TestCase):
    def test_stroke_volume_is_reproducible_from_recorded_samples(self):
        raw = [(0, 0)]*250 + [(2500, 100)]*250 + [(0, 0)]*170
        raw += [(-2500, -100)]*250 + [(0, 0)]*170
        frames = b''.join(struct.pack('<BHHB', i % 128, lo+32768, hi+32768, 255)
                          for i, (lo, hi) in enumerate(raw))
        with tempfile.TemporaryDirectory() as tmp:
            recorder = CalibrationRecording({'syringe_volume_L': 3.}, root=tmp)
            class Device:
                def __init__(self):
                    self.pos = 0
                    self._cpfs_session = StreamSession(FlowProcessor(), recorder=recorder)
                def read(self, *args, **kwargs):
                    if self.pos >= len(frames):
                        raise spirometry.usb.core.USBTimeoutError('test end')
                    chunk = frames[self.pos:self.pos+503]
                    self.pos += len(chunk)
                    return chunk
            device = Device()
            recorder.zero_ready(0., 0., (1., 1.))
            strokes = [spirometry.capturar_golpe_calibracion(device, timeout_s=1) for _ in range(2)]
            recorder.close()
            with (recorder.path/'samples.csv').open() as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), device._cpfs_session.count)
            self.assertEqual([int(row['record_index']) for row in rows], list(range(len(rows))))
            events = [json.loads(line) for line in (recorder.path/'events.jsonl').read_text().splitlines()]
            finished = [e for e in events if e['event']=='stroke_finished' and e['valid']]
            self.assertEqual(len(finished), 2)
            for stroke, event in zip(strokes, finished):
                selected = [row for row in rows if event['first_sample'] <= int(row['sample_index']) <= event['last_sample']]
                volume = sum(float(row['base_flow_Lps']) for row in selected)*.01
                self.assertEqual(volume, stroke['vol_modelo'])
                self.assertEqual(volume, event['volume_model_L'])
            # Trace logging must not change numerical processing.
            plain = FlowProcessor()
            for row in rows:
                self.assertEqual(plain.step(int(row['low_raw']), int(row['high_raw'])), float(row['base_flow_Lps']))
            info = json.loads((recorder.path/'session.json').read_text())
            self.assertEqual(info['status'], 'finished')
            self.assertEqual(info['samples'], len(rows))

    def test_worker_preserves_recording_when_zero_initialization_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            def recording(environment):
                item = CalibrationRecording(environment, root=tmp)
                paths.append(item.path)
                return item
            worker = CalibrationSessionWorker(environment={'syringe_volume_L':3.})
            saved, closed = [], []
            worker.recording_saved.connect(saved.append)
            worker.closed.connect(lambda:closed.append(True))
            with patch('app.workers.CalibrationRecording', side_effect=recording), \
                 patch.object(spirometry, 'open_device', return_value=object()), \
                 patch.object(spirometry, 'inicializar', side_effect=RuntimeError('test zero unstable')), \
                 patch.object(spirometry, 'send_bytes'), patch.object(spirometry.usb.util, 'release_interface'):
                worker.run()
            self.assertEqual(saved, [str(paths[0])])
            self.assertEqual(closed, [True])
            info = json.loads((paths[0]/'session.json').read_text())
            self.assertEqual(info['status'], 'error')
            self.assertIn('test zero unstable', info['error'])
