from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.sistema_visual import PALETA
from app.ui.tema import aplicar_apariencia
from data_dragon import get_champion_icon_path, get_item_icon_path


def _local_champion_names() -> dict[str, str]:
    """Carga nombres de campeón desde los metadatos instalados localmente."""
    import json

    from _paths import DATA_DIR

    names: dict[str, str] = {}
    for path in (DATA_DIR / "champion_metadata").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records = payload.get("data", {}) if isinstance(payload, dict) else {}
        for champion in records.values() if isinstance(records, dict) else []:
            if isinstance(champion, dict) and champion.get("key") is not None:
                names[str(champion["key"])] = str(champion.get("name") or "")
    return names


class RelojActividad(QWidget):
    """Dibuja las 24 horas en un anillo con intensidad según las partidas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inicializa el reloj circular sin datos de actividad."""
        super().__init__(parent)
        self.conteos: dict[int, int] = {}
        self.hora_pico: int | None = None
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, conteos: dict[int, int], hora_pico: int | None) -> None:
        """Actualiza el volumen por hora y repinta el reloj."""
        self.conteos = conteos
        self.hora_pico = hora_pico
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Pinta segmentos horarios y la hora de mayor actividad."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) * 0.36
        maximum = max(self.conteos.values(), default=0)
        for hour in range(24):
            angle = math.radians(hour * 15 - 90)
            intensity = self.conteos.get(hour, 0) / maximum if maximum else 0
            length = 8 + 23 * intensity
            color = PALETA["oro"] if intensity else PALETA["borde_sutil"]
            painter.setPen(QPen(QColor(color), 3.5 if intensity else 2.0))
            painter.drawLine(
                int(center_x + math.cos(angle) * radius),
                int(center_y + math.sin(angle) * radius),
                int(center_x + math.cos(angle) * (radius + length)),
                int(center_y + math.sin(angle) * (radius + length)),
            )
        painter.setPen(QColor(PALETA["oro_suave"]))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.hora_pico:02d}:00\nTU HORA"
            if self.hora_pico is not None
            else "24 h\nACTIVIDAD",
        )


class HomeDashboard(QWidget):
    """Presenta el resumen personal y las partidas recordadas localmente."""

    sync_requested = Signal()
    clear_requested = Signal()
    saved_match_requested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        item_catalog: dict[str, Any] | None = None,
        version: str = "",
    ) -> None:
        """Crea el dashboard adaptable con estado vacío y controles de historial."""
        super().__init__(parent)
        self._matches: list[dict[str, Any]] = []
        self._visible_count = 25
        catalog = item_catalog or {}
        self.item_catalog = catalog.get("items", catalog)
        self.version = version
        self._collection: dict[str, Any] = {}
        self._analytics: dict[str, Any] = {}
        self._matchups_two_columns: bool | None = None
        self.matchups_grid_host: QWidget | None = None
        self.matchups_grid: QGridLayout | None = None
        self.matchups_groups: tuple[QWidget, QWidget] | None = None
        self._collection_columns: int | None = None
        self._enemy_team_rows: list[tuple[list[QLabel], QLabel, list[str]]] = []
        self._syncing = False
        self._data_signature: tuple[Any, ...] | None = None
        self._build()

    def minimumSizeHint(self) -> QSize:
        """Permite que el scroll y el reflujo reduzcan el ancho sin desbordes."""
        return QSize(0, self.root.sizeHint().height())

    def _build(self) -> None:
        """Construye las tarjetas del dashboard dentro de una cuadrícula adaptable."""
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(18)
        self.root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.profile = self._card()
        self.profile.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum
        )
        profile_layout = QHBoxLayout(self.profile)
        self.profile_layout = profile_layout
        profile_layout.setContentsMargins(20, 18, 20, 18)
        profile_layout.setSpacing(18)
        self.profile_icon = QLabel("◎")
        self.profile_icon.setFixedSize(62, 62)
        self.profile_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        profile_layout.addWidget(self.profile_icon)
        info = QVBoxLayout()
        self.home_title = QLabel("Tu panel de League")
        self.home_title.setObjectName("heroTitle")
        info.addWidget(self.home_title)
        self.profile_line = QLabel("Conecta League para importar tu cuenta local")
        self.profile_line.setObjectName("sectionTitle")
        info.addWidget(self.profile_line)
        self.home_text = QLabel("Historial privado guardado en este dispositivo.")
        self.home_text.setWordWrap(True)
        info.addWidget(self.home_text)
        self.source_note = QLabel(
            "Datos del cliente local y del historial de SOLRALOL. No requiere la API pública de Riot."
        )
        self.source_note.setWordWrap(True)
        self.source_note.setObjectName("historyStatus")
        info.addWidget(self.source_note)
        profile_layout.addLayout(info, 1)
        self.connection = QLabel("Cliente sin sincronizar")
        self.connection.setObjectName("historyStatus")
        self.sync_button = QPushButton("Sincronizar LCU")
        self.sync_button.setObjectName("primaryButton")
        self.sync_button.clicked.connect(self.sync_requested)
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.addWidget(self.connection)
        actions_layout.addWidget(self.sync_button)
        profile_layout.addWidget(actions)
        self.root.addWidget(self.profile)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.root.addLayout(self.grid, 1)

        self.history_card = self._card()
        history_layout = QVBoxLayout(self.history_card)
        history_layout.setContentsMargins(20, 18, 20, 18)
        history_layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Historial de partidas recordadas")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Todas", "all")
        self.filter_combo.addItem("SoloQ", "solo")
        self.filter_combo.addItem("Flex", "flex")
        self.filter_combo.addItem("ARAM", "aram")
        self.filter_combo.addItem("Normal", "normal")
        self.filter_combo.currentIndexChanged.connect(self.render_matches)
        self.filter_combo.setMaximumWidth(110)
        header.addWidget(self.filter_combo)
        self.clear_button = QPushButton("Borrar historial local")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self.clear_requested)
        self.clear_button.setMaximumWidth(170)
        header.addWidget(self.clear_button)
        history_layout.addLayout(header)
        self.history_status = QLabel("Todavía no hay partidas recordadas.")
        history_layout.addWidget(self.history_status)
        self.match_rows = QVBoxLayout()
        self.match_rows.setSpacing(6)
        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("homeHistoryScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history_content = QWidget()
        self.history_content_layout = QVBoxLayout(self.history_content)
        self.history_content_layout.setContentsMargins(2, 2, 8, 2)
        self.history_content_layout.setSpacing(6)
        self.match_rows = QVBoxLayout()
        self.match_rows.setSpacing(6)
        self.history_content_layout.addLayout(self.match_rows)
        self.more_button = QPushButton("Cargar más")
        self.more_button.clicked.connect(self._load_more)
        self.history_content_layout.addWidget(
            self.more_button, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.history_scroll.setWidget(self.history_content)
        history_layout.addWidget(self.history_scroll, 1)

        self.activity_card = self._section(
            "Tu actividad", "Sin datos de actividad todavía."
        )
        self.activity_text = self.activity_card.findChild(QLabel, "sectionBody")
        self.activity_clock = RelojActividad()
        self.activity_card.layout().addWidget(self.activity_clock)
        self.heatmap_labels: list[QLabel] = []
        heatmap = QHBoxLayout()
        heatmap.setSpacing(5)
        for day in ("L", "M", "X", "J", "V", "S", "D"):
            label = QLabel(day)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(24)
            label.setObjectName("homeHeatmapCell")
            label.setToolTip(f"Actividad del día {day}")
            self.heatmap_labels.append(label)
            heatmap.addWidget(label)
        self.activity_card.layout().addLayout(heatmap)
        self.playstyle_card = self._section(
            "Tu estilo de juego", "Se calculará con el historial local."
        )
        self.playstyle_text = self.playstyle_card.findChild(QLabel, "sectionBody")
        self.teammates_card = self._section(
            "Compañeros frecuentes",
            "Los identificadores de jugador no siempre están disponibles en LCU.",
        )
        self.teammates_text = self.teammates_card.findChild(QLabel, "sectionBody")
        self.insights_card = self._section(
            "Enfrentamientos",
            "Los resultados se mostrarán al contar con rival de línea fiable.",
        )
        self.insights_text = self.insights_card.findChild(QLabel, "sectionBody")
        self.collection_card = self._section(
            "Colección y progreso", "Consultando datos locales del cliente."
        )
        self.collection_text = self.collection_card.findChild(QLabel, "sectionBody")
        self.tarjetas = [
            self.history_card,
            self.activity_card,
            self.playstyle_card,
            self.teammates_card,
            self.insights_card,
            self.collection_card,
        ]
        for indice, tarjeta in enumerate(self.tarjetas):
            self.grid.addWidget(tarjeta, indice, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _card(self) -> QFrame:
        """Crea una tarjeta con el estilo aprobado de la aplicación."""
        card = QFrame()
        card.setObjectName("sectionCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        aplicar_apariencia(card, "tarjeta")
        return card

    def _section(self, title: str, body: str) -> QFrame:
        """Crea una tarjeta secundaria con título y estado textual."""
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        text = QLabel(body)
        text.setObjectName("sectionBody")
        text.setWordWrap(True)
        layout.addWidget(text)
        return card

    def resizeEvent(self, event: Any) -> None:
        """Recoloca tarjetas en tres, dos o una columna según el ancho actual."""
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def _reflow(self, width: int) -> None:
        """Distribuye tarjetas y ajusta la altura al ancho y datos actuales."""
        self.profile_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if width < 850
            else QBoxLayout.Direction.LeftToRight
        )
        for tarjeta in self.tarjetas:
            self.grid.removeWidget(tarjeta)
        for columna in range(3):
            self.grid.setColumnStretch(columna, 0)
        for fila in range(3):
            self.grid.setRowMinimumHeight(fila, 0)
            self.grid.setRowStretch(fila, 0)
        if width >= 850:
            self.grid.setRowStretch(0, 1)
            if len(self._matches) >= 5:
                self.grid.setRowStretch(1, 1)
        if width < 850:
            for indice, tarjeta in enumerate(self.tarjetas):
                self.grid.addWidget(tarjeta, indice, 0)
        elif width < 1250:
            self.grid.setColumnStretch(0, 8)
            self.grid.setColumnStretch(1, 7)
            self.grid.setColumnStretch(2, 5)
            if len(self._matches) >= 5:
                self.grid.addWidget(self.history_card, 0, 0, 2, 2)
                self.grid.addWidget(self.activity_card, 0, 2)
                self.grid.addWidget(self.playstyle_card, 1, 2)
                self.grid.addWidget(self.teammates_card, 2, 0)
                self.grid.addWidget(self.insights_card, 2, 1)
                self.grid.addWidget(self.collection_card, 2, 2)
            else:
                self.grid.addWidget(self.history_card, 0, 0, 1, 2)
                self.grid.addWidget(self.activity_card, 0, 2)
                self.grid.addWidget(self.playstyle_card, 1, 2)
                self.grid.addWidget(self.teammates_card, 1, 0)
                self.grid.addWidget(self.insights_card, 1, 1)
                self.grid.addWidget(self.collection_card, 2, 0, 1, 3)
        else:
            self.grid.setColumnStretch(0, 8)
            self.grid.setColumnStretch(1, 7)
            self.grid.setColumnStretch(2, 5)
            if len(self._matches) >= 5:
                self.grid.addWidget(self.history_card, 0, 0, 2, 2)
                self.grid.addWidget(self.activity_card, 0, 2)
                self.grid.addWidget(self.playstyle_card, 1, 2)
                self.grid.addWidget(self.teammates_card, 2, 0)
                self.grid.addWidget(self.insights_card, 2, 1)
                self.grid.addWidget(self.collection_card, 2, 2)
            else:
                self.grid.addWidget(self.history_card, 0, 0)
                self.grid.addWidget(self.activity_card, 0, 1)
                self.grid.addWidget(self.playstyle_card, 0, 2)
                self.grid.addWidget(self.teammates_card, 1, 0)
                self.grid.addWidget(self.insights_card, 1, 1)
                self.grid.addWidget(self.collection_card, 1, 2)
        self.grid.activate()
        for tarjeta in (self.history_card, self.activity_card, self.playstyle_card):
            tarjeta.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
                if width >= 850
                else QSizePolicy.Policy.Preferred,
            )
        for tarjeta in (self.teammates_card, self.insights_card, self.collection_card):
            tarjeta.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        bottom_cards = (self.teammates_card, self.insights_card, self.collection_card)
        altura_comun = min(
            220, max(tarjeta.sizeHint().height() for tarjeta in bottom_cards)
        )
        for tarjeta in bottom_cards:
            tarjeta.setMinimumHeight(altura_comun if width >= 850 else 0)
        if self.matchups_grid is not None:
            self._arrange_matchup_groups()
        self._update_enemy_team_visibility()
        collection_columns = 3 if self.collection_card.width() >= 420 else 2
        if (
            self._collection_columns is not None
            and collection_columns != self._collection_columns
        ):
            self._render_collection()
        self.updateGeometry()

    def showEvent(self, event: Any) -> None:
        """Ajusta la cuadrícula al tamaño final al mostrar la página."""
        super().showEvent(event)
        self._reflow(self.width())

    def set_dashboard_data(
        self,
        profile: dict[str, Any] | None,
        history: dict[str, Any],
        analytics: dict[str, Any],
        status: str,
        collection: dict[str, Any] | None = None,
        syncing: bool = False,
    ) -> None:
        """Actualiza perfil, indicadores y filas visibles con datos calculados."""
        matches = history.get("matches", [])
        nuevos_matches = [match for match in matches if isinstance(match, dict)]
        firma = (
            history.get("last_sync"),
            len(nuevos_matches),
            tuple(
                str(match.get("stable_match_id") or "") for match in nuevos_matches[:10]
            ),
            repr(analytics),
            repr(collection or {}),
        )
        datos_cambiaron = firma != self._data_signature
        if datos_cambiaron:
            self._matches = nuevos_matches
            self._analytics = analytics
            self._visible_count = 25
            self._data_signature = firma
        self.connection.setText(status)
        self._collection = collection or {}
        self._syncing = syncing
        self.sync_button.setEnabled(not syncing)
        self.sync_button.setText("Sincronizando…" if syncing else "Sincronizar LCU")
        if profile:
            name = str(profile.get("gameName") or "Invocador")
            tag = str(profile.get("tagLine") or "")
            ranked = profile.get("ranked") or []
            solo = next(
                (
                    queue
                    for queue in ranked
                    if "SOLO" in str(queue.get("queue", "")).upper()
                ),
                None,
            )
            rank_text = (
                f" · {solo['tier']} {solo.get('division', '')} · {solo.get('league_points') if solo.get('league_points') is not None else '—'} LP"
                if solo
                else " · SoloQ sin datos locales"
            )
            self.profile_line.setText(
                f"{name}{'#' + tag if tag else ''} · Nivel {profile.get('summonerLevel') or '—'} · {profile.get('region') or 'Región LCU'}{rank_text}"
            )
            self.profile_icon.setText(f"◉ {profile.get('profileIconId') or ''}")
        self.home_title.setText("Tu panel de League")
        winrate = analytics.get("winrate")
        self.home_text.setText(
            f"{analytics.get('total', 0)} partidas recordadas · {winrate}% de victorias"
            + (
                f" · Más jugado: {analytics['top_champion']}"
                if analytics.get("top_champion")
                else ""
            )
            + f" · Racha actual: {analytics.get('current_win_streak', 0)}"
            if winrate is not None
            else f"{analytics.get('total', 0)} partidas recordadas · Sin muestra suficiente para winrate · Racha máxima: {analytics.get('longest_win_streak', 0)}"
        )
        self.history_status.setText(
            f"{len(self._matches)} partidas almacenadas en este dispositivo."
        )
        peak = analytics.get("peak_hour")
        self.activity_clock.set_data(dict(analytics.get("hours", [])), peak)
        dias = dict(analytics.get("weekdays", []))
        max_dia = max(dias.values(), default=0)
        for indice, label in enumerate(self.heatmap_labels):
            cantidad = dias.get(indice, 0)
            nivel = round(20 + 70 * cantidad / max_dia) if max_dia else 20
            label.setText(f"{label.toolTip()[-1]}\n{cantidad}")
            label.setProperty("intensity", min(4, max(0, nivel // 20)))
            label.style().unpolish(label)
            label.style().polish(label)
        best_hour = analytics.get("best_hour")
        worst_hour = analytics.get("worst_hour")
        hour_insights = []
        if best_hour:
            hour_insights.append(
                f"Mejor hora: {best_hour[0]:02d}:00 ({best_hour[1]}% en {best_hour[2]} partidas)"
            )
        if worst_hour:
            hour_insights.append(
                f"Peor hora: {worst_hour[0]:02d}:00 ({worst_hour[1]}% en {worst_hour[2]} partidas)"
            )
        self.activity_text.setText(
            f"Hora de mayor actividad: {peak:02d}:00 · {len(self._matches)} partidas"
            + (
                "\n" + "\n".join(hour_insights)
                if hour_insights
                else "\nMejor/peor winrate requiere cinco partidas por hora."
            )
            if peak is not None
            else "Faltan fechas de partida válidas para calcular actividad."
        )
        if datos_cambiaron:
            self._render_playstyle(analytics)
            self._render_teammates(analytics)
            self._render_matchups(analytics)
            self._render_collection()
            self.render_matches()
            self._reflow(self.width())

    def _clear_section(self, card: QFrame, keep: int = 1) -> QVBoxLayout:
        """Vacía widgets dinámicos de una tarjeta y conserva su cabecera."""
        layout = card.layout()
        while layout.count() > keep:
            item = layout.takeAt(keep)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_nested_layout(item.layout())
                item.layout().deleteLater()
        return layout

    def _clear_nested_layout(self, layout: QLayout) -> None:
        """Desconecta y elimina recursivamente widgets de un layout dinámico."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_nested_layout(item.layout())
                item.layout().deleteLater()

    def _render_playstyle(self, analytics: dict[str, Any]) -> None:
        """Dibuja roles, clases, campeones y modos con barras e iconos."""
        layout = self._clear_section(self.playstyle_card)
        if self.playstyle_text is not None:
            self.playstyle_text.deleteLater()
        self.playstyle_text = None
        total = max(1, int(analytics.get("played", 0)))
        lanes = analytics.get("lanes") or []
        labels = {
            "top": "Superior",
            "jungle": "Jungla",
            "mid": "Medio",
            "bot": "Inferior",
            "support": "Soporte",
            "unknown": "Sin rol",
        }
        primary = lanes[0] if lanes else None
        hero = QLabel(
            labels.get(primary[0], str(primary[0]).title())
            if primary
            else "Rol sin datos"
        )
        hero.setObjectName("homePlaystylePrimary")
        layout.addWidget(hero)
        if primary:
            layout.addWidget(
                QLabel(f"{primary[1]} partidas · {round(primary[1] * 100 / total)}%")
            )
        for role, count in lanes[:5]:
            self._add_bar(layout, labels.get(role, str(role).title()), count, total)
        classes = analytics.get("classes") or []
        if classes:
            layout.addWidget(self._subheading("Clases de campeones"))
            class_total = max(1, sum(count for _, count in classes))
            for name, count in classes[:4]:
                self._add_bar(layout, str(name), count, class_total)
        champions = analytics.get("champions") or []
        if champions:
            layout.addWidget(self._subheading("Campeones más jugados"))
            row = QHBoxLayout()
            for name, count in champions[:3]:
                row.addWidget(self._champion_entry(str(name), int(count), 36))
            row.addStretch(1)
            layout.addLayout(row)
        modes = analytics.get("modes") or []
        if modes:
            layout.addWidget(self._subheading("Modos"))
            row = QHBoxLayout()
            for name, count in modes[:3]:
                chip = QLabel(f"{name} · {count}")
                chip.setObjectName("homeModeChip")
                row.addWidget(chip)
            row.addStretch(1)
            layout.addLayout(row)

    def _add_bar(self, layout: QVBoxLayout, label: str, count: int, total: int) -> None:
        """Añade una fila con porcentaje y barra de proporción accesible."""
        percent = round(100 * count / max(1, total))
        row = QHBoxLayout()
        name = QLabel(label)
        name.setMinimumWidth(72)
        name.setObjectName("homeBarLabel")
        bar = QProgressBar()
        bar.setObjectName("homeAnalyticsBar")
        bar.setRange(0, 100)
        bar.setValue(percent)
        bar.setTextVisible(False)
        bar.setAccessibleName(f"{label}: {percent}%")
        value = QLabel(f"{percent}%")
        value.setMinimumWidth(34)
        row.addWidget(name)
        row.addWidget(bar, 1)
        row.addWidget(value)
        layout.addLayout(row)

    def _subheading(self, text: str) -> QLabel:
        """Crea una etiqueta secundaria coherente para grupos analíticos."""
        label = QLabel(text)
        label.setObjectName("homeSubheading")
        return label

    def _champion_entry(self, name: str, count: int, size: int) -> QWidget:
        """Crea una miniatura con retrato local y cantidad de partidas."""
        entry = QWidget()
        row = QHBoxLayout(entry)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        icon = QLabel()
        icon.setObjectName("savedGameChampIcon")
        icon.setFixedSize(size + 8, size + 8)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setContentsMargins(3, 3, 3, 3)
        self._set_champion_icon(icon, name, size)
        icon.setToolTip(f"{name} · {count:,} puntos" if count else name)
        row.addWidget(icon)
        text = QLabel(f"{name}\n{count}" if count else name)
        text.setObjectName("homeCompactText")
        row.addWidget(text)
        return entry

    def _render_teammates(self, analytics: dict[str, Any]) -> None:
        """Presenta los tres aliados recurrentes con muestra y winrate."""
        layout = self._clear_section(self.teammates_card)
        if self.teammates_text is not None:
            self.teammates_text.deleteLater()
        self.teammates_text = None
        teammates = analytics.get("teammates") or []
        if not teammates:
            layout.addWidget(
                QLabel(
                    f"Sin identidades de aliados suficientes · {analytics.get('team_data_matches', 0)} partidas con datos de equipo"
                )
            )
            return
        for index, entry in enumerate(teammates[:3]):
            name = str(entry.get("name") or "Jugador")
            tag = str(entry.get("tag_line") or "")
            row_widget = QFrame()
            row_widget.setObjectName("homeTeammateRow")
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(7, 6, 7, 6)
            row.setSpacing(9)
            avatar = QFrame()
            avatar.setObjectName("homeTeammateAvatar")
            avatar.setFixedSize(44, 44)
            avatar_layout = QVBoxLayout(avatar)
            avatar_layout.setContentsMargins(5, 5, 5, 5)
            avatar_layout.setSpacing(0)
            avatar_image = QLabel("◉")
            avatar_image.setObjectName("homeTeammateAvatarImage")
            avatar_image.setFixedSize(32, 32)
            avatar_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar_layout.addWidget(avatar_image)
            self._set_teammate_icon(avatar_image, entry)
            row.addWidget(avatar)
            identity = QVBoxLayout()
            identity.setSpacing(2)
            title_line = QHBoxLayout()
            title_line.setSpacing(6)
            identity_label = QLabel(f"{name}{'#' + tag if tag else ''}")
            identity_label.setObjectName("homeTeammateName")
            title_line.addWidget(identity_label, 1)
            delta = entry.get("winrate_delta")
            matches_label = QLabel(f"{entry.get('games', 0)} partidas juntos")
            matches_label.setObjectName("homeTeammateMeta")
            identity.addLayout(title_line)
            identity.addWidget(matches_label)
            row.addLayout(identity, 1)
            metrics = QVBoxLayout()
            metrics.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            winrate = QLabel(f"{entry.get('winrate', 0)}% WR")
            winrate.setObjectName("homeTeammateWinrate")
            metrics.addWidget(winrate, alignment=Qt.AlignmentFlag.AlignRight)
            delta_label = QLabel(
                f"{delta:+} pp contigo" if delta is not None else "Sin comparación"
            )
            delta_label.setObjectName("homeTeammateDelta")
            delta_label.setProperty(
                "sentiment",
                "positive"
                if delta and delta > 0
                else "negative"
                if delta and delta < 0
                else "neutral",
            )
            delta_label.setToolTip(
                "Comparación entre tu winrate con este jugador y tu winrate sin él."
            )
            delta_label.style().unpolish(delta_label)
            delta_label.style().polish(delta_label)
            metrics.addWidget(delta_label, alignment=Qt.AlignmentFlag.AlignRight)
            row.addLayout(metrics)
            if (
                index == 0
                and int(entry.get("games", 0)) >= 8
                and int(entry.get("games", 0))
                >= 2
                * max(1, int(teammates[1].get("games", 0)) if len(teammates) > 1 else 1)
            ):
                duo = QLabel("DÚO HABITUAL")
                duo.setObjectName("homeDuoBadge")
                title_line.addWidget(duo)
            layout.addWidget(row_widget)
        coverage = QLabel(
            f"Datos de compañeros disponibles en {analytics.get('team_data_matches', 0)}/{analytics.get('total', 0)} partidas"
        )
        coverage.setObjectName("homeCoverage")
        layout.addWidget(coverage)

    def _set_teammate_icon(self, label: QLabel, entry: dict[str, Any]) -> None:
        """Carga icono de perfil local o recurre al campeón más jugado juntos."""
        icon_id = entry.get("profile_icon_id")
        if icon_id is not None:
            path = (
                Path.home()
                / ".solralol"
                / "ddragon"
                / "profileicons"
                / f"{icon_id}.png"
            )
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        32,
                        32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        champion = str(entry.get("champion_name") or "")
        if champion:
            self._set_champion_icon(label, champion, 30)

    def _render_matchups(self, analytics: dict[str, Any]) -> None:
        """Muestra rivales favorables y difíciles con sus retratos locales."""
        layout = self._clear_section(self.insights_card)
        if self.insights_text is not None:
            self.insights_text.deleteLater()
        self.insights_text = None
        self.matchups_grid_host = QWidget()
        self.matchups_grid_host.setObjectName("homeMatchupsHost")
        self.matchups_grid = QGridLayout(self.matchups_grid_host)
        self.matchups_grid.setContentsMargins(0, 0, 0, 0)
        self.matchups_grid.setHorizontalSpacing(12)
        self.matchups_grid.setVerticalSpacing(10)
        groups: list[QWidget] = []
        for title, entries, kind in (
            ("MÁS TE CUESTAN", analytics.get("hardest_matchups") or [], "hard"),
            ("MÁS GANAS", analytics.get("matchups") or [], "favorable"),
        ):
            group_widget = QWidget()
            group_widget.setObjectName("homeMatchupGroup")
            group = QVBoxLayout(group_widget)
            group.setContentsMargins(0, 0, 0, 0)
            group.setSpacing(7)
            group.addWidget(self._subheading(title))
            for entry in entries[:3]:
                row_widget = QFrame()
                row_widget.setObjectName("homeMatchupRow")
                line = QHBoxLayout(row_widget)
                line.setContentsMargins(5, 4, 5, 4)
                line.setSpacing(7)
                icon = QLabel()
                icon.setObjectName("savedGameEnemyIcon")
                row_widget.setMinimumHeight(52)
                icon.setFixedSize(38, 38)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setContentsMargins(4, 4, 4, 4)
                champion = str(entry.get("champion") or "Campeón")
                self._set_champion_icon(icon, champion, 28)
                icon.setToolTip(champion)
                line.addWidget(icon)
                details = QVBoxLayout()
                details.setContentsMargins(0, 0, 0, 0)
                details.setSpacing(2)
                name = QLabel(champion)
                name.setObjectName("homeMatchupName")
                name.setMinimumWidth(0)
                name.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                name.setWordWrap(True)
                name.setToolTip(champion)
                sample = QLabel(f"{entry.get('games', 0)} partidas")
                sample.setObjectName("homeCoverage")
                details.addWidget(name)
                details.addWidget(sample)
                line.addLayout(details, 1)
                winrate = QLabel(f"{entry.get('winrate', 0)}% WR")
                winrate.setObjectName("homeMatchupWinrate")
                winrate.setProperty("result", kind)
                winrate.setFixedWidth(66)
                line.addWidget(winrate)
                group.addWidget(row_widget)
            if not entries:
                group.addWidget(QLabel("Sin muestra fiable"))
            groups.append(group_widget)
        self.matchups_groups = (groups[0], groups[1])
        layout.addWidget(self.matchups_grid_host)
        self._arrange_matchup_groups()
        layout.addWidget(self._coverage_label(analytics))

    @staticmethod
    def _coverage_label(analytics: dict[str, Any]) -> QLabel:
        """Crea una nota secundaria con cobertura exacta y estados no exactos."""
        total = int(analytics.get("total", 0))
        exact = int(analytics.get("opponent_exact", 0))
        probable = int(analytics.get("opponent_probable", 0))
        unresolved = int(analytics.get("opponent_ambiguous", 0)) + int(
            analytics.get("opponent_unavailable", 0)
        )
        label = QLabel(
            f"{exact}/{total} exactas · {probable} probables · {unresolved} sin rival directo"
        )
        label.setObjectName("homeCoverage")
        return label

    def _arrange_matchup_groups(self) -> None:
        """Reubica los mismos grupos según el ancho real de la tarjeta."""
        if self.matchups_grid is None or self.matchups_grid_host is None:
            return
        if self.matchups_groups is None:
            return
        width = self.matchups_grid_host.width()
        if width <= 0:
            width = self.insights_card.width() - 36
        two_columns = width >= 520
        if two_columns == self._matchups_two_columns:
            return
        self._matchups_two_columns = two_columns
        for group in self.matchups_groups:
            self.matchups_grid.removeWidget(group)
        self.matchups_grid.setColumnStretch(0, 1)
        self.matchups_grid.setColumnStretch(1, 1 if two_columns else 0)
        if two_columns:
            self.matchups_grid.addWidget(self.matchups_groups[0], 0, 0)
            self.matchups_grid.addWidget(self.matchups_groups[1], 0, 1)
        else:
            self.matchups_grid.addWidget(self.matchups_groups[0], 0, 0)
            self.matchups_grid.addWidget(self.matchups_groups[1], 1, 0)

    def _render_collection(self) -> None:
        """Muestra las categorías de colección que respondieron desde la LCU."""
        layout = self._clear_section(self.collection_card)
        if self.collection_text is not None:
            self.collection_text.deleteLater()
        self.collection_text = None
        collection = self._collection
        names = _local_champion_names()
        masteries = collection.get("masteries")
        if isinstance(masteries, list) and masteries:
            layout.addWidget(self._subheading("MAESTRÍAS DESTACADAS"))
            mastery_grid = QGridLayout()
            mastery_grid.setContentsMargins(0, 0, 0, 0)
            mastery_grid.setHorizontalSpacing(6)
            mastery_grid.setVerticalSpacing(6)
            columns = 3 if self.collection_card.width() >= 420 else 2
            self._collection_columns = columns
            for index, entry in enumerate(masteries[:3]):
                name = names.get(
                    str(entry.get("champion_id")), f"Campeón {entry.get('champion_id')}"
                )
                points = int(entry.get("points", 0))
                mastery = QFrame()
                mastery.setObjectName("homeMasteryCard")
                mastery_row = QHBoxLayout(mastery)
                mastery_row.setContentsMargins(6, 5, 6, 5)
                mastery_row.setSpacing(6)
                icon_frame = QFrame()
                icon_frame.setObjectName("homeMasteryIconFrame")
                icon_frame.setFixedSize(38, 38)
                icon_layout = QVBoxLayout(icon_frame)
                icon_layout.setContentsMargins(4, 4, 4, 4)
                icon = QLabel()
                icon.setFixedSize(30, 30)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._set_champion_icon(icon, name, 28)
                icon_layout.addWidget(icon)
                mastery_row.addWidget(icon_frame)
                mastery_details = QVBoxLayout()
                mastery_details.setContentsMargins(0, 0, 0, 0)
                mastery_details.setSpacing(1)
                champion_label = QLabel(name)
                champion_label.setObjectName("homeMasteryName")
                champion_label.setWordWrap(True)
                mastery_points = QLabel(
                    f"{points / 1000:.0f}k" if points >= 1000 else str(points)
                )
                mastery_points.setObjectName("homeMasteryPoints")
                mastery_points.setToolTip(f"{points:,} puntos de maestría")
                mastery_details.addWidget(champion_label)
                mastery_details.addWidget(mastery_points)
                mastery_row.addLayout(mastery_details, 1)
                mastery_grid.addWidget(
                    mastery,
                    index // columns,
                    index % columns,
                )
            layout.addLayout(mastery_grid)
        elif masteries is None:
            layout.addWidget(QLabel("Maestrías: endpoint local no disponible"))
        if masteries is not None:
            layout.addWidget(self._collection_separator())
        champions = collection.get("champions")
        if isinstance(champions, dict):
            owned = int(champions.get("owned_count", 0))
            total = int(champions.get("total_count") or 0)
            percent = 100 * owned / total if total else 0
            layout.addWidget(self._subheading("CAMPEONES"))
            metric = QLabel(f"{owned} / {total}  ·  {percent:.1f}%")
            metric.setObjectName("homeCollectionMetric")
            layout.addWidget(metric)
            progress = QProgressBar()
            progress.setObjectName("homeCollectionProgress")
            progress.setTextVisible(False)
            progress.setRange(0, max(1, total))
            progress.setValue(min(owned, max(1, total)))
            progress.setFixedHeight(9)
            layout.addWidget(progress)
        elif champions is None:
            layout.addWidget(QLabel("Campeones: endpoint local no disponible"))
        skins = collection.get("skins")
        if isinstance(skins, dict):
            layout.addWidget(self._collection_separator())
            skin_row = QHBoxLayout()
            skin_value = QLabel(f"{int(skins.get('owned_count', 0)):,}")
            skin_value.setObjectName("homeCollectionMetric")
            skin_label = QLabel("SKINS EN PROPIEDAD")
            skin_label.setObjectName("homeCollectionLabel")
            skin_row.addWidget(skin_value)
            skin_row.addWidget(skin_label, 1)
            layout.addLayout(skin_row)
        elif skins is None:
            layout.addWidget(QLabel("Skins: endpoint local no disponible"))
        challenges = collection.get("challenges")
        if isinstance(challenges, dict):
            layout.addWidget(self._collection_separator())
            layout.addWidget(self._subheading("DESAFÍOS"))
            challenge_row = QHBoxLayout()
            tier = str(challenges.get("tier") or "SIN NIVEL")
            tier_badge = QLabel(tier)
            tier_badge.setObjectName("homeChallengeTier")
            challenge_row.addWidget(tier_badge)
            points = challenges.get("points")
            points_label = QLabel(
                f"{int(points):,} pts" if points is not None else "Puntos —"
            )
            points_label.setObjectName("homeCollectionMetric")
            challenge_row.addWidget(points_label, 1)
            layout.addLayout(challenge_row)
            count = challenges.get("count")
            if count is not None:
                count_label = QLabel(f"{count} desafíos destacados")
                count_label.setObjectName("homeCoverage")
                layout.addWidget(count_label)
        elif challenges is None:
            layout.addWidget(QLabel("Desafíos: endpoint local no disponible"))
        titles = collection.get("titles")
        if isinstance(titles, dict) and titles.get("selected"):
            layout.addWidget(self._collection_separator())
            layout.addWidget(self._subheading("TÍTULO ACTIVO"))
            title = QLabel(str(titles["selected"]))
            title.setObjectName("homeActiveTitle")
            layout.addWidget(title)
        elif titles is None:
            layout.addWidget(QLabel("Título: endpoint local no disponible"))
        elif not collection:
            layout.addWidget(QLabel("Sin conexión; se conserva el historial local."))

    @staticmethod
    def _collection_separator() -> QFrame:
        """Crea un separador sutil entre categorías de colección."""
        separator = QFrame()
        separator.setObjectName("homeCollectionSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        return separator

    def _set_champion_icon(self, label: QLabel, champion: str, size: int) -> None:
        """Carga un retrato ya almacenado localmente sin iniciar descargas."""
        if not champion:
            return
        try:
            path = get_champion_icon_path(champion, self.version, download=False)
            pixmap = QPixmap(str(path)) if path else QPixmap()
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        except (OSError, TypeError, ValueError):
            return

    def _set_item_icon(self, label: QLabel, item_id: Any, size: int) -> None:
        """Carga un icono de objeto de la caché local y añade su nombre alternativo."""
        item = self.item_catalog.get(str(item_id), {})
        name = str(item.get("name_es") or item.get("name") or item_id)
        label.setToolTip(name)
        try:
            path = get_item_icon_path(
                item_id, self.item_catalog, self.version, download=False
            )
            pixmap = QPixmap(str(path)) if path else QPixmap()
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                label.setText(name[:7])
        except (OSError, TypeError, ValueError):
            label.setText(name[:7])

    def _add_opponent_presentation(
        self, layout: QHBoxLayout, match: dict[str, Any]
    ) -> None:
        """Añade rival directo o equipo rival sin asignaciones ambiguas."""
        resolution = match.get("opponent_resolution") or {}
        state = str(match.get("opponent_state") or resolution.get("state") or "")
        confidence = float(
            resolution.get("confidence") or match.get("opponent_confidence") or 0.0
        )
        champion = str(
            match.get("opponent_champion_name") or resolution.get("champion_name") or ""
        )
        if not state:
            has_stored_opponent = bool(
                match.get("opponent") or match.get("opponent_champion_id")
            )
            state = (
                "exact"
                if champion and (confidence >= 0.75 or has_stored_opponent)
                else "unavailable"
            )
        enemy_team = match.get("enemy_team")
        if not isinstance(enemy_team, list):
            enemy_team = []
        if state in {"exact", "probable"} and champion:
            versus = QLabel("VS probable" if state == "probable" else "VS")
            versus.setObjectName("savedGameMatchup")
            if state == "probable":
                versus.setToolTip(
                    "Rival probable según posición, rol y datos disponibles."
                )
                versus.setProperty("state", "probable")
            layout.addWidget(versus)
            icon = QLabel()
            icon.setObjectName("savedGameEnemyIcon")
            icon.setFixedSize(42, 42)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setContentsMargins(3, 3, 3, 3)
            self._set_champion_icon(icon, champion, 34)
            icon.setToolTip(champion)
            layout.addWidget(icon)
            name = QLabel(champion)
            name.setObjectName("homeOpponentName")
            name.setToolTip(versus.toolTip() or champion)
            layout.addWidget(name)
            return
        if state == "ambiguous" and enemy_team:
            versus = QLabel("VS equipo")
            versus.setObjectName("savedGameMatchup")
            versus.setToolTip("Hay datos del equipo rival, sin rival directo fiable.")
            layout.addWidget(versus)
            icons: list[QLabel] = []
            names: list[str] = []
            for enemy in enemy_team[:5]:
                if not isinstance(enemy, dict):
                    continue
                name = str(enemy.get("champion_name") or "Campeón")
                icon = QLabel()
                icon.setObjectName("savedGameEnemyIcon")
                icon.setFixedSize(34, 34)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setContentsMargins(3, 3, 3, 3)
                self._set_champion_icon(icon, name, 26)
                icon.setToolTip(name)
                icons.append(icon)
                names.append(name)
                layout.addWidget(icon)
            overflow = QLabel()
            overflow.setObjectName("homeEnemyTeamOverflow")
            layout.addWidget(overflow)
            self._enemy_team_rows.append((icons, overflow, names))
            return
        versus = QLabel("VS")
        versus.setObjectName("savedGameMatchup")
        layout.addWidget(versus)
        unavailable = QLabel("—")
        unavailable.setObjectName("homeOpponentUnknown")
        unavailable.setToolTip(
            "No hay datos suficientes del equipo rival para esta partida."
        )
        layout.addWidget(unavailable)

    def _update_enemy_team_visibility(self) -> None:
        """Limita los iconos del equipo rival según el ancho del historial."""
        if not hasattr(self, "history_scroll"):
            return
        width = self.history_scroll.viewport().width()
        visible_count = 5 if width >= 1000 else 4 if width >= 700 else 3
        for icons, overflow, names in self._enemy_team_rows:
            for index, icon in enumerate(icons):
                icon.setVisible(index < visible_count)
            hidden = names[visible_count:]
            overflow.setVisible(bool(hidden))
            overflow.setText(f"+{len(hidden)}" if hidden else "")
            overflow.setToolTip(", ".join(hidden))

    def render_matches(self, *_args: Any) -> None:
        """Pinta un lote acotado de partidas según el filtro elegido."""
        self._enemy_team_rows.clear()
        while self.match_rows.count():
            item = self.match_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        queue = self.filter_combo.currentData()
        matches = (
            self._matches
            if queue == "all"
            else [
                m
                for m in self._matches
                if str(m.get("mode", "")).casefold().find(queue) >= 0
                or str(m.get("queue_id"))
                == {"solo": "420", "flex": "440", "aram": "450", "normal": "400"}.get(
                    queue
                )
                or (queue == "normal" and str(m.get("queue_id")) == "430")
            ]
        )
        visible = matches[: self._visible_count]
        for match in visible:
            row = QFrame()
            row.setObjectName("savedGameRow")
            result = str(match.get("result") or "unknown")
            row.setProperty(
                "result",
                "win"
                if result == "victory"
                else "loss"
                if result == "defeat"
                else "unknown",
            )
            row.setToolTip(str(match.get("mode") or ""))
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)
            upper = QHBoxLayout()
            upper.setSpacing(9)
            outcome = QLabel(
                {"victory": "VICTORIA", "defeat": "DERROTA", "remake": "REMAKE"}.get(
                    result, "SIN RESULTADO"
                )
            )
            outcome.setObjectName("savedGameResult")
            outcome.setProperty(
                "result", result if result in {"victory", "defeat"} else "unknown"
            )
            outcome.setMinimumWidth(76)
            upper.addWidget(outcome)
            player = self._champion_entry(
                str(match.get("champion_name") or "Campeón"), 0, 38
            )
            upper.addWidget(player)
            lane_names = {
                "top": "Superior",
                "jungle": "Jungla",
                "mid": "Medio",
                "bot": "Inferior",
                "support": "Soporte",
            }
            lane = QLabel(lane_names.get(str(match.get("lane") or ""), "—"))
            lane.setObjectName("homeModeChip")
            upper.addWidget(lane)
            self._add_opponent_presentation(upper, match)
            upper.addStretch(1)
            upper.addWidget(
                QLabel(
                    f"{int(match.get('duration_seconds') or 0) // 60}:{int(match.get('duration_seconds') or 0) % 60:02d}"
                )
            )
            row_layout.addLayout(upper)
            lower = QHBoxLayout()
            kda = QLabel(
                f"{match.get('kills', '—')} / {match.get('deaths', '—')} / {match.get('assists', '—')}"
            )
            kda.setObjectName("homeKda")
            lower.addWidget(kda)
            cs_rate = match.get("cs_per_min")
            lower.addWidget(
                QLabel(
                    f"{match.get('cs', '—')} CS"
                    + (f" · {cs_rate}/min" if cs_rate is not None else "")
                )
            )
            lower.addStretch(1)
            item_ids = list(match.get("items") or [])[:6]
            if match.get("trinket"):
                item_ids.append(match["trinket"])
            for item_id in item_ids:
                icon = QLabel()
                icon.setObjectName("itemSlot")
                icon.setFixedSize(34, 34)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setContentsMargins(2, 2, 2, 2)
                self._set_item_icon(icon, item_id, 26)
                lower.addWidget(icon)
            try:
                started = (
                    datetime.fromisoformat(
                        str(match.get("started_at") or "").replace("Z", "+00:00")
                    )
                    .astimezone()
                    .strftime("%d %b")
                )
            except ValueError:
                started = "Fecha —"
            lower.addSpacing(6)
            lower.addWidget(QLabel(started))
            if match.get("analyzable"):
                saved_link = match.get("saved_match_link") or {}
                saved_match_id = str(saved_link.get("saved_match_id") or "")
                badge = QPushButton("◆ ANALIZABLE")
                badge.setObjectName("homeAnalyzableBadge")
                badge.setToolTip("Abrir análisis de esta partida")
                badge.setCursor(Qt.CursorShape.PointingHandCursor)
                badge.setEnabled(bool(saved_match_id))
                badge.clicked.connect(
                    lambda checked=False, value=saved_match_id: (
                        self.saved_match_requested.emit(value) if value else None
                    )
                )
                lower.addWidget(badge)
            row_layout.addLayout(lower)
            self.match_rows.addWidget(row)
        self._update_enemy_team_visibility()
        self.more_button.setVisible(len(matches) > len(visible))

    def _load_more(self) -> None:
        """Añade el siguiente lote de partidas a la lista visible."""
        self._visible_count += 25
        self.render_matches()
