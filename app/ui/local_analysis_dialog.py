from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import math
from math import cos, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from app.services.item_synergy_calculator_service import ItemSynergyCalculatorService
from app.services.settings_service import SettingsService
from app.services.synergy_recommendation_service import SynergyRecommendationService
from app.ui.champion_ai_worker import ChampionAIWorker
from app.ui.champion_scraper_worker import ChampionScraperWorker
from data_dragon import get_champion_icon_path, get_item_icon_path, get_rune_icon_path, get_spell_icon_path

RUNE_TREE_OPTIONS = {
    "Precision": [
        ["Press the Attack", "Lethal Tempo", "Fleet Footwork", "Conqueror"],
        ["Overheal", "Triumph", "Presence of Mind"],
        ["Legend: Alacrity", "Legend: Tenacity", "Legend: Bloodline"],
        ["Coup de Grace", "Cut Down", "Last Stand"],
    ],
    "Resolve": [
        ["Demolish", "Font of Life", "Shield Bash"],
        ["Conditioning", "Second Wind", "Bone Plating"],
        ["Overgrowth", "Revitalize", "Unflinching"],
    ],
    "Domination": [
        ["Electrocute", "Predator", "Dark Harvest"],
        ["Cheap Shot", "Taste of Blood", "Sudden Impact"],
        ["Zombie Ward", "Ghost Poro", "Eyeball Collection"],
        ["Treasure Hunter", "Relentless Hunter", "Ultimate Hunter"],
    ],
    "Sorcery": [
        ["Summon Aery", "Arcane Comet", "Phase Rush"],
        ["Manaflow Band", "Nimbus Cloak", "Transcendence"],
        ["Celerity", "Absolute Focus", "Scorch"],
        ["Waterwalking", "Gathering Storm", "Haste"],
    ],
    "Inspiration": [
        ["Glacial Augment", "First Strike", "Unsealed Spellbook"],
        ["Hextech Flashtraption", "Magical Footwear", "Cash Back"],
        ["Future's Market", "Minion Dematerializer", "Biscuit Delivery"],
        ["Cosmic Insight", "Approach Velocity", "Jack of All Trades"],
    ],
}
RUNE_SHARD_OPTIONS = [
    ["Adaptive Force", "Attack Speed", "Ability Haste"],
    ["Adaptive Force", "Movement Speed", "Health Scaling"],
    ["Health", "Tenacity and Slow Resist", "Health Scaling"],
]


from PySide6.QtCore import QRectF

class DamageBarWidget(QWidget):
    def __init__(self, ad_pct: float = 85.0, ap_pct: float = 10.0, true_pct: float = 5.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ad_pct = ad_pct
        self.ap_pct = ap_pct
        self.true_pct = true_pct
        self.setFixedHeight(34)

    def set_percentages(self, ad: float, ap: float, true_dmg: float = 5.0) -> None:
        total = max(1.0, ad + ap + true_dmg)
        self.ad_pct = (ad / total) * 100.0
        self.ap_pct = (ap / total) * 100.0
        self.true_pct = (true_dmg / total) * 100.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()

        # Background track
        painter.setBrush(QColor(10, 20, 34))
        painter.setPen(QColor(35, 60, 90, 160))
        painter.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)

        track = r.adjusted(3, 3, -3, -3)
        tw = float(track.width())
        th = float(track.height())

        total = max(1.0, self.ad_pct + self.ap_pct + self.true_pct)
        gap = 3.0
        active_count = sum(1 for p in (self.ad_pct, self.ap_pct, self.true_pct) if p > 0)
        total_gaps = max(0, active_count - 1) * gap
        avail_w = tw - total_gaps

        ad_w = (self.ad_pct / total) * avail_w if self.ad_pct > 0 else 0.0
        ap_w = (self.ap_pct / total) * avail_w if self.ap_pct > 0 else 0.0
        true_w = (self.true_pct / total) * avail_w if self.true_pct > 0 else 0.0

        curr_x = float(track.left())

        # Font setup
        font = painter.font()
        font.setWeight(QFont.Weight.Bold)
        font.setPointSize(9)
        painter.setFont(font)

        # 1. AD Segment (Rosy Red -> Deep Crimson Gradient)
        if ad_w > 0:
            grad = QLinearGradient(curr_x, 0, curr_x + ad_w, 0)
            grad.setColorAt(0.0, QColor(244, 63, 94))
            grad.setColorAt(1.0, QColor(190, 18, 60))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(curr_x, track.top(), ad_w, th), 5, 5)

            if ad_w > 42:
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(
                    QRectF(curr_x + 8, track.top(), ad_w - 12, th),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"⚔ AD {int(self.ad_pct)}%"
                )
            curr_x += ad_w + gap

        # 2. AP Segment (Vibrant Blue -> Deep Royal Gradient)
        if ap_w > 0:
            grad = QLinearGradient(curr_x, 0, curr_x + ap_w, 0)
            grad.setColorAt(0.0, QColor(59, 130, 246))
            grad.setColorAt(1.0, QColor(29, 78, 216))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(curr_x, track.top(), ap_w, th), 5, 5)

            if ap_w > 42:
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(
                    QRectF(curr_x + 8, track.top(), ap_w - 12, th),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"🔮 AP {int(self.ap_pct)}%"
                )
            curr_x += ap_w + gap

        # 3. True Damage Segment (Bright Amber -> Gold Gradient)
        if true_w > 0:
            grad = QLinearGradient(curr_x, 0, curr_x + true_w, 0)
            grad.setColorAt(0.0, QColor(245, 158, 11))
            grad.setColorAt(1.0, QColor(180, 83, 9))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(curr_x, track.top(), true_w, th), 5, 5)

            if true_w > 32:
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(
                    QRectF(curr_x + 6, track.top(), true_w - 8, th),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"✨ True {int(self.true_pct)}%"
                )


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
    def __init__(self, values: list[tuple[str, float]] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values = values or []
        self.setMinimumHeight(220)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        painter.fillRect(rect, QColor(13, 20, 32, 230))

        # Title: Win Rate vs Game Length
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor(226, 232, 240))
        painter.drawText(QRectF(16, 12, rect.width() - 32, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Win Rate vs Game Length")

        if not self.values or len(self.values) < 2:
            return

        bounds = rect.adjusted(48, 42, -24, -32)

        val_list = [v for _, v in self.values if v > 0]
        if not val_list:
            return

        min_v = math.floor(min(val_list) - 0.8)
        max_v = math.ceil(max(val_list) + 0.8)
        if max_v - min_v < 4:
            min_v = math.floor(min(val_list) - 1.5)
            max_v = math.ceil(max(val_list) + 1.5)

        v_range = max(1.0, float(max_v - min_v))

        # Y-Axis grid lines & labels (% winrate)
        painter.setFont(QFont("Segoe UI", 8))
        step_count = 4
        for step in range(step_count + 1):
            val = min_v + (v_range * step / step_count)
            y = bounds.bottom() - (bounds.height() * step / step_count)

            painter.setPen(QPen(QColor(30, 41, 59, 180), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(bounds.left()), int(y), int(bounds.right()), int(y))

            painter.setPen(QColor(148, 163, 184))
            painter.drawText(QRectF(0, y - 8, bounds.left() - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{val:.0f}%")

        # Map X/Y points
        points: list[QPointF] = []
        n_points = len(self.values)
        for index, (label, val) in enumerate(self.values):
            x = bounds.left() + (bounds.width() * index / max(1, n_points - 1))
            norm_val = max(0.0, min(1.0, (val - min_v) / v_range))
            y = bounds.bottom() - (bounds.height() * norm_val)
            points.append(QPointF(x, y))

        # Smooth spline path (Cubic Bézier)
        path = QPainterPath()
        path.moveTo(points[0])
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            ctrl_offset = (p2.x() - p1.x()) * 0.4
            c1 = QPointF(p1.x() + ctrl_offset, p1.y())
            c2 = QPointF(p2.x() - ctrl_offset, p2.y())
            path.cubicTo(c1, c2, p2)

        # Gradient Fill beneath curve
        fill_path = QPainterPath(path)
        fill_path.lineTo(points[-1].x(), bounds.bottom())
        fill_path.lineTo(points[0].x(), bounds.bottom())
        fill_path.closeSubpath()

        grad = QLinearGradient(0, bounds.top(), 0, bounds.bottom())
        grad.setColorAt(0.0, QColor(16, 185, 129, 90))
        grad.setColorAt(1.0, QColor(16, 185, 129, 0))
        painter.fillPath(fill_path, grad)

        # Draw main emerald curve line
        line_pen = QPen(QColor(16, 185, 129), 2.5)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        painter.drawPath(path)

        # Draw points, percentage labels, and X-axis bracket labels
        for index, (label, val) in enumerate(self.values):
            pt = points[index]

            # Green circle marker
            painter.setBrush(QColor(16, 185, 129))
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.drawEllipse(pt, 4, 4)

            # Win rate % text above point
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor(52, 211, 153))
            val_str = f"{val:.1f}%" if val > 0 else "-"
            painter.drawText(QRectF(pt.x() - 25, pt.y() - 18, 50, 14), Qt.AlignmentFlag.AlignCenter, val_str)

            # Time bracket label below X axis
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(QRectF(pt.x() - 30, bounds.bottom() + 8, 60, 16), Qt.AlignmentFlag.AlignCenter, label)


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
        self.setObjectName("localAnalysisDialog")
        self.setWindowTitle("Análisis local · SolraLoL")
        self.resize(1100, 760)
        self.champions_path = Path(__file__).parents[2] / "data" / "champions_strict.json"
        self.items_path = Path(__file__).parents[2] / "data" / "legendary_items_strict.json"
        self.catalog_path = Path(__file__).parents[2] / "data" / "items.json"
        self.champions = self._load(self.champions_path)
        self._known_champion_names = {str(entry.get("character", "")).casefold(): str(entry.get("character", "")) for entry in self.champions}
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
        tabs.setObjectName("localAnalysisTabs")
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
        self.update_single_champ_btn.setToolTip("Descargar desde U.GG el build, runas y matchups del campeón seleccionado")
        self.update_single_champ_btn.clicked.connect(self._start_single_champion_winrate_update)
        self.update_winrates_btn = QPushButton("Actualizar todos")
        self.update_winrates_btn.setObjectName("updateWinratesBtn")
        self.update_winrates_btn.setToolTip("Descargar desde U.GG el build, runas y matchups de todos los campeones")
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

        # =========================================================================
        # ESTRUCTURA VISUAL COMPACTA (SEGÚN ESQUEMA PAINT REQUERIDO)
        # =========================================================================

        # 1. BLOQUE SUPERIOR DE TARJETAS (SUMMONERS, STARTING ITEMS, CORE BUILD)
        top_cards_row = QHBoxLayout()
        top_cards_row.setSpacing(10)

        # SUMMONERS (Caja Naranja)
        self.summoners_card = QFrame()
        self.summoners_card.setObjectName("summonersCard")
        sc_layout = QVBoxLayout(self.summoners_card)
        sc_layout.setContentsMargins(10, 8, 10, 8)
        sc_layout.setSpacing(4)
        s_title = QLabel("SUMMONERS")
        s_title.setStyleSheet("color: #fb923c; font-weight: 800; font-size: 11px; letter-spacing: 0.5px; border: none; background: transparent;")
        sc_layout.addWidget(s_title)
        self.summoners_row = QHBoxLayout()
        self.summoners_row.setSpacing(12)
        sc_layout.addLayout(self.summoners_row)
        top_cards_row.addWidget(self.summoners_card, 1)

        # STARTING ITEMS (Caja Roja)
        self.starters_card = QFrame()
        self.starters_card.setObjectName("startersCard")
        st_layout = QVBoxLayout(self.starters_card)
        st_layout.setContentsMargins(10, 8, 10, 8)
        st_layout.setSpacing(4)
        st_title = QLabel("STARTING ITEMS")
        st_title.setStyleSheet("color: #f87171; font-weight: 800; font-size: 11px; letter-spacing: 0.5px; border: none; background: transparent;")
        st_layout.addWidget(st_title)
        self.starters_row = QHBoxLayout()
        self.starters_row.setSpacing(12)
        st_layout.addLayout(self.starters_row)
        top_cards_row.addWidget(self.starters_card, 1)

        # CORE BUILD OVERVIEW (Caja Amarilla)
        self.core_overview_card = QFrame()
        self.core_overview_card.setObjectName("coreOverviewCard")
        co_layout = QVBoxLayout(self.core_overview_card)
        co_layout.setContentsMargins(10, 8, 10, 8)
        co_layout.setSpacing(4)
        co_title = QLabel("CORE BUILD")
        co_title.setStyleSheet("color: #eab308; font-weight: 800; font-size: 11px; letter-spacing: 0.5px; border: none; background: transparent;")
        co_layout.addWidget(co_title)
        self.core_overview_row = QHBoxLayout()
        self.core_overview_row.setSpacing(12)
        co_layout.addLayout(self.core_overview_row)
        top_cards_row.addWidget(self.core_overview_card, 2)

        analysis_layout.addLayout(top_cards_row)

        # 2. GRID PRINCIPAL (COLUMNA IZQUIERDA: BUILD / COLUMNA DERECHA: SITUACIONALES)
        main_grid_row = QHBoxLayout()
        main_grid_row.setSpacing(10)

        # Columna Izquierda: Único bloque BUILD (Marrón)
        self.build_card = QFrame()
        self.build_card.setObjectName("buildCard")
        b_layout = QVBoxLayout(self.build_card)
        b_layout.setContentsMargins(12, 10, 12, 10)
        b_layout.setSpacing(8)

        b_title = QLabel("BUILD")
        b_title.setStyleSheet("color: #fbbf24; font-weight: 800; font-size: 11px; letter-spacing: 0.5px; border: none; background: transparent;")
        b_layout.addWidget(b_title)

        # QGridLayout para alinear estrictamente las columnas de la build (Fila 0 = Items 1-3, Fila 1 = Items 4-6)
        self.build_grid = QGridLayout()
        self.build_grid.setHorizontalSpacing(24)
        self.build_grid.setVerticalSpacing(12)
        b_layout.addLayout(self.build_grid)
        b_layout.addStretch(1)

        main_grid_row.addWidget(self.build_card, 1)

        # Columna Derecha (Caja Verde Claro: SITUACIONALES)
        self.situational_card = QFrame()
        self.situational_card.setObjectName("situationalCard")
        sit_layout = QVBoxLayout(self.situational_card)
        sit_layout.setContentsMargins(10, 8, 10, 8)
        sit_layout.setSpacing(6)
        sit_title = QLabel("SITUACIONALES")
        sit_title.setStyleSheet("color: #a3e635; font-weight: 800; font-size: 11px; letter-spacing: 0.5px; border: none; background: transparent;")
        sit_layout.addWidget(sit_title)
        self.situational_items_row = QHBoxLayout()
        self.situational_items_row.setSpacing(12)
        sit_layout.addLayout(self.situational_items_row)
        main_grid_row.addWidget(self.situational_card, 1)

        analysis_layout.addLayout(main_grid_row)

        # 3. BARRA INFERIOR (Caja Roja Abajo: TIPO DE DAÑO EN UNA BARRA DE PORCENTAJE)
        damage_section = QVBoxLayout()
        damage_section.setSpacing(4)
        dmg_title = QLabel("TIPO DE DAÑO EN UNA BARRA DE PORCENTAJE")
        dmg_title.setStyleSheet("color: #f87171; font-weight: 800; font-size: 11px; letter-spacing: 0.5px;")
        damage_section.addWidget(dmg_title)
        self.damage_bar = DamageBarWidget(ad_pct=85.0, ap_pct=10.0, true_pct=5.0)
        damage_section.addWidget(self.damage_bar)

        analysis_layout.addLayout(damage_section)

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
        analysis_scroll.setObjectName("localAnalysisScroll")
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

    def _render_full_build(self, profile: dict[str, Any], champion_style: str) -> None:
        """Renderiza la Build Completa; usa power_spike_items como fallback si no hay datos scrapeados."""
        while self.full_build_row.count():
            item = self.full_build_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 1. Busca la build completa; si no existe, recurre al core de items existente
        wanted_names = profile.get("most_played_build")
        if not wanted_names:
            wanted_names = profile.get("power_curve_and_scaling", {}).get("power_spike_items", [])

        # 2. Solo si ambas listas están vacías muestra el texto de fallback
        if not wanted_names:
            no_data = QLabel("Sin build recomendada disponible.")
            no_data.setObjectName("localMuted")
            self.full_build_row.addWidget(no_data)
            return

        items_by_id = self._recommendation_items_by_id()
        catalog = self._catalog_items().get("items", {})

        for position, wanted_name in enumerate(wanted_names):
            target_id = self._catalog_id_for_name(wanted_name, catalog)
            match = None

            if target_id and target_id in items_by_id:
                match = (target_id, items_by_id[target_id])
            elif target_id and target_id in catalog:
                cat_item = catalog[target_id]
                display_name = cat_item.get("name_es") or cat_item.get("name") or str(wanted_name)
                synth_item = {
                    "id": target_id,
                    "item": display_name,
                    "name_en": cat_item.get("name_en", str(wanted_name)),
                    "basic_info": {
                        "id": target_id,
                        "name": display_name,
                        "tier": "Legendary" if "botas" not in str(wanted_name).casefold() else "Boots",
                        "gold_cost": int(cat_item.get("gold", {}).get("total", 0)),
                    },
                    "stats": cat_item.get("stats", {}),
                    "synergy_multipliers": {},
                }
                match = (target_id, synth_item)

            if match is None:
                self.full_build_row.addWidget(self._missing_core_item_card(str(wanted_name), position + 1), 1)
                continue

            item_id, item_data = match
            recommendation = self.service.score_item(profile, champion_style, item_id, item_data, [])
            self.full_build_row.addWidget(self._core_item_card(recommendation, position + 1), 1)

        self.full_build_row.addStretch(1)

    @staticmethod
    def _valid_rune_page_dict(page: Any) -> bool:
        """Valida la estructura interna de una única página de runas."""
        if not isinstance(page, dict):
            return False
        slots = page.get("slots") or page.get("runes")
        secondary = page.get("secondary_slots")
        return isinstance(slots, list) and len(slots) >= 3 and isinstance(secondary, list) and len(secondary) >= 2

    @staticmethod
    def _valid_rune_pages(pages: Any) -> bool:
        """Comprueba si la lista contiene al menos una página de runas válida."""
        if not isinstance(pages, list) or not pages:
            return False
        return any(LocalAnalysisDialog._valid_rune_page_dict(p) for p in pages)

    def _ugg_rune_page(self, profile: dict[str, Any]) -> dict[str, Any] | None:
        """Devuelve exclusivamente la primera página válida importada de U.GG."""
        pages = profile.get("common_runes", [])
        if not self._valid_rune_pages(pages):
            return None
        return pages[0] if isinstance(pages[0], dict) else None

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
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        title = QLabel("RUNAS")
        title.setObjectName("localInsightTitle")
        layout.addWidget(title)

        self.rune_pages_layout = QHBoxLayout()
        self.rune_pages_layout.setSpacing(12)
        layout.addLayout(self.rune_pages_layout)
        return panel

    def _render_rune_pages(self, profile: dict[str, Any]) -> None:
        while self.rune_pages_layout.count():
            item = self.rune_pages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        pages = profile.get("runes") or profile.get("common_runes") or []
        if not isinstance(pages, list):
            pages = []

        # Extraer página 1 (U.GG) y página 2 (Lolalytics)
        p1 = pages[0] if len(pages) > 0 and isinstance(pages[0], dict) else None
        p2 = pages[1] if len(pages) > 1 and isinstance(pages[1], dict) else None

        if not p1 or not self._valid_rune_page_dict(p1):
            p1 = self._default_rune_page(profile.get("basic_info", {}))
            p1["source"] = "U.GG"

        # Tarjeta 1 (Izquierda - Página 1 U.GG)
        self.rune_pages_layout.addWidget(self._rune_page_card(p1, 1), 1)

        # Tarjeta 2 (Derecha - Página 2 Lolalytics o Vacía)
        if p2 and self._valid_rune_page_dict(p2):
            self.rune_pages_layout.addWidget(self._rune_page_card(p2, 2), 1)
        else:
            self.rune_pages_layout.addWidget(self._empty_rune_page_card(2), 1)

    @staticmethod
    def _valid_rune_page_dict(page: Any) -> bool:
        if not isinstance(page, dict):
            return False
        slots = page.get("slots") or page.get("runes")
        secondary = page.get("secondary_slots")
        return isinstance(slots, list) and len(slots) >= 3 and isinstance(secondary, list) and len(secondary) >= 2

    def _rune_page_card(self, page: dict[str, Any], index: int) -> QFrame:
        card = QFrame()
        card.setObjectName("localRunePage")
        card.setMinimumHeight(175)

        main_layout = QVBoxLayout(card)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(8)

        # Cabecera de la tarjeta
        header = QHBoxLayout()
        header.setSpacing(8)

        source_label = page.get("source")
        if not source_label:
            source_label = "U.GG" if index == 1 else "Lolalytics"

        primary_tree = str(page.get("primary_tree", "Precision"))
        secondary_tree = str(page.get("secondary_tree", "Resolve"))
        keystone = str(page.get("keystone", ""))

        title_text = f"Página {index} {source_label} · {primary_tree}" + (f" / {secondary_tree}" if secondary_tree else "")
        title_lbl = QLabel(title_text)
        title_lbl.setObjectName("localRunePageTitle")
        header.addWidget(title_lbl)
        header.addStretch(1)

        win_rate = page.get("win_rate")
        games = int(page.get("games", 0) or 0)
        if isinstance(win_rate, (int, float)) and win_rate > 0:
            badge_text = f"{win_rate:.1%}" + (f" ({games:,} partidas)".replace(",", ".") if games else "")
            wr_badge = QLabel(badge_text)
            wr_badge.setObjectName("localRuneWrBadge")
            header.addWidget(wr_badge)

        main_layout.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("localRuneDivider")
        main_layout.addWidget(sep)

        # Cuerpo dividido en 2 columnas principales
        body = QHBoxLayout()
        body.setSpacing(16)

        # --- COLUMNA 1: RAMA PRINCIPAL ---
        primary_col = QVBoxLayout()
        primary_col.setSpacing(6)

        p_hdr = QLabel("RAMA PRINCIPAL")
        p_hdr.setObjectName("localRuneSectionLabel")
        primary_col.addWidget(p_hdr)

        p_tree_lbl = QLabel(f"{primary_tree} · {keystone}" if keystone else primary_tree)
        p_tree_lbl.setObjectName("localRuneTreeHeading")
        primary_col.addWidget(p_tree_lbl)

        p_runes_row = QHBoxLayout()
        p_runes_row.setSpacing(8)
        if keystone:
            p_runes_row.addWidget(self._rune_selection(keystone, is_keystone=True))

        slots = page.get("slots") or page.get("runes", [])
        for r_name in slots[:3]:
            p_runes_row.addWidget(self._rune_selection(str(r_name), is_keystone=False))
        p_runes_row.addStretch(1)
        primary_col.addLayout(p_runes_row)
        primary_col.addStretch(1)
        body.addLayout(primary_col, 1)

        v_sep = QFrame()
        v_sep.setFrameShape(QFrame.Shape.VLine)
        v_sep.setObjectName("localRuneVDivider")
        body.addWidget(v_sep)

        # --- COLUMNA 2: SECUNDARIAS (ARRIBA) Y FRAGMENTOS (ABAJO) ---
        sec_col = QVBoxLayout()
        sec_col.setSpacing(6)

        # Bloque Superior: Runas Secundarias
        s_hdr = QLabel("RAMA SECUNDARIA")
        s_hdr.setObjectName("localRuneSectionLabel")
        sec_col.addWidget(s_hdr)

        sec_runes_row = QHBoxLayout()
        sec_runes_row.setSpacing(8)
        sec_slots = page.get("secondary_slots", [])
        for r_name in sec_slots[:2]:
            sec_runes_row.addWidget(self._rune_selection(str(r_name), is_keystone=False))
        sec_runes_row.addStretch(1)
        sec_col.addLayout(sec_runes_row)

        # Bloque Inferior: Fragmentos de Estadísticas
        shards_hdr = QLabel("FRAGMENTOS DE ESTADÍSTICAS")
        shards_hdr.setObjectName("localRuneSectionLabel")
        sec_col.addWidget(shards_hdr)

        shards_row = QHBoxLayout()
        shards_row.setSpacing(6)
        shards = page.get("shards", ["Adaptive Force", "Adaptive Force", "Health Scaling"])
        for shard_name in shards[:3]:
            shards_row.addWidget(self._rune_selection(str(shard_name), is_shard=True))
        shards_row.addStretch(1)
        sec_col.addLayout(shards_row)

        sec_col.addStretch(1)
        body.addLayout(sec_col, 1)

        main_layout.addLayout(body)
        return card

    def _empty_rune_page_card(self, index: int) -> QFrame:
        card = QFrame()
        card.setObjectName("localRunePageEmpty")
        card.setMinimumHeight(175)

        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(4)

        icon = QLabel("⚔")
        icon.setObjectName("localRuneEmptyIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        source = "Lolalytics" if index == 2 else "U.GG"
        title = QLabel(f"Página {index} {source} vacía")
        title.setObjectName("localRuneEmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtext = QLabel(f"Sin configuración alternativa importada de {source}")
        subtext.setObjectName("localRuneEmptySubtext")
        subtext.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtext)
        return card

    @staticmethod
    def _rune_tree_panel(caption: str, tree: str, keystone: str, runes: Any, is_primary: bool) -> QFrame:
        panel = QFrame()
        panel.setObjectName("localRuneTreePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(5)
        heading = QHBoxLayout()
        label = QLabel(caption)
        label.setObjectName("localRuneSectionLabel")
        heading.addWidget(label)
        heading_text = tree + (f" · {keystone}" if is_primary and keystone else "")
        tree_label = QLabel(heading_text)
        tree_label.setObjectName("localRuneTreeHeading")
        heading.addWidget(tree_label)
        heading.addStretch(1)
        layout.addLayout(heading)

        values = [str(value) for value in runes] if isinstance(runes, list) else []
        # Mostramos sólo las runas seleccionadas: no el árbol entero.
        chosen = ([keystone] if is_primary and keystone else []) + values
        layout.addLayout(LocalAnalysisDialog._rune_option_row(chosen, set(chosen), keystone))
        return panel

    @staticmethod
    def _rune_option_row(names: list[str], selected: set[str], keystone: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        for name in names:
            object_name = "localRuneKeystone" if name == keystone else (
                "localRuneSelectionActive" if name in selected else "localRuneSelection"
            )
            row.addWidget(LocalAnalysisDialog._rune_selection(name, object_name), 1)
        row.addStretch(1)
        return row

    @staticmethod
    def _rune_selection(name: str, is_keystone: bool = False, is_shard: bool = False) -> QWidget:
        chip = QWidget()
        chip.setObjectName("localRuneChip")
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Tamaños incrementados para mayor visibilidad
        if is_keystone:
            size, icon_size = 44, 36
            icon.setObjectName("localRuneKeystoneIcon")
        elif is_shard:
            size, icon_size = 28, 20
            icon.setObjectName("localRuneShardIcon")
            shard_marks = {
                "Adaptive Force": "✦", "Attack Speed": "⚡", "Ability Haste": "⌛",
                "Movement Speed": "➜", "Health Scaling": "♥", "Health": "♥",
                "Tenacity and Slow Resist": "⛨",
            }
            icon.setText(shard_marks.get(name, "✦"))
        else:
            size, icon_size = 36, 28
            icon.setObjectName("localRuneNormalIcon")

        icon.setFixedSize(size, size)

        path = get_rune_icon_path(name, "16.17.1")
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                icon.setText("")
                icon.setPixmap(
                    pixmap.scaled(
                        icon_size,
                        icon_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        layout.addWidget(icon)
        chip.setToolTip(name)
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
            return {"name": "Página recomendada", "keystone": "Electrocutar", "primary_tree": "Dominación", "secondary_tree": "Inspiration", "slots": ["Impacto repentino", "Colección de globos", "Cazador de tesoros"], "secondary_slots": ["Magical Footwear", "Cosmic Insight"]}
        return {"name": "Página recomendada", "keystone": "Conquistador", "primary_tree": "Precision", "secondary_tree": "Resolve", "slots": ["Triunfo", "Leyenda: Presteza", "Golpe de gracia"], "secondary_slots": ["Second Wind", "Overgrowth"]}

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
            QDialog#localAnalysisDialog { background: #07111f; color: #e8f0ff; }
            QWidget#localAnalysisView, QScrollArea#localAnalysisScroll, QScrollArea#localAnalysisScroll::viewport,
            QScrollArea#localAnalysisScroll > QWidget > QWidget, QTabWidget#localAnalysisTabs::pane {
                background: #07111f; color: #e8f0ff;
            }
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
            QFrame#localRunePanel { background: #0a1827; border: 1px solid #1c3b57; border-radius: 10px; }
           QFrame#localRunePage {
                background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, stop: 0 #0d2136, stop: 1 #081524);
                border: 1px solid #234d75;
                border-radius: 8px;
            }
            QFrame#localRunePageEmpty {
                background: rgba(8, 20, 34, 0.45);
                border: 1px dashed #1d3e5e;
                border-radius: 8px;
            }
            QLabel#localRuneEmptyIcon { color: #3f6080; font-size: 22px; }
            QLabel#localRuneEmptyTitle { color: #82a0be; font-size: 12px; font-weight: 700; }
            QLabel#localRuneEmptySubtext { color: #4e6e8e; font-size: 10px; }
            QFrame#localRuneTreePanel { background: #06131f; border: 1px solid #193750; border-radius: 6px; }
            QWidget#localRuneSelection, QWidget#localRuneSelectionActive, QWidget#localRuneKeystone { background: transparent; border: none; }
            QLabel#localRuneSelectionIcon, QLabel#localRuneSelectionIconActive { color: #7890a8; background: #081522; border: 2px solid #29445b; border-radius: 22px; font-size: 9px; font-weight: 800; }
            QLabel#localRuneSelectionIconActive { color: #f6d477; background: #2a2111; border-color: #f0b944; }
            QLabel#localRuneSectionLabel { color: #d9ae4f; font-size: 9px; font-weight: 800; letter-spacing: 0.8px; }
            QLabel#localRuneTreeHeading { color: #77d8b0; font-size: 11px; font-weight: 700; margin-bottom: 2px; }
            QLabel#localRunePageTitle { color: #f0f5ff; font-size: 12px; font-weight: 800; }
            QLabel#localRuneWrBadge {
                color: #77d8b0;
                background: #0f3026;
                border: 1px solid #1f684e;
                border-radius: 4px;
                padding: 2px 7px;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#localRuneKeystoneIcon {
                color: #f6d477;
                background: #251e12;
                border: 2px solid #f0b944;
                border-radius: 22px;
            }
            QLabel#localRuneNormalIcon {
                color: #8bb3d6;
                background: #0d2238;
                border: 1px solid #2a5278;
                border-radius: 18px;
            }
            QLabel#localRuneShardIcon {
                color: #7890a8;
                background: #091726;
                border: 1px solid #1c3954;
                border-radius: 14px;
                font-size: 10px;
                font-weight: 800;
            }
            QFrame#localRuneDivider { color: #1a3854; background-color: #1a3854; max-height: 1px; border: none; }
            QFrame#localRuneVDivider { color: #1a3854; background-color: #1a3854; max-width: 1px; border: none; }
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
            QFrame#summonersCard { background: rgba(8, 19, 34, 210); border: 1px solid rgba(249, 115, 22, 0.5); border-radius: 8px; }
            QFrame#startersCard { background: rgba(8, 19, 34, 210); border: 1px solid rgba(239, 68, 68, 0.5); border-radius: 8px; }
            QFrame#coreOverviewCard { background: rgba(8, 19, 34, 210); border: 1px solid rgba(234, 179, 8, 0.5); border-radius: 8px; }
            QFrame#buildCard { background: rgba(8, 19, 34, 210); border: 1px solid rgba(180, 83, 9, 0.5); border-radius: 8px; }
            QFrame#situationalCard { background: rgba(8, 19, 34, 210); border: 1px solid rgba(132, 204, 22, 0.5); border-radius: 8px; }
            QLabel#localCoreItemName { color: #f0f5ff; font-size: 11px; font-weight: 700; }
            QLabel#localCoreItemScore { color: #77d8b0; font-size: 10px; }
            QLabel#localInsightText { color: #dce9f8; font-size: 12px; }
            QComboBox, QTableWidget, QTextEdit {
                background: #0c1c2e; color: #e8f0ff; border: 1px solid #315b7e; border-radius: 6px; padding: 6px;
            }
            QComboBox:focus, QTextEdit:focus { border-color: #d9ae4f; }
            QTableWidget { gridline-color: #193750; alternate-background-color: #10253b; }
            QHeaderView::section { background: #153452; color: #d9ae4f; border: 0; padding: 7px; font-weight: 700; }
            QTabWidget#localAnalysisTabs::pane { border: 1px solid #234663; background: #07111f; }
            QTabBar::tab { background: #0d2237; color: #9db3ca; padding: 9px 16px; border: 1px solid #234663; border-top-left-radius: 5px; border-top-right-radius: 5px; }
            QTabBar::tab:selected { background: #d9ae4f; color: #101a27; font-weight: 700; }
            QPushButton { min-height: 30px; background: #d9ae4f; color: #101a27; border: 1px solid #f0cc70; border-radius: 6px; padding: 6px 12px; font-weight: 700; font-size: 11px; }
            QPushButton:hover { background: #ebc56a; border-color: #ffe09a; }
            QPushButton:pressed { background: #bd9138; }
            QPushButton:disabled { background: #203a52; color: #6f869e; border-color: #2a4c6c; }
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
        rune_page = self._ugg_rune_page(profile)
        if rune_page:
            self.rune_summary.setText(
                "RUNAS U.GG · "
                f"{rune_page.get('keystone', '')} · {rune_page.get('primary_tree', '')} / "
                f"{rune_page.get('secondary_tree', '')}"
            )
        else:
            self.rune_summary.setText("RUNAS U.GG · Pendiente de una importación válida")
        self._render_rune_pages(profile)
        champion_style = str(basic.get("play_style", "Adaptable"))
        self.style_value.setText(champion_style)
        self.champion_badge.setText(champion_style.upper())
        values = self._radar_values(profile)
        self.radar.values = values
        self.radar.update()
        wr_curve = profile.get("win_rate_vs_game_length", [])
        if wr_curve and isinstance(wr_curve, list):
            self.power_curve.values = [
                (str(entry.get("label", "")), float(entry.get("winrate", 0)))
                for entry in wr_curve
                if isinstance(entry, dict)
            ]
        else:
            curve = profile.get("power_curve_and_scaling", {})
            curve_labels = (("0-15", "early_game"), ("20-25", "mid_game"), ("35-40", "late_game"))
            self.power_curve.values = [(label, 45.0 + float(curve.get(key, 5)) * 0.8) for label, key in curve_labels]
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
        self._render_full_build(profile, champion_style)
        self._render_starter_and_spells(profile)
        self._render_situational_items(profile)
        self._update_damage_bar(profile)
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

    def _update_damage_bar(self, profile: dict[str, Any]) -> None:
        breakdown = profile.get("damage_breakdown", {})
        if isinstance(breakdown, dict) and breakdown.get("physical_damage_percent") is not None:
            ad_pct = float(breakdown.get("physical_damage_percent", 85.0))
            ap_pct = float(breakdown.get("magic_damage_percent", 10.0))
            true_pct = float(breakdown.get("true_damage_percent", 5.0))
        else:
            basic = profile.get("basic_info", {})
            dmg_type = str(basic.get("damage_type", "AD"))
            if dmg_type == "AP":
                ad_pct, ap_pct, true_pct = 10.0, 85.0, 5.0
            elif dmg_type == "Hybrid":
                ad_pct, ap_pct, true_pct = 47.5, 47.5, 5.0
            elif dmg_type == "True":
                ad_pct, ap_pct, true_pct = 35.0, 15.0, 50.0
            else:
                ad_pct, ap_pct, true_pct = 85.0, 10.0, 5.0

        if hasattr(self, "damage_bar"):
            self.damage_bar.set_percentages(ad_pct, ap_pct, true_pct)

    @staticmethod
    def _champion_data(champion: str) -> dict[str, Any]:
        try:
            from data_dragon import get_champion_data
            return get_champion_data(champion, "16.17.1")
        except Exception:
            return {}

    def _ugg_rune_page(self, profile: dict[str, Any]) -> dict[str, Any] | None:
        """Devuelve exclusivamente la primera página válida importada de U.GG."""
        pages = profile.get("common_runes", [])
        if not self._valid_rune_pages(pages):
            return None
        return pages[0] if isinstance(pages[0], dict) else None

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

    def _clean_item_row(self, name: str, catalog: dict[str, Any], version: str) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        target_id = self._catalog_id_for_name(name, catalog)
        icon = QLabel()
        icon.setFixedSize(26, 26)
        icon.setStyleSheet("border: none; background: #091726; border-radius: 4px;")
        if target_id:
            path = get_item_icon_path(target_id, catalog, version)
            if path and path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    icon.setPixmap(pixmap.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setStyleSheet("color: #e2e8f0; font-weight: 500; font-size: 11px; border: none; background: transparent;")
        lbl.setToolTip(name)
        layout.addWidget(lbl)
        layout.addStretch(1)
        return widget

    def _clean_spell_row(self, name: str, version: str) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        path = get_spell_icon_path(name, version)
        icon = QLabel()
        icon.setFixedSize(26, 26)
        icon.setStyleSheet("border: none; background: #091726; border-radius: 4px;")
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(26, 26, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setStyleSheet("color: #fef08a; font-weight: 600; font-size: 11px; border: none; background: transparent;")
        layout.addWidget(lbl)
        layout.addStretch(1)
        return widget

    def _clean_spell_card_large(self, name: str, version: str) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        path = get_spell_icon_path(name, version)
        icon = QLabel()
        icon.setFixedSize(32, 32)
        icon.setStyleSheet("border: none; background: #091726; border-radius: 5px;")
        if path and path.exists():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                icon.setPixmap(pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setStyleSheet("color: #fef08a; font-weight: 600; font-size: 12px; border: none; background: transparent;")
        layout.addWidget(lbl)
        return widget

    def _clean_item_card_large(self, name: str, catalog: dict[str, Any], version: str) -> QWidget:
        widget = QWidget()
        widget.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        target_id = self._catalog_id_for_name(name, catalog)
        icon = QLabel()
        icon.setFixedSize(32, 32)
        icon.setStyleSheet("border: none; background: #091726; border-radius: 5px;")
        if target_id:
            path = get_item_icon_path(target_id, catalog, version)
            if path and path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    icon.setPixmap(pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setStyleSheet("color: #f1f5f9; font-weight: 600; font-size: 12px; border: none; background: transparent;")
        lbl.setToolTip(name)
        layout.addWidget(lbl, 1)
        return widget

    def _render_core_items(self, profile: dict[str, Any], style_key: str) -> None:
        while self.core_overview_row.count():
            item = self.core_overview_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Limpiar la fila 0 de build_grid
        for col in range(3):
            g_item = self.build_grid.itemAtPosition(0, col)
            if g_item and g_item.widget():
                g_item.widget().deleteLater()

        scaling = profile.get("power_curve_and_scaling", {})
        names = scaling.get("power_spike_items", []) if isinstance(scaling, dict) else []
        names = [name for name in names if "botas" not in str(name).casefold() and "boots" not in str(name).casefold()]
        if not names:
            names = profile.get("most_played_build", [])[:3]

        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        for col, wanted_name in enumerate(names[:3]):
            # Top card overview con icono 32x32 y texto 12px distribuido uniformemente
            self.core_overview_row.addWidget(self._clean_item_card_large(str(wanted_name), catalog, version), 1)
            # Fila 0 en el grid de BUILD (Alineado verticalmente con Fila 1)
            self.build_grid.addWidget(self._clean_item_card_large(str(wanted_name), catalog, version), 0, col)

        if not names:
            no_data = QLabel("Sin core build")
            no_data.setStyleSheet("color: #64748b; font-size: 10px; font-style: italic; border: none; background: transparent;")
            self.core_overview_row.addWidget(no_data, 1)
            self.build_grid.addWidget(no_data, 0, 0)

    def _render_full_build(self, profile: dict[str, Any], style_key: str) -> None:
        # Limpiar la fila 1 de build_grid
        for col in range(3):
            g_item = self.build_grid.itemAtPosition(1, col)
            if g_item and g_item.widget():
                g_item.widget().deleteLater()

        wanted_names = profile.get("most_played_build", [])
        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        # Objetos 4, 5, 6 para la Fila 1 del grid de BUILD
        late_items = wanted_names[3:6] if len(wanted_names) >= 4 else []

        if not late_items:
            no_data = QLabel("Sin objetos secundarios")
            no_data.setStyleSheet("color: #64748b; font-size: 10px; font-style: italic; border: none; background: transparent;")
            self.build_grid.addWidget(no_data, 1, 0)
        else:
            for col, wanted_name in enumerate(late_items[:3]):
                self.build_grid.addWidget(self._clean_item_card_large(str(wanted_name), catalog, version), 1, col)

    def _render_starter_and_spells(self, profile: dict[str, Any]) -> None:
        while self.summoners_row.count():
            item = self.summoners_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self.starters_row.count():
            item = self.starters_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        starters = profile.get("starter_items", [])
        spells = profile.get("summoner_spells", [])
        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        if spells:
            for spell_name in spells:
                self.summoners_row.addWidget(self._clean_spell_card_large(str(spell_name), version), 1)
        else:
            no_sp = QLabel("Sin hechizos")
            no_sp.setStyleSheet("color: #64748b; font-size: 10px; font-style: italic; border: none; background: transparent;")
            self.summoners_row.addWidget(no_sp, 1)

        if starters:
            for s_name in starters:
                self.starters_row.addWidget(self._clean_item_card_large(str(s_name), catalog, version), 1)
        else:
            no_s = QLabel("Sin objetos iniciales")
            no_s.setStyleSheet("color: #64748b; font-size: 10px; font-style: italic; border: none; background: transparent;")
            self.starters_row.addWidget(no_s, 1)

    def _render_situational_items(self, profile: dict[str, Any]) -> None:
        while self.situational_items_row.count():
            item = self.situational_items_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        situational = profile.get("situational_items", {})
        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        categories = [
            ("corta_curas", "Corta curas", "#f87171"),
            ("tanque", "Tanque / Resistencias", "#38bdf8"),
            ("asesino", "Asesino / Daño explosivo", "#fb923c"),
            ("utilidad_y_defensa", "Utilidad y Defensa", "#c084fc"),
        ]

        for cat_key, cat_label, color in categories:
            col_widget = QWidget()
            col_widget.setStyleSheet("background: transparent;")
            c_layout = QVBoxLayout(col_widget)
            c_layout.setContentsMargins(4, 2, 4, 2)
            c_layout.setSpacing(4)

            header = QLabel(cat_label)
            header.setStyleSheet(f"color: {color}; font-weight: 800; font-size: 10px; letter-spacing: 0.5px;")
            c_layout.addWidget(header)

            items_list = situational.get(cat_key, []) if isinstance(situational, dict) else []
            if items_list:
                for item_name in items_list[:4]:
                    chip = self._clean_item_row(str(item_name), catalog, version)
                    c_layout.addWidget(chip)
            else:
                none_lbl = QLabel("-")
                none_lbl.setStyleSheet("color: #64748b; font-size: 10px;")
                c_layout.addWidget(none_lbl)

            c_layout.addStretch(1)
            self.situational_items_row.addWidget(col_widget, 1)

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

    def _extract_matchup_info(self, entry: Any) -> tuple[str, float, float, str, int, int, str]:
        if isinstance(entry, dict):
            raw_name = str(entry.get("champion", "?"))
            name = self._known_champion_names.get(raw_name.casefold(), "")
            if not name:
                # Los JSON creados por el parser antiguo pueden contener la
                # tarjeta HTML completa. Sólo enseñamos un campeón reconocible.
                import re
                found = re.search(r"Games\s+vs\s+(.+?)(?:\s+(?:the|wins)\b|$)", raw_name, re.IGNORECASE)
                name = self._known_champion_names.get(found.group(1).strip().casefold(), "") if found else ""
            if not name:
                name = "Campeón no disponible"
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
        card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
        name_lbl.setMaximumWidth(135)
        name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
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
        """Inicia la sincronización pública con U.GG en un hilo secundario."""

        self.update_single_champ_btn.setEnabled(False)
        self.update_winrates_btn.setEnabled(False)
        self.winrate_progress_bar.setRange(0, 1 if target_champion_name else len(self.champions))
        self.winrate_progress_bar.setValue(0)
        self.winrate_progress_bar.setVisible(True)
        self.winrate_progress_label.setText("Iniciando...")
        self.winrate_progress_label.setVisible(True)

        if target_champion_name:
            self.status.setText(f"Actualizando datos de U.GG para '{target_champion_name}'...")
        else:
            self.status.setText("Actualizando datos de U.GG para todos los campeones...")

        self._winrate_worker = ChampionScraperWorker(
            target_champion_name=target_champion_name,
            champions_path=self.champions_path,
            parent=self,
        )
        self._winrate_worker.progress.connect(self._on_winrate_progress)
        self._winrate_worker.finished_scraping.connect(self._on_winrate_finished)
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
        if total_matchups:
            self.status.setText(f"Datos de U.GG actualizados: {total_matchups}/{total_champs} campeón/es sincronizados.")
        else:
            self.status.setText("U.GG no entregó todos los datos requeridos; no se modificó el JSON. Revisa tu conexión o el cambio de versión de U.GG.")

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
