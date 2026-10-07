from __future__ import annotations

import logging
import math
from contextlib import ExitStack
from functools import partial
from typing import Any

from PySide6.QtCore import QRect, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.lcu_service import LCUService
from app.services.rangos_campeones import OPCIONES_RANGO, RANGO_PREDETERMINADO
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones
from app.ui.async_task import run_async
from app.ui.componentes_visuales import MensajeEstado, Reflujo
from app.ui.draft_icon_cache import DraftIconCache
from app.ui.local_analysis_dialog import DamageBarWidget
from app.ui.sistema_visual import PALETA
from app.ui.tema import (
    actualizar_estilo,
    aplicar_apariencia,
    aplicar_color,
    aplicar_estado,
    aplicar_tema,
    color_con_alfa,
)
from data_dragon import (
    get_champion_icon_path,
    get_item_icon_path,
    get_rune_icon_path,
    get_spell_icon_path,
)


class RejillaCategoriasSituacionales(QWidget):
    """Distribuye categorías situacionales en columnas según el ancho disponible."""

    ANCHO_MINIMO_COLUMNA = 150
    SEPARACION = 12

    def __init__(self, parent: QWidget | None = None) -> None:
        """Prepara una rejilla adaptable vacía.

        Args:
            parent: Widget contenedor opcional.
        Returns:
            None.
        """
        super().__init__(parent)
        self._rejilla = QGridLayout(self)
        self._rejilla.setContentsMargins(0, 0, 0, 0)
        self._rejilla.setHorizontalSpacing(self.SEPARACION)
        self._rejilla.setVerticalSpacing(self.SEPARACION)
        self._columnas: list[QWidget] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self) -> QSize:
        """Permite que el contenedor reduzca su ancho para activar el reflujo.

        Args:
            None.
        Returns:
            QSize sin ancho mínimo forzado.
        """
        return QSize(0, 0)

    def establecer_columnas(self, columnas: list[QWidget]) -> None:
        """Reemplaza las categorías visibles y las distribuye en la rejilla.

        Args:
            columnas: Widgets de categoría ya preparados.
        Returns:
            None.
        """
        for columna in self._columnas:
            self._rejilla.removeWidget(columna)
            columna.hide()
            columna.setParent(None)
            columna.deleteLater()
        self._columnas = columnas
        self._recolocar_columnas()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Recalcula el número de columnas al cambiar el ancho disponible.

        Args:
            event: Evento de cambio de tamaño de Qt.
        Returns:
            None.
        """
        super().resizeEvent(event)
        self._recolocar_columnas()

    def _recolocar_columnas(self) -> None:
        """Coloca las categorías en una, dos o cuatro columnas según el ancho.

        Args:
            None.
        Returns:
            None.
        """
        while self._rejilla.count():
            self._rejilla.takeAt(0)
        for indice in range(len(self._columnas)):
            self._rejilla.setColumnStretch(indice, 0)
        cantidad = len(self._columnas)
        if not cantidad:
            return
        columnas = min(
            cantidad,
            max(
                1,
                (self.width() + self.SEPARACION)
                // (self.ANCHO_MINIMO_COLUMNA + self.SEPARACION),
            ),
        )
        for indice, widget in enumerate(self._columnas):
            self._rejilla.addWidget(widget, indice // columnas, indice % columnas)
            self._rejilla.setColumnStretch(indice % columnas, 1)


class DraftPowerCurveWidget(QWidget):
    """Widget de dibujo vectorizado para comparar las curvas de poder de Aliados vs Enemigos."""

    TIME_BRACKETS = ("0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40+")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.my_team_curve: dict[str, float] = {b: 50.0 for b in self.TIME_BRACKETS}
        self.enemy_team_curve: dict[str, float] = {b: 50.0 for b in self.TIME_BRACKETS}
        self.power_spike_label: str = "Calculando..."
        self.scope_label: str = "Equipo vs equipo"

    def set_data(
        self,
        my_curve: dict[str, float],
        enemy_curve: dict[str, float],
        spike_label: str,
        scope_label: str = "Equipo vs equipo",
    ) -> None:
        self.my_team_curve = my_curve
        self.enemy_team_curve = enemy_curve
        self.power_spike_label = spike_label
        self.scope_label = scope_label
        self.setToolTip(f"⚡ Power Spike: {spike_label}")
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Fondo del widget
        painter.fillRect(0, 0, w, h, color_con_alfa("superficie", 255))

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
        grid_pen = QPen(color_con_alfa("texto", 25), 1, Qt.PenStyle.DashLine)
        painter.setPen(grid_pen)
        font_grid = QFont("Segoe UI", 9)
        painter.setFont(font_grid)

        # Separación basada en la fuente real; conservar siempre el 50%.
        px_per_step = plot_h / (max_v - min_v)
        label_step = max(
            1, math.ceil((painter.fontMetrics().height() + 4) / px_per_step)
        )
        first_tick = 50 + math.ceil((min_v - 50) / label_step) * label_step
        for step_v in range(first_tick, int(max_v) + 1, label_step):
            yp = y_pos(float(step_v))
            painter.drawLine(int(margin_left), int(yp), int(w - margin_right), int(yp))
            painter.setPen(color_con_alfa("secundario", 255))
            painter.drawText(5, int(yp) + 4, f"{step_v}%")
            painter.setPen(grid_pen)

        # Línea de balance 50%
        y50 = y_pos(50.0)
        painter.setPen(QPen(color_con_alfa("teal", 120), 1.5, Qt.PenStyle.SolidLine))
        painter.drawLine(int(margin_left), int(y50), int(w - margin_right), int(y50))

        # Puntos x
        n_points = len(self.TIME_BRACKETS)
        step_x = plot_w / max(1, n_points - 1)
        x_coords = [margin_left + i * step_x for i in range(n_points)]

        # Etiquetas de tiempo en X
        painter.setPen(color_con_alfa("secundario", 255))
        for i, b_text in enumerate(self.TIME_BRACKETS):
            xp = x_coords[i]
            painter.drawText(int(xp - 18), int(h - 12), f"{b_text}m")

        # Puntos y trayectorias
        my_pts = [
            (x_coords[i], y_pos(self.my_team_curve.get(b, 50.0)))
            for i, b in enumerate(self.TIME_BRACKETS)
        ]
        en_pts = [
            (x_coords[i], y_pos(self.enemy_team_curve.get(b, 50.0)))
            for i, b in enumerate(self.TIME_BRACKETS)
        ]

        # Trazar curva enemigo (Rojo Coral)
        en_path = QPainterPath()
        en_path.moveTo(en_pts[0][0], en_pts[0][1])
        for xp, yp in en_pts[1:]:
            en_path.lineTo(xp, yp)
        painter.setPen(QPen(color_con_alfa("desventaja", 255), 2.5))
        painter.drawPath(en_path)

        # Trazar curva aliados (Verde Esmeralda)
        my_path = QPainterPath()
        my_path.moveTo(my_pts[0][0], my_pts[0][1])
        for xp, yp in my_pts[1:]:
            my_path.lineTo(xp, yp)
        painter.setPen(QPen(color_con_alfa("ventaja", 255), 3.0))
        painter.drawPath(my_path)

        # Dibujar nodos
        for i, (xp, yp) in enumerate(my_pts):
            val = self.my_team_curve.get(self.TIME_BRACKETS[i], 50.0)
            painter.setBrush(QBrush(color_con_alfa("ventaja", 255)))
            painter.setPen(QPen(color_con_alfa("texto", 255), 1.5))
            painter.drawEllipse(int(xp - 4), int(yp - 4), 8, 8)
            # Valor texto arriba
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.setPen(color_con_alfa("ventaja", 255))
            painter.drawText(int(xp - 14), int(yp - 8), f"{val:.1f}%")

        for i, (xp, yp) in enumerate(en_pts):
            val = self.enemy_team_curve.get(self.TIME_BRACKETS[i], 50.0)
            painter.setBrush(QBrush(color_con_alfa("desventaja", 255)))
            painter.setPen(QPen(color_con_alfa("texto", 255), 1.5))
            painter.drawEllipse(int(xp - 3), int(yp - 3), 6, 6)

        # Título y Power Spike comparten fila y alineación vertical.
        painter.setFont(title_font)
        painter.setPen(color_con_alfa("texto", 255))
        painter.drawText(
            QRect(margin_left, 8, badge_x - margin_left - 16, badge_h),
            Qt.AlignmentFlag.AlignVCenter,
            title_text,
        )
        painter.setFont(spike_font)
        painter.setBrush(QBrush(color_con_alfa("elevada", 255)))
        painter.setPen(QPen(color_con_alfa("ventaja", 255), 1.5))
        painter.drawRoundedRect(badge_x, 8, badge_w, badge_h, 6, 6)
        painter.setPen(color_con_alfa("ventaja", 255))
        painter.drawText(
            QRect(badge_x + 10, 8, badge_w - 20, badge_h),
            Qt.AlignmentFlag.AlignVCenter,
            spike_text,
        )

        painter.setFont(legend_font)
        painter.drawText(
            QRect(legend_x, legend_y, my_legend_w, badge_h),
            Qt.AlignmentFlag.AlignVCenter,
            "━ Mi Equipo",
        )
        painter.setPen(color_con_alfa("desventaja", 255))
        painter.drawText(
            QRect(legend_x + my_legend_w + 20, legend_y, enemy_legend_w, badge_h),
            Qt.AlignmentFlag.AlignVCenter,
            "━ Enemigos",
        )


class IconoBaneo(QLabel):
    """Icono de campeón baneado con velo oscuro y aspa de baneo."""

    def setPixmap(self, imagen: QPixmap) -> None:
        """Oscurece una copia del pixmap recibido y añade el aspa de baneo; retorna None."""
        if imagen.isNull():
            super().setPixmap(imagen)
            return
        lienzo = QPixmap(imagen.size())
        lienzo.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(lienzo)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.drawPixmap(0, 0, imagen)
        pintor.fillRect(lienzo.rect(), QColor(5, 7, 12, 90))
        lapiz = QPen(QColor(PALETA["desventaja"]), 2)
        pintor.setPen(lapiz)
        margen = max(6, lienzo.width() // 5)
        pintor.drawLine(
            margen, margen, lienzo.width() - margen, lienzo.height() - margen
        )
        pintor.drawLine(
            lienzo.width() - margen, margen, margen, lienzo.height() - margen
        )
        pintor.end()
        super().setPixmap(lienzo)


class TarjetaPaginaRunas(QFrame):
    """Página de runas seleccionable con toda su área como zona de clic."""

    clicked = Signal()

    def mousePressEvent(self, evento: QMouseEvent) -> None:
        """Emite `clicked` con el botón izquierdo y delega el resto; retorna None."""
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(evento)


class DraftToolDialog(QDialog):
    """Diálogo completo de la Herramienta de Draft en tiempo real."""

    ROLES = list(DraftAnalyzerService.ROLES)

    # Marca de línea probable: en el draft nadie sabe la línea real del rival.
    PROBABLE_ROLE_PREFIX = "~"

    # Marcador de línea desconocida: no hay dato del cliente ni del campeón.
    UNKNOWN_ROLE = "?"

    # Número de baneos por equipo en una selección real.
    MAX_BANS = 5

    # Rango de análisis/importación cuando el contexto no aporta otro válido.
    RANGO_IMPORTACION = RANGO_PREDETERMINADO

    # Líneas de la herramienta hacia la clave minúscula de las matrices locales.
    MAPA_LINEAS_IMPORTACION = {
        "top": "top",
        "jungle": "jungle",
        "mid": "mid",
        "bot": "adc",
        "adc": "adc",
        "support": "support",
    }

    # Etiquetas legibles de esas claves para los mensajes de importación.
    LINEAS_ETIQUETA = {
        "top": "Top",
        "jungle": "Jungle",
        "mid": "Mid",
        "adc": "Bot",
        "support": "Support",
    }

    def __init__(self, parent: Any = None) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        super().__init__(parent)
        self.setWindowTitle("Solralol — Herramienta de Draft en Tiempo Real")
        self.resize(1500, 920)
        self.setMinimumSize(900, 700)
        aplicar_tema(self)

        self.analyzer = DraftAnalyzerService()
        self.lcu_service = LCUService()
        # La versión del catálogo instalado basta para los assets; abrir el
        # draft no debe esperar una petición HTTP a versions.json.
        self.dd_version = self.analyzer.version
        self._icon_cache = DraftIconCache(self)

        self.all_champion_names = sorted(
            {
                prof.get("character") or prof.get("basic_info", {}).get("name")
                for prof in self.analyzer.champions.values()
                if prof.get("character") or prof.get("basic_info", {}).get("name")
            }
        )

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
        self.my_header_ban_cards: list[QFrame] = []
        self.enemy_header_ban_cards: list[QFrame] = []
        self.lcu_draft_active = False
        self.curve_scope = "Equipo vs equipo"
        self._last_session_key = None
        self._repositorio_local = RepositorioCampeones(self.analyzer.path)
        self._pagina_runas_activa = 1
        self._contexto_activo: tuple[str, str, str] = ("", "", "")
        self._datos_importacion: dict[str, Any] = {}
        self._estado_importacion: dict[str, str] = {}
        self._tarea_importacion: dict[str, Any] = {}

        self._build_ui()
        self._check_lcu_status()
        self._update_analytics()

    def _build_ui(self) -> None:
        """Construye la presentación con los parámetros recibidos y devuelve el resultado existente."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # 1. TOP HEADER BAR
        header_frame = QFrame()
        aplicar_apariencia(header_frame, "tarjeta")
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(14, 10, 14, 10)

        title_lbl = QLabel("Herramienta de Draft")
        title_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        aplicar_apariencia(title_lbl, "pagina")

        self.lcu_status_lbl = QLabel("🟡 Comprobando LCU...")
        self.lcu_status_lbl.setObjectName("draftConnectionStatus")
        self.lcu_status_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        aplicar_apariencia(self.lcu_status_lbl, "estado")

        refresh_lcu_btn = QPushButton("🔄 Reconectar LCU")
        refresh_lcu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        aplicar_apariencia(refresh_lcu_btn, "tarjeta")
        refresh_lcu_btn.clicked.connect(self._check_lcu_status)

        # Los datos del jugador local siguen existiendo para la lógica de LCU,
        # pero la cabecera se reserva para los baneos recomendados.
        local_champ_lbl = QLabel("Tu Campeón:")
        aplicar_apariencia(local_champ_lbl, "etiqueta")
        self.local_champ_combo = QComboBox()
        self.local_champ_combo.addItems([""] + self.all_champion_names)
        self.local_champ_combo.setCurrentText("")
        self.local_champ_combo.currentIndexChanged.connect(self._on_draft_changed)

        local_role_lbl = QLabel("Tu Rol:")
        aplicar_apariencia(local_role_lbl, "etiqueta")
        self.local_role_combo = QComboBox()
        self.local_role_combo.addItems(self.ROLES)
        self.local_role_combo.setCurrentText("Top")
        self.local_role_combo.currentIndexChanged.connect(self._on_draft_changed)

        header_layout.addWidget(title_lbl)
        header_layout.addWidget(self.lcu_status_lbl)
        header_layout.addWidget(refresh_lcu_btn)
        manual_role_label = QLabel("Mi rol:")
        aplicar_apariencia(manual_role_label, "etiqueta")
        header_layout.addWidget(manual_role_label)
        header_layout.addWidget(self.local_role_combo)
        header_layout.addStretch()
        bans_header = QFrame()
        bans_header.setObjectName("draftHeaderBans")
        aplicar_apariencia(bans_header, "tarjeta")
        bans_header_layout = QHBoxLayout(bans_header)
        bans_header_layout.setContentsMargins(10, 6, 10, 6)
        bans_header_layout.setSpacing(8)
        self._construir_bans_equipo(
            bans_header_layout,
            "MIS BANEOS",
            "aliado",
            self.my_header_ban_labels,
            self.my_header_ban_cards,
        )
        separador_bans = QFrame()
        separador_bans.setObjectName("draftBanSeparator")
        separador_bans.setFixedWidth(1)
        separador_bans.setFixedHeight(52)
        bans_header_layout.addWidget(separador_bans)
        self._construir_bans_equipo(
            bans_header_layout,
            "ENEMIGOS",
            "enemigo",
            self.enemy_header_ban_labels,
            self.enemy_header_ban_cards,
        )
        bans_header.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        header_layout.addWidget(bans_header)

        main_layout.addWidget(header_frame)

        # 2. SCROLLABLE CONTENT BODY
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        aplicar_apariencia(scroll_area, "tarjeta")

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(14)

        # 2A. GRID DE EQUIPOS 5v5
        teams_frame = QFrame()
        teams_frame.setObjectName("draftTeamsSection")
        aplicar_apariencia(teams_frame, "tarjeta")
        teams_layout = QVBoxLayout(teams_frame)
        teams_layout.setContentsMargins(14, 14, 14, 14)
        teams_layout.setSpacing(10)

        teams_header = QHBoxLayout()
        teams_title = QLabel("COMPOSICIONES 5v5")
        teams_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        aplicar_apariencia(teams_title, "seccion")
        teams_header.addWidget(teams_title)
        teams_header.addStretch()
        teams_hint = QLabel("✓ pick confirmado · casilla sin marcar = pre-pick")
        aplicar_apariencia(teams_hint, "metadatos")
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
        aplicar_apariencia(my_team_title, "metadatos")
        self.my_team_overall_lbl = QLabel("WR —")
        self.my_team_overall_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.my_team_overall_lbl.setToolTip(
            "Media de los win rates OVERALL de los campeones con al menos un pick/pre-pick. "
            "Referencia para estimar la probabilidad de victoria, no es una probabilidad calibrada."
        )
        aplicar_apariencia(self.my_team_overall_lbl, "tarjeta")
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
            role_cb.setMinimumWidth(96)
            role_cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
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
            matchup_lbl.setMinimumWidth(64)
            matchup_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            matchup_lbl.setToolTip("Win rate overall del campeón.")

            state_cb = QCheckBox()
            state_cb.setFixedWidth(26)
            state_cb.setToolTip(
                "Marcado: campeón seleccionado. Sin marcar: pre-seleccionado."
            )
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
        aplicar_apariencia(enemy_team_title, "metadatos")
        self.enemy_team_overall_lbl = QLabel("WR —")
        self.enemy_team_overall_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.enemy_team_overall_lbl.setToolTip(
            "Media de los win rates OVERALL de los campeones enemigos con al menos un pick/pre-pick. "
            "Referencia para estimar la probabilidad de victoria, no es una probabilidad calibrada."
        )
        aplicar_apariencia(self.enemy_team_overall_lbl, "tarjeta")
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
            role_lbl.setMinimumWidth(96)
            aplicar_apariencia(role_lbl, "etiqueta")
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
            matchup_lbl.setMinimumWidth(64)
            matchup_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            matchup_lbl.setToolTip("Win rate overall del campeón.")

            state_cb = QCheckBox()
            state_cb.setFixedWidth(26)
            state_cb.setToolTip(
                "Marcado: campeón seleccionado. Sin marcar: pre-seleccionado."
            )
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
        teams_grid_layout.addLayout(enemy_team_box)
        teams_layout.addLayout(teams_grid_layout)
        teams_layout.addLayout(self._create_damage_comparison_layout())

        content_layout.addWidget(teams_frame)

        # 2B. DESGRASE DE DAÑO Y PODER
        analytics_frame = QFrame()
        aplicar_apariencia(analytics_frame, "tarjeta")
        analytics_layout = QHBoxLayout(analytics_frame)
        analytics_layout.setContentsMargins(12, 12, 12, 12)

        scope_layout = QVBoxLayout()
        scope_layout.setSpacing(6)
        for scope in ["Equipo vs equipo", "Top", "Jungle", "Mid", "Bot", "Support"]:
            button = QPushButton(scope)
            button.setCheckable(True)
            button.setChecked(scope == self.curve_scope)
            button.setProperty("curve_scope", scope)
            aplicar_apariencia(button, "tarjeta")
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
        aplicar_apariencia(rec_frame, "tarjeta")
        rec_layout = QVBoxLayout(rec_frame)
        rec_layout.setContentsMargins(16, 14, 16, 16)
        rec_layout.setSpacing(12)

        bans_header = QHBoxLayout()
        bans_title = QLabel("BANEOS RECOMENDADOS")
        bans_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        aplicar_apariencia(bans_title, "metadatos")
        bans_header.addWidget(bans_title)
        bans_header.addStretch()
        bans_hint = QLabel("Win rate de tu campeón frente al rival")
        aplicar_apariencia(bans_hint, "metadatos")
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
            aplicar_apariencia(name_lbl, "tarjeta")
            wr_lbl = QLabel("WR —")
            wr_lbl.setObjectName("draftBanRate")
            wr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            aplicar_apariencia(wr_lbl, "etiqueta")
            tip_lbl = QLabel("")
            tip_lbl.setAlignment(
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            )
            tip_lbl.setWordWrap(True)
            aplicar_apariencia(tip_lbl, "metadatos")
            card_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
            card_layout.addWidget(name_lbl)
            card_layout.addWidget(wr_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
            card_layout.addSpacing(2)
            card_layout.addWidget(tip_lbl, 1)
            bans_row.addWidget(card, 1)
            self.ban_card_widgets.append(
                {"icon": icon_lbl, "name": name_lbl, "wr": wr_lbl, "tip": tip_lbl}
            )
        rec_layout.addLayout(bans_row)

        content_layout.addWidget(rec_frame)

        # 2D. IMPORTACIÓN AL CLIENTE (LCU): BUILD, RUNAS Y HECHIZOS
        import_frame = QFrame()
        import_frame.setObjectName("draftImportSection")
        aplicar_apariencia(import_frame, "tarjeta")
        import_layout = QVBoxLayout(import_frame)
        import_layout.setContentsMargins(16, 14, 16, 16)
        import_layout.setSpacing(12)

        import_header = QHBoxLayout()
        import_title = QLabel("IMPORTACIÓN AL CLIENTE")
        import_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        aplicar_apariencia(import_title, "seccion")
        import_header.addWidget(import_title)
        import_header.addStretch()
        import_hint = QLabel("Páginas de runas locales · Build asociada · Hechizos")
        aplicar_apariencia(import_hint, "metadatos")
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
        aplicar_apariencia(build_title, "etiqueta")
        build_header.addWidget(build_title)
        build_header.addStretch()
        build_box.addLayout(build_header)

        build_body = QHBoxLayout()
        build_body.setSpacing(6)
        build_items_widget = QWidget()
        build_items_row = QHBoxLayout(build_items_widget)
        build_items_row.setContentsMargins(0, 0, 0, 0)
        build_items_row.setSpacing(6)
        self.build_item_labels: list[QLabel] = []
        for _ in range(6):
            item_lbl = QLabel()
            item_lbl.setFixedSize(44, 44)
            item_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item_lbl.setObjectName("importItemIcon")
            item_lbl.setToolTip("Objeto principal de la build")
            build_items_row.addWidget(item_lbl)
            self.build_item_labels.append(item_lbl)
        build_body.addWidget(build_items_widget)
        build_body.addStretch(1)
        boots_widget = QWidget()
        boots_layout = QVBoxLayout(boots_widget)
        boots_layout.setContentsMargins(0, 0, 0, 0)
        boots_layout.setSpacing(4)
        boots_title = QLabel("BOTAS")
        boots_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        aplicar_apariencia(boots_title, "metadatos")
        boots_layout.addWidget(boots_title)
        self.build_boots_label = QLabel()
        self.build_boots_label.setFixedSize(44, 44)
        self.build_boots_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.build_boots_label.setObjectName("importBootsIcon")
        boots_layout.addWidget(self.build_boots_label, 0, Qt.AlignmentFlag.AlignCenter)
        build_body.addWidget(boots_widget)
        build_box.addLayout(build_body)

        self.build_note_lbl = QLabel("")
        self.build_note_lbl.setWordWrap(True)
        self.build_note_lbl.setObjectName("importNote")
        build_box.addWidget(self.build_note_lbl)

        # Bloque de objetos situacionales recomendados
        situational_title = QLabel("SITUACIONALES")
        aplicar_apariencia(situational_title, "etiqueta")
        build_box.addWidget(situational_title)

        self.situational_container = RejillaCategoriasSituacionales()
        self.situational_layout = self.situational_container._rejilla
        build_box.addWidget(self.situational_container)

        build_box.addStretch()
        import_row.addWidget(build_card, 3)

        # --- Columna 2: páginas de runas seleccionables y acción combinada ---
        runes_box = QVBoxLayout()
        runes_box.setSpacing(8)
        paginas_title = QLabel("PÁGINAS DE RUNAS")
        aplicar_apariencia(paginas_title, "etiqueta")
        runes_box.addWidget(paginas_title)
        self.rune_page_rows: dict[int, dict[str, Any]] = {}
        for page_index in (1, 2):
            tarjeta = TarjetaPaginaRunas()
            tarjeta.setObjectName("importRunePageCard")
            tarjeta.setProperty("seleccionado", page_index == self._pagina_runas_activa)
            tarjeta.setProperty("vacio", False)
            fila_interna = QVBoxLayout(tarjeta)
            fila_interna.setContentsMargins(10, 8, 10, 8)
            fila_interna.setSpacing(6)
            cabecera = QHBoxLayout()
            cabecera.setSpacing(6)
            check_lbl = QLabel("✓")
            check_lbl.setObjectName("importRunePageCheck")
            check_lbl.setFixedWidth(16)
            check_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check_lbl.setVisible(page_index == self._pagina_runas_activa)
            cabecera.addWidget(check_lbl)
            nombre_lbl = QLabel(f"PÁGINA {page_index}")
            aplicar_apariencia(nombre_lbl, "etiqueta")
            cabecera.addWidget(nombre_lbl)
            cabecera.addStretch(1)
            keystone_lbl = QLabel("—")
            aplicar_apariencia(keystone_lbl, "etiqueta")
            cabecera.addWidget(keystone_lbl)
            fila_interna.addLayout(cabecera)
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
            icons_row.addStretch(1)
            fila_interna.addLayout(icons_row)
            vacio_lbl = QLabel("")
            vacio_lbl.setWordWrap(True)
            vacio_lbl.setVisible(False)
            aplicar_apariencia(vacio_lbl, "metadatos")
            fila_interna.addWidget(vacio_lbl)
            tarjeta.clicked.connect(partial(self._seleccionar_pagina_runas, page_index))
            runes_box.addWidget(tarjeta)
            self.rune_page_rows[page_index] = {
                "card": tarjeta,
                "check": check_lbl,
                "nombre": nombre_lbl,
                "keystone": keystone_lbl,
                "icons": icon_slots,
                "vacio": vacio_lbl,
                "page": None,
            }

        self.btn_import_build_runes = QPushButton("↓  Importar build + runas")
        self.btn_import_build_runes.setToolTip(
            "Importa la página de runas seleccionada y la build asociada a esa "
            "página en una sola acción, usando el campeón, la línea y el rango "
            "activos. Crea la página general «Solralol - [campeón] Build» en los "
            "conjuntos del cliente, con objetos principales, botas y "
            "situacionales (en jungla el bloque inicial reúne los 3 compañeros)."
        )
        self._style_import_button(self.btn_import_build_runes, "green")
        self.btn_import_build_runes.clicked.connect(self._importar_build_y_runas)
        runes_box.addWidget(self.btn_import_build_runes)

        self.import_status = MensajeEstado()
        runes_box.addWidget(self.import_status)
        runes_box.addStretch(1)
        import_row.addLayout(runes_box, 2)

        # --- Columna 3: hechizos de invocador y contexto activo ---
        spells_card = QFrame()
        spells_card.setObjectName("importSpellsCard")
        spells_box = QVBoxLayout(spells_card)
        spells_box.setContentsMargins(12, 12, 12, 12)
        spells_box.setSpacing(12)
        spells_title = QLabel("HECHIZOS")
        aplicar_apariencia(spells_title, "etiqueta")
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

        # Panel explicativo del contexto activo
        context_title = QLabel("CONTEXTO ACTIVO")
        aplicar_apariencia(context_title, "etiqueta")
        spells_box.addWidget(context_title)
        self.context_info_lbl = QLabel("")
        self.context_info_lbl.setWordWrap(True)
        aplicar_apariencia(self.context_info_lbl, "metadatos")
        spells_box.addWidget(self.context_info_lbl)

        spells_box.addStretch()

        self.btn_import_spells = QPushButton("↓  Importar hechizos")
        self.btn_import_spells.setToolTip(
            "Importar los dos hechizos de invocador al cliente"
        )
        self._style_import_button(self.btn_import_spells, "blue")
        self.btn_import_spells.clicked.connect(self._import_spells)
        spells_box.addWidget(self.btn_import_spells)
        import_row.addWidget(spells_card, 1)

        import_layout.addLayout(import_row)

        content_layout.addWidget(import_frame)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        self.reflujo_cabecera = Reflujo(header_frame, [header_layout], 1100)
        self.reflujo_equipos = Reflujo(teams_frame, [teams_grid_layout], 1050)
        self.reflujo_importacion = Reflujo(import_frame, [import_row], 1050)
        self.reflujo_bans = Reflujo(rec_frame, [bans_row], 750)

    @staticmethod
    def _style_import_button(button: QPushButton, tone: str) -> None:
        """Aplica la base común de los botones de importación; retorna None."""
        background = {
            "blue": PALETA["teal"],
            "green": PALETA["borde"],
            "purple": PALETA["magenta"],
        }[tone]
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoDefault(False)
        button.setMinimumHeight(34)
        aplicar_color(button, background)

    def _create_damage_comparison_layout(self) -> QHBoxLayout:
        """Crea el desglose compacto, integrado bajo las dos composiciones."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.setSpacing(8)

        my_title = QLabel("🛡 Mi equipo")
        my_title.setFixedWidth(100)
        aplicar_apariencia(my_title, "etiqueta")
        self.my_damage_bar = DamageBarWidget(50.0, 45.0, 5.0)
        self.my_damage_bar.setToolTip(
            "Distribución estimada de daño físico, mágico y verdadero de tus aliados."
        )

        versus = QLabel("VS")
        versus.setFixedWidth(30)
        versus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        aplicar_apariencia(versus, "etiqueta")

        self.enemy_damage_bar = DamageBarWidget(50.0, 45.0, 5.0)
        self.enemy_damage_bar.setToolTip(
            "Distribución estimada de daño físico, mágico y verdadero del rival."
        )
        enemy_title = QLabel("Enemigos ⚔")
        enemy_title.setFixedWidth(100)
        enemy_title.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        aplicar_apariencia(enemy_title, "etiqueta")

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
            ("LÍNEA", 96, Qt.AlignmentFlag.AlignLeft, False),
            ("", 36, Qt.AlignmentFlag.AlignCenter, False),
            ("CAMPEÓN", 0, Qt.AlignmentFlag.AlignLeft, True),
            ("WR", 64, Qt.AlignmentFlag.AlignCenter, False),
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

    def _construir_bans_equipo(
        self,
        disposicion: QHBoxLayout,
        titulo: str,
        equipo: str,
        etiquetas: list[QLabel],
        tarjetas: list[QFrame],
    ) -> None:
        """Crea el grupo vertical de baneo del equipo en la fila recibida; retorna None.

        El rótulo va sobre los cinco huecos para que el bloque quepa en la
        cabecera sin apretar el resto. ``equipo`` marca el acento sutil del
        color de equipo (``aliado`` con teal apagado, ``enemigo`` con rojo
        apagado) sin colores agresivos.
        """
        grupo = QVBoxLayout()
        grupo.setSpacing(4)
        grupo.setContentsMargins(0, 0, 0, 0)
        rotulo = QLabel(titulo)
        rotulo.setObjectName("draftBanTeamTitle")
        rotulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        aplicar_apariencia(rotulo, "etiqueta")
        grupo.addWidget(rotulo)
        fila = QHBoxLayout()
        fila.setSpacing(4)
        for indice in range(self.MAX_BANS):
            hueco = QFrame()
            hueco.setObjectName("draftBanSlot")
            hueco.setFixedSize(32, 32)
            hueco.setProperty("equipo", equipo)
            hueco.setProperty("ocupado", False)
            relleno = QHBoxLayout(hueco)
            relleno.setContentsMargins(2, 2, 2, 2)
            marca = IconoBaneo()
            marca.setObjectName("draftBanSlotIcon")
            marca.setAlignment(Qt.AlignmentFlag.AlignCenter)
            marca.setFixedSize(26, 26)
            relleno.addWidget(marca, 0, Qt.AlignmentFlag.AlignCenter)
            hueco.setToolTip(f"Hueco de baneo {indice + 1} · pendiente")
            tarjetas.append(hueco)
            etiquetas.append(marca)
            fila.addWidget(hueco)
        grupo.addLayout(fila)
        disposicion.addLayout(grupo)

    def _actualizar_slot_ban(
        self, tarjeta: QFrame, marca: QLabel, campeon: str, equipo: str
    ) -> None:
        """Pinta el baneo recibido o deja el hueco limpio; retorna None."""
        ocupado = bool(campeon)
        if tarjeta.property("ocupado") != ocupado:
            tarjeta.setProperty("ocupado", ocupado)
            actualizar_estilo(tarjeta)
        if ocupado:
            self._icon_cache.assign(
                marca,
                ("champion", campeon, self.dd_version),
                26,
                partial(get_champion_icon_path, campeon, self.dd_version),
                placeholder="",
            )
            texto_equipo = "aliado" if equipo == "aliado" else "enemigo"
            tarjeta.setToolTip(f"Ban {texto_equipo}: {campeon}")
        else:
            self._icon_cache.assign(marca, None, 26, placeholder="")
            tarjeta.setToolTip("Hueco de baneo · pendiente")

    def _limpiar_bans_header(self) -> None:
        """Vacía los diez huecos de baneo al salir del draft real; retorna None."""
        for tarjetas, etiquetas, equipo in (
            (self.my_header_ban_cards, self.my_header_ban_labels, "aliado"),
            (self.enemy_header_ban_cards, self.enemy_header_ban_labels, "enemigo"),
        ):
            for tarjeta, marca in zip(tarjetas, etiquetas):
                self._actualizar_slot_ban(tarjeta, marca, "", equipo)

    def _check_lcu_status(self) -> None:
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        if self.lcu_service.is_connected():
            self.lcu_status_lbl.setText("🟢 LCU Conectado")
            aplicar_apariencia(self.lcu_status_lbl, "tarjeta")
            session = self.lcu_service.get_champ_select_session()
            if session:
                self.update_from_lcu_session(session)
        else:
            self.lcu_status_lbl.setText("🟡 Modo Manual / LCU Desconectado")
            aplicar_apariencia(self.lcu_status_lbl, "tarjeta")
            self._set_lcu_managed_controls(False)
            self._limpiar_bans_header()

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
                tuple(
                    player.get(field)
                    for field in (
                        "cellId",
                        "championId",
                        "championPickIntent",
                        "assignedPosition",
                    )
                )
                for player in session.get(team, [])[:5]
            )
            for team in ("myTeam", "theirTeam")
        )
        bans = tuple(
            tuple(
                action.get(field)
                for field in ("championId", "actorCellId", "isAllyAction")
            )
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
            + self.my_team_combo_widgets
            + self.enemy_team_combo_widgets
            + self.my_team_role_combos
            + self.my_team_pick_state_widgets
            + self.enemy_team_pick_state_widgets
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
        for champion_combo, state_combo in zip(
            self.my_team_combo_widgets, self.my_team_pick_state_widgets
        ):
            champion_combo.setCurrentText("-- Vacío --")
            state_combo.setChecked(False)
        for champion_combo, state_combo in zip(
            self.enemy_team_combo_widgets, self.enemy_team_pick_state_widgets
        ):
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
            champ_name = (
                self.analyzer.get_champion_name_by_id(champ_id) if champ_id else ""
            )
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
            champ_name = (
                self.analyzer.get_champion_name_by_id(champ_id) if champ_id else ""
            )
            if champ_name:
                self.enemy_team_combo_widgets[i].setCurrentText(champ_name)
                self.enemy_team_pick_state_widgets[i].setChecked(bool(selected_id))

        self._apply_role_hints()

    @staticmethod
    def _role_from_position(position: str) -> str:
        """Traduce la posición que publica LCU al nombre de línea de la interfaz."""
        return {
            "top": "Top",
            "jungle": "Jungle",
            "middle": "Mid",
            "bottom": "Bot",
            "utility": "Support",
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
            f"{self.PROBABLE_ROLE_PREFIX}{role}"
            if probable and role
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
        self.enemy_team_roles = (guessed + [""] * len(names))[: len(names)]
        for label, name, role in zip(
            self.enemy_team_role_labels, names, self.enemy_team_roles
        ):
            if not role:
                label.setText("—")
                aplicar_apariencia(label, "etiqueta")
                label.setToolTip(
                    "Línea del rival: el cliente no la publica."
                    if not name or name == "-- Vacío --"
                    else f"Sin datos de línea para {name}."
                )
                continue
            label.setText(f"{self.PROBABLE_ROLE_PREFIX}{role}")
            aplicar_apariencia(label, "etiqueta")
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
            from_client = (
                self.lcu_draft_active and self.my_team_roles_from_client[index]
            )
            role = self._base_role(combo.currentText())
            roles.append(role if (from_client or not self.lcu_draft_active) else "")
            deduced.append(False)
        if self.lcu_draft_active:
            confirmed = [role for role in roles if role]
            pending = [index for index, role in enumerate(roles) if not role]
            names = [
                self.my_team_combo_widgets[index].currentText() for index in pending
            ]
            for index, name, role in zip(
                pending,
                names,
                self.analyzer.assign_likely_roles(names, exclude=confirmed),
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
                aplicar_apariencia(combo, "metadatos")
                continue
            if role:
                aplicar_apariencia(combo, "metadatos")
                combo.setToolTip(
                    "Línea asignada por el cliente."
                    if self.lcu_draft_active
                    else "Línea que declaras para este aliado."
                )
                continue
            aplicar_apariencia(combo, "metadatos")
            combo.setToolTip(
                "Sin datos de línea: el cliente no publicó la posición de este aliado "
                "y su campeón no aporta roles conocidos."
            )
        if (
            self.lcu_draft_active
            and self._local_slot is not None
            and deduced[self._local_slot]
        ):
            # La cabecera «Tu rol» acompaña a la hipótesis de la fila del jugador.
            self._show_role(
                self.local_role_combo, roles[self._local_slot], probable=True
            )
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
        args = (
            (name, self.analyzer.items, self.dd_version)
            if kind == "item"
            else (name, self.dd_version)
        )
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

        for index, (my_combo, enemy_combo) in enumerate(
            zip(self.my_team_combo_widgets, self.enemy_team_combo_widgets)
        ):
            for label, champion in (
                (self.my_team_matchup_labels[index], my_combo.currentText()),
                (self.enemy_team_matchup_labels[index], enemy_combo.currentText()),
            ):
                if not champion or champion == "-- Vacío --":
                    label.setText("—")
                    aplicar_apariencia(label, "tarjeta")
                    continue
                rate = self.analyzer.get_champion_overall_win_rate(champion)
                color = PALETA["ventaja"] if rate > 50.0 else PALETA["texto"]
                label.setText(f"{rate:.1f}%")
                aplicar_color(label, color)

    def _update_header_bans(self, session: dict[str, Any]) -> None:
        """Rellena los diez huecos con los bans reales de la sesión, por equipo y en orden; retorna None."""
        my_cell_ids = {player.get("cellId") for player in session.get("myTeam", [])}
        enemy_cell_ids = {
            player.get("cellId") for player in session.get("theirTeam", [])
        }
        my_bans: list[str] = []
        enemy_bans: list[str] = []

        for phase_actions in session.get("actions", []):
            for action in phase_actions:
                if not isinstance(action, dict) or action.get("type") != "ban":
                    continue
                champion_id = action.get("championId")
                champion_name = (
                    self.analyzer.get_champion_name_by_id(champion_id)
                    if champion_id
                    else ""
                )
                if not champion_name:
                    continue
                actor_id = action.get("actorCellId")
                if actor_id in my_cell_ids or action.get("isAllyAction") is True:
                    my_bans.append(champion_name)
                elif actor_id in enemy_cell_ids or action.get("isAllyAction") is False:
                    enemy_bans.append(champion_name)

        for tarjetas, etiquetas, bans, equipo in (
            (self.my_header_ban_cards, self.my_header_ban_labels, my_bans, "aliado"),
            (
                self.enemy_header_ban_cards,
                self.enemy_header_ban_labels,
                enemy_bans,
                "enemigo",
            ),
        ):
            for indice, (tarjeta, marca) in enumerate(zip(tarjetas, etiquetas)):
                campeon = bans[indice] if indice < len(bans[: self.MAX_BANS]) else ""
                self._actualizar_slot_ban(tarjeta, marca, campeon, equipo)

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
            (
                self.my_team_overall_lbl,
                self._team_overall_win_rate(self.my_team_combo_widgets),
            ),
            (
                self.enemy_team_overall_lbl,
                self._team_overall_win_rate(self.enemy_team_combo_widgets),
            ),
        ):
            if rate is None:
                label.setText("WR —")
                color = PALETA["secundario"]
            else:
                color = PALETA["ventaja"] if rate > 50.0 else PALETA["texto"]
                label.setText(f"WR {rate:.1f}%")
            aplicar_color(label, color)

    def _update_analytics(self) -> None:
        # Las líneas se recalculan antes de analizar: confirmadas o hipótesis.
        """Actualiza la presentación con los parámetros recibidos y devuelve el resultado existente."""
        self._apply_role_hints()

        # Obtener selecciones de equipo
        my_team_champs = [
            cb.currentText()
            for cb in self.my_team_combo_widgets
            if cb.currentText() and cb.currentText() != "-- Vacío --"
        ]
        enemy_team_champs = [
            cb.currentText()
            for cb in self.enemy_team_combo_widgets
            if cb.currentText() and cb.currentText() != "-- Vacío --"
        ]

        local_champ = self.local_champ_combo.currentText()
        local_role = self._current_local_role()
        if not self.lcu_draft_active:
            # En modo manual el rol marcado en cabecera identifica al jugador.
            # Su campeón es el aliado que ocupe ese mismo rol.
            for role, champion_combo in zip(
                self.my_team_roles, self.my_team_combo_widgets
            ):
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
                for role, combo in zip(
                    self.enemy_team_roles, self.enemy_team_combo_widgets
                )
                if role == self.curve_scope and combo.currentText() != "-- Vacío --"
            ]
        my_curve = self.analyzer.calculate_team_power_curve(curve_my_champs)
        en_curve = self.analyzer.calculate_team_power_curve(curve_enemy_champs)
        spike_label = self.analyzer.analyze_power_spike_phase(my_curve, en_curve)

        self.power_curve_widget.set_data(
            my_curve, en_curve, spike_label, self.curve_scope
        )

        # 3. Bans recomendados (3 tarjetas con icono)
        bans = self.analyzer.get_recommended_bans(local_champ)
        for index, card in enumerate(self.ban_card_widgets):
            if index < len(bans):
                ban = bans[index]
                champion = str(ban.get("champion", ""))
                card["name"].setText(champion)
                card["wr"].setText(f"WR {ban.get('win_rate', 0):.1f}%")
                aplicar_estado(
                    card["wr"],
                    "error" if ban.get("win_rate", 50) < 50.0 else "informacion",
                )
                card["tip"].setText(str(ban.get("tip", "")))
                card["tip"].setToolTip(str(ban.get("tip", "")))
                self._set_icon(card["icon"], "champion", champion, 64)
            else:
                self._set_icon(card["icon"], "champion", "", 64)
                card["name"].setText("Sin dato")
                card["wr"].setText("WR —")
                aplicar_apariencia(card["wr"], "etiqueta")
                card["tip"].setText("")
                card["tip"].setToolTip("")

        # 4. Páginas de runas, build asociada y hechizos del contexto local
        self._refrescar_importacion()

        self._update_team_overall_labels()
        self._update_slot_visuals()

    def _resolver_contexto_importacion(self) -> tuple[str, str, str]:
        """Resuelve campeón, línea local y rango del draft activo; retorna la tupla normalizada.

        El campeón y la línea salen del estado real (LCU rellena los mismos
        selectores) o del selector de la fila asignada a «Mi rol» en modo manual.
        """
        local_role = self._current_local_role()
        if not self.lcu_draft_active:
            campeon = ""
            for role, champion_combo in zip(
                self.my_team_roles, self.my_team_combo_widgets
            ):
                if role == local_role and champion_combo.currentText() not in (
                    "",
                    "-- Vacío --",
                ):
                    campeon = champion_combo.currentText()
                    break
        else:
            campeon = self.local_champ_combo.currentText().strip()

        linea = self.MAPA_LINEAS_IMPORTACION.get(local_role.casefold(), "top")
        return campeon, linea, self.RANGO_IMPORTACION

    def _etiqueta_contexto(self) -> str:
        """Describe el contexto activo para el estado inline; retorna el texto legible."""
        campeon, linea, rango = self._contexto_activo
        return (
            f"{campeon} · {self.LINEAS_ETIQUETA.get(linea, linea)} · "
            f"{dict(OPCIONES_RANGO).get(rango, rango)}"
        )

    def _enemigos_actuales(self) -> list[str]:
        """Devuelve los campeones enemigos con pick; retorna la lista del estado actual."""
        return [
            combo.currentText()
            for combo in self.enemy_team_combo_widgets
            if combo.currentText() and combo.currentText() != "-- Vacío --"
        ]

    def _refrescar_importacion(self) -> None:
        """Carga páginas, build y hechizos locales del contexto sin red; retorna None.

        Solo vuelve a leer el repositorio cuando cambia el contexto (campeón,
        línea o rango) o cuando todavía no hay datos; los cambios de rival
        reutilizan la variante ya cargada y solo repintan la build asociada.
        """
        contexto = self._resolver_contexto_importacion()
        if contexto != self._contexto_activo:
            self._contexto_activo = contexto
            self._restablecer_estado_importacion()
        elif self._datos_importacion:
            self._datos_importacion["enemigos"] = self._enemigos_actuales()
            self._pintar_build_desde_pagina()
            return
        campeon, linea, rango = contexto
        if not campeon:
            self._datos_importacion = {}
            self._pintar_importacion_sin_datos(
                "Selecciona un campeón para ver runas y build locales."
            )
            return
        consulta = self._repositorio_local.consultar(campeon, linea, rango)
        if consulta.estado != EstadoDatos.DISPONIBLE or not consulta.datos:
            self._datos_importacion = {}
            self._pintar_importacion_sin_datos(
                f"No hay datos locales para {self._etiqueta_contexto()}. "
                "Actualiza los datos del campeón desde Análisis."
            )
            return
        variante = consulta.datos
        paginas = [
            pagina for pagina in variante.get("runes") or [] if isinstance(pagina, dict)
        ][:2]
        crudo = variante.get("summoner_spells") or (consulta.perfil or {}).get(
            "summoner_spells"
        )
        self._datos_importacion = {
            "paginas": paginas,
            "hechizos": DraftAnalyzerService.normalizar_hechizos(
                crudo, self._current_local_role()
            ),
            "enemigos": self._enemigos_actuales(),
        }
        self._pintar_importacion_disponible()

    def _pintar_importacion_sin_datos(self, mensaje: str) -> None:
        """Explica la ausencia de datos locales y desactiva las acciones; retorna None."""
        for indice in (1, 2):
            fila = self.rune_page_rows[indice]
            fila["page"] = None
            fila["keystone"].setText("Sin datos")
            fila["vacio"].setText(
                "Sin páginas de runas en los datos locales."
                if indice == 1
                else "Sin segunda página en los datos locales."
            )
            fila["vacio"].setVisible(True)
            for slot in fila["icons"]:
                self._set_icon(slot, "rune", "", 24)
                slot.setToolTip("")
            if fila["card"].property("vacio") is not True:
                fila["card"].setProperty("vacio", True)
                actualizar_estilo(fila["card"])
            fila["card"].setEnabled(False)
        for item_lbl in self.build_item_labels:
            self._set_icon(item_lbl, "item", "", 40)
            item_lbl.setToolTip("")
        self._set_icon(self.build_boots_label, "item", "", 40)
        self.build_boots_label.setToolTip("")
        self.build_note_lbl.setText("Sin build local para esta configuración.")
        self._limpiar_situacionales()
        for spell_lbl in self.spell_icon_labels:
            self._set_icon(spell_lbl, "spell", "", 44)
            spell_lbl.setToolTip("")
        self.spells_text_lbl.setText("Sin hechizos locales.")
        self.import_status.establecer(mensaje, "advertencia")
        self.btn_import_build_runes.setEnabled(False)
        self.btn_import_spells.setEnabled(False)

    def _pintar_importacion_disponible(self) -> None:
        """Pinta páginas, build y hechizos del contexto cargado; retorna None."""
        paginas = self._datos_importacion.get("paginas", [])
        if paginas and self._pagina_runas_activa - 1 >= len(paginas):
            self._pagina_runas_activa = 1
        for indice in (1, 2):
            fila = self.rune_page_rows[indice]
            pagina = paginas[indice - 1] if indice - 1 < len(paginas) else None
            fila["page"] = pagina
            vacio = pagina is None
            if bool(fila["card"].property("vacio")) != vacio:
                fila["card"].setProperty("vacio", vacio)
                actualizar_estilo(fila["card"])
            fila["card"].setEnabled(not vacio)
            fila["vacio"].setVisible(vacio)
            if vacio:
                fila["vacio"].setText(
                    "Sin páginas de runas en los datos locales."
                    if indice == 1
                    else "Sin segunda página en los datos locales."
                )
                fila["keystone"].setText("Sin datos")
                nombres: list[Any] = []
            else:
                fila["keystone"].setText(str(pagina.get("keystone") or "—"))
                nombres = [
                    pagina.get("keystone", ""),
                    *list(pagina.get("slots") or [])[:3],
                    *list(pagina.get("secondary_slots") or [])[:2],
                    *list(pagina.get("shards") or [])[:3],
                ]
            for posicion, slot in enumerate(fila["icons"]):
                nombre = (
                    str(nombres[posicion])
                    if posicion < len(nombres) and nombres[posicion]
                    else ""
                )
                self._set_icon(slot, "rune", nombre, 24)
                slot.setToolTip(nombre)
        self._aplicar_seleccion_pagina()
        self._pintar_build_desde_pagina()
        self._pintar_hechizos()
        self.import_status.establecer(
            f"Listo para importar · {self._etiqueta_contexto()}", "informacion"
        )
        self.btn_import_build_runes.setEnabled(True)
        self.btn_import_spells.setEnabled(True)

    def _aplicar_seleccion_pagina(self) -> None:
        """Marca visualmente la página seleccionada con check y borde de oro; retorna None."""
        for indice, fila in self.rune_page_rows.items():
            seleccionada = indice == self._pagina_runas_activa
            if bool(fila["card"].property("seleccionado")) != seleccionada:
                fila["card"].setProperty("seleccionado", seleccionada)
                actualizar_estilo(fila["card"])
            fila["check"].setVisible(seleccionada)

    def _build_desde_pagina(
        self, campeon: str, pagina: dict[str, Any] | None, enemigos: list[str]
    ) -> dict[str, Any] | None:
        """Deriva la build de importación de la página de runas seleccionada; devuelve None sin datos.

        Los objetos vienen del `build` de la página local; si la página no los
        tiene, se completan con la build del perfil y sus situacionales. Las
        botas son las de la página cuando existen y si no las adaptadas al
        daño enemigo del cálculo local ya probado.
        """
        if not campeon:
            return None
        referencia = self.analyzer.get_champion_build(campeon, enemigos)
        nombres = list((pagina or {}).get("build") or [])
        if not nombres:
            nombres = list(
                (self.analyzer.get_champion_profile(campeon) or {}).get(
                    "most_played_build"
                )
                or []
            )
        ids: list[str] = []
        botas_pagina = ""
        for nombre in nombres:
            identificador = self.analyzer.item_names.get(
                str(nombre).strip().casefold(), ""
            )
            objeto = self.analyzer.items.get(identificador, {})
            if not objeto:
                continue
            if "Boots" in objeto.get("tags", []):
                botas_pagina = identificador
            elif identificador and identificador not in ids:
                ids.append(identificador)
        for item in referencia.get("items", []):
            if len(ids) >= 6:
                break
            if item["id"] not in ids:
                ids.append(item["id"])
        if not ids:
            return None
        resultado = dict(referencia)
        resultado["items"] = [
            {
                "id": identificador,
                "name": str(
                    self.analyzer.items.get(identificador, {}).get(
                        "name", identificador
                    )
                ),
            }
            for identificador in ids[:6]
        ]
        if botas_pagina:
            resultado["boots"] = {
                "id": botas_pagina,
                "name": str(
                    self.analyzer.items.get(botas_pagina, {}).get("name", botas_pagina)
                ),
            }
            resultado["boots_reason"] = "Botas de la página de runas seleccionada."
        return resultado

    def _limpiar_situacionales(self) -> None:
        """Limpia todos los widgets del contenedor de objetos situacionales; retorna None."""
        self.situational_container.establecer_columnas([])

    @classmethod
    def _limpiar_layout_anidado(
        cls,
        layout: QVBoxLayout | QHBoxLayout | QGridLayout,
    ) -> None:
        """Elimina recursivamente los widgets contenidos en diseños anidados."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            sublayout = item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif sublayout is not None:
                cls._limpiar_layout_anidado(sublayout)

    def _pintar_situacionales(self, campeon: str) -> None:
        """Pinta los objetos situacionales agrupados por categoría para el campeón activo; retorna None."""
        self._limpiar_situacionales()
        if not campeon:
            return
        grupos = self.analyzer.get_situational_items(campeon)
        grupos_visibles = [
            grupo
            for grupo in grupos
            if isinstance(grupo, dict)
            and isinstance(grupo.get("items"), list)
            and grupo["items"]
        ]
        if not grupos_visibles:
            msg_lbl = QLabel("Sin objetos situacionales recomendados.")
            aplicar_apariencia(msg_lbl, "metadatos")
            self.situational_container.establecer_columnas([msg_lbl])
            return

        columnas: list[QWidget] = []
        for grupo in grupos_visibles:
            cat_widget = QFrame()
            cat_widget.setObjectName("situationalCategory")
            cat_box = QVBoxLayout(cat_widget)
            cat_box.setContentsMargins(10, 10, 10, 10)
            cat_box.setSpacing(6)
            cat_lbl = QLabel(str(grupo.get("label", "")).upper())
            cat_lbl.setObjectName("situationalCategoryTitle")
            cat_lbl.setWordWrap(True)
            aplicar_apariencia(cat_lbl, "metadatos")
            cat_box.addWidget(cat_lbl)
            separador = QFrame()
            separador.setObjectName("situationalCategoryDivider")
            separador.setFixedHeight(1)
            cat_box.addWidget(separador)
            for item in grupo["items"]:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id", ""))
                metadata = self.analyzer.items.get(item_id, {})
                nombre = str(item.get("name") or metadata.get("name") or item_id)
                fila = QWidget()
                fila.setObjectName("situationalItemRow")
                fila_layout = QHBoxLayout(fila)
                fila_layout.setContentsMargins(0, 0, 0, 0)
                fila_layout.setSpacing(8)
                item_lbl = QLabel()
                item_lbl.setFixedSize(32, 32)
                item_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                item_lbl.setObjectName("importItemIcon")
                self._set_icon(item_lbl, "item", item_id, 32)
                item_lbl.setToolTip(nombre)
                nombre_lbl = QLabel(nombre)
                nombre_lbl.setObjectName("situationalItemName")
                nombre_lbl.setWordWrap(True)
                nombre_lbl.setToolTip(nombre)
                fila_layout.addWidget(item_lbl, 0, Qt.AlignmentFlag.AlignTop)
                fila_layout.addWidget(nombre_lbl, 1)
                cat_box.addWidget(fila)
            cat_box.addStretch(1)
            columnas.append(cat_widget)
        self.situational_container.establecer_columnas(columnas)

    def _pintar_build_desde_pagina(self) -> None:
        """Muestra la build asociada a la página seleccionada, sin datos anteriores; retorna None."""
        campeon = self._contexto_activo[0]
        paginas = self._datos_importacion.get("paginas", [])
        pagina = (
            paginas[self._pagina_runas_activa - 1]
            if self._pagina_runas_activa - 1 < len(paginas)
            else None
        )
        build = self._build_desde_pagina(
            campeon, pagina, self._datos_importacion.get("enemigos", [])
        )
        self._datos_importacion["build"] = build
        self._pintar_situacionales(campeon)
        if not build:
            for item_lbl in self.build_item_labels:
                self._set_icon(item_lbl, "item", "", 40)
                item_lbl.setToolTip("")
            self._set_icon(self.build_boots_label, "item", "", 40)
            self.build_boots_label.setToolTip("")
            self.build_note_lbl.setText("Sin build local para esta configuración.")
            return
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
            self.build_boots_label.setToolTip(
                f"{boots['name']} — {build.get('boots_reason', '')}"
            )
        else:
            self._set_icon(self.build_boots_label, "item", "", 40)
            self.build_boots_label.setToolTip("")
        self.build_note_lbl.setText(
            " · ".join(
                filter(None, [build.get("boots_reason", ""), build.get("note", "")])
            )
        )

    def _pintar_hechizos(self) -> None:
        """Muestra los hechizos normalizados del contexto local; retorna None."""
        hechizos = tuple(self._datos_importacion.get("hechizos") or ())
        for index, spell_lbl in enumerate(self.spell_icon_labels):
            nombre = str(hechizos[index]) if index < len(hechizos) else ""
            self._set_icon(spell_lbl, "spell", nombre, 44)
            spell_lbl.setToolTip(nombre)
        if len(hechizos) == 2:
            smite_note = (
                " (Smite obligatorio en Jungla)"
                if self._contexto_activo[1] == "jungle"
                else ""
            )
            self.spells_text_lbl.setText(f"{hechizos[0]} + {hechizos[1]}{smite_note}")
        else:
            self.spells_text_lbl.setText("Sin hechizos locales.")

        modo = "LCU" if self.lcu_draft_active else "Manual"
        if self._contexto_activo[0]:
            self.context_info_lbl.setText(
                f"Modo: {modo}\n"
                f"Campeón: {self._contexto_activo[0]}\n"
                f"Línea: {self.LINEAS_ETIQUETA.get(self._contexto_activo[1], self._contexto_activo[1])}\n"
                f"Rango: {dict(OPCIONES_RANGO).get(self._contexto_activo[2], self._contexto_activo[2])}"
            )
        else:
            self.context_info_lbl.setText("Sin contexto de campeón activo.")

    def _seleccionar_pagina_runas(self, indice: int) -> None:
        """Selecciona la página recibida, repinta su build y reinicia estados; retorna None."""
        paginas = self._datos_importacion.get("paginas", [])
        if indice - 1 >= len(paginas) or self._pagina_runas_activa == indice:
            return
        self._pagina_runas_activa = indice
        self._restablecer_estado_importacion()
        self._aplicar_seleccion_pagina()
        self._pintar_build_desde_pagina()

    def _establecer_texto_boton(self, boton: QPushButton, texto: str) -> None:
        """Cambia el texto del botón y su nombre accesible sin tocar su tamaño; retorna None."""
        boton.setText(texto)
        boton.setAccessibleName(texto.lstrip("↓✓⚠… ").strip() or texto)

    def _restablecer_estado_importacion(self) -> None:
        """Devuelve los botones y el estado inline a su valor normal; retorna None."""
        for clave, boton, texto in (
            ("build_runas", self.btn_import_build_runes, "↓  Importar build + runas"),
            ("hechizos", self.btn_import_spells, "↓  Importar hechizos"),
        ):
            tarea = self._tarea_importacion.pop(clave, None)
            if tarea is not None:
                tarea.cancel()
            self._estado_importacion.pop(clave, None)
            boton.setProperty("cargando", "false")
            aplicar_estado(boton, "normal")
            self._establecer_texto_boton(boton, texto)
            boton.setEnabled(bool(self._datos_importacion))
        if self._datos_importacion:
            self.import_status.establecer(
                f"Listo para importar · {self._etiqueta_contexto()}", "informacion"
            )

    def _lanzar_importacion(
        self,
        clave: str,
        boton: QPushButton,
        operacion: Any,
    ) -> None:
        """Ejecuta la importación fuera del hilo gráfico con estado en su botón; retorna None.

        El clic repetido mientras la tarea corre se ignora; el resultado se
        descarta si el contexto o la página cambian durante la operación.
        """
        if self._estado_importacion.get(clave) == "cargando":
            return
        self._estado_importacion[clave] = "cargando"
        boton.setProperty("cargando", "true")
        boton.setEnabled(False)
        self._establecer_texto_boton(boton, "… Importando...")
        contexto = (self._contexto_activo, self._pagina_runas_activa)

        def entregado(
            token: Any,
            resultado: Any,
            error: Any,
            _clave: str = clave,
            _boton: QPushButton = boton,
            _contexto: tuple = contexto,
        ) -> None:
            """Aplica el resultado en la GUI si el contexto sigue vigente; retorna None."""
            if not isValid(_boton):
                return
            if _contexto != (self._contexto_activo, self._pagina_runas_activa):
                return
            if error:
                self._finalizar_importacion(_clave, _boton, False, str(error))
                return
            exito, mensaje = (
                resultado if isinstance(resultado, tuple) else (bool(resultado), "")
            )
            self._finalizar_importacion(_clave, _boton, bool(exito), str(mensaje))

        self._tarea_importacion[clave] = run_async(
            operacion, on_finished=entregado, token=clave
        )

    def _finalizar_importacion(
        self, clave: str, boton: QPushButton, exito: bool, mensaje: str
    ) -> None:
        """Refleja el resultado en su botón y en el estado inline; retorna None."""
        self._estado_importacion[clave] = "exito" if exito else "error"
        self._tarea_importacion.pop(clave, None)
        boton.setProperty("cargando", "false")
        aplicar_estado(boton, "exito" if exito else "error")
        self._establecer_texto_boton(
            boton, "✓ Importado" if exito else "⚠ Error al importar"
        )
        boton.setEnabled(True)
        self.import_status.establecer(
            mensaje or ("Importación completada" if exito else "Error al importar"),
            "exito" if exito else "error",
        )
        if exito:
            logging.getLogger(__name__).debug(
                "[draft] importación %s completada", clave
            )
        else:
            logging.getLogger(__name__).warning(
                "[draft] importación %s fallida: %s", clave, mensaje
            )

    def _importar_build_y_runas(self) -> None:
        """Importa la página seleccionada y su build con feedback en el botón; retorna None."""
        if self._estado_importacion.get("build_runas") == "cargando":
            return
        campeon, _linea, _rango = self._resolver_contexto_importacion()
        rol = self._current_local_role()
        indice = self._pagina_runas_activa
        paginas = self._datos_importacion.get("paginas", [])
        pagina = paginas[indice - 1] if indice - 1 < len(paginas) else None
        build = self._datos_importacion.get("build")
        if not campeon or pagina is None or not build:
            return
        lcu = self.lcu_service

        def operacion() -> tuple[bool, str]:
            """Importa runas y build al cliente con los datos capturados; devuelve éxito y mensaje."""
            exito_runas, mensaje_runas = lcu.import_rune_page(
                name=f"{campeon} Página {indice}",
                primary_tree=str(pagina.get("primary_tree") or "Precision"),
                secondary_tree=str(pagina.get("secondary_tree") or "Resolve"),
                keystone_name=str(pagina.get("keystone") or ""),
                slots=list(pagina.get("slots") or []),
                secondary_slots=list(pagina.get("secondary_slots") or []),
                shards=list(pagina.get("shards") or []),
            )
            exito_build, mensaje_build = lcu.import_item_set(
                champion_id=int(build.get("champion_id") or 0),
                champion_name=campeon,
                role=rol,
                item_ids=[str(item["id"]) for item in build["items"]],
                boots_id=str(build["boots"]["id"]) if build.get("boots") else None,
                situational=build.get("situational", []),
            )
            return (
                bool(exito_runas and exito_build),
                f"{mensaje_runas} {mensaje_build}",
            )

        self._lanzar_importacion("build_runas", self.btn_import_build_runes, operacion)

    def _import_spells(self) -> None:
        """Importa los hechizos del contexto con feedback en el botón; retorna None."""
        if self._estado_importacion.get("hechizos") == "cargando":
            return
        hechizos = tuple(self._datos_importacion.get("hechizos") or ())
        if len(hechizos) != 2:
            return
        lcu = self.lcu_service

        def operacion() -> tuple[bool, str]:
            """Envía los dos hechizos capturados al cliente; devuelve éxito y mensaje."""
            return lcu.import_summoner_spells(str(hechizos[0]), str(hechizos[1]))

        self._lanzar_importacion("hechizos", self.btn_import_spells, operacion)
