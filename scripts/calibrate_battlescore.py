"""Reproducible, read-only BattleScore role calibration over cached SoloQ.

Run with ``.venv/Scripts/python.exe scripts/calibrate_battlescore.py``.
This command never requests Riot data or writes scores back to match history.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import mean, median, pstdev
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.home_history_service import HomeHistoryRepository
from app.services.match_history_cache import MatchHistoryCache
from backend.battlescore import VERSION, calculate_match
from backend.battlescore_v2_1 import calculate_match as calculate_match_v21
from backend.battlescore_calibration import build_role_phase_baselines
from backend.soloq_analyses import _normalize_events
from backend.battlescore_calibration import canonical_role


def _ids(match: dict[str, Any]) -> set[str]:
    result = set()
    for key in ("game_id", "stable_match_id", "match_id"):
        value = str(match.get(key) or "")
        if value:
            result.update((value, value.split("_", 1)[-1]))
    return result


def _participants(match: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for row in match.get("participants", []) if isinstance(match.get("participants"), list) else []:
        if not isinstance(row, dict):
            continue
        pid = row.get("participant_id", row.get("participantId"))
        if not isinstance(pid, int):
            continue
        stats = row.get("final_stats") if isinstance(row.get("final_stats"), dict) else {}
        result.append({
            "participantId": pid, "teamId": row.get("team_id", row.get("teamId")),
            "championId": row.get("champion_id"), "champion": row.get("champion_name"),
            "role": next((canonical_role(row.get(key)) for key in
                           ("team_position", "teamPosition", "timeline_role", "team_role", "lane", "role")
                           if canonical_role(row.get(key))), None),
            "local": bool(row.get("is_local")),
            "championDamageDealt": stats.get("total_damage_dealt_to_champions"),
            "damageToEpicMonsters": stats.get("damage_dealt_to_epic_monsters"),
            "damageToBuildings": stats.get("damage_dealt_to_buildings"),
            "damageToTurrets": stats.get("damage_dealt_to_turrets"),
            "wardsPlaced": stats.get("wards_placed"), "wardsKilled": stats.get("wards_killed"),
            "vision": stats.get("vision_score"),
            "totalHealsOnTeammates": stats.get("total_heals_on_teammates"),
            "totalDamageShieldedOnTeammates": stats.get("total_damage_shielded_on_teammates"),
            "objectivesStolen": stats.get("objectives_stolen"),
        })
    return result


def _aggregate(matches: list[dict[str, Any]], timelines: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    by_id = {match_id: match for match in matches for match_id in _ids(match)}
    variations: dict[str, list[float]] = defaultdict(list)
    previous_scores: dict[str, list[float]] = defaultdict(list)
    components: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    previous_components: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    positive_components: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    durations: dict[str, list[float]] = defaultdict(list)
    samples = 0
    for cached_id, entry in timelines.items():
        match = by_id.get(str(cached_id)) or by_id.get(str(cached_id).split("_", 1)[-1])
        if not match or str(match.get("queue_id") or "") != "420":
            continue
        raw_timeline = entry.get("timeline") if isinstance(entry, dict) else None
        participants = _participants(match)
        if not participants or not isinstance(raw_timeline, dict):
            continue
        events, frames = _normalize_events(raw_timeline, participants)
        duration = float(match.get("duration_seconds") or 0)
        if duration <= 0:
            continue
        references = build_role_phase_baselines(matches, timelines, exclude_match_id=str(cached_id))
        scored = calculate_match(str(cached_id), participants, events, frames, duration, references)
        previous = calculate_match_v21(str(cached_id), participants, events, frames, duration, references)
        previous_by_pid = {row.get("participantId"): row for row in previous.get("participants", [])}
        samples += 1
        for row in scored["participants"]:
            role = str(row.get("role") or "UNKNOWN")
            if role == "UNKNOWN":
                continue
            variations[role].append(float(row["finalScore"]) - 5.0)
            old_row = previous_by_pid.get(row.get("participantId"))
            if old_row and old_row.get("finalScore") is not None:
                previous_scores[role].append(float(old_row["finalScore"]))
                for name, value in old_row.get("breakdown", {}).items():
                    if name not in {"initial_score", "final_score", "contextual_adjustment", "floor_adjustment", "diminishing_adjustment", "recovery_adjustment"}:
                        previous_components[role][name].append(float(value))
            durations[role].append(duration / 60.0)
            for name, value in row.get("breakdown", {}).items():
                if name in {"initial_score", "final_score", "contextual_adjustment", "floor_adjustment", "diminishing_adjustment", "recovery_adjustment"}:
                    continue
                components[role][name].append(float(value))
                if float(value) > 0:
                    positive_components[role][name] += float(value)
    summary = {}
    for role, values in sorted(variations.items()):
        positive = [value for value in values if value > 0]
        negative = [value for value in values if value < 0]
        component_means = {name: round(mean(items), 4) for name, items in sorted(components[role].items())}
        new_scores = [5.0 + value for value in values]
        old_scores = previous_scores[role]
        old_component_means = {name: round(mean(items), 4) for name, items in sorted(previous_components[role].items())}
        passive = positive_components[role].get("gold", 0) + positive_components[role].get("experience", 0)
        all_positive = sum(positive_components[role].values())
        summary[role] = {
            "participants": len(values), "mean_variation": round(mean(values), 3),
            "mean_final_score": round(5.0 + mean(values), 3),
            "median_variation": round(median(values), 3), "stddev": round(pstdev(values), 3),
            "median_final_score": round(5.0 + median(values), 3),
            "positive_pct": round(100 * len(positive) / len(values), 1),
            "negative_pct": round(100 * len(negative) / len(values), 1),
            "median_duration_min": round(median(durations[role]), 1),
            "passive_gold_xp_share_pct": round(100 * passive / all_positive, 1) if all_positive else None,
            "mean_components": component_means,
            "v2_1_mean_final_score": round(mean(previous_scores[role]), 3) if previous_scores[role] else None,
            "v2_1_median_final_score": round(median(old_scores), 3) if old_scores else None,
            "mean_final_score_delta_v2_2_minus_v2_1": round((5.0 + mean(values)) - mean(previous_scores[role]), 3) if previous_scores[role] else None,
            "v2_1_pct_below_2": round(100 * sum(value < 2 for value in old_scores) / len(old_scores), 1) if old_scores else None,
            "v2_2_pct_below_2": round(100 * sum(value < 2 for value in new_scores) / len(new_scores), 1),
            "v2_1_pct_above_8": round(100 * sum(value > 8 for value in old_scores) / len(old_scores), 1) if old_scores else None,
            "v2_2_pct_above_8": round(100 * sum(value > 8 for value in new_scores) / len(new_scores), 1),
            "v2_1_pct_above_10": round(100 * sum(value > 10 for value in old_scores) / len(old_scores), 1) if old_scores else None,
            "v2_2_pct_above_10": round(100 * sum(value > 10 for value in new_scores) / len(new_scores), 1),
            "v2_1_mean_components": old_component_means,
        }
    result = {"version": VERSION, "matches_scored": samples, "roles": summary,
              "reference_labels": "No hay etiquetas independientes de rendimiento; no se clasifican partidas como buenas o malas.",
              "scope": "Muestras repetidas por participante y minuto, agrupadas por partido; no equivalen a una muestra de jugadores independientes."}
    if profile:
        result["local_saved_analysis_comparison"] = _saved_comparison(profile, by_id, timelines)
    return result


def _saved_comparison(profile: dict[str, Any], matches: dict[str, dict[str, Any]], timelines: dict[str, Any]) -> dict[str, Any] | None:
    saved = profile.get("saved_analyses", [])
    if not isinstance(saved, list):
        return None
    for record in saved:
        if not isinstance(record, dict):
            continue
        old = record.get("battle_score") if isinstance(record.get("battle_score"), dict) else {}
        old_rows = old.get("participants", [])
        match_id = str(record.get("match_id") or "")
        match = matches.get(match_id) or matches.get(match_id.split("_", 1)[-1])
        entry = timelines.get(match_id)
        if not match or not isinstance(entry, dict):
            continue
        # Match the authoritative saved-analysis input when it exists; the
        # compact history roster can omit Match-V5 final statistics.
        participants = record.get("participants") if isinstance(record.get("participants"), list) else _participants(match)
        events, frames = _normalize_events(entry.get("timeline") or {}, participants)
        refs = build_role_phase_baselines(list({id(v): v for v in matches.values()}.values()), timelines, exclude_match_id=match_id)
        duration = float(record.get("duration") or match.get("duration_seconds") or 0)
        new = calculate_match(match_id, participants, events, frames, duration, refs)
        old_comparison = calculate_match_v21(match_id, participants, events, frames, duration, refs)
        champion_id = record.get("champion_id")
        champion_name = str(record.get("champion") or "").casefold()
        local_id = next((row["participantId"] for row in participants
                         if (champion_id is not None and str(row.get("championId")) == str(champion_id))
                         or (champion_id is None and str(row.get("champion") or "").casefold() == champion_name)), None)
        old_local = next((row for row in old_rows if isinstance(row, dict)
                          and ((champion_id is not None and str(row.get("championId")) == str(champion_id))
                               or (champion_id is None and str(row.get("champion") or "").casefold() == champion_name))), None)
        old_final = old_local.get("finalScore") if old_local else None
        new_local = next((row for row in new["participants"] if row.get("participantId") == local_id), None)
        new_final = new_local.get("finalScore") if new_local else None
        old_rows_by_id = {row.get("participantId"): row for row in old_comparison.get("participants", [])}
        participant_comparison = []
        for player in participants:
            pid = player.get("participantId")
            new_row = next((row for row in new["participants"] if row.get("participantId") == pid), None)
            old_row = old_rows_by_id.get(pid)
            if new_row:
                participant_comparison.append({
                    "participantId": pid, "champion": player.get("champion"), "role": player.get("role"),
                    "v2_1": old_row.get("finalScore") if old_row else None,
                    "v2_1_breakdown": old_row.get("breakdown") if old_row else None,
                    "v2_2": new_row.get("finalScore"),
                    "delta": round(float(new_row["finalScore"]) - float(old_row["finalScore"]), 4) if old_row else None,
                    "v2_2_audit": new_row.get("audit"),
                })
        old_local_calculated = old_rows_by_id.get(local_id)
        return {"previous_version": "battlescore_v2_1", "new_version": VERSION,
                "previous_local_score": old_local_calculated.get("finalScore") if old_local_calculated else old_final,
                "new_local_score": new_final,
                "delta": round(float(new_final) - float(old_local_calculated["finalScore"]), 3) if new_final is not None and old_local_calculated and old_local_calculated.get("finalScore") is not None else None,
                "match_duration_min": round(duration / 60, 1), "participants": participant_comparison}
    return None


def main() -> None:
    repository = HomeHistoryRepository()
    profile_data = repository.load_last_profile()
    if not profile_data:
        print(json.dumps({"version": VERSION, "matches_scored": 0, "confidence": "no_local_profile"}, ensure_ascii=False, indent=2))
        return
    history = repository.load(profile_data).get("matches", [])
    cache = MatchHistoryCache()
    report = _aggregate(history, cache.data.get("timelines", {}), profile=repository.load(profile_data))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
