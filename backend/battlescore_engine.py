"""Versioned chronological BattleScore 2.7 scoring engine."""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from typing import Any

VERSION = "battlescore_v2_7"
SAMPLE_INTERVAL_MS = 10_000
DECAY_START_MS = 120_000
DECAY_PER_MINUTE = .14
PROTECTED_DECAY_PER_MINUTE = .085
PROTECTION_THRESHOLD = 2.0
RECOVERY_BANDS = ((3.0, 1.10), (4.0, 1.05), (None, 1.00))
MINIMUM_SCORE = .10
MAXIMUM_SCORE = 10.0
DIMINISHING_THRESHOLD = 10.0
DIMINISHING_MULTIPLIER = .50
SAME_ROLE_OPPONENT_CONTEXT_WEIGHT = .25
CONTEXT_DEVIATION_WEIGHT = .25
CONTEXT_MAX_DOWNSIDE_FRACTION = .50
PHASE_BOUNDS = ((0.0, 10.0, "early"), (10.0, 20.0, "middle"), (20.0, math.inf, "late"))
MAJOR_OBJECTIVES = {"DRAGON", "BARON_NASHOR", "RIFTHERALD", "HORDE"}

# Experimental starting configuration. Caps apply to base rewards before role
# multipliers; all monetary/damage/XP figures are per 1,000 units.
COEFFICIENTS = {
    # Calibrated globally against the reference match. The source coefficients
    # and role multipliers remain configurable; no champion-specific offsets.
    "gold_per_1000": .150, "kill": .156, "assist": .1633, "death": .270,
    "experience_per_1000": .014, "champion_damage_per_1000": .03255,
    "useful_damage_per_1000": .0186, "epic_monster_damage_per_1000": .00925,
    "epic_monster_damage_cap": .35, "structure_damage_per_1000": .00814,
    "structure_damage_cap": .35, "ward_placed": .0224, "ward_destroyed": .056,
    "vision_event_cap": .45, "final_vision_per_point": .01344, "final_vision_cap": .45,
    "major_objective_secure": .0407, "major_objective_participation": .0222,
    "tower_destroyed": .0296, "structure_participation": .01295,
    "turret_plate": .00814, "turret_plate_cap": .13,
    "allied_heal_shield_per_1000": .0264, "allied_heal_shield_cap": .25,
    "first_blood": .096, "shutdown": .084, "teamfight_participation": .042,
    "teamfight_cap": .18, "objective_steal": .0148, "objective_steal_cap": .12,
    "teamfight_window_ms": 15_000, "teamfight_min_kills": 2,
    "teamfight_min_participants": 4,
}
CALIBRATION_SOURCE_VERSION = "battlescore_v2_1"
CALIBRATION_FAMILY_MULTIPLIERS = {
    "kills": .39, "assists": .71, "economy": .70, "damage": .93,
    "objectives": .37, "vision": 1.12, "utility": 1.20,
}
ROLE_MULTIPLIERS = {
    "TOP": {"gold": .90, "kills": 1.05, "assists": .95, "death": 1.05, "experience": 1.05, "champion_damage": 1.00, "useful_damage": 1.35, "structure_damage": 1.50, "vision": .90, "allied_utility": .75, "objective_secure": 1.00},
    "JUNGLE": {"gold": .85, "kills": 1.00, "assists": .95, "death": 1.15, "experience": .85, "champion_damage": .90, "useful_damage": 1.10, "structure_damage": .85, "vision": 1.05, "allied_utility": .80, "objective_secure": .85},
    "MIDDLE": {"gold": 1.00, "kills": 1.15, "assists": 1.15, "death": 1.10, "experience": 1.10, "champion_damage": 1.10, "useful_damage": .75, "structure_damage": 1.00, "vision": .95, "allied_utility": .90, "objective_secure": 1.00},
    "BOTTOM": {"gold": .95, "kills": 1.10, "assists": 1.05, "death": 1.20, "experience": 1.10, "champion_damage": 1.20, "useful_damage": .50, "structure_damage": 1.25, "vision": .85, "allied_utility": .60, "objective_secure": 1.00},
    "UTILITY": {"gold": .70, "kills": .80, "assists": 1.20, "death": .90, "experience": .60, "champion_damage": .85, "useful_damage": 1.15, "structure_damage": .65, "vision": 1.25, "allied_utility": 1.45, "objective_secure": .90},
}
NEUTRAL_ROLE_MULTIPLIERS = {key: 1.0 for key in next(iter(ROLE_MULTIPLIERS.values()))}
ROLE_ALIASES = {
    "TOP": "TOP", "JUNG": "JUNGLE", "JUNGLE": "JUNGLE", "MID": "MIDDLE", "MIDDLE": "MIDDLE",
    "BOTTOM": "BOTTOM", "BOT": "BOTTOM", "ADC": "BOTTOM", "APC": "BOTTOM",
    "UTILITY": "UTILITY", "SUP": "UTILITY", "SUPPORT": "UTILITY",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def _positive(value: Any) -> float:
    return max(0.0, _number(value) or 0.0)


def _role_multipliers(role: Any, role_table: dict[str, dict[str, float]] | None = None,
                      neutral: dict[str, float] | None = None) -> tuple[str, dict[str, float]]:
    raw = str(role or "").strip().upper()
    normalized = ROLE_ALIASES.get(raw, "UNKNOWN")
    return normalized, (role_table or ROLE_MULTIPLIERS).get(normalized, neutral or NEUTRAL_ROLE_MULTIPLIERS)


def _phase(minutes: float, bounds: tuple[tuple[float, float, str], ...] = PHASE_BOUNDS) -> str:
    return next(name for start, end, name in bounds if start <= minutes < end)


def _metric(frame: dict[str, Any], name: str) -> float | None:
    key = {"gold": "gold", "experience": "xp", "champion_damage": "championDamageDealt"}[name]
    value = _number(frame.get(key))
    return max(0.0, value) if value is not None else None


def _reference_rate(baselines: dict[str, Any] | None, role: str, phase: str, metric: str) -> float | None:
    try:
        row = baselines["metrics"][role][phase][metric]
        rate = _number(row.get("medianPerMinute")) if row.get("available") else None
        return max(0.0, rate) if rate is not None else None
    except (KeyError, TypeError):
        return None


def telemetry_fingerprint(participants: list[dict[str, Any]], events: list[dict[str, Any]],
                          frames: list[dict[str, Any]], duration_seconds: float,
                          calibration_baselines: dict[str, Any] | None = None,
                          configuration: dict[str, Any] | None = None) -> str:
    from backend.analysis_settings import engine_snapshot
    config = engine_snapshot(configuration)
    payload = {
        "version": VERSION, "duration": float(duration_seconds), "configuration_hash": config["configuration_hash"],
        "coefficients": config["coefficients"],
    "decay_config": {"starts_at_ms": DECAY_START_MS, "per_minute": DECAY_PER_MINUTE,
                         "protected_per_minute": PROTECTED_DECAY_PER_MINUTE,
                         "protection_threshold": PROTECTION_THRESHOLD},
        "recovery_bands": RECOVERY_BANDS, "minimum_score": MINIMUM_SCORE, "maximum_score": MAXIMUM_SCORE,
        "diminishing": {"threshold": DIMINISHING_THRESHOLD, "multiplier": DIMINISHING_MULTIPLIER},
        "same_role_opponent_context_weight": SAME_ROLE_OPPONENT_CONTEXT_WEIGHT,
        "context_deviation_weight": CONTEXT_DEVIATION_WEIGHT,
        "context_max_downside_fraction": CONTEXT_MAX_DOWNSIDE_FRACTION,
        "roles": ROLE_MULTIPLIERS, "calibration": calibration_baselines or {"confidence": "fallback_linear"},
        "participants": [{key: p.get(key) for key in ("participantId", "role", "teamId", "championId", "championDamageDealt", "damageToEpicMonsters", "damageToBuildings", "damageToTurrets", "vision", "wardsPlaced", "wardsKilled", "totalHealsOnTeammates", "totalDamageShieldedOnTeammates", "objectivesStolen")} for p in participants],
        "events": [{key: e.get(key) for key in ("id", "timestamp", "type", "killerId", "victimId", "assistingIds", "participantId", "monsterType", "monsterSubType", "buildingType", "championDamageReceivedObserved", "championDamageReceivedDelta", "killParticipationAtEvent", "shutdownBounty")} for e in events],
        "frames": [{key: f.get(key) for key in ("timestamp", "participantId", "gold", "xp", "championDamageDealt")} for f in frames],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def apply_decay(score: float, elapsed_minutes: float, configuration: dict[str, Any] | None = None) -> float:
    """Apply -0.14 above 2, then -0.085 below 2, with a 0.10 floor."""
    from backend.analysis_settings import engine_snapshot
    config = engine_snapshot(configuration)
    minimum = config["general"]["minimum_score"]
    maximum = config["general"]["maximum_score"]
    threshold = config["decay"]["low_score_threshold"]
    ordinary_rate = config["decay"]["normal_per_minute"]
    protected_rate = config["decay"]["below_threshold_per_minute"]
    elapsed = max(0.0, elapsed_minutes)
    if score <= minimum or elapsed <= 0:
        return min(maximum, max(minimum, score))
    ordinary = min(elapsed, max(0.0, score - threshold) / ordinary_rate) if ordinary_rate > 0 else elapsed
    score -= ordinary * ordinary_rate
    elapsed -= ordinary
    return min(maximum, max(minimum, score - elapsed * protected_rate))


def _apply_reward_details(score: float, points: float, configuration: dict[str, Any] | None = None) -> tuple[float, float, float, float]:
    """Return score, recovery bonus, high-score adjustment, and upper-cap loss."""
    from backend.analysis_settings import engine_snapshot
    config = engine_snapshot(configuration)
    minimum = config["general"]["minimum_score"]
    maximum = config["general"]["maximum_score"]
    threshold = config["compression"]["threshold"]
    compression = config["compression"]["multiplier"]
    recovery_bands = ((config["recovery"]["below_3_threshold"], 1.0 + config["recovery"]["below_3_bonus"]),
                      (config["recovery"]["below_4_threshold"], 1.0 + config["recovery"]["below_4_bonus"]), (None, 1.0))
    remaining, recovery_bonus, diminishing_adjustment, cap_adjustment = max(0.0, points), 0.0, 0.0, 0.0
    score = min(maximum, max(minimum, score))
    while remaining > 1e-12:
        if score >= maximum:
            cap_adjustment -= remaining
            break
        recovery, boundary = next((mult, limit) for limit, mult in recovery_bands if limit is None or score < limit)
        next_boundary = boundary if boundary is not None else math.inf
        if score < threshold:
            next_boundary = min(next_boundary, threshold, maximum)
        diminishing = compression if score >= threshold else 1.0
        gain_rate = recovery * diminishing
        piece = min(remaining, (next_boundary - score) / gain_rate if math.isfinite(next_boundary) else math.inf)
        if piece <= 1e-12:
            score = next_boundary
            continue
        adjusted = piece * recovery
        gain = adjusted * diminishing
        recovery_bonus += piece * (recovery - 1.0)
        diminishing_adjustment += adjusted * (diminishing - 1.0)
        actual_gain = min(gain, maximum - score)
        cap_adjustment -= gain - actual_gain
        score += actual_gain
        remaining -= piece
    return min(maximum, max(minimum, score)), recovery_bonus, diminishing_adjustment, cap_adjustment


def apply_reward_with_adjustments(score: float, points: float, configuration: dict[str, Any] | None = None) -> tuple[float, float, float]:
    """Apply recovery and diminishing returns, retaining the prior API shape."""
    score, recovery, diminishing, cap = _apply_reward_details(score, points, configuration)
    return score, recovery, diminishing + cap


def apply_reward(score: float, points: float, configuration: dict[str, Any] | None = None) -> float:
    return _apply_reward_details(score, points, configuration)[0]


def apply_penalty(score: float, points: float, configuration: dict[str, Any] | None = None) -> float:
    from backend.analysis_settings import engine_snapshot
    config = engine_snapshot(configuration)
    return min(config["general"]["maximum_score"], max(config["general"]["minimum_score"], score - max(0.0, points)))


def _event_key(event: dict[str, Any], _index: int) -> tuple[Any, ...]:
    if event.get("id") is not None:
        return ("id", str(event["id"]))
    return ("fields", event.get("timestamp"), event.get("type"), event.get("killerId"), event.get("victimId"),
            tuple(event.get("assistingIds") or ()), event.get("participantId"), event.get("monsterType"),
            event.get("monsterSubType"), event.get("buildingType"), event.get("laneType"), event.get("wardType"))


TIMELINE_EVENT_CATEGORIES = {
    "kills", "death", "assists", "first_blood", "shutdown", "teamfight",
    "objective_secure", "objective_participation", "objective_steal", "tower",
    "structure_participation", "turret_plate",
}


def timeline_expressiveness(series: list[dict[str, Any]], event_markers: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize actual score movement; this diagnostic never changes the score."""
    values = [_number(point.get("score")) for point in series if isinstance(point, dict)]
    values = [value for value in values if value is not None]
    steps = [right - left for left, right in zip(values, values[1:])]
    significant_threshold = 0.05
    upward = sum(max(0.0, step) for step in steps)
    downward = sum(max(0.0, -step) for step in steps)
    marker_steps = [float(marker.get("scoreDelta") or 0.0) for marker in event_markers]
    meaningful_marker_steps = [step for step in marker_steps if abs(step) > 1e-12]
    turns = sum(1 for left, right in zip(meaningful_marker_steps, meaningful_marker_steps[1:]) if left * right < 0)
    mean = sum(values) / len(values) if values else 0.0
    variance = sum((value - mean) ** 2 for value in values) / len(values) if values else 0.0
    return {
        "upwardMovement": upward,
        "downwardMovement": downward,
        "largestUpwardStep": max((step for step in steps if step > 0), default=0.0),
        "largestDownwardStep": min((step for step in steps if step < 0), default=0.0),
        "significantPositiveSpikes": sum(step >= significant_threshold for step in steps),
        "significantNegativeDrops": sum(step <= -significant_threshold for step in steps),
        "significantStepThreshold": significant_threshold,
        "scoreRange": max(values) - min(values) if values else 0.0,
        "standardDeviation": math.sqrt(variance),
        "eventLinkedTurningPoints": turns,
        "eventLinkedPositiveMoves": sum(step > 0 for step in marker_steps),
        "eventLinkedNegativeMoves": sum(step < 0 for step in marker_steps),
        "eventLinkedMarkers": len(event_markers),
        "smoothingStrengthApplied": 0.0,
        "movementSource": "serie cronológica puntuada sin suavizado visual",
    }


def calculate_match(match_id: str, participants: list[dict[str, Any]], events: list[dict[str, Any]],
                    frames: list[dict[str, Any]], duration_seconds: float,
                    calibration_baselines: dict[str, Any] | None = None,
                    configuration: dict[str, Any] | None = None) -> dict[str, Any]:
    from backend.analysis_settings import engine_snapshot
    config = engine_snapshot(configuration)
    coefficients = config["coefficients"]
    enabled_components = config["enabled_components"]
    role_table = config["role_multipliers"]
    neutral_multipliers = config["neutral_role_multipliers"]
    minimum_score = config["general"]["minimum_score"]
    maximum_score = config["general"]["maximum_score"]
    initial_score = config["general"]["initial_score"]
    # Canonical score reconstruction stays independent from chart settings.
    sample_interval = SAMPLE_INTERVAL_MS
    decay_start = int(config["decay"]["grace_period_seconds"] * 1000)
    decay_config = config
    phase_limits = config["normalization"]["phase_bounds_minutes"]
    phase_bounds = ((0.0, float(phase_limits[0]), "early"),
                    (float(phase_limits[0]), float(phase_limits[1]), "middle"),
                    (float(phase_limits[1]), math.inf, "late"))
    same_role_opponent_weight = config["normalization"]["same_role_opponent_weight"]
    deviation_weight = config["normalization"]["deviation_weight"]
    downside_fraction = config["normalization"]["max_downside_fraction"]

    def enabled(name: str) -> bool:
        return bool(enabled_components.get(name, True))

    duration = _number(duration_seconds)
    if not match_id or duration is None or duration <= 0 or not participants or (not events and not frames):
        return {"version": VERSION, "state": "unavailable", "matchId": match_id, "participants": []}
    duration_ms = duration * 1000.0
    pids = {int(p["participantId"]) for p in participants if _number(p.get("participantId")) is not None}
    if not pids:
        return {"version": VERSION, "state": "unavailable", "matchId": match_id, "participants": []}
    players = {int(p["participantId"]): p for p in participants if _number(p.get("participantId")) is not None}
    roles = {pid: _role_multipliers(p.get("role"), role_table, neutral_multipliers) for pid, p in players.items()}
    teams = {pid: p.get("teamId") for pid, p in players.items()}
    rewards: dict[int, list[tuple[int, int, str, float]]] = defaultdict(list)
    observations: dict[int, set[int]] = defaultdict(set)
    component_available: dict[int, dict[str, str]] = defaultdict(dict)
    context_used: dict[int, set[str]] = defaultdict(set)
    distributed: dict[int, list[str]] = defaultdict(list)
    context_adjustment: dict[int, float] = defaultdict(float)

    def add_estimated_final_allocation(pid: int, category: str, points: float, tag: str) -> None:
        """Allocate reliable final-only totals over time as an explicit estimate.

        This is a modeled scoring allocation, not a claim that Riot timestamped
        the underlying actions. It avoids an artificial end-of-match impulse.
        """
        amount = max(0.0, float(points))
        end_ms = max(0, int(duration_ms))
        if amount <= 0.0:
            return
        if end_ms == 0:
            rewards[pid].append((0, 10, category, amount))
        else:
            boundaries = list(range(sample_interval, end_ms, sample_interval))
            boundaries.append(end_ms)
            previous_boundary = 0
            allocated = 0.0
            for index, timestamp in enumerate(boundaries):
                portion = (amount - allocated if index == len(boundaries) - 1
                           else amount * (timestamp - previous_boundary) / end_ms)
                if portion > 0.0:
                    rewards[pid].append((timestamp, 10, category, portion))
                    allocated += portion
                previous_boundary = timestamp
        distributed[pid].append(f"{tag}_final_only_estimated_linear")

    # Timeline cumulative deltas for gold, XP and champion damage.
    # Their first samples are baselines; only subsequent positive increments
    # earn rewards. Keep base and contextual portions distinct for audits.
    context_adjustment_by_metric: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    role_adjusted_base_by_metric: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    frame_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        pid_value, time_value = _number(frame.get("participantId")), _number(frame.get("timestamp"))
        if pid_value is None or time_value is None:
            continue
        pid, timestamp = int(pid_value), int(time_value)
        if pid in pids and 0 <= timestamp <= duration_ms:
            frame_by_key[(pid, timestamp)] = frame
            observations[pid].add(timestamp)
    frame_rows: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for (pid, timestamp), frame in frame_by_key.items():
        frame_rows[pid].append((timestamp, frame))
    deltas: dict[tuple[str, int, int], tuple[float, float, str]] = {}
    observed_metrics: dict[int, set[str]] = defaultdict(set)
    for pid, rows in frame_rows.items():
        rows.sort(key=lambda row: row[0])
        previous: dict[str, tuple[float, int]] = {}
        for timestamp, frame in rows:
            for metric in ("gold", "experience", "champion_damage"):
                value = _metric(frame, metric)
                if value is None:
                    continue
                observed_metrics[pid].add(metric)
                if metric not in previous:
                    previous[metric] = (value, timestamp)  # First sample is baseline.
                    continue
                old_value, old_timestamp = previous[metric]
                elapsed = (timestamp - old_timestamp) / 60_000.0
                previous[metric] = (max(old_value, value), timestamp)
                if elapsed > 0:
                    phase = _phase(((timestamp + old_timestamp) / 2.0) / 60_000.0, phase_bounds)
                    deltas[(metric, pid, timestamp)] = (max(0.0, value - old_value), elapsed, phase)

    for (metric, pid, timestamp), (amount, elapsed, phase) in sorted(deltas.items(), key=lambda row: (row[0][2], row[0][1], row[0][0])):
        role, mult = roles.get(pid, ("UNKNOWN", neutral_multipliers))
        coefficient_key = {"gold": "gold_per_1000", "experience": "experience_per_1000", "champion_damage": "champion_damage_per_1000"}[metric]
        enabled_key = {"gold": "gold", "experience": "experience", "champion_damage": "champion_damage"}[metric]
        if not enabled(enabled_key):
            continue
        base_points = amount / 1000.0 * coefficients[coefficient_key]
        expected_rate = _reference_rate(calibration_baselines, role, phase, metric)
        opponent = next((other for other in pids if other != pid and teams.get(other) not in (None, teams.get(pid)) and roles.get(other, ("UNKNOWN",))[0] == role), None)
        opponent_delta = deltas.get((metric, opponent, timestamp)) if opponent is not None else None
        if opponent_delta and opponent_delta[1] > 0:
            # A mirrored opponent is useful context, but using the better of
            # the two players as a hard floor systematically debits the other
            # player. Blend the measured opponent rate into the local median
            # so the comparison informs, rather than dominates, normalization.
            opponent_rate = opponent_delta[0] / opponent_delta[1]
            if expected_rate is not None:
                expected_rate += same_role_opponent_weight * (opponent_rate - expected_rate)
                context_used[pid].add("same_role_opponent")
        elif expected_rate is not None:
            context_used[pid].add("role_phase_median")
        role_key = {"gold": "gold", "experience": "experience", "champion_damage": "champion_damage"}[metric]
        role_adjusted_base = base_points * mult[role_key]
        role_adjusted_base_by_metric[pid][metric] += role_adjusted_base
        adjusted = role_adjusted_base
        if expected_rate is not None and elapsed <= 3.0:
            deviation = (amount / elapsed - expected_rate) * elapsed / 1000.0
            contextual_delta = deviation * coefficients[coefficient_key] * mult[role_key] * deviation_weight
            contextual_delta = max(-role_adjusted_base * downside_fraction,
                                   min(role_adjusted_base, contextual_delta))
            adjusted += contextual_delta
            context_adjustment[pid] += contextual_delta
            context_adjustment_by_metric[pid][metric] += contextual_delta
        if adjusted:
            rewards[pid].append((timestamp, {"gold": 0, "experience": 3, "champion_damage": 4}[metric], role_key, adjusted))

    # Riot events are deduplicated and retain their exact event timestamps.
    unique_events: list[tuple[int, str, dict[str, Any]]] = []
    seen: set[tuple[Any, ...]] = set()
    for index, event in enumerate(events):
        if not isinstance(event, dict) or (key := _event_key(event, index)) in seen:
            continue
        seen.add(key)
        ts = _number(event.get("timestamp"))
        if ts is not None and 0 <= ts <= duration_ms:
            unique_events.append((int(ts), str(event.get("id") or f"{index:08d}"), event))
    unique_events.sort(key=lambda row: (row[0], row[1]))
    placed: dict[int, int] = defaultdict(int)
    ward_kills: dict[int, int] = defaultdict(int)
    plates: dict[int, int] = defaultdict(int)
    useful_damage: dict[int, float] = defaultdict(float)
    useful_observed: set[int] = set()
    ward_rewards: dict[int, list[tuple[int, int, str, float]]] = defaultdict(list)
    kill_rows: list[tuple[int, str, dict[str, Any]]] = []
    first_blood = False
    objective_steal_awarded: dict[int, float] = defaultdict(float)
    objective_steal_event_count: dict[int, int] = defaultdict(int)
    for timestamp, eid, event in unique_events:
        for pid in [*event.get("participantIds", []), event.get("killerId"), event.get("victimId"), event.get("participantId"), *event.get("assistingIds", [])]:
            if isinstance(pid, int) and pid in pids:
                observations[pid].add(timestamp)
        kind = str(event.get("type") or "").upper()
        if kind == "CHAMPION_KILL":
            kill_rows.append((timestamp, eid, event))
            killer, victim = event.get("killerId"), event.get("victimId")
            is_first = not first_blood
            first_blood = True
            if enabled("death") and isinstance(victim, int) and victim in pids:
                death_mult = roles.get(victim, ("UNKNOWN", neutral_multipliers))[1]["death"]
                rewards[victim].append((timestamp, 0, f"death:{eid}", -coefficients["death"] * death_mult))
            if isinstance(killer, int) and killer in pids:
                mult = roles.get(killer, ("UNKNOWN", neutral_multipliers))[1]
                if enabled("kills"):
                    rewards[killer].append((timestamp, 1, f"kills:{eid}", coefficients["kill"] * mult["kills"]))
                if is_first and enabled("first_blood"):
                    rewards[killer].append((timestamp, 1, f"first_blood:{eid}", coefficients["first_blood"]))
                if _positive(event.get("shutdownBounty")) > 0 and enabled("shutdown"):
                    rewards[killer].append((timestamp, 1, f"shutdown:{eid}", coefficients["shutdown"]))
            if isinstance(victim, int) and victim in pids:
                delta = _positive(event.get("championDamageReceivedDelta"))
                if event.get("championDamageReceivedObserved"):
                    useful_observed.add(victim)
                kp = _number(event.get("killParticipationAtEvent"))
                useful_increment = delta * (min(1.0, max(0.0, kp)) if kp is not None else 0.0)
                useful_damage[victim] += useful_increment
                if useful_increment and enabled("useful_damage"):
                    mult = roles.get(victim, ("UNKNOWN", neutral_multipliers))[1]
                    rewards[victim].append((timestamp, 4, f"useful_damage:{eid}", useful_increment / 1000.0 * coefficients["useful_damage_per_1000"] * mult["useful_damage"]))
            for pid in sorted({x for x in event.get("assistingIds", []) if isinstance(x, int) and x in pids}):
                mult = roles.get(pid, ("UNKNOWN", neutral_multipliers))[1]
                if enabled("assists"):
                    rewards[pid].append((timestamp, 2, f"assists:{eid}", coefficients["assist"] * mult["assists"]))
        elif kind == "ELITE_MONSTER_KILL":
            monster = str(event.get("monsterType") or "").upper()
            killer = event.get("killerId")
            if monster in MAJOR_OBJECTIVES and isinstance(killer, int) and killer in pids:
                mult = roles.get(killer, ("UNKNOWN", neutral_multipliers))[1]
                if enabled("objective_secure"):
                    rewards[killer].append((timestamp, 5, f"objective_secure:{eid}", coefficients["major_objective_secure"] * mult["objective_secure"]))
                if str(event.get("monsterSubType") or "").upper() in {"STEAL", "STOLEN"} and enabled("objective_steal"):
                    amount = min(coefficients["objective_steal"], max(0.0, coefficients["objective_steal_cap"] - objective_steal_awarded[killer]))
                    if amount:
                        rewards[killer].append((timestamp, 5, f"objective_steal:{eid}", amount))
                        objective_steal_awarded[killer] += amount
                        objective_steal_event_count[killer] += 1
            if monster in MAJOR_OBJECTIVES and enabled("objective_participation"):
                for pid in sorted({x for x in event.get("assistingIds", []) if isinstance(x, int) and x in pids and x != killer}):
                    rewards[pid].append((timestamp, 5, f"objective_participation:{eid}", coefficients["major_objective_participation"]))
        elif kind == "BUILDING_KILL":
            building, killer = str(event.get("buildingType") or "").upper(), event.get("killerId")
            if "TOWER" in building and isinstance(killer, int) and killer in pids and enabled("tower"):
                rewards[killer].append((timestamp, 6, f"tower:{eid}", coefficients["tower_destroyed"]))
            if "TOWER" in building and enabled("structure_participation"):
                for pid in sorted({x for x in event.get("assistingIds", []) if isinstance(x, int) and x in pids and x != killer}):
                    rewards[pid].append((timestamp, 6, f"structure_participation:{eid}", coefficients["structure_participation"]))
        elif kind == "TURRET_PLATE_DESTROYED":
            pid = event.get("killerId", event.get("participantId"))
            if isinstance(pid, int) and pid in pids and enabled("turret_plate"):
                plates[pid] += 1
                before = min(coefficients["turret_plate_cap"], (plates[pid] - 1) * coefficients["turret_plate"])
                amount = min(coefficients["turret_plate"], max(0.0, coefficients["turret_plate_cap"] - before))
                if amount:
                    rewards[pid].append((timestamp, 6, f"turret_plate:{eid}", amount))
        elif kind in {"WARD_PLACED", "WARD_KILL"}:
            pid = event.get("participantId") if kind == "WARD_PLACED" else event.get("killerId")
            if isinstance(pid, int) and pid in pids and enabled("vision"):
                if kind == "WARD_PLACED":
                    placed[pid] += 1
                    base_before = (placed[pid] - 1) * coefficients["ward_placed"] + ward_kills[pid] * coefficients["ward_destroyed"]
                    coefficient, category = coefficients["ward_placed"], "vision"
                else:
                    ward_kills[pid] += 1
                    base_before = placed[pid] * coefficients["ward_placed"] + (ward_kills[pid] - 1) * coefficients["ward_destroyed"]
                    coefficient, category = coefficients["ward_destroyed"], "vision"
                amount = min(coefficient, max(0.0, coefficients["vision_event_cap"] - base_before))
                mult = roles.get(pid, ("UNKNOWN", neutral_multipliers))[1]
                if amount:
                    ward_rewards[pid].append((timestamp, 7, f"{category}:{eid}", amount * mult["vision"]))

    # Verified fight groups: at least two champion kills in 15s and four distinct
    # participants. Each participant is rewarded once per group, capped per match.
    groups: list[tuple[int, str, dict[str, Any]]] = []
    def add_fight(rows: list[tuple[int, str, dict[str, Any]]]) -> None:
        if not enabled("teamfight_participation") or len(rows) < coefficients["teamfight_min_kills"]:
            return
        involved = {pid for _t, _eid, event in rows for pid in (event.get("killerId"), event.get("victimId"), *(event.get("assistingIds") or [])) if isinstance(pid, int) and pid in pids}
        if len(involved) < coefficients["teamfight_min_participants"]:
            return
        for pid in involved:
            already = sum(points for _t, _priority, category, points in rewards[pid] if category.startswith("teamfight:"))
            points = min(coefficients["teamfight_participation"], max(0.0, coefficients["teamfight_cap"] - already))
            if points:
                rewards[pid].append((rows[-1][0], 3, f"teamfight:{rows[0][1]}:{pid}", points))
    for row in kill_rows:
        if groups and row[0] - groups[-1][0] > coefficients["teamfight_window_ms"]:
            add_fight(groups)
            groups = []
        groups.append(row)
    if groups:
        add_fight(groups)

    # Only use category-specific final Match-V5 fields. Final-only totals are
    # modeled as estimated linear allocations to avoid a terminal score spike;
    # they are separately labeled and are never presented as observed events.
    final_only_damage: dict[int, float] = {}
    for pid, participant in players.items():
        role, mult = roles.get(pid, ("UNKNOWN", neutral_multipliers))
        if enabled("champion_damage") and "champion_damage" not in observed_metrics[pid]:
            value = _number(participant.get("championDamageDealt"))
            if value is not None:
                final_only_damage[pid] = max(0.0, value)
        epic = _number(participant.get("damageToEpicMonsters"))
        if epic is not None and enabled("objective_damage"):
            amount = min(coefficients["epic_monster_damage_cap"], max(0.0, epic) / 1000.0 * coefficients["epic_monster_damage_per_1000"])
            if amount:
                add_estimated_final_allocation(pid, "objective_damage", amount, "epic_damage")
        structure = _number(participant.get("damageToBuildings"))
        if structure is None:
            structure = _number(participant.get("damageToTurrets"))
        if structure is not None and enabled("structure_damage"):
            amount = min(coefficients["structure_damage_cap"], max(0.0, structure) / 1000.0 * coefficients["structure_damage_per_1000"])
            if amount:
                add_estimated_final_allocation(pid, "structure_damage", amount * mult["structure_damage"], "structure_damage")
        final_vision = _number(participant.get("vision"))
        history_complete = (_number(participant.get("wardsPlaced")) is not None and _number(participant.get("wardsKilled")) is not None
                            and placed[pid] >= _positive(participant.get("wardsPlaced")) and ward_kills[pid] >= _positive(participant.get("wardsKilled")))
        if not enabled("vision"):
            pass
        elif history_complete:
            rewards[pid].extend(ward_rewards.get(pid, []))
        elif final_vision is not None:
            amount = min(coefficients["final_vision_cap"], max(0.0, final_vision) * coefficients["final_vision_per_point"]) * mult["vision"]
            if amount:
                add_estimated_final_allocation(pid, "vision", amount, "vision")
        else:
            rewards[pid].extend(ward_rewards.get(pid, []))
        heals = _number(participant.get("totalHealsOnTeammates")) or 0.0
        shields = _number(participant.get("totalDamageShieldedOnTeammates")) or 0.0
        if enabled("allied_heal_shield") and (participant.get("totalHealsOnTeammates") is not None or participant.get("totalDamageShieldedOnTeammates") is not None):
            amount = min(coefficients["allied_heal_shield_cap"], max(0.0, heals + shields) / 1000.0 * coefficients["allied_heal_shield_per_1000"]) * mult["allied_utility"]
            if amount:
                add_estimated_final_allocation(pid, "allied_heal_shield", amount, "healing_shielding")
            elif participant.get("totalHealsOnTeammates") is not None or participant.get("totalDamageShieldedOnTeammates") is not None:
                distributed[pid].append("healing_shielding_final_only_zero_reward")
        steals = _number(participant.get("objectivesStolen"))
        if enabled("objective_steal") and steals is not None and steals > objective_steal_event_count[pid]:
            unobserved_steals = max(0.0, steals - objective_steal_event_count[pid])
            amount = min(max(0.0, coefficients["objective_steal_cap"] - objective_steal_awarded[pid]),
                         unobserved_steals * coefficients["objective_steal"])
            add_estimated_final_allocation(pid, "objective_steal", amount, "objective_steals")

    # Final-only champion-damage comparison uses the higher of a role/phase
    # expectation and verified same-role enemy total. The reward is one end event.
    for pid, total_damage in (final_only_damage.items() if enabled("champion_damage") else []):
        role, mult = roles.get(pid, ("UNKNOWN", neutral_multipliers))
        expected, have_reference = 0.0, False
        for start, end, phase in phase_bounds:
            phase_minutes = max(0.0, min(duration / 60.0, end) - start)
            rate = _reference_rate(calibration_baselines, role, phase, "champion_damage")
            if rate is not None:
                expected += rate * phase_minutes
                have_reference = True
        opponent = next((other for other in pids if other != pid and teams.get(other) not in (None, teams.get(pid)) and roles.get(other, ("UNKNOWN",))[0] == role), None)
        opponent_damage = _number(players.get(opponent, {}).get("championDamageDealt")) if opponent is not None else None
        if opponent_damage is not None and have_reference:
            expected = expected + same_role_opponent_weight * (max(0.0, opponent_damage) - expected)
            context_used[pid].add("same_role_opponent_final")
        elif have_reference:
            context_used[pid].add("role_phase_median")
        raw_points = total_damage / 1000.0 * coefficients["champion_damage_per_1000"] * mult["champion_damage"]
        base_points = raw_points
        if have_reference:
            contextual_delta = ((total_damage - expected) / 1000.0 * coefficients["champion_damage_per_1000"]
                                * mult["champion_damage"] * deviation_weight)
            contextual_delta = max(-raw_points * downside_fraction,
                                   min(raw_points, contextual_delta))
            base_points += contextual_delta
            context_adjustment[pid] += contextual_delta
        if base_points:
            add_estimated_final_allocation(pid, "champion_damage", base_points, "champion_damage")

    rows_out = []
    for participant in participants:
        pid_value = _number(participant.get("participantId"))
        if pid_value is None:
            continue
        pid = int(pid_value)
        if not observations.get(pid) and not rewards.get(pid):
            rows_out.append({"participantId": pid, "championId": participant.get("championId"), "champion": participant.get("champion"), "state": "unavailable", "unavailableReason": "No hay telemetría utilizable para este participante."})
            continue
        score, previous_time = initial_score, 0
        series = [{"timestamp": 0, "score": score}]
        event_markers: list[dict[str, Any]] = []
        breakdown: dict[str, float] = defaultdict(float)
        floor_adjustment = diminishing_adjustment = maximum_cap_adjustment = 0.0
        by_time: dict[int, list[tuple[int, str, float]]] = defaultdict(list)
        for timestamp, priority, category, points in rewards.get(pid, []):
            if 0 <= timestamp <= duration_ms:
                by_time[timestamp].append((priority, category, points))
                observations[pid].add(timestamp)
        timestamps = set(range(sample_interval, int(duration_ms), sample_interval)) | {int(duration_ms)} | observations.get(pid, set())
        for timestamp in sorted(t for t in timestamps if 0 <= t <= duration_ms):
            before_decay = score
            grace_minutes = max(0, min(timestamp, decay_start) - previous_time) / 60_000.0
            if grace_minutes and config["decay"]["grace_per_minute"]:
                score = max(minimum_score, score - grace_minutes * config["decay"]["grace_per_minute"])
            decay_minutes = max(0, timestamp - max(previous_time, decay_start)) / 60_000.0
            score = apply_decay(score, decay_minutes, config)
            breakdown["time_decay"] += score - before_decay
            actions = sorted(by_time.get(timestamp, []), key=lambda row: (row[0], row[1]))
            if actions:
                series.append({"timestamp": timestamp, "score": score})
            for _priority, category, points in actions:
                before = score
                if points < 0:
                    score = apply_penalty(score, -points, config)
                    key = "death_penalties" if category.startswith("death:") else category.split(":", 1)[0]
                    breakdown[key] += points
                    floor_adjustment += (score - before) - points
                else:
                    score, recovery, diminishing, cap_adjustment = _apply_reward_details(score, points, config)
                    breakdown["recovery_adjustment"] += recovery
                    diminishing_adjustment += diminishing
                    maximum_cap_adjustment += cap_adjustment
                    component = category.split(":", 1)[0]
                    component = {"teamfight": "teamfight_participation"}.get(component, component)
                    breakdown[component] += points
                event_category, separator, event_id = category.partition(":")
                if event_category in TIMELINE_EVENT_CATEGORIES:
                    realized_delta = score - before
                    series.append({"timestamp": timestamp, "score": score})
                    event_markers.append({"timestamp": timestamp, "category": event_category,
                                          "eventId": event_id if separator else None,
                                          "scoreDelta": realized_delta})
            if (timestamp > 0 or actions) and (not series or series[-1]["timestamp"] != timestamp or series[-1]["score"] != score):
                series.append({"timestamp": timestamp, "score": score})
            previous_time = timestamp
        score = min(maximum_score, max(minimum_score, score))
        components = ("gold", "kills", "assists", "death_penalties", "experience", "champion_damage", "useful_damage", "objective_damage", "structure_damage", "vision", "allied_heal_shield", "objective_secure", "objective_participation", "objective_steal", "tower", "structure_participation", "turret_plate", "first_blood", "shutdown", "teamfight_participation", "recovery_adjustment")
        for component in components:
            breakdown.setdefault(component, 0.0)
        breakdown.update({"contextual_adjustment": context_adjustment.get(pid, 0.0), "initial_score": initial_score,
                          "diminishing_adjustment": diminishing_adjustment,
                          "maximum_cap_adjustment": maximum_cap_adjustment,
                          "floor_adjustment": floor_adjustment,
                          "final_score": score})
        role = roles.get(pid, ("UNKNOWN",))[0]
        ref_metrics = (calibration_baselines or {}).get("metrics", {}).get(role, {})
        ref_count = max((metric.get("matches", 0) for phase in ref_metrics.values() for metric in phase.values()), default=0)
        availability = {
            "gold": "partial" if "gold" in observed_metrics[pid] else "unavailable",
            "experience": "partial" if "experience" in observed_metrics[pid] else "unavailable",
            "champion_damage": "partial" if "champion_damage" in observed_metrics[pid] or participant.get("championDamageDealt") is not None else "unavailable",
            "useful_damage": "partial" if pid in useful_observed else "unavailable",
            "objective_damage": "partial" if participant.get("damageToEpicMonsters") is not None else "unavailable",
            "structure_damage": "partial" if participant.get("damageToBuildings") is not None or participant.get("damageToTurrets") is not None else "unavailable",
            "vision": "partial" if participant.get("vision") is not None or placed[pid] or ward_kills[pid] else "unavailable",
            "allied_heal_shield": "partial" if participant.get("totalHealsOnTeammates") is not None or participant.get("totalDamageShieldedOnTeammates") is not None else "unavailable",
            "turret_plate": "partial" if plates[pid] else "unavailable",
        }
        reconciled = (initial_score + breakdown["time_decay"] + sum(
            breakdown[name] for name in components if name not in {"recovery_adjustment"}
        ) + breakdown["recovery_adjustment"] + diminishing_adjustment + maximum_cap_adjustment + floor_adjustment)
        missing_metrics = sorted(name for name, state in availability.items() if state == "unavailable")
        audit = {
            "version": VERSION,
            "startingScore": initial_score,
            "decay": breakdown["time_decay"],
            "deathPenalties": breakdown["death_penalties"],
            "componentTotals": {name: breakdown[name] for name in components},
            "contextualAdjustmentDiagnostic": context_adjustment.get(pid, 0.0),
            "contextualAdjustmentByMetric": dict(context_adjustment_by_metric.get(pid, {})),
            "roleAdjustedBaseByMetric": dict(role_adjusted_base_by_metric.get(pid, {})),
            "recoveryBonusRealized": breakdown["recovery_adjustment"],
            "above10CompressionAdjustment": diminishing_adjustment,
            "maximumScoreCapAdjustment": maximum_cap_adjustment,
            "floorAdjustment": floor_adjustment,
            "missingOrUnavailableMetrics": missing_metrics,
            "estimatedAllocations": sorted(distributed.get(pid, [])),
            "finalScore": score,
            "reconciledScore": reconciled,
            "reconciles": math.isclose(reconciled, score, rel_tol=1e-9, abs_tol=1e-8),
            "timelineExpressiveness": timeline_expressiveness(series, event_markers),
        }
        rows_out.append({"participantId": pid, "state": "partial", "coverage": "partial",
            "championId": participant.get("championId"), "champion": participant.get("champion"), "role": role,
            "finalScore": score, "series": series, "breakdown": dict(sorted(breakdown.items())),
            "audit": audit,
            "componentAvailability": availability, "context": {"used": sorted(context_used.get(pid, set())), "referenceMatchCount": ref_count,
                "confidence": "local_reference" if context_used.get(pid) else "opponent_or_linear_fallback"},
            "distributed": sorted(distributed.get(pid, [])), "deaths": sum(1 for _t, _e, event in unique_events if event.get("type") == "CHAMPION_KILL" and event.get("victimId") == pid),
            "usefulDamageReceived": useful_damage.get(pid, 0.0)})
    return {"version": VERSION, "configurationRevision": config["version"], "configurationHash": config["configuration_hash"], "visualization": config["visualization"], "sampleIntervalMs": sample_interval, "decayStartMs": decay_start,
        "state": "partial", "matchId": match_id, "matchDurationMs": duration_ms,
        "inputFingerprint": telemetry_fingerprint(participants, events, frames, duration, calibration_baselines, config),
        "coefficients": dict(coefficients), "calibrationSourceVersion": CALIBRATION_SOURCE_VERSION,
        "calibrationFamilyMultipliers": dict(CALIBRATION_FAMILY_MULTIPLIERS),
        "roleMultipliers": {k: dict(v) for k, v in role_table.items()},
        "decayPerMinute": config["decay"]["normal_per_minute"], "protectedDecayPerMinute": config["decay"]["below_threshold_per_minute"],
        "protectionThreshold": config["decay"]["low_score_threshold"],
        "recoveryBonusBands": [{"below": config["recovery"]["below_3_threshold"], "multiplier": 1.0 + config["recovery"]["below_3_bonus"]},
                               {"below": config["recovery"]["below_4_threshold"], "multiplier": 1.0 + config["recovery"]["below_4_bonus"]},
                               {"below": None, "multiplier": 1.0}],
        "minimumScore": minimum_score, "maximumScore": maximum_score,
        "diminishingThreshold": config["compression"]["threshold"],
        "diminishingMultiplier": config["compression"]["multiplier"],
        "contextConfig": {"sameRoleOpponentWeight": same_role_opponent_weight,
            "deviationWeight": deviation_weight,
            "maximumDownsideFractionOfBase": downside_fraction,
            "policy": "La recompensa lineal base se conserva; la desviación contextual es acotada."},
        "calibration": calibration_baselines or {"confidence": "fallback_linear", "source": "sin referencia local suficiente"},
        "participants": rows_out}
