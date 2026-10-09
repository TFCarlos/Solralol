from __future__ import annotations

from threading import Lock
from typing import Any

from PySide6.QtCore import QThread, Signal

from app.services.match_ai_analyzer_service import MatchAIAnalyzerService

_BLOQUEO_ANALISIS = Lock()
_SESIONES_ANALIZADAS: set[str] = set()


class MatchAIWorker(QThread):
    """
    QThread worker para ejecutar el análisis de partida con IA de forma asíncrona
    sin congelar la interfaz de PySide6.
    """

    finished_analysis = Signal(object, str, str, str, str)
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
        self.session_id = str(session.get("session_id") or "")
        if not self.session_id:
            raise ValueError("La partida no tiene un identificador estable para asociar el análisis.")
        with _BLOQUEO_ANALISIS:
            if self.session_id in _SESIONES_ANALIZADAS:
                raise RuntimeError("Ya hay un análisis en curso para esta partida.")
            _SESIONES_ANALIZADAS.add(self.session_id)

    def run(self) -> None:
        try:
            service = MatchAIAnalyzerService()
            analysis, response, model_used, fingerprint = service.analyze_match(
                self.session,
                self.api_key,
            )
            self.finished_analysis.emit(
                analysis, response, model_used, fingerprint, self.session_id
            )
        except Exception as err:
            self.error_occurred.emit(str(err))
        finally:
            with _BLOQUEO_ANALISIS:
                _SESIONES_ANALIZADAS.discard(self.session_id)

