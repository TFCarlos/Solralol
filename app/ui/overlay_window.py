"""Overlays flotantes de la partida en vivo.

Tres paneles independientes, sin títulos y con la mínima información posible,
pensados para ocupar poco sobre el juego:

- ``gold``: oro por rol (aliado contra rival) y la diferencia acumulada.
- ``alerts``: compras de objetos completos y objetivos a punto de aparecer.
- ``threat``: el rival más fuerte y el más débil del equipo enemigo.

Cada panel se arrastra con el ratón, comparte opacidad y modo "click-through" y
recuerda su posición y su visibilidad en ``~/.solralol/settings.json``. Solo se
muestran durante una partida: fuera de ella no hay nada que enseñar.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from _paths import DATA_DIR
from app.services.elegibilidad_objetos import MODO_SOLOQ
from app.services.live_player_metrics_service import (
    ROLE_SHORT_LABELS,
    build_gold_report,
    build_rival_ranking,
    format_delta,
    format_gold,
)
from app.services.overlay_alert_service import (
    OverlayAlertTracker,
    format_clock,
)
from app.services.overlay_sound_service import (
    DEFAULT_VOLUME,
    OverlaySoundService,
)
from app.services.settings_service import SettingsService
from app.ui.async_task import run_async
from app.ui.tema import (
    aplicar_apariencia,
    aplicar_tema,
)
from data_dragon import get_champion_icon_path, get_item_icon_path

PANEL_KEYS = ("gold", "alerts", "threat", "purchase")

PANEL_LABELS = {
    "gold": "Oro",
    "alerts": "Alertas",
    "threat": "Rivales",
    "purchase": "Compra",
}

PANEL_WIDTHS = {
    "gold": 326,
    "alerts": 316,
    "threat": 302,
    "purchase": 370,
}

DEFAULT_OPACITY = 92
MIN_OPACITY = 0
MAX_OPACITY = 100
DEFAULT_ALERT_LEAD = 60
DEFAULT_NOTIFICATION_DURATION = 5
MIN_ALERT_LEAD = 15
MAX_ALERT_LEAD = 180
MAX_ALERT_ROWS = 1

CHAMPION_ICON_SIZE = 28
ITEM_ICON_SIZE = 20
PANEL_MARGIN = 24
PANEL_GAP = 12
PANEL_TOP_OFFSET = 120
PANEL_CORNER_RADIUS = 13

GOLD_LABEL_WIDTH = 52
DELTA_LABEL_WIDTH = 52
ROLE_LABEL_WIDTH = 34
THREAT_NAME_WIDTH = 94
ALERT_TEXT_WIDTH = 150

_DECORATIVE_ICON_CACHE: dict[tuple[str, int, int], QPixmap] = {}
_LOGGER = logging.getLogger(__name__)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _set_property(widget: QWidget, name: str, value) -> None:
    """Cambia una propiedad de estilo solo si hace falta (evita repintados)."""
    if widget.property(name) == value:
        return

    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _elide(label: QLabel, text: str, width: int) -> None:
    metrics = label.fontMetrics()
    label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))


def _icon_label(size: int) -> QLabel:
    label = QLabel()
    label.setObjectName("overlayIcon")
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setProperty("state", "empty")
    label.setProperty("asset_key", "")

    return label


def _set_decorative_icon(label: QLabel, name: str, size: int) -> None:
    """Carga un SVG decorativo local con caché y conserva un fallback.

    Parámetros: etiqueta destino, nombre del SVG y tamaño lógico.
    Retorno: None; asigna un pixmap transparente al control.
    """
    escala = label.devicePixelRatioF()
    clave = (name, size, round(escala * 100))
    pixmap = _DECORATIVE_ICON_CACHE.get(clave)
    if pixmap is None:
        ruta = DATA_DIR / "overlays" / "icons" / f"{name}.svg"
        pixmap = QPixmap(round(size * escala), round(size * escala))
        pixmap.setDevicePixelRatio(escala)
        pixmap.fill(Qt.GlobalColor.transparent)
        renderizador = QSvgRenderer(str(ruta)) if ruta.is_file() else None
        if renderizador is not None and renderizador.isValid():
            pintor = QPainter(pixmap)
            renderizador.render(pintor)
            pintor.end()
        else:
            ruta_png = DATA_DIR / "overlays" / "icons" / f"{name}.png"
            pixmap = QPixmap(str(ruta_png))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    round(size * escala),
                    round(size * escala),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                pixmap.setDevicePixelRatio(escala)
        _DECORATIVE_ICON_CACHE[clave] = pixmap
    label.setPixmap(pixmap)


def _calcular_compras_recomendadas(
    campeon: str,
    enemigos: tuple[tuple[str, str], ...],
    objetos_poseidos: tuple[str, ...],
    pagina_runas: dict | None,
    modo_partida: str = "CLASSIC",
    rol_jugador: str = "",
    instantanea: dict | None = None,
    catalogo_objetos: dict | None = None,
    sesion_live: dict | None = None,
) -> list[dict]:
    """Calcula hasta tres compras con el motor de recomendaciones LIVE.

    Parámetros: contexto de partida y fallback curado para llamadas heredadas.
    Retorno: candidatos elegibles y puntuados por sinergia y respuesta a rivales.
    """
    if isinstance(sesion_live, dict):
        from app.services.live_recommendation_service import LiveRecommendationService

        servicio = LiveRecommendationService(catalogo_objetos or {})
        informe = servicio.analyze(sesion_live)
        return [
            {
                "item_id": str(recomendacion.get("id", "")),
                "name": str(recomendacion.get("name", "Objeto")),
                "score": float(recomendacion.get("score", 0.0)),
                "cost": recomendacion.get("cost"),
                "next_buy": recomendacion.get("next_buy", {}),
                "reasons": list(recomendacion.get("reasons", []))
                + list(recomendacion.get("responses", [])),
            }
            for recomendacion in informe.get("recommendations", [])[:3]
            if str(recomendacion.get("id", ""))
        ]

    if isinstance(instantanea, dict):
        from app.services.live_recommendation_service import LiveRecommendationService

        servicio = LiveRecommendationService(catalogo_objetos or {})
        jugador_local = instantanea.get("local_player", {})
        equipo_local = str(
            instantanea.get("local_team") or (jugador_local or {}).get("team") or ""
        )
        jugadores_api = instantanea.get("all_players", [])
        jugadores_api = jugadores_api if isinstance(jugadores_api, list) else []
        jugadores: dict[str, dict] = {}
        clave_local = ""
        campeon_local = str((jugador_local or {}).get("championName") or campeon)
        nombre_local = str(
            (jugador_local or {}).get("riotId")
            or (jugador_local or {}).get("summonerName")
            or ""
        ).casefold()
        for indice, jugador in enumerate(jugadores_api):
            if not isinstance(jugador, dict):
                continue
            equipo = str(jugador.get("team") or "")
            campeon_api = str(jugador.get("championName") or "")
            nombre_api = str(
                jugador.get("riotId") or jugador.get("summonerName") or ""
            ).casefold()
            es_local = bool(
                (nombre_local and nombre_api == nombre_local)
                or (equipo_local and equipo == equipo_local and campeon_api == campeon_local)
            )
            clave = f"player-{indice}"
            rol_api = str(
                jugador.get("position") or jugador.get("teamPosition") or "UNKNOWN"
            ).upper()
            rol = {
                "TOP": "top",
                "JUNGLE": "jungle",
                "MIDDLE": "mid",
                "MID": "mid",
                "BOTTOM": "bot",
                "ADC": "bot",
                "UTILITY": "support",
                "SUPPORT": "support",
            }.get(rol_api, "UNKNOWN")
            items = jugador.get("items", [])
            marcador = jugador.get("scores")
            marcador = marcador if isinstance(marcador, dict) else {}
            jugadores[clave] = {
                "player_key": clave,
                "team": equipo,
                "side": "ally" if equipo == equipo_local else "enemy",
                "role": rol,
                "champion_name": campeon_api,
                "items": items if isinstance(items, list) else [],
                "kills": marcador.get("kills", 0),
                "deaths": marcador.get("deaths", 0),
                "assists": marcador.get("assists", 0),
                "level": jugador.get("level"),
            }
            if es_local:
                clave_local = clave
        if not clave_local and campeon_local:
            clave_local = "local-player"
            items_locales = (jugador_local or {}).get("items", [])
            jugadores[clave_local] = {
                "player_key": clave_local,
                "team": equipo_local,
                "side": "ally",
                "role": rol_jugador or "UNKNOWN",
                "champion_name": campeon_local,
                "items": items_locales if isinstance(items_locales, list) else [],
                "current_gold": (jugador_local or {}).get("currentGold"),
                "level": (jugador_local or {}).get("level"),
            }
        if not clave_local:
            return []
        local_normalizado = jugadores[clave_local]
        local_normalizado["current_gold"] = (jugador_local or {}).get(
            "currentGold", local_normalizado.get("current_gold")
        )
        local_normalizado["runes"] = (jugador_local or {}).get("runes", {})
        duracion = max(0.0, float(instantanea.get("game_time", 0) or 0))
        sesion = {
            "game_mode": modo_partida,
            "duration": duracion,
            "local_team": equipo_local,
            "local_player_key": clave_local,
            "champion_name": campeon_local,
            "players": jugadores,
            "snapshots": [{"time": duracion, "players": jugadores}],
        }
        informe = servicio.analyze(sesion)
        return [
            {
                "item_id": str(recomendacion.get("id", "")),
                "name": str(recomendacion.get("name", "Objeto")),
                "score": float(recomendacion.get("score", 0.0)),
                "cost": recomendacion.get("cost"),
                "next_buy": recomendacion.get("next_buy", {}),
                "reasons": list(recomendacion.get("reasons", []))
                + list(recomendacion.get("responses", [])),
            }
            for recomendacion in informe.get("recommendations", [])[:3]
            if str(recomendacion.get("id", ""))
        ]

    from app.services.draft_analyzer_service import DraftAnalyzerService

    modo_normalizado = str(modo_partida or "").upper()
    if modo_normalizado == "ARAM":
        modo_elegibilidad = "ARAM"
    elif modo_normalizado in {"CLASSIC", "SR_RANKED_SOLO_DUO"}:
        modo_elegibilidad = MODO_SOLOQ
    else:
        return []
    analizador = DraftAnalyzerService()
    perfil = analizador.get_champion_profile(campeon)
    if not isinstance(perfil, dict):
        return []
    variante = analizador._variante_recomendaciones_curada(
        campeon, perfil, pagina_runas, rol_jugador or None
    )
    candidatos = variante.get("recommended_build", [])
    if not isinstance(candidatos, list) or not candidatos:
        candidatos = (
            variante.get("item_candidates")
            or variante.get("recommendations")
            or variante.get("situational_item_candidates", [])
        )
    ids_candidatos = {
        str(item.get("item_id", item.get("id", "")))
        for item in candidatos
        if isinstance(item, dict)
    }
    estilo = str(perfil.get("basic_info", {}).get("play_style", "Adaptable"))
    motor = analizador.curador.motor_sinergia
    amenazas = [(nombre, rol) for nombre, rol in enemigos if nombre]
    puntuados_base = motor.rank_candidates(
        perfil,
        estilo,
        analizador.items,
        [],
        game_mode=modo_elegibilidad,
        catalog_patch=analizador.version,
    )
    puntuados_actuales = motor.rank_candidates(
        perfil,
        estilo,
        analizador.items,
        amenazas,
        game_mode=modo_elegibilidad,
        catalog_patch=analizador.version,
    )
    base_por_id = {item.item_id: item.score for item in puntuados_base}
    actual_por_id = {item.item_id: item.score for item in puntuados_actuales}
    candidato_por_id = {
        str(item.get("item_id", item.get("id", ""))): item
        for item in candidatos
        if isinstance(item, dict)
    }
    return [
        {
            "item_id": item_id,
            "name": str(
                candidato.get("name", analizador.items[item_id].get("name", item_id))
            ),
            "score": round(
                float(candidato.get("score", candidato.get("synergy_score", 0.0)))
                + actual_por_id.get(item_id, 0.0)
                - base_por_id.get(item_id, 0.0),
                1,
            ),
            "reasons": list(candidato.get("reasons", [])),
        }
        for item_id, candidato in sorted(
            candidato_por_id.items(),
            key=lambda par: (
                -(
                    float(par[1].get("score", par[1].get("synergy_score", 0.0)))
                    + actual_por_id.get(par[0], 0.0)
                    - base_por_id.get(par[0], 0.0)
                ),
                par[0],
            ),
        )
        if item_id in ids_candidatos
        and item_id not in objetos_poseidos
        and item_id in analizador.items
        and item_id in actual_por_id
    ][:3]


def _nombre_runa(valor: object) -> str:
    """Extrae el nombre visible de una runa reportada por Live Client.

    Parámetros: nombre directo o diccionario de runa/árbol.
    Retorno: nombre visible o cadena vacía si no se reconoce.
    """
    if isinstance(valor, dict):
        return str(valor.get("displayName") or valor.get("name") or "")
    return str(valor or "")


def _normalizar_runas_vivas(datos: object) -> dict | None:
    """Normaliza los campos de runas disponibles en el snapshot en vivo.

    Parámetros: contenido `runes` del jugador local.
    Retorno: página compatible con el curador o None si la API no la aporta.
    """
    if not isinstance(datos, dict) or not datos:
        return None
    keystone = _nombre_runa(datos.get("keystone"))
    if not keystone:
        return None
    primarias = datos.get("primaryRuneTree") or datos.get("primary_tree")
    secundarias = datos.get("secondaryRuneTree") or datos.get("secondary_tree")
    nombres = [
        _nombre_runa(valor)
        for clave, valor in datos.items()
        if clave
        not in {
            "keystone",
            "primaryRuneTree",
            "primary_tree",
            "secondaryRuneTree",
            "secondary_tree",
        }
    ]
    return {
        "keystone": keystone,
        "primary_tree": _nombre_runa(primarias),
        "secondary_tree": _nombre_runa(secundarias),
        "runes": [nombre for nombre in nombres if nombre],
    }


class _OverlayCard(QFrame):
    """Pinta el fondo y borde de la tarjeta con un único contorno redondeado."""

    def paintEvent(self, event) -> None:
        """Dibuja el fondo con alfa transparente fuera del radio de esquina.

        Parámetros: evento de pintura de Qt.
        Retorno: None; evita que el estilo base pinte un fondo rectangular.
        """
        super().paintEvent(event)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        ancho_borde = self.property("diagnostic_border_width")
        ancho_borde = max(1.0, float(ancho_borde or 1.0))
        rectangulo = QRectF(self.rect()).adjusted(
            ancho_borde / 2,
            ancho_borde / 2,
            -ancho_borde / 2,
            -ancho_borde / 2,
        )
        ruta = QPainterPath()
        radio = self.property("diagnostic_radius")
        radio = PANEL_CORNER_RADIUS if radio is None else max(0.0, float(radio))
        ruta.addRoundedRect(rectangulo, radio, radio)
        relleno = self.property("diagnostic_fill")
        if relleno:
            pincel = QColor(str(relleno))
        else:
            gradiente = QLinearGradient(rectangulo.topLeft(), rectangulo.bottomRight())
            gradiente.setColorAt(0.0, QColor(20, 27, 38, 248))
            gradiente.setColorAt(1.0, QColor(10, 15, 23, 248))
            pincel = gradiente
        borde = self.property("diagnostic_border_color")
        pintor.setPen(QPen(QColor(str(borde or "#806638")), ancho_borde))
        pintor.setBrush(pincel)
        pintor.drawPath(ruta)
        pintor.end()


class _FloatingPanel(QGraphicsView):
    """Ventana sin marco, translúcida, arrastrable y opcionalmente ignorada."""

    def __init__(self, key: str, item_catalog: dict | None = None) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        super().__init__(None)

        self.key = key
        self.item_catalog = item_catalog if isinstance(item_catalog, dict) else {}
        self.click_through = False
        self.drag_position: QPoint | None = None
        self.editing = False
        self.scale_factor = 1.0
        self.scale_changed_callback = None
        self._resize_origin: QPoint | None = None
        self._resize_scale = 1.0
        self.base_width = PANEL_WIDTHS.get(key, 240)
        self.moved_callback = None
        self.assets = None
        self._pending_icons: dict[str, list[tuple[QLabel, int, bool]]] = {}
        self._paint_event_logged = False

        self.setWindowTitle(f"Solralol · {PANEL_LABELS.get(key, key)}")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet("QGraphicsView { background: transparent; border: 0; }")
        self._apply_window_flags()
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(Qt.GlobalColor.transparent)
        self.setScene(self.scene)
        self.setInteractive(False)

        self.card = _OverlayCard()
        self.card.setObjectName("overlayCard")
        self.card.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.card.setAutoFillBackground(False)
        self.card.setStyleSheet("QFrame#overlayCard { background: transparent; border: none; }")
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 150))

        self.proxy = self.scene.addWidget(self.card)
        self.proxy.setGraphicsEffect(shadow)
        self.card.show()

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(8, 6, 8, 7)
        self.body.setSpacing(2)

        aplicar_tema(self)
        self._resize_logical_panel()

    def showEvent(self, event) -> None:
        """Completa los estilos nativos al mostrarse la ventana.

        Parámetros: evento de Qt.
        Retorno: None; ajusta el contenido final y fija topmost sin activarse.
        """
        super().showEvent(event)
        self._resize_logical_panel()
        QTimer.singleShot(0, self._ajustar_despues_de_mostrar)

    def paintEvent(self, event) -> None:
        """Registra la primera ejecución de pintura de la ventana.

        Parámetros: evento de pintura de Qt.
        Retorno: None; delega el renderizado y evita logs repetidos.
        """
        super().paintEvent(event)
        if self._paint_event_logged:
            return
        self._paint_event_logged = True
        _LOGGER.info(
            "[OverlayDebug] %s paintEvent first card_visible=%s proxy_visible=%s proxy_rect=%s card_size=%s window_size=%s",
            self.key,
            self.card.isVisible(),
            self.proxy.isVisible(),
            self.proxy.boundingRect(),
            self.card.size(),
            self.size(),
        )

    def _ajustar_despues_de_mostrar(self) -> None:
        """Sincroniza tamaño tras el layout diferido de widgets embebidos.

        Parámetros: ninguno.
        Retorno: None; corrige la geometría si Qt terminó el layout al mostrarse.
        """
        if self.isVisible():
            self._resize_logical_panel()
            self._asegurar_estilos_nativos()

    def _asegurar_estilos_nativos(self) -> None:
        """Aplica y registra los estilos Win32 necesarios para el HUD.

        Parámetros: ninguno.
        Retorno: None; conserva dibujo, paso de clics y foco del juego.
        """
        if os.name != "nt" or not self.isWindow() or not self.isVisible():
            return
        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            indice = -20
            user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowLongPtrW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_ssize_t,
            ]
            user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            user32.SetWindowPos.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = ctypes.c_int
            user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            user32.GetWindowRect.restype = ctypes.c_int
            user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            user32.IsWindowVisible.restype = ctypes.c_int
            user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user32.GetWindow.restype = ctypes.c_void_p
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            estilo = user32.GetWindowLongPtrW(hwnd, indice)
            estilo |= 0x00000080 | 0x08000000
            user32.SetWindowLongPtrW(hwnd, indice, estilo)
            user32.SetWindowPos(
                hwnd,
                ctypes.c_void_p(-1),
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0010 | 0x0020,
            )
            efectivo = user32.GetWindowLongPtrW(hwnd, indice)
            estilo_ventana = user32.GetWindowLongPtrW(hwnd, -16)
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            atributos_layered = ctypes.windll.user32.GetLayeredWindowAttributes
            atributos_layered.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.POINTER(ctypes.c_uint32),
            ]
            atributos_layered.restype = ctypes.c_int
            clave_color = ctypes.c_uint32()
            alfa_layered = ctypes.c_ubyte()
            banderas_layered = ctypes.c_uint32()
            layered_atributos_disponibles = bool(
                efectivo & 0x00080000
            ) and bool(
                atributos_layered(
                    hwnd,
                    ctypes.byref(clave_color),
                    ctypes.byref(alfa_layered),
                    ctypes.byref(banderas_layered),
                )
            )
            siguiente_z = int(user32.GetWindow(hwnd, 3) or 0)
            foreground = int(user32.GetForegroundWindow() or 0)
            cloaked = ctypes.c_int(-1)
            try:
                ctypes.windll.dwmapi.DwmGetWindowAttribute(
                    hwnd,
                    14,
                    ctypes.byref(cloaked),
                    ctypes.sizeof(cloaked),
                )
            except (AttributeError, OSError):
                cloaked.value = -1
            _LOGGER.info(
                "[OverlayDebug] %s HWND=%s visible=%s rect=(%d,%d,%d,%d) style=0x%X exstyle=0x%X layered=%s transparent=%s topmost=%s noactivate=%s layered_attrs=(available=%s alpha=%d flags=0x%X) z_prev=%s foreground=%s cloaked=%s",
                self.key,
                hwnd,
                bool(user32.IsWindowVisible(hwnd)),
                rect.left,
                rect.top,
                rect.right,
                rect.bottom,
                estilo_ventana,
                efectivo,
                bool(efectivo & 0x00080000),
                bool(efectivo & 0x00000020),
                bool(efectivo & 0x00000008),
                bool(efectivo & 0x08000000),
                layered_atributos_disponibles,
                alfa_layered.value,
                banderas_layered.value,
                hex(siguiente_z),
                hex(foreground),
                cloaked.value,
            )
        except Exception:
            _LOGGER.exception("[OverlayDebug] No se pudieron fijar estilos Win32 en %s", self.key)

    def _resize_logical_panel(self) -> None:
        """Recalcula la escena base y transforma el panel con escala uniforme.

        Parámetros: ninguno.
        Retorno: None; actualiza el tamaño externo sin deformar el contenido.
        """
        self.body.activate()
        self.card.setFixedWidth(self.base_width)
        height = max(64, self.card.minimumHeight(), self.card.sizeHint().height())
        for _ in range(4):
            if self.card.size().width() != self.base_width or self.card.size().height() != height:
                self.card.resize(self.base_width, height)
            self.body.invalidate()
            self.body.activate()
            siguiente = max(
                64,
                self.card.minimumHeight(),
                self.card.sizeHint().height(),
            )
            if siguiente == height:
                break
            height = siguiente
        if self.card.size().width() != self.base_width or self.card.size().height() != height:
            self.card.resize(self.base_width, height)
        rect_scene = QRectF(0, 0, self.base_width, height)
        if self.proxy.geometry() != rect_scene:
            self.proxy.setGeometry(rect_scene)
        if self.scene.sceneRect() != rect_scene:
            self.scene.setSceneRect(rect_scene)
        tamano_ventana = (
            round(self.base_width * self.scale_factor),
            round(height * self.scale_factor),
        )
        if self.size().width() != tamano_ventana[0] or self.size().height() != tamano_ventana[1]:
            self.setFixedSize(*tamano_ventana)
        transformacion = QTransform.fromScale(self.scale_factor, self.scale_factor)
        if self.transform() != transformacion:
            self.setTransform(transformacion)

    def adjustSize(self) -> None:
        """Ajusta el tamaño base a su contenido y conserva la escala elegida.

        Parámetros: ninguno.
        Retorno: None; evita el reajuste implícito del widget transformado.
        """
        self._resize_logical_panel()

    def set_scale(self, scale: float, notify: bool = False) -> None:
        """Aplica una escala uniforme dentro del rango permitido.

        Parámetros: factor solicitado y si se avisa al gestor.
        Retorno: None; escala panel, tipografía, iconos y espaciado juntos.
        """
        bounded = max(0.5, min(1.5, float(scale)))
        if abs(bounded - self.scale_factor) < 0.001:
            return
        self.scale_factor = bounded
        self._resize_logical_panel()
        if notify and callable(self.scale_changed_callback):
            self.scale_changed_callback(self)

    def set_editing(self, enabled: bool) -> None:
        """Habilita movimiento y resize temporal sin click-through.

        Parámetros: estado de edición.
        Retorno: None; muestra el handle y actualiza el modo de entrada.
        """
        if self.editing == bool(enabled):
            return
        self.editing = bool(enabled)
        self._refresh_window_flags()
        self.viewport().update()

    def _refresh_window_flags(self) -> None:
        """Reaplica flags Qt conservando visibilidad y posición.

        Parámetros: ninguno.
        Retorno: None; hace efectiva la captura o el paso de ratón.
        """
        visible = self.isVisible()
        self.hide()
        self._apply_window_flags()
        if visible:
            self.show()
            self.raise_()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        """Pinta el asa diagonal en la esquina solo durante la edición.

        Parámetros: painter y rectángulo de escena expuesto.
        Retorno: None; dibuja un indicador dorado pequeño.
        """
        super().drawForeground(painter, rect)
        if not self.editing:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#D4AA56"), 2))
        x, y = self.base_width - 18, self.card.height() - 18
        painter.drawLine(x, y + 10, x + 10, y)
        painter.drawLine(x + 4, y + 10, x + 10, y + 4)
        painter.restore()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Actualiza el cursor al pasar sobre el asa de escala.

        Parámetros: objeto observado y evento Qt recibido.
        Retorno: False para que Qt siga procesando el movimiento.
        """
        if (
            watched is self.viewport()
            and event.type() == QEvent.Type.MouseMove
            and self.editing
        ):
            point = self.mapToScene(event.position().toPoint())
            handle = QRectF(self.base_width - 24, self.card.height() - 24, 24, 24)
            if handle.contains(point):
                self.viewport().setCursor(Qt.CursorShape.SizeFDiagCursor)
            else:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        return super().eventFilter(watched, event)

    def _apply_window_flags(self) -> None:
        """Aplica flags Qt solo cuando cambia la configuración nativa.

        Parámetros: ninguno.
        Retorno: None; evita recrear el HWND con flags idénticos.
        """
        flags = self._desired_window_flags()
        if self.windowFlags() == flags:
            return
        self.setWindowFlags(flags)

    def _desired_window_flags(self) -> Qt.WindowType:
        """Calcula flags de ventana según click-through y edición.

        Parámetros: ninguno.
        Retorno: combinación Qt para la ventana flotante actual.
        """
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        if self.click_through and not self.editing:
            flags |= Qt.WindowType.WindowTransparentForInput
        return flags

    def set_assets(self, assets) -> None:
        """Servicio de iconos de Data Dragon (descarga asíncrona y caché)."""
        if assets is None or assets is self.assets:
            return

        if self.assets is not None:
            try:
                self.assets.image_ready.disconnect(self._receive_icon)
            except (RuntimeError, TypeError):
                pass

        self.assets = assets

        try:
            assets.image_ready.connect(
                self._receive_icon,
                Qt.ConnectionType.UniqueConnection,
            )
        except (RuntimeError, TypeError):
            assets.image_ready.connect(self._receive_icon)

    def _receive_icon(self, key: str, pixmap: QPixmap) -> None:
        """Entrega un recurso descargado a sus etiquetas pendientes."""
        pending = self._pending_icons.pop(key, None)

        if not pending:
            return

        for label, size, circular in pending:
            try:
                if label.property("asset_key") != key:
                    continue
                label.setPixmap(self._scaled(pixmap, size, circular))
            except RuntimeError:
                continue

    @staticmethod
    def _scaled(pixmap: QPixmap, size: int, rounded: bool = False) -> QPixmap:
        """Escala un recurso y, si se solicita, recorta sus esquinas.

        Parámetros: pixmap fuente, tamaño lógico y recorte redondeado.
        Retorno: imagen cuadrada y transparente en las esquinas redondeadas.
        """
        escalado = pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not rounded:
            return escalado
        lienzo = QPixmap(size, size)
        lienzo.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(lienzo)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        ruta = QPainterPath()
        ruta.addRoundedRect(QRectF(0, 0, size, size), 6, 6)
        pintor.setClipPath(ruta)
        x = (size - escalado.width()) / 2
        y = (size - escalado.height()) / 2
        pintor.drawPixmap(round(x), round(y), escalado)
        pintor.end()
        return lienzo

    def _apply_asset(
        self,
        label: QLabel,
        url: str,
        key: str,
        size: int,
        rounded: bool = False,
    ) -> None:
        """Solicita un recurso y conserva su recorte al completar la descarga."""
        pixmap = self.assets.request_pixmap(url, key)

        if not pixmap.isNull():
            label.setPixmap(self._scaled(pixmap, size, rounded))
            return

        self._pending_icons.setdefault(key, []).append((label, size, rounded))

    def _set_champion_icon(
        self,
        label: QLabel,
        champion: str,
        size: int = CHAMPION_ICON_SIZE,
    ) -> None:
        """Carga el retrato del campeón y recorta sus esquinas al marco."""
        if not champion:
            _set_property(label, "state", "empty")
            label.setPixmap(QPixmap())
            label.setText("")
            label.setProperty("asset_key", "")
            return

        _set_property(label, "state", "filled")

        # 1) caché local del repositorio (data/champion_icons), que llega con
        #    la instalación y evita depender de la red.
        pixmap = self._local_pixmap(
            get_champion_icon_path(champion, "", download=False)
        )

        if not pixmap.isNull():
            label.setPixmap(self._scaled(pixmap, size, True))
            return

        # 2) servicio de Data Dragon: caché en ~/.solralol y descarga async.
        label.setText(champion[:3].upper())

        if self.assets is None:
            return

        url = self.assets.champion_url(champion)
        key = f"overlay-champion::{url}"

        if label.property("asset_key") == key:
            return

        label.setProperty("asset_key", key)
        self._apply_asset(label, url, key, size, True)

    def _set_item_icon(
        self,
        label: QLabel,
        item_id,
        size: int = ITEM_ICON_SIZE,
    ) -> None:
        clave_item = str(item_id or "")
        if label.property("rendered_item_id") == clave_item:
            return
        if not item_id:
            _set_property(label, "state", "empty")
            label.setPixmap(QPixmap())
            label.setText("")
            label.setProperty("asset_key", "")
            label.setProperty("rendered_item_id", "")
            return

        label.setProperty("rendered_item_id", clave_item)
        _set_property(label, "state", "filled")
        label.setText("")

        # 1) caché local del repositorio (data/item_icons).
        try:
            local = get_item_icon_path(
                item_id,
                self.item_catalog,
                "",
                download=False,
            )
        except (OSError, ValueError):
            local = None

        pixmap = self._local_pixmap(local)

        if not pixmap.isNull():
            label.setPixmap(self._scaled(pixmap, size))
            return

        # 2) servicio de Data Dragon (caché en ~/.solralol y descarga async).
        if self.assets is None:
            return

        url = self.assets.item_url(item_id)
        key = f"overlay-item::{url}"

        if label.property("asset_key") == key:
            return

        label.setProperty("asset_key", key)
        self._apply_asset(label, url, key, size)

    @staticmethod
    def _local_pixmap(path) -> QPixmap:
        if path is None:
            return QPixmap()

        try:
            pixmap = QPixmap(str(path))
        except (OSError, RuntimeError):
            return QPixmap()

        return pixmap if not pixmap.isNull() else QPixmap()

    def set_click_through(self, enabled: bool) -> None:
        """Con los clics bloqueados el ratón atraviesa el panel."""
        enabled = bool(enabled)
        if self.click_through == enabled:
            return
        self.click_through = enabled
        self._refresh_window_flags()

    def _refresh_window_flags(self) -> None:
        """Actualiza la entrada de ratón y conserva la visibilidad.

        Parámetros: ninguno.
        Retorno: None; reaplica flags por modo de edición y click-through.
        """
        flags = self._desired_window_flags()
        if self.windowFlags() == flags:
            return
        was_visible = self.isVisible()
        self.hide()
        self.setWindowFlags(flags)

        if was_visible:
            self.show()
            self.raise_()

    def set_overlay_opacity(self, percent: int) -> None:
        bounded = max(MIN_OPACITY, min(int(percent), MAX_OPACITY))
        self.setWindowOpacity(bounded / 100)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.editing:
            super().mousePressEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        handle = QRectF(self.base_width - 24, self.card.height() - 24, 24, 24)
        if handle.contains(point):
            self._resize_origin = event.globalPosition().toPoint()
            self._resize_scale = self.scale_factor
            self.drag_position = None
        else:
            self.drag_position = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            self._resize_origin = None
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._resize_origin is not None
        ):
            delta = event.globalPosition().toPoint() - self._resize_origin
            change = (
                delta.x() / self.base_width + delta.y() / max(1, self.card.height())
            ) / 2
            self.set_scale(self._resize_scale + change, notify=True)
            event.accept()
            return
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self.drag_position is not None
        ):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
            return
        point = self.mapToScene(event.position().toPoint())
        handle = QRectF(self.base_width - 24, self.card.height() - 24, 24, 24)
        cursor = (
            Qt.CursorShape.SizeFDiagCursor
            if self.editing and handle.contains(point)
            else Qt.CursorShape.OpenHandCursor
            if self.editing
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)
        self.viewport().setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        moved = (
            self.drag_position is not None or self._resize_origin is not None
        ) and event.button() == Qt.MouseButton.LeftButton
        self.drag_position = None
        self._resize_origin = None

        if moved and self.moved_callback is not None:
            self.moved_callback(self)

        event.accept()


class _GoldRow(QWidget):
    """Una fila del panel de oro: rol, icono+oro aliado, delta, oro+icono rival."""

    def __init__(self, total: bool = False) -> None:
        """Crea la fila de oro con columnas numéricas alineadas."""
        super().__init__()

        self.total_row = total
        kind = "total" if total else ""

        self.role = QLabel("")
        self.role.setObjectName("overlayRole")
        self.role.setFixedWidth(ROLE_LABEL_WIDTH)
        self.role.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        self.ally_icon = _icon_label(CHAMPION_ICON_SIZE)
        self.ally_icon.setFixedSize(26, 26)
        self.ally_icon.setProperty("team", "ally")

        self.ally_gold = QLabel("")
        self.ally_gold.setObjectName("overlayGold")
        self.ally_gold.setProperty("side", "ally")
        self.ally_gold.setProperty("kind", kind)
        self.ally_gold.setFixedWidth(GOLD_LABEL_WIDTH)
        self.ally_gold.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.ally_gold.setFont(self.ally_gold.font())

        self.delta = QLabel("")
        self.delta.setObjectName("overlayDelta")
        self.delta.setProperty("kind", kind)
        self.delta.setFixedWidth(DELTA_LABEL_WIDTH)
        self.delta.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.enemy_gold = QLabel("")
        self.enemy_gold.setObjectName("overlayGold")
        self.enemy_gold.setProperty("side", "enemy")
        self.enemy_gold.setProperty("kind", kind)
        self.enemy_gold.setFixedWidth(GOLD_LABEL_WIDTH)
        self.enemy_gold.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.enemy_icon = _icon_label(CHAMPION_ICON_SIZE)
        self.enemy_icon.setFixedSize(26, 26)
        self.enemy_icon.setProperty("team", "enemy")

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(0)
        layout.addWidget(self.role, 0, 0)
        layout.addWidget(self.ally_icon, 0, 1)
        layout.addWidget(self.ally_gold, 0, 2)
        layout.addWidget(self.delta, 0, 3)
        layout.addWidget(self.enemy_gold, 0, 4)
        layout.addWidget(self.enemy_icon, 0, 5)
        layout.setColumnMinimumWidth(0, ROLE_LABEL_WIDTH)
        layout.setColumnMinimumWidth(1, 26)
        layout.setColumnMinimumWidth(2, GOLD_LABEL_WIDTH)
        layout.setColumnMinimumWidth(3, DELTA_LABEL_WIDTH)
        layout.setColumnMinimumWidth(4, GOLD_LABEL_WIDTH)
        layout.setColumnMinimumWidth(5, 26)
        self.setObjectName("overlayGoldRow")


class GoldPanel(_FloatingPanel):
    """Panel 1: oro por rol aliado contra rival y total de cada equipo."""

    def __init__(self, item_catalog: dict | None = None) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        super().__init__("gold", item_catalog)

        self.total_bar = QFrame()
        self.total_bar.setObjectName("overlayGoldSummary")
        total_layout = QHBoxLayout(self.total_bar)
        total_layout.setContentsMargins(8, 5, 8, 5)
        total_layout.setSpacing(5)
        self.total_label = QLabel("TOTAL EST.")
        self.total_label.setObjectName("overlayGoldSummaryLabel")
        coin_mini = QLabel()
        coin_mini.setFixedSize(19, 19)
        _set_decorative_icon(coin_mini, "gold_coins", 19)
        self.total_value = QLabel("—")
        self.total_value.setObjectName("overlayGoldSummaryValue")
        self.total_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        total_layout.addWidget(coin_mini)
        total_layout.addWidget(self.total_label, 1)
        total_layout.addWidget(self.total_value)
        self.body.addWidget(self.total_bar)

        self.header_row = _GoldRow()
        self.header_row.setObjectName("overlayGoldColumnHeader")
        for label, text, width, align in (
            (
                self.header_row.role,
                "LÍNEA",
                ROLE_LABEL_WIDTH,
                Qt.AlignmentFlag.AlignLeft,
            ),
            (
                self.header_row.ally_gold,
                "ALIADO",
                GOLD_LABEL_WIDTH,
                Qt.AlignmentFlag.AlignRight,
            ),
            (
                self.header_row.delta,
                "DIF.",
                DELTA_LABEL_WIDTH,
                Qt.AlignmentFlag.AlignCenter,
            ),
            (
                self.header_row.enemy_gold,
                "RIVAL",
                GOLD_LABEL_WIDTH,
                Qt.AlignmentFlag.AlignRight,
            ),
        ):
            label.setText(text)
            label.setFixedWidth(width)
            label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self.header_row.ally_icon.setFixedSize(26, 1)
        self.header_row.enemy_icon.setFixedSize(26, 1)
        self.body.addWidget(self.header_row)

        separator = QFrame()
        separator.setFixedHeight(1)
        aplicar_apariencia(separator, "separador")
        self.body.addWidget(separator)

        self.rows: list[_GoldRow] = []
        self._lane_count = -1
        self._last_render_signature: str | None = None

    def render(self, report: dict) -> None:
        """Pinta la estimación de oro y redimensiona si cambia el número de líneas."""
        team = report.get("team", {}) if isinstance(report, dict) else {}
        lanes = report.get("lanes", []) if isinstance(report, dict) else []

        if not isinstance(lanes, list):
            lanes = []

        firma = repr((team, lanes))
        if firma == self._last_render_signature:
            return
        self._last_render_signature = firma

        self._render_total(team)
        self._render_lanes(lanes)

        if self._lane_count != len(lanes):
            self._lane_count = len(lanes)
            self.adjustSize()

    def _render_total(self, team: dict) -> None:
        team = team if isinstance(team, dict) else {}
        if team.get("delta") is None:
            self.total_value.setText("Datos incompletos")
            _set_property(self.total_value, "state", "even")
        else:
            value = int(team["delta"])
            self.total_value.setText(format_delta(value))
            _set_property(
                self.total_value,
                "state",
                "ahead" if value > 0 else "behind" if value < 0 else "even",
            )

    def _render_lanes(self, lanes: list[dict]) -> None:
        while len(self.rows) < len(lanes):
            row = _GoldRow()
            self.rows.append(row)
            self.body.addWidget(row)

        for index, row in enumerate(self.rows):
            if index >= len(lanes):
                if row.isVisible():
                    row.setVisible(False)
                continue

            if not row.isVisible():
                row.setVisible(True)

            lane = lanes[index]
            lane = lane if isinstance(lane, dict) else {}
            self._render_side(
                row.ally_icon,
                row.ally_gold,
                lane.get("ally"),
            )
            row.role.setText(ROLE_SHORT_LABELS.get(str(lane.get("role", "")), "?"))

            if lane.get("paired"):
                if lane.get("delta") is None:
                    row.delta.setText("—")
                else:
                    self._set_delta(row.delta, int(lane["delta"]))
            else:
                row.delta.setText("—")

            self._render_side(
                row.enemy_icon,
                row.enemy_gold,
                lane.get("enemy"),
            )

    def _render_side(
        self,
        icon: QLabel,
        gold_label: QLabel,
        entry: dict | None,
    ) -> None:
        """Actualiza una columna de campeón y oro, con retrato recortado."""
        if not isinstance(entry, dict):
            self._set_champion_icon(icon, "")
            gold_label.setText("")
            return

        self._set_champion_icon(icon, str(entry.get("champion", "") or ""), 26)
        gold_label.setText(
            format_gold(entry["gold"]) if entry.get("gold") is not None else "—"
        )

    def _set_delta(self, label: QLabel, delta: int) -> None:
        if delta > 0:
            _set_property(label, "state", "ahead")
        elif delta < 0:
            _set_property(label, "state", "behind")
        else:
            _set_property(label, "state", "even")

        label.setText(format_delta(delta))


class _AlertRow(QFrame):
    """Una fila del panel de alertas: acento de bando, iconos y texto."""

    def __init__(self) -> None:
        """Crea una fila estrecha para iconos y texto de alerta."""
        super().__init__()
        self.setObjectName("overlayAlertRow")

        self.accent = QFrame()
        self.accent.setObjectName("overlayAccent")
        self.accent.setFixedSize(3, 18)

        self.slot_a = _icon_label(CHAMPION_ICON_SIZE)
        self.slot_a.setFixedSize(28, 28)

        self.slot_b = _icon_label(ITEM_ICON_SIZE)
        self.slot_b.setFixedSize(36, 28)

        self.text = QLabel("")
        self.text.setObjectName("overlayAlertText")
        self.text.setWordWrap(True)
        self.secondary = QLabel("")
        self.secondary.setObjectName("overlayAlertSecondary")
        self.secondary.setWordWrap(True)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        text_layout.addWidget(self.text)
        text_layout.addWidget(self.secondary)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        layout.addWidget(self.accent)
        layout.addWidget(self.slot_a)
        layout.addWidget(self.slot_b)
        layout.addLayout(text_layout, 1)


class _RecordingRow(QFrame):
    """Fila fija del panel de alertas: indica que la partida se está grabando."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlayRecordingRow")

        self.dot = QLabel("●")
        self.dot.setObjectName("overlayRecordingDot")
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text = QLabel("")
        self.text.setObjectName("overlayRecordingText")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)
        layout.addWidget(self.dot)
        layout.addWidget(self.text, 1)

    def set_elapsed(self, elapsed_seconds: float) -> None:
        try:
            total = max(0, int(float(elapsed_seconds)))
        except (TypeError, ValueError):
            total = 0

        minutes, seconds = divmod(total, 60)
        self.text.setText(f"Grabando {minutes:02d}:{seconds:02d}")


class AlertsPanel(_FloatingPanel):
    """Panel 2: compras de objetos completos y objetivos a punto de aparecer."""

    activity_changed = Signal()

    def __init__(self, item_catalog: dict | None = None) -> None:
        super().__init__("alerts", item_catalog)

        self.feed: list[dict] = []
        self.rows: list[_AlertRow] = []
        self._visible_count = -1
        self.recording = False
        self.recording_timer = QTimer(self)
        self.recording_timer.setSingleShot(True)
        self.recording_timer.timeout.connect(self._expire_recording_notice)
        self.alert_timer = QTimer(self)
        self.alert_timer.setSingleShot(True)
        self.alert_timer.timeout.connect(self._expire_alert_notice)
        self._active_alert_key = ""
        self._queued_alerts: deque[tuple[str, dict]] = deque()
        self._known_alert_keys: set[str] = set()
        self.duration_seconds = DEFAULT_NOTIFICATION_DURATION

        self.recording_row = _RecordingRow()
        self.recording_row.hide()
        self.body.addWidget(self.recording_row)

        self.body.setSpacing(4)

    def render(self, alerts: list[dict]) -> None:
        self.feed = alerts if isinstance(alerts, list) else []
        presentes: set[str] = set()
        for alerta in self.feed:
            clave = str(
                alerta.get("key") or f"{alerta.get('kind')}:{alerta.get('name')}"
            )
            clave += f":{alerta.get('spawn_at', alerta.get('time', ''))}"
            presentes.add(clave)
            if clave not in self._known_alert_keys:
                self._known_alert_keys.add(clave)
                self._queued_alerts.append((clave, dict(alerta)))
        self._known_alert_keys.intersection_update(presentes | {self._active_alert_key})
        self._show_next_alert()

    def enqueue_test_alert(self) -> None:
        """Encola una alerta de demostración con el renderer de juego.

        Parámetros: ninguno.
        Retorno: None; muestra un aviso temporal sin afectar a la partida.
        """
        clave = f"test:dragon:{id(self)}:{len(self._queued_alerts)}"
        self._queued_alerts.append(
            (
                clave,
                {
                    "kind": "objective",
                    "key": clave,
                    "name": "Dragón",
                    "remaining": 45,
                    "urgent": False,
                },
            )
        )
        self._show_next_alert()

    def enqueue_recording_error(self, detail: str) -> None:
        """Notifica un error de grabación como evento temporal del overlay.

        Parámetros: diagnóstico breve mostrado bajo el título.
        Retorno: None; encola el aviso sin alterar el servicio de grabación.
        """
        clave = f"recording:error:{id(self)}:{len(self._queued_alerts)}"
        self._queued_alerts.append(
            (
                clave,
                {
                    "kind": "error",
                    "name": "Error de grabación",
                    "detail": str(detail)[:120],
                },
            )
        )
        self._show_next_alert()

    def clear_transient(self) -> None:
        """Elimina avisos temporales y pendientes al salir de la partida.

        Parámetros: ninguno.
        Retorno: None; deja las filas ocultas y los temporizadores detenidos.
        """
        self.alert_timer.stop()
        self.recording_timer.stop()
        self._queued_alerts.clear()
        self._active_alert_key = ""
        self.feed.clear()
        for row in self.rows:
            row.hide()
        self.recording_row.hide()
        self.recording = False
        self.activity_changed.emit()

    def _show_next_alert(self) -> None:
        """Muestra la próxima alerta si no hay otra activa.

        Parámetros: ninguno.
        Retorno: None; actualiza la fila común de notificación.
        """
        if self.alert_timer.isActive() or not self._queued_alerts:
            return
        clave, alerta = self._queued_alerts.popleft()
        if not self.rows:
            fila = _AlertRow()
            self.rows.append(fila)
            self.body.addWidget(fila)
        self._active_alert_key = clave
        self._render_row(self.rows[0], alerta)
        self.rows[0].show()
        self.alert_timer.start(self.duration_seconds * 1000)
        self.adjustSize()
        self.activity_changed.emit()

    def _expire_alert_notice(self) -> None:
        """Retira el aviso de partida tras cinco segundos.

        Parámetros: ninguno.
        Retorno: None; conserva el feed del servicio para detectar el siguiente aviso.
        """
        for row in self.rows:
            row.hide()
        self._active_alert_key = ""
        self.alert_timer.stop()
        self._visible_count = -1
        self.adjustSize()
        self.activity_changed.emit()
        QTimer.singleShot(0, self._show_next_alert)

    def _render_row(self, row: _AlertRow, alert: dict) -> None:
        alert = alert if isinstance(alert, dict) else {}
        kind = str(alert.get("kind", ""))

        if kind in {"objective", "recording", "error", "test"}:
            row.accent.setProperty("kind", "objective")
            row.accent.setProperty("side", "")
            _repolish(row.accent)

            _set_decorative_icon(
                row.slot_a, "recording" if kind == "recording" else "dragon_alert", 24
            )
            row.slot_a.setText("")
            row.slot_a.setProperty("asset_key", "")
            row.slot_a.setObjectName("overlayIcon")
            row.slot_a.setProperty("state", "filled")
            _repolish(row.slot_a)

            row.slot_b.setPixmap(QPixmap())
            row.slot_b.setText("")
            row.slot_b.setProperty("asset_key", "")
            row.slot_b.setObjectName("overlayClock")
            row.slot_b.setProperty("urgent", "true" if alert.get("urgent") else "false")
            _repolish(row.slot_b)
            row.slot_b.setText(
                format_clock(alert.get("remaining", 0)) if kind == "objective" else ""
            )
            row.slot_b.setAlignment(Qt.AlignmentFlag.AlignCenter)

            remaining = format_clock(alert.get("remaining", 0))
            row.text.setText(
                f"{alert.get('name', 'Objetivo')} en"
                if kind == "objective"
                else str(alert.get("name", "Aviso"))
            )
            row.secondary.setText(
                str(
                    alert.get(
                        "detail",
                        "Coloca visión y prepara la rotación."
                        if kind == "objective"
                        else "",
                    )
                )
            )
            row.text.setToolTip(
                f"{alert.get('name', '')} aparece en {remaining}"
                if kind == "objective"
                else ""
            )
        else:
            side = "ally" if str(alert.get("side", "")) == "ally" else "enemy"
            row.accent.setProperty("kind", "")
            row.accent.setProperty("side", side)
            _repolish(row.accent)

            row.slot_a.setObjectName("overlayIcon")
            row.slot_a.setProperty("state", "filled")
            _repolish(row.slot_a)
            self._set_champion_icon(
                row.slot_a,
                str(alert.get("champion", "") or ""),
                28,
            )

            row.slot_b.setObjectName("overlayIcon")
            row.slot_b.setProperty("state", "filled")
            row.slot_b.setProperty("urgent", "false")
            _repolish(row.slot_b)
            self._set_item_icon(row.slot_b, alert.get("item_id"), 22)

            row.text.setText("Compra rival detectada")
            row.secondary.setText(
                str(alert.get("item_name", "") or "Objeto completado")
            )
            row.text.setToolTip(str(alert.get("detail", "") or ""))

    def set_recording(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        """Muestra u oculta la fila «Grabando» del panel de alertas.

        Con los padres ocultos Qt ignora ``setVisible(True)`` en el hijo, así
        que si el panel aún no se ha mostrado la primera vez la fila quedará
        visible en cuanto se ordene el layout del panel.
        """
        active = bool(active)

        if self.recording == active:
            return

        self.recording = active
        self.recording_timer.stop()
        self._queued_alerts.append(
            (
                f"recording:{'started' if active else 'stopped'}:{id(self)}:{len(self._queued_alerts)}",
                {
                    "kind": "recording",
                    "name": "Grabación iniciada" if active else "Grabación finalizada",
                },
            )
        )
        self._show_next_alert()

    def _expire_recording_notice(self) -> None:
        """Oculta el aviso temporal sin alterar la grabación.

        Parámetros: ninguno.
        Retorno: None; retira la fila después de 4,5 segundos.
        """
        self.recording_row.hide()
        self._visible_count = -1
        self.adjustSize()
        if self.feed and not self.recording:
            self._active_alert_key = ""
            self.render(self.feed)
        self.activity_changed.emit()

    def _clear_row(self, row: _AlertRow) -> None:
        row.slot_a.setPixmap(QPixmap())
        row.slot_a.setText("")
        row.slot_a.setProperty("asset_key", "")
        row.slot_b.setPixmap(QPixmap())
        row.slot_b.setText("")
        row.slot_b.setProperty("asset_key", "")
        row.text.setText("")
        row.text.setToolTip("")
        row.secondary.setText("")


class _ThreatRow(QWidget):
    """Tarjeta de amenaza con clasificación, campeón, rol y BattleScore."""

    def __init__(self) -> None:
        """Prepara una fila de amenaza con retrato, rol y puntuación."""
        super().__init__()

        self.setObjectName("overlayThreatCard")
        self.setProperty("ranking", "strongest")
        self.heading = QLabel("")
        self.heading.setObjectName("overlayThreatHeading")
        self.marker = QLabel("")
        self.marker.setObjectName("overlayThreatMarker")
        self.marker.setFixedWidth(24)
        self.marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_layout = QHBoxLayout()
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.addWidget(self.marker)
        heading_layout.addWidget(self.heading, 1)
        self.icon = _icon_label(CHAMPION_ICON_SIZE)
        self.icon.setFixedSize(40, 40)

        self.name = QLabel("")
        self.name.setObjectName("overlayThreatName")
        self.name.setWordWrap(False)
        self.name.setMinimumWidth(0)
        self.name.setMaximumWidth(THREAT_NAME_WIDTH)

        self.role = QLabel("")
        self.role.setObjectName("overlayThreatRole")
        self.score_label = QLabel("BattleScore")
        self.score_label.setObjectName("overlayThreatScoreLabel")
        self.score = QLabel("—")
        self.score.setObjectName("overlayThreatScore")
        score_layout = QVBoxLayout()
        score_layout.setContentsMargins(0, 0, 0, 0)
        score_layout.setSpacing(0)
        score_layout.addWidget(self.score_label, 0, Qt.AlignmentFlag.AlignRight)
        score_layout.addWidget(self.score, 0, Qt.AlignmentFlag.AlignRight)
        identity_layout = QVBoxLayout()
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.addWidget(self.name)
        identity_layout.addWidget(self.role)

        details = QHBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(10)
        details.addWidget(self.icon)
        details.addLayout(identity_layout, 1)
        details.addLayout(score_layout)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(2)
        layout.addLayout(heading_layout)
        layout.addLayout(details)


class ThreatPanel(_FloatingPanel):
    """Panel 3: el rival más fuerte y el más débil (icono, nombre y oro)."""

    def __init__(self, item_catalog: dict | None = None) -> None:
        super().__init__("threat", item_catalog)
        self._last_render_signature: str | None = None

        self.strongest = _ThreatRow()
        _set_decorative_icon(self.strongest.marker, "crown", 22)
        self.strongest.marker.setProperty("role", "strongest")
        self.strongest.heading.setText("MÁS FUERTE")
        _set_property(self.strongest, "ranking", "strongest")
        self.strongest.setToolTip("Más fuerte · BattleScore")
        self.body.addWidget(self.strongest)

        self.weakest = _ThreatRow()
        _set_decorative_icon(self.weakest.marker, "arrow_down", 22)
        self.weakest.marker.setProperty("role", "weakest")
        self.weakest.heading.setText("MÁS DÉBIL")
        _set_property(self.weakest, "ranking", "weakest")
        self.weakest.setToolTip("Más débil · BattleScore")
        self.body.addWidget(self.weakest)

    def render(self, ranking: dict) -> None:
        """Pinta los rivales destacados y ajusta la ventana a las filas disponibles."""
        ranking = ranking if isinstance(ranking, dict) else {}
        firma = repr(ranking)
        if firma == self._last_render_signature:
            return
        self._last_render_signature = firma
        visibilidad_previa = (self.strongest.isHidden(), self.weakest.isHidden())
        self._render_row(self.strongest, ranking.get("strongest"))
        self._render_row(self.weakest, ranking.get("weakest"))
        for row, key in (
            (self.strongest, "strongest_tie_count"),
            (self.weakest, "weakest_tie_count"),
        ):
            empate = int(ranking.get(key, 1) or 1)
            base = "MÁS FUERTE" if key.startswith("strongest") else "MÁS DÉBIL"
            row.heading.setText(f"{base} · EMPATE ({empate})" if empate > 1 else base)

        visibilidad_actual = (self.strongest.isHidden(), self.weakest.isHidden())
        if visibilidad_actual != visibilidad_previa:
            self.adjustSize()

    def _render_row(self, row: _ThreatRow, entry: dict | None) -> None:
        """Actualiza una fila de amenaza y recorta el retrato a su marco."""
        if not isinstance(entry, dict):
            row.setVisible(False)
            return

        if not row.isVisible():
            row.setVisible(True)

        champion = str(entry.get("champion", "") or "")
        self._set_champion_icon(row.icon, champion, 40)
        role = ROLE_SHORT_LABELS.get(
            str(entry.get("role", "UNKNOWN")), "Rol no disponible"
        )
        _elide(row.name, champion or "Campeón no disponible", THREAT_NAME_WIDTH)
        row.name.setToolTip(champion)
        row.role.setText(role)
        row.score.setText(
            f"{int(entry['score']):,}" if entry.get("score") is not None else "—"
        )
        row.setToolTip(
            f"{champion} · BattleScore {int(entry['score']):,} · {role}"
            if entry.get("score") is not None
            else f"{champion} · BattleScore no disponible · {role}"
        )


class PanelCompraRecomendada(_FloatingPanel):
    """Muestra hasta tres compras de la progresión curada del campeón."""

    def __init__(self, item_catalog: dict | None = None) -> None:
        """Crea el panel compacto de compras.

        Parámetros: catálogo local de objetos.
        Retorno: None; prepara tres tarjetas persistentes de objetos.
        """
        super().__init__("purchase", item_catalog)
        self.status_label = QLabel()
        self.status_label.setObjectName("overlayPurchaseStatus")
        self.status_label.setWordWrap(False)
        self.body.addWidget(self.status_label)
        fila_tarjetas = QWidget()
        self.fila_tarjetas = fila_tarjetas
        self.cards_layout = QHBoxLayout(fila_tarjetas)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(5)
        self.cards: list[dict[str, QWidget | QLabel | QProgressBar]] = []
        for _ in range(3):
            tarjeta = QFrame()
            tarjeta.setObjectName("overlayPurchaseCard")
            tarjeta.setProperty("rank", len(self.cards) + 1)
            tarjeta.setFixedWidth(108)
            disposicion = QVBoxLayout(tarjeta)
            disposicion.setContentsMargins(6, 5, 6, 5)
            disposicion.setSpacing(3)
            puesto = QLabel(str(len(self.cards) + 1))
            puesto.setObjectName("overlayPurchaseRank")
            icono = _icon_label(40)
            icono.setFixedSize(40, 40)
            nombre = QLabel("")
            nombre.setObjectName("overlayPurchaseName")
            nombre.setWordWrap(False)
            nombre.setMinimumWidth(0)
            nombre.setMaximumWidth(96)
            nombre.setFixedHeight(18)
            nombre.setAlignment(Qt.AlignmentFlag.AlignCenter)
            puntuacion = QLabel("—")
            puntuacion.setObjectName("overlayPurchaseScore")
            puntuacion.setAlignment(Qt.AlignmentFlag.AlignCenter)
            barra = QProgressBar()
            barra.setObjectName("overlayPurchaseBar")
            barra.setRange(0, 100)
            barra.setTextVisible(False)
            barra.setFixedHeight(7)
            disposicion.addWidget(puesto, 0, Qt.AlignmentFlag.AlignLeft)
            disposicion.addWidget(icono, 0, Qt.AlignmentFlag.AlignHCenter)
            disposicion.addWidget(nombre)
            disposicion.addWidget(puntuacion)
            disposicion.addWidget(barra)
            self.cards.append(
                {
                    "widget": tarjeta,
                    "icon": icono,
                    "name": nombre,
                    "score": puntuacion,
                    "bar": barra,
                }
            )
            self.cards_layout.addWidget(tarjeta)
            tarjeta.hide()
        self.body.addWidget(fila_tarjetas)
        self._status_signature: tuple[str, str] | None = None
        self._rendered_recommendations: tuple[tuple[object, ...], ...] = ()
        self._rendered_champion = ""
        self._showing_recommendations = False
        self.model_change_count = 0
        self.set_status("Esperando datos de partida…")

    def set_status(self, message: str, detail: str = "") -> None:
        """Muestra un estado inequívoco cuando aún no hay tarjetas válidas.

        Parámetros: estado breve y diagnóstico opcional.
        Retorno: None; oculta resultados anteriores y reajusta el panel.
        """
        firma = (str(message), str(detail))
        if firma == self._status_signature and not self._showing_recommendations:
            return
        cambio_vista = self._showing_recommendations
        self._status_signature = firma
        if self.status_label.text() != firma[0]:
            self.status_label.setText(firma[0])
        if self.status_label.toolTip() != firma[1]:
            self.status_label.setToolTip(firma[1])
        if self._showing_recommendations:
            self._showing_recommendations = False
        if self.status_label.isHidden():
            self.status_label.show()
        if not self.fila_tarjetas.isHidden():
            self.fila_tarjetas.hide()
        if cambio_vista:
            self.adjustSize()

    def render(self, campeon: str, recomendaciones: list[dict]) -> None:
        """Actualiza tres tarjetas con iconos y puntuaciones reales.

        Parámetros: campeón propio y objetos válidos recomendados.
        Retorno: None; actualiza nombres e iconos mediante la caché de assets.
        """
        if not recomendaciones:
            self.set_status("Sin recomendaciones para esta partida")
            return
        modelo = tuple(
            (
                str(item.get("item_id", item.get("id", ""))),
                str(item.get("name", "Objeto")),
                float(item.get("score", 0.0)),
                item.get("cost"),
                tuple(str(motivo) for motivo in item.get("reasons", [])),
                repr(item.get("next_buy", {})),
            )
            for item in recomendaciones[:3]
            if isinstance(item, dict)
        )
        if modelo == self._rendered_recommendations and campeon == self._rendered_champion and self._showing_recommendations:
            return
        cambio_vista = not self._showing_recommendations
        self._status_signature = None
        if not self.status_label.isHidden():
            self.status_label.hide()
        if self.fila_tarjetas.isHidden():
            self.fila_tarjetas.show()
        self._showing_recommendations = True
        self.model_change_count += 1
        mayor_puntuacion = max(
            (
                float(item["score"])
                for item in recomendaciones
                if isinstance(item, dict) and item.get("score") is not None
            ),
            default=0.0,
        )
        for indice, tarjeta in enumerate(self.cards):
            item = recomendaciones[indice] if indice < len(recomendaciones) else None
            fila = tarjeta["widget"]
            icono = tarjeta["icon"]
            nombre = tarjeta["name"]
            puntuacion = tarjeta["score"]
            barra = tarjeta["bar"]
            if not isinstance(item, dict):
                if not fila.isHidden():
                    fila.hide()
                continue
            if fila.isHidden():
                fila.show()
            item_id = str(item.get("item_id", item.get("id", "")))
            nombre_completo = str(item.get("name", "Objeto"))
            nombre_elidido = nombre.fontMetrics().elidedText(
                nombre_completo, Qt.TextElideMode.ElideRight, 94
            )
            if nombre.text() != nombre_elidido:
                nombre.setText(nombre_elidido)
            if nombre.toolTip() != nombre_completo:
                nombre.setToolTip(nombre_completo)
            score = float(item["score"])
            texto_puntuacion = f"{score:.1f} · Sinergia"
            if puntuacion.text() != texto_puntuacion:
                puntuacion.setText(texto_puntuacion)
            valor_barra = round(100 * score / mayor_puntuacion) if mayor_puntuacion > 0 else 0
            if barra.value() != valor_barra:
                barra.setValue(valor_barra)
            ayuda_barra = "Proporción visual respecto a la mayor puntuación mostrada; la cifra son puntos del motor."
            if barra.toolTip() != ayuda_barra:
                barra.setToolTip(ayuda_barra)
            self._set_item_icon(icono, item_id, 40)
            motivos = "\n".join(str(motivo) for motivo in item.get("reasons", []))
            if item.get("cost") is not None:
                motivos = f"{motivos}\nCoste: {int(item['cost']):,} oro".strip()
            if fila.toolTip() != motivos:
                fila.setToolTip(motivos)
            _set_property(fila, "rank", str(indice + 1))
        self._rendered_recommendations = modelo
        self._rendered_champion = campeon
        if cambio_vista:
            self.adjustSize()

    def reset_recommendations(self, message: str) -> None:
        """Elimina recomendaciones al cambiar de sesión o campeón.

        Parámetros: estado breve para la nueva identidad de partida.
        Retorno: None; limpia tarjetas e iconos evitando datos de otra sesión.
        """
        self._status_signature = None
        self.set_status(message)
        self._rendered_recommendations = ()
        self._rendered_champion = ""
        self.model_change_count += 1
        for tarjeta in self.cards:
            fila = tarjeta["widget"]
            icono = tarjeta["icon"]
            if not fila.isHidden():
                fila.hide()
            icono.setProperty("rendered_item_id", "")
            icono.setProperty("asset_key", "")
            icono.setPixmap(QPixmap())
            tarjeta["name"].clear()
            tarjeta["score"].setText("—")
            tarjeta["bar"].setValue(0)
        self._showing_recommendations = False


class OverlayWindow(QObject):
    """Gestor de los tres paneles flotantes y de su configuración.

    La ventana principal lo alimenta con ``update_snapshot`` cada segúndo y el
    gestor calcula oro, alertas y rivales destacados y muestra u oculta cada
    panel según sus ajustes. La configuración vive en el dict ``settings``
    compartido con la ventana principal y se guarda con ``settings_service``.
    """

    state_changed = Signal()

    @staticmethod
    def configurar_registro_diagnostico() -> None:
        """Activa un registro rotatorio para el ciclo de vida de los overlays.

        Parámetros: ninguno.
        Retorno: None; guarda diagnósticos acotados en ~/.solralol/logs.
        """
        if any(
            getattr(handler, "_solralol_overlay_handler", False)
            for handler in _LOGGER.handlers
        ):
            return
        try:
            ruta = Path.home() / ".solralol" / "logs" / "overlay.log"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                ruta,
                maxBytes=2_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
            handler.setLevel(logging.INFO)
            handler._solralol_overlay_handler = True
            _LOGGER.addHandler(handler)
            _LOGGER.setLevel(logging.INFO)
        except OSError:
            _LOGGER.warning("No se pudo crear el registro de diagnóstico de overlays")

    SETTINGS_PANELS = "overlay_panels"
    SETTINGS_POSITIONS = "overlay_positions"
    SETTINGS_OPACITY = "overlay_opacity"
    SETTINGS_CLICK_THROUGH = "overlay_click_through"
    SETTINGS_ALERT_LEAD = "overlay_alert_lead"
    SETTINGS_SOUND_ENABLED = "overlay_sound_enabled"
    SETTINGS_SOUND_OBJECTIVE = "overlay_sound_objective"
    SETTINGS_SOUND_DRAGON = "overlay_sound_dragon"
    SETTINGS_SOUND_ENEMY_BUY = "overlay_sound_enemy_buy"
    SETTINGS_SOUND_VOLUME = "overlay_sound_volume"
    SETTINGS_TAB_ONLY = "overlay_tab_only"
    SETTINGS_PANEL_OPACITY = "overlay_panel_opacity"
    SETTINGS_PANEL_CLICK_THROUGH = "overlay_panel_click_through"
    SETTINGS_ALERT_DURATION = "overlay_alert_duration"
    SETTINGS_PANEL_SCALE = "overlay_panel_scales"

    def __init__(
        self,
        item_catalog: dict,
        settings_service: SettingsService | None = None,
        settings: dict | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.item_catalog = item_catalog if isinstance(item_catalog, dict) else {}
        self.settings_service = settings_service or SettingsService()
        self.settings = (
            settings if isinstance(settings, dict) else self.settings_service.load()
        )

        self.click_through = bool(self.settings.get(self.SETTINGS_CLICK_THROUGH, False))
        self.opacity = self._bounded(
            int(self.settings.get(self.SETTINGS_OPACITY, DEFAULT_OPACITY)),
            MIN_OPACITY,
            MAX_OPACITY,
        )
        self.alert_lead_seconds = self._bounded(
            int(self.settings.get(self.SETTINGS_ALERT_LEAD, DEFAULT_ALERT_LEAD)),
            MIN_ALERT_LEAD,
            MAX_ALERT_LEAD,
        )
        self.alert_duration_seconds = self._bounded(
            int(
                self.settings.get(
                    self.SETTINGS_ALERT_DURATION, DEFAULT_NOTIFICATION_DURATION
                )
            ),
            3,
            10,
        )
        self.alert_tracker = OverlayAlertTracker(
            self.item_catalog,
            lead_seconds=self.alert_lead_seconds,
        )
        self.sound_service = OverlaySoundService(
            enabled=bool(self.settings.get(self.SETTINGS_SOUND_ENABLED, True)),
            volume=float(self.settings.get(self.SETTINGS_SOUND_VOLUME, DEFAULT_VOLUME)),
        )
        self.sound_service.set_kind_enabled(
            "objective",
            bool(self.settings.get(self.SETTINGS_SOUND_OBJECTIVE, True)),
        )
        self.sound_service.set_kind_enabled(
            "dragon",
            bool(self.settings.get(self.SETTINGS_SOUND_DRAGON, True)),
        )
        self.sound_service.set_kind_enabled(
            "enemy_buy",
            bool(self.settings.get(self.SETTINGS_SOUND_ENEMY_BUY, True)),
        )
        # Avisos ya sonados: cada alerta emite su pitido una sola vez.
        self._last_sound_alerts: set[str] = set()

        self.panels: dict[str, _FloatingPanel] = {
            "gold": GoldPanel(self.item_catalog),
            "alerts": AlertsPanel(self.item_catalog),
            "threat": ThreatPanel(self.item_catalog),
            "purchase": PanelCompraRecomendada(self.item_catalog),
        }
        self.panels["alerts"].activity_changed.connect(self.refresh_visibility)
        self.panels["alerts"].duration_seconds = self.alert_duration_seconds
        self.panels_enabled = dict(self._load_enabled())
        self.tab_only = dict(self._load_tab_only())
        self.panel_opacities = self._load_panel_opacities()
        self.panel_click_through = self._load_panel_click_through()
        self.panel_scales = self._load_panel_scales()
        self.editing_panel: str | None = None
        self.tab_down = False
        self._in_game = False
        self._last_game_time = -1.0
        self._match_generation = 0
        self._recording_snapshot: tuple[bool, float] | None = None
        self._purchase_signature: tuple = ()
        self._purchase_request_token: tuple | None = None
        self._purchase_generation = 0
        self._purchase_task = None
        self._purchase_context: tuple[str, str, str] | None = None
        self._purchase_recommendations: list[dict] = []
        self._purchase_owned_ids: tuple[str, ...] = ()
        self._last_logged_purchase_ids: tuple[str, ...] | None = None
        self._recommendation_session: dict | None = None
        self._panel_error_signatures: dict[str, tuple[str, str]] = {}
        self._demo_mode = False
        self._demo_previous_in_game = False
        self._visibility_signatures: dict[str, tuple[object, ...]] = {}

        for panel in self.panels.values():
            panel.moved_callback = self._panel_moved
            panel.scale_changed_callback = self._panel_scale_changed
            panel.set_click_through(self.panel_click_through[panel.key])
            panel.set_overlay_opacity(self.panel_opacities[panel.key])
            panel.set_scale(self.panel_scales[panel.key])

        self._restore_positions()

    def connect_tab_hotkey(self, service) -> None:
        """Conecta el vigilante de TAB: emite state_changed en cada flanco."""
        if service is None:
            return

        service.tab_changed.connect(self._on_tab_changed)

        if service.is_tab_down:
            self._on_tab_changed(True)

    def _on_tab_changed(self, down: bool) -> None:
        down = bool(down)

        if down == self.tab_down:
            return

        self.tab_down = down
        self.refresh_visibility()
        self.state_changed.emit()

    @staticmethod
    def _bounded(value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(int(value), maximum))

    def _load_enabled(self) -> dict[str, bool]:
        stored = self.settings.get(self.SETTINGS_PANELS, {})

        if not isinstance(stored, dict):
            stored = {}

        return {key: bool(stored.get(key, True)) for key in PANEL_KEYS}

    def _load_tab_only(self) -> dict[str, bool]:
        stored = self.settings.get(self.SETTINGS_TAB_ONLY, {})

        if not isinstance(stored, dict):
            stored = {}

        return {key: bool(stored.get(key, False)) for key in PANEL_KEYS}

    def _load_panel_opacities(self) -> dict[str, int]:
        """Migra y valida las opacidades independientes de cada panel.

        Parámetros: ninguno.
        Retorno: mapa por panel; los usuarios antiguos heredan el valor global.
        """
        stored = self.settings.get(self.SETTINGS_PANEL_OPACITY, {})
        stored = stored if isinstance(stored, dict) else {}
        return {
            key: self._bounded(int(stored.get(key, self.opacity)), 0, MAX_OPACITY)
            for key in PANEL_KEYS
        }

    def _load_panel_click_through(self) -> dict[str, bool]:
        """Migra y valida la captura de clics independiente de cada panel.

        Parámetros: ninguno.
        Retorno: mapa por panel con el ajuste global heredado si falta.
        """
        stored = self.settings.get(self.SETTINGS_PANEL_CLICK_THROUGH, {})
        stored = stored if isinstance(stored, dict) else {}
        return {key: bool(stored.get(key, self.click_through)) for key in PANEL_KEYS}

    def _load_panel_scales(self) -> dict[str, float]:
        """Carga escalas individuales y migra perfiles antiguos al 100 %.

        Parámetros: ninguno.
        Retorno: factor entre 0,5 y 1,5 por overlay.
        """
        stored = self.settings.get(self.SETTINGS_PANEL_SCALE, {})
        stored = stored if isinstance(stored, dict) else {}
        result: dict[str, float] = {}
        for key in PANEL_KEYS:
            try:
                result[key] = max(0.5, min(1.5, float(stored.get(key, 1.0))))
            except (TypeError, ValueError):
                result[key] = 1.0
        return result

    def panel_scale(self, key: str) -> float:
        """Devuelve la escala persistida de un panel.

        Parámetros: clave del overlay.
        Retorno: factor uniforme entre 0,5 y 1,5.
        """
        return self.panel_scales.get(key, 1.0)

    def set_panel_scale(self, key: str, scale: float) -> None:
        """Actualiza desde Ajustes la escala común del overlay.

        Parámetros: clave del panel y factor solicitado.
        Retorno: None; actualiza la ventana y guarda la preferencia.
        """
        if key not in self.panels:
            return
        self.panel_scales[key] = max(0.5, min(1.5, float(scale)))
        self.panels[key].set_scale(self.panel_scales[key])
        self._clamp_panel_position(self.panels[key])
        self._persist()
        self.state_changed.emit()

    def _panel_scale_changed(self, panel: _FloatingPanel) -> None:
        """Recibe la escala producida al arrastrar el asa del panel.

        Parámetros: panel que se acaba de escalar.
        Retorno: None; sincroniza el estado común sin escribir por cada pixel.
        """
        self.panel_scales[panel.key] = panel.scale_factor
        self.state_changed.emit()

    def begin_editing(self, key: str) -> None:
        """Desbloquea un overlay para moverlo y cambiar su escala.

        Parámetros: clave del overlay elegido.
        Retorno: None; fuerza entrada de ratón temporalmente.
        """
        if key not in self.panels:
            return
        if self.editing_panel and self.editing_panel != key:
            self.panels[self.editing_panel].set_editing(False)
            self.panels[self.editing_panel].set_click_through(
                self.panel_click_through[self.editing_panel]
            )
        self.editing_panel = key
        panel = self.panels[key]
        panel.set_editing(True)
        panel.setVisible(True)
        panel.raise_()
        self.state_changed.emit()

    def end_editing(self) -> None:
        """Cierra la edición y restaura la configuración de click-through.

        Parámetros: ninguno.
        Retorno: None; persiste posición y escala del panel desbloqueado.
        """
        key = self.editing_panel
        if key is None:
            return
        panel = self.panels[key]
        panel.set_editing(False)
        panel.set_click_through(self.panel_click_through[key])
        self.editing_panel = None
        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

    def panel_opacity(self, key: str) -> int:
        """Devuelve la opacidad guardada para un panel.

        Parámetros: clave del panel.
        Retorno: porcentaje entre 0 y 100.
        """
        return self.panel_opacities.get(key, self.opacity)

    def panel_clicks_locked(self, key: str) -> bool:
        """Indica si el panel deja pasar los clics al juego.

        Parámetros: clave del panel.
        Retorno: True si el panel está en modo click-through.
        """
        return self.panel_click_through.get(key, self.click_through)

    def set_panel_opacity(self, key: str, percent: int) -> None:
        """Actualiza la opacidad de un único panel y la persiste.

        Parámetros: clave y porcentaje de opacidad.
        Retorno: None; aplica el valor al panel existente.
        """
        if key not in self.panels:
            return
        self.panel_opacities[key] = self._bounded(int(percent), 0, MAX_OPACITY)
        self.panels[key].set_overlay_opacity(self.panel_opacities[key])
        self._persist()

    def set_panel_click_through(self, key: str, enabled: bool) -> None:
        """Cambia el bloqueo de clics de un único panel y lo persiste.

        Parámetros: clave del panel y modo click-through.
        Retorno: None; actualiza el estilo de ventana independiente.
        """
        if key not in self.panels:
            return
        self.panel_click_through[key] = bool(enabled)
        self.panels[key].set_click_through(bool(enabled))
        self._persist()

    def set_assets(self, assets) -> None:
        """Conecta el servicio de iconos de Data Dragon a los tres paneles."""
        for panel in self.panels.values():
            panel.set_assets(assets)

    @property
    def in_game(self) -> bool:
        return self._in_game

    def is_panel_enabled(self, key: str) -> bool:
        return bool(self.panels_enabled.get(key, False))

    def enabled_panels(self) -> dict[str, bool]:
        return {key: self.is_panel_enabled(key) for key in PANEL_KEYS}

    def any_enabled(self) -> bool:
        return any(self.is_panel_enabled(key) for key in PANEL_KEYS)

    def set_panel_enabled(self, key: str, enabled: bool) -> None:
        if key not in PANEL_KEYS:
            return

        self.panels_enabled[key] = bool(enabled)
        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

    def toggle_panel(self, key: str) -> bool:
        enabled = not self.is_panel_enabled(key)
        self.set_panel_enabled(key, enabled)

        return enabled

    def toggle_all(self) -> bool:
        """Activa los tres paneles si hay alguno apagado; si no, los apaga."""
        enabled = not self.any_enabled()

        for key in PANEL_KEYS:
            self.panels_enabled[key] = enabled

        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

        return enabled

    def set_click_through(self, enabled: bool) -> None:
        self.click_through = bool(enabled)

        for panel in self.panels.values():
            self.panel_click_through[panel.key] = self.click_through
            panel.set_click_through(self.click_through)

        self._persist()
        self.state_changed.emit()

    def set_overlay_opacity(self, percent: int) -> None:
        self.opacity = self._bounded(int(percent), MIN_OPACITY, MAX_OPACITY)

        for panel in self.panels.values():
            self.panel_opacities[panel.key] = self.opacity
            panel.set_overlay_opacity(self.opacity)

        self._persist()
        self.state_changed.emit()

    def set_alert_lead_seconds(self, seconds: int) -> None:
        self.alert_lead_seconds = self._bounded(
            int(seconds), MIN_ALERT_LEAD, MAX_ALERT_LEAD
        )
        self.alert_tracker.lead_seconds = self.alert_lead_seconds
        self._persist()
        self.state_changed.emit()

    def set_alert_duration_seconds(self, seconds: int) -> None:
        """Actualiza y persiste la duración de una notificación.

        Parámetros: duración en segundos.
        Retorno: None; la próxima alerta usa el tiempo seleccionado.
        """
        self.alert_duration_seconds = self._bounded(int(seconds), 3, 10)
        self.panels["alerts"].duration_seconds = self.alert_duration_seconds
        self._persist()
        self.state_changed.emit()

    def update_snapshot(self, snapshot: dict) -> None:
        """Recalcula los tres paneles con el snapshot de la partida."""
        if self._demo_mode:
            return
        if not isinstance(snapshot, dict) or not snapshot:
            self.clear()
            return

        game_time = float(snapshot.get("game_time", 0) or 0)

        nueva_partida = not self._in_game or game_time + 5 < self._last_game_time
        if nueva_partida:
            self._match_generation += 1
            _LOGGER.info(
                "[OverlayDebug] transición partida activa game_time=%.1f reinicio=%s",
                game_time,
                self._in_game and game_time + 5 < self._last_game_time,
            )
            self.alert_tracker.reset()
            self._last_sound_alerts.clear()

        self._in_game = True
        self._demo_mode = False
        self._last_game_time = max(game_time, self._last_game_time)

        operaciones = (
            (
                "gold",
                lambda: self.panels["gold"].render(
                    build_gold_report(snapshot, self.item_catalog)
                ),
            ),
            (
                "threat",
                lambda: self.panels["threat"].render(
                    build_rival_ranking(snapshot, self.item_catalog)
                ),
            ),
            ("purchase", lambda: self._update_purchase_panel(snapshot)),
            (
                "alerts",
                lambda: self.panels["alerts"].render(
                    self.alert_tracker.update(snapshot)
                ),
            ),
        )
        for clave, actualizar in operaciones:
            try:
                actualizar()
                self._panel_error_signatures.pop(clave, None)
            except Exception as error:
                firma_error = (type(error).__name__, str(error))
                if self._panel_error_signatures.get(clave) != firma_error:
                    self._panel_error_signatures[clave] = firma_error
                    _LOGGER.exception("Falló la actualización del overlay %s", clave)

        if self._recording_snapshot is not None:
            self.panels["alerts"].set_recording(
                self._recording_snapshot[0], self._recording_snapshot[1]
            )

        self.refresh_visibility()

        # Cada aviso nuevo emite su pitido (si los sonidos están activados).
        self._emit_alert_sounds(game_time)

    def update_recommendation_session(self, session: dict) -> None:
        """Entrega al overlay la misma sesión que analiza la pestaña LIVE.

        Parámetros: sesión normalizada del tracker LIVE.
        Retorno: None; reutiliza el servicio y el esquema de recomendaciones LIVE.
        """
        if not isinstance(session, dict) or not session:
            return
        self._recommendation_session = session
        if self._in_game and not self._demo_mode:
            self._update_purchase_session(session)

    def _prepare_purchase_context(
        self,
        identity: tuple[str, str, str],
        owned_ids: tuple[str, ...],
    ) -> None:
        """Aísla recomendaciones por partida, campeón y modo.

        Parámetros: identidad de sesión y objetos que el jugador ya posee.
        Retorno: None; invalida datos de otra partida y retira compras adquiridas.
        """
        panel = self.panels["purchase"]
        if identity != self._purchase_context:
            if self._purchase_task is not None:
                self._purchase_task.cancel()
            self._purchase_generation += 1
            self._purchase_context = identity
            self._purchase_signature = ()
            self._purchase_request_token = None
            self._purchase_recommendations = []
            self._purchase_owned_ids = owned_ids
            self._last_logged_purchase_ids = None
            panel.reset_recommendations("Preparando recomendaciones…")
            _LOGGER.info(
                "[PurchaseOverlay] nuevo contexto session=%s champion=%s mode=%s",
                identity[0],
                identity[1],
                identity[2],
            )
            return
        if owned_ids == self._purchase_owned_ids:
            return
        self._purchase_owned_ids = owned_ids
        anteriores = tuple(
            str(item.get("item_id", item.get("id", "")))
            for item in self._purchase_recommendations
        )
        conservadas = [
            item
            for item in self._purchase_recommendations
            if str(item.get("item_id", item.get("id", ""))) not in owned_ids
        ]
        self._purchase_recommendations = conservadas
        posteriores = tuple(
            str(item.get("item_id", item.get("id", ""))) for item in conservadas
        )
        if anteriores != posteriores:
            if conservadas:
                panel.render(identity[1], conservadas)
            else:
                panel.reset_recommendations("Actualizando recomendaciones…")
            _LOGGER.info(
                "[PurchaseOverlay] inventario actualizado items=%s",
                posteriores,
            )

    def _update_purchase_session(self, session: dict) -> None:
        """Actualiza compras desde la sesión canónica de la pestaña LIVE.

        Parámetros: sesión actual construida por LiveMatchTracker.
        Retorno: None; programa solo cambios en campeón, inventario o amenazas.
        """
        from app.services.live_recommendation_service import LiveRecommendationService

        jugadores, _ = LiveRecommendationService.latest(session)
        clave_local = str(session.get("local_player_key") or "")
        local = jugadores.get(clave_local, {})
        campeon = str(local.get("champion_name") or session.get("champion_name") or "")
        if not campeon:
            if self._purchase_context and self._purchase_recommendations:
                _LOGGER.info(
                    "[PurchaseOverlay] identidad local temporalmente incompleta; "
                    "se mantienen items=%s",
                    tuple(
                        str(item.get("item_id", item.get("id", "")))
                        for item in self._purchase_recommendations
                    ),
                )
                return
            self.panels["purchase"].set_status("Esperando datos del campeón")
            return
        inventario_local = tuple(
            sorted(
                str(item.get("itemID", item.get("id", "")) if isinstance(item, dict) else item)
                for item in local.get("items", [])
            )
        )
        equipo_local = str(local.get("team") or session.get("local_team") or "")
        contexto_enemigo = tuple(
            sorted(
                (
                    str(jugador.get("champion_name") or ""),
                    tuple(
                        sorted(
                            str(
                                item.get("itemID", item.get("id", ""))
                                if isinstance(item, dict)
                                else item
                            )
                            for item in (
                                jugador.get("items", [])
                                if isinstance(jugador.get("items"), list)
                                else []
                            )
                        )
                    ),
                    str(jugador.get("kills", "")),
                    str(jugador.get("deaths", "")),
                    str(jugador.get("level", "")),
                )
                for clave, jugador in jugadores.items()
                if isinstance(jugador, dict)
                and clave != clave_local
                and (
                    jugador.get("side") == "enemy"
                    or (
                        equipo_local
                        and jugador.get("team")
                        and jugador.get("team") != equipo_local
                    )
                )
            )
        )
        modo = str(session.get("game_mode") or "UNKNOWN")
        identidad_sesion = str(
            session.get("session_id") or session.get("started_at") or "live"
        )
        identidad = (identidad_sesion, campeon, modo)
        self._prepare_purchase_context(identidad, inventario_local)
        firma = (identidad, inventario_local, contexto_enemigo)
        if firma == self._purchase_signature:
            return
        if self._purchase_task is not None:
            try:
                self._purchase_task.cancel()
            except AttributeError:
                pass
        self._purchase_signature = firma
        self._purchase_generation += 1
        token = (self._purchase_generation, identidad, firma)
        self._purchase_request_token = token
        if not self._purchase_recommendations:
            self.panels["purchase"].set_status("Calculando recomendaciones…")
        try:
            self._purchase_task = run_async(
                partial(
                    _calcular_compras_recomendadas,
                    campeon,
                    (),
                    (),
                    None,
                    modo,
                    str(local.get("role") or ""),
                    catalogo_objetos=self.item_catalog,
                    sesion_live=session,
                ),
                on_finished=self._apply_purchase_recommendations,
                token=token,
            )
        except Exception as error:
            _LOGGER.exception("No se pudo iniciar el worker de compras LIVE")
            self._purchase_task = None
            self._mostrar_fallo_compra(identidad, str(error))

    def _update_purchase_panel(self, snapshot: dict) -> None:
        """Calcula compras curadas solo cuando cambia el contexto relevante.

        Parámetros: snapshot actual de Live Client Data.
        Retorno: None; mantiene una caché de build para evitar recálculos por tick.
        """
        local = snapshot.get("local_player", {})
        if not isinstance(local, dict):
            if self._purchase_recommendations:
                _LOGGER.info(
                    "[PurchaseOverlay] snapshot local temporalmente ausente; se mantienen items=%s",
                    tuple(
                        str(item.get("item_id", item.get("id", "")))
                        for item in self._purchase_recommendations
                    ),
                )
                return
            self.panels["purchase"].set_status("Esperando datos de partida…")
            return
        campeon = str(local.get("championName", ""))
        sesion_live = self._recommendation_session
        if (
            isinstance(sesion_live, dict)
            and not sesion_live.get("ended_at")
            and (
                not campeon
                or str(sesion_live.get("champion_name") or "") == campeon
            )
        ):
            self._update_purchase_session(sesion_live)
            return
        if not campeon:
            if self._purchase_recommendations:
                _LOGGER.info(
                    "[PurchaseOverlay] campeón temporalmente ausente; se mantienen las compras"
                )
                return
            self.panels["purchase"].set_status("Esperando identificación del campeón")
            return
        enemigos = tuple(
            sorted(
                (
                    str(jugador.get("championName", "")),
                    str(
                        jugador.get("position")
                        or jugador.get("teamPosition")
                        or "UNKNOWN"
                    ),
                )
                for jugador in snapshot.get("all_players", [])
                if isinstance(jugador, dict)
                and jugador.get("team") != local.get("team")
            )
        )
        inventario = local.get("items", [])
        ids_poseidos = (
            tuple(
                sorted(
                    str(item.get("itemID"))
                    for item in inventario
                    if isinstance(item, dict) and item.get("itemID") is not None
                )
            )
            if isinstance(inventario, list)
            else ()
        )
        pagina_runas = _normalizar_runas_vivas(local.get("runes"))
        modo_partida = str(snapshot.get("game_mode") or "UNKNOWN")
        rol_original = str(local.get("position") or local.get("teamPosition") or "")
        rol_jugador = {
            "TOP": "top",
            "JUNGLE": "jungle",
            "MIDDLE": "mid",
            "MID": "mid",
            "BOTTOM": "bot",
            "ADC": "bot",
            "UTILITY": "support",
            "SUPPORT": "support",
        }.get(rol_original.upper(), "")
        firma = (
            campeon,
            rol_jugador,
            enemigos,
            ids_poseidos,
            repr(pagina_runas),
            modo_partida,
            tuple(
                sorted(
                    (
                        str(jugador.get("championName", "")),
                        tuple(sorted(str(item.get("itemID", "")) for item in jugador.get("items", []) if isinstance(item, dict))),
                        int((jugador.get("scores") or {}).get("kills", 0) or 0),
                        int((jugador.get("scores") or {}).get("deaths", 0) or 0),
                    )
                    for jugador in snapshot.get("all_players", [])
                    if isinstance(jugador, dict) and jugador.get("team") != local.get("team")
                )
            ),
        )
        identidad = (
            f"snapshot:{self._match_generation}",
            campeon,
            modo_partida,
        )
        self._prepare_purchase_context(identidad, ids_poseidos)
        firma = (identidad, firma)
        if firma == self._purchase_signature:
            return
        if self._purchase_task is not None:
            try:
                self._purchase_task.cancel()
            except AttributeError:
                pass
        self._purchase_signature = firma
        self._purchase_generation += 1
        token = (self._purchase_generation, identidad, firma)
        self._purchase_request_token = token
        if not self._purchase_recommendations:
            self.panels["purchase"].set_status("Calculando recomendaciones…")
        try:
            self._purchase_task = run_async(
                partial(
                    _calcular_compras_recomendadas,
                    campeon,
                    enemigos,
                    ids_poseidos,
                    pagina_runas,
                    modo_partida,
                    rol_jugador,
                    instantanea=snapshot,
                    catalogo_objetos=self.item_catalog,
                ),
                on_finished=self._apply_purchase_recommendations,
                token=token,
            )
        except Exception as error:
            _LOGGER.exception("No se pudo iniciar el worker de compras")
            self._purchase_task = None
            self._mostrar_fallo_compra(identidad, str(error))

    def _apply_purchase_recommendations(
        self, token: tuple, result: object, error: str | None
    ) -> None:
        """Aplica solo el resultado vigente y conserva datos v?lidos ante fallos.

        Par?metros: token generacional, lista de candidatos y error opcional.
        Retorno: None; descarta resultados obsoletos y actualiza slots persistentes.
        """
        if token != self._purchase_request_token:
            return
        self._purchase_task = None
        self._purchase_request_token = None
        identidad = token[1]
        panel = self.panels["purchase"]
        if error:
            _LOGGER.error(
                "[PurchaseOverlay] fallo generation=%s champion=%s: %s",
                token[0],
                identidad[1],
                error,
            )
            self._mostrar_fallo_compra(identidad, error)
            return
        recomendaciones = result if isinstance(result, list) else []
        if not recomendaciones:
            if identidad == self._purchase_context and self._purchase_recommendations:
                _LOGGER.info(
                    "[PurchaseOverlay] respuesta vac?a temporal; se conservan items=%s",
                    tuple(
                        str(item.get("item_id", item.get("id", "")))
                        for item in self._purchase_recommendations
                    ),
                )
                return
            panel.set_status("Sin recomendaciones v?lidas")
            return
        recomendaciones = [
            item
            for item in recomendaciones
            if isinstance(item, dict)
            and str(item.get("item_id", item.get("id", "")))
            and str(item.get("item_id", item.get("id", "")))
            not in self._purchase_owned_ids
        ][:3]
        if not recomendaciones:
            if identidad == self._purchase_context and self._purchase_recommendations:
                _LOGGER.info(
                    "[PurchaseOverlay] resultados ya pose?dos; se preserva la lista actual"
                )
                return
            panel.set_status("Sin recomendaciones compatibles")
            return
        try:
            panel.render(str(identidad[1]), recomendaciones)
        except Exception as render_error:
            _LOGGER.exception(
                "[PurchaseOverlay] fall? el render para %s", identidad[1]
            )
            self._mostrar_fallo_compra(identidad, str(render_error))
            return
        ids = tuple(
            str(item.get("item_id", item.get("id", "")))
            for item in recomendaciones
        )
        if ids != self._last_logged_purchase_ids:
            _LOGGER.info(
                "[PurchaseOverlay] recomendaciones session=%s champion=%s ids=%s",
                identidad[0],
                identidad[1],
                ids,
            )
            self._last_logged_purchase_ids = ids
        self._purchase_recommendations = recomendaciones

    def _mostrar_fallo_compra(
        self, identidad: tuple[str, str, str], detalle: str
    ) -> None:
        """Mantiene las ?ltimas compras v?lidas ante un fallo temporal.

        Par?metros: identidad de sesi?n y detalle diagn?stico del fallo.
        Retorno: None; muestra error solo si no hay recomendaciones actuales.
        """
        panel = self.panels["purchase"]
        if identidad == self._purchase_context and self._purchase_recommendations:
            panel.status_label.setToolTip(str(detalle))
            _LOGGER.warning(
                "[PurchaseOverlay] se mantienen items=%s durante el fallo temporal",
                tuple(
                    str(item.get("item_id", item.get("id", "")))
                    for item in self._purchase_recommendations
                ),
            )
            return
        panel.set_status("No se pudieron calcular las recomendaciones", detalle)

    def _emit_alert_sounds(self, game_time: float) -> None:
        """Suena cada aviso nuevo: objetivos, dragón y compras rivales."""
        if not self.sound_service.enabled:
            return

        alerts = self.alert_tracker.active_alerts(game_time)
        current_keys: set[str] = set()

        for alert in alerts:
            key = str(alert.get("key") or "")

            if not key:
                continue

            current_keys.add(key)

            if key in self._last_sound_alerts:
                continue

            self._last_sound_alerts.add(key)

            if alert.get("kind") == "objective":
                if key == "objective:dragon":
                    self.sound_service.play_dragon_spawn()
                else:
                    self.sound_service.play_objective_spawn()
            elif alert.get("kind") == "purchase" and alert.get("side") == "enemy":
                self.sound_service.play_enemy_buy()

        # Los avisos que ya no están activos podrán volver a sonar si reaparecen.
        self._last_sound_alerts &= current_keys

    def set_sound_enabled(self, enabled: bool) -> None:
        """Activa o desactiva todos los sonidos del overlay."""
        self.sound_service.set_enabled(enabled)
        self._persist()
        self.state_changed.emit()

    def set_sound_kind_enabled(self, kind: str, enabled: bool) -> None:
        """Activa o desactiva un tipo concreto de sonido."""
        self.sound_service.set_kind_enabled(kind, enabled)
        self._persist()
        self.state_changed.emit()

    def set_sound_volume(self, volume: float) -> None:
        """Ajusta el volumen de los pitidos (0.0 a 1.0)."""
        self.sound_service.set_volume(volume)
        self._persist()
        self.state_changed.emit()

    def is_sound_enabled(self) -> bool:
        """True si los pitidos del overlay están activados."""
        return self.sound_service.enabled

    def set_recording(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        """Guarda el estado de grabación para mostrarlo en el panel de alertas.

        La fila «Grabando» se pinta en el siguiente ``render`` (o en el
        siguiente ``update_snapshot``), porque los widgets solo deben tocarse
        desde el hilo que los usa.
        """
        try:
            elapsed = max(0.0, float(elapsed_seconds))
        except (TypeError, ValueError):
            elapsed = 0.0

        self._recording_snapshot = (bool(active), elapsed)
        self.panels["alerts"].set_recording(active, elapsed)
        self.refresh_visibility()

    def clear(self) -> None:
        """Sin partida no hay nada que mostrar: se ocultan los paneles."""
        if self._in_game or self._demo_mode:
            _LOGGER.info("[OverlayDebug] transición a espera; ocultando overlays")
        self._in_game = False
        self._demo_mode = False
        self._last_game_time = -1.0
        self._last_sound_alerts.clear()
        self.alert_tracker.reset()
        self._recording_snapshot = None
        self._purchase_signature = ()
        self._recommendation_session = None
        self._purchase_generation += 1
        self._purchase_request_token = None
        if self._purchase_context is not None:
            self.panels["purchase"].reset_recommendations(
                "Esperando datos de partida…"
            )
        self._purchase_context = None
        self._purchase_recommendations = []
        self._purchase_owned_ids = ()
        self._last_logged_purchase_ids = None
        if self._purchase_task is not None:
            self._purchase_task.cancel()
            self._purchase_task = None
        self.panels["alerts"].set_recording(False)
        self.panels["alerts"].clear_transient()

        for panel in self.panels.values():
            if panel.isVisible():
                panel.hide()
        self.refresh_visibility()

    def is_tab_only(self, key: str) -> bool:
        """True si ese panel solo se muestra mientras TAB está pulsado."""
        return bool(self.tab_only.get(key, False))

    def set_tab_only(self, key: str, enabled: bool) -> None:
        """El panel con esta opción solo aparece mientras TAB está pulsado."""
        if key not in PANEL_KEYS:
            return

        self.tab_only[key] = bool(enabled)
        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

    def refresh_visibility(self) -> None:
        for key, panel in self.panels.items():
            visible = self.is_panel_enabled(key) and (self._in_game or self._demo_mode)

            if key == "alerts":
                alerts_panel = self.panels["alerts"]
                panel_alerts = any(not row.isHidden() for row in alerts_panel.rows)
                panel_alerts = panel_alerts or not alerts_panel.recording_row.isHidden()
                visible = (
                    self.is_panel_enabled(key)
                    and (self._in_game or self._demo_mode)
                    and panel_alerts
                )

            if self.is_tab_only(key) and not self.tab_down:
                visible = False

            if self.editing_panel == key:
                visible = True

            if panel.isVisible() != visible:
                panel.setVisible(visible)
                if visible:
                    panel.raise_()

            self._log_panel_state(key, "visibility")

    def show_demo_overlays(self) -> None:
        """Muestra los cuatro renderizadores con muestras aisladas de demostración.

        Parámetros: ninguno.
        Retorno: None; activa temporalmente solo los paneles habilitados.
        """
        _LOGGER.info("[OverlayDebug] activando modo de prueba de overlays")
        self._demo_previous_in_game = self._in_game
        self._demo_mode = True
        self.panels["alerts"].render(
            [
                {
                    "kind": "objective",
                    "key": "demo-dragon",
                    "name": "Dragón en 45 s",
                    "remaining": 45,
                    "detail": "Coloca visión y prepara rotación.",
                }
            ]
        )
        self.panels["gold"].render(
            {
                "team": {"delta": 1900},
                "lanes": [
                    {
                        "role": role,
                        "ally": {"champion": "Garen", "gold": ally},
                        "enemy": {"champion": "Darius", "gold": enemy},
                        "paired": True,
                        "delta": ally - enemy,
                    }
                    for role, ally, enemy in (
                        ("TOP", 3200, 2700),
                        ("JUNGLE", 2800, 3000),
                        ("MIDDLE", 4100, 3300),
                        ("BOTTOM", 3700, 3050),
                        ("UTILITY", 1950, 1800),
                    )
                ],
            }
        )
        self.panels["threat"].render(
            {
                "strongest": {"champion": "Garen", "role": "TOP", "score": 1324},
                "weakest": {"champion": "Xin Zhao", "role": "JUNGLE", "score": 642},
            }
        )
        self.panels["purchase"].render(
            "Gragas",
            [
                {"item_id": "3100", "name": "Perdición del liche", "score": 37.9},
                {"item_id": "4646", "name": "Sobrecarga tormentosa", "score": 23.9},
                {"item_id": "4645", "name": "Llamasombría", "score": 19.6},
            ],
        )
        self.refresh_visibility()

    def end_demo_overlays(self) -> None:
        """Retira los datos de demostración y restaura la visibilidad de partida.

        Parámetros: ninguno.
        Retorno: None; evita que muestras de prueba entren en el snapshot vivo.
        """
        if not self._demo_mode:
            return
        self._demo_mode = False
        self._in_game = self._demo_previous_in_game
        self.panels["alerts"].clear_transient()
        for panel in self.panels.values():
            panel.hide()
        self.refresh_visibility()

    def _log_panel_state(self, key: str, reason: str) -> None:
        """Registra cambios de estado nativo del panel sin emitir por frame.

        Parámetros: clave del panel y motivo de comprobación.
        Retorno: None; registra solo cuando cambia una propiedad relevante.
        """
        panel = self.panels[key]
        screen = (
            QGuiApplication.screenAt(panel.frameGeometry().center())
            or QGuiApplication.primaryScreen()
        )
        screen_name = screen.name() if screen is not None else "unavailable"
        signature = (
            self.is_panel_enabled(key),
            self._in_game,
            self._demo_mode,
            self.is_tab_only(key),
            self.editing_panel == key,
            panel.isVisible(),
            panel.pos().x(),
            panel.pos().y(),
            panel.width(),
            panel.height(),
            self.panel_scales[key],
            self.panel_opacities[key],
            panel.windowFlags().value,
            screen_name,
        )
        if self._visibility_signatures.get(key) == signature:
            return
        self._visibility_signatures[key] = signature
        _LOGGER.info(
            "[OverlayDebug] %s reason=%s created=%s enabled=%s match=%s demo=%s global=%s tab_only=%s editing=%s visible=%s native_state=%s position=%s size=%s scale=%.2f opacity=%d flags=%s screen=%s",
            key,
            reason,
            True,
            signature[0],
            self._in_game,
            self._demo_mode,
            self.is_panel_enabled(key),
            self.is_tab_only(key),
            self.editing_panel == key,
            panel.isVisible(),
            panel.windowState().value,
            panel.pos(),
            panel.size(),
            self.panel_scales[key],
            self.panel_opacities[key],
            panel.windowFlags().value,
            screen_name,
        )

    def test_alert(self) -> None:
        """Lanza un aviso de prueba en el panel real de alertas.

        Parámetros: ninguno.
        Retorno: None; no accede al juego ni modifica la grabación.
        """
        if not self.is_panel_enabled("alerts"):
            self.set_panel_enabled("alerts", True)
        self.panels["alerts"].enqueue_test_alert()
        self.refresh_visibility()

    def notify_recording_error(self, detail: str) -> None:
        """Entrega al panel de avisos el fallo del servicio de grabación.

        Parámetros: mensaje seguro del servicio.
        Retorno: None; muestra la notificación temporal si las alertas están activas.
        """
        self.panels["alerts"].enqueue_recording_error(detail)
        self.refresh_visibility()

    def _panel_moved(self, panel: _FloatingPanel) -> None:
        positions = self.settings.get(self.SETTINGS_POSITIONS, {})

        if not isinstance(positions, dict):
            positions = {}

        self._clamp_panel_position(panel)
        positions[panel.key] = [int(panel.x()), int(panel.y())]
        self.settings[self.SETTINGS_POSITIONS] = positions
        self.settings[self.SETTINGS_PANEL_SCALE] = dict(self.panel_scales)
        self.settings_service.save(self.settings)

    @staticmethod
    def _clamp_panel_position(panel: _FloatingPanel) -> None:
        """Mantiene accesible la ventana dentro del área utilizable del monitor.

        Parámetros: panel cuyo tamaño o posición acaba de cambiar.
        Retorno: None; corrige posición según la pantalla actual o principal.
        """
        screen = QGuiApplication.screenAt(panel.frameGeometry().center())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        bounds = screen.availableGeometry()
        x = max(bounds.left(), min(panel.x(), bounds.right() - panel.width() + 1))
        y = max(bounds.top(), min(panel.y(), bounds.bottom() - panel.height() + 1))
        if (x, y) != (panel.x(), panel.y()):
            panel.move(x, y)

    def _persist(self) -> None:
        self.settings[self.SETTINGS_PANELS] = self.enabled_panels()
        self.settings[self.SETTINGS_TAB_ONLY] = {
            key: self.is_tab_only(key) for key in PANEL_KEYS
        }
        self.settings[self.SETTINGS_OPACITY] = self.opacity
        self.settings[self.SETTINGS_CLICK_THROUGH] = self.click_through
        self.settings[self.SETTINGS_PANEL_OPACITY] = dict(self.panel_opacities)
        self.settings[self.SETTINGS_PANEL_CLICK_THROUGH] = dict(
            self.panel_click_through
        )
        self.settings[self.SETTINGS_PANEL_SCALE] = dict(self.panel_scales)
        self.settings[self.SETTINGS_ALERT_LEAD] = self.alert_lead_seconds
        self.settings[self.SETTINGS_ALERT_DURATION] = self.alert_duration_seconds
        self.settings[self.SETTINGS_SOUND_ENABLED] = bool(self.sound_service.enabled)
        self.settings[self.SETTINGS_SOUND_OBJECTIVE] = self.sound_service.kind_enabled(
            "objective"
        )
        self.settings[self.SETTINGS_SOUND_DRAGON] = self.sound_service.kind_enabled(
            "dragon"
        )
        self.settings[self.SETTINGS_SOUND_ENEMY_BUY] = self.sound_service.kind_enabled(
            "enemy_buy"
        )
        self.settings[self.SETTINGS_SOUND_VOLUME] = self.sound_service.volume
        self.settings[self.SETTINGS_POSITIONS] = {
            key: [int(panel.x()), int(panel.y())] for key, panel in self.panels.items()
        }
        self.settings_service.save(self.settings)

    def _restore_positions(self) -> None:
        positions = self.settings.get(self.SETTINGS_POSITIONS, {})

        if not isinstance(positions, dict):
            positions = {}

        missing = [key for key in PANEL_KEYS if not positions.get(key)]

        if missing:
            defaults = self._default_positions(missing)

            for key, point in defaults.items():
                positions[key] = [point[0], point[1]]

            self.settings[self.SETTINGS_POSITIONS] = positions

        for key, panel in self.panels.items():
            stored = positions.get(key)

            if (
                isinstance(stored, (list, tuple))
                and len(stored) == 2
                and all(isinstance(value, int) for value in stored)
            ):
                panel.move(stored[0], stored[1])
                screen = QGuiApplication.screenAt(panel.frameGeometry().center())
                screen = screen or QGuiApplication.primaryScreen()
                if screen is not None:
                    bounds = screen.availableGeometry()
                    x = max(
                        bounds.left(),
                        min(stored[0], bounds.right() - panel.width() + 1),
                    )
                    y = max(
                        bounds.top(),
                        min(stored[1], bounds.bottom() - panel.height() + 1),
                    )
                    panel.move(x, y)

    def _default_positions(self, keys: list[str]) -> dict[str, tuple[int, int]]:
        screen = QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry() if screen is not None else None

        if geometry is None:
            return {key: (PANEL_MARGIN, PANEL_TOP_OFFSET) for key in keys}

        positions: dict[str, tuple[int, int]] = {}
        cursor = geometry.top() + PANEL_TOP_OFFSET

        for key in keys:
            panel = self.panels[key]
            panel.adjustSize()
            height = max(panel.height(), 60)
            positions[key] = (geometry.left() + PANEL_MARGIN, cursor)
            cursor += height + PANEL_GAP

        return positions

    def close(self) -> None:
        self._persist()

        for panel in self.panels.values():
            panel.close()
