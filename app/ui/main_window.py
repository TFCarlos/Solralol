from __future__ import annotations
from datetime import datetime

from PySide6.QtCore import (
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
)

from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineUrlRequestInterceptor,
)

from PySide6.QtWebEngineWidgets import (
    QWebEngineView,
)

from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QPainter,
    QRadialGradient,
)

from PySide6.QtWidgets import (
    QButtonGroup,
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

from app.ui.live_match_analysis_dialog import (
    LiveMatchAnalysisDialog,
)

from app.ui.match_inspector_dialog import (
    MatchInspectorDialog,
)
from app.services.data_dragon_assets import (
    DataDragonAssetService,
)
from app.services.settings_service import SettingsService
from app.services.live_data_worker import LiveDataWorker
from app.services.match_history_worker import (
    MatchHistoryWorker,
)

from app.services.postgame_sync_worker import (
    PostgameSyncWorker,
)

from app.ui.champion_card import ChampionCard
from app.ui.overlay_window import OverlayWindow
from app.ui.styles import CONTROL_WINDOW_STYLE


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

class QuietWebEnginePage(QWebEnginePage):
    """Oculta ruido conocido de consola de proveedores web."""

    def javaScriptConsoleMessage(
        self,
        level,
        message: str,
        line_number: int,
        source_id: str,
    ) -> None:
        ignored_messages = (
            "fun-hooks:",
            "Error initializing Facebook integration",
            "firstPartyData",
        )

        if any(
            value in message
            for value in ignored_messages
        ):
            return

        super().javaScriptConsoleMessage(
            level,
            message,
            line_number,
            source_id,
        )

class AdBlockInterceptor(
    QWebEngineUrlRequestInterceptor,
):
    """Bloqueo ligero de anuncios y rastreadores en el visor web."""

    BLOCKED_DOMAINS = (
        "doubleclick.net",
        "googlesyndication.com",
        "googleadservices.com",
        "google-analytics.com",
        "googletagmanager.com",
        "adservice.google.",
        "amazon-adsystem.com",
        "adnxs.com",
        "adsrvr.org",
        "taboola.com",
        "outbrain.com",
        "criteo.com",
        "criteo.net",
        "pubmatic.com",
        "rubiconproject.com",
        "openx.net",
        "moatads.com",
        "scorecardresearch.com",
        "quantserve.com",
        "hotjar.com",
        "facebook.net",
        "connect.facebook.net",
        "adsystem.com",
        "adform.net",
        "advertising.com",
        "adskeeper.co.uk",
        "popads.net",
    )

    BLOCKED_URL_PARTS = (
        "/ads/",
        "/adserver/",
        "/advert/",
        "/advertising/",
        "/banner/",
        "/banners/",
        "/promo/",
        "doubleclick",
        "google_ads",
        "googleads",
        "googlesyndication",
        "adservice",
        "adnxs",
        "taboola",
        "outbrain",
    )

    def interceptRequest(self, info) -> None:
        url = info.requestUrl()
        host = url.host().casefold()
        full_url = url.toString().casefold()

        if any(
            domain in host
            for domain in self.BLOCKED_DOMAINS
        ):
            info.block(True)
            return

        if any(
            value in full_url
            for value in self.BLOCKED_URL_PARTS
        ):
            info.block(True)

class MainWindow(QMainWindow):
    """Ventana única de Solralol."""

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

        self.postgame_sync_in_progress = False
        self.pending_postgame_session_id = ""

        self.current_live_session: dict | None = None
        self.live_analysis_dialog: LiveMatchAnalysisDialog | None = None

        self.overlay = OverlayWindow(item_catalog)

        self.setWindowTitle("Solralol")
        self.resize(1600, 1000)
        self.setMinimumSize(1400, 900)

        self.build_ui()
        self.data_dragon_assets = (
            DataDragonAssetService(self)
        )
        self.setStyleSheet(CONTROL_WINDOW_STYLE)
        self.setup_live_data_worker()
        self.setup_match_history_worker()
        self.setup_postgame_sync_worker()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.request_snapshot)
        self.poll_timer.start(1000)

        self.request_snapshot()

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
        self.pages.addWidget(
            self.create_settings_page()
        )

        root.addWidget(self.pages, 1)

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
            2,
        )
        self.saved_games_button = self.create_nav_button(
            "Partidas guardadas",
            3,
        )
        self.settings_button = self.create_nav_button(
            "Ajustes",
            4,
        )

        self.home_button.setChecked(True)
        self.live_button.setEnabled(False)

        layout.addWidget(self.home_button)
        layout.addWidget(self.analysis_button)
        layout.addWidget(self.live_button)
        layout.addWidget(self.saved_games_button)
        layout.addWidget(self.settings_button)
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

        hero = QFrame()
        hero.setObjectName("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(32, 30, 32, 30)
        hero_layout.setSpacing(8)

        eyebrow = QLabel("ESTADO DEL CLIENTE")
        eyebrow.setObjectName("eyebrow")
        hero_layout.addWidget(eyebrow)

        self.home_title = QLabel("Esperando una partida")
        self.home_title.setObjectName("heroTitle")
        hero_layout.addWidget(self.home_title)

        self.home_text = QLabel(
            "Abre League of Legends y entra en una partida para activar el panel en vivo."
        )
        self.home_text.setObjectName("heroText")
        self.home_text.setWordWrap(True)
        hero_layout.addWidget(self.home_text)
        layout.addWidget(hero)

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
        activity_layout.addWidget(self.history_status)

        self.history_list_layout = QVBoxLayout()
        self.history_list_layout.setSpacing(8)
        activity_layout.addLayout(self.history_list_layout)

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
        page = QWidget()
        page.setObjectName("analysisPage")

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("sectionCard")

        filters_layout = QGridLayout(filters)
        filters_layout.setContentsMargins(18, 16, 18, 16)
        filters_layout.setHorizontalSpacing(10)
        filters_layout.setVerticalSpacing(7)

        champion_label = QLabel("CAMPEÓN")
        champion_label.setObjectName("filterLabel")
        filters_layout.addWidget(champion_label, 0, 0)

        role_label = QLabel("ROL")
        role_label.setObjectName("filterLabel")
        filters_layout.addWidget(role_label, 0, 1)

        rank_label = QLabel("RANGO")
        rank_label.setObjectName("filterLabel")
        filters_layout.addWidget(rank_label, 0, 2)

        region_label = QLabel("REGIÓN")
        region_label.setObjectName("filterLabel")
        filters_layout.addWidget(region_label, 0, 3)

        self.analysis_champion_input = QLineEdit()
        self.analysis_champion_input.setObjectName("analysisInput")
        self.analysis_champion_input.setPlaceholderText(
            "Ej.: Mordekaiser"
        )
        self.analysis_champion_input.setText(
            self.analysis_champion
        )
        self.analysis_champion_input.returnPressed.connect(
            self.load_selected_analysis
        )
        filters_layout.addWidget(
            self.analysis_champion_input,
            1,
            0,
        )

        self.analysis_role_combo = QComboBox()
        self.analysis_role_combo.setObjectName("analysisCombo")

        for label, value in (
            ("Top", "top"),
            ("Jungla", "jungle"),
            ("Mid", "middle"),
            ("ADC", "adc"),
            ("Support", "support"),
        ):
            self.analysis_role_combo.addItem(label, value)

        self.set_combo_value(
            self.analysis_role_combo,
            self.analysis_role,
        )
        filters_layout.addWidget(
            self.analysis_role_combo,
            1,
            1,
        )

        self.analysis_rank_combo = QComboBox()
        self.analysis_rank_combo.setObjectName("analysisCombo")

        for label, value in (
            ("Todos los rangos", "all"),
            ("Hierro+", "iron_plus"),
            ("Bronce+", "bronze_plus"),
            ("Plata+", "silver_plus"),
            ("Oro+", "gold_plus"),
            ("Platino+", "platinum_plus"),
            ("Esmeralda+", "emerald_plus"),
            ("Diamante+", "diamond_plus"),
            ("Master+", "master_plus"),
            ("Grandmaster+", "grandmaster_plus"),
            ("Challenger", "challenger"),
        ):
            self.analysis_rank_combo.addItem(label, value)

        self.set_combo_value(
            self.analysis_rank_combo,
            self.analysis_rank,
        )
        filters_layout.addWidget(
            self.analysis_rank_combo,
            1,
            2,
        )

        self.analysis_region_combo = QComboBox()
        self.analysis_region_combo.setObjectName("analysisCombo")

        for label, value in (
            ("Europa Oeste", "euw1"),
            ("Europa Este", "eun1"),
            ("Norteamérica", "na1"),
            ("Corea", "kr"),
            ("Brasil", "br1"),
            ("Latinoamérica Norte", "la1"),
            ("Latinoamérica Sur", "la2"),
            ("Oceanía", "oc1"),
            ("Japón", "jp1"),
            ("Turquía", "tr1"),
            ("Rusia", "ru"),
        ):
            self.analysis_region_combo.addItem(label, value)

        self.set_combo_value(
            self.analysis_region_combo,
            self.analysis_region,
        )
        filters_layout.addWidget(
            self.analysis_region_combo,
            1,
            3,
        )

        self.load_analysis_button = QPushButton(
            "Cargar análisis"
        )
        self.load_analysis_button.setObjectName("primaryButton")
        self.load_analysis_button.clicked.connect(
            self.load_selected_analysis
        )
        filters_layout.addWidget(
            self.load_analysis_button,
            1,
            4,
        )

        layout.addWidget(filters)

        sources = QFrame()
        sources.setObjectName("analysisSourcesBar")

        sources_layout = QHBoxLayout(sources)
        sources_layout.setContentsMargins(12, 8, 12, 8)
        sources_layout.setSpacing(8)

        source_title = QLabel("FUENTE")
        source_title.setObjectName("filterLabel")
        sources_layout.addWidget(source_title)

        self.lolalytics_button = QPushButton(
            "LoLalytics"
        )
        self.lolalytics_button.setObjectName(
            "analysisSourceButton"
        )
        self.lolalytics_button.setCheckable(True)
        self.lolalytics_button.setChecked(True)
        self.lolalytics_button.clicked.connect(
            lambda: self.select_analysis_source(
                "lolalytics"
            )
        )
        sources_layout.addWidget(self.lolalytics_button)

        self.ugg_button = QPushButton("U.GG")
        self.ugg_button.setObjectName("analysisSourceButton")
        self.ugg_button.setCheckable(True)
        self.ugg_button.clicked.connect(
            lambda: self.select_analysis_source("ugg")
        )
        sources_layout.addWidget(self.ugg_button)

        self.leagueofgraphs_button = QPushButton(
            "LeagueOfGraphs"
        )
        self.leagueofgraphs_button.setObjectName(
            "analysisSourceButton"
        )
        self.leagueofgraphs_button.setCheckable(True)
        self.leagueofgraphs_button.clicked.connect(
            lambda: self.select_analysis_source(
                "leagueofgraphs"
            )
        )
        sources_layout.addWidget(
            self.leagueofgraphs_button
        )

        self.adblock_button = QPushButton(
            "Bloqueador: SÍ"
        )
        self.adblock_button.setObjectName(
            "analysisSourceButton"
        )
        self.adblock_button.setCheckable(True)
        self.adblock_button.setChecked(True)
        self.adblock_button.clicked.connect(
            self.toggle_analysis_adblock
        )

        sources_layout.addWidget(self.adblock_button)

        self.analysis_status = QLabel(
            "LoLalytics seleccionado. Introduce un campeón "
            "y pulsa “Cargar análisis”."
        )
        self.analysis_web_view = QWebEngineView()
        self.analysis_web_view.setObjectName(
            "analysisWebView"
        )

        self.analysis_web_page = QuietWebEnginePage(
            self.analysis_web_view
        )

        self.analysis_web_view.setPage(
            self.analysis_web_page
        )

        self.analysis_adblocker = AdBlockInterceptor(
            self.analysis_web_view
        )

        self.analysis_web_view.page().profile().setUrlRequestInterceptor(
            self.analysis_adblocker
        )
        
        self.analysis_web_view.setMinimumHeight(620)
        self.analysis_web_view.loadStarted.connect(
            self.analysis_load_started
        )
        self.analysis_web_view.loadFinished.connect(
            self.analysis_load_finished
        )
        
        sources_layout.addStretch(1)

        self.reload_analysis_button = QPushButton(
            "Recargar"
        )
        self.reload_analysis_button.setObjectName(
            "analysisSourceButton"
        )
        self.reload_analysis_button.clicked.connect(
            self.analysis_web_view.reload
        )

        sources_layout.addWidget(
            self.reload_analysis_button
        )

        self.open_external_button = QPushButton(
            "Abrir en navegador"
        )
        self.open_external_button.setObjectName(
            "secondaryButton"
        )
        self.open_external_button.clicked.connect(
            self.open_current_analysis_externally
        )
        sources_layout.addWidget(self.open_external_button)

        layout.addWidget(sources)

        layout.addWidget(self.analysis_web_view, 1)

        self.analysis_source = "lolalytics"
        self.current_analysis_url = ""

        if self.analysis_champion:
            QTimer.singleShot(
                0,
                self.load_selected_analysis,
            )
        return page

    def toggle_analysis_adblock(
        self,
        enabled: bool,
    ) -> None:
        if enabled:
            self.analysis_web_view.page().profile().setUrlRequestInterceptor(
                self.analysis_adblocker
            )

            self.adblock_button.setText(
                "Bloqueador: SÍ"
            )

            self.set_analysis_status(
                "Bloqueador activado. Recarga la página "
                "para aplicar los cambios.",
                "success",
            )
        else:
            self.analysis_web_view.page().profile().setUrlRequestInterceptor(
                None
            )

            self.adblock_button.setText(
                "Bloqueador: NO"
            )

            self.set_analysis_status(
                "Bloqueador desactivado.",
                "idle",
            )

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
        self.save_analysis_preferences()

        if QDesktopServices.openUrl(
            QUrl(url)
        ):
            self.set_analysis_status(
                f"Abriendo {source_name}.",
                "success",
            )
        else:
            self.set_analysis_status(
                f"No se pudo abrir {source_name}.",
                "error",
            )

    def open_ugg_analysis(self) -> None:
        values = self.analysis_values()

        if values is None:
            return

        champion, role, _, _ = values

        self.open_analysis_url(
            (
                "https://u.gg/lol/champions/"
                f"{champion}/build/{role}"
            ),
            "U.GG",
        )

    def open_leagueofgraphs_analysis(self) -> None:
        values = self.analysis_values()

        if values is None:
            return

        champion, role, _, _ = values

        url = (
            "https://www.leagueofgraphs.com/"
            "champions/builds/"
            f"{champion}/{role}"
        )

        self.open_analysis_url(
            url,
            "LeagueOfGraphs",
        )

    def select_analysis_source(
        self,
        source: str,
    ) -> None:
        self.analysis_source = source

        self.lolalytics_button.setChecked(
            source == "lolalytics"
        )
        self.ugg_button.setChecked(source == "ugg")
        self.leagueofgraphs_button.setChecked(
            source == "leagueofgraphs"
        )

        source_names = {
            "lolalytics": "LoLalytics",
            "ugg": "U.GG",
            "leagueofgraphs": "LeagueOfGraphs",
        }

        self.set_analysis_status(
            f"{source_names[source]} seleccionado. "
            "Pulsa “Cargar análisis”.",
            "idle",
        )

    def load_selected_analysis(self) -> None:
        values = self.analysis_values()

        if values is None:
            return

        champion, role, rank, region = values

        self.save_analysis_preferences()

        if self.analysis_source == "ugg":
            url = (
                "https://u.gg/lol/champions/"
                f"{champion}/build/{role}"
            )
            source_name = "U.GG"

        elif self.analysis_source == "leagueofgraphs":
            url = (
                "https://www.leagueofgraphs.com/"
                "champions/builds/"
                f"{champion}/{role}"
            )
            source_name = "LeagueOfGraphs"

        else:
            url = (
                "https://lolalytics.com/lol/"
                f"{champion}/build/"
                f"?lane={role}"
            )
            source_name = "LoLalytics"

        self.current_analysis_url = url

        self.set_analysis_status(
            f"Cargando {source_name}…",
            "loading",
        )

        self.analysis_web_view.load(QUrl(url))

    def open_current_analysis_externally(self) -> None:
        if not self.current_analysis_url:
            self.load_selected_analysis()

        if not self.current_analysis_url:
            return

        opened = QDesktopServices.openUrl(
            QUrl(self.current_analysis_url)
        )

        if opened:
            self.set_analysis_status(
                "Abierto en el navegador.",
                "success",
            )
        else:
            self.set_analysis_status(
                "No se pudo abrir el navegador.",
                "error",
            )

    def analysis_load_started(self) -> None:
        self.load_analysis_button.setEnabled(False)

    def analysis_load_finished(
        self,
        success: bool,
    ) -> None:
        self.load_analysis_button.setEnabled(True)

        if success:
            self.set_analysis_status(
                "Análisis cargado en el visor.",
                "success",
            )
        else:
            self.set_analysis_status(
                "El sitio no pudo cargarse en el visor. "
                "Prueba “Abrir en navegador”.",
                "error",
            )


    def open_lolalytics_analysis(self) -> None:
        values = self.analysis_values()

        if values is None:
            return

        champion, role, _, _ = values

        self.open_analysis_url(
            (
                "https://lolalytics.com/lol/"
                f"{champion}/build/?lane={role}"
            ),
            "LoLalytics",
        )

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
        layout.setSpacing(14)

        status_card = QFrame()
        status_card.setObjectName("sectionCard")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(22, 18, 22, 18)
        status_layout.setSpacing(16)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

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

        self.live_time_label = QLabel("—")
        self.live_time_label.setObjectName("liveTime")
        status_layout.addWidget(self.live_time_label)

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
        self.cards_layout.setSpacing(14)

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
        self.saved_games_layout = QVBoxLayout(
            self.saved_games_content
        )
        self.saved_games_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.saved_games_layout.setSpacing(10)

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

    def create_saved_game_row(
        self,
        session: dict,
    ) -> QWidget:
        row = QFrame()
        row.setObjectName("savedGameRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 13, 16, 13)
        layout.setSpacing(10)

        details = QVBoxLayout()
        details.setSpacing(3)

        champion = session.get(
            "champion_name",
            "Desconocido",
        )

        game_mode = session.get(
            "game_mode",
            "UNKNOWN",
        )

        title = QLabel(
            f"{champion} · {game_mode}"
        )

        title.setObjectName("savedGameTitle")
        details.addWidget(title)

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
            f"{started_at} · {duration} · "
            f"{len(events)} eventos registrados"
        )

        subtitle.setObjectName("savedGameDetail")
        details.addWidget(subtitle)

        final_sync = session.get(
            "final_sync",
            {},
        )

        sync_status = final_sync.get(
            "status",
            "live_only",
        )

        sync_texts = {
            "live_only": "Solo telemetría LIVE",
            "pending": "Pendiente de sincronización",
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
        details.addWidget(status)

        sync_message = final_sync.get(
            "message",
            "",
        )

        if sync_message:
            message = QLabel(
                str(sync_message)
            )

            message.setObjectName(
                "savedGameSyncMessage"
            )

            message.setWordWrap(True)
            message.setMaximumWidth(470)

            details.addWidget(message)

        layout.addLayout(details, 1)

        session_id = str(
            session.get(
                "session_id",
                "",
            )
        )

        actions = QVBoxLayout()
        actions.setSpacing(6)

        if session_id:
            if sync_status == "synced":
                resync_button = QPushButton(
                    "Re-sincronizar"
                )

                resync_button.setObjectName(
                    "secondaryButton"
                )

                resync_button.setFixedWidth(108)

                resync_button.setEnabled(
                    not self.postgame_sync_in_progress
                )

                resync_button.clicked.connect(
                    lambda checked=False, value=session_id:
                    self.request_resync_session(
                        value
                    )
                )

                actions.addWidget(resync_button)

            elif sync_status in {
                "live_only",
                "pending",
                "failed",
            }:
                sync_button = QPushButton(
                    "Buscar Riot"
                )

                sync_button.setObjectName(
                    "secondaryButton"
                )

                sync_button.setFixedWidth(108)

                sync_button.setEnabled(
                    not self.postgame_sync_in_progress
                )

                sync_button.clicked.connect(
                    lambda checked=False, value=session_id:
                    self.request_saved_session_sync(
                        value
                    )
                )

                actions.addWidget(sync_button)

        open_button = QPushButton(
            "Abrir análisis"
        )

        open_button.setObjectName(
            "primaryButton"
        )

        open_button.setFixedWidth(108)

        open_button.clicked.connect(
            lambda checked=False, value=session:
            self.open_saved_game_analysis(
                value
            )
        )

        actions.addWidget(open_button)

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

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)

        panel = QFrame()
        panel.setObjectName("sectionCard")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 20, 22, 20)
        panel_layout.setSpacing(16)

        title = QLabel("Ajustes")
        title.setObjectName("sectionTitle")
        panel_layout.addWidget(title)

        api_title = QLabel("Riot API")
        api_title.setObjectName("settingsGroupTitle")
        panel_layout.addWidget(api_title)

        api_description = QLabel(
            "Introduce tu Riot API key para habilitar los datos de "
            "invocador, historial de partidas y estadísticas externas. "
            "La clave se guarda localmente en tu configuración."
        )
        api_description.setObjectName("mutedText")
        api_description.setWordWrap(True)
        panel_layout.addWidget(api_description)

        self.api_key_input = QLineEdit()
        self.api_key_input.setObjectName("apiKeyInput")
        self.api_key_input.setPlaceholderText(
            "RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        )
        self.api_key_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.api_key_input.setText(self.riot_api_key)
        panel_layout.addWidget(self.api_key_input)

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
        panel_layout.addLayout(api_actions)

        self.api_key_status = QLabel()
        self.api_key_status.setObjectName("apiKeyStatus")
        self.api_key_status.setWordWrap(True)
        panel_layout.addWidget(self.api_key_status)

        self.update_api_key_status()

        self.show_overlay_button = QPushButton("Mostrar overlay")
        self.show_overlay_button.setObjectName("primaryButton")
        self.show_overlay_button.clicked.connect(
            self.toggle_overlay_visibility
        )
        panel_layout.addWidget(self.show_overlay_button)

        self.lock_overlay_button = QPushButton("Bloquear clics: NO")
        self.lock_overlay_button.setObjectName("secondaryButton")
        self.lock_overlay_button.clicked.connect(
            self.toggle_overlay_click_through
        )
        panel_layout.addWidget(self.lock_overlay_button)

        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(10)

        opacity_label = QLabel("Opacidad del overlay")
        opacity_label.setObjectName("settingsLabel")
        opacity_row.addWidget(opacity_label)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(92)
        self.opacity_slider.valueChanged.connect(
            self.change_overlay_opacity
        )
        opacity_row.addWidget(self.opacity_slider, 1)

        self.opacity_value = QLabel("92%")
        self.opacity_value.setObjectName("opacityValue")
        opacity_row.addWidget(self.opacity_value)
        panel_layout.addLayout(opacity_row)

        info = QLabel(
            "Los controles se aplican al overlay inmediatamente. "
            "La lectura usa una frecuencia de un segundo y las tarjetas se regeneran cada diez segundos."
        )
        info.setObjectName("mutedText")
        info.setWordWrap(True)
        panel_layout.addWidget(info)

        layout.addWidget(panel)
        layout.addStretch(1)
        return page

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
            self.settings_service.save_riot_api_key(
                api_key
            )
            self.riot_api_key = api_key

            self.api_key_status.setText(message)
            self.api_key_status.setProperty(
                "state",
                "valid",
            )
        else:
            self.settings_service.clear_riot_api_key()
            self.riot_api_key = ""

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
        self.settings_service.clear_riot_api_key()

        self.riot_api_key = ""
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
            5,
        )


    @Slot(list)
    def receive_match_history(
        self,
        history: list,
    ) -> None:
        self.history_is_loading = False
        self.refresh_history_button.setEnabled(True)

        self.match_history = history
        self.render_match_history()

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

        self.current_live_session = None
        self.live_status.setText("No hay una partida activa.")
        self.live_time_label.setText("—")

        self.overlay.game_label.setText("Esperando partida...")
        self.overlay.player_label.setText("Sin datos de jugador")
        self.overlay.enemy_label.setText("")

        if (
            self.was_in_game
            and self.live_match_tracker.is_tracking
            and not self.live_session_finished
        ):
            completed_session = (
                self.live_match_tracker.finish()
            )

            self.live_session_finished = True

            if isinstance(completed_session, dict):
                self.schedule_postgame_sync(
                    completed_session
                )

            if hasattr(self, "saved_games_layout"):
                self.refresh_saved_games()

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
        self.live_status.setText(
            f"{game_mode} · {champion} · "
            f"{len(snapshot.get('all_players', []))} jugadores"
        )
        self.live_time_label.setText(
            f"{minutes:02d}:{seconds:02d}"
        )

        self.overlay.update_data(
            game_time,
            local_player,
            snapshot.get("enemies", []),
            snapshot.get("local_live_stats", {}),
        )

        if not self.live_match_tracker.is_tracking:
            self.live_match_tracker.start(snapshot)
            self.live_session_finished = False
        else:
            self.live_match_tracker.update(snapshot)

        self.was_in_game = True

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

        if dialog is None:
            return

        try:
            dialog.update_session(session)
        except RuntimeError:
            self.live_analysis_dialog = None


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
            key=lambda player: (
                role_order.get(
                    self.get_player_role(player),
                    99,
                ),
                str(
                    player.get(
                        "championName",
                        "",
                    )
                ),
            ),
        )

    def rebuild_cards(self, snapshot: dict) -> None:
        self.clear_cards()

        all_players = snapshot.get(
            "all_players",
            [],
        )

        order = [
            player
            for player in all_players
            if player.get("team") == "ORDER"
        ]

        chaos = [
            player
            for player in all_players
            if player.get("team") == "CHAOS"
        ]

        order = self.sort_players_by_role(order)
        chaos = self.sort_players_by_role(chaos)

        self.add_team_grid(order, snapshot)
        self.add_team_grid(chaos, snapshot)

    def add_team_grid(
        self,
        players: list[dict],
        snapshot: dict,
    ) -> None:
        grid_container = QWidget()
        grid_container.setObjectName("teamCardsRow")

        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        for column in range(5):
            grid.setColumnStretch(column, 1)

        local_player = snapshot.get(
            "local_player",
            {},
        )

        for index, player in enumerate(players[:5]):
            is_local = (
                player.get("riotId")
                == local_player.get("riotId")
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

        self.cards_layout.addWidget(grid_container)

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

            widget.deleteLater()

    def toggle_overlay_visibility(self) -> None:
        if self.overlay.isVisible():
            self.overlay.hide()
            self.show_overlay_button.setText(
                "Mostrar overlay"
            )
        else:
            self.overlay.show()
            self.overlay.raise_()
            self.show_overlay_button.setText(
                "Ocultar overlay"
            )

    def toggle_overlay_click_through(self) -> None:
        enabled = not self.overlay.click_through
        self.overlay.set_click_through(enabled)

        self.lock_overlay_button.setText(
            "Bloquear clics: SÍ"
            if enabled
            else "Bloquear clics: NO"
        )

    def change_overlay_opacity(self, percent: int) -> None:
        self.overlay.set_overlay_opacity(percent)
        self.opacity_value.setText(
            f"{percent}%"
        )

    def closeEvent(self, event) -> None:
        self.poll_timer.stop()
        self.overlay.close()

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
