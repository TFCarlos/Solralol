"""Superficies pintadas de bajo coste e imágenes contenidas del análisis."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from app.ui.sistema_visual import PALETA, RADIO_ICONO, RADIO_TARJETA


class FondoTecnologico(QWidget):
    """Fondo abstracto estático con luz cálida, luz teal y retícula tenue."""

    def paintEvent(self, event: QPaintEvent) -> None:
        """Pinta gradientes y retícula dentro del área del evento; retorna None."""
        pintor = QPainter(self)
        pintor.fillRect(self.rect(), QColor(PALETA["base"]))
        for x, y, radio, color, alfa in (
            (0.16, 0.02, 0.8, PALETA["oro"], 40),
            (0.95, 0.4, 0.65, PALETA["teal"], 22),
            (0.65, 1.0, 0.6, PALETA["calida"], 180),
        ):
            luz = QRadialGradient(
                self.width() * x,
                self.height() * y,
                max(self.width(), self.height()) * radio,
            )
            inicio = QColor(color)
            inicio.setAlpha(alfa)
            fin = QColor(color)
            fin.setAlpha(0)
            luz.setColorAt(0, inicio)
            luz.setColorAt(1, fin)
            pintor.fillRect(self.rect(), luz)
        pintor.setPen(QPen(QColor(180, 157, 94, 7), 1))
        for x in range(0, self.width(), 64):
            pintor.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 64):
            pintor.drawLine(0, y, self.width(), y)


class TarjetaCampeon(QFrame):
    """Contiene arte opcional local, recortado y oscurecido detrás del campeón."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Inicializa la tarjeta sin imagen con el padre recibido; retorna None."""
        super().__init__(parent)
        self.imagen = QPixmap()
        self.setObjectName("localChampionBanner")

    def establecer_imagen(self, imagen: QPixmap) -> None:
        """Sustituye el splash recibido, incluido uno vacío, y repinta; retorna None."""
        self.imagen = imagen
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Recorta arte y superpone degradados legibles en el evento; retorna None."""
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        limite = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        recorte = QPainterPath()
        recorte.addRoundedRect(limite, RADIO_TARJETA, RADIO_TARJETA)
        pintor.setClipPath(recorte)
        pintor.fillRect(limite, QColor(PALETA["superficie"]))
        if not self.imagen.isNull():
            ancho = self.imagen.width()
            alto = self.imagen.height()
            proporcion = limite.width() / limite.height()
            if ancho / alto > proporcion:
                fuente = QRectF(
                    (ancho - alto * proporcion) / 2, 0, alto * proporcion, alto
                )
            else:
                fuente = QRectF(
                    0, (alto - ancho / proporcion) / 2, ancho, ancho / proporcion
                )
            pintor.drawPixmap(limite, self.imagen, fuente)
        velo = QLinearGradient(limite.topLeft(), limite.topRight())
        velo.setColorAt(0, QColor(8, 11, 17, 250))
        velo.setColorAt(0.48, QColor(8, 11, 17, 226))
        velo.setColorAt(1, QColor(18, 15, 12, 160))
        pintor.fillRect(limite, velo)
        sombra = QLinearGradient(0, 0, 0, self.height())
        sombra.setColorAt(0, QColor(182, 154, 80, 18))
        sombra.setColorAt(1, QColor(5, 7, 12, 95))
        pintor.fillRect(limite, sombra)
        pintor.setClipping(False)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.setPen(QPen(QColor(PALETA["oro_oscuro"]), 1))
        pintor.drawRoundedRect(limite, RADIO_TARJETA, RADIO_TARJETA)


class IconoEnmarcado(QLabel):
    """Recorta el bitmap al asignarlo para evitar esquinas cuadradas sobre el marco."""

    def setPixmap(self, imagen: QPixmap) -> None:
        """Recorta las esquinas del pixmap recibido y conserva su proporción; retorna None."""
        if imagen.isNull():
            super().setPixmap(imagen)
            return
        recortada = QPixmap(imagen.size())
        recortada.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(recortada)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        camino = QPainterPath()
        camino.addRoundedRect(QRectF(imagen.rect()), RADIO_ICONO, RADIO_ICONO)
        pintor.setClipPath(camino)
        pintor.drawPixmap(0, 0, imagen)
        pintor.end()
        super().setPixmap(recortada)


class IconoRedondeado(QLabel):
    """QLabel que recorta el pixmap al radio de esquina especificado.

    Parámetros:
        radio: radio de esquina en píxeles que se aplicará al recorte del pixmap.
        Los demás argumentos se delegan a QLabel.
    """

    def __init__(self, *args: object, radio: int = RADIO_ICONO, **kwargs: object) -> None:
        """Inicializa el widget con el radio de esquina indicado."""
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._radio = radio

    def setPixmap(self, imagen: QPixmap) -> None:
        """Recorta las esquinas del pixmap al radio configurado; retorna None."""
        if imagen.isNull():
            super().setPixmap(imagen)
            return
        recortada = QPixmap(imagen.size())
        recortada.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(recortada)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        camino = QPainterPath()
        camino.addRoundedRect(QRectF(imagen.rect()), self._radio, self._radio)
        pintor.setClipPath(camino)
        pintor.drawPixmap(0, 0, imagen)
        pintor.end()
        super().setPixmap(recortada)
