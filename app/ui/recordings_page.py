"""Pestaña «Grabaciones»: biblioteca local y reproductor con marcadores.

La lista de la izquierda muestra los vídeos de la carpeta de grabaciones.
El panel de la derecha reproduce el vídeo elegido con los controles
clásicos (pausa, atrás/adelante 10 s) y una barra de progreso con los
indicadores de la partida: asesinatos, muertes, asistencias y objetivos
(torres, dragones, heraldos y barones).
"""

from __future__ import annotations

import logging
import math
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.recording_service import (
    RecordingLibrary,
    RecordingService,
    format_duration,
)
from app.ui.async_task import run_async
from app.ui.componentes_visuales import Reflujo
from app.ui.sistema_visual import PALETA
from app.ui.tema import (
    actualizar_texto_boton,
    color_con_alfa,
)

SEEK_SECONDS = 10
KEYBOARD_SEEK_MS = 5_000
logger = logging.getLogger(__name__)

#: Ancho común para los botones de acción de cada fila de grabación.
RECORDING_ROW_BUTTON_WIDTH = 100

#: Estilo de cada tipo de marcador en la barra y en la lista.
MARKER_STYLES: dict[str, dict[str, str]] = {
    "kill": {"color": PALETA["ventaja"], "glyph": "⚔️"},
    "teamfight": {"color": PALETA["oro_suave"], "glyph": "💥"},
    "death": {"color": PALETA["desventaja"], "glyph": "💀"},
    "assist": {"color": PALETA["teal"], "glyph": "🤝"},
    "dragon": {"color": PALETA["oro_suave"], "glyph": "🐉"},
    "baron": {"color": PALETA["magenta"], "glyph": "👑"},
    "herald": {"color": PALETA["magenta"], "glyph": "👁️"},
    "horde": {"color": PALETA["ventaja"], "glyph": "🐛"},
    "tower": {"color": PALETA["oro_suave"], "glyph": "🏰"},
    "inhibitor": {"color": PALETA["teal"], "glyph": "💠"},
    "objective": {"color": PALETA["magenta"], "glyph": "🎯"},
}


def marker_style(kind: str) -> dict[str, str]:
    return MARKER_STYLES.get(kind, {"color": PALETA["secundario"], "glyph": "•"})


#: Prioridad de cada tipo cuando varios sucesos caen en el mismo punto de la
#: barra: el chip agrupado muestra el icono del más importante de la pila.
KIND_PRIORITY: dict[str, int] = {
    "teamfight": 10,
    "baron": 9,
    "dragon": 8,
    "herald": 7,
    "kill": 6,
    "death": 5,
    "assist": 4,
    "tower": 3,
    "inhibitor": 2,
    "horde": 2,
    "objective": 1,
}


def kind_priority(kind: str) -> int:
    return KIND_PRIORITY.get(kind, 0)


#: Tipos cuyos chips van ARRIBA de la barra (combate: asesinatos/muertes
#: y sucesos ligados a ellos). Todo lo demás (objetivos, torres, dragones,
#: heraldo, barón/nashor, inhibidores, glóbulos/grumos...) va ABAJO.
TOP_ROW_KINDS = frozenset({"kill", "death", "assist", "teamfight"})


def chip_above(kind: str) -> bool:
    """Fila del chip según el tipo de suceso: combate arriba, resto abajo."""
    return str(kind or "").casefold() in TOP_ROW_KINDS


class MarkerSlider(QSlider):
    """Barra de progreso con los indicadores de la partida dibujados.

    Cada marcador es una rayita vertical de color; al pasar el ratón por
    encima muestra qué pasó y a qué minuto. Un clic salta directamente a
    esa posición del vídeo.
    """

    seek_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setObjectName("recordingSlider")
        self.markers: list[dict[str, Any]] = []
        self.duration_ms: int = 0
        self.show_marker_glyphs: bool = False
        self._hover_x: float | None = None
        self._scrubbing: bool = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(38)

    # -- datos ----------------------------------------------------------

    def set_show_marker_glyphs(self, value: bool) -> None:
        """Activa/desactiva los iconos sobre cada marcador."""
        self.show_marker_glyphs = bool(value)
        self.update()

    # -- datos ----------------------------------------------------------

    def set_markers(self, markers: list[dict[str, Any]], duration_ms: int) -> None:
        cleaned = []

        for marker in markers or []:
            if not isinstance(marker, dict):
                continue

            try:
                seconds = float(marker.get("time", 0))
            except (TypeError, ValueError):
                continue

            cleaned.append(
                {
                    "time": max(0.0, seconds),
                    "kind": str(marker.get("kind") or ""),
                    "label": str(marker.get("label") or "Evento"),
                    "detail": str(
                        marker.get("detail") or marker.get("label") or "Evento"
                    ),
                    "glyph": str(
                        marker.get("glyph")
                        or marker_style(str(marker.get("kind") or ""))["glyph"]
                    ),
                    # Bando beneficiado ("ally"/"enemy"): pinta el punto de
                    # la barra en verde o rojo cuando se conoce.
                    "side": str(marker.get("side") or ""),
                }
            )

        self.markers = sorted(cleaned, key=lambda item: item["time"])
        self.duration_ms = max(0, int(duration_ms or 0))
        self._hover_x = None
        self.update()

    # -- dibujo ---------------------------------------------------------

    def paintEvent(self, event: Any) -> None:  # noqa: N802 - firma de Qt
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        super().paintEvent(event)

        if not self.markers or self.duration_ms <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            self.getStyleOption(),
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if groove.height() > 0:
            groove_top = float(groove.top())
            groove_bottom = float(groove.bottom())
            center_y = groove_top + groove.height() / 2.0
        else:
            groove_top = 0.0
            groove_bottom = float(self.height())
            center_y = self.height() / 2.0

        # Cada marcador: rayita de color + punto sobre la barra. El punto se
        # pinta del color del BANDO cuando se conoce (verde = tu equipo,
        # rojo = el rival) y del color del tipo en caso contrario.
        plotted: list[tuple[float, dict[str, Any], dict[str, str]]] = []

        for marker in self.markers:
            x = self._x_for_seconds(marker["time"])

            if x is not None:
                plotted.append((float(x), marker, marker_style(marker["kind"])))

        # Línea-guía vertical bajo el chip apuntado por el ratón: conecta el
        # icono con su momento exacto de la barra.
        if self._hover_x is not None:
            guide_pen = QPen(color_con_alfa("oro_suave", 130), 2)
            painter.setPen(guide_pen)
            painter.drawLine(
                QPointF(self._hover_x, max(0.0, groove_top - 3.0)),
                QPointF(
                    self._hover_x,
                    min(float(self.height()), groove_bottom + 3.0),
                ),
            )

        # Rayitas de color cruzando la barra de lado a lado (una por suceso,
        # más visibles que antes) y punto central con el color del bando; el
        # suceso apuntado por el ratón crece y se resalta.
        pin_radius = 4.5

        for x, _marker, style in plotted:
            color = QColor(style["color"])
            tick_pen = QPen(color)
            tick_pen.setWidth(2)
            tick_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(tick_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(
                QPointF(x, groove_top + 1.0),
                QPointF(x, groove_bottom - 1.0),
            )

        for x, _marker, style in plotted:
            side = str(_marker.get("side") or "")

            if side == "ally":
                pin_color = QColor(PALETA["ventaja"])
            elif side == "enemy":
                pin_color = QColor(PALETA["desventaja"])
            else:
                pin_color = QColor(style["color"])

            hovered = self._hover_x is not None and abs(x - self._hover_x) <= 0.6
            radius = pin_radius + (2.0 if hovered else 0.0)
            ring = (
                QColor(PALETA["oro_suave"]) if hovered else QColor(PALETA["superficie"])
            )
            painter.setPen(QPen(ring, 1.6))
            painter.setBrush(QBrush(pin_color))
            painter.drawEllipse(QPointF(x, center_y), radius, radius)

        # Fila de iconos (chips) por TIPO de suceso: combate (asesinatos,
        # muertes, asistencias, peleas) ARRIBA de la barra; objetivos
        # (torres, dragones, heraldo, barón/nashor, inhibidores, glóbulos/
        # grumos...) ABAJO. Cada chip lleva su línea conectora hasta su
        # punto exacto de la barra. Los sucesos muy juntos se agrupan en
        # un solo chip con insignia «×n»; el tooltip detalla los apilados.
        chip_height = 0.0
        font: QFont | None = None

        if self.show_marker_glyphs and self.height() >= 26:
            chip_height = float(max(12, min(18, self.height() - 24)))
            font = QFont()
            font.setPixelSize(int(max(9, chip_height - 5)))
            font.setBold(True)

        if font is not None and chip_height > 0:
            painter.setFont(font)

            clusters = self._cluster_plotted(plotted)
            for cluster in clusters:
                # Fila por tipo: combate arriba, objetivos abajo. En un
                # cluster mezclado manda el tipo del marcador representante.
                above = chip_above(str(cluster["marker"].get("kind") or ""))
                x = cluster["x"]
                marker = cluster["marker"]
                style = cluster["style"]
                glyph = str(marker.get("glyph") or style["glyph"])
                color = QColor(style["color"])
                hovered = self._hover_x is not None and abs(x - self._hover_x) <= 0.6
                if above:
                    rect = QRectF(x - 10.0, 1.0, 20.0, chip_height)
                    # Conector del borde inferior del chip al punto de la barra.
                    stem_from = QPointF(x, rect.bottom())
                    stem_to = QPointF(x, max(groove_top - 1.0, rect.bottom()))
                else:
                    rect = QRectF(
                        x - 10.0,
                        float(self.height()) - chip_height - 1.0,
                        20.0,
                        chip_height,
                    )
                    # Conector del borde superior del chip al punto de la barra.
                    stem_from = QPointF(x, rect.top())
                    stem_to = QPointF(x, min(groove_bottom + 1.0, rect.top()))
                stem_pen = QPen(color)
                stem_pen.setWidth(2 if hovered else 1)
                stem_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(stem_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawLine(stem_from, stem_to)
                painter.setPen(QPen(color, 1.6 if hovered else 1.0))
                painter.setBrush(
                    QBrush(
                        QColor(
                            color.red(),
                            color.green(),
                            color.blue(),
                            150 if hovered else 70,
                        )
                    )
                )
                painter.drawRoundedRect(rect, 5.0, 5.0)
                painter.setPen(QPen(QColor(PALETA["texto"])))
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)

                if cluster["count"] > 1:
                    # Insignia con cuántos sucesos hay apilados en ese punto.
                    badge = QRectF(
                        rect.right() - 6.0,
                        rect.bottom() - 2.0,
                        11.0,
                        11.0,
                    )
                    badge.moveRight(min(badge.right(), self.width() - 1.0))
                    badge_font = QFont(font)
                    badge_font.setPixelSize(max(7, font.pixelSize() - 3))
                    painter.setFont(badge_font)
                    painter.setPen(QPen(color, 1.0))
                    painter.setBrush(QBrush(QColor(PALETA["superficie"])))
                    painter.drawEllipse(badge)
                    painter.setPen(QPen(QColor(PALETA["texto"])))
                    painter.drawText(
                        badge,
                        Qt.AlignmentFlag.AlignCenter,
                        str(cluster["count"]),
                    )
                    painter.setFont(font)

        painter.end()

    def _cluster_plotted(
        self,
        plotted: list[tuple[float, dict[str, Any], dict[str, str]]],
        min_gap_px: float = 14.0,
    ) -> list[dict[str, Any]]:
        """Junta los sucesos cuya x casi coincide en un único chip visible.

        El chip representa el suceso más importante de la pila (teamfight >
        barón > dragón > kill...); el tooltip de la barra lista todos los
        sucesos agrupados, así que no se pierde información.
        """
        clusters: list[dict[str, Any]] = []

        for x, marker, style in plotted:
            kind = str(marker.get("kind") or "")

            if clusters and abs(x - clusters[-1]["x"]) <= min_gap_px:
                cluster = clusters[-1]
                cluster["count"] += 1

                if kind_priority(kind) > kind_priority(
                    str(cluster["marker"].get("kind") or "")
                ):
                    cluster["marker"] = marker
                    cluster["style"] = style

                continue

            clusters.append({"x": x, "marker": marker, "style": style, "count": 1})

        return clusters

    def _x_for_seconds(self, seconds: float) -> int | None:
        duration = self.duration_ms / 1000.0

        if duration <= 0:
            return None

        ratio = min(1.0, max(0.0, seconds / duration))
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            self.getStyleOption(),
            QStyle.SubControl.SC_SliderGroove,
            self,
        )

        if groove.width() <= 0:
            return None

        return int(groove.left() + groove.width() * ratio)

    def getStyleOption(self):  # noqa: N802 - nombre de ayuda interno
        from PySide6.QtWidgets import QStyleOptionSlider

        option = QStyleOptionSlider()
        self.initStyleOption(option)

        return option

    # -- interacción ----------------------------------------------------

    def _seconds_at(self, x: int) -> float:
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            self.getStyleOption(),
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        width = max(1, groove.width())
        ratio = min(1.0, max(0.0, (x - groove.left()) / width))

        return ratio * (self.duration_ms / 1000.0)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._scrubbing = True
            seconds = self._seconds_at(int(event.position().x()))
            self.seek_requested.emit(int(seconds * 1000))
            event.accept()

            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        if event.button() == Qt.MouseButton.LeftButton and self._scrubbing:
            self._scrubbing = False
            seconds = self._seconds_at(int(event.position().x()))
            self.seek_requested.emit(int(seconds * 1000))
            event.accept()

            return

        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        if self._hover_x is not None:
            self._hover_x = None
            self.update()

        super().leaveEvent(event)

    def _emit_scrub(self, x: int) -> None:
        seconds = self._seconds_at(int(x))
        self.seek_requested.emit(int(seconds * 1000))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        if self._scrubbing:
            self._emit_scrub(int(event.position().x()))
        seconds = self._seconds_at(int(event.position().x()))
        hits = self._markers_at(seconds, tolerance=8.0)
        hover_x: float | None = None

        if hits:
            # El tooltip lista TODOS los sucesos del momento: en un mismo
            # punto pueden caer una muerte, dos asistencias y una torre.
            nearest = min(hits, key=lambda item: abs(item["time"] - seconds))
            hover_x = self._x_for_seconds(nearest["time"])
            lines = [
                f"{marker_style(hit['kind'])['glyph']} "
                f"{format_duration(hit['time'])} · {hit['label']} — "
                f"{hit['detail']}"
                for hit in hits
            ]
            tooltip = "\n".join(lines)

            if len(hits) > 1:
                tooltip = f"{len(hits)} sucesos en este momento:\n{tooltip}"
        else:
            tooltip = f"Saltar a {format_duration(seconds)} del vídeo"

        new_hover = float(hover_x) if hover_x is not None else None

        if new_hover != self._hover_x:
            self._hover_x = new_hover
            self.update()

        self.setToolTip(tooltip)
        super().mouseMoveEvent(event)

    def _markers_at(self, seconds: float, tolerance: float) -> list[dict[str, Any]]:
        """Todos los sucesos cercanos (tolerancia en segundos), por orden."""
        hits = [
            marker
            for marker in self.markers
            if abs(float(marker["time"]) - seconds) <= tolerance
        ]

        return sorted(hits, key=lambda marker: float(marker["time"]))


class RecordingsPage(QWidget):
    """Pestaña completa: cabecera, lista de vídeos y reproductor."""

    open_folder_requested = Signal(str)
    start_recording_requested = Signal()
    #: El usuario pulsa «Detener grabación»: la ventana cierra la sesión.
    stop_recording_requested = Signal()
    #: El usuario quiere ver la grabación en la ventana de repaso aparte.
    open_window_requested = Signal(str)
    #: La biblioteca de grabaciones cambió (nueva lista, borrado, …).
    recordings_changed = Signal()

    def __init__(
        self,
        library: RecordingLibrary,
        service: RecordingService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("recordingsPage")
        self.setStyleSheet("""
            QFrame#heroCard, QFrame#recordingPlayerCard { background:#10151e; border:1px solid #34302a; border-radius:14px; }
            QLabel#recordingsStatus { color:#afa99c; background:#151b23; border:1px solid #292f37; border-radius:7px; padding:6px 10px; }
            QLabel#recordingsStatus[state="live"] { color:#d0bb7b; border-color:#75633d; }
            QFrame#recordingStorageCard { background:#151b23; border:1px solid #373329; border-radius:10px; min-width:220px; }
            QLabel#recordingStorageValue { color:#e1dab2; font-size:18px; font-weight:700; }
            QProgressBar#recordingStorageBar { background:#242a32; border:0; border-radius:2px; }
            QProgressBar#recordingStorageBar::chunk { background:#b69a50; border-radius:2px; }
            QProgressBar#recordingStorageBar[state="warning"]::chunk { background:#d0a453; }
            QProgressBar#recordingStorageBar[state="full"]::chunk { background:#c46c61; }
            QFrame#recordingRow { background:#111720; border:1px solid #292f37; border-left:3px solid #4c535b; border-radius:11px; }
            QFrame#recordingRow[state="victory"] { border-left-color:#79af99; background:#131b1b; }
            QFrame#recordingRow[state="defeat"] { border-left-color:#ca8580; background:#1a171b; }
            QFrame#recordingRow[selected="true"] { border:1px solid #b69a50; border-left-width:3px; background:#1a1d22; }
            QFrame#recordingRow[state="victory"][selected="true"] { border-left-color:#79af99; }
            QFrame#recordingRow[state="defeat"][selected="true"] { border-left-color:#ca8580; }
            QFrame#recordingRow:hover { background:#1b222a; border-color:#75633d; }
            QLabel#recordingTitle { color:#eee8d8; font-size:16px; font-weight:700; }
            QLabel#recordingPerformanceLine { color:#d0bb7b; font-weight:600; }
            QLabel#recordingMatchIdentity { color:#d0bb7b; font-size:12px; }
            QLabel#recordingResult { font-weight:800; font-size:11px; padding:4px 8px; border-radius:6px; }
            QLabel#recordingResult[state="victory"] { color:#9bceb6; background:#1c302b; }
            QLabel#recordingResult[state="defeat"] { color:#dfa19b; background:#352326; }
            QLabel#recordingResult[state="unknown"] { color:#afa99c; background:#242a31; }
            QFrame#recordingScore { background:#201d18; border:1px solid #51452d; border-radius:8px; }
            QLabel#recordingScoreValue { color:#e1dab2; font-size:17px; font-weight:800; }
            QLabel#recordingScoreLabel { color:#afa99c; font-size:9px; font-weight:700; }
            QLabel#recordingKda { color:#eee8d8; font-size:15px; font-weight:700; }
            QLabel#recordingTeamLabel { color:#7faaa8; font-size:9px; font-weight:700; }
            QLabel#recordingTeamLabel[side="enemy"] { color:#bd8581; }
            QLabel#recordingVs { color:#d0bb7b; font-size:10px; font-weight:800; }
            QLabel#recordingTeamIcon { background:#172329; border:1px solid #416665; border-radius:5px; }
            QLabel#recordingTeamIcon[side="enemy"] { background:#281d20; border-color:#704b4b; }
            QLabel#recordingTeamIcon[own="true"] { border:2px solid #d0bb7b; }
            QPushButton#recordingAction { min-height:24px; padding:2px 9px; border-radius:6px; background:#202630; border:1px solid #343a42; color:#e1dab2; }
            QPushButton#recordingAction:hover { background:#292f37; border-color:#75633d; }
            QPushButton#recordingAction[kind="danger"] { color:#dfa19b; }
            QLabel#recordingMeta { color:#898f98; font-size:10px; }
            QLabel#recordingMatchDetail { color:#afa99c; font-size:10px; }
            QLabel#recordingKdaCaption { color:#898f98; font-size:9px; font-weight:700; }
            QWidget#recordingIdentity, QWidget#recordingPerformance, QWidget#recordingTeams { background:transparent; }
            QFrame#recordingPortraitFrame { background:#111720; border:1px solid #75633d; border-radius:9px; }
            QFrame#recordingRow[state="victory"] QFrame#recordingPortraitFrame { border-color:#456d5e; }
            QFrame#recordingRow[state="defeat"] QFrame#recordingPortraitFrame { border-color:#714746; }
            QFrame#recordingRow[selected="true"] QFrame#recordingPortraitFrame { border-color:#d0bb7b; }
            QFrame#recordingPlaybackStrip { background:#111720; border:1px solid #292f37; border-radius:10px; }
            QFrame#recordingEventLegend { background:#151b23; border:1px solid #292f37; border-radius:8px; }
            QFrame#recordingEventChip { background:#1b222b; border:1px solid #303640; border-radius:6px; }
            QLabel#recordingEventGlyph { font-size:12px; font-weight:700; }
            QLabel#recordingEventName { color:#b9b4a8; font-size:10px; }
            QListWidget#recordingMarkerList { background:#0d1219; border:1px solid #292f37; border-radius:8px; padding:4px; outline:0; }
            QListWidget#recordingMarkerList::item { color:#d8d2c3; padding:6px 8px; border-radius:5px; border-bottom:1px solid #20262e; }
            QListWidget#recordingMarkerList::item:hover { background:#1a222a; color:#eee8d8; }
            QListWidget#recordingMarkerList::item:selected { background:#29251e; color:#e1dab2; border:1px solid #544326; }
            QSlider#recordingSlider::groove:horizontal { height:6px; background:#252b33; border-radius:3px; margin:17px 8px; }
            QSlider#recordingSlider::sub-page:horizontal { background:#b69a50; border-radius:3px; }
            QSlider#recordingSlider::handle:horizontal { width:14px; height:14px; margin:-5px 0; background:#e1dab2; border:2px solid #b69a50; border-radius:7px; }
            QSlider#recordingSlider::handle:horizontal:hover { background:#ffffff; border-color:#d0bb7b; }
            QPushButton#recordingPlayButton { background:#1b222b; border:1px solid #343a42; border-radius:7px; color:#e1dab2; padding:5px 10px; min-height:25px; }
            QPushButton#recordingPlayButton:hover { background:#29251e; border-color:#75633d; }
            QPushButton#recordingPlayButton:disabled { color:#78818e; }
            QLineEdit, QComboBox { background:#10151e; border:1px solid #343a42; border-radius:8px; padding:7px; color:#eee8d8; }
        """)
        self.library = library
        self.service = service
        self.entries: list[dict[str, Any]] = []
        self._recording_cards: dict[str, QFrame] = {}
        self.current_path: Path | None = None
        self.current_saved_match: dict[str, Any] = {}
        self.pending_seek_ms: int = 0
        #: Lectura de la carpeta en curso (worker) y refresco pedido mientras
        #: tanto: la lista se lee en segundo plano y se pinta al llegar.
        self._scan_task: Any = None
        self._scan_pending = False
        #: Peso de la carpeta cacheado unos segundos: ``_sync_recording_status``
        #: lo pide en cada refresco y una vez por segundo mientras se graba.
        self._folder_size_cache: tuple[float, int] | None = None

        self._build_layout()
        self._build_player()
        self._install_playback_shortcuts()
        self._wire_service()

    # -- construcción ---------------------------------------------------

    def _build_layout(self) -> None:
        """Construye la presentación con los parámetros recibidos y devuelve el resultado existente."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())

        self.status_label = QLabel("Cargando biblioteca…")
        self.status_label.setObjectName("recordingsStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        body = QHBoxLayout()
        body.setSpacing(12)

        body.addWidget(self._build_list_column(), 5)
        body.addWidget(self._build_player_card(), 8)

        layout.addLayout(body, 1)
        self.reflujo = Reflujo(self, [body], 930)

    def _build_header(self) -> QWidget:
        """Construye cabecera, controles y resumen de almacenamiento."""
        header = QFrame()
        header.setObjectName("heroCard")

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        header_layout.setSpacing(18)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        eyebrow = QLabel("PARTIDAS LOCALES")
        eyebrow.setObjectName("eyebrow")
        text_layout.addWidget(eyebrow)

        title = QLabel("Grabaciones")
        title.setObjectName("heroTitle")
        text_layout.addWidget(title)

        description = QLabel(
            "Tus partidas, momentos clave y repeticiones en un solo lugar."
        )
        description.setObjectName("heroText")
        description.setWordWrap(True)
        text_layout.addWidget(description)

        header_layout.addLayout(text_layout, 1)

        storage = QFrame()
        storage.setObjectName("recordingStorageCard")
        storage_layout = QVBoxLayout(storage)
        storage_layout.setContentsMargins(14, 10, 14, 10)
        storage_layout.setSpacing(4)
        self.storage_title = QLabel("ALMACENAMIENTO")
        self.storage_title.setObjectName("eyebrow")
        storage_layout.addWidget(self.storage_title)
        self.storage_value = QLabel("Calculando…")
        self.storage_value.setObjectName("recordingStorageValue")
        storage_layout.addWidget(self.storage_value)
        self.storage_detail = QLabel("")
        self.storage_detail.setObjectName("recordingDetail")
        storage_layout.addWidget(self.storage_detail)
        self.storage_bar = QProgressBar()
        self.storage_bar.setObjectName("recordingStorageBar")
        self.storage_bar.setTextVisible(False)
        self.storage_bar.setFixedHeight(5)
        storage_layout.addWidget(self.storage_bar)
        header_layout.addWidget(storage, 0)

        buttons = QVBoxLayout()
        buttons.setSpacing(6)

        self.start_button = QPushButton("▶ Iniciar grabación")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setToolTip(
            "Inicia una grabación de la ventana de League of Legends."
        )
        self.start_button.clicked.connect(
            lambda _checked=False: self.start_recording_requested.emit()
        )
        buttons.addWidget(self.start_button)

        self.stop_button = QPushButton("⏹ Detener grabación")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setToolTip(
            "Cierra la grabación en curso y guarda el vídeo de la partida."
        )
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(
            lambda _checked=False: self.stop_recording_requested.emit()
        )
        buttons.addWidget(self.stop_button)

        self.refresh_button = QPushButton("↻ Actualizar")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)

        self.folder_button = QPushButton("Abrir carpeta")
        self.folder_button.setObjectName("secondaryButton")
        self.folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.folder_button)

        self.settings_button = QPushButton("⚙ Ajustes")
        self.settings_button.setObjectName("secondaryButton")
        self.settings_button.clicked.connect(lambda: self._open_recording_settings())
        buttons.addWidget(self.settings_button)
        header_layout.addLayout(buttons)

        return header

    def _build_list_column(self) -> QWidget:
        """Construye la biblioteca con búsqueda, filtros y lista desplazable."""
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        caption = QLabel("BIBLIOTECA DE PARTIDAS")
        caption.setObjectName("eyebrow")
        container_layout.addWidget(caption)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar campeón o modo…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._rebuild_rows)
        container_layout.addWidget(self.search_input)
        filters = QHBoxLayout()
        self.result_filter = QComboBox()
        self.result_filter.addItems(["Todos los resultados", "Victoria", "Derrota"])
        self.sort_filter = QComboBox()
        self.sort_filter.addItems(
            [
                "Más recientes",
                "Más antiguas",
                "Mayor BattleScore",
                "Partidas largas",
                "Archivos grandes",
            ]
        )
        self.metadata_filter = QComboBox()
        self.metadata_filter.addItems(["Todas", "Con BattleScore", "Con eventos"])
        self.date_filter = QComboBox()
        self.date_filter.addItems(
            ["Cualquier fecha", "Últimos 7 días", "Últimos 30 días"]
        )
        self.result_filter.currentIndexChanged.connect(self._rebuild_rows)
        self.sort_filter.currentIndexChanged.connect(self._rebuild_rows)
        self.metadata_filter.currentIndexChanged.connect(self._rebuild_rows)
        self.date_filter.currentIndexChanged.connect(self._rebuild_rows)
        filters.addWidget(self.result_filter, 1)
        filters.addWidget(self.sort_filter, 1)
        container_layout.addLayout(filters)
        filtros_secundarios = QHBoxLayout()
        filtros_secundarios.addWidget(self.metadata_filter, 1)
        filtros_secundarios.addWidget(self.date_filter, 1)
        container_layout.addLayout(filtros_secundarios)

        scroll = QScrollArea()
        scroll.setObjectName("recordingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.list_content = QWidget()
        self.list_content.setObjectName("recordingsContent")
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)

        scroll.setWidget(self.list_content)
        container_layout.addWidget(scroll, 1)

        return container

    def _build_player_card(self) -> QWidget:
        """Construye el reproductor, sus controles y la navegación por eventos."""
        card = QFrame()
        card.setObjectName("recordingPlayerCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        self.player_title = QLabel("Elige una grabación de la lista")
        self.player_title.setObjectName("recordingPlayerTitle")
        self.player_title.setWordWrap(True)
        title_row.addWidget(self.player_title, 1)
        self.player_result = QLabel("SIN PARTIDA")
        self.player_result.setObjectName("recordingResult")
        self.player_result.setProperty("state", "unknown")
        title_row.addWidget(self.player_result)
        self.player_date = QLabel("")
        self.player_date.setObjectName("recordingMeta")
        title_row.addWidget(self.player_date)
        self.player_score = QLabel("")
        self.player_score.setObjectName("recordingMatchIdentity")
        title_row.addWidget(self.player_score)
        layout.addLayout(title_row)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("recordingVideo")
        self.video_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Un mínimo alto (320) impedía que la tarjeta cupiera en pantallas
        # de poca altura (1600x900: la página no cabía y el reproductor se
        # salía de su hueco). El vídeo crece con el stretch: solo necesita
        # un suelo pequeño para seguir siendo usable.
        self.video_widget.setMinimumHeight(180)
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.video_widget, 1)

        self.position_slider = MarkerSlider()
        self.position_slider.setRange(0, 0)
        self.position_slider.seek_requested.connect(self.seek_to_ms)
        playback_strip = QFrame()
        playback_strip.setObjectName("recordingPlaybackStrip")
        playback_layout = QVBoxLayout(playback_strip)
        playback_layout.setContentsMargins(10, 3, 10, 8)
        playback_layout.setSpacing(3)
        playback_layout.addWidget(self.position_slider)

        controls = QHBoxLayout()
        controls.setSpacing(6)

        self.position_label = QLabel("00:00 / 00:00")
        self.position_label.setObjectName("recordingPlayerTime")
        controls.addWidget(self.position_label)
        controls.addSpacing(8)

        self.back_button = QPushButton(f"⏪ {SEEK_SECONDS}s")
        self.back_button.setObjectName("recordingPlayButton")
        self.back_button.setToolTip("Retroceder 10 segundos · ← retrocede 5 segundos")
        self.back_button.clicked.connect(self.seek_backward)
        controls.addWidget(self.back_button)

        self.play_button = QPushButton("▶ Reproducir")
        self.play_button.setObjectName("recordingPlayButton")
        self.play_button.setToolTip("Reproducir / pausar · Espacio")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)

        self.forward_button = QPushButton(f"{SEEK_SECONDS}s ⏩")
        self.forward_button.setObjectName("recordingPlayButton")
        self.forward_button.setToolTip("Avanzar 10 segundos · → avanza 5 segundos")
        self.forward_button.clicked.connect(self.seek_forward)
        controls.addWidget(self.forward_button)

        controls.addStretch(1)

        volume_caption = QLabel("Volumen")
        volume_caption.setObjectName("mutedText")
        controls.addWidget(volume_caption)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("recordingVolume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.valueChanged.connect(self._apply_volume)
        controls.addWidget(self.volume_slider)

        self.marker_count_label = QLabel("")
        self.marker_count_label.setObjectName("recordingMarkerLegend")
        self.marker_count_label.setWordWrap(False)
        controls.addSpacing(10)
        controls.addWidget(self.marker_count_label)

        playback_layout.addLayout(controls)
        layout.addWidget(playback_strip)

        legend = QFrame()
        legend.setObjectName("recordingEventLegend")
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(8, 5, 8, 5)
        legend_layout.setSpacing(6)
        event_names = {
            "kill": "Baja",
            "death": "Muerte",
            "assist": "Asistencia",
            "dragon": "Dragón",
            "herald": "Heraldo",
            "baron": "Barón",
            "tower": "Torre",
            "inhibitor": "Inhibidor",
        }
        for kind, name in event_names.items():
            style = marker_style(kind)
            chip = QFrame()
            chip.setObjectName("recordingEventChip")
            chip_layout = QHBoxLayout(chip)
            chip_layout.setContentsMargins(5, 2, 6, 2)
            chip_layout.setSpacing(4)
            glyph = QLabel(style["glyph"])
            glyph.setObjectName("recordingEventGlyph")
            glyph.setStyleSheet(f"color:{style['color']};")
            label = QLabel(name)
            label.setObjectName("recordingEventName")
            chip_layout.addWidget(glyph)
            chip_layout.addWidget(label)
            legend_layout.addWidget(chip)
        legend_layout.addStretch(1)
        layout.addWidget(legend)

        event_heading = QHBoxLayout()
        heading = QLabel("MOMENTOS CLAVE")
        heading.setObjectName("eyebrow")
        event_heading.addWidget(heading)
        event_heading.addStretch(1)
        hint = QLabel("Selecciona un evento para saltar a ese instante")
        hint.setObjectName("recordingMeta")
        event_heading.addWidget(hint)
        layout.addLayout(event_heading)

        self.marker_list = QListWidget()
        self.marker_list.setObjectName("recordingMarkerList")
        self.marker_list.setMaximumHeight(118)
        self.marker_list.setSpacing(2)
        self.marker_list.setUniformItemSizes(True)
        self.marker_list.itemClicked.connect(self._jump_to_marker_item)
        layout.addWidget(self.marker_list)

        return card

    def _build_player(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.8)
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget)
        self.player.playbackStateChanged.connect(self._sync_play_button)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self.player.errorOccurred.connect(self._on_player_error)

        self.recording_tick = QTimer(self)
        self.recording_tick.setInterval(1000)
        self.recording_tick.timeout.connect(self._sync_recording_status)

    def _install_playback_shortcuts(self) -> None:
        """Instala atajos limitados a la página de grabaciones.

        Returns:
            None.
        """
        acciones: tuple[tuple[str, Callable[[], None]], ...] = (
            ("Space", self.toggle_play),
            ("Left", lambda: self.seek_by_ms(-KEYBOARD_SEEK_MS)),
            ("Right", lambda: self.seek_by_ms(KEYBOARD_SEEK_MS)),
        )
        self._playback_shortcuts: list[QShortcut] = []
        shortcut_parent = self.video_widget.parentWidget() or self

        for sequence, action in acciones:
            shortcut = QShortcut(QKeySequence(sequence), shortcut_parent)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda accion=action: self._run_playback_shortcut(accion)
            )
            self._playback_shortcuts.append(shortcut)

    def _run_playback_shortcut(self, action: Callable[[], None]) -> None:
        """Evita que los atajos de vídeo interfieran con campos editables.

        Args:
            action: Acción de reproducción que se ejecutará.

        Returns:
            None.
        """
        focused = QApplication.focusWidget()

        if isinstance(
            focused, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)
        ):
            return

        if isinstance(focused, QComboBox) and focused.isEditable():
            return

        action()

    def seek_by_ms(self, offset_ms: int) -> None:
        """Busca un desplazamiento relativo y lo limita al vídeo conocido.

        Args:
            offset_ms: Desplazamiento solicitado en milisegundos.

        Returns:
            None.
        """
        if self.current_path is None:
            return

        duration = int(self.player.duration())
        target = max(0, int(self.player.position()) + int(offset_ms))

        if duration > 0:
            target = min(target, duration)

        self.seek_to_ms(target)

    def _wire_service(self) -> None:
        self.service.started.connect(self._on_service_started)
        self.service.finished.connect(self._on_service_finished)
        self.service.failed.connect(self._on_service_failed)
        self.service.state_changed.connect(self._on_service_state)

    # -- lista de grabaciones -------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Pide la lista de grabaciones y reconstruye las filas al llegar.

        ``list_recordings`` recorre la carpeta y lee un sidecar JSON por
        vídeo; en una biblioteca grande eso bloquea la interfaz, así que se
        hace en un worker. El estado «Cargando grabaciones…» se ve de
        inmediato y la lista se pinta cuando el worker responde.

        Si ya hay una lectura en curso se marca otra pendiente en vez de
        encolar varias: el usuario puede pulsar el botón mientras la carpeta
        se está leyendo (o hacerlo la propia ventana al mostrar la pestaña).
        """
        if self._scan_task is not None:
            self._scan_pending = True

            return

        self.status_label.setText("Cargando grabaciones…")
        self.refresh_button.setEnabled(False)

        self._scan_task = run_async(
            self.library.list_recordings,
            on_finished=self._apply_entries,
        )

    def _apply_entries(self, _token, entries, error) -> None:
        """Publica en el hilo de la GUI la lista que leyó el worker."""
        self._scan_task = None
        self.refresh_button.setEnabled(True)

        if error:
            # Sin lista nueva la interfaz sigue usable: solo se informa.
            self.status_label.setText(f"No se pudieron leer las grabaciones: {error}")
        else:
            self.entries = list(entries or [])
            self._attach_saved_match_data()
            # La carpeta puede haber cambiado: el peso mostrado se relee.
            self._folder_size_cache = None
            self._rebuild_rows()

        if self._scan_pending:
            self._scan_pending = False
            self.refresh()

    def _attach_saved_match_data(self) -> None:
        """Enriquece grabaciones solo mediante el session_id exacto del sidecar."""
        window = self.window()
        sessions = getattr(window, "saved_live_sessions", [])
        by_id = {
            str(session.get("session_id")): session
            for session in sessions
            if isinstance(session, dict) and session.get("session_id")
        }
        for entry in self.entries:
            metadata = (
                entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            )
            session_id = str(metadata.get("session_id") or "")
            session = by_id.get(session_id)
            if not session:
                continue
            players = (
                session.get("players")
                if isinstance(session.get("players"), dict)
                else {}
            )
            local_key = str(session.get("local_player_key") or "")
            local = players.get(local_key) if local_key else None
            final = (
                session.get("final_scoreboard")
                if isinstance(session.get("final_scoreboard"), dict)
                else {}
            )
            stats = final.get(local_key) if local_key else None
            stats = stats if isinstance(stats, dict) else {}
            score = None
            saved_score = session.get("performance_scoring")
            if (
                isinstance(saved_score, dict)
                and saved_score.get("state") == "POSTGAME_FINAL"
            ):
                score = next(
                    (
                        item.get("total")
                        for item in saved_score.get("players", [])
                        if isinstance(item, dict)
                        and str(item.get("participant_id") or "") == local_key
                    ),
                    None,
                )
            role_order = {"TOP": 0, "JUNGLE": 1, "MIDDLE": 2, "BOTTOM": 3, "UTILITY": 4}
            compositions: dict[str, list[dict[str, Any]]] = {"ally": [], "enemy": []}
            for player_key, player in players.items():
                if (
                    not isinstance(player, dict)
                    or player.get("side") not in compositions
                    or not player.get("champion_name")
                ):
                    continue
                compositions[str(player["side"])].append(
                    {
                        "champion": str(player["champion_name"]),
                        "name": str(
                            player.get("riot_id") or player.get("summoner_name") or ""
                        ),
                        "role": str(player.get("role") or ""),
                        "own": bool(
                            player.get("is_local_player")
                            or str(player_key) == local_key
                        ),
                    }
                )
            for team in compositions.values():
                team.sort(key=lambda player: role_order.get(player["role"], 5))
            entry["saved_match"] = {
                "win": stats.get(
                    "win", local.get("win") if isinstance(local, dict) else None
                ),
                "role": local.get("role") if isinstance(local, dict) else None,
                "riot_id": local.get("riot_id")
                if isinstance(local, dict)
                else session.get("player_riot_id"),
                "kda": [stats.get("kills"), stats.get("deaths"), stats.get("assists")]
                if all(
                    isinstance(stats.get(key), (int, float))
                    for key in ("kills", "deaths", "assists")
                )
                else None,
                "battle_score": score,
                "composition": compositions if any(compositions.values()) else None,
            }

    def _rebuild_rows(self) -> None:
        """Reconstruye las filas sin tocar lo que se esté reproduciendo."""
        self._recording_cards.clear()
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        entries = self._filtered_entries()
        if not entries:
            empty = QLabel(
                "No hay partidas que coincidan. Prueba a cambiar la búsqueda o los filtros."
            )
            empty.setObjectName("recordingsEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.list_layout.addWidget(empty)
        else:
            for entry in entries:
                self.list_layout.addWidget(self._build_entry_row(entry))

        self.list_layout.addStretch(1)
        self._sync_recording_status()

        # La biblioteca cambió: la pestaña «Partidas guardadas» debe
        # reconstruirse para mostrar/ocultar «Repaso con vídeo» según
        # exista la grabación asociada a cada partida.
        self.recordings_changed.emit()

    def _build_entry_row(self, entry: dict[str, Any]) -> QWidget:
        """Construye una tarjeta horizontal compacta con datos disponibles.

        Parámetros: entry contiene metadatos de grabación y partida.
        Retorno: tarjeta Qt con selección, reproducción y acciones existentes.
        """
        path = entry.get("path")
        row = QFrame()
        row.setObjectName("recordingRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        match = (
            entry.get("saved_match")
            if isinstance(entry.get("saved_match"), dict)
            else {}
        )
        result_state = (
            "victory"
            if match.get("win") is True
            else "defeat"
            if match.get("win") is False
            else "unknown"
        )
        row.setProperty("state", result_state)
        row.setProperty("selected", str(self.current_path == Path(path)).lower())
        self._recording_cards[str(path)] = row

        layout = QVBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(8)

        identity = QWidget()
        identity.setObjectName("recordingIdentity")
        identity_layout = QHBoxLayout(identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        identity_layout.setSpacing(7)

        portrait_frame = QFrame()
        portrait_frame.setObjectName("recordingPortraitFrame")
        portrait_frame.setFixedSize(50, 50)
        portrait_layout = QVBoxLayout(portrait_frame)
        portrait_layout.setContentsMargins(2, 2, 2, 2)
        portrait = QLabel("◈")
        portrait.setObjectName("recordingChampionPortrait")
        portrait.setFixedSize(44, 44)
        portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        portrait.setStyleSheet(
            "background:#1a2029; border-radius:6px; color:#b69a50; font-size:20px;"
        )
        portrait_layout.addWidget(portrait)
        identity_layout.addWidget(portrait_frame)

        title = QLabel(
            str(
                entry.get("champion") or entry.get("title") or "Partida grabada"
            ).upper()
        )
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("recordingTitle")
        title.setWordWrap(False)
        identity_text = QVBoxLayout()
        identity_text.setContentsMargins(0, 0, 0, 0)
        identity_text.setSpacing(1)
        identity_text.addWidget(title)

        player_name = str(match.get("riot_id") or "")
        if player_name:
            player = QLabel(player_name)
            player.setObjectName("recordingMeta")
            player.setWordWrap(False)
            identity_text.addWidget(player)
        else:
            player = QLabel("Jugador")
            player.setObjectName("recordingMeta")
            identity_text.addWidget(player)
        identity_layout.addLayout(identity_text)
        main_row.addWidget(identity, 2)

        performance = QVBoxLayout()
        performance.setContentsMargins(0, 0, 0, 0)
        performance.setSpacing(1)
        kda = match.get("kda")
        kda_label = QLabel()
        kda_label.setObjectName("recordingKda")
        if isinstance(kda, (list, tuple)) and len(kda) == 3:
            kda_label.setText(
                f"{kda[0]}  /  <span style='color:#ca8580'>{kda[1]}</span>  /  {kda[2]}"
            )
            kda_label.setTextFormat(Qt.TextFormat.RichText)
            kda_label.setToolTip("Asesinatos / Muertes / Asistencias")
        else:
            kda_label.setText("KDA —")
        performance.addWidget(kda_label)
        score = self._battle_score(match)
        score_line = QLabel(
            f"<span style='color:#898f98;font-size:9px'>BATTLESCORE</span>  "
            f"<span style='color:#e1dab2;font-weight:800'>{score if isinstance(score, (int, float)) else '—'}</span>"
        )
        score_line.setTextFormat(Qt.TextFormat.RichText)
        score_line.setToolTip("Puntuación final guardada por Solralol")
        performance.addWidget(score_line)
        main_row.addLayout(performance, 1)

        match_column = QVBoxLayout()
        match_column.setContentsMargins(0, 0, 0, 0)
        match_column.setSpacing(2)
        role = str(match.get("role") or "")
        detail = QLabel(
            f"{role + '  ·  ' if role else ''}{entry.get('game_mode') or 'Modo no disponible'}  ·  {entry.get('duration_label', '')}"
        )
        detail.setObjectName("recordingMatchDetail")
        detail.setWordWrap(False)
        match_column.addWidget(detail)
        badge = QLabel(
            "VICTORIA"
            if match.get("win") is True
            else "DERROTA"
            if match.get("win") is False
            else "SIN RESULTADO"
        )
        badge.setObjectName("recordingResult")
        badge.setProperty("state", result_state)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        champion = str(entry.get("champion") or "")
        if champion:
            run_async(
                lambda name=champion: self._champion_icon_bytes(name),
                token=(portrait, 44),
                on_finished=self._apply_champion_icon,
            )

        comp = match.get("composition")
        if isinstance(comp, dict) and (comp.get("ally") or comp.get("enemy")):
            matchup = QWidget()
            matchup.setObjectName("recordingMatchup")
            matchup.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            teams = QHBoxLayout(matchup)
            teams.setContentsMargins(0, 0, 0, 0)
            teams.setSpacing(2)
            for side in ("ally", "enemy"):
                team = comp.get(side) if isinstance(comp.get(side), list) else []
                for index in range(5):
                    participant = team[index] if index < len(team) else None
                    icon = QLabel("·")
                    icon.setObjectName("recordingTeamIcon")
                    icon.setProperty("side", side)
                    icon.setProperty(
                        "own", str(bool(participant and participant.get("own"))).lower()
                    )
                    icon.setFixedSize(20, 20)
                    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    if participant:
                        champion_name = str(participant.get("champion") or "")
                        tooltip = champion_name
                        if participant.get("name"):
                            tooltip += f" · {participant['name']}"
                        icon.setToolTip(tooltip)
                        if champion_name:
                            run_async(
                                lambda name=champion_name: self._champion_icon_bytes(
                                    name
                                ),
                                token=(icon, 20),
                                on_finished=self._apply_champion_icon,
                            )
                    if side == "enemy" and index == 0:
                        teams.addSpacing(4)
                    teams.addWidget(icon)
                if side == "ally":
                    vs = QLabel("VS")
                    vs.setObjectName("recordingVs")
                    vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    teams.addWidget(vs)
                    teams.addSpacing(2)
            match_column.addWidget(matchup, 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            unavailable = QLabel("Composición no disponible")
            unavailable.setObjectName("recordingMeta")
            match_column.addWidget(unavailable)
        main_row.addLayout(match_column, 5)
        main_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(main_row)

        subtitle = f"{entry.get('date_label', '')}  ·  {entry.get('size_label', '')}"
        summary = str(entry.get("summary") or "")
        actions = QHBoxLayout()
        footer = QLabel(subtitle)
        footer.setObjectName("recordingMeta")
        if summary:
            footer.setToolTip(f"Momentos detectados: {summary}")
        actions.addWidget(footer, 1)
        ver = QPushButton("▶ Ver")
        ver.setObjectName("recordingAction")
        ver.setProperty("class", "secondaryButton")
        ver.clicked.connect(lambda _checked=False, value=path: self.play_entry(value))
        ventana = QPushButton("↗ Repaso")
        ventana.setObjectName("recordingAction")
        ventana.setToolTip("Abrir esta partida en la ventana de repaso")
        ventana.clicked.connect(
            lambda _checked=False, value=path: self.open_window_requested.emit(
                str(value)
            )
        )
        eliminar = QPushButton("Eliminar")
        eliminar.setObjectName("recordingAction")
        eliminar.setProperty("kind", "danger")
        eliminar.clicked.connect(
            lambda _checked=False, value=path: self.delete_entry(value)
        )
        actions.addWidget(ver)
        actions.addWidget(ventana)
        actions.addWidget(eliminar)
        layout.addLayout(actions)

        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.mousePressEvent = lambda event, value=path: self.play_entry(value)

        return row

    @staticmethod
    def _champion_icon_bytes(champion: str) -> bytes:
        """Lee desde caché local el icono Data Dragon del campeón."""
        from data_dragon import get_champion_icon_path

        path = get_champion_icon_path(champion, "", download=False)
        return path.read_bytes() if path and path.is_file() else b""

    @staticmethod
    def _apply_champion_icon(token: Any, content: bytes, error: str | None) -> None:
        """Presenta un retrato recibido del worker si la tarjeta sigue viva."""
        if error or not content:
            return
        label, size = token if isinstance(token, tuple) else (token, 64)
        try:
            image = QImage.fromData(content)
            if not image.isNull():
                label.setText("")
                label.setPixmap(
                    QPixmap.fromImage(image).scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        except RuntimeError:
            return

    @staticmethod
    def _battle_score(saved_match: Any) -> int | None:
        """Normaliza el BattleScore canónico y distingue ausencia de cero."""
        if not isinstance(saved_match, dict):
            if saved_match is not None:
                logger.warning(
                    "Metadatos saved_match no válidos al leer BattleScore: %s",
                    type(saved_match).__name__,
                )
            return None
        raw_score = saved_match.get("battle_score")
        if raw_score is None or raw_score == "":
            return None
        try:
            if isinstance(raw_score, bool):
                raise ValueError("booleano no válido como BattleScore")
            if isinstance(raw_score, int):
                score = raw_score
            elif (
                isinstance(raw_score, float)
                and math.isfinite(raw_score)
                and raw_score.is_integer()
            ):
                score = int(raw_score)
            elif isinstance(raw_score, str):
                score = int(raw_score.strip())
            else:
                raise ValueError("tipo de BattleScore no válido")
        except (TypeError, ValueError, OverflowError) as error:
            logger.warning("BattleScore no válido (%r): %s", raw_score, error)
            return None
        if score < 0:
            logger.warning("BattleScore negativo descartado: %r", raw_score)
            return None
        return score

    @staticmethod
    def _sort_timestamp(entry: dict[str, Any]) -> float | None:
        """Devuelve una fecha numérica válida para ordenar una grabación."""
        raw_value = entry.get("created_at")
        if isinstance(raw_value, bool) or raw_value is None:
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if math.isfinite(value) else None

    @staticmethod
    def _sort_number(entry: dict[str, Any], field: str) -> float | None:
        """Normaliza duración o tamaño sin propagar datos mal formados."""
        raw_value = entry.get(field)
        if isinstance(raw_value, bool) or raw_value is None:
            return None
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if math.isfinite(value) and value >= 0 else None

    @classmethod
    def _sort_recording_entries(
        cls, entries: list[dict[str, Any]], mode: int
    ) -> list[dict[str, Any]]:
        """Ordena de forma estable y mantiene al final los valores ausentes."""
        ordered = list(entries)

        def name_key(entry: dict[str, Any]) -> tuple[str, str]:
            """Crea un desempate estable por nombre y ruta de archivo."""
            name = str(entry.get("name") or entry.get("title") or "").casefold()
            path = str(entry.get("path") or "").casefold()
            return name, path

        def fecha_reciente(entry: dict[str, Any]) -> tuple[bool, float, str, str]:
            """Ordena fechas recientes primero y deja fechas ausentes al final."""
            timestamp = cls._sort_timestamp(entry)
            name, path = name_key(entry)
            return timestamp is None, -(timestamp or 0.0), name, path

        def score_key(
            entry: dict[str, Any],
        ) -> tuple[bool, int, bool, float, str, str]:
            """Ordena scores válidos y después fecha y nombre de grabación."""
            saved_match = entry.get("saved_match")
            score = cls._battle_score(saved_match)
            timestamp = cls._sort_timestamp(entry)
            name, path = name_key(entry)
            return (
                score is None,
                -(score if score is not None else 0),
                timestamp is None,
                -(timestamp or 0.0),
                name,
                path,
            )

        def numero_key(
            entry: dict[str, Any], field: str
        ) -> tuple[bool, float, bool, float, str, str]:
            """Ordena un valor numérico y conserva un desempate reproducible."""
            value = cls._sort_number(entry, field)
            timestamp = cls._sort_timestamp(entry)
            name, path = name_key(entry)
            return (
                value is None,
                -(value if value is not None else 0.0),
                timestamp is None,
                -(timestamp or 0.0),
                name,
                path,
            )

        try:
            if mode == 1:
                ordered.sort(
                    key=lambda entry: (
                        cls._sort_timestamp(entry) is None,
                        cls._sort_timestamp(entry) or 0.0,
                        *name_key(entry),
                    )
                )
            elif mode == 2:
                ordered.sort(key=score_key)
            elif mode == 3:
                ordered.sort(key=lambda entry: numero_key(entry, "duration"))
            elif mode == 4:
                ordered.sort(key=lambda entry: numero_key(entry, "size_bytes"))
            else:
                ordered.sort(key=fecha_reciente)
        except Exception:
            logger.exception(
                "Falló la ordenación de grabaciones (modo %s); se usará fecha reciente",
                mode,
            )
            try:
                ordered.sort(key=fecha_reciente)
            except Exception:
                logger.exception(
                    "Falló también el orden seguro; se conserva el orden recibido"
                )
                return list(entries)
        return ordered

    def _filtered_entries(self) -> list[dict[str, Any]]:
        """Filtra y ordena la biblioteca con metadatos ya cargados."""
        entries = list(self.entries)
        needle = (
            self.search_input.text().strip().casefold()
            if hasattr(self, "search_input")
            else ""
        )
        if needle:
            entries = [
                entry
                for entry in entries
                if needle
                in " ".join(
                    (
                        str(entry.get("title", "")),
                        str(entry.get("champion", "")),
                        str(entry.get("game_mode", "")),
                        str(entry.get("summary", "")),
                    )
                ).casefold()
            ]
        result = (
            self.result_filter.currentIndex() if hasattr(self, "result_filter") else 0
        )
        if result in (1, 2):
            wanted = result == 1
            entries = [
                entry
                for entry in entries
                if (
                    entry.get("saved_match", {}).get("win")
                    if isinstance(entry.get("saved_match"), dict)
                    else None
                )
                is wanted
            ]
        metadata_filter = (
            self.metadata_filter.currentIndex()
            if hasattr(self, "metadata_filter")
            else 0
        )
        if metadata_filter == 1:
            entries = [
                entry
                for entry in entries
                if self._battle_score(entry.get("saved_match")) is not None
            ]
        elif metadata_filter == 2:
            entries = [entry for entry in entries if bool(entry.get("markers"))]
        date_filter = (
            self.date_filter.currentIndex() if hasattr(self, "date_filter") else 0
        )
        if date_filter in (1, 2):
            cutoff = time.time() - (7 if date_filter == 1 else 30) * 86400
            entries = [
                entry
                for entry in entries
                if (self._sort_timestamp(entry) or 0.0) >= cutoff
            ]
        sort = self.sort_filter.currentIndex() if hasattr(self, "sort_filter") else 0
        return self._sort_recording_entries(entries, sort)

    def _open_recording_settings(self) -> None:
        """Abre la sección de ajustes de grabación de la ventana principal."""
        window = self.window()
        if hasattr(window, "settings_button"):
            window.settings_button.click()
            tabs = window.findChild(QWidget, "settingsTabs")
            if tabs is not None:
                tabs.setCurrentIndex(2)

    def _update_storage_overview(self, total: int) -> None:
        """Actualiza ocupación y capacidad configurada de las grabaciones."""
        from app.services.recording_service import format_size

        settings = getattr(self.window(), "settings", {})
        limit = (
            settings.get("recording_size_limit_gb")
            if isinstance(settings, dict)
            else None
        )
        try:
            limit_gb = float(limit)
        except (TypeError, ValueError):
            limit_gb = None
        if limit_gb is None or limit_gb <= 0:
            self.storage_value.setText(f"{format_size(total)} / Límite no disponible")
            self.storage_detail.setText(
                f"{len(self.entries)} grabaciones · configuración no disponible"
            )
            self.storage_bar.setRange(0, 0)
            return
        capacity = int(limit_gb * 1024**3)
        percent = min(100, round(total * 100 / capacity)) if capacity else 0
        remaining = max(0, capacity - total)
        self.storage_value.setText(f"{format_size(total)} / {limit_gb:g} GB")
        self.storage_detail.setText(
            f"{len(self.entries)} partidas · {percent}% usado · {format_size(remaining)} disponibles"
        )
        self.storage_bar.setRange(0, 100)
        self.storage_bar.setValue(percent)
        self.storage_bar.setProperty(
            "state",
            "full" if total >= capacity else "warning" if percent >= 80 else "normal",
        )
        self.storage_bar.style().unpolish(self.storage_bar)
        self.storage_bar.style().polish(self.storage_bar)

    def _badge_state(self, entry: dict[str, Any], path: Any) -> str:
        if self._is_live_entry(path):
            return "live"

        if not bool(entry.get("complete", True)) and not self._has_video(path):
            return "pending"

        return "ready"

    def _badge_text(self, entry: dict[str, Any], path: Any) -> str:
        if self._is_live_entry(path):
            return "● REC"

        if not bool(entry.get("complete", True)) and not self._has_video(path):
            return "Procesando"

        return "Lista"

    def _is_live_entry(self, path: Any) -> bool:
        if not self.service.is_recording:
            return False

        current = self.service.output_path

        return current is not None and path is not None and Path(path) == Path(current)

    @staticmethod
    def _has_video(path: Any) -> bool:
        try:
            return Path(path).is_file()
        except (OSError, TypeError):
            return False

    def delete_entry(self, path: Any) -> None:
        if path is None:
            return

        video = Path(path)

        if self._is_live_entry(video):
            QMessageBox.information(
                self,
                "Grabando ahora mismo",
                "Esa partida se está grabando: podrás eliminarla al terminar.",
            )

            return

        answer = QMessageBox.question(
            self,
            "Eliminar grabación",
            f"¿Borrar «{video.name}»? Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self._release_media(video)

        if not self.library.delete(video):
            QMessageBox.warning(
                self,
                "No se pudo eliminar",
                f"«{video.name}» sigue en uso (por ejemplo, si se está "
                "reproduciendo o lo tiene abierto el explorador). Cierra "
                "el reproductor e inténtalo de nuevo.",
            )

        self.refresh()

    def _release_media(self, video: Path) -> None:
        """Suelta el vídeo del reproductor para que Windows deje borrarlo.

        El backend de FFmpeg mantiene el fichero abierto hasta que se cambia
        la fuente: con ``stop()`` no basta, hay que vaciar la fuente.
        """
        if self.current_path is None or Path(video) != self.current_path:
            return

        self.player.stop()
        self.player.setSource(QUrl())
        self.current_path = None
        self.pending_seek_ms = 0
        self.player_title.setText("Elige una grabación de la lista")
        self.player_result.setText("SIN PARTIDA")
        self.player_result.setProperty("state", "unknown")
        self.player_date.setText("")
        self.player_score.setText("")
        self.current_saved_match = {}
        self.play_button.setEnabled(False)
        actualizar_texto_boton(self.play_button, "▶ Reproducir")
        self.position_slider.setRange(0, 0)
        self.position_slider.set_markers([], 0)
        self.marker_list.clear()
        QApplication.processEvents()

    def open_folder(self) -> None:
        directory = self.library.ensure_directory()
        self.open_folder_requested.emit(str(directory))

    @staticmethod
    def open_in_explorer(directory: str) -> bool:
        try:
            subprocess.Popen(  # noqa: S603,S607 - ruta local del usuario
                ["explorer", directory]
            )
        except OSError:
            return False

        return True

    # -- reproducción ---------------------------------------------------

    def play_entry(self, path: Any) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        if path is None:
            return

        video = Path(path)

        if not video.is_file():
            QMessageBox.information(
                self,
                "Grabación no disponible",
                "Ese vídeo ya no existe en la carpeta.",
            )
            self.refresh()

            return

        if self._is_live_entry(video):
            QMessageBox.information(
                self,
                "Grabando ahora mismo",
                "Esa partida se está grabando: podrás verla al terminar.",
            )

            return

        self.current_path = video
        metadata = self.library.load_metadata(video)
        selected = next(
            (entry for entry in self.entries if Path(entry.get("path")) == video), {}
        )
        saved_match = (
            selected.get("saved_match")
            if isinstance(selected.get("saved_match"), dict)
            else {}
        )
        self.current_saved_match = saved_match
        markers = metadata.get("markers")

        if not isinstance(markers, list):
            markers = []

        self.pending_seek_ms = 0
        self.position_slider.set_markers(markers, 0)
        self.position_slider.setRange(0, 0)
        self._rebuild_marker_list(markers)
        champion = str(metadata.get("champion") or video.stem)
        self.player_title.setText(
            f"{champion} · {metadata.get('game_mode') or 'Partida grabada'}"
        )
        result = (
            "VICTORIA"
            if saved_match.get("win") is True
            else "DERROTA"
            if saved_match.get("win") is False
            else "RESULTADO NO DISPONIBLE"
        )
        result_state = (
            "victory"
            if saved_match.get("win") is True
            else "defeat"
            if saved_match.get("win") is False
            else "unknown"
        )
        self.player_result.setText(result)
        self.player_result.setProperty("state", result_state)
        self.player_result.style().unpolish(self.player_result)
        self.player_result.style().polish(self.player_result)
        self.player_date.setText(str(selected.get("date_label") or ""))
        score = self._battle_score(saved_match)
        self.player_score.setText(
            f"BATTLESCORE  {score}"
            if isinstance(score, (int, float))
            else "BATTLESCORE  —"
        )
        for recording_path, card in self._recording_cards.items():
            card.setProperty("selected", str(recording_path == str(video)).lower())
            card.style().unpolish(card)
            card.style().polish(card)
        self.play_button.setEnabled(True)
        actualizar_texto_boton(self.play_button, "⏸ Pausar")
        self.player.setSource(QUrl.fromLocalFile(str(video)))
        self.player.play()
        self.video_widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def toggle_play(self) -> None:
        if self.current_path is None:
            return

        state = self.player.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_to_ms(self, position_ms: int) -> None:
        """Busca una posición y conserva solicitudes durante la carga.

        Args:
            position_ms: Posición solicitada en milisegundos.

        Returns:
            None.
        """
        if self.current_path is None:
            return

        duration = int(self.player.duration())

        if duration <= 0:
            self.pending_seek_ms = max(0, int(position_ms))

            return

        self.player.setPosition(max(0, min(int(position_ms), duration)))

    def pause_for_replay(self) -> None:
        """Pausa el vídeo visible sin cambiar su posición.

        Returns:
            None.
        """
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()

    def seek_backward(self) -> None:
        self.seek_to_ms(self.player.position() - SEEK_SECONDS * 1000)

    def seek_forward(self) -> None:
        self.seek_to_ms(self.player.position() + SEEK_SECONDS * 1000)

    def _apply_volume(self, value: int) -> None:
        self.audio_output.setVolume(max(0, min(100, value)) / 100.0)

    def _sync_play_button(self, state: QMediaPlayer.PlaybackState) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        if self.current_path is None:
            actualizar_texto_boton(self.play_button, "▶ Reproducir")

            return

        if state == QMediaPlayer.PlaybackState.PlayingState:
            actualizar_texto_boton(self.play_button, "⏸ Pausar")
        else:
            actualizar_texto_boton(self.play_button, "▶ Reproducir")

    def _on_position_changed(self, position_ms: int) -> None:
        duration = self.player.duration()

        if duration > 0 and not self.position_slider.isSliderDown():
            self.position_slider.blockSignals(True)
            self.position_slider.setValue(position_ms)
            self.position_slider.blockSignals(False)

        self.position_label.setText(
            f"{format_duration(position_ms / 1000)} / "
            f"{format_duration(duration / 1000)}"
        )

    def _on_duration_changed(self, duration_ms: int) -> None:
        if duration_ms <= 0:
            return

        self.position_slider.setRange(0, duration_ms)

        if self.current_path is not None:
            metadata = self.library.load_metadata(self.current_path)
            markers = metadata.get("markers")

            if isinstance(markers, list):
                self.position_slider.set_markers(markers, duration_ms)
                total = sum(isinstance(item, dict) for item in markers)
                self.marker_count_label.setText(
                    f"{total} momento(s) marcado(s)"
                    if total
                    else "Sin momentos marcados"
                )

        if self.pending_seek_ms > 0:
            pending, self.pending_seek_ms = self.pending_seek_ms, 0
            self.player.setPosition(pending)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.pause()

    def _on_player_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return

        if self.current_path is None:
            return

        self.player_title.setText(
            f"No se pudo reproducir ese vídeo ({message or 'formato no soportado'})."
        )

    # -- lista de momentos ----------------------------------------------

    def _rebuild_marker_list(self, markers: list[Any]) -> None:
        self.marker_list.clear()

        for marker in markers:
            if not isinstance(marker, dict):
                continue

            try:
                seconds = float(marker.get("time", 0))
            except (TypeError, ValueError):
                continue

            style = marker_style(str(marker.get("kind") or ""))
            label = str(marker.get("label") or "Evento")
            detail = str(marker.get("detail") or label)
            item = QListWidgetItem(
                f"{style['glyph']}   {format_duration(seconds):>5}   {label} · {detail}"
            )
            item.setData(Qt.ItemDataRole.UserRole, int(seconds * 1000))
            item.setToolTip(f"{format_duration(seconds)} · {label} — {detail}")
            item.setForeground(QColor(style["color"]))
            self.marker_list.addItem(item)

    def _jump_to_marker_item(self, item: QListWidgetItem) -> None:
        position = item.data(Qt.ItemDataRole.UserRole)

        try:
            self.seek_to_ms(int(position))
        except (TypeError, ValueError):
            pass

    # -- estado de la grabación en curso --------------------------------

    def sync_recording_state(self) -> None:
        """Actualiza el estado visible (botón Detener, cabecera)."""
        self._sync_recording_status()

    def _on_service_started(self, _path: str) -> None:
        self.recording_tick.start()
        self._sync_recording_status()

    def _on_service_finished(self, path: str) -> None:
        self.recording_tick.stop()
        self.refresh()
        self.play_entry(path)

    def _on_service_failed(self, message: str) -> None:
        self.recording_tick.stop()
        self._sync_recording_status(message)

    def _on_service_state(self, _state: str) -> None:
        self._sync_recording_status()

    def folder_size_cached(self) -> int:
        """Peso de la carpeta de grabaciones, releído como mucho cada 5 s.

        ``_sync_recording_status`` se llama al refrescar, en cada cambio de
        estado de la grabación y una vez por segundo mientras se graba;
        ``total_size_bytes`` recorre la carpeta entera cada vez, así que sin
        caché ese trabajo caía en el hilo de la interfaz continuamente.
        """
        now = time.monotonic()
        cached = self._folder_size_cache

        if cached is not None and now - cached[0] < 5.0:
            return cached[1]

        total = self.library.total_size_bytes()
        self._folder_size_cache = (now, total)

        return total

    def _sync_recording_status(self, notice: str = "") -> None:
        from app.services.recording_service import format_size

        total = self.folder_size_cached()
        count = len(self.entries)
        self._update_storage_overview(total)
        base = f"{count} grabación(es) · {format_size(total)} en disco"

        activo = self.service.is_starting_or_recording
        parando = bool(self.service.stop_requested)
        self.start_button.setEnabled(not activo)
        self.stop_button.setEnabled(activo and not parando)

        if parando:
            self.status_label.setText(f"Finalizando grabación… · {base}")
            self.status_label.setProperty("state", "idle")
            self.recording_tick.stop()
        elif self.service.is_recording:
            elapsed = format_duration(self.service.elapsed_seconds())
            audio = self.service.audio_status_text
            detalle_audio = f"\n{audio}" if audio.startswith("Error:") else ""
            self.status_label.setText(
                f"● Grabando partida ({elapsed}) · {base}{detalle_audio}"
            )
            self.status_label.setProperty("state", "live")

            if not self.recording_tick.isActive():
                self.recording_tick.start()
        elif self.service.is_starting_or_recording:
            self.status_label.setText(f"Iniciando grabación… · {base}")
            self.status_label.setProperty("state", "idle")
            self.recording_tick.stop()
        else:
            diagnostico = self.service.audio_status_text
            aviso_audio = f"\n{diagnostico}" if diagnostico.startswith("Error:") else ""
            detalle = f"{notice} · {base}" if notice else base
            self.status_label.setText(f"{detalle}{aviso_audio}")
            self.status_label.setProperty("state", "idle")
            self.recording_tick.stop()

        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
