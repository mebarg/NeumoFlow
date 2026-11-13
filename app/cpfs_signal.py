"""CPFS USB signal reconstruction, independent of USB, GUI and clinical metrics.

Evidence and verification scope: docs/cpfs-signal.md. Input is signed ADC counts.
One processor belongs to one uninterrupted 100 Hz stream.
"""
from bisect import bisect_right
from collections import deque
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import struct

MODEL_ID = "cpfs-lup1-iir-v1"
TABLE_SHA256 = "c801546fd4fefaba7eff4f2445d116552658281982a4b17e381e391a073e72a2"
GAIN_INS = 1.89075684033629
GAIN_ESP = 1.83815531834252
RATE = 100


class VoltageFilter:
    def __init__(self):
        self.x, self.y = [], []
        self.count = 0
        self.accumulator = 0.0

    def step(self, value):
        a = (1., -1.5704, 1.2756, -.4844, .0762)
        b = (.0186, .0743, .1114, .0743, .0186)
        self.count += 1
        result = value
        if len(self.x) >= 4:
            result = b[0] * value
            for i in range(1, 5):
                result += b[i] * self.x[-i]
            for i in range(1, 5):
                result -= a[i] * self.y[-i]
        self.x.append(value)
        self.y.append(result)
        self.x, self.y = self.x[-4:], self.y[-4:]
        if self.count <= 8:
            self.accumulator += 1.0035 * value
            return self.accumulator / self.count
        if self.count <= 20:
            self.accumulator += result
            return self.accumulator / self.count
        return result


class FlowTable:
    def __init__(self, coefficients):
        if len(coefficients) != 1025 or not all(math.isfinite(c) for c in coefficients):
            raise ValueError("La tabla CPFS debe contener 1025 coeficientes finitos")
        self.inputs = tuple(-10 + i * 20 / 1024 for i in range(1025))
        self.outputs = tuple(x * c for x, c in zip(self.inputs, coefficients))

    def __call__(self, value):
        i = max(0, min(1023, bisect_right(self.inputs, value) - 1))
        x0, x1 = self.inputs[i:i + 2]
        y0, y1 = self.outputs[i:i + 2]
        return y0 + (y1 - y0) * ((value - x0) / (x1 - x0))


@lru_cache(maxsize=1)
def default_table():
    data = (Path(__file__).parent / "data" / "lup1.cfg").read_bytes()
    if hashlib.sha256(data).hexdigest() != TABLE_SHA256:
        raise ValueError("La tabla CPFS no coincide con el perfil verificado")
    return FlowTable(tuple(float(line) for line in data.decode("ascii").splitlines() if line.strip()))


class RangeMixer:
    def __init__(self):
        self.high = False
        self.count = 0

    def step(self, voltage, low, high):
        magnitude = abs(voltage)
        if magnitude > 9.5:
            self.high = True
            self.count = 0
        elif self.high:
            self.count += 1
            if self.count >= 10 or abs(high) < .3 or low <= 1.1 * high and .9 * high <= low:
                self.high = False
        if self.high:
            return high
        if magnitude <= 8.5:
            return low
        weight = (magnitude - 8.5)
        return (1 - weight) * low + weight * high


class StickyZero:
    def __init__(self):
        self.accumulated = 0.
        self.sign = False
        self.count = 0

    def step(self, value):
        negative = value < 0
        out = value
        if self.count > 0 and negative != self.sign:
            self.accumulated = 0.
            out = 0.
        elif abs(self.accumulated) <= .15:
            self.accumulated += value
            if abs(self.accumulated) <= .15:
                out = 0.
        self.sign = negative
        self.count += 1
        return out


class FlowProcessor:
    def __init__(self, low_zero=0., high_zero=0., table=None):
        if not all(math.isfinite(v) for v in (low_zero, high_zero)):
            raise ValueError("Ceros de sesión no finitos")
        self.low_zero, self.high_zero = low_zero, high_zero
        self.filters = VoltageFilter(), VoltageFilter()
        self.mixer, self.sticky = RangeMixer(), StickyZero()
        self.table = default_table() if table is None else table

    def step(self, low_raw, high_raw):
        lv, hv = [f.step((raw + .5) * 20 / 65535)
                  for f, raw in zip(self.filters, (low_raw, high_raw))]
        filtered = lv, hv
        lv -= self.low_zero
        hv -= self.high_zero
        low = 0. if abs(lv) < .006 else .461 * math.copysign(math.sqrt(abs(lv)), lv)
        high = 3.16227766016838 * math.copysign(math.sqrt(abs(hv)), hv)
        mixed = 1.2 * self.mixer.step(lv, low, high)
        sticky = self.sticky.step(mixed)
        value = self.table(sticky)
        flow = value * (GAIN_INS if value <= 0 else GAIN_ESP)
        self.last_trace = (*filtered, lv, hv, low, high, mixed, sticky, value, flow)
        return flow


class FlowSample(tuple):
    """Preserves the existing four raw fields; adds an already processed flow."""
    def __new__(cls, t, seq, low, high, base_flow):
        obj = super().__new__(cls, (t, seq, low, high))
        obj.base_flow = base_flow
        obj.daily_factor = 1.
        return obj


class StreamSession:
    """Keeps parser leftovers and signal history between calibration strokes."""
    def __init__(self, processor, daily_factors=(1., 1.), recorder=None):
        self.processor = processor
        self.recorder = recorder
        self.daily_factors = daily_factors  # expiration, inspiration; frozen for this stream
        self.buffer = bytearray()
        self.samples = deque()
        self.expected = None
        self.count = 0
        self.synchronized = False
        self.startup_discarded = 0
        self.startup_prefix = bytearray()

    def feed(self, chunk):
        self.buffer.extend(chunk)
        # SRA echoes ASCII before the binary stream. An ADC byte can also be
        # 0xff, so a single candidate frame is not enough to establish framing.
        if not self.synchronized:
            while len(self.buffer) >= 18:
                seqs = [self.buffer[i] for i in (0, 6, 12)]
                framed = all(self.buffer[i] == 255 for i in (5, 11, 17))
                consecutive = (all(s < 128 for s in seqs)
                               and seqs[1] == (seqs[0] + 1) % 128
                               and seqs[2] == (seqs[1] + 1) % 128)
                if framed and consecutive:
                    self.synchronized = True
                    if self.recorder is not None:
                        self.recorder.event('parser_synchronized', first_seq=seqs[0],
                                            discarded_bytes=self.startup_discarded,
                                            prefix_hex=self.startup_prefix.hex())
                    break
                if len(self.startup_prefix) < 64:
                    self.startup_prefix.append(self.buffer[0])
                self.startup_discarded += 1
                del self.buffer[0]
            if not self.synchronized:
                return
        while len(self.buffer) >= 6:
            if self.buffer[5] != 255 or self.buffer[0] > 127:
                if self.recorder is not None:
                    self.recorder.event('parser_error', expected_seq=self.expected,
                                        buffer_hex=self.buffer[:24].hex())
                raise RuntimeError("Trama USB inválida durante la adquisición; reiniciá la sesión")
            seq, lo, hi, _ = struct.unpack("<BHHB", self.buffer[:6])
            del self.buffer[:6]
            if self.expected is not None and seq != self.expected:
                if self.recorder is not None:
                    self.recorder.event('sequence_error', expected_seq=self.expected, received_seq=seq)
                raise RuntimeError(f"Se perdieron muestras USB (esperada {self.expected}, recibida {seq}); reiniciá la adquisición")
            self.expected = (seq + 1) & 127
            lo, hi = lo - 32768, hi - 32768
            flow = self.processor.step(lo, hi)
            sample = FlowSample(self.count / RATE, seq, lo, hi, flow)
            sample.sample_index = self.count
            sample.daily_factor = self.daily_factors[0 if flow >= 0 else 1]
            sample.signal_metadata = {
                "model": MODEL_ID, "table_sha256": TABLE_SHA256,
                "zero_low_V": self.processor.low_zero, "zero_high_V": self.processor.high_zero,
                "daily_factor_esp": self.daily_factors[0], "daily_factor_ins": self.daily_factors[1],
            }
            self.samples.append(sample)
            if self.recorder is not None:
                self.recorder.sample(sample, self.processor.last_trace)
            self.count += 1


def estimate_zero(raw_pairs):
    """Digital stationary zero in measurement mode; does not emulate the DAC loop."""
    filters = VoltageFilter(), VoltageFilter()
    volts = [[f.step((raw + .5) * 20 / 65535) for f, raw in zip(filters, pair)]
             for pair in raw_pairs]
    if len(volts) < 220:
        raise RuntimeError("Faltan muestras para medir el cero; revisá la conexión")
    stable = volts[-200:]
    means = tuple(sum(row[j] for row in stable) / len(stable) for j in range(2))
    spans = tuple(max(row[j] for row in stable) - min(row[j] for row in stable) for j in range(2))
    if abs(means[0]) >= .3 or abs(means[1]) >= 1 or spans[0] >= .025 or spans[1] >= .05:
        failures = []
        if abs(means[0]) >= .3:
            failures.append("media Lo fuera de ±0.300 V")
        if abs(means[1]) >= 1:
            failures.append("media Hi fuera de ±1.000 V")
        if spans[0] >= .025:
            failures.append("variación Lo ≥0.025 V")
        if spans[1] >= .05:
            failures.append("variación Hi ≥0.050 V")
        raise RuntimeError(
            "Cero inestable o fuera de rango: " + "; ".join(failures) + ". "
            f"Medias Lo={means[0]:+.8f} V, Hi={means[1]:+.8f} V; "
            f"variación pico a pico Lo={spans[0]:.8f} V, Hi={spans[1]:.8f} V "
            f"sobre {len(stable)} muestras. Mantené el sensor inmóvil durante la inicialización."
        )
    return means
