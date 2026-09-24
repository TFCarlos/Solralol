from __future__ import annotations

import json
import math
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QRect, Signal, QSignalBlocker
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.lcu_service import LCUService
from app.ui.local_analysis_dialog import DamageBarWidget
from app.ui.draft_icon_cache import DraftIconCache
from data_dragon import (
    get_champion_icon_path,
    get_item_icon_path,
    get_latest_version,
    get_rune_icon_path,
    get_spell_icon_path,
)


class DraftPowerCurveWidget(QWidget):
    """Widget de dibujo vectorizado para comparar las curvas de poder de Aliados vs Enemigos."""

    TIME_BRACKETS = ["0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40+"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.my_team_curve: dict[str, float] = {b: 50.0 for b in self.TIME_BRACKETS}
        self.enemy_team_curve: dict[str, float] = {b: 50.0 for b in self.TIME_BRACKETS}
        self.power_spike_label: str = "Calculando..."
        self.scope_label: str = "Equipo vs equipo"

    def set_data(self, my_curve: dict[str, float], enemy_curve: dict[str, float], spike_label: str, scope_label: str = "Equipo vs equipo") -> None:
        self.my_team_curve = my_curve
        self.enemy_team_curve = enemy_curve
        self.power_spike_label = spike_label
        self.scope_label = scope_label
        self.setToolTip(f"⚡ Power Spike: {spike_label}")
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Fondo del widget
        painter.fillRect(0, 0, w, h, QColor(15, 23, 42))

        # Márgenes
        margin_left = 50
        margin_right = 30
        margin_bottom = 32

        # Medir la cabecera antes de reservar el área de trazado.
        title_font = QFont("Segoe UI", 10, QFont.Weight.Bold)
        spike_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        legend_font = QFont("Segoe UI", 9)
        painter.setFont(title_font)
        title_fm = painter.fontMetrics()
        title_text = f"Evolución de Win Rate · {self.scope_label} (0m - 40m+)"
        painter.setFont(spike_font)
        spike_fm = painter.fontMetrics()
        spike_text = f"⚡ Power Spike: {self.power_spike_label}"
        badge_h = max(title_fm.height(), spike_fm.height()) + 8
        badge_w = spike_fm.horizontalAdvance(spike_text) + 20
        badge_x = margin_left + title_fm.horizontalAdvance(title_text) + 16
        painter.setFont(legend_font)
        legend_fm = painter.fontMetrics()
        my_legend_w = legend_fm.horizontalAdvance("━ Mi Equipo")
        enemy_legend_w = legend_fm.horizontalAdvance("━ Enemigos")
        legend_w = my_legend_w + 20 + enemy_legend_w
        legend_x = w - margin_right - legend_w
        # En ventanas estrechas, solo la leyenda pasa a una segunda fila.
        legend_below = badge_x + badge_w + 16 > legend_x
        legend_y = 8 + badge_h + 4 if legend_below else 8
        badge_w = min(badge_w, max(20, w - margin_right - badge_x))
        spike_text = spike_fm.elidedText(
            spike_text, Qt.TextElideMode.ElideRight, max(0, badge_w - 20)
        )
        margin_top = legend_y + badge_h + 22

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        if plot_w <= 0 or plot_h <= 0:
            return

        # La escala base 47–53% ocupa toda la altura, en lugar de quedar
        # comprimida dentro de 40–60%. Se amplía si alguna curva lo necesita.
        values = [
            curve.get(bracket, 50.0)
            for curve in (self.my_team_curve, self.enemy_team_curve)
            for bracket in self.TIME_BRACKETS
        ]
        half_range = max(3, math.ceil(max(abs(value - 50.0) for value in values) + 0.5))
        min_v, max_v = 50.0 - half_range, 50.0 + half_range

        def y_pos(val: float) -> float:
            v_clamped = max(min_v, min(max_v, val))
            ratio = (v_clamped - min_v) / (max_v - min_v)
            return margin_top + plot_h * (1.0 - ratio)

        # Rejilla horizontal
        grid_pen = QPen(QColor(255, 255, 255, 25), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        font_grid = QFont("Segoe UI", 9)
        painter.setFont(font_grid)

        # Separación basada en la fuente real; conservar siempre el 50%.
        px_per_step = plot_h / (max_v - min_v)
        label_step = max(1, math.ceil((painter.fontMetrics().height() + 4) / px_per_step))
        first_tick = 50 + math.ceil((min_v - 50) / label_step) * label_step
        for step_v in range(first_tick, int(max_v) + 1, label_step):
            yp = y_pos(float(step_v))
            painter.drawLine(int(margin_left), int(yp), int(w - margin_right), int(yp))
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(5, int(yp) + 4, f"{step_v}%")
            painter.setPen(grid_pen)

        # Línea de balance 50%
        y50 = y_pos(50.0)
        painter.setPen(QPen(QColor(100, 116, 139, 120), 1.5, Qt.PenStyle.SolidLine))
        painter.drawLine(int(margin_left), int(y50), int(w - margin_right), int(y50))

        # Puntos x
        n_points = len(self.TIME_BRACKETS)
        step_x = plot_w / max(1, n_points - 1)
        x_coords = [margin_left + i * step_x for i in range(n_points)]

        # Etiquetas de tiempo en X
        painter.setPen(QColor(148, 163, 184))
        for i, b_text in enumerate(self.TIME_BRACKETS):
            xp = x_coords[i]
            painter.drawText(int(xp - 18), int(h - 12), f"{b_text}m")

        # Puntos y trayectorias
        my_pts = [(x_coords[i], y_pos(self.my_team_curve.get(b, 50.0))) for i, b in enumerate(self.TIME_BRACKETS)]
        en_pts = [(x_coords[i], y_pos(self.enemy_team_curve.get(b, 50.0))) for i, b in enumerate(self.TIME_BRACKETS)]

        # Trazar curva enemigo (Rojo Coral)
        en_path = QPainterPath()
        en_path.moveTo(en_pts[0][0], en_pts[0][1])
        for xp, yp in en_pts[1:]:
            en_path.lineTo(xp, yp)
        painter.setPen(QPen(QColor(239, 68, 68), 2.5))
        painter.drawPath(en_path)

        # Trazar curva aliados (Verde Esmeralda)
        my_path = QPainterPath()
        my_path.moveTo(my_pts[0][0], my_pts[0][1])
        for xp, yp in my_pts[1:]:
            my_path.lineTo(xp, yp)
        painter.setPen(QPen(QColor(16, 185, 129), 3.0))
        painter.drawPath(my_path)

        # Dibujar nodos
        for i, (xp, yp) in enumerate(my_pts):
            val = self.my_team_curve.get(self.TIME_BRACKETS[i], 50.0)
            painter.setBrush(QBrush(QColor(16, 185, 129)))
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.drawEllipse(int(xp - 4), int(yp - 4), 8, 8)
            # Valor texto arriba
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(QColor(16, 185, 129))
            painter.drawText(int(xp - 14), int(yp - 8), f"{val:.1f}%")

        for i, (xp, yp) in enumerate(en_pts):
            val = self.enemy_team_curve.get(self.TIME_BRACKETS[i], 50.0)
            painter.setBrush(QBrush(QColor(239, 68, 68)))
            painter.setPen(QPen(QColor(255, 255, 255), 1.5))
            painter.drawEllipse(int(xp - 3), int(yp - 3), 6, 6)

        # Título y Power Spike comparten fila y alineación vertical.
        painter.setFont(title_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            QRect(margin_left, 8, badge_x - margin_left - 16, badge_h),
            Qt.AlignmentFlag.AlignVCenter, title_text,
        )
        painter.setFont(spike_font)
        painter.setBrush(QBrush(QColor(30, 41, 59)))
        painter.setPen(QPen(QColor(16, 185, 129), 1.5))
        painter.drawRoundedRect(badge_x, 8, badge_w, badge_h, 6, 6)
        painter.setPen(QColor(16, 185, 129))
        painter.drawText(
            QRect(badge_x + 10, 8, badge_w - 20, badge_h),
            Qt.AlignmentFlag.AlignVCenter, spike_text,
        )

        painter.setFont(legend_font)
        painter.drawText(
            QRect(legend_x, legend_y, my_legend_w, badge_h),
            Qt.AlignmentFlag.AlignVCenter, "━ Mi Equipo",
        )
        painter.setPen(QColor(239, 68, 68))
        painter.drawText(
            QRect(legend_x + my_legend_w + 20, legend_y, enemy_legend_w, badge_h),
            Qt.AlignmentFlag.AlignVCenter, "━ Enemigos",
        )


class DraftToolDialog(QDialog):
    """Diálogo completo de la Herramienta de Draft en tiempo real."""

    ROLES = list(DraftAnalyzerService.ROLES)

    # Marca de línea probable: en el draft nadie sabe la línea real del rival.
    PROBABLE_ROLE_PREFIX = "~"

    # Marcador de línea desconocida: no hay dato del cliente ni del campeón.
    UNKNOWN_ROLE = "?"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Solralol — Herramienta de Draft en Tiempo Real")
        self.resize(1500, 920)
        self.setMinimumSize(1180, 760)
        self.setStyleSheet("""
            QDialog { background: #0B0F19; color: #E5EEF9; font-family: 'Segoe UI'; }
            QComboBox { background: #111C30; border: 1px solid #2E405D; border-radius: 5px; padding: 3px 7px; min-height: 22px; }
            QComboBox:hover { border-color: #38BDF8; }
            QComboBox:disabled { color: #C7D2E2; background: #0E1728; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #52677F; border-radius: 4px; background: #101A2D; }
            QCheckBox::indicator:checked { background: #10B981; border-color: #6EE7B7; }
            QTableWidget { background: #0E1728; alternate-background-color: #111D32; border: 1px solid #2A3C58; gridline-color: #293B55; border-radius: 6px; }
            QHeaderView::section { background: #1B2A40; color: #DCE9FA; border: 0; border-bottom: 1px solid #334A69; padding: 5px; font-weight: 600; }
        """)

        self.analyzer = DraftAnalyzerService()
        self.lcu_service = LCUService()
        # La versión del catálogo instalado basta para los assets; abrir el
        # draft no debe esperar una petición HTTP a versions.json.
        self.dd_version = self.analyzer.version
        self._icon_cache = DraftIconCache(self)

        self.all_champion_names = sorted(list({
            prof.get("character") or prof.get("basic_info", {}).get("name")
            for prof in self.analyzer.champions.values()
            if prof.get("character") or prof.get("basic_info", {}).get("name")
        }))

        self.my_team_combo_widgets: list[QComboBox] = []
        self.enemy_team_combo_widgets: list[QComboBox] = []
        self.my_team_pick_state_widgets: list[QCheckBox] = []
        self.enemy_team_pick_state_widgets: list[QCheckBox] = []
        self.my_team_role_combos: list[QComboBox] = []
        self.enemy_team_role_labels: list[QLabel] = []
        # Línea efectiva por fila (sin la marca de hipótesis) y qué líneas
        # aliadas publicó el cliente como posición asignada.
        self.my_team_roles: list[str] = [""] * len(self.ROLES)
        self.enemy_team_roles: list[str] = [""] * len(self.ROLES)
        self.my_team_roles_from_client: list[bool] = [False] * len(self.ROLES)
        self._local_slot: int | None = None
        self.my_team_icon_labels: list[QLabel] = []
        self.enemy_team_icon_labels: list[QLabel] = []
        self.my_team_matchup_labels: list[QLabel] = []
        self.enemy_team_matchup_labels: list[QLabel] = []
        self.my_header_ban_labels: list[QLabel] = []
        self.enemy_header_ban_labels: list[QLabel] = []
        self.lcu_draft_active = False
        self.curve_scope = "Equipo vs equipo"
        self._last_session_key = None

        self._build_ui()
        self._check_lcu_status()
        self._update_analytics()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. TOP HEADER BAR
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(14, 10, 14, 10)

        title_lbl = QLabel("⚔️ HERRAMIENTA DE DRAFT Y LCU")
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #38BDF8;")

        self.lcu_status_lbl = QLabel("🟡 Comprobando LCU...")
        self.lcu_status_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lcu_status_lbl.setStyleSheet("color: #FBBF24; padding: 4px 10px; background-color: #0F172A; border-radius: 6px;")

        refresh_lcu_btn = QPushButton("🔄 Reconectar LCU")
        refresh_lcu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_lcu_btn.setStyleSheet("background-color: #334155; color: #F8FAFC; border-radius: 6px; padding: 6px 12px; font-weight: bold;")
        refresh_lcu_btn.clicked.connect(self._check_lcu_status)

        # Los datos del jugador local siguen existiendo para la lógica de LCU,
        # pero la cabecera se reserva para los baneos recomendados.
        local_champ_lbl = QLabel("Tu Campeón:")
        local_champ_lbl.setStyleSheet("color: #94A3B8; font-weight: bold;")
        self.local_champ_combo = QComboBox()
        self.local_champ_combo.addItems([""] + self.all_champion_names)
        self.local_champ_combo.setCurrentText("Aatrox")
        self.local_champ_combo.currentIndexChanged.connect(self._on_draft_changed)

        local_role_lbl = QLabel("Tu Rol:")
        local_role_lbl.setStyleSheet("color: #94A3B8; font-weight: bold;")
        self.local_role_combo = QComboBox()
        self.local_role_combo.addItems(self.ROLES)
        self.local_role_combo.setCurrentText("Top")
        self.local_role_combo.currentIndexChanged.connect(self._on_draft_changed)

        header_layout.addWidget(title_lbl)
        header_layout.addWidget(self.lcu_status_lbl)
        header_layout.addWidget(refresh_lcu_btn)
        manual_role_label = QLabel("Mi rol:")
        manual_role_label.setStyleSheet("color: #94A3B8; font-weight: bold;")
        header_layout.addWidget(manual_role_label)
        header_layout.addWidget(self.local_role_combo)
        header_layout.addStretch()
        bans_header = QFrame()
        bans_header.setStyleSheet("background: #111C30; border: 1px solid #2D405D; border-radius: 6px;")
        bans_header_layout = QHBoxLayout(bans_header)
        bans_header_layout.setContentsMargins(8, 4, 8, 4)
        bans_header_layout.setSpacing(5)
        for color, collection in (
            ("#2563EB", self.my_header_ban_labels),
            ("#DC2626", self.enemy_header_ban_labels),
        ):
            for _ in range(5):
                ban_label = QLabel()
                ban_label.setFixedSize(30, 30)
                ban_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                ban_label.setStyleSheet(
                    f"color: #CBD5E1; background: #111C30; border: 2px solid {color}; border-radius: 4px;"
                )
                ban_label.setText("—")
                bans_header_layout.addWidget(ban_label)
                collection.append(ban_label)
        header_layout.addWidget(bans_header)

        main_layout.addWidget(header_frame)

        # 2. SCROLLABLE CONTENT BODY
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        # 2A. GRID DE EQUIPOS 5v5
        teams_frame = QFrame()
        teams_frame.setObjectName("draftTeamsSection")
        teams_frame.setStyleSheet("""
            QFrame#draftTeamsSection {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #16213A, stop:1 #101B2D);
                border: 1px solid #2C3D57; border-radius: 12px;
            }
            QLabel { background: transparent; border: none; padding: 0px; }
            QFrame#draftAllyBanner {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #123129, stop:1 #141F35);
                border: 1px solid #245C4C; border-left: 4px solid #10B981;
                border-radius: 9px;
            }
            QFrame#draftEnemyBanner {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #141F35, stop:1 #30151B);
                border: 1px solid #633342; border-left: 4px solid #F87171;
                border-radius: 9px;
            }
            QFrame#draftAllySlot {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #16263C, stop:1 #131F33);
                border: 1px solid #2C4260; border-left: 3px solid #10B981;
                border-radius: 9px;
            }
            QFrame#draftAllySlot:hover {
                border-color: #34D399;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1A2F49, stop:1 #152438);
            }
            QFrame#draftEnemySlot {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #131F33, stop:1 #26171F);
                border: 1px solid #4C3040; border-left: 3px solid #F87171;
                border-radius: 9px;
            }
            QFrame#draftEnemySlot:hover {
                border-color: #FB7185;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #152438, stop:1 #2E1A23);
            }
            QLabel#draftSlotIcon {
                background: #0B1424; border: 2px solid #2E4A6B;
                border-radius: 8px; padding: 1px;
            }
            QLabel#draftSlotWr {
                background: #131E33; border: 1px solid #2C3D57;
                border-radius: 9px; font-size: 12px; font-weight: 700;
            }
            QLabel#draftEnemyRole { font-size: 11px; padding-left: 8px; }
            QLabel#draftColumnCaption {
                color: #5B6E8A; font-size: 10px; font-weight: 700;
                letter-spacing: 1px;
            }
            QComboBox#draftPickCombo { font-size: 12px; font-weight: 600; }
            QComboBox#draftRoleCombo { font-size: 11px; font-weight: 700; }
            QComboBox#draftPickCombo[empty="true"] { color: #64748B; font-style: italic; }
        """)
        teams_layout = QVBoxLayout(teams_frame)
        teams_layout.setContentsMargins(14, 14, 14, 14)
        teams_layout.setSpacing(10)

        teams_header = QHBoxLayout()
        teams_title = QLabel("COMPOSICIONES 5v5")
        teams_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        teams_title.setStyleSheet("color: #93C5FD; letter-spacing: 1px;")
        teams_header.addWidget(teams_title)
        teams_header.addStretch()
        teams_hint = QLabel("✓ pick confirmado · casilla sin marcar = pre-pick")
        teams_hint.setStyleSheet("color: #9CAEC9; font-size: 11px;")
        teams_header.addWidget(teams_hint)
        teams_layout.addLayout(teams_header)

        teams_grid_layout = QHBoxLayout()
        teams_grid_layout.setSpacing(12)

        # Columna Mi Equipo
        my_team_box = QVBoxLayout()
        my_team_box.setSpacing(8)

        my_banner = QFrame()
        my_banner.setObjectName("draftAllyBanner")
        my_team_title_row = QHBoxLayout(my_banner)
        my_team_title_row.setContentsMargins(14, 8, 12, 8)
        my_team_title_row.setSpacing(10)
        my_team_title = QLabel("🛡️ MI EQUIPO")
        my_team_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        my_team_title.setStyleSheet("color: #6EE7B7;")
        self.my_team_overall_lbl = QLabel("WR —")
        self.my_team_overall_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.my_team_overall_lbl.setToolTip(
            "Media de los win rates OVERALL de los campeones con al menos un pick/pre-pick. "
            "Referencia para estimar la probabilidad de victoria, no es una probabilidad calibrada."
        )
        self.my_team_overall_lbl.setStyleSheet(
            "color: #94A3B8; background: #131E33; border: 1px solid #2C3D57; "
            "border-radius: 10px; padding: 4px 12px; font-size: 12px; font-weight: 800;"
        )
        my_team_title_row.addWidget(my_team_title)
        my_team_title_row.addStretch()
        my_team_title_row.addWidget(self.my_team_overall_lbl)
        my_team_box.addWidget(my_banner)
        my_team_box.addLayout(self._slot_captions_layout())

        for i in range(5):
            slot_card = QFrame()
            slot_card.setObjectName("draftAllySlot")
            slot_h = QHBoxLayout(slot_card)
            slot_h.setContentsMargins(12, 8, 12, 8)
            slot_h.setSpacing(8)
            role_cb = QComboBox()
            role_cb.setObjectName("draftRoleCombo")
            role_cb.addItems(self.ROLES)
            role_cb.setCurrentIndex(i % 5)
            role_cb.setFixedWidth(80)
            role_cb.setMinimumHeight(26)
            role_cb.currentIndexChanged.connect(self._on_draft_changed)

            champ_cb = QComboBox()
            champ_cb.setObjectName("draftPickCombo")
            champ_cb.setProperty("empty", True)
            champ_cb.addItems(["-- Vacío --"] + self.all_champion_names)
            champ_cb.setMinimumHeight(26)
            champ_cb.currentIndexChanged.connect(self._on_draft_changed)

            icon_lbl = QLabel("—")
            icon_lbl.setObjectName("draftSlotIcon")
            icon_lbl.setFixedSize(36, 36)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            matchup_lbl = QLabel("—")
            matchup_lbl.setObjectName("draftSlotWr")
            matchup_lbl.setFixedWidth(56)
            matchup_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            matchup_lbl.setToolTip("Win rate overall del campeón.")

            state_cb = QCheckBox()
            state_cb.setFixedWidth(26)
            state_cb.setToolTip("Marcado: campeón seleccionado. Sin marcar: pre-seleccionado.")
            state_cb.toggled.connect(self._on_draft_changed)

            self.my_team_role_combos.append(role_cb)
            self.my_team_combo_widgets.append(champ_cb)
            self.my_team_pick_state_widgets.append(state_cb)
            self.my_team_icon_labels.append(icon_lbl)
            self.my_team_matchup_labels.append(matchup_lbl)

            slot_h.addWidget(role_cb)
            slot_h.addWidget(icon_lbl)
            slot_h.addWidget(champ_cb, 1)
            slot_h.addWidget(matchup_lbl)
            slot_h.addWidget(state_cb)
            my_team_box.addWidget(slot_card)

        # Columna Enemigos
        enemy_team_box = QVBoxLayout()
        enemy_team_box.setSpacing(8)

        enemy_banner = QFrame()
        enemy_banner.setObjectName("draftEnemyBanner")
        enemy_team_title_row = QHBoxLayout(enemy_banner)
        enemy_team_title_row.setContentsMargins(14, 8, 12, 8)
        enemy_team_title_row.setSpacing(10)
        enemy_team_title = QLabel("⚔️ EQUIPO ENEMIGO")
        enemy_team_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        enemy_team_title.setStyleSheet("color: #FCA5A5;")
        self.enemy_team_overall_lbl = QLabel("WR —")
        self.enemy_team_overall_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.enemy_team_overall_lbl.setToolTip(
            "Media de los win rates OVERALL de los campeones enemigos con al menos un pick/pre-pick. "
            "Referencia para estimar la probabilidad de victoria, no es una probabilidad calibrada."
        )
        self.enemy_team_overall_lbl.setStyleSheet(
            "color: #94A3B8; background: #131E33; border: 1px solid #2C3D57; "
            "border-radius: 10px; padding: 4px 12px; font-size: 12px; font-weight: 800;"
        )
        enemy_team_title_row.addWidget(enemy_team_title)
        enemy_team_title_row.addStretch()
        enemy_team_title_row.addWidget(self.enemy_team_overall_lbl)
        enemy_team_box.addWidget(enemy_banner)
        enemy_team_box.addLayout(self._slot_captions_layout())

        for i in range(5):
            slot_card = QFrame()
            slot_card.setObjectName("draftEnemySlot")
            slot_h = QHBoxLayout(slot_card)
            slot_h.setContentsMargins(12, 8, 12, 8)
            slot_h.setSpacing(8)
            role_lbl = QLabel("—")
            role_lbl.setObjectName("draftEnemyRole")
            role_lbl.setFixedWidth(80)
            role_lbl.setStyleSheet("color: #64748B; font-weight: 700;")
            role_lbl.setToolTip("Línea del rival: el cliente no la publica.")

            champ_cb = QComboBox()
            champ_cb.setObjectName("draftPickCombo")
            champ_cb.setProperty("empty", True)
            champ_cb.addItems(["-- Vacío --"] + self.all_champion_names)
            champ_cb.setMinimumHeight(26)
            champ_cb.currentIndexChanged.connect(self._on_draft_changed)

            icon_lbl = QLabel("—")
            icon_lbl.setObjectName("draftSlotIcon")
            icon_lbl.setFixedSize(36, 36)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            matchup_lbl = QLabel("—")
            matchup_lbl.setObjectName("draftSlotWr")
            matchup_lbl.setFixedWidth(56)
            matchup_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            matchup_lbl.setToolTip("Win rate overall del campeón.")

            state_cb = QCheckBox()
            state_cb.setFixedWidth(26)
            state_cb.setToolTip("Marcado: campeón seleccionado. Sin marcar: pre-seleccionado.")
            state_cb.toggled.connect(self._on_draft_changed)

            self.enemy_team_combo_widgets.append(champ_cb)
            self.enemy_team_pick_state_widgets.append(state_cb)
            self.enemy_team_role_labels.append(role_lbl)
            self.enemy_team_icon_labels.append(icon_lbl)
            self.enemy_team_matchup_labels.append(matchup_lbl)

            slot_h.addWidget(role_lbl)
            slot_h.addWidget(icon_lbl)
            slot_h.addWidget(champ_cb, 1)
            slot_h.addWidget(matchup_lbl)
            slot_h.addWidget(state_cb)
            enemy_team_box.addWidget(slot_card)

        teams_grid_layout.addLayout(my_team_box)
        teams_grid_layout.addWidget(QFrame(frameShape=QFrame.Shape.VLine, styleSheet="color: #334155;"))
        teams_grid_layout.addLayout(enemy_team_box)
        teams_layout.addLayout(teams_grid_layout)
        teams_layout.addLayout(self._create_damage_comparison_layout())

        content_layout.addWidget(teams_frame)

        # 2B. DESGRASE DE DAÑO Y PODER
        analytics_frame = QFrame()
        analytics_frame.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        analytics_layout = QHBoxLayout(analytics_frame)
        analytics_layout.setContentsMargins(12, 12, 12, 12)

        scope_layout = QVBoxLayout()
        scope_layout.setSpacing(6)
        for scope in ["Equipo vs equipo", "Top", "Jungle", "Mid", "Bot", "Support"]:
            button = QPushButton(scope)
            button.setCheckable(True)
            button.setChecked(scope == self.curve_scope)
            button.setProperty("curve_scope", scope)
            button.setStyleSheet(
                "QPushButton { background: #111C30; border: 1px solid #334A69; border-radius: 6px; padding: 5px 10px; color: #BFD0E7; }"
                "QPushButton:checked { background: #1D4ED8; border-color: #60A5FA; color: white; font-weight: 700; }"
            )
            button.clicked.connect(self._set_curve_scope)
            scope_layout.addWidget(button)
        scope_layout.addStretch()
        analytics_layout.addLayout(scope_layout)

        # Grafica de curva de poder
        self.power_curve_widget = DraftPowerCurveWidget()
        analytics_layout.addWidget(self.power_curve_widget, 1)

        content_layout.addWidget(analytics_frame)

        # 2C. BANEOS RECOMENDADOS (3 TARJETAS)
        rec_frame = QFrame()
        rec_frame.setObjectName("draftBansSection")
        rec_frame.setStyleSheet("""
            QFrame#draftBansSection {
                background: #101B2D; border: 1px solid #2C3D57; border-radius: 12px;
            }
            QLabel {
                background: transparent; border: none; padding: 0px;
            }
            QFrame#draftBanCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1D2B42, stop:1 #111D30);
                border: 1px solid #35445E; border-top: 2px solid #9F485F;
                border-radius: 10px;
            }
            QFrame#draftBanCard:hover { border-color: #CE7086; }
            QLabel#draftBanPortrait {
                background: #0B1424; border: 2px solid #AD6478;
                border-radius: 8px; padding: 2px;
            }
            QLabel#draftBanRate {
                background: #352333; border: 1px solid #614054;
                border-radius: 9px; padding: 3px 12px; font-size: 13px;
            }
        """)
        rec_layout = QVBoxLayout(rec_frame)
        rec_layout.setContentsMargins(16, 14, 16, 16)
        rec_layout.setSpacing(12)

        bans_header = QHBoxLayout()
        bans_title = QLabel("BANEOS RECOMENDADOS")
        bans_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        bans_title.setStyleSheet("color: #FDA4AF; letter-spacing: 1px;")
        bans_header.addWidget(bans_title)
        bans_header.addStretch()
        bans_hint = QLabel("Win rate de tu campeón frente al rival")
        bans_hint.setStyleSheet("color: #9CAEC9; font-size: 11px;")
        bans_header.addWidget(bans_hint)
        rec_layout.addLayout(bans_header)

        bans_row = QHBoxLayout()
        bans_row.setSpacing(12)
        self.ban_card_widgets: list[dict[str, QLabel]] = []
        for _ in range(3):
            card = QFrame()
            card.setObjectName("draftBanCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(7)
            icon_lbl = QLabel("—")
            icon_lbl.setObjectName("draftBanPortrait")
            icon_lbl.setFixedSize(72, 72)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl = QLabel("Sin dato")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #F4F7FF;")
            wr_lbl = QLabel("WR —")
            wr_lbl.setObjectName("draftBanRate")
            wr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wr_lbl.setStyleSheet("color: #94A3B8; font-weight: 700;")
            tip_lbl = QLabel("")
            tip_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            tip_lbl.setWordWrap(True)
            tip_lbl.setStyleSheet("color: #ADBED6; font-size: 11px;")
            card_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
            card_layout.addWidget(name_lbl)
            card_layout.addWidget(wr_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
            card_layout.addSpacing(2)
            card_layout.addWidget(tip_lbl, 1)
            bans_row.addWidget(card, 1)
            self.ban_card_widgets.append({"icon": icon_lbl, "name": name_lbl, "wr": wr_lbl, "tip": tip_lbl})
        rec_layout.addLayout(bans_row)

        content_layout.addWidget(rec_frame)

        # 2D. IMPORTACIÓN AL CLIENTE (LCU): BUILD, RUNAS Y HECHIZOS
        import_frame = QFrame()
        import_frame.setObjectName("draftImportSection")
        import_frame.setStyleSheet("""
            QFrame#draftImportSection {
                background: #101B2D; border: 1px solid #2C3D57; border-radius: 12px;
            }
            QLabel { background: transparent; border: none; padding: 0px; color: #ADBED6; }
            QFrame#importBuildCard, QFrame#importSpellsCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #192940, stop:1 #111D30);
                border: 1px solid #30445F; border-radius: 10px;
            }
            QFrame#importBuildCard { border-top: 2px solid #5283BA; }
            QFrame#importSpellsCard { border-top: 2px solid #B89B62; }
            QLabel#importItemIcon {
                background: #0A1424; border: 1px solid #466080; border-radius: 6px;
            }
            QLabel#importItemIcon:hover { border-color: #93C5FD; }
            QLabel#importBootsIcon {
                background: #241F1B; border: 2px solid #C4A263; border-radius: 6px;
            }
            QLabel#importSpellIcon {
                background: #0A1424; border: 1px solid #8E7A55; border-radius: 7px;
            }
            QLabel#importNote {
                color: #ADBED6; font-size: 11px;
                background: #0E1A2B; border-radius: 6px; padding: 9px;
            }
            QLabel#importRuneIcon {
                background: #101B2D; border: 1px solid #30445F; border-radius: 5px;
            }
            QLabel#importRuneIcon:hover { border-color: #A5B8D2; }
        """)
        import_layout = QVBoxLayout(import_frame)
        import_layout.setContentsMargins(16, 14, 16, 16)
        import_layout.setSpacing(12)

        import_header = QHBoxLayout()
        import_title = QLabel("IMPORTACIÓN AL CLIENTE")
        import_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        import_title.setStyleSheet("color: #C4B5FD; letter-spacing: 1px;")
        import_header.addWidget(import_title)
        import_header.addStretch()
        import_hint = QLabel("Build · Runas U.GG / Lolalytics · Hechizos")
        import_hint.setStyleSheet("color: #9CAEC9; font-size: 11px;")
        import_header.addWidget(import_hint)
        import_layout.addLayout(import_header)

        import_row = QHBoxLayout()
        import_row.setSpacing(12)

        # --- Columna 1: build de 6 objetos + botas recomendadas ---
        build_card = QFrame()
        build_card.setObjectName("importBuildCard")
        build_box = QVBoxLayout(build_card)
        build_box.setContentsMargins(12, 12, 12, 12)
        build_box.setSpacing(12)
        build_header = QHBoxLayout()
        build_title = QLabel("BUILD")
        build_title.setStyleSheet("color: #93C5FD; font-size: 12px; font-weight: 700;")
        build_header.addWidget(build_title)
        build_header.addStretch()
        boots_title = QLabel("BOTAS RECOMENDADAS")
        boots_title.setStyleSheet("color: #DEC28D; font-size: 10px; font-weight: 700;")
        build_header.addWidget(boots_title)
        build_box.addLayout(build_header)

        build_body = QHBoxLayout()
        build_body.setSpacing(6)
        self.build_item_labels: list[QLabel] = []
        for _ in range(6):
            item_lbl = QLabel()
            item_lbl.setFixedSize(44, 44)
            item_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item_lbl.setObjectName("importItemIcon")
            item_lbl.setToolTip("Objeto principal de la build")
            build_body.addWidget(item_lbl)
            self.build_item_labels.append(item_lbl)
        arrow = QLabel("→")
        arrow.setStyleSheet("color: #60A5FA; font-size: 14pt; font-weight: 700; background: transparent;")
        build_body.addWidget(arrow)
        self.build_boots_label = QLabel()
        self.build_boots_label.setFixedSize(44, 44)
        self.build_boots_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.build_boots_label.setObjectName("importBootsIcon")
        build_body.addWidget(self.build_boots_label)
        build_body.addStretch()
        build_box.addLayout(build_body)

        self.build_note_lbl = QLabel("")
        self.build_note_lbl.setWordWrap(True)
        self.build_note_lbl.setObjectName("importNote")
        build_box.addWidget(self.build_note_lbl)
        build_box.addStretch()

        self.btn_import_build = QPushButton("↓  Importar build al cliente")
        self.btn_import_build.setToolTip(
            "Crea la página general «Solralol - [campeón] Build» en los conjuntos "
            "de objetos del cliente, disponible para cualquier campeón. Incluye los "
            "6 objetos principales, las botas recomendadas y los objetos "
            "situacionales del campeón (Corta curas, Tanque, Asesino y Utilidad). "
            "En jungla, el bloque inicial (starter) reúne los 3 compañeros de jungla."
        )
        self._style_import_button(self.btn_import_build, "blue")
        self.btn_import_build.clicked.connect(self._import_build)
        build_box.addWidget(self.btn_import_build)
        import_row.addWidget(build_card, 3)

        # --- Columna 2: páginas de runas con iconos ---
        runes_box = QVBoxLayout()
        runes_box.setSpacing(8)
        self.rune_page_rows: dict[int, dict[str, Any]] = {}
        for page_index, source, color in ((1, "U.GG", "#6EE7B7"), (2, "Lolalytics", "#C4B5FD")):
            row_widget = QFrame()
            row_widget.setObjectName(f"importRunePage{page_index}")
            row_widget.setStyleSheet(
                f"QFrame#importRunePage{page_index} {{ background: #111E31; "
                f"border: 1px solid #30445F; border-left: 3px solid {color}; border-radius: 8px; }}"
            )
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)
            header = QHBoxLayout()
            src_lbl = QLabel(f"RUNAS {source.upper()}")
            src_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
            header.addWidget(src_lbl)
            header.addStretch()
            keystone_lbl = QLabel("—")
            keystone_lbl.setStyleSheet("color: #E5EEF9; font-size: 11px; font-weight: 600;")
            header.addWidget(keystone_lbl)
            row_layout.addLayout(header)
            icons_row = QHBoxLayout()
            icons_row.setSpacing(3)
            icon_slots: list[QLabel] = []
            # Keystone + 3 primarias + 2 secundarias + 3 fragmentos.
            for _ in range(9):
                icon_lbl = QLabel()
                icon_lbl.setFixedSize(26, 26)
                icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon_lbl.setObjectName("importRuneIcon")
                icons_row.addWidget(icon_lbl)
                icon_slots.append(icon_lbl)
            icons_row.addStretch()
            row_layout.addLayout(icons_row)
            runes_box.addWidget(row_widget)
            self.rune_page_rows[page_index] = {
                "keystone": keystone_lbl,
                "icons": icon_slots,
                "page": None,
            }

        self.btn_import_ugg = QPushButton("↓  Importar runas · Página 1 U.GG")
        self._style_import_button(self.btn_import_ugg, "green")
        self.btn_import_ugg.clicked.connect(lambda: self._import_runes(page_index=1))

        self.btn_import_lolalytics = QPushButton("↓  Importar runas · Página 2 Lolalytics")
        self._style_import_button(self.btn_import_lolalytics, "purple")
        self.btn_import_lolalytics.clicked.connect(lambda: self._import_runes(page_index=2))

        runes_box.addWidget(self.btn_import_ugg)
        runes_box.addWidget(self.btn_import_lolalytics)
        import_row.addLayout(runes_box, 2)

        # --- Columna 3: hechizos de invocador ---
        spells_card = QFrame()
        spells_card.setObjectName("importSpellsCard")
        spells_box = QVBoxLayout(spells_card)
        spells_box.setContentsMargins(12, 12, 12, 12)
        spells_box.setSpacing(12)
        spells_title = QLabel("HECHIZOS")
        spells_title.setStyleSheet("color: #DEC28D; font-size: 12px; font-weight: 700;")
        spells_box.addWidget(spells_title)
        spells_row = QHBoxLayout()
        self.spell_icon_labels: list[QLabel] = []
        for _ in range(2):
            spell_lbl = QLabel()
            spell_lbl.setFixedSize(48, 48)
            spell_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spell_lbl.setObjectName("importSpellIcon")
            spells_row.addWidget(spell_lbl)
            self.spell_icon_labels.append(spell_lbl)
        spells_row.addStretch()
        spells_box.addLayout(spells_row)
        self.spells_text_lbl = QLabel("")
        self.spells_text_lbl.setWordWrap(True)
        self.spells_text_lbl.setObjectName("importNote")
        spells_box.addWidget(self.spells_text_lbl)
        spells_box.addStretch()

        self.btn_import_spells = QPushButton("↓  Importar hechizos")
        self.btn_import_spells.setToolTip("Importar los dos hechizos de invocador al cliente")
        self._style_import_button(self.btn_import_spells, "blue")
        self.btn_import_spells.clicked.connect(self._import_spells)
        spells_box.addWidget(self.btn_import_spells)
        import_row.addWidget(spells_card, 1)

        import_layout.addLayout(import_row)

        content_layout.addWidget(import_frame)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    @staticmethod
    def _style_import_button(button: QPushButton, tone: str) -> None:
        """Estados coherentes sin propagar estilos a los textos de los paneles."""
        background, border, hover, pressed = {
            "blue": ("#234F8A", "#487BB8", "#2E639F", "#1A3C6A"),
            "green": ("#145C4C", "#2C8C73", "#1C7560", "#104536"),
            "purple": ("#503681", "#8563B7", "#654597", "#3F2967"),
        }[tone]
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoDefault(False)
        button.setMinimumHeight(34)
        button.setStyleSheet(f"""
            QPushButton {{
                background: {background}; color: #F4F7FF;
                border: 1px solid {border}; border-radius: 7px;
                padding: 2px 10px; font-size: 11px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {hover}; border-color: #B8CDEA; }}
            QPushButton:pressed {{ background: {pressed}; }}
            QPushButton:focus {{ border: 2px solid #D9E7FF; }}
            QPushButton:disabled {{ background: #182538; color: #8192AA; border-color: #304057; }}
        """)

    def _create_damage_comparison_layout(self) -> QHBoxLayout:
        """Crea el desglose compacto, integrado bajo las dos composiciones."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)

        my_title = QLabel("🛡 Mi equipo")
        my_title.setFixedWidth(100)
        my_title.setStyleSheet("color: #34D399; font-weight: 700;")
        self.my_damage_bar = DamageBarWidget(50.0, 45.0, 5.0)
        self.my_damage_bar.setToolTip("Distribución estimada de daño físico, mágico y verdadero de tus aliados.")

        versus = QLabel("VS")
        versus.setFixedWidth(30)
        versus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        versus.setStyleSheet("color: #94A3B8; font-weight: 800;")

        self.enemy_damage_bar = DamageBarWidget(50.0, 45.0, 5.0)
        self.enemy_damage_bar.setToolTip("Distribución estimada de daño físico, mágico y verdadero del rival.")
        enemy_title = QLabel("Enemigos ⚔")
        enemy_title.setFixedWidth(100)
        enemy_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        enemy_title.setStyleSheet("color: #FB7185; font-weight: 700;")

        row.addWidget(my_title)
        row.addWidget(self.my_damage_bar, 1)
        row.addWidget(versus)
        row.addWidget(self.enemy_damage_bar, 1)
        row.addWidget(enemy_title)
        return row

    @staticmethod
    def _slot_captions_layout() -> QHBoxLayout:
        """Cabeceras de columna alineadas con el reparto interno de cada tarjeta."""
        captions = QHBoxLayout()
        captions.setSpacing(8)
        captions.setContentsMargins(13, 2, 13, 0)
        for text, width, align, stretch in (
            ("LÍNEA", 80, Qt.AlignmentFlag.AlignLeft, False),
            ("", 36, Qt.AlignmentFlag.AlignCenter, False),
            ("CAMPEÓN", 0, Qt.AlignmentFlag.AlignLeft, True),
            ("WR", 56, Qt.AlignmentFlag.AlignCenter, False),
            ("✓", 26, Qt.AlignmentFlag.AlignCenter, False),
        ):
            caption = QLabel(text)
            caption.setObjectName("draftColumnCaption")
            caption.setAlignment(align)
            if stretch:
                captions.addWidget(caption, 1)
            else:
                caption.setFixedWidth(width)
                captions.addWidget(caption)
        return captions

    def _check_lcu_status(self) -> None:
        if self.lcu_service.is_connected():
            self.lcu_status_lbl.setText("🟢 LCU Conectado")
            self.lcu_status_lbl.setStyleSheet("color: #10B981; padding: 4px 10px; background-color: #0F172A; border-radius: 6px; font-weight: bold;")
            session = self.lcu_service.get_champ_select_session()
            if session:
                self.update_from_lcu_session(session)
        else:
            self.lcu_status_lbl.setText("🟡 Modo Manual / LCU Desconectado")
            self.lcu_status_lbl.setStyleSheet("color: #FBBF24; padding: 4px 10px; background-color: #0F172A; border-radius: 6px; font-weight: bold;")
            self._set_lcu_managed_controls(False)

    def _set_lcu_managed_controls(self, lcu_active: bool) -> None:
        """Bloquea los datos que LCU conoce durante la selección real."""
        if not lcu_active:
            self._last_session_key = None
            # Al volver al modo manual no quedan rastros de líneas deducidas.
            self.my_team_roles_from_client = [False] * len(self.ROLES)
            for combo in [self.local_role_combo, *self.my_team_role_combos]:
                self._clear_role_hints(combo)
        self.lcu_draft_active = lcu_active
        self.local_champ_combo.setEnabled(not lcu_active)
        self.local_role_combo.setEnabled(not lcu_active)
        for widget in (
            self.my_team_combo_widgets
            + self.my_team_role_combos
            + self.my_team_pick_state_widgets
            + self.enemy_team_combo_widgets
            + self.enemy_team_pick_state_widgets
        ):
            widget.setEnabled(not lcu_active)

    @staticmethod
    def _session_key(session: dict[str, Any]) -> tuple:
        """Solo datos visibles: ignorar el temporizador y metadatos del polling."""
        teams = tuple(
            tuple(
                tuple(player.get(field) for field in (
                    "cellId", "championId", "championPickIntent", "assignedPosition"
                ))
                for player in session.get(team, [])[:5]
            )
            for team in ("myTeam", "theirTeam")
        )
        bans = tuple(
            tuple(action.get(field) for field in (
                "championId", "actorCellId", "isAllyAction"
            ))
            for phase in session.get("actions", [])
            for action in phase
            if isinstance(action, dict) and action.get("type") == "ban"
        )
        return session.get("localPlayerCellId"), teams, bans

    def update_from_lcu_session(self, session: dict[str, Any]) -> None:
        """Una sesión, una actualización; nunca analizar estados intermedios."""
        key = self._session_key(session)
        if self.lcu_draft_active and key == self._last_session_key:
            return
        controls = (
            [self.local_champ_combo, self.local_role_combo]
            + self.my_team_combo_widgets + self.enemy_team_combo_widgets
            + self.my_team_role_combos
            + self.my_team_pick_state_widgets + self.enemy_team_pick_state_widgets
        )
        with ExitStack() as stack:
            for control in controls:
                stack.enter_context(QSignalBlocker(control))
            self._apply_lcu_session(session)
        self._update_analytics()
        self._last_session_key = key

    def _apply_lcu_session(self, session: dict[str, Any]) -> None:
        """Aplicar el snapshot completo con las señales bloqueadas por el llamante."""
        self._set_lcu_managed_controls(True)
        my_team = session.get("myTeam", [])
        their_team = session.get("theirTeam", [])
        local_cell_id = session.get("localPlayerCellId")
        self._update_header_bans(session)

        # La sesión LCU es la fuente de verdad: no conservamos picks de una
        # partida anterior ni valores introducidos antes de conectarse.
        for champion_combo, state_combo in zip(self.my_team_combo_widgets, self.my_team_pick_state_widgets):
            champion_combo.setCurrentText("-- Vacío --")
            state_combo.setChecked(False)
        for champion_combo, state_combo in zip(self.enemy_team_combo_widgets, self.enemy_team_pick_state_widgets):
            champion_combo.setCurrentText("-- Vacío --")
            state_combo.setChecked(False)
        self.local_champ_combo.setCurrentText("")

        # Actualizar aliados. El cliente sí publica la posición asignada de los
        # aliados (assignedPosition), así que su línea es un dato confirmado.
        self.my_team_roles_from_client = [False] * len(self.ROLES)
        self._local_slot = None
        for i, player in enumerate(my_team[:5]):
            selected_id = player.get("championId")
            intended_id = player.get("championPickIntent")
            champ_id = selected_id or intended_id
            champ_name = self.analyzer.get_champion_name_by_id(champ_id) if champ_id else ""
            if champ_name:
                self.my_team_combo_widgets[i].setCurrentText(champ_name)
                self.my_team_pick_state_widgets[i].setChecked(bool(selected_id))
            assigned_pos = self._role_from_position(player.get("assignedPosition", ""))
            if assigned_pos:
                self._show_role(self.my_team_role_combos[i], assigned_pos)
                self.my_team_roles_from_client[i] = True
            if player.get("cellId") == local_cell_id:
                self._local_slot = i
                if champ_name:
                    self.local_champ_combo.setCurrentText(champ_name)
                if assigned_pos:
                    self.local_role_combo.setCurrentText(assigned_pos)

        # Actualizar enemigos. LCU no revela su asignación de línea, así que
        # solo se puede proponer una hipótesis a partir de sus roles habituales.
        for i, player in enumerate(their_team[:5]):
            selected_id = player.get("championId")
            intended_id = player.get("championPickIntent")
            champ_id = selected_id or intended_id
            champ_name = self.analyzer.get_champion_name_by_id(champ_id) if champ_id else ""
            if champ_name:
                self.enemy_team_combo_widgets[i].setCurrentText(champ_name)
                self.enemy_team_pick_state_widgets[i].setChecked(bool(selected_id))

        self._apply_role_hints()

    @staticmethod
    def _role_from_position(position: str) -> str:
        """Traduce la posición que publica LCU al nombre de línea de la interfaz."""
        return {
            "top": "Top", "jungle": "Jungle", "middle": "Mid",
            "bottom": "Bot", "utility": "Support",
        }.get(str(position or "").casefold(), "")

    @classmethod
    def _base_role(cls, text: str) -> str:
        """Línea real de un texto con o sin marca de hipótesis; "" si no lo es."""
        clean = str(text or "").strip().lstrip(cls.PROBABLE_ROLE_PREFIX)
        return clean if clean in cls.ROLES else ""

    def _show_role(self, combo: QComboBox, role: str, probable: bool = False) -> None:
        """Pinta una línea en un selector; sin línea muestra el marcador ``?``.

        Cualquier marcador anterior (``~Rol`` o ``?``) se retira para no dejar
        residuos en el desplegable cuando la línea vuelve a ser un dato real.
        """
        text = (
            f"{self.PROBABLE_ROLE_PREFIX}{role}" if probable and role
            else role or self.UNKNOWN_ROLE
        )
        with QSignalBlocker(combo):
            for index in reversed(range(combo.count())):
                item = str(combo.itemText(index))
                if item not in self.ROLES and item != text:
                    combo.removeItem(index)
            if combo.findText(text) < 0:
                combo.addItem(text)
            combo.setCurrentText(text)

    def _clear_role_hints(self, combo: QComboBox) -> None:
        """Devuelve un selector a las cinco líneas reales al salir del modo LCU."""
        current = self._base_role(combo.currentText()) or self.ROLES[0]
        with QSignalBlocker(combo):
            for index in reversed(range(combo.count())):
                if str(combo.itemText(index)) not in self.ROLES:
                    combo.removeItem(index)
            combo.setCurrentText(current)

    def _apply_role_hints(self) -> None:
        """Etiqueta cada fila con lo que se sabe: línea confirmada o probable.

        El cliente publica la posición de los aliados, nunca la de los rivales.
        Todo lo que no venga del cliente se muestra como hipótesis (``~Rol``)
        para no presentar una suposición como si fuera la línea real.
        """
        self._apply_enemy_role_hints()
        self._apply_ally_role_hints()

    def _apply_enemy_role_hints(self) -> None:
        """Propone la línea de cada rival y la marca como hipótesis."""
        names = [combo.currentText() for combo in self.enemy_team_combo_widgets]
        guessed = list(self.analyzer.assign_likely_roles(names))
        self.enemy_team_roles = (guessed + [""] * len(names))[:len(names)]
        for label, name, role in zip(self.enemy_team_role_labels, names, self.enemy_team_roles):
            if not role:
                label.setText("—")
                label.setStyleSheet("color: #64748B; font-weight: bold;")
                label.setToolTip(
                    "Línea del rival: el cliente no la publica."
                    if not name or name == "-- Vacío --"
                    else f"Sin datos de línea para {name}."
                )
                continue
            label.setText(f"{self.PROBABLE_ROLE_PREFIX}{role}")
            label.setStyleSheet("color: #FBBF24; font-weight: bold; font-style: italic;")
            label.setToolTip(
                f"Línea probable de {name}: {role}. El cliente no publica la posición "
                "de los rivales; es la hipótesis que mejor encaja con los campeones "
                "elegidos y puede cambiar durante la partida."
            )

    def _apply_ally_role_hints(self) -> None:
        """Mantiene las líneas del cliente y marca con ``~`` las deducidas."""
        roles: list[str] = []
        deduced: list[bool] = []
        for index, combo in enumerate(self.my_team_role_combos):
            from_client = self.lcu_draft_active and self.my_team_roles_from_client[index]
            role = self._base_role(combo.currentText())
            roles.append(role if (from_client or not self.lcu_draft_active) else "")
            deduced.append(False)
        if self.lcu_draft_active:
            confirmed = [role for role in roles if role]
            pending = [index for index, role in enumerate(roles) if not role]
            names = [self.my_team_combo_widgets[index].currentText() for index in pending]
            for index, name, role in zip(
                pending, names, self.analyzer.assign_likely_roles(names, exclude=confirmed)
            ):
                if not role:
                    continue
                roles[index] = role
                deduced[index] = True
                self.my_team_role_combos[index].setToolTip(
                    f"Línea probable de {name or 'tu aliado'}: {role}. El cliente no "
                    "publicó su posición; es una hipótesis según sus roles habituales."
                )
        for combo, role, is_deduced in zip(self.my_team_role_combos, roles, deduced):
            self._show_role(combo, role, probable=is_deduced)
            if is_deduced:
                combo.setStyleSheet(
                    "QComboBox { color: #FBBF24; font-style: italic; border-color: #B98A2E; }"
                )
                continue
            if role:
                combo.setStyleSheet("")
                combo.setToolTip(
                    "Línea asignada por el cliente." if self.lcu_draft_active
                    else "Línea que declaras para este aliado."
                )
                continue
            combo.setStyleSheet("QComboBox { color: #94A3B8; font-style: italic; }")
            combo.setToolTip(
                "Sin datos de línea: el cliente no publicó la posición de este aliado "
                "y su campeón no aporta roles conocidos."
            )
        if self.lcu_draft_active and self._local_slot is not None and deduced[self._local_slot]:
            # La cabecera «Tu rol» acompaña a la hipótesis de la fila del jugador.
            self._show_role(self.local_role_combo, roles[self._local_slot], probable=True)
        self.my_team_roles = roles

    def _current_local_role(self) -> str:
        """Línea del jugador sin la marca de hipótesis, apta para runas y build."""
        return self._base_role(self.local_role_combo.currentText()) or self.ROLES[0]

    def _on_draft_changed(self) -> None:
        self._update_analytics()

    def _set_curve_scope(self) -> None:
        button = self.sender()
        if not isinstance(button, QPushButton):
            return
        self.curve_scope = str(button.property("curve_scope"))
        for sibling in button.parent().findChildren(QPushButton):
            if sibling.property("curve_scope"):
                sibling.setChecked(sibling is button)
        self._update_analytics()

    def _set_icon(self, label: QLabel, kind: str, name: str, size: int) -> None:
        if not name or name == "-- Vacío --":
            self._icon_cache.assign(label, None, size)
            return
        getter = {
            "champion": get_champion_icon_path,
            "item": get_item_icon_path,
            "rune": get_rune_icon_path,
            "spell": get_spell_icon_path,
        }[kind]
        args = (name, self.analyzer.items, self.dd_version) if kind == "item" else (name, self.dd_version)
        self._icon_cache.assign(
            label, (kind, name, self.dd_version), size, partial(getter, *args)
        )

    def _update_slot_visuals(self) -> None:
        """Sincroniza iconos y win rates de línea en el tablero compacto."""
        for icons, combos in (
            (self.my_team_icon_labels, self.my_team_combo_widgets),
            (self.enemy_team_icon_labels, self.enemy_team_combo_widgets),
        ):
            for icon_label, champion_combo in zip(icons, combos):
                champion_name = champion_combo.currentText()
                empty = not champion_name or champion_name == "-- Vacío --"
                if champion_combo.property("empty") != empty:
                    # El selector estiliza las casillas vacías en gris/itálica.
                    champion_combo.setProperty("empty", empty)
                    champion_combo.style().unpolish(champion_combo)
                    champion_combo.style().polish(champion_combo)
                self._set_icon(icon_label, "champion", champion_name, 30)

        for index, (my_combo, enemy_combo) in enumerate(zip(self.my_team_combo_widgets, self.enemy_team_combo_widgets)):
            for label, champion in (
                (self.my_team_matchup_labels[index], my_combo.currentText()),
                (self.enemy_team_matchup_labels[index], enemy_combo.currentText()),
            ):
                if not champion or champion == "-- Vacío --":
                    label.setText("—")
                    label.setStyleSheet(
                        "color: #64748B; background: #131E33; border: 1px solid #2C3D57; "
                        "border-radius: 9px; font-size: 11px; font-weight: 700;"
                    )
                    continue
                rate = self.analyzer.get_champion_overall_win_rate(champion)
                if rate > 50.0:
                    color, background, border = "#6EE7B7", "#0F2E24", "#1D6B54"
                elif rate < 50.0:
                    color, background, border = "#FECACA", "#2E1416", "#7F2F3F"
                else:
                    color, background, border = "#CBD5E1", "#131E33", "#2C3D57"
                label.setText(f"{rate:.1f}%")
                label.setStyleSheet(
                    f"color: {color}; background: {background}; border: 1px solid {border}; "
                    "border-radius: 9px; font-size: 11px; font-weight: 700;"
                )

    def _update_header_bans(self, session: dict[str, Any]) -> None:
        """Muestra los diez bans reales de la sesión LCU, separados por equipo."""
        my_cell_ids = {player.get("cellId") for player in session.get("myTeam", [])}
        enemy_cell_ids = {player.get("cellId") for player in session.get("theirTeam", [])}
        my_bans: list[str] = []
        enemy_bans: list[str] = []

        for phase_actions in session.get("actions", []):
            for action in phase_actions:
                if not isinstance(action, dict) or action.get("type") != "ban":
                    continue
                champion_id = action.get("championId")
                champion_name = self.analyzer.get_champion_name_by_id(champion_id) if champion_id else ""
                if not champion_name:
                    continue
                actor_id = action.get("actorCellId")
                if actor_id in my_cell_ids or action.get("isAllyAction") is True:
                    my_bans.append(champion_name)
                elif actor_id in enemy_cell_ids or action.get("isAllyAction") is False:
                    enemy_bans.append(champion_name)

        for labels, champions, team_name in (
            (self.my_header_ban_labels, my_bans, "aliado"),
            (self.enemy_header_ban_labels, enemy_bans, "enemigo"),
        ):
            for label, champion in zip(labels, champions[:5]):
                self._set_icon(label, "champion", champion, 26)
                label.setToolTip(f"Ban {team_name}: {champion}")
            for label in labels[len(champions[:5]):]:
                self._set_icon(label, "champion", "", 26)
                label.setToolTip("")

    def _team_overall_win_rate(self, champion_combos: list[QComboBox]) -> float | None:
        """Media de win rates OVERALL de los campeones con al menos un pick."""
        rates = [
            self.analyzer.get_champion_overall_win_rate(combo.currentText())
            for combo in champion_combos
            if combo.currentText() and combo.currentText() != "-- Vacío --"
        ]
        return round(sum(rates) / len(rates), 1) if rates else None

    def _update_team_overall_labels(self) -> None:
        """Muestra el WR OVERALL agregado junto al título de cada equipo."""
        for label, rate in (
            (self.my_team_overall_lbl, self._team_overall_win_rate(self.my_team_combo_widgets)),
            (self.enemy_team_overall_lbl, self._team_overall_win_rate(self.enemy_team_combo_widgets)),
        ):
            if rate is None:
                label.setText("WR —")
                color, background, border = "#94A3B8", "#131E33", "#2C3D57"
            else:
                color = "#6EE7B7" if rate > 50.0 else "#FECACA" if rate < 50.0 else "#CBD5E1"
                background = "#0F2E24" if rate > 50.0 else "#2E1416" if rate < 50.0 else "#131E33"
                border = "#1D6B54" if rate > 50.0 else "#7F2F3F" if rate < 50.0 else "#2C3D57"
                label.setText(f"WR {rate:.1f}%")
            label.setStyleSheet(
                f"color: {color}; background: {background}; border: 1px solid {border}; "
                "border-radius: 10px; padding: 4px 12px; font-size: 12px; font-weight: 800;"
            )

    def _update_analytics(self) -> None:
        # Las líneas se recalculan antes de analizar: confirmadas o hipótesis.
        self._apply_role_hints()

        # Obtener selecciones de equipo
        my_team_champs = [cb.currentText() for cb in self.my_team_combo_widgets if cb.currentText() and cb.currentText() != "-- Vacío --"]
        enemy_team_champs = [cb.currentText() for cb in self.enemy_team_combo_widgets if cb.currentText() and cb.currentText() != "-- Vacío --"]

        local_champ = self.local_champ_combo.currentText()
        local_role = self._current_local_role()
        if not self.lcu_draft_active:
            # En modo manual el rol marcado en cabecera identifica al jugador.
            # Su campeón es el aliado que ocupe ese mismo rol.
            for role, champion_combo in zip(self.my_team_roles, self.my_team_combo_widgets):
                if role == local_role and champion_combo.currentText() != "-- Vacío --":
                    local_champ = champion_combo.currentText()
                    break

        # 1. Desglose de Daño
        my_dmg = self.analyzer.calculate_team_damage_breakdown(my_team_champs)
        en_dmg = self.analyzer.calculate_team_damage_breakdown(enemy_team_champs)

        self.my_damage_bar.set_percentages(
            my_dmg["physical"], my_dmg["magic"], my_dmg["true"]
        )
        self.enemy_damage_bar.set_percentages(
            en_dmg["physical"], en_dmg["magic"], en_dmg["true"]
        )

        # 2. Curva de Poder
        curve_my_champs = my_team_champs
        curve_enemy_champs = enemy_team_champs
        if self.curve_scope != "Equipo vs equipo":
            # Se filtra por la línea efectiva (confirmada o hipótesis), no por el
            # texto pintado, que puede llevar la marca de línea probable.
            curve_my_champs = [
                combo.currentText()
                for role, combo in zip(self.my_team_roles, self.my_team_combo_widgets)
                if role == self.curve_scope and combo.currentText() != "-- Vacío --"
            ]
            curve_enemy_champs = [
                combo.currentText()
                for role, combo in zip(self.enemy_team_roles, self.enemy_team_combo_widgets)
                if role == self.curve_scope and combo.currentText() != "-- Vacío --"
            ]
        my_curve = self.analyzer.calculate_team_power_curve(curve_my_champs)
        en_curve = self.analyzer.calculate_team_power_curve(curve_enemy_champs)
        spike_label = self.analyzer.analyze_power_spike_phase(my_curve, en_curve)

        self.power_curve_widget.set_data(my_curve, en_curve, spike_label, self.curve_scope)

        # 3. Bans recomendados (3 tarjetas con icono)
        bans = self.analyzer.get_recommended_bans(local_champ)
        for index, card in enumerate(self.ban_card_widgets):
            if index < len(bans):
                ban = bans[index]
                champion = str(ban.get("champion", ""))
                card["name"].setText(champion)
                card["wr"].setText(f"WR {ban.get('win_rate', 0):.1f}%")
                card["wr"].setStyleSheet(
                    "color: #FB7185; font-weight: 700;"
                    if ban.get("win_rate", 50) < 50.0 else "color: #94A3B8; font-weight: 700;"
                )
                card["tip"].setText(str(ban.get("tip", "")))
                card["tip"].setToolTip(str(ban.get("tip", "")))
                self._set_icon(card["icon"], "champion", champion, 64)
            else:
                self._set_icon(card["icon"], "champion", "", 64)
                card["name"].setText("Sin dato")
                card["wr"].setText("WR —")
                card["wr"].setStyleSheet("color: #94A3B8; font-weight: 700;")
                card["tip"].setText("")
                card["tip"].setToolTip("")

        # 4. Build, runas y hechizos del campeón local
        build = self.analyzer.get_champion_build(local_champ, enemy_team_champs)
        for index, item_lbl in enumerate(self.build_item_labels):
            if index < len(build["items"]):
                item = build["items"][index]
                self._set_icon(item_lbl, "item", str(item["id"]), 40)
                item_lbl.setToolTip(f"{item['name']} (compra {index + 1})")
            else:
                self._set_icon(item_lbl, "item", "", 40)
                item_lbl.setToolTip("")
        if build.get("boots"):
            boots = build["boots"]
            self._set_icon(self.build_boots_label, "item", str(boots["id"]), 40)
            self.build_boots_label.setToolTip(f"{boots['name']} — {build.get('boots_reason', '')}")
        else:
            self._set_icon(self.build_boots_label, "item", "", 40)
            self.build_boots_label.setToolTip("")
        self.build_note_lbl.setText(
            " · ".join(filter(None, [build.get("boots_reason", ""), build.get("note", "")]))
        )

        # 5. Runas (iconos) y hechizos
        rune_data = self.analyzer.get_champion_runes_and_summoners(local_champ, local_role)
        for page_index in (1, 2):
            page = rune_data.get(f"page_{page_index}")
            row = self.rune_page_rows[page_index]
            row["page"] = page
            names = []
            if page:
                row["keystone"].setText(str(page.get("keystone", "—")))
                names = [page.get("keystone", ""), *page.get("slots", [])[:3],
                         *page.get("secondary_slots", [])[:2], *page.get("shards", [])[:3]]
            else:
                row["keystone"].setText("—")
            for index, slot in enumerate(row["icons"]):
                name = str(names[index]) if index < len(names) and names[index] else ""
                self._set_icon(slot, "rune", name, 24)
                slot.setToolTip(name)

        spells = rune_data.get("spells", ("Destello", "Teleportación"))
        for index, spell_lbl in enumerate(self.spell_icon_labels):
            name = str(spells[index]) if index < len(spells) else ""
            self._set_icon(spell_lbl, "spell", name, 44)
            spell_lbl.setToolTip(name)
        smite_note = " (Smite obligatorio en Jungla)" if local_role == "Jungle" else ""
        self.spells_text_lbl.setText(f"{spells[0]} + {spells[1]}{smite_note}")

        self._update_team_overall_labels()
        self._update_slot_visuals()

    def _import_build(self) -> None:
        local_champ = self.local_champ_combo.currentText()
        if not local_champ:
            QMessageBox.warning(self, "Importar Build", "Selecciona primero un campeón válido.")
            return
        enemy_team_champs = [
            cb.currentText() for cb in self.enemy_team_combo_widgets
            if cb.currentText() and cb.currentText() != "-- Vacío --"
        ]
        build = self.analyzer.get_champion_build(local_champ, enemy_team_champs)
        item_ids = [item["id"] for item in build["items"]]
        if len(item_ids) < 6:
            QMessageBox.warning(
                self, "Importar Build",
                f"La build de {local_champ} solo tiene {len(item_ids)} objetos identificados.",
            )
            return
        boots = build.get("boots")
        success, msg = self.lcu_service.import_item_set(
            champion_id=int(build.get("champion_id") or 0),
            champion_name=local_champ,
            role=self._current_local_role(),
            item_ids=item_ids,
            boots_id=boots["id"] if boots else None,
            situational=build.get("situational", []),
        )
        if success:
            QMessageBox.information(self, "Éxito al Importar Build", msg)
        else:
            QMessageBox.critical(self, "Error al Importar Build", msg)

    def _import_runes(self, page_index: int) -> None:
        local_champ = self.local_champ_combo.currentText()
        if not local_champ:
            QMessageBox.warning(self, "Importar Runas", "Selecciona primero un campeón válido.")
            return

        data = self.analyzer.get_champion_runes_and_summoners(local_champ, self._current_local_role())
        page = data.get("page_1") if page_index == 1 else data.get("page_2")
        if not page:
            QMessageBox.warning(self, "Importar Runas", f"No hay datos de runas (Página {page_index}) para {local_champ}.")
            return

        success, msg = self.lcu_service.import_rune_page(
            name=f"{local_champ} P{page_index}",
            primary_tree=page.get("primary_tree", "Precision"),
            secondary_tree=page.get("secondary_tree", "Resolve"),
            keystone_name=page.get("keystone", ""),
            slots=page.get("slots", []),
            secondary_slots=page.get("secondary_slots", []),
            shards=page.get("shards", []),
        )

        if success:
            QMessageBox.information(self, "Éxito al Importar Runas", msg)
        else:
            QMessageBox.critical(self, "Error al Importar Runas", msg)

    def _import_spells(self) -> None:
        local_champ = self.local_champ_combo.currentText()
        if not local_champ:
            QMessageBox.warning(self, "Importar Hechizos", "Selecciona primero un campeón válido.")
            return

        data = self.analyzer.get_champion_runes_and_summoners(local_champ, self._current_local_role())
        spells = data.get("spells", ("Destello", "Teleportación"))

        success, msg = self.lcu_service.import_summoner_spells(spells[0], spells[1])

        if success:
            QMessageBox.information(self, "Éxito al Importar Hechizos", msg)
        else:
            QMessageBox.critical(self, "Error al Importar Hechizos", msg)
