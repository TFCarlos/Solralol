from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app.services.game_service import GameService
from app.services.live_match_tracker import LiveMatchTracker


class LiveDataWorker(QObject):
    """Lee la API local y actualiza el análisis LIVE en tiempo real."""

    snapshot_ready = Signal(dict)
    snapshot_failed = Signal(str)
    live_analysis_ready = Signal(dict)
    live_analysis_failed = Signal(str)

    def __init__(self, item_catalog: dict[str, Any]) -> None:
        super().__init__()
        self.game_service = GameService()
        self.tracker = LiveMatchTracker(item_catalog)
        self.last_game_signature = ""

    @Slot()
    def read_snapshot(self) -> None:
        try:
            snapshot = self.game_service.get_game_snapshot()
            if snapshot is None:
                self._finish_if_needed()
                self.snapshot_failed.emit(
                    "League no está en una partida activa."
                )
                return

            snapshot = deepcopy(snapshot)
            self._update_tracker(snapshot)
            self.snapshot_ready.emit(snapshot)
            self._emit_live_analysis()
        except Exception as error:
            self.snapshot_failed.emit(
                f"No se pudo leer la partida: {error}"
            )
            self.live_analysis_failed.emit(str(error))

    def _update_tracker(self, snapshot: dict[str, Any]) -> None:
        local_player = snapshot.get("local_player", {})
        game_time = snapshot.get("game_time", 0)
        signature = "|".join(
            (
                str(snapshot.get("game_mode", "")),
                str(local_player.get("riotId", "")),
                str(local_player.get("summonerName", "")),
                str(snapshot.get("local_team", "")),
            )
        )

        if not self.tracker.is_tracking or (
            self.last_game_signature
            and signature != self.last_game_signature
            and float(game_time) < 10
        ):
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

    def _finish_if_needed(self) -> None:
        if not self.tracker.is_tracking:
            self.last_game_signature = ""
            return

        completed = self.tracker.finish()
        self.last_game_signature = ""
        if completed is not None:
            completed["live"] = False
            completed["source"] = "live_client_data_api"

    @Slot()
    def finish_tracking(self) -> None:
        self._finish_if_needed()
