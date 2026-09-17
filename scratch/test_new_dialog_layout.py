import sys
sys.path.insert(0, ".")
import json
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
)
from data_dragon import get_item_icon_path, get_spell_icon_path

class DamageBarWidget(QWidget):
    def __init__(self, ad_pct: float = 85.0, ap_pct: float = 10.0, true_pct: float = 5.0, parent=None):
        super().__init__(parent)
        self.ad_pct = ad_pct
        self.ap_pct = ap_pct
        self.true_pct = true_pct
        self.setFixedHeight(28)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        w = float(r.width())
        h = float(r.height())

        # Background track
        painter.setBrush(QColor(18, 24, 38))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(r, 6, 6)

        total = max(1.0, self.ad_pct + self.ap_pct + self.true_pct)
        ad_w = (self.ad_pct / total) * w
        ap_w = (self.ap_pct / total) * w
        true_w = w - ad_w - ap_w

        # Draw AD segment
        if ad_w > 0:
            painter.setBrush(QColor(225, 29, 72))  # Red/Orange AD
            painter.drawRoundedRect(QRectF(0, 0, ad_w, h), 6, 6)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(10, 0, ad_w, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{int(self.ad_pct)}% AD")

        # Draw AP segment
        if ap_w > 0:
            painter.setBrush(QColor(37, 99, 235))  # Blue AP
            painter.drawRoundedRect(QRectF(ad_w, 0, ap_w, h), 0, 0)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRectF(ad_w + 6, 0, ap_w, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{int(self.ap_pct)}% AP")

        # Draw True segment
        if true_w > 0:
            painter.setBrush(QColor(234, 179, 8))  # Gold True
            painter.drawRoundedRect(QRectF(ad_w + ap_w, 0, true_w, h), 0, 0)

print("DamageBarWidget defined successfully!")

