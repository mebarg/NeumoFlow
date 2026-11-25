# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata


root = Path(SPECPATH).resolve().parent

datas = [
    (str(root / "packaging/defaults/calibracion.json"), "app"),
    (str(root / "app/data/lup1.cfg"), "app/data"),
    (str(root / "app/data/gli_global_2022.json"), "app/data"),
    (str(root / "app/data/gli_volumes_2021.json"), "app/data"),
    (str(root / "app/data/GLI-NOTICE.txt"), "app/data"),
    (str(root / "app/data/brand/neumoflow.png"), "app/data/brand"),
    (str(root / "app/data/brand/neumoflow.ico"), "app/data/brand"),
    (str(root / "app/data/brand/neumoflow-source.png"), "app/data/brand"),
    (str(root / "app/data/brand/neumoflow-transparent.png"), "app/data/brand"),
] + [(str(path), "app/data/icons") for path in (root / "app/data/icons").glob("*.svg")] + collect_data_files("pyspiro")

binaries = collect_dynamic_libs("libusb_package")
for distribution in ('PySide6', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6',
                     'pyusb', 'pyserial', 'pyspiro', 'numpy', 'pandas', 'libusb-package'):
    datas += copy_metadata(distribution)


a = Analysis(
    [str(root / "app/main.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeumoFlow",
    icon=str(root / "app/data/brand/neumoflow.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NeumoFlow",
)
