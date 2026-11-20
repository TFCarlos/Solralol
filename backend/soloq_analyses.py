"""Riot Match-V5 downloads for explicitly saved SoloQ analyses."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
import json
import logging
from typing import Any

from _paths import DATA_DIR
from app.services.home_history_service import HomeHistoryRepository
from app.services.match_history_cache import MatchHistoryCache
from app.services.riot_api_service import RiotApiError, RiotApiService
from app.services.settings_service import SettingsService
import threading

_ai_lock = threading.Lock()


def _routing(platform: str) -> tuple[str, str]:
    platform = platform.strip().casefold()
    platform = {"euw": "euw1", "eune": "eun1", "europe west": "euw1", "na": "na1"}.get(platform, platform)
    account = ("europe" if platform in {"euw1", "eun1", "tr1", "ru"} else
               "asia" if platform in {"kr", "jp1", "ph2", "sg2", "th2", "tw2", "vn2"} else
               "americas" if platform in {"na1", "br1", "la1", "la2", "oc1"} else "")
    if not account:
        raise ValueError("La región de la cuenta no permite enrutar Match-V5.")
    return account, platform


def _records(repository: HomeHistoryRepository, profile: dict[str, Any]) -> list[dict[str, Any]]:
    return repository.load_saved_analyses(profile)


def _has_persisted_timeline(record: dict[str, Any]) -> bool:
    """A saved Riot timeline is sufficient for offline recalculation."""
    participants = record.get("participants")
    frames = record.get("frames")
    return bool(record.get("timeline_available") is True
                and isinstance(participants, list) and participants
                and isinstance(frames, list) and frames)


def is_deep_analysis_ready(record: dict[str, Any]) -> bool:
    """Only expose Open when Riot processing finished with a usable timeline."""
    return bool(
        isinstance(record, dict)
        and record.get("status") == "ready"
        and record.get("timeline_available") is True
        and record.get("local_identity_resolved") is True
        and isinstance(record.get("participants"), list) and record["participants"]
        and isinstance(record.get("frames"), list) and record["frames"]
    )


def _role_phase_references(repository: HomeHistoryRepository, profile: dict[str, Any], cache: Any,
                           match_id: str, analysis_config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Use only already-saved SoloQ rosters and cached Riot timelines."""
    try:
        from backend.battlescore_calibration import build_role_phase_baselines
        history = repository.load(profile).get("matches", [])
        timelines = getattr(cache, "data", {}).get("timelines", {})
        if isinstance(history, list) and isinstance(timelines, dict):
            if analysis_config is None:
                from backend.analysis_settings import load_configuration
                analysis_config = load_configuration()
            normalization = analysis_config.get("normalization", {})
            return build_role_phase_baselines(
                history, timelines, exclude_match_id=match_id,
                minimum_matches=normalization.get("minimum_reference_matches", 20),
                phase_bounds_minutes=tuple(normalization.get("phase_bounds_minutes", (10, 20))),
            )
    except (AttributeError, OSError, TypeError, ValueError):
        logging.getLogger(__name__).exception("No se pudieron preparar las referencias locales de BattleScore.")
    return None


def _legacy_saved_count() -> int:
    """Legacy Companion sessions are not retained Riot analyses and use no Riot slot."""
    return 0


def list_analyses(repository: HomeHistoryRepository) -> dict[str, Any]:
    from backend.battlescore import VERSION, telemetry_fingerprint
    from backend.analysis_settings import engine_snapshot, load_configuration
    analysis_config = load_configuration()
    active_scoring_hash = engine_snapshot(analysis_config)["configuration_hash"]
    profile = repository.load_last_profile()
    if not profile:
        legacy_count = _legacy_saved_count()
        return {"matches": [], "count": legacy_count, "analysisCount": 0, "legacyCount": legacy_count,
                "limit": analysis_config["analysis_limits"]["max_active_matches"], "overLimit": legacy_count > analysis_config["analysis_limits"]["max_active_matches"], "repositoryAvailable": True}
    records = _records(repository, profile)
    _recalculate_saved_scores_from_local_cache(repository, profile, records, analysis_config)
    records.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    summaries = [{key: item.get(key) for key in (
        "match_id", "history_match_id", "champion", "champion_id", "started_at", "duration", "mode", "role",
        "kills", "deaths", "assists", "win", "status", "status_message", "analysis_available",
        "timeline_available", "queue_id", "rank_context", "ai_generation_status", "ai_status_message",
    )} for item in records]
    for item, record in zip(summaries, records):
        item["deep_analysis_ready"] = is_deep_analysis_ready(record)
        cached_score = record.get("battle_score") if isinstance(record.get("battle_score"), dict) else {}
        item["battleScoreState"] = cached_score.get("state", "unavailable")
        participants = record.get("participants") if isinstance(record.get("participants"), list) else []
        local = next((player for player in participants if isinstance(player, dict) and player.get("local")), None)
        if local is None:
            # Some older saved analyses have no reliable per-participant local
            # marker. The saved analysis champion identifies the analyzed
            # player; use its canonical champion ID as a conservative fallback.
            champion_id = record.get("champion_id")
            champion_name = str(record.get("champion") or "").strip().casefold()
            candidates = [player for player in participants if isinstance(player, dict) and
                          ((champion_id is not None and str(player.get("championId", player.get("champion_id"))) == str(champion_id))
                           or (champion_id is None and str(player.get("champion") or "").strip().casefold() == champion_name))]
            if len(candidates) > 1 and record.get("role"):
                role = str(record.get("role") or "").strip().casefold()
                role_candidates = [player for player in candidates if str(player.get("role") or "").strip().casefold() == role]
                candidates = role_candidates or candidates
            local = candidates[0] if len(candidates) == 1 else None
        local_score = next((row for row in cached_score.get("participants", [])
                            if isinstance(row, dict) and local and row.get("participantId") == local.get("participantId")), None)
        events = record.get("events") if isinstance(record.get("events"), list) else []
        frames = record.get("frames") if isinstance(record.get("frames"), list) else []
        if (cached_score.get("version") == VERSION
                and cached_score.get("configurationHash") == active_scoring_hash
                and cached_score.get("state") in {"complete", "partial"}
                and local_score and local_score.get("state") in {"complete", "partial"}):
            item["battleScore"] = local_score.get("finalScore")
            item["battleScoreVersion"] = VERSION
        else:
            item["battleScore"] = None
            item["battleScoreVersion"] = VERSION if cached_score.get("version") == VERSION and cached_score.get("configurationHash") == active_scoring_hash else None
        item["id"] = item.pop("match_id")
        item["analysisAvailable"] = bool(item.pop("analysis_available", False))
        item["analysisState"] = "saved" if item["analysisAvailable"] else "none"
        item["startedAt"] = item.pop("started_at") or ""
    legacy_count = _legacy_saved_count()
    total = len(records) + legacy_count
    return {"matches": summaries, "count": total, "analysisCount": len(records), "legacyCount": legacy_count,
            "limit": analysis_config["analysis_limits"]["max_active_matches"], "overLimit": total > analysis_config["analysis_limits"]["max_active_matches"], "repositoryAvailable": True}


def _recalculate_saved_scores_from_local_cache(repository: HomeHistoryRepository, profile: dict[str, Any],
                                               records: list[dict[str, Any]],
                                               analysis_config: dict[str, Any] | None = None) -> None:
    """Upgrade stale scores from saved Match-V5 payloads only; never fetches Riot data."""
    from backend.battlescore import VERSION
    if analysis_config is None:
        from backend.analysis_settings import load_configuration
        analysis_config = load_configuration()

    cache = MatchHistoryCache()
    calibration_cache = getattr(cache, "data", {}).get("timelines", {})
    try:
        history_matches = repository.load(profile).get("matches", [])
    except (AttributeError, OSError, TypeError):
        history_matches = []
    for record in records:
        match_id = str(record.get("match_id") or "")
        participants = record.get("participants") if isinstance(record.get("participants"), list) else []
        if not match_id or not participants:
            continue
        timeline = cache.get_timeline(match_id)
        if timeline is not None:
            events, frames = _normalize_events(timeline, participants)
            record["events"], record["frames"] = events, frames
            record["timeline_available"] = True
            raw_match = cache.get_raw_match(match_id) or {}
            raw_info = raw_match.get("info") if isinstance(raw_match.get("info"), dict) else {}
            raw_players = {int(item.get("participantId")): item for item in raw_info.get("participants", [])
                           if isinstance(item, dict) and isinstance(item.get("participantId"), int)}
            for participant in participants:
                raw = raw_players.get(int(participant.get("participantId") or 0), {})
                dealt = raw.get("totalDamageDealtToChampions")
                participant["championDamageDealt"] = dealt if isinstance(dealt, (int, float)) and not isinstance(dealt, bool) else None
                if participant.get("allSourceDamageReceived") is None:
                    total_received = raw.get("totalDamageTaken")
                    participant["allSourceDamageReceived"] = total_received if isinstance(total_received, (int, float)) and not isinstance(total_received, bool) else None
                # Older saved analyses used these ambiguous names. Never reuse
                # the generic Match-V5 total as champion-sourced damage.
                participant.pop("damage", None)
                participant.pop("damageTaken", None)
                for local_key, riot_key in (("damageToEpicMonsters", "damageDealtToEpicMonsters"),
                                            ("damageToBuildings", "damageDealtToBuildings"),
                                            ("damageToTurrets", "damageDealtToTurrets"),
                                            ("damageToObjectives", "damageDealtToObjectives")):
                    if participant.get(local_key) is None and isinstance(raw.get(riot_key), (int, float)) and not isinstance(raw.get(riot_key), bool):
                        participant[local_key] = raw[riot_key]
        else:
            events = record.get("events") if isinstance(record.get("events"), list) else []
            frames = record.get("frames") if isinstance(record.get("frames"), list) else []
        if not (record.get("timeline_available") or events or frames):
            continue
        before = record.get("battle_score") if isinstance(record.get("battle_score"), dict) else {}
        old_fingerprint = before.get("inputFingerprint")
        try:
            from backend.battlescore_calibration import build_role_phase_baselines
            normalization = analysis_config.get("normalization", {})
            references = build_role_phase_baselines(
                history_matches, calibration_cache, exclude_match_id=match_id,
                minimum_matches=normalization.get("minimum_reference_matches", 20),
                phase_bounds_minutes=tuple(normalization.get("phase_bounds_minutes", (10, 20))),
            )
        except (ImportError, TypeError, ValueError):
            references = None
        result = _attach_battlescore(record, participants, match_id, events, frames,
                                     float(record.get("duration") or 0), references, analysis_config)
        if before.get("version") != VERSION or result.get("inputFingerprint") != old_fingerprint:
            repository.save_soloq_analysis(profile, record)


def recalculate_active_analyses(repository: HomeHistoryRepository, analysis_config: dict[str, Any],
                                is_current: Any, on_progress: Any, commit_result: Any = None) -> dict[str, Any]:
    """Rebuild currently scored analyses from local Riot data, never prior scores."""
    profile = repository.load_last_profile()
    if not profile:
        return {"recalculated": 0, "skipped": 0}
    records = _records(repository, profile)
    active = [record for record in records if isinstance(record.get("battle_score"), dict)
              and record["battle_score"].get("state") in {"complete", "partial"}]
    cache = MatchHistoryCache()
    timeline_cache = getattr(cache, "data", {}).get("timelines", {})
    try:
        history_matches = repository.load(profile).get("matches", [])
    except (AttributeError, OSError, TypeError):
        history_matches = []
    recalculated = skipped = 0
    total = len(active)
    for index, record in enumerate(active, start=1):
        if not is_current():
            return {"recalculated": recalculated, "skipped": skipped, "superseded": True}
        match_id = str(record.get("match_id") or "")
        participants = record.get("participants") if isinstance(record.get("participants"), list) else []
        timeline = cache.get_timeline(match_id)
        if timeline is not None:
            events, frames = _normalize_events(timeline, participants)
            record["events"], record["frames"] = events, frames
            record["timeline_available"] = True
        else:
            events = record.get("events") if isinstance(record.get("events"), list) else []
            frames = record.get("frames") if isinstance(record.get("frames"), list) else []
        if not participants or not (events or frames):
            skipped += 1
            on_progress(index, total, match_id, "Sin cronología local suficiente")
            continue
        try:
            from backend.battlescore_calibration import build_role_phase_baselines
            normalization = analysis_config.get("normalization", {})
            references = build_role_phase_baselines(
                history_matches, timeline_cache, exclude_match_id=match_id,
                minimum_matches=normalization.get("minimum_reference_matches", 20),
                phase_bounds_minutes=tuple(normalization.get("phase_bounds_minutes", (10, 20))),
            )
        except (ImportError, TypeError, ValueError):
            references = None
        result = _attach_battlescore(record, participants, match_id, events, frames,
                                     float(record.get("duration") or 0), references, analysis_config)
        if not is_current():
            return {"recalculated": recalculated, "skipped": skipped, "superseded": True}
        if result.get("state") in {"complete", "partial"}:
            record["battle_score"] = result
            record["analysis_timestamp"] = datetime.now(UTC).isoformat()
            if commit_result is None:
                repository.save_soloq_analysis(profile, record)
            elif not commit_result(profile, record):
                return {"recalculated": recalculated, "skipped": skipped, "superseded": True}
            recalculated += 1
        else:
            skipped += 1
        on_progress(index, total, match_id, "Recalculado" if result.get("state") in {"complete", "partial"} else "No disponible")
    return {"recalculated": recalculated, "skipped": skipped}


def get_analysis(repository: HomeHistoryRepository, match_id: str) -> dict[str, Any]:
    profile = repository.load_last_profile()
    if not profile:
        raise KeyError("No hay un perfil sincronizado para esta biblioteca.")
    record = next((item for item in _records(repository, profile) if str(item.get("match_id")) == match_id), None)
    if not record:
        raise KeyError("El análisis SoloQ no está guardado.")
    result = deepcopy(record)
    result["id"] = str(result.get("match_id") or match_id)
    result["startedAt"] = result.get("started_at") or ""
    result["analysisAvailable"] = bool(result.get("ai_analysis"))
    rune_evaluation_recovered = _recover_saved_rune_evaluation(result)
    participants = result.get("participants") if isinstance(result.get("participants"), list) else []
    # Rebuild normalized chronology from the existing local Riot cache so older
    # saved records gain component/consumable transactions without a download.
    riot_cache = MatchHistoryCache()
    timeline_load_state = "missing_local"
    try:
        cached_timeline = riot_cache.get_timeline(match_id)
    except (OSError, RuntimeError, ValueError) as error:
        cached_timeline = None
        timeline_load_state = "retrieval_failed"
        logging.getLogger(__name__).warning(
            "soloq.timeline_index cache_read_failed match=%s error=%s",
            match_id, type(error).__name__,
        )
    if cached_timeline is not None and participants:
        try:
            info = cached_timeline.get("info") if isinstance(cached_timeline, dict) else None
            if not isinstance(info, dict) or not isinstance(info.get("frames"), list):
                raise ValueError("cached_timeline_missing_frames")
            events, frames = _normalize_events(cached_timeline, participants)
        except (AttributeError, TypeError, ValueError, OverflowError) as error:
            timeline_load_state = "malformed"
            logging.getLogger(__name__).warning(
                "soloq.timeline_index cached_timeline_malformed match=%s error=%s",
                match_id, type(error).__name__,
            )
        else:
            result["events"] = events
            result["frames"] = frames
            result["timeline_available"] = True
            timeline_load_state = "available" if events or frames else "available_empty"
    events = result.get("events") if isinstance(result.get("events"), list) else []
    frames = result.get("frames") if isinstance(result.get("frames"), list) else []
    duration = float(result.get("duration") or 0)
    stored_timeline_available = bool(events or frames)
    # Persisted events/frames are authoritative even when an older saved row
    # left timeline_available false; that flag was not always synchronized.
    timeline_available = stored_timeline_available
    if timeline_available:
        result["timeline_available"] = True
    if timeline_available and timeline_load_state == "missing_local":
        timeline_load_state = "available"
    elif not timeline_available and timeline_load_state == "missing_local" and result.get("timeline_available"):
        timeline_load_state = "malformed"
    from backend.analysis_settings import load_configuration
    analysis_config = load_configuration()
    if timeline_available and participants:
        result["timeline_available"] = True
        references = _role_phase_references(repository, profile, riot_cache, match_id, analysis_config)
        result["battle_score"] = _attach_battlescore(result, participants, match_id, events, frames, duration, references, analysis_config)
        result["participants"] = participants
        _rebuild_saved_ai_timeline_index(result, events)
        repository.save_soloq_analysis(profile, result)
    else:
        current_index = result.get("timeline_event_index")
        if not (isinstance(current_index, dict) and current_index.get("index_version") == 1
                and current_index.get("extraction_version") == 6
                and current_index.get("correlation_version") == 3
                and current_index.get("personal_selection_version") == 2):
            result["timeline_event_index"] = {
                "index_version": 1, "extraction_version": 6,
                "correlation_version": 3, "status": timeline_load_state,
                "personal_selection_version": 2,
                "timeline_extraction": {"status": timeline_load_state},
                "notable_timeline": [], "teamfights": [], "objectives": [],
                "kill_objective_correlations": [], "player_death_objective_correlations": [],
                "fight_objective_correlations": [],
                "key_event_candidates": [], "global_key_event_candidates": [],
                "personal_event_selection": {"version": 2, "player_key": "player_local", "personal_event_ids": [], "counts": {}},
                "key_events": [],
            }
        from backend.battlescore import VERSION
        result["battle_score"] = {"version": VERSION, "state": "unavailable", "matchId": match_id, "participants": []}
        for participant in participants:
            participant.pop("battleScore", None)
            participant.pop("battleScoreSeries", None)
            participant.pop("battleScoreVersion", None)
            participant.pop("battleScoreCoverage", None)
        result["participants"] = participants
        repository.save_soloq_analysis(profile, result)
    for event in events:
        if isinstance(event, dict) and event.get("itemId") and not event.get("itemName"):
            event["itemName"] = _item_name(event.get("itemId"))
    from backend.match_achievements import evaluate_match_achievements
    result["achievements"] = evaluate_match_achievements(
        result.get("participants") or [], events, frames, duration,
        result.get("battle_score") or {}, analysis_config.get("achievements", {}),
        bool(result.get("timeline_available")),
    )
    from backend.negative_achievements import evaluate as evaluate_improvements
    result["improvement_opportunities"] = evaluate_improvements(
        result.get("participants") or [], events, frames, duration,
        bool(result.get("timeline_available")), analysis_config.get("negative_achievements", {}),
    )
    result["achievement_configuration"] = {
        "version": "match_achievements_v2", "configuration_version": analysis_config.get("configuration_version"),
        "negative_enabled": bool(analysis_config.get("negative_achievements", {}).get("enabled", True)),
    }
    if rune_evaluation_recovered:
        # Migrate only the missing rune subsection; retain the existing report and
        # its event interpretations without another provider request.
        repository.save_soloq_analysis(profile, result)
    return result


def _recover_saved_rune_evaluation(record: dict[str, Any]) -> bool:
    """Rebuild a missing deterministic rune assessment from the saved Riot roster."""
    saved = record.get("ai_analysis")
    analysis = saved.get("analysis") if isinstance(saved, dict) else None
    if not isinstance(analysis, dict) or isinstance(analysis.get("rune_evaluation"), dict):
        return False
    participants = record.get("participants")
    local = next((item for item in participants if isinstance(item, dict) and item.get("local")), None) if isinstance(participants, list) else None
    runes = local.get("runes") if isinstance(local, dict) else None
    if not isinstance(runes, dict):
        return False
    try:
        from _paths import DATA_DIR
        catalog = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        items = catalog.get("items", {}) if isinstance(catalog, dict) else {}
        tags = [tag for item_id in (local.get("items") or []) for tag in items.get(str(item_id), {}).get("tags", [])]
        archetype = "orientación de letalidad" if tags.count("Lethality") >= 2 else "build de combate observada"
        from app.services.match_analysis_models import _evaluar_runas
        evaluation = _evaluar_runas(runes, str(catalog.get("version") or ""), archetype)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return False
    if not isinstance(evaluation, dict):
        return False
    evaluation["assessment_source"] = "saved_match_reconstruction"
    analysis["rune_evaluation"] = evaluation
    if not isinstance(analysis.get("rune_comments"), list) or not analysis.get("rune_comments"):
        analysis["rune_comments"] = [str(evaluation.get("conclusion") or "")]
    return True


def _rebuild_saved_ai_timeline_index(record: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    """Build and persist the deterministic event index independently of AI."""
    saved = record.get("ai_analysis")
    analysis = saved.get("analysis") if isinstance(saved, dict) else None
    if not isinstance(events, list):
        return False
    old_evidence = analysis.get("match_evidence") if isinstance(analysis, dict) else None
    old_index = record.get("timeline_event_index")
    participants = record.get("participants") if isinstance(record.get("participants"), list) else []
    local = next((item for item in participants if isinstance(item, dict) and item.get("local")), None)
    if not local or local.get("participantId") is None:
        return False
    player_identity = str(local["participantId"])
    index_is_current = (
        isinstance(old_index, dict)
        and old_index.get("index_version") == 1
        and old_index.get("extraction_version") == 6
        and old_index.get("correlation_version") == 3
        and old_index.get("personal_selection_version") == 2
        and str(old_index.get("player_identity") or "") == player_identity
        and old_index.get("status") in {"available", "available_empty"}
        and isinstance(old_index.get("notable_timeline"), list)
        and isinstance(old_index.get("teamfights"), list)
        and isinstance(old_index.get("objectives"), list)
        and isinstance(old_index.get("key_event_candidates"), list)
        and isinstance(old_index.get("key_events"), list)
        and isinstance(old_index.get("personal_event_selection"), dict)
        and old_index["personal_event_selection"].get("version") == 2
    )
    ai_index_is_current = (
        analysis is None
        or (
            isinstance(old_evidence, dict)
            and old_evidence.get("evidence_version") == 6
            and old_evidence.get("correlation_version") == 3
            and old_evidence.get("personal_selection_version") == 2
            and isinstance(old_evidence.get("notable_timeline"), list)
            and isinstance(analysis.get("key_events"), list)
        )
    )
    if index_is_current and ai_index_is_current:
        return False

    players: dict[str, dict[str, Any]] = {}
    all_players = []
    for participant in participants:
        if not isinstance(participant, dict) or participant.get("participantId") is None:
            continue
        key = str(participant["participantId"])
        player = {
            "player_key": key,
            "champion": participant.get("champion"),
            "team": str(participant.get("teamId") or ""),
            "is_ally": participant.get("side") == "allied",
            "role": participant.get("role"),
            "kills": participant.get("kills"),
            "deaths": participant.get("deaths"),
            "assists": participant.get("assists"),
            "cs": participant.get("cs"),
            "gold": participant.get("gold"),
            "vision_score": participant.get("vision"),
            "damage_to_champions": participant.get("championDamageDealt"),
            "items": participant.get("items") or [],
            "runes": participant.get("runes"),
            "summoner_spells": participant.get("summonerSpells"),
        }
        players[key] = player
        all_players.append(player)

    local_key = str(local["participantId"])
    local_team = str(local.get("teamId") or "")
    chronology = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type") or "")
        timestamp_ms = event.get("timestamp")
        try:
            seconds = float(timestamp_ms) / 1000
        except (TypeError, ValueError):
            continue
        killer_id = event.get("killerId")
        victim_id = event.get("victimId")
        event_side = event.get("side")
        event_team = event.get("killerTeamId")
        if event_team is None and event_side in {"allied", "enemy"}:
            event_team = local_team if event_side == "allied" else ("200" if local_team == "100" else "100")
        chronology.append({
            "order": index,
            "time_seconds": seconds,
            "time_label": f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}",
            "timestamp_ms": int(timestamp_ms),
            "source_reference": str(event.get("id") or f"timeline:{index}"),
            "type": kind,
            "team": str(event_team or ""),
            "owner_team": str(event.get("teamId") or ""),
            "team_source": "killerTeamId" if event.get("killerTeamId") is not None else "side" if event_side in {"allied", "enemy"} else "unknown",
            "player_key": str(event.get("actorId") or killer_id or "") if (event.get("actorId") or killer_id) is not None else "",
            "killer_key": str(killer_id) if killer_id is not None else None,
            "victim_key": str(victim_id) if victim_id is not None else None,
            "assister_keys": [str(value) for value in event.get("assistingIds", []) if value is not None],
            "objective": event.get("monsterType") or event.get("buildingType"),
            "objective_label": event.get("category") if kind in {"ELITE_MONSTER_KILL", "BUILDING_KILL", "TURRET_PLATE_DESTROYED"} else None,
            "objective_subtype": event.get("monsterSubType"),
            "position": event.get("position") if isinstance(event.get("position"), dict) else None,
            "shutdown": bool(event.get("shutdownBounty")),
            "bounty": event.get("shutdownBounty"),
            "label": str(event.get("category") or kind),
        })
    metadata = {
        "duration_seconds": record.get("duration"),
        "result": "victory" if record.get("win") is True else "defeat" if record.get("win") is False else None,
        "game_version": record.get("patch"),
        "local_team": local_team,
        "winning_team": local_team if record.get("win") is True else None,
    }
    match_log = {
        "metadata": metadata,
        "local_player_key": local_key,
        "user_stats": players.get(local_key, {}),
        "all_players": all_players,
        "events_chronology": chronology,
    }
    from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
    from app.services.match_analysis_models import enriquecer_analisis_partida
    evidence = MatchAnalysisEvidenceService().build_evidence(match_log)
    evidence["personal_event_selection"]["player_identity"] = player_identity
    context = {**match_log, "analysis_evidence": evidence}
    deterministic = enriquecer_analisis_partida({
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {},
    }, context)
    extraction = evidence.get("timeline_extraction", {})
    index_status = (
        "available"
        if extraction.get("status") == "available" and index_candidates_exist(evidence)
        else "available_empty"
    )
    index = {
        "index_version": 1,
        "extraction_version": 6,
        "correlation_version": 3,
        "personal_selection_version": 2,
        "player_identity": player_identity,
        "status": index_status,
        "timeline_extraction": evidence.get("timeline_extraction", {}),
        "coverage": evidence.get("coverage", {}),
        "match": evidence.get("match", {}),
        "notable_timeline": evidence.get("notable_timeline", []),
        "teamfights": evidence.get("teamfights", []),
        "objectives": evidence.get("objectives", []),
        "kill_objective_correlations": evidence.get("kill_objective_correlations", []),
        "player_death_objective_correlations": evidence.get("player_death_objective_correlations", []),
        "fight_objective_correlations": evidence.get("fight_objective_correlations", []),
        "key_event_candidates": evidence.get("key_event_candidates", []),
        "global_key_event_candidates": evidence.get("global_key_event_candidates", []),
        "personal_event_selection": evidence.get("personal_event_selection", {}),
        "key_events": deterministic.get("key_events", []),
    }
    record["timeline_event_index"] = index
    if isinstance(analysis, dict):
        # Keep existing interpretation and phases. Rebuild only its event-linked
        # evidence when stale, malformed, or absent.
        try:
            rebuilt = enriquecer_analisis_partida(analysis, context)
        except (TypeError, ValueError) as error:
            logging.getLogger(__name__).warning(
                "soloq.timeline_index ai_interpretation_unavailable error=%s; factual index retained",
                type(error).__name__,
            )
        else:
            analysis["match_evidence"] = rebuilt.get("match_evidence", evidence)
            analysis["key_events"] = rebuilt.get("key_events", index["key_events"])
            saved["analysis"] = analysis
            record["ai_analysis"] = saved
    logging.getLogger(__name__).info(
        "soloq.timeline_index match=%s status=rebuilt source_events=%d kills=%d objectives=%d structures=%d fights=%d candidates=%d key_events=%d",
        str(record.get("match_id") or ""), len(chronology),
        evidence.get("coverage", {}).get("champion_kills", 0),
        sum(item.get("type") == "objective" for item in evidence.get("objectives", [])),
        sum(item.get("type") == "structure" for item in evidence.get("objectives", [])),
        len(evidence.get("teamfights", [])), len(evidence.get("key_event_candidates", [])),
        len(index.get("key_events", [])),
    )
    return True


def index_candidates_exist(evidence: dict[str, Any]) -> bool:
    """Whether extraction found at least one event sequence worth presenting."""
    return bool(evidence.get("notable_timeline") or evidence.get("key_event_candidates"))


def get_achievement_snapshot(repository: HomeHistoryRepository, match_id: str) -> dict[str, Any]:
    """Re-evaluate achievement presentation from persisted telemetry only."""
    profile = repository.load_last_profile()
    if not profile:
        raise KeyError("No hay un perfil sincronizado para esta biblioteca.")
    record = next((item for item in _records(repository, profile) if str(item.get("match_id")) == match_id), None)
    if not record:
        raise KeyError("El análisis SoloQ no está guardado.")
    participants = record.get("participants") if isinstance(record.get("participants"), list) else []
    events = record.get("events") if isinstance(record.get("events"), list) else []
    frames = record.get("frames") if isinstance(record.get("frames"), list) else []
    duration = float(record.get("duration") or 0)
    from backend.analysis_settings import _canonical_hash, load_configuration
    from backend.match_achievements import evaluate_match_achievements
    from backend.negative_achievements import evaluate as evaluate_improvements
    config = load_configuration()
    battle_score = record.get("battle_score") if isinstance(record.get("battle_score"), dict) else {}
    return {
        "achievements": evaluate_match_achievements(
            participants, events, frames, duration, battle_score,
            config.get("achievements", {}), bool(record.get("timeline_available")),
        ),
        "improvement_opportunities": evaluate_improvements(
            participants, events, frames, duration, bool(record.get("timeline_available")),
            config.get("negative_achievements", {}),
        ),
        "achievement_configuration": {
            "version": "match_achievements_v2",
            "configuration_hash": _canonical_hash({
                "positive": config.get("achievements", {}),
                "negative": config.get("negative_achievements", {}),
            }),
            "configuration_version": config.get("configuration_version"),
            "telemetry_coverage": battle_score.get("telemetryCoverage"),
        },
    }


def register_analysis(repository: HomeHistoryRepository, match_id: str) -> dict[str, Any]:
    from backend.analysis_settings import load_configuration
    analysis_limit = load_configuration()["analysis_limits"]["max_active_matches"]
    profile = repository.load_last_profile()
    if not profile or not profile.get("puuid"):
        raise ValueError("Sincroniza Inicio con League Client para identificar tu cuenta.")
    history = repository.load(profile)
    records = _records(repository, profile)
    existing = next((item for item in records if str(item.get("match_id")) == match_id), None)
    source_id = str(existing.get("history_match_id") or match_id) if existing else match_id
    source = next((item for item in history.get("matches", []) if match_id in {
        str(item.get("stable_match_id") or ""), str(item.get("game_id") or ""), str(item.get("gameId") or "")
    } or source_id in {
        str(item.get("stable_match_id") or ""), str(item.get("game_id") or ""), str(item.get("gameId") or "")
    }), None)
    if not source and existing and int(existing.get("queue_id") or 0) == 420:
        source = existing
    if not source:
        raise KeyError("La partida ya no está en el historial local. Sincroniza Inicio e inténtalo de nuevo.")
    if str(source.get("queue_id") or "") != "420":
        raise ValueError("Solo se pueden analizar partidas clasificatorias Solo/Duo (cola 420).")
    raw_id = str(source.get("game_id") or source.get("stable_match_id") or match_id).strip()
    _account_region, platform = _routing(str(profile.get("region") or ""))
    riot_match_id = raw_id if "_" in raw_id else f"{platform.upper()}_{raw_id}"
    rank = next((item for item in profile.get("ranked", []) if isinstance(item, dict) and "SOLO" in str(item.get("queue") or "").upper()), None) if isinstance(profile.get("ranked"), list) else None
    rank_context = " ".join(str((rank or {}).get(key) or "").strip() for key in ("tier", "division")).strip()
    if rank and rank.get("league_points") is not None:
        rank_context = f"{rank_context} · {rank['league_points']} LP".strip(" ·")
    existing = existing or next((item for item in records if str(item.get("match_id")) == riot_match_id), None)
    if existing:
        # `partial` may only indicate that Riot did not resolve the local
        # PUUID. If the roster and timeline are persisted, opening/registering
        # the analysis must not schedule another API download.
        if (existing.get("status") in {"error", "partial"}
                and not _has_persisted_timeline(existing)):
            existing["status"] = "pending"
            existing["status_message"] = "Reintentando descarga de Riot."
            existing["updated_at"] = datetime.now(UTC).isoformat()
            repository.save_soloq_analysis(profile, existing)
        return existing
    if len(records) >= analysis_limit:
        raise ValueError(f"Has alcanzado el límite de {analysis_limit} análisis activos. Desactiva uno para liberar espacio.")
    record = {
        "match_id": riot_match_id,
        "history_match_id": match_id,
        "queue_id": 420,
        "champion": str(source.get("champion_name") or "Campeón no disponible"),
        "champion_id": source.get("champion_id"),
        "started_at": str(source.get("started_at") or ""),
        "duration": source.get("duration_seconds"),
        "mode": str(source.get("mode") or "CLASSIC"),
        "rank_context": rank_context or None,
        "role": str(source.get("lane") or ""),
        "kills": source.get("kills"), "deaths": source.get("deaths"), "assists": source.get("assists"),
        "win": source.get("result") == "victory" if source.get("result") in {"victory", "defeat"} else None,
        "status": "pending", "status_message": "Pendiente de descarga.",
        "timeline_available": False, "analysis_available": False,
        "participants": [], "events": [], "frames": [], "ai_analysis": None,
        "created_at": datetime.now(UTC).isoformat(), "updated_at": datetime.now(UTC).isoformat(),
    }
    repository.save_soloq_analysis(profile, record)
    return record


def _public_participant(item: dict[str, Any], puuid: str) -> dict[str, Any]:
    return {
        "participantId": int(item.get("participant_id") or 0),
        "championId": item.get("champion_id"),
        "champion": str(item.get("champion_name") or "Campeón no disponible"),
        "teamId": int(item.get("team_id") or 0),
        "side": "allied" if item.get("is_player") else "enemy",  # corrected by caller using team id
        "local": bool(item.get("is_player")),
        "role": str(item.get("team_position") or ""),
        "win": item.get("win"), "kills": item.get("kills"), "deaths": item.get("deaths"), "assists": item.get("assists"),
        "cs": item.get("cs"), "gold": item.get("gold_earned"), "vision": item.get("vision_score"),
        "championDamageDealt": item.get("total_damage_dealt_to_champions"),
        "championDamageReceived": None, "championDamageReceivedCoverage": "unavailable",
        "allSourceDamageReceived": item.get("total_damage_taken"),
        "damageToObjectives": item.get("damage_to_objectives"),
        "damageToEpicMonsters": item.get("damage_to_epic_monsters"),
        "damageToBuildings": item.get("damage_dealt_to_buildings"),
        "damageToTurrets": item.get("damage_dealt_to_turrets"), "wardsPlaced": item.get("wards_placed"),
        "wardsKilled": item.get("wards_killed"), "detectorWardsPlaced": item.get("detector_wards_placed"),
        "totalTimeSpentDead": item.get("total_time_spent_dead"), "totalHeal": item.get("total_heal"),
        "totalHealsOnTeammates": item.get("total_heals_on_teammates"),
        "totalDamageShieldedOnTeammates": item.get("total_damage_shielded_on_teammates"),
        "timeCCingOthers": item.get("time_ccing_others"), "objectivesStolen": item.get("objectives_stolen"),
        "epicMonsterSteals": item.get("epic_monster_steals"),
        "level": item.get("champ_level"),
        "achievementAvailability": item.get("achievement_availability"),
        "items": item.get("items") or [], "summonerSpells": item.get("summoner_spells"), "runes": item.get("runes"),
    }


def _radar_for(participant: dict[str, Any], duration: float) -> list[float]:
    from backend.recording_review import _radar
    minutes = duration / 60 if duration > 0 else 0
    kills = float(participant.get("kills") or 0)
    deaths = float(participant.get("deaths") or 0)
    assists = float(participant.get("assists") or 0)
    cs = float(participant.get("cs") or 0)
    gold = float(participant.get("gold") or 0)
    return _radar({"duration": duration, "kills": kills, "deaths": deaths, "assists": assists,
        "vision": participant.get("vision"), "cspm": cs / minutes if minutes else 0,
        "gpm": gold / minutes if minutes else 0,
        "kda": (kills + assists) / deaths if deaths else kills + assists})


def _team_radar(participants: list[dict[str, Any]]) -> dict[str, list[float | None]]:
    result: dict[str, list[float | None]] = {}
    for side in ("allied", "enemy"):
        roster = [item for item in participants if item.get("side") == side and isinstance(item.get("radar"), list)]
        result[side] = [
            sum(float(item["radar"][axis]) for item in roster if item["radar"][axis] is not None) /
            sum(1 for item in roster if item["radar"][axis] is not None)
            if any(item["radar"][axis] is not None for item in roster) else None
            for axis in range(5)
        ]
    return result


@lru_cache(maxsize=1)
def _item_catalog() -> dict[str, dict[str, Any]]:
    try:
        document = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        items = document.get("items", {})
        return items if isinstance(items, dict) else {}
    except (OSError, ValueError):
        return {}


def _item_name(item_id: Any) -> str | None:
    item = _item_catalog().get(str(item_id))
    name = item.get("name") if isinstance(item, dict) else None
    return str(name) if name else None


def _normalize_events(timeline: dict[str, Any], participants: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    roster = {int(item["participantId"]): item for item in participants if item.get("participantId")}
    events: list[dict[str, Any]] = []
    frames_out: list[dict[str, Any]] = []
    frames = timeline.get("info", {}).get("frames", [])
    team_kills: dict[int, int] = {}
    player_kills: dict[int, int] = {}
    player_assists: dict[int, int] = {}
    received_champion_damage: dict[int, float] = {}
    useful_damage: dict[int, float] = {}
    for frame_index, frame in enumerate(frames if isinstance(frames, list) else []):
        if not isinstance(frame, dict):
            continue
        timestamp = frame.get("timestamp")
        if isinstance(timestamp, (int, float)):
            for participant_id, data in (frame.get("participantFrames") or {}).items():
                data = data if isinstance(data, dict) else {}
                position = data.get("position") if isinstance(data.get("position"), dict) else {}
                damage_stats = data.get("damageStats") if isinstance(data.get("damageStats"), dict) else {}
                champ_damage = damage_stats.get("totalDamageDoneToChampions")
                if not isinstance(champ_damage, (int, float)) or isinstance(champ_damage, bool):
                    parts = [damage_stats.get(key) for key in (
                        "physicalDamageDoneToChampions", "magicDamageDoneToChampions", "trueDamageDoneToChampions")]
                    champ_damage = sum(value for value in parts if isinstance(value, (int, float)) and not isinstance(value, bool)) if any(
                        isinstance(value, (int, float)) and not isinstance(value, bool) for value in parts) else None
                frames_out.append({"timestamp": timestamp, "participantId": int(participant_id),
                    "gold": data.get("totalGold"), "level": data.get("level"), "xp": data.get("xp"),
                    "minions": data.get("minionsKilled"), "jungleMinions": data.get("jungleMinionsKilled"),
                    "championDamageDealt": champ_damage,
                    # Riot's timeline field is all-source received damage, not
                    # champion-only received damage. Keep its scope explicit.
                    "allSourceDamageReceived": damage_stats.get("totalDamageTaken"),
                    "x": position.get("x"), "y": position.get("y")})
        for index, event in enumerate(frame.get("events", []) if isinstance(frame.get("events"), list) else []):
            if not isinstance(event, dict):
                continue
            kind = str(event.get("type") or "")
            if kind == "ITEM_UNDO":
                actor_id = event.get("participantId")
                ids = {value for value in (event.get("beforeId"), event.get("afterId")) if isinstance(value, int) and value > 0}
                for previous_index in range(len(events) - 1, -1, -1):
                    previous = events[previous_index]
                    if previous.get("type") == "ITEM_PURCHASED" and previous.get("actorId") == actor_id and previous.get("itemId") in ids:
                        events.pop(previous_index)
                        break
                continue
            if kind not in {"CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL", "TURRET_PLATE_DESTROYED", "WARD_PLACED", "WARD_KILL", "ITEM_PURCHASED", "ITEM_SOLD"}:
                continue
            timestamp = event.get("timestamp")
            if not isinstance(timestamp, (int, float)):
                continue
            killer_id = event.get("killerId") if isinstance(event.get("killerId"), int) else None
            victim_id = event.get("victimId") if isinstance(event.get("victimId"), int) else None
            assist_ids = [int(value) for value in event.get("assistingParticipantIds", []) if isinstance(value, int)]
            participant_id = event.get("participantId") if isinstance(event.get("participantId"), int) else None
            item_id = event.get("itemId") if isinstance(event.get("itemId"), int) else None
            if kind in {"ITEM_PURCHASED", "ITEM_SOLD"} and (not isinstance(item_id, int) or item_id <= 0):
                continue
            involved = list(dict.fromkeys([value for value in [killer_id, victim_id, *assist_ids, participant_id] if value]))
            killer = roster.get(killer_id, {})
            victim = roster.get(victim_id, {})
            actor = roster.get(participant_id, {})
            killer_team_id = event.get("killerTeamId")
            if killer_team_id is None:
                killer_team_id = killer.get("teamId")
            team_owner = next((item for item in roster.values() if killer_team_id is not None and item.get("teamId") == killer_team_id), {})
            beneficiary = killer or team_owner or actor
            event_side = beneficiary.get("side", "unknown")
            # Riot exposes damage received in the kill event payload, not as a
            # continuous per-frame series. Treat each reported batch as a new
            # accumulation window and apply KP at that event. Since only a
            # positive weighted batch is added, useful damage can never fall
            # when later team kills reduce a participant's KP.
            champion_damage_batch = 0.0
            all_source_damage_batch = 0.0
            champion_damage_observed = False
            useful_damage_value = None
            if kind == "CHAMPION_KILL":
                if killer_id and killer_team_id:
                    team_kills[int(killer_team_id)] = team_kills.get(int(killer_team_id), 0) + 1
                    player_kills[killer_id] = player_kills.get(killer_id, 0) + 1
                for assisted_id in assist_ids:
                    player_assists[assisted_id] = player_assists.get(assisted_id, 0) + 1
                victim_damage = event.get("victimDamageReceived")
                if victim_id and isinstance(victim_damage, list):
                    champion_damage_observed = True
                    for source in victim_damage:
                        if not isinstance(source, dict):
                            continue
                        damage = source.get("damage")
                        if not isinstance(damage, (int, float)):
                            damage = sum(float(source.get(key) or 0) for key in ("physicalDamage", "magicDamage", "trueDamage"))
                        if isinstance(damage, (int, float)) and damage > 0:
                            all_source_damage_batch += float(damage)
                            source_id = source.get("participantId") if isinstance(source.get("participantId"), int) else None
                            source_participant = roster.get(source_id) if source_id is not None else None
                            victim_participant = roster.get(victim_id)
                            source_team = source_participant.get("teamId") if source_participant else None
                            victim_team = victim_participant.get("teamId") if victim_participant else None
                            if (source_team not in (None, 0) and victim_team not in (None, 0)
                                    and source_team != victim_team):
                                champion_damage_batch += float(damage)
                if victim_id and champion_damage_batch > 0:
                    victim = roster.get(victim_id, {})
                    victim_team = int(victim.get("teamId") or 0)
                    denominator = team_kills.get(victim_team, 0)
                    participation = player_kills.get(victim_id, 0) + player_assists.get(victim_id, 0)
                    kp = min(1.0, participation / denominator) if denominator > 0 else 0.0
                    received_champion_damage[victim_id] = received_champion_damage.get(victim_id, 0.0) + champion_damage_batch
                    useful_damage[victim_id] = useful_damage.get(victim_id, 0.0) + champion_damage_batch * kp
                    useful_damage_value = useful_damage[victim_id]
            label = {"CHAMPION_KILL": "Asesinato", "ELITE_MONSTER_KILL": str(event.get("monsterType") or "Objetivo").replace("DRAGON", "Dragón").replace("BARON_NASHOR", "Barón Nashor").replace("RIFTHERALD", "Heraldo").replace("HORDE", "Larvas del Vacío"),
                     "BUILDING_KILL": str(event.get("buildingType") or "Estructura").replace("TOWER_BUILDING", "Torre").replace("INHIBITOR_BUILDING", "Inhibidor").replace("NEXUS_BUILDING", "Nexo"),
                     "ITEM_PURCHASED": "Compra", "ITEM_SOLD": "Venta", "ITEM_UNDO": "Reversión de objeto", "ITEM_DESTROYED": "Objeto destruido"}.get(kind, kind)
            events.append({"id": f"{frame_index}:{index}:{int(timestamp)}", "timestamp": timestamp,
                "type": kind, "category": "Centinela colocado" if kind == "WARD_PLACED" else "Centinela destruido" if kind == "WARD_KILL" else label, "side": event_side, "participantIds": involved,
                "killerId": killer_id, "victimId": victim_id, "assistingIds": assist_ids,
                "killerChampion": killer.get("champion"), "victimChampion": victim.get("champion"),
                "assistChampions": [roster.get(value, {}).get("champion") for value in assist_ids],
                "champion": (actor or killer).get("champion"), "actorId": participant_id or killer_id, "itemId": item_id,
                "itemName": _item_name(item_id) if item_id else None,
                "monsterType": event.get("monsterType"), "monsterSubType": event.get("monsterSubType"),
                "buildingType": event.get("buildingType"), "laneType": event.get("laneType"),
                "position": event.get("position") if isinstance(event.get("position"), dict) else None,
                "towerType": event.get("towerType"), "wardType": event.get("wardType"), "teamId": event.get("teamId"), "killerTeamId": killer_team_id,
                "shutdownBounty": event.get("shutdownBounty"),
                "championDamageReceivedObserved": champion_damage_observed if kind == "CHAMPION_KILL" else None,
                "championDamageReceivedDelta": champion_damage_batch if kind == "CHAMPION_KILL" else None,
                "allSourceDamageReceivedDelta": all_source_damage_batch if kind == "CHAMPION_KILL" else None,
                "championDamageReceivedCumulative": received_champion_damage.get(victim_id) if kind == "CHAMPION_KILL" and victim_id else None,
                "usefulDamageReceived": useful_damage_value,
                "killParticipationAtEvent": (min(1.0, (player_kills.get(victim_id, 0) + player_assists.get(victim_id, 0)) / team_kills.get(int(victim.get("teamId") or 0), 1))
                    if kind == "CHAMPION_KILL" and victim_id and int(victim.get("teamId") or 0) in team_kills else None)})
    return events, frames_out


def _attach_battlescore(record: dict[str, Any], participants: list[dict[str, Any]], match_id: str,
                        events: list[dict[str, Any]], frames: list[dict[str, Any]], duration: float,
                        calibration_baselines: dict[str, Any] | None = None,
                        analysis_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load a valid current-version result or calculate from stored Riot telemetry."""
    from backend.battlescore import VERSION, calculate_match, telemetry_fingerprint
    cached = record.get("battle_score") if isinstance(record.get("battle_score"), dict) else {}
    fingerprint = telemetry_fingerprint(participants, events, frames, duration, calibration_baselines, analysis_config)
    if cached.get("version") == VERSION and cached.get("inputFingerprint") == fingerprint and cached.get("state") in {"complete", "partial"}:
        result = cached
    else:
        result = calculate_match(match_id, participants, events, frames, duration, calibration_baselines, analysis_config)
        record["battle_score"] = result
        record["battle_score_calculated_at"] = datetime.now(UTC).isoformat()
    if result.get("configurationHash"):
        record["battle_score_configuration"] = {
            "engine": result.get("version"), "revision": result.get("configurationRevision"),
            "hash": result.get("configurationHash"), "telemetryState": result.get("state"),
        }
    scores = {int(item["participantId"]): item for item in result.get("participants", []) if isinstance(item, dict) and item.get("participantId") is not None}
    for participant in participants:
        score = scores.get(int(participant.get("participantId") or 0))
        participant.pop("battleScore", None)
        participant.pop("battleScoreSeries", None)
        participant.pop("battleScoreVersion", None)
        if score and score.get("state") in {"complete", "partial"}:
            participant["battleScore"] = score["finalScore"]
            participant["battleScoreSeries"] = score["series"]
            participant["battleScoreVersion"] = VERSION
            participant["battleScoreCoverage"] = "partial" if result.get("state") == "partial" else "complete"
        participant["battleScoreComponentAvailability"] = score.get("componentAvailability", {}) if score else {}
    _apply_champion_damage_received(participants, events)
    return result


def _apply_champion_damage_received(participants: list[dict[str, Any]], events: list[dict[str, Any]]) -> None:
    """Expose death-event champion-sourced receipt as partial coverage only."""
    totals: dict[int, float] = {}
    observed: set[int] = set()
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "CHAMPION_KILL":
            continue
        victim_id = event.get("victimId")
        if not isinstance(victim_id, int):
            continue
        if event.get("championDamageReceivedObserved"):
            observed.add(victim_id)
        delta = event.get("championDamageReceivedDelta")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta > 0:
            totals[victim_id] = totals.get(victim_id, 0.0) + float(delta)
    for participant in participants:
        pid = participant.get("participantId")
        if participant.get("championDamageDealt") is None and isinstance(participant.get("damage"), (int, float)):
            participant["championDamageDealt"] = participant.get("damage")
        if participant.get("allSourceDamageReceived") is None and isinstance(participant.get("damageTaken"), (int, float)):
            participant["allSourceDamageReceived"] = participant.get("damageTaken")
        participant.pop("damage", None)
        participant.pop("damageTaken", None)
        if isinstance(pid, int):
            participant["championDamageReceived"] = totals.get(pid) if pid in observed else None
            participant["championDamageReceivedCoverage"] = "partial" if pid in observed else "unavailable"


def download_match(repository: HomeHistoryRepository, match_id: str) -> dict[str, Any]:
    profile = repository.load_last_profile()
    if not profile:
        raise ValueError("No hay un perfil local sincronizado.")
    record = next((item for item in _records(repository, profile) if str(item.get("match_id")) == match_id), None)
    if not record:
        raise KeyError("El análisis guardado ya no existe.")
    if _has_persisted_timeline(record):
        # The saved analysis already contains Riot participants and timeline.
        # Re-opening it or changing analysis settings must not depend on a
        # Riot API/cache hit or restart a download.
        previous_status = record.get("status")
        record["status"] = "ready" if record.get("local_identity_resolved") else "partial"
        record["status_message"] = (
            "Listo para analizar." if record.get("local_identity_resolved")
            else "CronologÃ­a guardada; identidad local sin confirmar."
        )
        if previous_status != record["status"]:
            record["updated_at"] = datetime.now(UTC).isoformat()
            repository.save_soloq_analysis(profile, record)
        logging.getLogger(__name__).info(
            "soloq.stage match=%s stage=persisted_timeline_reused participants=%s frames=%s",
            match_id, len(record["participants"]), len(record["frames"]),
        )
        return record
    record.update({"status": "downloading", "status_message": "Descargando datos Match-V5.", "updated_at": datetime.now(UTC).isoformat()})
    repository.save_soloq_analysis(profile, record)
    api_key = str(SettingsService().load().get("riot_api_key") or "").strip()
    if not api_key:
        raise ValueError("No hay una clave de Riot API configurada en Ajustes.")
    account_region, platform = _routing(str(profile.get("region") or ""))
    if "_" not in match_id or match_id.partition("_")[0].casefold() != platform.casefold():
        raise ValueError(f"El ID {match_id} no corresponde a la región de plataforma {platform.upper()}.")
    api = RiotApiService(api_key, account_region=account_region, platform_region=platform)
    cache = api.cache
    puuid = str(profile.get("riot_puuid") or profile.get("puuid") or "").strip()
    logger = logging.getLogger(__name__)
    logger.info("soloq.stage match=%s stage=match_detail_start platform=%s regional=%s", match_id, platform, account_region)
    detail = cache.get_match(match_id, puuid) if puuid else None
    if detail and (detail.get("detail_version") != 1 or not detail.get("player_resolved", True)):
        detail = None
    raw = None
    resolved_puuid = puuid if detail else None
    if detail is None:
        raw = cache.get_raw_match(match_id)
        if raw:
            logger.info("soloq.stage match=%s stage=match_detail_raw_cache", match_id)
        else:
            cooldown = cache.rate_limit_remaining_seconds()
            if cooldown:
                raise RiotApiError("Riot ha limitado temporalmente las solicitudes.", 429, cooldown)
            raw = api.get_match(match_id)
            metadata = raw.get("metadata") if isinstance(raw, dict) and isinstance(raw.get("metadata"), dict) else {}
            info = raw.get("info") if isinstance(raw, dict) and isinstance(raw.get("info"), dict) else {}
            participants_raw = info.get("participants")
            if str(metadata.get("matchId") or "") != match_id:
                raise RiotApiError("Riot devolvió una partida con un ID distinto al solicitado.")
            if not isinstance(participants_raw, list) or not participants_raw:
                raise RiotApiError("La respuesta Match-V5 no contiene participantes válidos.")
            if int(info.get("queueId") or 0) != 420:
                raise ValueError("Riot confirmó que la partida no pertenece a la cola SoloQ 420.")
            cache.save_raw_match(match_id, raw)
            logger.info("soloq.stage match=%s stage=match_detail_validated queue=420 participants=%s", match_id, len(participants_raw))
        info = raw.get("info") if isinstance(raw, dict) and isinstance(raw.get("info"), dict) else {}
        participants_raw = info.get("participants", [])
        if any(isinstance(item, dict) and item.get("puuid") == puuid for item in participants_raw):
            resolved_puuid = puuid
        else:
            logger.warning("soloq.stage match=%s stage=local_identity profile_puuid_match=false participants=%s", match_id, len(participants_raw))
            game_name, tag_line = str(profile.get("gameName") or "").strip(), str(profile.get("tagLine") or "").strip()
            if game_name and tag_line:
                try:
                    account = api.get_account_by_riot_id(game_name, tag_line, use_cache=False)
                    candidate = str(account.get("puuid") or "").strip()
                    if candidate and any(isinstance(item, dict) and item.get("puuid") == candidate for item in participants_raw):
                        resolved_puuid = candidate
                        profile = repository.save_verified_riot_puuid(profile, candidate)
                        puuid = candidate
                        logger.info("soloq.stage match=%s stage=local_identity account_v1_match=true", match_id)
                    else:
                        logger.warning("soloq.stage match=%s stage=local_identity account_v1_match=false", match_id)
                except RiotApiError as error:
                    logger.warning("soloq.stage match=%s stage=local_identity account_v1_error status=%s", match_id, error.status_code)
        detail = RiotApiService._create_match_detail(raw, match_id, resolved_puuid or "", allow_unresolved=True)
        if int(detail.get("queue_id") or 0) != 420:
            raise ValueError("La partida descargada no es Solo/Duo clasificatoria.")
        cache.save_match(detail, puuid)
        logger.info("soloq.stage match=%s stage=participant_mapping resolved=%s participants=%s", match_id, bool(resolved_puuid), len(detail.get("allies", []) + detail.get("enemies", [])))
    if int(detail.get("queue_id") or 0) != 420:
        raise ValueError("La partida descargada no es Solo/Duo clasificatoria.")
    record.update({"status": "processing", "status_message": "Procesando cronología.", "updated_at": datetime.now(UTC).isoformat()})
    repository.save_soloq_analysis(profile, record)
    timeline = cache.get_timeline(match_id)
    if timeline is None:
        try:
            timeline = api.get_match_timeline(match_id)
        except RiotApiError as error:
            if error.status_code != 404:
                raise
            timeline = None
    if timeline is not None:
        metadata = timeline.get("metadata") if isinstance(timeline.get("metadata"), dict) else {}
        timeline_id = str(metadata.get("matchId") or "")
        if timeline_id and timeline_id != match_id:
            raise RiotApiError("La cronología de Riot pertenece a otro ID de partida.")
        timeline_info = timeline.get("info") if isinstance(timeline.get("info"), dict) else {}
        if not isinstance(timeline_info.get("frames"), list):
            raise RiotApiError("Riot devolvió una cronología sin frames válidos.")
    source_participants = detail.get("allies", []) + detail.get("enemies", [])
    local_team = int(detail.get("player_team_id") or 0)
    participants = []
    for item in source_participants:
        public = _public_participant(item, puuid)
        public["side"] = ("unknown" if not detail.get("player_resolved") or not local_team
                          else "allied" if public["teamId"] == local_team else "enemy")
        participants.append(public)
    participants.sort(key=lambda item: int(item.get("participantId") or 0))
    duration = float(detail.get("game_duration") or record.get("duration") or 0)
    for participant in participants:
        participant["radar"] = _radar_for(participant, duration)
    events, frames = _normalize_events(timeline, participants) if timeline else ([], [])
    timeline_available = timeline is not None
    if timeline_available:
        references = _role_phase_references(repository, profile, cache, match_id)
        battle_score = _attach_battlescore(record, participants, match_id, events, frames, duration, references)
    else:
        from backend.battlescore import VERSION
        battle_score = {"version": VERSION, "state": "unavailable", "matchId": match_id, "participants": []}
    local = next((item for item in participants if item["local"]), {})
    info_time = detail.get("game_creation")
    started = datetime.fromtimestamp(info_time / 1000, UTC).isoformat() if isinstance(info_time, (int, float)) and info_time > 0 else record.get("started_at", "")
    resolved = bool(detail.get("player_resolved"))
    record.update({
        "champion": local.get("champion", record.get("champion")), "champion_id": local.get("championId", record.get("champion_id")),
        "started_at": started, "duration": detail.get("game_duration", record.get("duration")), "mode": detail.get("game_mode", record.get("mode")),
        "role": local.get("role", record.get("role")), "kills": local.get("kills", record.get("kills")),
        "deaths": local.get("deaths", record.get("deaths")), "assists": local.get("assists", record.get("assists")),
        "win": local.get("win", record.get("win")), "queue_id": detail.get("queue_id"), "patch": detail.get("game_version"),
        "participants": participants, "events": events, "frames": frames, "radar_teams": _team_radar(participants), "battle_score": battle_score,
        "local_identity_resolved": resolved, "timeline_available": timeline_available,
        "status": "ready" if timeline_available and resolved else "partial",
        "status_message": ("Listo para analizar." if timeline_available and resolved else
            "Partida y cronología descargadas; identidad local sin confirmar. Reintenta la verificación del Riot ID." if timeline_available else
            "Detalle disponible; la cronología de Riot no está disponible."),
        "updated_at": datetime.now(UTC).isoformat(),
    })
    if timeline_available and participants:
        _rebuild_saved_ai_timeline_index(record, events)
    repository.save_soloq_analysis(profile, record)
    logger.info("soloq.stage match=%s stage=complete participants=%s local_resolved=%s timeline=%s frames=%s events=%s", match_id, len(participants), resolved, timeline_available, len(frames), len(events))
    return record

def update_status(repository: HomeHistoryRepository, match_id: str, status: str, message: str) -> None:
    profile = repository.load_last_profile()
    if not profile:
        return
    record = next((item for item in _records(repository, profile) if str(item.get("match_id")) == match_id), None)
    if not record:
        return
    record.update({"status": status, "status_message": message, "updated_at": datetime.now(UTC).isoformat()})
    repository.save_soloq_analysis(profile, record)


def save_ai_status(repository: HomeHistoryRepository, match_id: str, status: str, message: str) -> None:
    profile = repository.load_last_profile()
    if not profile:
        return
    record = next((item for item in _records(repository, profile) if str(item.get("match_id")) == match_id), None)
    if not record:
        return
    record["ai_generation_status"] = status
    record["ai_status_message"] = message
    record["updated_at"] = datetime.now(UTC).isoformat()
    repository.save_soloq_analysis(profile, record)


def get_ai_status(repository: HomeHistoryRepository, match_id: str) -> dict[str, Any]:
    """Read the short AI job status without recalculating or rewriting telemetry."""
    profile = repository.load_last_profile()
    if not profile:
        raise KeyError("No hay un perfil sincronizado para esta biblioteca.")
    record = next((item for item in _records(repository, profile)
                   if str(item.get("match_id") or "") == match_id), None)
    if not record:
        raise KeyError("El análisis SoloQ no está guardado.")
    saved = record.get("ai_analysis")
    public_analysis = ({key: saved[key] for key in ("analysis", "provider", "model", "created_at") if key in saved}
                       if isinstance(saved, dict) else None)
    return {
        "match_id": match_id,
        "ai_analysis": public_analysis,
        "ai_generation_status": str(record.get("ai_generation_status") or "idle"),
        "ai_status_message": str(record.get("ai_status_message") or "")[:300],
    }


def delete_analysis(repository: HomeHistoryRepository, match_id: str) -> bool:
    profile = repository.load_last_profile()
    if not profile:
        return False
    deleted = repository.delete_soloq_analysis(profile, match_id)
    if deleted:
        try:
            from app.services.match_log_service import MatchLogService
            MatchLogService().delete_match_log(match_id)
        except (OSError, ValueError):
            pass
    return deleted


def preview_saved_analysis_deletion(repository: HomeHistoryRepository, match_id: str) -> dict[str, Any]:
    from backend.match_deletion import preview_saved_match_deletion
    return preview_saved_match_deletion(match_id=match_id, repository=repository)


def delete_saved_analysis_cascade(repository: HomeHistoryRepository, match_id: str, manifest_id: str) -> dict[str, Any]:
    from backend.match_deletion import delete_saved_match_footprint
    return delete_saved_match_footprint(match_id=match_id, manifest_id=manifest_id, repository=repository)


def generate_ai_analysis(repository: HomeHistoryRepository, match_id: str, *, force: bool = False) -> dict[str, Any]:
    record = get_analysis(repository, match_id)
    if record.get("status") not in {"ready", "partial"}:
        raise ValueError("Espera a que termine la descarga de los datos de Riot.")
    if record.get("ai_analysis") and not force:
        return record
    if not _ai_lock.acquire(blocking=False):
        raise ValueError("Ya hay un análisis con IA en curso.")
    try:
        api_key = str(SettingsService().load().get("gemini_api_key") or "").strip()
        if not api_key:
            raise ValueError("No hay una clave de Gemini configurada en Ajustes.")
        participants = record.get("participants") or []
        local = next((item for item in participants if item.get("local")), None)
        if not local:
            raise ValueError("Riot no identificó al jugador local en este roster.")
        players: dict[str, dict[str, Any]] = {}
        final: dict[str, dict[str, Any]] = {}
        for participant in participants:
            key = str(participant.get("participantId"))
            players[key] = {
                "champion_name": participant.get("champion"), "role": participant.get("role"),
                "team": "100" if participant.get("side") == "allied" else "200",
                "kills": participant.get("kills"), "deaths": participant.get("deaths"),
                "assists": participant.get("assists"), "cs": participant.get("cs"),
                "gold_earned": participant.get("gold"), "vision_score": participant.get("vision"),
                "total_damage_dealt_to_champions": participant.get("championDamageDealt"),
                "damage_dealt_to_objectives": participant.get("damageToObjectives"),
                "all_source_damage_received": participant.get("allSourceDamageReceived"), "items": participant.get("items", []),
                "runes": participant.get("runes"), "summoner_spells": participant.get("summonerSpells"),
            }
            final[key] = dict(players[key])
        events = []
        for index, event in enumerate(record.get("events", [])):
            kind = str(event.get("type") or "")
            if kind not in {"CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL", "TURRET_PLATE_DESTROYED", "ITEM_PURCHASED", "ITEM_SOLD"}:
                continue
            event_actor = event.get("killerId") or (event.get("participantIds") or [None])[0]
            events.append({"order": index, "time": float(event.get("timestamp") or 0) / 1000,
                "type": kind, "team": "100" if event.get("side") == "allied" else "200" if event.get("side") == "enemy" else "",
                "label": event.get("category"), "objective": event.get("monsterType") or event.get("buildingType"),
                "objective_label": event.get("category") if kind in {"ELITE_MONSTER_KILL", "BUILDING_KILL", "TURRET_PLATE_DESTROYED"} else None,
                "objective_subtype": event.get("monsterSubType"),
                "owner_team": event.get("teamId"), "team_source": "killerTeamId" if event.get("killerTeamId") is not None else "side",
                "source_reference": event.get("id"), "timestamp_ms": event.get("timestamp"),
                "position": event.get("position") if isinstance(event.get("position"), dict) else None,
                "shutdown": bool(event.get("shutdownBounty")), "bounty": event.get("shutdownBounty"),
                "player_key": str(event_actor) if event_actor is not None else "",
                "killer_key": str(event.get("killerId") or "") if event.get("killerId") else None,
                "victim_key": str(event.get("victimId") or "") if event.get("victimId") else None,
                "assister_keys": [str(value) for value in event.get("assistingIds", [])], "item_id": event.get("itemId")})
        local_team = "100" if local.get("side") == "allied" else "200"
        session = {
            "session_id": match_id, "champion_name": local.get("champion"), "started_at": record.get("started_at"),
            "ended_at": record.get("started_at"), "duration": float(record.get("duration") or 0),
            "game_mode": record.get("mode"), "players": players, "local_player_key": str(local["participantId"]),
            "local_team": local_team, "winning_team": local_team if record.get("win") else ("200" if local_team == "100" else "100"),
            "final_scoreboard": final, "events": events,
            "metadata": {"game_version": record.get("patch"), "result": "victory" if record.get("win") else "defeat"},
        }
        from app.services.match_ai_analyzer_service import MatchAIAnalyzerService
        analysis, source_response, model, fingerprint = MatchAIAnalyzerService().analyze_match(session, api_key)
        record["ai_analysis"] = {"analysis": analysis, "provider": "Gemini", "model": model,
                                 "source_response": source_response, "source_fingerprint": fingerprint,
                                 "created_at": datetime.now(UTC).isoformat()}
        # The analyzer already enriches with the real match context. Re-enriching
        # without that context used to replace match_evidence with {}, deleting
        # every event reference before the report was persisted.
        if record.get("timeline_available") and record.get("participants"):
            _rebuild_saved_ai_timeline_index(record, record.get("events", []))
        record["analysis_available"] = True
        repository.save_soloq_analysis(repository.load_last_profile(), record)
        return record
    finally:
        _ai_lock.release()
