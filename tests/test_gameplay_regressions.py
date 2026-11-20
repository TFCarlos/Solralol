from __future__ import annotations

import subprocess
from unittest.mock import patch

from backend import recordings
from backend.draft import DraftRuntime
from app.services.live_match_tracker import LiveMatchTracker


def test_encoder_parser_reads_name_column_from_ffmpeg_encoder_listing():
    listing = """Encoders:\n V....D h264_amf AMD AMF H.264 Encoder (codec h264)\n V....D h264_nvenc NVIDIA NVENC H.264 encoder (codec h264)\n V..... h264_qsv H.264 / AVC encoder (codec h264)\n V....D libx264 libx264 H.264 encoder (codec h264)\n"""
    with patch.object(recordings.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, listing, "")):
        recordings._ENCODER_CACHE.clear()
        assert recordings._available_encoders("ffmpeg-test") == ("h264_amf", "h264_nvenc", "h264_qsv", "libx264")


def test_encoder_probe_keeps_working_fallbacks_and_reports_driver_failures():
    recordings._ENCODER_PROBE_CACHE.clear()
    with patch.object(recordings, "_available_encoders", return_value=("h264_nvenc", "h264_mf", "libx264")), \
         patch.object(recordings.subprocess, "run", side_effect=[
             subprocess.CompletedProcess([], 1, "", "NVENC device unavailable"),
             subprocess.CompletedProcess([], 0, "", ""),
             subprocess.CompletedProcess([], 0, "", ""),
         ]):
        available, failures = recordings._probe_encoders("ffmpeg-probe-test")
    assert available == ("h264_mf", "libx264")
    assert "NVENC device unavailable" in failures["h264_nvenc"]


def test_champion_select_only_marks_completed_pick_actions_as_locked():
    runtime = DraftRuntime.__new__(DraftRuntime)
    runtime.by_id = {233: "Briar", 22: "Ashe", 103: "Ahri"}
    locked = runtime._team([
        {"cellId": 7, "championId": 233, "championPickIntent": 22},
        {"cellId": 8, "championId": 22},
        {"cellId": 9, "championPickIntent": 103},
    ], True, {"8"})
    assert locked[0]["locked"] is False and locked[0]["state"] == "hover"
    assert locked[1]["locked"] is True and locked[1]["state"] == "locked"
    assert locked[2]["locked"] is False and locked[2]["intent"] == "Ahri"


def test_local_draft_uses_local_cell_hover_and_not_stale_manual_champion(monkeypatch):
    from tests.test_electron_draft import _LiveLCU, _runtime

    runtime = _runtime(monkeypatch)
    runtime.lcu = _LiveLCU()
    session = {
        "localPlayerCellId": 21,
        "myTeam": [{"cellId": 21, "summonerId": 1234, "championId": 0, "championPickIntent": 22}],
        "theirTeam": [],
        "actions": [[{"type": "pick", "actorCellId": 21, "championId": 22, "completed": False}]],
    }
    monkeypatch.setattr(runtime.lcu, "get_champ_select_session", lambda: session)
    snapshot = runtime.snapshot({"champion": "Ahri", "role": "mid"})
    assert snapshot["allies"][0]["local"] is True
    assert snapshot["allies"][0]["locked"] is False
    assert snapshot["localChampion"] == "Ashe"
    assert snapshot["analysis"]["champion"] == "Ashe"
