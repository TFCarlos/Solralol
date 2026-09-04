from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from math import cos, sin

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.services.item_synergy_calculator_service import ItemSynergyCalculatorService
from app.services.settings_service import SettingsService
from app.services.synergy_recommendation_service import SynergyRecommendationService
from app.ui.champion_ai_worker import ChampionAIWorker
from app.ui.winrate_worker import WinrateUpdateWorker
from data_dragon import get_champion_icon_path, get_item_icon_path, get_rune_icon_path


class RadarWidget(QWidget):
    def __init__(self, values: list[tuple[str, float]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values = values
        self.setMinimumSize(360, 250)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect_center = self.rect().center()
        center = QPointF(float(rect_center.x()), float(rect_center.y()))
        radius = min(self.width(), self.height()) * 0.32
        count = max(1, len(self.values))
        polygon = QPolygonF()
        for index in range(count):
            angle = -1.5708 + index * 6.28318 / count
            polygon.append(
                center
                + QPointF(radius * cos(angle), radius * sin(angle))
            )
        painter.setPen(QColor(70, 120, 180, 160))
        painter.drawPolygon(polygon)
        points = QPolygonF()
        for index, (_, value) in enumerate(self.values):
            angle = -1.5708 + index * 6.28318 / count
            scale = max(0.0, min(1.0, value / 10.0))
            points.append(
                center
                + QPointF(
                    radius * scale * cos(angle),
                    radius * scale * sin(angle),
                )
            )
        painter.setBrush(QColor(39, 199, 143, 80))
        painter.setPen(QColor(77, 231, 165, 230))
        painter.drawPolygon(points)
        painter.setPen(QColor(210, 225, 245))
        for index, (label, _) in enumerate(self.values):
            angle = -1.5708 + index * 6.28318 / count
            point = center + QPointF(
                (radius + 18) * cos(angle),
                (radius + 18) * sin(angle),
            )
            text_width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(int(point.x() - text_width / 2), int(point.y()), label)


class PowerCurveWidget(QWidget):
    def __init__(self, values: list[tuple[str, float]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values = values
        self.setMinimumHeight(220)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(9, 24, 40, 220))
        if not self.values:
            return
        bounds = self.rect().adjusted(38, 28, -22, -38)
        maximum = max(10.0, max(value for _, value in self.values))
        painter.setPen(QColor(38, 72, 98))
        for step in range(0, 11, 2):
            y = bounds.bottom() - int(bounds.height() * step / maximum)
            painter.drawLine(bounds.left(), y, bounds.right(), y)
        points = []
        for index, (_, value) in enumerate(self.values):
            x = bounds.left() + int(bounds.width() * index / max(1, len(self.values) - 1))
            y = bounds.bottom() - int(bounds.height() * value / maximum)
            points.append(QPointF(x, y))
        area = QPolygonF(points + [QPointF(points[-1].x(), bounds.bottom()), QPointF(points[0].x(), bounds.bottom())])
        painter.setBrush(QColor(57, 188, 218, 45))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(area)
        painter.setPen(QColor(57, 188, 218))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))
        for index, (label, value) in enumerate(self.values):
            point = points[index]
            painter.setBrush(QColor(57, 188, 218))
            painter.drawEllipse(point, 4, 4)
            painter.setPen(QColor(217, 174, 79))
            painter.drawText(int(point.x() - 8), int(point.y() - 10), str(int(value)))
            painter.setPen(QColor(180, 204, 225))
            painter.drawText(int(point.x() - 24), bounds.bottom() + 22, label)


class BarWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[tuple[str, float, str]] = []
        self.setMinimumHeight(112)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(9, 24, 40, 220))
        maximum = max((value for _, value, _ in self.values), default=1.0)
        width = max(1, self.width() // max(1, len(self.values)))
        for index, entry in enumerate(self.values):
            label, value, item_id = entry
            x = index * width + 8
            icon_path = get_item_icon_path(item_id, self.item_catalog, "16.17.1") if hasattr(self, "item_catalog") else None
            if icon_path and icon_path.exists():
                pixmap = QPixmap(str(icon_path))
                painter.drawPixmap(x, 10, pixmap.scaled(46, 46, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            painter.setPen(QColor(217, 174, 79))
            painter.drawText(x + 52, 27, f"{value:.1f}")
            painter.setPen(QColor(220, 232, 246))
            painter.drawText(x, 78, label[:18])
            painter.setPen(QColor(57, 188, 218))
            painter.drawRect(x + 52, 38, max(8, int((width - 66) * value / maximum)), 5)


class HeatmapWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[tuple[str, float]] = []
        self.setMinimumHeight(90)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        width = max(1, self.width() // max(1, len(self.values)))
        for index, (label, value) in enumerate(self.values):
            painter.setBrush(QColor(35, min(235, 100 + int(value * 135)), 125, 220))
            painter.drawRect(index * width + 2, 10, width - 5, 52)
            painter.setPen(QColor(240, 248, 255))
            painter.drawText(index * width + 6, 42, f"{label[:8]} {value:.0%}")


class LocalAnalysisDialog(QDialog):
    ITEM_NAME_ALIASES = {
        "abyssal mask": "Máscara abisal",
        "ardent censer": "Incensario ardiente",
        "black cleaver": "Cuchilla negra",
        "blade of the ruined king": "Hoja del rey arruinado",
        "botrk": "Hoja del rey arruinado",
        "bork": "Hoja del rey arruinado",
        "death's dance": "Baile de la muerte",
        "danza de la muerte": "Baile de la muerte",
        "duskblade": "Filoscuro de Draktharr",
        "duskblade of draktharr": "Filoscuro de Draktharr",
        "eclipse": "Eclipse",
        "essence reaver": "Segador de esencia",
        "everfrost": "Escarcha eterna",
        "glaciar eterno": "Escarcha eterna",
        "frostfire gauntlet": "Guantelete de hielo",
        "galeforce": "Viento huracanado",
        "fuerza del viento": "Viento huracanado",
        "guinsoo's rageblade": "Hoja de furia de Guinsoo",
        "rageblade": "Hoja de furia de Guinsoo",
        "furia de guinsoo": "Hoja de furia de Guinsoo",
        "heartsteel": "Corazón de acero",
        "hextech rocketbelt": "Cintomisil hextech",
        "cinturón cohete hextech": "Cintomisil hextech",
        "iceborn gauntlet": "Guantelete de hielo",
        "immortal shieldbow": "Arcoescudo inmortal",
        "infinity edge": "Filo infinito",
        "ie": "Filo infinito",
        "knight's vow": "Promesa de caballero",
        "kraken slayer": "Verdugo de krakens",
        "liandry's torment": "Tormento de Liandry",
        "locket of the iron solari": "Medallón de los Solari de hierro",
        "luden's companion": "Eco de Luden",
        "luden's tempest": "Eco de Luden",
        "luden's echo": "Eco de Luden",
        "compañero de luden": "Eco de Luden",
        "manamune": "Manamune",
        "moonstone renewer": "Renovación de piedra lunar",
        "nashor's tooth": "Diente de Nashor",
        "navori quickblades": "Filofugaz de Navori",
        "navori flickerblade": "Filofugaz de Navori",
        "hoja de navori": "Filofugaz de Navori",
        "rabadon's deathcap": "Sombrero mortal de Rabadon",
        "rapid firecannon": "Cañón de fuego rápido",
        "redemption": "Redención",
        "riftmaker": "Creagrietas",
        "creación de grietas": "Creagrietas",
        "runaan's hurricane": "Huracán de Runaan",
        "rylai's crystal scepter": "Cetro de cristal de Rylai",
        "rylai": "Cetro de cristal de Rylai",
        "shadowflame": "Llamasombría",
        "shurelya's battlesong": "Canción de batalla de Shurelya",
        "statikk shiv": "Puñal de Statikk",
        "estatikk": "Puñal de Statikk",
        "sterak's gage": "Calibrador de Sterak",
        "sterak": "Calibrador de Sterak",
        "stormrazor": "Navaja de asalto",
        "navaja de tormenta": "Navaja de asalto",
        "stridebreaker": "Cortasendas",
        "rompeavances": "Cortasendas",
        "sundered sky": "Firmamento desgarrado",
        "sunfire aegis": "Égida de fuego solar",
        "thornmail": "Malla de espinas",
        "titanic hydra": "Hidra titánica",
        "trinity force": "Fuerza de trinidad",
        "umbral glaive": "Guja sombría",
        "alabarda sombría": "Guja sombría",
        "youmuu's ghostblade": "Filo fantasmal de Youmuu",
        "espada fantasmal de youmuu": "Filo fantasmal de Youmuu",
        "zeke's convergence": "Convergencia de Zeke",
        "zhonya's hourglass": "Reloj de arena de Zhonya",
    }
    def __init__(self, parent: QWidget | None = None, version: str | None = None, item_catalog: dict | None = None) -> None:
        super().__init__(parent)
        self.version = version or "16.17.1"
        self.setWindowTitle("Análisis local · SolraLoL")
        self.resize(1100, 760)
        self.champions_path = Path(__file__).parents[2] / "data" / "champions_strict.json"
        self.items_path = Path(__file__).parents[2] / "data" / "legendary_items_strict.json"
        self.catalog_path = Path(__file__).parents[2] / "data" / "items.json"
        self.champions = self._load(self.champions_path)
        self.items = self._load(self.items_path)
        raw_catalog = item_catalog if (item_catalog and isinstance(item_catalog, dict)) else self._load(self.catalog_path)
        if not raw_catalog:
            from data_dragon import load_item_catalog
            self.version, loaded_items = load_item_catalog()
            self.item_catalog = {"version": self.version, "items": loaded_items}
        elif "items" in raw_catalog and isinstance(raw_catalog["items"], dict):
            self.item_catalog = raw_catalog
        else:
            self.item_catalog = {"version": self.version, "items": raw_catalog}
        self.service = SynergyRecommendationService()
        self._build_ui()
        self._apply_style()
        self._select_champion(0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        tabs = QTabWidget()
        analysis = QWidget()
        analysis.setObjectName("localAnalysisView")
        analysis_layout = QVBoxLayout(analysis)
        analysis_layout.setContentsMargins(0, 10, 0, 0)
        analysis_layout.setSpacing(12)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.champion_combo = QComboBox()
        self.champion_combo.setMinimumWidth(210)
        self.champion_combo.addItems([entry.get("character", "") for entry in self.champions])
        self.champion_combo.currentIndexChanged.connect(self._select_champion)
        champion_caption = QLabel("CAMPEÓN")
        champion_caption.setObjectName("localCaption")
        style_caption = QLabel("ESTILO DEL CAMPEÓN")
        style_caption.setObjectName("localCaption")
        controls.addWidget(champion_caption)
        controls.addWidget(self.champion_combo)
        controls.addSpacing(10)
        controls.addWidget(style_caption)
        self.style_value = QLabel("-")
        self.style_value.setObjectName("localStyleValue")
        controls.addWidget(self.style_value)
        controls.addStretch(1)
        self.winrate_progress_label = QLabel("")
        self.winrate_progress_label.setObjectName("winrateProgressLabel")
        self.winrate_progress_label.setVisible(False)
        self.winrate_progress_bar = QProgressBar()
        self.winrate_progress_bar.setObjectName("winrateProgressBar")
        self.winrate_progress_bar.setRange(0, len(self.champions))
        self.winrate_progress_bar.setValue(0)
        self.winrate_progress_bar.setFixedWidth(130)
        self.winrate_progress_bar.setFixedHeight(20)
        self.winrate_progress_bar.setTextVisible(False)
        self.winrate_progress_bar.setVisible(False)
        self.update_single_champ_btn = QPushButton("Actualizar campeón")
        self.update_single_champ_btn.setObjectName("secondaryButton")
        self.update_single_champ_btn.setToolTip("Actualizar winrates de matchups únicamente del campeón seleccionado")
        self.update_single_champ_btn.clicked.connect(self._start_single_champion_winrate_update)
        self.update_winrates_btn = QPushButton("Actualizar todos")
        self.update_winrates_btn.setObjectName("updateWinratesBtn")
        self.update_winrates_btn.setToolTip("Actualizar winrates de matchups para todos los campeones usando Riot Match V5 API")
        self.update_winrates_btn.clicked.connect(self._start_all_champions_winrate_update)
        controls.addWidget(self.winrate_progress_label)
        controls.addWidget(self.winrate_progress_bar)
        controls.addWidget(self.update_single_champ_btn)
        controls.addWidget(self.update_winrates_btn)
        analysis_layout.addLayout(controls)

        self.champion_banner = self._create_champion_banner()
        analysis_layout.addWidget(self.champion_banner)

        insight_row = QHBoxLayout()
        insight_row.setSpacing(10)
        self.counter_panel = self._insight_panel("COUNTERS", "Sin counters configurados.")
        self.advice_panel = self._insight_panel("CONSEJO DE PARTIDA", "Selecciona un campeón para ver el plan.")
        insight_row.addWidget(self.counter_panel, 1)
        insight_row.addWidget(self.advice_panel, 1)
        analysis_layout.addLayout(insight_row)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.radar = RadarWidget([])
        self.radar.setObjectName("radarPanel")
        charts_row.addWidget(self.radar, 1)
        self.power_curve = PowerCurveWidget([])
        self.power_curve.setObjectName("powerCurvePanel")
        charts_row.addWidget(self.power_curve, 1)
        analysis_layout.addLayout(charts_row, 1)

        self.rune_panel = self._create_rune_panel()
        analysis_layout.addWidget(self.rune_panel)

        self.core_title = QLabel("CORE ITEMS / POWER SPIKE")
        self.core_title.setObjectName("localSectionTitle")
        analysis_layout.addWidget(self.core_title)
        self.core_items_row = QHBoxLayout()
        self.core_items_row.setSpacing(10)
        analysis_layout.addLayout(self.core_items_row)

        secondary_charts = QHBoxLayout()
        secondary_charts.setSpacing(10)
        affinity_title = QLabel("AFINIDAD DE OBJETOS")
        affinity_title.setObjectName("localSectionTitle")
        affinity_column = QVBoxLayout()
        affinity_column.addWidget(affinity_title)
        self.bar = BarWidget()
        self.bar.item_catalog = self._catalog_items().get("items", {})
        self.bar.setObjectName("barPanel")
        affinity_column.addWidget(self.bar)
        secondary_charts.addLayout(affinity_column, 1)
        matchup_title = QLabel("MATCHUPS CONFIGURADOS (COUNTERS / VENTAJAS)")
        matchup_title.setObjectName("localSectionTitle")
        matchup_column = QVBoxLayout()
        matchup_column.addWidget(matchup_title)
        
        self.matchups_panel = QFrame()
        self.matchups_panel.setObjectName("localMatchupsPanel")
        self.matchups_panel_layout = QHBoxLayout(self.matchups_panel)
        self.matchups_panel_layout.setContentsMargins(10, 8, 10, 8)
        self.matchups_panel_layout.setSpacing(12)

        # Columna de Counters (3)
        self.counters_col = QVBoxLayout()
        self.counters_col.setSpacing(5)
        counters_hdr = QLabel("COUNTERS (DESVENTAJA)")
        counters_hdr.setObjectName("matchupCountersHeader")
        self.counters_col.addWidget(counters_hdr)
        self.counters_cards_layout = QVBoxLayout()
        self.counters_cards_layout.setSpacing(5)
        self.counters_col.addLayout(self.counters_cards_layout)
        self.counters_col.addStretch(1)

        # Columna de Bueno Contra (3)
        self.good_col = QVBoxLayout()
        self.good_col.setSpacing(5)
        good_hdr = QLabel("BUENO CONTRA (VENTAJA)")
        good_hdr.setObjectName("matchupGoodHeader")
        self.good_col.addWidget(good_hdr)
        self.good_cards_layout = QVBoxLayout()
        self.good_cards_layout.setSpacing(5)
        self.good_col.addLayout(self.good_cards_layout)
        self.good_col.addStretch(1)

        self.matchups_panel_layout.addLayout(self.counters_col, 1)
        self.matchups_panel_layout.addLayout(self.good_col, 1)

        matchup_column.addWidget(self.matchups_panel, 1)
        self.matchup_status = QLabel("Winrates calculados según el rol del campeón.")
        self.matchup_status.setObjectName("localMuted")
        matchup_column.addWidget(self.matchup_status)
        secondary_charts.addLayout(matchup_column, 1)
        analysis_layout.addLayout(secondary_charts)

        recommendations_title = QLabel("LISTA DE ITEMS")
        recommendations_title.setObjectName("localSectionTitle")
        analysis_layout.addWidget(recommendations_title)
        self.item_table = QTableWidget(0, 3)
        self.item_table.setObjectName("recommendationTable")
        self.item_table.setHorizontalHeaderLabels(["Objeto", "Afinidad", "Motivo / counter"])
        self.item_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.item_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.item_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.item_table.verticalHeader().setDefaultSectionSize(32)
        self.item_table.setWordWrap(False)
        self.item_table.setMinimumHeight(360)
        self.item_table.setSortingEnabled(True)
        analysis_layout.addWidget(self.item_table)
        analysis_layout.addStretch(1)
        analysis_scroll = QScrollArea()
        analysis_scroll.setWidgetResizable(True)
        analysis_scroll.setFrameShape(QFrame.Shape.NoFrame)
        analysis_scroll.setWidget(analysis)
        tabs.addTab(analysis_scroll, "Afinidad y gráficos")

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        self.edit_combo = QComboBox()
        self.edit_combo.addItems([entry.get("character", "") for entry in self.champions])
        self.edit_combo.currentIndexChanged.connect(self._load_editor)
        self.edit_text = QTextEdit()
        champ_buttons_layout = QHBoxLayout()
        champ_buttons_layout.setSpacing(8)
        self.reanalyze_champ_btn = QPushButton("Re-analizar con IA")
        self.reanalyze_champ_btn.setToolTip("Re-analiza los atributos subjetivos de este campeón usando Gemini AI (Google AI Studio)")
        self.reanalyze_champ_btn.clicked.connect(self._reanalyze_champion_with_ai)
        save = QPushButton("Guardar campeón")
        save.clicked.connect(self._save_editor)
        champ_buttons_layout.addWidget(self.reanalyze_champ_btn)
        champ_buttons_layout.addWidget(save)
        editor_layout.addWidget(self.edit_combo)
        editor_layout.addWidget(self.edit_text, 1)
        editor_layout.addLayout(champ_buttons_layout)
        tabs.addTab(editor, "Editar campeones")
        item_editor = QWidget()
        item_layout = QVBoxLayout(item_editor)
        self.item_combo = QComboBox()
        self.item_combo.addItems([entry.get("basic_info", {}).get("name", "") for entry in self.items])
        self.item_combo.currentIndexChanged.connect(self._load_item_editor)
        self.item_text = QTextEdit()
        item_buttons_layout = QHBoxLayout()
        item_buttons_layout.setSpacing(8)
        recalc_item = QPushButton("Recalcular sinergias del objeto")
        recalc_item.setToolTip("Calcula matemáticamente synergy_multipliers y counter_weights de este objeto")
        recalc_item.clicked.connect(self._recalculate_current_item_synergies)
        recalc_all_items = QPushButton("Recalcular todos los objetos")
        recalc_all_items.setToolTip("Recalcula y actualiza matemáticamente las sinergias de todo el catálogo")
        recalc_all_items.clicked.connect(self._recalculate_all_items_synergies)
        save_item = QPushButton("Guardar objeto")
        save_item.clicked.connect(self._save_item_editor)
        item_buttons_layout.addWidget(recalc_item)
        item_buttons_layout.addWidget(recalc_all_items)
        item_buttons_layout.addWidget(save_item)
        item_layout.addWidget(self.item_combo)
        item_layout.addWidget(self.item_text, 1)
        item_layout.addLayout(item_buttons_layout)
        tabs.addTab(item_editor, "Editar objetos")
        root.addWidget(tabs)
        self.status = QLabel()
        self.status.setObjectName("localStatus")
        root.addWidget(self.status)
        self._load_item_editor(0)

    def _create_champion_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("localChampionBanner")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        self.champion_portrait = QLabel()
        self.champion_portrait.setFixedSize(72, 72)
        self.champion_portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.champion_portrait.setObjectName("localChampionPortrait")
        layout.addWidget(self.champion_portrait)
        text = QVBoxLayout()
        self.champion_title = QLabel()
        self.champion_title.setObjectName("localChampionTitle")
        text.addWidget(self.champion_title)
        self.champion_meta = QLabel()
        self.champion_meta.setObjectName("localChampionMeta")
        text.addWidget(self.champion_meta)
        self.rune_summary = QLabel()
        self.rune_summary.setObjectName("localRuneSummary")
        self.rune_summary.setWordWrap(True)
        text.addWidget(self.rune_summary)
        layout.addLayout(text, 1)
        self.champion_badge = QLabel()
        self.champion_badge.setObjectName("localChampionBadge")
        self.champion_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.champion_badge)
        return banner

    def _create_rune_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("localRunePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(6)
        title = QLabel("RUNAS")
        title.setObjectName("localInsightTitle")
        layout.addWidget(title)
        self.rune_pages_layout = QHBoxLayout()
        self.rune_pages_layout.setSpacing(10)
        layout.addLayout(self.rune_pages_layout)
        return panel

    def _render_rune_pages(self, profile: dict[str, Any]) -> None:
        while self.rune_pages_layout.count():
            item = self.rune_pages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        pages = profile.get("common_runes", [])
        if not isinstance(pages, list) or not pages:
            pages = [self._default_rune_page(profile.get("basic_info", {}))]
        for index, page in enumerate(pages):
            if isinstance(page, dict):
                self.rune_pages_layout.addWidget(self._rune_page_card(page, index + 1), 1)

    def _rune_page_card(self, page: dict[str, Any], index: int) -> QFrame:
        card = QFrame()
        card.setObjectName("localRunePage")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(4)
        name = QLabel(str(page.get("name", f"Página {index}")))
        name.setObjectName("localRunePageTitle")
        layout.addWidget(name)
        primary = self._rune_row("PRINCIPAL", page.get("keystone", "Conqueror"), page.get("primary_tree", "Precision"))
        secondary = self._rune_row("SECUNDARIA", page.get("secondary_tree", "Resolve"), "")
        layout.addWidget(primary)
        layout.addWidget(secondary)
        runes = []
        for key in ("slots", "secondary_slots", "shards", "runes"):
            values = page.get(key, [])
            if isinstance(values, list):
                runes.extend(values)
        details = QHBoxLayout()
        details.setSpacing(8)
        values = runes[:10] if runes else ["Adaptive Force", "Attack Speed", "Flat Health"]
        for value in values:
            details.addWidget(self._rune_detail_chip(str(value)))
        details.addStretch(1)
        layout.addLayout(details)
        return card

    @staticmethod
    def _rune_detail_chip(name: str) -> QWidget:
        chip = QWidget()
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        icon = QLabel("•")
        icon.setObjectName("localRuneSmallIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(22, 22)
        path = get_rune_icon_path(name, "16.17.1")
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                icon.setText("")
                icon.setPixmap(pixmap.scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignCenter)
        label = QLabel(name)
        label.setObjectName("localRuneDetails")
        label.setToolTip(name)
        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
        return chip

    def _rune_row(self, caption: str, name: str, tree: str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("R")
        icon.setObjectName("localRuneIcon")
        icon.setFixedSize(24, 24)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = get_rune_icon_path(name, "16.17.1")
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                icon.setText("")
                icon.setPixmap(pixmap.scaled(22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)
        label = QLabel(f"{caption}  {name}" + (f"  ·  {tree}" if tree else ""))
        label.setObjectName("localRuneName")
        layout.addWidget(label)
        layout.addStretch(1)
        return row

    @staticmethod
    def _default_rune_page(basic: dict[str, Any]) -> dict[str, Any]:
        if str(basic.get("damage_type", "AD")) == "AP":
            return {"name": "Página recomendada", "keystone": "Electrocutar", "primary_tree": "Dominación", "secondary_tree": "Inspiration", "runes": ["Impacto repentino", "Colección de globos", "Cazador de tesoros"]}
        return {"name": "Página recomendada", "keystone": "Conquistador", "primary_tree": "Precision", "secondary_tree": "Resolve", "runes": ["Triunfo", "Leyenda: Presteza", "Golpe de gracia"]}

    @staticmethod
    def _rune_chip(mark: str, name: str, tree: str) -> QWidget:
        chip = QWidget()
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        icon = QLabel(mark)
        icon.setObjectName("localRuneIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(28, 28)
        layout.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        rune_name = QLabel(name)
        rune_name.setObjectName("localRuneName")
        text.addWidget(rune_name)
        rune_tree = QLabel(tree)
        rune_tree.setObjectName("localRuneTree")
        text.addWidget(rune_tree)
        layout.addLayout(text)
        chip.name_label = rune_name
        chip.tree_label = rune_tree
        chip.icon_label = icon
        return chip

    @staticmethod
    def _insight_panel(title: str, text: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("localInsightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 11, 14, 11)
        heading = QLabel(title)
        heading.setObjectName("localInsightTitle")
        layout.addWidget(heading)
        content = QLabel(text)
        content.setObjectName("localInsightText")
        content.setWordWrap(True)
        layout.addWidget(content)
        panel.content = content
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QDialog { background: #07111f; color: #e8f0ff; }
            QFrame#localAnalysisHeader {
                background: qlineargradient(x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #102b46, stop: 1 #0b192b);
                border: 1px solid #2b5578; border-radius: 12px;
            }
            QLabel#localAnalysisTitle { color: #d9ae4f; font-size: 20px; font-weight: 800; letter-spacing: 1px; }
            QLabel#localAnalysisSubtitle, QLabel#localMuted { color: #91a9c4; font-size: 12px; }
            QFrame#localChampionBanner { background: #0d2237; border: 1px solid #386483; border-radius: 10px; }
            QLabel#localChampionPortrait { background: #071525; border: 2px solid #d9ae4f; border-radius: 8px; }
            QLabel#localChampionTitle { color: #f1f6ff; font-size: 18px; font-weight: 800; }
            QLabel#localChampionMeta { color: #9fc1d9; font-size: 11px; }
            QFrame#localRunePanel { background: #0b1b2c; border: 1px solid #234663; border-radius: 8px; }
            QLabel#localRuneSummary, QLabel#localRuneShards { color: #77d8b0; font-size: 11px; font-weight: 700; }
            QLabel#localRuneIcon { color: #f6d477; background: #342611; border: 1px solid #d9ae4f; border-radius: 14px; font-size: 9px; font-weight: 800; }
            QLabel#localRuneName { color: #e8f0ff; font-size: 11px; font-weight: 700; }
            QLabel#localRuneTree { color: #8eaac5; font-size: 9px; }
            QLabel#localRuneSmallIcon { color: #f6d477; background: #172a3d; border: 1px solid #315b7e; border-radius: 11px; font-size: 14px; }
            QLabel#localRuneDetails { color: #9db7cf; font-size: 8px; }
            QLabel#localChampionBadge { color: #152033; background: #d9ae4f; border-radius: 5px; padding: 8px 10px; font-size: 10px; font-weight: 800; }
            QLabel#localCaption, QLabel#localSectionTitle, QLabel#localInsightTitle { color: #d9ae4f; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
            QLabel#localStyleValue { color: #77d8b0; font-size: 12px; font-weight: 700; padding: 5px 8px; background: #102d35; border: 1px solid #2d756d; border-radius: 5px; }
            QLabel#localSectionTitle { margin-top: 4px; }
            QFrame#localInsightPanel, QWidget#radarPanel, QWidget#barPanel, QFrame#localMatchupsPanel {
                background: rgba(12, 28, 47, 220); border: 1px solid #234663; border-radius: 9px;
            }
            QLabel#matchupCountersHeader { color: #ff7675; font-size: 10px; font-weight: 800; letter-spacing: 1px; padding-bottom: 2px; }
            QLabel#matchupGoodHeader { color: #55efc4; font-size: 10px; font-weight: 800; letter-spacing: 1px; padding-bottom: 2px; }
            QFrame#matchupCardCounter { background: #1a131b; border: 1px solid #5a2835; border-radius: 6px; }
            QFrame#matchupCardCounter:hover { background: #261625; border-color: #923a4f; }
            QFrame#matchupCardGood { background: #0c201e; border: 1px solid #1a5347; border-radius: 6px; }
            QFrame#matchupCardGood:hover { background: #112d2a; border-color: #27816f; }
            QLabel#matchupChampIcon { border-radius: 4px; border: 1px solid #234663; }
            QLabel#matchupChampName { color: #f0f5ff; font-size: 11px; font-weight: 700; }
            QLabel#matchupWrCounter { color: #ff7675; background: #3d1b22; border: 1px solid #7a2b38; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 800; }
            QLabel#matchupWrGood { color: #55efc4; background: #0f3026; border: 1px solid #1f684e; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 800; }
            QFrame#localCoreItem, QFrame#localCoreItemMissing { background: #122b3b; border: 1px solid #b18b3f; border-radius: 7px; }
            QFrame#localCoreItemMissing { border-color: #315b7e; }
            QLabel#localCoreItemName { color: #f0f5ff; font-size: 11px; font-weight: 700; }
            QLabel#localCoreItemScore { color: #77d8b0; font-size: 10px; }
            QLabel#localInsightText { color: #dce9f8; font-size: 12px; }
            QComboBox, QTableWidget, QTextEdit {
                background: #0c1c2e; color: #e8f0ff; border: 1px solid #315b7e; border-radius: 6px; padding: 6px;
            }
            QComboBox:focus, QTextEdit:focus { border-color: #d9ae4f; }
            QTableWidget { gridline-color: #193750; alternate-background-color: #10253b; }
            QHeaderView::section { background: #153452; color: #d9ae4f; border: 0; padding: 7px; font-weight: 700; }
            QTabWidget::pane { border: 1px solid #234663; background: #091827; }
            QTabBar::tab { background: #102238; color: #9db3ca; padding: 9px 16px; border: 1px solid #234663; }
            QTabBar::tab:selected { background: #d9ae4f; color: #101a27; font-weight: 700; }
            QPushButton { background: #d9ae4f; color: #101a27; border: 1px solid #f0cc70; border-radius: 6px; padding: 7px 12px; font-weight: 700; }
            QPushButton:hover { background: #ebc56a; }
            QPushButton#updateWinratesBtn { background: #d9ae4f; color: #101a27; border: 1px solid #f0cc70; border-radius: 6px; padding: 6px 12px; font-weight: 700; font-size: 11px; }
            QPushButton#updateWinratesBtn:hover { background: #ebc56a; }
            QPushButton#updateWinratesBtn:disabled { background: #203a52; color: #6f869e; border-color: #2a4c6c; }
            QLabel#winrateProgressLabel { color: #d9ae4f; font-size: 11px; font-weight: 700; padding-right: 4px; }
            QProgressBar#winrateProgressBar { border: 1px solid #234663; border-radius: 4px; background: #091827; }
            QProgressBar#winrateProgressBar::chunk { background-color: #d9ae4f; border-radius: 3px; }
            QLabel#localStatus { color: #7edfc0; padding-top: 3px; }
        """)

    def _select_champion(self, index: int) -> None:
        if self.champion_combo.currentIndex() != index:
            self.champion_combo.blockSignals(True)
            self.champion_combo.setCurrentIndex(max(0, index))
            self.champion_combo.blockSignals(False)
        self.edit_combo.blockSignals(True)
        self.edit_combo.setCurrentIndex(max(0, index))
        self.edit_combo.blockSignals(False)
        self._refresh_analysis()

    def _refresh_analysis(self) -> None:
        index = self.champion_combo.currentIndex()
        if index < 0 or index >= len(self.champions): return
        profile = self.champions[index]
        champion = str(profile.get("character", "Campeón"))
        basic = profile.get("basic_info", {})
        champion_data = self._champion_data(champion)
        title = champion_data.get("title", "Campeón adaptable")
        icon_path = get_champion_icon_path(champion, "16.17.1")
        self.champion_portrait.clear()
        if icon_path and icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                self.champion_portrait.setPixmap(pixmap.scaled(68, 68, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.champion_title.setText(f"{champion}  ·  {title}")
        self.champion_meta.setText(
            f"{basic.get('play_style', 'Adaptable')}  ·  {basic.get('damage_type', 'Híbrido')}  ·  "
            f"Dificultad {basic.get('difficulty_floor', '?')}-{basic.get('difficulty_ceiling', '?')}/10"
        )
        rune_primary, rune_secondary = self._recommended_runes(basic)
        self.rune_summary.setText(f"RUNAS RECOMENDADAS   {rune_primary}  /  {rune_secondary}")
        self._render_rune_pages(profile)
        champion_style = str(basic.get("play_style", "Adaptable"))
        self.style_value.setText(champion_style)
        self.champion_badge.setText(champion_style.upper())
        values = self._radar_values(profile)
        self.radar.values = values
        self.radar.update()
        curve = profile.get("power_curve_and_scaling", {})
        curve_labels = (("Early", "early_game"), ("Mid", "mid_game"), ("Late", "late_game"))
        self.power_curve.values = [(label, float(curve.get(key, 0))) for label, key in curve_labels]
        self.power_curve.update()
        matchups = profile.get("matchups", {})
        counters = matchups.get("counters", []) if isinstance(matchups, dict) else []
        counter_labels = []
        for entry in counters[:3]:
            if isinstance(entry, dict):
                c_name = str(entry.get("champion", "?"))
                wr = entry.get("win_rate")
                counter_labels.append(f"{c_name} ({wr:.1%})" if wr is not None else c_name)
            else:
                counter_labels.append(str(entry))
        self.counter_panel.content.setText(
            ", ".join(counter_labels)
            if counter_labels
            else "Sin counters configurados para este campeón."
        )
        strategy = profile.get("strategy_and_macro", {})
        advice = strategy.get("about", "Ajusta la build a la composición enemiga.") if isinstance(strategy, dict) else "Ajusta la build a la composición enemiga."
        self.advice_panel.content.setText(str(advice))
        ranked = self.service.rank_items(
            profile,
            champion_style,
            self._recommendation_items_by_id(),
            [],
            30,
        )
        self._render_core_items(profile, champion_style)
        self.bar.values = [(result.name, result.score, result.item_id) for result in ranked[:8]]
        self.bar.update()
        self._render_matchups_panel(profile)
        self.item_table.setRowCount(len(ranked))
        self.item_table.setSortingEnabled(False)
        for row, result in enumerate(ranked):
            self.item_table.setCellWidget(row, 0, self._item_cell(result.name, result.item_id))
            self.item_table.setItem(row, 1, QTableWidgetItem(f"{result.score:.1f}"))
            self.item_table.setItem(row, 2, QTableWidgetItem("; ".join(result.reasons)))
        self.item_table.setSortingEnabled(True)

    @staticmethod
    def _champion_data(champion: str) -> dict[str, Any]:
        try:
            from data_dragon import get_champion_data
            return get_champion_data(champion, "16.17.1")
        except Exception:
            return {}

    @staticmethod
    def _recommended_runes(basic: dict[str, Any]) -> tuple[str, str]:
        damage = str(basic.get("damage_type", "AD"))
        if damage == "AP":
            return "Electrocutar / Dominación", "Inspiration"
        if damage == "True":
            return "Conquistador / Precision", "Resolve"
        return "Conquistador / Precision", "Resolve"

    @staticmethod
    def _rune_parts(value: str) -> tuple[str, str]:
        parts = [part.strip() for part in value.split("/", 1)]
        return parts[0], parts[1] if len(parts) > 1 else "Runa secundaria"

    @staticmethod
    def _radar_values(profile: dict[str, Any]) -> list[tuple[str, float]]:
        sections = (
            ("combat_attributes", {"attack_damage": "Daño", "attack_power": "Poder", "critic": "Crítico", "lethality": "Letalidad"}),
            ("map_and_control", {"mobility": "Movilidad", "wave_clear": "Utilidad", "team_fight": "Alcance", "crowd_control": "Control"}),
            ("resistances_and_survivability", {"survivability_overall": "Supervivencia", "armor": "Resistencia", "magic_resistance": "Defensa mágica"}),
        )
        result = []
        for section_name, aliases in sections:
            section = profile.get(section_name, {})
            if not isinstance(section, dict):
                continue
            for key, label in aliases.items():
                if key in section:
                    result.append((label, float(section[key])))
        return result[:9]

    def _item_cell(self, name: str, item_id: str) -> QWidget:
        cell = QWidget()
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(6)
        icon = QLabel()
        icon.setFixedSize(28, 28)
        icon.setObjectName("localItemIcon")
        if item_id:
            path = get_item_icon_path(item_id, self._catalog_items().get("items", {}), "16.17.1")
            if path and path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    icon.setPixmap(pixmap.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)
        label = QLabel(name)
        label.setToolTip(name)
        layout.addWidget(label, 1)
        return cell

    def _catalog_items(self) -> dict[str, Any]:
        if isinstance(self.item_catalog, dict):
            if "items" in self.item_catalog and isinstance(self.item_catalog["items"], dict):
                return self.item_catalog
            return {"version": getattr(self, "version", "16.17.1"), "items": self.item_catalog}
        return {"version": getattr(self, "version", "16.17.1"), "items": {}}

    def _recommendation_items_by_id(self) -> dict[str, dict[str, Any]]:
        catalog = self._catalog_items().get("items", {})
        result: dict[str, dict[str, Any]] = {}
        for item in self.items:
            item_id = str(item.get("id") or item.get("basic_info", {}).get("id") or "")
            if not item_id or item_id not in catalog:
                basic = item.get("basic_info", {})
                name = str(basic.get("name", item.get("item", "")))
                item_id = self._catalog_id_for_name(name, catalog)
                if not item_id and "name_en" in basic:
                    item_id = self._catalog_id_for_name(basic["name_en"], catalog)
            if item_id:
                result[item_id] = item

        # Asegurar que todos los objetos terminados o legendarios de Data Dragon estén disponibles
        for cid, cat_item in catalog.items():
            if cid not in result and isinstance(cat_item, dict):
                gold = cat_item.get("gold", {})
                cost = int(gold.get("total", 0)) if isinstance(gold, dict) else 0
                if cost >= 2200 and not cat_item.get("into"):
                    display_name = cat_item.get("name_es") or cat_item.get("name") or str(cid)
                    result[cid] = {
                        "id": str(cid),
                        "item": display_name,
                        "name_en": cat_item.get("name_en", display_name),
                        "basic_info": {
                            "id": str(cid),
                            "name": display_name,
                            "name_en": cat_item.get("name_en", display_name),
                            "tier": "Legendary",
                            "gold_cost": cost,
                        },
                        "stats": cat_item.get("stats", {}),
                        "synergy_multipliers": {},
                    }
        return result

    def _catalog_id_for_name(
        self,
        name: str,
        catalog: dict[str, Any],
    ) -> str:
        if not name or not catalog:
            return ""
        name_str = str(name).strip()
        if name_str in catalog:
            return name_str

        wanted = self._normalise_item_name(name_str)
        raw_wanted = name_str.casefold()

        # 1. Coincidencia directa por nombre español o inglés
        for catalog_id, catalog_item in catalog.items():
            if not isinstance(catalog_item, dict):
                continue
            cat_name = self._normalise_item_name(catalog_item.get("name", ""))
            cat_es = self._normalise_item_name(catalog_item.get("name_es", ""))
            cat_en = str(catalog_item.get("name_en", "")).casefold().strip()

            if wanted in (cat_name, cat_es) or raw_wanted in (cat_name, cat_es, cat_en):
                return str(catalog_id)

        # 2. Coincidencia en términos coloquiales (colloq)
        for catalog_id, catalog_item in catalog.items():
            if not isinstance(catalog_item, dict):
                continue
            colloq = str(catalog_item.get("colloq", "")).casefold()
            if wanted and wanted in colloq:
                return str(catalog_id)
            if raw_wanted and raw_wanted in colloq:
                return str(catalog_id)

        return ""

    def _render_core_items(self, profile: dict[str, Any], style_key: str) -> None:
        while self.core_items_row.count():
            item = self.core_items_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        scaling = profile.get("power_curve_and_scaling", {})
        names = scaling.get("power_spike_items", []) if isinstance(scaling, dict) else []
        items_by_id = self._recommendation_items_by_id()
        catalog = self._catalog_items().get("items", {})

        for position, wanted_name in enumerate(names):
            wanted = self._normalise_item_name(wanted_name)
            target_id = self._catalog_id_for_name(wanted_name, catalog)

            match = None
            if target_id and target_id in items_by_id:
                match = (target_id, items_by_id[target_id])
            else:
                match = next(
                    ((item_id, itm) for item_id, itm in items_by_id.items()
                     if self._normalise_item_name(self._item_display_name(itm)) == wanted
                     or str(itm.get("name_en", "")).casefold() == str(wanted_name).casefold()
                     or str(itm.get("basic_info", {}).get("name_en", "")).casefold() == str(wanted_name).casefold()),
                    None,
                )

            # Si no está en items_by_id pero sí en el catálogo de Data Dragon, rescatar del catálogo
            if match is None and target_id and target_id in catalog:
                cat_item = catalog[target_id]
                display_name = cat_item.get("name_es") or cat_item.get("name") or str(wanted_name)
                synth_item = {
                    "id": target_id,
                    "item": display_name,
                    "name_en": cat_item.get("name_en", str(wanted_name)),
                    "basic_info": {
                        "id": target_id,
                        "name": display_name,
                        "name_en": cat_item.get("name_en", str(wanted_name)),
                        "tier": "Legendary",
                        "gold_cost": int(cat_item.get("gold", {}).get("total", 0)),
                    },
                    "stats": cat_item.get("stats", {}),
                    "synergy_multipliers": {},
                }
                match = (target_id, synth_item)

            if match is None:
                self.core_items_row.addWidget(
                    self._missing_core_item_card(str(wanted_name), position + 1),
                    1,
                )
                continue

            item_id, item = match
            recommendation = self.service.score_item(
                profile, style_key, item_id, item, []
            )
            recommendation = self.service._add_power_spike_bonus(
                recommendation,
                {wanted, str(wanted_name).casefold()},
            )
            self.core_items_row.addWidget(
                self._core_item_card(recommendation, position + 1), 1
            )
        self.core_items_row.addStretch(1)

    @staticmethod
    def _missing_core_item_card(name: str, position: int) -> QFrame:
        card = QFrame()
        card.setObjectName("localCoreItemMissing")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 9, 10, 9)
        title = QLabel(f"{position}. {name}")
        title.setObjectName("localCoreItemName")
        title.setWordWrap(True)
        layout.addWidget(title)
        status = QLabel("Sin datos en el catálogo")
        status.setObjectName("localCoreItemScore")
        layout.addWidget(status)
        return card

    def _core_item_card(self, recommendation: Any, position: int) -> QFrame:
        card = QFrame()
        card.setObjectName("localCoreItem")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8, 7, 8, 7)
        icon = QLabel()
        icon.setFixedSize(42, 42)
        version = self._catalog_items().get("version", "16.17.1")
        path = get_item_icon_path(
            recommendation.item_id,
            self._catalog_items().get("items", {}),
            version,
        )
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)
        text = QVBoxLayout()
        name = QLabel(f"{position}. {recommendation.name}")
        name.setObjectName("localCoreItemName")
        name.setToolTip(recommendation.name)
        text.addWidget(name)
        score = QLabel(f"Sinergia {recommendation.score:.1f}")
        score.setObjectName("localCoreItemScore")
        text.addWidget(score)
        layout.addLayout(text, 1)
        return card

    @staticmethod
    def _item_display_name(item: dict[str, Any]) -> str:
        basic = item.get("basic_info", {})
        return str(basic.get("name", item.get("item", ""))) if isinstance(basic, dict) else str(item.get("item", ""))

    @classmethod
    def _normalise_item_name(cls, name: Any) -> str:
        value = str(name).casefold().strip()
        return str(cls.ITEM_NAME_ALIASES.get(value, value)).casefold()

    def _item_id_for_name(self, name: str) -> str:
        catalog = self._catalog_items().get("items", {})
        return self._catalog_id_for_name(name, catalog)

    def _render_matchups_panel(self, profile: dict[str, Any]) -> None:
        """Renderiza las tarjetas de los 3 Counters y los 3 Bueno Contra con sus iconos, winrate en línea y winrate overall."""
        for layout in (self.counters_cards_layout, self.good_cards_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        matchups = profile.get("matchups", {})
        counters = matchups.get("counters", []) if isinstance(matchups, dict) else []
        good_against = matchups.get("good_against", []) if isinstance(matchups, dict) else []

        # 3 Counters (Desventaja)
        for entry in counters[:3]:
            name, wr_lane, wr_overall, tip, lg, og, role = self._extract_matchup_info(entry)
            card = self._create_matchup_card(name, wr_lane, wr_overall, tip, is_counter=True, lane_games=lg, overall_games=og, primary_role=role)
            self.counters_cards_layout.addWidget(card)
        if not counters:
            lbl = QLabel("Sin counters configurados")
            lbl.setObjectName("localMuted")
            self.counters_cards_layout.addWidget(lbl)

        # 3 Bueno Contra (Ventaja)
        for entry in good_against[:3]:
            name, wr_lane, wr_overall, tip, lg, og, role = self._extract_matchup_info(entry)
            card = self._create_matchup_card(name, wr_lane, wr_overall, tip, is_counter=False, lane_games=lg, overall_games=og, primary_role=role)
            self.good_cards_layout.addWidget(card)
        if not good_against:
            lbl = QLabel("Sin ventajas configuradas")
            lbl.setObjectName("localMuted")
            self.good_cards_layout.addWidget(lbl)

        has_data = bool(counters or good_against)
        summary = matchups.get("summary", {}) if isinstance(matchups, dict) else {}
        if isinstance(summary, dict) and summary.get("total_games_analyzed"):
            total_games = summary.get("total_games_analyzed", 0)
            role = summary.get("primary_role", "Mid")
            lane_wr = summary.get("lane_win_rate", 0.50)
            lane_games = summary.get("lane_total_games", 0)
            overall_wr = summary.get("overall_win_rate", 0.50)
            overall_games = summary.get("overall_total_games", total_games)
            self.matchup_status.setText(
                f"Línea [{role.upper()}]: {lane_wr:.1%} en {lane_games:,} Partidas  |  Overall: {overall_wr:.1%} en {overall_games:,} Partidas (Esmeralda+)".replace(",", ".")
            )
        elif has_data:
            self.matchup_status.setText("Winrates diferenciados por Línea Predilecta y Overall (Esmeralda+).")
        else:
            self.matchup_status.setText("Sin winrates configurados para este campeón.")

    @staticmethod
    def _extract_matchup_info(entry: Any) -> tuple[str, float, float, str, int, int, str]:
        if isinstance(entry, dict):
            name = str(entry.get("champion", "?"))
            wr_lane = float(entry.get("win_rate", 0.50) or 0.50)
            wr_overall = float(entry.get("overall_win_rate", entry.get("win_rate", 0.50)) or 0.50)
            tip = str(entry.get("tip", ""))
            lg = int(entry.get("lane_games", entry.get("matchup_games", 0)))
            og = int(entry.get("overall_games", entry.get("matchup_games", 0)))
            role = str(entry.get("primary_role", ""))
            return name, wr_lane, wr_overall, tip, lg, og, role
        return str(entry), 0.50, 0.50, "", 0, 0, ""

    def _create_matchup_card(
        self,
        champion_name: str,
        win_rate_lane: float,
        win_rate_overall: float,
        tip: str,
        is_counter: bool,
        lane_games: int = 0,
        overall_games: int = 0,
        primary_role: str = "",
    ) -> QFrame:
        """Crea una tarjeta estilizada con la imagen del campeón, nombre, winrate de línea y winrate overall."""
        card = QFrame()
        card.setObjectName("matchupCardCounter" if is_counter else "matchupCardGood")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(6, 5, 8, 5)
        layout.setSpacing(8)

        # Icono del campeón
        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setObjectName("matchupChampIcon")
        icon_path = get_champion_icon_path(champion_name, self.version)
        if icon_path and icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)

        # Nombre del campeón y partidas del enfrentamiento
        name_box = QVBoxLayout()
        name_box.setSpacing(1)
        name_lbl = QLabel(champion_name)
        name_lbl.setObjectName("matchupChampName")
        name_box.addWidget(name_lbl)

        games_count_val = lane_games or overall_games
        games_sub = QLabel(f"{games_count_val:,}".replace(",", ".") + " Games" if games_count_val else "Match V5")
        games_sub.setObjectName("localMuted")
        name_box.addWidget(games_sub)
        layout.addLayout(name_box, 1)

        # Contenedor de estadísticas (Línea + Overall)
        stats_layout = QVBoxLayout()
        stats_layout.setSpacing(1)
        stats_layout.setAlignment(Qt.AlignmentFlag.AlignRight)

        lane_badge = QLabel(f"{win_rate_lane:.1%}")
        lane_badge.setObjectName("matchupWrCounter" if is_counter else "matchupWrGood")
        stats_layout.addWidget(lane_badge)

        overall_lbl = QLabel(f"Overall {win_rate_overall:.1%}")
        overall_lbl.setObjectName("localMuted")
        stats_layout.addWidget(overall_lbl)

        layout.addLayout(stats_layout)

        # Tooltip explicativo detallado
        tooltip_text = (
            f"<b>{champion_name}</b><br/>"
            f"<b>Winrate en línea ({primary_role or 'Predilecta'}):</b> {win_rate_lane:.1%}" + (f" ({lane_games:,} partidas)<br/>".replace(",", ".") if lane_games else "<br/>") +
            f"<b>Winrate General (Overall):</b> {win_rate_overall:.1%}" + (f" ({overall_games:,} partidas)<br/>".replace(",", ".") if overall_games else "<br/>") +
            (f"<br/><i>{tip}</i>" if tip else "")
        )
        card.setToolTip(tooltip_text)
        name_lbl.setToolTip(tooltip_text)
        games_sub.setToolTip(tooltip_text)
        lane_badge.setToolTip(tooltip_text)
        overall_lbl.setToolTip(tooltip_text)

        return card

    def _load_editor(self, index: int) -> None:
        if 0 <= index < len(self.champions):
            self.edit_text.setPlainText(json.dumps(self.champions[index], ensure_ascii=False, indent=2))

    def _save_editor(self) -> None:
        try:
            value = json.loads(self.edit_text.toPlainText())
            self._validate(value)
            self.champions[self.edit_combo.currentIndex()] = value
            self.champions_path.write_text(json.dumps(self.champions, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status.setText("Campeón guardado correctamente.")
            self._refresh_analysis()
        except (json.JSONDecodeError, ValueError, OSError) as error:
            self.status.setText(f"No se guardó: {error}")

    def _reanalyze_champion_with_ai(self) -> None:
        """Llama a Gemini AI para re-analizar los atributos subjetivos del campeón seleccionado."""
        try:
            settings = SettingsService().load()
            gemini_key = settings.get("gemini_api_key", "").strip()
            if not gemini_key:
                self.status.setText("No se encontró Gemini API Key. Por favor, configúrala en la pestaña Ajustes.")
                return

            champ_data = json.loads(self.edit_text.toPlainText())
            character_name = champ_data.get("character", champ_data.get("basic_info", {}).get("name", "Campeón"))

            self.reanalyze_champ_btn.setEnabled(False)
            self.status.setText(f"Re-analizando a '{character_name}' con IA (Gemini)... Por favor espera.")

            self._ai_worker = ChampionAIWorker(champ_data, gemini_key, parent=self)
            self._ai_worker.finished_reanalysis.connect(self._on_ai_reanalysis_finished)
            self._ai_worker.error_occurred.connect(self._on_ai_reanalysis_error)
            self._ai_worker.start()
        except (json.JSONDecodeError, ValueError, OSError) as error:
            self.status.setText(f"Error en datos del campeón: {error}")

    def _on_ai_reanalysis_finished(self, updated_data: dict[str, Any]) -> None:
        self.reanalyze_champ_btn.setEnabled(True)
        self.edit_text.setPlainText(json.dumps(updated_data, ensure_ascii=False, indent=2))
        character_name = updated_data.get("character", "Campeón")
        self.status.setText(f"✓ '{character_name}' re-analizado con éxito por IA. Pulsa 'Guardar campeón' para conservar los cambios.")

    def _on_ai_reanalysis_error(self, error_msg: str) -> None:
        self.reanalyze_champ_btn.setEnabled(True)
        self.status.setText(f"Error al re-analizar con IA: {error_msg}")

    def _start_single_champion_winrate_update(self) -> None:
        current_champ = self.champion_combo.currentText()
        self._start_winrate_update(target_champion_name=current_champ)

    def _start_all_champions_winrate_update(self) -> None:
        self._start_winrate_update(target_champion_name="")

    def _start_winrate_update(self, target_champion_name: str = "") -> None:
        """Inicia el proceso de actualización de winrates mediante Riot Match V5."""
        settings_service = SettingsService()
        settings = settings_service.load()
        api_key = settings.get("riot_api_key", "")
        game_name = settings.get("riot_game_name", "")
        tag_line = settings.get("riot_tag_line", "")
        account_region = settings.get("riot_account_region", "europe")
        platform_region = settings.get("riot_platform_region", "euw1")

        self.update_single_champ_btn.setEnabled(False)
        self.update_winrates_btn.setEnabled(False)
        self.winrate_progress_bar.setRange(0, 1 if target_champion_name else len(self.champions))
        self.winrate_progress_bar.setValue(0)
        self.winrate_progress_bar.setVisible(True)
        self.winrate_progress_label.setText("Iniciando...")
        self.winrate_progress_label.setVisible(True)

        if target_champion_name:
            self.status.setText(f"Actualizando winrates de matchups para '{target_champion_name}'...")
        else:
            self.status.setText("Actualizando winrates de matchups para todos los campeones...")

        self._winrate_worker = WinrateUpdateWorker(
            api_key=api_key,
            account_region=account_region,
            platform_region=platform_region,
            game_name=game_name,
            tag_line=tag_line,
            target_champion_name=target_champion_name,
            champions_path=self.champions_path,
            parent=self,
        )
        self._winrate_worker.progress.connect(self._on_winrate_progress)
        self._winrate_worker.finished_calculation.connect(self._on_winrate_finished)
        self._winrate_worker.error_occurred.connect(self._on_winrate_error)
        self._winrate_worker.start()

    def _on_winrate_progress(self, current: int, total: int, name: str) -> None:
        self.winrate_progress_bar.setMaximum(total)
        self.winrate_progress_bar.setValue(current)
        self.winrate_progress_label.setText(f"{current}/{total} {name[:10]}")

    def _on_winrate_finished(self, total_champs: int, total_matchups: int) -> None:
        self.winrate_progress_bar.setVisible(False)
        self.winrate_progress_label.setText(f"✓ {total_champs}/{total_champs}")
        self.update_single_champ_btn.setEnabled(True)
        self.update_winrates_btn.setEnabled(True)
        self.champions = self._load(self.champions_path)
        self._refresh_analysis()
        self.status.setText(
            f"Winrates actualizados con éxito: {total_champs} campeón/es, {total_matchups} enfrentamientos calculados."
        )

    def _on_winrate_error(self, error_msg: str) -> None:
        self.winrate_progress_bar.setVisible(False)
        self.winrate_progress_label.setVisible(False)
        self.update_single_champ_btn.setEnabled(True)
        self.update_winrates_btn.setEnabled(True)
        self.status.setText(f"Error al actualizar winrates: {error_msg}")

    def _load_item_editor(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.item_text.setPlainText(json.dumps(self.items[index], ensure_ascii=False, indent=2))

    def _recalculate_current_item_synergies(self) -> None:
        """Recalcula matemáticamente las sinergias y contrapesos del objeto actual."""
        try:
            value = json.loads(self.item_text.toPlainText())
            calc = ItemSynergyCalculatorService()
            calc.update_item(value)
            self._validate_item(value)
            idx = self.item_combo.currentIndex()
            self.items[idx] = value
            self.item_text.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            self.items_path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status.setText(f"Sinergias y contrapesos recalculados matemáticamente para {value.get('item', 'el objeto')}.")
            self._refresh_analysis()
        except (json.JSONDecodeError, ValueError, OSError) as error:
            self.status.setText(f"Error al recalcular: {error}")

    def _recalculate_all_items_synergies(self) -> None:
        """Reconstruye completamente todos los objetos desde Data Dragon (precio, stats, pasivas) y recalcula sus sinergias matemáticamente."""
        try:
            calc = ItemSynergyCalculatorService()
            count, updated = calc.rebuild_all_items_from_datadragon(self.items_path)
            self.items = updated
            current_name = self.item_combo.currentText()
            self.item_combo.blockSignals(True)
            self.item_combo.clear()
            self.item_combo.addItems([entry.get("basic_info", {}).get("name", "") for entry in self.items])
            idx = self.item_combo.findText(current_name)
            if idx >= 0:
                self.item_combo.setCurrentIndex(idx)
            elif len(self.items) > 0:
                self.item_combo.setCurrentIndex(0)
            self.item_combo.blockSignals(False)
            curr_idx = self.item_combo.currentIndex()
            if 0 <= curr_idx < len(self.items):
                self.item_text.setPlainText(json.dumps(self.items[curr_idx], ensure_ascii=False, indent=2))
            self.status.setText(f"Objetos reconstruidos y sinergias recalculadas con éxito para los {count} objetos desde Data Dragon.")
            self._refresh_analysis()
        except Exception as error:
            self.status.setText(f"Error al recalcular objetos: {error}")

    def _save_item_editor(self) -> None:
        try:
            value = json.loads(self.item_text.toPlainText())
            calc = ItemSynergyCalculatorService()
            calc.update_item(value)
            self._validate_item(value)
            self.items[self.item_combo.currentIndex()] = value
            self.item_text.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
            self.items_path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status.setText("Objeto guardado y sinergias recalculadas correctamente.")
            self._refresh_analysis()
        except (json.JSONDecodeError, ValueError, OSError) as error:
            self.status.setText(f"No se guardó: {error}")

    @staticmethod
    def _validate(document: dict[str, Any]) -> None:
        if not isinstance(document, dict):
            raise ValueError("El documento debe ser un objeto JSON.")
        basic = document.get("basic_info", {})
        if not isinstance(basic, dict):
            raise ValueError("basic_info debe ser un objeto JSON.")
        allowed = {"Bruiser", "Diver", "Assassin", "Skirmisher", "Marksman", "Mage", "Enchanter", "Vanguard", "Warden", "Juggernaut"}
        if basic.get("play_style") not in allowed: raise ValueError("play_style no permitido.")
        if basic.get("damage_type") not in {"AD", "AP", "True", "Hybrid"}: raise ValueError("damage_type no permitido.")
        if basic.get("resource_type") not in {"Mana", "Energy", "Fury", "Health", "Rage", "Courage", "Shield", "None", "Flow", "Ferocity", "Heat"}: raise ValueError("resource_type no permitido.")
        if not 1 <= int(basic.get("difficulty_floor", 0)) <= 10 or not 1 <= int(basic.get("difficulty_ceiling", 0)) <= 10: raise ValueError("difficulty debe estar entre 1 y 10.")
        for section_name in ("combat_attributes", "resistances_and_survivability", "map_and_control"):
            section = document.get(section_name, {})
            if not isinstance(section, dict):
                raise ValueError(f"{section_name} debe ser un objeto JSON.")
            if any(
                not isinstance(stat_value, int) or not 1 <= stat_value <= 10
                for stat_value in section.values()
            ):
                raise ValueError("Las estadísticas deben ser enteros de 1 a 10.")

    @staticmethod
    def _validate_item(value: dict[str, Any]) -> None:
        if not isinstance(value, dict): raise ValueError("El objeto debe ser JSON.")
        basic = value.get("basic_info", {})
        if basic.get("tier") != "Legendary": raise ValueError("Solo se pueden editar objetos Legendary.")
        if basic.get("item_group") not in {"Fatality", "Blight", "Annul", "Boots", "Lifeline", "Hydra", "Quicksilver", "Glory", "Support", "None"}: raise ValueError("item_group no permitido.")
        allowed_stats = {"attack_damage", "ability_power", "armor_penetration_percent", "magic_penetration_percent", "magic_penetration_flat", "lethality", "critical_strike_chance_percent", "attack_speed_percent", "life_steal_percent", "omnivamp_percent", "health", "mana", "armor", "magic_resistance", "ability_haste", "base_health_regeneration_percent", "base_mana_regeneration_percent", "movement_speed_flat", "movement_speed_percent", "heal_and_shield_power_percent", "tenacity"}
        if any(key not in allowed_stats for key in value.get("stats", {})): raise ValueError("Estadística de objeto no permitida.")
        if any(not 0 <= float(number) <= 3.5 for number in value.get("synergy_multipliers", {}).values()): raise ValueError("Multiplicador fuera de rango.")

    @staticmethod
    def _load(path: Path) -> Any:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, (list, dict)) else []
        except (OSError, json.JSONDecodeError):
            return []
