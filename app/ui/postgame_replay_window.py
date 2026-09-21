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

from datetime import timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.services.recording_service import (
    SESSION_VIDEO_TOLERANCE_SECONDS,
    RecordingLibrary,
    build_markers,
    find_video_for_session,
    format_duration,
    parse_iso_timestamp,
)
from app.ui.postgame_sidebar import PostgameSidebar
from app.ui.recordings_page import MarkerSlider
from app.ui.styles import CONTROL_WINDOW_STYLE

#: Segundos que retrocede/avanza cada botón de salto.
SEEK_SECONDS = 10


class ReplayVideoWidget(QVideoWidget):
    """Vídeo que alterna la pantalla completa con doble clic."""

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt
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
        self.setMinimumHeight(48)
        self.set_show_marker_glyphs(True)


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
        super().__init__(parent)
        self.setObjectName("postgameReplayWindow")
        self.setWindowTitle("Repaso de partida · SolraLol")
        self.resize(1520, 900)
        self.setMinimumSize(1120, 700)

        self.session: dict[str, Any] = (
            session if isinstance(session, dict) else {}
        )
        self.video_path: Path | None = (
            Path(video_path) if video_path else None
        )
        self.library = library if library is not None else RecordingLibrary()
        self.tracker = tracker
        self.service = service
        self.assets = assets
        self.item_catalog = (
            item_catalog if isinstance(item_catalog, dict) else {}
        )
        self.game_time_offset = 0.0
        self.metadata: dict[str, Any] = {}
        self.markers: list[dict[str, Any]] = []
        self._pending_seek_ms = 0
        self.live_view: Any | None = None
        self._live_tab_index = -1
        # Ventana dedicada para la pantalla completa del vídeo (con la barra
        # de reproducción dentro); se crea la primera vez que se pide.
        self._fs_window: QWidget | None = None
        self._fs_video_host: QWidget | None = None
        self._fs_bar_layout: QVBoxLayout | None = None
        self._card_layout: QVBoxLayout | None = None

        self._build_ui()
        self._build_player()
        self._install_shortcuts()
        self.setStyleSheet(CONTROL_WINDOW_STYLE)

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
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        layout.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("postgameSplitter")
        splitter.addWidget(self._build_video_column())
        self.sidebar = PostgameSidebar(self.session or None)
        self.sidebar.setMinimumWidth(430)
        self.sidebar.event_activated.connect(self.jump_to_game_time)
        try:
            self.sidebar.events_changed.connect(self._refresh_markers)
        except (AttributeError, RuntimeError, TypeError):
            pass
        splitter.addWidget(self.sidebar)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([960, 580])
        layout.addWidget(splitter, 1)

        self.status_label = QLabel("Selecciona una grabación para verla.")
        self.status_label.setObjectName("postgameStatus")
        layout.addWidget(self.status_label)

        self._ensure_live_tab()

    def _ensure_live_tab(self) -> None:
        """Inserta las pantallas del análisis LIVE como pestaña del repaso.

        Reutiliza ``LiveMatchAnalysisDialog`` (mismos datos, mismos timers y
        mismas pantallas: roles, recomendaciones e IA) pero sin abrir un
        diálogo aparte: su contenido vive en una pestaña «Análisis LIVE».
        """
        if self._live_tab_index >= 0 and self.live_view is not None:
            return

        if self.assets is None:
            return

        try:
            from app.ui.live_match_analysis_dialog import (
                LiveMatchAnalysisDialog,
            )
        except ImportError:
            return

        tabs = getattr(self.sidebar, "tabs", None)
        if tabs is None:
            return

        try:
            view = LiveMatchAnalysisDialog(
                dict(self.session or {}),
                self.assets,
                dict(self.item_catalog or {}),
                self,
            )
        except (RuntimeError, TypeError, ValueError):
            return

        # Sin botones de ventana: el contenido pasa a ser una pestaña más.
        # QDialog también es un QWidget, así que puede vivir incrustado
        # directamente como página del QTabWidget (ya no es una ventana).
        try:
            view.setWindowFlags(Qt.Widget)
            view.setParent(self.sidebar)
        except RuntimeError:
            return

        for button in view.findChildren(QPushButton):
            text = str(button.text() or "").strip().lower()
            if text == "cerrar":
                button.setVisible(False)

        self.live_view = view
        self._live_tab_index = tabs.addTab(view, "Análisis LIVE")

    def _sync_live_tab(self) -> None:
        """Propaga la sesión del repaso a la pestaña LIVE (datos + timers)."""
        view = self.live_view
        if view is None:
            self._ensure_live_tab()
            view = self.live_view

        if view is None:
            return

        try:
            view.update_session(dict(self.session or {}))
        except RuntimeError:
            pass

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("postgameHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)

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
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        self._card_layout = layout

        self.video_widget = ReplayVideoWidget()
        self.video_widget.setObjectName("postgameVideo")
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.video_widget.setMinimumHeight(320)
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

    def _build_transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.back_button = QPushButton("⏪ 10 s")
        self.back_button.setObjectName("recordingPlayButton")
        self.back_button.setToolTip("Retroceder 10 segundos")
        self.back_button.clicked.connect(
            lambda: self.seek_relative(-SEEK_SECONDS)
        )
        row.addWidget(self.back_button)

        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("recordingPlayButton")
        self.play_button.setFixedWidth(64)
        self.play_button.setToolTip("Reproducir / pausar (Espacio)")
        self.play_button.clicked.connect(self.toggle_play)
        row.addWidget(self.play_button)

        self.forward_button = QPushButton("10 s ⏩")
        self.forward_button.setObjectName("recordingPlayButton")
        self.forward_button.setToolTip("Avanzar 10 segundos")
        self.forward_button.clicked.connect(
            lambda: self.seek_relative(SEEK_SECONDS)
        )
        row.addWidget(self.forward_button)

        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("postgameTime")
        row.addWidget(self.time_label)

        row.addStretch(1)

        self.marker_summary = QLabel("Sin marcadores")
        self.marker_summary.setObjectName("postgameMarkerLegend")
        row.addWidget(self.marker_summary)

        self.fullscreen_button = QPushButton("⛶ Pantalla completa")
        self.fullscreen_button.setObjectName("secondaryButton")
        self.fullscreen_button.setToolTip("Pantalla completa (F)")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        row.addWidget(self.fullscreen_button)

        return row

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

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("Space", self.toggle_play),
            ("Left", lambda: self.seek_relative(-SEEK_SECONDS)),
            ("Right", lambda: self.seek_relative(SEEK_SECONDS)),
            ("F", self.toggle_fullscreen),
            ("Esc", self.exit_fullscreen),
            ("Ctrl+R", self.reload_breakdown),
        )

        for sequence, slot in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(slot)
            # Cuando el vídeo está en pantalla completa vive en su propia
            # ventana de nivel superior: los atajos de la ventana principal
            # no llegan, así que se duplican sobre el propio widget.
            mirror = QShortcut(QKeySequence(sequence), self.video_widget)
            mirror.activated.connect(slot)

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
        if self.player.source().isEmpty():
            return

        target = self.player.position() + int(seconds * 1000)
        target = max(0, min(target, max(0, self.player.duration())))
        self.player.setPosition(target)

    def seek_to_ms(self, position_ms: int) -> None:
        if self.player.source().isEmpty():
            return

        duration = max(0, self.player.duration())
        clamped = max(0, min(int(position_ms), duration if duration else int(position_ms)))
        self.player.setPosition(clamped)

    def jump_to_game_time(self, game_seconds: float) -> None:
        """Salta al momento del vídeo correspondiente a ese segundo de juego."""
        video_seconds = max(0.0, float(game_seconds) - self.game_time_offset)
        self.seek_to_ms(int(video_seconds * 1000))
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
        self.fullscreen_button.setText("⛶ Salir de pantalla completa")

    def _ensure_fullscreen_window(self) -> QWidget:
        """Crea (una sola vez) la ventana de pantalla completa del vídeo."""
        if self._fs_window is not None:
            return self._fs_window

        window = QWidget(
            None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        window.setObjectName("postgameFullscreenWindow")
        window.setWindowTitle("Repaso de partida · pantalla completa")
        window.setStyleSheet(CONTROL_WINDOW_STYLE)

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

        return window

    def exit_fullscreen(self) -> None:
        if self._fs_window is not None and self._fs_window.isVisible():
            self._fs_window.hide()
            self._card_layout.insertWidget(0, self.video_widget, 1)
            self._card_layout.addWidget(self.marker_slider)
            self._card_layout.addWidget(self.transport_row)
            self.fullscreen_button.setText("⛶ Pantalla completa")
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
            self.status_label.setText(
                f"No se pudo preparar la carpeta {directory}."
            )
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
        self.play_button.setText(
            "⏸" if state == QMediaPlayer.PlayingState else "▶"
        )

    def _on_error(self, error: Any, message: str = "") -> None:
        if error == QMediaPlayer.Error.NoError:
            return

        self.status_label.setText(
            "No se pudo reproducir la grabación "
            f"({message or 'formato no soportado'})."
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

    def video_for_session(
        self, session: dict[str, Any] | None
    ) -> Path | None:
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

    def _session_by_time_window(
        self, sessions: list[dict[str, Any]]
    ) -> dict[str, Any]:
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
            inside = (
                abs((video_start - start).total_seconds()) <= margin
                or (
                    end is not None
                    and start <= video_start <= end + timedelta(seconds=margin)
                )
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

        if self._session_richness(candidate) <= self._session_richness(
            self.session
        ):
            return

        self.session = candidate
        self.sidebar.set_session(self.session)
        self._sync_live_tab()

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
        """Reconstruye eventos desde los ``markers`` del sidecar."""
        markers = metadata.get("markers")
        if not isinstance(markers, list) or not markers:
            return []

        local_key = str(metadata.get("local_player_key") or "")
        team = str(metadata.get("local_team") or "")
        events: list[dict[str, Any]] = []

        for order, marker in enumerate(markers):
            if not isinstance(marker, dict):
                continue

            kind = str(marker.get("kind") or "")

            try:
                moment = float(marker.get("time") or 0.0)
            except (TypeError, ValueError):
                moment = 0.0

            label = str(
                marker.get("detail") or marker.get("label") or kind
            )
            marker_team = str(
                marker.get("team") or marker.get("objective_team") or ""
            )
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
                        "player_key": local_key or None,
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
        """Indicadores de la barra: filtro de la revisión primero.

        Los marcadores reflejan los sucesos de ``sidebar.review_markers()``
        (jugador y alcance elegidos en la pestaña Revisión): si se elige un
        campeón o "Todos", la barra muestra esos mismos sucesos. Solo cuando
        la revisión está vacía se recurre a los marcadores de la sesión local
        y, en última instancia, al sidecar del vídeo.
        """
        sidebar = getattr(self, "sidebar", None)
        review = getattr(sidebar, "review_markers", None)

        if callable(review):
            try:
                markers = review(self.game_time_offset)
            except (TypeError, ValueError, AttributeError):
                markers = []

            if markers:
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
            "RIOT SINCRONIZADO"
            if status == "synced"
            else "TELEMETRÍA LIVE LOCAL"
        )
        self.badge.setProperty("state", status or "live")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)

    def _refresh_markers(self) -> None:
        self.markers = self._build_markers()
        duration_ms = self.player.duration()
        stored = float(self.metadata.get("duration_seconds") or 0) * 1000

        if duration_ms <= 0 and stored > 0:
            duration_ms = int(stored)

        self.marker_slider.set_markers(self.markers, int(duration_ms))
        kinds = sorted(
            {str(marker.get("kind") or "") for marker in self.markers} - {""}
        )

        if self.markers:
            from app.services.recording_service import MARKER_LABELS

            readable = ", ".join(
                MARKER_LABELS.get(kind, kind) for kind in kinds
            )
            self.marker_summary.setText(
                f"{len(self.markers)} marcador(es) · {readable}"
            )
        else:
            self.marker_summary.setText("Sin marcadores")

    # -- API pública ----------------------------------------------------

    def load_video(self, path: str | Path) -> None:
        """Carga un vídeo en el reproductor y lo deja listo para ver."""
        target = Path(path)

        if not target.is_file():
            self.status_label.setText(
                f"No se encontró el vídeo {target.name}."
            )
            return

        self.video_path = target
        self.player.stop()
        self.player.setSource(QUrl())
        self.metadata = self._load_metadata(target)
        self.game_time_offset = float(
            self.metadata.get("game_time_offset") or 0.0
        )
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
        self._sync_live_tab()

        if self.video_path is None:
            found = self.video_for_session(self.session)

            if found is not None:
                self.load_video(found)

    def update_session(self, session: dict[str, Any] | None) -> None:
        """Alias en vivo: mismos datos/timers que el diálogo LIVE."""
        self.set_session(session)

    def reload_breakdown(
        self, first_load: bool = False, **kwargs: Any
    ) -> None:
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
        self.game_time_offset = float(
            self.metadata.get("game_time_offset") or 0.0
        )
        self.sidebar.set_session(self.session)
        self._refresh_header()
        self._refresh_markers()
        self._sync_live_tab()

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
