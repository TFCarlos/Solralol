from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.services.game_service import GameService
from app.services.live_match_tracker import LiveMatchTracker

_LOGGER = logging.getLogger(__name__)


class LiveDataWorker(QObject):
    """Lee League y actualiza la sesión LIVE en segundo plano."""

    snapshot_ready = Signal(object)
    read_failed = Signal(str)
    live_analysis_ready = Signal(object)
    live_analysis_failed = Signal(str)
    #: La API local dejó de responder después de estar en partida: ha terminado.
    game_ended = Signal()
    game_finished = Signal(object)
    GAME_END_FAILURE_THRESHOLD = 3

    def __init__(
        self,
        item_catalog: dict[str, Any] | None = None,
        game_version: str = "",
    ) -> None:
        super().__init__()
        self.game_service = GameService()
        #: Este tracker solo alimenta el análisis en vivo (sus snapshots de 2 s
        #: y su sesión en memoria): la partida que se guarda en disco es la del
        #: tracker de la ventana. Sin ``persist`` cada partida se escribía dos
        #: veces, con dos ids distintos, y el historial duplicaba el trabajo y
        #: el tamaño del fichero de sesiones.
        self.tracker = LiveMatchTracker(
            item_catalog or {},
            game_version=game_version,
            persist=False,
        )
        self.last_game_signature = ""
        self.was_in_game = False
        self.consecutive_read_failures = 0

    @Slot()
    def read_snapshot(self) -> None:
        """Lee telemetría y tolera fallos transitorios antes de cerrar LIVE.

        Parámetros: ninguno.
        Retorno: None; emite el fin solo tras varios sondeos fallidos seguidos.
        """
        try:
            snapshot = self.game_service.get_game_snapshot()

            if snapshot is None:
                self._handle_snapshot_failure("League no está en una partida activa.")
                return

            snapshot = deepcopy(snapshot)
            self._update_tracker(snapshot)
            if self.was_in_game and self.consecutive_read_failures:
                _LOGGER.info(
                    "Telemetría LIVE recuperada tras %d sondeos fallidos",
                    self.consecutive_read_failures,
                )
            self.consecutive_read_failures = 0
            self.was_in_game = True
            self.snapshot_ready.emit(snapshot)
            self._emit_live_analysis()
        except Exception as error:
            self._handle_snapshot_failure(f"No se pudo leer la partida: {error}")
            self.live_analysis_failed.emit(str(error))

    def _handle_snapshot_failure(self, message: str) -> None:
        """Registra una lectura fallida y confirma el fin tras el umbral.

        Parámetros: mensaje de diagnóstico sin credenciales.
        Retorno: None; conserva la sesión hasta tres fallos consecutivos.
        """
        self.consecutive_read_failures += 1
        if self.consecutive_read_failures == 1:
            _LOGGER.warning("Fallo de telemetría LIVE; se conserva el estado actual")
        self._emit_read_failed(message)
        if (
            not self.was_in_game
            or self.consecutive_read_failures < self.GAME_END_FAILURE_THRESHOLD
        ):
            return
        _LOGGER.info(
            "Partida LIVE confirmada como finalizada tras %d sondeos fallidos",
            self.consecutive_read_failures,
        )
        completed = self._finish_tracking()
        if completed is not None:
            self.game_finished.emit(completed)
        self.was_in_game = False
        self.last_game_signature = ""
        self.consecutive_read_failures = 0
        self._emit_game_ended()

    def _update_tracker(self, snapshot: dict[str, Any]) -> None:
        local_player = snapshot.get("local_player", {})
        game_time = self._to_float(
            snapshot.get("game_time", 0)
        )
        signature = "|".join(
            (
                str(snapshot.get("game_mode", "")),
                str(local_player.get("riotId", "")),
                str(local_player.get("summonerName", "")),
                str(snapshot.get("local_team", "")),
            )
        )

        new_game = (
            not self.tracker.is_tracking
            or (
                self.last_game_signature
                and signature != self.last_game_signature
                and game_time < 10
            )
        )

        if new_game:
            if self.tracker.is_tracking:
                completed = self._finish_tracking()
                if completed is not None:
                    self.game_finished.emit(completed)
                    self._emit_game_ended()
            self.tracker.start(snapshot)
        else:
            self.tracker.update(snapshot)

        self.last_game_signature = signature

    def _emit_live_analysis(self) -> None:
        session = self.tracker.get_live_session()
        if session is None:
            return

        session["source"] = "live_client_data_api"
        session["live"] = True
        session["final_sync"] = {
            "status": "live",
            "match_id": None,
            "synced_at": None,
        }
        self.live_analysis_ready.emit(session)

    def _finish_tracking(self) -> dict[str, Any] | None:
        """Finaliza y entrega la sesión para su persistencia asíncrona."""
        return self.tracker.finish()

    def _emit_read_failed(self, message: str) -> None:
        try:
            self.read_failed.emit(message)
        except RuntimeError:
            pass

    def _emit_game_ended(self) -> None:
        try:
            self.game_ended.emit()
        except RuntimeError:
            pass

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
