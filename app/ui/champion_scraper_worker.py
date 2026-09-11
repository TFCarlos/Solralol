"""Worker Qt para descargar U.GG sin congelar la ventana de análisis."""
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.services.champion_scraper_service import ChampionScraperService
from data_dragon import download_all_rune_icons


class ChampionScraperWorker(QThread):
    progress = Signal(int, int, str)
    finished_scraping = Signal(int, int)
    error_occurred = Signal(str)

    def __init__(self, target_champion_name: str = "", champions_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self.target_champion_name = target_champion_name
        self.champions_path = champions_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            service = ChampionScraperService(champions_path=self.champions_path)
            total, updated = service.actualizar_todo(
                target_champion_name=self.target_champion_name,
                progress_callback=lambda current, count, name: self.progress.emit(current, count, name),
                stop_check=lambda: self._cancelled,
            )
            if not self._cancelled:
                # Se hace en el hilo de sincronización para que el panel no
                # muestre marcadores "R" cuando lleguen runas nuevas.
                download_all_rune_icons("16.17.1")
            if not self._cancelled:
                self.finished_scraping.emit(total, updated)
        except Exception as error:
            self.error_occurred.emit(str(error))
