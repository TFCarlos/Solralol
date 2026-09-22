"""Resolución de rutas de recursos (data/) para desarrollo y ejecutable frozen.

En desarrollo, ``DATA_DIR`` apunta al directorio ``data/`` del proyecto.

En un ejecutable de PyInstaller (``--onefile`` o ``--onedir``), los archivos
bundleados viven en ``sys._MEIPASS`` (temporal y **solo lectura**). Para poder
escribir en caché iconos e información descargada en tiempo de ejecución, los
datos se copian a ``~/.solralol/data/`` en el primer arranque y ahí se usan
tanto para lectura como para escritura. Si la copia falla por cualquier razón,
se devuelve el directorio del bundle (solo lectura): las lecturas siguen
funcionando y las escrituras que no están dentro de un ``try/except`` caen al
manejo de fallos que ya existe en el código.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Nombre del archivo marcador que indica que los datos están sincronizados.
_DATA_VERSION_MARKER = ".bundle_version"


def _copy_bundle_data() -> Path:
    """Copia los datos bundleados a ~/.solralol/data/ (solo la primera vez)."""
    meipass = Path(sys._MEIPASS)
    bundle_data = meipass / "data"
    user_data = Path.home() / ".solralol" / "data"

    if not bundle_data.exists():
        # No hay datos bundleados: usar el directorio de usuario vacío.
        user_data.mkdir(parents=True, exist_ok=True)
        return user_data

    # Si ya existe el directorio de usuario, actualizar archivos que falten
    # (por ejemplo después de una actualización del .exe) sin tocar los que
    # el usuario ya haya descargado/modificado.
    if not user_data.exists():
        user_data.parent.mkdir(parents=True, exist_ok=True)

    import shutil

    try:
        shutil.copytree(
            bundle_data,
            user_data,
            dirs_exist_ok=True,
        )
    except (OSError, shutil.Error):
        # Si falla la copia, usar el bundle read-only como fallback.
        return bundle_data

    return user_data


def _resolve_data_dir() -> Path:
    """Devuelve el directorio ``data`` apropiado según el modo de ejecución."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return _copy_bundle_data()

    # Modo desarrollo: raíz del proyecto (donde está _paths.py).
    return Path(__file__).resolve().parent / "data"


#: Directorio raíz de datos (JSON, iconos, etc.).
DATA_DIR: Path = _resolve_data_dir()
