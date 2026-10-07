"""Iconos vectoriales de trazo uniforme, cacheados y sin dependencias de fuentes."""

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.ui.sistema_visual import PALETA

TRAZOS_ACCIONES = {
    "cerrar": "M6 6l12 12M18 6L6 18",
    "actualizar": "M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 14-2l1 6M4 12l1 6a8 8 0 0 0 14-2",
    "guardar": "M4 3h13l3 3v15H4zM8 3v6h8V3M8 21v-8h8v8",
    "eliminar": "M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7",
    "play": "M8 5l12 7-12 7z",
    "pausa": "M8 5v14M16 5v14",
    "parar": "M6 6h12v12H6z",
    "retroceder": "M11 5l-8 7 8 7V5zM21 5l-8 7 8 7V5z",
    "avanzar": "M3 5l8 7-8 7V5zM13 5l8 7-8 7V5z",
    "volumen": "M3 9h4l5-5v16l-5-5H3zM16 8a6 6 0 0 1 0 8M19 5a10 10 0 0 1 0 14",
    "silencio": "M3 9h4l5-5v16l-5-5H3zM16 9l5 6M21 9l-5 6",
    "carpeta": "M3 5h7l2 3h9v12H3z",
    "abrir": "M14 3h7v7M21 3l-11 11M10 4H4v16h16v-6",
    "pantalla": "M3 9V3h6M15 3h6v6M21 15v6h-6M9 21H3v-6",
    "informacion": "M12 11v6M12 7v1M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20",
    "advertencia": "M12 3L2 21h20zM12 9v5M12 17v1",
    "exito": "M5 12l4 4L19 6",
    "analisis": "M4 3v18h17M8 16v-5m5 5V7m5 9V4",
    "ajustes": "M9 3h6l1 4 4 2v6l-4 2-1 4H9l-1-4-4-2V9l4-2zM9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
    "editar": "M4 16l12-12 4 4-12 12H4zM13 7l4 4",
    "buscar": "M10 3a7 7 0 1 0 0 14a7 7 0 1 0 0-14M15 15l6 6",
    "video": "M3 6h13v12H3zM16 10l5-3v10l-5-3",
    "draft": "M4 3l16 16M20 3L4 19M2 17l5 5M17 22l5-5",
    "ia": "M4 7h16v13H4zM12 3v4M8 11v2M16 11v2M8 17h8",
}


@lru_cache(maxsize=128)
def icono_trazo(trazo: str) -> QIcon:
    """Devuelve el icono del trazo SVG recibido, con variante deshabilitada."""
    icono = QIcon()
    for modo, color in ((QIcon.Mode.Normal, PALETA["oro_suave"]),
                        (QIcon.Mode.Disabled, PALETA["texto_deshabilitado"])):
        contenido = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{trazo}" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>'
        imagen = QPixmap(24, 24)
        imagen.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagen)
        QSvgRenderer(QByteArray(contenido.encode())).render(pintor)
        pintor.end()
        icono.addPixmap(imagen, modo)
    return icono


def icono_accion(nombre: str) -> QIcon:
    """Resuelve nombre en la biblioteca compartida y devuelve su icono vectorial."""
    return icono_trazo(TRAZOS_ACCIONES.get(nombre, TRAZOS_ACCIONES["informacion"]))
