from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.lcu_service import LCUService
from app.ui.local_analysis_dialog import DamageBarWidget
from data_dragon import get_champion_icon_path, get_latest_version, get_rune_icon_path, get_spell_icon_path


class DraftPowerCurveWidget(QWidget):
    """Widget de dibujo vectorizado para comparar las curvas de poder de Aliados vs Enemigos."""

    TIME_BRACKETS = ["0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40+"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.my_team_curve: dict[str, float] = {b: 50.0 for b in self.TIME_BRACKETS}
        self.enemy_team_curve: dict[str, float] = {b: 50.0 for b in self.TIME_BRACKETS}
        self.power_spike_label: str = "Calculando..."
        self.scope_label: str = "Equipo vs equipo"

    def set_data(self, my_curve: dict[str, float], enemy_curve: dict[str, float], spike_label: str, scope_label: str = "Equipo vs equipo") -> None:
        self.my_team_curve = my_curve
        self.enemy_team_curve = enemy_curve
        self.power_spike_label = spike_label
        self.scope_label = scope_label
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
        margin_top = 40
        margin_bottom = 45

        plot_w = w - margin_left - margin_right
        plot_h = h - margin_top - margin_bottom

        if plot_w <= 0 or plot_h <= 0:
            return

        # Rango vertical (40% - 60% win rate)
        min_v, max_v = 40.0, 60.0

        def y_pos(val: float) -> float:
            v_clamped = max(min_v, min(max_v, val))
            ratio = (v_clamped - min_v) / (max_v - min_v)
            return margin_top + plot_h * (1.0 - ratio)

        # Rejilla horizontal
        grid_pen = QPen(QColor(255, 255, 255, 25), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        font_grid = QFont("Segoe UI", 9)
        painter.setFont(font_grid)

        for step_v in range(47, 54):
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

        # Título y Leyenda
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(margin_left, 24, f"Evolución de Win Rate · {self.scope_label} (0m - 40m+)")

        # Leyendas
        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(QColor(16, 185, 129))
        painter.drawText(w - margin_right - 180, 24, "━ Mi Equipo")
        painter.setPen(QColor(239, 68, 68))
        painter.drawText(w - margin_right - 90, 24, "━ Enemigos")

        # Badge de Power Spike
        painter.setBrush(QBrush(QColor(30, 41, 59)))
        painter.setPen(QPen(QColor(16, 185, 129), 1.5))
        painter.drawRoundedRect(margin_left, int(margin_top + 10), 280, 26, 6, 6)
        painter.setPen(QColor(16, 185, 129))
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        painter.drawText(margin_left + 10, int(margin_top + 27), f"⚡ Power Spike: {self.power_spike_label}")


class DraftToolDialog(QDialog):
    """Diálogo completo de la Herramienta de Draft en tiempo real."""

    ROLES = ["Top", "Jungle", "Mid", "Bot", "Support"]

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
        self.dd_version = get_latest_version()

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
        self.my_team_icon_labels: list[QLabel] = []
        self.enemy_team_icon_labels: list[QLabel] = []
        self.my_team_matchup_labels: list[QLabel] = []
        self.enemy_team_matchup_labels: list[QLabel] = []
        self.my_header_ban_labels: list[QLabel] = []
        self.enemy_header_ban_labels: list[QLabel] = []
        self.lcu_draft_active = False
        self.curve_scope = "Equipo vs equipo"

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
        teams_frame.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        teams_layout = QVBoxLayout(teams_frame)
        teams_layout.setContentsMargins(12, 12, 12, 12)
        teams_grid_layout = QHBoxLayout()

        # Columna Mi Equipo
        my_team_box = QVBoxLayout()
        my_team_title = QLabel("🛡️ MI EQUIPO (Aliados)")
        my_team_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        my_team_title.setStyleSheet("color: #10B981;")
        my_team_box.addWidget(my_team_title)

        for i in range(5):
            slot_card = QFrame()
            slot_card.setStyleSheet("background: #172338; border: 1px solid #2D405D; border-radius: 7px;")
            slot_h = QHBoxLayout(slot_card)
            slot_h.setContentsMargins(6, 3, 6, 3)
            slot_h.setSpacing(6)
            role_cb = QComboBox()
            role_cb.addItems(self.ROLES)
            role_cb.setCurrentIndex(i % 5)
            role_cb.setFixedWidth(80)
            role_cb.currentIndexChanged.connect(self._on_draft_changed)

            champ_cb = QComboBox()
            champ_cb.addItems(["-- Vacío --"] + self.all_champion_names)
            champ_cb.currentIndexChanged.connect(self._on_draft_changed)

            icon_lbl = QLabel()
            icon_lbl.setFixedSize(30, 30)
            icon_lbl.setStyleSheet("background: #0F172A; border: 1px solid #334155; border-radius: 15px;")

            matchup_lbl = QLabel("—")
            matchup_lbl.setFixedWidth(52)
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
            slot_h.addWidget(champ_cb)
            slot_h.addWidget(matchup_lbl)
            slot_h.addWidget(state_cb)
            my_team_box.addWidget(slot_card)

        # Columna Enemigos
        enemy_team_box = QVBoxLayout()
        enemy_team_title = QLabel("⚔️ EQUIPO ENEMIGO")
        enemy_team_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        enemy_team_title.setStyleSheet("color: #EF4444;")
        enemy_team_box.addWidget(enemy_team_title)

        for i in range(5):
            slot_card = QFrame()
            slot_card.setStyleSheet("background: #172338; border: 1px solid #2D405D; border-radius: 7px;")
            slot_h = QHBoxLayout(slot_card)
            slot_h.setContentsMargins(6, 3, 6, 3)
            slot_h.setSpacing(6)
            role_lbl = QLabel(self.ROLES[i])
            role_lbl.setFixedWidth(60)
            role_lbl.setStyleSheet("color: #94A3B8; font-weight: bold;")

            champ_cb = QComboBox()
            champ_cb.addItems(["-- Vacío --"] + self.all_champion_names)
            champ_cb.currentIndexChanged.connect(self._on_draft_changed)

            icon_lbl = QLabel()
            icon_lbl.setFixedSize(30, 30)
            icon_lbl.setStyleSheet("background: #0F172A; border: 1px solid #334155; border-radius: 15px;")

            matchup_lbl = QLabel("—")
            matchup_lbl.setFixedWidth(52)
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
            slot_h.addWidget(champ_cb)
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

        # 2C. PANELS RECOMENDACIONES DE BANS Y PICKS
        rec_frame = QFrame()
        rec_frame.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        rec_layout = QHBoxLayout(rec_frame)
        rec_layout.setContentsMargins(12, 12, 12, 12)

        # Bans recomendados
        bans_box = QVBoxLayout()
        bans_title = QLabel("🚫 BANEOS RECOMENDADOS")
        bans_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        bans_title.setStyleSheet("color: #F43F5E;")
        bans_box.addWidget(bans_title)

        self.bans_table = QTableWidget(0, 3)
        self.bans_table.setHorizontalHeaderLabels(["Campeón", "Win Rate", "Tip / Razón"])
        self.bans_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.bans_table.setStyleSheet("QTableWidget { background-color: #0F172A; gridline-color: #334155; }")
        bans_box.addWidget(self.bans_table)

        # Picks recomendados
        picks_box = QVBoxLayout()
        picks_title = QLabel("✨ PICKS RECOMENDADOS (COUNTER ENEMY)")
        picks_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        picks_title.setStyleSheet("color: #38BDF8;")
        picks_box.addWidget(picks_title)

        self.picks_table = QTableWidget(0, 3)
        self.picks_table.setHorizontalHeaderLabels(["Campeón", "Score Counter", "Razón"])
        self.picks_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.picks_table.setStyleSheet("QTableWidget { background-color: #0F172A; gridline-color: #334155; }")
        picks_box.addWidget(self.picks_table)

        rec_layout.addLayout(bans_box)
        rec_layout.addLayout(picks_box)

        content_layout.addWidget(rec_frame)

        # 2D. IMPORTACIÓN DE RUNAS Y HECHIZOS AL CLIENTE (LCU)
        import_frame = QFrame()
        import_frame.setStyleSheet("background-color: #1E293B; border-radius: 8px; border: 1px solid #334155;")
        import_layout = QVBoxLayout(import_frame)
        import_layout.setContentsMargins(12, 12, 12, 12)

        import_title = QLabel("⚡ IMPORTACIÓN AL CLIENTE (PÁGINA 1 U.GG / PÁGINA 2 LOLALYTICS / HECHIZOS)")
        import_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        import_title.setStyleSheet("color: #A855F7;")
        import_layout.addWidget(import_title)

        self.runes_preview_lbl = QLabel("Cargando runas sugeridas...")
        self.runes_preview_lbl.setStyleSheet("color: #CBD5E1; background-color: #0F172A; padding: 8px; border-radius: 6px;")
        import_layout.addWidget(self.runes_preview_lbl)

        btn_h = QHBoxLayout()

        self.btn_import_ugg = QPushButton("⚡ Importar Runas (Página 1 U.GG)")
        self.btn_import_ugg.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_ugg.setStyleSheet("background-color: #059669; color: white; font-weight: bold; border-radius: 6px; padding: 8px 14px;")
        self.btn_import_ugg.clicked.connect(lambda: self._import_runes(page_index=1))

        self.btn_import_lolalytics = QPushButton("⚡ Importar Runas (Página 2 Lolalytics)")
        self.btn_import_lolalytics.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_lolalytics.setStyleSheet("background-color: #7C3AED; color: white; font-weight: bold; border-radius: 6px; padding: 8px 14px;")
        self.btn_import_lolalytics.clicked.connect(lambda: self._import_runes(page_index=2))

        self.btn_import_spells = QPushButton("🔮 Importar Hechizos de Invocador")
        self.btn_import_spells.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import_spells.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; border-radius: 6px; padding: 8px 14px;")
        self.btn_import_spells.clicked.connect(self._import_spells)

        btn_h.addWidget(self.btn_import_ugg)
        btn_h.addWidget(self.btn_import_lolalytics)
        btn_h.addWidget(self.btn_import_spells)

        import_layout.addLayout(btn_h)

        content_layout.addWidget(import_frame)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

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

    def update_from_lcu_session(self, session: dict[str, Any]) -> None:
        """Actualiza automáticamente la UI con la sesión activa de Champ Select de League."""
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

        # Actualizar aliados
        for i, player in enumerate(my_team[:5]):
            selected_id = player.get("championId")
            intended_id = player.get("championPickIntent")
            champ_id = selected_id or intended_id
            champ_name = self.analyzer.get_champion_name_by_id(champ_id) if champ_id else ""
            if champ_name:
                self.my_team_combo_widgets[i].setCurrentText(champ_name)
                self.my_team_pick_state_widgets[i].setChecked(bool(selected_id))
            if player.get("cellId") == local_cell_id:
                if champ_name:
                    self.local_champ_combo.setCurrentText(champ_name)
                assigned_pos = player.get("assignedPosition", "")
                if assigned_pos:
                    pos_map = {"top": "Top", "jungle": "Jungle", "middle": "Mid", "bottom": "Bot", "utility": "Support"}
                    clean_pos = pos_map.get(assigned_pos.lower(), "Top")
                    self.local_role_combo.setCurrentText(clean_pos)

        # Actualizar enemigos. LCU no revela su asignación de línea, así que
        # la inferimos después a partir de sus roles más habituales.
        for i, player in enumerate(their_team[:5]):
            selected_id = player.get("championId")
            intended_id = player.get("championPickIntent")
            champ_id = selected_id or intended_id
            champ_name = self.analyzer.get_champion_name_by_id(champ_id) if champ_id else ""
            if champ_name:
                self.enemy_team_combo_widgets[i].setCurrentText(champ_name)
                self.enemy_team_pick_state_widgets[i].setChecked(bool(selected_id))

        self._assign_likely_enemy_roles()
        self._update_analytics()

    def _assign_likely_enemy_roles(self) -> None:
        """Muestra la línea más probable de cada enemigo sin afirmar que sea segura."""
        assigned_roles: set[str] = set()
        for role_label, champion_combo in zip(self.enemy_team_role_labels, self.enemy_team_combo_widgets):
            champion_name = champion_combo.currentText()
            if not champion_name or champion_name == "-- Vacío --":
                continue
            likely_roles = self.analyzer.get_likely_roles(champion_name)
            chosen_role = next((role for role in likely_roles if role not in assigned_roles), None)
            chosen_role = chosen_role or (likely_roles[0] if likely_roles else "?")
            assigned_roles.add(chosen_role)
            role_label.setText(chosen_role)
            role_label.setToolTip(
                f"Rol probable de {champion_name}, inferido de sus datos de campeón."
            )

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

    def _update_slot_visuals(self) -> None:
        """Sincroniza iconos y win rates de línea en el tablero compacto."""
        for icons, combos in (
            (self.my_team_icon_labels, self.my_team_combo_widgets),
            (self.enemy_team_icon_labels, self.enemy_team_combo_widgets),
        ):
            for icon_label, champion_combo in zip(icons, combos):
                champion_name = champion_combo.currentText()
                icon_label.clear()
                if not champion_name or champion_name == "-- Vacío --":
                    continue
                icon_path = get_champion_icon_path(champion_name, self.dd_version)
                if icon_path and icon_path.exists():
                    icon = QPixmap(str(icon_path))
                    if not icon.isNull():
                        icon_label.setPixmap(icon.scaled(
                            28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        ))

        for index, (my_combo, enemy_combo) in enumerate(zip(self.my_team_combo_widgets, self.enemy_team_combo_widgets)):
            my_champion = my_combo.currentText()
            enemy_champion = enemy_combo.currentText()
            my_rate = self.analyzer.get_champion_overall_win_rate(my_champion)
            enemy_rate = self.analyzer.get_champion_overall_win_rate(enemy_champion)

            for label, rate in ((self.my_team_matchup_labels[index], my_rate), (self.enemy_team_matchup_labels[index], enemy_rate)):
                color = "#34D399" if rate > 50.0 else "#FB7185" if rate < 50.0 else "#94A3B8"
                label.setText(f"{rate:.1f}%")
                label.setStyleSheet(f"color: {color}; font-weight: 700;")

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
                label.clear()
                icon_path = get_champion_icon_path(champion, self.dd_version)
                if icon_path and icon_path.exists():
                    icon = QPixmap(str(icon_path))
                    if not icon.isNull():
                        label.setPixmap(icon.scaled(
                            26, 26, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        ))
                label.setToolTip(f"Ban {team_name}: {champion}")
            for label in labels[len(champions[:5]):]:
                label.setText("—")
                label.setToolTip("")

    def _update_analytics(self) -> None:
        # Obtener selecciones de equipo
        my_team_champs = [cb.currentText() for cb in self.my_team_combo_widgets if cb.currentText() and cb.currentText() != "-- Vacío --"]
        enemy_team_champs = [cb.currentText() for cb in self.enemy_team_combo_widgets if cb.currentText() and cb.currentText() != "-- Vacío --"]

        local_champ = self.local_champ_combo.currentText()
        local_role = self.local_role_combo.currentText()
        if not self.lcu_draft_active:
            # En modo manual el rol marcado en cabecera identifica al jugador.
            # Su campeón es el aliado que ocupe ese mismo rol.
            for role_combo, champion_combo in zip(self.my_team_role_combos, self.my_team_combo_widgets):
                if role_combo.currentText() == local_role and champion_combo.currentText() != "-- Vacío --":
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
            curve_my_champs = [
                combo.currentText()
                for role, combo in zip(self.my_team_role_combos, self.my_team_combo_widgets)
                if role.currentText() == self.curve_scope and combo.currentText() != "-- Vacío --"
            ]
            curve_enemy_champs = [
                combo.currentText()
                for role, combo in zip(self.enemy_team_role_labels, self.enemy_team_combo_widgets)
                if role.text() == self.curve_scope and combo.currentText() != "-- Vacío --"
            ]
        my_curve = self.analyzer.calculate_team_power_curve(curve_my_champs)
        en_curve = self.analyzer.calculate_team_power_curve(curve_enemy_champs)
        spike_label = self.analyzer.analyze_power_spike_phase(my_curve, en_curve)

        self.power_curve_widget.set_data(my_curve, en_curve, spike_label, self.curve_scope)

        # 3. Bans recomendados
        bans = self.analyzer.get_recommended_bans(local_champ)
        self.bans_table.setRowCount(len(bans))
        for r, ban in enumerate(bans):
            self.bans_table.setItem(r, 0, QTableWidgetItem(str(ban["champion"])))
            self.bans_table.setItem(r, 1, QTableWidgetItem(f"{ban['win_rate']:.1f}%"))
            self.bans_table.setItem(r, 2, QTableWidgetItem(str(ban["tip"])))

        # 4. Picks recomendados
        picks = self.analyzer.get_recommended_picks(local_role, enemy_team_champs, my_team_champs)
        self.picks_table.setRowCount(len(picks))
        for r, pick in enumerate(picks):
            self.picks_table.setItem(r, 0, QTableWidgetItem(str(pick["champion"])))
            self.picks_table.setItem(r, 1, QTableWidgetItem(f"+{pick['score']:.1f}"))
            self.picks_table.setItem(r, 2, QTableWidgetItem(str(pick["reason"])))

        # 5. Vista previa de Runas y Hechizos
        rune_data = self.analyzer.get_champion_runes_and_summoners(local_champ)
        p1 = rune_data.get("page_1")
        p2 = rune_data.get("page_2")
        spells = rune_data.get("spells", ("Destello", "Teleportación"))

        txt = f"<b>{local_champ} ({local_role})</b><br>"
        if p1:
            txt += f"<b>Página 1 (U.GG):</b> {p1.get('primary_tree')} ({p1.get('keystone')}) + {p1.get('secondary_tree')}<br>"
        if p2:
            txt += f"<b>Página 2 (Lolalytics):</b> {p2.get('primary_tree')} ({p2.get('keystone')}) + {p2.get('secondary_tree')}<br>"
        txt += f"<b>Hechizos Sugeridos:</b> {spells[0]} + {spells[1]}"

        self.runes_preview_lbl.setText(txt)
        self._update_slot_visuals()

    def _import_runes(self, page_index: int) -> None:
        local_champ = self.local_champ_combo.currentText()
        if not local_champ:
            QMessageBox.warning(self, "Importar Runas", "Selecciona primero un campeón válido.")
            return

        data = self.analyzer.get_champion_runes_and_summoners(local_champ)
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

        data = self.analyzer.get_champion_runes_and_summoners(local_champ)
        spells = data.get("spells", ("Destello", "Teleportación"))

        success, msg = self.lcu_service.import_summoner_spells(spells[0], spells[1])

        if success:
            QMessageBox.information(self, "Éxito al Importar Hechizos", msg)
        else:
            QMessageBox.critical(self, "Error al Importar Hechizos", msg)
