"""Build a self-contained amd64 DEB for Mint 21.2 (Ubuntu 22.04, glibc 2.35).

The Python standard library creates the DEB; dpkg-dev is not a build dependency.
Builds run without sudo, never open USB and never read the patient database.
"""
import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import struct
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
VERSION = '1.0.2'
TARGET_GLIBC = (2, 35)
DEPENDENCIES = (
    'libc6 (>= 2.35), libstdc++6, libgcc-s1, libusb-1.0-0, '
    'libglib2.0-0, libdbus-1-3, libfontconfig1, libfreetype6, '
    'libx11-6, libx11-xcb1, libxext6, libxfixes3, libxi6, libxrender1, '
    'libxkbcommon0, libxkbcommon-x11-0, libxcb1, libxcb-cursor0, '
    'libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, '
    'libxcb-randr0, libxcb-render0, libxcb-shape0, libxcb-shm0, '
    'libxcb-sync1, libxcb-xfixes0, libxcb-xinerama0, libxcb-xkb1, '
    'libgl1, libegl1, libopengl0, libsm6, libice6, libcups2, '
    'fonts-dejavu-core, udev'
)


def checked(arguments, **kwargs):
    print('+', shlex.join(map(str, arguments)), flush=True)
    return subprocess.run(list(map(str, arguments)), check=True, **kwargs)


def check_build_host():
    if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'amd64'):
        raise ValueError('Compilar en Linux x64, dentro de Mint 21.2 o Ubuntu 22.04.')
    system = platform.freedesktop_os_release()
    family = {system.get('ID', ''), *system.get('ID_LIKE', '').split()}
    if not family.intersection({'ubuntu', 'debian', 'linuxmint'}):
        raise ValueError('Para Mint 21.2, usar Mint 21.x o Ubuntu 22.04; no CachyOS/Arch.')
    name, version = platform.libc_ver()
    if name != 'glibc' or not version or tuple(map(int, version.split('.'))) > TARGET_GLIBC:
        raise ValueError('La glibc de compilación debe ser 2.35 o anterior. Usar Ubuntu 22.04/Mint 21.x.')
    if not (3, 10) <= sys.version_info[:2] <= (3, 13):
        raise ValueError('Usar Python 3.10–3.13; el Python 3.10 de Mint 21.2 es adecuado.')


def validate_bundle(bundle, root=ROOT):
    bundle = Path(bundle)
    executable = bundle / 'NeumoFlow'
    with executable.open('rb') as source:
        elf = source.read(20)
    if len(elf) != 20 or elf[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', elf, 18)[0] != 62:
        raise ValueError('El ejecutable debe ser ELF x86-64; no un EXE Windows.')
    internal = bundle / '_internal' / 'app'
    calibration = json.loads((internal / 'calibracion.json').read_text())
    if (calibration.get('fecha') != 'pendiente' or calibration.get('factor_esp') != 1.
            or calibration.get('factor_ins') != 1. or calibration.get('temperatura_C') is not None
            or calibration.get('presion_mmHg') is not None or calibration.get('humedad_pct') is not None):
        raise ValueError('El paquete debe contener sólo la calibración inicial pendiente.')
    for name in ('lup1.cfg', 'gli_global_2022.json', 'gli_volumes_2021.json',
                 'GLI-NOTICE.txt', 'brand/neumoflow.png', 'brand/neumoflow.ico'):
        if (internal / 'data' / name).read_bytes() != (root / 'app/data' / name).read_bytes():
            raise ValueError('Recurso ausente o modificado: ' + name)
    for path in bundle.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(bundle.resolve()):
            raise ValueError('Enlace fuera del paquete: ' + str(path))
        if path.suffix.lower() in ('.sqlite3', '.sqlite', '.db', '.cow', '.espiro', '.pcap', '.pcapng'):
            raise ValueError('No se empaquetan archivos clínicos/capturas: ' + str(path))


def check_glibc(bundle):
    """Check actual required versions in every bundled ELF, not just the builder."""
    maximum = (0, 0)
    for path in sorted(Path(bundle).rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        result = subprocess.run(['readelf', '--version-info', str(path)],
                                capture_output=True, text=True, check=True,
                                env=dict(os.environ, LC_ALL='C'))
        # The needs section is distinct from symbol versions defined by a library.
        needs = result.stdout.split('Version needs section', 1)
        if len(needs) == 2:
            versions = [tuple(map(int, match.split('.')))
                        for match in re.findall(r'Name: GLIBC_(\d+\.\d+)', needs[1])]
            maximum = max([maximum, *versions])
            if maximum > TARGET_GLIBC:
                raise ValueError(f'{path.name} requiere GLIBC {maximum}: no entregar a Mint 21.2.')
    return '.'.join(map(str, maximum))


def _tar_file(archive, name, source=None, data=None, mode=0o644):
    info = tarfile.TarInfo(name)
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    info.mtime = 0
    info.mode = mode
    if source is not None and source.is_symlink():
        info.type = tarfile.SYMTYPE
        info.linkname = os.readlink(source)
        archive.addfile(info)
    elif source is not None:
        info.size = source.stat().st_size
        with source.open('rb') as stream:
            archive.addfile(info, stream)
    else:
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def _ar_member(stream, name, source):
    size = source.stat().st_size
    header = f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{size:<10}`\n'
    if len(header) != 60:
        raise ValueError('Cabecera ar inválida.')
    stream.write(header.encode('ascii'))
    with source.open('rb') as item:
        while chunk := item.read(1024 * 1024):
            stream.write(chunk)
    if size % 2:
        stream.write(b'\n')


def _tar_directories(archive, payload, bundle):
    """dpkg requires explicit parents; tar's automatic mkdir hides their absence."""
    directories = {parent.as_posix()
                   for name, _, _ in payload
                   for parent in PurePosixPath(name).parents
                   if parent != PurePosixPath('.')}
    directories.update('opt/neumoflow/' + p.relative_to(bundle).as_posix()
                       for p in bundle.rglob('*') if p.is_dir() and not p.is_symlink())
    for name in sorted(directories, key=lambda name: (len(PurePosixPath(name).parts), name)):
        info = tarfile.TarInfo(name)
        info.type = tarfile.DIRTYPE
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        info.mtime = 0
        info.mode = 0o755
        archive.addfile(info)


def verify_deb_tar(path):
    """Validate raw headers: TarFile iteration hides unsupported PAX records.

    dpkg accepts GNU long-name/link records, but not POSIX PAX x/g records.
    Read through the compressed stream's end to verify its checksum as well.
    """
    allowed = {b'\0', b'0', b'2', b'5', b'L', b'K'}
    zero_blocks = 0
    with lzma.open(path, 'rb') as archive:
        while block := archive.read(512):
            if len(block) != 512:
                raise ValueError('Cabecera tar truncada.')
            if block == bytes(512):
                zero_blocks += 1
                continue
            if zero_blocks:
                raise ValueError('Datos inesperados después del fin de tar.')
            kind = block[156:157]
            if kind not in allowed:
                raise ValueError(f'Cabecera tar no admitida por el instalador Debian: {kind!r}')
            checksum = int(block[148:156].strip(b'\0 ') or b'0', 8)
            if checksum != sum(block[:148]) + 8 * 32 + sum(block[156:]):
                raise ValueError('Checksum de cabecera tar incorrecto.')
            size = int(block[124:136].strip(b'\0 ') or b'0', 8)
            remaining = (size + 511) // 512 * 512
            while remaining:
                chunk = archive.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError('Contenido tar truncado.')
                remaining -= len(chunk)
    if zero_blocks < 2:
        raise ValueError('Falta el marcador de fin de tar.')


def create_deb(bundle, destination, version=VERSION, root=ROOT):
    """Package only a validated onedir distribution plus explicit desktop assets."""
    if not re.fullmatch(r'\d[0-9A-Za-z.+~]*', version):
        raise ValueError('Versión Debian inválida.')
    bundle, destination = Path(bundle), Path(destination)
    validate_bundle(bundle, root)
    if destination.exists():
        raise ValueError('El instalador ya existe: moverlo antes de volver a construir.')
    assets = root / 'packaging/linux'
    payload = [(f'opt/neumoflow/{p.relative_to(bundle).as_posix()}', p,
                0o755 if p.stat().st_mode & 0o111 else 0o644)
               for p in sorted(bundle.rglob('*')) if p.is_file() or p.is_symlink()]
    payload += [
        ('usr/bin/neumoflow', assets / 'neumoflow', 0o755),
        ('usr/share/applications/neumoflow.desktop', assets / 'neumoflow.desktop', 0o644),
        ('usr/share/icons/hicolor/256x256/apps/neumoflow.png', root / 'app/data/brand/neumoflow.png', 0o644),
        ('usr/lib/udev/rules.d/69-neumoflow-cpfs.rules', assets / '69-neumoflow-cpfs.rules', 0o644),
        ('usr/share/doc/neumoflow/README.md', assets / 'README.md', 0o644),
        ('usr/share/doc/neumoflow/GLI-NOTICE.txt', root / 'app/data/GLI-NOTICE.txt', 0o644),
    ]
    installed_size = (sum(p.stat().st_size for _, p, _ in payload) + 1023) // 1024
    control = (f'Package: neumoflow\nVersion: {version}\nSection: science\nPriority: optional\n'
               f'Architecture: amd64\nMaintainer: NeumoFlow <mebarg@users.noreply.github.com>\n'
               f'Installed-Size: {installed_size}\nDepends: {DEPENDENCIES}\n'
               'Description: NeumoFlow - espirometria CPFS/D\n'
               ' Mediciones FVC, SVC y MVV, historial e informes PDF.\n'
               ' Incluye Python y sus dependencias de aplicacion.\n').encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='neumoflow-deb-') as temporary:
        temp = Path(temporary)
        hashes = []
        # Explicitly use GNU. The Python default is PAX, which introduces x/g
        # records for long or Unicode paths even when TarInfo has no pax_headers.
        with tarfile.open(temp / 'data.tar.xz', 'w:xz', format=tarfile.GNU_FORMAT) as archive:
            _tar_directories(archive, payload, bundle)
            for name, source, mode in payload:
                _tar_file(archive, name, source=source, mode=mode)
                if not source.is_symlink():
                    digest = hashlib.md5(source.read_bytes()).hexdigest()
                    hashes.append(f'{digest}  {name}\n')
        with tarfile.open(temp / 'control.tar.xz', 'w:xz', format=tarfile.GNU_FORMAT) as archive:
            _tar_file(archive, 'control', data=control)
            _tar_file(archive, 'md5sums', data=''.join(hashes).encode())
            for name in ('postinst', 'postrm'):
                _tar_file(archive, name, source=assets / name, mode=0o755)
        verify_deb_tar(temp / 'data.tar.xz')
        verify_deb_tar(temp / 'control.tar.xz')
        (temp / 'debian-binary').write_bytes(b'2.0\n')
        with destination.open('xb') as stream:
            stream.write(b'!<arch>\n')
            for name in ('debian-binary', 'control.tar.xz', 'data.tar.xz'):
                _ar_member(stream, name, temp / name)
    return destination


def build(args):
    check_build_host()
    if not args.current_environment and not args.repackage:
        environment = ROOT / '.venv-linux-build'
        python = environment / 'bin/python'
        if not python.exists():
            checked([sys.executable, '-m', 'venv', environment])
        checked([python, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt',
                 '-r', ROOT / 'requirements-build.txt', '-c', ROOT / 'packaging/constraints-linux.txt'])
        command = [python, __file__, '--current-environment', '--version', args.version]
        if args.skip_tests:
            command.append('--skip-tests')
        checked(command, cwd=ROOT)
        return
    build_dir = ROOT / 'build/linux'
    build_dir.mkdir(parents=True, exist_ok=True)
    destination = ROOT / f'dist-installer/neumoflow_{args.version}_mint21_amd64.deb'
    if destination.exists():
        raise ValueError(f'Ya existe {destination}; conservarlo en otra carpeta antes de recompilar.')
    with TemporaryDirectory(prefix='neumoflow-build-check-') as temporary:
        environment = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_DATA_HOME=temporary)
        if not args.skip_tests:
            selection = ['-p', 'test_linux_packaging.py'] if args.repackage else []
            checked([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q', *selection],
                    cwd=ROOT, env=environment)
        if not args.repackage:
            checked([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                     '--workpath', build_dir / 'pyinstaller', '--distpath', ROOT / 'dist/linux',
                     ROOT / 'packaging/neumoflow-linux.spec'], cwd=ROOT)
        bundle = ROOT / 'dist/linux/NeumoFlow'
        validate_bundle(bundle)
        glibc = check_glibc(bundle)
        report = build_dir / 'self-test.json'
        report.unlink(missing_ok=True)
        checked([bundle / 'NeumoFlow', '--self-test', report], env=environment)
        if not json.loads(report.read_text()).get('ok'):
            raise ValueError('Falló la comprobación de arranque del ejecutable.')
    output = create_deb(bundle, destination, args.version, root=ROOT)
    if not args.repackage:
        packages = subprocess.check_output([sys.executable, '-m', 'pip', 'freeze', '--all'], text=True)
        (build_dir / 'packages.txt').write_text(packages)
    metadata = {'version': args.version, 'target': 'Linux Mint 21.2 x64',
                'build_os': platform.freedesktop_os_release(), 'maximum_required_glibc': glibc,
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'frozen_self_test': True, 'deb_tar_headers_verified': True,
                'reused_frozen_bundle': args.repackage,
                'mint_desktop_and_usb_verified': False}
    output.with_suffix('.build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    output.with_suffix('.deb.sha256').write_text(metadata['sha256'] + '  ' + output.name + '\n')
    print(f'\nInstalador generado: {output}\nProbar menú, USB e informes en Mint 21.2 antes de entregar.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default=VERSION)
    parser.add_argument('--current-environment', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--skip-tests', action='store_true', help='Omitir suite; siempre verificar ejecutable y recursos.')
    parser.add_argument('--repackage', action='store_true',
                        help='Rehacer sólo el DEB desde dist/linux/NeumoFlow, sin descargar ni recompilar.')
    try:
        build(parser.parse_args())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'No se pudo generar el instalador: {exc}', file=sys.stderr)
        raise SystemExit(1)
