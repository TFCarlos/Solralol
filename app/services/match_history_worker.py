from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app.services.match_history_cache import MatchHistoryCache
from app.services.riot_api_service import RiotApiError, RiotApiService


class MatchHistoryWorker(QObject):
    """Descarga historial y detalles sin bloquear la interfaz."""

    history_ready = Signal(list)
    history_failed = Signal(str, int)

    detail_ready = Signal(dict)
    detail_failed = Signal(str, int)

    @staticmethod
    def _service(
        api_key: str,
        account_region: str,
        platform_region: str,
    ) -> RiotApiService:
        return RiotApiService(
            api_key=api_key,
            account_region=account_region,
            platform_region=platform_region,
            cache=MatchHistoryCache(),
        )

    @Slot(str, str, str, str, str, int)
    def load_history(
        self,
        api_key: str,
        game_name: str,
        tag_line: str,
        account_region: str,
        platform_region: str,
        count: int,
    ) -> None:
        try:
            service = self._service(
                api_key,
                account_region,
                platform_region,
            )
            history = service.get_recent_matches(
                game_name=game_name,
                tag_line=tag_line,
                count=count,
            )
        except RiotApiError as error:
            self.history_failed.emit(
                str(error),
                error.retry_after or 0,
            )
            return
        except Exception as error:
            self.history_failed.emit(
                f"No se pudo cargar el historial: {error}",
                0,
            )
            return

        self.history_ready.emit(history)

    @Slot(str, str, str, str, str, str)
    def load_match_detail(
        self,
        api_key: str,
        game_name: str,
        tag_line: str,
        account_region: str,
        platform_region: str,
        match_id: str,
    ) -> None:
        """Solicita siempre el detalle de la partida indicada."""
        if not match_id:
            self.detail_failed.emit(
                "La partida no tiene un match_id válido.",
                0,
            )
            return

        try:
            service = self._service(
                api_key,
                account_region,
                platform_region,
            )

            print(
                f"Solicitando detalle Riot API: match_id={match_id}",
                flush=True,
            )

            detail = service.get_match_detail(
                game_name=game_name,
                tag_line=tag_line,
                match_id=match_id,
            )

            if not isinstance(detail, dict):
                raise ValueError(
                    "La API no devolvió un detalle válido."
                )

            detail.setdefault("match_id", match_id)
            detail.setdefault("source", "riot_api")
            detail.setdefault(
                "final_sync",
                {"status": "synced"},
            )

            print(
                f"Detalle histórico recibido: match_id={match_id}",
                flush=True,
            )

        except RiotApiError as error:
            self.detail_failed.emit(
                str(error),
                error.retry_after or 0,
            )
            return
        except Exception as error:
            self.detail_failed.emit(
                f"No se pudo abrir la partida: {error}",
                0,
            )
            return

        self.detail_ready.emit(detail)
