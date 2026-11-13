"""Read-only decoder for the observed DBTools COW 510/6.4.1 profile.

RC2 inverse rounds and key schedule: RFC 2268 sections 2 and 4.
This legacy interoperability codec is not used to encrypt application exports.
No external executable, system crypto provider or extra install is required.
"""
import hashlib
import struct

from app.breeze_cow import CowFormatError


_PI = bytes.fromhex('''
d9 78 f9 c4 19 dd b5 ed 28 e9 fd 79 4a a0 d8 9d
c6 7e 37 83 2b 76 53 8e 62 4c 64 88 44 8b fb a2
17 9a 59 f5 87 b3 4f 13 61 45 6d 8d 09 81 7d 32
bd 8f 40 eb 86 b7 7b 0b f0 95 21 22 5c 6b 4e 82
54 d6 65 93 ce 60 b2 1c 73 56 c0 14 a7 8c f1 dc
12 75 ca 1f 3b be e4 d1 42 3d d4 30 a3 3c b6 26
6f bf 0e da 46 69 07 57 27 f2 1d 9b bc 94 43 03
f8 11 c7 f6 90 ef 3e e7 06 c3 d5 2f c8 66 1e d7
08 e8 ea de 80 52 ee f7 84 aa 72 ac 35 4d 6a 2a
96 1a d2 71 5a 15 49 74 4b 9f d0 5e 04 18 a4 ec
c2 e0 41 6e 0f 51 cb cc 24 91 af 50 a1 f4 70 39
99 7c 3a 85 23 b8 b4 7a fc 02 36 5b 25 55 97 31
2d 5d fa 98 e3 8a 92 ae 05 df 29 10 67 6c ba c9
d3 00 e6 cf e1 9e a8 2c 63 16 01 3f 58 e2 89 a9
0d 38 34 1b ab 33 ff b0 bb 48 0c 5f b9 b1 cd 2e
c5 f3 db 47 e5 a5 9c 77 0a a6 20 68 fe 7f c1 ad
''')


def _expand(key, bits=128):
    length = len(key)
    if not 1 <= length <= 128 or not 1 <= bits <= 1024:
        raise CowFormatError('Perfil RC2 inválido')
    buf = list(key) + [0] * (128-length)
    for i in range(length, 128):
        buf[i] = _PI[(buf[i-1]+buf[i-length]) & 255]
    width = (bits+7)//8
    buf[128-width] = _PI[buf[128-width] & (255 >> (8*width-bits))]
    for i in range(127-width, -1, -1):
        buf[i] = _PI[buf[i+1] ^ buf[i+width]]
    return struct.unpack('<64H', bytes(buf))


def _decrypt_block(block, key):
    r = list(struct.unpack('<4H', block))
    j = 63
    for round_index in range(16):
        if round_index in (5, 11):
            for i in (3, 2, 1, 0):
                r[i] = (r[i]-key[r[(i-1) % 4] & 63]) & 65535
        for i in (3, 2, 1, 0):
            shift = (1, 2, 3, 5)[i]
            value = ((r[i] >> shift) | (r[i] << (16-shift))) & 65535
            r[i] = (value-key[j]-(r[(i-1) % 4] & r[(i-2) % 4])
                    - ((~r[(i-1) % 4]) & r[(i-3) % 4])) & 65535
            j -= 1
    return struct.pack('<4H', *r)


def decrypt_cow(data):
    if len(data) < 264 or len(data) > 64*1024*1024 or (len(data)-256) % 8:
        raise CowFormatError('COW cifrado truncado o demasiado grande')
    if (not data.startswith(b'~Encrypted~\0') or
            data[12:18].split(b'\0', 1)[0] != b'510' or data[18:24] != b'6.4.1\0'):
        raise CowFormatError('Perfil COW cifrado no reconocido; se admite 6.4.1')
    seed, terminator, _ = data[24:45].partition(b'\0')
    seed = seed.strip(b' \t\r\n\v\f')
    if not seed or not terminator:
        raise CowFormatError('Falta el identificador del COW cifrado')
    key = _expand(hashlib.md5(seed).digest())
    previous, plain = bytes(8), bytearray()
    for offset in range(256, len(data), 8):
        block = data[offset:offset+8]
        plain.extend(a ^ b for a, b in zip(_decrypt_block(block, key), previous))
        previous = block
    padding = plain[-1]
    if not 1 <= padding <= 8 or plain[-padding:] != bytes([padding])*padding:
        raise CowFormatError('COW cifrado dañado: relleno inválido')
    payload = bytes(plain[:-padding])
    prefix = b'Patient\0PatientIDNum\0'
    if (not payload.startswith(prefix) or not payload.endswith(b'%LastField%\0%LastTable%\0')
            or payload[len(prefix):].split(b'\0', 1)[0].strip() != seed):
        raise CowFormatError('El contenido descifrado no tiene la estructura esperada')
    return payload
