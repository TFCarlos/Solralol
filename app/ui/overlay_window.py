from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFrame, QLabel, QMainWindow, QVBoxLayout, QWidget

from app.services.game_calculator import (
    get_inventory_value,
    get_kda,
    get_stat_chips,
    normalize_live_stats,
)


class OverlayWindow(QMainWindow):
    """Overlay compacto, movible y opcionalmente transparente a clics."""

    def __init__(self, item_catalog: dict) -> None:
        super().__init__()

        self.item_catalog = item_catalog
        self.click_through = False
        self.drag_position: QPoint | None = None

        self.setWindowTitle("Solralol Overlay")
        self.resize(430, 260)
        self.setMinimumSize(370, 210)

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.build_ui()
        self.apply_styles()

    def build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("overlayCentral")
        self.setCentralWidget(central)

        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(8, 8, 8, 8)

        self.overlay_card = QFrame()
        self.overlay_card.setObjectName("overlayCard")
        outer_layout.addWidget(self.overlay_card)

        layout = QVBoxLayout(self.overlay_card)
        layout.setContentsMargins(14, 11, 14, 12)
        layout.setSpacing(7)

        title = QLabel("SOLRALOL • OVERLAY")
        title.setObjectName("overlayTitle")
        layout.addWidget(title)

        self.game_label = QLabel("Esperando partida...")
        self.game_label.setObjectName("overlayGame")
        layout.addWidget(self.game_label)

        self.player_label = QLabel("Sin datos de jugador")
        self.player_label.setObjectName("overlayPlayer")
        self.player_label.setWordWrap(True)
        layout.addWidget(self.player_label)

        self.enemy_label = QLabel("Sin datos de enemigos")
        self.enemy_label.setObjectName("overlayEnemy")
        self.enemy_label.setWordWrap(True)
        layout.addWidget(self.enemy_label)

    def update_data(
        self,
        game_time: float,
        local_player: dict | None,
        enemies: list[dict],
        local_live_stats: dict | None,
    ) -> None:
        """Actualiza textos del overlay sin reconstruir la ventana."""
        minutes = int(game_time // 60)
        seconds = int(game_time % 60)

        self.game_label.setText(
            f"PARTIDA EN CURSO • {minutes:02d}:{seconds:02d}"
        )

        if local_player is None:
            self.player_label.setText(
                "No se identificó al jugador local."
            )
            self.enemy_label.setText("")
            return

        champion = local_player.get("championName", "Desconocido")
        level = int(local_player.get("level", 0))
        build_value = get_inventory_value(
            local_player,
            self.item_catalog,
        )

        stat_text = ""

        if local_live_stats is not None:
            stats = normalize_live_stats(local_live_stats)
            chips = get_stat_chips(stats, estimated=False)
            stat_text = " · ".join(chips[:4])

        self.player_label.setText(
            f"{champion} · NV {level} · "
            f"KDA {get_kda(local_player)} · "
            f"{build_value}g"
            f"\n{stat_text}"
        )

        enemy_text = []

        for enemy in enemies:
            enemy_champion = enemy.get(
                "championName",
                "Desconocido",
            )
            enemy_level = int(enemy.get("level", 0))
            enemy_build = get_inventory_value(
                enemy,
                self.item_catalog,
            )

            enemy_text.append(
                f"{enemy_champion} "
                f"NV {enemy_level} "
                f"{enemy_build}g"
            )

        self.enemy_label.setText(
            "Rivales: " + " | ".join(enemy_text)
        )

    def set_click_through(self, enabled: bool) -> None:
        """
        Al bloquear, los clics atraviesan el overlay y llegan a League.
        El panel de control sigue pudiendo desbloquearlo.
        """
        self.click_through = enabled
        was_visible = self.isVisible()

        self.hide()

        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        if enabled:
            flags |= Qt.WindowType.WindowTransparentForInput

        self.setWindowFlags(flags)

        if was_visible:
            self.show()
            self.raise_()

    def set_overlay_opacity(self, percent: int) -> None:
        """Aplica opacidad entre 30% y 100%."""
        bounded_percent = max(30, min(percent, 100))
        self.setWindowOpacity(bounded_percent / 100)

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
            new_position = (
                event.globalPosition().toPoint()
                - self.drag_position
            )
            self.move(new_position)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.drag_position = None
        event.accept()

    def apply_styles(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget#overlayCentral {
                background: transparent;
            }

            QFrame#overlayCard {
                background: #0b1220;
                border: 1px solid #34567f;
                border-radius: 14px;
            }

            QLabel {
                color: #e8f1fb;
                font-family: "Segoe UI";
                background: transparent;
            }

            QLabel#overlayTitle {
                color: #d6aa48;
                font-size: 14px;
                font-weight: 800;
                letter-spacing: 1px;
            }

            QLabel#overlayGame {
                color: #93c5fd;
                font-size: 12px;
                font-weight: 700;
                background: #111d30;
                border: 1px solid #29476a;
                border-radius: 7px;
                padding: 7px;
            }

            QLabel#overlayPlayer {
                color: #eef5ff;
                font-size: 13px;
                font-weight: 600;
            }

            QLabel#overlayEnemy {
                color: #b8c8da;
                font-size: 11px;
            }
        """)