# -*- mode: python ; coding: utf-8 -*-

# PyInstaller build spec for SolraLoL.
#
# Los datos de campeones (JSON, iconos, etc.) se incluyen como datos del
# bundle y, en tiempo de ejecución, se sincronizan a ~/.solralol/data/ para
# poder escribir caché e información descargada (_paths.DATA_DIR lo gestiona
# de forma transparente tanto en modo desarrollo como frozen).

datas = [
    # Todos los datos de campeones, items, runas, iconos, etc.
    ('data', 'data'),
]

# Icono del ejecutable (.exe) generado a partir de data/LogoApp.png.
icon = 'data/LogoApp.ico'

hiddenimports = [
    # imageio-ffmpeg se importa dinámicamente en recording_service.py y PyInstaller
    # no lo detecta por sí mismo.
    'imageio_ffmpeg',
    # Módulos de Qt que se usan pero que PyInstaller a veces no captura.
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    # shiboken6 se usa en app/ui/draft_icon_cache.py para isValid().
    'shiboken6',
    # El paquete completo de PySide6.QtWebEngine* se incluye de forma explícita
    # porque PyInstaller no siempre resuelve las dependencias transitivas.
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineQuick',
    # Módulos internos que se importan con rutas relativas y que el analizador
    # estático puede perder.
    '_paths',
    'data_dragon',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Solralol',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
