import hashlib
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('release_metadata', ROOT/'packaging/release_metadata.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseMetadataTests(unittest.TestCase):
    def test_tag_requires_portable_numeric_version(self):
        self.assertEqual(release.release_version('v1.0.3'), '1.0.3')
        self.assertEqual(release.release_version('v65535.0.1'), '65535.0.1')
        for tag in ('1.0.3', 'v01.0.3', 'v1.2', 'v1.0.3-beta', 'v1.2.3\n',
                    'v65536.0.0', 'v1.2.3;echo bad', 'v'+'9'*10000+'.0.0'):
            with self.subTest(tag=tag[:80]), self.assertRaises(ValueError):
                release.release_version(tag)

    def test_publish_requires_both_installers_and_matching_checksums(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            names = ['NeumoFlowSetup-1.0.3.exe', 'neumoflow_1.0.3_mint21_amd64.deb']
            for name in names:
                data = name.encode()
                (directory/name).write_bytes(data)
                (directory/(name+'.sha256')).write_text(hashlib.sha256(data).hexdigest()+'  '+name+'\n')
            self.assertEqual(len(release.verify_assets(directory, 'v1.0.3')), 4)
            (directory/names[0]).write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                release.verify_assets(directory, 'v1.0.3')
            (directory/names[0]).write_bytes(names[0].encode())
            extra = directory/'patient.db'
            extra.write_bytes(b'never publish')
            with self.assertRaises(ValueError):
                release.verify_assets(directory, 'v1.0.3')
            extra.unlink()
            (directory/names[1]).unlink()
            with self.assertRaises(ValueError):
                release.verify_assets(directory, 'v1.0.3')
