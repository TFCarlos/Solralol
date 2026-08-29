from __future__ import annotations
from tkinter.font import names

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.services.game_calculator import (
    calculate_estimated_enemy_stats,
    calculate_item_stats,
    get_inventory_value,
    get_kda,
    get_rune_summary,
    get_stat_chips,
    normalize_live_stats,
)
from app.ui.inventory import create_item_slots
from data_dragon import get_champion_data, get_champion_icon_path


class ChampionCard(QFrame):
    """Tarjeta visual individual de un jugador."""

    def __init__(
        self,
        player: dict,
        is_local_player: bool,
        item_catalog: dict,
        version: str,
        game_time: float,
        local_live_stats: dict | None,
    ) -> None:
        super().__init__()

        self.player = player
        self.is_local_player = is_local_player
        self.item_catalog = item_catalog
        self.version = version
        self.game_time = game_time
        self.local_live_stats = local_live_stats
        self.team = str(
            player.get("team", "")
        ).upper()

        self.setObjectName(
            "playerCardMe"
            if is_local_player
            else "playerCard"
        )

        self.setMinimumHeight(300)
        self.setMaximumHeight(300)

        self.build_ui()

    def build_ui(self) -> None:
        champion_name = self.player.get(
            "championName",
            "Desconocido",
        )

        riot_id = (
            self.player.get("riotId")
            or self.player.get("summonerName")
            or "Desconocido"
        )

        level = int(
            self.player.get("level", 0)
        )

        scores = self.player.get(
            "scores",
            {},
        )

        cs = int(
            scores.get("creepScore", 0)
        )

        build_value = get_inventory_value(
            self.player,
            self.item_catalog,
        )

        cs_per_minute = cs / max(
            self.game_time / 60,
            0.01,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        layout.addLayout(
            self.create_header(
                champion_name,
                riot_id,
                level,
            )
        )

        match_info = QLabel(
            f"KDA {get_kda(self.player)} • "
            f"CS {cs} ({cs_per_minute:.1f}/min) • "
            f"Build {build_value}g"
        )
        match_info.setObjectName("statsLabel")
        match_info.setWordWrap(True)
        layout.addWidget(match_info)

        layout.addWidget(
            self.create_stat_label()
        )

        layout.addWidget(
            self.create_rune_label()
        )

        inventory_title = QLabel("INVENTARIO")
        inventory_title.setObjectName("itemsTitle")
        layout.addWidget(inventory_title)

        inventory = create_item_slots(
            player=self.player,
            item_catalog=self.item_catalog,
            version=self.version,
            size=30,
        )
        if inventory is not None:
            layout.addWidget(inventory)

        layout.addStretch(1)

    def create_header(
        self,
        champion_name: str,
        riot_id: str,
        level: int,
    ) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(8)

        champion_icon = QLabel()
        champion_icon.setObjectName("championIcon")
        champion_icon.setFixedSize(48, 48)
        champion_icon.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        icon_path = get_champion_icon_path(
            champion_name,
            self.version,
        )

        if icon_path is not None and icon_path.exists():
            pixmap = QPixmap(str(icon_path))

            if not pixmap.isNull():
                champion_icon.setPixmap(
                    pixmap.scaled(
                        46,
                        46,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        header.addWidget(champion_icon)

        names = QVBoxLayout()
        names.setSpacing(0)

        champion_label = QLabel(champion_name)
        champion_label.setObjectName("championName")
        champion_label.setWordWrap(False)
        names.addWidget(champion_label)

        player_label = QLabel(riot_id)
        player_label.setObjectName("playerId")
        player_label.setWordWrap(False)
        names.addWidget(player_label)

        header.addLayout(names, 1)
        header.addStretch(1)

        level_label = QLabel(f"NV {level}")
        level_label.setObjectName("levelLabel")
        level_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        level_label.setMinimumWidth(48)
        level_label.setMinimumHeight(28)
        header.addWidget(level_label)

        if self.is_local_player:
            local_label = QLabel("TÚ")
            local_label.setObjectName("meLabel")
            local_label.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            header.addWidget(local_label)

        return header

    def create_stat_label(self) -> QLabel:
        if (
            self.is_local_player
            and self.local_live_stats is not None
        ):
            stats = normalize_live_stats(
                self.local_live_stats
            )

            item_stats = calculate_item_stats(
                self.player,
                self.item_catalog,
            )

            stats["grievous_wounds"] = item_stats.get(
                "grievous_wounds",
                False,
            )
            estimated = False

        else:
            champion_name = self.player.get(
                "championName",
                "",
            )

            champion_data = get_champion_data(
                champion_name,
                self.version,
            )

            stats = calculate_estimated_enemy_stats(
                self.player,
                champion_data,
                self.item_catalog,
            )
            estimated = True

        chips = get_stat_chips(
            stats,
            estimated=estimated,
        )

        label = QLabel(" ".join(chips))
        label.setObjectName("itemStatsLabel")
        label.setWordWrap(True)
        return label

    def create_rune_label(self) -> QLabel:
        runes = self.player.get(
            "runes",
            {},
        )

        keystone = runes.get(
            "keystone",
            {},
        ).get(
            "displayName",
            "Runa desconocida",
        )

        primary = runes.get(
            "primaryRuneTree",
            {},
        ).get(
            "displayName",
            "Primaria",
        )

        secondary = runes.get(
            "secondaryRuneTree",
            {},
        ).get(
            "displayName",
            "Secundaria",
        )

        colors = {
            "precision": "#e6a23c",
            "domination": "#e05b63",
            "sorcery": "#55a9ff",
            "resolve": "#55c98b",
            "inspiration": "#8ed6d9",
        }

        primary_color = colors.get(
            primary.lower(),
            "#b696eb",
        )
        secondary_color = colors.get(
            secondary.lower(),
            "#b696eb",
        )

        label = QLabel()
        label.setObjectName("runeLabel")
        label.setTextFormat(
            Qt.TextFormat.RichText
        )
        label.setWordWrap(True)
        label.setText(
            "Runas: "
            f"<span style='color:{primary_color}'>"
            f"{keystone} · {primary}"
            "</span> / "
            f"<span style='color:{secondary_color}'>"
            f"{secondary}"
            "</span>"
        )
        return label

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        if self.team == "ORDER":
            glow = QColor(18, 92, 220, 165)
        else:
            glow = QColor(210, 35, 50, 165)

        gradient = QRadialGradient(
            self.rect().center(),
            max(self.width(), self.height()) * 0.92,
        )

        gradient.setColorAt(
            0.0,
            QColor(
                glow.red(),
                glow.green(),
                glow.blue(),
                18,
            ),
        )
        gradient.setColorAt(
            0.55,
            QColor(
                glow.red(),
                glow.green(),
                glow.blue(),
                75,
            ),
        )
        gradient.setColorAt(1.0, glow)

        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            self.rect().adjusted(1, 1, -1, -1),
            9,
            9,
        )

        super().paintEvent(event)
