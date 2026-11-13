import traceback
from copy import deepcopy
from queue import Queue, Empty
from threading import Event
import time

from PySide6.QtCore import QObject, Signal, Slot

from app import spirometry
from app.calibration_recording import CalibrationRecording
from app.cpfs_signal import FlowSample, RATE
from app.cpfs_environment import annotate_sample


class StudySessionWorker(QObject):
    """Own one USB stream per study; drain idle data without re-zeroing each effort.

    Public commands only touch thread-safe queues/events. All USB work stays
    in run(), including preparation, explicit zero, idle reads and acquisition.
    """
    status = Signal(str)
    ready = Signal()
    capture_started = Signal()
    effort_marked = Signal(float)
    progress = Signal(object)
    finished = Signal(object, object)
    capture_closed = Signal()
    failed = Signal(str)
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.commands = Queue()
        self.shutdown_requested = Event()
        self.stop_requested = Event()
        self.environment = None

    def start_capture(self, environment, mode="fvc", direction="evc", target_seconds=12):
        self.environment = deepcopy(environment)
        self.stop_requested.clear()
        if mode not in ('fvc','svc','mvv') or direction not in ('evc','ivc') or target_seconds not in (12,15):
            raise ValueError('Configuración de captura inválida')
        self.commands.put(('capture', (self.environment, mode, direction, target_seconds)))

    def mark_effort(self):
        self.commands.put(('mark', None))

    def stop(self):
        self.stop_requested.set()

    def zero(self):
        self.commands.put(('zero', None))

    def shutdown(self):
        self.shutdown_requested.set()
        self.stop_requested.set()

    @Slot()
    def run(self):
        dev = None
        samples = None
        try:
            dev = spirometry.open_device()
            self.status.emit('Puesta a cero: mantené el sensor en reposo')
            threshold = spirometry.inicializar(dev)
            last_data = time.monotonic()
            environment = None
            mode, direction, target_seconds, marker_time = "fvc", "evc", 12, None
            first_index = None
            self.status.emit('Listo')
            self.ready.emit()
            while not self.shutdown_requested.is_set():
                try:
                    command, payload = self.commands.get_nowait()
                except Empty:
                    command = None
                if command == 'zero' and samples is None:
                    self.status.emit('Puesta a cero: mantené el sensor en reposo')
                    spirometry.send_bytes(dev, b'QST\r')
                    spirometry.flush(dev)
                    threshold = spirometry.inicializar(dev)
                    last_data = time.monotonic()
                    self.status.emit('Listo')
                    self.ready.emit()
                elif command == 'capture' and samples is None:
                    # Already parsed idle samples precede the Start command.
                    dev._cpfs_session.samples.clear()
                    samples, first_index = [], None
                    environment, mode, direction, target_seconds = deepcopy(payload)
                    marker_time = None
                    self.status.emit('Capturando')
                    self.capture_started.emit()

                elif command == 'mark' and samples is not None and mode != 'fvc' and marker_time is None:
                    marker_time = len(samples)/RATE
                    self.effort_marked.emit(marker_time)
                    self.status.emit('Esfuerzo lento' if mode == 'svc' else 'Intervalo MVV en curso')

                if samples is not None and self.stop_requested.is_set():
                    if mode == 'fvc':
                        params = spirometry.calcular_parametros(samples, umbral_inicio=threshold,
                                                               environment=environment)
                    else:
                        from app.respiratory_measurements import analyze_samples
                        params = analyze_samples(samples, mode, marker_time, direction, target_seconds, environment)
                    if params is not None and samples:
                        params['signal'] = samples[0].signal_metadata
                    self.finished.emit(samples, params)
                    self.capture_closed.emit()
                    samples = None

                try:
                    chunk = bytes(dev.read(spirometry.EP_IN, 128, timeout=100))
                except spirometry.usb.core.USBTimeoutError:
                    if time.monotonic() - last_data > 3:
                        raise RuntimeError('No llegan muestras USB; revisá la conexión y repetí Flujo cero')
                    continue
                if not chunk:
                    if time.monotonic() - last_data > 3:
                        raise RuntimeError('No llegan muestras USB; revisá la conexión y repetí Flujo cero')
                    continue
                session = dev._cpfs_session
                before = session.count
                session.feed(chunk)
                if session.count != before:
                    last_data = time.monotonic()
                elif time.monotonic() - last_data > 3:
                    raise RuntimeError('No llegan muestras USB válidas; repetí Flujo cero')
                while session.samples:
                    original = session.samples.popleft()
                    if samples is None:
                        continue
                    if first_index is None:
                        first_index = original.sample_index
                    sample = FlowSample((original.sample_index-first_index)/RATE,
                                        original[1],original[2],original[3],original.base_flow)
                    sample.__dict__.update(original.__dict__)
                    annotate_sample(sample, environment)
                    samples.append(sample)
                    if len(samples) % 5 == 0:
                        self.progress.emit(spirometry.calcular_curva_parcial(samples))
                    limit = 30 if mode == 'fvc' else 60
                    if len(samples) >= limit*RATE or (mode == 'mvv' and marker_time is not None and
                            len(samples)/RATE >= marker_time+target_seconds-1e-7):
                        self.stop_requested.set()
                        break
                # No QST here: zero, filters and parser state survive each capture.
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            if dev is not None:
                try:
                    spirometry.send_bytes(dev,b'QST\r')
                except Exception:
                    pass
                try:
                    spirometry.usb.util.release_interface(dev,0)
                    spirometry.usb.util.dispose_resources(dev)
                except Exception:
                    pass
            self.closed.emit()


class MeasurementWorker(QObject):
    status = Signal(str)
    progress = Signal(object)
    maneuver_detected = Signal()
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, environment=None):
        super().__init__()
        self._stop_requested = False
        self.environment = deepcopy(environment if environment is not None else
                                    spirometry.contexto_ambiental_medicion('syringe'))

    @Slot()
    def stop(self):
        self._stop_requested = True

    @Slot()
    def run(self):
        dev = None
        try:
            dev = spirometry.open_device()
            self.status.emit("Inicializando: mantené el sensor en reposo")
            umbral = spirometry.inicializar(dev)
            self.status.emit("Esperando maniobra")
            live_samples = []
            maneuver_seen = False

            def on_sample(sample):
                nonlocal maneuver_seen
                live_samples.append(sample)
                if not maneuver_seen and sample[2] > umbral:
                    maneuver_seen = True
                    self.maneuver_detected.emit()
                if len(live_samples) % 5 == 0:
                    self.progress.emit(spirometry.calcular_curva_parcial(live_samples, umbral_inicio=umbral))

            muestras = spirometry.medir(
                dev,
                umbral=umbral,
                on_sample=on_sample,
                should_stop=lambda: self._stop_requested,
                environment=self.environment,
            )
            params = spirometry.calcular_parametros(muestras, umbral_inicio=umbral,
                                                   environment=self.environment)
            if params is not None and muestras:
                params["signal"] = muestras[0].signal_metadata
            spirometry.send_bytes(dev, b"QST\r")
            self.finished.emit(muestras, params)
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            if dev is not None:
                try:
                    spirometry.send_bytes(dev, b"QST\r")
                except Exception:
                    pass
                try:
                    spirometry.usb.util.release_interface(dev, 0)
                except Exception:
                    pass


class CalibrationSessionWorker(QObject):
    status = Signal(str)
    progress = Signal(object)
    stroke_finished = Signal(object)
    ready = Signal()
    closed = Signal()
    failed = Signal(str)
    recording_saved = Signal(str)

    def __init__(self, environment=None):
        super().__init__()
        self._shutdown = False
        self.environment = environment

    @Slot()
    def shutdown(self):
        self._shutdown = True

    @Slot()
    def run(self):
        dev = None
        recording = None
        error = None
        try:
            dev = spirometry.open_device()
            recording = CalibrationRecording(self.environment)
            print(f"  Registro de calibración: {recording.path}", flush=True)
            self.status.emit("Inicializando: mantené el sensor en reposo")
            spirometry.inicializar(dev, recorder=recording)
            self.status.emit("Calibracion lista")
            self.ready.emit()
            while not self._shutdown:
                self.status.emit("Captura continua activa")
                golpe = spirometry.capturar_golpe_calibracion(
                    dev,
                    should_stop=lambda: self._shutdown,
                    on_sample=self.progress.emit,
                )
                self.stroke_finished.emit(golpe)
                if not self._shutdown:
                    self.status.emit("Calibracion lista")
            spirometry.send_bytes(dev, b"QST\r")
        except Exception:
            error = traceback.format_exc()
            if recording is not None:
                try:
                    recording.event('error', traceback=error)
                except OSError:
                    pass
            self.failed.emit(error)
        finally:
            if dev is not None:
                try:
                    spirometry.send_bytes(dev, b"QST\r")
                except Exception:
                    pass
                try:
                    spirometry.usb.util.release_interface(dev, 0)
                except Exception:
                    pass
            if recording is not None:
                try:
                    recording.close(error)
                    self.recording_saved.emit(str(recording.path))
                    print(f"  Registro guardado: {recording.path}", flush=True)
                except Exception:
                    self.failed.emit(traceback.format_exc())
            self.closed.emit()
