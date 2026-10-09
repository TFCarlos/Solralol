from __future__ import annotations

import logging
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QPainter,
    QPainterPath,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.data_dragon_assets import (
    DataDragonAssetService,
)
from app.services.game_calculator import get_inventory_value
from app.services.home_history_service import (
    HomeHistoryRepository,
    LCUHomeProvider,
    analyze_home_history,
)
from app.services.live_data_worker import LiveDataWorker
from app.services.live_match_tracker import (
    LiveMatchTracker,
)
from app.services.postgame_lcu_sync import (
    RETRASOS_REINTENTO_LCU,
    actualizar_estado_sync_final,
    conservar_enriquecimiento_final,
    contador_intentos_lcu,
    historial_contiene_enlace,
    marcar_sincronizacion_lcu_completa,
    marcar_sincronizacion_lcu_pendiente,
    reconciliar_puntuaciones_home,
    siguiente_retraso_lcu,
)
from app.services.postgame_sync_worker import (
    PostgameSyncWorker,
)
from app.services.recording_service import (
    AUDIO_MODE_LABELS,
    AUDIO_MODES,
    BITRATE_PRESETS,
    DEFAULT_BITRATE,
    LIMIT_DEFAULT_GB,
    LIMIT_MAX_GB,
    LIMIT_MIN_GB,
    RecordingConfig,
    RecordingLibrary,
    RecordingService,
    audio_mode_label,
    audio_mode_uses_game,
    audio_mode_uses_mic,
    audio_mode_uses_system,
    bitrate_label,
    find_ffmpeg,
    find_video_for_session,
    format_size,
    list_audio_devices,
    normalize_audio_mode,
    pick_game_audio_device,
    pick_microphone_device,
    pick_system_audio_device,
    quality_label,
    recording_settings_defaults,
)
from app.services.resumen_rendimiento_historial import (
    asegurar_puntuacion_guardada,
    etiqueta_puntuacion,
    resumen_puntuacion_local,
)
from app.services.settings_service import SettingsService
from app.services.tab_hotkey_service import TabHotkeyService
from app.ui.async_task import AsyncTask, run_async
from app.ui.barra_lateral import BarraLateral
from app.ui.champ_select_worker import ChampSelectWorker
from app.ui.champion_card import CARD_MAX_HEIGHT, ChampionCard
from app.ui.componentes_visuales import Interruptor, PaginaDesplazable
from app.ui.draft_tool_dialog import DraftToolDialog
from app.ui.live_match_analysis_dialog import (
    LiveMatchAnalysisDialog,
)
from app.ui.local_analysis_dialog import LocalAnalysisDialog
from app.ui.overlay_window import OverlayWindow
from app.ui.postgame_replay_window import PostgameReplayWindow  # noqa: E402
from app.ui.recordings_page import RecordingsPage  # noqa: E402
from app.ui.sistema_visual import PALETA
from app.ui.superficies_analisis import FondoTecnologico, IconoRedondeado
from app.ui.tema import aplicar_tema

#: Ancho común para todos los botones de acción de una fila de
#: «Partidas guardadas»: así los cuatro ocupan exactamente lo mismo.
ROW_BUTTON_WIDTH = 145


class Backdrop(FondoTecnologico):
    """Fondo abstracto compartido del shell, sin ilustraciones de fondo."""


class TarjetaPartidaGuardada(QFrame):
    """Contenedor de partida guardada con barra de acento semántica y fondo sutil."""

    def __init__(
        self, result_state: str = "unknown", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.result_state = result_state
        self.setObjectName("savedGameRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event: Any) -> None:
        """Pinta el acento de resultado recortado al interior redondeado.

        Args:
            event: evento de repintado de Qt.

        Returns:
            None.
        """
        super().paintEvent(event)
        if self.result_state not in ("win", "loss"):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color_hex = (
            PALETA["ventaja"] if self.result_state == "win" else PALETA["desventaja"]
        )
        accent_color = QColor(color_hex)
        accent_color.setAlpha(185)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 15, 15)
        painter.setClipPath(path)
        painter.fillRect(rect.adjusted(0, 0, -rect.width() + 4, 0), accent_color)

    @staticmethod
    def extraer_oponente_linea(session: dict[str, Any]) -> str:
        """Resuelve el campeón enemigo de línea (matchup) según la posición del jugador local."""
        if not isinstance(session, dict):
            return "—"

        local_key = session.get("local_player_key")
        players = session.get("players") or {}

        if not local_key or local_key not in players:
            return "—"

        local_player = players[local_key]
        local_side = local_player.get("side")
        local_role = str(local_player.get("role") or "").upper()

        if not local_side or not local_role:
            return "—"

        # Buscar en los enfrentamientos de línea precalculados
        lane_matchups = session.get("lane_matchups") or {}
        if local_role in lane_matchups:
            matchup = lane_matchups[local_role]
            opp_key = (
                matchup.get("enemy_key")
                if local_side == "ally"
                else matchup.get("ally_key")
            )
            if opp_key and opp_key in players:
                champ = players[opp_key].get("champion_name")
                if champ and champ != "Desconocido":
                    return str(champ)

        # Búsqueda directa entre los jugadores del equipo contrario con la misma posición
        enemy_side = "enemy" if local_side == "ally" else "ally"
        for p in players.values():
            if not isinstance(p, dict):
                continue
            if p.get("side") == enemy_side:
                p_role = str(p.get("role") or "").upper()
                if p_role and p_role == local_role:
                    champ = p.get("champion_name")
                    if champ and champ != "Desconocido":
                        return str(champ)

        return "—"


class RejillaTarjetasEquipo(QWidget):
    """Distribuye hasta cinco tarjetas según el ancho útil del equipo."""

    ANCHO_MINIMO_TARJETA = 200

    def __init__(self, tarjetas: list[ChampionCard]) -> None:
        """Crea una fila de tarjetas que comparte el alto disponible.

        Args:
            tarjetas: Tarjetas del equipo que se distribuiran en columnas.
        Returns:
            None.
        """
        super().__init__()
        self._tarjetas = tarjetas
        self._columnas = 0
        self._filas = 0
        self.setObjectName("teamCardsRow")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._rejilla = QGridLayout(self)
        self._rejilla.setContentsMargins(0, 0, 0, 0)
        self._rejilla.setHorizontalSpacing(10)
        self._rejilla.setVerticalSpacing(10)
        self._rejilla.setRowStretch(0, 1)
        self._redistribuir(max(1, len(tarjetas)))

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reorganiza las tarjetas al cambiar el ancho disponible.

        Args:
            event: Evento de redimensionado de la fila.
        Returns:
            None.
        """
        super().resizeEvent(event)
        columnas = max(
            1,
            min(
                len(self._tarjetas),
                (self.width() + self._rejilla.horizontalSpacing())
                // (self.ANCHO_MINIMO_TARJETA + self._rejilla.horizontalSpacing()),
            ),
        )
        self._redistribuir(columnas)

    def _redistribuir(self, columnas: int) -> None:
        """Coloca las tarjetas en columnas iguales manteniendo su instancia.

        Args:
            columnas: Número de columnas disponibles.
        Returns:
            None.
        """
        if columnas == self._columnas and self._rejilla.count() == len(self._tarjetas):
            return
        for columna_anterior in range(self._columnas):
            self._rejilla.setColumnStretch(columna_anterior, 0)
        for fila_anterior in range(self._filas):
            self._rejilla.setRowStretch(fila_anterior, 0)
        while self._rejilla.count():
            self._rejilla.takeAt(0)
        self._columnas = columnas
        for indice, tarjeta in enumerate(self._tarjetas):
            fila, columna = divmod(indice, columnas)
            self._rejilla.addWidget(tarjeta, fila, columna)
        for columna in range(columnas):
            self._rejilla.setColumnStretch(columna, 1)
        filas = (len(self._tarjetas) + columnas - 1) // columnas
        self._filas = filas
        for fila in range(filas):
            self._rejilla.setRowStretch(fila, 1)
        self._actualizar_alto_minimo()

    def _actualizar_alto_minimo(self) -> None:
        """Reserva el alto mínimo y máximo de las filas refluídas.

        Args:
            None.
        Returns:
            None.
        """
        columnas = max(1, self._columnas)
        filas = (len(self._tarjetas) + columnas - 1) // columnas
        alto_fila = max(
            (tarjeta.minimumHeight() for tarjeta in self._tarjetas), default=0
        )
        alto = filas * alto_fila + max(0, filas - 1) * self._rejilla.verticalSpacing()
        self.setMinimumHeight(alto)
        alto_maximo = (
            filas * CARD_MAX_HEIGHT
            + max(0, filas - 1) * self._rejilla.verticalSpacing()
        )
        self.setMaximumHeight(max(alto, alto_maximo))

    def sizeHint(self) -> QSize:
        """Devuelve el alto natural sin imponer cinco columnas al contenedor."""
        columnas = max(1, self._columnas)
        filas = (len(self._tarjetas) + columnas - 1) // columnas
        alto_fila = max(
            (tarjeta.sizeHint().height() for tarjeta in self._tarjetas), default=0
        )
        alto = filas * alto_fila + max(0, filas - 1) * self._rejilla.verticalSpacing()
        return QSize(0, alto)

    def minimumSizeHint(self) -> QSize:
        """Permite que el área de scroll reduzca el ancho para activar el reflujo."""
        return QSize(0, 0)


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Ventana única de Solralol."""

    # Índice de la pestaña "Partida en vivo" dentro de self.pages.
    LIVE_PAGE_INDEX = 2
    # Índice de la pestaña "Grabaciones" (antes de "Ajustes").
    RECORDINGS_PAGE_INDEX = 4
    SETTINGS_PAGE_INDEX = 5
    #: Sondeos seguidos sin respuesta de la API local para dar la partida por
    #: terminada (el sondeo es de 1 s, así que 30 ≈ medio minuto). Es la red de
    #: seguridad que cierra la grabación si la partida termina sin que llegue
    #: ninguna señal de fin.
    LIVE_LOST_POLLS_BEFORE_STOP = 30

    snapshot_requested = Signal()

    postgame_sync_requested = Signal(
        dict,
        str,
        str,
        str,
        str,
        str,
    )

    def __init__(self, version: str, item_catalog: dict) -> None:
        """Inicializa servicios y shell con versión y catálogo recibidos; retorna None."""
        super().__init__()

        self.version = version
        self.item_catalog = item_catalog
        # Sidecar por vídeo: [(mtime_ns del JSON, metadatos)], consultado
        # en cada fila de «Partidas guardadas» y cada coincidencia de
        # repaso; sin caché serían O(filas × vídeos) lecturas por refresco.
        self._recording_metadata_cache: dict[str, tuple[int, dict]] = {}
        # Listado de vídeos cacheado mientras el mtime de la carpeta no
        # cambie: video_files() hace iterdir+stat por fichero y se consulta
        # una vez por fila en cada refresco de la lista.
        self._recording_videos_cache: list[Path] | None = None
        self._recording_videos_cache_stamp: int | None = None
        # Peso de la carpeta (iterdir+stat de todo): se relee como mucho cada
        # pocos segundos para que los refrescos seguidos de Ajustes no lo
        # vuelvan a recorrer entero.
        self._recording_size_cache: tuple[float, int] | None = None
        self.settings_service = SettingsService()
        self.settings = self.settings_service.load()
        self.home_history_repository = HomeHistoryRepository()
        self.home_lcu_provider = LCUHomeProvider()
        self.home_profile = self.home_history_repository.load_last_profile()
        self.home_collection = (self.home_profile or {}).get("collection", {})
        self.home_history_error = False
        try:
            self.home_history = (
                self.home_history_repository.load(self.home_profile)
                if self.home_profile
                else {"matches": [], "last_sync": None}
            )
        except (OSError, TypeError, ValueError) as error:
            self.home_history = {"matches": [], "last_sync": None}
            self.home_history_error = True
            logger.error(
                "[home] fallo al cargar historial: category=%s detail=%s",
                type(error).__name__,
                str(error)[:240],
            )
        self._home_sync_in_progress = False
        self._home_collection_generation = 0
        self.riot_api_key = self.settings.get(
            "riot_api_key",
            "",
        )
        self.gemini_api_key = self.settings.get(
            "gemini_api_key",
            "",
        )

        self.tab_hotkey = TabHotkeyService(self)
        self.tab_hotkey.start()

        self.riot_game_name = self.settings.get(
            "riot_game_name",
            "",
        )
        self.riot_tag_line = self.settings.get(
            "riot_tag_line",
            "",
        )
        self.riot_account_region = self.settings.get(
            "riot_account_region",
            "europe",
        )
        self.riot_platform_region = self.settings.get(
            "riot_platform_region",
            "euw1",
        )

        self.analysis_champion = self.settings.get(
            "analysis_champion",
            "",
        )
        self.analysis_role = self.settings.get(
            "analysis_role",
            "jungle",
        )
        self.analysis_rank = self.settings.get(
            "analysis_rank",
            "emerald_plus",
        )
        self.analysis_region = self.settings.get(
            "analysis_region",
            "euw1",
        )

        for key, value in recording_settings_defaults().items():
            self.settings.setdefault(key, value)

        self.recording_config = RecordingConfig.from_settings(self.settings)
        self.recording_library = RecordingLibrary(self.recording_config.output_dir)
        self.recording_service = RecordingService(
            self.recording_library,
            self,
        )
        # La búsqueda de ffmpeg recorre el PATH y comprueba candidatos en
        # disco, y el sondeo de dispositivos de audio lanza ffmpeg: ambos se
        # hacen en workers para que la ventana aparezca sin esperar.
        self._ffmpeg_ready = False
        self._refresh_ffmpeg_task: AsyncTask | None = None
        self._pending_recording_snapshot: dict[str, Any] | None = None
        self._devices_task: AsyncTask | None = None
        self._system_devices_task: AsyncTask | None = None
        self._start_background_ffmpeg_check()
        self.recording_service.failed.connect(self._on_recording_failed)
        self.recording_service.finished.connect(self._on_recording_finished)
        self.recording_service.state_changed.connect(self._sync_overlay_recording)
        self.recording_system_audio_combo = None
        self.recording_system_audio_button = None
        self.recording_mic_capture_enabled = False

        self.last_snapshot: dict | None = None
        self.is_refreshing = False
        self.cards_built = False
        self.was_in_game = False
        self.panel_refresh_counter = 0
        self.panel_refresh_every_seconds = 10
        self.live_team_cards: dict[str, list[ChampionCard]] = {}
        self.live_team_summaries: dict[str, QLabel] = {}
        self.live_team_signatures: dict[str, tuple[tuple[str, ...], ...]] = {}
        self.live_team_order: tuple[str, ...] = ()
        self.live_match_tracker = LiveMatchTracker(
            item_catalog,
            game_version=self.version,
        )
        self.saved_live_sessions: list[dict] = []
        self.live_session_finished = False
        #: Sondeos seguidos sin respuesta de la API local estando en partida.
        self.live_snapshots_lost = 0

        self.postgame_sync_in_progress = False
        self.pending_postgame_session_id = ""
        self._postgame_lcu_scheduled: set[str] = set()
        #: Hay una lectura de «Partidas guardadas» en curso en un worker.
        self.saved_games_refreshing = False
        #: Mientras el worker trabaja, otra petición de refresco queda en cola.
        self.saved_games_pending = False
        #: ``session_id`` → vídeo de la grabación (resuelto en el worker).
        self.session_recordings: dict[str, str] = {}

        self.current_live_session: dict | None = None
        self.live_analysis_dialog: LiveMatchAnalysisDialog | None = None
        #: Ventana independiente de repaso (vídeo + desglose post-partida).
        self.replay_window: PostgameReplayWindow | None = None
        self.draft_tool_dialog: DraftToolDialog | None = None
        # Se activa al cerrarse el draft y se consume cuando la partida arranca
        # (es decir, cuando termina la pantalla de carga): el panel salta solo a
        # "Partida en vivo".
        self.pending_live_navigation = False

        self.overlay = OverlayWindow(
            item_catalog,
            settings_service=self.settings_service,
            settings=self.settings,
        )
        self.overlay.connect_tab_hotkey(self.tab_hotkey)

        self.setWindowTitle("Solralol")
        self.resize(1600, 1000)
        self.setMinimumSize(1000, 700)

        self.build_ui()
        self.data_dragon_assets = DataDragonAssetService(self)
        self.overlay.set_assets(self.data_dragon_assets)
        self.overlay.state_changed.connect(self.sync_overlay_settings_ui)
        aplicar_tema(self)
        self.setup_live_data_worker()
        self.setup_postgame_sync_worker()
        self.setup_champ_select_worker()
        self.refresh_home_dashboard("Historial local · sincronizando…")
        self.synchronize_home_history()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.request_snapshot)
        self.poll_timer.start(1000)

        self.request_snapshot()

        # Primera pasada de layout: showMaximized() en offscreen y en algunos
        # entornos no llena la ventana al instante y deja un scroll residual
        # en el panel de la partida en vivo.
        self.backdrop.adjustSize()
        self.pages.adjustSize()

    def build_ui(self) -> None:
        """Construye la ventana con navegación lateral y páginas; retorna None."""
        self.backdrop = Backdrop()
        self.setCentralWidget(self.backdrop)

        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        cabecera = self.create_header()
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(18)
        cuerpo.addWidget(self.create_navigation())
        root.addLayout(cuerpo, 1)

        self.pages = QStackedWidget()
        self.pages.setObjectName("mainPages")
        self.pages.currentChanged.connect(self._handle_page_changed)
        self.pages.addWidget(PaginaDesplazable(self.create_home_page()))
        self.pages.addWidget(self.create_analysis_page())
        self.pages.addWidget(self.create_live_page())
        self.pages.addWidget(self.create_saved_games_page())
        self.recordings_page = RecordingsPage(
            self.recording_library,
            self.recording_service,
            self,
        )
        self.recordings_page.open_folder_requested.connect(self.open_recordings_folder)
        self.recordings_page.stop_recording_requested.connect(
            self.stop_recording_manually
        )
        self.recordings_page.open_window_requested.connect(
            self.open_replay_window_for_video
        )
        self.recordings_page.recordings_changed.connect(self.refresh_saved_games)
        self.pages.addWidget(self.recordings_page)
        self.pages.addWidget(self.create_settings_page())
        self.pages.addWidget(QWidget())

        contenido = QVBoxLayout()
        contenido.setSpacing(12)
        contenido.addWidget(cabecera)
        contenido.addWidget(self.pages, 1)
        cuerpo.addLayout(contenido, 1)
        self.showMaximized()

    def create_header(self) -> QWidget:
        """Construye estado de conexión y cierre junto al contenido; devuelve la cabecera."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        subtitle = QLabel("Panel de control")
        subtitle.setObjectName("brandSubtitle")
        layout.addWidget(subtitle)
        layout.addStretch(1)

        self.connection_label = QLabel("Comprobando League...")
        self.connection_label.setObjectName("connectionLabel")
        layout.addWidget(self.connection_label)

        close_button = QPushButton("×")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        return header

    def create_navigation(self) -> QFrame:
        """Crea la barra plegable con los destinos existentes; retorna su marco."""
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        self.home_button = self.create_nav_button(
            "Inicio",
            0,
        )
        self.analysis_button = self.create_nav_button(
            "Análisis",
            1,
        )
        self.live_button = self.create_nav_button(
            "Partida en vivo",
            self.LIVE_PAGE_INDEX,
        )
        self.saved_games_button = self.create_nav_button(
            "Partidas guardadas",
            3,
        )
        self.recordings_button = self.create_nav_button(
            "Grabaciones",
            self.RECORDINGS_PAGE_INDEX,
        )
        self.settings_button = self.create_nav_button(
            "Ajustes",
            self.SETTINGS_PAGE_INDEX,
        )

        self.home_button.setChecked(True)
        self.live_button.setEnabled(False)

        self.draft_nav_button = self.create_nav_button("Herramienta de Draft", 6)
        self.draft_nav_button.clicked.connect(self.open_draft_tool_dialog)

        return BarraLateral(
            [
                self.home_button,
                self.analysis_button,
                self.live_button,
                self.saved_games_button,
                self.recordings_button,
                self.settings_button,
                self.draft_nav_button,
            ],
            self,
        )

    def create_nav_button(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.clicked.connect(lambda checked=False: self.pages.setCurrentIndex(index))
        self.nav_group.addButton(button)
        return button

    def create_home_page(self) -> QWidget:
        """Crea el dashboard persistente y conserva indicadores del estado en vivo."""
        from app.ui.home_dashboard import HomeDashboard

        self.home_dashboard = HomeDashboard(
            item_catalog=self.item_catalog, version=getattr(self, "version", "")
        )
        self.home_dashboard.sync_requested.connect(self.synchronize_home_history)
        self.home_dashboard.clear_requested.connect(self.confirm_clear_home_history)
        self.home_dashboard.saved_match_requested.connect(self.open_home_saved_match)
        return self.home_dashboard

    def open_home_saved_match(self, session_id: str) -> None:
        """Abre desde Home una sesión mediante el mismo análisis de Partidas guardadas."""
        session = self.find_saved_session(session_id) if session_id else None
        if isinstance(session, dict):
            self.open_saved_game_analysis(session)

    def create_analysis_page(self) -> QWidget:
        page = LocalAnalysisDialog(
            self,
            version=getattr(self, "version", "16.17.1"),
            item_catalog=getattr(self, "item_catalog", None),
        )
        page.setObjectName("analysisPage")
        page.setWindowFlags(Qt.WindowType.Widget)
        return page

    def open_local_analysis(self) -> None:
        dialog = LocalAnalysisDialog(
            self,
            version=getattr(self, "version", "16.17.1"),
            item_catalog=getattr(self, "item_catalog", None),
        )
        dialog.exec()

    def _handle_page_changed(self, index: int) -> None:
        """Sincroniza el destino activo con el índice recibido; retorna None."""
        botones = (
            self.home_button,
            self.analysis_button,
            self.live_button,
            self.saved_games_button,
            self.recordings_button,
            self.settings_button,
            self.draft_nav_button,
        )
        if 0 <= index < len(botones):
            botones[index].setChecked(True)
        if index == 0:
            self.refresh_home_dashboard("Cliente local · listo para sincronizar")

    def refresh_home_dashboard(self, status: str) -> None:
        """Actualiza Home desde la copia persistida sin realizar llamadas de red."""
        if not hasattr(self, "home_dashboard"):
            return
        analytics = analyze_home_history(self.home_history.get("matches", []))
        self.home_dashboard.set_dashboard_data(
            self.home_profile,
            self.home_history,
            analytics,
            status,
            collection=self.home_collection,
            syncing=self._home_sync_in_progress,
        )
        icon_id = (self.home_profile or {}).get("profileIconId")
        if icon_id and hasattr(self, "data_dragon_assets"):
            self.data_dragon_assets.set_label_image(
                self.home_dashboard.profile_icon,
                self.data_dragon_assets.profile_icon_url(icon_id),
                f"profileicon:{icon_id}:home",
                62,
            )

    def synchronize_home_history(self) -> None:
        """Sincroniza historial LCU en segundo plano y combina datos persistidos."""
        if self._home_sync_in_progress:
            return
        self._home_sync_in_progress = True
        self.refresh_home_dashboard(
            "Historial incompatible o dañado · conservado sin cambios"
            if self.home_history_error
            else "Sincronizando con League Client…"
        )
        run_async(
            self.synchronize_home_background,
            on_finished=self._home_sync_finished,
            on_progress=self._home_sync_progress,
            token="home_lcu_sync",
        )

    def _home_sync_progress(self, _current: int, _total: int, message: str) -> None:
        """Muestra en Home el progreso comunicado por la sincronización LCU."""
        if hasattr(self, "home_dashboard"):
            self.home_dashboard.connection.setText(message)

    def synchronize_home_background(
        self, progress_callback: Any = None
    ) -> dict[str, Any]:
        """Cruza todo el historial recordado con sesiones guardadas, incluso offline."""
        repository = HomeHistoryRepository()
        try:
            result = LCUHomeProvider().synchronize(repository, progress_callback)
        except (ConnectionError, OSError, RuntimeError, TimeoutError):
            profile = repository.load_last_profile() or dict(self.home_profile or {})
            if not profile:
                raise
            result = {
                "profile": profile,
                "history": repository.load(profile),
                "collection": profile.get("collection", {}),
                "connection": "offline",
            }
        try:
            tracker = LiveMatchTracker(
                self.item_catalog, game_version=self.version, persist=False
            )
            sessions = tracker.load_saved_sessions()
        except (OSError, TypeError, ValueError):
            sessions = []
        matches, puntuaciones_actualizadas = reconciliar_puntuaciones_home(
            result["history"].get("matches", []),
            sessions,
            str(result.get("profile", {}).get("puuid") or "") or None,
        )
        if puntuaciones_actualizadas:
            tracker._save_sessions(sessions)
        result["history"] = repository.merge(result["profile"], matches)
        result["saved_scores_updated"] = puntuaciones_actualizadas
        return result

    def actualizar_puntuaciones_home_en_segundo_plano(
        self, perfil: dict[str, Any], historial: dict[str, Any]
    ) -> dict[str, Any]:
        """Vincula los resultados postpartida nuevos con el historial local.

        Args:
            perfil: identidad de la cuenta cuyo historial se está mostrando.
            historial: copia del historial actual de Home.

        Returns:
            Historial fusionado y persistido por el repositorio local.
        """
        tracker = LiveMatchTracker(
            self.item_catalog, game_version=self.version, persist=False
        )
        sesiones = tracker.load_saved_sessions()
        partidas, puntuaciones_actualizadas = reconciliar_puntuaciones_home(
            historial.get("matches", []),
            sesiones,
            str(perfil.get("puuid") or "") or None,
        )
        if puntuaciones_actualizadas:
            tracker._save_sessions(sesiones)
        return HomeHistoryRepository().merge(perfil, partidas)

    def _home_saved_scores_finished(
        self, _token: Any, result: Any, error: str | None
    ) -> None:
        """Actualiza Home al terminar el vínculo local de resultados Riot."""
        if error or not isinstance(result, dict):
            return
        self.home_history = result
        self.refresh_home_dashboard("Historial local actualizado")

    def _home_sync_finished(self, _token: Any, result: Any, error: str | None) -> None:
        """Aplica el resultado del worker y conserva el último estado offline."""
        self._home_sync_in_progress = False
        if error or not isinstance(result, dict):
            self.refresh_home_dashboard(
                "Historial incompatible o dañado · conservado sin cambios"
                if self.home_history_error
                else "League cerrado · mostrando historial local"
            )
            self._revisar_sincronizaciones_lcu_pendientes(None)
            return
        self.home_profile = result["profile"]
        self.home_history = result["history"]
        self.home_collection = result.get("collection", {})
        self.home_history_error = False
        estado = (
            "Puntuaciones locales actualizadas · League desconectado"
            if result.get("connection") == "offline"
            else "League conectado · historial sincronizado"
        )
        self.refresh_home_dashboard(estado)
        self._revisar_sincronizaciones_lcu_pendientes(self.home_history)
        if result.get("saved_scores_updated") and hasattr(self, "saved_games_layout"):
            self.refresh_saved_games()
        if result.get("connection") == "offline":
            return
        profile = dict(self.home_profile)
        self._home_collection_generation += 1
        token = (
            HomeHistoryRepository.account_key(profile),
            self._home_collection_generation,
        )
        run_async(
            lambda: LCUHomeProvider().synchronize_collection(
                profile, HomeHistoryRepository()
            ),
            on_finished=self._home_collection_finished,
            token=token,
        )

    def _home_collection_finished(
        self, token: Any, result: Any, error: str | None
    ) -> None:
        """Aplica los módulos de colección si siguen perteneciendo a la cuenta activa."""
        if error or not isinstance(result, dict) or not self.home_profile:
            return
        if token != (
            HomeHistoryRepository.account_key(self.home_profile),
            self._home_collection_generation,
        ):
            return
        self.home_collection = result
        self.home_profile["collection"] = result
        self.refresh_home_dashboard("League conectado · colección actualizada")

    def confirm_clear_home_history(self) -> None:
        """Confirma y elimina únicamente el historial local de la cuenta activa."""
        if not self.home_profile:
            return
        confirmation = QMessageBox(self)
        confirmation.setIcon(QMessageBox.Icon.Warning)
        confirmation.setWindowTitle("Borrar historial local")
        confirmation.setText(
            "Se eliminarán las partidas recordadas y sus estadísticas de este perfil."
        )
        confirmation.setInformativeText(
            "Partidas guardadas, grabaciones, análisis y ajustes se conservarán."
        )
        confirmation.setStandardButtons(
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes
        )
        confirmation.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if confirmation.exec() != QMessageBox.StandardButton.Yes:
            return
        self.home_history_repository.clear(self.home_profile)
        self.home_history = {"matches": [], "last_sync": None}
        self.home_history_error = False
        self.refresh_home_dashboard("Historial local borrado")

    def toggle_analysis_adblock(
        self,
        enabled: bool,
    ) -> None:
        return

    def set_combo_value(
        self,
        combo: QComboBox,
        value: str,
    ) -> None:
        index = combo.findData(value)

        if index >= 0:
            combo.setCurrentIndex(index)

    def create_analysis_source_row(
        self,
        name: str,
        description: str,
        callback,
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("analysisSourceRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        title = QLabel(name)
        title.setObjectName("analysisSourceTitle")
        text_layout.addWidget(title)

        detail = QLabel(description)
        detail.setObjectName("mutedText")
        detail.setWordWrap(True)
        text_layout.addWidget(detail)

        layout.addLayout(text_layout, 1)

        button = QPushButton(f"Abrir {name}")
        button.setObjectName("primaryButton")
        button.clicked.connect(callback)
        layout.addWidget(button)

        return row

    def save_analysis_preferences(self) -> None:
        champion = self.analysis_champion_input.text().strip()

        self.analysis_champion = champion
        self.analysis_role = self.analysis_role_combo.currentData()
        self.analysis_rank = self.analysis_rank_combo.currentData()
        self.analysis_region = self.analysis_region_combo.currentData()

        self.settings.update(
            {
                "analysis_champion": self.analysis_champion,
                "analysis_role": self.analysis_role,
                "analysis_rank": self.analysis_rank,
                "analysis_region": self.analysis_region,
            }
        )

        self.settings_service.save(self.settings)

        self.set_analysis_status(
            "Selección guardada localmente.",
            "success",
        )

    def analysis_values(self) -> tuple[str, str, str, str] | None:
        champion = self.analysis_champion_input.text().strip()

        if not champion:
            self.set_analysis_status(
                "Escribe el nombre de un campeón.",
                "error",
            )
            return None

        role = self.analysis_role_combo.currentData()
        rank = self.analysis_rank_combo.currentData()
        region = self.analysis_region_combo.currentData()

        champion_slug = (
            champion.casefold().replace(" ", "").replace("'", "").replace(".", "")
        )

        return champion_slug, role, rank, region

    def open_analysis_url(
        self,
        url: str,
        source_name: str,
    ) -> None:
        return

    def select_analysis_source(
        self,
        source: str,
    ) -> None:
        return

    def load_selected_analysis(self) -> None:
        return

    def open_current_analysis_externally(self) -> None:
        return

    def analysis_load_started(self) -> None:
        return

    def analysis_load_finished(
        self,
        success: bool,
    ) -> None:
        return

    def set_combo_value(
        self,
        combo: QComboBox,
        value: str,
    ) -> None:
        index = combo.findData(value)

        if index >= 0:
            combo.setCurrentIndex(index)

    def set_combo_value(
        self,
        combo: QComboBox,
        value: str,
    ) -> None:
        index = combo.findData(value)

        if index >= 0:
            combo.setCurrentIndex(index)

    def create_live_page(self) -> QWidget:
        """Construye la página LIVE con una zona de equipos adaptable.

        Args:
            None.
        Returns:
            Página Qt con estado de partida y paneles de equipo.
        """
        page = QWidget()
        page.setObjectName("livePage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        status_card = QFrame()
        status_card.setObjectName("liveStatusCard")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(22, 16, 22, 16)
        status_layout.setSpacing(18)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)

        self.live_dot = QLabel()
        self.live_dot.setObjectName("liveDot")
        self.live_dot.setFixedSize(9, 9)
        self.live_dot.setProperty("state", "idle")
        badge_row.addWidget(self.live_dot)

        self.live_badge = QLabel("EN ESPERA")
        self.live_badge.setObjectName("liveEyebrow")
        badge_row.addWidget(self.live_badge)
        badge_row.addStretch(1)
        info_layout.addLayout(badge_row)

        title = QLabel("Partida en vivo")
        title.setObjectName("sectionTitle")
        info_layout.addWidget(title)

        self.live_status = QLabel("Esperando una partida activa...")
        self.live_status.setObjectName("mutedText")
        info_layout.addWidget(self.live_status)
        status_layout.addLayout(info_layout, 1)

        self.open_live_analysis_button = QPushButton("Abrir análisis LIVE")
        self.open_live_analysis_button.setObjectName("primaryButton")
        self.open_live_analysis_button.setEnabled(False)
        self.open_live_analysis_button.clicked.connect(self.open_live_analysis)

        status_layout.addWidget(self.open_live_analysis_button)

        status_layout.addWidget(self.create_live_clock())

        layout.addWidget(status_card)

        self.live_scroll_area = QScrollArea()
        self.live_scroll_area.setObjectName("liveScrollArea")
        self.live_scroll_area.setWidgetResizable(True)
        self.live_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.live_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.cards_widget = QWidget()
        self.cards_widget.setObjectName("cardsWidget")

        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)

        self.live_scroll_area.setWidget(self.cards_widget)
        layout.addWidget(self.live_scroll_area, 1)

        self.live_empty_label = QLabel(
            "La pestaña se habilitará automáticamente al comenzar una partida."
        )
        self.live_empty_label.setObjectName("liveSummary")
        self.live_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_empty_label.setWordWrap(True)
        self.cards_layout.addWidget(self.live_empty_label, 1)

        return page

    def create_live_clock(self) -> QFrame:
        """Reloj de la partida que acompaña al botón de análisis LIVE."""
        clock = QFrame()
        clock.setObjectName("liveClock")
        clock.setMinimumWidth(118)

        layout = QVBoxLayout(clock)
        layout.setContentsMargins(16, 5, 16, 5)
        layout.setSpacing(0)

        caption = QLabel("DURACIÓN")
        caption.setObjectName("liveClockCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)

        self.live_time_label = QLabel("—")
        self.live_time_label.setObjectName("liveTime")
        self.live_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.live_time_label)

        return clock

    def create_saved_games_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("savedGamesPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header = QFrame()
        header.setObjectName("heroCard")

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 20)
        header_layout.setSpacing(14)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        eyebrow = QLabel("REGISTRO LOCAL")
        eyebrow.setObjectName("eyebrow")
        text_layout.addWidget(eyebrow)

        title = QLabel("Partidas guardadas")
        title.setObjectName("heroTitle")
        text_layout.addWidget(title)

        description = QLabel(
            "Sesiones registradas mientras SolraLoL "
            "estaba abierto. Cada partida conserva "
            "snapshots, eventos y timelines LIVE."
        )
        description.setObjectName("heroText")
        description.setWordWrap(True)
        text_layout.addWidget(description)

        header_layout.addLayout(text_layout, 1)

        self.refresh_saved_games_button = QPushButton("Actualizar lista")
        self.refresh_saved_games_button.setObjectName("secondaryButton")
        self.refresh_saved_games_button.clicked.connect(self.refresh_saved_games)
        header_layout.addWidget(self.refresh_saved_games_button)

        layout.addWidget(header)

        self.saved_games_status = QLabel("Cargando partidas guardadas...")
        self.saved_games_status.setObjectName("savedGamesStatus")
        layout.addWidget(self.saved_games_status)

        scroll = QScrollArea()
        scroll.setObjectName("savedGamesScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.saved_games_content = QWidget()
        self.saved_games_content.setObjectName("savedGamesContent")
        self.saved_games_layout = QVBoxLayout(self.saved_games_content)
        self.saved_games_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.saved_games_layout.setSpacing(12)

        scroll.setWidget(self.saved_games_content)
        layout.addWidget(scroll, 1)

        QTimer.singleShot(
            0,
            self.refresh_saved_games,
        )

        return page

    def refresh_saved_games(self) -> None:
        """Pide en segundo plano las partidas guardadas y pinta al llegar.

        ``load_saved_sessions`` puede tener que analizar un JSON de cientos de
        MB y el emparejamiento vídeo↔sesión recorre la carpeta de grabaciones
        leyendo un sidecar por vídeo: las dos cosas se hacen en un worker, y
        la interfaz solo construye las filas cuando llega el resultado. Se
        avisa al usuario con «Cargando…» de inmediato.

        Mientras hay una lectura en curso, cualquier petición nueva (la propia
        reconstrucción avisa a la pestaña Grabaciones, que al refrescarse
        vuelve a pedir este refresco) no se encola en paralelo: se marca como
        pendiente y se repite una sola vez al terminar.
        """
        if self.saved_games_refreshing:
            self.saved_games_pending = True

            return

        self.saved_games_refreshing = True

        if hasattr(self, "saved_games_status"):
            self.saved_games_status.setText("Cargando partidas guardadas…")

        library = self.recording_library
        tracker = self.live_match_tracker

        def collect() -> tuple:
            """Lee sesiones, vídeos y sidecars (todo I/O) fuera del hilo GUI."""
            sessions = tracker.load_saved_sessions()
            puntuaciones_actualizadas = False
            for session in sessions:
                puntuaciones_actualizadas |= asegurar_puntuacion_guardada(session)
            if puntuaciones_actualizadas:
                tracker._save_sessions(sessions)
            videos = library.video_files()
            sidecars: dict[str, tuple[int, dict]] = {}

            for video in videos:
                try:
                    stamp = video.with_suffix(".json").stat().st_mtime_ns
                except OSError:
                    stamp = 0

                sidecars[str(video)] = (stamp, library.load_metadata(video))

            recordings: dict[str, str] = {}

            for session in sessions:
                if not isinstance(session, dict):
                    continue

                found = find_video_for_session(
                    videos, session, lambda path: sidecars.get(str(path), (0, {}))[1]
                )

                if found is not None:
                    recordings[str(session.get("session_id") or "")] = str(found)

            return sessions, videos, sidecars, recordings

        run_async(collect, on_finished=self._apply_saved_games_data)

    def _apply_saved_games_data(self, _token, result, error) -> None:
        """Publica en el hilo de la GUI lo que leyó el worker."""
        try:
            if error:
                # Nunca se deja la pestaña en «Cargando»: se avisa del error y
                # se conserva lo que ya se estuviera mostrando.
                if hasattr(self, "saved_games_status"):
                    self.saved_games_status.setText(
                        f"No se pudieron leer las partidas guardadas: {error}"
                    )

                return

            sessions, videos, sidecars, recordings = result

            self._adopt_recording_caches(videos, sidecars)
            self.session_recordings = recordings
            self.saved_live_sessions = sessions
            self._rebuild_saved_games()
        finally:
            self.saved_games_refreshing = False

            if self.saved_games_pending:
                self.saved_games_pending = False
                self.refresh_saved_games()

    def _adopt_recording_caches(
        self,
        videos: list[Path],
        sidecars: dict[str, tuple[int, dict]],
    ) -> None:
        """Adopta en la GUI los datos que leyó el worker de grabaciones.

        Con las cachés pobladas, resolver el vídeo de una sesión (lo que hace
        cada fila y el botón «Repaso con vídeo») es una consulta en memoria.
        """
        try:
            stamp = self.recording_library.directory.stat().st_mtime_ns
        except OSError:
            stamp = None

        self._recording_videos_cache = list(videos)
        self._recording_videos_cache_stamp = stamp
        self._recording_metadata_cache = dict(sidecars)

    def _rebuild_saved_games(self) -> None:
        while self.saved_games_layout.count():
            item = self.saved_games_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        if not self.saved_live_sessions:
            self.saved_games_status.setText(
                "Aún no hay partidas registradas. "
                "Inicia una partida con SolraLoL abierto."
            )

            empty = QLabel(
                "Las partidas aparecerán aquí al terminar. "
                "Por ahora se guarda la telemetría LIVE local."
            )
            empty.setObjectName("savedGamesEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)

            self.saved_games_layout.addWidget(empty)
            self.saved_games_layout.addStretch(1)
            return

        self.saved_games_status.setText(
            f"{len(self.saved_live_sessions)} partida(s) guardada(s)."
        )

        for session in reversed(self.saved_live_sessions):
            # El vídeo de cada sesión ya viene resuelto del worker: construir
            # la fila no vuelve a tocar el disco.
            session_id = (
                str(session.get("session_id") or "")
                if isinstance(session, dict)
                else ""
            )

            self.saved_games_layout.addWidget(
                self.create_saved_game_row(
                    session,
                    recording=self.session_recordings.get(session_id, ""),
                )
            )

        self.saved_games_layout.addStretch(1)

    def delete_saved_game_session(self, session_id: str) -> None:
        if not session_id:
            return

        # La grabación asociada se localiza antes de borrar la sesión:
        # después ya no se podría resolver su vídeo. Se prefiere el vídeo que
        # ya resolvió el worker del refresco (sin tocar el disco) y se cae al
        # barrido con cachés si esta sesión aún no se ha listado.
        session = self.find_saved_session(session_id)
        video_path = self.session_recordings.get(str(session_id))

        if not video_path and isinstance(session, dict):
            video_path = self.find_recording_for_session(session)

        self.live_match_tracker.delete_saved_session(session_id)
        if isinstance(session, dict):
            session.pop("ai_match_analysis", None)
            session.pop("ai_analysis", None)
        for dialogo in (
            getattr(self, "live_analysis_dialog", None),
            getattr(getattr(self, "replay_window", None), "live_view", None),
        ):
            if dialogo is not None:
                dialogo.invalidar_analisis_guardado(session_id)

        if video_path:
            self.delete_recording_file(video_path)

        # La lista cambió (y puede que la carpeta): se reconstruyen las dos
        # pestañas. El borrado del vídeo ya dispara ``recordings_changed``, que
        # refresca las partidas guardadas; aquí basta con pedir la otra.
        self.invalidate_recording_metadata_cache()
        self.refresh_saved_games()

        if video_path and hasattr(self, "recordings_page"):
            self.recordings_page.refresh()

    def invalidate_recording_metadata_cache(self) -> None:
        """Olvida sidecars y listado de vídeos (tras borrar o grabar)."""
        self._recording_metadata_cache.clear()
        self._recording_videos_cache = None
        self._recording_videos_cache_stamp = None
        self._recording_size_cache = None

    def recording_folder_size(self) -> int:
        """Peso de la carpeta de grabaciones, releído como mucho cada 5 s.

        ``sync_recording_controls`` lo consulta en cada cambio de Ajustes y
        ``total_size_bytes`` recorre la carpeta entera: con la caché los
        refrescos seguidos son gratis y el valor sigue actualizándose al
        grabar o al borrar (que invalidan la caché).
        """
        now = time.monotonic()
        cached = self._recording_size_cache

        if cached is not None and now - cached[0] < 5.0:
            return cached[1]

        size = self.recording_library.total_size_bytes()
        self._recording_size_cache = (now, size)

        return size

    def recording_videos_cached(self) -> list[Path]:
        """Listado de vídeos de la carpeta, releído solo si cambió.

        ``video_files()`` lista el directorio y hace ``stat`` de cada
        fichero: dentro de ``refresh_saved_games`` se consulta una vez por
        fila, así que se cachea contra el ``mtime`` de la carpeta (cambia
        al crear, borrar o renombrar entradas).
        """
        try:
            stamp = self.recording_library.directory.stat().st_mtime_ns
        except OSError:
            stamp = None

        if (
            self._recording_videos_cache is not None
            and self._recording_videos_cache_stamp == stamp
        ):
            return self._recording_videos_cache

        videos = self.recording_library.video_files()
        self._recording_videos_cache = videos
        self._recording_videos_cache_stamp = stamp

        return videos

    def recording_metadata_cached(self, video_path: str | Path) -> dict:
        """Sidecar de un vídeo leído de disco una sola vez.

        ``refresh_saved_games`` consulta los sidecars de TODOS los vídeos
        una vez por fila: sin caché son O(filas × vídeos) lecturas de
        fichero por refresco. La clave incluye el ``mtime`` del JSON para
        detectar sidecars reescritos sin invalidar todo el lote.
        """
        path = Path(video_path)
        key = str(path)

        try:
            stamp = path.with_suffix(".json").stat().st_mtime_ns
        except OSError:
            self._recording_metadata_cache.pop(key, None)
            return {}

        cached = self._recording_metadata_cache.get(key)

        if cached is not None and cached[0] == stamp:
            return cached[1]

        metadata = self.recording_library.load_metadata(path)
        self._recording_metadata_cache[key] = (stamp, metadata)

        return metadata

    def delete_recording_file(self, video_path: str) -> bool:
        """Borra un vídeo (y su sidecar) soltando antes los reproductores.

        Se usa tanto al eliminar una partida guardada (que arrastra su
        vídeo) como punto único para liberar la ventana de repaso y el
        reproductor de la pestaña Grabaciones si están con ese fichero.
        """
        video = Path(video_path)

        replay = getattr(self, "replay_window", None)

        if replay is not None:
            try:
                replay_path = getattr(replay, "video_path", None)

                if replay_path is not None and Path(replay_path) == video:
                    replay.player.stop()
                    replay.player.setSource(QUrl())
                    replay.video_path = None
            except RuntimeError:
                pass

        if hasattr(self, "recordings_page"):
            self.recordings_page._release_media(video)

        deleted = self.recording_library.delete(video)

        # Los sidecars han cambiado: la próxima consulta releerá disco.
        self.invalidate_recording_metadata_cache()

        return deleted

    def create_saved_game_row(
        self,
        session: dict,
        recording: str | None = None,
    ) -> QWidget:
        """Fila de una partida guardada.

        *recording* es el vídeo asociado ya resuelto (lo calcula el worker del
        refresco) y evita que pintar la fila toque el disco; ``None`` hace que
        se resuelva aquí mismo, para quien construya una fila suelta.
        """
        # Un resultado ausente no equivale a una derrota.
        local_key = session.get("local_player_key")
        players = session.get("players") or {}
        local_player = (players.get(local_key) or {}) if local_key else {}
        win = local_player.get("win")
        result_state = "win" if win is True else "loss" if win is False else "unknown"

        row = TarjetaPartidaGuardada(result_state=result_state)
        row.setProperty("result", result_state)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(18)

        champion = session.get(
            "champion_name",
            "Desconocido",
        )

        champ_icon = IconoRedondeado(str(champion or "?")[:1].upper(), radio=12)
        champ_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        champ_icon.setFixedSize(60, 60)
        champ_icon.setObjectName("savedGameChampIcon")
        champ_icon.setToolTip(str(champion))
        if (
            champion
            and champion != "Desconocido"
            and hasattr(self, "data_dragon_assets")
        ):
            icon_url = self.data_dragon_assets.champion_url(champion)
            self.data_dragon_assets.set_label_image(
                champ_icon, icon_url, f"champ:{champion}", 56
            )
        layout.addWidget(champ_icon)

        details = QVBoxLayout()
        details.setSpacing(8)

        game_mode = session.get(
            "game_mode",
            "UNKNOWN",
        )

        title_row = QHBoxLayout()
        title_row.setSpacing(12)

        title = QLabel(str(champion))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("savedGameTitle")
        title_row.addWidget(title)

        # Matchup de línea: Mi campeón VS [Icono] Campeón enemigo
        opponent_champ = TarjetaPartidaGuardada.extraer_oponente_linea(session)
        matchup_label = QLabel("VS")
        matchup_label.setObjectName("savedGameMatchup")
        title_row.addWidget(matchup_label)

        if opponent_champ != "—":
            enemy_icon = IconoRedondeado(
                str(opponent_champ or "?")[:1].upper(), radio=6
            )
            enemy_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            enemy_icon.setFixedSize(28, 28)
            enemy_icon.setObjectName("savedGameEnemyIcon")
            enemy_icon.setToolTip(str(opponent_champ))
            if hasattr(self, "data_dragon_assets"):
                icon_url = self.data_dragon_assets.champion_url(opponent_champ)
                self.data_dragon_assets.set_label_image(
                    enemy_icon, icon_url, f"champ:{opponent_champ}", 26
                )
            title_row.addWidget(enemy_icon)

            enemy_name = QLabel(str(opponent_champ))
            enemy_name.setTextFormat(Qt.TextFormat.PlainText)
            enemy_name.setObjectName("savedGameMatchup")
            title_row.addWidget(enemy_name)
        else:
            dash_label = QLabel("—")
            dash_label.setObjectName("savedGameMatchup")
            title_row.addWidget(dash_label)

        result = QLabel(
            {
                "win": "VICTORIA",
                "loss": "DERROTA",
                "unknown": "Sin resultado",
            }[result_state]
        )
        result.setObjectName("savedGameResult")
        result.setProperty("result", result_state)

        result.setToolTip(
            "Resultado del jugador local."
            if result_state != "unknown"
            else "No se ha registrado el resultado del jugador local. "
            "Si está disponible, sincroniza la partida con Riot."
        )
        title_row.addWidget(result)
        title_row.addStretch(1)
        details.addLayout(title_row)

        final_sync = session.get("final_sync") or {}

        sync_status = final_sync.get(
            "status",
            "live_only",
        )

        sync_texts = {
            "live_only": "Solo telemetría LIVE",
            "pending": "Pendiente de sincronización",
            "not_found": "No encontrada en Riot",
            "synced": "Sincronizada con Riot",
            "failed": "Error al sincronizar",
        }

        status = QLabel(
            sync_texts.get(
                sync_status,
                "Solo telemetría LIVE",
            )
        )
        status.setObjectName("savedGameSync")
        status.setProperty("state", sync_status)
        status.setToolTip(str(final_sync.get("message") or status.text()))

        duration = self.format_match_duration(
            session.get(
                "duration",
                0,
            )
        )

        started_at = self.format_saved_session_date(
            session.get(
                "started_at",
                "",
            )
        )

        events = session.get(
            "events",
            [],
        )

        subtitle = QLabel(f"{game_mode}   ·   {started_at}   ·   {duration}")
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setObjectName("savedGameDetail")
        subtitle.setWordWrap(True)
        details.addWidget(subtitle)

        metadata_row = QHBoxLayout()
        metadata_row.setSpacing(10)
        metadata_row.addWidget(status)
        event_count = QLabel(f"{len(events or [])} eventos registrados")
        event_count.setObjectName("savedGameDetail")
        metadata_row.addWidget(event_count)
        resumen = resumen_puntuacion_local(session)
        if resumen is not None:
            puntuacion = QLabel(etiqueta_puntuacion(resumen))
            puntuacion.setObjectName("savedGamePerformance")
            puntuacion.setProperty("award", resumen["award"])
            puntuacion.setToolTip("Puntuación final SOLRALOL · ranking global")
            metadata_row.addWidget(puntuacion)
        elif sync_status == "synced":
            pendiente = QLabel("Rendimiento incompleto")
            pendiente.setObjectName("savedGamePerformancePending")
            pendiente.setToolTip(
                "La partida está sincronizada, pero faltan datos para validar "
                "una puntuación final comparable."
            )
            metadata_row.addWidget(pendiente)
        metadata_row.addStretch(1)
        details.addLayout(metadata_row)

        layout.addLayout(details, 1)

        session_id = str(
            session.get(
                "session_id",
                "",
            )
        )

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)

        if session_id:
            if sync_status == "synced":
                resync_button = QPushButton("Re-sincronizar")
                resync_button.setObjectName("secondaryButton")
                resync_button.setFixedWidth(ROW_BUTTON_WIDTH)
                resync_button.setFixedHeight(36)
                resync_button.setEnabled(not self.postgame_sync_in_progress)
                resync_button.clicked.connect(
                    lambda checked=False, value=session_id: self.request_resync_session(
                        value
                    )
                )
                actions.addWidget(resync_button, 1, 0)

            elif sync_status in {
                "live_only",
                "pending",
                "failed",
                "not_found",
            }:
                # Modos locales que nunca están en Riot Match-V5.
                _practice_modes = {
                    "PRACTICETOOL",
                    "PRACTICE",
                    "TUTORIAL",
                    "CUSTOM",
                    "CUSTOM_GAME",
                }
                _is_local_only = str(game_mode).upper() in _practice_modes

                button_label = (
                    "Reintentar Riot" if sync_status == "not_found" else "Buscar Riot"
                )
                sync_button = QPushButton(button_label)

                # Las partidas locales usan objectName diferente para mostrarse
                # visualmente más apagadas que un botón deshabilitado normal.
                # No disponible sincronizacion para practica, tutorial o personalizada.
                if _is_local_only:
                    sync_button.setObjectName("disabledSyncButton")
                    sync_button.setToolTip(
                        "Sin sincronización Riot (práctica / tutorial / personalizada)"
                    )
                else:
                    sync_button.setObjectName("secondaryButton")
                    if sync_status == "not_found":
                        sync_button.setToolTip(
                            "Puedes reintentar si crees que ya fue procesada por Riot."
                        )

                sync_button.setFixedWidth(ROW_BUTTON_WIDTH)
                sync_button.setFixedHeight(36)
                sync_button.setEnabled(
                    not self.postgame_sync_in_progress and not _is_local_only
                )
                sync_button.clicked.connect(
                    lambda checked=False, value=session_id: (
                        self.request_saved_session_sync(value)
                    )
                )
                actions.addWidget(sync_button, 1, 0)

        # El repaso con vídeo solo se ofrece cuando la partida tiene una
        # grabación asociada: sin vídeo, el botón no aparece.
        if recording is not None:
            has_recording = bool(recording)
        else:
            has_recording = False
            find_recording = getattr(
                self,
                "find_recording_for_session",
                None,
            )

            if callable(find_recording) and isinstance(session, dict):
                has_recording = bool(find_recording(session))

        if has_recording:
            replay_button = QPushButton("Repaso con vídeo")
            replay_button.setObjectName("primaryButton")
            replay_button.setFixedWidth(ROW_BUTTON_WIDTH)
            replay_button.setFixedHeight(36)
            replay_button.setToolTip(
                "Abre la ventana independiente de repaso: grabación de la "
                "partida y desglose construido con la telemetría local."
            )
            replay_button.clicked.connect(
                lambda checked=False, value=session: self.open_replay_window(
                    session=value
                )
            )
            actions.addWidget(replay_button, 0, 0, Qt.AlignmentFlag.AlignRight)

        open_button = QPushButton("Abrir análisis")
        open_button.setObjectName("primaryButton")
        open_button.setFixedWidth(ROW_BUTTON_WIDTH)
        open_button.setFixedHeight(36)
        open_button.clicked.connect(
            lambda checked=False, value=session: self.open_saved_game_analysis(value)
        )
        actions.addWidget(open_button, 0, 1, Qt.AlignmentFlag.AlignRight)

        delete_button = QPushButton("Eliminar")
        delete_button.setObjectName("dangerButton")
        delete_button.setFixedWidth(ROW_BUTTON_WIDTH)
        delete_button.setFixedHeight(36)
        if session_id:
            delete_button.clicked.connect(
                lambda checked=False, val=session_id: self.delete_saved_game_session(
                    val
                )
            )
        delete_button.setEnabled(bool(session_id))
        actions.addWidget(delete_button, 1, 1)

        layout.addLayout(actions)

        return row

    def format_saved_session_date(
        self,
        value: str,
    ) -> str:
        if not value:
            return "Fecha desconocida"

        try:
            date = datetime.fromisoformat(value)
        except ValueError:
            return value

        return date.astimezone().strftime("%d/%m/%Y %H:%M")

    def request_saved_session_sync(
        self,
        session_id: str,
    ) -> None:
        """
        Busca manualmente datos Riot solo para una partida pública.

        Las partidas de práctica y custom se conservan como telemetría
        LIVE porque no se pueden asumir disponibles en Match-V5.
        """
        if self.postgame_sync_in_progress:
            return

        if not session_id:
            return

        sessions = self.live_match_tracker.load_saved_sessions()

        session = next(
            (value for value in sessions if value.get("session_id") == session_id),
            None,
        )

        if not isinstance(session, dict):
            return

        game_mode = str(
            session.get(
                "game_mode",
                "",
            )
        ).upper()

        practice_modes = {
            "PRACTICETOOL",
            "PRACTICE",
            "TUTORIAL",
            "CUSTOM",
            "CUSTOM_GAME",
        }

        if game_mode in practice_modes:
            self.update_saved_session_sync_status(
                session_id,
                "live_only",
                (
                    "No disponible en Riot Match-V5: "
                    "las partidas de práctica, tutorial y "
                    "personalizadas conservan telemetría LIVE local."
                ),
            )

            self.refresh_saved_games()
            return

        if not self.riot_api_key:
            self.update_saved_session_sync_status(
                session_id,
                "failed",
                ("Configura una Riot API key válida antes de buscar datos."),
            )

            self.refresh_saved_games()
            return

        game_name = self.riot_game_name
        tag_line = self.riot_tag_line

        if not game_name or not tag_line:
            self.update_saved_session_sync_status(
                session_id,
                "failed",
                ("Configura tu Riot ID en Ajustes antes de buscar datos."),
            )

            self.refresh_saved_games()
            return

        self.pending_postgame_session_id = session_id

        self.update_saved_session_sync_status(
            session_id,
            "pending",
            "Buscando detalle y timeline en Riot…",
        )

        self.refresh_saved_games()

        self.start_postgame_sync(session_id)

    def request_resync_session(
        self,
        session_id: str,
    ) -> None:
        """
        Fuerza una nueva sincronización con Riot para una partida ya sincronizada.

        Limpia final_sync y official_events, y vuelve a llamar a
        request_saved_session_sync().
        """
        if self.postgame_sync_in_progress:
            return

        if not session_id:
            return

        sessions = self.live_match_tracker.load_saved_sessions()

        session = next(
            (value for value in sessions if value.get("session_id") == session_id),
            None,
        )

        if not isinstance(session, dict):
            return

        # Limpiar estado de sincronización previa
        session["final_sync"] = {
            "status": "live_only",
            "match_id": None,
            "synced_at": None,
            "source": "live_client_data_api",
            "message": "Pendiente de re-sincronización.",
        }
        session.pop("performance_scoring", None)

        # Quitar eventos oficiales para que se regeneren
        session.pop("official_events", None)

        # Volver a usar eventos LIVE hasta que termine la nueva sync
        session["events"] = session.get("events", [])

        self.live_match_tracker._save_sessions(sessions)

        # Lanzar de nuevo la sincronización con Riot
        self.request_saved_session_sync(session_id)

    def update_saved_session_sync_status(
        self,
        session_id: str,
        status: str,
        message: str,
    ) -> None:
        """
        Actualiza solo el estado de sincronización de una partida guardada.

        No modifica snapshots, eventos, inventario ni métricas LIVE.
        """
        if not session_id:
            return

        sessions = self.live_match_tracker.load_saved_sessions()

        changed = False

        for session in sessions:
            if session.get("session_id") != session_id:
                continue

            changed = actualizar_estado_sync_final(session, status, message)
            break

        if changed:
            self.live_match_tracker._save_sessions(sessions)

    def open_saved_game_analysis(
        self,
        session: dict,
    ) -> None:
        dialog = LiveMatchAnalysisDialog(
            session,
            self.data_dragon_assets,
            self.item_catalog,
            self,
            tracker=self.live_match_tracker,
        )
        dialog.exec()

    def create_settings_page(self) -> QWidget:
        """Agrupa los ajustes existentes en pestañas desplazables; devuelve la página."""
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        pestanas = QTabWidget()
        pestanas.setObjectName("settingsTabs")
        for titulo, tarjeta in zip(
            (
                "Cuenta y Riot",
                "Análisis con IA",
                "Grabación y almacenamiento",
                "Overlay y avisos",
            ),
            self._settings_cards(),
        ):
            contenido = QWidget()
            disposicion = QVBoxLayout(contenido)
            disposicion.setContentsMargins(18, 18, 18, 18)
            disposicion.setSpacing(12)
            disposicion.addWidget(tarjeta)
            disposicion.addStretch(1)
            pestanas.addTab(PaginaDesplazable(contenido), titulo)
        layout.addWidget(pestanas)
        return page

    def _settings_cards(self) -> list[QWidget]:
        return [
            self._settings_api_card(),
            self._settings_gemini_card(),
            self._settings_recordings_card(),
            self._settings_overlay_card(),
        ]

    def _settings_card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(12)

        header = QLabel(title)
        header.setObjectName("sectionTitle")
        card_layout.addWidget(header)

        return card, card_layout

    def _settings_description(self, text: str) -> QLabel:
        description = QLabel(text)
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        description.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.MinimumExpanding,
        )

        return description

    def _settings_slider_row(
        self,
        label: str,
        low: int,
        high: int,
        step: int,
        start: int,
    ) -> tuple[QHBoxLayout, QSlider, QLabel]:
        row = QHBoxLayout()
        row.setSpacing(10)

        caption = QLabel(label)
        caption.setObjectName("settingsLabel")
        caption.setMinimumWidth(150)
        row.addWidget(caption)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(step)
        slider.setValue(start)
        row.addWidget(slider, 1)

        value = QLabel()
        value.setObjectName("opacityValue")
        value.setMinimumWidth(46)
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(value)

        return row, slider, value

    def _settings_web_button(self, url: str, label: str) -> QPushButton:
        """Botón que abre una web en el navegador del sistema."""
        button = QPushButton(label)
        button.setObjectName("secondaryButton")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(url)
        button.clicked.connect(
            lambda checked=False, target=url: QDesktopServices.openUrl(QUrl(target))
        )

        return button

    def _settings_api_card(self) -> QWidget:
        card, card_layout = self._settings_card(
            "Riot API — datos de invocador e historial"
        )

        card_layout.addWidget(
            self._settings_description(
                "La Riot API es el canal oficial de datos de Riot: partidas, "
                "estadísticas, perfiles, tier list, etc. SolraLoL la usa para "
                "sincronizar «Partidas guardadas» (KDA, oro, objetivos, timelines "
                "juego a juego), cargar el historial soloQ y siempre cuando un "
                "diálogo de análisis necesita datos oficiales."
            )
        )

        steps = QLabel(
            "Cómo conseguir la clave:\n"
            "1. Ve a developer.riotgames.com e inicia sesión con tu cuenta "
            "Riot.\n"
            "2. En el panel de desarrollador, acepta las condiciones y pulsa "
            "«Generate API Key» para crear una clave de desarrollo.\n"
            "3. Pega aquí la clave (empieza por RGAPI-). Caduca cada 24 h, "
            "así que vuelve a generarla cuando deje de funcionar.\n"
            "4. Con la clave activa: se sincronizan «Partidas guardadas», "
            "el historial soloQ y las estadísticas externas de análisis.\n"
            "La clave se guarda solo en tu equipo, dentro de la configuración "
            "local de la app."
        )
        steps.setObjectName("settingsSteps")
        steps.setTextFormat(Qt.TextFormat.PlainText)
        steps.setWordWrap(True)
        card_layout.addWidget(steps)

        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("apiKeyInput")
        self.api_key_input.setPlaceholderText(
            "RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setText(self.riot_api_key)
        card_layout.addWidget(self.api_key_input)

        api_actions = QHBoxLayout()
        api_actions.setSpacing(10)

        self.save_api_key_button = QPushButton("Guardar y comprobar")
        self.save_api_key_button.setObjectName("primaryButton")
        self.save_api_key_button.clicked.connect(self.save_and_validate_api_key)
        api_actions.addWidget(self.save_api_key_button)

        self.clear_api_key_button = QPushButton("Eliminar clave")
        self.clear_api_key_button.setObjectName("secondaryButton")
        self.clear_api_key_button.clicked.connect(self.clear_api_key)
        api_actions.addWidget(self.clear_api_key_button)

        api_actions.addWidget(
            self._settings_web_button(
                "https://developer.riotgames.com",
                "Abrir portal de desarrolladores ↗",
            )
        )

        api_actions.addStretch(1)
        card_layout.addLayout(api_actions)

        self.api_key_status = QLabel()
        self.api_key_status.setObjectName("apiKeyStatus")
        self.update_api_key_status()

        card_layout.addWidget(self.api_key_status)

        return card

    def _settings_gemini_card(self) -> QWidget:
        card, card_layout = self._settings_card("IA Gemini (Google AI Studio)")

        card_layout.addWidget(
            self._settings_description(
                "La IA Gemini alimenta el re-análisis inteligente de "
                "campeones: lee tus partidas y sugiere builds, runas y "
                "consejos concretos desde la pestaña de edición. Se "
                "consigue gratis en Google AI Studio con tu cuenta de "
                "Google y se guarda solo en tu configuración local."
            )
        )

        gemini_steps = QLabel(
            "Cómo conseguir la clave:\n"
            "1. Ve a aistudio.google.com e inicia sesión con tu cuenta de "
            "Google.\n"
            "2. Pulsa «Get API key» → «Create API key» dentro de un proyecto.\n"
            "3. Copia la clave (empieza por AIzaSy…) y pégala aquí abajo. "
            "La capa gratuita es más que suficiente para el re-análisis."
        )
        gemini_steps.setObjectName("settingsSteps")
        gemini_steps.setTextFormat(Qt.TextFormat.PlainText)
        gemini_steps.setWordWrap(True)
        card_layout.addWidget(gemini_steps)

        self.gemini_api_key_input = QLineEdit()
        self.gemini_api_key_input.setObjectName("apiKeyInput")
        self.gemini_api_key_input.setPlaceholderText("AIzaSy...")
        self.gemini_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key_input.setText(self.gemini_api_key)
        card_layout.addWidget(self.gemini_api_key_input)

        gemini_actions = QHBoxLayout()
        gemini_actions.setSpacing(10)

        self.save_gemini_api_key_button = QPushButton("Guardar y comprobar Gemini Key")
        self.save_gemini_api_key_button.setObjectName("primaryButton")
        self.save_gemini_api_key_button.clicked.connect(
            self.save_and_validate_gemini_api_key
        )
        gemini_actions.addWidget(self.save_gemini_api_key_button)

        self.clear_gemini_api_key_button = QPushButton("Eliminar clave Gemini")
        self.clear_gemini_api_key_button.setObjectName("secondaryButton")
        self.clear_gemini_api_key_button.clicked.connect(self.clear_gemini_api_key)
        gemini_actions.addWidget(self.clear_gemini_api_key_button)

        gemini_actions.addWidget(
            self._settings_web_button(
                "https://aistudio.google.com/apikey",
                "Abrir Google AI Studio ↗",
            )
        )

        gemini_actions.addStretch(1)
        card_layout.addLayout(gemini_actions)

        self.gemini_api_key_status = QLabel()
        self.gemini_api_key_status.setObjectName("apiKeyStatus")
        self.gemini_api_key_status.setWordWrap(True)
        card_layout.addWidget(self.gemini_api_key_status)

        self.update_gemini_api_key_status()

        return card

    def _settings_recordings_card(self) -> QWidget:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        card, card_layout = self._settings_card("Grabaciones")

        card_layout.addWidget(
            self._settings_description(
                "Cada partida se graba sola: la grabación empieza cuando "
                "empieza la partida y termina al acabarla. Guarda el vídeo "
                "de la pantalla con el sonido del juego; el micrófono es "
                "opcional. Los cambios se aplican a la próxima grabación."
            )
        )

        self.recording_auto_checkbox = Interruptor(
            "Grabar cada partida automáticamente"
        )
        self.recording_auto_checkbox.setChecked(
            bool(self.settings.get("recording_auto", True))
        )
        self.recording_auto_checkbox.toggled.connect(self._on_recording_auto_toggled)
        card_layout.addWidget(self.recording_auto_checkbox)

        quality_row = QHBoxLayout()
        quality_row.setSpacing(10)

        quality_caption = QLabel("Calidad de vídeo")
        quality_caption.setObjectName("settingsLabel")
        quality_caption.setMinimumWidth(150)
        quality_row.addWidget(quality_caption)

        self.recording_quality_combo = QComboBox()
        self.recording_quality_combo.setObjectName("analysisCombo")

        for key in (
            "1080",
            "108030",
            "900",
            "90030",
            "720",
            "72030",
            "540",
            "480",
            "420",
        ):
            self.recording_quality_combo.addItem(quality_label(key), key)

        self.set_combo_value(
            self.recording_quality_combo,
            str(self.settings.get("recording_quality", "1080")),
        )
        self.recording_quality_combo.currentIndexChanged.connect(
            self._on_recording_quality_changed
        )
        quality_row.addWidget(self.recording_quality_combo, 1)
        card_layout.addLayout(quality_row)

        bitrate_row = QHBoxLayout()
        bitrate_row.setSpacing(10)

        bitrate_caption = QLabel("Bitrate de vídeo")
        bitrate_caption.setObjectName("settingsLabel")
        bitrate_caption.setMinimumWidth(150)
        bitrate_row.addWidget(bitrate_caption)

        self.recording_bitrate_combo = QComboBox()
        self.recording_bitrate_combo.setObjectName("analysisCombo")

        for value in sorted(BITRATE_PRESETS):
            self.recording_bitrate_combo.addItem(bitrate_label(value), value)

        self.set_combo_value(
            self.recording_bitrate_combo,
            int(self.settings.get("recording_bitrate", DEFAULT_BITRATE)),
        )
        self.recording_bitrate_combo.currentIndexChanged.connect(
            self._on_recording_bitrate_changed
        )
        bitrate_row.addWidget(self.recording_bitrate_combo, 1)
        card_layout.addLayout(bitrate_row)

        card_layout.addWidget(
            self._settings_description(
                "Desplegables: calidad de 1080p a 420p, y bitrate de "
                "1,5 a 16 Mbps. Más calidad y más bitrate = más peso."
            )
        )

        # Selección del modo de audio para la grabación.
        audio_mode_row = QHBoxLayout()
        audio_mode_row.setSpacing(10)

        audio_mode_caption = QLabel("Qué sonido se graba")
        audio_mode_caption.setObjectName("settingsLabel")
        audio_mode_caption.setMinimumWidth(150)
        audio_mode_row.addWidget(audio_mode_caption)

        self.recording_audio_mode_combo = QComboBox()
        self.recording_audio_mode_combo.setObjectName("analysisCombo")

        for mode in AUDIO_MODES:
            self.recording_audio_mode_combo.addItem(AUDIO_MODE_LABELS[mode], mode)

        self.set_combo_value(
            self.recording_audio_mode_combo,
            RecordingConfig.from_settings(self.settings).audio_mode,
        )
        self.recording_audio_mode_combo.currentIndexChanged.connect(
            self._on_recording_audio_mode_changed
        )
        audio_mode_row.addWidget(self.recording_audio_mode_combo, 1)
        card_layout.addLayout(audio_mode_row)

        # Panel de insumos de audio: cada checkbox habilita/deshabilita su
        # dispositivo dentro del modo seleccionado. El modo "full" añade un
        # tercer insumo (mezcla del sistema) que captura Discord, YouTube,
        # navegadores, etc.
        audio_mix_card = QFrame()
        audio_mix_card.setObjectName("sectionCard")
        audio_mix_card.setMinimumHeight(150)
        audio_mix_layout = QVBoxLayout(audio_mix_card)
        audio_mix_layout.setContentsMargins(14, 12, 14, 12)
        audio_mix_layout.setSpacing(10)

        # --- Sonido del juego ---
        game_input = QWidget()
        game_input_layout = QHBoxLayout(game_input)
        game_input_layout.setContentsMargins(0, 0, 0, 0)
        game_input_layout.setSpacing(10)

        self.recording_game_audio_caption = QLabel("Sonido del juego")
        self.recording_game_audio_caption.setObjectName("settingsLabel")
        self.recording_game_audio_caption.setMinimumWidth(150)
        game_input_layout.addWidget(self.recording_game_audio_caption)

        self.recording_game_audio_combo = QComboBox()
        self.recording_game_audio_combo.setObjectName("analysisCombo")
        self.recording_game_audio_combo.currentIndexChanged.connect(
            self._on_recording_game_audio_changed
        )
        game_input_layout.addWidget(self.recording_game_audio_combo, 1)
        audio_mix_layout.addWidget(game_input)

        # --- Micrófono ---
        mic_input = QWidget()
        mic_input_layout = QHBoxLayout(mic_input)
        mic_input_layout.setContentsMargins(0, 0, 0, 0)
        mic_input_layout.setSpacing(10)

        self.recording_mic_caption = QLabel("Micrófono")
        self.recording_mic_caption.setObjectName("settingsLabel")
        self.recording_mic_caption.setMinimumWidth(150)
        mic_input_layout.addWidget(self.recording_mic_caption)

        self.recording_mic_combo = QComboBox()
        self.recording_mic_combo.setObjectName("analysisCombo")
        self.recording_mic_combo.currentIndexChanged.connect(
            self._on_recording_mic_device_changed
        )
        mic_input_layout.addWidget(self.recording_mic_combo, 1)
        audio_mix_layout.addWidget(mic_input)

        # --- Todo el resto (Discord, YouTube, …) ---
        system_input = QWidget()
        system_input_layout = QHBoxLayout(system_input)
        system_input_layout.setContentsMargins(0, 0, 0, 0)
        system_input_layout.setSpacing(10)

        self.recording_system_audio_caption = QLabel(
            "Todo el resto (Discord, YouTube, …)"
        )
        self.recording_system_audio_caption.setObjectName("settingsLabel")
        self.recording_system_audio_caption.setMinimumWidth(150)
        system_input_layout.addWidget(self.recording_system_audio_caption)

        self.recording_system_audio_combo = QComboBox()
        self.recording_system_audio_combo.setObjectName("analysisCombo")
        self.recording_system_audio_combo.setDisabled(True)
        self.recording_system_audio_combo.currentIndexChanged.connect(
            self._on_recording_system_audio_changed
        )
        system_input_layout.addWidget(self.recording_system_audio_combo, 1)
        audio_mix_layout.addWidget(system_input)

        card_layout.addWidget(audio_mix_card)

        # Nota sobre qué hace falta para el modo "full".
        card_layout.addWidget(
            self._settings_description(
                "«Todo el resto» necesita un capturador de la mezcla del "
                "sistema (Stereo Mix, VB-Cable, Voicemeeter…): si el sonido "
                "del juego ya sale de uno de esos, ese mismo ya incluye "
                "Discord y YouTube y no se añade otro aparte."
            )
        )

        # Botón para refrescar dispositivos de sistema (solo en modo full).
        self.recording_system_audio_button = QPushButton(
            "Buscar dispositivos del sistema"
        )
        self.recording_system_audio_button.setObjectName("secondaryButton")
        self.recording_system_audio_button.setDisabled(True)
        self.recording_system_audio_button.clicked.connect(
            self.refresh_system_audio_devices
        )
        card_layout.addWidget(self.recording_system_audio_button)

        card_layout.addWidget(
            self._settings_description(
                "Al elegir “full”, la app guarda automáticamente la "
                "configuración de captura de sistema y vuelve a buscar "
                "dispositivos de mezcla del sistema. Si no hay ninguno "
                "disponible, el modo “full” solo captura juego + micrófono."
            )
        )

        card_layout.addStretch(1)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(10)

        folder_caption = QLabel("Carpeta de grabaciones")
        folder_caption.setObjectName("settingsLabel")
        folder_caption.setMinimumWidth(150)
        folder_row.addWidget(folder_caption)

        self.recording_dir_input = QLineEdit(
            str(self.settings.get("recording_output_dir", ""))
        )
        self.recording_dir_input.setReadOnly(True)
        self.recording_dir_input.setObjectName("apiKeyInput")
        folder_row.addWidget(self.recording_dir_input, 1)

        self.recording_dir_button = QPushButton("Cambiar…")
        self.recording_dir_button.setObjectName("secondaryButton")
        self.recording_dir_button.clicked.connect(self.choose_recordings_folder)
        folder_row.addWidget(self.recording_dir_button)

        self.recording_folder_button = QPushButton("Abrir")
        self.recording_folder_button.setObjectName("secondaryButton")
        self.recording_folder_button.clicked.connect(self.open_recordings_folder)
        folder_row.addWidget(self.recording_folder_button)

        card_layout.addLayout(folder_row)

        limit_row, self.recording_limit_slider, self.recording_limit_value = (
            self._settings_slider_row(
                "Límite de peso total",
                LIMIT_MIN_GB,
                LIMIT_MAX_GB,
                5,
                int(
                    float(
                        self.settings.get(
                            "recording_size_limit_gb",
                            LIMIT_DEFAULT_GB,
                        )
                    )
                ),
            )
        )
        self.recording_limit_value.setText(
            f"{int(float(self.settings.get('recording_size_limit_gb', LIMIT_DEFAULT_GB)))} GB"
        )
        self.recording_limit_slider.valueChanged.connect(
            self._on_recording_limit_changed
        )
        card_layout.addLayout(limit_row)

        card_layout.addWidget(
            self._settings_description(
                "Cuando la carpeta supere ese límite, la última "
                "grabación se guarda igual y se borran las más "
                "antiguas hasta caber."
            )
        )

        self.recording_status = QLabel()
        self.recording_status.setObjectName("apiKeyStatus")
        self.recording_status.setWordWrap(True)
        card_layout.addWidget(self.recording_status)

        self.refresh_recording_devices(silent=True)
        self.sync_recording_controls()

        return card

    # -- ajustes de grabación -------------------------------------------

    def _save_recording_settings(self) -> None:
        self.settings_service.save(self.settings)
        self.recording_config = RecordingConfig.from_settings(self.settings)
        self.recording_library.set_directory(self.recording_config.output_dir)

    def _on_recording_auto_toggled(self, checked: bool) -> None:
        self.settings["recording_auto"] = bool(checked)
        self._save_recording_settings()
        self.sync_recording_controls()

    def _on_recording_quality_changed(self, _index: int) -> None:
        value = self.recording_quality_combo.currentData()

        if value:
            self.settings["recording_quality"] = str(value)
            self._save_recording_settings()

        self.sync_recording_controls()

    def _on_recording_bitrate_changed(self, _index: int) -> None:
        value = self.recording_bitrate_combo.currentData()

        if value is not None:
            self.settings["recording_bitrate"] = int(value)
            self._save_recording_settings()

        self.sync_recording_controls()

    def _on_recording_audio_mode_changed(self, _index: int) -> None:
        if not hasattr(self, "recording_audio_mode_combo"):
            return

        value = self.recording_audio_mode_combo.currentData()

        if value is not None:
            # Se persiste en cuanto se elige: así la próxima lectura de
            # RecordingConfig no tiene que deducirlo de las claves viejas.
            self.settings["recording_audio_mode"] = str(value)
            # El tercer insumo («Todo el resto») solo tiene sentido en los
            # modos que mezclan el sistema: se marca aquí para que
            # RecordingConfig.from_settings no lo pierda y el arranque lo
            # resuelva (con fallback si el dispositivo ya no existe).
            # En el resto de modos se desmarca para no arrastrar un insumo
            # fantasma de un modo anterior.
            self.settings["recording_mic_capture_enabled"] = bool(
                audio_mode_uses_system(normalize_audio_mode(str(value)))
            )
            self._save_recording_settings()

        # Al entrar en un modo con sistema se repuebla el combo del tercer
        # insumo (puede estar vacío si nunca se abrió); al salir no hace
        # falta sondear nada.
        if audio_mode_uses_system(
            normalize_audio_mode(self.settings.get("recording_audio_mode", ""))
        ):
            self.refresh_system_audio_devices()

        self.sync_recording_controls()

    def _on_recording_game_audio_changed(self, _index: int) -> None:
        if not hasattr(self, "recording_game_audio_combo"):
            return

        value = self.recording_game_audio_combo.currentData()

        if value is not None:
            self.settings["recording_game_audio_device"] = str(value)
            self._save_recording_settings()

        self.sync_recording_controls()

    def _on_recording_mic_device_changed(self, _index: int) -> None:
        if not hasattr(self, "recording_mic_combo"):
            return

        value = self.recording_mic_combo.currentData()

        if value is not None:
            self.settings["recording_mic_device"] = str(value)
            self._save_recording_settings()

        self.sync_recording_controls()

    # -- ffmpeg y dispositivos de audio (fuera del hilo de la interfaz) --

    def _start_background_ffmpeg_check(self) -> None:
        """Busca ffmpeg al arrancar sin bloquear la construcción de la ventana.

        ``find_ffmpeg`` recorre el ``PATH`` y comprueba candidatos en disco;
        hasta que el worker no conteste, los Ajustes muestran «Comprobando
        ffmpeg…» en vez de dar por hecho que no existe.
        """
        configured = str(self.settings.get("ffmpeg_path") or "")

        self._refresh_ffmpeg_task = run_async(
            lambda: find_ffmpeg(configured),
            on_finished=self._apply_ffmpeg_check,
        )

    def _apply_ffmpeg_check(
        self, _token: Any, found: str | None, error: str | None
    ) -> None:
        """Publica el binario detectado y reanuda una grabación aplazada.

        Parámetros:
            _token: Identificador opaco de la tarea.
            found: Ruta detectada o None.
            error: Error del worker o None.

        Retorno:
            None.
        """
        self._refresh_ffmpeg_task = None

        if not error:
            self.recording_service.apply_ffmpeg_result(found)

        self._ffmpeg_ready = bool(found) and not error

        pending_snapshot = self._pending_recording_snapshot
        self._pending_recording_snapshot = None

        if pending_snapshot is not None:
            self.start_match_recording(pending_snapshot)

        if hasattr(self, "recording_status"):
            self.sync_recording_controls()

    def _set_audio_combos_loading(self) -> None:
        """Marca los desplegables de audio como «Buscando…» y los deshabilita."""
        for name in ("recording_game_audio_combo", "recording_mic_combo"):
            combo = getattr(self, name, None)

            if combo is None:
                continue

            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Buscando dispositivos de audio…", "")
            combo.setEnabled(False)
            combo.blockSignals(False)

    def _on_recording_system_audio_changed(self, _index: int) -> None:
        if not hasattr(self, "recording_system_audio_combo"):
            return

        value = self.recording_system_audio_combo.currentData()

        if value is not None:
            self.settings["recording_system_audio_device"] = str(value)
            self._save_recording_settings()

        self.sync_recording_controls()

    def refresh_system_audio_devices(self) -> None:
        """Repite en background el sondeo de capturadores de sistema.

        Lo pide el botón de «buscar dispositivos»: fuerza una consulta nueva a
        ffmpeg (puede tardar segundos), así que se hace en un worker y el
        desplegable queda deshabilitado con un texto de espera mientras tanto.
        """
        combo = getattr(self, "recording_system_audio_combo", None)

        if combo is None:
            return

        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Buscando dispositivos del sistema…", "")
        combo.setEnabled(False)
        combo.blockSignals(False)

        configured = str(self.settings.get("ffmpeg_path") or "")

        def scan() -> tuple[str | None, list[str]]:
            found = find_ffmpeg(configured)
            devices = list_audio_devices(found or "", force=True) if found else []

            return found, devices

        self._system_devices_task = run_async(
            scan,
            on_finished=self._apply_system_audio_devices,
        )

    def _apply_system_audio_devices(self, _token, result, error) -> None:
        """Vuelca en el combo de sistema lo que devolvió el worker."""
        self._system_devices_task = None

        combo = getattr(self, "recording_system_audio_combo", None)

        if combo is None:
            return

        found, devices = self._unpack_device_scan(result, error)
        self.recording_service.apply_ffmpeg_result(found)
        combo.setEnabled(True)

        if not found:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Sin ffmpeg: no se puede grabar", "")
            combo.blockSignals(False)
            self.sync_recording_controls()

            return

        saved_system = str(
            self.settings.get("recording_system_audio_device")
            or self.settings.get("recording_mic_capture_device")
            or ""
        )

        # Si lo guardado ya no existe (dispositivo desconectado) se reelige
        # para no arrancar con un dshow que falla; si sigue sin haber nada
        # se deja en automático y el arranque aplicará el fallback.
        if saved_system and saved_system not in set(devices):
            saved_system = pick_system_audio_device(devices) or ""

        if not saved_system:
            saved_system = pick_system_audio_device(devices)

            if saved_system:
                self.settings["recording_system_audio_device"] = saved_system

        # Migrar la clave antigua a la moderna para no arrastrar dos fuentes
        # de verdad distintas.
        if saved_system:
            self.settings["recording_system_audio_device"] = saved_system
            self.settings["recording_mic_capture_device"] = saved_system

        self._fill_audio_combo(
            combo,
            devices,
            saved_system,
            "Automático (mejor capturador de sistema disponible)",
        )

        if audio_mode_uses_system(
            normalize_audio_mode(self.settings.get("recording_audio_mode", ""))
        ):
            self.settings["recording_mic_capture_enabled"] = True

        self._save_recording_settings()
        self.sync_recording_controls()

    def _on_recording_limit_changed(self, gigabytes: int) -> None:
        self.settings["recording_size_limit_gb"] = float(gigabytes)
        self.recording_limit_value.setText(f"{int(gigabytes)} GB")
        self._save_recording_settings()
        self.sync_recording_controls()

    @staticmethod
    def _unpack_device_scan(result, error: str | None) -> tuple[str | None, list[str]]:
        """Normaliza lo que devuelve un worker de sondeo de dispositivos.

        Un error del worker (o un resultado inesperado) se trata como «no hay
        ffmpeg»: la interfaz nunca se queda con un desplegable a medias.
        """
        if not error and isinstance(result, tuple) and len(result) == 2:
            found, devices = result

            return found or None, list(devices or [])

        return None, []

    def refresh_recording_devices(self, silent: bool = False) -> None:
        """Pide a un worker los dispositivos de audio que ve ffmpeg.

        El sondeo DirectShow lanza ffmpeg y tarda varios segundos: se hace
        fuera del hilo de la interfaz. Mientras responde, los desplegables de
        juego y micrófono avisan de que están cargando.

        ``silent`` usa la caché de dispositivos (apertura de Ajustes) y evita
        pisar el texto de estado; el rescan explícito se hace desde el botón
        de dispositivos del sistema.
        """
        if not hasattr(self, "recording_game_audio_combo"):
            return

        self._set_audio_combos_loading()

        configured = str(self.settings.get("ffmpeg_path") or "")
        force = not silent

        def scan() -> tuple[str | None, list[str]]:
            found = find_ffmpeg(configured)
            devices = list_audio_devices(found or "", force=force) if found else []

            return found, devices

        self._devices_task = run_async(
            scan,
            on_finished=lambda token, result, error: self._apply_recording_devices(
                result, error, silent
            ),
        )

    def _apply_recording_devices(self, result, error: str | None, silent: bool) -> None:
        """Rellena los desplegables de juego y micrófono con el sondeo."""
        self._devices_task = None

        if not hasattr(self, "recording_game_audio_combo"):
            return

        found, devices = self._unpack_device_scan(result, error)
        self.recording_service.apply_ffmpeg_result(found)

        combos = (
            self.recording_game_audio_combo,
            self.recording_mic_combo,
        )

        if not found:
            for combo in combos:
                combo.setEnabled(True)
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("Sin ffmpeg: no se puede grabar", "")
                combo.blockSignals(False)

            self.sync_recording_controls()

            if not silent and hasattr(self, "recording_status"):
                self.recording_status.setText(self.recording_service.ffmpeg_hint)

            return

        saved_game = str(self.settings.get("recording_game_audio_device") or "")
        saved_mic = str(self.settings.get("recording_mic_device") or "")

        if not saved_game:
            saved_game = pick_game_audio_device(devices)

            if saved_game:
                self.settings["recording_game_audio_device"] = saved_game

        if not saved_mic:
            saved_mic = pick_microphone_device(devices)

            if saved_mic:
                self.settings["recording_mic_device"] = saved_mic

        for combo in combos:
            combo.setEnabled(True)

        self._fill_audio_combo(
            self.recording_game_audio_combo,
            devices,
            saved_game,
            "Automático (mejor capturador disponible)",
        )
        self._fill_audio_combo(
            self.recording_mic_combo,
            devices,
            saved_mic,
            "Automático (mejor micrófono disponible)",
        )
        self._save_recording_settings()
        self.sync_recording_controls()

    def _fill_audio_combo(
        self,
        combo,
        devices: list[str],
        selected: str,
        empty_label: str,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(empty_label, "")

        for device in devices:
            combo.addItem(device, device)

        self.set_combo_value(combo, selected or "")
        combo.blockSignals(False)

    def choose_recordings_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        current = str(self.settings.get("recording_output_dir") or "")
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Carpeta de grabaciones",
            current or str(self.recording_library.directory),
        )

        if not chosen:
            return

        self.settings["recording_output_dir"] = chosen
        self.recording_dir_input.setText(chosen)
        self._save_recording_settings()
        self.sync_recording_controls()

        if hasattr(self, "recordings_page"):
            self.recordings_page.refresh()

    def open_recordings_folder(self, _directory: str = "") -> None:
        from app.ui.recordings_page import RecordingsPage

        directory = str(self.settings.get("recording_output_dir") or "")

        if not directory:
            return

        self.recording_library.ensure_directory()
        RecordingsPage.open_in_explorer(directory)

    # -- ventana independiente de repaso --------------------------------

    def open_replay_window_for_video(self, video_path: str) -> None:
        """Abre la ventana de repaso para una grabación concreta."""
        self.open_replay_window(video_path=video_path)

    def open_replay_window(
        self,
        session: dict | None = None,
        video_path: str = "",
        session_id: str = "",
    ) -> None:
        """Abre (o reutiliza) la ventana independiente de repaso.

        El desglose se construye con la telemetría local de la sesión y el
        vídeo se busca en la carpeta de grabaciones por ``session_id``.
        """
        if session_id and not isinstance(session, dict):
            session = self.find_saved_session(session_id)

        if not video_path and isinstance(session, dict):
            video_path = self.find_recording_for_session(session)

        window = self.replay_window
        reusable = False

        if window is not None:
            try:
                window.isVisible()
                reusable = True
            except RuntimeError:
                self.replay_window = None

        if not reusable:
            # Si se abre en caliente durante la partida, se usa la sesión
            # viva del diálogo LIVE (la más fresca) antes que la copia que
            # llegue por parámetro o la de disco.
            live_session = getattr(self.live_analysis_dialog, "session", None)
            live_id = ""
            wanted_id = ""
            if isinstance(live_session, dict):
                live_id = str(live_session.get("session_id") or "")
            if isinstance(session, dict):
                wanted_id = str(session.get("session_id") or "")
            if (
                isinstance(live_session, dict)
                and live_id
                and (not wanted_id or wanted_id == live_id)
            ):
                session = live_session
            window = PostgameReplayWindow(
                session=session if isinstance(session, dict) else None,
                video_path=video_path or None,
                library=self.recording_library,
                tracker=self.live_match_tracker,
                service=self.recording_service,
                assets=self.data_dragon_assets,
                item_catalog=self.item_catalog,
            )
            window.closed.connect(self.clear_replay_window)
            self.replay_window = window
        else:
            if isinstance(session, dict):
                window.set_session(session)

            if video_path:
                window.load_video(video_path)

        window.show()
        window.raise_()
        window.activateWindow()

    def clear_replay_window(self) -> None:
        """Suelta la referencia al cerrarse la ventana de repaso."""
        self.replay_window = None

    def find_saved_session(self, session_id: str) -> dict | None:
        """Sesión guardada por id (telemetría local del tracker)."""
        wanted = str(session_id or "")

        if not wanted:
            return None

        for session in self.live_match_tracker.load_saved_sessions():
            if str(session.get("session_id") or "") == wanted:
                return session

        return None

    def find_recording_for_session(self, session: dict) -> str:
        """Vídeo de la carpeta de grabaciones que corresponde a la sesión.

        Por ``session_id`` del sidecar y, si ningún sidecar lo declara
        (sidecars antiguos), por ventana temporal entre el inicio del vídeo
        y ``started_at``/``ended_at`` de la sesión.
        """
        found = find_video_for_session(
            self.recording_videos_cached(),
            session,
            self.recording_metadata_cached,
        )

        return str(found) if found is not None else ""

    def sync_recording_controls(self) -> None:
        """Refleja el estado real de la grabación en Ajustes."""
        if not hasattr(self, "recording_status"):
            return

        service = self.recording_service
        config = self.recording_config

        widgets = (
            self.recording_auto_checkbox,
            self.recording_quality_combo,
            self.recording_bitrate_combo,
            self.recording_audio_mode_combo,
            self.recording_game_audio_combo,
            self.recording_mic_combo,
            self.recording_system_audio_combo,
            self.recording_system_audio_button,
            self.recording_dir_button,
        )

        for widget in widgets:
            widget.blockSignals(True)

        self.recording_auto_checkbox.setChecked(config.enabled)
        self.set_combo_value(self.recording_quality_combo, config.quality)
        self.set_combo_value(self.recording_bitrate_combo, config.video_bitrate)
        self.set_combo_value(self.recording_audio_mode_combo, config.audio_mode)
        self.set_combo_value(self.recording_game_audio_combo, config.game_audio_device)
        self.set_combo_value(self.recording_mic_combo, config.mic_device)
        self.recording_limit_slider.setValue(int(config.size_limit_gb))
        self.recording_limit_value.setText(f"{int(config.size_limit_gb)} GB")
        self.recording_dir_input.setText(
            str(self.settings.get("recording_output_dir", ""))
        )

        # Los dispositivos solo tienen sentido en los modos que los usan:
        # se ocultan en vez de deshabilitarse para no marear con opciones.
        # «all» y «full» comparten el tercer insumo («Todo el resto»): la
        # única diferencia es histórica (full es el nombre nuevo de all).
        mode = normalize_audio_mode(config.audio_mode)
        show_game = audio_mode_uses_game(mode)
        show_mic = audio_mode_uses_mic(mode)

        self.recording_game_audio_caption.setVisible(show_game)
        self.recording_game_audio_combo.setVisible(show_game)
        self.recording_mic_caption.setVisible(show_mic)
        self.recording_mic_combo.setVisible(show_mic)

        # El tercer insumo (mezcla del sistema) tiene sentido en «all» y en
        # «full». Se habilita junto con su botón de búsqueda cuando se elige
        # cualquiera de esos modos.
        show_system = audio_mode_uses_system(mode)
        self.recording_system_audio_caption.setVisible(show_system)
        self.recording_system_audio_combo.setVisible(show_system)
        self.recording_system_audio_button.setVisible(show_system)
        self.recording_system_audio_combo.setDisabled(not show_system)
        self.recording_system_audio_button.setDisabled(not show_system)

        # Sincronizar el dispositivo elegido del tercer insumo. La UI guarda
        # la clave moderna ``recording_system_audio_device``; por
        # compatibilidad también se acepta la antigua
        # ``recording_mic_capture_device``.
        if show_system:
            system_value = config.system_audio_device or config.mic_capture_device or ""
            self.set_combo_value(self.recording_system_audio_combo, system_value)

        pieces = []

        searching = (
            self._refresh_ffmpeg_task is not None or self._devices_task is not None
        )

        if service.ffmpeg_available:
            pieces.append("ffmpeg listo")
        elif searching:
            # La búsqueda va en un worker: mientras responde no se da por
            # hecho que falte ffmpeg (sería un aviso falso de un instante).
            pieces.append("Comprobando ffmpeg…")
        else:
            pieces.append(service.ffmpeg_hint or "ffmpeg no encontrado")

        pieces.append(audio_mode_label(config.audio_mode))

        if audio_mode_uses_game(mode) and config.game_audio_device:
            pieces.append(f"Juego: {config.game_audio_device}")

        if audio_mode_uses_mic(mode):
            pieces.append(f"Micro: {config.mic_device or 'automático'}")

        if show_system:
            system_value = config.system_audio_device or config.mic_capture_device or ""
            pieces.append(f"Resto: {system_value or 'automático'}")

        total = self.recording_folder_size()
        pieces.append(
            f"Carpeta: {format_size(total)} de {int(config.size_limit_gb)} GB"
        )

        if service.is_recording:
            elapsed = service.elapsed_seconds()
            minutes, seconds = divmod(int(elapsed), 60)
            pieces.append(f"● Grabando ({minutes:02d}:{seconds:02d})")

        self.recording_status.setText(" · ".join(pieces))

        for widget in widgets:
            widget.blockSignals(False)

        if hasattr(self, "recordings_page"):
            self.recordings_page.sync_recording_state()

    # -- grabación automática de la partida -----------------------------

    def start_match_recording(self, snapshot: dict[str, Any]) -> None:
        """Arranca la grabación al empezar la partida si está activada.

        Parámetros:
            snapshot: Telemetría inicial de la partida.

        Retorno:
            None.
        """
        if (
            self.recording_service.is_recording
            or self.recording_service.is_starting_or_recording
        ):
            return

        if self._refresh_ffmpeg_task is not None:
            self._pending_recording_snapshot = dict(snapshot)

            return

        local_player = snapshot.get("local_player", {})

        if not isinstance(local_player, dict):
            local_player = {}

        champion = str(local_player.get("championName", "Desconocido"))
        game_mode = str(snapshot.get("game_mode", "UNKNOWN"))

        try:
            game_time = float(snapshot.get("game_time", 0))
        except (TypeError, ValueError):
            game_time = 0.0

        self.recording_service.start(
            self.recording_config,
            game_time=game_time,
            champion=champion,
            game_mode=game_mode,
        )
        self.sync_recording_controls()

    def stop_match_recording(self, reason: str, session: dict | None = None) -> None:
        """Para la grabación al terminar la partida."""
        if not self.recording_service.is_recording:
            return

        self.recording_service.stop(reason=reason, session=session)

    def stop_recording_manually(self) -> None:
        """Para la grabación desde el botón «Detener grabación».

        La parada manual no significa que la partida haya terminado: la
        sesión del tracker sigue viva para que, si el juego continúa, los
        datos de la partida sigan acumulándose. La sesión se pasa al motor
        para que los marcadores queden guardados en la grabación.
        """
        if not self.recording_service.is_recording:
            return

        session = self.live_match_tracker.get_live_session()
        self.stop_match_recording(
            "manual", session if isinstance(session, dict) else None
        )
        self.sync_recording_controls()

    def _on_recording_failed(self, message: str) -> None:
        if hasattr(self, "recording_status"):
            current = self.recording_status.text()
            self.recording_status.setText(f"{message} {current}".strip())

        if hasattr(self, "recordings_page"):
            self.recordings_page.refresh()

    def _on_recording_finished(self, _path: str) -> None:
        # Hay un vídeo nuevo en la carpeta: las cachés de sidecars y del
        # listado dejan de valer para las dos listas.
        self.invalidate_recording_metadata_cache()
        self.sync_recording_controls()

        if hasattr(self, "recordings_page"):
            self.recordings_page.refresh()

    def _sync_overlay_recording(self, _state: str = "") -> None:
        """Refleja si se está grabando en el overlay de alertas."""
        if not hasattr(self, "overlay"):
            return

        active = self.recording_service.is_recording
        elapsed = self.recording_service.elapsed_seconds() if active else 0.0
        self.overlay.set_recording(active, elapsed)

    def _settings_overlay_card(self) -> QWidget:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        card, card_layout = self._settings_card("Overlay en partida")

        self.show_overlay_button = QPushButton("Mostrar overlay")
        self.show_overlay_button.setObjectName("primaryButton")
        self.show_overlay_button.clicked.connect(self.toggle_overlay_visibility)
        card_layout.addWidget(self.show_overlay_button)

        overlay_group_title = QLabel("Paneles del overlay")
        overlay_group_title.setObjectName("settingsGroupTitle")
        card_layout.addWidget(overlay_group_title)

        card_layout.addWidget(
            self._settings_description(
                "Tres paneles independientes sobre el juego, sin títulos: "
                "oro por rol aliado contra rival, alertas de objetos "
                "completos y objetivos inminentes, y el rival más fuerte y "
                "el más débil. Se arrastran con el ratón y solo aparecen "
                "durante una partida."
            )
        )

        panels_row = QHBoxLayout()
        panels_row.setSpacing(10)

        self.overlay_panel_buttons: dict[str, QPushButton] = {}
        self.overlay_tab_only_checkboxes: dict[str, QCheckBox] = {}

        for panel_key, panel_name in (
            ("gold", "Oro"),
            ("alerts", "Alertas"),
            ("threat", "Rivales"),
        ):
            button = QPushButton(panel_name)
            button.setObjectName("analysisSourceButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, key=panel_key: self.toggle_overlay_panel(key)
            )
            panels_row.addWidget(button)
            self.overlay_panel_buttons[panel_key] = button

        panels_row.addStretch(1)
        card_layout.addLayout(panels_row)

        tab_only_title = QLabel("Mostrar solo con TAB pulsado")
        tab_only_title.setObjectName("settingsLabel")
        tab_only_title.setToolTip(
            "Cada panel marcado solo se muestra mientras mantienes "
            "pulsado TAB, como el marcador del juego."
        )
        card_layout.addWidget(tab_only_title)

        tab_only_row = QHBoxLayout()
        tab_only_row.setSpacing(10)

        for panel_key, panel_name in (
            ("gold", "Oro"),
            ("alerts", "Alertas"),
            ("threat", "Rivales"),
        ):
            checkbox = Interruptor(f"Solo TAB: {panel_name}")
            checkbox.setChecked(self.overlay.is_tab_only(panel_key))
            checkbox.setToolTip(
                f"El panel {panel_name} solo aparece mientras mantienes pulsado TAB."
            )
            checkbox.toggled.connect(
                lambda checked, key=panel_key: self.toggle_overlay_tab_only(
                    key, checked
                )
            )
            tab_only_row.addWidget(checkbox)
            self.overlay_tab_only_checkboxes[panel_key] = checkbox

        tab_only_row.addStretch(1)
        card_layout.addLayout(tab_only_row)

        self.lock_overlay_button = QPushButton("Bloquear clics: NO")
        self.lock_overlay_button.setObjectName("secondaryButton")
        self.lock_overlay_button.clicked.connect(self.toggle_overlay_click_through)
        card_layout.addWidget(self.lock_overlay_button)

        opacity_row, self.opacity_slider, self.opacity_value = (
            self._settings_slider_row(
                "Opacidad del overlay",
                30,
                100,
                1,
                self.overlay.opacity,
            )
        )
        self.opacity_value.setText(f"{self.overlay.opacity}%")
        self.opacity_slider.valueChanged.connect(self.change_overlay_opacity)
        card_layout.addLayout(opacity_row)

        lead_row, self.alert_lead_slider, self.alert_lead_value = (
            self._settings_slider_row(
                "Aviso de objetivos",
                15,
                180,
                5,
                self.overlay.alert_lead_seconds,
            )
        )
        self.alert_lead_value.setText(f"{self.overlay.alert_lead_seconds} s")
        self.alert_lead_slider.valueChanged.connect(self.change_overlay_alert_lead)
        card_layout.addLayout(lead_row)

        # Controles de sonido
        sound_title = QLabel("Sonidos del overlay")
        sound_title.setObjectName("settingsGroupTitle")
        card_layout.addWidget(sound_title)

        card_layout.addWidget(
            self._settings_description(
                "Cada aviso emite un pitido distinto: uno para Grumos, "
                "Heraldo o Barón, otro para el Dragón y otro cuando un "
                "rival completa un objeto. No se usan archivos de audio "
                "externos."
            )
        )

        self.sound_enabled_checkbox = Interruptor("Activar sonidos del overlay")
        self.sound_enabled_checkbox.setChecked(self.overlay.is_sound_enabled())
        self.sound_enabled_checkbox.toggled.connect(self.toggle_overlay_sound_enabled)
        card_layout.addWidget(self.sound_enabled_checkbox)

        self.sound_objective_checkbox = Interruptor(
            "Pitido: objetivos (Grumos, Heraldo, Barón)"
        )
        self.sound_objective_checkbox.setChecked(
            self.overlay.sound_service.kind_enabled("objective")
        )
        self.sound_objective_checkbox.toggled.connect(
            lambda checked, kind="objective": self.toggle_overlay_sound_kind(
                kind, checked
            )
        )
        card_layout.addWidget(self.sound_objective_checkbox)

        self.sound_dragon_checkbox = Interruptor("Pitido: Dragón")
        self.sound_dragon_checkbox.setChecked(
            self.overlay.sound_service.kind_enabled("dragon")
        )
        self.sound_dragon_checkbox.toggled.connect(
            lambda checked, kind="dragon": self.toggle_overlay_sound_kind(kind, checked)
        )
        card_layout.addWidget(self.sound_dragon_checkbox)

        self.sound_enemy_buy_checkbox = Interruptor("Pitido: compra de objeto rival")
        self.sound_enemy_buy_checkbox.setChecked(
            self.overlay.sound_service.kind_enabled("enemy_buy")
        )
        self.sound_enemy_buy_checkbox.toggled.connect(
            lambda checked, kind="enemy_buy": self.toggle_overlay_sound_kind(
                kind, checked
            )
        )
        card_layout.addWidget(self.sound_enemy_buy_checkbox)

        volume_row, self.sound_volume_slider, self.sound_volume_value = (
            self._settings_slider_row(
                "Volumen de los pitidos",
                0,
                100,
                5,
                int(round(self.overlay.sound_service.volume * 100)),
            )
        )
        self.sound_volume_value.setText(
            f"{int(round(self.overlay.sound_service.volume * 100))}%"
        )
        self.sound_volume_slider.valueChanged.connect(self.change_overlay_sound_volume)
        card_layout.addLayout(volume_row)

        self.overlay_status = QLabel()
        self.overlay_status.setObjectName("apiKeyStatus")
        self.overlay_status.setWordWrap(True)
        card_layout.addWidget(self.overlay_status)

        self.sync_overlay_settings_ui()

        card_layout.addWidget(
            self._settings_description(
                "Los controles se aplican al overlay inmediatamente. "
                "La lectura usa una frecuencia de un segundo y las tarjetas "
                "se regeneran cada diez segundos."
            )
        )

        return card

    def update_api_key_status(self) -> None:
        if self.riot_api_key:
            self.api_key_status.setText(
                "Hay una Riot API key guardada. "
                "Pulsa “Guardar y comprobar” para validarla."
            )
            self.api_key_status.setProperty(
                "state",
                "saved",
            )
        else:
            self.api_key_status.setText("No hay una Riot API key configurada.")
            self.api_key_status.setProperty(
                "state",
                "missing",
            )

        self.api_key_status.style().unpolish(self.api_key_status)
        self.api_key_status.style().polish(self.api_key_status)

    def save_and_validate_api_key(self) -> None:
        api_key = self.api_key_input.text().strip()

        self.save_api_key_button.setEnabled(False)
        self.api_key_status.setText("Comprobando Riot API key...")
        self.api_key_status.setProperty(
            "state",
            "checking",
        )

        self.api_key_status.style().unpolish(self.api_key_status)
        self.api_key_status.style().polish(self.api_key_status)

        valid, message = self.settings_service.validate_riot_api_key(api_key)

        self.save_api_key_button.setEnabled(True)

        if valid:
            self.riot_api_key = api_key
            self.settings["riot_api_key"] = api_key
            self.settings_service.save(self.settings)

            self.api_key_status.setText(message)
            self.api_key_status.setProperty(
                "state",
                "valid",
            )
        else:
            self.riot_api_key = ""
            self.settings.pop("riot_api_key", None)
            self.settings_service.save(self.settings)

            self.api_key_status.setText(message)
            self.api_key_status.setProperty(
                "state",
                "invalid",
            )

        self.api_key_status.style().unpolish(self.api_key_status)
        self.api_key_status.style().polish(self.api_key_status)

    def clear_api_key(self) -> None:
        self.riot_api_key = ""
        self.settings.pop("riot_api_key", None)
        self.settings_service.save(self.settings)

        self.api_key_input.clear()

        self.api_key_status.setText("Riot API key eliminada de la configuración local.")
        self.api_key_status.setProperty(
            "state",
            "missing",
        )

        self.api_key_status.style().unpolish(self.api_key_status)
        self.api_key_status.style().polish(self.api_key_status)

    def update_gemini_api_key_status(self) -> None:
        if self.gemini_api_key:
            self.gemini_api_key_status.setText(
                "Hay una Gemini API key guardada. Pulsa 'Guardar y comprobar' para validarla."
            )
            self.gemini_api_key_status.setProperty("state", "saved")
        else:
            self.gemini_api_key_status.setText("No hay una Gemini API key configurada.")
            self.gemini_api_key_status.setProperty("state", "missing")

        self.gemini_api_key_status.style().unpolish(self.gemini_api_key_status)
        self.gemini_api_key_status.style().polish(self.gemini_api_key_status)

    def save_and_validate_gemini_api_key(self) -> None:
        api_key = self.gemini_api_key_input.text().strip()

        self.save_gemini_api_key_button.setEnabled(False)
        self.gemini_api_key_status.setText("Comprobando Gemini API key...")
        self.gemini_api_key_status.setProperty("state", "checking")
        self.gemini_api_key_status.style().unpolish(self.gemini_api_key_status)
        self.gemini_api_key_status.style().polish(self.gemini_api_key_status)

        valid, message = self.settings_service.validate_gemini_api_key(api_key)

        self.save_gemini_api_key_button.setEnabled(True)

        if valid:
            self.gemini_api_key = api_key
            self.settings["gemini_api_key"] = api_key
            self.settings_service.save(self.settings)
            self.gemini_api_key_status.setText(message)
            self.gemini_api_key_status.setProperty("state", "valid")
        else:
            self.gemini_api_key = ""
            self.settings.pop("gemini_api_key", None)
            self.settings_service.save(self.settings)
            self.gemini_api_key_status.setText(message)
            self.gemini_api_key_status.setProperty("state", "invalid")

        self.gemini_api_key_status.style().unpolish(self.gemini_api_key_status)
        self.gemini_api_key_status.style().polish(self.gemini_api_key_status)

    def clear_gemini_api_key(self) -> None:
        self.gemini_api_key = ""
        self.settings.pop("gemini_api_key", None)
        self.settings_service.save(self.settings)
        self.gemini_api_key_input.clear()
        self.gemini_api_key_status.setText(
            "Gemini API key eliminada de la configuración local."
        )
        self.gemini_api_key_status.setProperty("state", "missing")
        self.gemini_api_key_status.style().unpolish(self.gemini_api_key_status)
        self.gemini_api_key_status.style().polish(self.gemini_api_key_status)

    def set_analysis_status(
        self,
        text: str,
        state: str,
    ) -> None:
        if not hasattr(self, "analysis_status"):
            return

        self.analysis_status.setText(text)
        self.analysis_status.setProperty(
            "state",
            state,
        )

        style = self.analysis_status.style()
        style.unpolish(self.analysis_status)
        style.polish(self.analysis_status)

    def setup_live_data_worker(self) -> None:
        self.worker_thread = QThread(self)
        self.live_data_worker = LiveDataWorker(
            self.item_catalog,
            game_version=self.version,
        )

        self.live_data_worker.moveToThread(self.worker_thread)

        self.snapshot_requested.connect(self.live_data_worker.read_snapshot)

        self.live_data_worker.snapshot_ready.connect(self.receive_snapshot)

        self.live_data_worker.live_analysis_ready.connect(self.receive_live_analysis)

        self.live_data_worker.read_failed.connect(self.show_read_error)

        self.live_data_worker.game_ended.connect(self.handle_game_ended)
        self.worker_thread.start()

    def setup_postgame_sync_worker(
        self,
    ) -> None:
        """
        Crea un hilo separado para sincronizar Match-V5 tras una partida.

        Nunca se hacen peticiones de Riot API desde el hilo de interfaz.
        """
        self.postgame_sync_thread = QThread(self)

        self.postgame_sync_worker = PostgameSyncWorker()

        self.postgame_sync_worker.moveToThread(self.postgame_sync_thread)

        self.postgame_sync_requested.connect(self.postgame_sync_worker.sync_session)

        self.postgame_sync_worker.sync_ready.connect(self.receive_postgame_sync)

        self.postgame_sync_worker.sync_failed.connect(self.receive_postgame_sync_error)

        self.postgame_sync_worker.sync_progress.connect(self.on_postgame_sync_progress)

        self.postgame_sync_thread.start()

    @staticmethod
    def format_match_duration(
        seconds: int | float | None,
    ) -> str:
        total_seconds = max(0, int(seconds or 0))
        minutes, remaining_seconds = divmod(
            total_seconds,
            60,
        )

        return f"{minutes}:{remaining_seconds:02d}"

    def set_live_badge(
        self,
        state: str,
        text: str,
    ) -> None:
        """Actualiza el punto y el texto de estado de la cabecera LIVE."""
        if not hasattr(self, "live_badge"):
            return

        self.live_badge.setText(text)
        self.live_dot.setProperty("state", state)

        self.live_dot.style().unpolish(self.live_dot)
        self.live_dot.style().polish(self.live_dot)

        self.live_dot.update()

    def request_snapshot(self) -> None:
        if self.is_refreshing:
            return

        self.is_refreshing = True
        self.snapshot_requested.emit()

    def receive_snapshot(
        self,
        snapshot: dict | None,
    ) -> None:
        try:
            self.last_snapshot = snapshot

            if snapshot is None:
                self.show_no_game()
            else:
                self.show_game(snapshot)
        finally:
            self.is_refreshing = False

    def show_read_error(self, message: str) -> None:
        self.connection_label.setText("League no disponible")
        self.live_button.setEnabled(False)
        self.is_refreshing = False

        self.count_lost_snapshot()

    @Slot()
    def handle_game_ended(self) -> None:
        """La API local dejó de responder: la partida ha terminado.

        El worker emite ``game_ended`` solo si antes había partida, así que
        aquí se cierra la sesión LIVE (y con ella la grabación) y se deja la
        interfaz en el estado de espera.
        """
        if not self.was_in_game:
            return

        self.finish_live_session("game_end")
        self.show_no_game()

    def finish_live_session(self, reason: str = "game_end") -> None:
        """Cierra la sesión LIVE: para la grabación y programa la sincronización.

        Se llama desde todos los caminos en los que la partida deja de estar
        activa (la API deja de responder, se cierra la ventana...). Es
        idempotente: si la sesión ya estaba cerrada y no hay grabación en
        curso, no hace nada.
        """
        if self.live_session_finished and not self.recording_service.is_recording:
            return

        completed_session = None

        if self.live_match_tracker.is_tracking:
            completed_session = self.live_match_tracker.finish()

        self.live_session_finished = True
        self.live_snapshots_lost = 0

        self.stop_match_recording(
            reason,
            completed_session if isinstance(completed_session, dict) else None,
        )

        if isinstance(completed_session, dict):
            self.schedule_postgame_sync(completed_session)

        if hasattr(self, "saved_games_layout"):
            self.refresh_saved_games()

    def count_lost_snapshot(self) -> None:
        """Cuenta los sondeos seguidos sin respuesta estando en partida.

        Si se encadenan demasiados sin que llegue la señal de fin (por ejemplo
        porque el hilo de lectura se ha quedado atascado), la grabación se
        cierra igualmente para no dejar el vídeo abierto.
        """
        if not self.was_in_game:
            self.live_snapshots_lost = 0

            return

        self.live_snapshots_lost = min(
            self.live_snapshots_lost + 1,
            self.LIVE_LOST_POLLS_BEFORE_STOP + 1,
        )

        if not self.recording_service.is_recording:
            return

        if self.live_snapshots_lost < self.LIVE_LOST_POLLS_BEFORE_STOP:
            return

        self.finish_live_session("game_end_lost")
        self.show_no_game()

    def show_no_game(self) -> None:
        self.connection_label.setText("League abierto · sin partida")

        self.live_button.setEnabled(False)
        if hasattr(self, "open_live_analysis_button"):
            self.open_live_analysis_button.setEnabled(False)

        if self.live_analysis_dialog is not None:
            self.live_analysis_dialog.close()
            self.live_analysis_dialog = None

        if self.replay_window is not None:
            try:
                self.replay_window.close()
            except RuntimeError:
                pass

            self.replay_window = None

        self.current_live_session = None
        self.live_status.setText("No hay una partida activa.")
        self.live_time_label.setText("—")
        self.set_live_badge("idle", "EN ESPERA")

        self.overlay.clear()
        self.finish_live_session("game_end")

        if self.was_in_game:
            self.clear_cards()

            self.live_empty_label = QLabel(
                "La pestaña se habilitará automáticamente al comenzar una partida."
            )
            self.live_empty_label.setObjectName("liveSummary")
            self.live_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.live_empty_label.setWordWrap(True)

            self.cards_layout.addWidget(
                self.live_empty_label,
                1,
            )

            self.was_in_game = False
            self.cards_built = False
            self.panel_refresh_counter = 0

    def show_game(self, snapshot: dict) -> None:
        game_time = float(snapshot.get("game_time", 0))
        minutes = int(game_time // 60)
        seconds = int(game_time % 60)

        local_player = snapshot.get(
            "local_player",
            {},
        )
        champion = local_player.get(
            "championName",
            "Campeón",
        )
        game_mode = snapshot.get(
            "game_mode",
            "UNKNOWN",
        )
        total_players = len(snapshot.get("all_players", []))

        short_modes = {
            "CLASSIC": "Grieta del Invocador",
            "PRACTICETOOL": "Herramienta de práctica",
            "ARAM": "ARAM",
            "TFT": "TFT",
            "CHERRY": "Arena",
            "ODYSSEY": "Odisea",
        }

        if game_mode in short_modes:
            mode_text = short_modes[game_mode]
        else:
            mode_text = str(game_mode).replace("_", " ").title()

        self.connection_label.setText("Partida en curso")

        self.live_button.setEnabled(True)
        self.open_live_analysis_button.setEnabled(self.current_live_session is not None)

        # La partida ya está en curso (la pantalla de carga terminó): si el draft
        # acaba de terminar, el panel se coloca en "Partida en vivo".
        if self.pending_live_navigation:
            self.pending_live_navigation = False
            self.navigate_to_live_page()

        self.live_status.setText(
            f"{mode_text} · {champion} · {total_players} jugadores"
        )
        self.live_time_label.setText(f"{minutes:02d}:{seconds:02d}")
        self.set_live_badge("live", "EN VIVO")

        self.overlay.update_snapshot(snapshot)

        if not self.live_match_tracker.is_tracking:
            self.live_match_tracker.start(snapshot)
            self.live_session_finished = False
            self.start_match_recording(snapshot)
        else:
            self.live_match_tracker.update(snapshot)

        self.was_in_game = True
        self.live_snapshots_lost = 0

        if not self.cards_built:
            self.cards_built = True
            self.rebuild_cards(snapshot)
            return

        self.panel_refresh_counter += 1

        if self.panel_refresh_counter < self.panel_refresh_every_seconds:
            return

        self.panel_refresh_counter = 0
        self.rebuild_cards(snapshot)

    @Slot(object)
    def receive_live_analysis(
        self,
        session: dict,
    ) -> None:
        """Recibe la sesión construida por LiveDataWorker cada segundo."""
        if not isinstance(session, dict):
            return

        self.current_live_session = session

        if hasattr(self, "open_live_analysis_button"):
            self.open_live_analysis_button.setEnabled(True)

        dialog = self.live_analysis_dialog

        if dialog is not None:
            try:
                dialog.update_session(session)
            except RuntimeError:
                self.live_analysis_dialog = None
                dialog = None

        replay = getattr(self, "replay_window", None)

        if replay is not None:
            try:
                current = getattr(replay, "session", None)
                live_id = str(session.get("session_id") or "")
                replay_id = (
                    str(current.get("session_id") or "")
                    if isinstance(current, dict)
                    else ""
                )
                # Solo se propaga si es la misma partida que el repaso
                # tiene abierta (o si el repaso aún no tiene sesión).
                if not replay_id or not live_id or replay_id == live_id:
                    replay.update_session(session)
            except RuntimeError:
                self.replay_window = None

    def open_live_analysis(self) -> None:
        """Abre un único diálogo que se refresca mientras juegas."""
        session = self.current_live_session

        if not isinstance(session, dict):
            return

        dialog = self.live_analysis_dialog

        if dialog is not None:
            try:
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
                dialog.update_session(session)
                return
            except RuntimeError:
                self.live_analysis_dialog = None

        dialog = LiveMatchAnalysisDialog(
            session,
            self.data_dragon_assets,
            self.item_catalog,
            self,
            tracker=self.live_match_tracker,
        )

        self.live_analysis_dialog = dialog

        dialog.finished.connect(self.clear_live_analysis_dialog)

        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

        try:
            dialog.update_session(session)
        except RuntimeError:
            self.live_analysis_dialog = None

    def clear_live_analysis_dialog(self, *args) -> None:
        """Elimina la referencia al cerrar el diálogo."""
        self.live_analysis_dialog = None

    def schedule_postgame_sync(
        self,
        session: dict,
    ) -> None:
        """Persiste el fin de partida y programa Home LCU más Match-V5 opcional.

        Args:
            session: sesión finalizada y guardada por el tracker LIVE.

        Returns:
            ``None``; inicia los flujos asíncronos de conciliación.
        """
        session_id = str(
            session.get(
                "session_id",
                "",
            )
        )

        if not session_id:
            return

        self.pending_postgame_session_id = session_id
        sesiones = self.live_match_tracker.load_saved_sessions()
        for sesion in sesiones:
            if str(sesion.get("session_id") or "") == session_id:
                marcar_sincronizacion_lcu_pendiente(sesion)
                break
        self.live_match_tracker._save_sessions(sesiones)
        self._programar_intento_sync_lcu(session_id, 2)

        game_name = self.riot_game_name
        tag_line = self.riot_tag_line
        if not self.riot_api_key or not game_name or not tag_line:
            return

        self.update_saved_session_sync_status(
            session_id,
            "pending",
            "Esperando a que Riot procese la partida…",
        )

        if hasattr(
            self,
            "saved_games_layout",
        ):
            self.refresh_saved_games()

        QTimer.singleShot(
            20_000,
            lambda value=session_id: self.start_postgame_sync(value),
        )

    def start_postgame_sync(
        self,
        session_id: str,
    ) -> None:
        """
        Inicia la consulta Match-V5 20 segundos después de terminar.

        Se vuelve a leer la sesión desde disco para usar el estado pending
        y evitar trabajar con una copia antigua.
        """
        if self.postgame_sync_in_progress:
            return

        if session_id != self.pending_postgame_session_id:
            return

        if not self.riot_api_key:
            return

        sessions = self.live_match_tracker.load_saved_sessions()

        session = next(
            (value for value in sessions if value.get("session_id") == session_id),
            None,
        )

        if not isinstance(session, dict):
            return

        game_name = self.riot_game_name
        tag_line = self.riot_tag_line

        if not game_name or not tag_line:
            return

        self.postgame_sync_in_progress = True

        self.postgame_sync_requested.emit(
            session,
            self.riot_api_key,
            game_name,
            tag_line,
            self.riot_account_region,
            self.riot_platform_region,
        )

    def _intentar_sync_lcu_home(self, session_id: str) -> None:
        """Inicia un intento de historial LCU en el worker existente.

        Args:
            session_id: identificador de la sesión postpartida pendiente.

        Returns:
            ``None``; el worker comunica el resultado mediante su callback.
        """
        self._postgame_lcu_scheduled.discard(session_id)
        sesiones = self.live_match_tracker.load_saved_sessions()
        sesion = next(
            (
                valor
                for valor in sesiones
                if str(valor.get("session_id") or "") == session_id
            ),
            None,
        )
        if not isinstance(sesion, dict):
            return
        estado = sesion.get("lcu_postgame_sync")
        if not isinstance(estado, dict) or estado.get("state") != "pending":
            return
        if self._home_sync_in_progress:
            self._programar_intento_sync_lcu(session_id, 5)
            return
        intentos = contador_intentos_lcu(estado)
        estado["attempts"] = intentos + 1
        self.live_match_tracker._save_sessions(sesiones)
        self.synchronize_home_history()

    def _programar_intento_sync_lcu(self, session_id: str, retraso: int) -> None:
        """Programa un único intento LCU por sesión y demora.

        Args:
            session_id: identificador de la sesión pendiente.
            retraso: segundos hasta la siguiente lectura LCU.

        Returns:
            ``None``; delega la espera al temporizador de Qt.
        """
        if not session_id or session_id in self._postgame_lcu_scheduled:
            return
        self._postgame_lcu_scheduled.add(session_id)
        QTimer.singleShot(
            max(0, retraso) * 1_000,
            lambda value=session_id: self._intentar_sync_lcu_home(value),
        )

    def _revisar_sincronizaciones_lcu_pendientes(
        self, historial: dict[str, Any] | None
    ) -> None:
        """Reconcilia tareas guardadas después de cada carga de Home.

        Args:
            historial: historial fusionado o ``None`` cuando falló la lectura.

        Returns:
            ``None``; persiste tareas completadas y agenda reintentos pendientes.
        """
        sesiones = self.live_match_tracker.load_saved_sessions()
        cambiadas = False
        pendientes: list[tuple[str, int]] = []
        for sesion in sesiones:
            estado = sesion.get("lcu_postgame_sync")
            if not isinstance(estado, dict) or estado.get("state") != "pending":
                continue
            session_id = str(sesion.get("session_id") or "")
            if historial is not None and historial_contiene_enlace(
                historial, session_id
            ):
                marcar_sincronizacion_lcu_completa(sesion)
                cambiadas = True
                continue
            intentos = contador_intentos_lcu(estado)
            pendientes.append((session_id, intentos))
        if cambiadas:
            self.live_match_tracker._save_sessions(sesiones)
        for session_id, intentos in pendientes:
            retraso = (
                RETRASOS_REINTENTO_LCU[intentos]
                if intentos < len(RETRASOS_REINTENTO_LCU)
                else siguiente_retraso_lcu(intentos)
            )
            self._programar_intento_sync_lcu(session_id, retraso)

    @Slot(int, int, str)
    def on_postgame_sync_progress(
        self,
        current: int,
        total: int,
        message: str,
    ) -> None:
        """
        Actualiza la etiqueta de estado con el progreso de la sincronización.

        Se llama desde el worker para cada paso: búsqueda de candidatos,
        descarga de timeline, etc.
        """
        if hasattr(self, "saved_games_status"):
            if total > 0:
                label_text = f"⏳ Sincronizando: {message} ({current}/{total})"
            else:
                label_text = f"⏳ {message}"
            self.saved_games_status.setText(label_text)

    @Slot(dict)
    def receive_postgame_sync(
        self,
        updated_session: dict,
    ) -> None:
        """
        Sustituye en disco la sesión por su versión Riot sincronizada.
        """
        self.postgame_sync_in_progress = False

        session_id = str(
            updated_session.get(
                "session_id",
                "",
            )
        )

        if not session_id:
            return

        sessions = self.live_match_tracker.load_saved_sessions()

        replaced = False

        for index, session in enumerate(sessions):
            if session.get("session_id") != session_id:
                continue

            sessions[index] = conservar_enriquecimiento_final(session, updated_session)
            updated_session = sessions[index]
            replaced = True
            break

        if replaced:
            self.live_match_tracker._save_sessions(sessions)
            if self.home_profile and self.home_history.get("matches"):
                perfil = deepcopy(self.home_profile)
                historial = deepcopy(self.home_history)
                run_async(
                    lambda: self.actualizar_puntuaciones_home_en_segundo_plano(
                        perfil, historial
                    ),
                    on_finished=self._home_saved_scores_finished,
                    token=f"home_saved_score_{session_id}",
                )

        if hasattr(
            self,
            "saved_games_layout",
        ):
            self.refresh_saved_games()

        self.pending_postgame_session_id = ""

        replay = getattr(self, "replay_window", None)

        if replay is not None and isinstance(updated_session, dict):
            try:
                current = getattr(replay, "session", None)
                replay_id = (
                    str(current.get("session_id") or "")
                    if isinstance(current, dict)
                    else ""
                )
                if not replay_id or replay_id == session_id:
                    replay.update_session(updated_session)
            except RuntimeError:
                self.replay_window = None

    @Slot(str)
    def receive_postgame_sync_error(
        self,
        message: str,
    ) -> None:
        """
        Conserva la telemetría local y muestra el estado de error.

        No borra ni altera los snapshots LIVE si Riot no responde.
        """
        self.postgame_sync_in_progress = False

        session_id = self.pending_postgame_session_id

        if session_id:
            self.update_saved_session_sync_status(
                session_id,
                "failed",
                message,
            )

        if hasattr(
            self,
            "saved_games_layout",
        ):
            self.refresh_saved_games()

        self.pending_postgame_session_id = ""

    def get_player_role(self, player: dict) -> str:
        position = str(player.get("position", "")).upper()

        aliases = {
            "MID": "MIDDLE",
            "JUNG": "JUNGLE",
            "SUP": "UTILITY",
            "SUPPORT": "UTILITY",
            "ADC": "BOTTOM",
            "APC": "BOTTOM",
        }

        position = aliases.get(position, position)

        if position in {
            "TOP",
            "JUNGLE",
            "MIDDLE",
            "BOTTOM",
            "UTILITY",
        }:
            return position

        spells = player.get(
            "summonerSpells",
            {},
        )

        spell_one = str(
            spells.get(
                "summonerSpellOne",
                {},
            ).get("displayName", "")
        ).lower()

        spell_two = str(
            spells.get(
                "summonerSpellTwo",
                {},
            ).get("displayName", "")
        ).lower()

        if "smite" in spell_one or "smite" in spell_two:
            return "JUNGLE"

        return "UNKNOWN"

    def sort_players_by_role(
        self,
        players: list[dict],
    ) -> list[dict]:
        """Ordena la fila como TOP → JUNGLA → MID → BOT → SUPPORT.

        `sorted` es estable, así que los jugadores sin rol reconocible
        conservan el orden original del snapshot (modos como ARAM o bots,
        donde la API no informa posición) en lugar de reordenarse
        alfabéticamente y quedar en posiciones sin sentido.
        """
        role_order = {
            "TOP": 0,
            "JUNGLE": 1,
            "MIDDLE": 2,
            "BOTTOM": 3,
            "UTILITY": 4,
            "UNKNOWN": 99,
        }

        return sorted(
            players,
            key=lambda player: role_order.get(
                self.get_player_role(player),
                99,
            ),
        )

    def rebuild_cards(self, snapshot: dict) -> None:
        """Actualiza tarjetas y paneles desde la instantánea LIVE.

        Args:
            snapshot: Equipos, participantes y datos actuales de partida.
        Returns:
            None.
        """
        all_players = snapshot.get("all_players", [])

        if not isinstance(all_players, list):
            all_players = []

        local_team = str(snapshot.get("local_team", "")).upper()

        if local_team not in ("ORDER", "CHAOS"):
            local_team = "ORDER"

        teams = [
            ("ORDER", "Equipo azul"),
            ("CHAOS", "Equipo rojo"),
        ]

        if local_team == "CHAOS":
            teams.reverse()

        if not all_players:
            self.clear_cards()
            waiting = QLabel("Esperando los datos de los diez jugadores...")
            waiting.setObjectName("liveSummary")
            waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)
            waiting.setWordWrap(True)
            self.cards_layout.addWidget(waiting, 1)
            return

        grupos = [
            (
                team,
                side_name,
                self.sort_players_by_role(
                    [player for player in all_players if player.get("team") == team]
                )[:5],
            )
            for team, side_name in teams
        ]
        grupos = [grupo for grupo in grupos if grupo[2]]
        orden = tuple(grupo[0] for grupo in grupos)
        firmas = {
            team: tuple(
                self._identidad_jugador(player)
                + (
                    "local"
                    if self.player_is_local(player, snapshot.get("local_player", {}))
                    else "",
                )
                for player in players
            )
            for team, _, players in grupos
        }
        if orden == self.live_team_order and firmas == self.live_team_signatures:
            for team, _, players in grupos:
                for tarjeta, player in zip(self.live_team_cards[team], players):
                    es_local = self.player_is_local(
                        player, snapshot.get("local_player", {})
                    )
                    tarjeta.actualizar_datos(
                        player,
                        float(snapshot.get("game_time", 0)),
                        snapshot.get("local_live_stats", {}) if es_local else None,
                    )
                self.live_team_summaries[team].setText(
                    self.format_team_summary(players)
                )
            self.cards_widget.updateGeometry()
            return

        self.clear_cards()
        self.live_team_order = orden
        self.live_team_signatures = firmas
        for team, side_name, players in grupos:
            self.add_team_panel(
                team,
                side_name,
                players,
                snapshot,
                is_local_team=team == local_team,
            )

    @staticmethod
    def _identidad_jugador(player: dict) -> tuple[str, ...]:
        """Devuelve una clave estable para detectar cambios de roster."""
        return tuple(
            str(player.get(clave) or "")
            for clave in ("riotId", "summonerName", "championName")
        )

    def add_team_panel(
        self,
        team: str,
        side_name: str,
        players: list[dict],
        snapshot: dict,
        is_local_team: bool,
    ) -> None:
        """Añade el equipo como un bloque que mide su cabecera y sus tarjetas.

        Args:
            team: Identificador del equipo en los datos LIVE.
            side_name: Nombre legible del lado del mapa.
            players: Participantes que se mostrarán en la fila.
            snapshot: Estado actual de la partida y del jugador local.
            is_local_team: Indica si el panel representa al equipo del usuario.
        Returns:
            None.
        """
        panel = QFrame()
        panel.setObjectName("liveTeamPanel")
        panel.setProperty(
            "side",
            "ally" if is_local_team else "enemy",
        )
        panel.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)

        layout.addLayout(
            self.create_team_header(
                players,
                side_name,
                is_local_team,
                team,
            )
        )

        tarjetas: list[ChampionCard] = []
        local_player = snapshot.get("local_player", {})

        for player in players[:5]:
            is_local = self.player_is_local(
                player,
                local_player,
            )

            card = ChampionCard(
                player=player,
                is_local_player=is_local,
                item_catalog=self.item_catalog,
                version=self.version,
                game_time=snapshot["game_time"],
                local_live_stats=(
                    snapshot.get(
                        "local_live_stats",
                        {},
                    )
                    if is_local
                    else None
                ),
            )

            card.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )

            tarjetas.append(card)

        grid_container = RejillaTarjetasEquipo(tarjetas)
        grid_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        layout.addWidget(grid_container, 1)
        self.cards_layout.addWidget(panel, 1)
        self.live_team_cards[team] = tarjetas
        self.cards_widget.updateGeometry()

    def create_team_header(
        self,
        players: list[dict],
        side_name: str,
        is_local_team: bool,
        team: str,
    ) -> QHBoxLayout:
        """Crea la cabecera del equipo y conserva su etiqueta de resumen."""
        header = QHBoxLayout()
        header.setSpacing(10)
        header.setContentsMargins(0, 0, 4, 0)

        tag = QLabel("TU EQUIPO" if is_local_team else "EQUIPO ENEMIGO")
        tag.setObjectName("liveTeamTag")
        header.addWidget(tag)

        side = QLabel(side_name)
        side.setObjectName("liveTeamSide")
        header.addWidget(side)
        header.addStretch(1)

        summary = QLabel(self.format_team_summary(players))
        summary.setObjectName("liveTeamSummary")
        summary.setWordWrap(False)
        header.addWidget(summary)
        self.live_team_summaries[team] = summary

        return header

    def format_team_summary(self, players: list[dict]) -> str:
        """Resume asesinatos y oro total observado en objetos del equipo.

        Args:
            players: Participantes LIVE pertenecientes al equipo.
        Returns:
            Texto compacto con asesinatos y oro en inventarios.
        """
        kills = 0
        kills_disponibles = True
        gold = 0

        for player in players:
            scores = player.get("scores", {})

            if isinstance(scores, dict):
                try:
                    valor_asesinatos = scores.get("kills")
                    if valor_asesinatos is None:
                        kills_disponibles = False
                    else:
                        kills += int(valor_asesinatos)
                except (TypeError, ValueError):
                    kills_disponibles = False
            else:
                kills_disponibles = False

            gold += get_inventory_value(
                player,
                self.item_catalog,
            )

        gold_text = f"{gold / 1000:.1f}k" if gold >= 1000 else str(gold)
        kills_text = str(kills) if kills_disponibles else "—"
        return f"{kills_text} ASESINATOS · {gold_text} ORO EN OBJETOS"

    @staticmethod
    def player_is_local(
        player: dict,
        local_player: dict,
    ) -> bool:
        """True cuando la tarjeta corresponde al jugador local."""
        if not isinstance(local_player, dict) or not local_player:
            return False

        if player is local_player:
            return True

        for key in ("riotId", "summonerName"):
            local_name = local_player.get(key)

            if local_name and player.get(key) == local_name:
                return True

        return False

    def clear_cards(
        self,
        keep_empty_label: bool = False,
    ) -> None:
        """Retira tarjetas y libera sus referencias de actualización."""
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()

            if widget is None:
                continue

            if keep_empty_label and widget is self.live_empty_label:
                widget.setParent(None)
                continue

            # Las tarjetas antiguas deben desaparecer de inmediato: si solo se
            # planifican con deleteLater(), en offscreen/ciertos estilos pueden
            # seguir pintándose un ciclo y dejar texto fantasma tras el fondo
            # semitransparente de la tarjeta nueva.
            widget.hide()
            try:
                widget.setParent(None)
            except RuntimeError:
                pass
            widget.deleteLater()
        self.live_team_cards = {}
        self.live_team_summaries = {}
        self.live_team_signatures = {}
        self.live_team_order = ()

    def toggle_overlay_visibility(self) -> None:
        enabled = self.overlay.toggle_all()
        self.show_overlay_button.setText(
            "Ocultar overlay" if enabled else "Mostrar overlay"
        )
        self.sync_overlay_settings_ui()

    def toggle_overlay_click_through(self) -> None:
        enabled = not self.overlay.click_through
        self.overlay.set_click_through(enabled)
        self.sync_overlay_settings_ui()

    def change_overlay_opacity(self, percent: int) -> None:
        self.overlay.set_overlay_opacity(percent)
        self.opacity_value.setText(f"{percent}%")

    def change_overlay_alert_lead(self, seconds: int) -> None:
        self.overlay.set_alert_lead_seconds(seconds)
        self.alert_lead_value.setText(f"{seconds} s")

    def toggle_overlay_panel(self, key: str) -> None:
        self.overlay.set_panel_enabled(
            key,
            not self.overlay.is_panel_enabled(key),
        )
        self.sync_overlay_settings_ui()

    def toggle_overlay_tab_only(self, key: str, enabled: bool) -> None:
        """Ese panel solo se muestra mientras TAB está pulsado."""
        self.overlay.set_tab_only(key, enabled)
        self.sync_overlay_settings_ui()

    def sync_overlay_settings_ui(self) -> None:
        """Refresca los controles de overlay de Ajustes con el estado real."""
        if not hasattr(self, "show_overlay_button"):
            return

        enabled = self.overlay.enabled_panels()
        self.show_overlay_button.setText(
            "Ocultar overlay" if self.overlay.any_enabled() else "Mostrar overlay"
        )
        self.lock_overlay_button.setText(
            "Bloquear clics: SÍ" if self.overlay.click_through else "Bloquear clics: NO"
        )

        for key, button in self.overlay_panel_buttons.items():
            button.blockSignals(True)
            button.setChecked(enabled.get(key, False))
            button.blockSignals(False)

        if hasattr(self, "overlay_tab_only_checkboxes"):
            for key, checkbox in self.overlay_tab_only_checkboxes.items():
                checkbox.blockSignals(True)
                checkbox.setChecked(self.overlay.is_tab_only(key))
                checkbox.blockSignals(False)

        panel_names = {
            "gold": "Oro",
            "alerts": "Alertas",
            "threat": "Rivales",
        }
        active = [name for key, name in panel_names.items() if enabled.get(key, False)]
        tab_hidden = sorted(
            name
            for key, name in panel_names.items()
            if enabled.get(key, False) and self.overlay.is_tab_only(key)
        )
        tab_notice = (
            f" Sin TAB activo están ocultos: {', '.join(tab_hidden)}."
            if tab_hidden
            else ""
        )

        if self.overlay.in_game:
            text = (
                "Paneles en pantalla: " + ", ".join(active) + "."
                if active
                else "Todos los paneles están apagados."
            )
        else:
            text = (
                "Paneles activos: "
                + ", ".join(active)
                + ". Aparecerán al empezar una partida."
                if active
                else "Todos los paneles están apagados."
            )

        self.overlay_status.setText(text + tab_notice)
        self.sync_overlay_sound_controls()

    def toggle_overlay_sound_enabled(self, enabled: bool) -> None:
        """Activa o desactiva todos los pitidos del overlay."""
        self.overlay.set_sound_enabled(enabled)
        self.sync_overlay_sound_controls()

    def toggle_overlay_sound_kind(self, kind: str, enabled: bool) -> None:
        """Activa o desactiva un tipo concreto de pitido."""
        self.overlay.set_sound_kind_enabled(kind, enabled)
        self.sync_overlay_sound_controls()

    def change_overlay_sound_volume(self, percent: int) -> None:
        """Cambia el volumen de los pitidos del overlay."""
        self.overlay.set_sound_volume(percent / 100.0)
        self.sound_volume_value.setText(f"{percent}%")

    def sync_overlay_sound_controls(self) -> None:
        """Refleja el estado real de los pitidos en los controles de Ajustes."""
        if not hasattr(self, "sound_enabled_checkbox"):
            return

        service = self.overlay.sound_service
        enabled = self.overlay.is_sound_enabled()

        widgets = (
            self.sound_enabled_checkbox,
            self.sound_objective_checkbox,
            self.sound_dragon_checkbox,
            self.sound_enemy_buy_checkbox,
            self.sound_volume_slider,
        )

        for widget in widgets:
            widget.blockSignals(True)

        self.sound_enabled_checkbox.setChecked(enabled)
        self.sound_objective_checkbox.setChecked(service.kind_enabled("objective"))
        self.sound_dragon_checkbox.setChecked(service.kind_enabled("dragon"))
        self.sound_enemy_buy_checkbox.setChecked(service.kind_enabled("enemy_buy"))
        self.sound_volume_slider.setValue(int(round(service.volume * 100)))
        self.sound_volume_value.setText(f"{int(round(service.volume * 100))}%")

        # Con el interruptor general apagado el resto de controles se atenúan.
        self.sound_enabled_checkbox.setEnabled(True)

        for widget in widgets[1:]:
            widget.setEnabled(enabled)

        for widget in widgets:
            widget.blockSignals(False)

    def setup_champ_select_worker(self) -> None:
        self.champ_select_worker = ChampSelectWorker(parent=self)
        self.champ_select_worker.champ_select_started.connect(
            self._on_champ_select_started
        )
        self.champ_select_worker.champ_select_updated.connect(
            self._on_champ_select_updated
        )
        self.champ_select_worker.champ_select_ended.connect(self._on_champ_select_ended)
        self.champ_select_worker.start()

    def open_draft_tool_dialog(self) -> None:
        """Abre el draft como página única del shell y mantiene las señales LCU."""
        if self.draft_tool_dialog is None:
            self.draft_tool_dialog = DraftToolDialog(self)
            self.draft_tool_dialog.setWindowFlags(Qt.WindowType.Widget)
            self.draft_tool_dialog.setMinimumSize(0, 0)
            anterior = self.pages.widget(6)
            if anterior is not None:
                self.pages.removeWidget(anterior)
                anterior.deleteLater()
            self.pages.insertWidget(6, self.draft_tool_dialog)
        self.pages.setCurrentIndex(6)
        self.draft_tool_dialog.show()

    @Slot(dict)
    def _on_champ_select_started(self, session: dict) -> None:
        self.pending_live_navigation = False
        self.open_draft_tool_dialog()
        if self.draft_tool_dialog:
            self.draft_tool_dialog.update_from_lcu_session(session)

    @Slot(dict)
    def _on_champ_select_updated(self, session: dict) -> None:
        if self.draft_tool_dialog is not None:
            self.draft_tool_dialog.update_from_lcu_session(session)

    def _on_champ_select_ended(self) -> None:
        if self.draft_tool_dialog is not None:
            self.draft_tool_dialog._set_lcu_managed_controls(False)
            # El draft ha terminado: se cierra para poder ver el panel principal.
            if self.pages.currentIndex() == 6:
                self.pages.setCurrentIndex(0)
        # El draft ha terminado; cuando la pantalla de carga acabe y la partida
        # arranque (primer snapshot de la API local) el panel irá solo a
        # "Partida en vivo" (ver show_game).
        self.pending_live_navigation = True

    def navigate_to_live_page(self) -> None:
        """Coloca el panel principal en la pestaña "Partida en vivo"."""
        self.pages.setCurrentIndex(self.LIVE_PAGE_INDEX)
        if hasattr(self, "live_button"):
            self.live_button.setChecked(True)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Detiene workers y cierra de forma segura la grabación activa.

        Parámetros:
            event: Evento Qt de cierre de ventana.

        Retorno:
            None.
        """
        self.poll_timer.stop()
        self.tab_hotkey.stop()
        self.overlay.close()

        if (
            self.recording_service.is_recording
            or self.recording_service.is_starting_or_recording
        ):
            self._pending_recording_snapshot = None

            if self.recording_service.pending_process is not None:
                self.recording_service.abort()
                self.recording_service.wait_for_stop(3000)
            else:
                live_session = self.live_match_tracker.get_live_session()
                self.recording_service.stop(
                    reason="app_close",
                    session=live_session,
                )
                self.recording_service.wait_for_stop(4000)

                if self.recording_service.is_recording:
                    self.recording_service.abort()
                    self.recording_service.wait_for_stop(3000)

        if (
            hasattr(self, "champ_select_worker")
            and self.champ_select_worker.isRunning()
        ):
            self.champ_select_worker.stop()
            self.champ_select_worker.quit()
            self.champ_select_worker.wait(2000)

        if self.worker_thread.isRunning():
            self.worker_thread.quit()

            if not self.worker_thread.wait(5000):
                self.worker_thread.terminate()
                self.worker_thread.wait(2000)

        if self.postgame_sync_thread.isRunning():
            self.postgame_sync_thread.quit()

        if not self.postgame_sync_thread.wait(5000):
            self.postgame_sync_thread.terminate()
            self.postgame_sync_thread.wait(2000)

        event.accept()
