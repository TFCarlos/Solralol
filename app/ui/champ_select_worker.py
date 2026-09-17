from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QThread, Signal

from app.services.lcu_service import LCUService


class ChampSelectWorker(QThread):
    """Worker en segundo plano para monitorizar la fase de selección de campeón en el cliente de League."""

    champ_select_started = Signal(dict)
    champ_select_updated = Signal(dict)
    champ_select_ended = Signal()

    def __init__(self, lcu_service: LCUService | None = None, poll_interval: float = 1.5, parent=None) -> None:
        super().__init__(parent)
        self.lcu_service = lcu_service or LCUService()
        self.poll_interval = poll_interval
        self._running = True
        self._in_session = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        while self._running:
            try:
                if self.lcu_service.is_champ_select_active():
                    session = self.lcu_service.get_champ_select_session()
                    if session:
                        if not self._in_session:
                            self._in_session = True
                            self.champ_select_started.emit(session)
                        else:
                            self.champ_select_updated.emit(session)
                else:
                    if self._in_session:
                        self._in_session = False
                        self.champ_select_ended.emit()
            except Exception:
                if self._in_session:
                    self._in_session = False
                    self.champ_select_ended.emit()

            time.sleep(self.poll_interval)
