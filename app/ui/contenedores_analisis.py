"""Contenedores de contenido variable del análisis, sin recortes ni alturas rígidas."""

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QTableWidget, QVBoxLayout

from app.ui.sistema_visual import espaciar_tarjeta


class TarjetaContenido(QFrame):
    """Agrupa título, contenido y pie dentro de una misma superficie adaptable."""

    def __init__(self, nombre: str, titulo: str) -> None:
        """Crea la tarjeta con nombre de estilo y título recibidos; retorna None."""
        super().__init__()
        self.setObjectName(nombre)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.disposicion = QVBoxLayout(self)
        espaciar_tarjeta(self.disposicion)
        self.titulo = QLabel(titulo)
        self.titulo.setObjectName("localSectionTitle")
        self.titulo.setWordWrap(True)
        self.disposicion.addWidget(self.titulo)


class TablaRecomendaciones(QTableWidget):
    """Tabla con filas ajustadas al texto y altura natural dentro del scroll principal."""

    def __init__(self) -> None:
        """Inicializa tres columnas y agrupa las solicitudes de ajuste; retorna None."""
        super().__init__(0, 3)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.ajuste = QTimer(self)
        self.ajuste.setSingleShot(True)
        self.ajuste.timeout.connect(self.ajustar_contenido)
        self.horizontalHeader().sectionResized.connect(self.programar_ajuste)
        self.model().layoutChanged.connect(self.programar_orden)

    def programar_ajuste(self, columna: int, anterior: int, actual: int) -> None:
        """Agrupa cambios de ancho de columna recibidos para ajustar filas; retorna None."""
        self.ajuste.start(0)

    def programar_orden(self) -> None:
        """Recalcula alturas tras ordenar recomendaciones; retorna None."""
        self.ajuste.start(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Reajusta las filas al cambiar el ancho del evento; retorna None."""
        super().resizeEvent(event)
        if hasattr(self, "ajuste") and event.size().width() != event.oldSize().width():
            self.ajuste.start(0)

    def ajustar_contenido(self) -> None:
        """Ajusta filas al texto y widgets y comunica su altura natural; retorna None."""
        self.resizeRowsToContents()
        for fila in range(self.rowCount()):
            celda = self.cellWidget(fila, 0)
            if celda is not None and celda.layout() is not None:
                alto = celda.layout().totalHeightForWidth(self.columnWidth(0))
                self.setRowHeight(fila, max(self.rowHeight(fila), alto))
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        """Devuelve el tamaño necesario para mostrar todas las filas sin altura fija."""
        tamano = super().sizeHint()
        marco = self.height() - self.viewport().height()
        tamano.setHeight(marco + self.verticalHeader().length())
        return tamano

    def minimumSizeHint(self) -> QSize:
        """Permite reducir el ancho manteniendo espacio para el contenido completo."""
        return QSize(0, self.sizeHint().height())
