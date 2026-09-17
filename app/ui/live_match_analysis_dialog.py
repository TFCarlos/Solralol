from __future__ import annotations


import time
from bisect import bisect_left
from copy import deepcopy
from functools import partial
from typing import Any


from PySide6.QtCore import QPointF, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
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
from app.services.match_log_service import MatchLogService
from app.services.settings_service import SettingsService
from app.ui.match_ai_worker import MatchAIWorker

from app.ui.recommendation_panel import RecommendationPanel
from app.ui.live_timeline import TimelineView
from app.ui.live_analysis_task import AnalysisTask
from app.ui.draft_icon_cache import DraftIconCache


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
        self.ally_values = sorted(ally_values)
        self.enemy_values = sorted(enemy_values)
        points = self.ally_values + self.enemy_values
        self._cached_ranges = self._ranges(points) if points else (0, 1, 0, 1)
        self._geometry_cache = {}
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
        if len(self.ally_values) + len(self.enemy_values) < 2:
            painter.setPen(QColor(147, 170, 202))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "Esperando snapshots LIVE…")
            return
        ranges = self._cached_ranges
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
        cache_key = (id(values), bounds.x(), bounds.y(), bounds.width(), bounds.height())
        polygon = self._geometry_cache.get(cache_key)
        if polygon is None:
            # At most four points per horizontal pixel, retaining spikes,
            # endpoints and chronological order. Original values are untouched.
            sampled = []
            bucket = []
            previous_x = None
            for point in values:
                x = int((point[0] - minimum_time) * max(1, bounds.width()) / (maximum_time - minimum_time))
                if previous_x is not None and x != previous_x:
                    sampled.extend(self._bucket_extrema(bucket))
                    bucket = []
                bucket.append(point)
                previous_x = x
            sampled.extend(self._bucket_extrema(bucket))
            polygon = QPolygonF([
                self._map_point(point, bounds, minimum_time, maximum_time, minimum_value, maximum_value)
                for point in sampled
            ])
            if len(self._geometry_cache) >= 2:
                self._geometry_cache.clear()
            self._geometry_cache[cache_key] = polygon
        painter.setPen(QPen(color, 2))
        painter.drawPolyline(polygon)
        if len(values) <= 60:
            painter.setPen(QPen(color, 5))
            painter.drawPoints(polygon)

    @staticmethod
    def _bucket_extrema(bucket):
        if len(bucket) <= 4:
            return bucket
        indices = sorted({0, len(bucket) - 1,
                          min(range(len(bucket)), key=lambda i: bucket[i][1]),
                          max(range(len(bucket)), key=lambda i: bucket[i][1])})
        return [bucket[i] for i in indices]


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
        if not values:
            return None
        index = bisect_left(values, time_value, key=lambda point: point[0])
        return min(values[max(0, index - 1):index + 1],
                   key=lambda point: abs(point[0] - time_value))


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
        self.ai_tab_button: QPushButton | None = None
        self.ai_worker: MatchAIWorker | None = None
        self.is_analyzing_ai = False
        self._last_ui_refresh = 0.0
        self._revision = 0
        self._role_pages = {}
        self._series_cache = {}
        self._event_cache = {}
        self._post_stats = {}
        self._stats_task = None
        self._closed = False
        self._ai_page = None
        self._ai_page_key = None
        self._recommendation_revision = -1
        self._sync_status = self.session.get("final_sync", {}).get("status")
        self._pending_session = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._flush_session)
        self._icon_cache = DraftIconCache(self)


        self.setObjectName("liveMatchAnalysisDialog")
        self.setWindowTitle("Análisis LIVE · SolraLoL")
        self.resize(1640, 1000)
        self.setMinimumSize(1200, 760)


        self._build_ui()
        self.show_role("TOP")
        self._prepare_session()


    def done(self, result):
        self._closed = True
        self._refresh_timer.stop()
        self._pending_session = None
        super().done(result)
        self._dispose_if_idle()

    def _dispose_if_idle(self):
        # QRunnables have no widget references and their queued connections
        # disconnect automatically on destruction. A QThread must finish first.
        if self._closed and not (self.ai_worker and self.ai_worker.isRunning()):
            self.deleteLater()

    def _prepare_session(self):
        """One background calculation at a time; newer sessions supersede old results."""
        if self._closed or self._stats_task is not None:
            return
        # Only three phase checkpoints and the latest point are needed by the
        # achievement/stat calculator. Do not copy the full event log/history.
        source = self.session
        checkpoints = []
        for seconds in (900, 1800, float("inf")):
            points = {}
            for snapshot in source.get("snapshots", []):
                if float(snapshot.get("time", 0) or 0) > seconds:
                    break
                points.update(snapshot.get("players", {}))
            checkpoints.append({"time": seconds, "players": points})
        compact = deepcopy({
            key: source.get(key, {})
            for key in ("players", "lane_matchups", "winning_team", "final_scoreboard")
        })
        compact["snapshots"] = deepcopy(checkpoints)
        catalog, version = self.item_catalog, self.assets.version

        def calculate():
            attach_achievements(compact, catalog, version)
            stats = {
                key: calculate_post_stats(compact, key, catalog, version)
                for key in compact["players"]
            }
            return compact["achievements"], stats

        task = AnalysisTask(self._revision, calculate)
        task.signals.finished.connect(self._stats_ready, Qt.ConnectionType.QueuedConnection)
        self._stats_task = task
        QThreadPool.globalInstance().start(task)

    @Slot(object, object, object)
    def _stats_ready(self, revision, result, error):
        self._stats_task = None
        if self._closed:
            return
        if revision != self._revision:
            self._prepare_session()
            return
        if error:
            self.header_badge.setToolTip(f"No se pudieron calcular los atributos: {error}")
            return
        self.session["achievements"], self._post_stats = result
        for page in self._role_pages.values():
            page["revision"] = -1
        if self.current_view == "role":
            self.show_role(self.current_role)

    def update_session(
        self,
        session: dict[str, Any],
    ) -> None:
        if not session or self._closed:
            return

        self._pending_session = session
        elapsed = time.monotonic() - self._last_ui_refresh
        if session.get("final_sync", {}).get("status") != self._sync_status or elapsed >= self.UI_REFRESH_INTERVAL_SECONDS:
            self._flush_session()
        elif not self._refresh_timer.isActive():
            self._refresh_timer.start(max(1, int((self.UI_REFRESH_INTERVAL_SECONDS - elapsed) * 1000)))

    def _flush_session(self):
        if self._pending_session is None:
            return
        self._refresh_timer.stop()
        self.session = self._pending_session
        self._pending_session = None
        self._sync_status = self.session.get("final_sync", {}).get("status")
        self._last_ui_refresh = time.monotonic()
        self._revision += 1
        self._series_cache.clear()
        self._event_cache.clear()
        self._refresh_header()
        self._prepare_session()
        if self.current_view == "recommendations":
            self.show_recommendations()
        elif self.current_view == "role":
            self.show_role(self.current_role)
        # Never interrupt reading/analyzing AI with an automatic role switch.


    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)
        self.header = self._create_header()
        root.addWidget(self.header)
        root.addLayout(self._create_role_tabs())
        self.content = QStackedWidget()
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

        # Botón de Análisis con IA
        self.ai_tab_button = QPushButton("🤖 ANALIZAR PARTIDA CON IA")
        self.ai_tab_button.setObjectName("aiTabButton")
        self.ai_tab_button.setCheckable(True)
        self.ai_tab_button.clicked.connect(
            lambda checked=False: self.show_ai_analysis()
        )
        layout.addWidget(self.ai_tab_button)
        
        return layout


    def show_role(self, role):
        self.current_view = "role"
        self.current_role = role
        self.role_group.setExclusive(False)
        for key, button in self.role_buttons.items():
            button.setChecked(key == role)
        self.role_group.setExclusive(True)
        self.recommendation_button.setChecked(False)
        self.ai_tab_button.setChecked(False)
        matchup = self.session.get("lane_matchups", {}).get(role, {})
        keys = (matchup.get("ally_key"), matchup.get("enemy_key"))
        page = self._role_pages.get(role)
        if page is not None and page["keys"] != keys:
            self.content.removeWidget(page["widget"])
            page["widget"].deleteLater()
            page = None
        if page is None:
            if not all(keys):
                widget = QLabel("No se pudo identificar este enfrentamiento en la telemetría actual.")
                widget.setObjectName("liveAnalysisEmpty")
                widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                page = {"widget": widget, "keys": keys, "revision": self._revision}
            else:
                players = self.session.get("players", {})
                widget = self._create_role_content(players.get(keys[0], {}), keys[0],
                                                   players.get(keys[1], {}), keys[1])
                page = {"widget": widget, "keys": keys, "revision": self._revision,
                        "timeline": self.timeline_view, "filters": self._timeline_filters}
            self._role_pages[role] = page
            self.content.addWidget(page["widget"])
        self.content.setCurrentWidget(page["widget"])
        if "timeline" not in page:
            return
        self.timeline_view = page["timeline"]
        if page["revision"] != self._revision:
            players = self.session.get("players", {})
            body = page["widget"].layout()
            # Keep timeline, its selection and scroll; refresh only side content.
            page["widget"].setUpdatesEnabled(False)
            try:
                for index, key, side in ((0, keys[0], "ally"), (2, keys[1], "enemy")):
                    scroll = body.itemAt(index).widget()
                    position = scroll.verticalScrollBar().value()
                    old = scroll.takeWidget()
                    scroll.setWidget(self._create_side_panel(players.get(key, {}), key, side))
                    if old is not None:
                        old.deleteLater()
                    scroll.verticalScrollBar().setValue(position)
                page["revision"] = self._revision
            finally:
                page["widget"].setUpdatesEnabled(True)
        for mode, button in page["filters"].items():
            button.setChecked(mode == self.timeline_mode)
        timeline_key = (self._revision, self.timeline_mode)
        if page.get("timeline_key") != timeline_key:
            self.timeline_view.set_events(self._events_for_mode(*keys), *keys)
            page["timeline_key"] = timeline_key


    def show_recommendations(self) -> None:
        """Muestra el panel de recomendaciones reutilizando su instancia."""
        self.current_view = "recommendations"

        self.role_group.setExclusive(False)
        for button in self.role_buttons.values():
            button.setChecked(False)
        self.role_group.setExclusive(True)

        if self.recommendation_button is not None:
            self.recommendation_button.setChecked(True)

        if self.ai_tab_button is not None:
            self.ai_tab_button.setChecked(False)

        if self.recommendation_panel is None:
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
            self.content.addWidget(self.recommendation_panel)

        self.content.setCurrentWidget(self.recommendation_panel)
        if self._recommendation_revision != self._revision:
            self.recommendation_panel.update_recommendations(self.session)
            self._recommendation_revision = self._revision

    def show_ai_analysis(self) -> None:
        """Muestra la pestaña de Análisis de Partida con IA."""
        self.current_view = "ai_analysis"

        self.role_group.setExclusive(False)
        for button in self.role_buttons.values():
            button.setChecked(False)
        self.role_group.setExclusive(True)

        if self.recommendation_button is not None:
            self.recommendation_button.setChecked(False)

        if self.ai_tab_button is not None:
            self.ai_tab_button.setChecked(True)

        key = (self.is_analyzing_ai, self.session.get("ai_analysis"), self.session.get("ai_analysis_model"))
        if self._ai_page is None or self._ai_page_key != key:
            if self._ai_page is not None:
                self.content.removeWidget(self._ai_page)
                self._ai_page.deleteLater()
            # Generating/writing the log is not needed merely to open this tab.
            self._ai_page = self._create_ai_analysis_view("")
            self._ai_page_key = key
            self.content.addWidget(self._ai_page)
        self.content.setCurrentWidget(self._ai_page)

    def _create_ai_analysis_view(self, formatted_log: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Header card para el log y la IA
        header_card = QFrame()
        header_card.setObjectName("aiHeaderCard")
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(18, 14, 18, 14)
        h_layout.setSpacing(14)

        info_vbox = QVBoxLayout()
        info_vbox.setSpacing(4)
        title = QLabel("🤖 ANÁLISIS DE PARTIDA CON IA (GEMINI)")
        title.setObjectName("aiHeaderTitle")
        info_vbox.addWidget(title)

        log_path_str = self.session.get("match_log_txt_path") or f"~/.solralol/match_logs/match_{self.session.get('session_id', 'id')}.log"
        path_label = QLabel(f"📄 Fichero de Log: {log_path_str}")
        path_label.setObjectName("aiLogPathLabel")
        info_vbox.addWidget(path_label)
        h_layout.addLayout(info_vbox, 1)

        # Botón para inspeccionar el log
        view_log_btn = QPushButton("📄 Ver Log de Partida")
        view_log_btn.setObjectName("secondaryAiButton")
        view_log_btn.clicked.connect(self._request_raw_log)
        h_layout.addWidget(view_log_btn)

        # Botón para ejecutar/re-ejecutar el análisis
        has_analysis = bool(self.session.get("ai_analysis"))
        analyze_btn = QPushButton("🔄 Re-analizar con IA" if has_analysis else "🤖 Analizar Partida con IA")
        analyze_btn.setObjectName("primaryAiButton")
        analyze_btn.setEnabled(not getattr(self, "is_analyzing_ai", False))
        analyze_btn.clicked.connect(self._start_ai_analysis)
        h_layout.addWidget(analyze_btn)

        layout.addWidget(header_card)

        # Cuerpo principal
        if getattr(self, "is_analyzing_ai", False):
            loading_card = QFrame()
            loading_card.setObjectName("aiIntroCard")
            l_layout = QVBoxLayout(loading_card)
            l_layout.setContentsMargins(24, 32, 24, 32)
            l_layout.setSpacing(16)
            l_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            spin_lbl = QLabel("⏳ Generando análisis inteligente con Gemini IA...")
            spin_lbl.setStyleSheet("color: #c4b5fd; font-size: 16px; font-weight: bold;")
            spin_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_layout.addWidget(spin_lbl)

            desc_lbl = QLabel("Procesando la cronología de eventos, farmeo, builds, asesinatos y muertes...")
            desc_lbl.setStyleSheet("color: #94a3b8; font-size: 12px;")
            desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l_layout.addWidget(desc_lbl)

            pbar = QProgressBar()
            pbar.setRange(0, 0)
            pbar.setMaximumWidth(400)
            pbar.setStyleSheet("QProgressBar { min-height: 8px; border-radius: 4px; background: rgba(30, 41, 59, 200); } QProgressBar::chunk { background: #8b5cf6; border-radius: 4px; }")
            l_layout.addWidget(pbar)

            layout.addWidget(loading_card, 1)

        elif has_analysis:
            model_used = self.session.get("ai_analysis_model", "Gemini AI")
            model_info = QLabel(f"✨ Análisis generado por {model_used}")
            model_info.setStyleSheet("color: #a78bfa; font-size: 11px; font-weight: bold; margin-left: 4px;")
            layout.addWidget(model_info)

            text_browser = QTextBrowser()
            text_browser.setObjectName("aiAnalysisTextBrowser")
            text_browser.setOpenExternalLinks(True)
            text_browser.setMarkdown(self.session["ai_analysis"])
            layout.addWidget(text_browser, 1)

        else:
            intro_card = QFrame()
            intro_card.setObjectName("aiIntroCard")
            i_layout = QVBoxLayout(intro_card)
            i_layout.setContentsMargins(28, 24, 28, 24)
            i_layout.setSpacing(14)

            head_lbl = QLabel("¿Qué evaluará la IA en esta partida?")
            head_lbl.setStyleSheet("color: #c4b5fd; font-size: 18px; font-weight: bold;")
            i_layout.addWidget(head_lbl)

            items_text = (
                "• 🟢🟡🔴 **Fases del juego:** Rendimiento en Early (0-15m), Mid (15-25m) y Late game.\n"
                "• 🌾 **Farmeo y Eficiencia:** CS por minuto, curva de farmeo y brechas de oro vs el rival.\n"
                "• ⚔️ **Build vs Equipo Enemigo:** Adaptación de ítems ante la composición y tipos de daño enemigos.\n"
                "• ⏱️ **Velocidad de Compra y Tempos:** Eficiencia de recalls y aprovechamiento de power spikes.\n"
                "• 🎯 **Kills vs Objetivos:** Identificación de bajas que dieron torres/dragones y **'kills vacías'**.\n"
                "• 💀 **Muertes e Impacto:** Cómo afectaron tus muertes a la pérdida de objetivos estratégicos.\n"
                "• 💡 **Consejos accionables:** Recomendaciones clave para tus siguientes partidas."
            )
            detail_lbl = QLabel()
            detail_lbl.setTextFormat(Qt.TextFormat.MarkdownText)
            detail_lbl.setText(items_text)
            detail_lbl.setStyleSheet("color: #cbd5e1; font-size: 13px; line-height: 1.5;")
            detail_lbl.setWordWrap(True)
            i_layout.addWidget(detail_lbl)

            start_btn = QPushButton("🚀 Comenzar Análisis con IA")
            start_btn.setObjectName("primaryAiButton")
            start_btn.setMinimumHeight(42)
            start_btn.clicked.connect(self._start_ai_analysis)
            i_layout.addWidget(start_btn, 0, Qt.AlignmentFlag.AlignLeft)

            i_layout.addStretch(1)
            layout.addWidget(intro_card, 1)

        return container

    def _request_raw_log(self):
        if getattr(self, "_log_task", None) is not None:
            return
        session = deepcopy(self.session)
        task = AnalysisTask(self._revision, lambda: MatchLogService().get_match_log(session)[1])
        task.signals.finished.connect(self._log_ready, Qt.ConnectionType.QueuedConnection)
        self._log_task = task
        QThreadPool.globalInstance().start(task)

    @Slot(object, object, object)
    def _log_ready(self, revision, text, error):
        self._log_task = None
        if self._closed:
            return
        if error:
            QMessageBox.warning(self, "Log de partida", error)
        elif self.isVisible():
            self._show_raw_log_dialog(text)

    def _start_ai_analysis(self) -> None:
        if self.is_analyzing_ai:
            return
        settings = SettingsService().load()
        api_key = settings.get("gemini_api_key", "").strip()

        if not api_key:
            QMessageBox.warning(
                self,
                "Gemini API Key Requerida",
                "No has configurado tu Gemini API Key.\n\n"
                "Por favor, ve a la pestaña de 'Ajustes' en la ventana principal de SolraLoL "
                "y añade tu API Key gratuita de Google AI Studio."
            )
            return

        self.is_analyzing_ai = True
        self.show_ai_analysis()

        self.ai_worker = MatchAIWorker(deepcopy(self.session), api_key, self)
        self.ai_worker.finished_analysis.connect(self._on_ai_analysis_success)
        self.ai_worker.error_occurred.connect(self._on_ai_analysis_error)
        self.ai_worker.finished.connect(self._dispose_if_idle)
        self.ai_worker.start()

    def _on_ai_analysis_success(self, markdown_text: str, model_used: str) -> None:
        self.is_analyzing_ai = False
        self.session["ai_analysis"] = markdown_text
        self.session["ai_analysis_model"] = model_used

        session = deepcopy(self.session)
        self._save_task = AnalysisTask(
            self._revision, lambda: MatchLogService().save_match_log(session)
        )
        QThreadPool.globalInstance().start(self._save_task)

        if not self._closed and self.current_view == "ai_analysis":
            self.show_ai_analysis()

    def _on_ai_analysis_error(self, error_msg: str) -> None:
        self.is_analyzing_ai = False
        if self._closed:
            return
        QMessageBox.critical(
            self,
            "Error en Análisis IA",
            f"No se pudo completar el análisis de la partida con IA:\n\n{error_msg}"
        )
        if self.current_view == "ai_analysis":
            self.show_ai_analysis()

    def _show_raw_log_dialog(self, formatted_log: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Registro Oficial de Log de Partida · SolraLoL")
        dialog.resize(950, 700)

        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(18, 18, 18, 18)
        d_layout.setSpacing(12)

        title = QLabel("📄 Fichero de Log de Partida")
        title.setStyleSheet("color: #c4b5fd; font-size: 15px; font-weight: bold;")
        d_layout.addWidget(title)

        text_edit = QTextBrowser()
        text_edit.setPlainText(formatted_log)
        text_edit.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11px; color: #cbd5e1; background: #090e1c; border: 1px solid rgba(138, 92, 246, 120); border-radius: 8px; padding: 10px;")
        d_layout.addWidget(text_edit, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        copy_btn = QPushButton("📋 Copiar Log")
        copy_btn.setObjectName("secondaryAiButton")
        def copy_log():
            QApplication.clipboard().setText(formatted_log)
            copy_btn.setText("✓ ¡Copiado!")
        copy_btn.clicked.connect(copy_log)
        btn_layout.addWidget(copy_btn)

        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("secondaryButton")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)

        d_layout.addLayout(btn_layout)
        dialog.exec()

    def _create_role_content(self, ally, ally_key, enemy, enemy_key):
        content = QWidget()
        body = QHBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        def side_scroll(player, key, side):
            scroll = QScrollArea()
            scroll.setObjectName("analysisFullScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setMinimumWidth(320)
            scroll.setWidget(self._create_side_panel(player, key, side))
            return scroll

        body.addWidget(side_scroll(ally, ally_key, "ally"), 3)
        body.addWidget(self._create_timeline_panel(ally_key, enemy_key), 4)
        body.addWidget(side_scroll(enemy, enemy_key, "enemy"), 3)
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


    def _extract_runes_data(self, player: dict) -> list[dict[str, Any]]:
        runes = player.get("runes", {})
        if not isinstance(runes, dict):
            runes = {}

        items = []
        keystone = runes.get("keystone")
        primary_tree = runes.get("primaryRuneTree") or runes.get("primary_tree")
        secondary_tree = runes.get("secondaryRuneTree") or runes.get("secondary_tree")

        def _val(x):
            if isinstance(x, dict):
                return x.get('displayName') or x.get('name') or ""
            return str(x) if x else ""

        k_name = _val(keystone)
        p_name = _val(primary_tree)
        s_name = _val(secondary_tree)

        if k_name:
            items.append({"label": "Clave", "name": k_name, "is_keystone": True})
        if p_name and p_name.lower() != k_name.lower():
            items.append({"label": "Principal", "name": p_name, "is_keystone": False})
        if s_name:
            items.append({"label": "Secundaria", "name": s_name, "is_keystone": False})

        if not items and "live" in runes and isinstance(runes["live"], list):
            for entry in runes["live"]:
                name = _val(entry)
                if name:
                    items.append({"label": "Runa", "name": name, "is_keystone": False})

        if not items:
            champ_name = player.get("champion_name", "")
            try:
                from data_dragon import CHAMPION_MEMORY_CACHE
                champ_info = CHAMPION_MEMORY_CACHE.get(champ_name, {})
                common_runes = champ_info.get("common_runes", []) if isinstance(champ_info, dict) else []
                if common_runes and isinstance(common_runes, list) and len(common_runes) > 0:
                    first_page = common_runes[0]
                    if isinstance(first_page, dict):
                        k = first_page.get("keystone")
                        p = first_page.get("primary_tree")
                        s = first_page.get("secondary_tree")
                        if k:
                            items.append({"label": "Clave", "name": str(k), "is_keystone": True})
                        if p:
                            items.append({"label": "Principal", "name": str(p), "is_keystone": False})
                        if s:
                            items.append({"label": "Secundaria", "name": str(s), "is_keystone": False})
            except Exception:
                pass

        return items

    def _create_runes_panel(self, player):
        frame = QFrame()
        frame.setObjectName("liveInfoPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title = QLabel("RUNAS DEL JUGADOR")
        title.setObjectName("livePanelTitle")
        layout.addWidget(title)

        runes_data = self._extract_runes_data(player)
        if not runes_data:
            empty_lbl = QLabel("Sin runas configuradas")
            empty_lbl.setStyleSheet("color: #7890a8; font-size: 11px; font-style: italic;")
            layout.addWidget(empty_lbl)
            return frame

        from data_dragon import get_rune_icon_path

        runes_row = QHBoxLayout()
        runes_row.setSpacing(12)

        for item in runes_data:
            rune_name = item["name"]
            label_type = item["label"]
            is_ks = item.get("is_keystone", False)

            item_layout = QHBoxLayout()
            item_layout.setSpacing(6)

            icon_lbl = QLabel()
            size = 32 if is_ks else 26
            icon_lbl.setFixedSize(size, size)
            icon_lbl.setObjectName("liveRuneIcon")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self._icon_cache.assign(
                icon_lbl, ("live-rune", self.assets.version, rune_name), size,
                partial(get_rune_icon_path, rune_name, self.assets.version),
                "⚡" if is_ks else "🔹",
            )

            text_vbox = QVBoxLayout()
            text_vbox.setSpacing(1)

            lbl_tag = QLabel(label_type.upper())
            lbl_tag.setStyleSheet("color: #d9ae4f; font-size: 9px; font-weight: 800;")

            lbl_name = QLabel(rune_name)
            lbl_name.setStyleSheet("color: #e2e8f0; font-size: 11px; font-weight: 700;")

            text_vbox.addWidget(lbl_tag)
            text_vbox.addWidget(lbl_name)

            item_layout.addWidget(icon_lbl)
            item_layout.addLayout(text_vbox)

            runes_row.addLayout(item_layout)

        runes_row.addStretch(1)
        layout.addLayout(runes_row)
        return frame

    def _create_awards_panel(self, player_key, side):
        frame = QFrame()
        frame.setObjectName("liveAwardsPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        title = QLabel("LOGROS Y DESTACADOS")
        title.setObjectName("livePanelTitle")
        layout.addWidget(title)
        awards = self.session.get("achievements", {}).get(player_key, [])
        if not awards:
            empty_lbl = QLabel("Sin logros detectados aún")
            empty_lbl.setStyleSheet("color: #7890a8; font-size: 11px; font-style: italic;")
            layout.addWidget(empty_lbl)
        else:
            grid_layout = QGridLayout()
            grid_layout.setContentsMargins(0, 0, 0, 0)
            grid_layout.setSpacing(5)

            for index, award in enumerate(awards):
                text = str(award)
                badge = QLabel(text)
                badge.setObjectName("liveAchievementBadge")
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

                lower_text = text.lower()
                if "early" in lower_text or "inicio" in lower_text:
                    state_type = "early"
                elif "mid" in lower_text:
                    state_type = "mid"
                elif "late" in lower_text or "tardío" in lower_text:
                    state_type = "late"
                elif "victoria" in lower_text or "mvp" in lower_text:
                    state_type = "victory"
                elif "crítico" in lower_text or "penetración" in lower_text or "daño" in lower_text:
                    state_type = "offense"
                elif "armadura" in lower_text or "antiheal" in lower_text or "resistencia" in lower_text:
                    state_type = "defense"
                else:
                    state_type = "default"

                badge.setProperty("type", state_type)

                row = index // 2
                col = index % 2
                grid_layout.addWidget(badge, row, col)

            layout.addLayout(grid_layout)
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
        layout.setSpacing(6)

        title = QLabel("ESTADÍSTICAS Y ATRIBUTOS")
        title.setObjectName("livePanelTitle")
        layout.addWidget(title)

        point = self._latest_player_point(player_key)
        post_stats = self._post_stats.get(player_key, {})
        riot_cs = self._riot_final_value(player_key, "cs")
        cs = riot_cs if riot_cs is not None else point.get("cs", 0)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        raw_stats = point.get("stats", {})
        if not isinstance(raw_stats, dict):
            raw_stats = {}

        armor_pen = float(post_stats.get("armor_pen_percent", 0) or 0)
        if armor_pen <= 1:
            armor_pen *= 100

        life_steal = float(post_stats.get("life_steal_percent", 0) or 0)
        if life_steal <= 1:
            life_steal *= 100

        critical = float(post_stats.get("crit", 0) or 0)
        if critical <= 1:
            critical *= 100

        metrics = [
            ("KDA", f"{int(point.get('kills', 0) or 0)}/{int(point.get('deaths', 0) or 0)}/{int(point.get('assists', 0) or 0)}", "#e2e8f0"),
            ("Nivel", f"{int(point.get('level', 1) or 1)}", "#cbd5e1"),
            ("CS", f"{int(cs or 0)}", "#38bdf8"),
            ("Oro estim.", f"{int(point.get('estimated_gold', 0) or 0):,}", "#facc15"),
            ("Visión", f"{int(raw_stats.get('vision_score', 0) or 0)}", "#a78bfa"),
            ("Vida máx.", f"{int(post_stats.get('hp', 0) or 0):,}", "#4ade80"),
            ("AD", f"{float(post_stats.get('ad', 0) or 0):.1f}", "#f87171"),
            ("AP", f"{float(post_stats.get('ap', 0) or 0):.1f}", "#c084fc"),
            ("Armadura", f"{float(post_stats.get('armor', 0) or 0):.1f}", "#fbbf24"),
            ("MR", f"{float(post_stats.get('mr', 0) or 0):.1f}", "#60a5fa"),
            ("Letalidad", f"{float(post_stats.get('lethality', 0) or 0):.1f}", "#f97316"),
            ("Pen. arm.", f"{armor_pen:.0f}%", "#fb923c"),
            ("Robo vida", f"{life_steal:.0f}%", "#f43f5e"),
            ("Crítico", f"{critical:.0f}%", "#eab308"),
        ]

        for index, (label, val, val_color) in enumerate(metrics):
            row_idx = index // 2
            col_idx = (index % 2) * 2

            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")

            val_lbl = QLabel(str(val))
            val_lbl.setStyleSheet(f"color: {val_color}; font-size: 11px; font-weight: 800;")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            grid.addWidget(lbl, row_idx, col_idx)
            grid.addWidget(val_lbl, row_idx, col_idx + 1)

        layout.addLayout(grid)

        quality = QLabel("≈ Base + nivel + objetos" if post_stats else "Calculando atributos en segundo plano…")
        quality.setObjectName("liveMetricEstimate")
        quality.setStyleSheet("color: #64748b; font-size: 10px; font-style: italic; margin-top: 4px;")
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

        valid_items = []
        for i in item_ids:
            try:
                val = int(i)
                if val > 0:
                    valid_items.append(val)
            except (TypeError, ValueError):
                continue

        if not valid_items:
            empty_lbl = QLabel("Sin objetos")
            empty_lbl.setStyleSheet("color: #7890a8; font-size: 11px; font-style: italic;")
            layout.addWidget(empty_lbl)
            return frame

        row = QHBoxLayout()
        row.setSpacing(6)

        for item_id in valid_items:
            icon = QLabel()
            icon.setFixedSize(32, 32)
            icon.setObjectName("liveEventIcon")
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

            catalog = self.item_catalog.get("items", self.item_catalog)
            item_info = catalog.get(str(item_id), catalog.get(item_id, {}))
            item_name = item_info.get("name", f"Objeto {item_id}") if isinstance(item_info, dict) else f"Objeto {item_id}"
            icon.setToolTip(item_name)

            icon_url = self.assets.item_url(item_id)
            self.assets.set_label_image(
                icon,
                icon_url,
                f"analysis-item:{item_id}:32",
                32,
                Qt.AspectRatioMode.KeepAspectRatio
            )
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

            # Missing official data is not an official zero.
            if all(final.get(field) is None for field in ("cs_minions", "cs_jungle")):
                return None

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
        self._timeline_filters = {}
        for text, mode in (("Eventos de línea", "lane"), ("Eventos globales", "global"), ("TODO", "all")):
            button = QPushButton(text)
            button.setObjectName("timelineFilterButton")
            button.setCheckable(True)
            button.setChecked(mode == self.timeline_mode)
            button.clicked.connect(lambda checked=False, selected=mode: self._change_timeline_mode(selected))
            group.addButton(button)
            self._timeline_filters[mode] = button
            filters.addWidget(button)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.timeline_view = TimelineView(self.item_catalog, panel)
        self.timeline_view.set_events(self._events_for_mode(ally_key, enemy_key), ally_key, enemy_key)
        layout.addWidget(self.timeline_view, 1)
        return panel


    def _events_for_mode(self, ally_key, enemy_key):
        cache_key = (ally_key, enemy_key, self.timeline_mode)
        if cache_key in self._event_cache:
            return self._event_cache[cache_key]
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
        result.sort(key=lambda item: (item.get("time", 0), item.get("order", 0)))
        self._event_cache[cache_key] = result
        return result


    def _change_timeline_mode(self, mode):
        self.timeline_mode = mode
        matchup = self.session.get("lane_matchups", {}).get(self.current_role, {})
        ally_key, enemy_key = matchup.get("ally_key"), matchup.get("enemy_key")
        self.timeline_view.set_events(self._events_for_mode(ally_key, enemy_key), ally_key, enemy_key)
        page = self._role_pages.get(self.current_role, {})
        page["timeline_key"] = (self._revision, mode)
        for value, button in page.get("filters", {}).items():
            button.setChecked(value == mode)


    def _player_series(
        self,
        player_key,
    ):
        """
        Construye series exclusivamente con snapshots LIVE registrados.

        No utiliza ni convierte las estadísticas finales de Riot.
        """
        if player_key in self._series_cache:
            return self._series_cache[player_key]
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

        self._series_cache[player_key] = series
        return series


    def _latest_player_point(self, player_key):
        for snapshot in reversed(self.session.get("snapshots", [])):
            point = snapshot.get("players", {}).get(player_key)
            if isinstance(point, dict):
                return point
        return {}