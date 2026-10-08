"""Timeline virtualizada para eventos de la partida LIVE y postgame."""

from __future__ import annotations

from typing import Any, ClassVar

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from app.services.data_dragon_assets import DataDragonAssetService
from app.services.live_event_participation import classify_event_participation
from app.services.live_match_tracker import LiveMatchTracker
from app.ui.sistema_visual import PALETA
from app.ui.tema import aplicar_tema


class TimelineModel(QAbstractListModel):
    EventRole = Qt.ItemDataRole.UserRole + 1
    ACTIONS: ClassVar[dict[str, str]] = {
        "item_purchased": "Compró",
        "item_purchase": "Compró",
        "item_sold": "Vendió",
        "item_destroyed": "Retiró",
        "item_removed": "Retiró",
        "item_undo": "Deshizo una compra de",
    }

    def __init__(self, item_catalog: dict[str, Any], parent: Any = None) -> None:
        """Prepara nombres y eventos visibles desde el catálogo de objetos."""
        super().__init__(parent)
        catalog = item_catalog.get("items", item_catalog)
        self.names = {
            str(key): str(value.get("name_es") or value.get("name") or f"Objeto {key}")
            for key, value in catalog.items()
            if isinstance(value, dict)
        }
        self.rows: list[dict[str, str]] = []

    def set_events(
        self,
        events: list[dict[str, Any]],
        ally_key: str,
        enemy_key: str,
        players: dict[str, Any] | None = None,
    ) -> None:
        """Normaliza eventos conservando sus datos para iconos y accesibilidad."""
        rows: list[dict[str, Any]] = []
        kill_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        for event in events:
            event_type = str(event.get("type", ""))
            if event_type in {
                "kill_exact",
                "death_exact",
                "champion_kill",
                "assist_exact",
            }:
                killer_key = str(
                    event.get("killer_key")
                    or (event.get("player_key") if event_type == "kill_exact" else "")
                )
                victim_key = str(
                    event.get("victim_key")
                    or (event.get("player_key") if event_type == "death_exact" else "")
                )
                if killer_key and victim_key:
                    moment = str(event.get("time", event.get("time_label", "")))
                    identity = str(
                        event.get("event_id") or f"{killer_key}|{victim_key}|{moment}"
                    )
                    key = (identity, killer_key, victim_key)
                    row = kill_groups.get(key)
                    if row is None:
                        participation = classify_event_participation(
                            event, ally_key, enemy_key
                        )
                        left_role = participation.left
                        right_role = participation.right
                        direct = participation.shared
                        side = (
                            "direct"
                            if direct
                            else "left"
                            if left_role != "NONE"
                            else "right"
                            if right_role != "NONE"
                            else "neutral"
                        )
                        killer = players.get(killer_key, {}) if players else {}
                        victim = players.get(victim_key, {}) if players else {}
                        killer_name = str(
                            killer.get("champion_name")
                            or event.get("killer_name")
                            or killer_key
                        )
                        victim_name = str(
                            victim.get("champion_name")
                            or event.get("victim_name")
                            or victim_key
                        )
                        category = _participation_category(left_role, right_role)
                        left_player = players.get(ally_key or "", {}) if players else {}
                        right_player = (
                            players.get(enemy_key or "", {}) if players else {}
                        )
                        left_name = str(left_player.get("champion_name") or "")
                        right_name = str(right_player.get("champion_name") or "")
                        assistants = event.get("assister_keys") or []
                        assister_names = [
                            str(players.get(key, {}).get("champion_name") or key)
                            for key in assistants
                            if players and key in players
                        ]
                        left_text = _participation_text(
                            left_role, left_name, killer_name, victim_name
                        )
                        right_text = _participation_text(
                            right_role, right_name, killer_name, victim_name
                        )
                        text = (
                            left_text
                            if left_role != "NONE"
                            else right_text
                            if right_role != "NONE"
                            else str(event.get("label") or "Eliminación")
                        )
                        row = {
                            "timestamp": str(
                                event.get("time_label")
                                or LiveMatchTracker.format_time(event.get("time", 0))
                            ),
                            "text": text,
                            "side": side,
                            "category": category,
                            "item_id": "",
                            "champion": "",
                            "killer_champion": killer_name,
                            "victim_champion": victim_name,
                            "killer_key": killer_key,
                            "victim_key": victim_key,
                            "event_type": "champion_kill",
                            "actor_key": killer_key,
                            "killer_text": f"{killer_name} eliminó a {victim_name}",
                            "victim_text": f"{victim_name} murió",
                            "event_identity": identity,
                            "left_involvement": left_role,
                            "right_involvement": right_role,
                            "left_text": left_text,
                            "right_text": right_text,
                            "left_champion": left_name,
                            "right_champion": right_name,
                            "assister_names": assister_names,
                            "assist_data_complete": participation.participation_complete,
                        }
                        kill_groups[key] = row
                        rows.append(row)
                    continue
            item_id = str(event.get("item_id", ""))
            valid_item = item_id.isdigit() and int(item_id) > 0
            if (
                event_type in self.ACTIONS
                and not valid_item
                and event_type != "item_undo"
            ):
                continue
            if event_type == "item_undo" and not valid_item:
                text = "Deshizo una compra"
            else:
                action = self.ACTIONS.get(event_type)
                text = (
                    f"{action} {self.names.get(item_id, f'Objeto {item_id}')}"
                    if action and valid_item
                    else str(event.get("label") or "Evento")
                )
            player_key = event.get("player_key")
            actor_key = (
                str(event.get("victim_key") or player_key or "")
                if event_type == "death_exact"
                else str(player_key or "")
                if event_type == "assist_exact"
                else str(event.get("killer_key") or player_key or "")
            )
            is_global = (
                event_type == "objective"
                or event.get("scope") == "global"
                or event.get("global") is True
            )
            side = (
                "left"
                if actor_key == ally_key
                else "right"
                if actor_key == enemy_key
                else "center"
                if is_global
                else "neutral"
            )
            timestamp = str(
                event.get("time_label")
                or LiveMatchTracker.format_time(event.get("time", 0))
            )
            killer_key = str(event.get("killer_key") or actor_key)
            victim_key = str(event.get("victim_key") or "")
            actor = players.get(actor_key, {}) if players else {}
            killer = players.get(killer_key, {}) if players else {}
            victim = players.get(victim_key, {}) if players else {}
            champion = (
                str(event.get("champion_name") or actor.get("champion_name", ""))
                if isinstance(actor, dict)
                else ""
            )
            killer_champion = (
                str(killer.get("champion_name", "")) if isinstance(killer, dict) else ""
            )
            victim_champion = (
                str(victim.get("champion_name", "")) if isinstance(victim, dict) else ""
            )
            rows.append(
                {
                    "timestamp": timestamp,
                    "text": text,
                    "side": side,
                    "item_id": item_id
                    if valid_item and event_type in self.ACTIONS
                    else "",
                    "champion": champion,
                    "killer_champion": killer_champion,
                    "victim_champion": victim_champion,
                    "event_type": event_type,
                    "actor_key": actor_key,
                    "category": "LEFT_KILL"
                    if side == "left" and event_type in {"kill_exact", "champion_kill"}
                    else "LEFT_DEATH"
                    if side == "left" and event_type == "death_exact"
                    else "LEFT_ASSIST"
                    if side == "left" and event_type == "assist_exact"
                    else "RIGHT_KILL"
                    if side == "right" and event_type in {"kill_exact", "champion_kill"}
                    else "RIGHT_DEATH"
                    if side == "right" and event_type == "death_exact"
                    else "RIGHT_ASSIST"
                    if side == "right" and event_type == "assist_exact"
                    else "NEUTRAL",
                }
            )
        if rows == self.rows:
            return
        if len(rows) > len(self.rows) and rows[: len(self.rows)] == self.rows:
            first = len(self.rows)
            self.beginInsertRows(QModelIndex(), first, len(rows) - 1)
            self.rows.extend(rows[first:])
            self.endInsertRows()
        else:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        """Devuelve el número de eventos raíz del modelo."""
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Entrega los datos normalizados de una fila para vista y lectores."""
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == self.EventRole:
            return row
        if role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
            Qt.ItemDataRole.AccessibleTextRole,
        ):
            return f"{row['timestamp']} · {row['text']} ({row['side']})"
        return None


def _participation_category(left: str, right: str) -> str:
    """Asigna una categoría semántica sin depender de colores o equipos."""
    if left == "KILL" and right == "DEATH":
        return "DIRECT_LEFT_KILLS_RIGHT"
    if right == "KILL" and left == "DEATH":
        return "DIRECT_RIGHT_KILLS_LEFT"
    if left != "NONE" and right != "NONE":
        return "SHARED_ASSIST_PARTICIPATION"
    role = left if left != "NONE" else right
    side = "LEFT" if left != "NONE" else "RIGHT"
    return f"{side}_{role}"


def _participation_text(
    role: str,
    player_name: str,
    killer_name: str,
    victim_name: str,
) -> str:
    """Crea una frase breve para el papel concreto del jugador en la baja."""
    if role == "KILL":
        return f"{killer_name} eliminó a {victim_name}"
    if role == "DEATH":
        return f"{victim_name} murió"
    if role == "ASSIST":
        assistance = f"{player_name} asistió en la baja de {victim_name}"
        if killer_name and killer_name != player_name:
            return f"{assistance}; {killer_name} eliminó a {victim_name}"
        return assistance
    return ""


class TimelineDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 76

    def __init__(self, assets: DataDragonAssetService, parent: Any = None) -> None:
        """Configura el pintor con el servicio cacheado de iconos Data Dragon."""
        super().__init__(parent)
        self.assets = assets

    def sizeHint(self, option: Any, index: QModelIndex) -> QSize:
        """Reserva una altura estable para cada evento de la cronología."""
        return QSize(300, self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: Any, index: QModelIndex) -> None:
        """Dibuja eje, tiempo, icono y descripción con color semántico."""
        row = index.data(TimelineModel.EventRole)
        timestamp = row["timestamp"]
        text = row["text"]
        side = row["side"]
        painter.save()
        rect = option.rect
        background = QColor(
            PALETA["superficie"] if index.row() % 2 == 0 else PALETA["elevada"]
        )
        if option.state & QStyle.StateFlag.State_Selected:
            background = QColor(PALETA["teal"])
        elif option.state & QStyle.StateFlag.State_MouseOver:
            background = QColor(PALETA["borde"])
        painter.fillRect(rect, background)
        axis_x = rect.center().x()
        painter.setPen(QPen(QColor(PALETA["oro_oscuro"]), 2))
        painter.drawLine(axis_x, rect.top(), axis_x, rect.bottom())
        painter.setBrush(
            QColor(
                PALETA["teal"]
                if side == "left"
                else PALETA["desventaja"]
                if side == "right"
                else PALETA["oro_suave"]
            )
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(axis_x - 5, rect.center().y() - 5, 10, 10)
        painter.setPen(QColor(PALETA["oro_suave"]))
        if side == "direct":
            left_rect = QRect(
                rect.left() + 8,
                rect.top() + 4,
                max(1, axis_x - rect.left() - 68),
                rect.height() - 8,
            )
            right_rect = QRect(
                axis_x + 60,
                rect.top() + 4,
                max(1, rect.right() - axis_x - 68),
                rect.height() - 8,
            )
            left_kills = row["left_involvement"] == "KILL"
            marker_color = (
                PALETA["teal"]
                if left_kills
                else PALETA["desventaja"]
                if row["right_involvement"] == "KILL"
                else PALETA["oro_suave"]
            )
            left_name = row["left_champion"] or row["victim_champion"]
            right_name = row["right_champion"] or row["victim_champion"]
            left_text = row["left_text"]
            right_text = row["right_text"]
            left_icon = QRect(left_rect.right() - 31, rect.center().y() - 15, 28, 28)
            right_icon = QRect(right_rect.left(), rect.center().y() - 15, 28, 28)
            self._draw_champion_icon(painter, left_icon, left_name)
            self._draw_champion_icon(painter, right_icon, right_name)
            painter.setPen(QColor(marker_color))
            painter.drawLine(
                left_icon.right() + 3, rect.center().y(), axis_x - 7, rect.center().y()
            )
            painter.drawLine(
                axis_x + 7, rect.center().y(), right_icon.left() - 3, rect.center().y()
            )
            painter.drawText(
                left_rect.adjusted(0, 0, -35, 0),
                Qt.AlignmentFlag.AlignVCenter
                | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap,
                left_text,
            )
            painter.drawText(
                right_rect.adjusted(35, 0, 0, 0),
                Qt.AlignmentFlag.AlignVCenter
                | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap,
                right_text,
            )
            time_rect = QRect(axis_x - 30, rect.top(), 60, 20)
            text_rect = QRect()
            content_rect = QRect()
            icon_url = ""
            icon_key = ""
            painter.setBrush(QColor(marker_color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(axis_x - 7, rect.center().y() - 7, 14, 14)
        elif side == "left":
            time_rect = QRect(axis_x - 58, rect.top(), 54, rect.height())
            content_rect = QRect(
                rect.left() + 8,
                rect.top() + 6,
                max(1, axis_x - rect.left() - 72),
                rect.height() - 12,
            )
            icon_rect = QRect(content_rect.right() - 32, rect.center().y() - 15, 30, 30)
        elif side == "right":
            time_rect = QRect(axis_x + 4, rect.top(), 54, rect.height())
            content_rect = QRect(
                axis_x + 64,
                rect.top() + 6,
                max(1, rect.right() - axis_x - 70),
                rect.height() - 12,
            )
            icon_rect = QRect(content_rect.left(), rect.center().y() - 15, 30, 30)
        else:
            time_rect = QRect(axis_x - 28, rect.top(), 56, 20)
            content_rect = QRect(
                rect.left() + 10, rect.top() + 20, rect.width() - 20, rect.height() - 22
            )
            icon_rect = QRect(axis_x - 15, rect.center().y() - 15, 30, 30)
        painter.setPen(QColor(PALETA["oro_suave"]))
        painter.drawText(time_rect, Qt.AlignmentFlag.AlignCenter, timestamp)
        if row["item_id"]:
            icon_url = self.assets.item_url(int(row["item_id"]))
            icon_key = f"item:{row['item_id']}"
            content_rect = (
                content_rect.adjusted(0, 0, -36 if side == "left" else 36, 0)
                if side != "center"
                else content_rect
            )
        else:
            icon_url = ""
            icon_key = ""
        if (
            row["event_type"]
            in ("kill_exact", "death_exact", "champion_kill", "assist_exact")
            and side != "direct"
        ):
            is_death = (
                row["category"].endswith("DEATH") or row["event_type"] == "death_exact"
            )
            first_name = row["victim_champion"] if is_death else row["killer_champion"]
            second_name = row["killer_champion"] if is_death else row["victim_champion"]
            if side == "left":
                first_icon = QRect(
                    content_rect.right() - 84, rect.center().y() - 13, 26, 26
                )
                second_icon = QRect(
                    content_rect.right() - 28, rect.center().y() - 13, 26, 26
                )
                text_rect = content_rect.adjusted(0, 0, -88, 0)
                arrow_rect = QRect(
                    first_icon.right() + 2, rect.top(), 26, rect.height()
                )
            else:
                first_icon = QRect(content_rect.left(), rect.center().y() - 13, 26, 26)
                second_icon = QRect(
                    content_rect.left() + 56, rect.center().y() - 13, 26, 26
                )
                text_rect = content_rect.adjusted(86, 0, 0, 0)
                arrow_rect = QRect(
                    first_icon.right() + 2, rect.top(), 26, rect.height()
                )
            self._draw_champion_icon(painter, first_icon, first_name)
            self._draw_champion_icon(painter, second_icon, second_name)
            painter.setPen(QColor(PALETA["oro_suave"]))
            arrow = "←" if is_death else "→"
            painter.drawText(arrow_rect, Qt.AlignmentFlag.AlignCenter, arrow)
        else:
            text_rect = (
                content_rect.adjusted(0, 0, -36, 0)
                if row["item_id"] and side == "left"
                else content_rect.adjusted(36, 0, 0, 0)
                if row["item_id"] and side == "right"
                else content_rect
            )
            if icon_url:
                pixmap = self.assets.request_pixmap(icon_url, f"timeline:{icon_key}")
                if not pixmap.isNull():
                    painter.drawPixmap(icon_rect, pixmap)
        category = row["category"]
        color = QColor(
            PALETA["desventaja"]
            if category.endswith("DEATH")
            else PALETA["teal"]
            if category.endswith(("KILL", "ASSIST"))
            or category == "SHARED_ASSIST_PARTICIPATION"
            else PALETA["texto"]
        )
        painter.setPen(color)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag(
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                | int(Qt.TextFlag.TextWordWrap)
            ),
            text,
        )
        painter.restore()

    def _draw_champion_icon(
        self, painter: QPainter, rect: QRect, champion: str
    ) -> None:
        """Pinta un retrato de campeón si el catálogo puede resolverlo."""
        if not champion:
            return
        url = self.assets.champion_url(champion)
        pixmap = self.assets.request_pixmap(url, f"timeline:champion:{champion}")
        if not pixmap.isNull():
            painter.drawPixmap(rect, pixmap)


class TimelineView(QListView):
    def __init__(
        self,
        item_catalog: dict[str, Any],
        assets: DataDragonAssetService,
        parent: Any = None,
    ) -> None:
        """Crea una lista virtualizada que reutiliza la caché común de recursos."""
        super().__init__(parent)
        self.setObjectName("liveTimelineView")
        self.timeline_model = TimelineModel(item_catalog, self)
        self.setModel(self.timeline_model)
        self.setItemDelegate(TimelineDelegate(assets, self))
        assets.image_ready.connect(self._asset_loaded)
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setSpacing(0)
        aplicar_tema(self)

    @Slot(str, QPixmap)
    def _asset_loaded(self, key: str, pixmap: QPixmap) -> None:
        """Repinta eventos visibles cuando llega un icono solicitado."""
        self.viewport().update()

    def set_events(
        self,
        events: list[dict[str, Any]],
        ally_key: str,
        enemy_key: str,
        players: dict[str, Any] | None = None,
    ) -> None:
        """Actualiza las filas y conserva la posición de scroll del usuario."""
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        following = scrollbar.maximum() > 0 and position == scrollbar.maximum()
        self.timeline_model.set_events(events, ally_key, enemy_key, players)
        self.doItemsLayout()
        if following:
            self.scrollToBottom()
        else:
            scrollbar.setValue(position)
        self.viewport().update()

    def paintEvent(self, event: Any) -> None:
        """Muestra un estado vacío cuando el filtro no contiene eventos."""
        super().paintEvent(event)
        if not self.timeline_model.rowCount():
            painter = QPainter(self.viewport())
            painter.setPen(QColor(PALETA["secundario"]))
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Aún no hay eventos para este filtro.",
            )
