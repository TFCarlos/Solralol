from __future__ import annotations

from typing import Any
from PySide6.QtCore import QThread, Signal

from app.services.champion_ai_analyzer_service import ChampionAIAnalyzerService


class ChampionAIWorker(QThread):
    """Worker QThread para realizar el re-análisis de campeones con Gemini AI en segundo plano."""

    finished_reanalysis = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, champion_data: dict[str, Any], api_key: str, parent=None) -> None:
        super().__init__(parent)
        self.champion_data = champion_data
        self.api_key = api_key
        self.service = ChampionAIAnalyzerService()

    def run(self) -> None:
        try:
            updated_data = self.service.reanalyze_champion(self.champion_data, self.api_key)
            self.finished_reanalysis.emit(updated_data)
        except Exception as error:
            self.error_occurred.emit(str(error))

