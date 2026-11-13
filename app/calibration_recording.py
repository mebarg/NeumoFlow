"""Local diagnostic recordings; never changes a signal or calibration factor."""
import csv
from datetime import datetime
import json
from pathlib import Path

from app.cpfs_signal import MODEL_ID, TABLE_SHA256, GAIN_ESP, GAIN_INS
from app.paths import ensure_user_data_dir


class CalibrationRecording:
    def __init__(self, environment=None, root=None):
        root = Path(root) if root is not None else ensure_user_data_dir() / 'calibration-recordings'
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.path.mkdir()
        self.phase = 'initialization'
        self.count = 0
        self.info = {'schema': 1, 'created_at': datetime.now().isoformat(),
                     'model': MODEL_ID, 'table_sha256': TABLE_SHA256, 'sample_rate_Hz': 100,
                     'profile_gains': {'expiration': GAIN_ESP, 'inspiration': GAIN_INS},
                     'environment': environment, 'status': 'recording'}
        self._write_info()
        self.csv_file = (self.path / 'samples.csv').open('w', newline='', encoding='utf-8')
        self.writer = csv.writer(self.csv_file)
        self.writer.writerow(['phase', 'record_index', 'sample_index', 'time_s', 'seq',
                              'low_raw', 'high_raw', 'daily_factor',
                              'filtered_low_V', 'filtered_high_V', 'corrected_low_V', 'corrected_high_V',
                              'low_range', 'high_range', 'mixed', 'sticky', 'lookup', 'base_flow_Lps'])
        self.events_file = (self.path / 'events.jsonl').open('w', encoding='utf-8')

    def _write_info(self):
        (self.path / 'session.json').write_text(json.dumps(self.info, indent=2, ensure_ascii=False), encoding='utf-8')

    def sample(self, sample, trace):
        self.writer.writerow([self.phase, self.count, sample.sample_index, sample[0], sample[1],
                              sample[2], sample[3], sample.daily_factor, *trace])
        self.count += 1

    def event(self, kind, **data):
        self.events_file.write(json.dumps({'event': kind, 'at': datetime.now().isoformat(),
                                           'phase': self.phase, **data}, ensure_ascii=False) + '\n')
        self.events_file.flush()

    def zero_ready(self, low, high, daily_factors):
        self.info.update(zero_low_V=low, zero_high_V=high, daily_factors=list(daily_factors))
        self.event('zero_ready', low_V=low, high_V=high)
        self.phase = 'calibration'
        self._write_info()

    def close(self, error=None):
        self.csv_file.close()
        self.events_file.close()
        self.info.update(status='error' if error else 'finished', error=error, samples=self.count,
                         ended_at=datetime.now().isoformat())
        self._write_info()
