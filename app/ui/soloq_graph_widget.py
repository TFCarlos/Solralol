from __future__ import annotations

from typing import Any
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class SoloQGraphWidget(QWidget):
    """
    Gráfica interactiva personalizada para visualizar la tendencia de Winrate / ELO
    del jugador en SoloQ a lo largo del tiempo.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = "TENDENCIA DE SOLOQ"
        self.points: list[dict[str, Any]] = []
        self.hover_position: QPointF | None = None

        self.setObjectName("soloqGraphWidget")
        self.setMinimumHeight(180)
        self.setMouseTracking(True)

    def set_data(self, points: list[dict[str, Any]]) -> None:
        """
        Establece los puntos a dibujar.
        Cada punto contiene:
        - "time_label": str (ej. "Partida #1")
        - "winrate": float (ej. 60.0)
        - "champion": str (ej. "Ahri")
        - "win": bool (True/False)
        """
        self.points = points or []
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self.hover_position = event.position()
        self.update()

    def leaveEvent(self, event) -> None:
        self.hover_position = None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fondo del gráfico
        painter.fillRect(self.rect(), QColor(8, 19, 34, 0))  # transparente: la card ya tiene fondo

        normal_font = painter.font()
        normal_font.setBold(False)
        normal_font.setPointSize(9)
        painter.setFont(normal_font)

        # Área de trazado (sin reservar espacio para título interno)
        bounds = self.rect().adjusted(52, 10, -15, -25)

        if not self.points or len(self.points) < 2:
            painter.setPen(QColor(147, 170, 202))
            painter.drawText(
                bounds,
                Qt.AlignmentFlag.AlignCenter,
                "Sin suficientes partidas para mostrar evolución",
            )
            return

        # Calcular rangos
        has_elo = any("elo" in p for p in self.points)
        if has_elo:
            values = [float(p.get("elo", 1200.0)) for p in self.points]
            min_val = min(values) - 25.0
            max_val = max(values) + 25.0
        else:
            values = [float(p.get("winrate", 50.0)) for p in self.points]
            min_val = max(0.0, min(values) - 10.0)
            max_val = min(100.0, max(values) + 10.0)

        if max_val <= min_val:
            max_val = min_val + 50.0

        # 1. Rejilla y etiquetas Y (una sola vez por línea)
        grid_pen = QPen(QColor(93, 126, 170, 60))
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)

        for step in range(4):
            ratio = step / 3.0
            y = int(bounds.bottom() - bounds.height() * ratio)
            painter.drawLine(bounds.left(), y, bounds.right(), y)

            v = min_val + (max_val - min_val) * ratio
            painter.setPen(QColor(135, 159, 194))
            if has_elo:
                label_text = self.format_elo_short(v)
            else:
                label_text = f"{int(round(v))}%"
            painter.drawText(4, y + 4, label_text)
            painter.setPen(grid_pen)

        # 2. Mapear puntos a coordenadas de pantalla
        n = len(self.points)
        mapped_points: list[tuple[QPointF, dict[str, Any]]] = []

        for i, pt in enumerate(self.points):
            x_ratio = i / (n - 1) if n > 1 else 0.5
            y_ratio = (pt.get("winrate", 50.0) - min_val) / (max_val - min_val)
            val = float(pt.get("elo", 1200.0)) if has_elo else float(pt.get("winrate", 50.0))
            y_ratio = (val - min_val) / (max_val - min_val)

            x = bounds.left() + bounds.width() * x_ratio
            y = bounds.bottom() - bounds.height() * y_ratio
            mapped_points.append((QPointF(x, y), pt))

        # 3. Dibujar área con degradado bajo la línea
        path = QPainterPath()
        path.moveTo(mapped_points[0][0])
        for pt_coords, _ in mapped_points[1:]:
            path.lineTo(pt_coords)

        fill_path = QPainterPath(path)
        fill_path.lineTo(mapped_points[-1][0].x(), bounds.bottom())
        fill_path.lineTo(mapped_points[0][0].x(), bounds.bottom())
        fill_path.closeSubpath()

        gradient = QLinearGradient(
            0, bounds.top(), 0, bounds.bottom()
        )
        gradient.setColorAt(0, QColor(217, 174, 79, 70))
        gradient.setColorAt(1, QColor(58, 188, 245, 5))
        painter.fillPath(fill_path, gradient)

        # 4. Dibujar línea principal
        line_pen = QPen(QColor(217, 174, 79), 2)
        painter.setPen(line_pen)
        painter.drawPath(path)

        # 5. Dibujar puntos de partidas
        for pt_coords, pt_info in mapped_points:
            is_win = bool(pt_info.get("win", False))
            color = QColor(58, 188, 245) if is_win else QColor(244, 87, 108)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(pt_coords, 4, 4)

        # 6. Tooltip al pasar el ratón
        if self.hover_position and bounds.contains(self.hover_position.toPoint()):
            hx = self.hover_position.x()
            # Encontrar el punto mapeado más cercano en X
            closest = min(
                mapped_points,
                key=lambda item: abs(item[0].x() - hx),
            )
            c_pos, c_info = closest

            # Línea vertical indicadora
            pen = QPen(QColor(237, 209, 117, 180))
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(c_pos.x()), bounds.top(), int(c_pos.x()), bounds.bottom())

            # Dibujar caja de tooltip
            win_str = "VICTORIA" if c_info.get("win") else "DERROTA"
            elo_val = int(c_info.get("elo", 0))
            elo_lbl = str(c_info.get("elo_label") or f"{elo_val} LP")
            val_line = (
                f"Rango: {elo_lbl}"
                if has_elo
                else f"Winrate: {c_info.get('winrate', 0)}%"
            )
            lines = [
                f"{c_info.get('champion', 'Campeón')} ({win_str})",
                f"Winrate: {c_info.get('winrate', 0)}%",
                val_line,
                f"{c_info.get('time_label', '')}",
            ]

            tw = max(painter.fontMetrics().horizontalAdvance(l) for l in lines) + 16
            th = len(lines) * 16 + 10
            tx = min(int(c_pos.x()) + 8, bounds.right() - tw)
            ty = bounds.top() + 10

            painter.fillRect(tx, ty, tw, th, QColor(5, 12, 24, 240))
            painter.setPen(QColor(217, 174, 79))
            painter.drawRect(tx, ty, tw, th)

            painter.setPen(QColor(235, 242, 252))
            for index, l in enumerate(lines):
                painter.drawText(tx + 8, ty + 16 + index * 16, l)

    @staticmethod
    def format_elo_short(elo_val: float) -> str:
        elo = max(0, int(round(elo_val)))
        if elo >= 2800:
            return f"{elo - 2800} LP"
        tier_names = [
            ("Hierro", 0),
            ("Bronce", 400),
            ("Plata", 800),
            ("Oro", 1200),
            ("Platino", 1600),
            ("Esmeralda", 2000),
            ("Diamante", 2400),
        ]
        tier_str = "Oro"
        tier_base = 1200
        for name, base in tier_names:
            if elo >= base:
                tier_str = name
                tier_base = base
        rem = elo - tier_base
        div_idx = min(3, max(0, int(rem // 100)))
        divs = ["IV", "III", "II", "I"]
        return f"{tier_str[:3]} {divs[div_idx]}"

