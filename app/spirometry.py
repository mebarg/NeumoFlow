#!/usr/bin/env python3
"""
Medición FVC con el espirómetro CPFS/D USB.

Protocolo confirmado: 57600 baud, 8N1, sin flow control.
Stream: 100 Hz, 6 bytes por muestra [seq][ch1 uint16 LE][ch2 uint16 LE][0xFF]
  ch1 = LoFlowV raw: rango bajo, alta sensibilidad
  ch2 = HiFlowV raw: rango alto, usado cuando ch1 se acerca a saturación

Los dos canales son uint16 little-endian con cero en 0x8000.

DUAL_RANGE=True activa el auto-ranging; si los resultados empeoran, desactivar.

Uso:
  sudo python3 medir.py               # medición normal
  sudo python3 medir.py --calibrar    # calibración con jeringa de 3L
  sudo python3 medir.py --legacy-linear  # escala lineal antigua solo para diagnóstico
"""
import usb.core
import usb.util
import usb.backend.libusb1
import struct
import time
import sys
import json
import os
import math
import select
from datetime import datetime
from pathlib import Path

from app.paths import ensure_user_data_dir
from app.cpfs_signal import (
    MODEL_ID, TABLE_SHA256, FlowProcessor, StreamSession, estimate_zero,
)

try:
    import libusb_package
except ImportError:  # pragma: no cover - optional runtime backend helper
    libusb_package = None

VID, PID  = 0x0ee5, 0x0103
EP_OUT, EP_IN = 0x01, 0x81

# CP210x vendor requests
REQTYPE_H2D = 0x41
REQTYPE_D2H = 0xC1


def find_libusb_package_library():
    if libusb_package is None:
        return None

    package_result = libusb_package.find_library("usb-1.0")
    if package_result:
        return str(package_result)

    package_dir = Path(libusb_package.__file__).resolve().parent
    matches = sorted(package_dir.rglob("libusb-1.0.dll"))
    return str(matches[0]) if matches else None


def get_usb_backend():
    if libusb_package is None:
        return None

    libusb_path = find_libusb_package_library()
    if libusb_path:
        return usb.backend.libusb1.get_backend(find_library=lambda _name: libusb_path)

    return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)


def find_device():
    backend = get_usb_backend()
    if backend is not None:
        return usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    return usb.core.find(idVendor=VID, idProduct=PID)


def open_device():
    dev = find_device()
    if dev is None:
        raise RuntimeError("Dispositivo no encontrado")

    try:
        config = dev.get_active_configuration()
        for iface in range(config.bNumInterfaces):
            try:
                if dev.is_kernel_driver_active(iface):
                    dev.detach_kernel_driver(iface)
            except (NotImplementedError, usb.core.USBError):
                pass
    except usb.core.USBError:
        pass

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    return dev


def cp210x_init(dev):
    reqs = [
        (0x11, 0x0000, 0,  None),                              # RESET
        (0x00, 0x0001, 0,  None),                              # IFC_ENABLE
        (0x13, 0x0000, 16, bytes.fromhex("01000000400000000000000000000000")),  # SET_FLOW 1
        (0x01, 0x0040, 0,  None),                              # SET_BAUDDIV → 57600
        (0x07, 0x0202, 0,  None),                              # SET_MHS RTS=1
        (0x07, 0x0101, 0,  None),                              # SET_MHS DTR=1
        (0x03, 0x0800, 0,  None),                              # SET_LINE_CTL 8N1
        (0x13, 0x0000, 16, bytes.fromhex("010000004000000000700000001c0000")),  # SET_FLOW 2
    ]
    for req, wval, wlen, data in reqs:
        if data:
            dev.ctrl_transfer(REQTYPE_H2D, req, wval, 0, list(data))
        else:
            dev.ctrl_transfer(REQTYPE_H2D, req, wval, 0, [])
    time.sleep(0.05)


def send_bytes(dev, data, byte_delay=0.002):
    for b in b"     " + data:
        dev.write(EP_OUT, bytes([b]), timeout=1000)
        time.sleep(byte_delay)


def read_resp(dev, timeout_ms=400):
    buf = b""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        try:
            buf += bytes(dev.read(EP_IN, 64, timeout=50))
            deadline = time.time() + 0.08
        except usb.core.USBTimeoutError:
            pass
    return buf


def cmd(dev, data, label):
    send_bytes(dev, data)
    r = read_resp(dev)
    r_ascii = "".join(chr(b) if 32 <= b < 127 else f"\\x{b:02x}" for b in r)
    ok = "✓" if r else "✗"
    print(f"  {label:<20} → {r_ascii!r:30} {ok}")
    return r


def flush(dev, ms=300):
    """Descarta datos pendientes en el buffer IN."""
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        try:
            dev.read(EP_IN, 256, timeout=50)
        except usb.core.USBTimeoutError:
            break


def puesta_a_cero(dev):
    """
    Fase 1: calibración/puesta a cero con WFC=0x80.
    Mide el ruido de línea de base → umbral dinámico para detectar maniobra.
    """
    print("► Puesta a cero (WFC=0x80)...")
    cmd(dev, b"QST\r",         "QST")
    cmd(dev, b"QST\r",         "QST (x2)")
    cmd(dev, b"TST\r",         "TST (firmware)")
    cmd(dev, b"TIM\r",         "TIM")
    cmd(dev, b"RSS\r",         "RSS")
    cmd(dev, b"DAX\x07\xff\r", "DAX ch.A")
    cmd(dev, b"DAX\x17\xff\r", "DAX ch.B")
    cmd(dev, b"WFC\x80\r",     "WFC=0x80 (zero)")
    cmd(dev, b"SAC\x03\r",     "SAC")
    print("  SRA → midiendo ruido de línea de base (3s)...")
    send_bytes(dev, b"SRA\r")

    # Recolectar muestras de baseline durante 3s
    t0     = time.time()
    buf    = b""
    ruido  = []

    while time.time() - t0 < 3:
        try:
            buf += bytes(dev.read(EP_IN, 128, timeout=100))
        except usb.core.USBTimeoutError:
            pass
        while len(buf) >= 6:
            if buf[5] == 0xff:
                _, _, ch2_hi = decode_sample(buf[:6])
                # En WFC=0x80 el canal LoFlow tiene movimiento mecánico grande;
                # el canal HiFlow es más estable para estimar ruido electrónico.
                ruido.append(abs(ch2_hi))
                buf = buf[6:]
            else:
                buf = buf[1:]

    # Umbral dinámico: media + 5σ, con piso mínimo y techo = 3×max
    # Usar max solo sería susceptible a un outlier puntual.
    # mean + 5σ cubre el 99.9999% de la distribución gaussiana del ruido.
    if ruido:
        noise_max = max(ruido)
        noise_avg = sum(ruido) / len(ruido)
        noise_var = sum((x - noise_avg) ** 2 for x in ruido) / len(ruido)
        noise_std = noise_var ** 0.5
        umbral_stat = noise_avg + 5 * noise_std   # 5-sigma sobre la media
        umbral = max(
            umbral_stat,     # estadístico
            noise_max * 1.5, # al menos 1.5× el máximo real visto
            2000,            # piso absoluto
        )
        print(f"  Ruido base: max={noise_max}  avg={noise_avg:.0f}  std={noise_std:.0f}")
        print(f"  Umbral (5σ): {umbral_stat:.0f}  Umbral final: {umbral:.0f} raw = {umbral*SCALE:.3f} L/s")
    else:
        umbral = 5000
        print(f"  Sin datos de ruido, umbral por defecto: {umbral}")

    cmd(dev, b"QST\r", "QST (stop zero)")
    flush(dev)
    print("  Puesta a cero OK\n")
    return int(umbral)


def inicializar(dev, recorder=None):
    print("► Inicializando CP210x...")
    cp210x_init(dev)

    # BreezeSuite repite TST/TIM/RSS varias veces antes de medir
    for i in range(2):
        cmd(dev, b"QST\r",         f"QST ({i+1})")
        cmd(dev, b"TST\r",         f"TST ({i+1})")
        cmd(dev, b"TIM\r",         f"TIM ({i+1})")
        cmd(dev, b"RSS\r",         f"RSS ({i+1})")

    umbral = puesta_a_cero(dev)

    # Preparar para medición real con WFC=0x00
    print("► Preparando medición (WFC=0x00)...")
    cmd(dev, b"DAX\x07\xff\r", "DAX ch.A")
    cmd(dev, b"DAX\x17\xff\r", "DAX ch.B")
    cmd(dev, b"WFC\x00\r",     "WFC=0x00 (medición)")
    cmd(dev, b"SAC\x03\r",     "SAC")
    print("  Iniciando stream de medición...")
    send_bytes(dev, b"SRA\r")
    # Measure signed offsets in the mode used for acquisition. Never reuse
    # debugger offsets from another session or the absolute noise threshold.
    print("  Midiendo cero digital: mantener el sensor inmóvil...")
    baseline = StreamSession(FlowProcessor(), recorder=recorder)
    raw_pairs = []
    deadline = time.monotonic() + 4
    while len(raw_pairs) < 250 and time.monotonic() < deadline:
        try:
            baseline.feed(bytes(dev.read(EP_IN, 128, timeout=100)))
        except usb.core.USBTimeoutError:
            continue
        while baseline.samples:
            sample = baseline.samples.popleft()
            raw_pairs.append((sample[2], sample[3]))
    low_zero, high_zero = estimate_zero(raw_pairs)
    # Keep the armed ADC stream, parser remainder and voltage-filter history.
    # QST here would stop acquisition; bare SRA does not rearm its channels.
    processor = FlowProcessor(low_zero, high_zero)
    processor.filters = baseline.processor.filters
    baseline.processor = processor
    baseline.daily_factors = (FACTOR_ESP, FACTOR_INS)
    baseline.count = 0
    dev._cpfs_session = baseline
    if recorder is not None:
        recorder.zero_ready(low_zero, high_zero, baseline.daily_factors)
    print(f"  Ceros digitales: Lo={low_zero:+.8f} V Hi={high_zero:+.8f} V")
    print("  OK\n")
    return umbral


def medir(dev, umbral=5000, duracion=30, on_sample=None, should_stop=None, environment=None):
    """
    Captura una maniobra FVC.
    umbral: raw mínimo para considerar flujo real (del baseline medido).
    """
    print("=" * 50)
    print("  INSPIRÁ PROFUNDO... luego SOPLÁ FUERTE")
    print("  La medición termina automáticamente")
    print("=" * 50)

    muestras   = []
    session = dev._cpfs_session
    t0         = time.time()
    ultimo     = t0
    iniciado   = False
    maniobra   = False
    while time.time() - t0 < duracion:
        if should_stop is not None and should_stop():
            print("  ► Fin manual de maniobra", flush=True)
            break

        try:
            chunk = bytes(dev.read(EP_IN, 128, timeout=100))
        except usb.core.USBTimeoutError:
            if iniciado and time.time() - ultimo > 3:
                break
            continue

        if not chunk:
            continue

        session.feed(chunk)
        ultimo = time.time()

        while session.samples:
            muestra = session.samples.popleft()
            if environment is not None:
                from app.cpfs_environment import annotate_sample
                annotate_sample(muestra, environment)
            t, seq, ch1_lo, ch2_hi = muestra
            muestras.append(muestra)
            if on_sample is not None:
                on_sample(muestra)

            if not iniciado:
                iniciado = True
                print(f"  ► Stream activo...", flush=True)

            if ch1_lo > umbral and not maniobra:
                maniobra = True
                print(f"  ► Maniobra detectada (t={t:.2f}s)", flush=True)

    return muestras


DT = 1 / 100   # s por muestra (100 Hz)

# ── Archivo de calibración ────────────────────────────────────────────────────
CAL_BUNDLED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibracion.json")
CAL_FILE = str(ensure_user_data_dir() / "calibracion_cpfs_v1.json")
CAL_LEGACY_FILE = str(ensure_user_data_dir() / "calibracion.json")

CAL_DEFAULT = {
    "volumen_jeringa": 3.00,
    "factor_esp":      1.0,
    "factor_ins":      1.0,
    "temperatura_C":   None,
    "presion_mmHg":    None,
    "humedad_pct":     None,
    "fecha":           "desconocida",
    "nota":            "valor inicial indirecto, recalibrar con jeringa",
}


def cargar_calibracion():
    if os.path.exists(CAL_FILE):
        with open(CAL_FILE) as f:
            return json.load(f)
    # Keep historical files intact. Only environmental metadata transfers;
    # polynomial model factors and strokes belong to a different model.
    cal = CAL_DEFAULT.copy()
    for old_path in (CAL_LEGACY_FILE, CAL_BUNDLED_FILE):
        if os.path.exists(old_path):
            with open(old_path) as f:
                old = json.load(f)
            for key in ("temperatura_C", "presion_mmHg", "humedad_pct"):
                cal[key] = old.get(key)
            break
    return cal


def guardar_calibracion(cal):
    cal.update(signal_model=MODEL_ID, table_sha256=TABLE_SHA256)
    os.makedirs(os.path.dirname(CAL_FILE), exist_ok=True)
    with open(CAL_FILE, "w") as f:
        json.dump(cal, f, indent=2, ensure_ascii=False)
    print(f"  Calibración guardada: {CAL_FILE}")


def aplicar_calibracion(cal):
    """Actualiza en memoria la calibración activa sin reiniciar el proceso."""
    global _cal, SCALE, SCALE_INS, FACTOR_ESP, FACTOR_INS, _btps
    _cal = dict(cal)
    compatible = (_cal.get("signal_model") == MODEL_ID
                  and _cal.get("table_sha256") == TABLE_SHA256)
    if not compatible:
        _cal.update(factor_esp=1.0, factor_ins=1.0, fecha="pendiente",
                    nota="Nuevo modelo CPFS: realizar calibración con jeringa")
    if not all(isinstance(_cal.get(k, 1.), (int, float)) and 0 < _cal.get(k, 1.) < float("inf")
               for k in ("factor_esp", "factor_ins")):
        raise ValueError("Factores de calibración inválidos")
    SCALE = _cal.get("scale_esp") or 0.00017032254548179706
    SCALE_INS = _cal.get("scale_ins") or SCALE
    FACTOR_ESP = _cal.get("factor_esp", 1.0)
    FACTOR_INS = _cal.get("factor_ins", 1.0)
    _btps = btps_factor(_cal.get("temperatura_C"), _cal.get("presion_mmHg"), _cal.get("humedad_pct"))


def capturar_golpe_calibracion(dev, signo=None, should_stop=None, on_sample=None, timeout_s=20):
    """Captura un stroke de calibración y devuelve sus datos crudos y métricas."""
    session = dev._cpfs_session
    t0 = time.time()
    activo = False
    fin_cnt = 0
    muestras = []
    included_indices = []
    curva = []
    pico_dir = 0.0
    volumen = 0.0
    signo_detectado = signo
    last_sample_at = time.monotonic()

    while time.time() - t0 < timeout_s:
        if should_stop is not None and should_stop():
            break
        if not session.samples:
            try:
                previous_count = session.count
                session.feed(bytes(dev.read(EP_IN, 128, timeout=200)))
                if session.count > previous_count:
                    last_sample_at = time.monotonic()
            except usb.core.USBTimeoutError:
                pass
            if time.monotonic() - last_sample_at > 3:
                raise RuntimeError("No llegan muestras del espirómetro después del cero; detené y reiniciá la calibración")

        while session.samples:
            sample = session.samples.popleft()
            # Calibration uses the fixed profile without daily multipliers.
            flow = sample.base_flow
            if signo_detectado is None and abs(flow) > 0.05:
                signo_detectado = 1 if flow > 0 else -1
            flow_dir = flow * signo_detectado if signo_detectado is not None else 0.0

            if flow_dir > 0.05:
                if not activo and session.recorder is not None:
                    session.recorder.event('stroke_started', sample_index=sample.sample_index,
                                           direction='push' if signo_detectado > 0 else 'pull')
                activo = True
                fin_cnt = 0
                muestras.append(flow)
                included_indices.append(sample.sample_index)
                pico_dir = max(pico_dir, flow_dir)
            elif activo:
                if flow_dir < 0.025:
                    fin_cnt += 1
                    if fin_cnt >= 50:
                        break
                muestras.append(flow)
                included_indices.append(sample.sample_index)

            if activo:
                volumen += flow * DT
                punto = (len(muestras) * DT, volumen, flow)
                curva.append(punto)
                if on_sample is not None:
                    on_sample(punto)
        else:
            continue
        break

    valid = len(muestras) >= 10 and pico_dir >= 0.2 and signo_detectado is not None
    if session.recorder is not None:
        session.recorder.event('stroke_finished', valid=valid,
                               first_sample=included_indices[0] if included_indices else None,
                               last_sample=included_indices[-1] if included_indices else None,
                               volume_model_L=sum(muestras) * DT,
                               peak_Lps=pico_dir, samples=len(muestras),
                               direction=('push' if signo_detectado > 0 else 'pull') if signo_detectado else None)
    if not valid:
        return None
    return {
        "vol_modelo": sum(muestras) * DT,
        "pico": pico_dir,
        "duracion": len(muestras) * DT,
        "curva": curva,
        "direction": "push" if signo_detectado > 0 else "pull",
    }


def calcular_resultado_calibracion(golpes_push, golpes_pull, temp_c, presion, humedad, volumen_jeringa=3.0):
    if not golpes_push or not golpes_pull:
        return None
    vols_push = [abs(g["vol_modelo"]) for g in golpes_push]
    vols_pull = [abs(g["vol_modelo"]) for g in golpes_pull]
    if not all(isinstance(v, (int, float)) and 0 < v < float("inf")
               for v in [volumen_jeringa, *vols_push, *vols_pull]):
        return None
    try:
        volume_btps_factor = btps_factor(temp_c, presion, humedad)
    except (ValueError, TypeError):
        return None
    prom_push = sum(vols_push) / len(vols_push)
    prom_pull = sum(vols_pull) / len(vols_pull)
    factor_esp = volumen_jeringa / prom_push
    factor_ins = volumen_jeringa / prom_pull
    vols_push_cal = [v * factor_esp for v in vols_push]
    vols_pull_cal = [v * factor_ins for v in vols_pull]
    err_esp = max(abs(v - volumen_jeringa) / volumen_jeringa * 100 for v in vols_push_cal)
    err_ins = max(abs(v - volumen_jeringa) / volumen_jeringa * 100 for v in vols_pull_cal)
    return {
        "volumen_jeringa": volumen_jeringa,
        "factor_esp": factor_esp,
        "factor_ins": factor_ins,
        "prom_push": prom_push,
        "prom_pull": prom_pull,
        "err_esp": err_esp,
        "err_ins": err_ins,
        "ok_ats": err_esp <= 3.0 and err_ins <= 3.0,
        "btps_factor": volume_btps_factor,
        "temperatura_C": temp_c,
        "presion_mmHg": presion,
        "humedad_pct": humedad,
    }


def btps_factor(temp_c, presion_mmhg, humedad_pct=100.):
    """Conversión volumétrica ATPS→BTPS; NO es la corrección total CPFS.

    Dos argumentos suponen gas saturado. La humedad explícita describe el gas
    de entrada. No aplicar automáticamente a la cadena calibrada del sensor:
    Breeze también utiliza densidad, composición y temperatura del neumotacógrafo.
    """
    if temp_c is None or presion_mmhg is None:
        return 1.0
    if humedad_pct is None:
        humedad_pct = 100.
    if (not all(math.isfinite(v) for v in (temp_c, presion_mmhg, humedad_pct))
            or not -50 <= temp_c <= 60 or presion_mmhg <= 47.07
            or not 0 <= humedad_pct <= 100):
        raise ValueError("Condiciones ambientales inválidas")
    vapor = 47.07 * 10 ** (6.36 * (temp_c - 37.) / (temp_c + 232.)) * humedad_pct / 100.
    if presion_mmhg <= vapor:
        raise ValueError("Presión menor que la presión de vapor del gas")
    return (presion_mmhg - vapor) / (presion_mmhg - 47.07) * 310.15 / (273.15 + temp_c)


def contexto_ambiental_medicion(mode=None, **conditions):
    """Build explicit acquisition conditions; no implicit use of calibration weather."""
    if mode is not None:
        from app.cpfs_environment import measurement_environment
        return measurement_environment(mode, **conditions)
    return {
        "status": "pending_cpfs_validation", "applied_factor": 1.0,
        "conditions_source": "saved_calibration",
        "calibration_conditions": {k: _cal.get(k) for k in
                                   ("temperatura_C", "presion_mmHg", "humedad_pct")},
    }


def descripcion_ambiente(context):
    if context.get('mode') == 'patient':
        return 'Paciente · corrección ambiental CPFS'
    if context.get('mode') == 'syringe':
        return 'Jeringa · sin corrección BTPS'
    return 'Conversión BTPS pendiente de verificar'


def ambiente_desde_calibracion(no_btps=False):
    """Daily calibration is the environmental source for all subsequent studies."""
    from copy import deepcopy
    if no_btps:
        return contexto_ambiental_medicion('syringe')
    context = contexto_ambiental_medicion('patient', temperature=_cal.get('temperatura_C'),
        pressure=_cal.get('presion_mmHg'), humidity=_cal.get('humedad_pct'),
        pneumo_temperature=_cal.get('temperatura_neumo_C', 30.))
    context['conditions_source'] = 'daily_calibration'
    context['calibration_date'] = _cal.get('fecha', 'desconocida')
    context['calibration_is_today'] = str(context['calibration_date'])[:10] == datetime.now().date().isoformat()
    if not context['calibration_is_today']:
        context['calibration_notice'] = ('Es recomendable calibrar todos los días antes de iniciar los estudios. '
            f"Se continuará usando la última calibración guardada: {context['calibration_date']}.")
    context['calibration_factors'] = {k:_cal.get(k) for k in ('factor_esp','factor_ins')}
    return deepcopy(context)


# Cargar calibración al inicio
_cal = {}
SCALE = 0.00017032254548179706
SCALE_INS = SCALE
FACTOR_ESP = 1.0
FACTOR_INS = 1.0
_btps = 1.0
aplicar_calibracion(cargar_calibracion())

# ── Dual-range: auto-ranging ch1/ch2 ─────────────────────────────────────────
# Captura simultánea captura_fvc2.pcapng + captura_fvc2.txt:
#   ch1_raw -> LoFlowV, satura cerca de 32767
#   ch2_raw -> HiFlowV, sigue la zona alta
DUAL_RANGE     = "--legacy-linear" not in sys.argv
LO_SAT_THRESH  = 28_000

# Conversión experimental ajustada contra las capturas simultáneas de WFATester:
#   captura_fvc2.txt
#   jeringa/jeringa_push_*.txt
#   pushpull/push_*.txt
#   pushpull/pull_*.txt
# Primero se reconstruyen las unidades internas WFATester:
#   LoFlowV ~= ch1_raw * WF_RAW_TO_V
#   HiFlowV ~= ch2_raw * WF_RAW_TO_V
# Luego se aplica una curva por tramos para estimar Flow L/s.
WF_RAW_TO_V    = 0.000305
WF_PUSH_SWITCH_LO_V = 8.6
WF_PUSH_LOW_LINEAR_MAX_V = 0.050
WF_PUSH_LOW_LINEAR_SLOPE = 4.9867
WF_PUSH_LO_COEFF    = (0.20186647326060878, 1.1948333261507624, -0.47578847988126965,
                       0.12119217168509257, -0.014715322980788542, 0.0006637153113670652)
WF_PUSH_HI_COEFF    = (1.460869094510511, 9.406594372627824, -5.9982688048396176,
                       2.3223995158634865, -0.19600828400113435)
WF_PUSH_HI_CLINICAL_COEFF = (2.0670507895336967, 6.574471808963537,
                             -2.31131289314703, 0.453765500390171)
WF_PUSH_HI_BLEND_START_V = 1.6
WF_PUSH_HI_BLEND_END_V = 2.0
WF_PULL_SWITCH_LO_V = -6.7
WF_PULL_LOW_LINEAR_MIN_V = -0.050
WF_PULL_LOW_LINEAR_SLOPE = 1.8910
WF_PULL_LO_COEFF    = (-0.2062538370262283, 1.2912468854139896, 0.6280623146297336,
                       0.20552921898768073, 0.032453831426372794, 0.0018941591391428024)
WF_PULL_HI_COEFF    = (-2.974691623699932, -15.800851243528479, -141.39632308116194,
                       -350.8208688516822, -301.01895391559304)

# ── Limpieza de señal ─────────────────────────────────────────────────────────
# El flujo CPFS ya fue filtrado antes de convertirlo a L/s. Las métricas y
# las curvas usan ese mismo flujo; el suavizado histórico se conserva solamente
# como herramienta diagnóstica para comparar resultados antiguos.


def correlacion(a, b):
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    a = a[:n]
    b = b[:n]
    avg_a = sum(a) / n
    avg_b = sum(b) / n
    var_a = sum((x - avg_a) ** 2 for x in a) / n
    var_b = sum((x - avg_b) ** 2 for x in b) / n
    if var_a == 0 or var_b == 0:
        return 0.0
    cov = sum((a[i] - avg_a) * (b[i] - avg_b) for i in range(n)) / n
    return cov / ((var_a ** 0.5) * (var_b ** 0.5))


def decode_sample(sample):
    """Decodifica [seq][ch1 uint16 LE][ch2 uint16 LE][0xff]."""
    seq = sample[0]
    ch1 = struct.unpack("<H", sample[1:3])[0] - 32768
    ch2 = struct.unpack("<H", sample[3:5])[0] - 32768
    return seq, ch1, ch2


def polyval(coeffs, x):
    return sum(c * (x ** i) for i, c in enumerate(coeffs))


def flujo_wf_lps(ch1_lo_raw, ch2_hi_raw):
    """Modelo polinómico anterior, conservado solo para comparaciones offline."""
    lo_v = ch1_lo_raw * WF_RAW_TO_V
    hi_v = ch2_hi_raw * WF_RAW_TO_V

    if lo_v >= 0:
        if lo_v <= WF_PUSH_LOW_LINEAR_MAX_V:
            flow = WF_PUSH_LOW_LINEAR_SLOPE * lo_v
        elif lo_v < WF_PUSH_SWITCH_LO_V:
            flow = polyval(WF_PUSH_LO_COEFF, lo_v)
        else:
            flow = polyval(WF_PUSH_HI_COEFF, hi_v)
            if hi_v > WF_PUSH_HI_BLEND_START_V:
                flow_clinical = polyval(WF_PUSH_HI_CLINICAL_COEFF, hi_v)
                if hi_v >= WF_PUSH_HI_BLEND_END_V:
                    flow = flow_clinical
                else:
                    blend = (
                        (hi_v - WF_PUSH_HI_BLEND_START_V)
                        / (WF_PUSH_HI_BLEND_END_V - WF_PUSH_HI_BLEND_START_V)
                    )
                    flow = flow * (1 - blend) + flow_clinical * blend
        return max(0.0, flow)

    if lo_v >= WF_PULL_LOW_LINEAR_MIN_V:
        flow = WF_PULL_LOW_LINEAR_SLOPE * lo_v
    elif lo_v > WF_PULL_SWITCH_LO_V:
        flow = polyval(WF_PULL_LO_COEFF, lo_v)
    else:
        flow = polyval(WF_PULL_HI_COEFF, hi_v)
    return min(0.0, flow)


def flujo_calibrado_lps(ch1_lo_raw, ch2_hi_raw):
    """Diagnóstico del modelo polinómico anterior; no se usa en adquisiciones nuevas."""
    flow = flujo_wf_lps(ch1_lo_raw, ch2_hi_raw)
    return flow * (FACTOR_ESP if flow >= 0 else FACTOR_INS)


def flujos_de_muestras(muestras):
    """Use cached acquisition flow without advancing filters a second time."""
    if not DUAL_RANGE:
        return [max(m[2], 0) * SCALE for m in muestras]
    if any(not hasattr(m, "base_flow") for m in muestras):
        raise ValueError("Captura sin flujo CPFS procesado: reprocesar el raw con sus ceros de sesión")
    return [m.base_flow * m.daily_factor * getattr(m, 'environment_factor', 1.) for m in muestras]


def diagnosticar_canales(ch1_lo, ch2_hi, flows=None):
    """Imprime diagnóstico de los dos rangos raw."""
    if not ch1_lo or not ch2_hi:
        return

    max_lo = max(ch1_lo)
    max_hi = max(ch2_hi)
    i_lo   = ch1_lo.index(max_lo)
    i_hi   = ch2_hi.index(max_hi)
    sat_idx = [i for i, v in enumerate(ch1_lo) if v >= LO_SAT_THRESH]
    n_sat   = len(sat_idx)

    if max_lo < LO_SAT_THRESH:
        return

    hi_sat = [ch2_hi[i] for i in sat_idx]
    lo_sat = [ch1_lo[i] for i in sat_idx]
    r_all  = correlacion(ch1_lo, ch2_hi)
    r_sat  = correlacion(lo_sat, hi_sat)
    pico_wf_ls = max(flows) if flows else 0.

    print(
        f"  [dual-range] modo={'ON' if DUAL_RANGE else 'OFF'}  "
        f"lo_max={max_lo}  hi_max={max_hi}  muestras_lo_sat={n_sat}  "
        f"PEF_wf={pico_wf_ls:.2f} L/s"
    )
    print(
        f"  [canales] r_all={r_all:+.3f}  r_sat={r_sat:+.3f}  "
        f"hi@lo_max={ch2_hi[i_lo]}  lo@hi_max={ch1_lo[i_hi]}  "
        f"hi_sat_min/max={min(hi_sat)}/{max(hi_sat)}"
    )


def limpiar_flujo_para_integracion(flows_lps):
    """
    Suaviza ruido sin modificar la señal usada para PEF.

    El filtro es centrado, por lo que no introduce retraso temporal relevante para FEV1.
    """
    if not flows_lps:
        return []

    if len(flows_lps) < 3:
        return list(flows_lps)

    filtrado = [flows_lps[0]]
    for i in range(1, len(flows_lps) - 1):
        filtrado.append((flows_lps[i - 1] + 2 * flows_lps[i] + flows_lps[i + 1]) / 4)
    filtrado.append(flows_lps[-1])

    return filtrado


def interpolar_volumen(vol_curve, t_obj):
    """Volumen acumulado en t_obj por interpolación lineal."""
    if not vol_curve:
        return 0.0
    if t_obj <= vol_curve[0][0]:
        return vol_curve[0][1]
    if t_obj >= vol_curve[-1][0]:
        return vol_curve[-1][1]

    prev_t, prev_v, _ = vol_curve[0]
    for t, v, _ in vol_curve[1:]:
        if t >= t_obj:
            dt = t - prev_t
            if dt <= 0:
                return v
            frac = (t_obj - prev_t) / dt
            return prev_v + (v - prev_v) * frac
        prev_t, prev_v = t, v
    return vol_curve[-1][1]


def tiempo_en_volumen(vol_curve, objetivo):
    """Primer cruce de volumen con interpolación entre límites de muestras."""
    for (t0, v0, _), (t1, v1, _) in zip(vol_curve, vol_curve[1:]):
        if v0 <= objetivo <= v1 and v1 > v0:
            return t0 + (objetivo - v0) * (t1 - t0) / (v1 - v0)
    return None


METRICS_VERSION = "cpfs-fvc-v2"


def calcular_parametros(muestras, umbral_inicio=5000, environment=None):
    """
    umbral_inicio: umbral dinámico del baseline.
    Calcula FVC, FEV1, PEF, FEF25-75.
    Usa dual-range (ch1/ch2) si DUAL_RANGE=True.
    """
    if not muestras:
        return None
    ch1_lo = [m[2] for m in muestras]
    ch2_hi = [m[3] for m in muestras]
    times  = [m[0] for m in muestras]

    # Flow was processed once from the beginning of the acquisition; the live
    # preview and final metrics reuse it without advancing filter history.
    flows_pef = flujos_de_muestras(muestras)
    if (not all(math.isfinite(v) for v in [*times, *flows_pef])
            or any(abs((b - a) - DT) > 1e-6 for a, b in zip(times, times[1:]))):
        raise ValueError("La maniobra requiere muestras continuas a 100 Hz")

    # Voltages were already filtered during acquisition. Metrics and the plot
    # integrate the same cached flow, without a second smoothing operation.
    flows_calc = flows_pef

    diagnosticar_canales(ch1_lo, ch2_hi, flows_pef)

    MUESTRAS_FIN = 200                  # 2.0 s para confirmar meseta de volumen
    DELTA_VOL_FIN = 0.025               # <=25 mL en 2 s = meseta

    pef_idx_global = max(range(len(flows_pef)), key=lambda i: flows_pef[i])
    if ch1_lo[pef_idx_global] <= umbral_inicio or flows_pef[pef_idx_global] <= 0:
        return None

    # Para FVC tomamos el tramo espiratorio positivo que contiene el PEF global.
    # Asi se descartan las respiraciones tidal previas a la inspiracion maxima,
    # aunque sigan formando parte de la captura grafica completa.
    inicio_idx = pef_idx_global
    while inicio_idx > 0 and flows_calc[inicio_idx - 1] > 0:
        inicio_idx -= 1

    t0       = times[inicio_idx]
    vol_acum = 0.0
    fin_idx  = inicio_idx

    # Construir curva de volumen acumulado muestra a muestra
    # Each sample is a constant-flow interval [t_i, t_i+DT). Keep an explicit
    # zero-volume origin and cumulative volumes at interval ends.
    vol_curve = [(0., 0., flows_calc[inicio_idx])]

    for i in range(inicio_idx, len(flows_calc)):
        f = flows_calc[i]
        if f < 0:
            break  # a following inspiration ends this expiration
        t = times[i] - t0 + DT
        vol_acum += max(f, 0) * DT
        vol_curve.append((t, vol_acum, f))
        fin_idx = i

        if len(vol_curve) > MUESTRAS_FIN:
            delta_2s = vol_acum - vol_curve[-MUESTRAS_FIN - 1][1]
            if t > 0.3 and delta_2s <= DELTA_VOL_FIN:
                fin_idx = i
                break

    pef  = max(flows_pef[inicio_idx:fin_idx+1])
    fvc  = vol_acum

    # ATS/ERS: tiempo cero por extrapolación retrógrada desde la pendiente máxima
    # de la curva V-T, que en FVC corresponde al PEF.
    pef_idx = max(range(inicio_idx, fin_idx + 1), key=lambda i: flows_pef[i])
    t_pef   = times[pef_idx] - t0 + DT / 2
    v_pef   = interpolar_volumen(vol_curve, t_pef)
    t_zero  = t_pef - (v_pef / pef) if pef > 0 else 0.0
    bev     = interpolar_volumen(vol_curve, t_zero) if t_zero > 0 else 0.0
    # ATS/ERS2019: BEV is included in FEV1 and FVC. Time zero shifts the
    # measurement clock, not the volume origin.
    fev1    = max(0.0, interpolar_volumen(vol_curve, t_zero + 1.0))
    ultimo_activo = max(i for i in range(inicio_idx, fin_idx + 1) if flows_calc[i] > 0)
    dur = max(0., times[ultimo_activo] - t0 + DT - t_zero)

    bev_limite = max(0.100, fvc * 0.05)
    inicio_aceptable = bev <= bev_limite

    # EOFE/meseta: cambio de volumen <=25 mL durante el último segundo.
    # Es una bandera de calidad; la captura todavía usa el umbral dinámico.
    fin_curva = vol_curve[-1][0]
    if fin_curva >= 1.0:
        vol_1s_antes_fin = interpolar_volumen(vol_curve, fin_curva - 1.0)
        delta_ultimo_s   = fvc - vol_1s_antes_fin
        meseta_eofe      = delta_ultimo_s <= 0.025
    else:
        delta_ultimo_s   = fvc
        meseta_eofe      = False

    flujo_interrumpido = False
    pausa_muestras = 0
    # Trailing rest is not an interruption inside the expiration.
    flujos_activos = flows_calc[inicio_idx:ultimo_activo + 1]
    for flow in flujos_activos:
        if flow <= 0:
            pausa_muestras += 1
            if pausa_muestras >= int(0.20 / DT):
                flujo_interrumpido = True
                break
        else:
            pausa_muestras = 0

    tos_detectada = False
    cierre_glotico = False
    flujos_curva = flujos_activos
    ventana_corta = max(1, int(0.15 / DT))
    ventana_persistencia = max(1, int(0.30 / DT))
    umbral_casi_cero = max(0.10, pef * 0.05)
    caida_relevante = max(0.50, pef * 0.20)

    limite_tos = min(len(flujos_curva) - (2 * ventana_corta), int(1.0 / DT))
    for i in range(ventana_corta, max(ventana_corta, limite_tos)):
        prev_peak = max(flujos_curva[max(0, i - ventana_corta):i])
        local_low = min(flujos_curva[i:i + ventana_corta])
        next_peak = max(flujos_curva[i + ventana_corta:i + (2 * ventana_corta)])
        if prev_peak - local_low >= caida_relevante and next_peak - local_low >= caida_relevante:
            tos_detectada = True
            break

    for i in range(ventana_corta, len(flujos_curva) - ventana_persistencia):
        prev_peak = max(flujos_curva[max(0, i - ventana_corta):i])
        after = flujos_curva[i:i + ventana_persistencia]
        if (
            prev_peak >= caida_relevante
            and prev_peak - flujos_curva[i] >= caida_relevante
            and max(after) <= umbral_casi_cero
        ):
            cierre_glotico = True
            break

    calidad_errores = []
    # Clock coverage belongs to the full recording. Expiration may finish
    # before one second while acquisition continues through the final rest.
    fin_registro = times[-1] - t0 + DT
    fev1_tiempo_cubierto = fin_registro + 1e-9 >= t_zero + 1.0
    if not fev1_tiempo_cubierto:
        calidad_errores.append("Registro no cubre 1 s desde T0")
    if not inicio_aceptable:
        calidad_errores.append("BEV alto")
    if dur < 0.5:
        calidad_errores.append("Duracion <0.5 s")
    if flujo_interrumpido:
        calidad_errores.append("Espiracion interrumpida")
    if tos_detectada:
        calidad_errores.append("Tos")
    if cierre_glotico:
        calidad_errores.append("Cierre glotico")
    if not meseta_eofe:
        calidad_errores.append("Sin meseta")

    # FEF25-75: flujo medio entre el 25% y 75% del FVC
    fef2575 = None
    if fvc > 0 and len(vol_curve) > 4:
        v25 = fvc * 0.25
        v75 = fvc * 0.75
        t25 = tiempo_en_volumen(vol_curve, v25)
        t75 = tiempo_en_volumen(vol_curve, v75)
        if t25 is not None and t75 is not None and t75 > t25:
            fef2575 = (v75 - v25) / (t75 - t25)

    return {
        "metrics_version": METRICS_VERSION,
        "environment": (environment if environment is not None else
                        getattr(muestras[0], 'environment', contexto_ambiental_medicion())),
        "pef":         pef,
        "fvc":         fvc,
        "fev1":        fev1,
        "fev1_fvc":    fev1 / fvc if fvc > 0 else 0,
        "fev1_tiempo_cubierto": fev1_tiempo_cubierto,
        "fef2575":     fef2575,
        "duracion":    dur,
        "umbral_usado": umbral_inicio,
        "inicio_idx":  inicio_idx,
        "fin_idx":     fin_idx,
        "t_zero":      t_zero,
        "bev":         bev,
        "bev_limite":  bev_limite,
        "inicio_aceptable": inicio_aceptable,
        "delta_ultimo_s": delta_ultimo_s,
        "meseta_eofe": meseta_eofe,
        "flujo_interrumpido": flujo_interrumpido,
        "tos_detectada": tos_detectada,
        "cierre_glotico": cierre_glotico,
        "calidad_errores": calidad_errores,
        "vol_curve":   vol_curve,
        "acq_curve":   calcular_curva_parcial(muestras, umbral_inicio),
    }


def calcular_curva_parcial(muestras, umbral_inicio=5000):
    """Full signed acquisition curve, including zero-flow before/after effort."""
    if not muestras:
        return []
    flows = flujos_de_muestras(muestras)
    t0 = muestras[0][0]
    vol_acum = 0.0
    curve = [(0., 0., flows[0])]
    for (t_abs, _, _ch1_lo, _ch2_hi), flow in zip(muestras, flows):
        vol_acum += flow * DT
        curve.append((t_abs - t0 + DT, vol_acum, flow))
    return curve


def suavizar(vals, ventana=5):
    """Media móvil simple."""
    out = []
    for i in range(len(vals)):
        lo = max(0, i - ventana // 2)
        hi = min(len(vals), i + ventana // 2 + 1)
        out.append(sum(vals[lo:hi]) / (hi - lo))
    return out


def curva_ascii(vol_curve, ancho=60, alto=20):
    """Imprime curva flujo-volumen en ASCII (con suavizado)."""
    if not vol_curve:
        return
    vols  = [v for _, v, _ in vol_curve]
    flows = suavizar([f for _, _, f in vol_curve], ventana=7)
    max_v = max(vols)  if vols  else 1
    max_f = max(flows) if flows else 1
    min_f = min(flows) if flows else 0

    rango_f = max_f - min(0, min_f)
    if rango_f == 0 or max_v == 0:
        return

    grid = [[" "] * ancho for _ in range(alto)]

    for v, f in zip(vols, flows):
        col = int((v / max_v) * (ancho - 1))
        row = alto - 1 - int(((f - min(0, min_f)) / rango_f) * (alto - 1))
        col = max(0, min(ancho - 1, col))
        row = max(0, min(alto - 1, row))
        grid[row][col] = "█"

    print(f"\n  Curva flujo-volumen")
    print(f"  {'PEF':>5} {max_f:.2f} L/s ┐")
    for row in grid:
        print(f"            │{''.join(row)}")
    print(f"  {'0':>10} └{'─'*ancho}→ Vol (0 → {max_v:.2f} L)")


def _svg_polyline(points):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def guardar_curvas_html(vol_curve, parametros, fname):
    """Guarda curvas flujo-volumen y volumen-tiempo en HTML/SVG sin dependencias."""
    if not vol_curve:
        return None

    width = 720
    height = 320
    pad_l, pad_r, pad_t, pad_b = 58, 18, 24, 42
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b

    times = [t for t, _, _ in vol_curve]
    vols = [v for _, v, _ in vol_curve]
    flows = [f for _, _, f in vol_curve]

    max_t = max(times) or 1.0
    max_v = max(vols) or 1.0
    max_f = max(flows) or 1.0
    min_f = min(flows)
    min_flow_axis = min(0.0, min_f)
    flow_span = max_f - min_flow_axis or 1.0

    def x_vol(v):
        return pad_l + (v / max_v) * inner_w

    def y_flow(f):
        return pad_t + inner_h - ((f - min_flow_axis) / flow_span) * inner_h

    def x_time(t):
        return pad_l + (t / max_t) * inner_w

    def y_vol(v):
        return pad_t + inner_h - (v / max_v) * inner_h

    fv_points = [(x_vol(v), y_flow(f)) for _, v, f in vol_curve]
    vt_points = [(x_time(t), y_vol(v)) for t, v, _ in vol_curve]

    t_zero = parametros.get("t_zero", 0.0)
    fev1_t = t_zero + 1.0
    fev1_x = x_time(min(max(fev1_t, 0.0), max_t))
    t0_x = x_time(min(max(t_zero, 0.0), max_t))

    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Curvas espirométricas</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #17202a; background: #f7f8fa; }}
    h1 {{ font-size: 22px; margin: 0 0 8px; }}
    .meta {{ margin-bottom: 18px; color: #4b5563; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; }}
    .panel {{ background: white; border: 1px solid #d9dee7; border-radius: 6px; padding: 14px; }}
    h2 {{ font-size: 16px; margin: 0 0 10px; }}
    svg {{ width: 100%; height: auto; display: block; }}
    .axis {{ stroke: #52606d; stroke-width: 1; }}
    .gridline {{ stroke: #d9dee7; stroke-width: 1; }}
    .curve {{ fill: none; stroke: #0f766e; stroke-width: 2.5; }}
    .marker {{ stroke: #b91c1c; stroke-width: 1.5; stroke-dasharray: 5 4; }}
    text {{ font-size: 12px; fill: #52606d; }}
  </style>
</head>
<body>
  <h1>Curvas espirométricas</h1>
  <div class="meta">
    FVC {parametros['fvc']:.2f} L · FEV1 {parametros['fev1']:.2f} L ·
    PEF {parametros['pef']:.2f} L/s · FEV1/FVC {parametros['fev1_fvc']*100:.1f}%
    · {descripcion_ambiente(parametros.get('environment', {}))}
  </div>
  <div class="grid">
    <section class="panel">
      <h2>Flujo-volumen</h2>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="Curva flujo volumen">
        <line class="axis" x1="{pad_l}" y1="{pad_t + inner_h}" x2="{pad_l + inner_w}" y2="{pad_t + inner_h}"/>
        <line class="axis" x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + inner_h}"/>
        <line class="gridline" x1="{pad_l}" y1="{y_flow(0):.1f}" x2="{pad_l + inner_w}" y2="{y_flow(0):.1f}"/>
        <polyline class="curve" points="{_svg_polyline(fv_points)}"/>
        <text x="{pad_l + inner_w/2:.1f}" y="{height - 8}" text-anchor="middle">Volumen (L)</text>
        <text x="16" y="{pad_t + inner_h/2:.1f}" transform="rotate(-90 16 {pad_t + inner_h/2:.1f})" text-anchor="middle">Flujo (L/s)</text>
        <text x="{pad_l}" y="{height - 22}">0</text>
        <text x="{pad_l + inner_w}" y="{height - 22}" text-anchor="end">{max_v:.2f}</text>
        <text x="{pad_l - 8}" y="{y_flow(max_f)+4:.1f}" text-anchor="end">{max_f:.2f}</text>
      </svg>
    </section>
    <section class="panel">
      <h2>Volumen-tiempo</h2>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="Curva volumen tiempo">
        <line class="axis" x1="{pad_l}" y1="{pad_t + inner_h}" x2="{pad_l + inner_w}" y2="{pad_t + inner_h}"/>
        <line class="axis" x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + inner_h}"/>
        <line class="marker" x1="{t0_x:.1f}" y1="{pad_t}" x2="{t0_x:.1f}" y2="{pad_t + inner_h}"/>
        <line class="marker" x1="{fev1_x:.1f}" y1="{pad_t}" x2="{fev1_x:.1f}" y2="{pad_t + inner_h}"/>
        <polyline class="curve" points="{_svg_polyline(vt_points)}"/>
        <text x="{pad_l + inner_w/2:.1f}" y="{height - 8}" text-anchor="middle">Tiempo (s)</text>
        <text x="16" y="{pad_t + inner_h/2:.1f}" transform="rotate(-90 16 {pad_t + inner_h/2:.1f})" text-anchor="middle">Volumen (L)</text>
        <text x="{pad_l}" y="{height - 22}">0</text>
        <text x="{pad_l + inner_w}" y="{height - 22}" text-anchor="end">{max_t:.2f}</text>
        <text x="{pad_l - 8}" y="{pad_t + 4}" text-anchor="end">{max_v:.2f}</text>
        <text x="{t0_x + 4:.1f}" y="{pad_t + 14}">T0</text>
        <text x="{fev1_x + 4:.1f}" y="{pad_t + 30}">FEV1</text>
      </svg>
    </section>
  </div>
</body>
</html>
"""
    with open(fname, "w") as f:
        f.write(html)
    return fname


def modo_calibrar(dev, umbral):
    """Calibración diaria con jeringa de 3 L sobre la curva raw->Flow."""
    print("\n" + "="*55)
    print("  CALIBRACIÓN DIARIA — Jeringa de 3 L")
    print("="*55)
    print("  Referencia física: jeringa de 3.000 L.")
    print("  Asegurate de que el espirómetro esté en reposo.\n")
    # CLI input can block for minutes: stop USB while asking questions rather
    # than overflow the device queue and silently drop signal history.
    cmd(dev, b"QST\r", "QST (esperando operador)")
    flush(dev)

    # Datos ambientales
    def pedir_float(msg, unidad, ejemplo):
        while True:
            try:
                v = input(f"  {msg} [{unidad}] (ej: {ejemplo}): ").strip()
                return float(v.replace(",", "."))
            except ValueError:
                print("  Valor inválido, ingresá un número.")

    temp_c    = pedir_float("Temperatura ambiente", "°C",   "20.0")
    presion   = pedir_float("Presión barométrica",  "mmHg", "752.0")
    humedad   = pedir_float("Humedad relativa",     "%",    "60.0")

    factor = btps_factor(temp_c, presion, humedad)
    print(f"\n  Conversión volumétrica ATPS→BTPS informativa: {factor:.4f}")
    print("  La corrección ambiental total CPFS sigue pendiente de verificar.\n")

    protocolo = [
        ("push", +1, "~6 s", "bajo"),
        ("push", +1, "~3 s", "medio"),
        ("push", +1, "~1 s", "alto"),
        ("pull", -1, "~6 s", "bajo"),
        ("pull", -1, "~3 s", "medio"),
        ("pull", -1, "~1 s", "alto"),
    ]
    golpes = {"push": [], "pull": []}

    print("  Protocolo: 3 golpes PUSH y 3 golpes PULL.")
    print("  Hacé cada stroke completo hasta el tope mecánico de la jeringa.")
    print("  Los tiempos sugeridos cubren flujo bajo, medio y alto.\n")
    print("  Si no detecta el final automáticamente, presioná ENTER al terminar el golpe.\n")

    for direccion, signo, tiempo_obj, rango in protocolo:
        while True:
            accion = "EMPUJÁ" if direccion == "push" else "TIRÁ"
            input(f"  ENTER → {accion} {tiempo_obj} ({rango}) hasta el tope...")
            previous = dev._cpfs_session.processor
            dev._cpfs_session = StreamSession(
                FlowProcessor(previous.low_zero, previous.high_zero), (FACTOR_ESP, FACTOR_INS))
            cmd(dev, b"SAC\x03\r", "SAC (reanudar canales)")
            send_bytes(dev, b"SRA\r")
            golpe = capturar_golpe_calibracion(dev, signo)
            cmd(dev, b"QST\r", "QST (fin golpe)")
            flush(dev)
            if golpe is None:
                print("  ⚠ No se detectó un golpe válido, repetir.")
                continue
            vol_abs = abs(golpe["vol_modelo"])
            print(
                f"  {direccion.upper():<4} {rango:<5}  "
                f"vol_modelo={golpe['vol_modelo']:+.3f} L  "
                f"pico={golpe['pico']:.2f} L/s  dur={golpe['duracion']:.2f}s"
            )
            confirmar = input("  ¿Aceptar golpe? [s/N]: ").strip().lower()
            if confirmar == "s":
                golpes[direccion].append(golpe)
                break
            print("  Golpe descartado, repetir.")

    if not golpes["push"] or not golpes["pull"]:
        print("  Error: no se obtuvieron datos válidos.")
        return

    vols_push = [abs(g["vol_modelo"]) for g in golpes["push"]]
    vols_pull = [abs(g["vol_modelo"]) for g in golpes["pull"]]
    prom_push = sum(vols_push) / len(vols_push)
    prom_pull = sum(vols_pull) / len(vols_pull)
    factor_esp = 3.000 / prom_push
    factor_ins = 3.000 / prom_pull
    vols_push_cal = [v * factor_esp for v in vols_push]
    vols_pull_cal = [v * factor_ins for v in vols_pull]
    err_esp = max(abs(v - 3.000) / 3.000 * 100 for v in vols_push_cal)
    err_ins = max(abs(v - 3.000) / 3.000 * 100 for v in vols_pull_cal)
    ok_ats = err_esp <= 3.0 and err_ins <= 3.0

    print(f"\n{'='*58}")
    print(f"  RESULTADO DE CALIBRACIÓN")
    print(f"{'='*58}")
    print(f"  Temp: {temp_c}°C  |  Presión: {presion} mmHg  |  HR: {humedad}%")
    print(f"  Factor volumétrico ATPS→BTPS (informativo, no aplicado): {factor:.4f}")
    print()
    print(f"  {'':16}  {'Golpes':>6}  {'Vol modelo':>12}  {'Factor diario':>14}  {'Error max'}")
    print(f"  {'-'*62}")
    print(f"  {'Espiratoria':<16}  {len(vols_push):>6}  {prom_push:>12.3f}  {factor_esp:>14.6f}  {err_esp:.2f}%")
    print(f"  {'Inspiratoria':<16}  {len(vols_pull):>6}  {prom_pull:>12.3f}  {factor_ins:>14.6f}  {err_ins:.2f}%")
    print()
    if ok_ats:
        print(f"  ✓ Calibración dentro del criterio diario (error ≤ 3.0%)")
    else:
        print(f"  ⚠ Error fuera del criterio diario (≤ 3.0%). Repetir.")

    pct_esp = (factor_esp - FACTOR_ESP) / FACTOR_ESP * 100 if FACTOR_ESP else 0
    pct_ins = (factor_ins - FACTOR_INS) / FACTOR_INS * 100 if FACTOR_INS else 0
    print(f"\n  Factor esp anterior: {FACTOR_ESP:.6f}")
    print(f"  Factor esp nuevo:    {factor_esp:.6f}  ({pct_esp:+.1f}%)")
    print(f"  Factor ins anterior: {FACTOR_INS:.6f}")
    print(f"  Factor ins nuevo:    {factor_ins:.6f}  ({pct_ins:+.1f}%)")
    if abs(pct_esp) >= 6 or abs(pct_ins) >= 6:
        print("  ⚠ Cambio >= 6% respecto de la calibración previa: revisar montaje/sensor.")

    confirmar = input("\n  ¿Guardar esta calibración? [s/N]: ").strip().lower()
    if confirmar == "s":
        cal = {
            "volumen_jeringa":     3.00,
            "factor_esp":          factor_esp,
            "factor_ins":          factor_ins,
            "golpes_push":         golpes["push"],
            "golpes_pull":         golpes["pull"],
            "temperatura_C":       temp_c,
            "presion_mmHg":        presion,
            "humedad_pct":         humedad,
            "btps_factor":         round(factor, 4),
            "fecha":               datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nota":                "calibración diaria por curva dual-range, "
                                   f"err_esp={err_esp:.2f}%, err_ins={err_ins:.2f}%",
        }
        guardar_calibracion(cal)
        aplicar_calibracion(cal)
        print("\n  ✓ Calibración guardada para las próximas adquisiciones.")
    else:
        print("  Calibración descartada.")


def mostrar_resultados(muestras, umbral=5000):
    if not muestras:
        print("Sin datos.")
        return

    flows = [m[2] for m in muestras]
    dur   = muestras[-1][0] - muestras[0][0]
    hz    = len(muestras) / dur if dur > 0 else 0

    p = calcular_parametros(muestras, umbral_inicio=umbral)

    print(f"\n{'='*52}")
    print(f"  RESULTADO ESPIROMÉTRICO")
    print(f"{'='*52}")
    print(f"  Muestras: {len(muestras)}   Duración: {dur:.1f}s   Frec: {hz:.1f} Hz")
    print(f"  Factores diarios: esp={FACTOR_ESP:.6f}  ins={FACTOR_INS:.6f}")
    print()

    if p:
        # Same results and units as GUI/curves. A theoretical ATPS factor is
        # not the total environmental correction of this pneumotachograph.
        fef_str = f"{p['fef2575']:.2f} L/s" if p['fef2575'] is not None else "N/D"
        print("  " + descripcion_ambiente(p['environment']))
        print()
        print(f"  {'Parámetro':<12} {'Valor':>10}  {'Unidad'}")
        print(f"  {'-'*38}")
        print(f"  {'PEF':<12} {p['pef']:>10.2f}  L/s  ({p['pef']*60:.0f} L/min)")
        print(f"  {'FVC':<12} {p['fvc']:>10.2f}  L")
        print(f"  {'FEV1':<12} {p['fev1']:>10.2f}  L")
        print(f"  {'FEV1/FVC':<12} {p['fev1_fvc']*100:>10.1f}  %")
        print(f"  {'FEF25-75':<12} {fef_str:>10}")
        print(f"  {'t_exp':<12} {p['duracion']:>10.2f}  s")
        print(f"  {'Umbral':<12} {p['umbral_usado']*SCALE:>10.3f}  L/s")
        print()
        print(f"  {'Calidad':<12} {'Valor':>10}  {'Criterio'}")
        print(f"  {'-'*48}")
        print(f"  {'BEV':<12} {p['bev']:>10.3f}  L  <= {p['bev_limite']:.3f} L  "
              f"{'OK' if p['inicio_aceptable'] else 'REPETIR'}")
        print(f"  {'T0 extra':<12} {p['t_zero']:>10.3f}  s  extrapolación retrógrada")
        print(f"  {'EOFE':<12} {p['delta_ultimo_s']:>10.3f}  L  <= 0.025 L en 1s  "
              f"{'OK' if p['meseta_eofe'] else 'sin meseta'}")

        if p.get("vol_curve"):
            curva_ascii(p["vol_curve"])
            html_name = f"curvas_{int(time.time())}.html"
            guardar_curvas_html(p["vol_curve"], p, html_name)
            print(f"\n  Curvas HTML: {html_name}")
    else:
        print("  No se detectó maniobra FVC. Soplá más fuerte al inicio.")

    fname = f"medicion_{int(time.time())}.csv"
    with open(fname, "w") as f:
        f.write("t_s,seq,flow_est_Ls,ch1_lo_raw,ch2_hi_raw\n")
        for (t, seq, ch1_lo, ch2_hi), flow_est in zip(muestras, flujos_de_muestras(muestras)):
            f.write(f"{t:.6f},{seq},{flow_est:.5f},{ch1_lo},{ch2_hi}\n")
    print(f"\n  CSV: {fname}")
    if muestras and hasattr(muestras[0], "signal_metadata"):
        Path(fname).with_suffix(".signal.json").write_text(
            json.dumps(muestras[0].signal_metadata, indent=2), encoding="utf-8")
    if p:
        processing = dict(p)
        if hasattr(muestras[0], "signal_metadata"):
            processing["signal"] = muestras[0].signal_metadata
        Path(fname).with_suffix(".processing.json").write_text(
            json.dumps(processing, indent=2), encoding="utf-8")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Adquisición CPFS USB')
    parser.add_argument('--calibrar', action='store_true')
    parser.add_argument('--legacy-linear', action='store_true')
    parser.add_argument('--modo', choices=['syringe','patient'], default='syringe')
    args = parser.parse_args()
    modo_cal = args.calibrar
    try:
        environment = ambiente_desde_calibracion(no_btps=modo_cal or args.modo == 'syringe')
    except ValueError as exc:
        parser.error(str(exc))
    if environment.get('calibration_notice'):
        print('Aviso: ' + environment['calibration_notice'])

    try:
        dev = open_device()
    except RuntimeError as exc:
        print(f"ERROR: {exc}. Verificar que el dispositivo este conectado")
        sys.exit(1)

    print(f"Dispositivo: {dev.manufacturer} — {dev.product}")

    cal = cargar_calibracion()
    print(f"Calibración: {cal['fecha']}  |  {descripcion_ambiente(environment)}")
    print(f"Modelo dual-range: {'ACTIVO' if DUAL_RANGE else 'legacy lineal'}")
    print(f"Factores diarios: esp={FACTOR_ESP:.6f}  ins={FACTOR_INS:.6f}")
    if cal.get("nota"):
        print(f"  ⚠ {cal['nota']}")
    print()

    try:
        umbral = inicializar(dev)

        if modo_cal:
            modo_calibrar(dev, umbral)
        else:
            muestras = medir(dev, umbral=umbral, environment=environment)
            mostrar_resultados(muestras, umbral=umbral)

        send_bytes(dev, b"QST\r")
    finally:
        usb.util.release_interface(dev, 0)


if __name__ == "__main__":
    main()
