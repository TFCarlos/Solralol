from __future__ import annotations

from typing import Any
from PySide6.QtCore import QThread, Signal

from app.services.match_ai_analyzer_service import MatchAIAnalyzerService


class MatchAIWorker(QThread):
    """
    QThread worker para ejecutar el análisis de partida con IA de forma asíncrona
    sin congelar la interfaz de PySide6.
    """

    finished_analysis = Signal(str, str)  # (markdown_text, model_name)
    error_occurred = Signal(str)

    def __init__(
        self,
        session: dict[str, Any],
        api_key: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.api_key = api_key

    def run(self) -> None:
        try:
            service = MatchAIAnalyzerService()
            markdown_result, model_used = service.analyze_match(
                self.session,
                self.api_key,
            )
            self.finished_analysis.emit(markdown_result, model_used)
        except Exception as err:
            self.error_occurred.emit(str(err))

