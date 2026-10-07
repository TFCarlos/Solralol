"""Componentes de presentación compartidos para páginas, tarjetas y estados."""

from PySide6.QtCore import QEvent, QObject, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.iconos import icono_accion
from app.ui.sistema_visual import ESPACIADO, PALETA, TRANSICIONES
from app.ui.tema import aplicar_apariencia, aplicar_estado


class TarjetaSistema(QFrame):
    """Tarjeta con título opcional y geometría común adaptable al contenido."""

    def __init__(self, titulo: str = "", variante: str = "tarjeta", parent: QWidget | None = None) -> None:
        """Construye superficie y disposición para título y variante recibidos."""
        super().__init__(parent)
        self.disposicion = QVBoxLayout(self)
        aplicar_apariencia(self, variante)
        if titulo:
            encabezado = QLabel(titulo)
            aplicar_apariencia(encabezado, "seccion")
            self.disposicion.addWidget(encabezado)


class MensajeEstado(QLabel):
    """Mensaje legible con semántica accesible que conserva el contenido textual."""

    def __init__(self, texto: str = "", parent: QWidget | None = None) -> None:
        """Inicializa el mensaje con texto y padre recibidos."""
        super().__init__(texto, parent)
        aplicar_apariencia(self, "estado")
        self.setWordWrap(True)

    def establecer(self, texto: str, estado: str = "informacion") -> None:
        """Actualiza texto, descripción y estado recibidos; retorna None."""
        self.setText(texto)
        self.setAccessibleDescription(texto)
        aplicar_estado(self, estado)


class EstadoVacio(TarjetaSistema):
    """Estado sin datos con explicación y una acción opcional conectable."""

    def __init__(self, titulo: str, detalle: str, accion: str = "", parent: QWidget | None = None) -> None:
        """Presenta título, detalle y acción recibidos sin inventar datos."""
        super().__init__(titulo, "compacta", parent)
        icono = QLabel()
        icono.setPixmap(icono_accion("informacion").pixmap(24, 24))
        self.disposicion.insertWidget(0, icono)
        explicacion = QLabel(detalle)
        aplicar_apariencia(explicacion, "metadatos")
        self.disposicion.addWidget(explicacion)
        self.accion = QPushButton(accion) if accion else None
        if self.accion:
            aplicar_apariencia(self.accion, "primaria")
            self.disposicion.addWidget(self.accion)


class PaginaDesplazable(QScrollArea):
    """Envuelve una página conservando su widget y todas sus señales."""

    def __init__(self, contenido: QWidget) -> None:
        """Aloja el contenido recibido y permite desplazamiento cuando sea necesario."""
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setWidget(contenido)
        self.setObjectName("paginaDesplazable")


class Reflujo(QObject):
    """Apila grupos al estrechar su contenedor sin trabajo continuo por fotograma."""

    def __init__(self, contenedor: QWidget, filas: list[QBoxLayout], umbral: int = 1000) -> None:
        """Observa contenedor y filas recibidos con el umbral de anchura indicado."""
        super().__init__(contenedor)
        self.filas = filas
        self.umbral = umbral
        contenedor.installEventFilter(self)
        self.actualizar(contenedor.width())

    def actualizar(self, ancho: int) -> None:
        """Aplica dirección horizontal o vertical según el ancho recibido."""
        direccion = QBoxLayout.Direction.TopToBottom if ancho < self.umbral else QBoxLayout.Direction.LeftToRight
        for fila in self.filas:
            if fila.direction() != direccion:
                fila.setDirection(direccion)
            fila.setSpacing(ESPACIADO["3"])

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Actualiza filas en resize/show del contenedor sin consumir el evento."""
        if isinstance(watched, QWidget) and event.type() in {QEvent.Type.Resize, QEvent.Type.Show}:
            self.actualizar(watched.width())
        return False


class Interruptor(QCheckBox):
    """Booleano Qt accesible con cursor animado y sin alterar sus señales."""

    def __init__(self, texto: str = "", parent: QWidget | None = None) -> None:
        """Inicializa interruptor con texto y padre, usando transiciones compartidas."""
        super().__init__(texto, parent)
        self.setProperty("interruptor", True)
        self.posicion = 0.0
        self.animacion = QVariantAnimation(self)
        self.animacion.setDuration(TRANSICIONES["estado"])
        self.animacion.valueChanged.connect(self.mover_cursor)
        self.toggled.connect(self.animar)

    def mover_cursor(self, posicion: float) -> None:
        """Guarda la posición interpolada recibida y repinta el control."""
        self.posicion = float(posicion)
        self.update()

    def animar(self, activado: bool) -> None:
        """Desplaza el cursor al estado recibido, sin animar controles invisibles."""
        self.animacion.stop()
        destino = 1.0 if activado else 0.0
        if not self.isVisible():
            self.mover_cursor(destino)
            return
        self.animacion.setStartValue(self.posicion)
        self.animacion.setEndValue(destino)
        self.animacion.start()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Pinta cursor y pista sobre el indicador Qt, conservando texto y foco."""
        super().paintEvent(event)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        centro = (self.height() - 20) // 2
        pintor.setPen(QColor(PALETA["oro"] if self.isChecked() else PALETA["borde"]))
        pintor.setBrush(QColor(PALETA["oro_oscuro"] if self.isChecked() else PALETA["base"]))
        pintor.drawRoundedRect(0, centro, 36, 20, 10, 10)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(PALETA["marfil"] if self.isEnabled() else PALETA["texto_deshabilitado"]))
        pintor.drawEllipse(int(3 + self.posicion * 16), centro + 3, 14, 14)
