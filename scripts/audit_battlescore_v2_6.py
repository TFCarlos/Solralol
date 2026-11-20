"""Offline v2.5/v2.6 comparison for the cached ten-player reference match."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import battlescore_engine as current
from backend import battlescore_v2_5 as previous

FIXTURE = ROOT / "docs" / "battlescore_v2_2_reference_fixture.json"
CHECKPOINTS = (0, 5, 8, 12, 16, 18, 22)


def _at(row: dict, timestamp: int) -> float:
    return next((float(point["score"]) for point in reversed(row["series"])
                 if int(point.get("timestamp", 0)) <= timestamp), float(row["series"][0]["score"]))


def build_report() -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    args = ("reference-match", fixture["participants"], fixture["events"], fixture["frames"],
            float(fixture["match_duration_seconds"]), fixture.get("calibration_baselines"))
    before, after = previous.calculate_match(*args), current.calculate_match(*args)
    old = {row["participantId"]: row for row in before["participants"]}
    new = {row["participantId"]: row for row in after["participants"]}
    targets = {int(key): float(value) for key, value in fixture.get("targets", {}).items()}
    participants = []
    for participant in fixture["participants"]:
        pid = int(participant["participantId"])
        prior, row = old[pid], new[pid]
        participants.append({
            "champion": participant.get("champion"), "role": row.get("role"), "target": targets.get(pid),
            "v2_5": prior["finalScore"], "v2_6": row["finalScore"],
            "goldV2_5": prior["breakdown"]["gold"], "goldV2_6": row["breakdown"]["gold"],
            "experienceV2_5": prior["breakdown"]["experience"], "experienceV2_6": row["breakdown"]["experience"],
            "allocations": row["distributed"],
        })
    duration_ms = int(float(fixture["match_duration_seconds"]) * 1000)
    briar_old, briar_new = old[7], new[7]
    return {
        "version": current.VERSION,
        "coefficients": {"goldPer1000": current.COEFFICIENTS["gold_per_1000"],
                         "experiencePer1000": current.COEFFICIENTS["experience_per_1000"],
                         "normalDecayPerMinute": current.DECAY_PER_MINUTE,
                         "protectedDecayPerMinute": current.PROTECTED_DECAY_PER_MINUTE},
        "briar": {
            "checkpointsV2_5": {str(m): _at(briar_old, m * 60_000) for m in CHECKPOINTS},
            "checkpointsV2_6": {str(m): _at(briar_new, m * 60_000) for m in CHECKPOINTS},
            "finalV2_5": briar_old["finalScore"], "finalV2_6": briar_new["finalScore"],
            "lastStepV2_5": briar_old["series"][-1]["score"] - briar_old["series"][-2]["score"],
            "lastStepV2_6": briar_new["series"][-1]["score"] - briar_new["series"][-2]["score"],
            "lastActualFrame": 1_740_586, "matchEnd": duration_ms,
        },
        "participants": participants,
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2, allow_nan=False))
