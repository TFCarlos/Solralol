"""Offline, role/phase reference rates from already cached Riot timelines.

The module never downloads data or writes to match history. A baseline is
usable only after enough distinct cached ranked matches contribute to it.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median, quantiles
from typing import Any

CALIBRATION_VERSION = "role_phase_median_v1"
MINIMUM_MATCHES = 20
PHASES = ((0.0, 10.0, "early"), (10.0, 20.0, "middle"), (20.0, float("inf"), "late"))
METRICS = ("gold", "experience", "champion_damage")
ROLE_ALIASES = {
    "TOP": "TOP", "SOLO": "TOP", "JUNGLE": "JUNGLE", "MID": "MIDDLE", "MIDDLE": "MIDDLE",
    "BOT": "BOTTOM", "BOTTOM": "BOTTOM", "CARRY": "BOTTOM", "ADC": "BOTTOM",
    "SUPPORT": "UTILITY", "UTILITY": "UTILITY",
}


def canonical_role(value: Any) -> str | None:
    return ROLE_ALIASES.get(str(value or "").strip().upper())


def _match_ids(match: dict[str, Any]) -> set[str]:
    ids = set()
    for key in ("game_id", "gameId", "stable_match_id", "match_id"):
        value = str(match.get(key) or "").strip()
        if value:
            ids.add(value)
            ids.add(value.split("_", 1)[-1])
    return ids


def _phase(minutes: float, phase_bounds: tuple[tuple[float, float, str], ...] = PHASES) -> str:
    return next(name for start, end, name in phase_bounds if start <= minutes < end)


def _frame_metric(frame: dict[str, Any], metric: str) -> float | None:
    if metric == "gold":
        value = frame.get("totalGold")
    elif metric == "experience":
        value = frame.get("xp")
    else:
        stats = frame.get("damageStats") if isinstance(frame.get("damageStats"), dict) else {}
        value = stats.get("totalDamageDoneToChampions")
        if value is None:
            parts = [stats.get(key) for key in (
                "physicalDamageDoneToChampions", "magicDamageDoneToChampions", "trueDamageDoneToChampions"
            )]
            if any(isinstance(part, (int, float)) and not isinstance(part, bool) for part in parts):
                value = sum(max(0.0, float(part)) for part in parts if isinstance(part, (int, float)) and not isinstance(part, bool))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_role_phase_baselines(history_matches: list[dict[str, Any]], timeline_cache: dict[str, Any], *,
                               exclude_match_id: str | None = None,
                               minimum_matches: int = MINIMUM_MATCHES,
                               phase_bounds_minutes: tuple[float, float] = (10.0, 20.0)) -> dict[str, Any]:
    """Build robust per-minute medians, with one sample per match/player/phase.

    Rates come only from consecutive cumulative timeline observations. An
    interval spanning a phase boundary is assigned by its midpoint; it is
    never presented as a timestamped scoring event.
    """
    match_index: dict[str, dict[str, Any]] = {}
    for match in history_matches:
        if not isinstance(match, dict) or str(match.get("queue_id") or "") != "420":
            continue
        for match_id in _match_ids(match):
            match_index.setdefault(match_id, match)

    excluded = str(exclude_match_id or "")
    samples: dict[tuple[str, str, str], list[tuple[str, float]]] = defaultdict(list)
    matched_matches: set[str] = set()
    for cached_id, entry in (timeline_cache or {}).items():
        if not isinstance(entry, dict):
            continue
        timeline = entry.get("timeline")
        info = timeline.get("info") if isinstance(timeline, dict) else None
        raw_frames = info.get("frames") if isinstance(info, dict) else None
        if not isinstance(raw_frames, list):
            continue
        match = match_index.get(str(cached_id)) or match_index.get(str(cached_id).split("_", 1)[-1])
        if not match:
            continue
        match_ids = _match_ids(match)
        canonical_id = str(match.get("match_id") or match.get("game_id") or match.get("stable_match_id") or cached_id)
        if excluded and (excluded in match_ids or excluded.split("_", 1)[-1] in match_ids
                         or canonical_id == excluded or canonical_id.split("_", 1)[-1] == excluded.split("_", 1)[-1]):
            continue
        if not raw_frames:
            continue
        roster: dict[int, tuple[str, int | None]] = {}
        for participant in match.get("participants", []) if isinstance(match.get("participants"), list) else []:
            if not isinstance(participant, dict):
                continue
            raw_pid = participant.get("participant_id", participant.get("participantId"))
            # Home-history rows can explicitly contain lane="unknown" while
            # the Riot timeline metadata still has teamPosition/role. Prefer
            # the first recognized canonical value rather than the first
            # non-empty string.
            role = next((canonical_role(participant.get(key)) for key in
                         ("team_position", "teamPosition", "timeline_role", "team_role", "lane", "role")
                         if canonical_role(participant.get(key))), None)
            if isinstance(raw_pid, int) and role:
                team = participant.get("team_id", participant.get("teamId"))
                roster[raw_pid] = (role, team if isinstance(team, int) else None)
        if not roster:
            continue

        # Aggregate within each participant and phase first, so a longer match
        # does not count each of its frames as an independent reference match.
        totals: dict[tuple[int, str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
        previous: dict[int, tuple[float, dict[str, float | None]]] = {}
        for raw in raw_frames:
            if not isinstance(raw, dict) or not isinstance(raw.get("timestamp"), (int, float)):
                continue
            timestamp_min = max(0.0, float(raw["timestamp"]) / 60_000.0)
            frame_players = raw.get("participantFrames") if isinstance(raw.get("participantFrames"), dict) else {}
            for raw_pid, frame in frame_players.items():
                try:
                    pid = int(raw_pid)
                except (TypeError, ValueError):
                    continue
                if pid not in roster or not isinstance(frame, dict):
                    continue
                current = {metric: _frame_metric(frame, metric) for metric in METRICS}
                old = previous.get(pid)
                if old:
                    old_time, old_values = old
                    elapsed = timestamp_min - old_time
                    if elapsed > 0:
                        phase_limits = ((0.0, float(phase_bounds_minutes[0]), "early"),
                                        (float(phase_bounds_minutes[0]), float(phase_bounds_minutes[1]), "middle"),
                                        (float(phase_bounds_minutes[1]), float("inf"), "late"))
                        phase = _phase((old_time + timestamp_min) / 2.0, phase_limits)
                        for metric in METRICS:
                            before, after = old_values.get(metric), current.get(metric)
                            if before is None or after is None:
                                continue
                            key = (pid, phase, metric)
                            totals[key][0] += max(0.0, after - before)
                            totals[key][1] += elapsed
                previous[pid] = (timestamp_min, current)
        for (pid, phase, metric), (amount, minutes) in totals.items():
            if minutes <= 0:
                continue
            role = roster[pid][0]
            samples[(role, phase, metric)].append((canonical_id, amount / minutes))
        matched_matches.add(canonical_id)

    result: dict[str, Any] = {
        "version": CALIBRATION_VERSION,
        "source": "historial SoloQ y cronologías de Riot ya guardados",
        "matches": len(matched_matches),
        "minimumMatches": minimum_matches,
        "phases": ["early", "middle", "late"],
        "metrics": {},
    }
    for (role, phase, metric), rows in sorted(samples.items()):
        # Require distinct games; repeated/duplicate participant records do
        # not inflate confidence.
        per_match: dict[str, list[float]] = defaultdict(list)
        for match_id, rate in rows:
            per_match[match_id].append(rate)
        rates = [median(values) for values in per_match.values()]
        n = len(rates)
        usable = n >= minimum_matches
        stats: dict[str, Any] = {"matches": n, "available": usable}
        if usable:
            ordered = sorted(rates)
            quartiles = quantiles(ordered, n=4, method="inclusive")
            stats.update({"medianPerMinute": median(ordered), "p25PerMinute": quartiles[0], "p75PerMinute": quartiles[2]})
        result["metrics"].setdefault(role, {}).setdefault(phase, {})[metric] = stats
    result["confidence"] = "local_reference" if any(
        item.get("available") for phases in result["metrics"].values() for metrics in phases.values() for item in metrics.values()
    ) else "fallback_linear"
    return result
