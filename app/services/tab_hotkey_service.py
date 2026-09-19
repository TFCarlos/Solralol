"""Detección global de la tecla TAB para el overlay.

En Windows se usa ``GetAsyncKeyState`` por polling ligero (sin dependencias
externas ni hooks globales): el overlay puede mostrarse solo mientras TAB está
pulsado, como el marcador del juego. Fuera de Windows el servicio queda
desactivado y los paneles se comportan como siempre.

El módulo solo depende de Qt, de modo que puede probarse sin interfaz.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal


VK_TAB = 0x09
POLL_MS = 100


def _default_reader() -> bool:
    """True mientras TAB está pulsado (solo Windows)."""
    import ctypes

    state = ctypes.windll.user32.GetAsyncKeyState(VK_TAB)

    return bool(state & 0x8000)


def _windll_available() -> bool:
    try:
        import ctypes

        ctypes.windll.user32.GetAsyncKeyState
    except Exception:  # noqa: BLE001 - cualquier fallo desactiva el servicio
        return False

    return True


class TabHotkeyService(QObject):
    """Vigila TAB en segundo plano y avisa solo en cada flanco.

    ``reader`` permite inyectar otra función de lectura en las pruebas.
    """

    tab_changed = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        reader: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)

        if reader is not None:
            self._reader = reader
            self.available = True
        else:
            self._reader = _default_reader
            self.available = _windll_available()

        self._down = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    @property
    def is_tab_down(self) -> bool:
        return self._down

    def start(self) -> None:
        if self.available and not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def _poll(self) -> None:
        try:
            down = bool(self._reader())
        except Exception:  # noqa: BLE001 - el teclado nunca rompe el overlay
            return

        if down == self._down:
            return

        self._down = down
        self.tab_changed.emit(down)
