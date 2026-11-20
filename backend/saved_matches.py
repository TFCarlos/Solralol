"""Electron adapter for the legacy saved Live Match sessions."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.services.live_match_tracker import LiveMatchTracker
from app.services.storage_manager import StorageWriteError

_analysis_lock = __import__("threading").Lock()


def _tracker() -> LiveMatchTracker:
    return LiveMatchTracker({}, persist=False)


def _local_player(session: dict[str, Any]) -> dict[str, Any]:
    players = session.get("players") if isinstance(session.get("players"), dict) else {}
    player = players.get(str(session.get("local_player_key") or ""), {})
    return player if isinstance(player, dict) else {}


def _saved_participant_cs(participant: dict[str, Any], match: dict[str, Any]) -> int | None:
    """Expose only CS with a known component-based definition."""
    if match.get("cs_source_version") == 2 and participant.get("cs_source_version") == 2:
        value = participant.get("cs")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    if participant.get("is_local") or participant.get("is_player") or participant.get("local"):
        value = match.get("cs")
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None
    return None


def _matches_profile_identity(participant: dict[str, Any], profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    for participant_key, profile_key in (
        ("puuid", "puuid"),
        ("account_id", "accountId"),
        ("summoner_id", "summonerId"),
    ):
        participant_id = participant.get(participant_key)
        profile_id = profile.get(profile_key)
        if participant_id not in (None, "", 0, "0") and profile_id not in (None, "", 0, "0"):
            if str(participant_id) == str(profile_id):
                return True
    return False


def _refresh_selected_lcu_detail(
    repository: Any,
    profile: dict[str, Any],
    session_id: str,
    history_match: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Refresh one stale selected roster from the local LCU detail endpoint."""
    if not isinstance(history_match, dict) or int(history_match.get("queue_id") or 0) != 420:
        return history_match
    if history_match.get("participant_data_version") == 4:
        return history_match
    game_id = str(history_match.get("game_id") or history_match.get("gameId") or session_id)
    try:
        from app.services.home_history_service import LCUHomeProvider

        provider = LCUHomeProvider()
        if not provider.cliente.refresh_connection():
            return history_match
        raw = provider._get(f"/lol-match-history/v1/games/{game_id}")
        normalized = provider._normalize(raw, profile, history_match)
        if not normalized or len(normalized.get("participants", [])) != 10:
            return history_match
        normalized["participant_data_version"] = 4
        normalized["enrichment"] = {
            **(history_match.get("enrichment") or {}),
            "detail_attempted": True,
            "participants_complete": True,
            "participant_data_version": 4,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        repository.merge(profile, [normalized])
        return next((row for row in repository.load(profile).get("matches", [])
                     if isinstance(row, dict) and session_id in {
                         str(row.get("stable_match_id") or ""),
                         str(row.get("game_id") or ""),
                         str(row.get("gameId") or ""),
                     }), normalized)
    except (ConnectionError, OSError, RuntimeError, TimeoutError, ValueError):
        # Cached LCU details remain usable when the client or endpoint is offline.
        return history_match


def _participant_sides(participants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Assign sides only when the local participant and team IDs are authoritative."""
    local_rows = [item for item in participants if item.get("is_local") or item.get("is_player") or item.get("local")]
    local_team = local_rows[0].get("team_id", local_rows[0].get("teamId")) if len(local_rows) == 1 else None
    team_values = {str(item.get("team_id", item.get("teamId"))) for item in participants
                   if item.get("team_id", item.get("teamId")) not in (None, 0, "0", "")}
    known = (local_team not in (None, 0, "0", "") and len(team_values) == 2
             and all(item.get("team_id", item.get("teamId")) not in (None, 0, "0", "") for item in participants))
    normalized = []
    for item in participants:
        team = item.get("team_id", item.get("teamId"))
        marked_side = str(item.get("side") or "").casefold()
        if known:
            side = "allied" if str(team) == str(local_team) else "enemy"
        elif len(local_rows) == 1 and item is local_rows[0]:
            side = "allied"
        elif marked_side in {"allied", "ally"}:
            side = "allied"
        elif marked_side in {"enemy", "opponent"}:
            side = "enemy"
        else:
            side = "unknown"
        normalized.append({**item, "side": side})
    return normalized, bool(known and len(local_rows) == 1)


def _summary(session: dict[str, Any]) -> dict[str, Any]:
    player = _local_player(session)
    key = str(session.get("local_player_key") or "")
    final = session.get("final_scoreboard") if isinstance(session.get("final_scoreboard"), dict) else {}
    stats = final.get(key) if isinstance(final.get(key), dict) else {}
    return {
        "id": str(session.get("session_id") or ""),
        "champion": str(player.get("champion_name") or session.get("champion_name") or "Campeón no disponible"),
        "championId": player.get("champion_id"),
        "startedAt": str(session.get("started_at") or ""),
        "duration": session.get("duration"),
        "mode": str(session.get("game_mode") or "Modo desconocido"),
        "role": str(player.get("role") or ""),
        "kills": stats.get("kills", player.get("kills")),
        "deaths": stats.get("deaths", player.get("deaths")),
        "assists": stats.get("assists", player.get("assists")),
        "cs": stats.get("cs", player.get("cs")),
        "win": stats.get("win", player.get("win")) if isinstance(stats.get("win", player.get("win")), bool) else None,
        "analysisAvailable": False,
        "analysisState": "local_only",
        "deepAnalysisReady": False,
        "riotMatchId": None,
    }


def _local_summary(record: dict[str, Any]) -> dict[str, Any]:
    win = record.get("result") == "victory" if record.get("result") in {"victory", "defeat"} else None
    sync_state = str(record.get("riot_sync_status") or "local_only")
    public_state = {"failed": "error", "pending": "pending", "downloading": "downloading", "processing": "processing"}.get(sync_state, "local_only")
    return {"id": str(record.get("match_id") or ""), "champion": str(record.get("champion") or "Campeón no disponible"),
        "championId": record.get("champion_id"), "startedAt": str(record.get("started_at") or ""),
        "duration": record.get("duration"), "mode": str(record.get("mode") or "Modo desconocido"), "queueId": record.get("queue_id"),
        "role": str(record.get("role") or ""), "kills": record.get("kills"), "deaths": record.get("deaths"),
        "assists": record.get("assists"), "cs": record.get("cs"), "win": win,
        "analysisAvailable": False, "analysisState": public_state, "deepAnalysisReady": False,
        "riotMatchId": None, "analysisMessage": str(record.get("riot_sync_message") or ""), "sessionId": str(record.get("session_id") or ""), "retainedAnalysis": False}


def _match_ids(session: dict[str, Any]) -> set[str]:
    final_sync = session.get("final_sync") if isinstance(session.get("final_sync"), dict) else {}
    return {str(value).strip() for value in (
        session.get("match_id"), session.get("riot_match_id"), final_sync.get("match_id"), final_sync.get("riot_match_id")
    ) if value is not None and str(value).strip()}


def _deep_analysis_for(session: dict[str, Any], analyses: list[dict[str, Any]]) -> dict[str, Any] | None:
    identifiers = _match_ids(session)
    return next((item for item in analyses if identifiers & {
        str(item.get("match_id") or ""), str(item.get("history_match_id") or "")
    }), None)


def persist_latest_local_lcu_match(repository: Any, profile: dict[str, Any], match_id: str | None = None) -> dict[str, Any] | None:
    """Snapshot a matching or newest unseen LCU history row as shallow saved data."""
    requested_match_id = match_id
    history = repository.load(profile)
    existing = repository.load_saved_lcu_matches(profile)
    known = {str(item.get("match_id") or "") for item in existing}
    candidates = [item for item in history.get("matches", []) if isinstance(item, dict)
        and str(item.get("stable_match_id") or item.get("game_id") or item.get("gameId") or "").strip()
        and isinstance(item.get("data_quality"), dict) and item["data_quality"].get("source") == "LCU"]
    if match_id:
        candidates = [item for item in candidates if match_id in {str(item.get("stable_match_id") or ""), str(item.get("game_id") or ""), str(item.get("gameId") or "")}]
    candidates.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    for source in candidates:
        match_id = str(source.get("stable_match_id") or source.get("game_id") or source.get("gameId") or "").strip()
        if match_id in known:
            if requested_match_id:
                return next((item for item in existing if str(item.get("match_id") or "") == match_id), None)
            continue
        exact_session = next((session for session in _tracker().load_saved_sessions_checked()
            if isinstance(session, dict) and match_id in _match_ids(session)), None)
        saved_link = source.get("saved_match_link") if isinstance(source.get("saved_match_link"), dict) else {}
        if exact_session is None and str(saved_link.get("association") or "").casefold() == "exact":
            linked_id = str(saved_link.get("saved_match_id") or "")
            exact_session = next((session for session in _tracker().load_saved_sessions_checked()
                if isinstance(session, dict) and str(session.get("session_id") or "") == linked_id), None)
        participants = []
        for item in source.get("participants", []) if isinstance(source.get("participants"), list) else []:
            if not isinstance(item, dict):
                continue
            participants.append({key: item.get(key) for key in (
                "source_index", "participant_id", "champion_id", "champion_name", "team_id", "side", "lane", "role", "display_role", "team_position", "individual_position", "timeline_role", "lane_raw", "is_local", "is_player",
                "kills", "deaths", "assists", "cs", "cs_lane_minions", "cs_neutral_minions", "cs_source_version", "level", "items", "summoner_spells", "runes", "win",
            ) if key in item})
        record = {
            "match_id": match_id, "source": "LCU", "champion_id": source.get("champion_id"),
            "champion": str(source.get("champion_name") or "Campeón no disponible"),
            "started_at": str(source.get("started_at") or ""), "duration": source.get("duration_seconds"),
            "queue_id": source.get("queue_id"), "mode": str(source.get("mode") or "Modo desconocido"),
            "role": str(source.get("lane") or ""), "result": source.get("result"),
            "kills": source.get("kills"), "deaths": source.get("deaths"), "assists": source.get("assists"),
            "cs": source.get("cs"), "cs_source_version": source.get("cs_source_version"), "items": list(source.get("items") or [])[:7],
            "summoner_spells": list(source.get("summoner_spells") or [])[:2],
            "runes": list(source.get("runes") or []), "participants": participants,
            "recording_id": str(source.get("recording_id") or (exact_session or {}).get("recording_id") or "") or None,
            "session_id": str((exact_session or {}).get("session_id") or "") or None, "deep_analysis": False,
            "riot_sync_status": "pending", "riot_sync_message": "Pendiente de sincronización segura con Riot.",
        }
        if repository.save_lcu_match(profile, record, limit=LiveMatchTracker.MAX_SAVED_SESSIONS):
            return record
        return None
    return None


def list_saved_matches() -> dict[str, Any]:
    from backend.soloq_analyses import is_deep_analysis_ready
    sessions = [item for item in _tracker().load_saved_sessions_checked() if isinstance(item, dict) and item.get("session_id") and item.get("ended_at")]
    sessions.sort(key=lambda item: str(item.get("ended_at") or item.get("started_at") or ""), reverse=True)
    from app.services.home_history_service import HomeHistoryRepository
    repository = HomeHistoryRepository()
    profile = repository.load_last_profile()
    analyses = repository.load_saved_analyses(profile) if profile else []
    local_records = repository.load_saved_lcu_matches(profile) if profile else []
    matches = []
    session_by_match: dict[str, dict[str, Any]] = {}
    for session in sessions:
        for identifier in _match_ids(session):
            session_by_match[identifier] = session
    local_ids = {str(item.get("match_id") or "") for item in local_records}
    for record in local_records:
        row = _local_summary(record)
        session = session_by_match.get(row["id"])
        if session:
            row["sessionId"] = str(session.get("session_id") or "")
        analysis = next((item for item in analyses if row["id"] in {str(item.get("match_id") or ""), str(item.get("history_match_id") or "")}), None)
        if analysis:
            row["riotMatchId"] = str(analysis.get("match_id") or "") or None
            row["deepAnalysisReady"] = is_deep_analysis_ready(analysis)
            row["analysisAvailable"] = row["deepAnalysisReady"]
            row["analysisState"] = analysis.get("status") or "pending"
            row["analysisMessage"] = analysis.get("status_message") or ""
            row["retainedAnalysis"] = True
        matches.append(row)
    for session in sessions:
        if _match_ids(session) & local_ids:
            continue
        row = _summary(session)
        analysis = _deep_analysis_for(session, analyses)
        if analysis:
            row["riotMatchId"] = str(analysis.get("match_id") or "") or None
            row["deepAnalysisReady"] = is_deep_analysis_ready(analysis)
            row["analysisAvailable"] = row["deepAnalysisReady"]
            row["analysisState"] = analysis.get("status") or "pending"
            row["analysisMessage"] = analysis.get("status_message") or ""
        matches.append(row)
    # The browser is the LCU history, not the small retained-analysis repository.
    # Use the same cached history consumed by Home and overlay Riot analysis state
    # by stable history/Riot identifiers without copying every row into saved_lcu_matches.
    history = repository.load(profile) if profile else {"matches": []}
    saved_analyses = repository.load_saved_analyses(profile) if profile else []
    history_rows = history.get("matches", []) if isinstance(history.get("matches"), list) else []
    known = {str(item.get("id") or "") for item in matches}
    for source in sorted((row for row in history_rows if isinstance(row, dict)),
                         key=lambda row: str(row.get("started_at") or ""), reverse=True):
        match_id = str(source.get("stable_match_id") or source.get("game_id") or source.get("gameId") or "").strip()
        if not match_id or match_id in known:
            continue
        analysis = next((item for item in saved_analyses if match_id in {
            str(item.get("match_id") or ""), str(item.get("history_match_id") or "")
        }), None)
        row = {
            "id": match_id, "champion": str(source.get("champion_name") or "Campeón no disponible"),
            "championId": source.get("champion_id"), "startedAt": str(source.get("started_at") or ""),
            "duration": source.get("duration_seconds"), "mode": str(source.get("mode") or "Modo desconocido"),
            "queueId": source.get("queue_id"), "role": str(source.get("lane") or ""),
            "kills": source.get("kills"), "deaths": source.get("deaths"), "assists": source.get("assists"),
            "cs": source.get("cs"), "win": source.get("result") == "victory" if source.get("result") in {"victory", "defeat"} else None,
            "analysisAvailable": False, "analysisState": "local_only", "deepAnalysisReady": False,
            "riotMatchId": None, "analysisMessage": str(source.get("soloq_analysis_message") or ""),
            "historySource": "cache" if history.get("last_sync") else "local", "retainedAnalysis": bool(analysis),
        }
        if analysis:
            row["riotMatchId"] = str(analysis.get("match_id") or "") or None
            ready = is_deep_analysis_ready(analysis)
            row.update(deepAnalysisReady=ready, analysisAvailable=ready,
                       analysisState=analysis.get("status") or "pending",
                       analysisMessage=analysis.get("status_message") or "", retainedAnalysis=True)
        matches.append(row)
        known.add(match_id)
    matches.sort(key=lambda row: str(row.get("startedAt") or ""), reverse=True)
    from backend.analysis_settings import load_configuration
    analysis_limit = load_configuration()["analysis_limits"]["max_active_matches"]
    return {"matches": matches, "count": len(matches), "historyCount": len(history_rows),
            "analysisCount": len(saved_analyses), "limit": analysis_limit,
            "overLimit": len(saved_analyses) > analysis_limit, "historyCached": bool(history.get("last_sync")),
            "historyAvailable": bool(profile and history_rows),
            "legacyCount": len(sessions)}


def _sync_saved_match(session_id: str, repository: Any | None = None) -> dict[str, Any]:
    """Register Riot detail only from an exact local match ID/history association."""
    tracker = _tracker()
    session = next((item for item in tracker.load_saved_sessions() if str(item.get("session_id") or "") == session_id), None)
    from app.services.home_history_service import HomeHistoryRepository
    from backend.soloq_analyses import register_analysis
    repository = repository or HomeHistoryRepository()
    profile = repository.load_last_profile()
    if not profile:
        raise ValueError("Sincroniza Inicio con League Client antes de solicitar datos de Riot.")
    local_record = next((item for item in repository.load_saved_lcu_matches(profile) if str(item.get("match_id") or "") == session_id), None)
    history = repository.load(profile)
    source_row = next((row for row in history.get("matches", []) if isinstance(row, dict) and session_id in {
        str(row.get("stable_match_id") or ""), str(row.get("game_id") or ""), str(row.get("gameId") or "")
    }), None)
    if not session and not local_record and not source_row:
        raise KeyError("La partida ya no está disponible en el historial local.")
    known_ids = _match_ids(session or {}) | ({str(local_record.get("match_id") or "")} if local_record else set()) | {session_id}
    def exact_history_link(row: dict[str, Any]) -> bool:
        linked = row.get("saved_match_link") if isinstance(row.get("saved_match_link"), dict) else {}
        return str(linked.get("saved_match_id") or "") == session_id and str(linked.get("association") or "").casefold() == "exact"
    source = next((row for row in history.get("matches", []) if known_ids & {
        str(row.get("stable_match_id") or ""), str(row.get("game_id") or ""), str(row.get("gameId") or "")
    } or exact_history_link(row)), None)
    queue_id = int((source or {}).get("queue_id") or (local_record or {}).get("queue_id") or (session or {}).get("queue_id") or 0)
    if queue_id != 420:
        raise ValueError("La sincronización profunda solo está disponible para partidas clasificatorias Solo/Duo (cola 420).")
    if not source:
        raise ValueError("Riot todavía no ha publicado esta partida en el historial local. Se conserva la ficha LCU; inténtalo de nuevo más tarde.")
    match_id = str(source.get("stable_match_id") or source.get("game_id") or source.get("gameId") or "").strip()
    if not match_id or not (known_ids & {match_id} or exact_history_link(source)):
        raise ValueError("No se pudo verificar una relación exacta entre la partida LCU y el historial de Riot.")
    participants = source.get("participants") if isinstance(source.get("participants"), list) else []
    local_participants = [item for item in participants if isinstance(item, dict) and (item.get("is_local") or item.get("is_player"))]
    if len(local_participants) != 1:
        raise ValueError("No se pudo identificar de forma segura a tu participante local en esta partida.")
    return register_analysis(repository, match_id)


def sync_saved_match(session_id: str, repository: Any | None = None) -> dict[str, Any]:
    """Attempt Riot linking, recording an honest local state if linking fails."""
    from app.services.home_history_service import HomeHistoryRepository
    repository = repository or HomeHistoryRepository()
    profile = repository.load_last_profile()
    local = next((row for row in repository.load_saved_lcu_matches(profile) if str(row.get("match_id") or "") == session_id), None) if profile else None
    if local:
        repository.update_saved_lcu_match(profile, session_id, {"riot_sync_status": "pending", "riot_sync_message": "Buscando la coincidencia exacta en el historial de Riot."})
    try:
        result = _sync_saved_match(session_id, repository)
        if local:
            repository.update_saved_lcu_match(profile, session_id, {"riot_sync_status": "downloading", "riot_sync_message": "Sincronizando datos detallados de Riot."})
        return result
    except StorageWriteError:
        # A local persistence failure says nothing about Riot availability or the
        # validity of an already saved analysis; surface it as a storage error.
        raise
    except (KeyError, ValueError, OSError, RuntimeError, TimeoutError) as error:
        if local:
            repository.update_saved_lcu_match(profile, session_id, {"riot_sync_status": "failed", "riot_sync_message": str(error)[:300]})
            return {"match_id": session_id, "history_match_id": session_id, "status": "error", "status_message": str(error)[:300], "timeline_available": False}
        return {"match_id": session_id, "history_match_id": session_id, "status": "error", "status_message": str(error)[:300], "timeline_available": False}


def get_saved_match(session_id: str) -> dict[str, Any]:
    session = next((item for item in _tracker().load_saved_sessions() if isinstance(item, dict) and str(item.get("session_id") or "") == session_id), None)
    from app.services.home_history_service import HomeHistoryRepository
    repository = HomeHistoryRepository()
    profile = repository.load_last_profile()
    local = next((item for item in repository.load_saved_lcu_matches(profile) if str(item.get("match_id") or "") == session_id), None) if profile else None
    history_match = next((item for item in repository.load(profile).get("matches", [])
        if isinstance(item, dict) and session_id in {
            str(item.get("stable_match_id") or ""), str(item.get("game_id") or ""), str(item.get("gameId") or "")
        }), None) if profile else None
    if profile and history_match:
        history_match = _refresh_selected_lcu_detail(repository, profile, session_id, history_match)
    if local:
        cached_history_match = history_match
        refreshed_participants = {
            (str(item.get("participant_id") or ""), str(item.get("champion_id") or ""), str(item.get("team_id") or "")): item
            for item in (cached_history_match or {}).get("participants", [])
            if isinstance(item, dict)
        }
        if cached_history_match and cached_history_match.get("cs_source_version") == 2:
            local = {
                **local,
                "cs": cached_history_match.get("cs"),
                "cs_source_version": 2,
                "lane": cached_history_match.get("lane") or local.get("lane"),
            }
        from app.services.live_match_tracker import LiveMatchTracker
        sessions = LiveMatchTracker({}, persist=False).load_saved_sessions()
        linked = next((item for item in sessions if str(item.get("match_id") or "") == session_id or session_id in _match_ids(item)), None)
        participants = []
        for index, item in enumerate(local.get("participants", [])):
            if not isinstance(item, dict):
                continue
            is_local = bool(item.get("is_local") or item.get("is_player"))
            participant_key = (str(item.get("participant_id") or ""), str(item.get("champion_id") or ""), str(item.get("team_id") or ""))
            refreshed = refreshed_participants.get(participant_key)
            participant_cs = (refreshed.get("cs") if refreshed.get("cs_source_version") == 2 else None) if refreshed is not None else _saved_participant_cs(item, local)
            is_local = bool(item.get("is_local") or item.get("is_player") or _matches_profile_identity(item, profile) or (refreshed or {}).get("is_local"))
            participant_id = item.get("participant_id")
            source_index = (refreshed or {}).get("source_index", item.get("source_index"))
            participants.append({"participantId": str(participant_id) if participant_id is not None else None, "sourceIndex": source_index, "championId": item.get("champion_id"),
                "champion": str(item.get("champion_name") or "Campeón no disponible"), "teamId": item.get("team_id"),
                "side": "unknown",
                "local": is_local, "role": str((refreshed or {}).get("display_role") or item.get("display_role") or ""), "kills": item.get("kills"),
                "deaths": item.get("deaths"), "assists": item.get("assists"), "cs": participant_cs, "level": item.get("level"),
                "items": item.get("items") or [], "summonerSpells": item.get("summoner_spells"), "runes": item.get("runes")})
        if participants and all(isinstance(item.get("sourceIndex"), int) for item in participants):
            participants.sort(key=lambda item: item["sourceIndex"])
        participants, team_assignment_known = _participant_sides(participants)
        result = local.get("result")
        detail = {"available": bool(participants), "champion": local.get("champion") or "Campeón no disponible", "gameMode": local.get("mode") or "Modo desconocido",
            "duration": float(local.get("duration") or 0), "gameTimeOffset": 0, "participants": participants, "teamAssignmentKnown": team_assignment_known, "teams": {}, "events": [], "markers": [],
            "analysis": None, "analysisState": "local_only", "analysisSource": "LCU", "result": result == "victory" if result in {"victory", "defeat"} else None,
            "summary": _local_summary(local), "sessionId": str((linked or {}).get("session_id") or ""), "matchAnalysis": None,
            "localData": {key: deepcopy(local.get(key)) for key in ("items", "summoner_spells", "runes", "queue_id", "source") if key in local}}
        session = linked or {"session_id": "", "match_id": session_id}
    else:
        if session is None:
            if history_match is None:
                raise KeyError("Partida no encontrada en el historial LCU disponible")
            raw_participants = history_match.get("participants", []) if isinstance(history_match.get("participants"), list) else []
            participants = []
            for index, item in enumerate(raw_participants):
                if not isinstance(item, dict):
                    continue
                is_local = bool(item.get("is_local") or item.get("is_player") or _matches_profile_identity(item, profile))
                participant_cs = _saved_participant_cs(item, history_match)
                stats = item.get("final_stats") if isinstance(item.get("final_stats"), dict) else {}
                participant_id = item.get("participant_id")
                participants.append({"participantId": str(participant_id) if participant_id is not None else None, "sourceIndex": item.get("source_index"),
                    "championId": item.get("champion_id"), "champion": item.get("champion_name") or "Campeón no disponible",
                    "teamId": item.get("team_id"), "side": "unknown", "local": is_local,
                    "role": item.get("display_role") or "", "win": item.get("win"), "kills": item.get("kills"),
                    "deaths": item.get("deaths"), "assists": item.get("assists"), "cs": participant_cs,
                    "gold": stats.get("gold_earned"), "vision": stats.get("vision_score"),
                    "damage": stats.get("total_damage_dealt_to_champions"), "items": item.get("items") or [],
                    "summonerSpells": item.get("summoner_spells"), "runes": item.get("runes")})
            participants, team_assignment_known = _participant_sides(participants)
            summary = {"id": session_id, "champion": history_match.get("champion_name") or "Campeón no disponible",
                "championId": history_match.get("champion_id"), "startedAt": history_match.get("started_at") or "",
                "duration": history_match.get("duration_seconds"), "mode": history_match.get("mode") or "Modo desconocido",
                "role": history_match.get("lane") or "", "kills": history_match.get("kills"), "deaths": history_match.get("deaths"),
                "assists": history_match.get("assists"), "cs": history_match.get("cs"),
                "win": history_match.get("result") == "victory" if history_match.get("result") in {"victory", "defeat"} else None,
                "analysisState": "local_only", "analysisAvailable": False, "deepAnalysisReady": False,
                "riotMatchId": None, "queueId": history_match.get("queue_id"), "retainedAnalysis": False}
            detail = {"available": bool(participants), "champion": summary["champion"], "gameMode": summary["mode"],
                "duration": float(summary["duration"] or 0), "gameTimeOffset": 0, "participants": participants, "teamAssignmentKnown": team_assignment_known,
                "teams": {}, "events": [], "markers": [], "analysis": None, "analysisState": "local_only",
                "analysisSource": "LCU history", "result": summary["win"], "summary": summary,
                "sessionId": "", "matchAnalysis": None, "localData": {"items": history_match.get("items") or [],
                "queue_id": history_match.get("queue_id"), "source": "LCU"}}
            session = {"session_id": "", "match_id": session_id}
        else:
            from backend.recording_review import _public_session
            detail = _public_session(session, {})
            detail["summary"] = _summary(session)
            detail["sessionId"] = session_id
    deep = _deep_analysis_for(session, repository.load_saved_analyses(profile) if profile else [])
    detail["deepAnalysis"] = None
    if deep:
        detail["deepAnalysis"] = {"matchId": deep.get("match_id"), "status": deep.get("status"),
            "statusMessage": deep.get("status_message"), "available": bool(deep.get("timeline_available") and deep.get("participants") and deep.get("frames") and deep.get("local_identity_resolved"))}
    legacy_analysis = session.get("ai_match_analysis")
    if not isinstance(legacy_analysis, dict) and session.get("ai_analysis"):
        raw_analysis = session.get("ai_analysis")
        legacy_analysis = raw_analysis if isinstance(raw_analysis, dict) else {"analysis": {"summary": {"short_summary": str(raw_analysis)}}}
    detail["matchAnalysis"] = deepcopy(legacy_analysis) if isinstance(legacy_analysis, dict) else None
    return detail


def generate_saved_match_analysis(session_id: str, *, force: bool = False) -> dict[str, Any]:
    tracker = _tracker()
    session = next((item for item in tracker.load_saved_sessions() if isinstance(item, dict) and str(item.get("session_id") or "") == session_id), None)
    if session is None:
        raise KeyError("Partida guardada no encontrada")
    current = session.get("ai_match_analysis")
    if not force and isinstance(current, dict) and isinstance(current.get("analysis"), dict):
        return get_saved_match(session_id)
    if not _analysis_lock.acquire(blocking=False):
        raise ValueError("Ya hay un análisis de partida en curso.")
    try:
        from app.services.match_ai_analyzer_service import MatchAIAnalyzerService
        from app.services.match_analysis_models import VERSION_ESQUEMA_ANALISIS, enriquecer_analisis_partida
        from app.services.settings_service import SettingsService
        api_key = str(SettingsService().load().get("gemini_api_key") or "").strip()
        if not api_key:
            raise ValueError("No hay una clave de Gemini configurada. Añádela en Ajustes.")
        analysis, source_response, model, fingerprint = MatchAIAnalyzerService().analyze_match(session, api_key)
        analysis = enriquecer_analisis_partida(analysis)
        now = datetime.now(UTC).isoformat()
        record = {
            "saved_match_id": session_id,
            "analysis_type": "general_match_analysis",
            "schema_version": VERSION_ESQUEMA_ANALISIS,
            "provider": "Gemini", "model": model,
            "created_at": now, "last_successful_analysis_at": now,
            "source_fingerprint": fingerprint, "status": "complete",
            "analysis": analysis, "source_response": source_response,
        }
        tracker.guardar_analisis_partida(session_id, record)
        return get_saved_match(session_id)
    finally:
        _analysis_lock.release()


def preview_saved_match_delete(session_id: str) -> dict[str, Any]:
    from app.services.home_history_service import HomeHistoryRepository
    from backend.match_deletion import preview_saved_match_deletion
    repository = HomeHistoryRepository()
    profile = repository.load_last_profile()
    if profile and any(str(item.get("match_id") or "") == session_id for item in repository.load_saved_lcu_matches(profile)):
        return preview_saved_match_deletion(match_id=session_id, repository=repository)
    return preview_saved_match_deletion(session_id=session_id)


def delete_saved_match(session_id: str, manifest_id: str) -> dict[str, Any]:
    from app.services.home_history_service import HomeHistoryRepository
    from backend.match_deletion import delete_saved_match_footprint
    repository = HomeHistoryRepository()
    profile = repository.load_last_profile()
    if profile and any(str(item.get("match_id") or "") == session_id for item in repository.load_saved_lcu_matches(profile)):
        result = delete_saved_match_footprint(match_id=session_id, manifest_id=manifest_id, repository=repository)
        return {"deleted": bool(result.get("deleted")), "count": len(_tracker().load_saved_sessions())}
    result = delete_saved_match_footprint(session_id=session_id, manifest_id=manifest_id)
    return {"deleted": bool(result.get("deleted")), "count": len(_tracker().load_saved_sessions())}
