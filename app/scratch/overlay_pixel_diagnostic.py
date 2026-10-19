"""Captura píxeles del escritorio para validar los overlays nativos en Windows."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import struct
import sys
import zlib
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QWidget

RAIZ = Path(__file__).resolve().parent
NOMBRE_EVIDENCIA = "overlay_desktop"
sys.path.insert(0, str(RAIZ.parent.parent))

from app.ui.overlay_window import OverlayWindow, _FloatingPanel, PANEL_KEYS


def _capturar_escritorio() -> tuple[int, int, bytes]:
    """Captura el escritorio compuesto mediante BitBlt y devuelve RGBA.

    Parámetros: ninguno.
    Retorno: ancho, alto y bytes RGBA de la pantalla principal.
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.GetDC.restype = ctypes.c_void_p
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.BitBlt.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    gdi32.BitBlt.restype = ctypes.c_int
    ancho = user32.GetSystemMetrics(0)
    alto = user32.GetSystemMetrics(1)
    dc_pantalla = user32.GetDC(None)
    dc_memoria = gdi32.CreateCompatibleDC(dc_pantalla)
    bitmap = gdi32.CreateCompatibleBitmap(dc_pantalla, ancho, alto)
    bitmap_anterior = gdi32.SelectObject(dc_memoria, bitmap)
    if not gdi32.BitBlt(
        dc_memoria,
        0,
        0,
        ancho,
        alto,
        dc_pantalla,
        0,
        0,
        0x00CC0020 | 0x40000000,
    ):
        raise ctypes.WinError()

    class BITMAPINFOHEADER(ctypes.Structure):
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

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    info = BITMAPINFO()
    info.bmiHeader = BITMAPINFOHEADER(
        ctypes.sizeof(BITMAPINFOHEADER), ancho, -alto, 1, 32, 0, ancho * alto * 4, 0, 0, 0, 0
    )
    pixels = ctypes.create_string_buffer(ancho * alto * 4)
    filas = gdi32.GetDIBits(
        ctypes.c_void_p(dc_memoria),
        ctypes.c_void_p(bitmap),
        0,
        alto,
        pixels,
        ctypes.byref(info),
        0,
    )
    gdi32.SelectObject(ctypes.c_void_p(dc_memoria), ctypes.c_void_p(bitmap_anterior))
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
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.DeleteObject(ctypes.c_void_p(bitmap))
    gdi32.DeleteDC(ctypes.c_void_p(dc_memoria))
    user32.ReleaseDC(None, ctypes.c_void_p(dc_pantalla))
    if filas != alto:
        raise RuntimeError(f"GetDIBits devolvió {filas} de {alto} filas")
    origen = pixels.raw
    rgba = bytearray(len(origen))
    rgba[0::4] = origen[2::4]
    rgba[1::4] = origen[1::4]
    rgba[2::4] = origen[0::4]
    rgba[3::4] = b"\xff" * (ancho * alto)
    return ancho, alto, bytes(rgba)


def _guardar_png(ruta: Path, ancho: int, alto: int, rgba: bytes) -> None:
    """Guarda píxeles RGBA como PNG sin dependencias externas.

    Parámetros: ruta, dimensiones y píxeles RGBA.
    Retorno: None; escribe una captura de pantalla completa.
    """
    def chunk(tipo: bytes, datos: bytes) -> bytes:
        contenido = tipo + datos
        return struct.pack(">I", len(datos)) + contenido + struct.pack(">I", zlib.crc32(contenido))

    filas = b"".join(
        b"\0" + rgba[fila * ancho * 4 : (fila + 1) * ancho * 4]
        for fila in range(alto)
    )
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(filas, 6))
    png += chunk(b"IEND", b"")
    ruta.write_bytes(png)


def _contar_cambios(
    antes: bytes,
    despues: bytes,
    ancho: int,
    rect: tuple[int, int, int, int],
) -> int:
    """Compara la captura antes/después en la región de una ventana.

    Parámetros: dos imágenes RGBA, ancho de pantalla y rectángulo nativo.
    Retorno: cantidad de píxeles cuyo color visible cambió materialmente.
    """
    x, y, ancho_rect, alto_rect = rect
    cambios = 0
    for fila in range(max(0, y), min(y + alto_rect, len(antes) // (ancho * 4))):
        inicio = (fila * ancho + max(0, x)) * 4
        fin = (fila * ancho + min(ancho, x + ancho_rect)) * 4
        for indice in range(inicio, fin, 4):
            if max(
                abs(antes[indice + canal] - despues[indice + canal])
                for canal in range(3)
            ) > 20:
                cambios += 1
    return cambios


def _leer_rectangulo_nativo(panel: QWidget) -> tuple[int, int, int, int]:
    """Obtiene el rectángulo físico de pantalla a partir del HWND.

    Parámetros: ventana nativa.
    Retorno: x, y, ancho y alto en coordenadas del escritorio.
    """
    rect = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(
        ctypes.c_void_p(int(panel.winId())), ctypes.byref(rect)
    )
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _contar_color(
    rgba: bytes,
    ancho: int,
    rect: tuple[int, int, int, int],
    objetivo: tuple[int, int, int],
) -> int:
    """Cuenta píxeles de un color saturado dentro del rectángulo esperado.

    Parámetros: píxeles RGBA, ancho, rectángulo y color RGB objetivo.
    Retorno: píxeles coincidentes con tolerancia de 25 niveles por canal.
    """
    x, y, ancho_rect, alto_rect = rect
    total = 0
    for fila in range(max(0, y), min(y + alto_rect, len(rgba) // (ancho * 4))):
        inicio = (fila * ancho + max(0, x)) * 4
        fin = (fila * ancho + min(ancho, x + ancho_rect)) * 4
        trozo = rgba[inicio:fin]
        total += sum(
            1
            for indice in range(0, len(trozo), 4)
            if all(
                abs(trozo[indice + canal] - objetivo[canal]) <= 25
                for canal in range(3)
            )
        )
    return total


def _diagnosticar_hwnd(panel: QWidget, etiqueta: str) -> dict[str, object]:
    """Consulta geometría, estilos y compositor de un HWND visible.

    Parámetros: ventana y etiqueta de diagnóstico.
    Retorno: estado nativo relevante para explicar la composición.
    """
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_int
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetWindow.restype = ctypes.c_void_p
    hwnd = int(panel.winId())
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    estilos = user32.GetWindowLongPtrW(hwnd, -20)
    info: dict[str, object] = {
        "label": etiqueta,
        "hwnd": hex(hwnd),
        "qt_visible": panel.isVisible(),
        "win_visible": bool(user32.IsWindowVisible(hwnd)),
        "rect": (rect.left, rect.top, rect.right, rect.bottom),
        "opacity": panel.windowOpacity(),
        "exstyle": hex(estilos),
        "layered": bool(estilos & 0x00080000),
        "transparent": bool(estilos & 0x00000020),
        "noactivate": bool(estilos & 0x08000000),
        "topmost": bool(estilos & 0x00000008),
        "z_order_next": hex(int(user32.GetWindow(hwnd, 3) or 0)),
        "foreground": hex(int(user32.GetForegroundWindow() or 0)),
    }
    try:
        dwmapi = ctypes.windll.dwmapi
        cloaked = ctypes.c_int(-1)
        dwmapi.DwmGetWindowAttribute(
            hwnd,
            14,
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        info["cloaked"] = cloaked.value
    except (AttributeError, OSError):
        info["cloaked"] = "unavailable"
    print(f"hwnd_diagnostic={info}", flush=True)
    return info


def _contar_magenta_widget(panel: QWidget) -> int:
    """Cuenta píxeles magenta en el renderizado local de la ventana Qt.

    Parámetros: ventana de overlay.
    Retorno: píxeles magenta en el QPixmap de diagnóstico.
    """
    imagen = panel.grab().toImage()
    tarjeta = panel.card.grab().toImage()
    escena = QImage(500, 250, QImage.Format.Format_ARGB32_Premultiplied)
    escena.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(escena)
    panel.scene.render(pintor)
    pintor.end()
    imagen.save(str(RAIZ / "overlay_widget_grab.png"))
    tarjeta.save(str(RAIZ / "overlay_card_grab.png"))
    escena.save(str(RAIZ / "overlay_scene_render.png"))
    print(
        "qt_widget_state="
        f"card_visible:{panel.card.isVisible()} card_geometry:{panel.card.geometry()} "
        f"proxy_rect:{panel.proxy.boundingRect()} scene_items:{len(panel.scene.items())} "
        f"proxy_visible:{panel.proxy.isVisible()} proxy_opacity:{panel.proxy.opacity()} "
        f"proxy_widget_same:{panel.proxy.widget() is panel.card} "
        f"view_scene_rect:{panel.scene.sceneRect()} views:{len(panel.scene.views())} "
        f"sample_center:{imagen.pixelColor(imagen.width() // 2, imagen.height() // 2).getRgb()}",
        flush=True,
    )
    print(
        f"card_sample:{tarjeta.pixelColor(tarjeta.width() // 2, tarjeta.height() // 2).getRgb()} "
        f"card_stylesheet:{panel.card.styleSheet()!r} "
        f"scene_sample:{escena.pixelColor(250, 125).getRgb()}",
        flush=True,
    )
    cuenta = 0
    for y in range(imagen.height()):
        for x in range(imagen.width()):
            color = imagen.pixelColor(x, y)
            cuenta += color.red() > 230 and color.green() < 30 and color.blue() > 230 and color.alpha() > 230
    return cuenta


def _crear_ventana_diagnostico() -> tuple[_FloatingPanel, tuple[int, int, int, int]]:
    """Prepara la superficie magenta en el renderizador nativo de producción.

    Parámetros: ninguno.
    Retorno: ventana flotante y rectángulo esperado en coordenadas de pantalla.
    """
    panel = _FloatingPanel("gold", {})
    panel.base_width = 500
    panel.set_click_through(False)
    panel.set_overlay_opacity(100)
    panel.set_scale(1.0)
    panel.setWindowOpacity(1.0)
    panel.card.setProperty("diagnostic_fill", "#FF00FF")
    panel.card.setProperty("diagnostic_border_color", "#FFFFFF")
    panel.card.setProperty("diagnostic_border_width", 8)
    panel.card.setProperty("diagnostic_radius", 0)
    panel.card.update()
    etiqueta = QLabel("SOLRALOL OVERLAY TEST", panel.card)
    etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
    etiqueta.setStyleSheet("color: white; background: transparent; font-weight: 900;")
    fuente = QFont("Segoe UI", 26, QFont.Weight.Black)
    etiqueta.setFont(fuente)
    panel.body.addWidget(etiqueta)
    panel.card.setMinimumHeight(250)
    panel.adjustSize()
    panel.scene.setSceneRect(QRectF(0, 0, 500, 250))
    panel.setFixedSize(500, 250)
    pantalla = QGuiApplication.primaryScreen()
    if pantalla is None:
        raise RuntimeError("No hay monitor primario disponible")
    area = pantalla.geometry()
    x = area.left() + (area.width() - 500) // 2
    y = area.top() + (area.height() - 250) // 2
    panel.move(x, y)
    return panel, (x, y, panel.width(), panel.height())


def _crear_control_nativo() -> tuple[QWidget, tuple[int, int, int, int]]:
    """Crea una ventana Qt opaca de control para validar la captura GDI.

    Parámetros: ninguno.
    Retorno: ventana QWidget estándar y rectángulo esperado.
    """
    control = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
    control.setWindowTitle("Control de captura Solralol")
    control.setFixedSize(500, 250)
    control.setStyleSheet("background:#00C000; border:8px solid white;")
    etiqueta = QLabel("CAPTUREBLT CONTROL", control)
    etiqueta.setGeometry(20, 80, 460, 80)
    etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
    etiqueta.setStyleSheet("color:white; font-size:28px; font-weight:900;")
    pantalla = QGuiApplication.primaryScreen()
    if pantalla is None:
        raise RuntimeError("No hay monitor primario disponible")
    area = pantalla.geometry()
    x = area.left() + (area.width() - 500) // 2
    y = area.top() + (area.height() - 250) // 2
    control.move(x, y)
    return control, (x, y, 500, 250)


class _PersistenciaMemoria:
    """Evita escrituras del ensayo en los ajustes personales.

    Parámetros: ninguno.
    Retorno: proporciona el contrato mínimo usado por OverlayWindow.
    """

    def load(self) -> dict:
        """Devuelve un documento vacío para el ensayo.

        Parámetros: ninguno.
        Retorno: configuración vacía.
        """
        return {}

    def save(self, _settings: dict) -> None:
        """Descarta cambios de configuración propios del ensayo.

        Parámetros: configuración temporal.
        Retorno: None; no toca archivos del usuario.
        """
        return None


def _capturar_fase(
    nombre: str,
    panel: QWidget,
    rect: tuple[int, int, int, int],
    objetivo: tuple[int, int, int] = (255, 0, 255),
) -> int:
    """Guarda y mide una fase de captura del escritorio.

    Parámetros: nombre de fase, panel y rectángulo inspeccionado.
    Retorno: cantidad de píxeles magenta de la captura.
    """
    ancho, alto, rgba = _capturar_escritorio()
    _guardar_png(RAIZ / f"{NOMBRE_EVIDENCIA}_{nombre}.png", ancho, alto, rgba)
    pixeles = _contar_color(rgba, ancho, rect, objetivo)
    print(
        f"{nombre}: visible={panel.isVisible()} color_pixels={pixeles} rect={rect}",
        flush=True,
    )
    return pixeles


def main() -> int:
    """Ejecuta la prueba de escritorio y verifica capturas antes, durante y después.

    Parámetros: argumentos de proceso.
    Retorno: cero si la captura demuestra los píxeles de la ventana.
    """
    if sys.platform != "win32":
        raise RuntimeError("La captura de escritorio requiere Windows")
    app = QApplication(sys.argv)
    panel, rect = _crear_ventana_diagnostico()
    control, control_rect = _crear_control_nativo()
    resultados: dict[str, int] = {}

    def paso_antes() -> None:
        resultados["antes"] = _capturar_fase("antes", panel, rect)
        panel.show()
        panel.raise_()
        QTimer.singleShot(1500, paso_durante)

    def paso_durante() -> None:
        print(f"qt_widget_magenta={_contar_magenta_widget(panel)}", flush=True)
        _diagnosticar_hwnd(panel, "floating-panel")
        resultados["durante"] = _capturar_fase("durante", panel, rect)
        _ancho, _alto, imagen_opacidad_100 = _capturar_escritorio()
        panel.set_overlay_opacity(50)
        QTimer.singleShot(500, lambda: paso_opacidad_50(imagen_opacidad_100))

    def paso_opacidad_50(imagen_opacidad_100: bytes) -> None:
        """Compara la composición real con la opacidad configurada al 50 %.

        Parámetros: captura GDI del overlay al 100 %.
        Retorno: None; registra diferencia y captura la ventana semitransparente.
        """
        ancho, alto, imagen_opacidad_50 = _capturar_escritorio()
        _guardar_png(
            RAIZ / "overlay_desktop_opacity_50.png",
            ancho,
            alto,
            imagen_opacidad_50,
        )
        diferencia = _contar_cambios(imagen_opacidad_100, imagen_opacidad_50, ancho, rect)
        resultados["opacidad"] = diferencia
        print(f"opacity_50_changed_pixels={diferencia}", flush=True)
        panel.set_overlay_opacity(100)
        panel.hide()
        QTimer.singleShot(500, paso_despues)

    def paso_despues() -> None:
        resultados["despues"] = _capturar_fase("despues", panel, rect)
        control.show()
        control.raise_()
        QTimer.singleShot(500, paso_control)

    def paso_control() -> None:
        resultados["control"] = _capturar_fase(
            "control", control, control_rect, (0, 192, 0)
        )
        panel.close()
        control.close()
        diferencia = resultados["durante"] - max(
            resultados["antes"], resultados["despues"]
        )
        print(f"delta_magenta={diferencia} control_green={resultados['control']}", flush=True)
        if (
            resultados["durante"] < 90_000
            or diferencia < 90_000
            or resultados["opacidad"] < 20_000
        ):
            app.exit(2)
            return
        probar_paneles_reales()

    def probar_paneles_reales() -> None:
        """Verifica por captura de escritorio los cuatro paneles de producción.

        Parámetros: ninguno.
        Retorno: finaliza con código de error si alguna región no cambia.
        """
        nonlocal gestor
        enabled = {key: True for key in PANEL_KEYS}
        posiciones = {
            "gold": [35, 90],
            "alerts": [500, 90],
            "threat": [890, 90],
            "purchase": [1320, 90],
        }
        settings = {
            "overlay_panels": enabled,
            "overlay_positions": posiciones,
            "overlay_tab_only": {key: False for key in PANEL_KEYS},
            "overlay_panel_opacity": {key: 100 for key in PANEL_KEYS},
            "overlay_panel_click_through": {key: False for key in PANEL_KEYS},
            "overlay_panel_scales": {key: 1.0 for key in PANEL_KEYS},
            "overlay_opacity": 100,
        }
        OverlayWindow.configurar_registro_diagnostico()
        gestor = OverlayWindow({}, settings_service=_PersistenciaMemoria(), settings=settings)
        ancho, alto, imagen_antes = _capturar_escritorio()
        _guardar_png(RAIZ / "overlay_production_before.png", ancho, alto, imagen_antes)
        gestor.show_demo_overlays()
        app.processEvents()
        QTimer.singleShot(1500, lambda: terminar_prueba_paneles(imagen_antes, ancho, alto))

    def terminar_prueba_paneles(antes: bytes, ancho: int, alto: int) -> None:
        """Guarda captura de los paneles reales y valida cada región visible.

        Parámetros: píxeles de referencia y dimensiones del escritorio.
        Retorno: None; cierra la aplicación tras el resultado automatizado.
        """
        assert gestor is not None
        ancho_actual, alto_actual, despues = _capturar_escritorio()
        _guardar_png(RAIZ / "overlay_production_after.png", ancho_actual, alto_actual, despues)
        resultados_paneles: dict[str, int] = {}
        rectangulos: dict[str, tuple[int, int, int, int]] = {}
        for clave, ventana in gestor.panels.items():
            rect_panel = _leer_rectangulo_nativo(ventana)
            rectangulos[clave] = rect_panel
            cambios = _contar_cambios(antes, despues, ancho, rect_panel)
            resultados_paneles[clave] = cambios
            _diagnosticar_hwnd(ventana, clave)
            contenido = {
                "card": ventana.card.size().toTuple(),
                "window": ventana.size().toTuple(),
                "scale": ventana.scale_factor,
                "card_hint": ventana.card.sizeHint().toTuple(),
                "body_hint": ventana.body.sizeHint().toTuple(),
                "proxy": ventana.proxy.boundingRect().size().toSize().toTuple(),
                "lanes": len(getattr(ventana, "rows", [])),
                "lane_sizes": [row.size().toTuple() for row in getattr(ventana, "rows", [])],
            }
            print(
                f"production_panel={clave} visible={ventana.isVisible()} "
                f"geometry={rect_panel} changed_pixels={cambios} content={contenido}",
                flush=True,
            )
        if not all(valor > 1000 for valor in resultados_paneles.values()):
            for ventana in gestor.panels.values():
                ventana.close()
            app.exit(4)
            return
        for clave in PANEL_KEYS:
            gestor.set_panel_click_through(clave, True)
        app.processEvents()
        QTimer.singleShot(
            700,
            lambda: terminar_prueba_clickthrough(
                antes,
                despues,
                ancho,
                alto,
                rectangulos,
            ),
        )

    def terminar_prueba_clickthrough(
        antes: bytes,
        imagen_normal: bytes,
        ancho: int,
        alto: int,
        rectangulos: dict[str, tuple[int, int, int, int]],
    ) -> None:
        """Verifica pixels con click-through activo en las cuatro ventanas.

        Parámetros: referencia sin overlays, captura normal, dimensiones y rects.
        Retorno: None; cierra la prueba tras confirmar dibujo y modo de entrada.
        """
        assert gestor is not None
        _ancho_actual, _alto_actual, captura = _capturar_escritorio()
        _guardar_png(RAIZ / "overlay_production_clickthrough.png", ancho, alto, captura)
        resultados_clickthrough: dict[str, int] = {}
        for clave, ventana in gestor.panels.items():
            cambios = _contar_cambios(antes, captura, ancho, rectangulos[clave])
            diferencia_normal = _contar_cambios(
                imagen_normal, captura, ancho, rectangulos[clave]
            )
            resultado = bool(ventana.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            resultados_clickthrough[clave] = cambios
            print(
                f"production_clickthrough={clave} input_passthrough={resultado} "
                f"visible={ventana.isVisible()} changed_pixels={cambios} "
                f"delta_vs_normal={diferencia_normal}",
                flush=True,
            )
        for ventana in gestor.panels.values():
            ventana.close()
        correcto = all(valor > 1000 for valor in resultados_clickthrough.values())
        correcto = correcto and all(
            bool(gestor.panel_click_through[key]) for key in PANEL_KEYS
        )
        app.exit(0 if correcto else 5)

    gestor: OverlayWindow | None = None
    QTimer.singleShot(500, paso_antes)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
