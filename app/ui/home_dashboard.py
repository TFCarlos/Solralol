from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.services.home_history_service import normalizar_partidas_unicas
from app.services.resumen_rendimiento_historial import (
    etiqueta_puntuacion,
    puntuacion_historial_vigente,
)
from app.ui.sistema_visual import PALETA
from app.ui.superficies_analisis import IconoRedondeado
from app.ui.tema import aplicar_apariencia
from data_dragon import get_champion_icon_path, get_item_icon_path

_HOME_CHAMPION_PIXMAPS: dict[tuple[str, int], QPixmap] = {}


def _local_champion_names() -> dict[str, str]:
    """Carga nombres de campeón desde los metadatos instalados localmente."""
    import json

    from _paths import DATA_DIR

    names: dict[str, str] = {}
    for path in (DATA_DIR / "champion_metadata").glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records = payload.get("data", {}) if isinstance(payload, dict) else {}
        for champion in records.values() if isinstance(records, dict) else []:
            if isinstance(champion, dict) and champion.get("key") is not None:
                names[str(champion["key"])] = str(champion.get("name") or "")
    return names


class RelojActividad(QWidget):
    """Dibuja las 24 horas en un anillo con intensidad según las partidas."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inicializa el reloj circular sin datos de actividad.

        Parámetros: widget padre opcional.
        Retorno: None; reserva una banda compacta para el reloj.
        """
        super().__init__(parent)
        self.setObjectName("homeDashboard")
        self.conteos: dict[int, int] = {}
        self.hora_pico: int | None = None
        self.setMinimumHeight(118)
        self.setMaximumHeight(122)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, conteos: dict[int, int], hora_pico: int | None) -> None:
        """Actualiza el volumen por hora y repinta el reloj."""
        self.conteos = conteos
        self.hora_pico = hora_pico
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Pinta segmentos horarios y la hora de mayor actividad.

        Parámetros: evento de pintura de Qt.
        Retorno: None; representa la intensidad horaria disponible.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) * 0.30
        maximum = max(self.conteos.values(), default=0)
        for hour in range(24):
            angle = math.radians(hour * 15 - 90)
            intensity = self.conteos.get(hour, 0) / maximum if maximum else 0
            length = 6 + 16 * intensity
            color = PALETA["oro"] if intensity else PALETA["borde_sutil"]
            painter.setPen(QPen(QColor(color), 3.5 if intensity else 2.0))
            painter.drawLine(
                int(center_x + math.cos(angle) * radius),
                int(center_y + math.sin(angle) * radius),
                int(center_x + math.cos(angle) * (radius + length)),
                int(center_y + math.sin(angle) * (radius + length)),
            )
        painter.setPen(QColor(PALETA["oro_suave"]))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.hora_pico:02d}:00\nTU HORA"
            if self.hora_pico is not None
            else "24 h\nACTIVIDAD",
        )


class GraficoProgresionClasificatoria(QWidget):
    """Dibuja la evolución de rango de las partidas clasificatorias recientes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inicializa el gráfico sin muestra clasificatoria.

        Parámetros: widget padre opcional.
        Retorno: None; deja la serie vacía hasta recibir historial.
        """
        super().__init__(parent)
        self.valores: list[float] = []
        self.fuente = ""
        self.etiquetas: list[str] = []
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def establecer_partidas(self, partidas: list[dict[str, Any]]) -> None:
        """Prepara LP exactos o un proxy determinista de resultados clasificatorios.

        Parámetros: partidas recibidas en orden de más recientes a más antiguas.
        Retorno: None; conserva la serie solo si cambia el conjunto representado.
        """
        clasificatorias = sorted(
            (
                partida
                for partida in partidas
                if self._es_clasificatoria(partida)
                and partida.get("result") in {"victory", "defeat"}
            ),
            key=lambda partida: str(partida.get("started_at") or ""),
        )[-20:]
        if len(clasificatorias) < 2:
            valores: list[float] = []
            fuente = ""
        else:
            puntos = [
                self._numero(
                    partida,
                    ("lp_after", "league_points_after", "ranked_lp", "league_points", "lp"),
                )
                for partida in clasificatorias
            ]
            deltas = [
                self._numero(
                    partida,
                    ("lp_delta", "league_points_delta", "lp_change", "ranked_lp_change"),
                )
                for partida in clasificatorias
            ]
            if all(valor is not None for valor in puntos):
                valores = [float(valor) for valor in puntos if valor is not None]
                fuente = "LP registrados"
            elif all(valor is not None for valor in deltas):
                valores = []
                acumulado = 0.0
                for valor in deltas:
                    acumulado += float(valor or 0)
                    valores.append(acumulado)
                fuente = "Variación LP registrada"
            else:
                valores = []
                acumulado = 0.0
                for partida in clasificatorias:
                    acumulado += 1 if partida.get("result") == "victory" else -1
                    valores.append(acumulado)
                fuente = "Índice W/L · proxy clasificatorio"
        etiquetas = [
            str(partida.get("started_at") or partida.get("result") or "")
            for partida in clasificatorias
        ]
        if (valores, fuente, etiquetas) == (self.valores, self.fuente, self.etiquetas):
            return
        self.valores = valores
        self.fuente = fuente
        self.etiquetas = etiquetas
        self.update()

    @staticmethod
    def _es_clasificatoria(partida: dict[str, Any]) -> bool:
        """Identifica SoloQ o Flex mediante el ID o nombre explícito de cola.

        Parámetros: registro normalizado de una partida.
        Retorno: True si la partida pertenece a una cola clasificatoria.
        """
        cola = str(
            partida.get("queue")
            or partida.get("queue_type")
            or partida.get("queueType")
            or ""
        ).upper()
        queue_id = str(partida.get("queue_id") or "")
        return "RANKED" in cola or queue_id in {"420", "440"}

    @staticmethod
    def _numero(partida: dict[str, Any], campos: tuple[str, ...]) -> float | None:
        """Devuelve el primer valor numérico disponible entre campos admitidos.

        Parámetros: partida y nombres de campos de progresión.
        Retorno: número finito o None si los campos faltan o no son válidos.
        """
        for campo in campos:
            try:
                valor = float(partida.get(campo))
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(valor):
                return valor
        return None

    def paintEvent(self, event: Any) -> None:
        """Pinta una curva clasificatoria con guías, ejes y marcadores.

        Parámetros: evento de pintura de Qt.
        Retorno: None; dibuja progreso real o informa que falta muestra.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect()).adjusted(30, 12, -12, -25)
        if len(self.valores) < 2:
            painter.setPen(QColor("#AAB4BF"))
            painter.drawText(
                area,
                Qt.AlignmentFlag.AlignCenter,
                "Progresión clasificatoria no disponible\nSe necesitan al menos 2 partidas registradas",
            )
            return
        minimo = min(self.valores)
        maximo = max(self.valores)
        margen = max(1.0, (maximo - minimo) * 0.18)
        minimo -= margen
        maximo += margen
        painter.setFont(QFont("Segoe UI", 8))
        for indice in range(4):
            fraccion = indice / 3
            y = area.top() + area.height() * fraccion
            valor_eje = maximo - (maximo - minimo) * fraccion
            painter.setPen(QPen(QColor("#35404a"), 1))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor("#AAB4BF"))
            painter.drawText(QRectF(0, y - 8, 26, 16), Qt.AlignmentFlag.AlignRight, f"{valor_eje:.0f}")
        coordenadas = [
            QPointF(
                area.left() + area.width() * indice / (len(self.valores) - 1),
                area.bottom() - (valor - minimo) / max(0.001, maximo - minimo) * area.height(),
            )
            for indice, valor in enumerate(self.valores)
        ]
        for indice, (anterior, siguiente) in enumerate(
            zip(coordenadas, coordenadas[1:])
        ):
            sube = self.valores[indice + 1] >= self.valores[indice]
            color = QColor("#36B982" if sube else "#E4515B")
            painter.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(anterior, siguiente)
        for indice, punto in enumerate(coordenadas):
            sube = indice == 0 or self.valores[indice] >= self.valores[indice - 1]
            color = QColor("#36B982" if sube else "#E4515B")
            painter.setPen(QPen(QColor("#10151e"), 1.5))
            painter.setBrush(color)
            painter.drawEllipse(punto, 3.2, 3.2)
        painter.setPen(QColor("#AAB4BF"))
        painter.drawText(QRectF(area.left(), area.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignLeft, "Antiguas")
        painter.drawText(QRectF(area.right() - 60, area.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignRight, "Recientes")


class GraficoPorcentajeVictorias(QWidget):
    """Muestra un anillo proporcional a victorias y derrotas reales."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inicializa el anillo sin partidas; retorna None."""
        super().__init__(parent)
        self.victorias = 0
        self.derrotas = 0
        self.porcentaje: int | None = None
        self.setMinimumSize(112, 112)
        self.setMaximumSize(148, 148)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def establecer_valores(self, victorias: int, derrotas: int) -> None:
        """Actualiza el conteo real y porcentaje de resultados.

        Parámetros: cantidades de victorias y derrotas válidas.
        Retorno: None; evita repintar si ambas cantidades se mantienen.
        """
        victorias_nuevas = max(0, int(victorias))
        derrotas_nuevas = max(0, int(derrotas))
        if (victorias_nuevas, derrotas_nuevas) == (self.victorias, self.derrotas):
            return
        self.victorias = victorias_nuevas
        self.derrotas = derrotas_nuevas
        total = self.victorias + self.derrotas
        self.porcentaje = round(self.victorias * 100 / total) if total else None
        self.update()

    def paintEvent(self, event: Any) -> None:
        """Pinta el anillo, el porcentaje central y el total de partidas."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diametro = min(self.width(), self.height()) - 20
        rect = QRectF(
            (self.width() - diametro) / 2,
            (self.height() - diametro) / 2,
            diametro,
            diametro,
        )
        grosor = max(8, round(diametro * 0.12))
        painter.setPen(QPen(QColor("#27313a"), grosor, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawArc(rect, 0, 360 * 16)
        total = self.victorias + self.derrotas
        if total:
            victoria = round(360 * 16 * self.victorias / total)
            painter.setPen(QPen(QColor("#36B982"), grosor, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawArc(rect, 90 * 16, -victoria)
            painter.setPen(QPen(QColor("#E4515B"), grosor, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            painter.drawArc(rect, (90 * 16 - victoria) % (360 * 16), -(360 * 16 - victoria))
        painter.setPen(QColor("#F1E7CD"))
        painter.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        painter.drawText(
            QRectF(0, self.height() * 0.36, self.width(), 28),
            Qt.AlignmentFlag.AlignCenter,
            f"{self.porcentaje}%" if self.porcentaje is not None else "—",
        )
        painter.setPen(QColor("#AAB4BF"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(
            QRectF(0, self.height() * 0.54, self.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            f"{total} partidas",
        )


class HomeDashboard(QWidget):
    """Presenta el resumen personal y las partidas recordadas localmente."""

    sync_requested = Signal()
    clear_requested = Signal()
    saved_match_requested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        item_catalog: dict[str, Any] | None = None,
        version: str = "",
    ) -> None:
        """Crea el dashboard adaptable con estado vacío y controles de historial."""
        super().__init__(parent)
        self._matches: list[dict[str, Any]] = []
        self._visible_count = 25
        catalog = item_catalog or {}
        self.item_catalog = catalog.get("items", catalog)
        self.version = version
        self._profile: dict[str, Any] = {}
        self._collection: dict[str, Any] = {}
        self._analytics: dict[str, Any] = {}
        self._matchups_two_columns: bool | None = None
        self._summary_columns: int | None = None
        self._dashboard_layout_mode: str | None = None
        self._dashboard_matches_grouped: bool | None = None
        self._perfil_horizontal: bool | None = None
        self._enemy_visibility_signature: tuple[Any, ...] | None = None
        self._layout_inicial_activado = False
        self.matchups_grid_host: QWidget | None = None
        self.matchups_grid: QGridLayout | None = None
        self.matchups_groups: tuple[QWidget, QWidget] | None = None
        self._collection_columns: int | None = None
        self._top_champions_signature: tuple[Any, ...] | None = None
        self._enemy_team_rows: list[tuple[list[QLabel], QLabel, list[str]]] = []
        self._syncing = False
        self._data_signature: tuple[Any, ...] | None = None
        self._build()

    def minimumSizeHint(self) -> QSize:
        """Permite que el scroll adapte el dashboard a distintas alturas.

        Parámetros: ninguno.
        Retorno: tamaño mínimo flexible en anchura y acotado en altura.
        """
        return QSize(0, min(680, self.root.sizeHint().height()))

    def _build(self) -> None:
        """Construye las tarjetas del dashboard dentro de una cuadrícula adaptable."""
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(18)
        self.root.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.profile = self._card()
        self.profile.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        profile_layout = QHBoxLayout(self.profile)
        self.profile_layout = profile_layout
        profile_layout.setContentsMargins(14, 12, 14, 12)
        profile_layout.setSpacing(12)
        self.profile_frame = QFrame()
        self.profile_frame.setObjectName("homeProfileFrame")
        self.profile_frame.setFixedSize(92, 92)
        profile_glow = QGraphicsDropShadowEffect(self.profile_frame)
        profile_glow.setBlurRadius(20)
        profile_glow.setOffset(0, 0)
        profile_glow.setColor(QColor(200, 167, 90, 75))
        self.profile_frame.setGraphicsEffect(profile_glow)
        profile_frame_layout = QVBoxLayout(self.profile_frame)
        profile_frame_layout.setContentsMargins(5, 5, 5, 5)
        self.profile_icon = IconoRedondeado(radio=13)
        self.profile_icon.setObjectName("homeProfilePortrait")
        self.profile_icon.setFixedSize(80, 80)
        self.profile_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        profile_frame_layout.addWidget(self.profile_icon)
        profile_layout.addWidget(self.profile_frame)
        info = QVBoxLayout()
        self.profile_info_layout = info
        self.home_title = QLabel("Tu panel de League")
        self.home_title.setObjectName("heroTitle")
        self.profile_line = QLabel("Conecta League para importar tu cuenta local")
        self.profile_line.setObjectName("sectionTitle")
        info.addWidget(self.profile_line)
        self.profile_meta = QLabel("Nivel —  ·  Región LCU")
        self.profile_meta.setObjectName("homeProfileMeta")
        info.addWidget(self.profile_meta)
        self.home_text = QLabel("Historial privado guardado en este dispositivo.")
        self.home_text.setWordWrap(True)
        info.addWidget(self.home_text)
        self.source_note = QLabel(
            "Datos del cliente local y del historial de SOLRALOL. No requiere la API pública de Riot."
        )
        self.source_note.setObjectName("homeCoverage")
        self.source_note.setToolTip(self.source_note.text())
        profile_layout.addLayout(info, 1)
        self.connection = QLabel("Cliente sin sincronizar")
        self.connection.setObjectName("homeConnectionStatus")
        self.connection.setMaximumHeight(28)
        self.connection.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sync_button = QPushButton("Sincronizar LCU")
        self.sync_button.setObjectName("primaryButton")
        self.sync_button.setFixedHeight(34)
        self.sync_button.clicked.connect(self.sync_requested)
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(7)
        actions_layout.addWidget(self.connection)
        actions_layout.addWidget(self.sync_button)
        profile_layout.addWidget(actions)
        self.dashboard_heading = QWidget()
        heading_layout = QVBoxLayout(self.dashboard_heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(2)
        heading_layout.addWidget(self.home_title)
        self.home_subtitle = QLabel(
            "Actividad, clasificatorias e historial en un solo lugar."
        )
        self.home_subtitle.setObjectName("homeProfileMeta")
        heading_layout.addWidget(self.home_subtitle)
        self.root.addWidget(self.dashboard_heading)
        self.summary_host = QWidget()
        self.summary_host.setObjectName("homeSummaryHost")
        self.summary_grid = QGridLayout(self.summary_host)
        self.summary_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_grid.setHorizontalSpacing(12)
        self.summary_grid.setVerticalSpacing(12)
        self._build_summary_cards()
        self.root.addWidget(self.summary_host)

        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.root.addLayout(self.grid, 1)

        self.history_card = self._card()
        history_layout = QVBoxLayout(self.history_card)
        history_layout.setContentsMargins(20, 18, 20, 18)
        history_layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Historial de partidas recientes")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Todas", "all")
        self.filter_combo.addItem("SoloQ", "solo")
        self.filter_combo.addItem("Flex", "flex")
        self.filter_combo.addItem("ARAM", "aram")
        self.filter_combo.addItem("Normal", "normal")
        self.filter_combo.currentIndexChanged.connect(self.render_matches)
        self.filter_combo.setMaximumWidth(110)
        header.addWidget(self.filter_combo)
        self.clear_button = QPushButton("Borrar historial local")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self.clear_requested)
        self.clear_button.setMaximumWidth(170)
        header.addWidget(self.clear_button)
        history_layout.addLayout(header)
        self.history_status = QLabel("Todavía no hay partidas recordadas.")
        history_layout.addWidget(self.history_status)
        self.match_rows = QVBoxLayout()
        self.match_rows.setSpacing(6)
        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("homeHistoryScroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history_scroll.viewport().setAutoFillBackground(False)
        self.history_content = QWidget()
        self.history_content_layout = QVBoxLayout(self.history_content)
        self.history_content.setAutoFillBackground(False)
        self.history_content_layout.setContentsMargins(2, 2, 8, 2)
        self.history_content_layout.setSpacing(6)
        self.match_rows = QVBoxLayout()
        self.match_rows.setSpacing(6)
        self.history_content_layout.addLayout(self.match_rows)
        self.more_button = QPushButton("Cargar más")
        self.more_button.clicked.connect(self._load_more)
        self.history_content_layout.addWidget(
            self.more_button, alignment=Qt.AlignmentFlag.AlignCenter
        )
        self.history_scroll.setWidget(self.history_content)
        history_layout.addWidget(self.history_scroll, 1)

        self.activity_card = self._section(
            "Tu actividad", "Sin datos de actividad todavía."
        )
        self.activity_text = self.activity_card.findChild(QLabel, "sectionBody")
        self.activity_clock = RelojActividad()
        self.activity_card.layout().addWidget(self.activity_clock)
        self.heatmap_labels: list[QLabel] = []
        heatmap = QHBoxLayout()
        heatmap.setSpacing(5)
        for day in ("L", "M", "X", "J", "V", "S", "D"):
            label = QLabel(day)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(24)
            label.setObjectName("homeHeatmapCell")
            label.setToolTip(f"Actividad del día {day}")
            self.heatmap_labels.append(label)
            heatmap.addWidget(label)
        self.activity_card.layout().addLayout(heatmap)
        self.playstyle_card = self._section(
            "Tu estilo de juego", "Se calculará con el historial local."
        )
        self.playstyle_card.layout().setContentsMargins(12, 10, 12, 10)
        self.playstyle_card.layout().setSpacing(4)
        self.playstyle_text = self.playstyle_card.findChild(QLabel, "sectionBody")
        self.teammates_card = self._section(
            "Compañeros frecuentes",
            "Los identificadores de jugador no siempre están disponibles en LCU.",
        )
        self.teammates_text = self.teammates_card.findChild(QLabel, "sectionBody")
        self.insights_card = self._section(
            "Enfrentamientos",
            "Los resultados se mostrarán al contar con rival de línea fiable.",
        )
        self.insights_text = self.insights_card.findChild(QLabel, "sectionBody")
        self.collection_card = self._section(
            "Colección y progreso", "Consultando datos locales del cliente."
        )
        self.collection_text = self.collection_card.findChild(QLabel, "sectionBody")
        self.tarjetas = [
            self.history_card,
            self.activity_card,
            self.playstyle_card,
            self.teammates_card,
            self.insights_card,
            self.collection_card,
        ]
        for indice, tarjeta in enumerate(self.tarjetas):
            self.grid.addWidget(tarjeta, indice, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _build_summary_cards(self) -> None:
        """Construye los paneles compactos de análisis superior.

        Parámetros: ninguno.
        Retorno: None; crea perfil, progresión, win rate y campeones.
        """
        self.recent_card = self._card()
        recent_layout = QVBoxLayout(self.recent_card)
        recent_layout.setContentsMargins(16, 13, 16, 12)
        recent_layout.setSpacing(6)
        recent_heading = QHBoxLayout()
        recent_title = QLabel("Progresión clasificatoria")
        recent_title.setObjectName("sectionTitle")
        recent_heading.addWidget(recent_title)
        recent_heading.addStretch(1)
        self.progression_source = QLabel("LP exactos o proxy de resultados")
        self.progression_source.setObjectName("homeCoverage")
        recent_heading.addWidget(self.progression_source)
        recent_layout.addLayout(recent_heading)
        self.recent_chart = GraficoProgresionClasificatoria()
        recent_layout.addWidget(self.recent_chart, 1)

        self.winrate_card = self._card()
        winrate_layout = QVBoxLayout(self.winrate_card)
        winrate_layout.setContentsMargins(16, 13, 16, 12)
        winrate_layout.setSpacing(6)
        self.winrate_title = QLabel("Win rate SoloQ")
        self.winrate_title.setObjectName("sectionTitle")
        winrate_layout.addWidget(self.winrate_title)
        self.winrate_source = QLabel("Según historial registrado")
        self.winrate_source.setObjectName("homeCoverage")
        winrate_layout.addWidget(self.winrate_source)
        winrate_body = QHBoxLayout()
        self.winrate_chart = GraficoPorcentajeVictorias()
        winrate_body.addWidget(self.winrate_chart)
        legend = QVBoxLayout()
        self.win_legend = QLabel("● 0 victorias")
        self.loss_legend = QLabel("● 0 derrotas")
        self.win_legend.setObjectName("homeWinLegend")
        self.loss_legend.setObjectName("homeLossLegend")
        legend.addStretch(1)
        legend.addWidget(self.win_legend)
        legend.addWidget(self.loss_legend)
        legend.addStretch(1)
        winrate_body.addLayout(legend, 1)
        winrate_layout.addLayout(winrate_body, 1)

        self.rank_emblem = QLabel("◇")
        self.rank_emblem.setObjectName("homeRankInlineEmblem")
        self.rank_emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rank_value = QLabel("Rango no disponible")
        self.rank_value.setObjectName("homeRankValue")
        self.rank_lp = QLabel("Sin datos locales de clasificatoria")
        self.rank_lp.setObjectName("homeRankLp")
        self.rank_row = QHBoxLayout()
        self.rank_row.setContentsMargins(0, 5, 0, 0)
        self.rank_row.setSpacing(6)
        self.rank_row.addWidget(self.rank_emblem)
        self.rank_row.addWidget(self.rank_value)
        self.rank_row.addWidget(self.rank_lp)
        self.rank_row.addStretch(1)
        self.profile_info_layout.addLayout(self.rank_row)

        self.champions_card = self._card()
        champions_layout = QVBoxLayout(self.champions_card)
        champions_layout.setContentsMargins(16, 13, 16, 12)
        champions_layout.setSpacing(8)
        champions_title = QLabel("Campeones más jugados")
        champions_title.setObjectName("sectionTitle")
        champions_layout.addWidget(champions_title)
        champions_source = QLabel("Según partidas registradas localmente por SOLRALOL")
        champions_source.setObjectName("homeChampionsSource")
        champions_source.setWordWrap(True)
        champions_layout.addWidget(champions_source)
        self.champions_row = QHBoxLayout()
        self.champions_row.setSpacing(8)
        champions_layout.addLayout(self.champions_row, 1)
        self.summary_cards = [
            self.profile,
            self.recent_card,
            self.winrate_card,
            self.champions_card,
        ]
        for index, card in enumerate(self.summary_cards):
            self.summary_grid.addWidget(card, 0, index)

    def _card(self) -> QFrame:
        """Crea una tarjeta con el estilo aprobado de la aplicación."""
        card = QFrame()
        card.setObjectName("sectionCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        aplicar_apariencia(card, "tarjeta")
        return card

    def _section(self, title: str, body: str) -> QFrame:
        """Crea una tarjeta secundaria con título y estado textual."""
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        text = QLabel(body)
        text.setObjectName("sectionBody")
        text.setWordWrap(True)
        layout.addWidget(text)
        return card

    def resizeEvent(self, event: Any) -> None:
        """Recoloca las tarjetas al cambiar el ancho disponible.

        Parámetros: evento de redimensionado de Qt.
        Retorno: None; refluye los resúmenes y las secciones existentes.
        """
        super().resizeEvent(event)
        width = event.size().width()
        modo = "estrecho" if width < 850 else "medio" if width < 1250 else "amplio"
        columnas_resumen = 4 if width >= 1180 else 2 if width >= 720 else 1
        muchas_partidas = len(self._matches) >= 5
        requiere_reflujo = (
            columnas_resumen != self._summary_columns
            or modo != self._dashboard_layout_mode
            or muchas_partidas != self._dashboard_matches_grouped
            or (self.profile.width() >= 430) != self._perfil_horizontal
        )
        actualizaciones_activas = self.updatesEnabled()
        if requiere_reflujo and actualizaciones_activas:
            self.setUpdatesEnabled(False)
        self._reflow_summary(event.size().width())
        self._reflow(event.size().width())
        self._arrange_matchup_groups()
        self._update_enemy_team_visibility()
        self._revisar_columnas_coleccion()
        if requiere_reflujo and actualizaciones_activas:
            self.setUpdatesEnabled(True)
            self.update()

    def _reflow_summary(self, width: int) -> None:
        """Refluye los paneles superiores según el ancho disponible.

        Parámetros: ancho lógico del dashboard.
        Retorno: None; distribuye los paneles en cuatro, dos o una columna.
        """
        if not hasattr(self, "summary_grid"):
            return
        columnas = 4 if width >= 1180 else 2 if width >= 720 else 1
        horizontal = self.profile.width() >= 430
        if columnas == self._summary_columns and horizontal == self._perfil_horizontal:
            return
        self._summary_columns = columnas
        self._perfil_horizontal = horizontal
        actualizaciones_activas = self.updatesEnabled()
        if actualizaciones_activas:
            self.setUpdatesEnabled(False)
        for card in self.summary_cards:
            self.summary_grid.removeWidget(card)
        for columna in range(4):
            self.summary_grid.setColumnStretch(columna, 0)
        for index, card in enumerate(self.summary_cards):
            fila, columna = divmod(index, columnas)
            self.summary_grid.addWidget(card, fila, columna)
            card.setMinimumHeight(208 if columnas == 4 else 176 if columnas == 2 else 150)
        if columnas == 4:
            for columna, peso in enumerate((5, 4, 2, 3)):
                self.summary_grid.setColumnStretch(columna, peso)
        else:
            for columna in range(columnas):
                self.summary_grid.setColumnStretch(columna, 1)
        self.profile_layout.setDirection(QBoxLayout.Direction.LeftToRight if horizontal else QBoxLayout.Direction.TopToBottom)
        if actualizaciones_activas:
            self.setUpdatesEnabled(True)
            self.update()

    def _reflow(self, width: int) -> None:
        """Distribuye tarjetas y adapta el perfil al ancho disponible.

        Parámetros: anchura lógica del dashboard.
        Retorno: None; conserva el reflujo de historial y paneles inferiores.
        """
        modo = "estrecho" if width < 850 else "medio" if width < 1250 else "amplio"
        muchas_partidas = len(self._matches) >= 5
        if modo == self._dashboard_layout_mode and muchas_partidas == self._dashboard_matches_grouped:
            return
        self._dashboard_layout_mode = modo
        self._dashboard_matches_grouped = muchas_partidas
        actualizaciones_activas = self.updatesEnabled()
        if actualizaciones_activas:
            self.setUpdatesEnabled(False)
        horizontal = self.profile.width() >= 430
        if horizontal != self._perfil_horizontal:
            self._perfil_horizontal = horizontal
            self.profile_layout.setDirection(QBoxLayout.Direction.LeftToRight if horizontal else QBoxLayout.Direction.TopToBottom)
        for tarjeta in self.tarjetas:
            self.grid.removeWidget(tarjeta)
        for columna in range(3):
            self.grid.setColumnStretch(columna, 0)
        for fila in range(3):
            self.grid.setRowMinimumHeight(fila, 0)
            self.grid.setRowStretch(fila, 0)
        if width >= 850:
            self.grid.setRowStretch(0, 1)
            if len(self._matches) >= 5:
                self.grid.setRowStretch(1, 1)
        if width < 850:
            for indice, tarjeta in enumerate(self.tarjetas):
                self.grid.addWidget(tarjeta, indice, 0)
        elif width < 1250:
            self.grid.setColumnStretch(0, 8)
            self.grid.setColumnStretch(1, 7)
            self.grid.setColumnStretch(2, 5)
            if len(self._matches) >= 5:
                self.grid.addWidget(self.history_card, 0, 0, 2, 2)
                self.grid.addWidget(self.activity_card, 0, 2)
                self.grid.addWidget(self.playstyle_card, 1, 2)
                self.grid.addWidget(self.teammates_card, 2, 0)
                self.grid.addWidget(self.insights_card, 2, 1)
                self.grid.addWidget(self.collection_card, 2, 2)
            else:
                self.grid.addWidget(self.history_card, 0, 0, 1, 2)
                self.grid.addWidget(self.activity_card, 0, 2)
                self.grid.addWidget(self.playstyle_card, 1, 2)
                self.grid.addWidget(self.teammates_card, 1, 0)
                self.grid.addWidget(self.insights_card, 1, 1)
                self.grid.addWidget(self.collection_card, 2, 0, 1, 3)
        else:
            self.grid.setColumnStretch(0, 8)
            self.grid.setColumnStretch(1, 7)
            self.grid.setColumnStretch(2, 5)
            if len(self._matches) >= 5:
                self.grid.addWidget(self.history_card, 0, 0, 2, 2)
                self.grid.addWidget(self.activity_card, 0, 2)
                self.grid.addWidget(self.teammates_card, 2, 0)
                self.grid.addWidget(self.insights_card, 2, 1)
                self.grid.addWidget(self.playstyle_card, 1, 2)
                self.grid.addWidget(self.collection_card, 2, 2)
            else:
                self.grid.addWidget(self.history_card, 0, 0)
                self.grid.addWidget(self.activity_card, 0, 1)
                self.grid.addWidget(self.playstyle_card, 0, 2)
                self.grid.addWidget(self.teammates_card, 1, 0)
                self.grid.addWidget(self.insights_card, 1, 1)
                self.grid.addWidget(self.collection_card, 1, 2)
        self.grid.activate()
        for tarjeta in (self.history_card, self.activity_card, self.playstyle_card):
            tarjeta.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding
                if width >= 850
                else QSizePolicy.Policy.Preferred,
            )
        for tarjeta in (self.teammates_card, self.insights_card, self.collection_card):
            tarjeta.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        bottom_cards = (self.teammates_card, self.insights_card, self.collection_card)
        altura_comun = min(
            220, max(tarjeta.sizeHint().height() for tarjeta in bottom_cards)
        )
        for tarjeta in bottom_cards:
            tarjeta.setMinimumHeight(altura_comun if width >= 850 else 0)
        self.updateGeometry()
        if actualizaciones_activas:
            self.setUpdatesEnabled(True)
            self.update()

    def showEvent(self, event: Any) -> None:
        """Ajusta las cuadrículas después de mostrar la página.

        Parámetros: evento de visualización de Qt.
        Retorno: None; aplica el reflujo con el ancho final del viewport.
        """
        super().showEvent(event)
        self._reflow_summary(self.width())
        self._reflow(self.width())
        QTimer.singleShot(0, self._activate_matchup_geometry)

    def _activate_matchup_geometry(self) -> None:
        """Activa la geometría de enfrentamientos tras completar el primer show."""
        if not self.isVisible() or self.matchups_grid is None:
            return
        if self._layout_inicial_activado:
            return
        self._reflow_summary(self.width())
        self._reflow(self.width())
        self.matchups_grid.activate()
        if self.matchups_grid_host is not None:
            self.matchups_grid_host.updateGeometry()
        for group in self.matchups_groups or ():
            if group.layout() is not None:
                group.layout().activate()
            group.updateGeometry()
        if self.insights_card.layout() is not None:
            self.insights_card.layout().activate()
        self.updateGeometry()
        self._layout_inicial_activado = True

    def set_dashboard_data(
        self,
        profile: dict[str, Any] | None,
        history: dict[str, Any],
        analytics: dict[str, Any],
        status: str,
        collection: dict[str, Any] | None = None,
        syncing: bool = False,
    ) -> None:
        """Actualiza identidad, estadísticas, gráficos y partidas visibles.

        Parámetros: perfil LCU, historial, analítica, estado y colección opcional.
        Retorno: None; conserva filtros, scroll y widgets de resumen sin cambios.
        """
        matches = history.get("matches", [])
        nuevos_matches = normalizar_partidas_unicas(
            [match for match in matches if isinstance(match, dict)]
        )
        ids_anteriores = tuple(
            str(match.get("stable_match_id") or match.get("game_id") or "")
            for match in self._matches
        )
        ids_nuevos = tuple(
            str(match.get("stable_match_id") or match.get("game_id") or "")
            for match in nuevos_matches
        )
        conservar_estado_historial = (
            bool(self._matches) and ids_anteriores == ids_nuevos
        )
        posicion_scroll = self.history_scroll.verticalScrollBar().value()
        firma = (
            history.get("last_sync"),
            len(nuevos_matches),
            ids_nuevos[:10],
            tuple(
                (
                    str(match.get("stable_match_id") or match.get("game_id") or ""),
                    repr(match.get("performance_summary")),
                )
                for match in nuevos_matches
            ),
            repr(analytics),
            repr(collection or {}),
        )
        datos_cambiaron = firma != self._data_signature
        if datos_cambiaron:
            self._matches = nuevos_matches
            self._analytics = analytics
            if not conservar_estado_historial:
                self._visible_count = 25
            self._data_signature = firma
        self._profile = profile or {}
        self.connection.setText(
            "LCU listo"
            if any(token in status.casefold() for token in ("listo", "conectado", "ready"))
            else "LCU sin conexión"
        )
        self.connection.setToolTip(status)
        self._collection = collection or {}
        self._syncing = syncing
        self.sync_button.setEnabled(not syncing)
        self.sync_button.setText("Sincronizando…" if syncing else "Sincronizar LCU")
        if profile:
            self._render_profile(profile)
        self.home_title.setText("Tu panel de League")
        winrate = analytics.get("winrate")
        streak_type = analytics.get("current_streak_result")
        streak = (
            f"Racha actual: {analytics.get('current_streak', 0)} "
            f"{'victorias' if streak_type == 'victory' else 'derrotas'}"
            if streak_type
            else "Sin racha registrada"
        )
        summary = f"{analytics.get('total', 0)} partidas recordadas"
        summary += (
            f" · {winrate}% de victorias"
            if winrate is not None
            else " · Sin muestra suficiente para winrate"
        )
        if analytics.get("top_champion"):
            summary += f" · Más jugado: {analytics['top_champion']}"
        self.home_text.setText(f"{analytics.get('total', 0)} partidas registradas · {streak}")
        self.home_text.setToolTip(summary)
        self.history_status.setText(
            f"{len(self._matches)} partidas almacenadas en este dispositivo."
        )
        peak = analytics.get("peak_hour")
        self.activity_clock.set_data(dict(analytics.get("hours", [])), peak)
        dias = dict(analytics.get("weekdays", []))
        max_dia = max(dias.values(), default=0)
        for indice, label in enumerate(self.heatmap_labels):
            cantidad = dias.get(indice, 0)
            nivel = round(20 + 70 * cantidad / max_dia) if max_dia else 20
            label.setText(f"{label.toolTip()[-1]}\n{cantidad}")
            label.setProperty("intensity", min(4, max(0, nivel // 20)))
            label.style().unpolish(label)
            label.style().polish(label)
        best_hour = analytics.get("best_hour")
        worst_hour = analytics.get("worst_hour")
        hour_insights = []
        if best_hour:
            hour_insights.append(
                f"Mejor hora: {best_hour[0]:02d}:00 ({best_hour[1]}% en {best_hour[2]} partidas)"
            )
        if worst_hour:
            hour_insights.append(
                f"Peor hora: {worst_hour[0]:02d}:00 ({worst_hour[1]}% en {worst_hour[2]} partidas)"
            )
        self.activity_text.setText(
            f"Pico {peak:02d}:00 · {len(self._matches)} partidas"
            if peak is not None
            else "Faltan fechas válidas para calcular actividad."
        )
        self.activity_text.setToolTip(
            "\n".join(hour_insights)
            if hour_insights
            else "Mejor/peor win rate requiere cinco partidas por hora."
        )
        self._render_summary(analytics)
        if datos_cambiaron:
            self._render_playstyle(analytics)
            self._render_teammates(analytics)
            self._render_matchups(analytics)
            self._render_collection()
            self.render_matches()
            self._reflow(self.width())
            if conservar_estado_historial:
                QTimer.singleShot(
                    0,
                    lambda valor=posicion_scroll: (
                        self.history_scroll.verticalScrollBar().setValue(valor)
                    ),
                )

    def _render_profile(self, profile: dict[str, Any]) -> None:
        """Pinta nombre, nivel y región de la cuenta local.

        Parámetros: perfil local normalizado o vacío.
        Retorno: None; muestra solo información proporcionada por la LCU.
        """
        name = str(profile.get("gameName") or "Invocador")
        tag = str(profile.get("tagLine") or "")
        level = profile.get("summonerLevel")
        region = str(profile.get("region") or "Región LCU")
        self.profile_line.setText(f"{name}{'#' + tag if tag else ''}")
        self.profile_meta.setText(
            f"Nivel {level if level is not None else '—'}  ·  {region}"
        )
        if not self.profile_icon.pixmap() or self.profile_icon.pixmap().isNull():
            self.profile_icon.setText("SOL")

    def _render_summary(self, analytics: dict[str, Any]) -> None:
        """Actualiza las tarjetas con estadísticas reales del historial.

        Parámetros: analítica agregada del historial local.
        Retorno: None; evita inventar rango o resultados no disponibles.
        """
        self.recent_chart.establecer_partidas(self._matches)
        self.progression_source.setText(
            self.recent_chart.fuente or "SoloQ/Flex · muestra insuficiente"
        )
        victories = int(analytics.get("wins", 0) or 0)
        played = int(analytics.get("played", 0) or 0)
        defeats = max(0, played - victories)
        ranked_queues = self._profile.get("ranked", [])
        ranked_queues = ranked_queues if isinstance(ranked_queues, list) else []
        solo = next(
            (
                queue
                for queue in ranked_queues
                if isinstance(queue, dict)
                and "SOLO" in str(queue.get("queue", "")).upper()
            ),
            None,
        )
        if solo:
            tier = str(solo.get("tier") or "Rango no disponible").replace("_", " ")
            division = str(solo.get("division") or "").strip()
            lp = solo.get("league_points")
            self.rank_emblem.setText("✦")
            self.rank_value.setText(f"{tier} {division}".strip())
            self.rank_lp.setText(
                f"{lp} LP" if lp is not None else "LP no disponible"
            )
            wins_clasificatorios = solo.get("wins")
            derrotas_clasificatorias = solo.get("losses")
            if wins_clasificatorios is not None and derrotas_clasificatorias is not None:
                victories = int(wins_clasificatorios)
                defeats = int(derrotas_clasificatorias)
                self.winrate_source.setText("Registro actual de SoloQ")
                self.winrate_title.setText("Win rate SoloQ")
            else:
                self.winrate_source.setText("SoloQ · historial local disponible")
                self.winrate_title.setText("Win rate registrado")
        else:
            self.rank_emblem.setText("◇")
            self.rank_value.setText("Rango no disponible")
            self.rank_lp.setText("Sin datos locales de clasificatoria")
            self.winrate_source.setText("Historial local · SoloQ no disponible")
            self.winrate_title.setText("Win rate registrado")
        self.winrate_chart.establecer_valores(victories, defeats)
        self.win_legend.setText(f"●  {victories} victorias")
        self.loss_legend.setText(f"●  {defeats} derrotas")
        self._render_top_champions(analytics)

    def _render_top_champions(self, analytics: dict[str, Any]) -> None:
        """Muestra campeones, volumen y win rate individual.

        Parámetros: analítica agregada que define el orden de campeones.
        Retorno: None; conserva las tarjetas cuando el modelo no ha cambiado.
        """
        champions = analytics.get("champions") or []
        entradas: list[tuple[str, int, int | None]] = []
        for champion, count in champions[:3]:
            name = str(champion)
            partidas = [
                match
                for match in self._matches
                if match.get("champion_name") == name
                and match.get("result") in {"victory", "defeat"}
            ]
            victorias = sum(match.get("result") == "victory" for match in partidas)
            porcentaje = round(victorias * 100 / len(partidas)) if partidas else None
            entradas.append((name, int(count), porcentaje))
        firma = tuple(entradas)
        if firma == self._top_champions_signature:
            return
        self._top_champions_signature = firma
        while self.champions_row.count():
            item = self.champions_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not champions:
            vacio = QLabel("Sin partidas registradas")
            vacio.setObjectName("homeCoverage")
            self.champions_row.addWidget(vacio)
            return
        for name, count, winrate in entradas:
            entrada = QWidget()
            layout = QVBoxLayout(entrada)
            layout.setContentsMargins(2, 0, 2, 0)
            layout.setSpacing(3)
            icono = QLabel()
            icono.setObjectName("homeTopChampionPortrait")
            icono.setFixedSize(56, 56)
            icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._set_champion_icon(icono, name, 48)
            layout.addWidget(icono, alignment=Qt.AlignmentFlag.AlignHCenter)
            nombre = QLabel(name)
            nombre.setObjectName("homeTopChampionName")
            nombre.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(nombre)
            partidas_label = QLabel(f"{count} partidas")
            partidas_label.setObjectName("homeCoverage")
            partidas_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(partidas_label)
            winrate_label = QLabel(f"{winrate}% WR" if winrate is not None else "WR —")
            winrate_label.setObjectName("homeTopChampionWinrate")
            winrate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(winrate_label)
            self.champions_row.addWidget(entrada, 1)

    def _clear_section(self, card: QFrame, keep: int = 1) -> QVBoxLayout:
        """Vacía widgets dinámicos de una tarjeta y conserva su cabecera."""
        layout = card.layout()
        while layout.count() > keep:
            item = layout.takeAt(keep)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_nested_layout(item.layout())
                item.layout().deleteLater()
        return layout

    def _clear_nested_layout(self, layout: QLayout) -> None:
        """Desconecta y elimina recursivamente widgets de un layout dinámico."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_nested_layout(item.layout())
                item.layout().deleteLater()

    def _render_playstyle(self, analytics: dict[str, Any]) -> None:
        """Dibuja distribuciones compactas de roles, clases y modos.

        Parámetros: analítica local ya agregada.
        Retorno: None; reconstruye solo el contenido de estilo de juego.
        """
        layout = self._clear_section(self.playstyle_card)
        if self.playstyle_text is not None:
            self.playstyle_text.deleteLater()
        self.playstyle_text = None
        total = max(1, int(analytics.get("played", 0)))
        lanes = analytics.get("lanes") or []
        labels = {
            "top": "Superior",
            "jungle": "Jungla",
            "mid": "Medio",
            "bot": "Inferior",
            "support": "Soporte",
            "unknown": "Sin rol",
        }
        if lanes:
            layout.addWidget(self._subheading("Roles principales"))
        for role, count in lanes[:3]:
            self._add_bar(layout, labels.get(role, str(role).title()), count, total)
        classes = analytics.get("classes") or []
        if classes:
            layout.addWidget(self._subheading("Clases de campeones"))
            class_total = max(1, sum(count for _, count in classes))
            for name, count in classes[:3]:
                self._add_bar(layout, str(name), count, class_total)
        modes = analytics.get("modes") or []
        if modes:
            row = QHBoxLayout()
            row.setSpacing(4)
            for name, count in modes[:3]:
                chip = QLabel(f"{name} · {count}")
                chip.setObjectName("homeModeChip")
                row.addWidget(chip)
            row.addStretch(1)
            layout.addLayout(row)
        self.playstyle_card.setMinimumHeight(0)

    def _add_bar(self, layout: QVBoxLayout, label: str, count: int, total: int) -> None:
        """Añade una fila con porcentaje y barra de proporción accesible."""
        percent = round(100 * count / max(1, total))
        row = QHBoxLayout()
        name = QLabel(label)
        name.setMinimumWidth(72)
        name.setObjectName("homeBarLabel")
        bar = QProgressBar()
        bar.setObjectName("homeAnalyticsBar")
        bar.setRange(0, 100)
        bar.setValue(percent)
        bar.setTextVisible(False)
        bar.setAccessibleName(f"{label}: {percent}%")
        value = QLabel(f"{percent}%")
        value.setMinimumWidth(34)
        row.addWidget(name)
        row.addWidget(bar, 1)
        row.addWidget(value)
        layout.addLayout(row)

    def _subheading(self, text: str) -> QLabel:
        """Crea una etiqueta secundaria coherente para grupos analíticos."""
        label = QLabel(text)
        label.setObjectName("homeSubheading")
        return label

    def _champion_entry(self, name: str, count: int, size: int) -> QWidget:
        """Crea una miniatura con retrato local y cantidad de partidas."""
        entry = QWidget()
        row = QHBoxLayout(entry)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        icon = QLabel()
        icon.setObjectName("savedGameChampIcon")
        icon.setFixedSize(size + 8, size + 8)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setContentsMargins(3, 3, 3, 3)
        self._set_champion_icon(icon, name, size)
        icon.setToolTip(f"{name} · {count:,} puntos" if count else name)
        row.addWidget(icon)
        text = QLabel(f"{name}\n{count}" if count else name)
        text.setObjectName("homeCompactText")
        row.addWidget(text)
        return entry

    def _render_teammates(self, analytics: dict[str, Any]) -> None:
        """Presenta los tres aliados recurrentes con muestra y winrate."""
        layout = self._clear_section(self.teammates_card)
        if self.teammates_text is not None:
            self.teammates_text.deleteLater()
        self.teammates_text = None
        teammates = analytics.get("teammates") or []
        if not teammates:
            layout.addWidget(
                QLabel(
                    f"Sin identidades de aliados suficientes · {analytics.get('team_data_matches', 0)} partidas con datos de equipo"
                )
            )
            if analytics.get("unresolved_teammate_count", 0):
                nota = QLabel(
                    "Algunos jugadores ocultos no se incluyen porque no se puede confirmar su identidad."
                )
                nota.setObjectName("homeCoverage")
                nota.setWordWrap(True)
                layout.addWidget(nota)
            return
        for index, entry in enumerate(teammates[:3]):
            name = str(entry.get("name") or "Jugador")
            tag = str(entry.get("tag_line") or "")
            row_widget = QFrame()
            row_widget.setObjectName("homeTeammateRow")
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(7, 6, 7, 6)
            row.setSpacing(9)
            avatar = QFrame()
            avatar.setObjectName("homeTeammateAvatar")
            avatar.setFixedSize(44, 44)
            avatar_layout = QVBoxLayout(avatar)
            avatar_layout.setContentsMargins(5, 5, 5, 5)
            avatar_layout.setSpacing(0)
            avatar_image = QLabel("◉")
            avatar_image.setObjectName("homeTeammateAvatarImage")
            avatar_image.setFixedSize(32, 32)
            avatar_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar_layout.addWidget(avatar_image)
            self._set_teammate_icon(avatar_image, entry)
            row.addWidget(avatar)
            identity = QVBoxLayout()
            identity.setSpacing(2)
            title_line = QHBoxLayout()
            title_line.setSpacing(6)
            identity_label = QLabel(f"{name}{'#' + tag if tag else ''}")
            identity_label.setObjectName("homeTeammateName")
            title_line.addWidget(identity_label, 1)
            delta = entry.get("winrate_delta")
            matches_label = QLabel(f"{entry.get('games', 0)} partidas juntos")
            matches_label.setObjectName("homeTeammateMeta")
            identity.addLayout(title_line)
            identity.addWidget(matches_label)
            row.addLayout(identity, 1)
            metrics = QVBoxLayout()
            metrics.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            winrate = QLabel(f"{entry.get('winrate', 0)}% WR")
            winrate.setObjectName("homeTeammateWinrate")
            metrics.addWidget(winrate, alignment=Qt.AlignmentFlag.AlignRight)
            delta_label = QLabel(
                f"{delta:+} pp contigo" if delta is not None else "Sin comparación"
            )
            delta_label.setObjectName("homeTeammateDelta")
            delta_label.setProperty(
                "sentiment",
                "positive"
                if delta and delta > 0
                else "negative"
                if delta and delta < 0
                else "neutral",
            )
            delta_label.setToolTip(
                "Comparación entre tu winrate con este jugador y tu winrate sin él."
            )
            delta_label.style().unpolish(delta_label)
            delta_label.style().polish(delta_label)
            metrics.addWidget(delta_label, alignment=Qt.AlignmentFlag.AlignRight)
            row.addLayout(metrics)
            if (
                index == 0
                and int(entry.get("games", 0)) >= 8
                and int(entry.get("games", 0))
                >= 2
                * max(1, int(teammates[1].get("games", 0)) if len(teammates) > 1 else 1)
            ):
                duo = QLabel("DÚO HABITUAL")
                duo.setObjectName("homeDuoBadge")
                title_line.addWidget(duo)
            layout.addWidget(row_widget)
        coverage = QLabel(
            f"Datos de compañeros disponibles en {analytics.get('team_data_matches', 0)}/{analytics.get('total', 0)} partidas"
        )
        coverage.setObjectName("homeCoverage")
        layout.addWidget(coverage)
        if analytics.get("unresolved_teammate_count", 0):
            nota = QLabel(
                "Algunos jugadores ocultos no se incluyen porque no se puede confirmar su identidad."
            )
            nota.setObjectName("homeCoverage")
            nota.setWordWrap(True)
            layout.addWidget(nota)

    def _set_teammate_icon(self, label: QLabel, entry: dict[str, Any]) -> None:
        """Carga icono de perfil local o recurre al campeón más jugado juntos."""
        icon_id = entry.get("profile_icon_id")
        if icon_id is not None:
            path = (
                Path.home()
                / ".solralol"
                / "ddragon"
                / "profileicons"
                / f"{icon_id}.png"
            )
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        32,
                        32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        champion = str(entry.get("champion_name") or "")
        if champion:
            self._set_champion_icon(label, champion, 30)

    def _render_matchups(self, analytics: dict[str, Any]) -> None:
        """Muestra rivales favorables y difíciles con sus retratos locales."""
        layout = self._clear_section(self.insights_card)
        if self.insights_text is not None:
            self.insights_text.deleteLater()
        self.insights_text = None
        self.matchups_grid_host = QWidget()
        self.matchups_grid_host.setObjectName("homeMatchupsHost")
        self.matchups_grid = QGridLayout(self.matchups_grid_host)
        self.matchups_grid.setContentsMargins(0, 0, 0, 0)
        self.matchups_grid.setHorizontalSpacing(12)
        self.matchups_grid.setVerticalSpacing(10)
        self._matchups_two_columns = None
        groups: list[QWidget] = []
        for title, entries, kind in (
            ("MÁS TE CUESTAN", analytics.get("hardest_matchups") or [], "hard"),
            ("MÁS GANAS", analytics.get("matchups") or [], "favorable"),
        ):
            group_widget = QWidget()
            group_widget.setObjectName("homeMatchupGroup")
            group = QVBoxLayout(group_widget)
            group.setContentsMargins(0, 0, 0, 0)
            group.setSpacing(7)
            group.addWidget(self._subheading(title))
            for entry in entries[:3]:
                row_widget = QFrame()
                row_widget.setObjectName("homeMatchupRow")
                line = QHBoxLayout(row_widget)
                line.setContentsMargins(5, 4, 5, 4)
                line.setSpacing(7)
                icon = QLabel()
                icon.setObjectName("savedGameEnemyIcon")
                row_widget.setMinimumHeight(52)
                icon.setFixedSize(38, 38)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setContentsMargins(4, 4, 4, 4)
                champion = str(entry.get("champion") or "Campeón")
                self._set_champion_icon(icon, champion, 28)
                icon.setToolTip(champion)
                line.addWidget(icon)
                details = QVBoxLayout()
                details.setContentsMargins(0, 0, 0, 0)
                details.setSpacing(2)
                name = QLabel(champion)
                name.setObjectName("homeMatchupName")
                name.setMinimumWidth(0)
                name.setSizePolicy(
                    QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
                )
                name.setWordWrap(True)
                name.setToolTip(champion)
                sample = QLabel(f"{entry.get('games', 0)} partidas")
                sample.setObjectName("homeCoverage")
                details.addWidget(name)
                details.addWidget(sample)
                line.addLayout(details, 1)
                winrate = QLabel(f"{entry.get('winrate', 0)}% WR")
                winrate.setObjectName("homeMatchupWinrate")
                winrate.setProperty("result", kind)
                winrate.setFixedWidth(66)
                line.addWidget(winrate)
                group.addWidget(row_widget)
            if not entries:
                group.addWidget(QLabel("Sin muestra fiable"))
            groups.append(group_widget)
        self.matchups_groups = (groups[0], groups[1])
        layout.addWidget(self.matchups_grid_host)
        self._arrange_matchup_groups()
        layout.addWidget(self._coverage_label(analytics))

    @staticmethod
    def _coverage_label(analytics: dict[str, Any]) -> QLabel:
        """Crea una nota secundaria con cobertura exacta y estados no exactos."""
        total = int(analytics.get("total", 0))
        exact = int(analytics.get("opponent_exact", 0))
        probable = int(analytics.get("opponent_probable", 0))
        unresolved = int(analytics.get("opponent_ambiguous", 0)) + int(
            analytics.get("opponent_unavailable", 0)
        )
        label = QLabel(
            f"{exact}/{total} exactas · {probable} probables · {unresolved} sin rival directo"
        )
        label.setObjectName("homeCoverage")
        return label

    def _arrange_matchup_groups(self) -> None:
        """Reubica los mismos grupos según el ancho real de la tarjeta."""
        if self.matchups_grid is None or self.matchups_grid_host is None:
            return
        if self.matchups_groups is None:
            return
        width = self.matchups_grid_host.width()
        if width <= 0:
            width = self.insights_card.width() - 36
        two_columns = width >= 520
        if two_columns == self._matchups_two_columns:
            return
        self._matchups_two_columns = two_columns
        actualizaciones_activas = self.matchups_grid_host.updatesEnabled()
        if actualizaciones_activas:
            self.matchups_grid_host.setUpdatesEnabled(False)
        for group in self.matchups_groups:
            self.matchups_grid.removeWidget(group)
        self.matchups_grid.setColumnStretch(0, 1)
        self.matchups_grid.setColumnStretch(1, 1 if two_columns else 0)
        if two_columns:
            self.matchups_grid.addWidget(self.matchups_groups[0], 0, 0)
            self.matchups_grid.addWidget(self.matchups_groups[1], 0, 1)
        else:
            self.matchups_grid.addWidget(self.matchups_groups[0], 0, 0)
            self.matchups_grid.addWidget(self.matchups_groups[1], 1, 0)
        if actualizaciones_activas:
            self.matchups_grid_host.setUpdatesEnabled(True)
            self.matchups_grid_host.update()

    def _revisar_columnas_coleccion(self) -> None:
        """Recompone los iconos de colección solo al cruzar su breakpoint real."""
        if not hasattr(self, "collection_card"):
            return
        columnas = 3 if self.collection_card.width() >= 420 else 2
        if self._collection_columns is None:
            self._collection_columns = columnas
            return
        if columnas == self._collection_columns:
            return
        self._collection_columns = columnas
        if self._collection.get("masteries"):
            actualizaciones_activas = self.collection_card.updatesEnabled()
            if actualizaciones_activas:
                self.collection_card.setUpdatesEnabled(False)
            self._render_collection()
            if actualizaciones_activas:
                self.collection_card.setUpdatesEnabled(True)
                self.collection_card.update()

    def _render_collection(self) -> None:
        """Muestra las categorías de colección que respondieron desde la LCU."""
        layout = self._clear_section(self.collection_card)
        if self.collection_text is not None:
            self.collection_text.deleteLater()
        self.collection_text = None
        collection = self._collection
        names = _local_champion_names()
        masteries = collection.get("masteries")
        if isinstance(masteries, list) and masteries:
            layout.addWidget(self._subheading("MAESTRÍAS DESTACADAS"))
            mastery_grid = QGridLayout()
            mastery_grid.setContentsMargins(0, 0, 0, 0)
            mastery_grid.setHorizontalSpacing(6)
            mastery_grid.setVerticalSpacing(6)
            columns = 3 if self.collection_card.width() >= 420 else 2
            self._collection_columns = columns
            for index, entry in enumerate(masteries[:3]):
                name = names.get(
                    str(entry.get("champion_id")), f"Campeón {entry.get('champion_id')}"
                )
                points = int(entry.get("points", 0))
                mastery = QFrame()
                mastery.setObjectName("homeMasteryCard")
                mastery_row = QHBoxLayout(mastery)
                mastery_row.setContentsMargins(6, 5, 6, 5)
                mastery_row.setSpacing(6)
                icon_frame = QFrame()
                icon_frame.setObjectName("homeMasteryIconFrame")
                icon_frame.setFixedSize(38, 38)
                icon_layout = QVBoxLayout(icon_frame)
                icon_layout.setContentsMargins(4, 4, 4, 4)
                icon = QLabel()
                icon.setFixedSize(30, 30)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._set_champion_icon(icon, name, 28)
                icon_layout.addWidget(icon)
                mastery_row.addWidget(icon_frame)
                mastery_details = QVBoxLayout()
                mastery_details.setContentsMargins(0, 0, 0, 0)
                mastery_details.setSpacing(1)
                champion_label = QLabel(name)
                champion_label.setObjectName("homeMasteryName")
                champion_label.setWordWrap(True)
                mastery_points = QLabel(
                    f"{points / 1000:.0f}k" if points >= 1000 else str(points)
                )
                mastery_points.setObjectName("homeMasteryPoints")
                mastery_points.setToolTip(f"{points:,} puntos de maestría")
                mastery_details.addWidget(champion_label)
                mastery_details.addWidget(mastery_points)
                mastery_row.addLayout(mastery_details, 1)
                mastery_grid.addWidget(
                    mastery,
                    index // columns,
                    index % columns,
                )
            layout.addLayout(mastery_grid)
        elif masteries is None:
            layout.addWidget(QLabel("Maestrías: endpoint local no disponible"))
        skins = collection.get("skins")
        if isinstance(skins, dict):
            self._add_collection_separator(layout)
            skin_row = QHBoxLayout()
            skin_value = QLabel(f"{int(skins.get('owned_count', 0)):,}")
            skin_value.setObjectName("homeCollectionMetric")
            skin_label = QLabel("SKINS EN PROPIEDAD")
            skin_label.setObjectName("homeCollectionLabel")
            skin_row.addWidget(skin_value)
            skin_row.addWidget(skin_label, 1)
            layout.addLayout(skin_row)
        elif skins is None:
            layout.addWidget(QLabel("Skins: endpoint local no disponible"))
        challenges = collection.get("challenges")
        if isinstance(challenges, dict):
            self._add_collection_separator(layout)
            layout.addWidget(self._subheading("DESAFÍOS"))
            challenge_row = QHBoxLayout()
            tier = str(challenges.get("tier") or "SIN NIVEL")
            tier_badge = QLabel(tier)
            tier_badge.setObjectName("homeChallengeTier")
            challenge_row.addWidget(tier_badge)
            points = challenges.get("points")
            points_label = QLabel(
                f"{int(points):,} pts" if points is not None else "Puntos —"
            )
            points_label.setObjectName("homeCollectionMetric")
            challenge_row.addWidget(points_label, 1)
            layout.addLayout(challenge_row)
            count = challenges.get("count")
            if count is not None:
                count_label = QLabel(f"{count} desafíos destacados")
                count_label.setObjectName("homeCoverage")
                layout.addWidget(count_label)
        elif challenges is None:
            layout.addWidget(QLabel("Desafíos: endpoint local no disponible"))
        titles = collection.get("titles")
        if isinstance(titles, dict) and titles.get("selected"):
            self._add_collection_separator(layout)
            layout.addWidget(self._subheading("TÍTULO ACTIVO"))
            title = QLabel(str(titles["selected"]))
            title.setObjectName("homeActiveTitle")
            layout.addWidget(title)
        elif titles is None:
            layout.addWidget(QLabel("Título: endpoint local no disponible"))
        elif not collection:
            layout.addWidget(QLabel("Sin conexión; se conserva el historial local."))

    def _add_collection_separator(self, layout: QVBoxLayout) -> None:
        """Añade separadores solo entre secciones presentes en el panel."""
        if layout.count() > 1:  # El primer elemento es el encabezado fijo de la tarjeta.
            layout.addWidget(self._collection_separator())

    @staticmethod
    def _collection_separator() -> QFrame:
        """Crea un separador sutil entre categorías de colección."""
        separator = QFrame()
        separator.setObjectName("homeCollectionSeparator")
        separator.setFrameShape(QFrame.Shape.HLine)
        return separator

    def _set_champion_icon(self, label: QLabel, champion: str, size: int) -> None:
        """Carga y recorta un retrato campeón cacheado localmente.

        Parámetros: etiqueta, nombre del campeón y tamaño lógico del icono.
        Retorno: None; reutiliza pixmaps escalados y evita descargas.
        """
        if not champion:
            return
        try:
            path = get_champion_icon_path(champion, self.version, download=False)
            key = (str(path), size)
            pixmap = _HOME_CHAMPION_PIXMAPS.get(key)
            if pixmap is None:
                original = QPixmap(str(path)) if path else QPixmap()
                if not original.isNull():
                    escalado = original.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    pixmap = QPixmap(escalado.size())
                    pixmap.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(pixmap)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    recorte = QPainterPath()
                    recorte.addRoundedRect(QRectF(pixmap.rect()), 7, 7)
                    painter.setClipPath(recorte)
                    painter.drawPixmap(0, 0, escalado)
                    painter.end()
                    if len(_HOME_CHAMPION_PIXMAPS) >= 96:
                        _HOME_CHAMPION_PIXMAPS.pop(next(iter(_HOME_CHAMPION_PIXMAPS)))
                    _HOME_CHAMPION_PIXMAPS[key] = pixmap
                else:
                    pixmap = QPixmap()
            if not pixmap.isNull():
                label.setPixmap(pixmap)
        except (OSError, TypeError, ValueError):
            return

    def _set_item_icon(self, label: QLabel, item_id: Any, size: int) -> None:
        """Carga un icono de objeto de la caché local y añade su nombre alternativo."""
        item = self.item_catalog.get(str(item_id), {})
        name = str(item.get("name_es") or item.get("name") or item_id)
        label.setToolTip(name)
        try:
            path = get_item_icon_path(
                item_id, self.item_catalog, self.version, download=False
            )
            pixmap = QPixmap(str(path)) if path else QPixmap()
            if not pixmap.isNull():
                label.setPixmap(
                    pixmap.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                label.setText(name[:7])
        except (OSError, TypeError, ValueError):
            label.setText(name[:7])

    def _add_opponent_presentation(
        self, layout: QHBoxLayout, match: dict[str, Any]
    ) -> None:
        """Añade rival directo o equipo rival sin asignaciones ambiguas."""
        resolution = match.get("opponent_resolution") or {}
        state = str(match.get("opponent_state") or resolution.get("state") or "")
        confidence = float(
            resolution.get("confidence") or match.get("opponent_confidence") or 0.0
        )
        champion = str(
            match.get("opponent_champion_name") or resolution.get("champion_name") or ""
        )
        if not state:
            has_stored_opponent = bool(
                match.get("opponent") or match.get("opponent_champion_id")
            )
            state = (
                "exact"
                if champion and (confidence >= 0.75 or has_stored_opponent)
                else "unavailable"
            )
        enemy_team = match.get("enemy_team")
        if not isinstance(enemy_team, list):
            enemy_team = []
        if state in {"exact", "probable"} and champion:
            versus = QLabel("VS probable" if state == "probable" else "VS")
            versus.setObjectName("savedGameMatchup")
            if state == "probable":
                versus.setToolTip(
                    "Rival probable según posición, rol y datos disponibles."
                )
                versus.setProperty("state", "probable")
            layout.addWidget(versus)
            icon = QLabel()
            icon.setObjectName("savedGameEnemyIcon")
            icon.setFixedSize(42, 42)
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon.setContentsMargins(3, 3, 3, 3)
            self._set_champion_icon(icon, champion, 34)
            icon.setToolTip(champion)
            layout.addWidget(icon)
            name = QLabel(champion)
            name.setObjectName("homeOpponentName")
            name.setToolTip(versus.toolTip() or champion)
            layout.addWidget(name)
            return
        if state == "ambiguous" and enemy_team:
            versus = QLabel("VS equipo")
            versus.setObjectName("savedGameMatchup")
            versus.setToolTip("Hay datos del equipo rival, sin rival directo fiable.")
            layout.addWidget(versus)
            icons: list[QLabel] = []
            names: list[str] = []
            for enemy in enemy_team[:5]:
                if not isinstance(enemy, dict):
                    continue
                name = str(enemy.get("champion_name") or "Campeón")
                icon = QLabel()
                icon.setObjectName("savedGameEnemyIcon")
                icon.setFixedSize(34, 34)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setContentsMargins(3, 3, 3, 3)
                self._set_champion_icon(icon, name, 26)
                icon.setToolTip(name)
                icons.append(icon)
                names.append(name)
                layout.addWidget(icon)
            overflow = QLabel()
            overflow.setObjectName("homeEnemyTeamOverflow")
            layout.addWidget(overflow)
            self._enemy_team_rows.append((icons, overflow, names))
            return
        versus = QLabel("VS")
        versus.setObjectName("savedGameMatchup")
        layout.addWidget(versus)
        unavailable = QLabel("—")
        unavailable.setObjectName("homeOpponentUnknown")
        unavailable.setToolTip(
            "No hay datos suficientes del equipo rival para esta partida."
        )
        layout.addWidget(unavailable)

    def _update_enemy_team_visibility(self) -> None:
        """Limita los iconos del equipo rival según el ancho del historial."""
        if not hasattr(self, "history_scroll"):
            return
        width = self.history_scroll.viewport().width()
        visible_count = 5 if width >= 1000 else 4 if width >= 700 else 3
        firma = (visible_count, tuple(tuple(nombres) for _, _, nombres in self._enemy_team_rows))
        if firma == self._enemy_visibility_signature:
            return
        self._enemy_visibility_signature = firma
        for icons, overflow, names in self._enemy_team_rows:
            for index, icon in enumerate(icons):
                ocultar = index >= visible_count
                if icon.isHidden() != ocultar:
                    icon.setHidden(ocultar)
            hidden = names[visible_count:]
            if overflow.isHidden() != (not hidden):
                overflow.setHidden(not hidden)
            overflow.setText(f"+{len(hidden)}" if hidden else "")
            overflow.setToolTip(", ".join(hidden))

    def render_matches(self, *_args: Any) -> None:
        """Pinta un lote acotado de partidas según el filtro elegido."""
        self._enemy_team_rows.clear()
        self._enemy_visibility_signature = None
        while self.match_rows.count():
            item = self.match_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        queue = self.filter_combo.currentData()
        matches = (
            self._matches
            if queue == "all"
            else [
                m
                for m in self._matches
                if str(m.get("mode", "")).casefold().find(queue) >= 0
                or str(m.get("queue_id"))
                == {"solo": "420", "flex": "440", "aram": "450", "normal": "400"}.get(
                    queue
                )
                or (queue == "normal" and str(m.get("queue_id")) == "430")
            ]
        )
        visible = matches[: self._visible_count]
        for match in visible:
            row = QFrame()
            row.setObjectName("savedGameRow")
            row.setProperty("history", True)
            result = str(match.get("result") or "unknown")
            row.setProperty(
                "result",
                "win"
                if result == "victory"
                else "loss"
                if result == "defeat"
                else "unknown",
            )
            row.setToolTip(str(match.get("mode") or ""))
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(6)
            upper = QHBoxLayout()
            upper.setSpacing(9)
            outcome = QLabel(
                {"victory": "VICTORIA", "defeat": "DERROTA", "remake": "REMAKE"}.get(
                    result, "SIN RESULTADO"
                )
            )
            outcome.setObjectName("savedGameResult")
            outcome.setProperty(
                "result", result if result in {"victory", "defeat"} else "unknown"
            )
            outcome.setMinimumWidth(76)
            upper.addWidget(outcome)
            player = self._champion_entry(
                str(match.get("champion_name") or "Campeón"), 0, 38
            )
            upper.addWidget(player)
            lane_names = {
                "top": "Superior",
                "jungle": "Jungla",
                "mid": "Medio",
                "bot": "Inferior",
                "support": "Soporte",
            }
            lane = QLabel(lane_names.get(str(match.get("lane") or ""), "—"))
            lane.setObjectName("homeModeChip")
            upper.addWidget(lane)
            self._add_opponent_presentation(upper, match)
            upper.addStretch(1)
            upper.addWidget(
                QLabel(
                    f"{int(match.get('duration_seconds') or 0) // 60}:{int(match.get('duration_seconds') or 0) % 60:02d}"
                )
            )
            row_layout.addLayout(upper)
            lower = QHBoxLayout()
            kda = QLabel(
                f"{match.get('kills', '—')} / {match.get('deaths', '—')} / {match.get('assists', '—')}"
            )
            kda.setObjectName("homeKda")
            lower.addWidget(kda)
            cs_rate = match.get("cs_per_min")
            lower.addWidget(
                QLabel(
                    f"{match.get('cs', '—')} CS"
                    + (f" · {cs_rate}/min" if cs_rate is not None else "")
                )
            )
            lower.addStretch(1)
            item_ids = list(match.get("items") or [])[:6]
            if match.get("trinket"):
                item_ids.append(match["trinket"])
            for item_id in item_ids:
                icon = QLabel()
                icon.setObjectName("itemSlot")
                icon.setFixedSize(34, 34)
                icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
                icon.setContentsMargins(2, 2, 2, 2)
                self._set_item_icon(icon, item_id, 26)
                lower.addWidget(icon)
            try:
                started = (
                    datetime.fromisoformat(
                        str(match.get("started_at") or "").replace("Z", "+00:00")
                    )
                    .astimezone()
                    .strftime("%d %b")
                )
            except ValueError:
                started = "Fecha —"
            lower.addSpacing(6)
            lower.addWidget(QLabel(started))
            resumen = match.get("performance_summary")
            if puntuacion_historial_vigente(resumen):
                puntuacion = QLabel(etiqueta_puntuacion(resumen))
                puntuacion.setObjectName("homePerformanceScore")
                puntuacion.setProperty("award", str(resumen.get("award") or ""))
                puntuacion.setToolTip("Puntuación final SOLRALOL · ranking global")
                lower.addWidget(puntuacion)
            if match.get("analyzable"):
                saved_link = match.get("saved_match_link") or {}
                saved_match_id = str(saved_link.get("saved_match_id") or "")
                badge = QPushButton("◆ ANALIZABLE")
                badge.setObjectName("homeAnalyzableBadge")
                badge.setToolTip("Abrir análisis de esta partida")
                badge.setCursor(Qt.CursorShape.PointingHandCursor)
                badge.setEnabled(bool(saved_match_id))
                badge.clicked.connect(
                    lambda checked=False, value=saved_match_id: (
                        self.saved_match_requested.emit(value) if value else None
                    )
                )
                lower.addWidget(badge)
            row_layout.addLayout(lower)
            self.match_rows.addWidget(row)
        self._update_enemy_team_visibility()
        self.more_button.setVisible(len(matches) > len(visible))

    def _load_more(self) -> None:
        """Añade el siguiente lote de partidas a la lista visible."""
        self._visible_count += 25
        self.render_matches()
