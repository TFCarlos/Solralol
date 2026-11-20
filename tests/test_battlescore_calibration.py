from __future__ import annotations

from backend.battlescore_calibration import MINIMUM_MATCHES, build_role_phase_baselines


def _reference_data(count=25):
    history, timelines = [], {}
    roles = ["TOP", "JUNGLE", "MID", "BOT", "SUPPORT"] * 2
    for match_index in range(count):
        match_id = f"EUW1_{match_index}"
        roster = [{"participant_id": pid, "team_id": 100 if pid <= 5 else 200,
                   "lane": roles[pid - 1]} for pid in range(1, 11)]
        history.append({"match_id": match_id, "queue_id": 420, "participants": roster})
        frames = []
        for minute in (0, 5, 10, 15, 20, 25):
            participant_frames = {}
            for pid in range(1, 11):
                activity = (100 + (pid % 5) * 20 + match_index) * minute
                participant_frames[str(pid)] = {
                    "totalGold": 500 + activity,
                    "xp": activity * 1.5,
                    "damageStats": {"totalDamageDoneToChampions": activity * 2},
                }
            frames.append({"timestamp": minute * 60_000, "participantFrames": participant_frames})
        timelines[match_id] = {"timeline": {"info": {"frames": frames}}}
    return history, timelines


def test_role_phase_reference_uses_cached_data_and_excludes_current_match():
    history, cache = _reference_data()
    baseline = build_role_phase_baselines(history, cache, exclude_match_id="EUW1_24")
    assert baseline["matches"] == 24
    assert baseline["confidence"] == "local_reference"
    for role in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
        for phase in ("early", "middle", "late"):
            for metric in ("gold", "experience", "champion_damage"):
                row = baseline["metrics"][role][phase][metric]
                assert row["matches"] == 24
                assert row["available"] is True
                assert row["medianPerMinute"] > 0
                assert row["p25PerMinute"] <= row["medianPerMinute"] <= row["p75PerMinute"]


def test_small_or_missing_reference_sets_are_explicitly_uncalibrated():
    history, cache = _reference_data(MINIMUM_MATCHES - 1)
    baseline = build_role_phase_baselines(history, cache)
    assert baseline["confidence"] == "fallback_linear"
    row = baseline["metrics"]["JUNGLE"]["early"]["gold"]
    assert row["matches"] == MINIMUM_MATCHES - 1
    assert row["available"] is False
    assert "medianPerMinute" not in row
    empty = build_role_phase_baselines([], {})
    assert empty["confidence"] == "fallback_linear"
    assert empty["matches"] == 0
