"""Decode version-10 MGCSourceData blobs from the observed COW exports.

Binary layout corroborated against MGCHISExporter.dll 0x1005ef00/0x1005f4a0.
Reserved/padding bytes are intentionally not interpreted. Clinical results
are retained separately: these source channels are quantized stored points.
"""
from dataclasses import dataclass
import struct
from app.breeze_cow import CowFormatError


@dataclass(frozen=True)
class SourceChannel:
    channel_id: int
    scale: int
    representation: int
    raw: tuple

    @property
    def values(self):
        divisor = self.scale or 1
        return tuple(value/divisor for value in self.raw)


@dataclass(frozen=True)
class SourceData:
    version: int
    point_count: int
    channels: tuple
    markers: tuple
    extra_data: bytes

    def channel(self, channel_id):
        return next((channel.values for channel in self.channels if channel.channel_id == channel_id), None)

    def _check_fvl_scales(self):
        expected = {1: 200, 2: 1000, 3: 1000}
        if any(channel.channel_id not in expected or channel.scale != expected[channel.channel_id]
               for channel in self.channels):
            raise CowFormatError('Escala o canal FVL fuera del perfil comprobado')

    def flow_volume_points(self):
        """Return volume/flow, including tidal blobs that store no time channel."""
        self._check_fvl_scales()
        volumes, flows = self.channel(2), self.channel(3)
        if volumes is None or flows is None:
            raise CowFormatError('Faltan canales FVL de volumen o flujo')
        return list(zip(volumes, flows))

    def fvl_points(self, relative_time=False):
        """Return observed FVL channels as (seconds, liters, liters/second).

        Times come from channel 1; no sampling rate is assumed. Empty tidal
        blobs may omit this channel. Stored results must not be recomputed
        from these quantized points when importing historical studies.
        """
        if self.point_count == 0:
            return []
        self._check_fvl_scales()
        times, volumes, flows = (self.channel(key) for key in (1, 2, 3))
        if any(values is None for values in (times, volumes, flows)):
            raise CowFormatError('Faltan canales FVL de tiempo, volumen o flujo')
        if any(a > b for a, b in zip(times, times[1:])):
            raise CowFormatError('Los tiempos de la curva FVL no están ordenados')
        offset = times[0] if relative_time else 0.
        return [(t-offset, v, f) for t, v, f in zip(times, volumes, flows)]


def decode_source_blob(blob):
    if len(blob) < 24:
        raise CowFormatError('Bloque de curva truncado: falta la cabecera')
    version, size = struct.unpack_from('<II', blob)
    channels, points, markers = struct.unpack_from('<hhh', blob, 8)
    extra_size = struct.unpack_from('<I', blob, 16)[0]
    if version != 10:
        raise CowFormatError(f'Versión de curva no reconocida: {version}')
    if size != len(blob):
        raise CowFormatError('La longitud declarada de la curva no coincide con el bloque')
    if not 0 <= channels <= 255 or not 0 <= points <= 32767 or not 0 <= markers <= points:
        raise CowFormatError('Cantidad inválida de canales, puntos o marcas')
    offset, decoded, ids = 24, [], set()
    for _ in range(channels):
        if offset+6 > len(blob):
            raise CowFormatError('Cabecera de canal truncada')
        channel_id = blob[offset]
        scale = struct.unpack_from('<h', blob, offset+2)[0]
        representation = blob[offset+4]
        offset += 6
        if channel_id in ids:
            raise CowFormatError('Canal duplicado en bloque de curva')
        ids.add(channel_id)
        if representation not in (0, 1):
            raise CowFormatError('Representación numérica de canal no reconocida')
        width, code = (2, 'h') if representation == 0 else (4, 'i')
        if offset+width*points > len(blob):
            raise CowFormatError('Muestras de canal truncadas')
        raw = struct.unpack_from('<'+str(points)+code, blob, offset)
        offset += width*points
        decoded.append(SourceChannel(channel_id, scale, representation, raw))
    if offset+2*markers+extra_size != len(blob):
        raise CowFormatError('El bloque contiene datos truncados o bytes sin interpretar')
    indices = struct.unpack_from('<'+str(markers)+'h', blob, offset)
    if any(index < 0 or index >= points for index in indices):
        raise CowFormatError('Marca de curva fuera del rango de muestras')
    offset += 2*markers
    return SourceData(version, points, tuple(decoded), indices, blob[offset:])
