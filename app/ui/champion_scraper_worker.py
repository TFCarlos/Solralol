"""Worker Qt para descargar U.GG sin congelar la ventana de análisis."""

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.services.champion_scraper_service import ChampionScraperService
from app.services.rangos_campeones import RANGO_PREDETERMINADO


class ChampionScraperWorker(QThread):
    progress = Signal(int, int, str)
    finished_scraping = Signal(int, int)
    error_occurred = Signal(str)

    def __init__(
        self,
        target_champion_name: str = "",
        champions_path: Path | None = None,
        rank: str = RANGO_PREDETERMINADO,
        parent: QObject | None = None,
    ) -> None:
        """Recibe selección y raíz para actualizar matrices completas fuera de Qt; retorna None."""
        super().__init__(parent)
        self.target_champion_name = target_champion_name
        self.champions_path = champions_path
        self.rank = rank
        self._cancelled = False

    def cancel(self) -> None:
        """Solicita cancelación entre peticiones sin borrar datos; retorna None."""
        self._cancelled = True

    def run(self) -> None:
        """Genera datos con progreso y comunica resultado o error por señales; retorna None."""
        try:
            service = ChampionScraperService(
                champions_path=self.champions_path, rank=self.rank
            )
            total, updated = service.actualizar_todo(
                target_champion_name=self.target_champion_name,
                progress_callback=lambda current, count, name: self.progress.emit(
                    current, count, name
                ),
                stop_check=lambda: self._cancelled,
            )
            if not self._cancelled:
                self.finished_scraping.emit(total, updated)
        except Exception as error:
            self.error_occurred.emit(str(error))
