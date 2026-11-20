"""Read-only reference-match audit for BattleScore 2.3 timeline behavior."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import battlescore_v2_2
from backend.battlescore import VERSION, calculate_match


FIXTURE = Path(__file__).resolve().parents[1] / "docs" / "battlescore_v2_2_reference_fixture.json"


def build_report(fixture: dict | None = None) -> dict:
    fixture = fixture or json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = fixture.get("source")
    match_id = source.get("match_id") if isinstance(source, dict) else None
    arguments = (
        str(match_id or "reference-match"),
        fixture["participants"], fixture["events"], fixture["frames"],
        fixture["match_duration_seconds"], fixture.get("calibration_baselines"),
    )
    old = battlescore_v2_2.calculate_match(*arguments)
    current = calculate_match(*arguments)
    old_by_id = {row["participantId"]: row for row in old.get("participants", [])}
    target_by_id = {int(pid): value for pid, value in fixture.get("targets", {}).items()}
    rows = []
    for row in current.get("participants", []):
        participant_id = row["participantId"]
        prior = old_by_id.get(participant_id, {})
        target = target_by_id.get(participant_id)
        rows.append({
            "participantId": participant_id,
            "champion": row.get("champion"),
            "role": row.get("role"),
            "previousFinalScore": prior.get("finalScore"),
            "currentFinalScore": row.get("finalScore"),
            "finalScoreDelta": float(row.get("finalScore", 0)) - float(prior.get("finalScore", 0)),
            "targetScore": target,
            "targetAbsoluteError": abs(float(row["finalScore"]) - target) if target is not None else None,
            "previousPointCount": len(prior.get("series", [])),
            "currentPointCount": len(row.get("series", [])),
            "timelineExpressiveness": row.get("audit", {}).get("timelineExpressiveness", {}),
            "breakdown": row.get("breakdown", {}),
        })
    errors = [row["targetAbsoluteError"] for row in rows if row["targetAbsoluteError"] is not None]
    return {
        "version": VERSION,
        "matchId": arguments[0],
        "durationSeconds": fixture["match_duration_seconds"],
        "comparison": "v2.2 frente a v2.3 con idénticos datos y fórmula de puntuación",
        "finalScoresUnchanged": all(abs(float(row["finalScoreDelta"])) < 1e-12 for row in rows),
        "referenceMae": mean(errors) if errors else None,
        "participantCount": len(rows),
        "participants": rows,
    }


if __name__ == "__main__":
    print(json.dumps(build_report(), ensure_ascii=False, indent=2, sort_keys=True))
