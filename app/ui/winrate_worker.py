"""Worker en hilo secundario (QThread) para actualizar winrates sin bloquear la interfaz."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QThread, Signal

from app.services.winrate_calculator_service import WinrateCalculatorService


class WinrateUpdateWorker(QThread):
    """Hilo secundario para ejecutar el cálculo de winrates de matchups."""

    progress = Signal(int, int, str)  # (current, total, champion_name)
    finished_calculation = Signal(int, int)  # (total_champions, total_matchups)
    error_occurred = Signal(str)

    def __init__(
        self,
        api_key: str,
        account_region: str = "europe",
        platform_region: str = "euw1",
        game_name: str = "",
        tag_line: str = "",
        target_champion_name: str = "",
        champions_path: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.account_region = account_region
        self.platform_region = platform_region
        self.game_name = game_name
        self.tag_line = tag_line
        self.target_champion_name = target_champion_name
        self.champions_path = champions_path
        self._is_cancelled = False

    def cancel(self) -> None:
        """Marca el hilo para cancelación temprana."""
        self._is_cancelled = True

    def run(self) -> None:
        try:
            service = WinrateCalculatorService(
                api_key=self.api_key,
                account_region=self.account_region,
                platform_region=self.platform_region,
                champions_path=self.champions_path,
            )

            def on_progress(current: int, total: int, name: str) -> None:
                self.progress.emit(current, total, name)

            def stop_check() -> bool:
                return self._is_cancelled

            total_champs, total_matchups = service.calculate_all_winrates(
                game_name=self.game_name,
                tag_line=self.tag_line,
                target_champion_name=self.target_champion_name,
                progress_callback=on_progress,
                stop_check=stop_check,
            )

            if not self._is_cancelled:
                self.finished_calculation.emit(total_champs, total_matchups)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
