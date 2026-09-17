"""Iconos del draft: caché acotada y descargas fuera del hilo de Qt."""
from __future__ import annotations

import time
from collections import OrderedDict
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid


class _Result(QObject):
    ready = Signal(object, object)


class _Download(QRunnable):
    def __init__(self, key: tuple, resolver: Callable) -> None:
        super().__init__()
        self.key = key
        self.resolver = resolver
        self.result = _Result()

    def run(self) -> None:
        try:
            path = self.resolver(download=True)
        except Exception:
            path = None
        try:
            self.result.ready.emit(self.key, path)
        except RuntimeError:
            # QApplication puede haber destruido los QObject mientras una
            # petición terminaba. No acceder a widgets ni bloquear el cierre.
            pass


class DraftIconCache(QObject):
    """QPixmap solo en GUI; cada recurso pendiente se descarga una sola vez."""

    LIMIT = 256
    RETRY_SECONDS = 60.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pixmaps = OrderedDict()
        self.pending: dict[tuple, _Download] = {}
        self.failed = OrderedDict()
        self.targets: dict[QLabel, tuple] = {}

    def assign(self, label: QLabel, key: tuple | None, size: int,
               resolver: Callable | None = None, placeholder: str = "—") -> None:
        target = (key, size)
        changed = self.targets.get(label) != target
        self.targets[label] = target
        if changed:
            label.setText(placeholder)
        if key is None:
            return
        cache_key = (key, size)
        if cache_key in self.pixmaps:
            self.pixmaps.move_to_end(cache_key)
            pixmap = self.pixmaps[cache_key]
            if changed or label.pixmap().isNull():
                label.setPixmap(pixmap)
            return
        if key in self.pending:
            return
        if time.monotonic() - self.failed.get(key, float("-inf")) < self.RETRY_SECONDS:
            return
        try:
            path = resolver(download=False)
        except Exception:
            path = None
        if path:
            self._ready(key, path)
            return
        task = _Download(key, resolver)
        task.result.ready.connect(self._ready, Qt.ConnectionType.QueuedConnection)
        self.pending[key] = task
        QThreadPool.globalInstance().start(task)

    @Slot(object, object)
    def _ready(self, key: tuple, path) -> None:
        self.pending.pop(key, None)
        icon = QPixmap(str(path)) if path else QPixmap()
        if icon.isNull():
            self.failed[key] = time.monotonic()
            while len(self.failed) > self.LIMIT:
                self.failed.popitem(last=False)
            return
        self.failed.pop(key, None)
        for label, (wanted, size) in list(self.targets.items()):
            if not isValid(label):
                self.targets.pop(label, None)
                continue
            # Una respuesta tardía nunca sobrescribe un campeón nuevo.
            if wanted != key:
                continue
            cache_key = (key, size)
            if cache_key not in self.pixmaps:
                self.pixmaps[cache_key] = icon.scaled(
                    size, size, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            label.setPixmap(self.pixmaps[cache_key])
        while len(self.pixmaps) > self.LIMIT:
            self.pixmaps.popitem(last=False)