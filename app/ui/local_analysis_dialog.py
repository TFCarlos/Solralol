from __future__ import annotations

import json
import logging
import math
from math import cos, sin
from pathlib import Path
from time import perf_counter
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from _paths import DATA_DIR
from app.services.analisis_local_service import AnalisisLocalService
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.champion_variant_service import ChampionVariantService
from app.services.item_synergy_calculator_service import ItemSynergyCalculatorService
from app.services.rangos_campeones import OPCIONES_RANGO, RANGO_PREDETERMINADO
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones
from app.services.settings_service import SettingsService
from app.services.synergy_recommendation_service import SynergyRecommendationService
from app.ui.analisis_local_worker import AnalisisLocalWorker
from app.ui.barra_lateral import crear_icono
from app.ui.champion_ai_worker import ChampionAIWorker
from app.ui.champion_scraper_worker import ChampionScraperWorker
from app.ui.contenedores_analisis import TablaRecomendaciones, TarjetaContenido
from app.ui.estilo_analisis import ESTILO_ANALISIS
from app.ui.sistema_visual import (
    ALTURA_CONTROL,
    ESPACIO_SECCION,
    PALETA,
    espaciar_tarjeta,
)
from app.ui.superficies_analisis import FondoTecnologico, IconoEnmarcado, TarjetaCampeon
from app.ui.tema import (
    aplicar_apariencia,
    aplicar_color,
    aplicar_tema,
    color_con_alfa,
)

#: Líneas disponibles en el selector del panel (clave normalizada, etiqueta).
_ANALYSIS_LANES: tuple[tuple[str, str], ...] = (
    ("top", "Top"),
    ("jungle", "Jungle"),
    ("mid", "Mid"),
    ("adc", "ADC"),
    ("support", "Support"),
)

#: Habilidades del campeón, en el orden de la cuadrícula de niveles.
_SKILL_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")

#: Alias en español/otros formatos que pueden aparecer en `flex_potential`.
_LANE_ALIASES = {
    "bot": "adc",
    "bottom": "adc",
    "tirador": "adc",
    "utility": "support",
    "soporte": "support",
    "middle": "mid",
    "medio": "mid",
    "jungla": "jungle",
}

#: Ancho fijo de la columna de acciones del héroe (botones y estado).
ANCHO_ACCIONES_HEROE = 210
#: Altura fija reservada para etiqueta y barra de progreso dentro del héroe.
ALTO_ESTADO_ACTUALIZACION = 60

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


class ClickableFrame(QFrame):
    """`QFrame` que emite `clicked` al pulsar con el botón izquierdo.

    Se usa para las tarjetas de página de runas: al pulsar la página 2, el panel
    de build cambia a la build asociada a esa página.
    """

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected = False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        """Resalta la tarjeta cuando es la página de runas activa."""
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self.setProperty("selected", "true" if selected else "false")
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()


class DamageBarWidget(QWidget):
    def __init__(
        self,
        ad_pct: float = 85.0,
        ap_pct: float = 10.0,
        true_pct: float = 5.0,
        parent: QWidget | None = None,
    ) -> None:
        """Inicializa proporciones recibidas y reserva espacio para su leyenda; retorna None."""
        super().__init__(parent)
        self.ad_pct = ad_pct
        self.ap_pct = ap_pct
        self.true_pct = true_pct
        self.setFixedHeight(60)

    def set_percentages(self, ad: float, ap: float, true_dmg: float = 5.0) -> None:
        total = max(1.0, ad + ap + true_dmg)
        self.ad_pct = (ad / total) * 100.0
        self.ap_pct = (ap / total) * 100.0
        self.true_pct = (true_dmg / total) * 100.0
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Pinta proporciones recibidas en coral, teal y oro; retorna None."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, 0, -26)

        painter.setBrush(color_con_alfa("superficie", 255))
        painter.setPen(color_con_alfa("borde", 160))
        painter.drawRoundedRect(r.adjusted(0, 0, -1, -1), 8, 8)

        track = r.adjusted(3, 3, -3, -3)
        tw = float(track.width())
        th = float(track.height())

        total = max(1.0, self.ad_pct + self.ap_pct + self.true_pct)
        gap = 3.0
        active_count = sum(
            1 for p in (self.ad_pct, self.ap_pct, self.true_pct) if p > 0
        )
        total_gaps = max(0, active_count - 1) * gap
        avail_w = tw - total_gaps

        ad_w = (self.ad_pct / total) * avail_w if self.ad_pct > 0 else 0.0
        ap_w = (self.ap_pct / total) * avail_w if self.ap_pct > 0 else 0.0
        true_w = (self.true_pct / total) * avail_w if self.true_pct > 0 else 0.0

        curr_x = float(track.left())

        font = painter.font()
        font.setWeight(QFont.Weight.Bold)
        font.setPointSize(9)
        painter.setFont(font)

        if ad_w > 0:
            grad = QLinearGradient(curr_x, 0, curr_x + ad_w, 0)
            grad.setColorAt(0.0, QColor(PALETA["desventaja"]))
            grad.setColorAt(1.0, color_con_alfa("desventaja", 255))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(curr_x, track.top(), ad_w, th), 5, 5)

            if ad_w > 42:
                painter.setPen(color_con_alfa("texto", 255))
                painter.drawText(
                    QRectF(curr_x + 8, track.top(), ad_w - 12, th),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"⚔ AD {int(self.ad_pct)}%",
                )
            curr_x += ad_w + gap

        if ap_w > 0:
            grad = QLinearGradient(curr_x, 0, curr_x + ap_w, 0)
            grad.setColorAt(0.0, QColor(PALETA["teal"]))
            grad.setColorAt(1.0, color_con_alfa("borde", 255))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(curr_x, track.top(), ap_w, th), 5, 5)

            if ap_w > 42:
                painter.setPen(color_con_alfa("texto", 255))
                painter.drawText(
                    QRectF(curr_x + 8, track.top(), ap_w - 12, th),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"🔮 AP {int(self.ap_pct)}%",
                )
            curr_x += ap_w + gap

        if true_w > 0:
            grad = QLinearGradient(curr_x, 0, curr_x + true_w, 0)
            grad.setColorAt(0.0, QColor(PALETA["oro"]))
            grad.setColorAt(1.0, QColor(PALETA["oro_oscuro"]))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(curr_x, track.top(), true_w, th), 5, 5)

            if true_w > 32:
                painter.setPen(color_con_alfa("texto", 255))
                painter.drawText(
                    QRectF(curr_x + 6, track.top(), true_w - 8, th),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    f"✨ True {int(self.true_pct)}%",
                )
        painter.setPen(QColor(PALETA["secundario"]))
        painter.drawText(
            QRectF(0, r.bottom() + 5, self.width(), 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"AD {self.ad_pct:.1f}%   ·   AP {self.ap_pct:.1f}%   ·   Verdadero {self.true_pct:.1f}%",
        )


class RadarWidget(QWidget):
    def __init__(
        self, values: list[tuple[str, float]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.values = values
        self.setMinimumSize(360, 250)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Pinta los datos recibidos con oro y marfil, sin modificar valores; retorna None."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect_center = self.rect().center()
        center = QPointF(float(rect_center.x()), float(rect_center.y()))
        radius = min(self.width(), self.height()) * 0.32
        count = max(1, len(self.values))
        polygon = QPolygonF()
        for index in range(count):
            angle = -1.5708 + index * 6.28318 / count
            polygon.append(center + QPointF(radius * cos(angle), radius * sin(angle)))
        painter.setPen(QColor(PALETA["borde"]))
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
        painter.setBrush(color_con_alfa("oro", 45))
        painter.setPen(QColor(PALETA["oro"]))
        painter.drawPolygon(points)
        painter.setPen(QColor(PALETA["secundario"]))
        for index, (label, _) in enumerate(self.values):
            angle = -1.5708 + index * 6.28318 / count
            point = center + QPointF(
                (radius + 18) * cos(angle),
                (radius + 18) * sin(angle),
            )
            text_width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(int(point.x() - text_width / 2), int(point.y()), label)


class PowerCurveWidget(QWidget):
    def __init__(
        self,
        values: list[tuple[str, float]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.values = values or []
        self.setMinimumHeight(220)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Pinta los datos recibidos con oro y marfil, sin modificar valores; retorna None."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        painter.fillRect(rect, color_con_alfa("base", 0))

        # Title: Win Rate vs Game Length
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor(PALETA["marfil"]))
        painter.drawText(
            QRectF(16, 12, rect.width() - 32, 22),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Win rate por duración de partida",
        )

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

            painter.setPen(QPen(QColor(PALETA["borde"]), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(bounds.left()), int(y), int(bounds.right()), int(y))

            painter.setPen(QColor(PALETA["tenue"]))
            painter.drawText(
                QRectF(0, y - 8, bounds.left() - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{val:.0f}%",
            )

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
        grad.setColorAt(0.0, color_con_alfa("oro", 48))
        grad.setColorAt(1.0, color_con_alfa("oro", 0))
        painter.fillPath(fill_path, grad)

        # Draw main emerald curve line
        line_pen = QPen(QColor(PALETA["oro"]), 2.5)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        painter.drawPath(path)

        # Draw points, percentage labels, and X-axis bracket labels
        for index, (label, val) in enumerate(self.values):
            pt = points[index]

            # Green circle marker
            painter.setBrush(QColor(PALETA["marfil"]))
            painter.setPen(QPen(QColor(PALETA["oro"]), 1.5))
            painter.drawEllipse(pt, 4, 4)

            # Win rate % text above point
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor(PALETA["marfil"]))
            val_str = f"{val:.1f}%" if val > 0 else "-"
            painter.drawText(
                QRectF(pt.x() - 25, pt.y() - 18, 50, 14),
                Qt.AlignmentFlag.AlignCenter,
                val_str,
            )

            # Time bracket label below X axis
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QColor(PALETA["tenue"]))
            painter.drawText(
                QRectF(pt.x() - 30, bounds.bottom() + 8, 60, 16),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )


class BarWidget(QWidget):
    """Lista ordenada de sinergias: icono, nombre, barra degradada y puntuación."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inicializa el gráfico con parent y sus iconos preparados; retorna None."""
        super().__init__(parent)
        self.values: list[tuple[str, float, str]] = []
        self.iconos_preparados: dict[str, QPixmap] = {}
        self.setMinimumHeight(112)

    def set_values(self, values: list[tuple[str, float, str]]) -> None:
        self.values = values
        self.updateGeometry()
        self.update()

    def _row_height(self) -> int:
        """Devuelve la altura legible de una fila de afinidad."""
        return 52

    def sizeHint(self):  # noqa: N802
        height = max(
            self.minimumHeight(), self._row_height() * max(1, len(self.values)) + 16
        )
        return QSize(self.width(), height)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Dibuja valores e iconos en respuesta a event sin acceder a red/disco; retorna None."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), color_con_alfa("base", 0))

        if not self.values:
            painter.setPen(color_con_alfa("teal", 255))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Sin datos de sinergia disponibles.",
            )
            return

        maximum = max((value for _, value, _ in self.values), default=1.0) or 1.0
        row_h = self._row_height()
        top = 8
        for index, (label, value, item_id) in enumerate(self.values):
            y = top + index * row_h
            if index % 2 == 0:
                painter.fillRect(
                    6, y, self.width() - 12, row_h - 6, color_con_alfa("texto", 10)
                )

            icon_x = 14
            icon_size = 32
            icon_cy = y + (row_h - 6) // 2
            pixmap = self.iconos_preparados.get(str(item_id))
            if pixmap is not None and not pixmap.isNull():
                pintor_recorte = QPainterPath()
                pintor_recorte.addRoundedRect(
                    QRectF(icon_x, icon_cy - icon_size // 2, icon_size, icon_size), 8, 8
                )
                painter.save()
                painter.setClipPath(pintor_recorte)
                painter.drawPixmap(
                    icon_x,
                    icon_cy - icon_size // 2,
                    pixmap.scaled(
                        icon_size,
                        icon_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
                painter.restore()
            else:
                painter.setPen(QPen(QColor(PALETA["oro_oscuro"]), 1.2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    icon_x, icon_cy - icon_size // 2, icon_size, icon_size, 6, 6
                )

            text_x = icon_x + icon_size + 10
            name_w = min(170, self.width() // 3)
            painter.setPen(QColor(PALETA["texto"]))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(9)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            painter.drawText(
                text_x,
                icon_cy + metrics.ascent() // 2,
                metrics.elidedText(label, Qt.TextElideMode.ElideRight, name_w),
            )

            font.setBold(False)
            painter.setFont(font)
            bar_x = text_x + name_w + 10
            bar_w = max(40, self.width() - bar_x - 78)
            bar_h = 10
            bar_y = icon_cy - bar_h // 2
            track = QRectF(bar_x, bar_y, bar_w, bar_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color_con_alfa("texto", 18))
            painter.drawRoundedRect(track, bar_h / 2, bar_h / 2)
            ratio = max(0.0, min(1.0, value / maximum))
            fill_w = max(bar_h, bar_w * ratio) if ratio > 0 else 0
            if fill_w > 0:
                gradient = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
                gradient.setColorAt(0.0, QColor(PALETA["teal"]))
                gradient.setColorAt(1.0, QColor(PALETA["oro"]))
                painter.setBrush(gradient)
                painter.drawRoundedRect(
                    QRectF(bar_x, bar_y, fill_w, bar_h), bar_h / 2, bar_h / 2
                )

            score_text = f"{value:.1f}"
            pill_w = 52
            pill_h = 20
            pill_x = self.width() - pill_w - 14
            pill_y = icon_cy - pill_h // 2
            painter.setBrush(color_con_alfa("oro_suave", 40))
            painter.setPen(QPen(QColor(PALETA["oro"]), 1.0))
            painter.drawRoundedRect(
                QRectF(pill_x, pill_y, pill_w, pill_h), pill_h / 2, pill_h / 2
            )
            painter.setPen(QColor(PALETA["marfil"]))
            pill_font = painter.font()
            pill_font.setBold(True)
            painter.setFont(pill_font)
            painter.drawText(
                QRectF(pill_x, pill_y, pill_w, pill_h),
                Qt.AlignmentFlag.AlignCenter,
                score_text,
            )


class HeatmapWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.values: list[tuple[str, float]] = []
        self.setMinimumHeight(90)

    def paintEvent(self, event: Any) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        painter = QPainter(self)
        width = max(1, self.width() // max(1, len(self.values)))
        for index, (label, value) in enumerate(self.values):
            painter.setBrush(QColor(35, min(235, 100 + int(value * 135)), 125, 220))
            painter.drawRect(index * width + 2, 10, width - 5, 52)
            painter.setPen(color_con_alfa("texto", 255))
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

    def __init__(
        self,
        parent: QWidget | None = None,
        version: str | None = None,
        item_catalog: dict | None = None,
    ) -> None:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        super().__init__(parent)
        self.version = version or "16.17.1"
        self.setObjectName("localAnalysisDialog")
        self.setWindowTitle("Análisis local · SolraLoL")
        self.resize(1100, 760)
        self.champions_path = DATA_DIR / "champion_data"
        self._repositorio_campeones = RepositorioCampeones(self.champions_path)
        self.items_path = DATA_DIR / "legendary_items_strict.json"
        self.catalog_path = DATA_DIR / "items.json"
        self.champions = self._repositorio_campeones.perfiles()
        self._known_champion_names = {
            str(entry.get("character", "")).casefold(): str(entry.get("character", ""))
            for entry in self.champions
        }
        self.items = self._load(self.items_path)
        raw_catalog = (
            item_catalog
            if (item_catalog and isinstance(item_catalog, dict))
            else self._load(self.catalog_path)
        )
        if not raw_catalog:
            from data_dragon import load_cached_item_catalog

            self.version, loaded_items = load_cached_item_catalog()
            self.item_catalog = {"version": self.version, "items": loaded_items}
        elif "items" in raw_catalog and isinstance(raw_catalog["items"], dict):
            self.item_catalog = raw_catalog
        else:
            self.item_catalog = {"version": self.version, "items": raw_catalog}
        self.service = SynergyRecommendationService()
        self.analysis_rank = self._load_analysis_rank()
        self.analysis_lane = self._load_analysis_lane()
        self._active_variant_key = ""
        self._active_variant: dict[str, Any] | None = None
        # WR por línea cacheados por campeón+rango: son datos del rango, no de la línea,
        # así que se conservan mientras se recarga una variante (evita parpadeos en el selector).
        self._lane_wr_cache: dict[str, dict[str, Any]] = {}
        # Páginas de runas de la variante activa y cuál está seleccionada: la build y el
        # orden de habilidades mostrados son los de esa página.
        self._rune_pages: list[dict[str, Any]] = []
        self._rune_page_cards: list[ClickableFrame] = []
        self._selected_rune_page = 0
        self._current_profile: dict[str, Any] = {}
        self._clave_analisis_aplicado = ""
        self._generacion_analisis = 0
        self._carga_pendiente = False
        self._cerrando_analisis = False
        self._worker_analisis: AnalisisLocalWorker | None = None
        self._rutas_recursos: dict[tuple[str, str], Path] = {}
        self._imagenes_recursos: dict[str, bytes] = {}
        self._pixmaps_recursos: dict[str, QPixmap] = {}
        self._datos_preparados: dict[str, Any] = {}
        self._catalogo_analisis = CatalogoAnalisisLocal(
            self._catalog_items().get("items", {}), self.items, self.ITEM_NAME_ALIASES
        )
        self._servicio_analisis = AnalisisLocalService(
            self._catalogo_analisis, self.champions_path, self.version
        )
        self._temporizador_analisis = QTimer(self)
        self._temporizador_analisis.setSingleShot(True)
        self._temporizador_analisis.timeout.connect(self._iniciar_carga_analisis)
        self._actualizacion_activa = False
        self._modo_actualizacion = "todos"
        self._temporizador_progreso = QTimer(self)
        self._temporizador_progreso.setSingleShot(True)
        self._temporizador_progreso.timeout.connect(self._ocultar_barra_progreso)
        self._build_ui()
        self._apply_style()
        self._select_champion(0)

    def _build_ui(self) -> None:
        """Construye controles, secciones e indicador de carga del diálogo; retorna None."""
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(14)

        tabs = QTabWidget()
        tabs.setObjectName("localAnalysisTabs")
        analysis = FondoTecnologico()
        analysis.setObjectName("localAnalysisView")
        analysis_layout = QVBoxLayout(analysis)
        analysis_layout.setContentsMargins(18, 18, 18, 18)
        analysis_layout.setSpacing(ESPACIO_SECCION)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.champion_combo = QComboBox()
        self.champion_combo.setMinimumWidth(210)
        self.champion_combo.setMaximumWidth(300)
        self.champion_combo.addItems(
            [entry.get("character", "") for entry in self.champions]
        )
        self.champion_combo.currentIndexChanged.connect(self._select_champion)
        champion_caption = QLabel("CAMPEÓN")
        champion_caption.setObjectName("localCaption")
        style_caption = QLabel("ESTILO DEL CAMPEÓN")
        style_caption.setObjectName("localCaption")
        rank_caption = QLabel("RANGO")
        rank_caption.setObjectName("localCaption")
        controls.addWidget(champion_caption)
        controls.addWidget(self.champion_combo)
        controls.addSpacing(10)
        lane_caption = QLabel("LÍNEA")
        lane_caption.setObjectName("localCaption")
        controls.addWidget(lane_caption)
        self.analysis_lane_combo = QComboBox()
        self.analysis_lane_combo.setObjectName("analysisLaneCombo")
        self.analysis_lane_combo.setMinimumWidth(150)
        self.analysis_lane_combo.setMaximumWidth(360)
        self.analysis_lane_combo.setToolTip(
            "Línea mostrada: runas, ítems, matchups y winrate por duración de esa línea"
        )
        for lane_key, lane_label in _ANALYSIS_LANES:
            self.analysis_lane_combo.addItem(lane_label, lane_key)
        lane_index = self.analysis_lane_combo.findData(self.analysis_lane)
        self.analysis_lane_combo.setCurrentIndex(lane_index if lane_index >= 0 else 0)
        self.analysis_lane_combo.currentIndexChanged.connect(self._on_lane_changed)
        controls.addWidget(self.analysis_lane_combo)
        controls.addSpacing(10)
        controls.addWidget(style_caption)
        self.style_value = QLabel("-")
        self.style_value.setObjectName("localStyleValue")
        self.style_value.setMaximumWidth(240)
        controls.addWidget(self.style_value)
        controls.addSpacing(10)
        controls.addWidget(rank_caption)
        self.analysis_rank_combo = QComboBox()
        self.analysis_rank_combo.setObjectName("analysisRankCombo")
        self.analysis_rank_combo.setMinimumWidth(140)
        self.analysis_rank_combo.setMaximumWidth(220)
        self.analysis_rank_combo.setToolTip("Rango de los datos guardados localmente")
        for rank_key, rank_label in OPCIONES_RANGO:
            self.analysis_rank_combo.addItem(rank_label, rank_key)
        saved_rank_index = self.analysis_rank_combo.findData(self.analysis_rank)
        self.analysis_rank_combo.setCurrentIndex(
            saved_rank_index
            if saved_rank_index >= 0
            else self.analysis_rank_combo.findData(RANGO_PREDETERMINADO)
        )
        self.analysis_rank_combo.currentIndexChanged.connect(self._on_rank_changed)
        controls.addWidget(self.analysis_rank_combo)
        controls.addStretch(1)
        self.winrate_progress_label = QLabel("")
        self.winrate_progress_label.setObjectName("winrateProgressLabel")
        self.winrate_progress_label.setWordWrap(True)
        self.winrate_progress_label.setVisible(False)
        self.winrate_progress_bar = QProgressBar()
        self.winrate_progress_bar.setObjectName("winrateProgressBar")
        self.winrate_progress_bar.setRange(0, len(self.champions))
        self.winrate_progress_bar.setValue(0)
        self.winrate_progress_bar.setFixedWidth(ANCHO_ACCIONES_HEROE)
        self.winrate_progress_bar.setFixedHeight(20)
        self.winrate_progress_bar.setTextVisible(False)
        self.winrate_progress_bar.setVisible(False)
        self._estado_actualizacion = QWidget()
        self._estado_actualizacion.setObjectName("updateStatusSlot")
        self._estado_actualizacion.setFixedSize(
            ANCHO_ACCIONES_HEROE, ALTO_ESTADO_ACTUALIZACION
        )
        estado_layout = QVBoxLayout(self._estado_actualizacion)
        estado_layout.setContentsMargins(0, 0, 0, 0)
        estado_layout.setSpacing(6)
        estado_layout.addWidget(self.winrate_progress_label)
        estado_layout.addWidget(self.winrate_progress_bar)
        self.update_single_champ_btn = QPushButton("Actualizar campeón")
        self.update_single_champ_btn.setObjectName("secondaryButton")
        self.update_single_champ_btn.setIcon(
            crear_icono("M20 7a9 9 0 1 0 1 8M20 3v5h-5")
        )
        self.update_single_champ_btn.setFixedSize(ANCHO_ACCIONES_HEROE, ALTURA_CONTROL)
        self.update_single_champ_btn.setToolTip(
            "Actualiza los datos del campeón seleccionado en todas sus líneas y rangos"
        )
        self.update_single_champ_btn.clicked.connect(
            self._start_single_champion_winrate_update
        )
        self.update_winrates_btn = QPushButton("Actualizar todos")
        self.update_winrates_btn.setObjectName("updateWinratesBtn")
        self.update_winrates_btn.setIcon(crear_icono("M20 7a9 9 0 1 0 1 8M20 3v5h-5"))
        self.update_winrates_btn.setFixedSize(ANCHO_ACCIONES_HEROE, ALTURA_CONTROL)
        self.update_winrates_btn.setToolTip(
            "Actualiza los datos de todos los campeones en todas sus líneas y rangos"
        )
        self.update_winrates_btn.clicked.connect(
            self._start_all_champions_winrate_update
        )
        controls.addWidget(self._estado_actualizacion)
        controls.addWidget(self.update_single_champ_btn)
        controls.addWidget(self.update_winrates_btn)
        controles_visibles = [
            controls.itemAt(i).widget()
            for i in range(controls.count())
            if controls.itemAt(i).widget()
        ]
        while controls.count():
            controls.takeAt(0)
        panel_filtros = QFrame()
        panel_filtros.setObjectName("localFilters")
        filtros = QGridLayout(panel_filtros)
        filtros.setHorizontalSpacing(16)
        filtros.setVerticalSpacing(6)
        for columna, (etiqueta, componente) in enumerate(
            (
                (champion_caption, self.champion_combo),
                (lane_caption, self.analysis_lane_combo),
                (rank_caption, self.analysis_rank_combo),
                (style_caption, self.style_value),
            )
        ):
            filtros.addWidget(etiqueta, 0, columna)
            filtros.addWidget(componente, 1, columna)
            filtros.setColumnStretch(columna, 1)
        analysis_layout.addWidget(panel_filtros)
        self._filtros_analisis = filtros
        self._pares_filtros = (
            (champion_caption, self.champion_combo),
            (lane_caption, self.analysis_lane_combo),
            (rank_caption, self.analysis_rank_combo),
            (style_caption, self.style_value),
        )
        self.analysis_loading_bar = QProgressBar()
        self.analysis_loading_bar.setObjectName("winrateProgressBar")
        self.analysis_loading_bar.setRange(0, 0)
        self.analysis_loading_bar.setTextVisible(False)
        self.analysis_loading_bar.setFixedHeight(5)
        self.analysis_loading_bar.hide()
        analysis_layout.addWidget(self.analysis_loading_bar)

        self.skill_order_panel = self._create_skill_order_panel()

        banner_row = QHBoxLayout()
        banner_row.setSpacing(10)
        self.champion_banner = self._create_champion_banner()
        banner_row.addWidget(self.champion_banner, 1)
        analysis_layout.addLayout(banner_row)

        insight_row = QHBoxLayout()
        insight_row.setSpacing(10)
        self.counter_panel = self._insight_panel(
            "COUNTERS", "Sin counters configurados."
        )
        self.advice_panel = self._insight_panel(
            "CONSEJO DE PARTIDA", "Selecciona un campeón para ver el plan."
        )
        insight_row.addWidget(self.skill_order_panel, 2)
        insight_row.addWidget(self.counter_panel, 1)
        insight_row.addWidget(self.advice_panel, 1)
        analysis_layout.addLayout(insight_row)

        charts_row = QHBoxLayout()
        charts_row.setSpacing(10)
        self.radar = RadarWidget([])
        self.radar.setObjectName("radarPanel")
        perfil_panel = QFrame()
        perfil_panel.setObjectName("localChartCard")
        perfil_layout = QVBoxLayout(perfil_panel)
        perfil_titulo = QLabel("PERFIL DEL CAMPEÓN")
        perfil_titulo.setObjectName("localSectionTitle")
        perfil_layout.addWidget(perfil_titulo)
        perfil_layout.addWidget(self.radar)
        charts_row.addWidget(perfil_panel, 1)
        self.power_curve = PowerCurveWidget([])
        self.power_curve.setObjectName("powerCurvePanel")
        curva_panel = QFrame()
        curva_panel.setObjectName("localChartCard")
        curva_layout = QVBoxLayout(curva_panel)
        curva_layout.addWidget(self.power_curve)
        charts_row.addWidget(curva_panel, 1)
        analysis_layout.addLayout(charts_row, 1)

        self.rune_panel = self._create_rune_panel()
        analysis_layout.addWidget(self.rune_panel)

        top_cards_row = QHBoxLayout()
        top_cards_row.setSpacing(10)

        self.summoners_card = QFrame()
        self.summoners_card.setObjectName("summonersCard")
        sc_layout = QVBoxLayout(self.summoners_card)
        sc_layout.setContentsMargins(10, 8, 10, 8)
        sc_layout.setSpacing(4)
        s_title = QLabel("HECHIZOS DE INVOCADOR")
        s_title.setObjectName("localSectionTitle")
        sc_layout.addWidget(s_title)
        self.summoners_row = QHBoxLayout()
        self.summoners_row.setSpacing(12)
        sc_layout.addLayout(self.summoners_row)
        top_cards_row.addWidget(self.summoners_card, 1)

        self.starters_card = QFrame()
        self.starters_card.setObjectName("startersCard")
        st_layout = QVBoxLayout(self.starters_card)
        st_layout.setContentsMargins(10, 8, 10, 8)
        st_layout.setSpacing(4)
        st_title = QLabel("OBJETOS INICIALES")
        st_title.setObjectName("localSectionTitle")
        st_layout.addWidget(st_title)
        self.starters_row = QHBoxLayout()
        self.starters_row.setSpacing(12)
        st_layout.addLayout(self.starters_row)
        top_cards_row.addWidget(self.starters_card, 1)

        self.core_overview_card = QFrame()
        self.core_overview_card.setObjectName("coreOverviewCard")
        co_layout = QVBoxLayout(self.core_overview_card)
        co_layout.setContentsMargins(10, 8, 10, 8)
        co_layout.setSpacing(4)
        co_title = QLabel("NÚCLEO DE LA BUILD")
        co_title.setObjectName("localSectionTitle")
        co_layout.addWidget(co_title)
        self.core_overview_row = QHBoxLayout()
        self.core_overview_row.setSpacing(12)
        co_layout.addLayout(self.core_overview_row)
        top_cards_row.addWidget(self.core_overview_card, 2)

        analysis_layout.addLayout(top_cards_row)

        main_grid_row = QHBoxLayout()
        main_grid_row.setSpacing(10)

        self.build_card = QFrame()
        self.build_card.setObjectName("buildCard")
        b_layout = QVBoxLayout(self.build_card)
        b_layout.setContentsMargins(12, 10, 12, 10)
        b_layout.setSpacing(8)

        b_title = QLabel("BUILD COMPLETA")
        b_title.setObjectName("localSectionTitle")
        b_layout.addWidget(b_title)

        self.build_grid = QGridLayout()
        self.build_grid.setHorizontalSpacing(24)
        self.build_grid.setVerticalSpacing(12)
        b_layout.addLayout(self.build_grid)
        b_layout.addStretch(1)

        columna_build = QVBoxLayout()
        columna_build.setSpacing(ESPACIO_SECCION)
        self.build_card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        columna_build.addWidget(self.build_card)
        main_grid_row.addLayout(columna_build, 1)

        self.situational_card = QFrame()
        self.situational_card.setObjectName("situationalCard")
        sit_layout = QVBoxLayout(self.situational_card)
        sit_layout.setContentsMargins(10, 8, 10, 8)
        sit_layout.setSpacing(6)
        sit_title = QLabel("SITUACIONALES")
        sit_title.setObjectName("localSectionTitle")
        sit_layout.addWidget(sit_title)
        self.situational_items_row = QGridLayout()
        self.situational_items_row.setSpacing(16)
        sit_layout.addLayout(self.situational_items_row)
        main_grid_row.addWidget(self.situational_card, 1)

        analysis_layout.addLayout(main_grid_row)

        damage_section = QVBoxLayout()
        perfil_dano = QFrame()
        perfil_dano.setObjectName("localDamageCard")
        perfil_dano.setLayout(damage_section)
        damage_section.setSpacing(4)
        dmg_title = QLabel("DISTRIBUCIÓN DE DAÑO")
        dmg_title.setObjectName("localSectionTitle")
        damage_section.addWidget(dmg_title)
        self.damage_bar = DamageBarWidget(ad_pct=85.0, ap_pct=10.0, true_pct=5.0)
        damage_section.addWidget(self.damage_bar)

        perfil_dano.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        columna_build.addWidget(perfil_dano)
        columna_build.addStretch(1)

        secondary_charts = QHBoxLayout()
        secondary_charts.setSpacing(10)
        affinity_title = QLabel("AFINIDAD DE OBJETOS")
        affinity_title.setObjectName("localSectionTitle")
        affinity_column = QVBoxLayout()
        afinidad_panel = QFrame()
        afinidad_panel.setObjectName("localChartCard")
        afinidad_panel.setLayout(affinity_column)
        affinity_column.addWidget(affinity_title)
        self.bar = BarWidget()
        self.bar.item_catalog = self._catalog_items().get("items", {})
        self.bar.setObjectName("barPanel")
        affinity_column.addWidget(self.bar)
        secondary_charts.addWidget(afinidad_panel, 1)
        matchup_title = QLabel("MATCHUPS CONFIGURADOS (COUNTERS / VENTAJAS)")
        matchup_title.setObjectName("localSectionTitle")
        self.matchups_panel = TarjetaContenido(
            "localMatchupsPanel", matchup_title.text()
        )
        self.matchups_panel_layout = QHBoxLayout()
        self.matchups_panel.disposicion.addLayout(self.matchups_panel_layout)
        self.matchups_panel_layout.setSpacing(12)

        self.counters_col = QVBoxLayout()
        self.counters_col.setSpacing(5)
        counters_hdr = QLabel("COUNTERS (DESVENTAJA)")
        counters_hdr.setObjectName("matchupCountersHeader")
        self.counters_col.addWidget(counters_hdr)
        self.counters_cards_layout = QVBoxLayout()
        self.counters_cards_layout.setSpacing(5)
        self.counters_col.addLayout(self.counters_cards_layout)
        self.counters_col.addStretch(1)

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

        self.matchup_status = QLabel("Winrates calculados según el rol del campeón.")
        self.matchup_status.setObjectName("localMuted")
        self.matchup_status.setWordWrap(True)
        self.matchups_panel.disposicion.addWidget(self.matchup_status)
        secondary_charts.addWidget(self.matchups_panel, 1)
        analysis_layout.addLayout(secondary_charts)

        self.recommendations_panel = TarjetaContenido(
            "localRecommendationsPanel", "SINERGIAS Y RECOMENDACIONES DE OBJETOS"
        )
        self.item_table = TablaRecomendaciones()
        self.item_table.setObjectName("recommendationTable")
        self.item_table.setHorizontalHeaderLabels(
            ["Objeto", "Afinidad", "Motivo / counter"]
        )
        self.item_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.item_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.item_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.item_table.verticalHeader().setDefaultSectionSize(44)
        self.item_table.setWordWrap(True)
        self.item_table.setSortingEnabled(True)
        self.recommendations_panel.disposicion.addWidget(self.item_table)
        analysis_layout.addWidget(self.recommendations_panel)
        analysis_layout.addStretch(1)
        controles = set(controles_visibles) | {panel_filtros, self.champion_banner}
        self._secciones_analisis = [
            componente
            for componente in analysis.findChildren(QWidget)
            if componente.parentWidget() is analysis
            and componente is not self.analysis_loading_bar
            and componente not in controles
        ]
        analysis_scroll = QScrollArea()
        analysis_scroll.setObjectName("localAnalysisScroll")
        analysis_scroll.setWidgetResizable(True)
        analysis_scroll.setFrameShape(QFrame.Shape.NoFrame)
        analysis_scroll.setWidget(analysis)
        self._filas_adaptables = [
            banner_row,
            insight_row,
            charts_row,
            top_cards_row,
            main_grid_row,
            secondary_charts,
        ]
        self._scroll_analisis = analysis_scroll
        tabs.addTab(analysis_scroll, "Afinidad y gráficos")

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        self.edit_combo = QComboBox()
        self.edit_combo.addItems(
            [entry.get("character", "") for entry in self.champions]
        )
        self.edit_combo.currentIndexChanged.connect(self._load_editor)
        self.edit_text = QTextEdit()
        champ_buttons_layout = QHBoxLayout()
        champ_buttons_layout.setSpacing(8)
        self.reanalyze_champ_btn = QPushButton("Re-analizar con IA")
        self.reanalyze_champ_btn.setToolTip(
            "Re-analiza los atributos subjetivos de este campeón usando Gemini AI (Google AI Studio)"
        )
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
        self.item_combo.addItems(
            [entry.get("basic_info", {}).get("name", "") for entry in self.items]
        )
        self.item_combo.currentIndexChanged.connect(self._load_item_editor)
        self.item_text = QTextEdit()
        item_buttons_layout = QHBoxLayout()
        item_buttons_layout.setSpacing(8)
        recalc_item = QPushButton("Recalcular sinergias del objeto")
        recalc_item.setToolTip(
            "Calcula matemáticamente synergy_multipliers y counter_weights de este objeto"
        )
        recalc_item.clicked.connect(self._recalculate_current_item_synergies)
        recalc_all_items = QPushButton("Recalcular todos los objetos")
        recalc_all_items.setToolTip(
            "Recalcula y actualiza matemáticamente las sinergias de todo el catálogo"
        )
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
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self._load_item_editor(0)

    @staticmethod
    def _valid_rune_page_dict(page: Any) -> bool:
        """Valida la estructura interna de una única página de runas."""
        if not isinstance(page, dict):
            return False
        slots = page.get("slots") or page.get("runes")
        secondary = page.get("secondary_slots")
        return (
            isinstance(slots, list)
            and len(slots) >= 3
            and isinstance(secondary, list)
            and len(secondary) >= 2
        )

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
        """Construye identidad, métricas y acciones del campeón; devuelve su tarjeta."""
        banner = TarjetaCampeon()
        layout = QHBoxLayout(banner)
        espaciar_tarjeta(layout)
        contenido = QHBoxLayout()
        contenido.setSpacing(20)
        self.champion_portrait = IconoEnmarcado()
        self.champion_portrait.setFixedSize(108, 108)
        self.champion_portrait.setContentsMargins(9, 9, 9, 9)
        self.champion_portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.champion_portrait.setObjectName("localChampionPortrait")
        contenido.addWidget(self.champion_portrait, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(8)
        self.champion_title = QLabel()
        self.champion_title.setObjectName("localChampionTitle")
        text.addWidget(self.champion_title)
        self.champion_subtitle = QLabel()
        self.champion_subtitle.setObjectName("localChampionSubtitle")
        self.champion_subtitle.setWordWrap(True)
        text.addWidget(self.champion_subtitle)
        identidad = QHBoxLayout()
        self.champion_badge = QLabel()
        self.champion_badge.setObjectName("localChampionBadge")
        identidad.addWidget(self.champion_badge)
        self.champion_meta = QLabel()
        self.champion_meta.setObjectName("localChampionMeta")
        self.champion_meta.setWordWrap(True)
        identidad.addWidget(self.champion_meta, 1)
        text.addLayout(identidad)
        metricas = QHBoxLayout()
        metricas.setSpacing(28)
        self.champion_winrate = QLabel("—")
        self.champion_winrate.setToolTip(
            "Resumen: media de los tramos de duración disponibles; usa la primera página de runas cuando no hay curva. No es un win rate global ponderado."
        )
        self.champion_lane = QLabel("—")
        for valor in (self.champion_winrate, self.champion_lane):
            valor.setObjectName("localChampionStat")
            metricas.addWidget(valor)
        self.champion_winrate.setAccessibleName("Win rate de resumen")
        self.champion_lane.setAccessibleName("Win rate de la l?nea seleccionada")
        metricas.addStretch(1)
        text.insertLayout(2, metricas)
        self.rune_summary = QLabel()
        self.rune_summary.setObjectName("localRuneSummary")
        self.rune_summary.setWordWrap(True)
        text.addWidget(self.rune_summary)
        contenido.addLayout(text, 1)
        layout.addLayout(contenido, 1)
        self._acciones_campeon = QVBoxLayout()
        self._acciones_campeon.setSpacing(10)
        self._acciones_campeon.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._acciones_campeon.addWidget(self.update_single_champ_btn)
        self._acciones_campeon.addWidget(self.update_winrates_btn)
        self._acciones_campeon.addWidget(self._estado_actualizacion)
        layout.addLayout(self._acciones_campeon)
        self._disposicion_hero = layout
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

    def _create_skill_order_panel(self) -> QFrame:
        """Panel con el orden de subida de habilidades: 18 columnas x 4 filas (Q/W/E/R)."""
        panel = QFrame()
        panel.setObjectName("localSkillOrderPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = QLabel("ORDEN DE HABILIDADES")
        title.setObjectName("localSectionTitle")
        header.addWidget(title)
        self.skill_order_priority = QLabel()
        self.skill_order_priority.setObjectName("localSkillOrderPriority")
        header.addWidget(self.skill_order_priority)
        self.skill_order_levels = QLabel()
        self.skill_order_levels.setObjectName("localSkillOrderLevel")
        header.addStretch(1)
        header.addWidget(self.skill_order_levels)
        layout.addLayout(header)

        self.skill_order_grid = QGridLayout()
        self.skill_order_grid.setHorizontalSpacing(2)
        self.skill_order_grid.setVerticalSpacing(2)
        self.skill_order_grid.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.skill_order_grid)
        return panel

    @staticmethod
    def _clear_layout(layout) -> None:
        """Vacía un layout borrando sus widgets."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _ability_pixmap(self, champion: str, key: str, size: int) -> QPixmap | None:
        """Pixmap de la habilidad `key` del campeón, o None si no hay icono."""
        path = self._recurso_analisis("ability", champion, key, "16.17.1")
        if path:
            pixmap = self._pixmap_analisis(path)
            if not pixmap.isNull():
                return pixmap.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        return None

    def _render_skill_order(self, champion: str, skill_order: Any) -> None:
        """Dibuja la cuadrícula 18x4 con el icono de cada habilidad en su nivel."""
        self._clear_layout(self.skill_order_grid)

        order: list[str] = []
        priority = ""
        if isinstance(skill_order, dict):
            raw_order = skill_order.get("order")
            if isinstance(raw_order, list):
                order = [
                    str(value).upper()
                    for value in raw_order
                    if str(value).upper() in _SKILL_KEYS
                ]
            priority = str(skill_order.get("priority") or "").upper()
        elif isinstance(skill_order, list):
            order = [
                str(value).upper()
                for value in skill_order
                if str(value).upper() in _SKILL_KEYS
            ]

        if not priority and order:
            # Sin prioridad explícita se deduce por el número de mejoras de cada una.
            priority = "".join(sorted(_SKILL_KEYS, key=lambda key: -order.count(key)))
        self.skill_order_priority.setText(
            f"Prioridad: {' > '.join(priority)}" if priority else ""
        )
        # La fila de niveles va en la cabecera: evita una fila extra en la cuadrícula.
        self.skill_order_levels.setText(
            "Nivel: " + " ".join(str(level + 1) for level in range(18))
        )

        # Columna 0 = icono de la habilidad de la fila (Q/W/E/R). Columnas 1..18 = niveles.
        icon_size = 20
        for row, key in enumerate(_SKILL_KEYS):
            row_label = QLabel()
            row_label.setFixedSize(icon_size, icon_size)
            row_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = self._ability_pixmap(champion, key, icon_size - 2)
            if pixmap is not None:
                row_label.setPixmap(pixmap)
                row_label.setToolTip(key)
            else:
                row_label.setText(key)
            row_label.setObjectName("localSkillOrderRow")
            self.skill_order_grid.addWidget(row_label, row, 0)

            for level in range(18):
                cell = QLabel()
                cell.setFixedSize(icon_size, icon_size)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                skill = order[level] if level < len(order) else ""
                if skill == key:
                    cell_pixmap = self._ability_pixmap(champion, key, icon_size - 4)
                    if cell_pixmap is not None:
                        cell.setPixmap(cell_pixmap)
                    else:
                        cell.setText(key)
                    cell.setObjectName("localSkillOrderCellActive")
                    cell.setToolTip(f"Nivel {level + 1}: {key}")
                else:
                    cell.setObjectName("localSkillOrderCell")
                self.skill_order_grid.addWidget(cell, row, level + 1)

    def _lane_display_label(self) -> str:
        """Etiqueta de la línea activa con su winrate (si está disponible)."""
        lane_key = str(
            self.analysis_lane_combo.currentData() or self.analysis_lane or ""
        )
        label = dict(_ANALYSIS_LANES).get(lane_key, lane_key or "—")
        stats = (
            self._profile_lane_stats(self._active_variant).get(lane_key)
            if lane_key
            else None
        )
        win_rate = stats.get("win_rate") if isinstance(stats, dict) else None
        if isinstance(win_rate, (int, float)):
            return f"{label} · {float(win_rate):.1%} WR"
        return label

    def _render_rune_pages(self, profile: dict[str, Any]) -> None:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        self._clear_layout(self.rune_pages_layout)
        self._rune_page_cards = []

        pages = profile.get("runes") or profile.get("common_runes") or []
        if not isinstance(pages, list):
            pages = []

        # Extraer página 1 (U.GG) y página 2 (Lolalytics)
        p1 = pages[0] if len(pages) > 0 and isinstance(pages[0], dict) else None
        p2 = pages[1] if len(pages) > 1 and isinstance(pages[1], dict) else None

        if not p1 or not self._valid_rune_page_dict(p1):
            p1 = self._default_rune_page(profile.get("basic_info", {}))
            p1["source"] = "U.GG"

        # Las páginas guardadas son las que mandan sobre la build mostrada.
        self._rune_pages = [
            page for page in (p1, p2) if self._valid_rune_page_dict(page)
        ]

        # Tarjeta 1 (Izquierda - Página 1 U.GG)
        self.rune_pages_layout.addWidget(self._rune_page_card(p1, 1), 1)

        # Tarjeta 2 (Derecha - Página 2 Lolalytics o Vacía)
        if p2 and self._valid_rune_page_dict(p2):
            self.rune_pages_layout.addWidget(self._rune_page_card(p2, 2), 1)
        else:
            self.rune_pages_layout.addWidget(self._empty_rune_page_card(2), 1)

        # Ajusta la selección a las páginas disponibles (puede haber solo una).
        if self._selected_rune_page >= len(self._rune_pages):
            self._selected_rune_page = 0
        self._update_rune_page_selection(repintar=False)

    def _update_rune_page_selection(self, repintar: bool = True) -> None:
        """Resalta la página y, si repintar, actualiza build y habilidades; retorna None."""
        for position, card in enumerate(self._rune_page_cards):
            card.set_selected(position == self._selected_rune_page)

        profile = self._current_profile
        if not repintar or not profile:
            return
        champion_style = str(
            profile.get("basic_info", {}).get("play_style", "Adaptable")
        )
        self._render_core_items(profile, champion_style)
        self._render_full_build(profile, champion_style)
        self._render_skill_order(
            str(profile.get("character", "")),
            self._active_rune_page_skill_order(profile),
        )
        # El resumen del banner sigue a la página seleccionada.
        active = self._active_rune_page()
        if active:
            self.rune_summary.setText(
                "RUNAS · "
                f"{active.get('keystone', '')} · {active.get('primary_tree', '')} / "
                f"{active.get('secondary_tree', '')}"
            )

    def _active_rune_page(self) -> dict[str, Any] | None:
        """Página de runas seleccionada (la que manda sobre la build mostrada)."""
        if 0 <= self._selected_rune_page < len(self._rune_pages):
            return self._rune_pages[self._selected_rune_page]
        return None

    def _active_build(self, profile: dict[str, Any]) -> list[str]:
        """Build de la página de runas activa; si no tiene, la del perfil."""
        page = self._active_rune_page()
        build = page.get("build") if isinstance(page, dict) else None
        if isinstance(build, list) and build:
            return [str(item) for item in build]
        stored = profile.get("most_played_build")
        if isinstance(stored, list) and stored:
            return [str(item) for item in stored]
        # Último recurso: el core de la curva de poder guardado en el perfil.
        scaling = profile.get("power_curve_and_scaling", {})
        spike = (
            scaling.get("power_spike_items", []) if isinstance(scaling, dict) else []
        )
        return [str(item) for item in spike] if isinstance(spike, list) else []

    def _active_rune_page_skill_order(self, profile: dict[str, Any]) -> Any:
        """Orden de habilidades de la página activa; si no tiene, el del perfil."""
        page = self._active_rune_page()
        order = page.get("skill_order") if isinstance(page, dict) else None
        return order if order else profile.get("skill_order")

    def _on_rune_page_clicked(self, index: int) -> None:
        """Selector de arquetipo: cambia runas, build y orden de habilidades."""
        if index == self._selected_rune_page or not (
            0 <= index < len(self._rune_pages)
        ):
            return
        previous_build = list(self._active_build(self._current_profile))
        self._selected_rune_page = index
        page = self._active_rune_page() or {}
        games = page.get("games")
        page_label = f"Página {index + 1}"
        if isinstance(games, int) and games:
            page_label += f" ({games:,} partidas)".replace(",", ".")
        self._update_rune_page_selection()
        changed = self._active_build(self._current_profile) != previous_build
        detail = (
            "su build y su orden de habilidades"
            if changed
            else "su orden de habilidades"
        )
        self.status.setText(f"{page_label} seleccionada: mostrando {detail}.")

    @staticmethod
    def _valid_rune_page_dict(page: Any) -> bool:
        if not isinstance(page, dict):
            return False
        slots = page.get("slots") or page.get("runes")
        secondary = page.get("secondary_slots")
        return (
            isinstance(slots, list)
            and len(slots) >= 3
            and isinstance(secondary, list)
            and len(secondary) >= 2
        )

    def _rune_page_card(self, page: dict[str, Any], index: int) -> ClickableFrame:
        """Construye ramas, muestra y seleccion de la pagina recibida; devuelve su tarjeta."""
        card = ClickableFrame()
        card.setObjectName("localRunePage")
        card.setMinimumHeight(175)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setToolTip(
            "Pulsa para mostrar la build y el orden de habilidades de este arquetipo."
        )
        self._rune_page_cards.append(card)
        card.clicked.connect(lambda: self._on_rune_page_clicked(index - 1))

        main_layout = QVBoxLayout(card)
        espaciar_tarjeta(main_layout)

        # Cabecera de la tarjeta
        header = QVBoxLayout()
        header.setSpacing(8)

        source_label = page.get("source")
        if not source_label:
            source_label = "U.GG" if index == 1 else "Lolalytics"

        primary_tree = str(page.get("primary_tree", "Precision"))
        secondary_tree = str(page.get("secondary_tree", "Resolve"))
        keystone = str(page.get("keystone", ""))

        title_text = f"Página {index} {source_label} · {primary_tree}" + (
            f" / {secondary_tree}" if secondary_tree else ""
        )
        title_lbl = QLabel(title_text)
        title_lbl.setObjectName("localRunePageTitle")
        title_lbl.setWordWrap(True)
        header.addWidget(title_lbl)
        muestra = QHBoxLayout()

        win_rate = page.get("win_rate")
        games = int(page.get("games", 0) or 0)
        if isinstance(win_rate, (int, float)) and win_rate > 0:
            wr_badge = QLabel(f"{win_rate:.1%} victorias")
            wr_badge.setObjectName("localRuneWrBadge")
            muestra.addWidget(wr_badge)
        if games:
            partidas = QLabel(f"{games:,} partidas".replace(",", "."))
            partidas.setObjectName("localRuneGamesBadge")
            muestra.addWidget(partidas)
        muestra.addStretch(1)
        header.addLayout(muestra)

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

        p_tree_lbl = QLabel(
            f"{primary_tree} · {keystone}" if keystone else primary_tree
        )
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
            sec_runes_row.addWidget(
                self._rune_selection(str(r_name), is_keystone=False)
            )
        sec_runes_row.addStretch(1)
        sec_col.addLayout(sec_runes_row)

        # Bloque Inferior: Fragmentos de Estadísticas
        shards_hdr = QLabel("FRAGMENTOS DE ESTADÍSTICAS")
        shards_hdr.setObjectName("localRuneSectionLabel")
        sec_col.addWidget(shards_hdr)

        shards_row = QHBoxLayout()
        shards_row.setSpacing(6)
        shards_raw = (
            page.get("shards") or page.get("stat_shards") or page.get("stat_mods")
        )
        if (
            not shards_raw
            and hasattr(self, "_current_profile")
            and isinstance(self._current_profile, dict)
        ):
            profile_shard_ids = self._current_profile.get("shard_ids")
            if isinstance(profile_shard_ids, list) and profile_shard_ids:
                from app.services.champion_scraper_service import ChampionScraperService

                shards_raw = [
                    ChampionScraperService._PERK_NAMES.get(val, str(val))
                    for val in profile_shard_ids[:3]
                ]

        if isinstance(shards_raw, list) and shards_raw:
            for shard_name in shards_raw[:3]:
                shards_row.addWidget(
                    self._rune_selection(str(shard_name), is_shard=True)
                )
        else:
            no_shards_lbl = QLabel("No disponible")
            aplicar_apariencia(no_shards_lbl, "metadatos")
            shards_row.addWidget(no_shards_lbl)

        shards_row.addStretch(1)
        sec_col.addLayout(shards_row)

        sec_col.addStretch(1)
        body.addLayout(sec_col, 1)

        main_layout.addLayout(body)
        return card

    def _empty_rune_page_card(self, index: int) -> QFrame:
        """Presenta ausencia de la página recibida sin ocultar su posición; devuelve tarjeta."""
        card = QFrame()
        card.setObjectName("localRunePageEmpty")
        card.setMinimumHeight(175)

        layout = QVBoxLayout(card)
        espaciar_tarjeta(layout)
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

    def _rune_selection(
        self, name: str, is_keystone: bool = False, is_shard: bool = False
    ) -> QWidget:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        chip = QWidget()
        chip.setObjectName("localRuneChip")
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(0, 0, 0, 0)

        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Tamaños incrementados para mayor visibilidad
        if is_keystone:
            size, icon_size = 50, 40
            icon.setObjectName("localRuneKeystoneIcon")
        elif is_shard:
            size, icon_size = 32, 24
            icon.setObjectName("localRuneShardIcon")
            shard_marks = {
                "Adaptive Force": "✦",
                "Attack Speed": "⚡",
                "Ability Haste": "⌛",
                "Movement Speed": "➜",
                "Health Scaling": "♥",
                "Health": "♥",
                "Tenacity and Slow Resist": "⛨",
            }
            icon.setText(shard_marks.get(name, "✦"))
        else:
            size, icon_size = 42, 32
            icon.setObjectName("localRuneNormalIcon")

        icon.setFixedSize(size, size)

        path = self._recurso_analisis("rune", name, "16.17.1")
        if path:
            pixmap = self._pixmap_analisis(path)
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
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        icon = QLabel("R")
        icon.setObjectName("localRuneIcon")
        icon.setFixedSize(24, 24)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = self._recurso_analisis("rune", name, "16.17.1")
        if path:
            pixmap = self._pixmap_analisis(path)
            if not pixmap.isNull():
                icon.setText("")
                icon.setPixmap(
                    pixmap.scaled(
                        22,
                        22,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(icon)
        label = QLabel(f"{caption}  {name}" + (f"  ·  {tree}" if tree else ""))
        label.setObjectName("localRuneName")
        layout.addWidget(label)
        layout.addStretch(1)
        return row

    @staticmethod
    def _default_rune_page(basic: dict[str, Any]) -> dict[str, Any]:
        if str(basic.get("damage_type", "AD")) == "AP":
            return {
                "name": "Página recomendada",
                "keystone": "Electrocutar",
                "primary_tree": "Dominación",
                "secondary_tree": "Inspiration",
                "slots": [
                    "Impacto repentino",
                    "Colección de globos",
                    "Cazador de tesoros",
                ],
                "secondary_slots": ["Magical Footwear", "Cosmic Insight"],
            }
        return {
            "name": "Página recomendada",
            "keystone": "Conquistador",
            "primary_tree": "Precision",
            "secondary_tree": "Resolve",
            "slots": ["Triunfo", "Leyenda: Presteza", "Golpe de gracia"],
            "secondary_slots": ["Second Wind", "Overgrowth"],
        }

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
        """Agrupa el título y consejo recibidos con relleno legible; devuelve el panel."""
        panel = QFrame()
        panel.setObjectName("localInsightPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
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
        """Aplica paleta compartida, relleno de tarjetas y estilo de desplegables; retorna None."""
        self.setFont(QFont("Segoe UI", 10))
        aplicar_tema(self)
        self.setStyleSheet(ESTILO_ANALISIS)
        for tarjeta in self.findChildren(QFrame):
            if tarjeta.layout() and tarjeta.objectName() in {
                "localChampionBanner",
                "localRunePanel",
                "localSkillOrderPanel",
                "localInsightPanel",
                "summonersCard",
                "startersCard",
                "coreOverviewCard",
                "buildCard",
                "situationalCard",
                "localMatchupsPanel",
                "localChartCard",
                "localDamageCard",
                "localFilters",
            }:
                espaciar_tarjeta(tarjeta.layout())
        for selector in self.findChildren(QComboBox):
            ventana_menu = selector.view().window()
            ventana_menu.setObjectName("localSelectorPopup")
            ventana_menu.setStyleSheet(self.styleSheet())

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Apila grupos al reducir el ancho recibido y conserva todas las secciones; retorna None."""
        super().resizeEvent(event)
        if hasattr(self, "_filas_adaptables"):
            direccion = (
                QBoxLayout.Direction.TopToBottom
                if self.width() < 1180
                else QBoxLayout.Direction.LeftToRight
            )
            for fila in self._filas_adaptables:
                fila.setDirection(direccion)
            self._disposicion_hero.setDirection(
                QBoxLayout.Direction.TopToBottom
                if self.width() < 1100
                else QBoxLayout.Direction.LeftToRight
            )
            self._acciones_campeon.setDirection(
                QBoxLayout.Direction.LeftToRight
                if self.width() < 1100
                else QBoxLayout.Direction.TopToBottom
            )
            columnas = 2 if self.width() < 1100 else 4
            while self._filtros_analisis.count():
                self._filtros_analisis.takeAt(0)
            for columna in range(4):
                self._filtros_analisis.setColumnStretch(
                    columna, int(columna < columnas)
                )
            for indice, (etiqueta, componente) in enumerate(self._pares_filtros):
                fila, columna = divmod(indice, columnas)
                self._filtros_analisis.addWidget(etiqueta, fila * 2, columna)
                self._filtros_analisis.addWidget(componente, fila * 2 + 1, columna)
            self.rune_pages_layout.setDirection(
                QBoxLayout.Direction.TopToBottom
                if self.width() < 1100
                else QBoxLayout.Direction.LeftToRight
            )

    def _select_champion(self, index: int) -> None:
        """Selecciona index, sincroniza el editor y agenda su análisis; retorna None."""
        if self.champion_combo.currentIndex() != index:
            self.champion_combo.blockSignals(True)
            self.champion_combo.setCurrentIndex(max(0, index))
            self.champion_combo.blockSignals(False)
        self.edit_combo.blockSignals(True)
        self.edit_combo.setCurrentIndex(max(0, index))
        self.edit_combo.blockSignals(False)
        self._active_variant_key = ""
        self._active_variant = None
        # Cada campeón/línea empieza por su página de runas principal.
        self._selected_rune_page = 0
        self._reset_lane_to_recommended()
        self._ensure_variant()

    def _ensure_variant(self) -> None:
        """Captura cambios de filtros y agenda la última selección; retorna None."""
        indice = self.champion_combo.currentIndex()
        if not 0 <= indice < len(self.champions):
            return
        campeon = str(self.champions[indice].get("character", ""))
        self.style_value.setText(
            str(
                self.champions[indice]
                .get("basic_info", {})
                .get("play_style", "Sin datos")
            )
        )
        linea = str(self.analysis_lane_combo.currentData() or "mid")
        rango = str(self.analysis_rank_combo.currentData() or RANGO_PREDETERMINADO)
        clave = ChampionVariantService.key(campeon, linea, rango)
        if (
            clave == self._clave_analisis_aplicado
            and not self._carga_pendiente
            and self._worker_analisis is None
        ):
            return
        self._generacion_analisis += 1
        self._inicio_seleccion_analisis = perf_counter()
        self._active_variant_key = clave
        self._carga_pendiente = True
        self._mostrar_contenido(False)
        self.analysis_loading_bar.show()
        self.update_single_champ_btn.setEnabled(False)
        self.update_winrates_btn.setEnabled(False)
        self.status.setText(
            f"Cargando análisis de {campeon} para {dict(_ANALYSIS_LANES).get(linea, linea)} ({self.analysis_rank_combo.currentText()})..."
        )
        if self._worker_analisis is not None:
            self._worker_analisis.requestInterruption()
        self._temporizador_analisis.start(0)

    def _iniciar_carga_analisis(self) -> None:
        """Inicia un worker para la selección vigente cuando la cola queda libre; retorna None."""
        if (
            self._cerrando_analisis
            or not self._carga_pendiente
            or self._worker_analisis is not None
        ):
            return
        indice = self.champion_combo.currentIndex()
        if not 0 <= indice < len(self.champions):
            self._carga_pendiente = False
            self.analysis_loading_bar.hide()
            return
        perfil = self.champions[indice]
        self._carga_pendiente = False
        worker = AnalisisLocalWorker(
            self._servicio_analisis,
            self._generacion_analisis,
            self._active_variant_key,
            perfil,
            str(self.analysis_lane_combo.currentData() or "mid"),
            str(self.analysis_rank_combo.currentData() or RANGO_PREDETERMINADO),
            self._default_rune_page(perfil.get("basic_info", {})),
            parent=self,
        )
        self._worker_analisis = worker
        worker.analisis_listo.connect(self._recibir_analisis)
        worker.analisis_fallido.connect(self._fallar_analisis)
        worker.finished.connect(self._terminar_carga_analisis)
        worker.start()

    def _recibir_analisis(
        self, generacion: int, clave: str, datos: dict[str, Any]
    ) -> None:
        """Aplica datos solo si generación y clave siguen vigentes; retorna None."""
        if (
            generacion != self._generacion_analisis
            or clave != self._active_variant_key
            or self._cerrando_analisis
        ):
            return
        if (
            datos.get("estado", EstadoDatos.DISPONIBLE.value)
            != EstadoDatos.DISPONIBLE.value
        ):
            self._mostrar_ausencia(datos["estado"])
            return
        inicio = perf_counter()
        self._mostrar_contenido(True)
        self._datos_preparados = datos
        self._active_variant = datos["variante"]
        self._rutas_recursos = datos["rutas"]
        self._imagenes_recursos = datos["imagenes"]
        self.setUpdatesEnabled(False)
        try:
            self._apply_lane_labels(self._active_variant)
            self._renderizar_analisis(datos["perfil"])
        except Exception:
            logging.getLogger(__name__).exception("Error al renderizar el análisis")
            self._mostrar_contenido(False)
            self.status.setText("No se pudo mostrar el análisis. Inténtalo de nuevo.")
        else:
            self._clave_analisis_aplicado = clave
            self.status.setText(
                "La actualización falló; se muestran los últimos datos válidos."
                if datos.get("actualizacion") == EstadoDatos.ACTUALIZACION_FALLIDA.value
                else "Análisis actualizado"
            )
            QTimer.singleShot(2500, lambda: self._limpiar_estado_analisis(generacion))
        finally:
            self.setUpdatesEnabled(True)
            self.analysis_loading_bar.hide()
            self.update_single_champ_btn.setEnabled(True)
            self.update_winrates_btn.setEnabled(True)
        self._tiempos_ultima_carga = dict(
            datos.get("tiempos", {}),
            render_ms=(perf_counter() - inicio) * 1000,
            seleccion_ms=(perf_counter() - self._inicio_seleccion_analisis) * 1000,
        )
        logging.getLogger(__name__).debug(
            "Carga local %s: %s", clave, self._tiempos_ultima_carga
        )

    def _mostrar_contenido(self, visible: bool) -> None:
        """Muestra u oculta secciones analíticas según visible; retorna None."""
        for componente in self._secciones_analisis:
            componente.setVisible(visible)
        if not visible:
            self.champion_title.setText(self.champion_combo.currentText())
            self.champion_subtitle.setText("Esperando datos locales")
            self.champion_meta.clear()
            self.champion_badge.clear()
            self.rune_summary.clear()
            self.champion_winrate.setText("—")
            self.champion_lane.setText("—")
            self.champion_portrait.clear()
            self.champion_banner.establecer_imagen(QPixmap())

    def _mostrar_ausencia(self, estado: str) -> None:
        """Presenta estado local recibido, oculta datos de otra selección y termina carga."""
        self._active_variant = None
        self._current_profile = {}
        self._datos_preparados = {}
        self._mostrar_contenido(False)
        self._apply_lane_labels(None)
        self.analysis_loading_bar.hide()
        self.update_single_champ_btn.setEnabled(True)
        self.update_winrates_btn.setEnabled(True)
        campeon = self.champion_combo.currentText()
        linea = dict(_ANALYSIS_LANES).get(
            str(self.analysis_lane_combo.currentData()), ""
        )
        rango = self.analysis_rank_combo.currentText()
        mensajes = {
            EstadoDatos.SIN_DATOS_LOCALES.value: "No hay datos guardados",
            EstadoDatos.SIN_DATOS_FUENTE.value: "La fuente no proporcionó muestra suficiente",
            EstadoDatos.NO_COMPATIBLE.value: "Esta combinación no es compatible",
            EstadoDatos.CORRUPTOS.value: "Los datos locales están dañados",
            EstadoDatos.ESQUEMA_INCOMPATIBLE.value: "El formato local requiere actualización",
        }
        self.status.setText(
            f"{mensajes.get(estado, 'Datos no disponibles')} para {campeon} · {linea} · {rango}. Actualiza los datos del campeón para intentar obtener esta información."
        )

    def _limpiar_estado_analisis(self, generacion: int) -> None:
        """Retira la confirmación temporal de generacion si sigue vigente; retorna None."""
        if (
            generacion == self._generacion_analisis
            and self.status.text() == "Análisis actualizado"
        ):
            self.status.clear()

    def _fallar_analisis(self, generacion: int, clave: str) -> None:
        """Termina la carga fallida vigente, preservando lo visible; retorna None."""
        if (
            generacion == self._generacion_analisis
            and clave == self._active_variant_key
        ):
            self._mostrar_contenido(False)
            self.analysis_loading_bar.hide()
            self.update_single_champ_btn.setEnabled(True)
            self.update_winrates_btn.setEnabled(True)
            self.status.setText(
                "No se pudieron cargar los datos del análisis. Inténtalo de nuevo."
            )

    def _terminar_carga_analisis(self) -> None:
        """Libera el worker finalizado y procesa la última solicitud pendiente; retorna None."""
        worker = self._worker_analisis
        self._worker_analisis = None
        if worker is not None:
            worker.deleteLater()
        if self._cerrando_analisis:
            self.close()
        elif self._carga_pendiente:
            self._temporizador_analisis.start(0)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancela cargas pendientes antes de aceptar el evento de cierre; retorna None."""
        self._temporizador_analisis.stop()
        self._carga_pendiente = False
        actualizador = getattr(self, "_winrate_worker", None)
        if actualizador is not None and actualizador.isRunning():
            self._cerrando_analisis = True
            actualizador.cancel()
            self.status.setText("Terminando la actualización en curso...")
            event.ignore()
            return
        if self._worker_analisis is not None:
            self._cerrando_analisis = True
            self._worker_analisis.requestInterruption()
            self.status.setText("Terminando la carga en curso...")
            event.ignore()
            return
        super().closeEvent(event)

    def _recurso_analisis(
        self, tipo: str, nombre: Any, *argumentos: Any
    ) -> Path | None:
        """Devuelve la ruta preparada de tipo/nombre sin red ni lectura; ignora argumentos heredados."""
        clave = str(nombre)
        if tipo == "ability":
            clave = f"{nombre}|{argumentos[0]}"
        return self._rutas_recursos.get((tipo, clave))

    def _pixmap_analisis(self, ruta: Path) -> QPixmap:
        """Decodifica una vez los bytes preparados de ruta y devuelve el pixmap Qt."""
        clave = str(ruta)
        if clave not in self._pixmaps_recursos:
            pixmap = QPixmap()
            pixmap.loadFromData(self._imagenes_recursos.get(clave, b""))
            if len(self._pixmaps_recursos) >= 128:
                self._pixmaps_recursos.pop(next(iter(self._pixmaps_recursos)))
            self._pixmaps_recursos[clave] = pixmap
        return self._pixmaps_recursos[clave]

    def _refresh_analysis(self, profile: dict[str, Any] | None = None) -> None:
        """Invalida datos editados y agenda perfil o campeón vigente; retorna None."""
        if profile is not None:
            self.champions[self.champion_combo.currentIndex()] = profile
        self._catalogo_analisis = CatalogoAnalisisLocal(
            self._catalog_items().get("items", {}), self.items, self.ITEM_NAME_ALIASES
        )
        self._servicio_analisis = AnalisisLocalService(
            self._catalogo_analisis, self.champions_path, self.version
        )
        self._clave_analisis_aplicado = ""
        self._active_variant_key = ""
        self._ensure_variant()

    def _apply_lane_labels(self, variant: dict[str, Any] | None) -> None:
        """Usa variante para mostrar winrates y destacar la línea más jugada; retorna None."""
        lanes = self._profile_lane_stats(variant)
        partidas_por_linea = {
            linea: datos["games"]
            for linea, datos in lanes.items()
            if linea in dict(_ANALYSIS_LANES)
            and isinstance(datos, dict)
            and isinstance(datos.get("games"), (int, float))
            and not isinstance(datos["games"], bool)
            and math.isfinite(datos["games"])
            and datos["games"] > 0
        }
        linea_comun = (
            max(partidas_por_linea, key=partidas_por_linea.get)
            if partidas_por_linea
            else None
        )
        current = self.analysis_lane_combo.currentData()
        self.analysis_lane_combo.blockSignals(True)
        for position in range(self.analysis_lane_combo.count()):
            lane_key = str(self.analysis_lane_combo.itemData(position))
            label = dict(_ANALYSIS_LANES).get(lane_key, lane_key)
            stats = lanes.get(lane_key) if isinstance(lanes, dict) else None
            win_rate = stats.get("win_rate") if isinstance(stats, dict) else None
            if isinstance(win_rate, (int, float)):
                label = f"{label} · {float(win_rate):.1%}"
            es_comun = lane_key == linea_comun
            if es_comun:
                label = f"★ {label} · Más común"
            fuente = QFont(self.analysis_lane_combo.font())
            fuente.setBold(es_comun)
            self.analysis_lane_combo.setItemData(
                position, fuente, Qt.ItemDataRole.FontRole
            )
            self.analysis_lane_combo.setItemData(
                position,
                "Línea con más partidas registradas para este campeón y rango."
                if es_comun
                else "",
                Qt.ItemDataRole.ToolTipRole,
            )
            self.analysis_lane_combo.setItemText(position, label)
        index = self.analysis_lane_combo.findData(current)
        if index >= 0:
            self.analysis_lane_combo.setCurrentIndex(index)
        self.analysis_lane_combo.blockSignals(False)
        fuente_medicion = QFont(self.analysis_lane_combo.font())
        fuente_medicion.setBold(True)
        metricas = QFontMetrics(fuente_medicion)
        ancho_texto = max(
            metricas.horizontalAdvance(self.analysis_lane_combo.itemText(posicion))
            for posicion in range(self.analysis_lane_combo.count())
        )
        self.analysis_lane_combo.setMinimumWidth(ancho_texto + 56)
        self.analysis_lane_combo.view().setMinimumWidth(ancho_texto + 40)

    def _lane_wr_cache_key(self) -> str:
        """Clave de caché de WR por línea (campeón + rango activos)."""
        index = self.champion_combo.currentIndex()
        champion = (
            str(self.champions[index].get("character", ""))
            if 0 <= index < len(self.champions)
            else ""
        )
        rank_key = str(self.analysis_rank_combo.currentData() or RANGO_PREDETERMINADO)
        return f"{champion.casefold()}|{rank_key}"

    def _profile_lane_stats(self, variant: dict[str, Any] | None) -> dict[str, Any]:
        """Winrates por línea de la variante activa o, si no hay, del perfil guardado."""
        if isinstance(variant, dict):
            stats = variant.get("lane_stats")
            lanes = stats.get("lanes") if isinstance(stats, dict) else None
            if isinstance(lanes, dict) and lanes:
                cache_key = self._lane_wr_cache_key()
                self._lane_wr_cache.pop(cache_key, None)
                self._lane_wr_cache[cache_key] = lanes
                # Se recorre campeón × rango: se acotan las entradas más antiguas.
                while len(self._lane_wr_cache) > 40:
                    self._lane_wr_cache.pop(next(iter(self._lane_wr_cache)))
                return lanes
        cached_lanes = self._lane_wr_cache.get(self._lane_wr_cache_key())
        if isinstance(cached_lanes, dict) and cached_lanes:
            return cached_lanes
        index = self.champion_combo.currentIndex()
        if not (0 <= index < len(self.champions)):
            return {}
        rank_key = str(self.analysis_rank_combo.currentData() or RANGO_PREDETERMINADO)
        stored = (
            self.champions[index].get("lane_stats")
            if 0 <= index < len(self.champions)
            else None
        )
        if not isinstance(stored, dict):
            return {}
        if str(stored.get("rank") or "") != rank_key:
            return {}
        lanes = stored.get("lanes")
        return lanes if isinstance(lanes, dict) else {}

    @staticmethod
    def _load_analysis_lane() -> str:
        """Lee la línea guardada en ajustes (clave `analysis_lane`)."""
        try:
            saved = (
                str(SettingsService().load().get("analysis_lane", "")).strip().lower()
            )
        except (OSError, ValueError):
            return ""
        return saved if saved in dict(_ANALYSIS_LANES) else ""

    def _recommended_lane(self, index: int) -> str:
        """Línea recomendada del campeón (primer elemento de `flex_potential`)."""
        if 0 <= index < len(self.champions):
            flex = (self.champions[index].get("basic_info") or {}).get(
                "flex_potential"
            ) or []
            if isinstance(flex, list) and flex:
                candidate = str(flex[0]).strip().lower()
                candidate = _LANE_ALIASES.get(candidate, candidate)
                if candidate in dict(_ANALYSIS_LANES):
                    return candidate
        return self.analysis_lane or "mid"

    def _reset_lane_to_recommended(self) -> None:
        """Coloca el selector de línea en la línea recomendada del campeón activo."""
        lane_key = self._recommended_lane(self.champion_combo.currentIndex())
        index = self.analysis_lane_combo.findData(lane_key)
        if index < 0:
            return
        self.analysis_lane_combo.blockSignals(True)
        self.analysis_lane_combo.setCurrentIndex(index)
        self.analysis_lane_combo.blockSignals(False)
        self.analysis_lane = lane_key

    def _on_lane_changed(self) -> None:
        """Persiste la línea elegida y recarga la variante correspondiente."""
        lane_key = str(
            self.analysis_lane_combo.currentData() or self.analysis_lane or "mid"
        )
        self.analysis_lane = lane_key
        self._ensure_variant()

    def _renderizar_analisis(self, profile: dict[str, Any]) -> None:
        """Actualiza widgets con profile preparado en segundo plano; retorna None."""
        index = self.champion_combo.currentIndex()
        if index < 0 or index >= len(self.champions):
            return
        # Se guarda para que el selector de páginas de runas pueda repintar la build.
        self._current_profile = profile
        champion = str(profile.get("character", "Campeón"))
        basic = profile.get("basic_info", {})
        champion_data = self._datos_preparados.get("metadatos", {})
        title = champion_data.get("title", "Campeón adaptable")
        icon_path = self._recurso_analisis("champion", champion, "16.17.1")
        self.champion_portrait.clear()
        if icon_path:
            pixmap = self._pixmap_analisis(icon_path)
            if not pixmap.isNull():
                self.champion_portrait.setPixmap(
                    pixmap.scaled(
                        88,
                        88,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        self.champion_title.setText(champion.upper())
        self.champion_subtitle.setText(str(title))
        splash = self._recurso_analisis("splash", champion)
        pixmap_splash = self._pixmap_analisis(splash) if splash else QPixmap()
        self.champion_banner.establecer_imagen(pixmap_splash)
        if not pixmap_splash.isNull():
            logging.getLogger(__name__).debug("[ui] hero splash loaded: %s", champion)

        # Calcular Win Rate general: media de win_rate_vs_game_length si existe
        wr_curve_raw = profile.get("win_rate_vs_game_length", [])
        if wr_curve_raw and isinstance(wr_curve_raw, list):
            wr_values = [
                float(e.get("winrate", 0))
                for e in wr_curve_raw
                if isinstance(e, dict) and e.get("winrate")
            ]
            overall_wr = (
                round(sum(wr_values) / len(wr_values), 1) if wr_values else None
            )
        else:
            # Fallback: usar win_rate de la primera página de runas (U.GG)
            runes_list = profile.get("common_runes", [])
            ugg_wr_raw = (
                runes_list[0].get("win_rate")
                if runes_list and isinstance(runes_list[0], dict)
                else None
            )
            if isinstance(ugg_wr_raw, (int, float)) and float(ugg_wr_raw) > 0:
                overall_wr = (
                    round(float(ugg_wr_raw) * 100, 1)
                    if float(ugg_wr_raw) <= 1.0
                    else round(float(ugg_wr_raw), 1)
                )
            else:
                overall_wr = None

        # Línea mostrada: la elegida en el selector (con su winrate si se conoce).
        primary_lane = self._lane_display_label()
        self._render_rune_pages(profile)

        self.champion_winrate.setText(
            f"{overall_wr:.1f}% WR" if overall_wr is not None else "N/D"
        )
        self.champion_lane.setText(primary_lane)
        self.champion_meta.setText(
            f"{basic.get('damage_type', 'Híbrido')}   ·   "
            f"Dificultad {basic.get('difficulty_floor', '?')}–{basic.get('difficulty_ceiling', '?')}/10"
        )
        rune_page = self._active_rune_page() or self._ugg_rune_page(profile)
        if rune_page:
            self.rune_summary.setText(
                "RUNAS · "
                f"{rune_page.get('keystone', '')} · {rune_page.get('primary_tree', '')} / "
                f"{rune_page.get('secondary_tree', '')}"
            )
        else:
            self.rune_summary.setText(
                "RUNAS U.GG · Pendiente de una importación válida"
            )
        champion_style = str(basic.get("play_style", "Adaptable"))
        self.style_value.setText(champion_style)
        self.champion_badge.setText(champion_style.upper())
        values = self._radar_values(profile)
        if self.radar.values != values:
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
            curve_labels = (
                ("0-15", "early_game"),
                ("20-25", "mid_game"),
                ("35-40", "late_game"),
            )
            self.power_curve.values = [
                (label, 45.0 + float(curve.get(key, 5)) * 0.8)
                for label, key in curve_labels
            ]
        self.power_curve.update()
        matchups = profile.get("matchups", {})
        counters = matchups.get("counters", []) if isinstance(matchups, dict) else []
        counter_labels = []
        for entry in counters[:5]:
            if isinstance(entry, dict):
                c_name = str(entry.get("champion", "?"))
                wr = entry.get("win_rate")
                counter_labels.append(
                    f"{c_name} ({wr:.1%})" if wr is not None else c_name
                )
            else:
                counter_labels.append(str(entry))
        self.counter_panel.content.setText(
            ", ".join(counter_labels)
            if counter_labels
            else "Sin counters configurados para este campeón."
        )
        strategy = profile.get("strategy_and_macro", {})
        advice = (
            strategy.get("about", "Ajusta la build a la composición enemiga.")
            if isinstance(strategy, dict)
            else "Ajusta la build a la composición enemiga."
        )
        self.advice_panel.content.setText(str(advice))
        ranked = self._datos_preparados.get("recomendaciones", [])
        self._render_core_items(profile, champion_style)
        self._render_full_build(profile, champion_style)
        self._render_starter_and_spells(profile)
        self._render_situational_items(profile)
        self._render_skill_order(champion, self._active_rune_page_skill_order(profile))
        self._update_damage_bar(profile)
        self.bar.iconos_preparados = {
            str(resultado.item_id): self._pixmap_analisis(ruta)
            for resultado in ranked[:8]
            if (ruta := self._recurso_analisis("item", resultado.item_id)) is not None
        }
        self.bar.set_values(
            [(result.name, result.score, result.item_id) for result in ranked[:8]]
        )
        self._render_matchups_panel(profile)
        self.item_table.setRowCount(len(ranked))
        self.item_table.setSortingEnabled(False)
        for row, result in enumerate(ranked):
            self.item_table.setCellWidget(
                row, 0, self._item_cell(result.name, result.item_id)
            )
            self.item_table.setItem(row, 1, QTableWidgetItem(f"{result.score:.1f}"))
            self.item_table.setItem(row, 2, QTableWidgetItem("; ".join(result.reasons)))
        self.item_table.setSortingEnabled(True)
        self.item_table.ajustar_contenido()

    def _update_damage_bar(self, profile: dict[str, Any]) -> None:
        breakdown = profile.get("damage_breakdown", {})
        if (
            isinstance(breakdown, dict)
            and breakdown.get("physical_damage_percent") is not None
        ):
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
            (
                "combat_attributes",
                {
                    "attack_damage": "Daño",
                    "attack_power": "Poder",
                    "critic": "Crítico",
                    "lethality": "Letalidad",
                },
            ),
            (
                "map_and_control",
                {
                    "mobility": "Movilidad",
                    "wave_clear": "Utilidad",
                    "team_fight": "Alcance",
                    "crowd_control": "Control",
                },
            ),
            (
                "resistances_and_survivability",
                {
                    "survivability_overall": "Supervivencia",
                    "armor": "Resistencia",
                    "magic_resistance": "Defensa mágica",
                },
            ),
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
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        cell = QWidget()
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        icon = IconoEnmarcado()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(34, 34)
        icon.setObjectName("localItemIcon")
        if item_id:
            path = self._recurso_analisis(
                "item", item_id, self._catalog_items().get("items", {}), "16.17.1"
            )
            if path:
                pixmap = self._pixmap_analisis(path)
                if not pixmap.isNull():
                    icon.setPixmap(
                        pixmap.scaled(
                            26,
                            26,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
        layout.addWidget(icon)
        label = QLabel(name)
        label.setToolTip(name)
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(label, 1)
        return cell

    def _catalog_items(self) -> dict[str, Any]:
        if isinstance(self.item_catalog, dict):
            if "items" in self.item_catalog and isinstance(
                self.item_catalog["items"], dict
            ):
                return self.item_catalog
            return {
                "version": getattr(self, "version", "16.17.1"),
                "items": self.item_catalog,
            }
        return {"version": getattr(self, "version", "16.17.1"), "items": {}}

    def _recommendation_items_by_id(self) -> dict[str, dict[str, Any]]:
        """Devuelve los objetos preparados sin reconstruir el catálogo."""
        return self._datos_preparados.get("objetos", {})

    def _catalog_id_for_name(self, name: str, catalog: dict[str, Any]) -> str:
        """Resuelve name en catalog con las reglas compartidas y devuelve su identificador."""
        return self._catalogo_analisis.id_por_nombre(name, catalog)

    def _clean_item_row(
        self, name: str, catalog: dict[str, Any], version: str
    ) -> QWidget:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        widget = QWidget()
        widget.setObjectName("localItemRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)

        target_id = self._catalog_id_for_name(name, catalog)
        icon = IconoEnmarcado()
        icon.setObjectName("localItemIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(34, 34)
        if target_id:
            path = self._recurso_analisis("item", target_id, catalog, version)
            if path:
                pixmap = self._pixmap_analisis(path)
                if not pixmap.isNull():
                    icon.setPixmap(
                        pixmap.scaled(
                            26,
                            26,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setObjectName("localItemName")
        lbl.setToolTip(name)
        layout.addWidget(lbl)
        layout.addStretch(1)
        return widget

    def _clean_spell_row(self, name: str, version: str) -> QWidget:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        widget = QWidget()
        widget.setObjectName("localItemRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(6)

        path = self._recurso_analisis("spell", name, version)
        icon = IconoEnmarcado()
        icon.setObjectName("localItemIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(34, 34)
        if path:
            pixmap = self._pixmap_analisis(path)
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        26,
                        26,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setObjectName("localItemName")
        layout.addWidget(lbl)
        layout.addStretch(1)
        return widget

    def _clean_spell_card_large(self, name: str, version: str) -> QWidget:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        widget = QWidget()
        widget.setObjectName("localItemRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(8)

        path = self._recurso_analisis("spell", name, version)
        icon = IconoEnmarcado()
        icon.setObjectName("localItemIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        if path:
            pixmap = self._pixmap_analisis(path)
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        32,
                        32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setObjectName("localItemName")
        layout.addWidget(lbl)
        return widget

    def _clean_item_card_large(
        self, name: str, catalog: dict[str, Any], version: str
    ) -> QWidget:
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        widget = QWidget()
        widget.setObjectName("localItemRow")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(8)

        target_id = self._catalog_id_for_name(name, catalog)
        icon = IconoEnmarcado()
        icon.setObjectName("localItemIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(40, 40)
        if target_id:
            path = self._recurso_analisis("item", target_id, catalog, version)
            if path:
                pixmap = self._pixmap_analisis(path)
                if not pixmap.isNull():
                    icon.setPixmap(
                        pixmap.scaled(
                            32,
                            32,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
        layout.addWidget(icon)

        lbl = QLabel(name)
        lbl.setObjectName("localItemName")
        lbl.setToolTip(name)
        layout.addWidget(lbl, 1)
        return widget

    def _clear_grid_row(self, grid: QGridLayout, row: int) -> None:
        """Vacía una fila del grid quitando sus items del layout.

        `deleteLater()` sin quitar el item del layout deja el widget ocupando su
        celda: Qt lo sigue pintando encima del nuevo y se ven dos textos superpuestos.
        """
        doomed: list[int] = []
        for index in range(grid.count()):
            if grid.getItemPosition(index)[0] == row:
                doomed.append(index)
        for index in reversed(doomed):
            item = grid.takeAt(index)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _render_core_items(self, profile: dict[str, Any], style_key: str) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        self._clear_layout(self.core_overview_row)
        self._clear_grid_row(self.build_grid, 0)

        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        # `_build_slots` reparte la build sin repetir objetos (ver _render_full_build).
        core_items, late_items = self._build_slots(profile)

        for col, wanted_name in enumerate(core_items[:3]):
            # Top card overview con icono 32x32 y texto 12px distribuido uniformemente
            self.core_overview_row.addWidget(
                self._clean_item_card_large(str(wanted_name), catalog, version), 1
            )
            # Fila 0 en el grid de BUILD (Alineado verticalmente con Fila 1)
            self.build_grid.addWidget(
                self._clean_item_card_large(str(wanted_name), catalog, version), 0, col
            )

        if not core_items:
            no_data = QLabel("Sin core build")
            aplicar_apariencia(no_data, "tarjeta")
            self.core_overview_row.addWidget(no_data, 1)
            self.build_grid.addWidget(no_data, 0, 0)

    def _build_slots(self, profile: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Reparte la build activa en (core, tardíos) sin repetir objetos.

        U.GG entrega la build con las botas intercaladas; aquí se deduplica por
        nombre normalizado para que un objeto no aparezca en las dos filas.
        """
        seen: set[str] = set()
        unique: list[str] = []
        for name in self._active_build(profile):
            normalised = self._normalise_item_name(name)
            if not normalised or normalised in seen:
                continue
            seen.add(normalised)
            unique.append(str(name))

        def is_boots(value: str) -> bool:
            return "botas" in str(value).casefold() or "boots" in str(value).casefold()

        core_items = [name for name in unique if not is_boots(name)]
        late_items = unique[len(core_items) :]
        return core_items[:3], late_items[:3]

    def _render_full_build(self, profile: dict[str, Any], style_key: str) -> None:
        """Construye la presentación con los parámetros recibidos y devuelve el resultado existente."""
        self._clear_grid_row(self.build_grid, 1)

        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        # Objetos 4, 5, 6 para la Fila 1 del grid de BUILD
        _, late_items = self._build_slots(profile)

        if not late_items:
            no_data = QLabel("Sin objetos secundarios")
            aplicar_apariencia(no_data, "tarjeta")
            self.build_grid.addWidget(no_data, 1, 0)
        else:
            for col, wanted_name in enumerate(late_items[:3]):
                self.build_grid.addWidget(
                    self._clean_item_card_large(str(wanted_name), catalog, version),
                    1,
                    col,
                )

    def _render_starter_and_spells(self, profile: dict[str, Any]) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
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
                self.summoners_row.addWidget(
                    self._clean_spell_card_large(str(spell_name), version), 1
                )
        else:
            no_sp = QLabel("Sin hechizos")
            aplicar_apariencia(no_sp, "tarjeta")
            self.summoners_row.addWidget(no_sp, 1)

        if starters:
            for s_name in starters:
                self.starters_row.addWidget(
                    self._clean_item_card_large(str(s_name), catalog, version), 1
                )
        else:
            no_s = QLabel("Sin objetos iniciales")
            aplicar_apariencia(no_s, "tarjeta")
            self.starters_row.addWidget(no_s, 1)

    def _render_situational_items(self, profile: dict[str, Any]) -> None:
        """Agrupa los objetos situacionales del perfil sin repetir la build; retorna None."""
        self._clear_layout(self.situational_items_row)

        situational = profile.get("situational_items", {})
        catalog = self._catalog_items().get("items", {})
        version = self._catalog_items().get("version", "16.17.1")

        # Un objeto que ya forma parte de la build no puede ser "situacional":
        # se filtran por nombre normalizado para que no se repitan en ambas tarjetas.
        build_names = {
            self._normalise_item_name(name) for name in self._active_build(profile)
        }

        categories = [
            ("corta_curas", "Corta curas", PALETA["desventaja"]),
            ("tanque", "Tanque / Resistencias", PALETA["teal"]),
            ("asesino", "Asesino / Daño explosivo", PALETA["oro_suave"]),
            ("utilidad_y_defensa", "Utilidad y Defensa", PALETA["magenta"]),
        ]

        for posicion, (cat_key, cat_label, color) in enumerate(categories):
            col_widget = QWidget()
            aplicar_apariencia(col_widget, "transparente")
            c_layout = QVBoxLayout(col_widget)
            c_layout.setContentsMargins(4, 2, 4, 2)
            c_layout.setSpacing(4)

            header = QLabel(cat_label)
            aplicar_color(header, color)
            header.setWordWrap(True)
            c_layout.addWidget(header)

            items_list = (
                situational.get(cat_key, []) if isinstance(situational, dict) else []
            )
            # Se descartan los objetos que ya están en la build activa.
            if isinstance(items_list, list):
                items_list = [
                    name
                    for name in items_list
                    if self._normalise_item_name(name) not in build_names
                ]
            if items_list:
                for item_name in items_list[:4]:
                    chip = self._clean_item_row(str(item_name), catalog, version)
                    c_layout.addWidget(chip)
            else:
                none_lbl = QLabel("-")
                aplicar_apariencia(none_lbl, "metadatos")
                c_layout.addWidget(none_lbl)

            c_layout.addStretch(1)
            self.situational_items_row.addWidget(
                col_widget, posicion // 2, posicion % 2
            )

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
        """Actualiza el componente con los parámetros recibidos y devuelve su resultado Qt."""
        card = QFrame()
        card.setObjectName("localCoreItem")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(8, 7, 8, 7)
        icon = QLabel()
        icon.setFixedSize(42, 42)
        version = self._catalog_items().get("version", "16.17.1")
        path = self._recurso_analisis(
            "item",
            recommendation.item_id,
            self._catalog_items().get("items", {}),
            version,
        )
        if path:
            pixmap = self._pixmap_analisis(path)
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        40,
                        40,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
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
        return (
            str(basic.get("name", item.get("item", "")))
            if isinstance(basic, dict)
            else str(item.get("item", ""))
        )

    @classmethod
    def _normalise_item_name(cls, name: Any) -> str:
        value = str(name).casefold().strip()
        return str(cls.ITEM_NAME_ALIASES.get(value, value)).casefold()

    def _item_id_for_name(self, name: str) -> str:
        catalog = self._catalog_items().get("items", {})
        return self._catalog_id_for_name(name, catalog)

    MATCHUP_CARD_LIMIT = 5

    def _render_matchups_panel(self, profile: dict[str, Any]) -> None:
        """Renderiza las tarjetas de los 5 Counters y los 5 Bueno Contra con sus iconos, winrate en línea y winrate overall."""
        for layout in (self.counters_cards_layout, self.good_cards_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        matchups = profile.get("matchups", {})
        counters = matchups.get("counters", []) if isinstance(matchups, dict) else []
        good_against = (
            matchups.get("good_against", []) if isinstance(matchups, dict) else []
        )

        # 5 Counters (Desventaja)
        for entry in counters[: self.MATCHUP_CARD_LIMIT]:
            name, wr_lane, wr_overall, tip, lg, og, role = self._extract_matchup_info(
                entry
            )
            card = self._create_matchup_card(
                name,
                wr_lane,
                wr_overall,
                tip,
                is_counter=True,
                lane_games=lg,
                overall_games=og,
                primary_role=role,
            )
            self.counters_cards_layout.addWidget(card)
        if not counters:
            lbl = QLabel("Sin counters configurados")
            lbl.setObjectName("localMuted")
            self.counters_cards_layout.addWidget(lbl)

        # 5 Bueno Contra (Ventaja)
        for entry in good_against[: self.MATCHUP_CARD_LIMIT]:
            name, wr_lane, wr_overall, tip, lg, og, role = self._extract_matchup_info(
                entry
            )
            card = self._create_matchup_card(
                name,
                wr_lane,
                wr_overall,
                tip,
                is_counter=False,
                lane_games=lg,
                overall_games=og,
                primary_role=role,
            )
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
                f"Línea [{role.upper()}]: {lane_wr:.1%} en {lane_games:,} Partidas  |  Overall: {overall_wr:.1%} en {overall_games:,} Partidas (Esmeralda+)".replace(
                    ",", "."
                )
            )
        elif has_data:
            self.matchup_status.setText(
                "Winrates diferenciados por Línea Predilecta y Overall (Esmeralda+)."
            )
        else:
            self.matchup_status.setText("Sin winrates configurados para este campeón.")

    def _extract_matchup_info(
        self, entry: Any
    ) -> tuple[str, float, float, str, int, int, str]:
        if isinstance(entry, dict):
            raw_name = str(entry.get("champion", "?"))
            name = self._known_champion_names.get(raw_name.casefold(), "")
            if not name:
                # Los JSON creados por el parser antiguo pueden contener la
                # tarjeta HTML completa. Sólo enseñamos un campeón reconocible.
                import re

                found = re.search(
                    r"Games\s+vs\s+(.+?)(?:\s+(?:the|wins)\b|$)",
                    raw_name,
                    re.IGNORECASE,
                )
                name = (
                    self._known_champion_names.get(
                        found.group(1).strip().casefold(), ""
                    )
                    if found
                    else ""
                )
            if not name:
                name = "Campeón no disponible"
            wr_lane = float(entry.get("win_rate", 0.50) or 0.50)
            wr_overall = float(
                entry.get("overall_win_rate", entry.get("win_rate", 0.50)) or 0.50
            )
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
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(6, 5, 8, 5)
        layout.setSpacing(8)

        # Icono del campeón
        icon = QLabel()
        icon.setFixedSize(36, 36)
        icon.setObjectName("matchupChampIcon")
        icon_path = self._recurso_analisis("champion", champion_name, self.version)
        if icon_path:
            pixmap = self._pixmap_analisis(icon_path)
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        36,
                        36,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(icon)

        # Nombre del campeón y partidas del enfrentamiento
        name_box = QVBoxLayout()
        name_box.setSpacing(1)
        name_lbl = QLabel(champion_name)
        name_lbl.setObjectName("matchupChampName")
        name_lbl.setWordWrap(True)
        name_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        name_box.addWidget(name_lbl)

        games_count_val = lane_games or overall_games
        games_sub = QLabel(
            f"{games_count_val:,}".replace(",", ".") + " Games"
            if games_count_val
            else "Match V5"
        )
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
            f"<b>Winrate en línea ({primary_role or 'Predilecta'}):</b> {win_rate_lane:.1%}"
            + (
                f" ({lane_games:,} partidas)<br/>".replace(",", ".")
                if lane_games
                else "<br/>"
            )
            + f"<b>Winrate General (Overall):</b> {win_rate_overall:.1%}"
            + (
                f" ({overall_games:,} partidas)<br/>".replace(",", ".")
                if overall_games
                else "<br/>"
            )
            + (f"<br/><i>{tip}</i>" if tip else "")
        )
        card.setToolTip(tooltip_text)
        name_lbl.setToolTip(tooltip_text)
        games_sub.setToolTip(tooltip_text)
        lane_badge.setToolTip(tooltip_text)
        overall_lbl.setToolTip(tooltip_text)

        return card

    def _load_editor(self, index: int) -> None:
        if 0 <= index < len(self.champions):
            self.edit_text.setPlainText(
                json.dumps(self.champions[index], ensure_ascii=False, indent=2)
            )

    def _save_editor(self) -> None:
        """Valida y persiste el perfil del editor sin alterar su matriz; retorna None."""
        try:
            value = json.loads(self.edit_text.toPlainText())
            self._validate(value)
            self.champions[self.edit_combo.currentIndex()] = value
            self._repositorio_campeones.guardar_perfil(value)
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
                self.status.setText(
                    "No se encontró Gemini API Key. Por favor, configúrala en la pestaña Ajustes."
                )
                return

            champ_data = json.loads(self.edit_text.toPlainText())
            character_name = champ_data.get(
                "character", champ_data.get("basic_info", {}).get("name", "Campeón")
            )

            self.reanalyze_champ_btn.setEnabled(False)
            self.status.setText(
                f"Re-analizando a '{character_name}' con IA (Gemini)... Por favor espera."
            )

            self._ai_worker = ChampionAIWorker(champ_data, gemini_key, parent=self)
            self._ai_worker.finished_reanalysis.connect(self._on_ai_reanalysis_finished)
            self._ai_worker.error_occurred.connect(self._on_ai_reanalysis_error)
            self._ai_worker.start()
        except (json.JSONDecodeError, ValueError, OSError) as error:
            self.status.setText(f"Error en datos del campeón: {error}")

    def _on_ai_reanalysis_finished(self, updated_data: dict[str, Any]) -> None:
        self.reanalyze_champ_btn.setEnabled(True)
        self.edit_text.setPlainText(
            json.dumps(updated_data, ensure_ascii=False, indent=2)
        )
        character_name = updated_data.get("character", "Campeón")
        self.status.setText(
            f"✓ '{character_name}' re-analizado con éxito por IA. Pulsa 'Guardar campeón' para conservar los cambios."
        )

    def _on_ai_reanalysis_error(self, error_msg: str) -> None:
        self.reanalyze_champ_btn.setEnabled(True)
        self.status.setText(f"Error al re-analizar con IA: {error_msg}")

    @staticmethod
    def _load_analysis_rank() -> str:
        """Devuelve Esmeralda+ como rango inicial del panel, sin parámetros."""
        return RANGO_PREDETERMINADO

    def _on_rank_changed(self) -> None:
        """Persiste el rango elegido y recarga la variante de la línea activa."""
        rank_key = str(self.analysis_rank_combo.currentData() or RANGO_PREDETERMINADO)
        self.analysis_rank = rank_key
        self._active_variant_key = ""
        self._active_variant = None
        self._ensure_variant()

    def _start_single_champion_winrate_update(self) -> None:
        """Actualiza un campeón guardando su matriz completa rango x línea.

        Es la vía prevista: tras esto, cambiar de rango o de línea en el panel es
        una lectura del JSON, sin ninguna descarga adicional.
        """
        current_champ = self.champion_combo.currentText()
        self._start_winrate_update(target_champion_name=current_champ)

    def _start_all_champions_winrate_update(self) -> None:
        """Actualiza matrices completas de todos los campeones en segundo plano; retorna None."""
        self._start_winrate_update(target_champion_name="")

    def _start_winrate_update(self, target_champion_name: str = "") -> None:
        """Inicia la sincronización pública con U.GG/OP.GG/Lolalytics en un hilo secuencial."""

        if (
            getattr(self, "_winrate_worker", None) is not None
            and self._winrate_worker.isRunning()
        ):
            self.status.setText("Actualización en curso")
            return
        rank_key = str(self.analysis_rank_combo.currentData() or RANGO_PREDETERMINADO)
        rank_label = self.analysis_rank_combo.currentText()
        self._last_rank_label = rank_label
        self._modo_actualizacion = "uno" if target_champion_name else "todos"
        self._actualizacion_activa = True
        self._temporizador_progreso.stop()

        self._marcar_botones_actualizacion(True)
        self.champion_combo.setEnabled(False)
        self.analysis_rank_combo.setEnabled(False)
        self.analysis_lane_combo.setEnabled(False)
        self.winrate_progress_bar.setRange(
            0, 100 if target_champion_name else max(1, len(self.champions))
        )
        self.winrate_progress_bar.setValue(0)
        self.winrate_progress_bar.setVisible(True)
        self.winrate_progress_label.setText("Iniciando...")
        self.winrate_progress_label.setVisible(True)
        logging.getLogger(__name__).info(
            "[update] %s iniciada",
            target_champion_name or "todos los campeones",
        )

        if target_champion_name:
            self.status.setText(
                f"Actualizando {target_champion_name} en todas sus líneas y rangos..."
            )
        else:
            self.status.setText(
                "Actualizando todos los campeones en todas sus líneas y rangos..."
            )

        self._winrate_worker = ChampionScraperWorker(
            target_champion_name=target_champion_name,
            champions_path=self.champions_path,
            rank=rank_key,
            parent=self,
        )
        self._winrate_worker.progress.connect(self._on_winrate_progress)
        self._winrate_worker.finished_scraping.connect(self._on_winrate_finished)
        self._winrate_worker.error_occurred.connect(self._on_winrate_error)
        self._winrate_worker.finished.connect(self._terminar_actualizacion)
        self._winrate_worker.start()

    def _terminar_actualizacion(self) -> None:
        """Libera el actualizador Qt finalizado, reinicia un estado obsoleto y continúa el cierre; retorna None."""
        if self._actualizacion_activa:
            self._actualizacion_activa = False
            self.winrate_progress_bar.setVisible(False)
            self.winrate_progress_bar.reset()
            self.winrate_progress_label.clear()
            self.winrate_progress_label.setVisible(False)
            self._marcar_botones_actualizacion(False)
            logging.getLogger(__name__).debug(
                "[update] actualización cancelada o obsoleta reiniciada"
            )
        actualizador = getattr(self, "_winrate_worker", None)
        self._winrate_worker = None
        if actualizador is not None:
            actualizador.deleteLater()
        if self._cerrando_analisis:
            self.close()

    def _marcar_botones_actualizacion(self, cargando: bool) -> None:
        """Aplica o retira el estado cargando de los botones sin variar sus dimensiones; retorna None."""
        for boton in (self.update_single_champ_btn, self.update_winrates_btn):
            boton.setEnabled(not cargando)
            boton.setProperty("cargando", "true" if cargando else "false")
            boton.style().unpolish(boton)
            boton.style().polish(boton)

    def _ocultar_barra_progreso(self) -> None:
        """Oculta la barra tras el estado de éxito si no hay otra actualización; retorna None."""
        if self._actualizacion_activa:
            return
        self.winrate_progress_bar.setVisible(False)

    def _on_winrate_progress(self, current: int, total: int, name: str) -> None:
        """Muestra el progreso real recibido sin retroceder; retorna None."""
        if total <= 0:
            return
        if self.winrate_progress_bar.maximum() != total:
            self.winrate_progress_bar.setRange(0, total)
        valor = max(self.winrate_progress_bar.value(), max(0, min(current, total)))
        self.winrate_progress_bar.setValue(valor)
        texto = f"{valor}% {name}" if total == 100 else f"{valor}/{total} {name}"
        self.winrate_progress_label.setText(texto[:64])
        self.winrate_progress_label.setToolTip(name)
        logging.getLogger(__name__).debug("[update] progreso: %s", texto)

    def _on_winrate_finished(self, total_champs: int, total_matchups: int) -> None:
        """Completa el progreso al 100 %, presenta el resultado y agenda el ocultado de la barra; retorna None."""
        self._actualizacion_activa = False
        rank_label = getattr(self, "_last_rank_label", "")
        rank_suffix = f" ({rank_label})" if rank_label else ""
        self.winrate_progress_bar.setValue(self.winrate_progress_bar.maximum())
        self.winrate_progress_bar.setVisible(True)
        self.winrate_progress_label.setText(
            f"Datos actualizados correctamente · {total_matchups}/{total_champs} campeones"
            if total_matchups == total_champs
            else f"Actualización completada con errores · {total_matchups} correctos · {total_champs - total_matchups} con error"
        )
        self.winrate_progress_label.setVisible(True)
        self._temporizador_progreso.start(1500)
        self._marcar_botones_actualizacion(False)
        self.champion_combo.setEnabled(True)
        self.analysis_rank_combo.setEnabled(True)
        self.analysis_lane_combo.setEnabled(True)
        self.champions = self._repositorio_campeones.perfiles()
        self._active_variant_key = ""
        self._active_variant = None
        self._lane_wr_cache.clear()
        if total_matchups:
            self.status.setText(
                f"Datos de U.GG/OP.GG/Lolalytics{rank_suffix} actualizados: {total_matchups}/{total_champs} campeón/es sincronizados."
            )
        else:
            self.status.setText(
                "Las fuentes no entregaron todos los datos requeridos; no se modificó el JSON. Revisa tu conexión o el cambio de versión de las fuentes."
            )
        logging.getLogger(__name__).info(
            "[update] completada: %s/%s campeones", total_matchups, total_champs
        )
        self._refresh_analysis()

    def _on_winrate_error(self, error_msg: str) -> None:
        """Detiene el progreso, restaura controles y presenta error_msg en el área de estado; retorna None."""
        self._actualizacion_activa = False
        self._temporizador_progreso.stop()
        self.winrate_progress_bar.setVisible(False)
        self.winrate_progress_label.setText(
            "Error en la actualización · revisa el registro"
        )
        self.winrate_progress_label.setVisible(True)
        self._marcar_botones_actualizacion(False)
        self.champion_combo.setEnabled(True)
        self.analysis_rank_combo.setEnabled(True)
        self.analysis_lane_combo.setEnabled(True)
        logging.getLogger(__name__).error(
            "[update] falló la sincronización manual: %s", error_msg
        )
        self.status.setText(
            "No se pudieron actualizar las estadísticas. Inténtalo de nuevo."
        )

    def _load_item_editor(self, index: int) -> None:
        if 0 <= index < len(self.items):
            self.item_text.setPlainText(
                json.dumps(self.items[index], ensure_ascii=False, indent=2)
            )

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
            self.items_path.write_text(
                json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.status.setText(
                f"Sinergias y contrapesos recalculados matemáticamente para {value.get('item', 'el objeto')}."
            )
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
            self.item_combo.addItems(
                [entry.get("basic_info", {}).get("name", "") for entry in self.items]
            )
            idx = self.item_combo.findText(current_name)
            if idx >= 0:
                self.item_combo.setCurrentIndex(idx)
            elif len(self.items) > 0:
                self.item_combo.setCurrentIndex(0)
            self.item_combo.blockSignals(False)
            curr_idx = self.item_combo.currentIndex()
            if 0 <= curr_idx < len(self.items):
                self.item_text.setPlainText(
                    json.dumps(self.items[curr_idx], ensure_ascii=False, indent=2)
                )
            self.status.setText(
                f"Objetos reconstruidos y sinergias recalculadas con éxito para los {count} objetos desde Data Dragon."
            )
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
            self.items_path.write_text(
                json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.status.setText(
                "Objeto guardado y sinergias recalculadas correctamente."
            )
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
        allowed = {
            "Bruiser",
            "Diver",
            "Assassin",
            "Skirmisher",
            "Marksman",
            "Mage",
            "Enchanter",
            "Vanguard",
            "Warden",
            "Juggernaut",
        }
        if basic.get("play_style") not in allowed:
            raise ValueError("play_style no permitido.")
        if basic.get("damage_type") not in {"AD", "AP", "True", "Hybrid"}:
            raise ValueError("damage_type no permitido.")
        if basic.get("resource_type") not in {
            "Mana",
            "Energy",
            "Fury",
            "Health",
            "Rage",
            "Courage",
            "Shield",
            "None",
            "Flow",
            "Ferocity",
            "Heat",
        }:
            raise ValueError("resource_type no permitido.")
        if (
            not 1 <= int(basic.get("difficulty_floor", 0)) <= 10
            or not 1 <= int(basic.get("difficulty_ceiling", 0)) <= 10
        ):
            raise ValueError("difficulty debe estar entre 1 y 10.")
        for section_name in (
            "combat_attributes",
            "resistances_and_survivability",
            "map_and_control",
        ):
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
        if not isinstance(value, dict):
            raise ValueError("El objeto debe ser JSON.")
        basic = value.get("basic_info", {})
        if basic.get("tier") != "Legendary":
            raise ValueError("Solo se pueden editar objetos Legendary.")
        if basic.get("item_group") not in {
            "Fatality",
            "Blight",
            "Annul",
            "Boots",
            "Lifeline",
            "Hydra",
            "Quicksilver",
            "Glory",
            "Support",
            "None",
        }:
            raise ValueError("item_group no permitido.")
        allowed_stats = {
            "attack_damage",
            "ability_power",
            "armor_penetration_percent",
            "magic_penetration_percent",
            "magic_penetration_flat",
            "lethality",
            "critical_strike_chance_percent",
            "attack_speed_percent",
            "life_steal_percent",
            "omnivamp_percent",
            "health",
            "mana",
            "armor",
            "magic_resistance",
            "ability_haste",
            "base_health_regeneration_percent",
            "base_mana_regeneration_percent",
            "movement_speed_flat",
            "movement_speed_percent",
            "heal_and_shield_power_percent",
            "tenacity",
        }
        if any(key not in allowed_stats for key in value.get("stats", {})):
            raise ValueError("Estadística de objeto no permitida.")
        if any(
            not 0 <= float(number) <= 3.5
            for number in value.get("synergy_multipliers", {}).values()
        ):
            raise ValueError("Multiplicador fuera de rango.")

    @staticmethod
    def _load(path: Path) -> Any:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, (list, dict)) else []
        except (OSError, json.JSONDecodeError):
            return []
