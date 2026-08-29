from __future__ import annotations


from typing import Any


from PySide6.QtCore import (
    QObject,
    Signal,
    Slot,
)


from app.services.match_history_cache import MatchHistoryCache
from app.services.postgame_sync_service import (
    PostgameSyncService,
)
from app.services.riot_api_service import RiotApiService



class PostgameSyncWorker(QObject):
    """
    Ejecuta la sincronización Match-V5 fuera del hilo de interfaz.


    No modifica widgets ni archivos directamente desde este hilo.
    Devuelve la sesión sincronizada mediante señales Qt.
    """


    sync_ready = Signal(dict)
    sync_failed = Signal(str)


    @Slot(
        dict,
        str,
        str,
        str,
        str,
        str,
    )
    def sync_session(
        self,
        session: dict[str, Any],
        api_key: str,
        game_name: str,
        tag_line: str,
        account_region: str,
        platform_region: str,
    ) -> None:
        print(f"[WORKER] Iniciando sincronización para {session.get('session_id')}")
        
        try:
            print(f"[WORKER] Creando RiotApiService...")
            
            riot_service = RiotApiService(
                api_key=api_key,
                account_region=account_region,
                platform_region=platform_region,
                cache=MatchHistoryCache(),
            )

            print(f"[WORKER] Creando PostgameSyncService...")

            service = PostgameSyncService(
                api_key=api_key,
                game_name=game_name,
                tag_line=tag_line,
                account_region=account_region,
                platform_region=platform_region,
                riot_api_service=riot_service,
            )

            print(f"[WORKER] Llamando a service.sync_session()...")

            updated_session = service.sync_session(
                session
            )

            print(f"[WORKER] Sincronización completada: {updated_session.get('final_sync', {}).get('status')}")

            self.sync_ready.emit(
                updated_session
            )

        except Exception as error:
            print(f"[WORKER] Error: {error}")
            import traceback
            traceback.print_exc()
            
            self.sync_failed.emit(
                f"No se pudo sincronizar la partida: {error}"
            )