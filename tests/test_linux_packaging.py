"""Check install permissions, data isolation and the real DEB archive format."""
import hashlib
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

if sys.platform != 'linux':
    raise unittest.SkipTest('Linux packaging checks run on Linux only')

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('neumoflow_linux_build', ROOT / 'packaging/build_linux.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def deb_members(path):
    raw = path.read_bytes()
    assert raw[:8] == b'!<arch>\n'
    result = {}
    pos = 8
    while pos < len(raw):
        header = raw[pos:pos + 60]
        assert len(header) == 60 and header[-2:] == b'`\n'
        name = header[:16].decode().strip().rstrip('/')
        size = int(header[48:58])
        result[name] = raw[pos + 60:pos + 60 + size]
        pos += 60 + size + size % 2
    assert pos == len(raw)
    return result


def test_bundle(directory):
    bundle = Path(directory) / 'NeumoFlow'
    assets = bundle / '_internal/app'
    assets.mkdir(parents=True)
    shutil.copytree(ROOT / 'app/data', assets / 'data')
    shutil.copy2(ROOT / 'packaging/defaults/calibracion.json', assets / 'calibracion.json')
    # Real small ELF, not a fabricated installer executable. Never launched.
    shutil.copy2(shutil.which('true'), bundle / 'NeumoFlow')
    (bundle / '_internal/plugins/empty').mkdir(parents=True)
    (bundle / 'shortcut').symlink_to('_internal/app/calibracion.json')
    # Frozen distributions contain paths/links longer than the tar base fields.
    # Short fixtures hid the PAX records rejected by dpkg in a real installation.
    long_name = '_internal/' + 'reference_distribution_' * 4 + '/licenses/licencia_ñ.txt'
    long_file = bundle / long_name
    long_file.parent.mkdir(parents=True)
    long_file.write_text('Synthetic test resource\n')
    (bundle / 'long-link').symlink_to(long_name)
    return bundle


def strict_unpack(archive, destination):
    """Model dpkg's file creation: never silently create missing parent dirs."""
    for item in archive.getmembers():
        path = destination / item.name
        if item.isdir():
            path.mkdir(exist_ok=True)
        elif item.issym():
            path.symlink_to(item.linkname)
        elif item.isfile():
            staging = path.with_name(path.name + '.dpkg-new')
            staging.write_bytes(archive.extractfile(item).read())
            staging.chmod(item.mode)
            staging.rename(path)
        else:
            raise AssertionError('Unexpected archive entry')


@unittest.skipUnless(os.name == 'posix' and shutil.which('true'), 'Requires Unix ELF fixture')
class LinuxPackagingTests(unittest.TestCase):
    def test_deb_contains_only_app_and_specific_usb_rule_with_root_ownership(self):
        with TemporaryDirectory() as temporary:
            bundle = test_bundle(temporary)
            output = builder.create_deb(bundle, Path(temporary) / 'test.deb')
            members = deb_members(output)
            self.assertEqual(set(members), {'debian-binary', 'control.tar.xz', 'data.tar.xz'})
            self.assertEqual(members['debian-binary'], b'2.0\n')
            for name in ('control.tar.xz', 'data.tar.xz'):
                compressed = Path(temporary) / name
                compressed.write_bytes(members[name])
                builder.verify_deb_tar(compressed)
                # Inspect physical records, not TarFile members (which hide x/g).
                raw = lzma.decompress(members[name])
                flags, offset = [], 0
                while raw[offset:offset + 512] != bytes(512):
                    header = raw[offset:offset + 512]
                    flags.append(header[156:157])
                    size = int(header[124:136].strip(b'\0 ') or b'0', 8)
                    offset += 512 + ((size + 511) // 512) * 512
                self.assertNotIn(b'x', flags)
                self.assertNotIn(b'g', flags)
                if name == 'data.tar.xz':
                    self.assertIn(b'L', flags)
                    self.assertIn(b'K', flags)
            if shutil.which('ar'):
                listing = subprocess.check_output(['ar', 't', str(output)], text=True)
                self.assertEqual(listing.splitlines(), ['debian-binary', 'control.tar.xz', 'data.tar.xz'])
            if shutil.which('dpkg-deb'):
                subprocess.run(['dpkg-deb', '--info', str(output)], check=True, capture_output=True)
            with tarfile.open(fileobj=io.BytesIO(members['control.tar.xz'])) as control:
                text = control.extractfile('control').read().decode()
                self.assertIn('Architecture: amd64\n', text)
                self.assertIn('libc6 (>= 2.35)', text)
                self.assertIn('libatomic1', text)
                self.assertNotIn('python3', text)
                self.assertEqual(control.getmember('postinst').mode, 0o755)
                removal = control.extractfile('postrm').read().decode()
                self.assertNotIn('rm -', removal)
                self.assertNotIn('/home/', removal)
                hashes = control.extractfile('md5sums').read().decode().splitlines()
            with tarfile.open(fileobj=io.BytesIO(members['data.tar.xz'])) as data:
                staging = Path(temporary) / 'installed'
                staging.mkdir()
                strict_unpack(data, staging)
                self.assertEqual((staging / 'opt/neumoflow/NeumoFlow').read_bytes(),
                                 (bundle / 'NeumoFlow').read_bytes())
                self.assertTrue((staging / 'opt/neumoflow/_internal/plugins/empty').is_dir())
                self.assertTrue((staging / 'opt/neumoflow/shortcut').is_symlink())
                self.assertEqual((staging / 'opt/neumoflow/long-link').read_text(),
                                 'Synthetic test resource\n')
                for item in data.getmembers():
                    self.assertEqual((item.uid, item.gid), (0, 0))
                    self.assertFalse(item.name.startswith(('/', 'home/', 'root/', 'tmp/')))
                    if item.isdir():
                        self.assertEqual(item.mode, 0o755)
                launcher = data.extractfile('usr/bin/neumoflow').read().decode()
                self.assertIn('exec /opt/neumoflow/NeumoFlow "$@"', launcher)
                self.assertEqual(data.getmember('usr/bin/neumoflow').mode, 0o755)
                rule = data.extractfile('usr/lib/udev/rules.d/69-neumoflow-cpfs.rules').read().decode()
                self.assertIn('ATTR{idVendor}=="0ee5"', rule)
                self.assertIn('ATTR{idProduct}=="0103"', rule)
                self.assertIn('TAG+="uaccess"', rule)
                self.assertNotIn('0666', rule)
                neutral = json.loads(data.extractfile('opt/neumoflow/_internal/app/calibracion.json').read())
                self.assertEqual(neutral['fecha'], 'pendiente')
                for row in hashes:
                    digest, name = row.split('  ', 1)
                    self.assertEqual(hashlib.md5(data.extractfile(name).read()).hexdigest(), digest)
                # Prove this check detects the original missing-directory bug.
                missing_parents = io.BytesIO()
                with tarfile.open(fileobj=missing_parents, mode='w') as broken:
                    for item in data.getmembers():
                        if not item.isdir():
                            broken.addfile(item, data.extractfile(item) if item.isfile() else None)
                missing_parents.seek(0)
                failed_root = Path(temporary) / 'failed-install'
                failed_root.mkdir()
                with tarfile.open(fileobj=missing_parents) as broken:
                    with self.assertRaises(FileNotFoundError):
                        strict_unpack(broken, failed_root)
            with self.assertRaisesRegex(ValueError, 'ya existe'):
                builder.create_deb(bundle, output)

    def test_raw_tar_verifier_rejects_pax_headers_hidden_by_normal_tar_iteration(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'pax.tar.xz'
            long_name = 'synthetic/path/' + 'long-' * 25
            with tarfile.open(path, 'w:xz', format=tarfile.PAX_FORMAT) as archive:
                info = tarfile.TarInfo(long_name)
                info.size = 4
                archive.addfile(info, io.BytesIO(b'test'))
            with tarfile.open(path) as archive:
                self.assertEqual(archive.getnames(), [long_name])
            with self.assertRaisesRegex(ValueError, "no admitida.*b'x'"):
                builder.verify_deb_tar(path)

    def test_repackage_reuses_binary_without_pip_or_pyinstaller_and_checks_startup(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = test_bundle(root / 'dist/linux')
            (root / 'app').mkdir()
            (root / 'app/data').symlink_to(ROOT / 'app/data', target_is_directory=True)
            (root / 'packaging').mkdir()
            (root / 'packaging/linux').symlink_to(ROOT / 'packaging/linux', target_is_directory=True)
            previous = root / 'build/linux/packages.txt'
            previous.parent.mkdir(parents=True)
            previous.write_text('original-frozen-packages\n')
            calls = []
            def checked(arguments, **kwargs):
                calls.append(list(map(str, arguments)))
                if str(arguments[0]) == str(bundle / 'NeumoFlow'):
                    Path(arguments[2]).write_text('{"ok": true}')
            args = SimpleNamespace(current_environment=False, repackage=True,
                                   skip_tests=False, version='1.0.1')
            with patch.object(builder, 'ROOT', root), patch.object(builder, 'check_build_host'), \
                 patch.object(builder, 'checked', side_effect=checked), \
                 patch.object(builder, 'check_glibc', return_value='2.35'):
                builder.build(args)
            self.assertEqual(previous.read_text(), 'original-frozen-packages\n')
            self.assertEqual(len(calls), 2)
            self.assertIn('test_linux_packaging.py', calls[0])
            self.assertEqual(calls[1][1], '--self-test')
            self.assertNotIn('PyInstaller', str(calls))
            self.assertNotIn('pip', str(calls))
            metadata = json.loads((root / 'dist-installer/neumoflow_1.0.1_mint21_amd64.build.json').read_text())
            self.assertTrue(metadata['reused_frozen_bundle'])
            self.assertTrue(metadata['frozen_self_test'])
            self.assertTrue(metadata['deb_tar_headers_verified'])
            self.assertFalse(metadata['mint_desktop_and_usb_verified'])

    def test_rejects_personal_calibration_patient_files_and_external_links(self):
        with TemporaryDirectory() as temporary:
            bundle = test_bundle(temporary)
            path = bundle / '_internal/app/calibracion.json'
            original = path.read_bytes()
            path.write_text(json.dumps({'fecha': '2026-01-01', 'factor_esp': 1., 'factor_ins': 1.}))
            with self.assertRaisesRegex(ValueError, 'calibración inicial'):
                builder.validate_bundle(bundle)
            path.write_bytes(original)
            local = bundle / 'pacientes.sqlite3'
            local.touch()
            with self.assertRaisesRegex(ValueError, 'clínicos'):
                builder.validate_bundle(bundle)
            local.unlink()
            (bundle / 'outside').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'fuera del paquete'):
                builder.validate_bundle(bundle)

    def test_rejects_host_or_elf_newer_than_mint21(self):
        with patch.object(builder.platform, 'machine', return_value='x86_64'), \
             patch.object(builder.platform, 'freedesktop_os_release', return_value={'ID': 'ubuntu'}), \
             patch.object(builder.platform, 'libc_ver', return_value=('glibc', '2.39')):
            with self.assertRaisesRegex(ValueError, '2.35'):
                builder.check_build_host()
        with TemporaryDirectory() as temporary:
            elf = Path(temporary) / 'program'
            elf.write_bytes(b'\x7fELF')
            result = subprocess.CompletedProcess([], 0, 'Version needs section\n Name: GLIBC_2.36\n')
            with patch.object(builder.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(ValueError, 'no entregar a Mint'):
                    builder.check_glibc(temporary)

    def test_linux_source_archive_uses_neutral_defaults_and_contains_build_scripts(self):
        spec = importlib.util.spec_from_file_location('linux_source', ROOT / 'packaging/prepare_linux_source.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as temporary:
            output = module.build_archive(destination=Path(temporary) / 'source.tar.gz')
            with tarfile.open(output) as source:
                names = source.getnames()
                self.assertEqual(len(names),len(set(names)))
                self.assertIn('NeumoFlow-Linux/packaging/build_linux.py', names)
                self.assertIn('NeumoFlow-Linux/packaging/linux/postinst', names)
                self.assertNotIn('NeumoFlow-Linux/RETOMAR_SESION.md', names)
                for name in names:
                    self.assertTrue(name.startswith('NeumoFlow-Linux/'))
                    self.assertFalse(name.endswith(('.cow', '.sqlite3', '.db', '.pcapng', '.pdf', '.pyc', '.exe')))
                neutral = json.loads(source.extractfile('NeumoFlow-Linux/app/calibracion.json').read())
                self.assertEqual(neutral['fecha'], 'pendiente')


if __name__ == '__main__':
    unittest.main()
