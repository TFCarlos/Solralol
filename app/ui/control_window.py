from __future__ import annotations

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from app.services.live_data_worker import LiveDataWorker

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtGui import (
    QColor,
    QPainter,
    QRadialGradient,
)

from app.services.game_service import GameService
from app.ui.champion_card import ChampionCard
from app.ui.overlay_window import OverlayWindow
from app.ui.styles import CONTROL_WINDOW_STYLE

class TeamBackground(QWidget):
    def __init__(
        self,
        team: str,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.team = team
        self.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground,
            True,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        if self.team == "blue":
            edge_color = QColor(
                15,
                86,
                210,
                155,
            )
        else:
            edge_color = QColor(
                205,
                30,
                45,
                155,
            )

        center = self.rect().center()

        gradient = QRadialGradient(
            center,
            max(
                self.width(),
                self.height(),
            ) * 0.8,
        )

        gradient.setColorAt(
            0.0,
            QColor(0, 0, 0, 0),
        )

        gradient.setColorAt(
            0.45,
            QColor(
                edge_color.red(),
                edge_color.green(),
                edge_color.blue(),
                30,
            ),
        )

        gradient.setColorAt(
            1.0,
            edge_color,
        )

        painter.fillRect(
            self.rect(),
            gradient,
        )

class SolralolWindow(QMainWindow):
    snapshot_requested = Signal()
    """Panel principal de Solralol y controlador del overlay."""

    def __init__(self, version: str, item_catalog: dict) -> None:
        super().__init__()

        self.cards_built = False

        self.version = version
        self.item_catalog = item_catalog

        self.overlay = OverlayWindow(item_catalog)

        self.is_refreshing = False
        self.was_in_game = False
        self.panel_refresh_every_seconds = 10
        self.panel_refresh_counter = 0

        self.setWindowTitle("Solralol - Panel de control")
        self.resize(1080, 800)
        self.setMinimumSize(600, 500)

        self.build_ui()
        self.setStyleSheet(CONTROL_WINDOW_STYLE)

        self.setup_live_data_worker()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.request_snapshot)
        self.refresh_timer.start(1000)

    def get_player_role(
        self,
        player: dict,
    ) -> str:
        position = str(
            player.get("position", "")
        ).upper()

        aliases = {
            "MID": "MIDDLE",
            "JUNG": "JUNGLE",
            "SUP": "UTILITY",
            "SUPPORT": "UTILITY",
            "ADC": "BOTTOM",
            "APC": "BOTTOM",
        }

        position = aliases.get(position, position)

        if position in {
            "TOP",
            "JUNGLE",
            "MIDDLE",
            "BOTTOM",
            "UTILITY",
        }:
            return position

        spells = player.get(
            "summonerSpells",
            {},
        )

        spell_one = str(
            spells.get(
                "summonerSpellOne",
                {},
            ).get(
                "displayName",
                "",
            )
        ).lower()

        spell_two = str(
            spells.get(
                "summonerSpellTwo",
                {},
            ).get(
                "displayName",
                "",
            )
        ).lower()

        if "smite" in spell_one or "smite" in spell_two:
            return "JUNGLE"

        return "UNKNOWN"


    def sort_players_by_role(
        self,
        players: list[dict],
    ) -> list[dict]:
        role_order = {
            "TOP": 0,
            "JUNGLE": 1,
            "MIDDLE": 2,
            "BOTTOM": 3,
            "UTILITY": 4,
            "UNKNOWN": 99,
        }

        return sorted(
            players,
            key=lambda player: (
                role_order.get(
                    self.get_player_role(player),
                    99,
                ),
                str(
                    player.get(
                        "championName",
                        "",
                    )
                ),
            ),
        )
    
    def setup_live_data_worker(self) -> None:
        """Crea un hilo dedicado a consultar la API local de League."""
        self.worker_thread = QThread(self)
        self.live_data_worker = LiveDataWorker()

        self.live_data_worker.moveToThread(self.worker_thread)

        self.snapshot_requested.connect(
            self.live_data_worker.read_snapshot
        )

        self.live_data_worker.snapshot_ready.connect(
            self.receive_snapshot
        )

        self.live_data_worker.read_failed.connect(
            self.show_read_error
        )

        self.worker_thread.start()

    def request_snapshot(self) -> None:
        """Pide al worker un snapshot sin bloquear la UI."""
        if not self.is_refreshing:
            self.is_refreshing = True
            self.snapshot_requested.emit()


    def receive_snapshot(self, snapshot: dict | None) -> None:
        try:
            if snapshot is None:
                print("[DEBUG] snapshot = None")
                self.show_no_game_state()
            else:
                print("[DEBUG] snapshot recibido:", snapshot)
                self.show_game_state(snapshot)
        finally:
            self.is_refreshing = False

    def show_read_error(self, message: str) -> None:
        print("[DEBUG] error de lectura:", message)
        self.status_label.setText(f"Error de lectura: {message}")
        self.is_refreshing = False

    def build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(14, 14, 14, 14)
        self.main_layout.setSpacing(10)

        self.main_layout.addLayout(self.create_header())
        self.main_layout.addWidget(self.create_overlay_controls())
        self.main_layout.addWidget(self.create_status_label())
        self.main_layout.addWidget(self.create_cards_area())

    def create_header(self) -> QHBoxLayout:
        header = QHBoxLayout()

        title = QLabel("SOLRALOL")
        title.setObjectName("title")
        header.addWidget(title)

        subtitle = QLabel("Panel de control")
        subtitle.setObjectName("subtitle")
        header.addWidget(subtitle)

        header.addStretch()

        close_button = QPushButton("×")
        close_button.setObjectName("closeButton")
        close_button.setToolTip("Cerrar Solralol")
        close_button.clicked.connect(self.close)
        header.addWidget(close_button)

        return header

    def create_overlay_controls(self) -> QFrame:
        controls = QFrame()
        controls.setObjectName("controlsFrame")

        layout = QHBoxLayout(controls)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(8)

        label = QLabel("CONTROL DEL OVERLAY")
        label.setObjectName("controlsTitle")
        layout.addWidget(label)

        layout.addStretch()

        self.overlay_visibility_button = QPushButton("Mostrar overlay")
        self.overlay_visibility_button.setObjectName("controlButton")
        self.overlay_visibility_button.clicked.connect(
            self.toggle_overlay_visibility
        )
        layout.addWidget(self.overlay_visibility_button)

        self.overlay_lock_button = QPushButton("Bloquear clics: NO")
        self.overlay_lock_button.setObjectName("controlButton")
        self.overlay_lock_button.clicked.connect(
            self.toggle_overlay_click_through
        )
        layout.addWidget(self.overlay_lock_button)

        opacity_label = QLabel("Opacidad")
        opacity_label.setObjectName("opacityLabel")
        layout.addWidget(opacity_label)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("opacitySlider")
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(92)
        self.opacity_slider.setFixedWidth(110)
        self.opacity_slider.valueChanged.connect(
            self.change_overlay_opacity
        )
        layout.addWidget(self.opacity_slider)

        self.opacity_value_label = QLabel("92%")
        self.opacity_value_label.setObjectName("opacityValue")
        self.opacity_value_label.setFixedWidth(35)
        layout.addWidget(self.opacity_value_label)

        return controls

    def create_status_label(self) -> QLabel:
        self.status_label = QLabel(
            "Esperando una partida de League of Legends..."
        )
        self.status_label.setObjectName("statusLabel")
        return self.status_label

    def create_cards_area(self) -> QScrollArea:
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setObjectName("scrollArea")

        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(0)

        self.scroll_area.setWidget(self.cards_widget)
        return self.scroll_area

    def refresh_game_data(self) -> None:
        """Compatibilidad: el temporizador usa ahora request_snapshot."""
        self.request_snapshot()

    def show_no_game_state(self) -> None:
        self.status_label.setText(
            "Esperando una partida de League of Legends..."
        )

        self.overlay.game_label.setText(
            "Esperando partida..."
        )

        self.overlay.player_label.setText(
            "Sin datos de jugador"
        )

        self.overlay.enemy_label.setText("")

        if self.was_in_game:
            self.clear_cards()

        self.was_in_game = False
        self.cards_built = False
        self.panel_refresh_counter = 0

    def show_game_state(self, snapshot: dict) -> None:
        game_time = snapshot["game_time"]

        print("[DEBUG UI] show_game_state llamado")
        print("[DEBUG UI] champion_id:", snapshot.get("champion_id"))
        print(
            "[DEBUG UI] all_players count:",
            len(snapshot.get("all_players", [])),
        )
        print(
            "[DEBUG UI] enemies count:",
            len(snapshot.get("enemies", [])),
        )

        self.was_in_game = True

        minutes = int(game_time // 60)
        seconds = int(game_time % 60)

        self.status_label.setText(
            f"PARTIDA EN CURSO • {minutes:02d}:{seconds:02d} • "
            f"Panel: {self.panel_refresh_every_seconds} s"
        )

        self.overlay.update_data(
            game_time,
            snapshot["local_player"],
            snapshot["enemies"],
            snapshot["local_live_stats"],
        )

        if not self.cards_built:
            self.cards_built = True
            self.rebuild_cards(snapshot)
            return

        self.panel_refresh_counter += 1

        if self.panel_refresh_counter < self.panel_refresh_every_seconds:
            return

        self.panel_refresh_counter = 0
        self.rebuild_cards(snapshot)

    def add_team_grid(
        self,
        team_title: str,
        players: list[dict],
        snapshot: dict,
    ) -> None:
        grid_container = TeamBackground(
            "blue"
            if "ORDER" in team_title
            else "red"
        )

        grid_container.setObjectName(
            "blueTeamGrid"
            if "ORDER" in team_title
            else "redTeamGrid"
        )

        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        for column in range(5):
            grid.setColumnStretch(column, 1)

        for index, player in enumerate(players[:5]):
            local_player = snapshot.get(
                "local_player",
                {},
            )

            is_local = (
                player.get("riotId")
                == local_player.get("riotId")
            )

            card = ChampionCard(
                player=player,
                is_local_player=is_local,
                item_catalog=self.item_catalog,
                version=self.version,
                game_time=snapshot["game_time"],
                local_live_stats=(
                    snapshot.get(
                        "local_live_stats",
                        {},
                    )
                    if is_local
                    else None
                ),
            )
            shadow = QGraphicsDropShadowEffect(card)
            shadow.setBlurRadius(12)
            shadow.setOffset(2, 3)
            shadow.setColor(QColor(0, 0, 0, 190))

            card.setGraphicsEffect(shadow)

            grid.addWidget(card, 0, index)

        self.cards_layout.addWidget(grid_container)

    def paint_team_background(
        self,
        event,
    ) -> None:
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        is_blue = (
            self.objectName()
            == "blueTeamGrid"
        )

        color = (
            QColor(12, 76, 180, 150)
            if is_blue
            else QColor(180, 22, 32, 150)
        )

        gradient = QRadialGradient(
            self.rect().center(),
            max(
                self.width(),
                self.height(),
            ) * 0.75,
        )

        gradient.setColorAt(
            0.0,
            QColor(0, 0, 0, 0),
        )

        gradient.setColorAt(
            0.55,
            QColor(
                color.red(),
                color.green(),
                color.blue(),
                55,
            ),
        )

        gradient.setColorAt(
            1.0,
            color,
        )

        painter.fillRect(
            self.rect(),
            gradient,
        )

    def rebuild_cards(
        self,
        snapshot: dict,
    ) -> None:
        self.clear_cards()

        all_players = snapshot.get(
            "all_players",
            [],
        )

        order = [
            player
            for player in all_players
            if player.get("team") == "ORDER"
        ]

        chaos = [
            player
            for player in all_players
            if player.get("team") == "CHAOS"
        ]

        order = self.sort_players_by_role(order)
        chaos = self.sort_players_by_role(chaos)

        self.add_team_grid(
            "EQUIPO AZUL (ORDER)",
            order,
            snapshot,
        )

        self.add_team_grid(
            "EQUIPO ROJO (CHAOS)",
            chaos,
            snapshot,
        )

    def get_grid_columns(self) -> int:
        return 5

    def clear_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

    def toggle_overlay_visibility(self) -> None:
        if self.overlay.isVisible():
            self.overlay.hide()
            self.overlay_visibility_button.setText("Mostrar overlay")
        else:
            self.overlay.show()
            self.overlay.raise_()
            self.overlay_visibility_button.setText("Ocultar overlay")

    def toggle_overlay_click_through(self) -> None:
        enabled = not self.overlay.click_through
        self.overlay.set_click_through(enabled)

        self.overlay_lock_button.setText(
            "Bloquear clics: SÍ"
            if enabled
            else "Bloquear clics: NO"
        )

    def change_overlay_opacity(self, percent: int) -> None:
        self.overlay.set_overlay_opacity(percent)
        self.opacity_value_label.setText(f"{percent}%")

    def resizeEvent(self, event) -> None:
        """
        No reconstruimos tarjetas al redimensionar.

        Evita recursión y freezeos. El grid se actualizará en el próximo
        refresco normal del panel.
        """
        super().resizeEvent(event)

def closeEvent(self, event) -> None:
    self.refresh_timer.stop()

    try:
        self.snapshot_requested.disconnect(
            self.live_data_worker.read_snapshot
        )
    except (TypeError, RuntimeError):
        pass

    self.overlay.close()

    if self.worker_thread.isRunning():
        self.worker_thread.quit()

        if not self.worker_thread.wait(5000):
            self.worker_thread.terminate()
            self.worker_thread.wait(2000)

    event.accept()