"""Application facade for Electron.

The facade reuses Solralol's existing local repositories and dispatches the
bounded operations exposed to the Electron renderer.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import UTC, datetime
from typing import Any

from _paths import DATA_DIR
from app.services.home_dashboard_analytics import (
    build_home_counter_summary,
    build_ranked_dashboard_analytics,
    gold_difference_at_15,
)
from app.services.home_history_service import (
    HomeHistoryRepository,
    LCUHomeProvider,
    _home_number,
    aggregate_soloq_champion_performance,
    analyze_home_history,
    analyze_recent_soloq_performance,
    calculate_soloq_rolling_winrate,
)
from app.services.rangos_campeones import CLAVES_RANGOS
from app.services.identidad_campeon import IndiceIdentidadCampeon
from app.services.repositorio_campeones import RepositorioCampeones
from app.services.riot_api_service import RiotApiError, RiotApiService
from app.services.lcu_service import LCUService
from app.services.settings_service import SettingsService
from app.services.storage_manager import StorageManager, get_storage_manager
from backend.assets import resolve_home_assets
from backend.home_battlescore import attach_saved_battlescores
from backend.contracts import BackendOperationError
from backend.bootstrap import bootstrap_payload


def _boot_step(stage: str, action):
    """Expose slow optional initialization without writing to JSONL stdout."""
    started = time.perf_counter()
    print(f"[BOOT] time={datetime.now(UTC).isoformat()} stage={stage}_started", file=sys.stderr, flush=True)
    try:
        result = action()
    except Exception as error:
        print(f"[BOOT] time={datetime.now(UTC).isoformat()} stage={stage}_failed duration_ms={(time.perf_counter() - started) * 1000:.1f} detail={type(error).__name__}",
              file=sys.stderr, flush=True)
        raise
    print(f"[BOOT] time={datetime.now(UTC).isoformat()} stage={stage}_complete duration_ms={(time.perf_counter() - started) * 1000:.1f}",
          file=sys.stderr, flush=True)
    return result

class Application:
    def __init__(self) -> None:
        self._shutdown_lock = threading.Lock()
        self._closing = False
        self._closed = False
        self._storage = _boot_step("storage_manager", StorageManager)
        self._storage_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="solralol-storage")
        self._storage_lock = threading.RLock()
        self._storage_condition = threading.Condition(self._storage_lock)
        self._active_requests = 0
        self._storage_migration: dict[str, Any] = _boot_step("migration_state", StorageManager.startup_migration_state) or {
            "migrationId": None, "state": "idle", "phase": "idle", "currentBytes": 0,
            "verifiedBytes": 0, "totalBytes": 0, "processedFiles": 0, "fileCount": 0,
            "currentFile": "", "lastProgressAt": None, "message": "",
        }
        _boot_step("storage_catalogs", self._prepare_storage_catalogs)
        self.champions = _boot_step("champion_repository", RepositorioCampeones)
        self.settings = _boot_step("settings", SettingsService)
        self._lcu_service = _boot_step("lcu_client", LCUService)
        self._catalog = _boot_step("champion_catalog", self._load_champion_catalog)
        self._home_repository = _boot_step("history_repository", HomeHistoryRepository)
        from backend.analysis_settings import load_configuration
        self._analysis_configuration = _boot_step("analysis_configuration", load_configuration)
        self._analysis_recalculation_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="solralol-battlescore")
        self._analysis_recalculation_lock = threading.RLock()
        self._analysis_recalculation: dict[str, Any] = {"state": "idle", "current": 0, "total": 0, "message": ""}
        self._home_lock = threading.RLock()
        self._soloq_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="solralol-soloq")
        self._soloq_jobs_lock = threading.RLock()
        self._soloq_jobs: set[str] = set()
        self._soloq_ai_jobs: set[str] = set()
        self._soloq_combat_jobs: set[str] = set()
        self._timeline_api_rejected_key: str | None = None
        self._riot_readiness: tuple[str, float, dict[str, Any]] | None = None
        self._riot_readiness_guard = threading.Lock()
        self._analysis_service = None
        self._analysis_lock = threading.RLock()
        self._analysis_update_lock = threading.RLock()
        self._analysis_update_state: dict[str, Any] = {"state": "idle", "current": 0, "total": 0, "message": ""}
        self._analysis_update_stop: threading.Event | None = None
        self._analysis_update_thread: threading.Thread | None = None
        self._meta_service = None
        self._meta_lock = threading.RLock()
        self._draft_runtime = None
        self._draft_lock = threading.RLock()
        from backend.recordings import RecordingRuntime
        self._recordings = _boot_step("recording_runtime", lambda: RecordingRuntime(self.settings))
        self._live_match = None
        self._recording_history_tracker = None

    def _prepare_storage_catalogs(self) -> None:
        """Keep mutable champion analysis inputs under the configured data root."""
        target_root = self._storage.cache_dir
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            from app.services.storage_manager import atomic_write_bytes
            for name in ("champion_catalog.json", "items.json", "legendary_items_strict.json", "passive_rules.json"):
                source = DATA_DIR / name
                target = target_root / name
                if source.is_file() and not target.exists():
                    atomic_write_bytes(target, source.read_bytes())
        except OSError:
            # Keep startup alive if a configured drive is disconnected; storage
            # settings remain available for recovery.
            logging.getLogger(__name__).warning("No se pudo inicializar la caché de catálogos en la ubicación configurada")

    def request_shutdown(self) -> None:
        """Reject new RPC work and signal cancellable background operations."""
        with self._shutdown_lock:
            if self._closing:
                return
            self._closing = True
        logger = logging.getLogger(__name__)
        logger.info("[Shutdown] Preventing new backend operations")
        if self._analysis_update_stop is not None:
            self._analysis_update_stop.set()
        with self._analysis_recalculation_lock:
            if self._analysis_recalculation.get("state") == "running":
                self._analysis_recalculation.update(
                    id=None, state="cancelled", message="Cierre de la aplicación."
                )

    def close(self) -> None:
        """Stop new work and release backend-owned workers and processes once."""
        self.request_shutdown()
        with self._shutdown_lock:
            if self._closed:
                return
            self._closed = True
        logger = logging.getLogger(__name__)
        logger.info("[Shutdown] Stopping backend background operations")

        for label, resource in (
            ("Live Client and LCU monitor", self._live_match),
            ("Recording monitor and FFmpeg", self._recordings),
        ):
            if resource is None:
                continue
            try:
                logger.info("[Shutdown] Stopping %s", label)
                resource.close()
            except Exception:
                logger.exception("[Shutdown] Failed while stopping %s", label)

        update_thread = self._analysis_update_thread
        if update_thread is not None and update_thread.is_alive():
            update_thread.join(timeout=12)
            if update_thread.is_alive():
                logger.warning("[Shutdown] Analysis update did not stop within 12 seconds")

        for label, executor in (
            ("SoloQ jobs", self._soloq_executor),
            ("BattleScore recalculation", self._analysis_recalculation_executor),
            ("Storage jobs", self._storage_executor),
        ):
            try:
                logger.info("[Shutdown] Draining %s", label)
                executor.shutdown(wait=True, cancel_futures=True)
            except Exception:
                logger.exception("[Shutdown] Failed while draining %s", label)
        try:
            self._lcu_service.session.close()
        except Exception:
            logger.exception("[Shutdown] Failed to close the LCU HTTP session")
        logger.info("[Shutdown] Backend resources released")

    def _check_riot_readiness(self) -> dict[str, Any]:
        """Verify Riot access with a low-cost platform status request and short cache."""
        with self._riot_readiness_guard:
            return self._check_riot_readiness_locked()

    def _recalculate_analysis_scores(self, job_id: str, analysis_config: dict[str, Any]) -> None:
        def is_current() -> bool:
            with self._analysis_recalculation_lock:
                return self._analysis_recalculation.get("id") == job_id

        def progress(current: int, total: int, match_id: str, message: str) -> None:
            with self._analysis_recalculation_lock:
                if self._analysis_recalculation.get("id") != job_id:
                    return
                self._analysis_recalculation.update({
                    "state": "running", "current": current, "total": total,
                    "matchId": match_id, "message": message,
                })

        try:
            with self._analysis_recalculation_lock:
                if self._analysis_recalculation.get("id") != job_id:
                    return
                self._analysis_recalculation.update({"state": "running", "message": "Recalculando BattleScore con datos locales."})
            from backend.soloq_analyses import recalculate_active_analyses
            def commit_result(profile: dict[str, Any], record: dict[str, Any]) -> bool:
                # Serialize the revision check and persistence so an older batch
                # can never overwrite results after a newer save is accepted.
                with self._analysis_recalculation_lock:
                    if self._analysis_recalculation.get("id") != job_id:
                        return False
                    self._home_repository.save_soloq_analysis(profile, record)
                    return True
            outcome = recalculate_active_analyses(self._home_repository, analysis_config, is_current, progress, commit_result)
            with self._analysis_recalculation_lock:
                if self._analysis_recalculation.get("id") != job_id:
                    return
                if outcome.get("superseded"):
                    self._analysis_recalculation.update({"state": "superseded", "message": "Un cambio más reciente sustituyó este recálculo."})
                    return
                self._analysis_recalculation.update({
                    "state": "completed", "current": outcome.get("recalculated", 0) + outcome.get("skipped", 0),
                    "total": outcome.get("recalculated", 0) + outcome.get("skipped", 0),
                    "recalculated": outcome.get("recalculated", 0), "skipped": outcome.get("skipped", 0),
                    "message": f"BattleScore actualizado en {outcome.get('recalculated', 0)} análisis; {outcome.get('skipped', 0)} sin telemetría suficiente.",
                })
        except Exception as error:
            logging.getLogger(__name__).exception("Falló el recálculo BattleScore de la revisión %s", analysis_config.get("configuration_version"))
            with self._analysis_recalculation_lock:
                if self._analysis_recalculation.get("id") == job_id:
                    self._analysis_recalculation.update({"state": "failed", "message": "No se pudieron recalcular todos los análisis. La telemetría original se conserva.", "errorCode": type(error).__name__})

    def _recalculate_analysis_achievements(self, analysis_config: dict[str, Any]) -> None:
        """Reevaluate achievements from saved Riot telemetry without API requests."""
        from backend.analysis_settings import _canonical_hash
        from backend.match_achievements import evaluate_match_achievements
        from backend.negative_achievements import evaluate as evaluate_improvements
        profile = self._home_repository.load_last_profile()
        if not profile:
            return
        records = self._home_repository.load_saved_analyses(profile)
        settings_hash = _canonical_hash({
            "positive": analysis_config.get("achievements", {}),
            "negative": analysis_config.get("negative_achievements", {}),
        })
        for record in records:
            battle = record.get("battle_score") if isinstance(record.get("battle_score"), dict) else {}
            participants = record.get("participants") if isinstance(record.get("participants"), list) else []
            if battle.get("state") not in {"complete", "partial"} or not participants:
                continue
            events = record.get("events") if isinstance(record.get("events"), list) else []
            frames = record.get("frames") if isinstance(record.get("frames"), list) else []
            duration = float(record.get("duration") or 0)
            with self._analysis_recalculation_lock:
                if self._analysis_configuration.get("configuration_hash") != analysis_config.get("configuration_hash"):
                    return
            record["achievements"] = evaluate_match_achievements(
                participants, events, frames, duration, battle,
                analysis_config.get("achievements", {}), bool(record.get("timeline_available")),
            )
            record["improvement_opportunities"] = evaluate_improvements(
                participants, events, frames, duration, bool(record.get("timeline_available")),
                analysis_config.get("negative_achievements", {}),
            )
            record["achievement_configuration"] = {
                "version": "match_achievements_v2", "configuration_hash": settings_hash,
                "configuration_version": analysis_config.get("configuration_version"),
                "analysis_timestamp": datetime.now(UTC).isoformat(),
                "telemetry_coverage": battle.get("telemetryCoverage"),
            }
            with self._analysis_recalculation_lock:
                if self._analysis_configuration.get("configuration_hash") != analysis_config.get("configuration_hash"):
                    return
                self._home_repository.save_soloq_analysis(profile, record)

    def _check_riot_readiness_locked(self) -> dict[str, Any]:
        key = str(self.settings.load().get("riot_api_key") or "").strip()
        if not key:
            return {"state": "missing", "checkedAt": None}
        fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
        cached = self._riot_readiness
        now = time.monotonic()
        if cached and cached[0] == fingerprint and cached[1] > now:
            return dict(cached[2])
        try:
            service = RiotApiService(key, platform_region="euw1")
            service._request(service.PLATFORM_BASE_URLS["euw1"], "/lol/status/v4/platform-data")
            result = {"state": "ready", "checkedAt": datetime.now(UTC).isoformat()}
            ttl = 300
        except RiotApiError as error:
            state = {401: "invalid", 403: "forbidden", 429: "rate_limited"}.get(error.status_code, "unavailable")
            result = {"state": state, "checkedAt": datetime.now(UTC).isoformat(),
                      "retryAfter": error.retry_after if state == "rate_limited" else None}
            ttl = 60 if state in {"invalid", "forbidden"} else min(max(error.retry_after or 30, 15), 120) if state == "rate_limited" else 20
        except (OSError, RuntimeError, TimeoutError):
            result = {"state": "unavailable", "checkedAt": datetime.now(UTC).isoformat()}
            ttl = 20
        self._riot_readiness = (fingerprint, now + ttl, result)
        return dict(result)

    @staticmethod
    def _load_champion_catalog() -> list[dict[str, Any]]:
        for path in (get_storage_manager().cache_dir / "champion_catalog.json", DATA_DIR / "champion_catalog.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                data = value.get("data", value) if isinstance(value, dict) else {}
                rows = [
                    {"id": str(key), "key": str(entry.get("key", "")), "name": str(entry.get("name", key)), "title": str(entry.get("title", ""))}
                    for key, entry in data.items() if isinstance(entry, dict)
                ]
                if rows:
                    return sorted(rows, key=lambda item: item["name"].casefold())
            except (OSError, ValueError, AttributeError):
                continue
        return []

    def dispatch(self, method: str, params: dict[str, Any] | None = None) -> object:
        params = params or {}
        if getattr(self, "_closing", False):
            raise BackendOperationError("app_shutting_down", "La aplicación se está cerrando.")
        with self._storage_condition:
            if (self._storage_migration.get("state") in {"preparing", "validating", "copying", "verifying", "committing", "reinitializing"}
                    and not method.startswith("storage.")):
                raise BackendOperationError("storage_migration_active", "La aplicación está trasladando los datos. Espera a que termine para continuar.")
            self._active_requests += 1
        try:
            return self._dispatch_active(method, params)
        finally:
            with self._storage_condition:
                self._active_requests = max(0, self._active_requests - 1)
                self._storage_condition.notify_all()

    def _dispatch_active(self, method: str, params: dict[str, Any] | None = None) -> object:
        params = params or {}
        if method == "overlay.visibility":
            overlays = params.get("overlays", [])
            if set(params) - {"overlays"} or not isinstance(overlays, list) or len(overlays) > 8:
                raise ValueError("Consulta de visibilidad no válida.")
            from app.services.game_window_geometry import overlay_window_visibility
            return overlay_window_visibility(overlays)
        if method == "overlay.tab-state":
            if params:
                raise ValueError("La consulta TAB no admite parámetros.")
            import ctypes
            return {"down": bool(ctypes.windll.user32.GetAsyncKeyState(0x09) & 0x8000) if hasattr(ctypes, "windll") else False}
        if method == "riot.readiness":
            if params:
                raise ValueError("La consulta de estado de Riot no acepta parámetros.")
            return self._check_riot_readiness()
        if method == "live.snapshot":
            if params:
                raise ValueError("La consulta de partida en vivo no admite parámetros.")
            if self._live_match is None:
                from backend.live_match import LiveMatchRuntime
                self._live_match = LiveMatchRuntime(self._catalog, self._recordings, self._queue_recent_saved_match_sync, self.settings, self._lcu_service)
            return self._live_match.snapshot()
        if method == "app.bootstrap":
            return bootstrap_payload()
        if method == "champions.list":
            query = str(params.get("query", "")).strip().casefold()
            return [
                champion for champion in self._catalog
                if not query or query in champion["name"].casefold() or query in champion["id"].casefold()
            ][:250]
        if method.startswith("draft."):
            with self._draft_lock:
                if self._draft_runtime is None:
                    from backend.draft import DraftRuntime
                    self._draft_runtime = DraftRuntime(self._catalog, getattr(self, "_lcu_service", None))
                if method == "draft.snapshot":
                    live = getattr(self, "_live_match", None)
                    return self._draft_runtime.snapshot(params, live.draft_state() if live else None)
                if method == "draft.import":
                    return self._draft_runtime.import_selection(params)
        if method == "meta.bootstrap":
            region = str(self.settings.load().get("meta_region", "euw")).casefold()
            if region not in {"all", "na", "euw", "kr"}:
                region = "euw"
            return {
                "region": region,
                "roles": [
                    {"id": "top", "label": "Top"},
                    {"id": "jungle", "label": "Jungla"},
                    {"id": "mid", "label": "Medio"},
                    {"id": "adc", "label": "Bot"},
                    {"id": "support", "label": "Apoyo"},
                ],
                "regions": [
                    {"id": "all", "label": "Mundo"},
                    {"id": "euw", "label": "Europa Oeste (EUW)"},
                    {"id": "na", "label": "Norteamérica (NA)"},
                    {"id": "kr", "label": "Corea (KR)"},
                ],
                "rank": "emerald_plus",
                "queue": "ranked_solo_duo",
            }
        if method == "meta.tier":
            role = str(params.get("role", "top")).casefold()
            region = params.get("region")
            force = params.get("force", False)
            if role not in {"top", "jungle", "mid", "adc", "support"}:
                raise ValueError("Posición de Meta no válida.")
            if region is not None and region not in {"all", "na", "euw", "kr"}:
                raise ValueError("Región de Meta no válida.")
            if not isinstance(force, bool):
                raise ValueError("El indicador de actualización no es válido.")
            with self._meta_lock:
                if region is None:
                    region = str(self.settings.load().get("meta_region", "euw")).casefold()
                    if region not in {"all", "na", "euw", "kr"}:
                        region = "euw"
                else:
                    saved = self.settings.load()
                    if saved.get("meta_region") != region:
                        saved["meta_region"] = region
                        self.settings.save(saved)
                if self._meta_service is None:
                    from app.services.meta_service import ServicioMeta
                    self._meta_service = ServicioMeta()
                try:
                    return self._meta_service.obtener_lista_niveles(
                        {"role": role, "region": region}, force
                    )
                except Exception as error:
                    import logging
                    import requests
                    logger = logging.getLogger(__name__)
                    if isinstance(error, requests.RequestException):
                        logger.warning("LoLalytics no disponible role=%s region=%s: %s", role, region, error)
                        raise BackendOperationError(
                            "meta_source_unavailable",
                            "LoLalytics no está disponible y no hay una caché válida para estos filtros.",
                        ) from error
                    if not isinstance(error, (RuntimeError, ValueError, TypeError)):
                        raise
                    logger.exception("LoLalytics devolvió datos inválidos role=%s region=%s", role, region)
                    raise BackendOperationError(
                        "meta_source_invalid",
                        "LoLalytics devolvió datos incompletos o incompatibles; no se publicó un ranking incorrecto.",
                    ) from error
        if method == "meta.notes":
            force = params.get("force", False)
            if not isinstance(force, bool):
                raise ValueError("El indicador de actualización no es válido.")
            with self._meta_lock:
                if self._meta_service is None:
                    from app.services.meta_service import ServicioMeta
                    self._meta_service = ServicioMeta()
                try:
                    result = dict(self._meta_service.obtener_notas(force))
                except Exception:
                    cached = self._meta_service.cargar_cache("patch_notes.json")
                    if not cached or cached.get("schema_version") != self._meta_service.VERSION_ESQUEMA_NOTAS:
                        raise
                    result = {**cached, "cached": True, "stale": True}
            from backend.assets import _data_url
            hero_path = result.pop("hero_image_path", None)
            result["hero_image"] = _data_url(Path(hero_path), max_bytes=8_000_000) if hero_path else None
            return result
        if method == "meta.assets":
            champion_ids = params.get("champions", [])
            item_ids = params.get("items", [])
            abilities = params.get("abilities", [])
            rune_ids = params.get("runes", [])
            spell_ids = params.get("spells", [])
            patch = params.get("patch")
            if not (
                isinstance(champion_ids, list) and len(champion_ids) <= 20
                and all(isinstance(value, str) and len(value) <= 60 for value in champion_ids)
                and isinstance(item_ids, list) and len(item_ids) <= 100
                and all(isinstance(value, str) and value.isdigit() and len(value) <= 8 for value in item_ids)
                and isinstance(abilities, list) and len(abilities) <= 20
                and all(isinstance(value, dict) and set(value) == {"champion", "slot"}
                        and isinstance(value["champion"], str) and len(value["champion"]) <= 60
                        and isinstance(value["slot"], str) and value["slot"] in {"passive", "q", "w", "e", "r"}
                        for value in abilities)
                and isinstance(rune_ids, list) and len(rune_ids) <= 100
                and all(isinstance(value, str) and len(value) <= 60 and "/" not in value and "\\" not in value and not any(ord(char) < 32 for char in value) for value in rune_ids)
                and isinstance(spell_ids, list) and len(spell_ids) <= 20
                and all(isinstance(value, str) and len(value) <= 60 and "/" not in value and "\\" not in value and not any(ord(char) < 32 for char in value) for value in spell_ids)
                and (patch is None or isinstance(patch, str) and re.fullmatch(r"\d{1,2}\.\d{1,2}(?:\.\d{1,10}){0,2}", patch))
            ):
                raise ValueError("Solicitud de recursos de Meta no válida.")
            from backend.assets import resolve_meta_assets
            return resolve_meta_assets(champion_ids, item_ids, abilities, self._catalog, rune_ids, spell_ids, patch)
        if method == "champions.analysis.update":
            if getattr(self, "_closing", False):
                raise BackendOperationError("app_shutting_down", "La aplicación se está cerrando.")
            target = str(params.get("champion", "")).strip()
            if target:
                identities = IndiceIdentidadCampeon({item["id"]: item for item in self._catalog})
                canonical = identities.resolve(target)
                if not canonical:
                    raise ValueError("Campeón desconocido")
                target = identities.display_name(canonical) or canonical
            with self._analysis_update_lock:
                if self._analysis_update_state.get("state") == "running":
                    return dict(self._analysis_update_state)
                stop = threading.Event()
                self._analysis_update_stop = stop
                self._analysis_update_state = {
                    "state": "running", "current": 0, "total": 100 if target else len(self.champions.perfiles()),
                    "message": f"Preparando actualización de {target}" if target else "Preparando todos los campeones",
                    "target": target, "operationId": uuid.uuid4().hex,
                }

            def update_analysis() -> None:
                from app.services.champion_scraper_service import ChampionScraperService
                from app.services.rangos_campeones import RANGO_ANALISIS_LOCAL

                def progress(current: int, total: int, message: str) -> None:
                    with self._analysis_update_lock:
                        if self._analysis_update_state.get("state") == "running":
                            self._analysis_update_state.update(current=current, total=total, message=message[:120])
                try:
                    service = ChampionScraperService(
                        champions_path=self._storage.cache_dir / "champions",
                        rank=RANGO_ANALISIS_LOCAL,
                        solo_rango_analisis_local=True,
                    )
                    total, updated = service.actualizar_todo(
                        target_champion_name=target,
                        progress_callback=progress,
                        stop_check=stop.is_set,
                    )
                    with self._analysis_update_lock:
                        state = "cancelled" if stop.is_set() else "complete"
                        self._analysis_update_state.update(
                            state=state, current=total if target else self._analysis_update_state.get("current", 0),
                            total=total, updated=updated,
                            message=(f"Actualizados {updated} de {total} campeones en Esmeralda+"),
                        )
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Falló la actualización de Análisis local")
                    with self._analysis_update_lock:
                        self._analysis_update_state.update(state="error", message="No se pudo completar la actualización. Revisa la conexión y vuelve a intentarlo.")

            self._analysis_update_thread = threading.Thread(target=update_analysis, name="solralol-analysis-update")
            self._analysis_update_thread.start()
            with self._analysis_update_lock:
                return dict(self._analysis_update_state)
        if method == "champions.analysis.update.status":
            with self._analysis_update_lock:
                return dict(self._analysis_update_state)
        if method == "champions.analysis.update.cancel":
            with self._analysis_update_lock:
                if self._analysis_update_stop is not None:
                    self._analysis_update_stop.set()
                return dict(self._analysis_update_state)
        if method == "champions.analysis":
            champion = str(params.get("champion", ""))
            lane = str(params.get("lane", "mid"))
            # Local Analysis has always been restricted to Emerald+.
            requested_rank = str(params.get("rank", "emerald_plus"))
            if requested_rank not in CLAVES_RANGOS:
                raise ValueError("Rango no válido")
            rank = "emerald_plus"
            champion = IndiceIdentidadCampeon({item["id"]: item for item in self._catalog}).resolve(champion)
            if not champion:
                raise ValueError("Campeón desconocido")
            if lane not in {"top", "jungle", "mid", "adc", "support"}:
                raise ValueError("Línea no válida")
            if rank not in CLAVES_RANGOS:
                raise ValueError("Rango no válido")
            result = self.champions.consultar(champion, lane, rank)
            response = {
                "status": result.estado.value,
                "champion": champion,
                "lane": lane,
                "rank": rank,
                "data": None,
                "profile": result.perfil,
                "updatedAt": result.actualizacion,
                "runeVariants": [],
                "assets": {},
                "items": [],
                "recommendations": [],
                "itemCandidates": [],
            }
            if result.datos is None or not isinstance(result.perfil, dict):
                return response
            # Reuse the existing Python analysis/recommendation pipeline. Its own
            # caches are protected because protocol requests run concurrently.
            with self._analysis_lock:
                if self._analysis_service is None:
                    from app.services.analisis_local_service import AnalisisLocalService
                    from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
                    from app.services.item_name_aliases import ITEM_NAME_ALIASES

                    raw_items = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
                    strict_items = json.loads((DATA_DIR / "legendary_items_strict.json").read_text(encoding="utf-8"))
                    item_catalog = raw_items.get("items", {}) if isinstance(raw_items, dict) else {}
                    version = str(raw_items.get("version", "")) if isinstance(raw_items, dict) else ""
                    catalog = CatalogoAnalisisLocal(item_catalog, strict_items if isinstance(strict_items, list) else [], ITEM_NAME_ALIASES, version)
                    self._analysis_service = AnalisisLocalService(catalog, self._storage.cache_dir / "champions", version)
                source_profile = dict(result.perfil)
                source_profile.setdefault("character", champion)
                prepared = self._analysis_service.cargar(source_profile, lane, rank, {}, lambda: False)
            if prepared.get("variante") is None:
                response["status"] = str(prepared.get("estado") or response["status"])
                return response
            profile = prepared.get("perfil") if isinstance(prepared.get("perfil"), dict) else {}
            keys = prepared.get("rune_profile_keys", [])
            variants = prepared.get("rune_profiles_by_key", {})
            pages = profile.get("runes") or profile.get("common_runes") or []
            response["data"] = profile
            response["runeVariants"] = [
                {"key": key, "page": pages[index] if isinstance(pages, list) and index < len(pages) else {},
                 "profile": variants[key]}
                for index, key in enumerate(keys)
                if isinstance(key, str) and isinstance(variants, dict) and isinstance(variants.get(key), dict)
            ]
            from backend.assets import _data_url
            resources = {}
            for (kind, name), path in prepared.get("rutas", {}).items():
                image = _data_url(Path(path), max_bytes=2_000_000)
                if image:
                    resources[f"{kind}:{name}"] = image
            response["assets"] = resources
            response["items"] = [
                {"id": str(item_id), "name": str(item.get("item") or (item.get("basic_info") or {}).get("name") or item_id),
                 "nameEn": str(item.get("name_en") or (item.get("basic_info") or {}).get("name_en") or ""),
                 "description": str(item.get("plaintext") or item.get("description") or "")}
                for item_id, item in (prepared.get("objetos") or {}).items()
                if isinstance(item, dict)
            ]
            def serialize_items(values: Any) -> list[dict[str, Any]]:
                output: list[dict[str, Any]] = []
                for value in values if isinstance(values, list) else []:
                    if isinstance(value, dict):
                        output.append(value)
                        continue
                    item_id = str(getattr(value, "item_id", "") or "")
                    name = str(getattr(value, "name", "") or "")
                    if item_id and name:
                        output.append({
                            "item_id": item_id, "name": name,
                            "score": float(getattr(value, "score", 0) or 0),
                            "reasons": list(getattr(value, "reasons", ()) or ()),
                            "counter_reasons": list(getattr(value, "counter_reasons", ()) or ()),
                            "compatibility_label": str(getattr(value, "compatibility_label", "") or ""),
                            "compatibility_reasons": list(getattr(value, "compatibility_reasons", ()) or ()),
                            "compatibility_score": float(getattr(value, "compatibility_score", 0) or 0),
                            "matchup_score": float(getattr(value, "matchup_score", 0) or 0),
                            "build_synergy_score": float(getattr(value, "build_synergy_score", 0) or 0),
                        })
                return output
            response["recommendations"] = serialize_items(prepared.get("recomendaciones"))
            response["itemCandidates"] = serialize_items(prepared.get("candidatos_afinidad"))
            response["profile"] = prepared.get("metadatos") or result.perfil
            response["updatedAt"] = prepared.get("actualizacion") or result.actualizacion
            return response
        if method == "settings.public":
            # The initial renderer receives status flags only; credentials remain in Python.
            settings = self.settings.load()
            return {
                "riotApiKeyConfigured": bool(settings.get("riot_api_key")),
                "geminiApiKeyConfigured": bool(settings.get("gemini_api_key")),
            }
        if method == "storage.info":
            if params:
                raise ValueError("La consulta de almacenamiento no admite parámetros.")
            result = self._storage.storage_stats(self.settings.load().get("recording_output_dir"))
            result["defaultRoot"] = str(self._storage.default_root)
            journal = StorageManager.migration_journal()
            with self._storage_lock:
                if journal and journal.get("migrationId") == self._storage_migration.get("migrationId"):
                    self._storage_migration = dict(journal)
                result["migration"] = dict(self._storage_migration)
            return result
        if method == "storage.preview":
            if set(params) != {"path"} or not isinstance(params.get("path"), str):
                raise ValueError("Selecciona una carpeta de destino v?lida.")
            plan = self._storage.migration_plan(params["path"], self.settings.load().get("recording_output_dir"))
            recording = self._recordings.snapshot()
            return {"source": str(plan.source), "destination": str(plan.destination),
                    "totalBytes": plan.total_bytes, "fileCount": plan.file_count,
                    "availableBytes": plan.available_bytes,
                    "recordingActive": recording.get("state") in {"preparing", "recording", "stopping", "finalizing"}}
        if method == "storage.migrate.start":
            if set(params) != {"path"} or not isinstance(params.get("path"), str):
                raise ValueError("Selecciona una carpeta de destino v?lida.")
            with self._storage_lock:
                if self._storage_migration.get("state") in {"preparing", "validating", "copying", "verifying", "committing", "reinitializing"}:
                    raise BackendOperationError("storage_migration_active", "Ya hay una migraci?n de datos en curso.")
                migration_id = str(uuid.uuid4())
                self._storage_migration = {
                    "migrationId": migration_id, "state": "preparing", "phase": "preparing",
                    "currentBytes": 0, "verifiedBytes": 0, "totalBytes": 0,
                    "processedFiles": 0, "fileCount": 0, "currentFile": "",
                    "lastProgressAt": time.time(), "message": "Preparando el cierre de Solralol",
                }
            destination = params["path"]
            recording_dir = self.settings.load().get("recording_output_dir")
            try:
                plan = self._storage.migration_plan(destination, recording_dir)
                self._recordings.storage_paused = True
                recording = self._recordings.snapshot()
                if recording.get("state") in {"preparing", "recording", "stopping", "finalizing"}:
                    self._recordings.stop_manual()
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        recording = self._recordings.snapshot()
                        if recording.get("state") not in {"preparing", "recording", "stopping", "finalizing"}:
                            break
                        time.sleep(0.2)
                    else:
                        raise TimeoutError("No se pudo finalizar la grabaci?n activa de forma segura.")
                with self._analysis_update_lock:
                    if self._analysis_update_state.get("state") == "running" and self._analysis_update_stop:
                        self._analysis_update_stop.set()
                    analysis_thread = self._analysis_update_thread
                if analysis_thread and analysis_thread.is_alive():
                    analysis_thread.join(timeout=60)
                    if analysis_thread.is_alive():
                        raise TimeoutError("No se pudo detener a tiempo la actualizaci?n de an?lisis local.")
                self._soloq_executor.submit(lambda: None).result(timeout=60)
                migration = {
                    "migrationId": migration_id, "state": "preparing", "phase": "preparing",
                    "source": str(plan.source), "destination": str(plan.destination),
                    "totalBytes": plan.total_bytes, "fileCount": plan.file_count,
                    "currentBytes": 0, "verifiedBytes": 0, "processedFiles": 0,
                    "lastProgressAt": time.time(), "message": "Preparando el cierre de Solralol",
                    "extraRecordings": [str(value) for value in plan.extra_recordings],
                    "includeExistingDestination": bool(plan.existing_destination_bytes),
                    "extraElectronData": str(plan.extra_electron_data) if plan.extra_electron_data else None,
                    "settingsPath": str(self._storage.settings_path),
                    "recordingDirectory": str(recording_dir or ""),
                    "bootstrapPath": str(self._storage._migration_journal_path().with_name("storage.json")),
                }
                self._storage._save_migration_journal(migration)
                with self._storage_lock:
                    self._storage_migration = migration
            except Exception as error:
                self._recordings.storage_paused = False
                with self._storage_lock:
                    self._storage_migration = {"migrationId": migration_id, "state": "failed", "phase": "preparing",
                        "currentBytes": 0, "verifiedBytes": 0, "totalBytes": 0,
                        "processedFiles": 0, "fileCount": 0, "lastProgressAt": time.time(),
                        "message": "No se pudo preparar el cierre. La ubicaci?n original sigue activa."}
                raise BackendOperationError("storage_migration_prepare_failed", "No se pudo preparar Solralol para cerrar. La carpeta original permanece activa.") from error
            return dict(self._storage_migration)
        if method == "storage.migrate.abort":
            if set(params) != {"migrationId"} or params.get("migrationId") != self._storage_migration.get("migrationId"):
                raise ValueError("La operaci?n de migraci?n no coincide.")
            self._recordings.storage_paused = False
            self._storage_migration = {**self._storage_migration, "state": "failed", "phase": "failed",
                "lastProgressAt": time.time(), "message": "No se pudo iniciar el asistente. La ubicaci?n original sigue activa."}
            self._storage._save_migration_journal(self._storage_migration)
            return dict(self._storage_migration)
        if method == "storage.migrate.status":
            if params:
                raise ValueError("La consulta de migración no admite parámetros.")
            journal = StorageManager.migration_journal()
            with self._storage_lock:
                if journal and journal.get("migrationId") == self._storage_migration.get("migrationId"):
                    self._storage_migration = dict(journal)
                return dict(self._storage_migration)
        if method == "settings.load":
            return self.settings.electron_snapshot()
        if method == "analysis.settings.load":
            from backend.analysis_settings import configuration_load_warning, public_configuration
            from backend.match_achievements import public_achievement_registry
            from backend.negative_achievements import public_registry as public_negative_achievement_registry
            profile = self._home_repository.load_last_profile()
            active_count = 0
            if profile:
                active_count = sum(1 for item in self._home_repository.load_saved_analyses(profile)
                    if isinstance(item.get("battle_score"), dict) and item["battle_score"].get("state") in {"complete", "partial"})
            active_limit = self._analysis_configuration["analysis_limits"]["max_active_matches"]
            return {"configuration": public_configuration(self._analysis_configuration),
                    "achievementRegistry": public_achievement_registry(self._analysis_configuration.get("achievements")),
                    "negativeAchievementRegistry": public_negative_achievement_registry(self._analysis_configuration.get("negative_achievements")),
                    "recalculation": dict(self._analysis_recalculation), "activeAnalyses": active_count,
                    "overLimit": active_count > active_limit, "warning": configuration_load_warning()}
        if method == "analysis.settings.defaults":
            from backend.analysis_settings import default_configuration
            from backend.match_achievements import public_achievement_registry
            from backend.negative_achievements import public_registry as public_negative_achievement_registry
            configuration = default_configuration()
            return {"configuration": configuration,
                    "achievementRegistry": public_achievement_registry(configuration.get("achievements")),
                    "negativeAchievementRegistry": public_negative_achievement_registry(configuration.get("negative_achievements"))}
        if method == "analysis.settings.save":
            if getattr(self, "_closing", False):
                raise BackendOperationError("app_shutting_down", "La aplicación se está cerrando.")
            if set(params) != {"configuration"}:
                raise ValueError("La solicitud de configuración de análisis no es válida.")
            from backend.analysis_settings import save_configuration, public_configuration, engine_snapshot
            from backend.match_achievements import public_achievement_registry
            from backend.negative_achievements import public_registry as public_negative_achievement_registry
            job_id = str(uuid.uuid4())
            with self._analysis_recalculation_lock:
                previous_engine_hash = engine_snapshot(self._analysis_configuration).get("configuration_hash")
                previous_achievement_hash = json.dumps({"positive": self._analysis_configuration.get("achievements", {}), "negative": self._analysis_configuration.get("negative_achievements", {})}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                updated = save_configuration(params["configuration"])
                self._analysis_configuration = updated
                score_changed = engine_snapshot(updated).get("configuration_hash") != previous_engine_hash
                achievement_changed = previous_achievement_hash != json.dumps({"positive": updated.get("achievements", {}), "negative": updated.get("negative_achievements", {})}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                profile = self._home_repository.load_last_profile()
                active_count = sum(1 for item in self._home_repository.load_saved_analyses(profile)
                    if isinstance(item.get("battle_score"), dict) and item["battle_score"].get("state") in {"complete", "partial"}) if profile else 0
                self._analysis_recalculation = {
                    "id": job_id, "revision": updated["configuration_version"],
                    "configurationHash": updated["configuration_hash"], "state": "queued" if score_changed else "completed",
                    "current": 0, "total": active_count if score_changed or achievement_changed else 0, "recalculated": 0,
                    "message": "Preparando recálculo de análisis activos." if score_changed else "Ajustes de logros guardados; no fue necesario recalcular BattleScore.",
                }
            if score_changed and not self._closing:
                self._analysis_recalculation_executor.submit(self._recalculate_analysis_scores, job_id, updated)
            if achievement_changed and not self._closing:
                self._analysis_recalculation_executor.submit(self._recalculate_analysis_achievements, updated)
            return {"configuration": public_configuration(updated),
                    "achievementRegistry": public_achievement_registry(updated.get("achievements")),
                    "negativeAchievementRegistry": public_negative_achievement_registry(updated.get("negative_achievements")),
                    "recalculation": dict(self._analysis_recalculation),
                    "activeAnalyses": active_count, "overLimit": active_count > updated["analysis_limits"]["max_active_matches"]}
        if method == "analysis.settings.recalculation.status":
            if params:
                raise ValueError("La consulta de recálculo no admite parámetros.")
            with self._analysis_recalculation_lock:
                return dict(self._analysis_recalculation)
        if method == "recordings.status":
            return self._recordings.snapshot()
        if method == "recordings.start":
            return self._recordings.start_manual()
        if method == "recordings.stop":
            return self._recordings.stop_manual()
        if method == "recordings.list":
            from app.services.recording_service import RecordingLibrary, format_duration, format_size
            saved = self.settings.load()
            library = RecordingLibrary(saved.get("recording_output_dir") or None)
            rows = library.list_recordings()
            recording_status = self._recordings.snapshot()
            active_name = recording_status.get("recordingName")
            if self._recording_history_tracker is None:
                from app.services.live_match_tracker import LiveMatchTracker
                self._recording_history_tracker = LiveMatchTracker({}, persist=False)
            sessions = self._recording_history_tracker.load_saved_sessions()
            sessions_by_id = {str(item.get("session_id")): item for item in sessions if isinstance(item, dict) and item.get("session_id")}
            for row in rows:
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                is_active = row.get("name") == active_name
                if is_active:
                    row["active"] = True
                    row["complete"] = False
                    row["duration"] = recording_status.get("elapsedSeconds", 0)
                    row["duration_label"] = format_duration(recording_status.get("elapsedSeconds", 0))
                    row["size_bytes"] = recording_status.get("fileSizeBytes", row.get("size_bytes", 0))
                    row["size_label"] = format_size(row["size_bytes"])
                    row["champion"] = recording_status.get("currentChampion") or row.get("champion", "")
                    row["game_mode"] = recording_status.get("currentGameMode") or row.get("game_mode", "")
                    row["position"] = recording_status.get("currentRole") or row.get("position", "")
                    row["recording_state"] = recording_status.get("state", "recording")
                session = None if is_active else sessions_by_id.get(str(metadata.get("session_id") or ""))
                if session:
                    local_key = str(session.get("local_player_key") or "")
                    players = session.get("players") if isinstance(session.get("players"), dict) else {}
                    local_player = players.get(local_key) if local_key else None
                    if isinstance(local_player, dict):
                        row["champion"] = row.get("champion") or local_player.get("champion_name") or ""
                        raw_role = str(local_player.get("role") or "").upper()
                        row["position"] = row.get("position") or {
                            "TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid",
                            "BOTTOM": "adc", "UTILITY": "support",
                        }.get(raw_role, "")
                    matchups = session.get("lane_matchups") if isinstance(session.get("lane_matchups"), dict) else {}
                    matchup = matchups.get(str((local_player or {}).get("role") or "").upper()) if isinstance(local_player, dict) else None
                    enemy_key = str(matchup.get("enemy_key") or "") if isinstance(matchup, dict) else ""
                    enemy_player = players.get(enemy_key) if enemy_key else None
                    if isinstance(enemy_player, dict):
                        row["opponent_champion"] = row.get("opponent_champion") or str(enemy_player.get("champion_name") or "")
                        row["opponent_position"] = row.get("opponent_position") or row.get("position", "")
                    final = session.get("final_scoreboard") if isinstance(session.get("final_scoreboard"), dict) else {}
                    stats = final.get(local_key) if local_key else None
                    stats = stats if isinstance(stats, dict) else {}
                    score_data = session.get("performance_scoring") if isinstance(session.get("performance_scoring"), dict) else {}
                    score = next((item.get("total") for item in score_data.get("players", []) if isinstance(item, dict) and str(item.get("participant_id") or "") == local_key), None)
                    kda = [stats.get(key) for key in ("kills", "deaths", "assists")] if all(isinstance(stats.get(key), (int, float)) for key in ("kills", "deaths", "assists")) else None
                    if kda and not row.get("kda"):
                        row["kda"] = kda
                    row["saved_match"] = {
                        "win": stats.get("win", local_player.get("win") if isinstance(local_player, dict) else None),
                        "battle_score": score if score_data.get("version") == "battlescore_v2_0" and score_data.get("calibration_version") == "battlescore_v2_0" and score_data.get("state") == "POSTGAME_FINAL" else None,
                        "battle_score_version": score_data.get("version") if score_data.get("version") == "battlescore_v2_0" else None,
                        "kda": kda,
                    }
                    row["game_mode"] = row.get("game_mode") or str(session.get("game_mode") or "")
                canonical = next((item["name"] for item in self._catalog if str(row.get("champion") or "").casefold() in {
                    str(item.get("id", "")).casefold(), str(item.get("key", "")).casefold(), str(item.get("name", "")).casefold()
                }), "")
                if canonical:
                    row["champion"] = canonical
                    from app.services.recording_service import RecordingLibrary
                    row["title"] = RecordingLibrary.title_for(Path(row["name"]), {**metadata, "champion": canonical})
                row.pop("path", None)
                row["metadata"] = {key: metadata[key] for key in ("started_at", "ended_at", "duration_seconds", "champion", "game_mode", "session_id", "recording_id", "match_id", "riot_match_id", "complete", "markers", "position", "lane", "kda", "opponent_champion", "opponent_champion_name", "opponent_position", "opponent_lane") if key in metadata}
            return rows
        if method in {"recordings.review", "recordings.review.generate"}:
            name = params.get("name")
            if not isinstance(name, str) or not name or Path(name).name != name or Path(name).suffix.casefold() not in {".mp4", ".mkv"}:
                raise ValueError("La grabación seleccionada no es válida.")
            from backend.recording_review import review_recording
            return review_recording(name, generate=method.endswith(".generate"))
        if method == "saved_matches.list":
            from backend.saved_matches import list_saved_matches
            return list_saved_matches()
        if method in {"saved_matches.detail", "saved_matches.analysis.generate"}:
            session_id = params.get("id")
            if not isinstance(session_id, str) or not session_id or len(session_id) > 160:
                raise ValueError("Identificador de partida no válido.")
            if method == "saved_matches.detail":
                from backend.saved_matches import get_saved_match
                return get_saved_match(session_id)
        if method == "saved_matches.sync":
            session_id = params.get("id")
            if set(params) != {"id"} or not isinstance(session_id, str) or not session_id or len(session_id) > 160:
                raise ValueError("Identificador de partida no válido.")
            from backend.saved_matches import sync_saved_match
            from app.services.storage_manager import StorageWriteError
            try:
                record = sync_saved_match(session_id)
            except StorageWriteError as error:
                raise BackendOperationError("storage_write_failed", str(error)) from error
            if record.get("status") in {"pending", "downloading", "processing"}:
                self._start_soloq_download(str(record.get("match_id") or ""))
            return record
            force = params.get("force", False)
            if not isinstance(force, bool):
                raise ValueError("La opción de regeneración no es válida.")
            from backend.saved_matches import generate_saved_match_analysis
            return generate_saved_match_analysis(session_id, force=force)
        if method in {"saved_matches.delete.preview", "saved_matches.delete"}:
            session_id = params.get("id")
            expected = {"id"} if method.endswith("preview") else {"id", "manifestId"}
            if set(params) != expected or not isinstance(session_id, str) or not session_id or len(session_id) > 160:
                raise ValueError("Identificador de partida no válido.")
            if method.endswith("preview"):
                from backend.saved_matches import preview_saved_match_delete
                return preview_saved_match_delete(session_id)
            manifest_id = params.get("manifestId")
            if not isinstance(manifest_id, str) or len(manifest_id) != 64:
                raise ValueError("Vista previa de eliminación no válida.")
            from backend.saved_matches import delete_saved_match
            return delete_saved_match(session_id, manifest_id)
        if method == "soloq_analyses.list":
            if params:
                raise ValueError("La operación no admite parámetros.")
            from backend.soloq_analyses import list_analyses
            result = list_analyses(self._home_repository)
            for match in result["matches"]:
                if match.get("status") in {"pending", "downloading", "processing"}:
                    self._start_soloq_download(str(match.get("id") or ""))
                if match.get("ai_generation_status") == "generating":
                    self._start_soloq_ai(str(match.get("id") or ""), False)
            return result
        if method == "soloq_analyses.register":
            if set(params) != {"matchId"}:
                raise ValueError("Parámetros de análisis SoloQ no válidos.")
            match_id = params.get("matchId")
            if not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador Riot no válido.")
            from backend.soloq_analyses import register_analysis
            record = register_analysis(self._home_repository, match_id.strip())
            if record.get("status") not in {"ready", "partial"}:
                self._start_soloq_download(str(record.get("match_id") or match_id.strip()))
            return record
        if method == "soloq_analyses.detail":
            if set(params) != {"matchId"}:
                raise ValueError("Parámetros de análisis SoloQ no válidos.")
            match_id = params.get("matchId")
            if not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador Riot no válido.")
            from backend.soloq_analyses import get_analysis
            return get_analysis(self._home_repository, match_id.strip())
        if method == "soloq_analyses.achievements":
            if set(params) != {"matchId"}:
                raise ValueError("Parámetros de logros SoloQ no válidos.")
            match_id = params.get("matchId")
            if not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador Riot no válido.")
            from backend.soloq_analyses import get_achievement_snapshot
            return get_achievement_snapshot(self._home_repository, match_id.strip())
        if method in {"soloq_analyses.delete.preview", "soloq_analyses.delete"}:
            expected = {"matchId"} if method.endswith("preview") else {"matchId", "manifestId"}
            if set(params) != expected:
                raise ValueError("Parámetros de análisis SoloQ no válidos.")
            match_id = params.get("matchId")
            if not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador Riot no válido.")
            if method.endswith("preview"):
                from backend.soloq_analyses import preview_saved_analysis_deletion
                return preview_saved_analysis_deletion(self._home_repository, match_id.strip())
            manifest_id = params.get("manifestId")
            if not isinstance(manifest_id, str) or len(manifest_id) != 64:
                raise ValueError("Vista previa de eliminación no válida.")
            with self._soloq_jobs_lock:
                if match_id in self._soloq_jobs or match_id in self._soloq_ai_jobs or match_id in self._soloq_combat_jobs:
                    raise ValueError("Hay un proceso de análisis activo; espera a que termine antes de eliminarla.")
            from backend.soloq_analyses import delete_saved_analysis_cascade
            return delete_saved_analysis_cascade(self._home_repository, match_id.strip(), manifest_id)
        if method == "soloq_analyses.analysis.generate":
            match_id = params.get("matchId")
            force = params.get("force", False)
            if not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120 or not isinstance(force, bool) or set(params) - {"matchId", "force"}:
                raise ValueError("Parámetros del análisis con IA no válidos.")
            from backend.soloq_analyses import get_analysis
            current = get_analysis(self._home_repository, match_id.strip())
            if current.get("ai_analysis") and not force:
                return current
            if not self._start_soloq_ai(match_id.strip(), force):
                return current
            current["ai_generation_status"] = "generating"
            current["ai_status_message"] = "Generando análisis a partir de datos Match-V5."
            return current
        if method == "soloq_analyses.analysis.status":
            match_id = params.get("matchId")
            if set(params) != {"matchId"} or not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador de partida no válido.")
            from backend.soloq_analyses import get_ai_status, save_ai_status
            result = get_ai_status(self._home_repository, match_id.strip())
            if result["ai_generation_status"] == "generating":
                with self._soloq_jobs_lock:
                    job_active = match_id.strip() in self._soloq_ai_jobs
                if not job_active:
                    save_ai_status(self._home_repository, match_id.strip(), "idle", "La generación anterior no terminó.")
                    result = get_ai_status(self._home_repository, match_id.strip())
            return result
        if method == "soloq_analyses.combat.context":
            match_id = params.get("matchId")
            if set(params) != {"matchId"} or not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador de partida no vÃ¡lido.")
            from backend.combat_matchups import context_response
            result = context_response(self._home_repository, match_id.strip())
            if result.get("generation_status") == "generating":
                with self._soloq_jobs_lock:
                    job_active = match_id.strip() in self._soloq_combat_jobs
                if not job_active:
                    from backend.combat_matchups import persist_status
                    persist_status(self._home_repository, match_id.strip(), "idle", "La generación anterior no terminó.")
                    result = context_response(self._home_repository, match_id.strip())
            return result
        if method == "soloq_analyses.combat.generate":
            match_id = params.get("matchId")
            if set(params) != {"matchId"} or not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador de partida no vÃ¡lido.")
            from backend.combat_matchups import context_response
            current = context_response(self._home_repository, match_id.strip())
            if current.get("generation_status") == "generating":
                with self._soloq_jobs_lock:
                    job_active = match_id.strip() in self._soloq_combat_jobs
                if not job_active:
                    from backend.combat_matchups import persist_status
                    persist_status(self._home_repository, match_id.strip(), "idle", "La generación anterior no terminó.")
                    current = context_response(self._home_repository, match_id.strip())
            cached = current.get("matchups") if isinstance(current.get("matchups"), dict) else None
            cached_rows = cached.get("matchups") if cached and isinstance(cached.get("matchups"), list) else []
            needs_baiting_refresh = bool(cached_rows) and any(
                not isinstance(item, dict) or not str(item.get("baiting_strategy") or "").strip()
                for item in cached_rows
            )
            if (cached and not needs_baiting_refresh) or current.get("generation_status") == "generating":
                return current
            if not current.get("available"):
                raise ValueError(current.get("reason") or "No hay datos locales completos para preparar los enfrentamientos.")
            if not self._start_soloq_combat(match_id.strip()):
                return current
            current["generation_status"] = "generating"
            current["status_message"] = "Analizando los cinco emparejamientos con las habilidades del catÃ¡logo local."
            return current
        if method == "recordings.thumbnail":
            name = params.get("name")
            if not isinstance(name, str) or not name or Path(name).name != name or Path(name).suffix.casefold() not in {".mp4", ".mkv"}:
                raise ValueError("Identificador de grabación no válido.")
            return self._recordings.thumbnail(name)
        if method == "recordings.delete":
            from app.services.recording_service import RecordingLibrary
            name = params.get("name")
            if isinstance(name, str) and self._recordings.snapshot().get("recordingName") == name:
                raise ValueError("No se puede eliminar una grabaciÃ³n mientras estÃ¡ activa.")
            if not isinstance(name, str) or not name or Path(name).name != name or Path(name).suffix.casefold() not in {".mp4", ".mkv"}:
                raise ValueError("Identificador de grabación no válido.")
            saved = self.settings.load()
            library = RecordingLibrary(saved.get("recording_output_dir") or None)
            target = (library.directory / name).resolve()
            if target.parent != library.directory.resolve():
                raise ValueError("La grabación está fuera de la carpeta permitida.")
            if not target.is_file():
                return {"deleted": False, "message": "El archivo ya no existe."}
            ok = library.delete(target)
            return {"deleted": ok, "message": "Grabación eliminada." if ok else "No se pudo eliminar; puede estar abierta en el reproductor."}
        if method == "settings.update":
            changes = params.get("changes")
            if not isinstance(changes, dict):
                raise ValueError("Cambios de configuración no válidos.")
            recording_directory = changes.get("recording_output_dir")
            if recording_directory:
                requested = Path(str(recording_directory)).expanduser().resolve(strict=False)
                if not requested.is_relative_to(self._storage.root):
                    raise ValueError("La carpeta de grabaciones debe estar dentro del directorio central de datos.")
            return self.settings.update_electron_settings(changes)
        if method == "settings.key.save":
            provider = params.get("provider")
            api_key = params.get("apiKey")
            if provider not in {"riot", "gemini"} or not isinstance(api_key, str) or len(api_key) > 512:
                raise ValueError("Datos de clave no válidos.")
            valid, message, configured = self.settings.store_validated_api_key(provider, api_key)
            return {"valid": valid, "message": message, "configured": configured}
        if method == "settings.key.clear":
            provider = params.get("provider")
            if provider not in {"riot", "gemini"}:
                raise ValueError("Proveedor de clave no válido.")
            self.settings.clear_api_key(provider)
            return {"configured": False}
        if method == "settings.audio-devices":
            from app.services.recording_service import find_ffmpeg, list_audio_devices

            saved = self.settings.load()
            ffmpeg = find_ffmpeg(str(saved.get("ffmpeg_path") or ""), force=True)
            return {
                "available": bool(ffmpeg),
                "devices": list_audio_devices(ffmpeg or "", force=True) if ffmpeg else [],
                "message": "Dispositivos actualizados." if ffmpeg else "No se encontró FFmpeg.",
            }
        if method == "settings.recording-test":
            from app.services.recording_service import (
                RecordingConfig,
                find_ffmpeg,
                run_recording_diagnostic,
            )

            current = self.settings.load()
            ffmpeg = find_ffmpeg(str(current.get("ffmpeg_path") or ""), force=True)
            if not ffmpeg:
                return {"video_ok": False, "message": "No se encontró un ejecutable FFmpeg válido."}
            result = run_recording_diagnostic(RecordingConfig.from_settings(current), ffmpeg)
            # Technical process output and local paths are never exposed over IPC.
            return {
                "video_ok": bool(result.get("video_ok")),
                "audio_ok": bool(result.get("audio_ok")),
                "audio_state": str(result.get("audio_state") or "No comprobado"),
                "frames": int(result.get("frames") or 0),
                "stage": str(result.get("stage") or "captura"),
                "message": str(result.get("message") or ""),
            }
        if method == "home.counter":
            # The repository serializes its own reads; avoid the broader Home lock,
            # which can be held during a League Client sync.
            profile = self._home_repository.load_last_profile()
            history = self._home_repository.load(profile) if profile else {"matches": []}
            return build_home_counter_summary(history.get("matches", []))
        if method == "home.dashboard":
            with self._home_lock:
                return self._home_snapshot("offline", **_page_params(params))
        if method == "home.sync":
            with self._home_lock:
                try:
                    result = LCUHomeProvider().synchronize(self._home_repository)
                    profile = result["profile"]
                    self._backfill_gold_difference(profile)
                    # Keep a shallow, independently-owned snapshot of the newest
                    # LCU match. Riot data is attached only by the async sync job.
                    from backend.saved_matches import persist_latest_local_lcu_match
                    persist_latest_local_lcu_match(self._home_repository, profile)
                    self._queue_recent_saved_match_sync()
                    # Optional LCU collection calls are isolated from essential history;
                    # preserve cached collection if a client endpoint is unavailable.
                    try:
                        result["collection"] = LCUHomeProvider().synchronize_collection(
                            profile, self._home_repository
                        )
                    except (ConnectionError, OSError, RuntimeError, TimeoutError):
                        result["collection"] = profile.get("collection", {})
                    return self._home_snapshot("conectado", **_page_params(params))
                except (ConnectionError, OSError, RuntimeError, TimeoutError):
                    snapshot = self._home_snapshot("offline", **_page_params(params))
                    snapshot["message"] = "League Client no está conectado; se muestra el historial local."
                    return snapshot
        if method == "home.matches":
            params = _page_params(params)
            with self._home_lock:
                profile = self._home_repository.load_last_profile()
                history = self._home_repository.load(profile) if profile else {"matches": []}
                matches = attach_saved_battlescores(history.get("matches", []), history.get("saved_analyses", []), profile)
                rows = _serialize_home_matches(matches, **params, saved_analyses=history.get("saved_analyses", []))
                return {"matches": rows, "totalMatches": len(matches),
                        "analysisCount": len(history.get("saved_analyses", [])),
                        "hasMore": params["offset"] + len(rows) < len(matches)}
        if method == "home.match.detail":
            match_id = params.get("matchId")
            if not isinstance(match_id, str) or not match_id.strip() or len(match_id) > 120:
                raise ValueError("Identificador de partida no vÃ¡lido")
            with self._home_lock:
                profile = self._home_repository.load_last_profile()
                history = self._home_repository.load(profile) if profile else {"matches": []}
                matches = attach_saved_battlescores(history.get("matches", []), history.get("saved_analyses", []), profile)
                for index, match in enumerate(matches):
                    identifiers = {str(match.get(key) or "") for key in ("stable_match_id", "game_id", "gameId")}
                    if match_id in identifiers:
                        rows = _serialize_home_matches(matches, index, 1, include_details=True, saved_analyses=history.get("saved_analyses", []))
                        if rows:
                            return rows[0]
                        break
            raise KeyError("Partida no encontrada en el historial local")
        if method == "home.clear-history":
            with self._home_lock:
                profile = self._home_repository.load_last_profile()
                if profile:
                    self._home_repository.clear(profile)
                return self._home_snapshot("offline")
        if method == "home.assets":
            names = params.get("champions", [])
            if not isinstance(names, list) or len(names) > 20 or any(
                not isinstance(name, str) or len(name) > 80 for name in names
            ):
                raise ValueError("Lista de campeones no válida")
            splash_names = params.get("splashChampions", [])
            if not isinstance(splash_names, list) or len(splash_names) > 3 or any(
                not isinstance(name, str) or len(name) > 80 for name in splash_names
            ):
                raise ValueError("Invalid splash champion list")
            profile_id = params.get("profileIconId")
            if profile_id is not None and (not isinstance(profile_id, int) or isinstance(profile_id, bool)):
                raise ValueError("Identificador de icono no válido")
            if splash_names:
                return resolve_home_assets(names, profile_id, self._catalog, splash_names)
            return resolve_home_assets(names, profile_id, self._catalog)
        raise KeyError(f"Método no disponible: {method}")

    def _start_soloq_download(self, match_id: str) -> None:
        if not match_id or getattr(self, "_closing", False):
            return
        with self._storage_lock:
            if self._storage_migration.get("state") in {"preparing", "validating", "copying", "verifying", "committing", "reinitializing"}:
                return
        with self._soloq_jobs_lock:
            if match_id in self._soloq_jobs:
                return
            self._soloq_jobs.add(match_id)
        self._soloq_executor.submit(self._run_soloq_download, match_id)

    def _queue_recent_saved_match_sync(self) -> None:
        """After a successful LCU refresh, asynchronously pair finished local sessions with exact Riot history IDs."""
        if getattr(self, "_closing", False):
            return
        try:
            self._soloq_executor.submit(self._auto_sync_completed_saved_matches)
        except RuntimeError:
            logging.getLogger(__name__).debug("Skipped automatic postgame sync during backend shutdown")

    def _auto_sync_completed_saved_matches(self) -> None:
        from backend.saved_matches import _tracker, sync_saved_match
        profile = self._home_repository.load_last_profile()
        saved_ids = [str(row.get("match_id") or "") for row in
                     (self._home_repository.load_saved_lcu_matches(profile) if profile else [])
                     if str(row.get("riot_sync_status") or "local_only") in {"local_only", "pending"}]
        session_ids = [str(row.get("session_id") or "") for row in _tracker().load_saved_sessions_checked()
                       if isinstance(row, dict) and row.get("ended_at")]
        for saved_id in dict.fromkeys([*saved_ids, *session_ids]):
            if not saved_id:
                continue
            try:
                record = sync_saved_match(saved_id, self._home_repository)
                if record.get("status") in {"pending", "downloading", "processing"}:
                    self._start_soloq_download(str(record.get("match_id") or ""))
            except (KeyError, ValueError, OSError):
                # Local LCU entry remains intact; an unavailable Riot match is retryable from its detail panel.
                continue

    def _run_soloq_download(self, match_id: str) -> None:
        from backend.soloq_analyses import download_match, update_status
        try:
            download_match(self._home_repository, match_id)
        except RiotApiError as error:
            logging.getLogger(__name__).warning("soloq.stage match=%s stage=riot_request_failed status=%s retry_after=%s", match_id, error.status_code, error.retry_after)
            if error.status_code == 429:
                message = f"L\u00edmite de solicitudes alcanzado. Reintenta en {error.retry_after or 120} s."
            elif error.status_code == 401:
                message = "Credenciales de Riot no v\u00e1lidas. Rev\u00edsalas en Ajustes."
            elif error.status_code == 403:
                message = "Acceso a Riot denegado. La clave no tiene permisos para esta operaci\u00f3n."
            elif error.status_code == 404:
                message = "Riot no dispone de esta partida o cronología."
            elif error.status_code is None:
                message = "API de Riot no disponible. Comprueba tu conexi\u00f3n e int\u00e9ntalo m\u00e1s tarde."
            else:
                message = str(error)[:300]
            update_status(self._home_repository, match_id, "error", message)
        except (ValueError, OSError, RuntimeError, TimeoutError) as error:
            logging.getLogger(__name__).warning("soloq.stage match=%s stage=validation_or_persistence_failed error_type=%s", match_id, type(error).__name__)
            update_status(self._home_repository, match_id, "error", str(error)[:300])
        except Exception as error:
            logging.getLogger(__name__).exception("soloq.stage match=%s stage=unexpected_processing_failure error_type=%s", match_id, type(error).__name__)
            update_status(self._home_repository, match_id, "error", "No se pudo procesar la respuesta de Riot. Puedes reintentar.")
        finally:
            with self._soloq_jobs_lock:
                self._soloq_jobs.discard(match_id)

    def _run_soloq_ai(self, match_id: str, force: bool) -> None:
        from backend.soloq_analyses import generate_ai_analysis, save_ai_status
        completed = False
        try:
            generate_ai_analysis(self._home_repository, match_id, force=force)
            save_ai_status(self._home_repository, match_id, "complete", "Análisis con IA guardado.")
            completed = True
        except Exception as error:
            save_ai_status(self._home_repository, match_id, "error", str(error)[:300])
        finally:
            with self._soloq_jobs_lock:
                self._soloq_ai_jobs.discard(match_id)
        if completed:
            # Refresh the matchup cache after the report succeeds. The combat
            # result is committed only after validation, so failures preserve
            # the previous matchup advice attached to this match.
            from backend.combat_matchups import context_response
            if context_response(self._home_repository, match_id).get("available"):
                self._start_soloq_combat(match_id)

    def _run_soloq_combat(self, match_id: str) -> None:
        from backend.combat_matchups import generate, persist_status
        try:
            result = generate(self._home_repository, match_id)
            persist_status(self._home_repository, match_id, "complete", "Los cinco enfrentamientos están listos.", result)
        except Exception as error:
            logging.getLogger(__name__).warning("Falló la generación de enfrentamientos de SoloQ: %s", type(error).__name__)
            persist_status(self._home_repository, match_id, "error", str(error)[:300])
        finally:
            with self._soloq_jobs_lock:
                self._soloq_combat_jobs.discard(match_id)

    def _start_soloq_combat(self, match_id: str) -> bool:
        if not match_id or getattr(self, "_closing", False):
            return False
        with self._storage_lock:
            if self._storage_migration.get("state") in {"preparing", "validating", "copying", "verifying", "committing", "reinitializing"}:
                return False
        with self._soloq_jobs_lock:
            if match_id in self._soloq_jobs or match_id in self._soloq_ai_jobs or match_id in self._soloq_combat_jobs:
                return False
            self._soloq_combat_jobs.add(match_id)
        from backend.combat_matchups import persist_status
        persist_status(self._home_repository, match_id, "generating", "Analizando los cinco enfrentamientos con el catálogo local.")
        self._soloq_executor.submit(self._run_soloq_combat, match_id)
        return True

    def _start_soloq_ai(self, match_id: str, force: bool) -> bool:
        if not match_id or getattr(self, "_closing", False):
            return False
        with self._storage_lock:
            if self._storage_migration.get("state") in {"preparing", "validating", "copying", "verifying", "committing", "reinitializing"}:
                return False
        with self._soloq_jobs_lock:
            if match_id in self._soloq_ai_jobs or match_id in self._soloq_combat_jobs:
                return False
            self._soloq_ai_jobs.add(match_id)
        from backend.soloq_analyses import save_ai_status
        save_ai_status(self._home_repository, match_id, "generating", "Generando análisis a partir de datos Match-V5.")
        self._soloq_executor.submit(self._run_soloq_ai, match_id, force)
        return True

    def _backfill_gold_difference(self, profile: dict[str, Any]) -> None:
        """Incrementally fill one missing SoloQ Riot detail/timeline per sync."""
        api_key = str(self.settings.load().get("riot_api_key") or "").strip()
        if not api_key or getattr(self, "_timeline_api_rejected_key", None) == api_key:
            return
        platform = str(profile.get("region") or "").strip().casefold()
        platform = {"euw": "euw1", "eune": "eun1", "europe west": "euw1",
                    "north america": "na1", "korea": "kr", "japan": "jp1"}.get(platform, platform)
        account_region = (
            "europe" if platform in {"euw1", "eun1", "tr1", "ru"}
            else "asia" if platform in {"kr", "jp1", "ph2", "sg2", "th2", "tw2", "vn2"}
            else "americas" if platform in {"na1", "br1", "la1", "la2", "oc1"}
            else None
        )
        if account_region is None:
            return
        from app.services.home_history_service import _solo_queue_matches
        matches = self._home_repository.load(profile).get("matches", [])

        def resolver_version(match: dict[str, Any], key: str) -> int:
            try:
                return max(0, int(match.get(key) or 0))
            except (TypeError, ValueError, OverflowError):
                return 0

        def local_damage_available(match: dict[str, Any]) -> bool:
            champion_id = str(match.get("champion_id") or "")
            participants = match.get("participants")
            if not champion_id or not isinstance(participants, list):
                return False
            for participant in participants:
                if not isinstance(participant, dict) or str(participant.get("champion_id") or "") != champion_id:
                    continue
                if not all(participant.get(key) == match.get(key) for key in ("kills", "deaths", "assists")):
                    continue
                final_stats = participant.get("final_stats")
                if isinstance(final_stats, dict) and _home_number(final_stats, "total_damage_dealt_to_champions") is not None:
                    return True
            return False

        candidate = next((match for match in reversed(_solo_queue_matches(matches))
                          if ((match.get("gold_diff_15") is None
                               and (not match.get("gold_diff_15_checked_at")
                                    or resolver_version(match, "gold_diff_15_resolver_version") < 3)
                               and (_home_number(match, "duration_seconds", positive=True) or 0) >= 900)
                              or (not local_damage_available(match)
                                  and match.get("total_damage_dealt_to_champions") is None
                                  and (not match.get("riot_match_checked_at")
                                       or resolver_version(match, "riot_match_resolver_version") < 3)))
                          and (str(match.get("game_id") or match.get("stable_match_id") or "").startswith(f"{platform.upper()}_")
                               or str(match.get("game_id") or match.get("stable_match_id") or "").isdigit())), None)
        if candidate is None:
            return
        raw_game_id = str(candidate.get("game_id") or candidate["stable_match_id"])
        match_id = raw_game_id if raw_game_id.startswith(f"{platform.upper()}_") else f"{platform.upper()}_{raw_game_id}"
        api = RiotApiService(api_key, account_region=account_region, platform_region=platform)
        needs_damage = (not local_damage_available(candidate)
                        and candidate.get("total_damage_dealt_to_champions") is None
                        and (not candidate.get("riot_match_checked_at")
                             or resolver_version(candidate, "riot_match_resolver_version") < 3))
        detail = None
        patch = {"stable_match_id": str(candidate["stable_match_id"])}
        if needs_damage:
            try:
                detail = api.get_match(match_id)
            except RiotApiError as error:
                # Invalid credentials are final; throttling and transient errors
                # remain retryable at a later explicit sync.
                if error.status_code in {401, 403}:
                    self._timeline_api_rejected_key = api_key
                    return
                if error.status_code != 404:
                    return
            except (OSError, RuntimeError, TimeoutError):
                return
            patch["riot_match_checked_at"] = datetime.now(UTC).isoformat()
            patch["riot_match_resolver_version"] = 3
            patch["riot_match_status"] = "available" if detail is not None else "unavailable"
        info = detail.get("info") if isinstance(detail, dict) else None
        api_participants = info.get("participants") if isinstance(info, dict) else None
        puuid = str(profile.get("puuid") or "")
        local_api = next((item for item in api_participants
                          if isinstance(item, dict) and puuid and str(item.get("puuid") or "") == puuid), None) if isinstance(api_participants, list) else None
        if local_api is None and isinstance(api_participants, list):
            champion_id = str(candidate.get("champion_id") or "")
            fallback = [item for item in api_participants
                        if isinstance(item, dict)
                        and str(item.get("championId") or item.get("champion_id") or "") == champion_id
                        and all(_home_number(item, key) == _home_number(candidate, key)
                                for key in ("kills", "deaths", "assists"))]
            if len(fallback) == 1:
                local_api = fallback[0]
        if isinstance(local_api, dict):
            damage = _home_number(local_api, "totalDamageDealtToChampions")
            if damage is not None:
                patch["total_damage_dealt_to_champions"] = damage

        needs_gold = (candidate.get("gold_diff_15") is None
                      and (not candidate.get("gold_diff_15_checked_at")
                           or resolver_version(candidate, "gold_diff_15_resolver_version") < 3)
                      and (_home_number(candidate, "duration_seconds", positive=True) or 0) >= 900)
        if needs_gold:
            patch["gold_diff_15_resolver_version"] = 3
        if needs_gold and not candidate.get("gold_diff_15_checked_at") and detail is None and needs_damage:
            patch["gold_diff_15_checked_at"] = datetime.now(UTC).isoformat()
            patch["gold_diff_15_status"] = "unavailable"
        elif needs_gold:
            try:
                timeline = api.get_match_timeline(match_id)
            except RiotApiError as error:
                if error.status_code in {401, 403}:
                    self._timeline_api_rejected_key = api_key
                    return
                if error.status_code in {404}:
                    patch["gold_diff_15_checked_at"] = datetime.now(UTC).isoformat()
                    patch["gold_diff_15_status"] = "unavailable"
                elif error.status_code not in {429}:
                    return
            except (OSError, RuntimeError, TimeoutError):
                return
            else:
                value = gold_difference_at_15(candidate, timeline)
                patch["gold_diff_15_checked_at"] = datetime.now(UTC).isoformat()
                patch["gold_diff_15_status"] = "available" if value is not None else "unavailable"
                if value is not None:
                    patch["gold_diff_15"] = value
        self._home_repository.merge(profile, [patch])

    def _home_snapshot(self, connection: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Build the bounded, privacy-safe Home contract from the existing repository."""
        profile = self._home_repository.load_last_profile()
        if not profile:
            analytics = analyze_home_history([])
            analytics["rolling_winrate"] = calculate_soloq_rolling_winrate([])
            analytics["recent_performance"] = analyze_recent_soloq_performance([])
            analytics["champion_performance"] = []
            analytics["ranked_dashboard"] = build_ranked_dashboard_analytics([])
            return {"profile": None, "matches": [], "totalMatches": 0, "hasMore": False,
                    "analytics": analytics, "collection": {}, "connection": connection, "lastSync": None}
        history = self._home_repository.load(profile)
        matches = attach_saved_battlescores(history.get("matches", []), history.get("saved_analyses", []), profile)
        public_matches = _serialize_home_matches(matches, offset, limit, saved_analyses=history.get("saved_analyses", []))
        analytics = analyze_home_history(matches)
        analytics["rolling_winrate"] = calculate_soloq_rolling_winrate(matches)
        analytics["recent_performance"] = analyze_recent_soloq_performance(matches)
        analytics["champion_performance"] = aggregate_soloq_champion_performance(matches, self._catalog)
        analytics["ranked_dashboard"] = build_ranked_dashboard_analytics(matches)
        # Teammates only qualify by stable account identity in the legacy service.
        analytics["teammates"] = [
            {key: item.get(key) for key in ("name", "tag_line", "games", "wins", "winrate")}
            for item in analytics.get("teammates", []) if isinstance(item, dict)
        ]
        for group in ("matchups", "hardest_matchups"):
            analytics[group] = [
                {key: item.get(key) for key in ("champion", "games", "wins", "losses", "winrate")}
                for item in analytics.get(group, []) if isinstance(item, dict)
            ]
        return {
            "profile": {
                **{key: profile.get(key) for key in (
                    "gameName", "tagLine", "summonerLevel", "profileIconId", "region"
                )},
                "ranked": profile.get("ranked") if isinstance(profile.get("ranked"), list) else [],
            },
            "matches": public_matches,
            "totalMatches": len(matches),
            "hasMore": offset + len(public_matches) < len(matches),
            "analytics": analytics,
            "collection": profile.get("collection", {}) if isinstance(profile.get("collection"), dict) else {},
            "connection": connection,
            "lastSync": history.get("last_sync"),
        }


def _page_params(params: dict[str, Any]) -> dict[str, int]:
    """Validate the bounded match-history pagination contract."""
    offset = params.get("offset", 0)
    limit = params.get("limit", 50)
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 100000:
        raise ValueError("Offset de historial no válido")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Tamaño de página no válido")
    return {"offset": offset, "limit": limit}


def _serialize_home_matches(matches: list[dict[str, Any]], offset: int, limit: int,
                            *, include_details: bool = False,
                            saved_analyses: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Return a small display-only page with account/session internals removed."""
    from backend.soloq_analyses import is_deep_analysis_ready
    fields = (
        "stable_match_id", "game_id", "started_at", "duration_seconds", "mode",
        "queue_id", "result", "champion_id", "champion_name", "lane", "kills", "deaths",
        "assists", "cs", "cs_per_min", "vision_score", "items", "trinket", "opponent_state",
        "opponent_champion_name", "opponent_lane", "enemy_team", "analyzable",
        "saved_match_link", "battle_score", "battle_score_version", "champion_classes",
        "lp_delta", "league_points_delta", "lp_change", "ranked_lp_change",
    )
    public = []
    status_by_id = {str(item.get("match_id") or ""): item for item in (saved_analyses or []) if isinstance(item, dict)}
    for match in matches[offset:offset + limit]:
        if not isinstance(match, dict):
            continue
        row = {key: match[key] for key in fields if key in match}
        match_id = str(match.get("stable_match_id") or match.get("game_id") or "")
        saved_analysis = status_by_id.get(match_id) or next((item for item in (saved_analyses or []) if isinstance(item, dict) and str(item.get("history_match_id") or "") == match_id), None)
        if saved_analysis:
            row["soloq_analysis_status"] = saved_analysis.get("status")
            row["soloq_analysis_message"] = saved_analysis.get("status_message")
            row["soloq_analysis_match_id"] = str(saved_analysis.get("match_id") or "") or None
            row["soloq_analysis_ready"] = is_deep_analysis_ready(saved_analysis)
        opponent = match.get("opponent")
        if isinstance(opponent, dict):
            row["opponent"] = {key: opponent[key] for key in ("champion_name", "lane") if key in opponent}
        row["enemy_team"] = [
            {key: enemy[key] for key in ("champion_id", "champion_name") if key in enemy}
            for enemy in match.get("enemy_team", [])[:5]
            if isinstance(enemy, dict) and "champion_name" in enemy
        ] if isinstance(match.get("enemy_team"), list) else []
        participants = match.get("participants")
        if include_details and isinstance(participants, list):
            row["participants"] = [
                {key: participant.get(key) for key in (
                    "participant_id", "team_id", "champion_id", "champion_name", "lane",
                    "win", "kills", "deaths", "assists", "cs", "cs_lane_minions",
                    "cs_neutral_minions", "is_local", "final_stats",
                ) if key in participant}
                for participant in participants[:10] if isinstance(participant, dict)
            ]
            for participant in row["participants"]:
                stats = participant.get("final_stats")
                if isinstance(stats, dict):
                    participant["final_stats"] = {key: stats.get(key) for key in ("total_damage_dealt_to_champions", "solo_kills", "gold_earned", "vision_score", "cs", "cs_lane_minions", "cs_neutral_minions") if key in stats}
        link = row.get("saved_match_link")
        if isinstance(link, dict):
            row["saved_match_link"] = {"saved_match_id": link.get("saved_match_id")}
        public.append(row)
    return public
