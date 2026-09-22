"""Utilidad genérica para ejecutar funciones pesadas fuera del hilo de Qt.

Proporciona ``AsyncTask``: un ``QRunnable`` que ejecuta una función en un
pool de hilos (``QThreadPool.globalInstance()``) y entrega el resultado —o
el error— al hilo de la GUI mediante señales conectadas con
``QueuedConnection``.

El diseño sigue el patrón establecido por ``AnalysisTask`` y
``DraftIconCache``: nunca se tocan widgets desde el worker y las señales
usan conexión asíncrona para evitar reentradas.

Para el caso más habitual —una operación suelta cuyo resultado publica el
hilo de la GUI— está :func:`run_async`; para varias peticiones de la misma
naturaleza donde solo interesa la última, :class:`TaskManager`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal


class TaskSignals(QObject):
    """Señales para comunicación worker → GUI."""

    #: (token, result, error)  — error es *str* o *None*
    finished = Signal(object, object, object)
    #: (current, total, message) — progreso opcional
    progress = Signal(int, int, str)
    #: () — emitido siempre que el worker se cancele
    cancelled = Signal()


class AsyncTask(QRunnable):
    """Ejecuta *function* en segundo plano y notifica al hilo GUI.

    Parámetros
    ----------
    token
        Valor opaco que se devuelve en ``finished`` para poder identificar
        qué resultado corresponde a qué solicitud (útil para descartar
        resultados obsoletos).
    function
        Callable sín args que realiza el trabajo pesado y devuelve el
        resultado.
    progress_callback
        Si se pasa, se inyecta como primer argumento a *function* y permite
        informar progreso vía ``signals.progress``.
    auto_delete
        Si es ``True`` (por defecto) el runnable se marca para borrado
        automático tras ejecutarse.
    """

    def __init__(
        self,
        token: Any,
        function: Callable[..., Any],
        *,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        auto_delete: bool = True,
    ) -> None:
        super().__init__()
        self.token = token
        self.function = function
        self._progress_callback = progress_callback
        self._cancelled = False
        self.signals = TaskSignals()
        self.setAutoDelete(auto_delete)

    # -- API pública ---------------------------------------------------

    def cancel(self) -> None:
        """Marca la tarea para cancelación. El worker comprueba el flag
        entre operaciones. No fuerza la interrupción del hilo."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    # -- QRunnable -----------------------------------------------------

    def run(self) -> None:
        try:
            if self._progress_callback is not None:
                result = self.function(self._progress_callback)
            else:
                result = self.function()
        except Exception as exc:  # noqa: BLE001 — capturamos TODO error del worker
            try:
                self.signals.finished.emit(self.token, None, str(exc))
            except RuntimeError:
                # QApplication destruido durante el cierre.
                pass
            return

        try:
            if self._cancelled:
                self.signals.cancelled.emit()
            self.signals.finished.emit(self.token, result, None)
        except RuntimeError:
            pass


class TaskManager:
    """Orquesta tareas asíncronas con semántica *supersede*.

    Mantiene una referencia a la tarea activa por clave. Cuando se
    solicita una nueva tarea con la misma clave, la anterior se marca
    como cancelada (aunque ya esté en ejecución) y se reemplaza. Al
    recibir el resultado se descarta si ya no es el de la última tarea
    solicitada con esa clave.

    Esto evita que resultados tardíos de una operación anterior
    sobrescriban los de una más reciente —exactamente el patrón usado en
    ``LiveMatchAnalysisDialog._prepare_session``.
    """

    def __init__(self) -> None:
        self._active: dict[Any, AsyncTask] = {}
        self._pool = QThreadPool.globalInstance()

    def start(
        self,
        key: Any,
        function: Callable[..., Any],
        *,
        on_finished: Callable[[Any, Any, Optional[str]], None],
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        auto_delete: bool = True,
    ) -> AsyncTask:
        """Programa *function* en background.

        Si ya había una tarea con la misma *key*, se cancela y su resultado
        —cuando llegue— se descarta: *on_finished* solo recibe el de la
        última tarea solicitada con esa clave.
        """
        previous = self._active.pop(key, None)

        if previous is not None:
            previous.cancel()

        task = AsyncTask(
            token=key,
            function=function,
            progress_callback=on_progress,
            auto_delete=auto_delete,
        )

        def deliver(token, result, error, _task=task, _key=key) -> None:
            # Un resultado viejo (ya sustituido por otra petición con la
            # misma clave) no debe tocar el estado que pinta la GUI.
            if self._active.get(_key) is not _task:
                return

            self._active.pop(_key, None)
            on_finished(token, result, error)

        task.signals.finished.connect(
            deliver,
            Qt.ConnectionType.QueuedConnection,
        )

        self._active[key] = task
        self._pool.start(task)

        return task

    def cancel(self, key: Any) -> None:
        """Cancela y descarta la tarea asociada a *key*."""
        task = self._active.pop(key, None)
        if task is not None:
            task.cancel()

    def cancel_all(self) -> None:
        """Cancela todas las tareas activas."""
        for task in list(self._active.values()):
            task.cancel()
        self._active.clear()

    @property
    def active_count(self) -> int:
        return len(self._active)


#: Tareas de ``run_async`` que aún no han entregado su resultado. Mantener la
#: referencia es lo que impide que el recolector de basura se lleve el
#: ``QRunnable`` (y con él sus señales) antes de que la GUI reciba el aviso.
_PENDING: set[AsyncTask] = set()


def run_async(
    function: Callable[..., Any],
    *,
    on_finished: Callable[[Any, Any, Optional[str]], None],
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    token: Any = None,
) -> AsyncTask:
    """Lanza *function* en el pool de hilos y entrega el resultado a la GUI.

    Azúcar para el caso más común (una operación suelta que el llamador
    guarda en un atributo): devuelve la tarea recién lanzada para que quien
    la pidió mantenga su referencia —y pueda cancelarla— hasta recibir
    *on_finished*. La tarea queda además en la lista interna de pendientes,
    de modo que el resultado llega aunque el llamador descarte la referencia.

    *on_finished* se invoca **en el hilo de la GUI** con la firma
    ``(token, result, error)``; si el worker lanzó una excepción, *result*
    es ``None`` y *error* su mensaje.
    """
    task = AsyncTask(
        token=token,
        function=function,
        progress_callback=on_progress,
    )

    def deliver(tok, result, error, _task=task) -> None:
        _PENDING.discard(_task)
        on_finished(tok, result, error)

    task.signals.finished.connect(
        deliver,
        Qt.ConnectionType.QueuedConnection,
    )

    _PENDING.add(task)
    QThreadPool.globalInstance().start(task)

    return task
