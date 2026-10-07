"""Componente para representar iconos Qt sin perder su pixmap fuente."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class IconoPixmap(QLabel):
    """Ajusta un pixmap fuente al área visible y al factor de escala de Qt."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Crea una etiqueta de icono con límites de tamaño compartidos.

        Args:
            parent: Widget padre opcional.
        Returns:
            None.
        """
        super().__init__(parent)
        self._pixmap_fuente = QPixmap()
        self.setMinimumSize(16, 16)
        self.setMaximumSize(64, 64)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setContentsMargins(1, 1, 1, 1)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def establecer_pixmap_fuente(self, pixmap: QPixmap) -> None:
        """Guarda el recurso original y actualiza su representación visible.

        Args:
            pixmap: Pixmap sin recortar que se conservará como fuente.
        Returns:
            None.
        """
        self._pixmap_fuente = QPixmap(pixmap) if not pixmap.isNull() else QPixmap()
        self._ajustar_pixmap()

    def obtener_pixmap_fuente(self) -> QPixmap:
        """Devuelve una copia de la fuente sin escalar.

        Args:
            None.
        Returns:
            Copia del pixmap fuente, vacía si no hay recurso.
        """
        return QPixmap(self._pixmap_fuente)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Vuelve a encajar el recurso al cambiar la geometría de la etiqueta.

        Args:
            event: Evento Qt con el tamaño nuevo.
        Returns:
            None.
        """
        super().resizeEvent(event)
        self._ajustar_pixmap()

    def _ajustar_pixmap(self) -> None:
        """Escala suavemente la fuente al contenido usando el DPR actual.

        Args:
            None.
        Returns:
            None.
        """
        if self._pixmap_fuente.isNull():
            super().setPixmap(QPixmap())
            return
        area = self.contentsRect().size()
        factor = max(1.0, self.devicePixelRatioF())
        destino = QSize(round(area.width() * factor), round(area.height() * factor))
        if destino.isEmpty():
            return
        visible = self._pixmap_fuente.scaled(
            destino,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        visible.setDevicePixelRatio(factor)
        super().setPixmap(visible)
