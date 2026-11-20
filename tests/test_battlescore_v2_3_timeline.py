from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import battlescore_v2_2, battlescore_v2_3


FIXTURE = Path(__file__).parent.parent / "docs" / "battlescore_v2_2_reference_fixture.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_v2_3_snapshot_exposes_event_steps_without_changing_v2_2_final_scores():
    fixture = _fixture()
    args = (
        "reference-match", fixture["participants"], fixture["events"], fixture["frames"],
        fixture["match_duration_seconds"], fixture["calibration_baselines"],
    )
    previous = battlescore_v2_2.calculate_match(*args)
    current = battlescore_v2_3.calculate_match(*args)

    assert battlescore_v2_3.VERSION == "battlescore_v2_3"
    assert current["version"] == battlescore_v2_3.VERSION
    assert len(current["participants"]) == 10
    previous_by_id = {row["participantId"]: row for row in previous["participants"]}
    for row in current["participants"]:
        old = previous_by_id[row["participantId"]]
        assert row["finalScore"] == pytest.approx(old["finalScore"], abs=1e-12)
        assert row["series"][-1]["score"] == row["finalScore"]
        assert row["audit"]["reconciles"]
        assert len(row["series"]) >= len(old["series"])
        expressive = row["audit"]["timelineExpressiveness"]
        assert expressive["smoothingStrengthApplied"] == 0
        assert expressive["eventLinkedMarkers"] > 0
        assert expressive["scoreRange"] >= 0


def test_death_and_kill_impulses_are_kept_at_their_actual_event_time():
    events = [
        {"id": "kill-a", "timestamp": 45_000, "type": "CHAMPION_KILL", "killerId": 1, "victimId": 2,
         "assistingIds": []},
        {"id": "kill-b", "timestamp": 45_000, "type": "CHAMPION_KILL", "killerId": 2, "victimId": 1,
         "assistingIds": []},
    ]
    result = battlescore_v2_3.calculate_match("same-timestamp", [
        {"participantId": 1, "role": "MIDDLE"}, {"participantId": 2, "role": "TOP"},
    ], events, [], 120)
    first, second = result["participants"]
    for row in (first, second):
        event_points = [point for point in row["series"] if point["timestamp"] == 45_000]
        assert len(event_points) >= 2
        movement = [right["score"] - left["score"] for left, right in zip(event_points, event_points[1:])]
        assert any(value > 0 for value in movement)
        assert any(value < 0 for value in movement)
        diagnostics = row["audit"]["timelineExpressiveness"]
        assert diagnostics["eventLinkedPositiveMoves"] >= 1
        assert diagnostics["eventLinkedNegativeMoves"] >= 1


def test_expressiveness_diagnostic_reports_real_movements_and_no_smoothing():
    result = battlescore_v2_3.timeline_expressiveness(
        [{"timestamp": 0, "score": 5.0}, {"timestamp": 10_000, "score": 5.2},
         {"timestamp": 10_000, "score": 4.9}],
        [{"timestamp": 10_000, "category": "kills", "scoreDelta": .2},
         {"timestamp": 10_000, "category": "death", "scoreDelta": -.3}],
    )
    assert result["upwardMovement"] == pytest.approx(.2)
    assert result["downwardMovement"] == pytest.approx(.3)
    assert result["largestUpwardStep"] == pytest.approx(.2)
    assert result["largestDownwardStep"] == pytest.approx(-.3)
    assert result["eventLinkedTurningPoints"] == 1
    assert result["smoothingStrengthApplied"] == 0
