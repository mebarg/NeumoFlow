"""Export only build sources/resources, never local clinical data or captures."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parent.parent


def build_archive(root=ROOT, destination=None):
    root=Path(root)
    destination=Path(destination or root/'dist-installer/Espirometro-Fuentes-Windows-x64.zip')
    files={p.relative_to(root).as_posix():p for p in (root/'app').rglob('*.py') if '__pycache__' not in p.parts}
    files.update({p.relative_to(root).as_posix():p for p in (root/'tests').glob('test_*.py')})
    files.update({p.relative_to(root).as_posix():p for p in (root/'app/data/icons').glob('*.svg')})
    files.update({p.relative_to(root).as_posix():p for p in (root/'app/data/brand').glob('*') if p.suffix in ('.svg','.png','.ico')})
    for name in ('requirements.txt','requirements-build.txt','app/data/lup1.cfg',
                 'tests/fixtures/wfa_low_flow.json.gz','tests/fixtures/gli_2022_oracle.csv','tests/fixtures/gli_volumes_2021_oracle.csv',
                 'app/data/gli_global_2022.json','app/data/gli_volumes_2021.json','app/data/GLI-NOTICE.txt','packaging/README.md',
                 'packaging/espirometro.spec','packaging/espirometro.iss',
                 'packaging/constraints-windows.txt','packaging/build-windows.ps1',
                 'packaging/crear-instalador.cmd','packaging/usb-windows.html',
                 'packaging/defaults/calibracion.json','packaging/prepare_windows_source.py'):
        files[name]=root/name
    for name in ('packaging/check_usb_bundle.py','packaging/windows-usb/README.md'):
        files[name]=root/name
    for name in ('packaging/comprobar-windows.cmd','packaging/comprobar-windows.ps1'):
        files[name]=root/name
    for name in ('packaging/probar-app-windows.cmd','packaging/probar-app-windows.ps1',
                 'packaging/crear-ejecutable-prueba.cmd'):
        files[name]=root/name
    for name in ('packaging/setup-usb-windows.ps1',):
        files[name]=root/name
    for p in (root/'packaging/windows-usb/package').rglob('*'):
        if p.is_file():
            files[p.relative_to(root).as_posix()]=p
    # Running sources in Windows must also start from a neutral calibration.
    files['app/calibracion.json']=root/'packaging/defaults/calibracion.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    manifest={}
    with ZipFile(destination,'w',ZIP_DEFLATED) as archive:
        for name,path in sorted(files.items()):
            data=path.read_bytes()
            archive.writestr('Espirometro-Windows/'+name,data)
            manifest[name]=hashlib.sha256(data).hexdigest()
        archive.writestr('Espirometro-Windows/source-manifest.json',json.dumps(manifest,indent=2))
    return destination,manifest


if __name__=='__main__':
    output,manifest=build_archive()
    print(f'{output} ({len(manifest)} archivos)')
