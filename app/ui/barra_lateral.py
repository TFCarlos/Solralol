"""Navegación lateral con iconos vectoriales y transición de ancho."""

from PySide6.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from _paths import DATA_DIR
from app.ui.estilo_analisis import ESTILO_BARRA
from app.ui.iconos import icono_trazo
from app.ui.sistema_visual import (
    ANCHO_BARRA,
    ANCHO_BARRA_COMPACTA,
    DURACION_BARRA,
)

TRAZOS = (
    "M3 11L12 3l9 8M5 10v11h5v-7h4v7h5V10",
    "M4 3v18h17M8 16v-5m5 5V7m5 9V4",
    "M8 5l12 7-12 7z",
    "M4 8h16v13H4zM3 3h18v5H3zM9 12h6",
    "M3 6h13v12H3zM16 10l5-3v10l-5-3",
    "M9 3h6l1 4 4 2v6l-4 2-1 4H9l-1-4-4-2V9l4-2zM9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0",
    "M4 3l16 16M20 3L4 19M2 17l5 5M17 22l5-5M4 3v5l4-4M20 3v5l-4-4",
)


def crear_icono(trazo: str) -> QIcon:
    """Dibuja el trazo SVG recibido y devuelve un icono de oro independiente de fuentes."""
    return icono_trazo(trazo)


class BarraLateral(QFrame):
    """Agrupa botones existentes conservando señales y estados de navegación."""

    def __init__(
        self, botones: list[QPushButton], parent: QWidget | None = None
    ) -> None:
        """Recibe los siete destinos y construye la barra expandida; retorna None."""
        super().__init__(parent)
        self.setObjectName("barraLateral")
        self.botones = botones
        self.etiquetas = [
            "Inicio",
            "Análisis",
            "Partida en vivo",
            "Partidas guardadas",
            "Grabaciones",
            "Ajustes",
            "Herramienta de Draft",
        ]
        self.expandida = True
        self.setFixedWidth(ANCHO_BARRA)
        disposicion = QVBoxLayout(self)
        disposicion.setContentsMargins(12, 22, 12, 16)
        disposicion.setSpacing(10)
        identidad = QHBoxLayout()
        identidad.setSpacing(10)
        self.logo = QLabel()
        self.logo.setObjectName("logoLateral")
        self.logo.setFixedSize(58, 58)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setPixmap(
            QPixmap(str(DATA_DIR / "LogoApp.png")).scaled(
                46,
                46,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.logo.setAccessibleName("Solralol")
        self.marca = QLabel("SOLRALOL")
        self.marca.setObjectName("marcaLateral")
        identidad.addWidget(self.logo)
        identidad.addWidget(self.marca, 1)
        disposicion.addLayout(identidad)
        disposicion.addSpacing(20)
        self.categoria = QLabel("ESPACIO DE JUEGO")
        self.categoria.setObjectName("categoriaLateral")
        disposicion.addWidget(self.categoria)
        for boton, etiqueta, trazo in zip(botones, self.etiquetas, TRAZOS):
            boton.setParent(self)
            boton.setObjectName("destinoLateral")
            boton.setIcon(crear_icono(trazo))
            boton.setIconSize(QSize(22, 22))
            boton.setText(etiqueta)
            boton.setToolTip(etiqueta)
            boton.setAccessibleName(etiqueta)
            disposicion.addWidget(boton)
        disposicion.addStretch(1)
        separador = QFrame()
        separador.setObjectName("separadorLateral")
        separador.setFixedHeight(1)
        disposicion.addWidget(separador)
        self.control = QPushButton("Contraer navegación")
        self.control.setObjectName("controlBarra")
        self.control.setIcon(crear_icono("M15 5l-7 7 7 7M20 5l-7 7 7 7"))
        self.control.setIconSize(QSize(22, 22))
        self.control.setToolTip("Contraer navegación")
        self.control.setAccessibleName("Contraer navegación")
        self.control.clicked.connect(self.alternar)
        disposicion.addWidget(self.control)
        self.animacion = QVariantAnimation(self)
        self.animacion.setDuration(DURACION_BARRA)
        self.animacion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animacion.valueChanged.connect(self.aplicar_ancho)
        self.setStyleSheet(ESTILO_BARRA)

    def aplicar_ancho(self, valor: object) -> None:
        """Aplica el ancho interpolado recibido y retorna None."""
        self.setFixedWidth(int(valor))

    def alternar(self) -> None:
        """Alterna etiquetas, accesibilidad y ancho animado; retorna None."""
        self.expandida = not self.expandida
        for boton, etiqueta in zip(self.botones, self.etiquetas):
            boton.setText(etiqueta if self.expandida else "")
        self.marca.setVisible(self.expandida)
        self.categoria.setVisible(self.expandida)
        self.control.setText("Contraer navegación" if self.expandida else "")
        self.control.setIcon(
            crear_icono(
                "M15 5l-7 7 7 7M20 5l-7 7 7 7"
                if self.expandida
                else "M4 5l7 7-7 7M9 5l7 7-7 7"
            )
        )
        self.control.setToolTip(
            "Contraer navegación" if self.expandida else "Expandir navegación"
        )
        self.control.setAccessibleName(self.control.toolTip())
        self.animacion.stop()
        self.animacion.setStartValue(self.width())
        self.animacion.setEndValue(
            ANCHO_BARRA if self.expandida else ANCHO_BARRA_COMPACTA
        )
        self.animacion.start()
