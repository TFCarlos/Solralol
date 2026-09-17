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
from app.ui.local_analysis_dialog import LocalAnalysisDialog

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

        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(14)

        champion = session.get(
            "champion_name",
            "Desconocido",
        )

        champ_icon = QLabel()
        champ_icon.setFixedSize(44, 44)
        champ_icon.setObjectName("savedGameChampIcon")
        if champion and champion != "Desconocido" and hasattr(self, "data_dragon_assets"):
            icon_url = self.data_dragon_assets.champion_url(champion)
            self.data_dragon_assets.set_label_image(
                champ_icon, icon_url, f"champ:{champion}", 44
            )
        layout.addWidget(champ_icon)

        details = QVBoxLayout()
        details.setSpacing(4)

        game_mode = session.get(
            "game_mode",
            "UNKNOWN",
        )

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel(
            f"{champion} · {game_mode}"
        )
        title.setObjectName("savedGameTitle")
        title_row.addWidget(title)

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
        title_row.addWidget(status)
        title_row.addStretch(1)

        details.addLayout(title_row)

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
            f"📅 {started_at}  ·  ⏱ {duration}  ·  ⚡ {len(events)} eventos registrados"
        )
        subtitle.setObjectName("savedGameDetail")
        details.addWidget(subtitle)

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

        actions = QHBoxLayout()
        actions.setSpacing(8)

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
                actions.addWidget(resync_button)

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
                actions.addWidget(sync_button)

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
        actions.addWidget(open_button)

        delete_button = QPushButton("Eliminar")
        delete_button.setObjectName("dangerButton")
        delete_button.setFixedWidth(90)
        delete_button.setFixedHeight(36)
        if session_id:
            delete_button.clicked.connect(
                lambda checked=False, val=session_id: self.delete_saved_game_session(val)
            )
        actions.addWidget(delete_button)

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
        self.update_api_key_status()

        panel_layout.addWidget(self.api_key_status)

        gemini_title = QLabel("IA Gemini (Google AI Studio)")
        gemini_title.setObjectName("settingsGroupTitle")
        panel_layout.addWidget(gemini_title)

        gemini_description = QLabel(
            "Introduce tu API key de Google AI Studio (Gemini) para habilitar "
            "el re-análisis inteligente de campeones desde la pestaña de edición."
        )
        gemini_description.setObjectName("mutedText")
        gemini_description.setWordWrap(True)
        panel_layout.addWidget(gemini_description)

        self.gemini_api_key_input = QLineEdit()
        self.gemini_api_key_input.setObjectName("apiKeyInput")
        self.gemini_api_key_input.setPlaceholderText("AIzaSy...")
        self.gemini_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_api_key_input.setText(self.gemini_api_key)
        panel_layout.addWidget(self.gemini_api_key_input)

        gemini_actions = QHBoxLayout()
        gemini_actions.setSpacing(10)

        self.save_gemini_api_key_button = QPushButton("Guardar y comprobar Gemini Key")
        self.save_gemini_api_key_button.setObjectName("primaryButton")
        self.save_gemini_api_key_button.clicked.connect(self.save_and_validate_gemini_api_key)
        gemini_actions.addWidget(self.save_gemini_api_key_button)

        self.clear_gemini_api_key_button = QPushButton("Eliminar clave Gemini")
        self.clear_gemini_api_key_button.setObjectName("secondaryButton")
        self.clear_gemini_api_key_button.clicked.connect(self.clear_gemini_api_key)
        gemini_actions.addWidget(self.clear_gemini_api_key_button)

        gemini_actions.addStretch(1)
        panel_layout.addLayout(gemini_actions)

        self.gemini_api_key_status = QLabel()
        self.gemini_api_key_status.setObjectName("apiKeyStatus")
        self.gemini_api_key_status.setWordWrap(True)
        panel_layout.addWidget(self.gemini_api_key_status)

        self.update_gemini_api_key_status()

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
            self.settings_service.save_gemini_api_key(api_key)
            self.gemini_api_key = api_key
            self.gemini_api_key_status.setText(message)
            self.gemini_api_key_status.setProperty("state", "valid")
        else:
            self.settings_service.clear_gemini_api_key()
            self.gemini_api_key = ""
            self.gemini_api_key_status.setText(message)
            self.gemini_api_key_status.setProperty("state", "invalid")

        self.gemini_api_key_status.style().unpolish(self.gemini_api_key_status)
        self.gemini_api_key_status.style().polish(self.gemini_api_key_status)

    def clear_gemini_api_key(self) -> None:
        self.settings_service.clear_gemini_api_key()
        self.gemini_api_key = ""
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
