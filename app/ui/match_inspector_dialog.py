from __future__ import annotations

from datetime import datetime
from logging import root
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services.data_dragon_assets import DataDragonAssetService


class MatchInspectorDialog(QDialog):
    OBJECTIVES = (
        ("dragon", "Dragones", "🐉"),
        ("baron", "Barones", "🟣"),
        ("rift_herald", "Heraldos", "👁"),
        ("tower", "Torres", "🏰"),
        ("inhibitor", "Inhibidores", "💎"),
    )

    def __init__(
        self,
        match: dict[str, Any],
        item_catalog: dict[str, Any] | None = None,
        assets: DataDragonAssetService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.match = match
        self.item_catalog = item_catalog or {}
        self.assets = assets or DataDragonAssetService(self)
        self.setObjectName("matchInspectorDialog")
        self.setWindowTitle("Inspector de partida · SolraLoL")
        self.setModal(True)
        self.resize(1540, 1050)
        self.setMinimumSize(1220, 840)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 27, 30, 27)
        root.setSpacing(20)
        root.addWidget(self._create_header())

        scroll = QScrollArea()
        scroll.setObjectName("matchInspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("matchInspectorContent")
        teams = QHBoxLayout(content)
        teams.setContentsMargins(0, 0, 0, 0)
        teams.setSpacing(22)
        teams.addWidget(self._create_team_card("ALIADOS", self.match.get("allies", []), "ally"), 1)
        teams.addWidget(self._create_team_card("ENEMIGOS", self.match.get("enemies", []), "enemy"), 1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("Cerrar")
        close.setObjectName("secondaryButton")
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def _create_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("matchInspectorHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(20)
        player = self._find_player()
        champion = player.get("champion_name") or self.match.get("champion_name") or "Desconocido"
        layout.addWidget(self._champion_image(champion, 96))
        result = QLabel("VICTORIA" if self.match.get("win") else "DERROTA")
        result.setObjectName("inspectorResult")
        result.setProperty("result", "victory" if self.match.get("win") else "defeat")
        layout.addWidget(result)
        text = QVBoxLayout()
        title = QLabel(f"{champion} · {self._queue_name(self.match.get('queue_id'))}")
        title.setObjectName("inspectorTitle")
        text.addWidget(title)
        subtitle = QLabel(f"{self._format_date(self.match.get('game_creation'))} · {self._format_duration(self.match.get('game_duration'))}")
        subtitle.setObjectName("inspectorSubtitle")
        text.addWidget(subtitle)
        layout.addLayout(text, 1)
        kda = QLabel(f"{self.match.get('kills', 0)} / {self.match.get('deaths', 0)} / {self.match.get('assists', 0)}")
        kda.setObjectName("inspectorKda")
        layout.addWidget(kda)
        return header

    def _create_compact_objectives(
        self,
        values: dict[str, Any],
        state: str,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)

        for key, name, fallback in self.OBJECTIVES:
            cell = QHBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)

            icon = self._objective_icon(
                key,
                fallback,
                20,
            )
            cell.addWidget(icon)

            count = QLabel(
                str(values.get(key, 0))
            )
            count.setObjectName("compactObjectiveCount")
            count.setProperty("team", state)
            count.setToolTip(name)
            cell.addWidget(count)

            row.addLayout(cell)

        return row

    def _create_team_card(
        self,
        title: str,
        players: list[dict[str, Any]],
        state: str,
    ) -> QWidget:
        card = QFrame()
        card.setObjectName("matchTeamCard")
        card.setProperty("team", state)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(3, 0, 3, 0)
        header.setSpacing(8)

        heading = QLabel(title)
        heading.setObjectName("teamHeading")
        heading.setProperty("team", state)
        header.addWidget(heading)

        header.addStretch(1)

        objectives = self.match.get(
            "objectives",
            {},
        ).get(
            "allies" if state == "ally" else "enemies",
            {},
        )

        header.addLayout(
            self._create_compact_objectives(
                objectives,
                state,
            )
        )

        layout.addLayout(header)

        for player in players:
            layout.addWidget(
                self._create_player_row(player)
            )

        layout.addStretch(1)
        return card

    def _create_player_row(self, player: dict[str, Any]) -> QWidget:
        row = QFrame()
        row.setObjectName("matchPlayerRow")
        row.setProperty("player", "self" if player.get("is_player") else "other")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(6)
        champion = player.get("champion_name") or "Desconocido"
        layout.addWidget(self._champion_image(champion, 66))
        details = QVBoxLayout()
        details.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        position = QLabel(self._position_name(player.get("team_position", "")))
        position.setObjectName("playerPosition")
        top.addWidget(position)
        champion_label = QLabel(champion)
        champion_label.setObjectName("playerChampion")
        top.addWidget(champion_label)
        top.addStretch(1)
        name = player.get("riot_id_game_name") or "Desconocido"
        tag = player.get("riot_id_tag_line") or ""
        name_label = QLabel(f"{name}#{tag}" if tag else name)
        name_label.setObjectName("playerName")
        top.addWidget(name_label)
        details.addLayout(top)
        stats = QLabel(
            f"{player.get('kills', 0)} / {player.get('deaths', 0)} / {player.get('assists', 0)}"
            f"    ·    {player.get('cs', 0)} CS    ·    {player.get('gold_earned', 0):,} oro"
            f"    ·    Visión {player.get('vision_score', 0)}    ·    Nv. {player.get('champ_level', 0)}"
        )
        stats.setObjectName("playerStats")
        details.addWidget(stats)
        details.addWidget(self._items_widget(player.get("items", [])))
        layout.addLayout(details, 1)
        return row

    def _items_widget(self, items: list[Any]) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        caption = QLabel("Build")
        caption.setObjectName("itemsCaption")
        layout.addWidget(caption)
        for value in items:
            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue
            if item_id > 0:
                layout.addWidget(self._item_image(item_id))
        layout.addStretch(1)
        return widget

    def _champion_image(self, champion: str, size: int) -> QLabel:
        label = QLabel(champion[:3].upper())
        label.setObjectName("championPortrait")
        label.setFixedSize(size, size)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.assets.set_label_image(label, self.assets.champion_url(champion), f"champion:{champion}:{size}", size)
        return label

    def _item_image(self, item_id: int) -> QLabel:
        label = QLabel(str(item_id))
        label.setObjectName("itemIcon")
        label.setFixedSize(34, 34)

        self.assets.set_label_image(
            label,
            self.assets.item_url(item_id),
            f"item:{item_id}:34",
            34,
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        label.setToolTip(f"Objeto {item_id}")
        return label

    def _objective_icon(self, key: str, fallback: str, size: int) -> QLabel:
        label = QLabel(fallback)
        label.setObjectName("objectiveIcon")
        label.setFixedSize(size, size)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = self.item_catalog.get("objectives", {}).get(key, {})
        path = value.get("image_path", value.get("path", "")) if isinstance(value, dict) else ""
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        return label

    def _find_player(self) -> dict[str, Any]:
        for player in self.match.get("allies", []) + self.match.get("enemies", []):
            if player.get("is_player"):
                return player
        return {}

    @staticmethod
    def _format_duration(seconds: Any) -> str:
        total = max(0, int(seconds or 0))
        minutes, seconds = divmod(total, 60)
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _format_date(timestamp_ms: Any) -> str:
        try:
            value = datetime.fromtimestamp(int(timestamp_ms) / 1000)
        except (TypeError, ValueError, OSError):
            return "Fecha desconocida"
        return value.strftime("%d/%m/%Y %H:%M")

    @staticmethod
    def _queue_name(queue_id: Any) -> str:
        queues = {420: "Clasificatoria solo/dúo", 440: "Clasificatoria flexible", 450: "ARAM", 490: "Partida rápida", 700: "Clash", 1700: "Arena"}
        try:
            return queues.get(int(queue_id), "League of Legends")
        except (TypeError, ValueError):
            return "League of Legends"

    @staticmethod
    def _position_name(position: Any) -> str:
        positions = {"TOP": "TOP", "JUNGLE": "JGL", "MIDDLE": "MID", "BOTTOM": "ADC", "UTILITY": "SUP"}
        return positions.get(str(position).upper(), "—")
