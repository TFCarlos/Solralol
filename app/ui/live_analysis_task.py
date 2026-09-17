"""Trabajos de análisis sin acceso a widgets; resultados entregados al hilo GUI."""
from PySide6.QtCore import QObject, QRunnable, Signal


class TaskSignals(QObject):
    finished = Signal(object, object, object)


class AnalysisTask(QRunnable):
    def __init__(self, token, function):
        super().__init__()
        self.token = token
        self.function = function
        self.signals = TaskSignals()

    def run(self):
        result, error = None, None
        try:
            result = self.function()
        except Exception as exc:
            error = str(exc)
        try:
            self.signals.finished.emit(self.token, result, error)
        except RuntimeError:
            # Qt may already have shut down. Never touch widgets from here.
            pass
