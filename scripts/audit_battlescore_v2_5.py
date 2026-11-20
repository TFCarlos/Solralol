"""Offline v2.3/v2.5 scoring audit against the cached Briar reference match."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import battlescore_v2_5 as current
from backend import battlescore_v2_3 as previous

FIXTURE = ROOT / "docs" / "battlescore_v2_2_reference_fixture.json"
CHECKPOINTS = (0, 5, 8, 12, 16, 18, 22)


def _at(row: dict[str, Any], timestamp: int) -> float:
    points = row.get("series", [])
    return next((float(point["score"]) for point in reversed(points)
                 if int(point.get("timestamp", 0)) <= timestamp), float(points[0]["score"]))


def _mae(rows: list[dict[str, Any]], targets: dict[int, float]) -> float:
    return sum(abs(row["finalScore"] - targets[row["participantId"]]) for row in rows) / max(1, len(rows))


def build_report(fixture: dict[str, Any] | None = None) -> dict[str, Any]:
    fixture = fixture or json.loads(FIXTURE.read_text(encoding="utf-8"))
    args = ("reference-match", fixture["participants"], fixture["events"], fixture["frames"],
            float(fixture["match_duration_seconds"]), fixture.get("calibration_baselines"))
    before, after = previous.calculate_match(*args), current.calculate_match(*args)
    early_end_ms = 8 * 60_000
    early_participants = [{key: row.get(key) for key in
                           ("participantId", "role", "teamId", "championId", "champion")}
                          for row in fixture["participants"]]
    early_args = (
        "reference-match-first-eight-minutes", early_participants,
        [event for event in fixture["events"] if int(event.get("timestamp", 0)) <= early_end_ms],
        [frame for frame in fixture["frames"] if int(frame.get("timestamp", 0)) <= early_end_ms],
        480.0, fixture.get("calibration_baselines"),
    )
    early_before, early_after = previous.calculate_match(*early_args), current.calculate_match(*early_args)
    targets = {int(key): float(value) for key, value in fixture.get("targets", {}).items()}
    old = {row["participantId"]: row for row in before["participants"]}
    new = {row["participantId"]: row for row in after["participants"]}
    roster = {int(row["participantId"]): row for row in fixture["participants"]}
    duration_ms = int(float(fixture["match_duration_seconds"]) * 1000)
    rows = []
    for pid, row in new.items():
        prior = old[pid]
        gold_delta = row["breakdown"]["gold"] - prior["breakdown"]["gold"]
        death_delta = row["breakdown"]["death_penalties"] - prior["breakdown"]["death_penalties"]
        decay_delta = row["breakdown"]["time_decay"] - prior["breakdown"]["time_decay"]
        rows.append({
            "participantId": pid, "champion": roster[pid].get("champion"), "role": row.get("role"),
            "target": targets.get(pid), "v2_3": prior["finalScore"], "v2_5": row["finalScore"],
            "change": row["finalScore"] - prior["finalScore"],
            "absoluteErrorV2_3": abs(prior["finalScore"] - targets[pid]) if pid in targets else None,
            "absoluteErrorV2_5": abs(row["finalScore"] - targets[pid]) if pid in targets else None,
            "goldRewardV2_3": prior["breakdown"]["gold"], "goldRewardV2_5": row["breakdown"]["gold"],
            "goldRewardChange": gold_delta,
            "decayV2_3": prior["breakdown"]["time_decay"], "decayV2_5": row["breakdown"]["time_decay"],
            "decayChange": decay_delta,
            "deathPenaltyV2_3": prior["breakdown"]["death_penalties"],
            "deathPenaltyV2_5": row["breakdown"]["death_penalties"], "deathPenaltyChange": death_delta,
            "checkpointsV2_3": {str(minute): _at(prior, minute * 60_000) for minute in CHECKPOINTS},
            "checkpointsV2_5": {str(minute): _at(row, minute * 60_000) for minute in CHECKPOINTS},
            "finalScoreV2_3": _at(prior, duration_ms),
            "finalTimestampV2_5": _at(row, duration_ms),
        })
    briar = next(row for row in rows if row["champion"] == "Briar")
    early_old_briar = next(row for row in early_before["participants"] if row["participantId"] == 7)
    early_new_briar = next(row for row in early_after["participants"] if row["participantId"] == 7)
    return {
        "version": current.VERSION,
        "source": fixture.get("source"),
        "durationSeconds": fixture["match_duration_seconds"],
        "previousVersion": previous.VERSION,
        "coefficients": dict(current.COEFFICIENTS),
        "decay": {"startsAtMs": current.DECAY_START_MS, "normalPerMinute": current.DECAY_PER_MINUTE,
                  "belowTwoPerMinute": current.PROTECTED_DECAY_PER_MINUTE},
        "roleMultipliers": current.ROLE_MULTIPLIERS,
        "referenceTargets": {"maeV2_3": _mae(before["participants"], targets),
                             "maeV2_5": _mae(after["participants"], targets)},
        "earlyBriar": {
            "scoreAt8V2_3": _at(old[7], 8 * 60_000), "scoreAt8V2_5": _at(new[7], 8 * 60_000),
            "prefixV2_3": {"scoreAt8": early_old_briar["finalScore"],
                "timeDecay": early_old_briar["breakdown"]["time_decay"],
                "goldReward": early_old_briar["breakdown"]["gold"],
                "experienceReward": early_old_briar["breakdown"]["experience"],
                "kills": early_old_briar["breakdown"]["kills"],
                "assists": early_old_briar["breakdown"]["assists"],
                "deathPenalties": early_old_briar["breakdown"]["death_penalties"],
                "contextualAdjustmentByMetric": early_old_briar["audit"].get("contextualAdjustmentByMetric", {})},
            "prefixV2_5": {"scoreAt8": early_new_briar["finalScore"],
                "timeDecay": early_new_briar["breakdown"]["time_decay"],
                "goldReward": early_new_briar["breakdown"]["gold"],
                "experienceReward": early_new_briar["breakdown"]["experience"],
                "kills": early_new_briar["breakdown"]["kills"],
                "assists": early_new_briar["breakdown"]["assists"],
                "deathPenalties": early_new_briar["breakdown"]["death_penalties"],
                "contextualAdjustmentByMetric": early_new_briar["audit"].get("contextualAdjustmentByMetric", {})},
            "matchDeathTimestampsMs": [int(event["timestamp"]) for event in fixture["events"]
                if event.get("type") == "CHAMPION_KILL" and event.get("victimId") == 7],
            "goldRewardV2_3": old[7]["breakdown"]["gold"], "goldRewardV2_5": new[7]["breakdown"]["gold"],
            "roleAdjustedBaseByMetricV2_5": new[7]["audit"].get("roleAdjustedBaseByMetric", {}),
            "contextualAdjustmentByMetricV2_5": new[7]["audit"].get("contextualAdjustmentByMetric", {}),
            "totalContextualAdjustmentV2_5": new[7]["breakdown"]["contextual_adjustment"],
            "totalDecayV2_3": old[7]["breakdown"]["time_decay"],
            "totalDecayV2_5": new[7]["breakdown"]["time_decay"],
            "deathPenaltyV2_3": old[7]["breakdown"]["death_penalties"],
            "deathPenaltyV2_5": new[7]["breakdown"]["death_penalties"],
        },
        "participants": rows,
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2, allow_nan=False))
