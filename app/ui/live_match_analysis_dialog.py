from __future__ import annotations


import time
from typing import Any


from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from app.services.data_dragon_assets import DataDragonAssetService
from app.services.game_calculator import calculate_item_stats
from app.services.live_match_tracker import LiveMatchTracker
from app.services.live_analysis_models_and_calculator import (
    attach_achievements,
    calculate_post_stats,
)

import requests
from app.ui.recommendation_panel import RecommendationPanel


class VersusChart(QWidget):
    def __init__(
        self,
        title: str,
        ally_values: list[tuple[float, float]],
        enemy_values: list[tuple[float, float]],
        ally_name: str,
        enemy_name: str,
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)


        self.title = title
        self.ally_values = ally_values
        self.enemy_values = enemy_values
        self.ally_name = ally_name
        self.enemy_name = enemy_name
        self.unit = unit


        self.hover_position: QPointF | None = None


        self.setObjectName("versusChart")
        self.setMinimumHeight(178)
        self.setMouseTracking(True)


    def mouseMoveEvent(self, event):
        self.hover_position = event.position()
        self.update()


    def leaveEvent(self, event):
        self.hover_position = None
        self.update()


    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(8, 19, 34, 220))
        painter.setPen(QColor(220, 231, 247))
        painter.drawText(12, 18, self.title)
        painter.setPen(QColor(58, 188, 245))
        painter.drawText(12, 36, f"● {self.ally_name}")
        enemy_text = f"● {self.enemy_name}"
        enemy_width = painter.fontMetrics().horizontalAdvance(enemy_text)
        painter.setPen(QColor(244, 87, 108))
        painter.drawText(self.width() - enemy_width - 15, 36, enemy_text)
        bounds = self.rect().adjusted(43, 49, -15, -30)
        points = self.ally_values + self.enemy_values
        if len(points) < 2:
            painter.setPen(QColor(147, 170, 202))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "Esperando snapshots LIVE…")
            return
        ranges = self._ranges(points)
        self._draw_grid(painter, bounds, *ranges)
        self._draw_series(painter, bounds, self.ally_values, *ranges, QColor(58, 188, 245))
        self._draw_series(painter, bounds, self.enemy_values, *ranges, QColor(244, 87, 108))
        painter.setPen(QColor(58, 188, 245))
        painter.drawText(
            12,
            36,
            f"● {self.ally_name}",
        )
        painter.setPen(QColor(244, 87, 108))
        painter.drawText(
            self.width() - enemy_width - 15,
            36,
            enemy_text,
        )
        self._draw_hover(painter, bounds, *ranges)


    @staticmethod
    def _ranges(points):
        times = [point[0] for point in points]
        values = [point[1] for point in points]
        minimum_time, maximum_time = min(times), max(times)
        minimum_value, maximum_value = min(0.0, min(values)), max(values)
        if maximum_time <= minimum_time:
            maximum_time = minimum_time + 1.0
        if maximum_value <= minimum_value:
            maximum_value = minimum_value + 1.0
        padding = max((maximum_value - minimum_value) * 0.08, 1.0)
        return minimum_time, maximum_time, max(0.0, minimum_value - padding), maximum_value + padding


    def _draw_grid(self, painter, bounds, minimum_time, maximum_time, minimum_value, maximum_value):
        grid_pen = QPen(QColor(93, 126, 170, 80))
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        for step in range(5):
            ratio = step / 4
            y = int(bounds.bottom() - bounds.height() * ratio)
            painter.drawLine(bounds.left(), y, bounds.right(), y)
            value = minimum_value + (maximum_value - minimum_value) * ratio
            painter.setPen(QColor(135, 159, 194))
            painter.drawText(3, y + 4, self._format_value(value))
            painter.setPen(grid_pen)
        for step in range(5):
            ratio = step / 4
            x = int(bounds.left() + bounds.width() * ratio)
            painter.drawLine(x, bounds.top(), x, bounds.bottom())
            seconds = minimum_time + (maximum_time - minimum_time) * ratio
            painter.setPen(QColor(135, 159, 194))
            painter.drawText(x - 17, self.height() - 9, LiveMatchTracker.format_time(seconds))
            painter.setPen(grid_pen)


    def _draw_series(self, painter, bounds, values, minimum_time, maximum_time, minimum_value, maximum_value, color):
        if not values:
            return
        painter.setPen(QPen(color, 2))
        previous = None
        for point in values:
            mapped = self._map_point(point, bounds, minimum_time, maximum_time, minimum_value, maximum_value)
            if previous is not None:
                painter.drawLine(previous, mapped)
            previous = mapped
        painter.setPen(QPen(color, 5))
        for point in values:
            painter.drawPoint(self._map_point(point, bounds, minimum_time, maximum_time, minimum_value, maximum_value))


    def _draw_hover(self, painter, bounds, minimum_time, maximum_time, minimum_value, maximum_value):
        if self.hover_position is None or not bounds.contains(self.hover_position.toPoint()):
            return
        x = self.hover_position.x()
        ratio = (x - bounds.left()) / max(bounds.width(), 1)
        hover_time = minimum_time + ratio * (maximum_time - minimum_time)
        ally = self._nearest(self.ally_values, hover_time)
        enemy = self._nearest(self.enemy_values, hover_time)
        pen = QPen(QColor(237, 209, 117, 180))
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(int(x), bounds.top(), int(x), bounds.bottom())
        lines = [LiveMatchTracker.format_time(hover_time)]
        if ally:
            lines.append(f"{self.ally_name}: {self._format_value(ally[1])}")
        if enemy:
            lines.append(f"{self.enemy_name}: {self._format_value(enemy[1])}")
        width = max(painter.fontMetrics().horizontalAdvance(line) for line in lines) + 16
        height = len(lines) * 16 + 10
        tooltip_x = min(int(x) + 9, bounds.right() - width)
        tooltip_y = bounds.top() + 8
        painter.fillRect(tooltip_x, tooltip_y, width, height, QColor(3, 10, 20, 238))
        painter.setPen(QColor(235, 242, 252))
        for index, line in enumerate(lines):
            painter.drawText(tooltip_x + 8, tooltip_y + 17 + index * 16, line)


    @staticmethod
    def _nearest(values, time_value):
        return min(values, key=lambda point: abs(point[0] - time_value)) if values else None


    @staticmethod
    def _map_point(point, bounds, minimum_time, maximum_time, minimum_value, maximum_value):
        x_ratio = (point[0] - minimum_time) / (maximum_time - minimum_time)
        y_ratio = (point[1] - minimum_value) / (maximum_value - minimum_value)
        return QPointF(bounds.left() + bounds.width() * x_ratio, bounds.bottom() - bounds.height() * y_ratio)


    def _format_value(self, value):
        return f"{int(round(value)):,}{self.unit}"

class RiotComparisonBar(QWidget):
    """
    Comparativa final de Riot mediante dos barras horizontales.

    Azul: aliado.
    Rojo: enemigo.
    """

    def __init__(
        self,
        title: str,
        ally_value: float,
        enemy_value: float,
        ally_name: str,
        enemy_name: str,
        unit: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.title = title
        self.ally_value = float(ally_value or 0)
        self.enemy_value = float(enemy_value or 0)
        self.ally_name = str(ally_name or "Aliado")
        self.enemy_name = str(enemy_name or "Enemigo")
        self.unit = unit

        self.setObjectName("riotComparisonBar")
        self.setMinimumHeight(108)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(8, 19, 34, 220))

        bold_font = painter.font()
        bold_font.setBold(True)
        painter.setFont(bold_font)
        painter.setPen(QColor(237, 209, 117))
        painter.drawText(12, 20, f"{self.title} · RIOT")

        normal_font = painter.font()
        normal_font.setBold(False)
        painter.setFont(normal_font)

        ally_color = QColor(58, 188, 245)
        enemy_color = QColor(244, 87, 108)
        muted_color = QColor(135, 159, 194)
        background_color = QColor(33, 54, 82)

        maximum = max(self.ally_value, self.enemy_value, 1.0)

        label_width = 84
        value_width = 78
        left = label_width + 12
        right = self.width() - value_width - 12
        available_width = max(1, right - left)

        ally_y = 45
        enemy_y = 76
        bar_height = 16

        painter.setPen(ally_color)
        painter.drawText(
            10,
            ally_y + 13,
            self._short_name(self.ally_name),
        )

        painter.setPen(enemy_color)
        painter.drawText(
            10,
            enemy_y + 13,
            self._short_name(self.enemy_name),
        )

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background_color)

        painter.drawRoundedRect(
            left,
            ally_y,
            available_width,
            bar_height,
            4,
            4,
        )

        painter.drawRoundedRect(
            left,
            enemy_y,
            available_width,
            bar_height,
            4,
            4,
        )

        ally_width = int(
            available_width * self.ally_value / maximum
        )

        enemy_width = int(
            available_width * self.enemy_value / maximum
        )

        painter.setBrush(ally_color)
        painter.drawRoundedRect(
            left,
            ally_y,
            max(0, ally_width),
            bar_height,
            4,
            4,
        )

        painter.setBrush(enemy_color)
        painter.drawRoundedRect(
            left,
            enemy_y,
            max(0, enemy_width),
            bar_height,
            4,
            4,
        )

        painter.setPen(muted_color)
        painter.drawText(
            right + 7,
            ally_y + 13,
            self._format_value(self.ally_value),
        )

        painter.drawText(
            right + 7,
            enemy_y + 13,
            self._format_value(self.enemy_value),
        )

    def _format_value(self, value: float) -> str:
        if self.unit:
            return f"{value:,.0f}{self.unit}"

        return f"{value:,.0f}"

    @staticmethod
    def _short_name(name: str) -> str:
        return name[:12] + "…" if len(name) > 13 else name

class LiveMatchAnalysisDialog(QDialog):
    ROLE_LABELS = {"TOP": "TOP VS TOP", "JUNGLE": "JGL VS JGL", "MIDDLE": "MID VS MID", "BOTTOM": "BOT VS BOT", "UTILITY": "SUP VS SUP"}
    UI_REFRESH_INTERVAL_SECONDS = 5.0


    def __init__(
        self,
        session: dict[str, Any],
        assets: DataDragonAssetService,
        item_catalog: dict[str, Any],
        parent=None,
    ) -> None:
        super().__init__(parent)


        self.session = session or {}
        self.assets = assets
        self.item_catalog = item_catalog or {}


        self.timeline_mode = "lane"
        self.current_role = "TOP"
        self.current_view = "role"
        self.role_buttons: dict[str, QPushButton] = {}
        self.recommendation_button: QPushButton | None = None
        self.recommendation_panel: RecommendationPanel | None = None
        self._last_ui_refresh = 0.0


        self.setObjectName("liveMatchAnalysisDialog")
        self.setWindowTitle("Análisis LIVE · SolraLoL")
        self.resize(1640, 1000)
        self.setMinimumSize(1200, 760)


        self._prepare_session()
        self._build_ui()
        self.show_role("TOP")


    def _prepare_session(self):
        self.session.setdefault("achievements", {})
        try:
            attach_achievements(self.session, self.item_catalog)
        except Exception:
            pass

    def update_session(
        self,
        session: dict[str, Any],
    ) -> None:
        if not session:
            return

        previous_sync_status = self.session.get("final_sync", {}).get("status")
        now = time.monotonic()
        final_sync_changed = (
            session.get("final_sync", {}).get("status")
            != previous_sync_status
        )
        self.session = session
        if (
            not final_sync_changed
            and now - self._last_ui_refresh < self.UI_REFRESH_INTERVAL_SECONDS
        ):
            return
        self._last_ui_refresh = now
        self._prepare_session()
        self._refresh_header()

        if getattr(self, "current_view", "role") == "recommendations":
            if (
                getattr(self, "recommendation_panel", None)
                is not None
            ):
                self.recommendation_panel.update_recommendations(
                    self.session
                )
            return

        self.show_role(self.current_role)


    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        self.header = self._create_header()
        root.addWidget(self.header)
        root.addLayout(self._create_role_tabs())
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.content, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_button = QPushButton("Cerrar")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)


    def _create_header(self):
        header = QFrame()
        header.setObjectName("liveAnalysisHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        self.header_title = QLabel()
        self.header_title.setObjectName("liveAnalysisTitle")
        layout.addWidget(self.header_title)
        layout.addStretch(1)
        self.header_badge = QLabel()
        self.header_badge.setObjectName("liveAnalysisBadge")
        layout.addWidget(self.header_badge)
        self._refresh_header()
        return header


    def _refresh_header(self):
        if not hasattr(self, "header_title"):
            return
        self.header_title.setText(f"{self.session.get('champion_name', 'Partida LIVE')} · {self.session.get('game_mode', 'UNKNOWN')}")
        self.header_badge.setText("TELEMETRÍA POSTGAME" if self.session.get("final_sync", {}).get("status") == "synced" else "TELEMETRÍA LIVE")


    def _create_role_tabs(self):
        layout = QHBoxLayout()
        layout.setSpacing(7)
        self.role_group = QButtonGroup(self)
        self.role_group.setExclusive(True)
        for role, label in self.ROLE_LABELS.items():
            button = QPushButton(label)
            button.setObjectName("liveRoleButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=role: self.show_role(value))
            self.role_group.addButton(button)
            self.role_buttons[role] = button
            layout.addWidget(button)
        layout.addStretch(1)
        
        # Botón de recomendaciones
        self.recommendation_button = QPushButton("📊 RECOMENDACIONES")
        self.recommendation_button.setObjectName("recommendationTabButton")
        self.recommendation_button.setCheckable(True)
        self.recommendation_button.clicked.connect(
            lambda checked=False: self.show_recommendations()
        )
        layout.addWidget(self.recommendation_button)
        
        return layout


    def show_role(self, role):
        if self.current_view == "recommendations" and self.recommendation_button:
            self.recommendation_button.setChecked(False)
        
        self.current_view = "role"
        self.current_role = role
        if role in self.role_buttons:
            self.role_buttons[role].setChecked(True)
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        matchup = self.session.get("lane_matchups", {}).get(role, {})
        ally_key, enemy_key = matchup.get("ally_key"), matchup.get("enemy_key")
        players = self.session.get("players", {})
        ally, enemy = players.get(ally_key, {}), players.get(enemy_key, {})
        if not ally_key or not enemy_key:
            empty = QLabel("No se pudo identificar este enfrentamiento en la telemetría actual.")
            empty.setObjectName("liveAnalysisEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(empty, 1)
            return
        scroll = QScrollArea()
        scroll.setObjectName("analysisFullScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._create_role_content(ally, ally_key, enemy, enemy_key))
        self.content_layout.addWidget(scroll, 1)


    def show_recommendations(self) -> None:
        """Muestra el panel de recomendaciones reutilizando su instancia."""
        self.current_view = "recommendations"

        for button in self.role_buttons.values():
            button.setChecked(False)

        if self.recommendation_button is not None:
            self.recommendation_button.setChecked(True)

        if self.recommendation_panel is None:
            while self.content_layout.count():
                item = self.content_layout.takeAt(0)
                widget = item.widget()

                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()

            self.recommendation_panel = RecommendationPanel(
                self.content
            )
            self.recommendation_panel.configure(
                self.assets,
                self.item_catalog,
            )
            self.recommendation_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            self.content_layout.addWidget(
                self.recommendation_panel,
                1,
            )

        self.recommendation_panel.update_recommendations(
            self.session
        )

    def _create_role_content(self, ally, ally_key, enemy, enemy_key):
        content = QWidget()
        body = QHBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(self._create_side_panel(ally, ally_key, "ally"), 3)
        body.addWidget(self._create_timeline_panel(ally_key, enemy_key), 4)
        body.addWidget(self._create_side_panel(enemy, enemy_key, "enemy"), 3)
        return content


    def _create_side_panel(self, player, player_key, side):
        panel = QFrame()
        panel.setObjectName("livePlayerPanel")
        panel.setProperty("side", side)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self._create_player_header(player, player_key, side))
        layout.addWidget(self._create_runes_panel(player))
        layout.addWidget(self._create_awards_panel(player_key, side))
        layout.addWidget(self._create_metrics_panel(player, player_key))
        layout.addWidget(self._create_inventory_panel(player, player_key))
        layout.addWidget(self._create_charts_panel(player_key))
        layout.addStretch(1)
        return panel


    def _player_match_rank(
        self,
        player_key: str,
    ) -> str:
        """
        Clasifica los 10 jugadores por oro estimado final.


        MVP = mayor oro.
        2º a 10º = resto de posiciones.
        Si hay empate de oro, se ordena por KDA y después por CS.
        """
        rows = []


        for key in self.session.get(
            "players",
            {},
        ):
            point = self._latest_player_point(key)


            gold = float(
                point.get(
                    "estimated_gold",
                    0,
                ) or 0
            )


            kills = float(
                point.get(
                    "kills",
                    0,
                ) or 0
            )


            deaths = float(
                point.get(
                    "deaths",
                    0,
                ) or 0
            )


            assists = float(
                point.get(
                    "assists",
                    0,
                ) or 0
            )


            cs = float(
                point.get(
                    "cs",
                    0,
                ) or 0
            )


            kda_score = (
                kills + assists
            ) / max(1.0, deaths)


            rows.append(
                (
                    key,
                    gold,
                    kda_score,
                    cs,
                )
            )


        rows.sort(
            key=lambda row: (
                row[1],
                row[2],
                row[3],
            ),
            reverse=True,
        )


        for index, row in enumerate(
            rows,
            start=1,
        ):
            if row[0] != player_key:
                continue


            if index == 1:
                return "MVP"


            return f"{index}º"


        return "—"


    def _create_player_header(self, player, player_key, side):
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        champion = player.get("champion_name", "Desconocido")
        portrait = QLabel(champion[:3].upper())
        portrait.setObjectName("livePlayerPortrait")
        portrait.setFixedSize(62, 62)
        portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.assets.set_label_image(portrait, self.assets.champion_url(champion), f"live-champion:{champion}:62", 62)
        layout.addWidget(portrait)
        text = QVBoxLayout()
        champion_label = QLabel(champion)
        champion_label.setObjectName("livePlayerChampion")
        text.addWidget(champion_label)
        name = QLabel(player.get("riot_id", "Desconocido"))
        name.setObjectName("livePlayerName")
        text.addWidget(name)
        role = QLabel(player.get("role", "UNKNOWN"))
        role.setObjectName("livePlayerRole")
        text.addWidget(role)
        layout.addLayout(text, 1)
        point = self._latest_player_point(player_key)
        rank = self._player_match_rank(
            player_key
        )


        rank_label = QLabel(rank)
        rank_label.setObjectName("livePlayerRank")


        layout.addWidget(rank_label)


        score = QLabel(
            f"{point.get('kills', 0)} / "
            f"{point.get('deaths', 0)} / "
            f"{point.get('assists', 0)}"
        )


        score.setObjectName("livePlayerScore")


        layout.addWidget(score)
        return header


    def _create_runes_panel(self, player):
        frame = QFrame()
        frame.setObjectName("liveInfoPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel("RUNAS · VISIBLES EN LIVE")
        title.setObjectName("livePanelTitle")
        layout.addWidget(title)
        runes = player.get("runes", {})
        entries = runes.get("live", []) if isinstance(runes, dict) else []
        if not entries:
            entries = ["Runa no disponible"]
        for entry in entries:
            text = entry.get("displayName", entry.get("name", "Runa")) if isinstance(entry, dict) else str(entry)
            layout.addWidget(QLabel(text))
        return frame


    def _create_awards_panel(self, player_key, side):
        frame = QFrame()
        frame.setObjectName("liveAwardsPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel("LOGROS")
        title.setObjectName("livePanelTitle")
        layout.addWidget(title)
        awards = self.session.get("achievements", {}).get(player_key, [])
        if not awards:
            layout.addWidget(QLabel("Aún sin logros detectados"))
        else:
            for award in awards:
                badge = QLabel(str(award))
                badge.setObjectName("liveAchievementBadge")
                layout.addWidget(badge)
        return frame


    def _create_metrics_panel(
        self,
        player,
        player_key,
    ):
        frame = QFrame()
        frame.setObjectName("liveMetricSummary")


        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)


        point = self._latest_player_point(
            player_key
        )


        post_stats = calculate_post_stats(
            self.session,
            player_key,
            self.item_catalog,
            self.assets.version,
        )


        layout.addWidget(
            self._metric_line(
                "KDA",
                (
                    f"{int(point.get('kills', 0) or 0)} / "
                    f"{int(point.get('deaths', 0) or 0)} / "
                    f"{int(point.get('assists', 0) or 0)}"
                ),
            )
        )


        layout.addWidget(
            self._metric_line(
                "Nivel",
                int(point.get("level", 1) or 1),
            )
        )


        layout.addWidget(
            self._metric_line(
                "CS",
                int(point.get("cs", 0) or 0),
            )
        )


        layout.addWidget(
            self._metric_line(
                "Oro estimado",
                f"{int(point.get('estimated_gold', 0) or 0):,}",
            )
        )


        raw_stats = point.get("stats", {})


        if not isinstance(raw_stats, dict):
            raw_stats = {}


        if raw_stats.get("vision_score") is not None:
            layout.addWidget(
                self._metric_line(
                    "Visión",
                    int(
                        raw_stats.get(
                            "vision_score",
                            0,
                        ) or 0
                    ),
                )
            )


        layout.addWidget(
            self._metric_line(
                "Vida máxima",
                f"{int(post_stats.get('hp', 0) or 0):,}",
            )
        )


        layout.addWidget(
            self._metric_line(
                "AD",
                f"{float(post_stats.get('ad', 0) or 0):.1f}",
            )
        )


        layout.addWidget(
            self._metric_line(
                "AP",
                f"{float(post_stats.get('ap', 0) or 0):.1f}",
            )
        )


        layout.addWidget(
            self._metric_line(
                "Armadura",
                f"{float(post_stats.get('armor', 0) or 0):.1f}",
            )
        )


        layout.addWidget(
            self._metric_line(
                "MR",
                f"{float(post_stats.get('mr', 0) or 0):.1f}",
            )
        )


        layout.addWidget(
            self._metric_line(
                "Letalidad",
                f"{float(post_stats.get('lethality', 0) or 0):.1f}",
            )
        )


        armor_pen = float(
            post_stats.get(
                "armor_pen_percent",
                0,
            ) or 0
        )


        if armor_pen <= 1:
            armor_pen *= 100


        layout.addWidget(
            self._metric_line(
                "Pen. armadura",
                f"{armor_pen:.0f}%",
            )
        )


        life_steal = float(
            post_stats.get(
                "life_steal_percent",
                0,
            ) or 0
        )


        if life_steal <= 1:
            life_steal *= 100


        layout.addWidget(
            self._metric_line(
                "Robo de vida",
                f"{life_steal:.0f}%",
            )
        )


        critical = float(
            post_stats.get(
                "crit",
                0,
            ) or 0
        )


        if critical <= 1:
            critical *= 100


        layout.addWidget(
            self._metric_line(
                "Crítico",
                f"{critical:.0f}%",
            )
        )


        quality = QLabel(
            "≈ Estimado: base + nivel + objetos; "
            "runas y buffs no incluidos para rivales."
        )


        quality.setObjectName(
            "liveMetricEstimate"
        )


        quality.setWordWrap(True)


        layout.addWidget(quality)


        return frame


    def _metric_line(
        self,
        label: str,
        value: object,
    ) -> QLabel:
        row = QLabel(
            f"{label}: {value}"
        )


        row.setObjectName(
            "liveMetricLine"
        )


        return row


    def _build_item_metrics(
        self,
        player: dict,
        point: dict,
    ) -> dict:
        """
        Calcula estadísticas totales estimadas:


        base del campeón
        + crecimiento por nivel
        + inventario actual.


        Para el jugador local, si el tracker guardó championStats,
        se usan sus valores reales como prioridad.
        """
        from data_dragon import get_champion_data


        champion_name = player.get(
            "champion_name",
            "Desconocido",
        )


        level = int(
            point.get(
                "level",
                1,
            ) or 1
        )


        item_ids = point.get(
            "items",
            player.get("items", []),
        )


        normalized_items = []


        for item_id in item_ids:
            try:
                normalized_items.append(
                    {
                        "itemID": int(item_id),
                    }
                )
            except (TypeError, ValueError):
                continue


        item_player = {
            **player,
            "items": normalized_items,
        }


        item_stats = calculate_item_stats(
            item_player,
            self.item_catalog,
        )


        champion_data = get_champion_data(
            champion_name,
            self.assets.version,
        )


        champion_stats = champion_data.get(
            "stats",
            {},
        )


        if not isinstance(champion_stats, dict):
            champion_stats = {}


        levels_gained = max(0, level - 1)


        def stat(
            base_key: str,
            growth_key: str,
            item_key: str,
        ) -> float:
            return (
                float(champion_stats.get(base_key, 0))
                + float(champion_stats.get(growth_key, 0))
                * levels_gained
                + float(item_stats.get(item_key, 0))
            )


        calculated = {
            "hp": stat(
                "hp",
                "hpperlevel",
                "hp",
            ),
            "ad": stat(
                "attackdamage",
                "attackdamageperlevel",
                "ad",
            ),
            "ap": float(item_stats.get("ap", 0)),
            "armor": stat(
                "armor",
                "armorperlevel",
                "armor",
            ),
            "mr": stat(
                "spellblock",
                "spellblockperlevel",
                "mr",
            ),
            "crit": float(item_stats.get("crit", 0)),
            "lethality": float(
                item_stats.get(
                    "lethality",
                    0,
                )
            ),
            "armor_pen_percent": float(
                item_stats.get(
                    "armor_pen_percent",
                    0,
                )
            ),
            "grievous_wounds": bool(
                item_stats.get(
                    "grievous_wounds",
                    False,
                )
            ),
        }


        live_stats = point.get(
            "live_stats",
            {},
        )


        if not isinstance(live_stats, dict):
            live_stats = {}


        live_stat_keys = {
            "hp": (
                "maxHealth",
                "maxhealth",
                "healthMax",
            ),
            "ad": (
                "attackDamage",
                "attackdamage",
            ),
            "ap": (
                "abilityPower",
                "abilitypower",
            ),
            "armor": ("armor",),
            "mr": (
                "magicResist",
                "magicresist",
                "spellBlock",
            ),
            "crit": (
                "critChance",
                "critchance",
            ),
            "lethality": (
                "lethality",
                "armorPenetrationFlat",
            ),
            "armor_pen_percent": (
                "armorPenetrationPercent",
                "percentArmorPenetration",
            ),
        }


        for output_key, source_keys in live_stat_keys.items():
            for source_key in source_keys:
                value = live_stats.get(source_key)


                if value is None:
                    continue


                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue


                if value > 0:
                    calculated[output_key] = value


                break


        return calculated


    def _create_inventory_panel(self, player, player_key):
        frame = QFrame()
        frame.setObjectName("liveInventoryPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        title = QLabel("INVENTARIO · TIEMPO REAL")
        title.setObjectName("livePanelTitle")
        layout.addWidget(title)
        point = self._latest_player_point(player_key)
        item_ids = point.get("items", player.get("items", []))
        if not item_ids:
            layout.addWidget(QLabel("Sin objetos"))
            return frame
        row = QHBoxLayout()
        for item_id in item_ids:
            icon = QLabel(str(item_id))
            icon.setFixedSize(30, 30)
            icon.setObjectName("liveEventIcon")
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.assets.set_label_image(icon, self.assets.item_url(int(item_id)), f"analysis-item:{item_id}:30", 30, Qt.AspectRatioMode.KeepAspectRatio)
            row.addWidget(icon)
        row.addStretch(1)
        layout.addLayout(row)
        return frame

    def _riot_final_value(
        self,
        player_key: str,
        metric: str,
    ) -> float | None:
        final_sync = self.session.get("final_sync", {})

        if (
            not isinstance(final_sync, dict)
            or final_sync.get("status") != "synced"
        ):
            return None

        player = self.session.get("players", {}).get(
            player_key,
            {},
        )

        if not isinstance(player, dict):
            return None

        final = player.get("final", {})

        if not isinstance(final, dict):
            return None

        # CS oficial total: súbditos de línea + monstruos neutrales.
        # Primero utiliza el total normalizado que ya produces.
        if metric == "cs":
            cs_total = final.get("cs_total")

            if cs_total is not None:
                try:
                    return float(cs_total)
                except (TypeError, ValueError):
                    pass

            try:
                return (
                    float(final.get("cs_minions", 0) or 0)
                    + float(final.get("cs_jungle", 0) or 0)
                )
            except (TypeError, ValueError):
                return None

        metric_keys = {
            "gold": (
                "gold_earned",
                "goldEarned",
            ),
            "kills": (
                "kills",
            ),
            "vision": (
                "vision_score",
                "visionScore",
            ),
            "damage_champions": (
                "damage_to_champions",
                "total_damage_dealt_to_champions",
            ),
            "damage_structures": (
                "damage_to_structures",
                "damage_dealt_to_turrets",
            ),
            "damage_objectives": (
                "damage_to_objectives",
                "damageDealtToObjectives",
            ),
            "damage_taken": (
                "damage_taken",
                "total_damage_taken",
            ),
            "healing": (
                "healing",
                "total_heal",
            ),
        }

        for field in metric_keys.get(metric, (metric,)):
            value = final.get(field)

            if value is None:
                continue

            try:
                return float(value)
            except (TypeError, ValueError):
                continue

        return None

    def _create_charts_panel(
        self,
        player_key,
    ):
        """
        Muestra comparativas del enfrentamiento actual.

        - Riot sincronizado: barras finales oficiales.
        - LIVE: gráficas de línea con snapshots temporales reales.
        - Cada métrica se muestra solo al ganador; los empates aparecen en
        ambos paneles.
        """
        container = QWidget()

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        matchup = self.session.get(
            "lane_matchups",
            {},
        ).get(
            self.current_role,
            {},
        )

        ally_key = matchup.get("ally_key")
        enemy_key = matchup.get("enemy_key")

        if player_key not in {
            ally_key,
            enemy_key,
        }:
            return container

        players = self.session.get(
            "players",
            {},
        )

        ally = players.get(
            ally_key,
            {},
        )

        enemy = players.get(
            enemy_key,
            {},
        )

        if not isinstance(ally, dict) or not isinstance(enemy, dict):
            return container

        # -------------------------------------------------------------
        # BARRAS FINALES RIOT
        # -------------------------------------------------------------
        riot_specs = (
            ("Oro ganado", "gold", "g"),
            ("CS", "cs", ""),
            ("Kills", "kills", ""),
            ("Visión", "vision", ""),
            ("Daño a campeones", "damage_champions", ""),
            ("Daño a estructuras", "damage_structures", ""),
            ("Daño a objetivos", "damage_objectives", ""),
            ("Daño recibido", "damage_taken", ""),
            ("Curación", "healing", ""),
        )

        riot_bars_added = 0

        for title, metric, unit in riot_specs:
            ally_value = self._riot_final_value(
                ally_key,
                metric,
            )

            enemy_value = self._riot_final_value(
                enemy_key,
                metric,
            )

            # Riot debe proporcionar ambos valores para comparar.
            if ally_value is None or enemy_value is None:
                continue

            if ally_value > enemy_value:
                winner_key = ally_key
            elif enemy_value > ally_value:
                winner_key = enemy_key
            else:
                winner_key = "tie"

            # La barra se añade al panel ganador, o a los dos si empatan.
            if winner_key not in {
                player_key,
                "tie",
            }:
                continue

            if riot_bars_added == 0:
                riot_title = QLabel(
                    "COMPARACIÓN FINAL · DATOS OFICIALES RIOT"
                )
                riot_title.setObjectName("livePanelTitle")
                riot_title.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                layout.addWidget(riot_title)

            if winner_key == "tie":
                tie_label = QLabel("EMPATE")
                tie_label.setObjectName("liveChartTie")
                tie_label.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                layout.addWidget(tie_label)

            bar = RiotComparisonBar(
                title=title,
                ally_value=ally_value,
                enemy_value=enemy_value,
                ally_name=ally.get(
                    "champion_name",
                    "Aliado",
                ),
                enemy_name=enemy.get(
                    "champion_name",
                    "Enemigo",
                ),
                unit=unit,
            )

            layout.addWidget(bar)
            riot_bars_added += 1

        # -------------------------------------------------------------
        # GRÁFICAS TEMPORALES LIVE
        # -------------------------------------------------------------
        ally_series = self._player_series(
            ally_key,
        )

        enemy_series = self._player_series(
            enemy_key,
        )

        live_specs = (
            ("Oro", "estimated_gold", " oro"),
            ("CS", "cs", " CS"),
            ("Kills", "kills", ""),
            ("Visión", "vision_score", ""),
            ("Daño a campeones", "damage_to_champions", ""),
            ("Daño a estructuras", "damage_to_structures", ""),
            ("Daño recibido", "damage_taken", ""),
            ("Sanación", "healing", ""),
        )

        live_charts_added = 0

        for title, key, unit in live_specs:
            ally_values = ally_series.get(
                key,
                [],
            )

            enemy_values = enemy_series.get(
                key,
                [],
            )

            # Se requiere timeline real. Una serie de un solo snapshot no
            # representa evolución; sí se acepta que la timeline exista solo
            # para uno de los dos jugadores.
            if len(ally_values) < 2 and len(enemy_values) < 2:
                continue

            winner_key = self._metric_winner(
                key,
                ally_key,
                enemy_key,
                ally_values,
                enemy_values,
            )

            if winner_key not in {
                player_key,
                "tie",
            }:
                continue

            if live_charts_added == 0:
                live_title = QLabel(
                    "EVOLUCIÓN TEMPORAL · DATOS LIVE"
                )
                live_title.setObjectName("livePanelTitle")
                live_title.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                layout.addWidget(live_title)

            chart_wrapper = QWidget()

            chart_layout = QVBoxLayout(chart_wrapper)
            chart_layout.setContentsMargins(0, 0, 0, 0)
            chart_layout.setSpacing(3)

            if winner_key == "tie":
                tie_label = QLabel("EMPATE")
                tie_label.setObjectName("liveChartTie")
                tie_label.setAlignment(
                    Qt.AlignmentFlag.AlignCenter
                )
                chart_layout.addWidget(tie_label)

            chart = VersusChart(
                title,
                ally_values,
                enemy_values,
                ally.get(
                    "champion_name",
                    "Aliado",
                ),
                enemy.get(
                    "champion_name",
                    "Enemigo",
                ),
                unit,
            )

            chart_layout.addWidget(chart)
            layout.addWidget(chart_wrapper)
            live_charts_added += 1

        if riot_bars_added == 0 and live_charts_added == 0:
            empty = QLabel(
                "No hay datos Riot comparables ni timelines LIVE "
                "suficientes para este enfrentamiento."
            )
            empty.setObjectName("liveChartsEmpty")
            empty.setWordWrap(True)
            layout.addWidget(empty)

        return container


    def _metric_winner(
        self,
        key,
        ally_key,
        enemy_key,
        ally_values,
        enemy_values,
    ):
        """
        Devuelve el jugador con el valor final mayor.

        Si una serie no está disponible, el jugador que sí tiene serie es el
        ganador. Si los valores finales son iguales, devuelve 'tie'.
        """
        if not ally_values and not enemy_values:
            return None

        if not ally_values:
            return enemy_key

        if not enemy_values:
            return ally_key

        ally_value = ally_values[-1][1]
        enemy_value = enemy_values[-1][1]

        if ally_value == enemy_value:
            return "tie"

        return ally_key if ally_value > enemy_value else enemy_key


    def _create_timeline_panel(self, ally_key, enemy_key):
        panel = QFrame()
        panel.setObjectName("liveTimelinePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        title = QLabel("TIMELINE · LIVE")
        title.setObjectName("liveTimelineTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        filters = QHBoxLayout()
        filters.addStretch(1)
        group = QButtonGroup(panel)
        for text, mode in (("Eventos de línea", "lane"), ("Eventos globales", "global"), ("TODO", "all")):
            button = QPushButton(text)
            button.setObjectName("timelineFilterButton")
            button.setCheckable(True)
            button.setChecked(mode == self.timeline_mode)
            button.clicked.connect(lambda checked=False, selected=mode: self._change_timeline_mode(selected))
            group.addButton(button)
            filters.addWidget(button)
        filters.addStretch(1)
        layout.addLayout(filters)
        scroll = QScrollArea()
        scroll.setObjectName("liveTimelineScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._create_timeline_content(ally_key, enemy_key))
        layout.addWidget(scroll, 1)
        return panel


    def _create_timeline_content(self, ally_key, enemy_key):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        events = self._events_for_mode(ally_key, enemy_key)
        for event in events:
            layout.addWidget(self._timeline_event_row(event, ally_key, enemy_key))
        if not events:
            empty = QLabel("Aún no hay eventos para este filtro.")
            empty.setObjectName("liveTimelineEmpty")
            layout.addWidget(empty)
        layout.addStretch(1)
        return root


    def _timeline_event_row(self, event, ally_key, enemy_key):
        row = QFrame()
        row.setObjectName("liveTimelineEvent")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 3, 0, 3)
        
        left, center, right = QLabel(), QLabel(event.get("time_label", "00:00")), QLabel()
        center.setObjectName("liveEventTime")
        
        player_key = event.get("player_key")
        target = left if player_key == ally_key else right if player_key == enemy_key else center
        
        event_type = event.get("type", "")
        
        # Eventos de objetos: solo nombre, sin imagen
        if event_type in {"item_purchased", "item_sold", "item_destroyed", "item_undo"}:
            item_id = event.get("item_id")
            item_name = self.assets.item_name(item_id)
            
            action_texts = {
                "item_purchased": "Compró",
                "item_sold": "Vendió",
                "item_destroyed": "Retiró",
                "item_undo": "Deshizo compra de",
            }
            
            action = action_texts.get(event_type, "Objeto")
            
            text_label = QLabel(f"{action} {item_name}")
            text_label.setWordWrap(True)
            text_label.setObjectName("liveEventLabel")
            
            # AÑADIR SIEMPRE EL CENTRO (timestamp)
            layout.addWidget(left, 1)
            layout.addWidget(center, 0)
            layout.addWidget(right, 1)
            
            # Reemplazar el target con el texto del objeto
            if target is left or target is right:
                target.setText(f"{action} {item_name}")
                target.setWordWrap(True)
                target.setObjectName("liveEventLabel")
        else:
            text = event.get("label", "Evento")
            target.setText(text if target is not center else "◆ " + text)
            target.setWordWrap(True)
            target.setObjectName("liveEventLabel")
            layout.addWidget(left, 1)
            layout.addWidget(center, 0)
            layout.addWidget(right, 1)
        
        return row


    def _get_item_name(self, item_id: int, version: str) -> str:
        """
        Obtiene el nombre de un objeto desde Data Dragon.
        """
        if not item_id or item_id == 0:
            return f"Objeto {item_id}"
        
        try:
            # Usar el catálogo ya descargado
            item_data = self.item_catalog.get(str(item_id))
            if item_data and isinstance(item_data, dict):
                return item_data.get("name", f"Objeto {item_id}")
            
            # Fallback: petición directa
            url = (
                f"https://ddragon.leagueoflegends.com/cdn/"
                f"{version}/data/es_ES/item.json"
            )
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            item_data = data.get("data", {}).get(str(item_id))
            if item_data:
                return item_data.get("name", f"Objeto {item_id}")
        except Exception:
            pass
        
        return f"Objeto {item_id}"


    def _events_for_mode(self, ally_key, enemy_key):
        result = []
        for event in self.session.get("events", []):
            player_key = event.get("player_key")
            lane_event = player_key in (ally_key, enemy_key)
            global_event = event.get("type") == "objective" or event.get("scope") == "global" or event.get("global") is True
            if self.timeline_mode == "lane" and lane_event:
                result.append(event)
            elif self.timeline_mode == "global" and global_event:
                result.append(event)
            elif self.timeline_mode == "all" and (lane_event or global_event):
                result.append(event)
        return sorted(result, key=lambda item: (item.get("time", 0), item.get("order", 0)))


    def _change_timeline_mode(self, mode):
        self.timeline_mode = mode
        self.show_role(self.current_role)


    def _player_series(
        self,
        player_key,
    ):
        """
        Construye series exclusivamente con snapshots LIVE registrados.

        No utiliza ni convierte las estadísticas finales de Riot.
        """
        keys = (
            "estimated_gold",
            "cs",
            "kills",
            "vision_score",
            "damage_to_champions",
            "damage_to_structures",
            "damage_taken",
            "healing",
        )

        series = {
            key: []
            for key in keys
        }

        for snapshot in self.session.get(
            "snapshots",
            [],
        ):
            if not isinstance(snapshot, dict):
                continue

            try:
                time_value = float(
                    snapshot.get(
                        "time",
                        0,
                    ) or 0
                )
            except (TypeError, ValueError):
                continue

            point = snapshot.get(
                "players",
                {},
            ).get(
                player_key,
                {},
            )

            if not isinstance(point, dict):
                continue

            for key in (
                "estimated_gold",
                "cs",
                "kills",
            ):
                value = point.get(key)

                if value is None:
                    continue

                try:
                    series[key].append(
                        (
                            time_value,
                            float(value),
                        )
                    )
                except (TypeError, ValueError):
                    continue

            stats = point.get("stats", {})

            if not isinstance(stats, dict):
                continue

            for key in (
                "vision_score",
                "damage_to_champions",
                "damage_to_structures",
                "damage_taken",
                "healing",
            ):
                value = stats.get(key)

                if value is None:
                    continue

                try:
                    series[key].append(
                        (
                            time_value,
                            float(value),
                        )
                    )
                except (TypeError, ValueError):
                    continue

        return series


    def _latest_player_point(self, player_key):
        for snapshot in reversed(self.session.get("snapshots", [])):
            point = snapshot.get("players", {}).get(player_key)
            if isinstance(point, dict):
                return point
        return {}