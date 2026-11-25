"""Export a neutral, explicit build-source package; never scan clinical folders."""
import importlib.util
import io
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent


def build_archive(root=ROOT, destination=None):
    root = Path(root)
    destination = Path(destination or root / 'dist-installer/NeumoFlow-Fuentes-Linux-Mint21-x64.tar.gz')
    # Reuse the existing reviewed allowlist, including resources used by the full
    # packaging test suite. It substitutes the neutral calibration automatically.
    spec = importlib.util.spec_from_file_location('neumoflow_source_export', root / 'packaging/prepare_windows_source.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='neumoflow-source-') as temporary:
        sources, _ = module.build_archive(root, Path(temporary) / 'sources.zip')
        with ZipFile(sources) as original, tarfile.open(destination, 'w:gz') as output:
            exported = set()
            for member in original.infolist():
                name = member.filename.removeprefix(module.SOURCE_FOLDER + '/')
                if name == 'source-manifest.json':
                    continue
                content = original.read(member)
                info = tarfile.TarInfo('NeumoFlow-Linux/' + name)
                info.mode = 0o644
                info.size = len(content)
                output.addfile(info, io.BytesIO(content))
                exported.add(name)
            extra = [root / 'README.md', root / 'packaging/build_linux.py',
                     root / 'packaging/crear-instalador-linux.sh',
                     root / 'packaging/prepare_linux_source.py',
                     root / 'packaging/neumoflow-linux.spec', root / 'packaging/constraints-linux.txt']
            extra += sorted((root / 'packaging/linux').glob('*'))
            extra += sorted((root / 'docs').glob('*.md'))
            extra += sorted((root / 'docs').glob('*.json'))
            for path in extra:
                if path.is_file() and path.relative_to(root).as_posix() not in exported:
                    output.add(path, arcname='NeumoFlow-Linux/' + path.relative_to(root).as_posix(), recursive=False)
    return destination


if __name__ == '__main__':
    print(build_archive())
