"""Mide estabilidad visual de overlays en la salida compuesta de Windows."""

from __future__ import annotations

import sys
import time
import ctypes
import ctypes.wintypes
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ.parent.parent))

from app.scratch.overlay_pixel_diagnostic import (
    _guardar_png,
    _leer_rectangulo_nativo,
)
from app.ui.overlay_window import PANEL_KEYS, OverlayWindow


def _capturar_region_escritorio(
    rect: tuple[int, int, int, int],
) -> tuple[int, int, bytes]:
    """Captura por GDI solo la región conjunta de los overlays.

    Parámetros: rectángulo físico del escritorio.
    Retorno: ancho, alto y píxeles RGBA de la composición visible.
    """
    x, y, ancho, alto = rect
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    dc_pantalla = user32.GetDC(None)
    dc_memoria = gdi32.CreateCompatibleDC(dc_pantalla)
    bitmap = gdi32.CreateCompatibleBitmap(dc_pantalla, ancho, alto)
    anterior = gdi32.SelectObject(dc_memoria, bitmap)
    capturado = gdi32.BitBlt(
        dc_memoria, 0, 0, ancho, alto, dc_pantalla, x, y, 0x00CC0020 | 0x40000000
    )

    class EncabezadoBitmap(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32),
            ("biWidth", ctypes.c_int32),
            ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16),
            ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32),
            ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32),
            ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32),
            ("biClrImportant", ctypes.c_uint32),
        ]

    class InformacionBitmap(ctypes.Structure):
        _fields_ = [("bmiHeader", EncabezadoBitmap), ("bmiColors", ctypes.c_uint32 * 3)]

    informacion = InformacionBitmap()
    informacion.bmiHeader = EncabezadoBitmap(
        ctypes.sizeof(EncabezadoBitmap), ancho, -alto, 1, 32, 0, ancho * alto * 4, 0, 0, 0, 0
    )
    pixels = ctypes.create_string_buffer(ancho * alto * 4)
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    filas = gdi32.GetDIBits(
        dc_memoria, bitmap, 0, alto, pixels, ctypes.byref(informacion), 0
    )
    gdi32.SelectObject(dc_memoria, anterior)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(dc_memoria)
    user32.ReleaseDC(None, dc_pantalla)
    if not capturado or filas != alto:
        raise ctypes.WinError()
    origen = pixels.raw
    rgba = bytearray(len(origen))
    rgba[0::4] = origen[2::4]
    rgba[1::4] = origen[1::4]
    rgba[2::4] = origen[0::4]
    rgba[3::4] = b"\xff" * (ancho * alto)
    return ancho, alto, bytes(rgba)


class _PersistenciaMemoria:
    """Evita leer o escribir preferencias reales durante la prueba."""

    def load(self) -> dict:
        """Devuelve ajustes vacíos para el gestor de prueba.

        Parámetros: ninguno.
        Retorno: documento vacío.
        """
        return {}

    def save(self, _settings: dict) -> None:
        """Descarta cambios temporales de configuración.

        Parámetros: ajustes de la prueba.
        Retorno: None; no escribe preferencias de usuario.
        """
        return None


def _muestras_region(
    rgba: bytes,
    ancho: int,
    rect: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int], ...]:
    """Extrae una cuadrícula interior para detectar desapariciones del panel.

    Parámetros: captura RGBA, ancho del escritorio y rectángulo de ventana.
    Retorno: colores de 7 por 7 puntos separados del borde redondeado.
    """
    x, y, ancho_rect, alto_rect = rect
    muestras = []
    for fila in range(7):
        py = y + 12 + round((alto_rect - 24) * (fila + 0.5) / 7)
        for columna in range(7):
            px = x + 12 + round((ancho_rect - 24) * (columna + 0.5) / 7)
            indice = (py * ancho + px) * 4
            muestras.append(tuple(rgba[indice : indice + 3]))
    return tuple(muestras)


def main() -> int:
    """Muestra los cuatro overlays y compara sus píxeles compuestos por 2 s.

    Parámetros: ninguno.
    Retorno: código cero si las ventanas y sus regiones permanecen estables.
    """
    app = QApplication.instance() or QApplication([])
    ajustes = {
        "overlay_panels": {key: True for key in PANEL_KEYS},
        "overlay_tab_only": {key: False for key in PANEL_KEYS},
        "overlay_panel_click_through": {key: False for key in PANEL_KEYS},
        "overlay_panel_scales": {key: 1.0 for key in PANEL_KEYS},
    }
    gestor = OverlayWindow({}, _PersistenciaMemoria(), ajustes)
    gestor.show_demo_overlays()
    pantalla = QGuiApplication.primaryScreen()
    if pantalla is not None:
        limites = pantalla.availableGeometry()
        cursor_x = limites.left() + 16
        cursor_y = limites.top() + 24
        alto_fila = 0
        for panel in gestor.panels.values():
            if cursor_x + panel.width() > limites.right() + 1:
                cursor_x = limites.left() + 16
                cursor_y += alto_fila + 12
                alto_fila = 0
            panel.move(cursor_x, cursor_y)
            cursor_x += panel.width() + 12
            alto_fila = max(alto_fila, panel.height())
    app.processEvents()
    time.sleep(0.25)
    app.processEvents()
    rectangulos = {
        key: _leer_rectangulo_nativo(panel) for key, panel in gestor.panels.items()
    }
    x_region = min(rect[0] for rect in rectangulos.values())
    y_region = min(rect[1] for rect in rectangulos.values())
    x_final = max(rect[0] + rect[2] for rect in rectangulos.values())
    y_final = max(rect[1] + rect[3] for rect in rectangulos.values())
    rect_region = (x_region, y_region, x_final - x_region, y_final - y_region)
    rectangulos_locales = {
        key: (rect[0] - x_region, rect[1] - y_region, rect[2], rect[3])
        for key, rect in rectangulos.items()
    }
    ancho, alto, referencia = _capturar_region_escritorio(rect_region)
    base = {
        key: _muestras_region(referencia, ancho, rect)
        for key, rect in rectangulos_locales.items()
    }
    compra = gestor.panels["purchase"]
    recomendaciones_estaticas = [
        {"item_id": "3100", "name": "Perdición del liche", "score": 37.9},
        {"item_id": "4646", "name": "Sobrecarga tormentosa", "score": 23.9},
        {"item_id": "4645", "name": "Llamasombría", "score": 19.6},
    ]
    compra_widgets = tuple(id(card["widget"]) for card in compra.cards)
    compra_hwnd = int(compra.winId())
    compra_cambios = compra.model_change_count
    compra_geometria = compra.geometry()
    _guardar_png(RAIZ / "overlay_stability_before.png", ancho, alto, referencia)
    frames = 0
    frames_blank = {key: 0 for key in PANEL_KEYS}
    frames_changed = {key: 0 for key in PANEL_KEYS}
    inicio = time.perf_counter()
    fin = inicio + 2.0
    while time.perf_counter() < fin:
        compra.render("Gragas", recomendaciones_estaticas)
        app.processEvents()
        _ancho, _alto, captura = _capturar_region_escritorio(rect_region)
        frames += 1
        for key, rect in rectangulos_locales.items():
            muestras = _muestras_region(captura, ancho, rect)
            cambios = sum(
                max(abs(a - b) for a, b in zip(color, inicial)) > 45
                for color, inicial in zip(muestras, base[key])
            )
            if cambios:
                frames_changed[key] += 1
            if cambios >= 42:
                frames_blank[key] += 1
    duracion = time.perf_counter() - inicio
    _ancho, _alto, final = _capturar_region_escritorio(rect_region)
    _guardar_png(RAIZ / "overlay_stability_after.png", ancho, alto, final)
    rectangulos_finales = {
        key: _leer_rectangulo_nativo(panel) for key, panel in gestor.panels.items()
    }
    compra_estable = (
        compra.model_change_count == compra_cambios
        and tuple(id(card["widget"]) for card in compra.cards) == compra_widgets
        and int(compra.winId()) == compra_hwnd
        and compra.geometry() == compra_geometria
    )
    print(
        f"purchase_identical_updates={frames} model_changes={compra.model_change_count - compra_cambios} "
        f"hwnd_stable={int(compra.winId()) == compra_hwnd} "
        f"widgets_stable={tuple(id(card['widget']) for card in compra.cards) == compra_widgets} "
        f"geometry_stable={compra.geometry() == compra_geometria}",
        flush=True,
    )
    for key, panel in gestor.panels.items():
        print(
            f"panel={key} visible={panel.isVisible()} rect={rectangulos[key]} "
            f"rect_stable={rectangulos_finales[key] == rectangulos[key]} "
            f"frames_different={frames_changed[key]} blank_like_frames={frames_blank[key]}",
            flush=True,
        )
    fps = frames / max(duracion, 0.001)
    print(f"desktop_capture_frames={frames} elapsed={duracion:.3f}s fps={fps:.1f}", flush=True)
    correcto = compra_estable and all(
        panel.isVisible()
        and rectangulos_finales[key] == rectangulos[key]
        and frames_blank[key] == 0
        for key, panel in gestor.panels.items()
    )
    gestor.close()
    app.processEvents()
    return 0 if correcto else 3


if __name__ == "__main__":
    raise SystemExit(main())
