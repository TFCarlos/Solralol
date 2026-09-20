"""Overlays flotantes de la partida en vivo.

Tres paneles independientes, sin títulos y con la mínima información posible,
pensados para ocupar poco sobre el juego:

- ``gold``: oro por rol (aliado contra rival) y la diferencia acumulada.
- ``alerts``: compras de objetos completos y objetivos a punto de aparecer.
- ``threat``: el rival más fuerte y el más débil del equipo enemigo.

Cada panel se arrastra con el ratón, comparte opacidad y modo "click-through" y
recuerda su posición y su visibilidad en ``~/.solralol/settings.json``. Solo se
muestran durante una partida: fuera de ella no hay nada que enseñar.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.services.live_player_metrics_service import (
    ROLE_SHORT_LABELS,
    build_gold_report,
    build_rival_ranking,
    format_delta,
    format_gold,
)
from app.services.overlay_alert_service import (
    OverlayAlertTracker,
    format_clock,
)
from app.services.overlay_sound_service import (
    DEFAULT_VOLUME,
    OverlaySoundService,
)
from app.services.settings_service import SettingsService
from data_dragon import get_champion_icon_path, get_item_icon_path


PANEL_KEYS = ("gold", "alerts", "threat")

PANEL_LABELS = {
    "gold": "Oro",
    "alerts": "Alertas",
    "threat": "Rivales",
}

PANEL_WIDTHS = {
    "gold": 252,
    "alerts": 252,
    "threat": 208,
}

DEFAULT_OPACITY = 92
MIN_OPACITY = 30
MAX_OPACITY = 100
DEFAULT_ALERT_LEAD = 60
MIN_ALERT_LEAD = 15
MAX_ALERT_LEAD = 180
MAX_ALERT_ROWS = 3

CHAMPION_ICON_SIZE = 26
ITEM_ICON_SIZE = 22
PANEL_MARGIN = 24
PANEL_GAP = 12
PANEL_TOP_OFFSET = 120

GOLD_LABEL_WIDTH = 44
DELTA_LABEL_WIDTH = 40
ROLE_LABEL_WIDTH = 24
THREAT_NAME_WIDTH = 84
ALERT_TEXT_WIDTH = 150

_PANEL_STYLE = """
QWidget {
    background: transparent;
    font-family: "Segoe UI";
}

QFrame#overlayCard {
    background: rgba(8, 15, 27, 238);
    border: 1px solid rgba(97, 148, 211, 140);
    border-radius: 10px;
}

QLabel#overlayRole {
    color: #7d8fa8;
    font-size: 9px;
    font-weight: 800;
}

QLabel#overlayGold {
    font-size: 12px;
    font-weight: 800;
    color: #cfe0f5;
}

QLabel#overlayGold[side="enemy"] {
    color: #ffc6ce;
}

QLabel#overlayGold[kind="total"] {
    color: #f0d491;
    font-size: 13px;
}

QLabel#overlayDelta {
    color: #8fa2bd;
    font-size: 11px;
    font-weight: 800;
}

QLabel#overlayDelta[state="ahead"] {
    color: #70e0ad;
}

QLabel#overlayDelta[state="behind"] {
    color: #ff8793;
}

QLabel#overlayDelta[kind="total"] {
    font-size: 13px;
}

QLabel#overlayIcon {
    border: 1px solid rgba(120, 160, 205, 120);
    border-radius: 6px;
    background: rgba(15, 30, 50, 190);
    color: #dbe8f8;
    font-size: 9px;
    font-weight: 800;
}

QLabel#overlayIcon[state="empty"] {
    border: 1px dashed rgba(128, 167, 215, 80);
    background: rgba(5, 12, 24, 120);
    color: #46586e;
}

QLabel#overlayIcon[state="transparent"] {
    border: none;
    background: transparent;
}

QLabel#overlayClock {
    border: 1px solid rgba(217, 174, 79, 165);
    border-radius: 6px;
    background: rgba(58, 45, 20, 205);
    color: #f3d276;
    font-size: 11px;
    font-weight: 800;
}

QLabel#overlayClock[urgent="true"] {
    border-color: rgba(255, 135, 147, 200);
    background: rgba(70, 22, 30, 215);
    color: #ff9aa5;
}

QFrame#overlayAlertRow {
    background: rgba(13, 25, 43, 205);
    border-radius: 7px;
}

QFrame#overlayAccent {
    border-radius: 2px;
    background: rgba(255, 135, 147, 200);
}

QFrame#overlayAccent[side="ally"] {
    background: rgba(112, 176, 255, 205);
}

QFrame#overlayAccent[kind="objective"] {
    background: rgba(217, 174, 79, 215);
}

QLabel#overlayAlertText {
    color: #dbe6f4;
    font-size: 11px;
    font-weight: 700;
}

QFrame#overlayRecordingRow {
    background: rgba(74, 22, 30, 215);
    border: 1px solid rgba(255, 135, 147, 200);
    border-radius: 7px;
}

QLabel#overlayRecordingDot {
    color: #ff8793;
    font-size: 11px;
    font-weight: 900;
}

QLabel#overlayRecordingText {
    color: #ffdbe0;
    font-size: 11px;
    font-weight: 800;
}

QLabel#overlayMarker {
    color: #ff8793;
    font-size: 12px;
    font-weight: 900;
}

QLabel#overlayMarker[role="weakest"] {
    color: #70e0ad;
}

QLabel#overlayChampionName {
    color: #e6eefb;
    font-size: 11px;
    font-weight: 700;
}
"""


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _set_property(widget: QWidget, name: str, value) -> None:
    """Cambia una propiedad de estilo solo si hace falta (evita repintados)."""
    if widget.property(name) == value:
        return

    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _elide(label: QLabel, text: str, width: int) -> None:
    metrics = label.fontMetrics()
    label.setText(
        metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)
    )


def _icon_label(size: int) -> QLabel:
    label = QLabel()
    label.setObjectName("overlayIcon")
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setProperty("state", "empty")
    label.setProperty("asset_key", "")

    return label


class _FloatingPanel(QWidget):
    """Ventana sin marco, translúcida, arrastrable y opcionalmente ignorada."""

    def __init__(self, key: str, item_catalog: dict | None = None) -> None:
        super().__init__(None)

        self.key = key
        self.item_catalog = (
            item_catalog if isinstance(item_catalog, dict) else {}
        )
        self.click_through = False
        self.drag_position: QPoint | None = None
        self.moved_callback = None
        self.assets = None
        self._pending_icons: dict[str, list[tuple[QLabel, int]]] = {}

        self.setWindowTitle(f"Solralol · {PANEL_LABELS.get(key, key)}")
        self.setFixedWidth(PANEL_WIDTHS.get(key, 240))
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        self._apply_window_flags()

        self.card = QFrame()
        self.card.setObjectName("overlayCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(10, 8, 10, 9)
        self.body.setSpacing(3)

        self.setStyleSheet(_PANEL_STYLE)

    def _apply_window_flags(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        if self.click_through:
            flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)

    def set_assets(self, assets) -> None:
        """Servicio de iconos de Data Dragon (descarga asíncrona y caché)."""
        if assets is None or assets is self.assets:
            return

        if self.assets is not None:
            try:
                self.assets.image_ready.disconnect(self._receive_icon)
            except (RuntimeError, TypeError):
                pass

        self.assets = assets

        try:
            assets.image_ready.connect(
                self._receive_icon,
                Qt.ConnectionType.UniqueConnection,
            )
        except (RuntimeError, TypeError):
            assets.image_ready.connect(self._receive_icon)

    def _receive_icon(self, key: str, pixmap: QPixmap) -> None:
        pending = self._pending_icons.pop(key, None)

        if not pending:
            return

        for label, size in pending:
            try:
                if label.property("asset_key") != key:
                    continue
                label.setPixmap(self._scaled(pixmap, size))
            except RuntimeError:
                continue

    @staticmethod
    def _scaled(pixmap: QPixmap, size: int) -> QPixmap:
        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _apply_asset(
        self,
        label: QLabel,
        url: str,
        key: str,
        size: int,
    ) -> None:
        pixmap = self.assets.request_pixmap(url, key)

        if not pixmap.isNull():
            label.setPixmap(self._scaled(pixmap, size))
            return

        self._pending_icons.setdefault(key, []).append((label, size))

    def _set_champion_icon(
        self,
        label: QLabel,
        champion: str,
        size: int = CHAMPION_ICON_SIZE,
    ) -> None:
        if not champion:
            _set_property(label, "state", "empty")
            label.setPixmap(QPixmap())
            label.setText("")
            label.setProperty("asset_key", "")
            return

        _set_property(label, "state", "filled")

        # 1) caché local del repositorio (data/champion_icons), que llega con
        #    la instalación y evita depender de la red.
        pixmap = self._local_pixmap(
            get_champion_icon_path(champion, "", download=False)
        )

        if not pixmap.isNull():
            label.setPixmap(self._scaled(pixmap, size))
            return

        # 2) servicio de Data Dragon: caché en ~/.solralol y descarga async.
        label.setText(champion[:3].upper())

        if self.assets is None:
            return

        url = self.assets.champion_url(champion)
        key = f"overlay-champion::{url}"

        if label.property("asset_key") == key:
            return

        label.setProperty("asset_key", key)
        self._apply_asset(label, url, key, size)

    def _set_item_icon(
        self,
        label: QLabel,
        item_id,
        size: int = ITEM_ICON_SIZE,
    ) -> None:
        if not item_id:
            _set_property(label, "state", "empty")
            label.setPixmap(QPixmap())
            label.setText("")
            label.setProperty("asset_key", "")
            return

        _set_property(label, "state", "filled")
        label.setText("")

        # 1) caché local del repositorio (data/item_icons).
        try:
            local = get_item_icon_path(
                item_id,
                self.item_catalog,
                "",
                download=False,
            )
        except (OSError, ValueError):
            local = None

        pixmap = self._local_pixmap(local)

        if not pixmap.isNull():
            label.setPixmap(self._scaled(pixmap, size))
            return

        # 2) servicio de Data Dragon (caché en ~/.solralol y descarga async).
        if self.assets is None:
            return

        url = self.assets.item_url(item_id)
        key = f"overlay-item::{url}"

        if label.property("asset_key") == key:
            return

        label.setProperty("asset_key", key)
        self._apply_asset(label, url, key, size)

    @staticmethod
    def _local_pixmap(path) -> QPixmap:
        if path is None:
            return QPixmap()

        try:
            pixmap = QPixmap(str(path))
        except (OSError, RuntimeError):
            return QPixmap()

        return pixmap if not pixmap.isNull() else QPixmap()

    def set_click_through(self, enabled: bool) -> None:
        """Con los clics bloqueados el ratón atraviesa el panel."""
        self.click_through = bool(enabled)
        was_visible = self.isVisible()
        self.hide()
        self._apply_window_flags()

        if was_visible:
            self.show()
            self.raise_()

    def set_overlay_opacity(self, percent: int) -> None:
        bounded = max(MIN_OPACITY, min(int(percent), MAX_OPACITY))
        self.setWindowOpacity(bounded / 100)

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self.click_through
        ):
            self.drag_position = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self.drag_position is not None
            and not self.click_through
        ):
            self.move(
                event.globalPosition().toPoint() - self.drag_position
            )
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        moved = (
            self.drag_position is not None
            and event.button() == Qt.MouseButton.LeftButton
        )
        self.drag_position = None

        if moved and self.moved_callback is not None:
            self.moved_callback(self)

        event.accept()


class _GoldRow(QWidget):
    """Una fila del panel de oro: rol, icono+oro aliado, delta, oro+icono rival."""

    def __init__(self, total: bool = False) -> None:
        super().__init__()

        self.total_row = total
        kind = "total" if total else ""

        self.role = QLabel("")
        self.role.setObjectName("overlayRole")
        self.role.setFixedWidth(ROLE_LABEL_WIDTH)
        self.role.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.ally_icon = _icon_label(CHAMPION_ICON_SIZE)

        self.ally_gold = QLabel("")
        self.ally_gold.setObjectName("overlayGold")
        self.ally_gold.setProperty("side", "ally")
        self.ally_gold.setProperty("kind", kind)
        self.ally_gold.setFixedWidth(GOLD_LABEL_WIDTH)
        self.ally_gold.setAlignment(Qt.AlignmentFlag.AlignRight)

        self.delta = QLabel("")
        self.delta.setObjectName("overlayDelta")
        self.delta.setProperty("kind", kind)
        self.delta.setFixedWidth(DELTA_LABEL_WIDTH)
        self.delta.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.enemy_gold = QLabel("")
        self.enemy_gold.setObjectName("overlayGold")
        self.enemy_gold.setProperty("side", "enemy")
        self.enemy_gold.setProperty("kind", kind)
        self.enemy_gold.setFixedWidth(GOLD_LABEL_WIDTH)
        self.enemy_gold.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.enemy_icon = _icon_label(CHAMPION_ICON_SIZE)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(0)
        layout.addWidget(self.role, 0, 0)
        layout.addWidget(self.ally_icon, 0, 1)
        layout.addWidget(self.ally_gold, 0, 2)
        layout.addWidget(self.delta, 0, 3)
        layout.addWidget(self.enemy_gold, 0, 4)
        layout.addWidget(self.enemy_icon, 0, 5)


class GoldPanel(_FloatingPanel):
    """Panel 1: oro por rol aliado contra rival y total de cada equipo."""

    def __init__(self, item_catalog: dict | None = None) -> None:
        super().__init__("gold", item_catalog)

        self.total = _GoldRow(total=True)
        self.total.role.setText("")
        # Los huecos de icono no tienen sentido en el total: se dejan vacios
        # pero ocupando su sitio para que las columnas no se desplacen.
        for icon in (self.total.ally_icon, self.total.enemy_icon):
            _set_property(icon, "state", "transparent")
            icon.setText("")
        self.body.addWidget(self.total)

        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: rgba(97, 148, 211, 70);")
        self.body.addWidget(separator)

        self.rows: list[_GoldRow] = []
        self._lane_count = -1

    def render(self, report: dict) -> None:
        team = report.get("team", {}) if isinstance(report, dict) else {}
        lanes = report.get("lanes", []) if isinstance(report, dict) else []

        if not isinstance(lanes, list):
            lanes = []

        self._render_total(team)
        self._render_lanes(lanes)

        if self._lane_count != len(lanes):
            self._lane_count = len(lanes)
            self.adjustSize()

    def _render_total(self, team: dict) -> None:
        team = team if isinstance(team, dict) else {}
        self.total.ally_gold.setText(format_gold(team.get("ally", 0)))
        self.total.enemy_gold.setText(format_gold(team.get("enemy", 0)))
        self._set_delta(self.total.delta, int(team.get("delta", 0) or 0))

    def _render_lanes(self, lanes: list[dict]) -> None:
        while len(self.rows) < len(lanes):
            row = _GoldRow()
            self.rows.append(row)
            self.body.addWidget(row)

        for index, row in enumerate(self.rows):
            if index >= len(lanes):
                if row.isVisible():
                    row.setVisible(False)
                continue

            if not row.isVisible():
                row.setVisible(True)

            lane = lanes[index]
            lane = lane if isinstance(lane, dict) else {}
            self._render_side(
                row.ally_icon,
                row.ally_gold,
                lane.get("ally"),
            )
            row.role.setText(
                ROLE_SHORT_LABELS.get(str(lane.get("role", "")), "?")
            )

            if lane.get("paired"):
                self._set_delta(row.delta, int(lane.get("delta", 0) or 0))
            else:
                row.delta.setText("")

            self._render_side(
                row.enemy_icon,
                row.enemy_gold,
                lane.get("enemy"),
            )

    def _render_side(
        self,
        icon: QLabel,
        gold_label: QLabel,
        entry: dict | None,
    ) -> None:
        if not isinstance(entry, dict):
            self._set_champion_icon(icon, "")
            gold_label.setText("")
            return

        self._set_champion_icon(icon, str(entry.get("champion", "") or ""))
        gold_label.setText(format_gold(entry.get("gold", 0)))

    def _set_delta(self, label: QLabel, delta: int) -> None:
        if delta > 0:
            _set_property(label, "state", "ahead")
        elif delta < 0:
            _set_property(label, "state", "behind")
        else:
            _set_property(label, "state", "even")

        label.setText(format_delta(delta))


class _AlertRow(QFrame):
    """Una fila del panel de alertas: acento de bando, iconos y texto."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlayAlertRow")

        self.accent = QFrame()
        self.accent.setObjectName("overlayAccent")
        self.accent.setFixedSize(3, 18)

        self.slot_a = _icon_label(CHAMPION_ICON_SIZE)
        self.slot_a.setFixedSize(24, 24)

        self.slot_b = _icon_label(ITEM_ICON_SIZE)
        self.slot_b.setFixedSize(26, 22)

        self.text = QLabel("")
        self.text.setObjectName("overlayAlertText")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        layout.addWidget(self.accent)
        layout.addWidget(self.slot_a)
        layout.addWidget(self.slot_b)
        layout.addWidget(self.text, 1)


class _RecordingRow(QFrame):
    """Fila fija del panel de alertas: indica que la partida se está grabando."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("overlayRecordingRow")

        self.dot = QLabel("●")
        self.dot.setObjectName("overlayRecordingDot")
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.text = QLabel("")
        self.text.setObjectName("overlayRecordingText")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(8)
        layout.addWidget(self.dot)
        layout.addWidget(self.text, 1)

    def set_elapsed(self, elapsed_seconds: float) -> None:
        try:
            total = max(0, int(float(elapsed_seconds)))
        except (TypeError, ValueError):
            total = 0

        minutes, seconds = divmod(total, 60)
        self.text.setText(f"Grabando {minutes:02d}:{seconds:02d}")


class AlertsPanel(_FloatingPanel):
    """Panel 2: compras de objetos completos y objetivos a punto de aparecer."""

    def __init__(self, item_catalog: dict | None = None) -> None:
        super().__init__("alerts", item_catalog)

        self.feed: list[dict] = []
        self.rows: list[_AlertRow] = []
        self._visible_count = -1
        self.recording = False

        self.recording_row = _RecordingRow()
        self.recording_row.hide()
        self.body.addWidget(self.recording_row)

        self.body.setSpacing(4)

    def render(self, alerts: list[dict]) -> None:
        self.feed = alerts if isinstance(alerts, list) else []
        self.feed = self.feed[:MAX_ALERT_ROWS]

        if (
            self.recording
            and self.recording_row.parentWidget() is not None
            and not self.recording_row.isVisibleTo(self)
        ):
            self.recording_row.setVisible(True)
            self._visible_count = -1

        while len(self.rows) < MAX_ALERT_ROWS:
            row = _AlertRow()
            self.rows.append(row)
            self.body.addWidget(row)

        visible = 0

        for index, row in enumerate(self.rows):
            if index < len(self.feed):
                visible += 1
                if not row.isVisible():
                    row.setVisible(True)
                self._render_row(row, self.feed[index])
            elif row.isVisible():
                self._clear_row(row)
                row.setVisible(False)

        if visible != self._visible_count:
            self._visible_count = visible
            self.adjustSize()

    def _render_row(self, row: _AlertRow, alert: dict) -> None:
        alert = alert if isinstance(alert, dict) else {}
        kind = str(alert.get("kind", ""))

        if kind == "objective":
            row.accent.setProperty("kind", "objective")
            row.accent.setProperty("side", "")
            _repolish(row.accent)

            row.slot_a.setPixmap(QPixmap())
            row.slot_a.setText("")
            row.slot_a.setProperty("asset_key", "")
            row.slot_a.setObjectName("overlayIcon")
            row.slot_a.setProperty("state", "empty")
            _repolish(row.slot_a)

            row.slot_b.setPixmap(QPixmap())
            row.slot_b.setText("")
            row.slot_b.setProperty("asset_key", "")
            row.slot_b.setObjectName("overlayClock")
            row.slot_b.setProperty(
                "urgent", "true" if alert.get("urgent") else "false"
            )
            _repolish(row.slot_b)
            row.slot_b.setText(
                format_clock(alert.get("remaining", 0))
            )
            row.slot_b.setAlignment(Qt.AlignmentFlag.AlignCenter)

            _elide(
                row.text,
                str(alert.get("name", "Objetivo")),
                ALERT_TEXT_WIDTH,
            )
            row.text.setToolTip(
                f"{alert.get('name', '')} aparece en "
                f"{format_clock(alert.get('remaining', 0))}"
            )
        else:
            side = "ally" if str(alert.get("side", "")) == "ally" else "enemy"
            row.accent.setProperty("kind", "")
            row.accent.setProperty("side", side)
            _repolish(row.accent)

            row.slot_a.setObjectName("overlayIcon")
            row.slot_a.setProperty("state", "filled")
            _repolish(row.slot_a)
            self._set_champion_icon(
                row.slot_a,
                str(alert.get("champion", "") or ""),
                24,
            )

            row.slot_b.setObjectName("overlayIcon")
            row.slot_b.setProperty("state", "filled")
            row.slot_b.setProperty("urgent", "false")
            _repolish(row.slot_b)
            self._set_item_icon(row.slot_b, alert.get("item_id"), 22)

            _elide(
                row.text,
                str(alert.get("item_name", "") or "Objeto"),
                ALERT_TEXT_WIDTH,
            )
            row.text.setToolTip(str(alert.get("detail", "") or ""))

    def set_recording(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        """Muestra u oculta la fila «Grabando» del panel de alertas.

        Con los padres ocultos Qt ignora ``setVisible(True)`` en el hijo, así
        que si el panel aún no se ha mostrado la primera vez la fila quedará
        visible en cuanto se ordene el layout del panel.
        """
        active = bool(active)

        if active:
            self.recording_row.set_elapsed(elapsed_seconds)

        already = (
            self.recording == active
            and self.recording_row.isVisibleTo(self) == active
        )

        if already:
            return

        self.recording = active
        self.recording_row.setVisible(active)
        self._visible_count = -1
        self.adjustSize()

    def _clear_row(self, row: _AlertRow) -> None:
        row.slot_a.setPixmap(QPixmap())
        row.slot_a.setText("")
        row.slot_a.setProperty("asset_key", "")
        row.slot_b.setPixmap(QPixmap())
        row.slot_b.setText("")
        row.slot_b.setProperty("asset_key", "")
        row.text.setText("")
        row.text.setToolTip("")


class _ThreatRow(QWidget):
    """Una fila del panel de rivales: marcador, icono, nombre y oro."""

    def __init__(self) -> None:
        super().__init__()

        self.marker = QLabel("")
        self.marker.setObjectName("overlayMarker")
        self.marker.setFixedWidth(14)
        self.marker.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon = _icon_label(CHAMPION_ICON_SIZE)

        self.name = QLabel("")
        self.name.setObjectName("overlayChampionName")
        self.name.setFixedWidth(THREAT_NAME_WIDTH)

        self.gold = QLabel("")
        self.gold.setObjectName("overlayGold")
        self.gold.setProperty("side", "enemy")
        self.gold.setFixedWidth(GOLD_LABEL_WIDTH)
        self.gold.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.marker)
        layout.addWidget(self.icon)
        layout.addWidget(self.name)
        layout.addWidget(self.gold, 1)


class ThreatPanel(_FloatingPanel):
    """Panel 3: el rival más fuerte y el más débil (icono, nombre y oro)."""

    def __init__(self, item_catalog: dict | None = None) -> None:
        super().__init__("threat", item_catalog)

        self.strongest = _ThreatRow()
        self.strongest.marker.setText("▲")
        self.strongest.marker.setProperty("role", "strongest")
        self.body.addWidget(self.strongest)

        self.weakest = _ThreatRow()
        self.weakest.marker.setText("▼")
        self.weakest.marker.setProperty("role", "weakest")
        self.body.addWidget(self.weakest)

    def render(self, ranking: dict) -> None:
        ranking = ranking if isinstance(ranking, dict) else {}
        self._render_row(self.strongest, ranking.get("strongest"))
        self._render_row(self.weakest, ranking.get("weakest"))

        if self.strongest.isVisible() or self.weakest.isVisible():
            self.adjustSize()

    def _render_row(self, row: _ThreatRow, entry: dict | None) -> None:
        if not isinstance(entry, dict):
            row.setVisible(False)
            return

        if not row.isVisible():
            row.setVisible(True)

        champion = str(entry.get("champion", "") or "")
        self._set_champion_icon(row.icon, champion)
        _elide(row.name, champion or "?", THREAT_NAME_WIDTH)
        row.gold.setText(format_gold(entry.get("gold", 0)))
        row.setToolTip(
            f"{champion} · {format_gold(entry.get('gold', 0))} de oro"
        )


class OverlayWindow(QObject):
    """Gestor de los tres paneles flotantes y de su configuración.

    La ventana principal lo alimenta con ``update_snapshot`` cada segúndo y el
    gestor calcula oro, alertas y rivales destacados y muestra u oculta cada
    panel según sus ajustes. La configuración vive en el dict ``settings``
    compartido con la ventana principal y se guarda con ``settings_service``.
    """

    state_changed = Signal()

    SETTINGS_PANELS = "overlay_panels"
    SETTINGS_POSITIONS = "overlay_positions"
    SETTINGS_OPACITY = "overlay_opacity"
    SETTINGS_CLICK_THROUGH = "overlay_click_through"
    SETTINGS_ALERT_LEAD = "overlay_alert_lead"
    SETTINGS_SOUND_ENABLED = "overlay_sound_enabled"
    SETTINGS_SOUND_OBJECTIVE = "overlay_sound_objective"
    SETTINGS_SOUND_DRAGON = "overlay_sound_dragon"
    SETTINGS_SOUND_ENEMY_BUY = "overlay_sound_enemy_buy"
    SETTINGS_SOUND_VOLUME = "overlay_sound_volume"
    SETTINGS_TAB_ONLY = "overlay_tab_only"

    def __init__(
        self,
        item_catalog: dict,
        settings_service: SettingsService | None = None,
        settings: dict | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self.item_catalog = (
            item_catalog if isinstance(item_catalog, dict) else {}
        )
        self.settings_service = settings_service or SettingsService()
        self.settings = (
            settings
            if isinstance(settings, dict)
            else self.settings_service.load()
        )

        self.click_through = bool(
            self.settings.get(self.SETTINGS_CLICK_THROUGH, False)
        )
        self.opacity = self._bounded(
            int(self.settings.get(self.SETTINGS_OPACITY, DEFAULT_OPACITY)),
            MIN_OPACITY,
            MAX_OPACITY,
        )
        self.alert_lead_seconds = self._bounded(
            int(
                self.settings.get(
                    self.SETTINGS_ALERT_LEAD, DEFAULT_ALERT_LEAD
                )
            ),
            MIN_ALERT_LEAD,
            MAX_ALERT_LEAD,
        )
        self.alert_tracker = OverlayAlertTracker(
            self.item_catalog,
            lead_seconds=self.alert_lead_seconds,
        )
        self.sound_service = OverlaySoundService(
            enabled=bool(self.settings.get(self.SETTINGS_SOUND_ENABLED, True)),
            volume=float(
                self.settings.get(self.SETTINGS_SOUND_VOLUME, DEFAULT_VOLUME)
            ),
        )
        self.sound_service.set_kind_enabled(
            "objective",
            bool(self.settings.get(self.SETTINGS_SOUND_OBJECTIVE, True)),
        )
        self.sound_service.set_kind_enabled(
            "dragon",
            bool(self.settings.get(self.SETTINGS_SOUND_DRAGON, True)),
        )
        self.sound_service.set_kind_enabled(
            "enemy_buy",
            bool(self.settings.get(self.SETTINGS_SOUND_ENEMY_BUY, True)),
        )
        # Avisos ya sonados: cada alerta emite su pitido una sola vez.
        self._last_sound_alerts: set[str] = set()

        self.panels: dict[str, _FloatingPanel] = {
            "gold": GoldPanel(self.item_catalog),
            "alerts": AlertsPanel(self.item_catalog),
            "threat": ThreatPanel(self.item_catalog),
        }
        self.panels_enabled = dict(self._load_enabled())
        self.tab_only = dict(self._load_tab_only())
        self.tab_down = False
        self._in_game = False
        self._last_game_time = -1.0
        self._recording_snapshot: tuple[bool, float] | None = None

        for panel in self.panels.values():
            panel.moved_callback = self._panel_moved
            panel.set_click_through(self.click_through)
            panel.set_overlay_opacity(self.opacity)

        self._restore_positions()

    def connect_tab_hotkey(self, service) -> None:
        """Conecta el vigilante de TAB: emite state_changed en cada flanco."""
        if service is None:
            return

        service.tab_changed.connect(self._on_tab_changed)

        if service.is_tab_down:
            self._on_tab_changed(True)

    def _on_tab_changed(self, down: bool) -> None:
        down = bool(down)

        if down == self.tab_down:
            return

        self.tab_down = down
        self.refresh_visibility()
        self.state_changed.emit()

    @staticmethod
    def _bounded(value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(int(value), maximum))

    def _load_enabled(self) -> dict[str, bool]:
        stored = self.settings.get(self.SETTINGS_PANELS, {})

        if not isinstance(stored, dict):
            stored = {}

        return {
            key: bool(stored.get(key, True))
            for key in PANEL_KEYS
        }

    def _load_tab_only(self) -> dict[str, bool]:
        stored = self.settings.get(self.SETTINGS_TAB_ONLY, {})

        if not isinstance(stored, dict):
            stored = {}

        return {
            key: bool(stored.get(key, False))
            for key in PANEL_KEYS
        }

    def set_assets(self, assets) -> None:
        """Conecta el servicio de iconos de Data Dragon a los tres paneles."""
        for panel in self.panels.values():
            panel.set_assets(assets)

    @property
    def in_game(self) -> bool:
        return self._in_game

    def is_panel_enabled(self, key: str) -> bool:
        return bool(self.panels_enabled.get(key, False))

    def enabled_panels(self) -> dict[str, bool]:
        return {key: self.is_panel_enabled(key) for key in PANEL_KEYS}

    def any_enabled(self) -> bool:
        return any(self.is_panel_enabled(key) for key in PANEL_KEYS)

    def set_panel_enabled(self, key: str, enabled: bool) -> None:
        if key not in PANEL_KEYS:
            return

        self.panels_enabled[key] = bool(enabled)
        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

    def toggle_panel(self, key: str) -> bool:
        enabled = not self.is_panel_enabled(key)
        self.set_panel_enabled(key, enabled)

        return enabled

    def toggle_all(self) -> bool:
        """Activa los tres paneles si hay alguno apagado; si no, los apaga."""
        enabled = not self.any_enabled()

        for key in PANEL_KEYS:
            self.panels_enabled[key] = enabled

        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

        return enabled

    def set_click_through(self, enabled: bool) -> None:
        self.click_through = bool(enabled)

        for panel in self.panels.values():
            panel.set_click_through(self.click_through)

        self._persist()
        self.state_changed.emit()

    def set_overlay_opacity(self, percent: int) -> None:
        self.opacity = self._bounded(
            int(percent), MIN_OPACITY, MAX_OPACITY
        )

        for panel in self.panels.values():
            panel.set_overlay_opacity(self.opacity)

        self._persist()
        self.state_changed.emit()

    def set_alert_lead_seconds(self, seconds: int) -> None:
        self.alert_lead_seconds = self._bounded(
            int(seconds), MIN_ALERT_LEAD, MAX_ALERT_LEAD
        )
        self.alert_tracker.lead_seconds = self.alert_lead_seconds
        self._persist()
        self.state_changed.emit()

    def update_snapshot(self, snapshot: dict) -> None:
        """Recalcula los tres paneles con el snapshot de la partida."""
        if not isinstance(snapshot, dict) or not snapshot:
            self.clear()
            return

        game_time = float(snapshot.get("game_time", 0) or 0)

        if not self._in_game or game_time + 5 < self._last_game_time:
            self.alert_tracker.reset()
            self._last_sound_alerts.clear()

        self._in_game = True
        self._last_game_time = max(game_time, self._last_game_time)

        self.panels["gold"].render(
            build_gold_report(snapshot, self.item_catalog)
        )
        self.panels["threat"].render(
            build_rival_ranking(snapshot, self.item_catalog)
        )
        self.panels["alerts"].render(
            self.alert_tracker.update(snapshot)
        )

        if self._recording_snapshot is not None:
            self.panels["alerts"].set_recording(
                self._recording_snapshot[0], self._recording_snapshot[1]
            )

        self.refresh_visibility()

        # Cada aviso nuevo emite su pitido (si los sonidos están activados).
        self._emit_alert_sounds(game_time)

    def _emit_alert_sounds(self, game_time: float) -> None:
        """Suena cada aviso nuevo: objetivos, dragón y compras rivales."""
        if not self.sound_service.enabled:
            return

        alerts = self.alert_tracker.active_alerts(game_time)
        current_keys: set[str] = set()

        for alert in alerts:
            key = str(alert.get("key") or "")

            if not key:
                continue

            current_keys.add(key)

            if key in self._last_sound_alerts:
                continue

            self._last_sound_alerts.add(key)

            if alert.get("kind") == "objective":
                if key == "objective:dragon":
                    self.sound_service.play_dragon_spawn()
                else:
                    self.sound_service.play_objective_spawn()
            elif alert.get("kind") == "purchase":
                if alert.get("side") == "enemy":
                    self.sound_service.play_enemy_buy()

        # Los avisos que ya no están activos podrán volver a sonar si reaparecen.
        self._last_sound_alerts &= current_keys

    def set_sound_enabled(self, enabled: bool) -> None:
        """Activa o desactiva todos los sonidos del overlay."""
        self.sound_service.set_enabled(enabled)
        self._persist()
        self.state_changed.emit()

    def set_sound_kind_enabled(self, kind: str, enabled: bool) -> None:
        """Activa o desactiva un tipo concreto de sonido."""
        self.sound_service.set_kind_enabled(kind, enabled)
        self._persist()
        self.state_changed.emit()

    def set_sound_volume(self, volume: float) -> None:
        """Ajusta el volumen de los pitidos (0.0 a 1.0)."""
        self.sound_service.set_volume(volume)
        self._persist()
        self.state_changed.emit()

    def is_sound_enabled(self) -> bool:
        """True si los pitidos del overlay están activados."""
        return self.sound_service.enabled

    def set_recording(self, active: bool, elapsed_seconds: float = 0.0) -> None:
        """Guarda el estado de grabación para mostrarlo en el panel de alertas.

        La fila «Grabando» se pinta en el siguiente ``render`` (o en el
        siguiente ``update_snapshot``), porque los widgets solo deben tocarse
        desde el hilo que los usa.
        """
        try:
            elapsed = max(0.0, float(elapsed_seconds))
        except (TypeError, ValueError):
            elapsed = 0.0

        self._recording_snapshot = (bool(active), elapsed)
        self.panels["alerts"].set_recording(active, elapsed)

    def clear(self) -> None:
        """Sin partida no hay nada que mostrar: se ocultan los paneles."""
        self._in_game = False
        self._last_game_time = -1.0
        self._last_sound_alerts.clear()
        self.alert_tracker.reset()
        self._recording_snapshot = None
        self.panels["alerts"].set_recording(False)

        for panel in self.panels.values():
            if panel.isVisible():
                panel.hide()

    def is_tab_only(self, key: str) -> bool:
        """True si ese panel solo se muestra mientras TAB está pulsado."""
        return bool(self.tab_only.get(key, False))

    def set_tab_only(self, key: str, enabled: bool) -> None:
        """El panel con esta opción solo aparece mientras TAB está pulsado."""
        if key not in PANEL_KEYS:
            return

        self.tab_only[key] = bool(enabled)
        self._persist()
        self.refresh_visibility()
        self.state_changed.emit()

    def refresh_visibility(self) -> None:
        for key, panel in self.panels.items():
            visible = self.is_panel_enabled(key) and self._in_game

            if self.is_tab_only(key) and not self.tab_down:
                visible = False

            if panel.isVisible() == visible:
                continue

            panel.setVisible(visible)

            if visible:
                panel.raise_()

    def _panel_moved(self, panel: _FloatingPanel) -> None:
        positions = self.settings.get(self.SETTINGS_POSITIONS, {})

        if not isinstance(positions, dict):
            positions = {}

        positions[panel.key] = [int(panel.x()), int(panel.y())]
        self.settings[self.SETTINGS_POSITIONS] = positions
        self.settings_service.save(self.settings)

    def _persist(self) -> None:
        self.settings[self.SETTINGS_PANELS] = self.enabled_panels()
        self.settings[self.SETTINGS_TAB_ONLY] = {
            key: self.is_tab_only(key) for key in PANEL_KEYS
        }
        self.settings[self.SETTINGS_OPACITY] = self.opacity
        self.settings[self.SETTINGS_CLICK_THROUGH] = self.click_through
        self.settings[self.SETTINGS_ALERT_LEAD] = self.alert_lead_seconds
        self.settings[self.SETTINGS_SOUND_ENABLED] = bool(
            self.sound_service.enabled
        )
        self.settings[self.SETTINGS_SOUND_OBJECTIVE] = (
            self.sound_service.kind_enabled("objective")
        )
        self.settings[self.SETTINGS_SOUND_DRAGON] = (
            self.sound_service.kind_enabled("dragon")
        )
        self.settings[self.SETTINGS_SOUND_ENEMY_BUY] = (
            self.sound_service.kind_enabled("enemy_buy")
        )
        self.settings[self.SETTINGS_SOUND_VOLUME] = self.sound_service.volume
        self.settings[self.SETTINGS_POSITIONS] = {
            key: [int(panel.x()), int(panel.y())]
            for key, panel in self.panels.items()
        }
        self.settings_service.save(self.settings)

    def _restore_positions(self) -> None:
        positions = self.settings.get(self.SETTINGS_POSITIONS, {})

        if not isinstance(positions, dict):
            positions = {}

        missing = [key for key in PANEL_KEYS if not positions.get(key)]

        if missing:
            defaults = self._default_positions(missing)

            for key, point in defaults.items():
                positions[key] = [point[0], point[1]]

            self.settings[self.SETTINGS_POSITIONS] = positions

        for key, panel in self.panels.items():
            stored = positions.get(key)

            if (
                isinstance(stored, (list, tuple))
                and len(stored) == 2
                and all(isinstance(value, int) for value in stored)
            ):
                panel.move(stored[0], stored[1])

    def _default_positions(
        self, keys: list[str]
    ) -> dict[str, tuple[int, int]]:
        screen = QGuiApplication.primaryScreen()
        geometry = (
            screen.availableGeometry() if screen is not None else None
        )

        if geometry is None:
            return {key: (PANEL_MARGIN, PANEL_TOP_OFFSET) for key in keys}

        positions: dict[str, tuple[int, int]] = {}
        cursor = geometry.top() + PANEL_TOP_OFFSET

        for key in keys:
            panel = self.panels[key]
            panel.adjustSize()
            height = max(panel.sizeHint().height(), 60)
            positions[key] = (geometry.left() + PANEL_MARGIN, cursor)
            cursor += height + PANEL_GAP

        return positions

    def close(self) -> None:
        self._persist()

        for panel in self.panels.values():
            panel.close()

