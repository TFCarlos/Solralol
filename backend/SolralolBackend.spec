from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path.cwd()
analysis = Analysis(
    [str(root / "backend" / "protocol.py")],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files("certifi"),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="SolralolBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
