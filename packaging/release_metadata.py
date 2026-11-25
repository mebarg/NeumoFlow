"""Validate release tags and the exact assets published by GitHub Actions."""
import argparse
import hashlib
import os
from pathlib import Path
import re


def release_version(tag):
    match = re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', tag)
    if not match or any(len(p) > 5 or int(p) > 65535 for p in match.groups()):
        raise ValueError('Usar una etiqueta vX.Y.Z, con componentes entre 0 y 65535.')
    return tag[1:]


def verify_assets(directory, tag):
    version = release_version(tag)
    directory = Path(directory)
    names = [f'NeumoFlowSetup-{version}.exe', f'neumoflow_{version}_mint21_amd64.deb']
    expected = set(names + [name + '.sha256' for name in names])
    if {p.name for p in directory.iterdir()} != expected:
        raise ValueError('Faltan instaladores o hay archivos inesperados para publicar.')
    for name in names:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Instalador invalido: {name}')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if (directory / (name + '.sha256')).read_text(encoding='utf-8-sig').strip().lower() != f'{digest}  {name}'.lower():
            raise ValueError(f'SHA256 incorrecto: {name}')
    return sorted(expected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('--assets', type=Path)
    args = parser.parse_args()
    version = release_version(args.tag)
    if args.assets:
        for name in verify_assets(args.assets, args.tag):
            print(name)
    else:
        print(version)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write(f'version={version}\n')
