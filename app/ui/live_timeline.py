"""Timeline virtualizada: sin widgets por evento ni E/S durante el renderizado."""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListView, QStyle, QStyledItemDelegate

from app.services.live_match_tracker import LiveMatchTracker


class TimelineModel(QAbstractListModel):
    EventRole = Qt.ItemDataRole.UserRole + 1
    ACTIONS = {
        "item_purchased": "Compró",
        "item_sold": "Vendió",
        "item_destroyed": "Retiró",
        "item_undo": "Deshizo compra de",
    }

    def __init__(self, item_catalog, parent=None):
        super().__init__(parent)
        catalog = item_catalog.get("items", item_catalog)
        self.names = {
            str(key): str(value.get("name_es") or value.get("name") or f"Objeto {key}")
            for key, value in catalog.items() if isinstance(value, dict)
        }
        self.rows = []

    def set_events(self, events, ally_key, enemy_key):
        rows = []
        for event in events:
            action = self.ACTIONS.get(event.get("type"))
            if action:
                item_id = str(event.get("item_id", ""))
                text = f"{action} {self.names.get(item_id, f'Objeto {item_id}')}"
            else:
                text = str(event.get("label") or "Evento")
            player_key = event.get("player_key")
            side = "ally" if player_key == ally_key else "enemy" if player_key == enemy_key else "global"
            timestamp = str(event.get("time_label") or LiveMatchTracker.format_time(event.get("time", 0)))
            rows.append((timestamp, text, side))
        if rows == self.rows:
            return
        # Append-only updates preserve selection and scroll position.
        if len(rows) > len(self.rows) and rows[:len(self.rows)] == self.rows:
            first = len(self.rows)
            self.beginInsertRows(QModelIndex(), first, len(rows) - 1)
            self.rows.extend(rows[first:])
            self.endInsertRows()
        else:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == self.EventRole:
            return row
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.AccessibleTextRole):
            return f"{row[0]} · {row[1]}"
        return None


class TimelineDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 54

    def sizeHint(self, option, index):
        return QSize(300, self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index):
        timestamp, text, side = index.data(TimelineModel.EventRole)
        painter.save()
        rect = option.rect
        background = QColor("#0d1c30" if index.row() % 2 == 0 else "#102239")
        if option.state & QStyle.StateFlag.State_Selected:
            background = QColor("#254665")
        elif option.state & QStyle.StateFlag.State_MouseOver:
            background = QColor("#1a324d")
        painter.fillRect(rect, background)
        painter.setPen(QPen(QColor("#233b54")))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        center_x = rect.center().x()
        time_rect = QRect(center_x - 29, rect.top(), 58, rect.height())
        painter.setFont(option.font)
        painter.setPen(QColor("#e9c875"))
        painter.drawText(time_rect, Qt.AlignmentFlag.AlignCenter, timestamp)
        color = QColor("#57cafa" if side == "ally" else "#fa7e92" if side == "enemy" else "#c3b1fc")
        # Global events keep their timestamp; previously it was overwritten.
        if side == "global":
            time_rect = QRect(rect.left() + 8, rect.top(), 54, rect.height())
            painter.fillRect(rect, background)
            painter.setPen(QColor("#e9c875"))
            painter.drawText(time_rect, Qt.AlignmentFlag.AlignCenter, timestamp)
            text_rect = rect.adjusted(72, 4, -10, -4)
        elif side == "ally":
            text_rect = QRect(rect.left() + 10, rect.top() + 4,
                              max(1, center_x - rect.left() - 45), rect.height() - 8)
        else:
            text_rect = QRect(center_x + 39, rect.top() + 4,
                              max(1, rect.right() - center_x - 49), rect.height() - 8)
        painter.setPen(color)
        # Fixed geometry makes scrolling independent of the event count.
        # Full text remains available by tooltip and accessibility.
        fm = option.fontMetrics
        words = text.split()
        first = ""
        while words and fm.horizontalAdvance((first + " " + words[0]).strip()) <= text_rect.width():
            first = (first + " " + words.pop(0)).strip()
        if not first:
            first = words.pop(0) if words else ""
        lines = [fm.elidedText(first, Qt.TextElideMode.ElideRight, text_rect.width())]
        if words:
            lines.append(fm.elidedText(" ".join(words), Qt.TextElideMode.ElideRight, text_rect.width()))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "\n".join(lines))
        painter.restore()


class TimelineView(QListView):
    def __init__(self, item_catalog, parent=None):
        super().__init__(parent)
        self.setObjectName("liveTimelineView")
        self.timeline_model = TimelineModel(item_catalog, self)
        self.setModel(self.timeline_model)
        self.setItemDelegate(TimelineDelegate(self))
        self.setUniformItemSizes(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setStyleSheet(
            "QListView { background: #0d1c30; border: 1px solid #29435e; "
            "border-radius: 6px; outline: none; padding: 0; }"
        )

    def set_events(self, events, ally_key, enemy_key):
        scrollbar = self.verticalScrollBar()
        position = scrollbar.value()
        following = scrollbar.maximum() > 0 and position == scrollbar.maximum()
        self.timeline_model.set_events(events, ally_key, enemy_key)
        self.doItemsLayout()
        if following:
            self.scrollToBottom()
        else:
            scrollbar.setValue(position)
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.timeline_model.rowCount():
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter,
                             "Aún no hay eventos para este filtro.")