"""Join persisted SoloQ BattleScores to account-scoped Home history.

This reads the existing saved result; scoring and migration remain owned by
soloq_analyses and the BattleScore engine.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from backend.analysis_settings import engine_snapshot, load_configuration
from backend.battlescore import VERSION


def attach_saved_battlescores(matches: list[dict[str, Any]], records: list[dict[str, Any]],
                             profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return shallow history rows with only verified, current player scores."""
    if not profile or not str(profile.get("riot_puuid") or profile.get("puuid") or "").strip():
        return matches
    active_hash = engine_snapshot(load_configuration())["configuration_hash"]
    by_id: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or record.get("local_identity_resolved") is not True:
            continue
        if str(record.get("queue_id")) != "420":
            continue
        result = record.get("battle_score")
        if not isinstance(result, dict) or result.get("version") != VERSION or result.get("configurationHash") != active_hash:
            continue
        if result.get("state") not in {"complete", "partial"}:
            continue
        match_id = record.get("match_id")
        if not isinstance(match_id, str) or not match_id or result.get("matchId") != match_id:
            continue
        players = record.get("participants")
        if not isinstance(players, list):
            continue
        local = [player for player in players if isinstance(player, dict) and player.get("local") is True]
        if len(local) != 1:
            continue
        participant_id = local[0].get("participantId")
        if isinstance(participant_id, bool) or not isinstance(participant_id, int):
            continue
        scored = result.get("participants")
        if not isinstance(scored, list):
            continue
        scores = [item for item in scored if isinstance(item, dict) and item.get("participantId") == participant_id]
        if len(scores) != 1 or scores[0].get("state") not in {"complete", "partial"}:
            continue
        value = scores[0].get("finalScore")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 10:
            continue
        for identifier in (match_id, record.get("history_match_id")):
            if not isinstance(identifier, str) or not identifier:
                continue
            if identifier in by_id and by_id[identifier] is not record:
                conflicts.add(identifier)
            by_id[identifier] = record
    output = []
    for match in matches:
        if not isinstance(match, dict) or str(match.get("queue_id")) != "420":
            output.append(match)
            continue
        identifiers = {str(match.get(key)) for key in ("stable_match_id", "game_id", "gameId")
                       if match.get(key) is not None and str(match.get(key))}
        if identifiers & conflicts:
            output.append(match)
            continue
        found = {id(by_id[key]): by_id[key] for key in identifiers if key in by_id and key not in conflicts}
        if len(found) != 1:
            output.append(match)
            continue
        record = next(iter(found.values()))
        local_id = next(player["participantId"] for player in record["participants"] if isinstance(player, dict) and player.get("local") is True)
        score = next(item["finalScore"] for item in record["battle_score"]["participants"]
                     if isinstance(item, dict) and item.get("participantId") == local_id)
        output.append({**match, "battle_score": score, "battle_score_version": VERSION,
                       "battle_score_verified": True})
    return output
