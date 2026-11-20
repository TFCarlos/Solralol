"""Real-data analytics for the Electron Home dashboard redesign.

All ranked scopes are Solo/Duo queue 420. Activity buckets assign each match
once by its local start time; champion archetypes split each match evenly over
the champion's Data Dragon tags.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from typing import Any

from app.services.home_history_service import (
    _aggregate_kda,
    _home_number,
    _local_champion_metadata,
    _solo_queue_matches,
    normalizar_partidas_unicas,
)

ROLE_KEYS = ("top", "jungle", "mid", "adc", "support")
ROLE_LABELS = {"top": "Superior", "jungle": "Jungla", "mid": "Medio", "adc": "Inferior", "support": "Soporte"}
ARCHETYPE_LABELS = {"Assassin": "Asesino", "Tank": "Tanque", "Fighter": "Luchador", "Mage": "Mago", "Marksman": "Tirador", "Support": "Apoyo"}
WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def build_ranked_dashboard_analytics(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the complete unique queue-420 history for Home cards."""
    ranked = _solo_queue_matches(matches)
    groups: dict[str, list[dict[str, Any]]] = {"all": ranked}
    roles: Counter[str] = Counter()
    for match in ranked:
        lane = _canonical_role(match.get("lane"))
        if lane:
            roles[lane] += 1
            groups.setdefault(lane, []).append(match)
    primary = min(ROLE_KEYS, key=lambda role: (-roles[role], ROLE_KEYS.index(role))) if roles else None
    selectable = [role for role in ROLE_KEYS if role == primary or roles[role] >= 16]
    champion_metadata = _local_champion_metadata()
    evolution_by_role = {role: _performance_evolution(group, champion_metadata) for role, group in groups.items()}
    return {
        "scope": "SoloQ (cola 420), historial local registrado",
        "ranked_match_count": len(ranked),
        "roles": [{"id": role, "label": ROLE_LABELS[role], "matches": roles[role], "primary": role == primary, "selectable": role in selectable} for role in ROLE_KEYS if roles[role]],
        "primary_role": primary,
        "role_options": ["all", *selectable],
        "stats_by_role": {role: _ranked_stats(group, role, len(ranked), evolution_by_role[role]) for role, group in groups.items()},
        "champions": _champion_rows(ranked),
        "performance_evolution": evolution_by_role["all"],
        "performance_evolution_by_role": evolution_by_role,
        "archetype": _archetype_summary(ranked),
        "counter": _counter_summary(_counter_solo_queue_matches(matches)),
        "activity": _activity_summary([m for m in normalizar_partidas_unicas(matches) if m.get("result") in {"victory", "defeat"}]),
    }


def _performance_evolution(matches: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return real per-match metrics for the 30 newest eligible SoloQ games."""
    metadata = metadata if metadata is not None else _local_champion_metadata()
    output = []
    for index, match in enumerate(matches[-30:], 1):
        kills, deaths, assists = (_home_number(match, key) for key in ("kills", "deaths", "assists"))
        duration = _home_number(match, "duration_seconds", positive=True)
        cs = _home_number(match, "cs")
        local = _local_stats(match)
        damage = _final(match, "total_damage_dealt_to_champions")
        solo_kills = _final(match, "solo_kills")
        gold_diff_15 = _signed_home_number(match, "gold_diff_15")
        kill_participation = _match_kill_participation(match, local)
        vision = _home_number(match, "vision_score")
        if vision is None:
            vision = _home_number(local.get("final_stats", {}) if isinstance(local.get("final_stats"), dict) else {}, "vision_score")
        kda = round((kills + assists) / deaths, 2) if None not in (kills, deaths, assists) and deaths > 0 else None
        score = _validated_performance_score(match)
        champion_id = str(match.get("champion_id") or "")
        output.append({
            "position": index,
            "match_id": str(match.get("stable_match_id") or match.get("game_id") or match.get("gameId") or ""),
            "started_at": match.get("started_at"),
            "result": match.get("result"),
            "role": _canonical_role(match.get("lane")),
            "champion_id": metadata.get(champion_id, {}).get("id") or champion_id or None,
            "champion_name": str(match.get("champion_name") or metadata.get(champion_id, {}).get("name") or "") or None,
            "duration_seconds": duration,
            "kda": kda,
            "cs_per_minute": round(cs / (duration / 60), 2) if cs is not None and duration else None,
            "damage_per_minute": round(damage / (duration / 60), 1) if damage is not None and duration else None,
            "kill_participation": kill_participation,
            "solo_kills": solo_kills,
            "vision_score": _match_vision_score(match, local),
            "gold_diff_15": gold_diff_15,
            "performance_score": score,
        })
    return output


def _canonical_role(value: Any) -> str | None:
    role = str(value or "").strip().casefold()
    aliases = {"bottom": "adc", "bot": "adc", "utility": "support", "sup": "support", "middle": "mid", "jungler": "jungle"}
    role = aliases.get(role, role)
    return role if role in ROLE_KEYS else None


def _local_stats(match: dict[str, Any]) -> dict[str, Any]:
    participants = match.get("participants")
    if isinstance(participants, list):
        marked = next((item for item in participants if isinstance(item, dict) and item.get("is_local")), None)
        if marked is not None:
            return marked
        # Recover records saved before participants received an is_local marker.
        # Champion plus the match-level KDA gives a unique identity in SoloQ;
        # ambiguous matches remain unavailable rather than misattributed.
        champion_id = str(match.get("champion_id") or "")
        candidates = [item for item in participants if isinstance(item, dict)
                      and champion_id and str(item.get("champion_id") or "") == champion_id
                      and item.get("team_id") is not None]
        exact = [item for item in candidates
                 if all(_home_number(match, key) is not None
                        and _home_number(item, key) == _home_number(match, key)
                        for key in ("kills", "deaths", "assists"))]
        if len(exact) == 1:
            return exact[0]
        if len(candidates) == 1:
            return candidates[0]
    return {}


def _final(match: dict[str, Any], key: str) -> float | None:
    stats = _local_stats(match).get("final_stats")
    if isinstance(stats, dict):
        value = _home_number(stats, key)
        if value is not None:
            return value
    return _home_number(match, key)


def _signed_home_number(source: dict[str, Any], key: str) -> float | None:
    value = source.get(key)
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _match_vision_score(match: dict[str, Any], local: dict[str, Any] | None = None) -> float | None:
    value = _home_number(match, "vision_score")
    if value is not None:
        return value
    local = local if isinstance(local, dict) else _local_stats(match)
    stats = local.get("final_stats")
    return _home_number(stats, "vision_score") if isinstance(stats, dict) else None


def _match_kill_participation(match: dict[str, Any], local: dict[str, Any]) -> float | None:
    participants = match.get("participants")
    if not isinstance(participants, list) or local.get("team_id") is None:
        return None
    enemies = [row for row in participants if isinstance(row, dict) and row.get("team_id") is not None and row.get("team_id") != local["team_id"]]
    if len(enemies) != 5:
        return None
    enemy_deaths = [_home_number(player, "deaths") for player in enemies]
    kills, assists = _home_number(local, "kills"), _home_number(local, "assists")
    if any(value is None for value in enemy_deaths) or kills is None or assists is None:
        return None
    team_kills = sum(value for value in enemy_deaths if value is not None)
    if team_kills <= 0:
        return None
    return round((kills + assists) * 100 / team_kills, 1)


def _ranked_stats(matches: list[dict[str, Any]], role: str, total: int, evolution: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    kda, kda_n, zero_deaths = _aggregate_kda(matches)
    durations = [(match, _home_number(match, "duration_seconds", positive=True)) for match in matches]
    cs_rows = [(match, duration) for match, duration in durations if duration and _home_number(match, "cs") is not None]
    cs_minutes = sum(float(duration) for _, duration in cs_rows) / 60
    cs_min = round(sum(_home_number(match, "cs") or 0 for match, _ in cs_rows) / cs_minutes, 2) if cs_minutes else None
    damage_rows = [(match, duration, _final(match, "total_damage_dealt_to_champions")) for match, duration in durations]
    damage_rows = [(match, duration, damage) for match, duration, damage in damage_rows if duration and damage is not None]
    damage_min = round(sum(damage for _, _, damage in damage_rows) / (sum(float(duration) for _, duration, _ in damage_rows) / 60)) if damage_rows else None
    kp_num = kp_den = 0.0
    kp_sample = 0
    for match in matches:
        local = _local_stats(match)
        team_id = local.get("team_id")
        participants = match.get("participants")
        if team_id is None or not isinstance(participants, list):
            continue
        enemies = [p for p in participants if isinstance(p, dict) and p.get("team_id") is not None and p.get("team_id") != team_id]
        if len(enemies) != 5:
            continue
        enemy_deaths = [_home_number(p, "deaths") for p in enemies]
        player_kills, player_assists = _home_number(local, "kills"), _home_number(local, "assists")
        if all(value is not None for value in enemy_deaths) and player_kills is not None and player_assists is not None:
            team_kills = sum(value for value in enemy_deaths if value is not None)
            if team_kills <= 0:
                continue
            kp_num += player_kills + player_assists
            kp_den += team_kills
            kp_sample += 1
    kp = round(kp_num * 100 / kp_den, 1) if kp_den else None
    solo_rows = [(match, _final(match, "solo_kills")) for match in matches]
    solo_rows = [(match, value) for match, value in solo_rows if value is not None]
    gold_rows = [_signed_home_number(match, "gold_diff_15") for match in matches]
    gold_rows = [value for value in gold_rows if value is not None]
    vision_rows = [_match_vision_score(match) for match in matches]
    vision_rows = [value for value in vision_rows if value is not None]
    scores = [_validated_performance_score(match) for match in matches]
    scores = [score for score in scores if score is not None]
    champion_counts = Counter(str(match.get("champion_id") or "") for match in matches if match.get("champion_id"))
    metadata = _local_champion_metadata()
    champion_id = champion_counts.most_common(1)[0][0] if champion_counts else None
    champion = metadata.get(champion_id or "", {})
    evolution = evolution or []
    trends = {
        "kda": _metric_trend(evolution, "kda", 2),
        "damage_per_minute": _metric_trend(evolution, "damage_per_minute", 1),
        "kill_participation": _metric_trend(evolution, "kill_participation", 1),
        "cs_per_minute": _metric_trend(evolution, "cs_per_minute", 2),
        "vision_score": _metric_trend(evolution, "vision_score", 1),
        "gold_diff_15": _metric_trend(evolution, "gold_diff_15", 0),
        "performance_score": _metric_trend(evolution, "performance_score", 1),
    }
    return {
        "role": role, "matches": len(matches), "wins": sum(match.get("result") == "victory" for match in matches),
        "kda": {"value": kda, "sample": kda_n, "zero_deaths": zero_deaths, "trend": trends["kda"]},
        "damage_per_minute": {"value": damage_min, "sample": len(damage_rows), "trend": trends["damage_per_minute"]},
        "kill_participation": {"value": kp, "sample": kp_sample, "trend": trends["kill_participation"]},
        "cs_per_minute": {"value": cs_min, "sample": len(cs_rows), "trend": trends["cs_per_minute"]},
        "vision_score": {"value": round(sum(vision_rows) / len(vision_rows), 1) if vision_rows else None, "sample": len(vision_rows), "trend": trends["vision_score"]},
        "solo_kills_per_match": {"value": round(sum(value for _, value in solo_rows) / len(solo_rows), 2) if solo_rows else None, "sample": len(solo_rows)},
        "gold_diff_15": {"value": round(sum(gold_rows) / len(gold_rows)) if gold_rows else None, "sample": len(gold_rows), "trend": trends["gold_diff_15"]},
        "performance_score": {"value": float((sum(Decimal(str(score)) for score in scores) / Decimal(len(scores))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if scores else None, "sample": len(scores), "version": next((match.get("battle_score_version") for match in matches if _validated_performance_score(match) is not None), None), "trend": trends["performance_score"]},
        "top_champion_id": champion.get("id"), "top_champion_name": champion.get("name"),
        "recorded_scope_count": total,
    }


def _metric_trend(points: list[dict[str, Any]], key: str, precision: int) -> dict[str, Any] | None:
    values = [point.get(key) for point in points]
    valid = [float(value) for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if len(valid) < 2:
        return None
    latest = valid[-1]
    baseline = sum(valid[:-1]) / len(valid[:-1])
    delta = latest - baseline
    tolerance = 0.5 * (10 ** -precision)
    direction = "neutral" if abs(delta) < tolerance else "positive" if delta > 0 else "negative"
    return {"latest": round(latest, precision), "previous_average": round(baseline, precision),
            "delta": round(delta, precision), "direction": direction, "sample": len(valid) - 1,
            "precision": precision}


def gold_difference_at_15(match: dict[str, Any], timeline: dict[str, Any]) -> int | None:
    """Resolve local minus direct opponent gold from the frame nearest minute 15."""
    duration = _home_number(match, "duration_seconds", positive=True)
    if duration is None or duration < 900 or not isinstance(timeline, dict):
        return None
    participants = match.get("participants")
    info = timeline.get("info")
    frames = info.get("frames") if isinstance(info, dict) else None
    metadata = timeline.get("metadata")
    timeline_puuids = metadata.get("participants") if isinstance(metadata, dict) else None
    if not isinstance(participants, list) or not isinstance(timeline_puuids, list) or not isinstance(frames, list):
        return None
    local = _local_stats(match)
    if not isinstance(local, dict) or local.get("team_id") is None:
        return None
    lane = _canonical_role(local.get("lane") or match.get("lane"))
    if lane is None:
        return None
    enemies = [row for row in participants if isinstance(row, dict) and row.get("team_id") is not None and row.get("team_id") != local["team_id"]]
    resolution = match.get("opponent_resolution") if isinstance(match.get("opponent_resolution"), dict) else {}
    opponent = match.get("opponent") if isinstance(match.get("opponent"), dict) else {}
    try:
        confidence = float(resolution.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    if confidence > 1:
        confidence /= 100
    opponent_id = resolution.get("champion_id") or opponent.get("champion_id") or match.get("opponent_champion_id")
    opponent_puuid = resolution.get("puuid") or opponent.get("puuid")
    resolved_enemies = [row for row in enemies
                        if (opponent_puuid and str(row.get("puuid") or "") == str(opponent_puuid))
                        or (opponent_id is not None and str(row.get("champion_id")) == str(opponent_id))]
    if confidence >= 0.75 and len(resolved_enemies) == 1:
        enemies = resolved_enemies
    else:
        enemies = [row for row in enemies if _canonical_role(row.get("lane")) == lane]
    if len(enemies) != 1:
        return None
    local_puuid, enemy_puuid = str(local.get("puuid") or ""), str(enemies[0].get("puuid") or "")
    # Riot timeline metadata orders PUUIDs by participantId (1-based), so this
    # remains reliable even when LCU's participant order differs from Match-V5.
    # Some legacy LCU rows have an unmatchable PUUID; participant_id is the
    # stable per-match fallback handled below.
    local_indexes = [index + 1 for index, puuid in enumerate(timeline_puuids) if local_puuid and str(puuid) == local_puuid]
    enemy_indexes = [index + 1 for index, puuid in enumerate(timeline_puuids) if enemy_puuid and str(puuid) == enemy_puuid]
    local_id = local_indexes[0] if len(local_indexes) == 1 else 0
    enemy_id = enemy_indexes[0] if len(enemy_indexes) == 1 else 0
    minute_15_frames = [row for row in frames if isinstance(row, dict)
                        and isinstance(row.get("timestamp"), (int, float))
                        and abs(float(row["timestamp"]) - 900_000) <= 30_000]
    frame = min(minute_15_frames, key=lambda row: abs(float(row["timestamp"]) - 900_000)) if minute_15_frames else None
    if not isinstance(frame, dict) or not isinstance(frame.get("participantFrames"), dict):
        return None
    participant_frames = frame["participantFrames"]
    def participant_frame_id(participant: dict[str, Any], puuid: str, mapped: int) -> str | None:
        if puuid and mapped:
            return str(mapped)
        # Older LCU cache records can have a different/obfuscated PUUID than
        # Match-V5 metadata. participantId is stable within a match and uses the
        # same 1..10 frame keys as Riot's timeline.
        value = participant.get("participant_id")
        return str(value) if isinstance(value, int) and 1 <= value <= 10 else None

    local_key = participant_frame_id(local, local_puuid, local_id)
    enemy_key = participant_frame_id(enemies[0], enemy_puuid, enemy_id)
    local_frame = participant_frames.get(local_key) if local_key else None
    enemy_frame = participant_frames.get(enemy_key) if enemy_key else None
    if not isinstance(local_frame, dict) or not isinstance(enemy_frame, dict):
        return None
    local_gold = _home_number(local_frame, "totalGold")
    enemy_gold = _home_number(enemy_frame, "totalGold")
    return round(local_gold - enemy_gold) if local_gold is not None and enemy_gold is not None else None


def _validated_performance_score(match: dict[str, Any]) -> float | None:
    points = match.get("battle_score")
    if (match.get("battle_score_verified") is True and isinstance(points, (int, float))
            and not isinstance(points, bool) and isfinite(points) and 0 <= points <= 10):
        return float(points)
    return None


def _champion_rows(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metadata = _local_champion_metadata()
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        if match.get("champion_id") is not None:
            buckets[str(match["champion_id"])].append(match)
    rows = []
    for key, group in buckets.items():
        wins = sum(match.get("result") == "victory" for match in group)
        kda, sample, zero_deaths = _aggregate_kda(group)
        score_values = [value for match in group if (value := _validated_performance_score(match)) is not None]
        rows.append({"champion_id": metadata.get(key, {}).get("id") or key, "name": metadata.get(key, {}).get("name") or group[0].get("champion_name") or key,
                     "matches": len(group), "wins": wins, "losses": len(group)-wins, "winrate": round(100*wins/len(group),1),
                     "kda": kda, "kda_sample": sample, "zero_deaths": zero_deaths,
                     "score": round(sum(score_values)/len(score_values),1) if score_values else None})
    return sorted(rows, key=lambda row: (-row["matches"], row["name"].casefold()))[:3]


def _archetype_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = _local_champion_metadata()
    weights: Counter[str] = Counter()
    tagged_matches = 0
    for match in matches:
        tags = metadata.get(str(match.get("champion_id") or ""), {}).get("tags", [])
        tags = [tag for tag in tags if tag in ARCHETYPE_LABELS]
        if tags:
            tagged_matches += 1
            for tag in tags:
                weights[tag] += 1 / len(tags)
    ordered = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
    return {"primary": ARCHETYPE_LABELS.get(ordered[0][0]) if ordered else None,
            "secondary": ARCHETYPE_LABELS.get(ordered[1][0]) if len(ordered)>1 else None,
            "sample": tagged_matches, "provisional": tagged_matches < 10,
            "method": "Cada partida se reparte por igual entre las etiquetas Data Dragon del campeón."}


def _counter_summary(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    metadata = _local_champion_metadata()
    encountered: dict[str, Counter[str]] = defaultdict(Counter)
    names: dict[str, str] = {}
    for match in matches:
        result = match.get("result")
        seen: set[str] = set()
        enemies = match.get("enemy_team")
        if not isinstance(enemies, list):
            continue
        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue
            key = str(enemy.get("champion_id") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            names[key] = str(enemy.get("champion_name") or metadata.get(key, {}).get("name") or key)
            if result in {"victory", "defeat"}:
                encountered[key][str(result)] += 1
    candidates = [(key, counts) for key, counts in encountered.items() if counts["defeat"]]
    if not candidates:
        return None
    key, counts = min(candidates, key=lambda item: (-item[1]["defeat"], -sum(item[1].values()), item[1]["victory"] / sum(item[1].values()) if sum(item[1].values()) else 1, item[0]))
    total = sum(counts.values())
    return {"champion_id": metadata.get(key, {}).get("id") or key, "name": names[key], "losses": counts["defeat"], "encounters": total, "wins": counts["victory"], "winrate": round(counts["victory"]*100/total,1) if total else None}


def _counter_solo_queue_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select deduplicated completed matches with authoritative queue ID 420.

    Counter history is read from the complete local repository, including old
    records. Do not infer SoloQ from mode text or match appearance: records
    without an explicit queue ID are ineligible. Filtering before deduplication
    also prevents a duplicate non-SoloQ record from shadowing an eligible row.
    """
    eligible = [
        match for match in matches
        if isinstance(match, dict)
        and str(match.get("queue_id") or "").strip() == "420"
        and match.get("result") in {"victory", "defeat"}
    ]
    return normalizar_partidas_unicas(eligible)


def build_home_counter_summary(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the SoloQ-only history-based counter shown on Home and Draft."""
    return _counter_summary(_counter_solo_queue_matches(matches))


def _activity_summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    hours: dict[int, Counter[str]] = defaultdict(Counter)
    weekdays: dict[int, Counter[str]] = defaultdict(Counter)
    for match in matches:
        value = match.get("started_at")
        if not value or match.get("result") not in {"victory", "defeat"}:
            continue
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
        except (TypeError, ValueError, OverflowError):
            continue
        outcome = str(match["result"])
        hours[dt.hour][outcome] += 1
        weekdays[dt.weekday()][outcome] += 1
    def rows(groups: dict[int, Counter[str]], labels: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        output = []
        for key, values in sorted(groups.items()):
            count = values["victory"] + values["defeat"]
            output.append({"key": key, "label": labels[key] if labels else f"{key:02d}:00", "matches": count, "wins": values["victory"], "winrate": round(100*values["victory"]/count,1) if count else None})
        return output
    hour_rows, day_rows = rows(hours), rows(weekdays, WEEKDAYS)
    busiest_hour = max(hour_rows, key=lambda row: (row["matches"], -row["key"])) if hour_rows else None
    busiest_day = max(day_rows, key=lambda row: (row["matches"], -row["key"])) if day_rows else None
    return {"assignment": "Hora local de inicio de partida; cada partida cuenta una vez.", "hours": hour_rows, "weekdays": day_rows, "busiest_hour": busiest_hour, "busiest_day": busiest_day}
