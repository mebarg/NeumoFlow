# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).resolve().parent
resources = [
    (root / 'packaging/defaults/calibracion.json', 'app'),
    (root / 'app/data/lup1.cfg', 'app/data'),
    (root / 'app/data/gli_global_2022.json', 'app/data'),
    (root / 'app/data/gli_volumes_2021.json', 'app/data'),
    (root / 'app/data/GLI-NOTICE.txt', 'app/data'),
    (root / 'app/data/brand/neumoflow.png', 'app/data/brand'),
    (root / 'app/data/brand/neumoflow.ico', 'app/data/brand'),
]
resources += [(path, 'app/data/icons') for path in (root / 'app/data/icons').glob('*.svg')]
datas = [(str(path), destination) for path, destination in resources]
datas += collect_data_files('pyspiro')
for distribution in ('PySide6', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6',
                     'pyusb', 'pyserial', 'pyspiro', 'numpy', 'pandas', 'libusb-package'):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(root / 'app/main.py')], pathex=[str(root)],
    binaries=collect_dynamic_libs('libusb_package'), datas=datas,
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'tkinter'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='NeumoFlow',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='NeumoFlow')
