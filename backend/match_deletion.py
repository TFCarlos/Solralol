"""Read-only deletion manifests and coordinated match-scoped cleanup."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.services.home_history_service import HomeHistoryRepository
from app.services.live_match_tracker import LiveMatchTracker
from app.services.match_history_cache import MatchHistoryCache
from app.services.recording_service import RecordingLibrary
from app.services.settings_service import SettingsService
from app.services.storage_manager import get_storage_manager

_LOG = logging.getLogger(__name__)
_DELETE_LOCK = threading.Lock()


def _ids(*values: Any) -> set[str]:
    return {str(value).strip() for value in values if value is not None and str(value).strip()}


def _session_match_ids(record: dict[str, Any]) -> set[str]:
    final_sync = record.get("final_sync") if isinstance(record.get("final_sync"), dict) else {}
    return _ids(record.get("match_id"), record.get("riot_match_id"), final_sync.get("match_id"), final_sync.get("riot_match_id"))


def _metadata_match_ids(metadata: dict[str, Any]) -> set[str]:
    return _session_match_ids(metadata) | _ids(metadata.get("matchId"), metadata.get("riotMatchId"))


def _resolve_scope(*, session_id: str | None, match_id: str | None, repository: HomeHistoryRepository | None = None) -> dict[str, Any]:
    if not session_id and not match_id:
        raise ValueError("Falta el identificador de la partida guardada.")
    repository = repository or HomeHistoryRepository()
    profile = repository.load_last_profile()
    analyses = repository.load_saved_analyses(profile) if profile else []
    history = repository.load(profile) if profile else {}
    all_sessions = LiveMatchTracker({}, persist=False).load_saved_sessions()
    session = next((item for item in all_sessions if session_id and str(item.get("session_id") or "") == session_id), None)
    analysis = next((item for item in analyses if match_id and str(item.get("match_id") or "") == match_id), None)
    local_loader = getattr(repository, "load_saved_lcu_matches", None)
    local_rows = local_loader(profile) if profile and callable(local_loader) else []
    local_record = next((item for item in local_rows if match_id and str(item.get("match_id") or "") == match_id), None)
    if not session and not analysis and not local_record:
        raise KeyError("La partida guardada ya no existe. Actualiza la biblioteca.")

    session_ids: set[str] = set()
    riot_ids = _ids(match_id)
    if session:
        session_ids |= _ids(session.get("session_id"))
        riot_ids |= _session_match_ids(session)
    if analysis:
        riot_ids |= _ids(analysis.get("match_id"), analysis.get("history_match_id"))
    if local_record:
        riot_ids |= _ids(local_record.get("match_id"))
        session_ids |= _ids(local_record.get("session_id"))
    changed = True
    while changed:
        before = (len(session_ids), len(riot_ids))
        for candidate in all_sessions:
            candidate_id = str(candidate.get("session_id") or "")
            if candidate_id == session_id or (_session_match_ids(candidate) & riot_ids):
                session_ids |= _ids(candidate_id)
                riot_ids |= _session_match_ids(candidate)
        for candidate in analyses:
            candidate_ids = _ids(candidate.get("match_id"), candidate.get("history_match_id"))
            if candidate_ids & riot_ids:
                riot_ids |= candidate_ids
        changed = before != (len(session_ids), len(riot_ids))

    # Expand history links only after the match/session relationship is known.
    # In particular, never let a missing saved_match_id compare equal to an
    # absent query session ID, which would attach unrelated rows to this delete.
    linked_history_rows: list[dict[str, Any]] = []
    if session_ids:
        for row in (history.get("matches", []) if isinstance(history, dict) else []):
            link = row.get("saved_match_link") if isinstance(row, dict) else None
            if not isinstance(link, dict) or str(link.get("saved_match_id") or "") not in session_ids:
                continue
            linked_history_rows.append(row)
            if str(link.get("association") or "").casefold() == "exact":
                riot_ids |= _ids(row.get("stable_match_id"), row.get("game_id"), row.get("gameId"))
    changed = True
    while changed:
        before = (len(session_ids), len(riot_ids))
        for candidate in all_sessions:
            candidate_id = str(candidate.get("session_id") or "")
            if _session_match_ids(candidate) & riot_ids:
                session_ids |= _ids(candidate_id)
                riot_ids |= _session_match_ids(candidate)
        for candidate in analyses:
            candidate_ids = _ids(candidate.get("match_id"), candidate.get("history_match_id"))
            if candidate_ids & riot_ids:
                riot_ids |= candidate_ids
        changed = before != (len(session_ids), len(riot_ids))

    linked_analyses = [item for item in analyses if _ids(item.get("match_id"), item.get("history_match_id")) & riot_ids]
    linked_sessions = [item for item in all_sessions if str(item.get("session_id") or "") in session_ids]
    uncertain_history = [row for row in linked_history_rows
                         if str((row.get("saved_match_link") or {}).get("association") or "").casefold() != "exact"]
    return {"repository": repository, "profile": profile, "history": history, "sessions": all_sessions,
            "session": session, "local_record": local_record, "analysis": analysis, "analyses": linked_analyses,
            "linked_sessions": linked_sessions, "session_ids": session_ids, "riot_ids": riot_ids,
            "uncertain_history": uncertain_history, "session_id": session_id, "match_id": match_id}


def _file_resource(path: Path, category: str, resource_type: str, *, owner: str = "") -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        stat = path.stat()
    except OSError:
        return None
    file_key = hashlib.sha256(str(path.resolve()).casefold().encode("utf-8")).hexdigest()
    return {"id": f"file:{file_key}", "category": category, "kind": "file", "type": resource_type,
            "name": path.name, "size": stat.st_size, "modified": stat.st_mtime_ns,
            "owner": owner, "path": path}


def _estimated_json_size(value: Any) -> int | None:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
    except (TypeError, ValueError, OverflowError):
        return None


def _record_resource(category: str, name: str, detail: str = "", *, value: Any = None) -> dict[str, Any]:
    return {"id": f"record:{category}:{name}", "category": category, "kind": "record", "type": "Registro local",
            "name": name, "detail": detail, "size": _estimated_json_size(value) if value is not None else None, "owner": ""}


def _state_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        payload = repr(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_manifest(scope: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    records = 0
    session = scope["session"] or {}
    local_record = scope.get("local_record") or {}
    analysis = scope["analysis"] or (scope["analyses"][0] if scope["analyses"] else {})
    champion = str(session.get("champion_name") or local_record.get("champion") or (analysis or {}).get("champion") or "Partida")
    started_at = str(session.get("started_at") or local_record.get("started_at") or (analysis or {}).get("started_at") or "")

    if session:
        session_data = {key: value for key, value in session.items()
                        if key not in {"ai_match_analysis", "ai_match_review", "ai_analysis"}}
        entry = _record_resource("partida", f"Partida guardada · {scope['session_id']}", "Registro de live_match_sessions.json; incluye metadatos y estadísticas", value=session_data)
        entry["state"] = _state_hash(session)
        resources.append(entry)
        records += 1
    if local_record:
        entry = _record_resource("partida", f"Ficha local LCU · {local_record.get('match_id')}", "Entrada saved_lcu_matches; resumen superficial, participantes locales y vínculo de grabación", value=local_record)
        entry["state"] = _state_hash(local_record)
        resources.append(entry)
        records += 1
    for item in scope["analyses"]:
        riot_id = str(item.get("match_id") or "")
        analysis_data = {key: value for key, value in item.items() if key != "ai_analysis"}
        entry = _record_resource("partida", f"Análisis guardado · {riot_id}", "Entrada saved_analyses de match_history.json; datos procesados, participantes y estado", value=analysis_data)
        entry["state"] = _state_hash(item)
        resources.append(entry)
        records += 1
        if item.get("ai_analysis"):
            entry = _record_resource("ia", f"Análisis con IA · {riot_id}", "Resultado estructurado guardado dentro del análisis", value=item.get("ai_analysis"))
            entry["state"] = _state_hash(item.get("ai_analysis")); resources.append(entry)
            records += 1
    for item in scope["linked_sessions"]:
        for field, label in (("ai_match_analysis", "Análisis IA de repaso"), ("ai_match_review", "Revisión IA"), ("ai_analysis", "Análisis IA")):
            if item.get(field):
                entry = _record_resource("ia", f"{label} · {item.get('session_id')}", "Dato asociado a la sesión guardada", value=item.get(field))
                entry["state"] = _state_hash(item.get(field))
                resources.append(entry)
                records += 1

    for session_id in sorted(scope["session_ids"]):
        resources.append(_record_resource("historial", f"Vínculo local · {session_id}", "Referencia en match_history.json; se retira solo el vínculo guardado, no el historial general", value={"saved_match_id": session_id}))
        records += 1
    profile = scope["profile"]
    if profile:
        for row in (scope["history"].get("matches", []) if isinstance(scope["history"], dict) else []):
            link = row.get("saved_match_link") if isinstance(row, dict) else None
            if isinstance(link, dict) and str(link.get("saved_match_id") or "") in scope["session_ids"]:
                game_id = str(row.get("stable_match_id") or row.get("game_id") or "partida")
                derived = {"link": link, "summary": row.get("performance_summary")}
                entry = _record_resource("historial", f"Resumen derivado · {game_id}", "Campos saved_match_link y performance_summary en match_history.json; la fila permanece", value=derived)
                entry["state"] = _state_hash(derived)
                resources.append(entry)
                records += 1

    settings = SettingsService().load()
    library = RecordingLibrary(settings.get("recording_output_dir") or None)
    linked_videos: list[Path] = []
    preserved_shared: list[dict[str, Any]] = []
    local_recording_id = str((scope.get("local_record") or {}).get("recording_id") or "")
    local_rows = scope["repository"].load_saved_lcu_matches(scope["profile"]) if scope.get("profile") and hasattr(scope["repository"], "load_saved_lcu_matches") else []
    other_lcu_owners = [item for item in local_rows if str(item.get("recording_id") or "") == local_recording_id
                        and str(item.get("match_id") or "") != str((scope.get("local_record") or {}).get("match_id") or "")] if local_recording_id else []
    for video in library.video_files():
        metadata = library.load_metadata(video)
        metadata_session = str(metadata.get("session_id") or "")
        metadata_recording_id = str(metadata.get("recording_id") or "")
        by_session = bool(metadata_session and metadata_session in scope["session_ids"])
        by_match = bool(_metadata_match_ids(metadata) & scope["riot_ids"])
        recording_owners = [item for item in scope["sessions"] if metadata_recording_id and str(item.get("recording_id") or "") == metadata_recording_id]
        by_recording = bool((recording_owners and any(str(item.get("session_id") or "") in scope["session_ids"] for item in recording_owners))
                            or (local_recording_id and metadata_recording_id == local_recording_id))
        if not (by_session or by_match or by_recording):
            continue
        if len({str(item.get("session_id") or "") for item in recording_owners}) > 1 or other_lcu_owners:
            preserved_shared.append({"id": f"preserved:shared-recording:{video.name}", "category": "conservado", "kind": "record", "type": "Grabación compartida", "name": video.name, "detail": "Varias sesiones hacen referencia a este recurso; se conserva para evitar borrar datos compartidos", "size": None})
            continue
        linked_videos.append(video)
        owner = metadata_session or next(iter(sorted(scope["riot_ids"])), "")
        for target, category, kind in ((video, "grabacion", "Vídeo"), (library.metadata_path(video), "grabacion", "Metadatos")):
            resource = _file_resource(target, category, kind, owner=owner)
            if resource:
                resources.append(resource)
        seek_dir = library.directory / ".seek_cache"
        try:
            for target in seek_dir.iterdir() if seek_dir.is_dir() else ():
                if target.is_file() and target.name.startswith(f"{video.name}.") and target.name.endswith(".seek.mp4"):
                    resource = _file_resource(target, "grabacion", "Caché de reproducción", owner=owner)
                    if resource:
                        resources.append(resource)
        except OSError:
            _LOG.warning("Could not inspect seek cache during deletion preview")
        thumb_key = hashlib.sha256(str(video.resolve()).casefold().encode("utf-8")).hexdigest()
        thumb_dir = get_storage_manager().recording_thumbnails_dir
        try:
            for target in thumb_dir.glob(f"{thumb_key}.*.jpg") if thumb_dir.is_dir() else ():
                resource = _file_resource(target, "grabacion", "Miniatura", owner=owner)
                if resource:
                    resources.append(resource)
        except OSError:
            _LOG.warning("Could not inspect thumbnail cache during deletion preview")

    # Riot payloads and normalized data live as per-match entries in one shared cache file.
    cache = MatchHistoryCache()
    cache_data = cache.data
    match_cache = cache_data.get("matches", {}) or {}
    for match_id in sorted(scope["riot_ids"]):
        entries = [(key, value) for key, value in match_cache.items() if key == match_id or str(key).startswith(f"{match_id}:")]
        if entries:
            entry = _record_resource("riot", f"Datos de partida procesados · {match_id}", "Registro asociado en match_history_cache.json; el resto de la caché se conserva", value=entries)
            entry["state"] = _state_hash(entries); resources.append(entry); records += 1
    for collection, label in (("raw_matches", "Respuesta Match-V5"), ("timelines", "Cronología Match-V5")):
        for key in scope["riot_ids"]:
            if key in (cache_data.get(collection, {}) or {}):
                cached_value = (cache_data.get(collection, {}) or {})[key]
                entry = _record_resource("riot", f"{label} · {key}", "Registro asociado en match_history_cache.json; el resto de la caché se conserva", value=cached_value)
                entry["state"] = _state_hash(cached_value); resources.append(entry); records += 1

    log_dir = get_storage_manager().match_logs_dir
    log_ids = scope["session_ids"] | scope["riot_ids"]
    for identifier in sorted(log_ids):
        if not identifier or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-." for char in identifier):
            continue
        for suffix in (".json", ".log"):
            resource = _file_resource(log_dir / f"match_{identifier}{suffix}", "riot" if identifier in scope["riot_ids"] else "historial", "Registro local", owner=identifier)
            if resource:
                resources.append(resource)

    # Deduplicate paths (e.g. the same file reached via session and Riot IDs).
    unique: dict[str, dict[str, Any]] = {}
    for resource in resources:
        unique[resource["id"]] = resource
    resources = list(unique.values())
    files = [item for item in resources if item["kind"] != "record"]
    record_items = [item for item in resources if item["kind"] == "record"]
    # For embedded records, count their compact JSON payload as an estimate;
    # this is not the size of the shared cache/history container.
    known_sizes = [int(item["size"]) for item in resources if isinstance(item.get("size"), int) and item["size"] >= 0]
    bytes_total = sum(known_sizes) if known_sizes or not resources else None
    file_signature = [{"id": item["id"], "size": item["size"], "modified": item.get("modified")} for item in sorted(files, key=lambda entry: entry["id"])]
    fingerprint_payload = {"match": match_id_or_session(scope), "files": file_signature,
                           "records": sorted([{"id": item["id"], "state": item.get("state", "")} for item in record_items], key=lambda item: (item["id"], item["state"]))}
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    public_resources = [{key: value for key, value in item.items() if key not in {"path", "modified", "owner", "state"}}
                        for item in sorted(resources, key=lambda entry: (entry["category"], entry["name"]))]
    preserved = [
        {"id": "preserved:profile", "category": "conservado", "kind": "record", "type": "Datos protegidos", "name": "Perfil persistente del jugador", "detail": "Identidad, estadísticas generales y datos de cuenta", "size": None},
        {"id": "preserved:riot-remote", "category": "conservado", "kind": "record", "type": "Datos protegidos", "name": "Historial oficial de Riot", "detail": "Permanece en los servidores de Riot; esta acción solo elimina datos locales", "size": None},
        {"id": "preserved:history", "category": "conservado", "kind": "record", "type": "Datos protegidos", "name": "Historial general de Inicio", "detail": "Las partidas recientes del perfil permanecen", "size": None},
        {"id": "preserved:shared", "category": "conservado", "kind": "record", "type": "Datos protegidos", "name": "Ajustes y recursos compartidos", "detail": "Configuración y recursos Data Dragon permanecen", "size": None},
        {"id": "preserved:uncertain-recordings", "category": "conservado", "kind": "record", "type": "Datos protegidos", "name": "Grabaciones sin vínculo verificable", "detail": "No se seleccionan por campeón, fecha ni similitud de nombre", "size": None},
    ] + preserved_shared
    if scope["uncertain_history"]:
        count = len(scope["uncertain_history"])
        preserved.append({"id": "preserved:unverified-history", "category": "conservado", "kind": "record", "type": "Vínculos no verificados",
                          "name": f"Datos Riot sin vínculo exacto · {count} partidas", "detail": f"Se conservan {count} registros porque los enlaces locales no confirman el mismo ID de partida", "size": None})
    public = {"manifestId": fingerprint, "matchId": scope["match_id"] or next(iter(sorted(scope["riot_ids"])), None),
              "sessionId": scope["session_id"], "champion": champion, "startedAt": started_at,
              "resources": public_resources, "preserved": preserved,
              "summary": {"files": len(files), "records": len(record_items), "bytes": bytes_total}}
    internal = {"scope": scope, "resources": resources, "library": library, "manifestId": fingerprint,
                "linkedVideos": linked_videos}
    return public, internal


def match_id_or_session(scope: dict[str, Any]) -> str:
    return str(scope["match_id"] or scope["session_id"] or "")


def preview_saved_match_deletion(*, session_id: str | None = None, match_id: str | None = None,
                                 repository: HomeHistoryRepository | None = None) -> dict[str, Any]:
    scope = _resolve_scope(session_id=session_id, match_id=match_id, repository=repository)
    public, _internal = _build_manifest(scope)
    return public


def delete_saved_match_footprint(*, session_id: str | None = None, match_id: str | None = None,
                                manifest_id: str, repository: HomeHistoryRepository | None = None) -> dict[str, Any]:
    if not manifest_id or len(manifest_id) != 64:
        raise ValueError("Actualiza la vista previa antes de eliminar la partida.")
    if not _DELETE_LOCK.acquire(blocking=False):
        raise ValueError("Ya hay una eliminación de partida en curso. Espera a que termine.")
    try:
        scope = _resolve_scope(session_id=session_id, match_id=match_id, repository=repository)
        _public, internal = _build_manifest(scope)
        if internal["manifestId"] != manifest_id:
            raise ValueError("Los archivos asociados cambiaron desde la vista previa. Revísala y confirma de nuevo.")

        # Delete the exact physical files reviewed in the manifest, then remove the owned records.
        for video in internal["linkedVideos"]:
            if not video.is_file():
                continue
            if not internal["library"].delete(video):
                _LOG.error("Saved match cleanup failed at recording stage (name=%s)", video.name)
                raise ValueError("No se pudo eliminar la grabación vinculada. Cierra cualquier reproductor abierto e inténtalo de nuevo.")

        from app.services.match_log_service import MatchLogService
        logs = MatchLogService()
        for identifier in sorted(scope["session_ids"] | scope["riot_ids"]):
            try:
                logs.delete_match_log(identifier)
            except ValueError:
                continue
        remaining = [str(resource["path"]) for resource in internal["resources"]
                     if resource.get("path") and Path(resource["path"]).exists()]
        if remaining:
            _LOG.error("Saved match cleanup left %s manifest files on disk", len(remaining))
            raise ValueError("Algunos archivos siguen en uso o no se pudieron borrar. Actualiza la vista previa e inténtalo de nuevo.")

        try:
            tracker = LiveMatchTracker({}, persist=False)
            for sid in sorted(scope["session_ids"]):
                tracker.delete_saved_session(sid)
            profile = scope["profile"]
            repository = scope["repository"]
            if profile:
                local_record = scope.get("local_record") or {}
                local_match_id = str(local_record.get("match_id") or "")
                if local_match_id:
                    repository.delete_saved_lcu_match(profile, local_match_id)
                for sid in scope["session_ids"]:
                    repository.unlink_saved_match(profile, sid)
            from backend.soloq_analyses import delete_analysis
            for item in scope["analyses"]:
                canonical_id = str(item.get("match_id") or "")
                if canonical_id:
                    delete_analysis(repository, canonical_id)
            cache = MatchHistoryCache()
            for riot_id in sorted(scope["riot_ids"]):
                cache.delete_match_data(riot_id)
        except Exception as error:
            _LOG.exception("Saved match cleanup failed after media stage")
            raise ValueError("Se eliminó parte del contenido, pero falló la limpieza de los datos locales. Actualiza la vista previa antes de reintentar.") from error

        return {"deleted": True, "recordingDeleted": bool(internal["linkedVideos"]), "warnings": []}
    finally:
        _DELETE_LOCK.release()
