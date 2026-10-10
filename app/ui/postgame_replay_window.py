"""Ventana independiente de repaso post-partida.

Abre el vídeo grabado de la partida y, junto a él, el desglose completo:
marcador de los diez jugadores, comparativa por radar del enfrentamiento
y la timeline de revisión con los sucesos valorados.

El desglose se construye **siempre con la telemetría local** de la sesión
(``LiveMatchTracker``), esté o no sincronizada con Riot. Al pulsar
«Re-desglosar» se vuelve a leer la sesión de disco y se reconstruye todo,
que es lo útil cuando se acaba de actualizar la partida con la Riot API.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
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
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.services.recording_service import (
    MARKER_LABELS,
    SESSION_VIDEO_TOLERANCE_SECONDS,
    RecordingLibrary,
    build_markers,
    find_video_for_session,
    format_duration,
    normalise_marker_kind,
    parse_iso_timestamp,
)
from app.ui.postgame_sidebar import PostgameSidebar
from app.ui.recordings_page import MarkerSlider
from app.ui.tema import (
    actualizar_texto_boton,
    aplicar_tema,
)

#: Segundos que retrocede/avanza cada botón de salto.
SEEK_SECONDS = 10
KEYBOARD_SEEK_SECONDS = 5

REPLAY_MARKER_GROUPS: tuple[tuple[str, str, str, frozenset[str]], ...] = (
    ("kill", "Asesinatos", "⚔", frozenset({"kill"})),
    ("death", "Muertes", "☠", frozenset({"death"})),
    ("assist", "Asistencias", "✦", frozenset({"assist"})),
    ("dragon", "Dragones", "🐉", frozenset({"dragon"})),
    ("herald", "Heraldos", "◈", frozenset({"herald", "rift_herald"})),
    ("baron", "Barones", "♛", frozenset({"baron"})),
    ("tower", "Torres", "♜", frozenset({"tower"})),
    ("inhibitor", "Inhibidores", "◆", frozenset({"inhibitor"})),
    ("other", "Otros", "•", frozenset({"teamfight", "horde", "objective"})),
)


def marker_filter_group(kind: Any) -> str:
    """Clasifica un tipo de marcador para el filtro de la cronología.

    Args:
        kind: Tipo canónico o alias del marcador.

    Returns:
        Clave del grupo visible correspondiente.
    """
    raw_category = kind.get("category") if isinstance(kind, dict) else kind
    if not raw_category and isinstance(kind, dict):
        raw_category = kind.get("kind")

    normalizado = normalise_marker_kind(str(raw_category or ""))

    if normalizado in {"kill_exact", "death_exact", "assist_exact", "championkill"}:
        return "unclassified"

    for group, _label, _glyph, kinds in REPLAY_MARKER_GROUPS:
        if normalizado in kinds:
            return group

    return "other"


def filter_replay_markers(
    markers: list[dict[str, Any]], active_categories: set[str]
) -> list[dict[str, Any]]:
    """Filtra marcadores por su categoría normalizada.

    Args:
        markers: Marcadores independientes ya asociados a una perspectiva.
        active_categories: Claves de las categorías seleccionadas.

    Returns:
        Marcadores cuya categoría está activa, en el orden original.
    """
    return [
        marker for marker in markers if marker_filter_group(marker) in active_categories
    ]


def marker_filter_summary(
    markers: list[dict[str, Any]], active_categories: set[str]
) -> str:
    """Resume marcadores visibles, totales y categorías activas.

    Args:
        markers: Marcadores completos de la perspectiva seleccionada.
        active_categories: Claves de las categorías seleccionadas.

    Returns:
        Resumen breve en español con singular y plural correctos.
    """
    if not markers:
        return "Sin marcadores"

    count = len(active_categories)
    label = "categoría activa" if count == 1 else "categorías activas"
    visible = len(filter_replay_markers(markers, active_categories))
    return f"{visible} de {len(markers)} marcadores · {count} {label}"


def game_time_to_video_position_ms(game_seconds: float, offset_seconds: float) -> int:
    """Convierte un segundo de partida a la posición del vídeo.

    Args:
        game_seconds: Tiempo de partida del marcador seleccionado.
        offset_seconds: Diferencia entre el inicio del vídeo y la partida.

    Returns:
        Posición de vídeo en milisegundos, limitada a cero como mínimo.
    """
    try:
        return max(0, int((float(game_seconds) - float(offset_seconds)) * 1000))
    except (TypeError, ValueError, OverflowError):
        return 0


class ReplayVideoWidget(QVideoWidget):
    """Vídeo que alterna la pantalla completa con doble clic."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return

        super().mouseDoubleClickEvent(event)


class PostgameMarkerSlider(MarkerSlider):
    """Barra de progreso con los indicadores de la partida.

    Reutiliza la barra de la pestaña Grabaciones (misma lógica de pintado y
    de salto al marcador) con un nombre de objeto propio para el estilo de
    esta ventana.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("postgameMarkerSlider")
        self.setMinimumHeight(38)
        self.set_show_marker_glyphs(False)


class PostgameReplayWindow(QMainWindow):
    """Vídeo del repaso y desglose de la partida en una ventana aparte."""

    closed = Signal()

    def __init__(
        self,
        *,
        session: dict[str, Any] | None = None,
        video_path: str | Path | None = None,
        library: RecordingLibrary | None = None,
        tracker: Any = None,
        service: Any = None,
        assets: Any = None,
        item_catalog: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        super().__init__(parent)
        self.setObjectName("postgameReplayWindow")
        self.setWindowTitle("Repaso de partida · SolraLol")
        self.resize(1520, 900)
        self.setMinimumSize(1000, 640)

        self.session: dict[str, Any] = session if isinstance(session, dict) else {}
        self.video_path: Path | None = Path(video_path) if video_path else None
        self.library = library if library is not None else RecordingLibrary()
        self.tracker = tracker
        self.service = service
        self.assets = assets
        self.item_catalog = item_catalog if isinstance(item_catalog, dict) else {}
        self.game_time_offset = 0.0
        self.metadata: dict[str, Any] = {}
        self.markers: list[dict[str, Any]] = []
        self._pending_seek_ms = 0
        self.ai_review_view: Any | None = None
        self._ai_review_tab_index = -1
        # Ventana dedicada para la pantalla completa del vídeo (con la barra
        # de reproducción dentro); se crea la primera vez que se pide.
        self._fs_window: QWidget | None = None
        self._fs_video_host: QWidget | None = None
        self._fs_bar_layout: QVBoxLayout | None = None
        self._card_layout: QVBoxLayout | None = None
        self._playback_shortcuts: list[QShortcut] = []
        self._fullscreen_shortcuts: list[QShortcut] = []

        self._build_ui()
        self._build_player()
        self._install_shortcuts()
        aplicar_tema(self)

        if self.video_path is None:
            self.video_path = self.video_for_session(self.session)

            if self.video_path is not None:
                self.metadata = self._load_metadata(self.video_path)

        if self.video_path is not None:
            # El vídeo describe su partida en el sidecar y el tracker guarda
            # la sesión completa en disco: el desglose se construye con la
            # más rica de las dos (nunca con una sesión vacía).
            self._adopt_session_for_video()

        self.reload_breakdown(first_load=True)

    # -- construcción ---------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("postgameRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        layout.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("postgameSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_video_column())
        self.sidebar = PostgameSidebar(self.session or None)
        self.sidebar.setMinimumWidth(390)
        self.sidebar.event_activated.connect(self.jump_to_game_time)
        self.selector_contexto_cronologia.currentIndexChanged.connect(
            self._on_timeline_context_changed
        )
        try:
            self.sidebar.events_changed.connect(self._refresh_markers)
        except (AttributeError, RuntimeError, TypeError):
            pass
        splitter.addWidget(self.sidebar)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([880, 600])
        layout.addWidget(splitter, 1)

        self.status_label = QLabel("Selecciona una grabación para verla.")
        self.status_label.setObjectName("postgameStatus")
        layout.addWidget(self.status_label)

        self._ensure_ai_review_tab()

    def _ensure_ai_review_tab(self) -> None:
        """Inserta el lector de coaching IA y lo conecta con el reproductor."""
        if self._ai_review_tab_index >= 0 and self.ai_review_view is not None:
            return
        tabs = getattr(self.sidebar, "tabs", None)
        if tabs is None:
            return
        try:
            from app.ui.postgame_ai_review import PostgameAIReview

            view = PostgameAIReview(self.tracker, self.sidebar)
            view.seek_requested.connect(self.jump_to_game_time)
        except (ImportError, RuntimeError, TypeError, ValueError):
            return
        self.ai_review_view = view
        self._ai_review_tab_index = tabs.addTab(view, "Análisis con IA")
        self._sync_ai_review_tab()

    def _sync_ai_review_tab(self) -> None:
        """Actualiza el lector de IA con la sesión del vídeo seleccionado."""
        view = self.ai_review_view
        if view is None:
            self._ensure_ai_review_tab()
            view = self.ai_review_view

        if view is None:
            return

        try:
            ai_session = dict(self.session or {})
            if self.video_path is not None:
                ai_session["recording_id"] = self.video_path.name
            view.set_session(ai_session)
        except RuntimeError:
            pass

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("postgameHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(9)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title_label = QLabel("Repaso de partida")
        self.title_label.setObjectName("postgameTitle")
        texts.addWidget(self.title_label)
        self.subtitle_label = QLabel("Sin grabación cargada")
        self.subtitle_label.setObjectName("postgameSubtitle")
        texts.addWidget(self.subtitle_label)
        layout.addLayout(texts, 1)

        self.badge = QLabel("TELEMETRÍA LIVE")
        self.badge.setObjectName("postgameBadge")
        layout.addWidget(self.badge)

        self.rebuild_button = QPushButton("🔄 Re-desglosar")
        self.rebuild_button.setObjectName("primaryButton")
        self.rebuild_button.setToolTip(
            "Vuelve a construir el desglose con la telemetría local de la "
            "sesión guardada (útil después de sincronizar con la Riot API)."
        )
        self.rebuild_button.clicked.connect(self.reload_breakdown)
        layout.addWidget(self.rebuild_button)

        self.folder_button = QPushButton("📂 Abrir carpeta")
        self.folder_button.setObjectName("secondaryButton")
        self.folder_button.clicked.connect(self.open_in_explorer)
        layout.addWidget(self.folder_button)

        return header

    def _build_video_column(self) -> QWidget:
        card = QFrame()
        card.setObjectName("postgamePlayerCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 9)
        layout.setSpacing(5)
        self._card_layout = layout

        self.video_widget = ReplayVideoWidget()
        self.video_widget.setObjectName("postgameVideo")
        self.video_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_widget.setMinimumHeight(260)
        self.video_widget.double_clicked.connect(self.toggle_fullscreen)
        layout.addWidget(self.video_widget, 1)

        self.marker_slider = PostgameMarkerSlider()
        self.marker_slider.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.marker_slider.seek_requested.connect(self.seek_to_ms)
        layout.addWidget(self.marker_slider)

        # Fila de transporte envuelta en un widget para poder moverla (con
        # todos sus controles) a la ventana de pantalla completa.
        self.transport_row = QWidget()
        self.transport_row.setObjectName("postgameTransportRow")
        self.transport_row.setLayout(self._build_transport())
        layout.addWidget(self.transport_row)

        return card

    def _build_transport(self) -> QVBoxLayout:
        """Construye controles agrupados y filtros de sucesos.

        Returns:
            Diseño vertical con transporte y filtros de marcadores.
        """
        transport = QVBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(5)

        controls = QFrame()
        controls.setObjectName("postgameControlsSurface")
        row = QHBoxLayout(controls)
        row.setContentsMargins(8, 5, 8, 5)
        row.setSpacing(6)
        self.back_button = QPushButton("⏪ 10 s")
        self.back_button.setObjectName("recordingPlayButton")
        self.back_button.setToolTip("Retroceder 10 segundos · ← retrocede 5 segundos")
        self.back_button.clicked.connect(lambda: self.seek_relative(-SEEK_SECONDS))
        row.addWidget(self.back_button)

        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("recordingPlayButton")
        self.play_button.setFixedSize(48, 34)
        self.play_button.setToolTip("Reproducir / pausar (Espacio)")
        self.play_button.clicked.connect(self.toggle_play)
        row.addWidget(self.play_button)

        self.forward_button = QPushButton("10 s ⏩")
        self.forward_button.setObjectName("recordingPlayButton")
        self.forward_button.setToolTip("Avanzar 10 segundos · → avanza 5 segundos")
        self.forward_button.clicked.connect(lambda: self.seek_relative(SEEK_SECONDS))
        row.addWidget(self.forward_button)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("postgameTime")
        self.time_label.setMinimumWidth(112)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.time_label)

        self.volume_button = QPushButton("\U0001f50a")
        self.volume_button.setObjectName("recordingPlayButton")
        self.volume_button.setFixedWidth(44)
        self.volume_button.setToolTip("Silenciar / activar audio (M)")
        self.volume_button.clicked.connect(self.toggle_muted)
        row.addWidget(self.volume_button)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("postgameVolume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setToolTip("Volumen del reproductor")
        self.volume_slider.valueChanged.connect(self.set_volume)
        row.addWidget(self.volume_slider)

        row.addStretch(1)

        self.fullscreen_button = QPushButton("⛶ Pantalla completa")
        self.fullscreen_button.setObjectName("secondaryButton")
        self.fullscreen_button.setMinimumWidth(124)
        self.fullscreen_button.setToolTip("Pantalla completa (F)")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        row.addWidget(self.fullscreen_button)
        transport.addWidget(controls)

        marker_tools = QFrame()
        marker_tools.setObjectName("postgameMarkerTools")
        tools_layout = QVBoxLayout(marker_tools)
        tools_layout.setContentsMargins(8, 5, 8, 5)
        tools_layout.setSpacing(4)

        marker_heading = QHBoxLayout()
        marker_heading.setSpacing(6)
        marker_title = QLabel("MARCADORES")
        marker_title.setObjectName("postgameMarkerTitle")
        marker_heading.addWidget(marker_title)
        etiqueta_contexto = QLabel("CONTEXTO")
        etiqueta_contexto.setObjectName("postgameMarkerContextLabel")
        marker_heading.addWidget(etiqueta_contexto)
        self.selector_contexto_cronologia = QComboBox()
        self.selector_contexto_cronologia.setObjectName("postgameTimelineContext")
        self.selector_contexto_cronologia.addItem("Jugador seleccionado", "player")
        self.selector_contexto_cronologia.addItem("Todos", "all")
        self.selector_contexto_cronologia.setToolTip(
            "Elige si la cronología muestra los sucesos del jugador o de todos."
        )
        self.selector_contexto_cronologia.setAccessibleName("Contexto de la cronología")
        marker_heading.addWidget(self.selector_contexto_cronologia)
        marker_heading.addStretch(1)
        self.marker_summary = QLabel("Sin marcadores")
        self.marker_summary.setObjectName("postgameMarkerLegend")
        self.marker_summary.setToolTip(
            "Cuenta marcadores por perspectiva mostrados en la barra; "
            "un mismo evento original puede generar una marca por participante."
        )
        marker_heading.addWidget(self.marker_summary)
        tools_layout.addLayout(marker_heading)

        self.marker_filter_scroll = QScrollArea()
        self.marker_filter_scroll.setObjectName("postgameMarkerFilterScroll")
        self.marker_filter_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.marker_filter_scroll.setWidgetResizable(True)
        self.marker_filter_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.marker_filter_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.marker_filter_scroll.setFixedHeight(32)
        marker_strip = QWidget()
        marker_strip_layout = QHBoxLayout(marker_strip)
        marker_strip_layout.setContentsMargins(0, 0, 0, 0)
        marker_strip_layout.setSpacing(4)
        self.marker_filter_buttons: dict[str, QPushButton] = {}

        for key, label, glyph, kinds in REPLAY_MARKER_GROUPS:
            button = QPushButton(f"{glyph} {label}")
            button.setObjectName("postgameMarkerFilter")
            button.setCheckable(True)
            button.setChecked(True)
            button.setToolTip(f"Mostrar u ocultar marcadores: {label.lower()}")
            button.setAccessibleName(f"Filtro de marcadores: {label}")
            button.setProperty("markerGroup", key)
            button.setMinimumHeight(25)
            button.toggled.connect(self._apply_marker_filters)
            self.marker_filter_buttons[key] = button
            marker_strip_layout.addWidget(button)

        marker_strip_layout.addStretch(1)
        self.marker_filter_scroll.setWidget(marker_strip)
        tools_layout.addWidget(self.marker_filter_scroll)
        transport.addWidget(marker_tools)

        return transport

    def _build_player(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video_widget)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(self._on_error)
        try:
            self._sync_volume_button()
        except RuntimeError:
            pass

    def _install_shortcuts(self) -> None:
        """Registra atajos únicamente en la ventana de repaso activa.

        Returns:
            None.
        """
        actions: tuple[tuple[str, Callable[[], None]], ...] = (
            ("Space", self.toggle_play),
            ("Left", lambda: self.seek_relative(-KEYBOARD_SEEK_SECONDS)),
            ("Right", lambda: self.seek_relative(KEYBOARD_SEEK_SECONDS)),
            ("M", self.toggle_muted),
            ("F", self.toggle_fullscreen),
            ("Esc", self.exit_fullscreen),
            ("Ctrl+R", self.reload_breakdown),
        )

        for sequence, slot in actions:
            shortcut_parent = self.video_widget.parentWidget() or self
            shortcut = QShortcut(QKeySequence(sequence), shortcut_parent)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda action=slot: self._run_replay_shortcut(action)
            )
            self._playback_shortcuts.append(shortcut)

    def _run_replay_shortcut(self, action: Callable[[], None]) -> None:
        """Ignora atajos si el foco está escribiendo en un control editable.

        Args:
            action: Acción de reproducción o ventana que se ejecutará.

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

    def set_volume(self, value: int) -> None:
        clamped = max(0, min(100, int(value)))
        self.audio.setVolume(clamped / 100.0)
        if clamped > 0 and self.audio.isMuted():
            self.audio.setMuted(False)
        self._sync_volume_button()

    def toggle_muted(self) -> None:
        self.audio.setMuted(not self.audio.isMuted())
        self._sync_volume_button()

    def _sync_volume_button(self) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        muted = self.audio.isMuted() or self.audio.volume() <= 0.0
        actualizar_texto_boton(self.volume_button, "🔇" if muted else "🔊")
        tip = "Activar audio (M)" if muted else "Silenciar (M)"
        self.volume_button.setToolTip(tip)

    # -- reproducción ---------------------------------------------------

    def toggle_play(self) -> None:
        if self.player.source().isEmpty():
            self.status_label.setText(
                "No hay ninguna grabación cargada en esta ventana."
            )
            return

        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek_relative(self, seconds: float) -> None:
        """Busca un desplazamiento relativo sin salir de la duración conocida.

        Args:
            seconds: Desplazamiento en segundos.

        Returns:
            None.
        """
        if self.player.source().isEmpty():
            return

        target = self.player.position() + int(seconds * 1000)
        target = max(0, target)
        duration = int(self.player.duration())

        if duration > 0:
            target = min(target, duration)

        self.player.setPosition(target)

    def seek_to_ms(self, position_ms: int) -> None:
        if self.player.source().isEmpty():
            return

        duration = max(0, self.player.duration())
        clamped = max(
            0, min(int(position_ms), duration if duration else int(position_ms))
        )
        self.player.setPosition(clamped)

    def jump_to_game_time(self, game_seconds: float) -> None:
        """Salta al momento del vídeo correspondiente al marcador elegido.

        Args:
            game_seconds: Tiempo de partida del marcador.

        Returns:
            None.
        """
        video_position_ms = game_time_to_video_position_ms(
            game_seconds, self.game_time_offset
        )
        video_seconds = video_position_ms / 1000
        self.seek_to_ms(video_position_ms)
        self.status_label.setText(
            f"Saltando a {format_duration(video_seconds)} del vídeo "
            f"(minuto {format_duration(game_seconds)} de partida)."
        )

    def toggle_fullscreen(self) -> None:
        if self._fs_window is not None and self._fs_window.isVisible():
            self.exit_fullscreen()
        else:
            self._enter_video_fullscreen()

    def _enter_video_fullscreen(self) -> None:
        """Pantalla completa del vídeo CON la barra de reproducción visible.

        El vídeo, la barra de marcadores y la fila de transporte se mueven a
        una ventana dedicada sin bordes. Como son los mismos widgets, los
        indicadores, el tiempo y el estado de reproducción se conservan: se
        puede mover por el vídeo igual que en la ventana normal (con F, Esc,
        doble clic o el botón «Salir de pantalla completa»).
        """
        window = self._ensure_fullscreen_window()
        self._fs_video_host.layout().addWidget(self.video_widget)
        self._fs_bar_layout.addWidget(self.marker_slider)
        self._fs_bar_layout.addWidget(self.transport_row)
        window.showFullScreen()
        window.activateWindow()
        self.video_widget.setFocus(Qt.FocusReason.OtherFocusReason)
        self.fullscreen_button.setText("⛶ Salir de pantalla completa")

    def _ensure_fullscreen_window(self) -> QWidget:
        """Crea (una sola vez) la ventana de pantalla completa del vídeo."""
        if self._fs_window is not None:
            return self._fs_window

        window = QWidget(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        window.setObjectName("postgameFullscreenWindow")
        window.setWindowTitle("Repaso de partida · pantalla completa")
        aplicar_tema(window)

        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        host = QWidget()
        host.setObjectName("postgameFullscreenVideoHost")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        layout.addWidget(host, 1)

        bar = QFrame()
        bar.setObjectName("postgameFullscreenBar")
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(18, 10, 18, 12)
        bar_layout.setSpacing(6)
        layout.addWidget(bar)

        self._fs_window = window
        self._fs_video_host = host
        self._fs_bar_layout = bar_layout
        actions: tuple[tuple[str, Callable[[], None]], ...] = (
            ("Space", self.toggle_play),
            ("Left", lambda: self.seek_relative(-KEYBOARD_SEEK_SECONDS)),
            ("Right", lambda: self.seek_relative(KEYBOARD_SEEK_SECONDS)),
            ("M", self.toggle_muted),
            ("F", self.toggle_fullscreen),
            ("Esc", self.exit_fullscreen),
            ("Ctrl+R", self.reload_breakdown),
        )

        for sequence, action in actions:
            shortcut = QShortcut(QKeySequence(sequence), window)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(
                lambda callback=action: self._run_replay_shortcut(callback)
            )
            self._fullscreen_shortcuts.append(shortcut)

        return window

    def exit_fullscreen(self) -> None:
        """Devuelve vídeo y controles a la ventana de repaso.

        Returns:
            None.
        """
        if self._fs_window is not None and self._fs_window.isVisible():
            self._fs_window.hide()
            self._card_layout.insertWidget(0, self.video_widget, 1)
            self._card_layout.addWidget(self.marker_slider)
            self._card_layout.addWidget(self.transport_row)
            self.fullscreen_button.setText("⛶ Pantalla completa")
            self.raise_()
            self.activateWindow()
            self.video_widget.setFocus(Qt.FocusReason.OtherFocusReason)
        elif self.isFullScreen():
            self.showNormal()

    def open_in_explorer(self) -> None:
        path = self.video_path

        if path is None:
            directory = self.library.directory
        else:
            directory = path.parent

        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.status_label.setText(f"No se pudo preparar la carpeta {directory}.")
            return

        from app.ui.recordings_page import RecordingsPage

        RecordingsPage.open_in_explorer(str(directory))

    # -- señales del reproductor ---------------------------------------

    def _on_position(self, position_ms: int) -> None:
        if not self.marker_slider.isSliderDown():
            self.marker_slider.setValue(int(position_ms))

        self.time_label.setText(
            f"{format_duration(position_ms / 1000.0)} / "
            f"{format_duration(self.player.duration() / 1000.0)}"
        )

    def _on_duration(self, duration_ms: int) -> None:
        self.marker_slider.setRange(0, int(max(1, duration_ms)))
        self.marker_slider.set_markers(self.markers, int(duration_ms))
        self._pending_seek_ms = min(self._pending_seek_ms, int(duration_ms))

        if self._pending_seek_ms > 0:
            self.seek_to_ms(self._pending_seek_ms)
            self._pending_seek_ms = 0

    def _on_state(self, state: QMediaPlayer.PlaybackState) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        actualizar_texto_boton(
            self.play_button, "⏸" if state == QMediaPlayer.PlayingState else "▶"
        )

    def _on_error(self, error: Any, message: str = "") -> None:
        if error == QMediaPlayer.Error.NoError:
            return

        self.status_label.setText(
            f"No se pudo reproducir la grabación ({message or 'formato no soportado'})."
        )

    # -- datos de la partida -------------------------------------------

    def _load_metadata(self, path: Path | None) -> dict[str, Any]:
        if path is None:
            return {}

        try:
            data = self.library.load_metadata(path)
        except (OSError, ValueError):
            return {}

        return data if isinstance(data, dict) else {}

    def video_for_session(self, session: dict[str, Any] | None) -> Path | None:
        """Grabación que corresponde a esa sesión.

        Empareja por ``session_id`` del sidecar y, si ningún sidecar lo
        declara (sidecars antiguos), por ventana temporal entre el inicio
        del vídeo y ``started_at``/``ended_at`` de la sesión. Si nada
        coincide, se devuelve la más reciente de la carpeta.
        """
        videos = self.library.video_files()

        if not videos:
            return None

        found = find_video_for_session(
            videos,
            session if isinstance(session, dict) else None,
            self._load_metadata,
        )

        return found if found is not None else videos[-1]

    def _session_from_disk(self) -> dict[str, Any]:
        """Sesión guardada en disco, la versión más actualizada posible.

        Orden de búsqueda: por ``session_id`` (sidecar o sesión ya cargada)
        y, si no hay id —o el disco no la conoce—, por ventana temporal
        entre el inicio del vídeo y las marcas de la sesión. Los sidecars
        antiguos no guardan ``session_id``: el inicio del vídeo y de la
        sesión difieren en milisegundos, así que el emparejamiento temporal
        es fiable y preferible a caer en la reconstrucción del sidecar.
        """
        wanted = str(self.session.get("session_id") or "") or str(
            self.metadata.get("session_id") or ""
        )
        sessions = self._saved_sessions()

        if wanted:
            best = self._best_session_by_id(sessions, wanted)

            if best:
                return best

        matched = self._session_by_time_window(sessions)

        if matched:
            return matched

        return self._session_from_metadata()

    def _saved_sessions(self) -> list[dict[str, Any]]:
        """Sesiones del tracker o, en su ausencia, del fichero en disco."""
        tracker = self.tracker

        if tracker is not None:
            try:
                sessions = tracker.load_saved_sessions()
            except (OSError, ValueError, AttributeError):
                sessions = []
            else:
                return sessions if isinstance(sessions, list) else []

        # Ventana de repaso abierta sin tracker (ventana suelta o tests): se
        # lee el fichero del tracker directamente para no perder la
        # telemetría local de la partida. Solo se lee si hay algo que
        # emparejar (id o marca temporal); si no, la lectura no aporta nada.
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        can_match = (
            str(self.session.get("session_id") or "")
            or str(metadata.get("session_id") or "")
            or str(metadata.get("started_at") or "")
        )

        if not can_match:
            return []

        try:
            from app.services.live_match_tracker import LiveMatchTracker

            reader = LiveMatchTracker(item_catalog={})
        except (ImportError, TypeError):
            return []

        try:
            sessions = reader.load_saved_sessions()
        except (OSError, ValueError):
            return []

        return sessions if isinstance(sessions, list) else []

    @staticmethod
    def _session_event_count(session: Any) -> int:
        try:
            return len(session.get("events") or [])
        except (TypeError, AttributeError):
            return 0

    def _best_session_by_id(
        self,
        sessions: list[dict[str, Any]],
        wanted: str,
    ) -> dict[str, Any]:
        """Copia más completa de la sesión con ese id.

        Hay partidas guardadas dos veces en disco (mismo arranque, dos
        copias): se usa la copia con más eventos, no la primera vacía.
        """
        best: dict[str, Any] = {}
        best_events = -1

        for session in sessions:
            if not isinstance(session, dict):
                continue

            if str(session.get("session_id") or "") != wanted:
                continue

            count = self._session_event_count(session)

            if count >= best_events:
                best = session
                best_events = count

        return best

    def _session_by_time_window(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        """Sesión cuya ventana temporal contiene el inicio del vídeo.

        Se prefiere la misma campeona, después la copia con más sucesos y
        por último el arranque más cercano al del vídeo (así, de dos copias
        duplicadas de la misma partida, gana la buena).
        """
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        video_start = parse_iso_timestamp(
            metadata.get("started_at") or metadata.get("recorded_at")
        )

        if video_start is None:
            return {}

        champion = str(metadata.get("champion") or "").strip().casefold()
        margin = abs(SESSION_VIDEO_TOLERANCE_SECONDS)
        best: dict[str, Any] = {}
        best_score: tuple[int, int, float] | None = None

        for session in sessions:
            if not isinstance(session, dict):
                continue

            start = parse_iso_timestamp(session.get("started_at"))

            if start is None:
                continue

            end = parse_iso_timestamp(session.get("ended_at"))
            inside = abs((video_start - start).total_seconds()) <= margin or (
                end is not None
                and start <= video_start <= end + timedelta(seconds=margin)
            )

            if not inside:
                continue

            same_champion = int(
                bool(champion)
                and str(session.get("champion_name") or "").strip().casefold()
                == champion
            )
            count = self._session_event_count(session)
            closeness = -abs((video_start - start).total_seconds())
            score = (same_champion, count, closeness)

            if best_score is None or score > best_score:
                best = session
                best_score = score

        return best

    @staticmethod
    def _session_richness(
        session: dict[str, Any] | None,
    ) -> tuple[int, int, int]:
        """Volumen de datos útiles: jugadores, sucesos y snapshots."""
        data = session if isinstance(session, dict) else {}

        def count(key: str) -> int:
            value = data.get(key)

            try:
                return len(value)
            except TypeError:
                return 0

        return (count("players"), count("events"), count("snapshots"))

    def _adopt_session_for_video(self) -> None:
        """Adopta la mejor sesión conocida para el vídeo cargado.

        Combina el sidecar (eventos reconstruidos de los ``markers``) con
        la sesión completa del tracker en disco y se queda con la que más
        datos aporte. Nunca mezcla partidas distintas: si la sesión actual
        y el candidato declaran ids diferentes, el candidato se descarta.
        """
        candidate = self._session_from_disk()

        if not candidate:
            return

        current_id = str(self.session.get("session_id") or "")
        candidate_id = str(candidate.get("session_id") or "")

        if current_id and candidate_id and current_id != candidate_id:
            return

        if self._session_richness(candidate) <= self._session_richness(self.session):
            return

        self.session = candidate
        self.sidebar.set_session(self.session)
        self._sync_ai_review_tab()

    def _session_from_metadata(self) -> dict[str, Any]:
        """Sesión descrita por el sidecar del vídeo (si trae eventos).

        Los sidecars antiguos no traen ``events`` pero sí ``markers`` (ya
        calculados al cerrar la grabación): en ese caso se reconstruyen
        pseudo-eventos para que la pestaña Revisión no quede en (0) aunque
        la sesión de disco ya no exista o esté duplicada.
        """
        metadata = self.metadata if isinstance(self.metadata, dict) else {}
        events = metadata.get("events")

        if not isinstance(events, list) or not events:
            events = self._events_from_metadata_markers(metadata)

        if not events:
            return {}

        session: dict[str, Any] = {
            "session_id": str(metadata.get("session_id") or ""),
            "started_at": str(metadata.get("started_at") or ""),
            "ended_at": str(metadata.get("ended_at") or ""),
            "champion_name": str(
                metadata.get("champion") or metadata.get("champion_name") or ""
            ),
            "game_mode": str(metadata.get("game_mode") or ""),
            "duration": metadata.get("game_duration_seconds")
            or metadata.get("duration_seconds")
            or 0.0,
            "local_player_key": str(metadata.get("local_player_key") or ""),
            "local_team": str(metadata.get("local_team") or ""),
            "players": (
                metadata.get("players")
                if isinstance(metadata.get("players"), dict)
                else {}
            ),
            "events": events,
            "snapshots": (
                metadata.get("snapshots")
                if isinstance(metadata.get("snapshots"), list)
                else []
            ),
            "final_sync": (
                metadata.get("final_sync")
                if isinstance(metadata.get("final_sync"), dict)
                else {}
            ),
        }

        if isinstance(metadata.get("lane_matchups"), dict):
            session["lane_matchups"] = metadata["lane_matchups"]

        return session

    @staticmethod
    def _events_from_metadata_markers(
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Reconstruye eventos conservando la categoría del sidecar.

        Args:
            metadata: Metadatos persistidos junto al vídeo.

        Returns:
            Eventos tipados disponibles en el sidecar.
        """
        markers = metadata.get("markers")
        if not isinstance(markers, list) or not markers:
            return []

        local_key = str(metadata.get("local_player_key") or "")
        team = str(metadata.get("local_team") or "")
        events: list[dict[str, Any]] = []

        for order, marker in enumerate(markers):
            if not isinstance(marker, dict):
                continue

            kind = str(marker.get("category") or marker.get("kind") or "")
            kind = normalise_marker_kind(kind)

            if kind not in MARKER_LABELS:
                continue

            marker_player_key = str(marker.get("player_key") or local_key)

            try:
                moment = float(marker.get("time") or 0.0)
            except (TypeError, ValueError):
                moment = 0.0

            label = str(marker.get("detail") or marker.get("label") or kind)
            marker_team = str(marker.get("team") or marker.get("objective_team") or "")
            objective_name = str(
                marker.get("objective")
                or marker.get("objective_label")
                or ("" if kind in ("kill", "death", "assist") else kind)
            )

            if kind in ("kill", "death", "assist"):
                events.append(
                    {
                        "time": moment,
                        "order": order,
                        "type": kind,
                        "category": kind,
                        "event_id": marker.get("source_event_id"),
                        "player_key": marker_player_key or None,
                        "team": marker_team or team,
                        "objective_team": marker_team or "",
                        "label": label,
                    }
                )
            elif kind:
                events.append(
                    {
                        "time": moment,
                        "order": order,
                        "type": "objective",
                        "objective": objective_name or kind,
                        "objective_label": objective_name,
                        "player_key": None,
                        "team": marker_team or team,
                        "objective_team": marker_team or team,
                        "label": label,
                    }
                )

        return events

    def _build_markers(self) -> list[dict[str, Any]]:
        """Indicadores de la barra según el contexto activo.

        Si existe un desglose, incluso una perspectiva vacía es definitiva y
        no se reemplaza por sucesos globales del sidecar.
        """
        sidebar = getattr(self, "sidebar", None)
        review = getattr(sidebar, "review_markers", None)

        if callable(review):
            try:
                markers = review(self.game_time_offset)
            except (TypeError, ValueError, AttributeError):
                markers = []

            return markers

        markers = []

        if self.session:
            try:
                markers = build_markers(self.session, self.game_time_offset)
            except (TypeError, ValueError):
                markers = []

        if markers:
            return markers

        stored = self.metadata.get("markers")

        return stored if isinstance(stored, list) else []

    def _refresh_header(self) -> None:
        champion = str(self.session.get("champion_name") or "").strip()
        mode = str(self.session.get("game_mode") or "").strip()
        duration = float(self.metadata.get("duration_seconds") or 0)
        pieces = []

        if champion:
            pieces.append(champion)

        if mode and mode != "UNKNOWN":
            pieces.append(mode.replace("_", " ").title())

        if duration:
            pieces.append(format_duration(duration))

        self.title_label.setText(champion or "Repaso de partida")
        self.subtitle_label.setText(
            " · ".join(pieces[1:]) if pieces else "Sin metadatos de partida"
        )

        final_sync = self.session.get("final_sync")
        status = ""

        if isinstance(final_sync, dict):
            status = str(final_sync.get("status") or "")

        self.badge.setText(
            "RIOT SINCRONIZADO" if status == "synced" else "TELEMETRÍA LIVE LOCAL"
        )
        self.badge.setProperty("state", status or "live")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

    def _refresh_markers(self) -> None:
        """Reconstruye marcadores al cambiar la partida o el filtro de revisión.

        Returns:
            None.
        """
        self._sync_timeline_context()
        self.markers = self._build_markers()

        self._apply_marker_filters()

    def _sync_timeline_context(self) -> None:
        """Sincroniza el selector con el alcance activo del desglose.

        Returns:
            None.
        """
        sidebar = getattr(self, "sidebar", None)
        alcance = getattr(sidebar, "scope", PostgameSidebar.SCOPE_PLAYER)
        indice = self.selector_contexto_cronologia.findData(alcance)

        if indice >= 0 and self.selector_contexto_cronologia.currentIndex() != indice:
            self.selector_contexto_cronologia.blockSignals(True)
            self.selector_contexto_cronologia.setCurrentIndex(indice)
            self.selector_contexto_cronologia.blockSignals(False)

    def _on_timeline_context_changed(self, indice: int) -> None:
        """Cambia el alcance de eventos compartido con la pestaña Revisión.

        Args:
            indice: Índice seleccionado en el selector de contexto.

        Returns:
            None.
        """
        alcance = str(self.selector_contexto_cronologia.itemData(indice) or "player")
        self.sidebar.set_scope(alcance)

    def _apply_marker_filters(self) -> None:
        """Aplica las categorías activas a los marcadores ya preparados.

        Returns:
            None.
        """
        duration_ms = self.player.duration()
        stored = float(self.metadata.get("duration_seconds") or 0) * 1000

        if duration_ms <= 0 and stored > 0:
            duration_ms = int(stored)

        active_categories = {
            category
            for category, button in self.marker_filter_buttons.items()
            if button.isChecked()
        }
        visibles = filter_replay_markers(self.markers, active_categories)
        self.marker_slider.set_markers(visibles, int(duration_ms))
        self.marker_summary.setText(
            marker_filter_summary(self.markers, active_categories)
        )

    # -- API pública ----------------------------------------------------

    def load_video(self, path: str | Path) -> None:
        """Carga un vídeo en el reproductor y lo deja listo para ver."""
        target = Path(path)

        if not target.is_file():
            self.status_label.setText(f"No se encontró el vídeo {target.name}.")
            return

        self.video_path = target
        self.player.stop()
        self.player.setSource(QUrl())
        self.metadata = self._load_metadata(target)
        self.game_time_offset = float(self.metadata.get("game_time_offset") or 0.0)
        # El sidecar puede traer la partida (eventos, jugador local...) y el
        # tracker la sesión completa en disco: se toma la más rica de las
        # dos, sin mezclar partidas distintas.
        self._adopt_session_for_video()
        self.player.setSource(QUrl.fromLocalFile(str(target)))
        self.player.pause()
        self._pending_seek_ms = 0
        self._refresh_header()
        self._refresh_markers()
        self.status_label.setText(
            f"Reproduciendo {target.name}. Pulsa los indicadores de la "
            "barra para saltar a cada suceso."
        )

    def set_session(self, session: dict[str, Any] | None) -> None:
        """Cambia la sesión analizada (y recarga el vídeo si hace falta)."""
        self.session = session if isinstance(session, dict) else {}
        self.sidebar.set_session(self.session)
        self._refresh_header()
        self._refresh_markers()
        self._sync_ai_review_tab()

        if self.video_path is None:
            found = self.video_for_session(self.session)

            if found is not None:
                self.load_video(found)

    def update_session(self, session: dict[str, Any] | None) -> None:
        """Alias en vivo: mismos datos/timers que el diálogo LIVE."""
        self.set_session(session)

    def reload_breakdown(self, first_load: bool = False, **kwargs: Any) -> None:
        """Reconstruye el desglose con la telemetría LOCAL de la sesión.

        Se recarga la sesión de disco (por si acaba de sincronizarse con la
        Riot API) y se vuelven a calcular marcador, radar y timeline. Los
        números siguen saliendo siempre de los datos locales.
        """
        self.metadata = self._load_metadata(self.video_path)
        # «Re-desglosar» vuelve a consultar disco/sidecar, pero solo adopta
        # la sesión que aporte MÁS datos y sea la MISMA partida (ids
        # coincidentes o emparejada por tiempo): así nunca se pisa la sesión
        # viva del diálogo LIVE ni se mezclan partidas distintas.
        self._adopt_session_for_video()
        self.game_time_offset = float(self.metadata.get("game_time_offset") or 0.0)
        self.sidebar.set_session(self.session)
        self._refresh_header()
        self._refresh_markers()
        self._sync_ai_review_tab()

        if self.video_path is None:
            self.video_path = self.video_for_session(self.session)

        needs_load = self.video_path is not None and str(
            self.player.source().toLocalFile() or ""
        ) != str(self.video_path)

        if first_load and needs_load:
            self.load_video(self.video_path)
            return

        summary = self.sidebar.summary_text()
        self.status_label.setText(
            "Desglose reconstruido con la telemetría local"
            + (f" · {summary}" if summary else "")
        )

    # -- cierre ---------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        try:
            self.exit_fullscreen()
        except RuntimeError:
            pass

        fs_window = self._fs_window

        if fs_window is not None:
            if fs_window.isVisible() and self._card_layout is not None:
                # Salvavidas: devuelve el vídeo a la tarjeta antes de cerrar.
                fs_window.hide()
                self._card_layout.addWidget(self.video_widget)

            fs_window.close()
            self._fs_window = None
            self._fs_video_host = None
            self._fs_bar_layout = None

        try:
            self.player.stop()
            self.player.setSource(QUrl())
        except RuntimeError:
            pass

        self.closed.emit()
        super().closeEvent(event)
