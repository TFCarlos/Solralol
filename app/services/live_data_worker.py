from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.services.game_service import GameService
from app.services.live_match_tracker import LiveMatchTracker


class LiveDataWorker(QObject):
    """Lee League y actualiza la sesión LIVE en segundo plano."""

    snapshot_ready = Signal(object)
    read_failed = Signal(str)
    live_analysis_ready = Signal(object)
    live_analysis_failed = Signal(str)
    #: La API local dejó de responder después de estar en partida: ha terminado.
    game_ended = Signal()

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

    @Slot()
    def read_snapshot(self) -> None:
        try:
            snapshot = self.game_service.get_game_snapshot()

            if snapshot is None:
                was_in_game = self.was_in_game
                self._finish_tracking()
                self.was_in_game = False
                self.last_game_signature = ""
                self._emit_read_failed(
                    "League no está en una partida activa."
                )

                if was_in_game:
                    self._emit_game_ended()

                return

            snapshot = deepcopy(snapshot)
            self._update_tracker(snapshot)
            self.was_in_game = True
            self.snapshot_ready.emit(snapshot)
            self._emit_live_analysis()
        except Exception as error:
            self._emit_read_failed(
                f"No se pudo leer la partida: {error}"
            )
            self.live_analysis_failed.emit(str(error))

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
                self._finish_tracking()
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

    def _finish_tracking(self) -> None:
        """Cierra la sesión en curso (la guarda el tracker de la ventana)."""
        self.tracker.finish()

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
