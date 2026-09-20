"""Pestaña «Grabaciones»: biblioteca local y reproductor con marcadores.

La lista de la izquierda muestra los vídeos de la carpeta de grabaciones.
El panel de la derecha reproduce el vídeo elegido con los controles
clásicos (pausa, atrás/adelante 10 s) y una barra de progreso con los
indicadores de la partida: asesinatos, muertes, asistencias y objetivos
(torres, dragones, heraldos y barones).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen
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

SEEK_SECONDS = 10

#: Estilo de cada tipo de marcador en la barra y en la lista.
MARKER_STYLES: dict[str, dict[str, str]] = {
    "kill": {"color": "#4adea0", "glyph": "⚔️"},
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
                }
            )

        self.markers = sorted(cleaned, key=lambda item: item["time"])
        self.duration_ms = max(0, int(duration_ms or 0))
        self.update()

    # -- dibujo ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        super().paintEvent(event)

        if not self.markers or self.duration_ms <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        top = 2
        bottom = max(top + 4, self.height() - 2)
        glyph_baseline = 0

        if self.show_marker_glyphs:
            from PySide6.QtGui import QFont

            font = QFont()
            font.setPixelSize(max(9, min(13, self.height() - 12)))
            painter.setFont(font)
            glyph_baseline = top + font.pixelSize() + 2
            top = glyph_baseline + 2
            bottom = max(top + 2, self.height() - 2)

        last_glyph_x = -10**9

        for marker in self.markers:
            x = self._x_for_seconds(marker["time"])

            if x is None:
                continue

            style = marker_style(marker["kind"])
            pen = QPen(QColor(style["color"]))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.drawLine(x, top, x, bottom)

            # Icono del suceso sobre la rayita (espada, torre, calavera...):
            # se omite si está pegado al anterior para no solaparlos.
            if self.show_marker_glyphs and x - last_glyph_x >= 16:
                glyph = str(marker.get("glyph") or style["glyph"])
                painter.drawText(x - 8, top - 4, 16, 14, Qt.AlignCenter, glyph)
                last_glyph_x = x

        painter.end()

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

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - firma de Qt
        seconds = self._seconds_at(int(event.position().x()))
        hit = self._marker_at(seconds, tolerance=8.0)

        if hit is not None:
            self.setToolTip(
                f"{marker_style(hit['kind'])['glyph']} "
                f"{format_duration(hit['time'])} · "
                f"{hit['label']} — {hit['detail']}"
            )
        else:
            self.setToolTip(
                f"Saltar a {format_duration(seconds)} del vídeo"
            )

        super().mouseMoveEvent(event)

    def _marker_at(
        self, seconds: float, tolerance: float
    ) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        best_distance = tolerance

        for marker in self.markers:
            distance = abs(float(marker["time"]) - seconds)

            if distance <= best_distance:
                best = marker
                best_distance = distance

        return best


class RecordingsPage(QWidget):
    """Pestaña completa: cabecera, lista de vídeos y reproductor."""

    open_folder_requested = Signal(str)
    #: El usuario pulsa «Detener grabación»: la ventana cierra la sesión.
    stop_recording_requested = Signal()
    #: El usuario quiere ver la grabación en la ventana de repaso aparte.
    open_window_requested = Signal(str)

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

        self.player_title = QLabel("Elige una grabación de la lista")
        self.player_title.setObjectName("recordingPlayerTitle")
        self.player_title.setWordWrap(True)
        layout.addWidget(self.player_title)

        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumHeight(320)
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
        """Reconstruye la lista sin tocar lo que se esté reproduciendo."""
        self.entries = self.library.list_recordings()

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
        play.setFixedWidth(80)
        play.clicked.connect(
            lambda _checked=False, value=path: self.play_entry(value)
        )
        actions.addWidget(play)

        window_button = QPushButton("🗔 Ventana")
        window_button.setObjectName("secondaryButton")
        window_button.setFixedWidth(100)
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
        remove.setFixedWidth(90)
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

    def _sync_recording_status(self, notice: str = "") -> None:
        from app.services.recording_service import format_size

        total = self.library.total_size_bytes()
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
