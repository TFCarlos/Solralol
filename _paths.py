"""Resolución de rutas de recursos (data/) para desarrollo y ejecutable frozen.

En desarrollo, ``DATA_DIR`` apunta al directorio ``data/`` del proyecto.

En un ejecutable de PyInstaller (``--onefile`` o ``--onedir``), los archivos
bundleados viven en ``sys._MEIPASS`` (temporal y **solo lectura**). Los recursos
de usuario se copian, cuando hace falta, a ``data/`` dentro de la raíz activa
de ``StorageManager``. Si la copia falla se conserva el bundle como respaldo de
solo lectura; las escrituras persistentes nuevas usan rutas del almacenamiento
central.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from app.services.storage_manager import atomic_write_text, get_storage_manager

# Nombre del archivo marcador que indica que los datos están sincronizados.
_DATA_VERSION_MARKER = ".bundle_version"


def _copy_bundle_data() -> Path:
    """Copia los datos bundleados a la raíz activa (solo la primera vez)."""
    meipass = Path(sys._MEIPASS)
    bundle_data = meipass / "data"
    user_data = get_storage_manager().root / "data"

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
    bundled_data = os.environ.get("SOLRALOL_BUNDLE_DATA_DIR")
    if bundled_data and getattr(sys, "frozen", False):
        user_data = get_storage_manager().root / "data"
        bundle_version = os.environ.get("SOLRALOL_BUNDLE_VERSION", "unknown")
        marker = user_data / _DATA_VERSION_MARKER
        try:
            if marker.read_text(encoding="utf-8").strip() == bundle_version:
                return user_data
        except OSError:
            pass
        try:
            import shutil

            def copiar_solo_ausentes(origen: str, destino: str) -> str:
                if Path(destino).exists():
                    return destino
                return shutil.copy2(origen, destino)

            shutil.copytree(
                Path(bundled_data),
                user_data,
                dirs_exist_ok=True,
                copy_function=copiar_solo_ausentes,
            )
            atomic_write_text(marker, bundle_version)
        except (OSError, shutil.Error):
            return Path(bundled_data)
        return user_data

    """Devuelve el directorio ``data`` apropiado según el modo de ejecución."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return _copy_bundle_data()

    # Modo desarrollo: raíz del proyecto (donde está _paths.py).
    return Path(__file__).resolve().parent / "data"


#: Directorio raíz de datos (JSON, iconos, etc.).
DATA_DIR: Path = _resolve_data_dir()
