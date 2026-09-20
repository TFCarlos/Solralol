from __future__ import annotations
from datetime import datetime

from PySide6.QtCore import (
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)

from PySide6.QtGui import (
    QColor,
    QPainter,
    QRadialGradient,
)
from app.ui.postgame_replay_window import PostgameReplayWindow


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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.services.live_match_tracker import (
    LiveMatchTracker,
)

from app.services.game_calculator import get_inventory_value

from app.ui.live_match_analysis_dialog import (
    LiveMatchAnalysisDialog,
)
from app.ui.local_analysis_dialog import LocalAnalysisDialog

from app.ui.match_inspector_dialog import (
    MatchInspectorDialog,
)
from app.services.data_dragon_assets import (
    DataDragonAssetService,
)
from app.services.settings_service import SettingsService
from app.services.tab_hotkey_service import TabHotkeyService
from app.services.live_data_worker import LiveDataWorker
from app.services.match_history_worker import (
    MatchHistoryWorker,
)

from app.services.postgame_sync_worker import (
    PostgameSyncWorker,
)

from app.services.recording_service import (
    BITRATE_PRESETS,
    DEFAULT_BITRATE,
    LIMIT_DEFAULT_GB,
    LIMIT_MAX_GB,
    LIMIT_MIN_GB,
    QUALITY_PRESETS,
    RecordingConfig,
    RecordingLibrary,
    RecordingService,
    bitrate_label,
    find_video_for_session,
    format_size,
    list_audio_devices,
    pick_game_audio_device,
    pick_microphone_device,
    quality_label,
    recording_settings_defaults,
)
from app.ui.champion_card import ChampionCard
from app.ui.recordings_page import RecordingsPage  # noqa: E402
from app.ui.postgame_replay_window import PostgameReplayWindow  # noqa: E402
from app.ui.overlay_window import OverlayWindow
from app.ui.styles import CONTROL_WINDOW_STYLE
from app.ui.champ_select_worker import ChampSelectWorker
from app.ui.draft_tool_dialog import DraftToolDialog



class Backdrop(QWidget):
    """Fondo oscuro general de la aplicación."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(7, 11, 20))

        blue = QRadialGradient(
            self.width() * 0.10,
            -30,
            max(self.width(), self.height()) * 0.72,
        )
        blue.setColorAt(0.0, QColor(25, 104, 220, 58))
        blue.setColorAt(1.0, QColor(25, 104, 220, 0))
        painter.fillRect(self.rect(), blue)

        red = QRadialGradient(
            self.width() * 0.96,
            0,
            max(self.width(), self.height()) * 0.56,
        )
        red.setColorAt(0.0, QColor(208, 45, 62, 30))
        red.setColorAt(1.0, QColor(208, 45, 62, 0))
        painter.fillRect(self.rect(), red)

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

    history_requested = Signal(
        str,
        str,
        str,
        str,
        str,
        int,
    )

    match_detail_requested = Signal(
        str,
        str,
        str,
        str,
        str,
        str,
    )

    profile_requested = Signal(
        str,
        str,
        str,
        str,
        str,
    )
        
    def __init__(self, version: str, item_catalog: dict) -> None:
        super().__init__()

        self.version = version
        self.item_catalog = item_catalog
        self.settings_service = SettingsService()
        self.settings = self.settings_service.load()
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

        self.recording_config = RecordingConfig.from_settings(
            self.settings
        )
        self.recording_library = RecordingLibrary(
            self.recording_config.output_dir
        )
        self.recording_service = RecordingService(
            self.recording_library,
            self,
        )
        self.recording_service.refresh_ffmpeg(
            self.recording_config.ffmpeg_path
        )
        self.recording_service.failed.connect(
            self._on_recording_failed
        )
        self.recording_service.finished.connect(
            self._on_recording_finished
        )
        self.recording_service.state_changed.connect(
            self._sync_overlay_recording
        )

        self.match_history: list[dict] = []
        self.history_is_loading = False

        self.last_snapshot: dict | None = None
        self.is_refreshing = False
        self.cards_built = False
        self.was_in_game = False
        self.panel_refresh_counter = 0
        self.panel_refresh_every_seconds = 10
        self.live_match_tracker = LiveMatchTracker(
            item_catalog
        )
        self.saved_live_sessions: list[dict] = []
        self.live_session_finished = False
        #: Sondeos seguidos sin respuesta de la API local estando en partida.
        self.live_snapshots_lost = 0

        self.postgame_sync_in_progress = False
        self.pending_postgame_session_id = ""

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
        self.setMinimumSize(1400, 900)

        self.build_ui()
        self.data_dragon_assets = (
            DataDragonAssetService(self)
        )
        self.overlay.set_assets(self.data_dragon_assets)
        self.overlay.state_changed.connect(self.sync_overlay_settings_ui)
        self.setStyleSheet(CONTROL_WINDOW_STYLE)
        self.setup_live_data_worker()
        self.setup_match_history_worker()
        self.setup_postgame_sync_worker()
        self.setup_champ_select_worker()

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
        self.backdrop = Backdrop()
        self.setCentralWidget(self.backdrop)

        root = QVBoxLayout(self.backdrop)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        root.addWidget(self.create_header())
        root.addWidget(self.create_navigation())

        self.pages = QStackedWidget()
        self.pages.setObjectName("mainPages")
        self.pages.currentChanged.connect(self._handle_page_changed)
        self.pages.addWidget(
            self.create_home_page()
        )
        self.pages.addWidget(
            self.create_analysis_page()
        )
        self.pages.addWidget(
            self.create_live_page()
        )
        self.pages.addWidget(
            self.create_saved_games_page()
        )
        self.recordings_page = RecordingsPage(
            self.recording_library,
            self.recording_service,
            self,
        )
        self.recordings_page.open_folder_requested.connect(
            self.open_recordings_folder
        )
        self.recordings_page.stop_recording_requested.connect(
            self.stop_recording_manually
        )
        self.recordings_page.open_window_requested.connect(
            self.open_replay_window_for_video
        )
        self.pages.addWidget(self.recordings_page)
        self.pages.addWidget(
            self.create_settings_page()
        )

        root.addWidget(self.pages, 1)
        self.showMaximized()

    def create_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(13, 13)
        layout.addWidget(mark)

        title = QLabel("SOLRALOL")
        title.setObjectName("brandTitle")
        layout.addWidget(title)

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
        navigation = QFrame()
        navigation.setObjectName("navigation")

        layout = QHBoxLayout(navigation)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

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

        self.draft_nav_button = QPushButton("⚔️ Herramienta de Draft")
        self.draft_nav_button.setObjectName("navButton")
        self.draft_nav_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.draft_nav_button.clicked.connect(self.open_draft_tool_dialog)

        layout.addWidget(self.home_button)
        layout.addWidget(self.analysis_button)
        layout.addWidget(self.live_button)
        layout.addWidget(self.saved_games_button)
        layout.addWidget(self.recordings_button)
        layout.addWidget(self.settings_button)
        layout.addWidget(self.draft_nav_button)
        layout.addStretch(1)

        return navigation


    def create_nav_button(self, text: str, index: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.clicked.connect(
            lambda checked=False: self.pages.setCurrentIndex(index)
        )
        self.nav_group.addButton(button)
        return button

    def create_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("homePage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

    def create_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("homePage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        # 1. Card Izquierda: Perfil del Invocador
        self.summoner_card = QFrame()
        self.summoner_card.setObjectName("summonerCard")
        self.summoner_card.setMinimumWidth(260)
        self.summoner_card.setMinimumHeight(220)
        self.summoner_card.setMaximumHeight(245)
        summoner_layout = QVBoxLayout(self.summoner_card)
        summoner_layout.setContentsMargins(16, 14, 16, 14)
        summoner_layout.setSpacing(8)

        header_hbox = QHBoxLayout()
        header_hbox.setSpacing(12)

        self.profile_icon_label = QLabel("Icono")
        self.profile_icon_label.setObjectName("profileIconLabel")
        self.profile_icon_label.setFixedSize(48, 48)
        self.profile_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.profile_icon_label.setStyleSheet("border: 2px solid #d9ae4f; border-radius: 9px; background: rgba(5, 12, 24, 180); color: #d9ae4f; font-weight: bold; font-size: 11px;")
        header_hbox.addWidget(self.profile_icon_label)

        id_vbox = QVBoxLayout()
        id_vbox.setSpacing(2)
        self.summoner_riot_id_label = QLabel(f"{self.riot_game_name}#{self.riot_tag_line}" if self.riot_game_name else "Invocador")
        self.summoner_riot_id_label.setObjectName("summonerRiotId")
        self.summoner_riot_id_label.setStyleSheet("color: #f4f7ff; font-size: 15px; font-weight: 800;")
        id_vbox.addWidget(self.summoner_riot_id_label)

        self.summoner_level_label = QLabel(f"Nivel — · {self.riot_platform_region.upper()}")
        self.summoner_level_label.setObjectName("summonerLevel")
        self.summoner_level_label.setStyleSheet("color: #8fa2bd; font-size: 11px;")
        id_vbox.addWidget(self.summoner_level_label)

        header_hbox.addLayout(id_vbox, 1)
        summoner_layout.addLayout(header_hbox)

        # Rango SoloQ Badge
        self.soloq_tier_badge = QLabel("🏆 RANKED SOLOQ · UNRANKED")
        self.soloq_tier_badge.setObjectName("soloqTierBadge")
        self.soloq_tier_badge.setStyleSheet("padding: 5px 10px; border: 1px solid rgba(217, 174, 79, 150); border-radius: 6px; color: #f0cf78; background: rgba(76, 60, 30, 160); font-size: 11px; font-weight: 800;")
        summoner_layout.addWidget(self.soloq_tier_badge)

        self.soloq_winrate_label = QLabel("Winrate SoloQ: — (0V / 0D)")
        self.soloq_winrate_label.setStyleSheet("color: #c9d9ee; font-size: 11px; font-weight: 600;")
        summoner_layout.addWidget(self.soloq_winrate_label)

        # Personaje más jugado
        most_played_box = QFrame()
        most_played_box.setStyleSheet("border: 1px solid rgba(97, 148, 211, 70); border-radius: 6px; background: rgba(10, 20, 36, 170);")
        mp_layout = QHBoxLayout(most_played_box)
        mp_layout.setContentsMargins(8, 6, 8, 6)
        mp_layout.setSpacing(8)

        self.most_played_icon = QLabel("M")
        self.most_played_icon.setFixedSize(48, 48)
        self.most_played_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.most_played_icon.setStyleSheet(
            "border-radius: 6px; background: rgba(5, 12, 24, 180); color: #8fa2bd; font-size: 13px;"
        )
        mp_layout.addWidget(self.most_played_icon)

        mp_text_vbox = QVBoxLayout()
        mp_text_vbox.setSpacing(1)
        self.most_played_title = QLabel("Más Jugado: —")
        self.most_played_title.setStyleSheet("color: #e2e8f0; font-size: 11px; font-weight: 700;")
        mp_text_vbox.addWidget(self.most_played_title)

        self.most_played_stats = QLabel("0 partidas (0% WR)")
        self.most_played_stats.setStyleSheet("color: #94a3b8; font-size: 10px;")
        mp_text_vbox.addWidget(self.most_played_stats)

        mp_layout.addLayout(mp_text_vbox, 1)
        summoner_layout.addWidget(most_played_box)

        # 2. Card Central: Contenedor con Título Externo + Gráfica de evolución SoloQ
        soloq_card = QFrame()
        soloq_card.setObjectName("soloqGraphCard")
        soloq_card.setStyleSheet("QFrame#soloqGraphCard { border: 1px solid rgba(80, 118, 171, 95); border-radius: 12px; background: rgba(8, 19, 34, 220); }")
        soloq_card.setMinimumHeight(220)
        soloq_card.setMaximumHeight(245)
        soloq_card_layout = QVBoxLayout(soloq_card)
        soloq_card_layout.setContentsMargins(14, 12, 14, 12)
        soloq_card_layout.setSpacing(6)

        graph_header_label = QLabel("📈 TENDENCIA DE SOLOQ")
        graph_header_label.setStyleSheet(
            "color: #edd175; font-weight: 800; font-size: 10px; letter-spacing: 1px;"
        )
        soloq_card_layout.addWidget(graph_header_label)

        from app.ui.soloq_graph_widget import SoloQGraphWidget
        self.soloq_graph = SoloQGraphWidget()
        soloq_card_layout.addWidget(self.soloq_graph, 1)

        # 3. Card Derecha: Estado del Cliente
        hero = QFrame()
        hero.setObjectName("heroCard")
        hero.setMinimumWidth(250)
        hero.setMinimumHeight(220)
        hero.setMaximumHeight(245)
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(6)

        eyebrow = QLabel("ESTADO DEL CLIENTE")
        eyebrow.setObjectName("eyebrow")
        eyebrow.setStyleSheet("font-size: 11px;")
        hero_layout.addWidget(eyebrow)

        self.home_title = QLabel("Esperando una partida")
        self.home_title.setObjectName("heroTitle")
        self.home_title.setStyleSheet("font-size: 18px; font-weight: 800;")
        hero_layout.addWidget(self.home_title)

        self.home_text = QLabel(
            "Abre League of Legends y entra en una partida para activar el panel en vivo."
        )
        self.home_text.setObjectName("heroText")
        self.home_text.setStyleSheet("font-size: 12px;")
        self.home_text.setWordWrap(True)
        hero_layout.addWidget(self.home_text)
        hero_layout.addStretch(1)

        # Disposición horizontal superior: [JUGADOR] [TENDENCIA] [ESTADO CLIENTE]
        top_section = QHBoxLayout()
        top_section.setSpacing(14)
        top_section.addWidget(self.summoner_card, 2)
        top_section.addWidget(soloq_card, 4)
        top_section.addWidget(hero, 2)
        layout.addLayout(top_section)

        metrics = QHBoxLayout()
        metrics.setSpacing(14)

        self.player_metric = self.create_metric_card(
            "INVOCADOR",
            "Sin datos",
            "La API local aún no ha devuelto un jugador activo.",
        )
        self.mode_metric = self.create_metric_card(
            "MODO",
            "—",
            "Se muestra al detectar una partida.",
        )
        self.session_metric = self.create_metric_card(
            "ESTADO",
            "En espera",
            "El panel se actualiza automáticamente.",
        )

        metrics.addWidget(self.player_metric)
        metrics.addWidget(self.mode_metric)
        metrics.addWidget(self.session_metric)
        layout.addLayout(metrics)

        activity = QFrame()
        activity.setObjectName("sectionCard")

        activity_layout = QVBoxLayout(activity)
        activity_layout.setContentsMargins(22, 20, 22, 20)
        activity_layout.setSpacing(12)

        activity_header = QHBoxLayout()
        activity_header.setSpacing(12)

        heading = QLabel("Actividad reciente")
        heading.setObjectName("sectionTitle")
        activity_header.addWidget(heading)

        activity_header.addStretch(1)

        self.refresh_history_button = QPushButton(
            "Actualizar historial"
        )
        self.refresh_history_button.setObjectName(
            "primaryButton"
        )
        self.refresh_history_button.clicked.connect(
            self.request_match_history
        )
        activity_header.addWidget(self.refresh_history_button)

        activity_layout.addLayout(activity_header)

        riot_id_row = QHBoxLayout()
        riot_id_row.setSpacing(10)

        self.riot_game_name_input = QLineEdit()
        self.riot_game_name_input.setObjectName(
            "riotIdInput"
        )
        self.riot_game_name_input.setPlaceholderText(
            "Nombre de Riot ID"
        )
        self.riot_game_name_input.setText(
            self.riot_game_name
        )
        riot_id_row.addWidget(self.riot_game_name_input, 3)

        tag_prefix = QLabel("#")
        tag_prefix.setObjectName("riotTagPrefix")
        riot_id_row.addWidget(tag_prefix)

        self.riot_tag_line_input = QLineEdit()
        self.riot_tag_line_input.setObjectName(
            "riotIdInput"
        )
        self.riot_tag_line_input.setPlaceholderText(
            "TAG"
        )
        self.riot_tag_line_input.setMaxLength(5)
        self.riot_tag_line_input.setText(
            self.riot_tag_line
        )
        riot_id_row.addWidget(self.riot_tag_line_input, 1)

        activity_layout.addLayout(riot_id_row)

        self.history_status = QLabel(
            "Introduce tu Riot ID y pulsa “Actualizar historial”."
        )
        self.history_status.setObjectName("historyStatus")
        self.history_status.setWordWrap(True)
        self.history_status.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.history_status.setMaximumHeight(24)
        activity_layout.addWidget(self.history_status)

        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("historyScrollArea")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.history_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QWidget { background: transparent; }")
        self.history_scroll.setMinimumHeight(300)

        history_scroll_widget = QWidget()
        self.history_list_layout = QVBoxLayout(history_scroll_widget)
        self.history_list_layout.setContentsMargins(0, 0, 0, 0)
        self.history_list_layout.setSpacing(8)

        self.history_scroll.setWidget(history_scroll_widget)
        activity_layout.addWidget(self.history_scroll, 1)

        layout.addWidget(activity)

        return page

    def create_metric_card(
        self,
        label: str,
        value: str,
        detail: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(5)

        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        layout.addWidget(label_widget)

        value_widget = QLabel(value)
        value_widget.setObjectName("metricValue")
        value_widget.setWordWrap(True)
        layout.addWidget(value_widget)

        detail_widget = QLabel(detail)
        detail_widget.setObjectName("metricDetail")
        detail_widget.setWordWrap(True)
        layout.addWidget(detail_widget)

        card.metric_value = value_widget
        card.metric_detail = detail_widget
        return card

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
        return

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

        button = QPushButton(
            f"Abrir {name}"
        )
        button.setObjectName("primaryButton")
        button.clicked.connect(callback)
        layout.addWidget(button)

        return row

    def save_analysis_preferences(self) -> None:
        champion = (
            self.analysis_champion_input
            .text()
            .strip()
        )

        self.analysis_champion = champion
        self.analysis_role = (
            self.analysis_role_combo.currentData()
        )
        self.analysis_rank = (
            self.analysis_rank_combo.currentData()
        )
        self.analysis_region = (
            self.analysis_region_combo.currentData()
        )

        self.settings.update(
            {
                "analysis_champion": self.analysis_champion,
                "analysis_role": self.analysis_role,
                "analysis_rank": self.analysis_rank,
                "analysis_region": self.analysis_region,
            }
        )

        self.settings_service.save(
            self.settings
        )

        self.set_analysis_status(
            "Selección guardada localmente.",
            "success",
        )

    def analysis_values(self) -> tuple[str, str, str, str] | None:
        champion = (
            self.analysis_champion_input
            .text()
            .strip()
        )

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
            champion.casefold()
            .replace(" ", "")
            .replace("'", "")
            .replace(".", "")
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

        self.open_live_analysis_button = QPushButton(
            "Abrir análisis LIVE"
        )
        self.open_live_analysis_button.setObjectName(
            "primaryButton"
        )
        self.open_live_analysis_button.setEnabled(False)
        self.open_live_analysis_button.clicked.connect(
            self.open_live_analysis
        )

        status_layout.addWidget(
            self.open_live_analysis_button
        )

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
        self.live_time_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
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

        self.refresh_saved_games_button = QPushButton(
            "Actualizar lista"
        )
        self.refresh_saved_games_button.setObjectName(
            "secondaryButton"
        )
        self.refresh_saved_games_button.clicked.connect(
            self.refresh_saved_games
        )
        header_layout.addWidget(
            self.refresh_saved_games_button
        )

        layout.addWidget(header)

        self.saved_games_status = QLabel(
            "Cargando partidas guardadas..."
        )
        self.saved_games_status.setObjectName(
            "savedGamesStatus"
        )
        layout.addWidget(self.saved_games_status)

        scroll = QScrollArea()
        scroll.setObjectName("savedGamesScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.saved_games_content = QWidget()
        self.saved_games_content.setObjectName("savedGamesContent")
        self.saved_games_layout = QVBoxLayout(
            self.saved_games_content
        )
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
        self.saved_live_sessions = (
            self.live_match_tracker.load_saved_sessions()
        )

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
            empty.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            empty.setWordWrap(True)

            self.saved_games_layout.addWidget(empty)
            self.saved_games_layout.addStretch(1)
            return

        self.saved_games_status.setText(
            f"{len(self.saved_live_sessions)} "
            "partida(s) guardada(s)."
        )

        for session in reversed(
            self.saved_live_sessions
        ):
            self.saved_games_layout.addWidget(
                self.create_saved_game_row(session)
            )

        self.saved_games_layout.addStretch(1)

    def delete_saved_game_session(self, session_id: str) -> None:
        if not session_id:
            return
        self.live_match_tracker.delete_saved_session(session_id)
        self.refresh_saved_games()

    def create_saved_game_row(
        self,
        session: dict,
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("savedGameRow")
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Un resultado ausente no equivale a una derrota.
        local_key = session.get("local_player_key")
        players = session.get("players") or {}
        local_player = (players.get(local_key) or {}) if local_key else {}
        win = local_player.get("win")
        result_state = "win" if win is True else "loss" if win is False else "unknown"
        row.setProperty("result", result_state)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(18)

        champion = session.get(
            "champion_name",
            "Desconocido",
        )

        champ_icon = QLabel(str(champion or "?")[:1].upper())
        champ_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        champ_icon.setFixedSize(60, 60)
        champ_icon.setObjectName("savedGameChampIcon")
        champ_icon.setToolTip(str(champion))
        if champion and champion != "Desconocido" and hasattr(self, "data_dragon_assets"):
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
        title_row.setSpacing(8)

        title = QLabel(str(champion))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("savedGameTitle")
        title_row.addWidget(title)

        result = QLabel({
            "win": "VICTORIA",
            "loss": "DERROTA",
            "unknown": "Sin resultado",
        }[result_state])
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

        subtitle = QLabel(
            f"{game_mode}   ·   {started_at}   ·   {duration}"
        )
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
                resync_button = QPushButton(
                    "Re-sincronizar"
                )
                resync_button.setObjectName(
                    "secondaryButton"
                )
                resync_button.setFixedWidth(125)
                resync_button.setFixedHeight(36)
                resync_button.setEnabled(
                    not self.postgame_sync_in_progress
                )
                resync_button.clicked.connect(
                    lambda checked=False, value=session_id:
                    self.request_resync_session(
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

                button_label = "Reintentar Riot" if sync_status == "not_found" else "Buscar Riot"
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

                sync_button.setFixedWidth(125)
                sync_button.setFixedHeight(36)
                sync_button.setEnabled(
                    not self.postgame_sync_in_progress and not _is_local_only
                )
                sync_button.clicked.connect(
                    lambda checked=False, value=session_id:
                    self.request_saved_session_sync(value)
                )
                actions.addWidget(sync_button, 1, 0)

        open_button = QPushButton(
            "Abrir análisis"
        )
        open_button.setObjectName(
            "primaryButton"
        )
        open_button.setFixedWidth(125)
        open_button.setFixedHeight(36)
        open_button.clicked.connect(
            lambda checked=False, value=session:
            self.open_saved_game_analysis(
                value
            )
        )
        actions.addWidget(open_button, 0, 1, Qt.AlignmentFlag.AlignRight)

        replay_button = QPushButton("Repaso con vídeo")
        replay_button.setObjectName("primaryButton")
        replay_button.setFixedWidth(145)
        replay_button.setFixedHeight(36)
        replay_button.setToolTip(
            "Abre la ventana independiente de repaso: grabación de la "
            "partida y desglose construido con la telemetría local."
        )
        replay_button.clicked.connect(
            lambda checked=False, value=session:
            self.open_replay_window(session=value)
        )
        actions.addWidget(replay_button, 0, 0, Qt.AlignmentFlag.AlignRight)

        delete_button = QPushButton("Eliminar")
        delete_button.setObjectName("dangerButton")
        delete_button.setFixedWidth(90)
        delete_button.setFixedHeight(36)
        if session_id:
            delete_button.clicked.connect(
                lambda checked=False, val=session_id: self.delete_saved_game_session(val)
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

        return date.astimezone().strftime(
            "%d/%m/%Y %H:%M"
        )

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
            (
                value
                for value in sessions
                if value.get("session_id") == session_id
            ),
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
                (
                    "Configura una Riot API key válida "
                    "antes de buscar datos."
                ),
            )

            self.refresh_saved_games()
            return

        game_name = self.riot_game_name_input.text().strip()
        tag_line = self.riot_tag_line_input.text().strip()

        if not game_name or not tag_line:
            self.update_saved_session_sync_status(
                session_id,
                "failed",
                (
                    "Configura tu Riot ID en Inicio "
                    "antes de buscar datos."
                ),
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
            (
                value
                for value in sessions
                if value.get("session_id") == session_id
            ),
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

            final_sync = session.setdefault(
                "final_sync",
                {},
            )

            final_sync["status"] = status
            final_sync["message"] = message

            changed = True
            break

        if changed:
            self.live_match_tracker._save_sessions(
                sessions
            )

    def open_saved_game_analysis(
        self,
        session: dict,
    ) -> None:
        dialog = LiveMatchAnalysisDialog(
            session,
            self.data_dragon_assets,
            self.item_catalog,
            self,
        )
        dialog.exec()

    def create_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settingsPage")

        scroll = QScrollArea()
        scroll.setObjectName("settingsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(scroll)

        content = QWidget()
        content.setObjectName("settingsContent")
        scroll.setWidget(content)

        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(18)

        for card in self._settings_cards():
            content_layout.addWidget(card)

        content_layout.addStretch(1)

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

    def _settings_api_card(self) -> QWidget:
        card, card_layout = self._settings_card("Ajustes")

        api_title = QLabel("Riot API")
        api_title.setObjectName("settingsGroupTitle")
        card_layout.addWidget(api_title)

        card_layout.addWidget(
            self._settings_description(
                "Introduce tu Riot API key para habilitar los datos de "
                "invocador, historial de partidas y estadísticas externas. "
                "La clave se guarda localmente en tu configuración."
            )
        )

        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("apiKeyInput")
        self.api_key_input.setPlaceholderText(
            "RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
        self.api_key_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.api_key_input.setText(self.riot_api_key)
        card_layout.addWidget(self.api_key_input)

        api_actions = QHBoxLayout()
        api_actions.setSpacing(10)

        self.save_api_key_button = QPushButton(
            "Guardar y comprobar"
        )
        self.save_api_key_button.setObjectName("primaryButton")
        self.save_api_key_button.clicked.connect(
            self.save_and_validate_api_key
        )
        api_actions.addWidget(self.save_api_key_button)

        self.clear_api_key_button = QPushButton(
            "Eliminar clave"
        )
        self.clear_api_key_button.setObjectName(
            "secondaryButton"
        )
        self.clear_api_key_button.clicked.connect(
            self.clear_api_key
        )
        api_actions.addWidget(self.clear_api_key_button)

        api_actions.addStretch(1)
        card_layout.addLayout(api_actions)

        self.api_key_status = QLabel()
        self.api_key_status.setObjectName("apiKeyStatus")
        self.update_api_key_status()

        card_layout.addWidget(self.api_key_status)

        return card

    def _settings_gemini_card(self) -> QWidget:
        card, card_layout = self._settings_card(
            "IA Gemini (Google AI Studio)"
        )

        card_layout.addWidget(
            self._settings_description(
                "Introduce tu API key de Google AI Studio (Gemini) para "
                "habilitar el re-análisis inteligente de campeones desde "
                "la pestaña de edición."
            )
        )

        self.gemini_api_key_input = QLineEdit()
        self.gemini_api_key_input.setObjectName("apiKeyInput")
        self.gemini_api_key_input.setPlaceholderText("AIzaSy...")
        self.gemini_api_key_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.gemini_api_key_input.setText(self.gemini_api_key)
        card_layout.addWidget(self.gemini_api_key_input)

        gemini_actions = QHBoxLayout()
        gemini_actions.setSpacing(10)

        self.save_gemini_api_key_button = QPushButton(
            "Guardar y comprobar Gemini Key"
        )
        self.save_gemini_api_key_button.setObjectName("primaryButton")
        self.save_gemini_api_key_button.clicked.connect(
            self.save_and_validate_gemini_api_key
        )
        gemini_actions.addWidget(self.save_gemini_api_key_button)

        self.clear_gemini_api_key_button = QPushButton(
            "Eliminar clave Gemini"
        )
        self.clear_gemini_api_key_button.setObjectName(
            "secondaryButton"
        )
        self.clear_gemini_api_key_button.clicked.connect(
            self.clear_gemini_api_key
        )
        gemini_actions.addWidget(self.clear_gemini_api_key_button)

        gemini_actions.addStretch(1)
        card_layout.addLayout(gemini_actions)

        self.gemini_api_key_status = QLabel()
        self.gemini_api_key_status.setObjectName("apiKeyStatus")
        self.gemini_api_key_status.setWordWrap(True)
        card_layout.addWidget(self.gemini_api_key_status)

        self.update_gemini_api_key_status()

        return card

    def _settings_recordings_card(self) -> QWidget:
        card, card_layout = self._settings_card("Grabaciones")

        card_layout.addWidget(
            self._settings_description(
                "Cada partida se graba sola: la grabación empieza cuando "
                "empieza la partida y termina al acabarla. Guarda el vídeo "
                "de la pantalla con el sonido del juego; el micrófono es "
                "opcional. Los cambios se aplican a la próxima grabación."
            )
        )

        self.recording_auto_checkbox = QCheckBox(
            "Grabar cada partida automáticamente"
        )
        self.recording_auto_checkbox.setChecked(
            bool(self.settings.get("recording_auto", True))
        )
        self.recording_auto_checkbox.toggled.connect(
            self._on_recording_auto_toggled
        )
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
            self.recording_quality_combo.addItem(
                quality_label(key), key
            )

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
            self.recording_bitrate_combo.addItem(
                bitrate_label(value), value
            )

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

        game_audio_row = QHBoxLayout()
        game_audio_row.setSpacing(10)

        game_audio_caption = QLabel("Sonido del juego")
        game_audio_caption.setObjectName("settingsLabel")
        game_audio_caption.setMinimumWidth(150)
        game_audio_row.addWidget(game_audio_caption)

        self.recording_game_audio_combo = QComboBox()
        self.recording_game_audio_combo.setObjectName("analysisCombo")
        self.recording_game_audio_combo.currentIndexChanged.connect(
            self._on_recording_game_audio_changed
        )
        game_audio_row.addWidget(self.recording_game_audio_combo, 1)
        card_layout.addLayout(game_audio_row)

        self.recording_mic_checkbox = QCheckBox("Grabar mi micrófono")
        self.recording_mic_checkbox.setChecked(
            bool(self.settings.get("recording_mic_enabled", False))
        )
        self.recording_mic_checkbox.toggled.connect(
            self._on_recording_mic_toggled
        )
        card_layout.addWidget(self.recording_mic_checkbox)

        mic_row = QHBoxLayout()
        mic_row.setSpacing(10)

        mic_caption = QLabel("Micrófono")
        mic_caption.setObjectName("settingsLabel")
        mic_caption.setMinimumWidth(150)
        mic_row.addWidget(mic_caption)

        self.recording_mic_combo = QComboBox()
        self.recording_mic_combo.setObjectName("analysisCombo")
        self.recording_mic_combo.currentIndexChanged.connect(
            self._on_recording_mic_device_changed
        )
        mic_row.addWidget(self.recording_mic_combo, 1)
        card_layout.addLayout(mic_row)

        self.recording_devices_button = QPushButton(
            "Buscar dispositivos de sonido"
        )
        self.recording_devices_button.setObjectName("secondaryButton")
        self.recording_devices_button.clicked.connect(
            self.refresh_recording_devices
        )
        card_layout.addWidget(self.recording_devices_button)

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
        self.recording_dir_button.clicked.connect(
            self.choose_recordings_folder
        )
        folder_row.addWidget(self.recording_dir_button)

        self.recording_folder_button = QPushButton("Abrir")
        self.recording_folder_button.setObjectName("secondaryButton")
        self.recording_folder_button.clicked.connect(
            self.open_recordings_folder
        )
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
        self.recording_config = RecordingConfig.from_settings(
            self.settings
        )
        self.recording_library.set_directory(
            self.recording_config.output_dir
        )

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

    def _on_recording_game_audio_changed(self, _index: int) -> None:
        if not hasattr(self, "recording_game_audio_combo"):
            return

        value = self.recording_game_audio_combo.currentData()

        if value is not None:
            self.settings["recording_game_audio_device"] = str(value)
            self._save_recording_settings()

        self.sync_recording_controls()

    def _on_recording_mic_toggled(self, checked: bool) -> None:
        self.settings["recording_mic_enabled"] = bool(checked)
        self._save_recording_settings()
        self.sync_recording_controls()

    def _on_recording_mic_device_changed(self, _index: int) -> None:
        if not hasattr(self, "recording_mic_combo"):
            return

        value = self.recording_mic_combo.currentData()

        if value is not None:
            self.settings["recording_mic_device"] = str(value)
            self._save_recording_settings()

    def _on_recording_limit_changed(self, gigabytes: int) -> None:
        self.settings["recording_size_limit_gb"] = float(gigabytes)
        self.recording_limit_value.setText(f"{int(gigabytes)} GB")
        self._save_recording_settings()
        self.sync_recording_controls()

    def refresh_recording_devices(self, silent: bool = False) -> None:
        """Rellena los desplegables de sonido con lo que ve ffmpeg."""
        if not hasattr(self, "recording_game_audio_combo"):
            return

        found = self.recording_service.refresh_ffmpeg(
            str(self.settings.get("ffmpeg_path") or "")
        )

        if not found:
            for combo in (
                self.recording_game_audio_combo,
                self.recording_mic_combo,
            ):
                combo.blockSignals(True)
                combo.clear()
                combo.addItem("Sin ffmpeg: no se puede grabar", "")
                combo.blockSignals(False)

            self.sync_recording_controls()

            if not silent:
                self.recording_status.setText(
                    self.recording_service.ffmpeg_hint
                )

            return

        devices = list_audio_devices(found)
        saved_game = str(
            self.settings.get("recording_game_audio_device") or ""
        )
        saved_mic = str(self.settings.get("recording_mic_device") or "")

        if not saved_game:
            saved_game = pick_game_audio_device(devices)

            if saved_game:
                self.settings["recording_game_audio_device"] = saved_game

        if not saved_mic:
            saved_mic = pick_microphone_device(devices)

            if saved_mic:
                self.settings["recording_mic_device"] = saved_mic

        self._fill_audio_combo(
            self.recording_game_audio_combo, devices, saved_game,
            "Sin sonido del juego (solo vídeo)",
        )
        self._fill_audio_combo(
            self.recording_mic_combo, devices, saved_mic,
            "Micrófono no elegido",
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
            live_session = getattr(
                self.live_analysis_dialog, "session", None
            )
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
            self.recording_library.video_files(),
            session,
            self.recording_library.load_metadata,
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
            self.recording_game_audio_combo,
            self.recording_mic_checkbox,
            self.recording_mic_combo,
            self.recording_devices_button,
            self.recording_dir_button,
        )

        for widget in widgets:
            widget.blockSignals(True)

        self.recording_auto_checkbox.setChecked(config.enabled)
        self.set_combo_value(
            self.recording_quality_combo, config.quality
        )
        self.set_combo_value(
            self.recording_bitrate_combo, config.video_bitrate
        )
        self.set_combo_value(
            self.recording_game_audio_combo, config.game_audio_device
        )
        self.recording_mic_checkbox.setChecked(config.mic_enabled)
        self.set_combo_value(
            self.recording_mic_combo, config.mic_device
        )
        self.recording_limit_slider.setValue(int(config.size_limit_gb))
        self.recording_limit_value.setText(
            f"{int(config.size_limit_gb)} GB"
        )
        self.recording_dir_input.setText(
            str(self.settings.get("recording_output_dir", ""))
        )

        self.recording_mic_combo.setEnabled(config.mic_enabled)

        pieces = []

        if service.ffmpeg_available:
            pieces.append("ffmpeg listo")
        else:
            pieces.append(
                service.ffmpeg_hint or "ffmpeg no encontrado"
            )

        if config.game_audio_device:
            pieces.append(
                f"Sonido del juego: {config.game_audio_device}"
            )
        else:
            pieces.append("Sin sonido del juego (solo vídeo)")

        if config.mic_enabled:
            pieces.append(
                f"Micrófono: {config.mic_device or 'automático'}"
            )

        total = self.recording_library.total_size_bytes()
        pieces.append(
            f"Carpeta: {format_size(total)} de "
            f"{int(config.size_limit_gb)} GB"
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

    def start_match_recording(self, snapshot: dict) -> None:
        """Arranca la grabación al empezar la partida (si está activada)."""
        if self.recording_service.is_recording:
            return

        local_player = snapshot.get("local_player", {})

        if not isinstance(local_player, dict):
            local_player = {}

        champion = str(
            local_player.get("championName", "Desconocido")
        )
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

    def stop_match_recording(
        self, reason: str, session: dict | None = None
    ) -> None:
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
            self.recording_status.setText(
                f"{message} {current}".strip()
            )

        if hasattr(self, "recordings_page"):
            self.recordings_page.refresh()

    def _on_recording_finished(self, _path: str) -> None:
        self.sync_recording_controls()

        if hasattr(self, "recordings_page"):
            self.recordings_page.refresh()

    def _sync_overlay_recording(self, _state: str = "") -> None:
        """Refleja si se está grabando en el overlay de alertas."""
        if not hasattr(self, "overlay"):
            return

        active = self.recording_service.is_recording
        elapsed = (
            self.recording_service.elapsed_seconds() if active else 0.0
        )
        self.overlay.set_recording(active, elapsed)

    def _settings_overlay_card(self) -> QWidget:
        card, card_layout = self._settings_card("Overlay en partida")

        self.show_overlay_button = QPushButton("Mostrar overlay")
        self.show_overlay_button.setObjectName("primaryButton")
        self.show_overlay_button.clicked.connect(
            self.toggle_overlay_visibility
        )
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
                lambda _checked=False, key=panel_key: (
                    self.toggle_overlay_panel(key)
                )
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
            checkbox = QCheckBox(f"Solo TAB: {panel_name}")
            checkbox.setChecked(self.overlay.is_tab_only(panel_key))
            checkbox.setToolTip(
                f"El panel {panel_name} solo aparece mientras "
                "mantienes pulsado TAB."
            )
            checkbox.toggled.connect(
                lambda checked, key=panel_key: (
                    self.toggle_overlay_tab_only(key, checked)
                )
            )
            tab_only_row.addWidget(checkbox)
            self.overlay_tab_only_checkboxes[panel_key] = checkbox

        tab_only_row.addStretch(1)
        card_layout.addLayout(tab_only_row)

        self.lock_overlay_button = QPushButton("Bloquear clics: NO")
        self.lock_overlay_button.setObjectName("secondaryButton")
        self.lock_overlay_button.clicked.connect(
            self.toggle_overlay_click_through
        )
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
        self.opacity_slider.valueChanged.connect(
            self.change_overlay_opacity
        )
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
        self.alert_lead_value.setText(
            f"{self.overlay.alert_lead_seconds} s"
        )
        self.alert_lead_slider.valueChanged.connect(
            self.change_overlay_alert_lead
        )
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

        self.sound_enabled_checkbox = QCheckBox("Activar sonidos del overlay")
        self.sound_enabled_checkbox.setChecked(self.overlay.is_sound_enabled())
        self.sound_enabled_checkbox.toggled.connect(
            self.toggle_overlay_sound_enabled
        )
        card_layout.addWidget(self.sound_enabled_checkbox)

        self.sound_objective_checkbox = QCheckBox(
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

        self.sound_dragon_checkbox = QCheckBox("Pitido: Dragón")
        self.sound_dragon_checkbox.setChecked(
            self.overlay.sound_service.kind_enabled("dragon")
        )
        self.sound_dragon_checkbox.toggled.connect(
            lambda checked, kind="dragon": self.toggle_overlay_sound_kind(
                kind, checked
            )
        )
        card_layout.addWidget(self.sound_dragon_checkbox)

        self.sound_enemy_buy_checkbox = QCheckBox(
            "Pitido: compra de objeto rival"
        )
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
        self.sound_volume_slider.valueChanged.connect(
            self.change_overlay_sound_volume
        )
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
            self.api_key_status.setText(
                "No hay una Riot API key configurada."
            )
            self.api_key_status.setProperty(
                "state",
                "missing",
            )

        self.api_key_status.style().unpolish(
            self.api_key_status
        )
        self.api_key_status.style().polish(
            self.api_key_status
        )


    def save_and_validate_api_key(self) -> None:
        api_key = self.api_key_input.text().strip()

        self.save_api_key_button.setEnabled(False)
        self.api_key_status.setText(
            "Comprobando Riot API key..."
        )
        self.api_key_status.setProperty(
            "state",
            "checking",
        )

        self.api_key_status.style().unpolish(
            self.api_key_status
        )
        self.api_key_status.style().polish(
            self.api_key_status
        )

        valid, message = (
            self.settings_service.validate_riot_api_key(
                api_key
            )
        )

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

        self.api_key_status.style().unpolish(
            self.api_key_status
        )
        self.api_key_status.style().polish(
            self.api_key_status
        )


    def clear_api_key(self) -> None:
        self.riot_api_key = ""
        self.settings.pop("riot_api_key", None)
        self.settings_service.save(self.settings)

        self.api_key_input.clear()

        self.api_key_status.setText(
            "Riot API key eliminada de la configuración local."
        )
        self.api_key_status.setProperty(
            "state",
            "missing",
        )

        self.api_key_status.style().unpolish(
            self.api_key_status
        )
        self.api_key_status.style().polish(
            self.api_key_status
        )

    def update_gemini_api_key_status(self) -> None:
        if self.gemini_api_key:
            self.gemini_api_key_status.setText("Hay una Gemini API key guardada. Pulsa 'Guardar y comprobar' para validarla.")
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
        self.gemini_api_key_status.setText("Gemini API key eliminada de la configuración local.")
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
        self.item_catalog
        )

        self.live_data_worker.moveToThread(
            self.worker_thread
        )

        self.snapshot_requested.connect(
            self.live_data_worker.read_snapshot
        )

        self.live_data_worker.snapshot_ready.connect(
            self.receive_snapshot
        )

        self.live_data_worker.live_analysis_ready.connect(
            self.receive_live_analysis
        )

        self.live_data_worker.read_failed.connect(
            self.show_read_error
        )

        self.live_data_worker.game_ended.connect(
            self.handle_game_ended
        )
        self.worker_thread.start()

    def setup_match_history_worker(self) -> None:
        self.history_thread = QThread(self)
        self.match_history_worker = MatchHistoryWorker()
        self.match_history_worker.moveToThread(
            self.history_thread
        )

        self.history_requested.connect(
            self.match_history_worker.load_history
        )
        self.match_history_worker.history_ready.connect(
            self.receive_match_history
        )
        self.match_history_worker.history_failed.connect(
            self.show_match_history_error
        )

        self.profile_requested.connect(
            self.match_history_worker.load_profile
        )
        self.match_history_worker.profile_ready.connect(
            self.receive_summoner_profile
        )

        self.history_thread.start()

        self.match_detail_requested.connect(
            self.match_history_worker.load_match_detail
        )

        self.match_history_worker.detail_ready.connect(
            self.open_match_inspector
        )

        self.match_history_worker.detail_failed.connect(
            self.show_match_detail_error
        )

    def setup_postgame_sync_worker(
        self,
    ) -> None:
        """
        Crea un hilo separado para sincronizar Match-V5 tras una partida.

        Nunca se hacen peticiones de Riot API desde el hilo de interfaz.
        """
        self.postgame_sync_thread = QThread(self)

        self.postgame_sync_worker = (
            PostgameSyncWorker()
        )

        self.postgame_sync_worker.moveToThread(
            self.postgame_sync_thread
        )

        self.postgame_sync_requested.connect(
            self.postgame_sync_worker.sync_session
        )

        self.postgame_sync_worker.sync_ready.connect(
            self.receive_postgame_sync
        )

        self.postgame_sync_worker.sync_failed.connect(
            self.receive_postgame_sync_error
        )

        self.postgame_sync_worker.sync_progress.connect(
            self.on_postgame_sync_progress
        )

        self.postgame_sync_thread.start()

    def request_match_detail(
        self,
        match_id: str,
    ) -> None:
        if self.history_is_loading:
            return

        if not match_id:
            return

        if not self.riot_api_key:
            self.set_history_status(
                "Configura una Riot API key válida "
                "en Ajustes antes de abrir partidas.",
                "error",
            )
            return

        game_name = self.riot_game_name_input.text().strip()
        tag_line = self.riot_tag_line_input.text().strip()

        if not game_name or not tag_line:
            self.set_history_status(
                "Indica tu Riot ID antes de abrir partidas.",
                "error",
            )
            return

        self.history_is_loading = True
        self.refresh_history_button.setEnabled(False)

        self.set_history_status(
            "Abriendo detalle de partida…",
            "loading",
        )

        self.match_detail_requested.emit(
            self.riot_api_key,
            game_name,
            tag_line,
            self.riot_account_region,
            self.riot_platform_region,
            match_id,
        )


    @Slot(dict)
    def open_match_inspector(
        self,
        match_detail: dict,
    ) -> None:
        self.history_is_loading = False
        self.refresh_history_button.setEnabled(True)

        self.set_history_status(
            "Detalle de partida cargado.",
            "success",
        )

        dialog = MatchInspectorDialog(
            match_detail,
            self.item_catalog,
            self.data_dragon_assets,
            self,
        )
        dialog.exec()

    @Slot(str, int)
    def show_match_detail_error(
        self,
        message: str,
        retry_after: int,
    ) -> None:
        self.history_is_loading = False
        self.refresh_history_button.setEnabled(True)

        if retry_after:
            message = (
                f"{message} El botón volverá a estar "
                f"disponible en {retry_after} s."
            )

            self.refresh_history_button.setEnabled(False)

            QTimer.singleShot(
                retry_after * 1000,
                self.enable_history_refresh,
            )

        self.set_history_status(message, "error")

    def request_match_history(self) -> None:
        if self.history_is_loading:
            return

        if not self.riot_api_key:
            self.set_history_status(
                "Configura primero una Riot API key válida "
                "en Ajustes.",
                "error",
            )
            return

        game_name = self.riot_game_name_input.text().strip()
        tag_line = self.riot_tag_line_input.text().strip()

        if not game_name or not tag_line:
            self.set_history_status(
                "Indica tu Riot ID en formato Nombre#TAG.",
                "error",
            )
            return

        self.save_riot_id(
            game_name,
            tag_line,
        )

        self.match_history = []
        self.render_match_history()

        self.history_is_loading = True
        self.refresh_history_button.setEnabled(False)

        self.set_history_status(
            "Actualizando historial…",
            "loading",
        )

        self.history_requested.emit(
            self.riot_api_key,
            game_name,
            tag_line,
            self.riot_account_region,
            self.riot_platform_region,
            30,
        )

        self.profile_requested.emit(
            self.riot_api_key,
            game_name,
            tag_line,
            self.riot_account_region,
            self.riot_platform_region,
        )

    @Slot(dict)
    def receive_summoner_profile(self, profile_data: dict[str, Any]) -> None:
        if not profile_data:
            return

        riot_id = profile_data.get("riot_id", f"{self.riot_game_name}#{self.riot_tag_line}")
        if hasattr(self, "summoner_riot_id_label"):
            self.summoner_riot_id_label.setText(riot_id)

        level = profile_data.get("summoner_level", 0)
        if hasattr(self, "summoner_level_label"):
            self.summoner_level_label.setText(f"Nivel {level} · {self.riot_platform_region.upper()}")

        icon_id = profile_data.get("profile_icon_id")
        if icon_id and hasattr(self, "profile_icon_label"):
            icon_url = self.data_dragon_assets.profile_icon_url(icon_id)
            self.data_dragon_assets.set_label_image(
                self.profile_icon_label,
                icon_url,
                f"profileicon:{icon_id}",
                54,
            )

        ranked_solo = profile_data.get("ranked_solo", {})
        self.current_ranked_solo = ranked_solo
        if ranked_solo and ranked_solo.get("tier_formatted") and hasattr(self, "soloq_tier_badge"):
            tier_str = ranked_solo["tier_formatted"]
            wr = ranked_solo.get("winrate", 0.0)
            wins = ranked_solo.get("wins", 0)
            losses = ranked_solo.get("losses", 0)
            total = ranked_solo.get("total_games", wins + losses)

            self.soloq_tier_badge.setText(f"🏆 {tier_str}")
            self.soloq_winrate_label.setText(
                f"Season Record: {wins}V / {losses}D ({total} partidas) · {wr}% WR Total"
            )
        elif hasattr(self, "soloq_tier_badge"):
            self.soloq_tier_badge.setText("🏆 RANKED SOLOQ · UNRANKED")
            self.soloq_winrate_label.setText("Season Record: Sin partidas de clasificatoria")

        if hasattr(self, "match_history") and self.match_history:
            self.update_soloq_dashboard_from_history(self.match_history)

    @Slot(str)
    def show_summoner_profile_error(self, message: str) -> None:
        pass

    @Slot(list)
    def receive_match_history(
        self,
        history: list,
    ) -> None:
        self.history_is_loading = False
        self.refresh_history_button.setEnabled(True)

        self.match_history = history
        self.render_match_history()
        self.update_soloq_dashboard_from_history(history)

        if history:
            self.set_history_status(
                f"Historial actualizado: "
                f"{len(history)} partidas.",
                "success",
            )
        else:
            self.set_history_status(
                "No se encontraron partidas recientes.",
                "empty",
            )

    @staticmethod
    def calculate_elo_points(tier: str, rank: str, lp: int) -> int:
        tier_bases = {
            "IRON": 0,
            "BRONZE": 400,
            "SILVER": 800,
            "GOLD": 1200,
            "PLATINUM": 1600,
            "EMERALD": 2000,
            "DIAMOND": 2400,
            "MASTER": 2800,
            "GRANDMASTER": 3200,
            "CHALLENGER": 3600,
        }
        rank_offsets = {"IV": 0, "III": 100, "II": 200, "I": 300}
        base = tier_bases.get(tier.upper(), 1200)
        offset = rank_offsets.get(rank.upper(), 0)
        return base + offset + max(0, lp)

    @staticmethod
    def elo_to_rank_label(elo: int) -> str:
        if elo >= 2800:
            if elo >= 3600:
                return f"Aspirante ({elo - 3600} LP)"
            elif elo >= 3200:
                return f"Gran Máster ({elo - 3200} LP)"
            else:
                return f"Máster ({elo - 2800} LP)"
        tier_bases = [
            ("Hierro", 0),
            ("Bronce", 400),
            ("Plata", 800),
            ("Oro", 1200),
            ("Platino", 1600),
            ("Esmeralda", 2000),
            ("Diamante", 2400),
        ]
        tier_name = "Hierro"
        base_val = 0
        for name, val in tier_bases:
            if elo >= val:
                tier_name = name
                base_val = val
        rem = elo - base_val
        div_idx = min(3, max(0, int(rem // 100)))
        divs = ["IV", "III", "II", "I"]
        lp = int(rem % 100)
        return f"{tier_name} {divs[div_idx]} ({lp} LP)"

    def update_soloq_dashboard_from_history(self, history: list[dict]) -> None:
        if not history or not hasattr(self, "soloq_graph"):
            return

        from collections import Counter
        champs = [h.get("champion_name") for h in history if h.get("champion_name")]
        if champs:
            counter = Counter(champs)
            most_common_champ, count = counter.most_common(1)[0]
            champ_wins = sum(1 for h in history if h.get("champion_name") == most_common_champ and h.get("win"))
            champ_wr = round((champ_wins / count) * 100, 1)

            if hasattr(self, "most_played_title"):
                self.most_played_title.setText(f"Más Jugado: {most_common_champ}")
            if hasattr(self, "most_played_stats"):
                self.most_played_stats.setText(f"{count} partidas en historial ({champ_wr}% WR)")
            if hasattr(self, "most_played_icon"):
                self.data_dragon_assets.set_label_image(
                    self.most_played_icon,
                    self.data_dragon_assets.champion_url(most_common_champ),
                    f"champion:{most_common_champ}:48",
                    48,
                )

        # Filter history for Ranked Solo/Duo matches only (queue_id == 420 or missing queue_id as fallback)
        ranked_matches = [
            m for m in history
            if m.get("queue_id") is None or m.get("queue_id") == 420
        ]

        if not ranked_matches:
            self.soloq_graph.set_data([])
            return

        base_elo = 1200
        if hasattr(self, "current_ranked_solo") and self.current_ranked_solo:
            tier = str(self.current_ranked_solo.get("tier", "")).upper()
            rank = str(self.current_ranked_solo.get("rank", "")).upper()
            lp = int(self.current_ranked_solo.get("league_points", 0))
            base_elo = self.calculate_elo_points(tier, rank, lp)

        n = len(ranked_matches)
        match_elos = [0] * n
        curr = base_elo
        for idx, match in enumerate(ranked_matches):
            match_elos[idx] = curr
            is_win = bool(match.get("win", False))
            curr = curr - 25 if is_win else curr + 25

        points = []
        for i, match in enumerate(reversed(ranked_matches)):
            orig_idx = n - 1 - i
            elo_val = match_elos[orig_idx]
            is_win = bool(match.get("win", False))
            champ = match.get("champion_name", "Campeón")
            elo_lbl = self.elo_to_rank_label(elo_val)

            label_name = "Partida SoloQ (Última)" if i == n - 1 else f"Partida SoloQ #{i + 1}"

            points.append({
                "time_label": label_name,
                "elo": elo_val,
                "elo_label": elo_lbl,
                "champion": champ,
                "win": is_win,
            })

        self.soloq_graph.set_data(points)

    @Slot(str, int)
    def show_match_history_error(
        self,
        message: str,
        retry_after: int,
    ) -> None:
        self.history_is_loading = False
        self.refresh_history_button.setEnabled(True)

        if retry_after:
            message = (
                f"{message} El botón volverá a estar "
                f"disponible en {retry_after} s."
            )
            self.refresh_history_button.setEnabled(False)

            QTimer.singleShot(
                retry_after * 1000,
                self.enable_history_refresh,
            )

        self.set_history_status(message, "error")

    def enable_history_refresh(self) -> None:
        if not self.history_is_loading:
            self.refresh_history_button.setEnabled(True)

    def save_riot_id(
        self,
        game_name: str,
        tag_line: str,
    ) -> None:
        self.riot_game_name = game_name
        self.riot_tag_line = tag_line

        self.settings.update(
            {
                "riot_game_name": game_name,
                "riot_tag_line": tag_line,
                "riot_account_region": (
                    self.riot_account_region
                ),
                "riot_platform_region": (
                    self.riot_platform_region
                ),
            }
        )

        self.settings_service.save(self.settings)

    def render_match_history(self) -> None:
        while self.history_list_layout.count():
            item = self.history_list_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        for match in self.match_history:
            self.history_list_layout.addWidget(
                self.create_match_history_row(match)
            )

    def create_match_history_row(
        self,
        match: dict,
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("matchHistoryRow")
        row.setMinimumHeight(50)

        result = "Victoria" if match.get("win") else "Derrota"
        result_state = (
            "victory"
            if match.get("win")
            else "defeat"
        )

        kills = match.get("kills", 0)
        deaths = match.get("deaths", 0)
        assists = match.get("assists", 0)
        cs = match.get("cs", 0)

        duration = self.format_match_duration(
            match.get("game_duration", 0)
        )

        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 11, 14, 11)
        row_layout.setSpacing(16)

        result_label = QLabel(result)
        result_label.setObjectName("matchResult")
        result_label.setProperty("result", result_state)
        result_label.setMinimumWidth(72)
        row_layout.addWidget(result_label)

        champion_label = QLabel(
            match.get("champion_name") or "Desconocido"
        )
        champion_label.setObjectName("matchChampion")
        champion_label.setMinimumWidth(130)
        row_layout.addWidget(champion_label)

        kda_label = QLabel(
            f"{kills} / {deaths} / {assists}"
        )
        kda_label.setObjectName("matchKda")
        kda_label.setMinimumWidth(92)
        row_layout.addWidget(kda_label)

        cs_label = QLabel(f"{cs} CS")
        cs_label.setObjectName("matchCs")
        cs_label.setMinimumWidth(70)
        row_layout.addWidget(cs_label)

        duration_label = QLabel(duration)
        duration_label.setObjectName("matchDuration")
        duration_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )
        row_layout.addWidget(duration_label, 1)

        row.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        row.mousePressEvent = (
            lambda event, match_id=match.get("match_id", ""):
            self.request_match_detail(match_id)
        )

        return row


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


    def set_history_status(
        self,
        text: str,
        state: str,
    ) -> None:
        self.history_status.setText(text)
        self.history_status.setProperty("state", state)

        self.history_status.style().unpolish(
            self.history_status
        )
        self.history_status.style().polish(
            self.history_status
        )

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
        self.home_title.setText("No se pudo leer el cliente")
        self.home_text.setText(message)
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
        self.connection_label.setText(
            "League abierto · sin partida"
        )
        self.home_title.setText("Esperando una partida")
        self.home_text.setText(
            "El cliente está disponible. Entra en una partida para habilitar el panel en vivo."
        )

        self.player_metric.metric_value.setText("Disponible")
        self.player_metric.metric_detail.setText(
            "Se detectó la API local de League."
        )
        self.mode_metric.metric_value.setText("—")
        self.mode_metric.metric_detail.setText(
            "Se mostrará al detectar una partida."
        )
        self.session_metric.metric_value.setText("En espera")
        self.session_metric.metric_detail.setText(
            "El panel se actualiza automáticamente."
        )

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
                "La pestaña se habilitará automáticamente "
                "al comenzar una partida."
            )
            self.live_empty_label.setObjectName(
                "liveSummary"
            )
            self.live_empty_label.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            self.live_empty_label.setWordWrap(True)

            self.cards_layout.addWidget(
                self.live_empty_label,
                1,
            )

            self.was_in_game = False
            self.cards_built = False
            self.panel_refresh_counter = 0

    def show_game(self, snapshot: dict) -> None:
        game_time = float(
            snapshot.get("game_time", 0)
        )
        minutes = int(game_time // 60)
        seconds = int(game_time % 60)

        local_player = snapshot.get(
            "local_player",
            {},
        )
        player_name = (
            local_player.get("riotId")
            or local_player.get("summonerName")
            or "Jugador local"
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
        self.home_title.setText(
            f"En partida con {champion}"
        )
        self.home_text.setText(
            "Los datos en vivo se están actualizando. "
            "Consulta la pestaña Partida en vivo para ver ambos equipos."
        )

        self.player_metric.metric_value.setText(
            player_name
        )
        self.player_metric.metric_detail.setText(
            f"Campeón actual: {champion}"
        )
        self.mode_metric.metric_value.setText(
            game_mode
        )
        self.mode_metric.metric_detail.setText(
            f"Tiempo: {minutes:02d}:{seconds:02d}"
        )
        self.session_metric.metric_value.setText(
            "En curso"
        )
        self.session_metric.metric_detail.setText(
            f"{len(snapshot.get('all_players', []))} jugadores detectados."
        )

        self.live_button.setEnabled(True)
        self.open_live_analysis_button.setEnabled(
            self.current_live_session is not None
        )

        # La partida ya está en curso (la pantalla de carga terminó): si el draft
        # acaba de terminar, el panel se coloca en "Partida en vivo".
        if self.pending_live_navigation:
            self.pending_live_navigation = False
            self.navigate_to_live_page()

        self.live_status.setText(
            f"{mode_text} · {champion} · "
            f"{total_players} jugadores"
        )
        self.live_time_label.setText(
            f"{minutes:02d}:{seconds:02d}"
        )
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

        if (
            self.panel_refresh_counter
            < self.panel_refresh_every_seconds
        ):
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
        )

        self.live_analysis_dialog = dialog

        dialog.finished.connect(
            self.clear_live_analysis_dialog
        )

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
        """
        Marca la sesión como pendiente y espera antes de consultar Riot.

        Match-V5 puede tardar unos segundos en registrar una partida
        terminada; no consultamos inmediatamente.
        """
        if not self.riot_api_key:
            return

        game_name = self.riot_game_name_input.text().strip()
        tag_line = self.riot_tag_line_input.text().strip()

        if not game_name or not tag_line:
            return

        session_id = str(
            session.get(
                "session_id",
                "",
            )
        )

        if not session_id:
            return

        self.pending_postgame_session_id = session_id

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
            lambda value=session_id: self.start_postgame_sync(
                value
            ),
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
            (
                value
                for value in sessions
                if value.get("session_id") == session_id
            ),
            None,
        )

        if not isinstance(session, dict):
            return

        game_name = self.riot_game_name_input.text().strip()
        tag_line = self.riot_tag_line_input.text().strip()

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

            sessions[index] = updated_session
            replaced = True
            break

        if replaced:
            self.live_match_tracker._save_sessions(
                sessions
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
        position = str(
            player.get("position", "")
        ).upper()

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
        """Reconstruye el panel: un bloque por equipo con su cabecera."""
        self.clear_cards()

        all_players = snapshot.get("all_players", [])

        if not isinstance(all_players, list):
            all_players = []

        local_team = str(
            snapshot.get("local_team", "")
        ).upper()

        if local_team not in ("ORDER", "CHAOS"):
            local_team = "ORDER"

        teams = [
            ("ORDER", "Equipo azul"),
            ("CHAOS", "Equipo rojo"),
        ]

        if local_team == "CHAOS":
            teams.reverse()

        if not all_players:
            waiting = QLabel(
                "Esperando los datos de los diez jugadores..."
            )
            waiting.setObjectName("liveSummary")
            waiting.setAlignment(Qt.AlignmentFlag.AlignCenter)
            waiting.setWordWrap(True)
            self.cards_layout.addWidget(waiting, 1)
            return

        for team, side_name in teams:
            players = self.sort_players_by_role(
                [
                    player
                    for player in all_players
                    if player.get("team") == team
                ]
            )

            if not players:
                continue

            self.add_team_panel(
                team,
                side_name,
                players,
                snapshot,
                is_local_team=team == local_team,
            )

    def add_team_panel(
        self,
        team: str,
        side_name: str,
        players: list[dict],
        snapshot: dict,
        is_local_team: bool,
    ) -> None:
        """Añade el bloque de un equipo con su cabecera y sus tarjetas."""
        panel = QFrame()
        panel.setObjectName("liveTeamPanel")
        panel.setProperty(
            "side",
            "ally" if is_local_team else "enemy",
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)

        layout.addLayout(
            self.create_team_header(
                players,
                side_name,
                is_local_team,
            )
        )

        grid_container = QWidget()
        grid_container.setObjectName("teamCardsRow")

        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        for column in range(5):
            grid.setColumnStretch(column, 1)

        local_player = snapshot.get("local_player", {})

        for index, player in enumerate(players[:5]):
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
                QSizePolicy.Policy.Preferred,
            )

            grid.addWidget(card, 0, index)

        layout.addWidget(grid_container)
        self.cards_layout.addWidget(panel)
        # Tras reconstruir, el alto del contenido debe ser válido de
        # inmediato: el scroll depende de él y la tarjeta mide su fondo.
        self.cards_widget.adjustSize()

    def create_team_header(
        self,
        players: list[dict],
        side_name: str,
        is_local_team: bool,
    ) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(10)
        header.setContentsMargins(0, 0, 4, 0)

        tag = QLabel(
            "TU EQUIPO" if is_local_team else "EQUIPO ENEMIGO"
        )
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

        return header

    def format_team_summary(self, players: list[dict]) -> str:
        """Resumen del equipo: asesinatos, oro en objetos y jugadores."""
        kills = 0
        gold = 0

        for player in players:
            scores = player.get("scores", {})

            if isinstance(scores, dict):
                try:
                    kills += int(scores.get("kills", 0) or 0)
                except (TypeError, ValueError):
                    pass

            gold += get_inventory_value(
                player,
                self.item_catalog,
            )

        gold_text = (
            f"{gold / 1000:.1f}k" if gold >= 1000 else str(gold)
        )
        total = min(len(players), 5)
        players_text = (
            "1 JUGADOR" if total == 1 else f"{total} JUGADORES"
        )

        return (
            f"{kills} ASESINATOS · {gold_text} ORO EN OBJETOS · "
            f"{players_text}"
        )

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
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()

            if widget is None:
                continue

            if (
                keep_empty_label
                and widget is self.live_empty_label
            ):
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

    def toggle_overlay_visibility(self) -> None:
        enabled = self.overlay.toggle_all()
        self.show_overlay_button.setText(
            "Ocultar overlay"
            if enabled
            else "Mostrar overlay"
        )
        self.sync_overlay_settings_ui()

    def toggle_overlay_click_through(self) -> None:
        enabled = not self.overlay.click_through
        self.overlay.set_click_through(enabled)
        self.sync_overlay_settings_ui()

    def change_overlay_opacity(self, percent: int) -> None:
        self.overlay.set_overlay_opacity(percent)
        self.opacity_value.setText(
            f"{percent}%"
        )

    def change_overlay_alert_lead(self, seconds: int) -> None:
        self.overlay.set_alert_lead_seconds(seconds)
        self.alert_lead_value.setText(
            f"{seconds} s"
        )

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
            "Ocultar overlay"
            if self.overlay.any_enabled()
            else "Mostrar overlay"
        )
        self.lock_overlay_button.setText(
            "Bloquear clics: SÍ"
            if self.overlay.click_through
            else "Bloquear clics: NO"
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
        active = [
            name
            for key, name in panel_names.items()
            if enabled.get(key, False)
        ]
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
        self.sound_objective_checkbox.setChecked(
            service.kind_enabled("objective")
        )
        self.sound_dragon_checkbox.setChecked(service.kind_enabled("dragon"))
        self.sound_enemy_buy_checkbox.setChecked(
            service.kind_enabled("enemy_buy")
        )
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
        self.champ_select_worker.champ_select_started.connect(self._on_champ_select_started)
        self.champ_select_worker.champ_select_updated.connect(self._on_champ_select_updated)
        self.champ_select_worker.champ_select_ended.connect(self._on_champ_select_ended)
        self.champ_select_worker.start()

    def open_draft_tool_dialog(self) -> None:
        if not self.draft_tool_dialog or not self.draft_tool_dialog.isVisible():
            self.draft_tool_dialog = DraftToolDialog(self)
            self.draft_tool_dialog.show()
        else:
            self.draft_tool_dialog.raise_()
            self.draft_tool_dialog.activateWindow()

    @Slot(dict)
    def _on_champ_select_started(self, session: dict) -> None:
        self.pending_live_navigation = False
        self.open_draft_tool_dialog()
        if self.draft_tool_dialog:
            self.draft_tool_dialog.update_from_lcu_session(session)

    @Slot(dict)
    def _on_champ_select_updated(self, session: dict) -> None:
        if self.draft_tool_dialog and self.draft_tool_dialog.isVisible():
            self.draft_tool_dialog.update_from_lcu_session(session)

    def _on_champ_select_ended(self) -> None:
        if self.draft_tool_dialog and self.draft_tool_dialog.isVisible():
            self.draft_tool_dialog._set_lcu_managed_controls(False)
            # El draft ha terminado: se cierra para poder ver el panel principal.
            self.draft_tool_dialog.close()
        # El draft ha terminado; cuando la pantalla de carga acabe y la partida
        # arranque (primer snapshot de la API local) el panel irá solo a
        # "Partida en vivo" (ver show_game).
        self.pending_live_navigation = True

    def navigate_to_live_page(self) -> None:
        """Coloca el panel principal en la pestaña "Partida en vivo"."""
        self.pages.setCurrentIndex(self.LIVE_PAGE_INDEX)
        if hasattr(self, "live_button"):
            self.live_button.setChecked(True)

    def closeEvent(self, event) -> None:
        self.poll_timer.stop()
        self.tab_hotkey.stop()
        self.overlay.close()

        if self.recording_service.is_recording:
            live_session = self.live_match_tracker.get_live_session()
            self.recording_service.stop(
                reason="app_close",
                session=live_session,
            )
            self.recording_service.wait_for_stop(4000)

            if self.recording_service.is_recording:
                self.recording_service.abort()
                self.recording_service.wait_for_stop(3000)

        if hasattr(self, "champ_select_worker") and self.champ_select_worker.isRunning():
            self.champ_select_worker.stop()
            self.champ_select_worker.quit()
            self.champ_select_worker.wait(2000)

        if self.worker_thread.isRunning():
            self.worker_thread.quit()

            if not self.worker_thread.wait(5000):
                self.worker_thread.terminate()
                self.worker_thread.wait(2000)

        if self.history_thread.isRunning():
            self.history_thread.quit()

            if not self.history_thread.wait(5000):
                self.history_thread.terminate()
                self.history_thread.wait(2000)

        if self.postgame_sync_thread.isRunning():
            self.postgame_sync_thread.quit()

        if not self.postgame_sync_thread.wait(5000):
            self.postgame_sync_thread.terminate()
            self.postgame_sync_thread.wait(2000)
            
        event.accept()
