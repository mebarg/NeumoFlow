"""Directional CPFS environmental initialization reconstructed from Breeze.

Model scope: fixed dry gas compositions, open circuit, no optional three-sensor
normalization. Runtime factors corroborated at 22 C / 764 mmHg / 86% RH and
30 C pneumotach. This is an engineering model, not clinical validation.
"""
from copy import deepcopy
import math
import struct

MODEL = 'cpfs-environment-open-v1'
MASS_BITS = (0x403fffb15b573eab, 0x404601374bc6a7f0, 0x403c03736cdf266c,
             0x4043f95810624dd3, 0x403203e963dc486b)
AIR_BITS = (0x3fcacf95d4e8fb01, 0x3f35a07b352a8438,
            0x3fe8fca42aed1394, 0x3f8330941c8216c6)
HUMAN_BITS = (0x3fc47ae147ae147b, 0x3fa4fdf3b645a1cb,
              0x3fe9438088509bfa, 0x3f8379fa97e132b5)


def _number(bits):
    return struct.unpack('<d', struct.pack('<Q', bits))[0]


def _vapor(temp):
    return 47.07 * 10**(6.36*(temp-37)/(temp+232))


def _density_term(temp, pressure, humidity, human=False):
    water = _vapor(temp)*humidity/100/pressure
    dry = HUMAN_BITS if human else AIR_BITS
    fractions = [_number(b)*(1-water) for b in dry] + [water]
    mass = sum(_number(b)*x for b,x in zip(MASS_BITS, fractions))
    return math.sqrt(mass/(273.15+temp))


def measurement_environment(mode='syringe', temperature=None, pressure=None,
                            humidity=None, pneumo_temperature=30.):
    if mode not in ('syringe', 'patient'):
        raise ValueError('Modo de medición inválido')
    context = {'model': MODEL, 'mode':mode, 'status':'syringe_uncorrected',
               'conditions_source':'not_required', 'factor_negative':1.,
               'factor_positive':1., 'assumptions':{'closed_box':False,
               'three_environment_sensors':False, 'fixed_gas_composition':True}}
    if mode == 'syringe':
        return context
    values = (temperature, pressure, humidity, pneumo_temperature)
    if (any(v is None or not math.isfinite(v) for v in values)
            or not -50 <= temperature <= 60 or not -50 <= pneumo_temperature <= 60
            or pressure <= max(47.07, _vapor(temperature), _vapor(pneumo_temperature))
            or not 0 <= humidity <= 100):
        raise ValueError('Completá temperatura, presión y humedad actuales válidas')
    reference = _density_term(temperature, pressure, humidity)
    positive = _density_term(pneumo_temperature, pressure, 100., human=True)
    def volume_factor(temp, rh):
        return (pressure-_vapor(temp)*rh/100)/(pressure-47.07)*310.15/(273.15+temp)
    context.update(status='patient_directional_engineering', conditions_source='operator_current',
                   conditions={'temperature_C':temperature, 'pressure_mmHg':pressure,
                               'humidity_pct':humidity, 'pneumo_temperature_C':pneumo_temperature},
                   factor_negative=volume_factor(temperature,humidity),
                   factor_positive=volume_factor(pneumo_temperature,100.)*reference/positive)
    return context


def annotate_sample(sample, context):
    """Attach once; leave raw/base flow and syringe calibration untouched."""
    if hasattr(sample, 'environment'):
        if sample.environment != context:
            raise ValueError('La muestra ya tiene otro contexto ambiental')
        return
    sample.environment = deepcopy(context)
    sample.environment_factor = context['factor_positive' if sample.base_flow >= 0 else 'factor_negative']
    sample.signal_metadata = {**getattr(sample,'signal_metadata',{}),
                              'environment':deepcopy(context)}
