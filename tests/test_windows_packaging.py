import hashlib
import importlib.util
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app import db, spirometry
from app.cpfs_signal import TABLE_SHA256
from app.smoke_test import run

ROOT=Path(__file__).resolve().parent.parent


class WindowsPackagingTests(unittest.TestCase):
    def test_brand_png_and_every_windows_icon_size_have_transparent_corners(self):
        import struct
        from PySide6.QtGui import QImage
        brand=ROOT/'app/data/brand'
        images=[QImage(str(brand/'neumoflow.png'))]
        raw=(brand/'neumoflow.ico').read_bytes()
        reserved,kind,count=struct.unpack_from('<HHH',raw)
        self.assertEqual((reserved,kind,count),(0,1,7))
        for index,size in enumerate((16,24,32,48,64,128,256)):
            length,offset=struct.unpack_from('<II',raw,6+index*16+8)
            image=QImage.fromData(raw[offset:offset+length],'PNG')
            self.assertEqual((image.width(),image.height()),(size,size))
            images.append(image)
        for image in images:
            self.assertTrue(image.hasAlphaChannel())
            for x,y in ((0,0),(image.width()-1,0),(0,image.height()-1),(image.width()-1,image.height()-1)):
                self.assertEqual(image.pixelColor(x,y).alpha(),0)
            self.assertGreaterEqual(image.pixelColor(image.width()//2,image.height()//2).alpha(),250)

    def test_integrated_usb_bundle_rejects_missing_changed_or_wrong_device(self):
        import shutil
        spec=importlib.util.spec_from_file_location('usb_bundle_check',ROOT/'packaging/check_usb_bundle.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as tmp:
            directory=Path(tmp)/'package'
            with self.assertRaisesRegex(ValueError,'Falta el componente USB'):
                module.validate_bundle(directory)
            shutil.copytree(ROOT/'packaging/windows-usb/package',directory)
            manifest=module.validate_bundle(directory)
            self.assertFalse(manifest['clean_install_verified'])
            path=directory/'manifest.json'
            changed=dict(manifest, device_id=r'USB\VID_1234&PID_5678')
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'Identificador USB'):
                module.validate_bundle(directory)
            path.write_text(json.dumps(manifest))
            cert=directory/'signer.cer'
            cert.write_bytes(cert.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'hash'):
                module.validate_bundle(directory)

    def test_source_export_contains_resources_and_neutral_calibration_not_clinical_files(self):
        spec=importlib.util.spec_from_file_location('source_export',ROOT/'packaging/prepare_windows_source.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as tmp:
            output,manifest=module.build_archive(destination=Path(tmp)/'sources.zip')
            with ZipFile(output) as archive:
                prefix='Espirometro-Windows/'
                self.assertEqual(archive.testzip(),None)
                names=archive.namelist()
                self.assertTrue(all(n.startswith(prefix) for n in names))
                for name in names:
                    self.assertFalse(name.endswith(('.sqlite3','.pdf','.pcapng','.pyc','.exe')))
                neutral=json.loads(archive.read(prefix+'app/calibracion.json'))
                self.assertEqual(neutral['fecha'],'pendiente')
                self.assertIsNone(neutral['temperatura_C'])
                self.assertEqual(neutral['factor_esp'],1.)
                self.assertEqual(hashlib.sha256(archive.read(prefix+'app/data/lup1.cfg')).hexdigest(),TABLE_SHA256)
                self.assertIn('packaging/crear-instalador.cmd',manifest)
                self.assertIn('app/data/gli_global_2022.json',manifest)
                self.assertIn('app/data/GLI-NOTICE.txt',manifest)
                for extension in ('png','ico'):
                    self.assertIn('app/data/brand/neumoflow.'+extension,manifest)
                self.assertIn('app/data/brand/neumoflow-source.png',manifest)
                self.assertIn('app/data/brand/neumoflow-transparent.png',manifest)
                self.assertEqual(json.loads(archive.read(prefix+'source-manifest.json')),manifest)
                for name,digest in manifest.items():
                    self.assertNotIn('\\',name, 'ZIP paths must use forward slashes on Windows too')
                    self.assertEqual(hashlib.sha256(archive.read(prefix+name)).hexdigest(),digest)

    def test_smoke_check_loads_resources_without_device_or_database_and_reports_failure(self):
        with TemporaryDirectory() as tmp,patch.object(spirometry,'open_device',side_effect=AssertionError('USB opened')), \
                patch.object(db,'connect',side_effect=AssertionError('Patient DB opened')):
            report=Path(tmp)/'check.json'
            self.assertEqual(run(report),0)
            self.assertTrue(json.loads(report.read_text())['libusb_library_loaded'])
            with patch.object(spirometry,'find_libusb_package_library',return_value=None):
                self.assertEqual(run(report),1)
            failed=json.loads(report.read_text())
            self.assertFalse(failed['ok'])
            self.assertIn('Falta la biblioteca libusb',failed['error'])


if __name__=='__main__':unittest.main()
