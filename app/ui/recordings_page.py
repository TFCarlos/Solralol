"""Pestaña «Grabaciones»: biblioteca local y reproductor con marcadores.

La lista de la izquierda muestra los vídeos de la carpeta de grabaciones.
El panel de la derecha reproduce el vídeo elegido con los controles
clásicos (pausa, atrás/adelante 10 s) y una barra de progreso con los
indicadores de la partida: asesinatos, muertes, asistencias y objetivos
(torres, dragones, heraldos y barones).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from app.services.recording_service import (
    RecordingLibrary,
    RecordingService,
    format_duration,
)
from app.ui.async_task import run_async

SEEK_SECONDS = 10

#: Ancho común para los botones de acción de cada fila de grabación.
RECORDING_ROW_BUTTON_WIDTH = 100

#: Estilo de cada tipo de marcador en la barra y en la lista.
MARKER_STYLES: dict[str, dict[str, str]] = {
    "kill": {"color": "#4adea0", "glyph": "⚔️"},
    "teamfight": {"color": "#fbbf24", "glyph": "💥"},
    "death": {"color": "#f07d8a", "glyph": "💀"},
    "assist": {"color": "#57cafa", "glyph": "🤝"},
    "dragon": {"color": "#fb923c", "glyph": "🐉"},
    "baron": {"color": "#c084fc", "glyph": "👑"},
    "herald": {"color": "#c3b1fc", "glyph": "👁️"},
    "horde": {"color": "#a3e635", "glyph": "🐛"},
    "tower": {"color": "#e9c875", "glyph": "🏰"},
    "inhibitor": {"color": "#2dd4bf", "glyph": "💠"},
    "objective": {"color": "#a78bfa", "glyph": "🎯"},
}


def marker_style(kind: str) -> dict[str, str]:
    return MARKER_STYLES.get(kind, {"color": "#94a3b8", "glyph": "•"})


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


#: Tipos de marcador que cuentan como objetivo en la tarjeta ESTADÍSTICAS
#: (asesinatos, muertes y asistencias van aparte).
OBJECTIVE_MARKER_KINDS = frozenset(
    {
        "dragon",
        "baron",
        "herald",
        "tower",
        "inhibitor",
        "horde",
        "objective",
    }
)


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
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- datos ----------------------------------------------------------

    def set_show_marker_glyphs(self, value: bool) -> None:
        """Activa/desactiva los iconos sobre cada marcador."""
        self.show_marker_glyphs = bool(value)
        self.update()

    # -- datos ----------------------------------------------------------

    def set_markers(
        self, markers: list[dict[str, Any]], duration_ms: int
    ) -> None:
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
                        marker.get("detail")
                        or marker.get("label")
                        or "Evento"
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

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
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
                plotted.append(
                    (float(x), marker, marker_style(marker["kind"]))
                )

        # Línea-guía vertical bajo el chip apuntado por el ratón: conecta el
        # icono con su momento exacto de la barra.
        if self._hover_x is not None:
            guide_pen = QPen(QColor(217, 174, 79, 130), 2)
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
                pin_color = QColor("#4ade80")
            elif side == "enemy":
                pin_color = QColor("#f07d8a")
            else:
                pin_color = QColor(style["color"])

            hovered = (
                self._hover_x is not None and abs(x - self._hover_x) <= 0.6
            )
            radius = pin_radius + (2.0 if hovered else 0.0)
            ring = QColor("#f0cc70") if hovered else QColor("#0b1423")
            painter.setPen(QPen(ring, 1.6))
            painter.setBrush(QBrush(pin_color))
            painter.drawEllipse(QPointF(x, center_y), radius, radius)

        # Fila de iconos (chips) sobre la barra: solo si el slider es lo
        # bastante alto y la pestaña los activa. Los sucesos muy juntos se
        # agrupan en un solo chip con insignia «×n» para que nada quede
        # ilegible; el tooltip detalla todos los sucesos apilados.
        chip_height = 0.0
        font: QFont | None = None

        if self.show_marker_glyphs and self.height() >= 26:
            chip_height = float(max(12, min(18, self.height() - 24)))
            font = QFont()
            font.setPixelSize(int(max(9, chip_height - 5)))
            font.setBold(True)

        if font is not None and chip_height > 0:
            painter.setFont(font)

            for cluster in self._cluster_plotted(plotted):
                x = cluster["x"]
                marker = cluster["marker"]
                style = cluster["style"]
                glyph = str(marker.get("glyph") or style["glyph"])
                color = QColor(style["color"])
                hovered = (
                    self._hover_x is not None and abs(x - self._hover_x) <= 0.6
                )
                rect = QRectF(x - 10.0, 1.0, 20.0, chip_height)
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
                painter.setPen(QPen(QColor("#eef4ff")))
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
                    painter.setBrush(QBrush(QColor("#0b1423")))
                    painter.drawEllipse(badge)
                    painter.setPen(QPen(QColor("#eef4ff")))
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

            clusters.append(
                {"x": x, "marker": marker, "style": style, "count": 1}
            )

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
            seconds = self._seconds_at(int(event.position().x()))
            self.seek_requested.emit(int(seconds * 1000))
            event.accept()

            return

        super().mousePressEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        if self._hover_x is not None:
            self._hover_x = None
            self.update()

        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
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

    def _markers_at(
        self, seconds: float, tolerance: float
    ) -> list[dict[str, Any]]:
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
        self.library = library
        self.service = service
        self.entries: list[dict[str, Any]] = []
        self.current_path: Path | None = None
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
        self._wire_service()

    # -- construcción ---------------------------------------------------

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(self._build_header())

        self.status_label = QLabel("Cargando grabaciones…")
        self.status_label.setObjectName("recordingsStatus")
        layout.addWidget(self.status_label)

        body = QHBoxLayout()
        body.setSpacing(14)

        body.addWidget(self._build_list_column(), 1)
        body.addWidget(self._build_player_card(), 2)

        layout.addLayout(body, 1)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("heroCard")

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 20)
        header_layout.setSpacing(14)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        eyebrow = QLabel("PARTIDAS LOCALES")
        eyebrow.setObjectName("eyebrow")
        text_layout.addWidget(eyebrow)

        title = QLabel("Grabaciones")
        title.setObjectName("heroTitle")
        text_layout.addWidget(title)

        description = QLabel(
            "Cada partida se graba sola de principio a fin: vídeo de la "
            "pantalla con el sonido del juego (el micrófono es opcional). "
            "Pulsa un marcador para saltar a ese momento."
        )
        description.setObjectName("heroText")
        description.setWordWrap(True)
        text_layout.addWidget(description)

        header_layout.addLayout(text_layout, 1)

        buttons = QVBoxLayout()
        buttons.setSpacing(8)

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

        self.refresh_button = QPushButton("Actualizar lista")
        self.refresh_button.setObjectName("secondaryButton")
        self.refresh_button.clicked.connect(self.refresh)
        buttons.addWidget(self.refresh_button)

        self.folder_button = QPushButton("Abrir carpeta")
        self.folder_button.setObjectName("secondaryButton")
        self.folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.folder_button)

        header_layout.addLayout(buttons)

        return header

    def _build_list_column(self) -> QWidget:
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        caption = QLabel("VÍDEOS GUARDADOS")
        caption.setObjectName("eyebrow")
        container_layout.addWidget(caption)

        scroll = QScrollArea()
        scroll.setObjectName("recordingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.list_content = QWidget()
        self.list_content.setObjectName("recordingsContent")
        self.list_layout = QVBoxLayout(self.list_content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(12)

        scroll.setWidget(self.list_content)
        container_layout.addWidget(scroll, 1)

        return container

    def _build_player_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("recordingPlayerCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # Título y ESTADÍSTICAS comparten fila: antes la tarjeta de
        # estadísticas tenía una fila propia (robaba altura al vídeo y, sin
        # marcadores, quedaba como una caja vacía encima del reproductor).
        title_row = QHBoxLayout()
        title_row.setSpacing(10)

        self.player_title = QLabel("Elige una grabación de la lista")
        self.player_title.setObjectName("recordingPlayerTitle")
        self.player_title.setWordWrap(True)
        title_row.addWidget(self.player_title, 1)
        title_row.addWidget(self._build_kda_card())
        layout.addLayout(title_row)

        self.video_widget = QVideoWidget()
        self.video_widget.setObjectName("recordingVideo")
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
        layout.addWidget(self.position_slider)

        time_row = QHBoxLayout()
        time_row.setSpacing(10)

        self.position_label = QLabel("00:00 / 00:00")
        self.position_label.setObjectName("recordingPlayerTime")
        time_row.addWidget(self.position_label)
        time_row.addStretch(1)

        self.marker_count_label = QLabel("")
        self.marker_count_label.setObjectName("recordingMarkerLegend")
        self.marker_count_label.setWordWrap(True)
        time_row.addWidget(self.marker_count_label)

        layout.addLayout(time_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.back_button = QPushButton(f"⏪ {SEEK_SECONDS}s")
        self.back_button.setObjectName("recordingPlayButton")
        self.back_button.clicked.connect(self.seek_backward)
        controls.addWidget(self.back_button)

        self.play_button = QPushButton("▶ Reproducir")
        self.play_button.setObjectName("recordingPlayButton")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.toggle_play)
        controls.addWidget(self.play_button)

        self.forward_button = QPushButton(f"{SEEK_SECONDS}s ⏩")
        self.forward_button.setObjectName("recordingPlayButton")
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

        layout.addLayout(controls)

        legend = QLabel(
            "⚔ asesinato · ✖ muerte · ✚ asistencia · 🐉 dragón · "
            "👁 heraldo · 👑 barón · 🗼 torre · 💠 inhibidor"
        )
        legend.setObjectName("recordingMarkerLegend")
        legend.setWordWrap(True)
        layout.addWidget(legend)

        self.marker_list = QListWidget()
        self.marker_list.setObjectName("recordingMarkerList")
        self.marker_list.setMaximumHeight(150)
        self.marker_list.itemClicked.connect(self._jump_to_marker_item)
        layout.addWidget(self.marker_list)

        return card

    def _build_kda_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("recordingKdaCard")
        card.setFixedWidth(120)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        title = QLabel("ESTADÍSTICAS")
        title.setObjectName("recordingKdaEyebrow")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.kda_value = QLabel("—")
        self.kda_value.setObjectName("recordingKdaValue")
        self.kda_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kda_value.setWordWrap(False)
        self.kda_value.setToolTip(
            "Asesinatos · muertes · asistencias de la partida grabada"
        )
        layout.addWidget(self.kda_value)

        self.kda_objectives = QLabel("")
        self.kda_objectives.setObjectName("recordingKdaObjectives")
        self.kda_objectives.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.kda_objectives.setToolTip(
            "Objetivos de la partida (torres, dragones, heraldos, barones…)"
        )
        layout.addWidget(self.kda_objectives)

        return card

    def _update_kda_card(self) -> None:
        kills = deaths = assists = objectives = 0
        markers = (
            self.position_slider.markers
            if hasattr(self, "position_slider")
            else []
        )
        for marker in markers or []:
            if not isinstance(marker, dict):
                continue
            kind = str(marker.get("kind") or "")
            if kind == "kill":
                kills += 1
            elif kind == "death":
                deaths += 1
            elif kind == "assist":
                assists += 1
            elif kind in OBJECTIVE_MARKER_KINDS:
                objectives += 1

        # Un guion en vez de texto vacío: sin marcadores la tarjeta seguía
        # pareciendo rota («ESTADÍSTICAS no muestra nada»).
        if kills or deaths or assists:
            self.kda_value.setText(f"⚔ {kills}  ✖ {deaths}  ✚ {assists}")
        else:
            self.kda_value.setText("—")

        self.kda_objectives.setText(
            f"🎯 {objectives}" if objectives else ""
        )
        self.kda_objectives.setVisible(objectives > 0)

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
            self.status_label.setText(
                f"No se pudieron leer las grabaciones: {error}"
            )
        else:
            self.entries = list(entries or [])
            # La carpeta puede haber cambiado: el peso mostrado se relee.
            self._folder_size_cache = None
            self._rebuild_rows()

        if self._scan_pending:
            self._scan_pending = False
            self.refresh()

    def _rebuild_rows(self) -> None:
        """Reconstruye las filas sin tocar lo que se esté reproduciendo."""
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        if not self.entries:
            empty = QLabel(
                "Aún no hay grabaciones. Juega una partida con SolraLoL "
                "abierto y aparecerá aquí sola al terminar."
            )
            empty.setObjectName("recordingsEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.list_layout.addWidget(empty)
        else:
            for entry in self.entries:
                self.list_layout.addWidget(
                    self._build_entry_row(entry)
                )

        self.list_layout.addStretch(1)
        self._sync_recording_status()

        # La biblioteca cambió: la pestaña «Partidas guardadas» debe
        # reconstruirse para mostrar/ocultar «Repaso con vídeo» según
        # exista la grabación asociada a cada partida.
        self.recordings_changed.emit()

    def _build_entry_row(self, entry: dict[str, Any]) -> QWidget:
        path = entry.get("path")
        row = QFrame()
        row.setObjectName("recordingRow")
        row.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        layout = QVBoxLayout(row)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel(str(entry.get("title") or "Grabación"))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("recordingTitle")
        title_row.addWidget(title, 1)

        badge = QLabel()
        badge.setObjectName("recordingBadge")
        badge.setProperty("state", self._badge_state(entry, path))
        badge.setText(self._badge_text(entry, path))
        title_row.addWidget(badge)

        layout.addLayout(title_row)

        detail = QLabel(
            f"{entry.get('date_label', '')} · "
            f"{entry.get('duration_label', '')} · "
            f"{entry.get('size_label', '')}"
        )
        detail.setObjectName("recordingDetail")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        subtitle = str(entry.get("subtitle") or "")

        if subtitle:
            extra = QLabel(subtitle)
            extra.setObjectName("recordingDetail")
            extra.setWordWrap(True)
            layout.addWidget(extra)

        summary = str(entry.get("summary") or "")

        if summary:
            moments = QLabel(f"Momentos: {summary}")
            moments.setObjectName("recordingDetail")
            moments.setWordWrap(True)
            layout.addWidget(moments)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        play = QPushButton("▶ Ver")
        play.setObjectName("secondaryButton")
        play.setFixedWidth(RECORDING_ROW_BUTTON_WIDTH)
        play.clicked.connect(
            lambda _checked=False, value=path: self.play_entry(value)
        )
        actions.addWidget(play)

        window_button = QPushButton("🗔 Ventana")
        window_button.setObjectName("secondaryButton")
        window_button.setFixedWidth(RECORDING_ROW_BUTTON_WIDTH)
        window_button.setToolTip(
            "Abrir la partida en la ventana de repaso (vídeo + desglose)"
        )
        window_button.clicked.connect(
            lambda _checked=False, value=path: self.open_window_requested.emit(
                str(value)
            )
        )
        actions.addWidget(window_button)

        remove = QPushButton("Eliminar")
        remove.setObjectName("dangerButton")
        remove.setFixedWidth(RECORDING_ROW_BUTTON_WIDTH)
        remove.clicked.connect(
            lambda _checked=False, value=path: self.delete_entry(value)
        )
        actions.addWidget(remove)
        actions.addStretch(1)

        layout.addLayout(actions)

        return row

    def _badge_state(self, entry: dict[str, Any], path: Any) -> str:
        if self._is_live_entry(path):
            return "live"

        if not bool(entry.get("complete", True)) and not self._has_video(
            path
        ):
            return "pending"

        return "ready"

    def _badge_text(self, entry: dict[str, Any], path: Any) -> str:
        if self._is_live_entry(path):
            return "● REC"

        if not bool(entry.get("complete", True)) and not self._has_video(
            path
        ):
            return "Procesando"

        return "Lista"

    def _is_live_entry(self, path: Any) -> bool:
        if not self.service.is_recording:
            return False

        current = self.service.output_path

        return (
            current is not None
            and path is not None
            and Path(path) == Path(current)
        )

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
                "Esa partida se está grabando: podrás eliminarla al "
                "terminar.",
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
        self.play_button.setEnabled(False)
        self.play_button.setText("▶ Reproducir")
        self.position_slider.setRange(0, 0)
        self.position_slider.set_markers([], 0)
        self._update_kda_card()
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
        markers = metadata.get("markers")

        if not isinstance(markers, list):
            markers = []

        self.pending_seek_ms = 0
        self.position_slider.set_markers(markers, 0)
        self.position_slider.setRange(0, 0)
        self._rebuild_marker_list(markers)
        self._update_kda_card()

        champion = str(metadata.get("champion") or video.stem)
        self.player_title.setText(f"▶ {champion} — {video.name}")
        self.play_button.setEnabled(True)
        self.play_button.setText("⏸ Pausar")
        self.player.setSource(QUrl.fromLocalFile(str(video)))
        self.player.play()

    def toggle_play(self) -> None:
        if self.current_path is None:
            return

        state = self.player.playbackState()

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_to_ms(self, position_ms: int) -> None:
        if self.current_path is None or self.player.duration() <= 0:
            self.pending_seek_ms = max(0, int(position_ms))

            return

        self.player.setPosition(max(0, int(position_ms)))

    def seek_backward(self) -> None:
        self.seek_to_ms(self.player.position() - SEEK_SECONDS * 1000)

    def seek_forward(self) -> None:
        self.seek_to_ms(self.player.position() + SEEK_SECONDS * 1000)

    def _apply_volume(self, value: int) -> None:
        self.audio_output.setVolume(max(0, min(100, value)) / 100.0)

    def _sync_play_button(
        self, state: QMediaPlayer.PlaybackState
    ) -> None:
        if self.current_path is None:
            self.play_button.setText("▶ Reproducir")

            return

        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_button.setText("⏸ Pausar")
        else:
            self.play_button.setText("▶ Reproducir")

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
                self._update_kda_card()

                total = sum(
                    isinstance(item, dict) for item in markers
                )
                self.marker_count_label.setText(
                    f"{total} momento(s) marcado(s)"
                    if total
                    else "Sin momentos marcados"
                )

        if self.pending_seek_ms > 0:
            pending, self.pending_seek_ms = self.pending_seek_ms, 0
            self.player.setPosition(pending)

    def _on_media_status(
        self, status: QMediaPlayer.MediaStatus
    ) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.setPosition(0)
            self.player.pause()

    def _on_player_error(
        self, error: QMediaPlayer.Error, message: str
    ) -> None:
        if error == QMediaPlayer.Error.NoError:
            return

        if self.current_path is None:
            return

        self.player_title.setText(
            "No se pudo reproducir ese vídeo "
            f"({message or 'formato no soportado'})."
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
                f"{style['glyph']} {format_duration(seconds)} · "
                f"{label} — {detail}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole, int(seconds * 1000)
            )
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
        base = f"{count} grabación(es) · {format_size(total)} en disco"

        self.stop_button.setEnabled(self.service.is_recording)

        if self.service.is_recording:
            elapsed = format_duration(self.service.elapsed_seconds())
            self.status_label.setText(
                f"● Grabando partida ({elapsed}) · {base}"
            )
            self.status_label.setProperty("state", "live")

            if not self.recording_tick.isActive():
                self.recording_tick.start()
        else:
            self.status_label.setText(
                f"{notice} · {base}" if notice else base
            )
            self.status_label.setProperty("state", "idle")
            self.recording_tick.stop()

        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
