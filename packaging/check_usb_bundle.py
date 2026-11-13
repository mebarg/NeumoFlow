"""Reproducibility checks; Windows performs signature and hardware checks."""
import hashlib
import json
from pathlib import Path
import re
import sys

FILES = ('Medical_Graphics_CPFS_USB.inf', 'Medical_Graphics_CPFS_USB.cat',
         'amd64/WdfCoInstaller01011.dll', 'amd64/winusbcoinstaller2.dll',
         'x86/WdfCoInstaller01011.dll', 'x86/winusbcoinstaller2.dll', 'signer.cer')
THUMBPRINT = 'AE87D0D43947DE135B9C33F87D00CE9E9ED25D2B'


def validate_bundle(directory):
    directory = Path(directory)
    for name in (*FILES, 'manifest.json'):
        if not (directory/name).is_file():
            raise ValueError('Falta el componente USB integrado: '+name)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8-sig'))
    if manifest.get('device_id') != r'USB\VID_0EE5&PID_0103':
        raise ValueError('Identificador USB incorrecto')
    if manifest.get('certificate_thumbprint') != THUMBPRINT:
        raise ValueError('Certificado USB inesperado')
    if set(manifest.get('sha256', {})) != set(FILES):
        raise ValueError('Lista de archivos USB incorrecta')
    for name in FILES:
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != manifest['sha256'][name]:
            raise ValueError('El hash del componente USB no coincide: '+name)
    inf = (directory/FILES[0]).read_text(encoding='utf-16')
    ids = set(re.findall(r'VID_[0-9A-F]{4}&PID_[0-9A-F]{4}', inf, re.I))
    if ids != {'VID_0EE5&PID_0103'} or 'Include = winusb.inf' not in inf:
        raise ValueError('El INF no corresponde exclusivamente al CPFS/D WinUSB')
    return manifest


if __name__ == '__main__':
    try:
        validate_bundle(Path(sys.argv[1]) if len(sys.argv)>1 else
                        Path(__file__).parent/'windows-usb/package')
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    print('Archivos USB comprobados. La instalacion limpia requiere prueba en Windows.')
