"""Pantalla de carga del arranque, sin bloquear el hilo de la interfaz.

Antes de poder construir la ventana principal hay que resolver el catálogo de
objetos de Data Dragon, que la primera vez se descarga de la red. Hacerlo en
el hilo de la interfaz dejaba al usuario mirando una consola congelada; aquí
el trabajo va a un worker (``AsyncTask``) y el hilo principal se queda
animando el indicador de progreso y contando el tiempo transcurrido.

Uso::

    loader = StartupWindow("Descargando catálogo de objetos…")
    loader.finished.connect(on_catalog_ready)
    loader.show()
    loader.start(load_item_catalog)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.ui.async_task import AsyncTask, run_async

#: Estilo propio (la ventana principal aún no existe cuando se muestra).
STARTUP_STYLE = """
QWidget#startupWindow {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(21, 52, 93, 245),
        stop: 1 rgba(7, 11, 20, 250)
    );
    border: 1px solid rgba(97, 148, 211, 90);
    border-radius: 18px;
    font-family: "Segoe UI";
}
QLabel#startupBrand {
    color: #d9ae4f;
    font-size: 26px;
    font-weight: 800;
    letter-spacing: 3px;
}
QLabel#startupMessage {
    color: #e8f0ff;
    font-size: 13px;
}
QLabel#startupElapsed {
    color: #9caec9;
    font-size: 11px;
}
QLabel#startupHint {
    color: #7d8ea6;
    font-size: 11px;
}
QProgressBar#startupBar {
    border: 1px solid rgba(97, 148, 211, 90);
    border-radius: 7px;
    background: rgba(8, 16, 30, 200);
    height: 12px;
    text-align: center;
}
QProgressBar#startupBar::chunk {
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #1f6fe0,
        stop: 1 #4fa3ff
    );
    border-radius: 6px;
}
"""


class StartupWindow(QWidget):
    """Ventana de espera con indicador animado y trabajo en background."""

    #: ``(resultado, error)`` — *error* es ``str`` o ``None``.
    finished = Signal(object, object)

    def __init__(
        self,
        message: str = "Cargando…",
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("startupWindow")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(460, 220)
        self.setStyleSheet(STARTUP_STYLE)

        self._task: AsyncTask | None = None
        self._elapsed = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 26)
        layout.setSpacing(12)

        brand = QLabel("SOLRALOL")
        brand.setObjectName("startupBrand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand)

        self.message_label = QLabel(message)
        self.message_label.setObjectName("startupMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("startupBar")
        # Rango vacío: la barra se anima sola (indicador de ocupado) y prueba
        # que el hilo principal sigue procesando eventos.
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.elapsed_label = QLabel("0,0 s")
        self.elapsed_label.setObjectName("startupElapsed")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.elapsed_label)

        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("startupHint")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(bool(hint))
        layout.addWidget(self.hint_label)

        layout.addStretch(1)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._on_tick)

    # -- API pública ----------------------------------------------------

    def start(self, task: Callable[[], Any]) -> AsyncTask:
        """Lanza *task* en un worker y avisa con ``finished`` al terminar.

        Devuelve la tarea para poder conservar la referencia o cancelarla.
        """
        self._elapsed = 0.0
        self._tick_timer.start()
        self.move_to_center()

        self._task = run_async(task, on_finished=self._on_worker_finished)

        return self._task

    def move_to_center(self) -> None:
        """Centra la ventana en la pantalla principal."""
        screen = self.screen()

        if screen is None:
            return

        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            area.center().y() - self.height() // 2,
        )

    def set_message(self, message: str) -> None:
        """Cambia el texto de estado (p. ej. al construir la UI principal)."""
        self.message_label.setText(message)

    def stop(self) -> None:
        """Detiene el contador y cierra la ventana."""
        self._tick_timer.stop()
        self.close()

    # -- interno --------------------------------------------------------

    def _on_tick(self) -> None:
        # Contador honesto de espera: si avanza, el bucle de Qt está vivo.
        self._elapsed += self._tick_timer.interval() / 1000.0
        self.elapsed_label.setText(
            f"{self._elapsed:.1f} s".replace(".", ",")
        )

    def _on_worker_finished(self, _token, result, error) -> None:
        self._task = None
        self._tick_timer.stop()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.finished.emit(result, error)


def run_startup_task(
    task: Callable[[], Any],
    on_finished: Callable[[Any, Optional[str]], None],
    *,
    message: str = "Cargando…",
    hint: str = "",
) -> tuple[StartupWindow, AsyncTask]:
    """Atajo: muestra la ventana de carga y lanza *task* en un worker.

    *on_finished* se llama en el hilo de la GUI con ``(resultado, error)``.
    """
    window = StartupWindow(message=message, hint=hint)

    def relay(result: Any, error: Optional[str]) -> None:
        # El llamador crea su ventana antes de cerrar la de carga: si esta
        # fuera la última ventana, cerrarla antes cerraba la aplicación.
        on_finished(result, error)
        window.stop()

    window.finished.connect(relay)
    window.show()
    task_handle = window.start(task)

    return window, task_handle
