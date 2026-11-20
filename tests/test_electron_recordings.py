"""Contract checks for the headless Electron recording adapter."""
from __future__ import annotations

import json
import base64
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.recording_service import RecordingLibrary, build_ffmpeg_command
from backend.application import Application
from backend.recordings import RecordingRuntime


class ElectronRecordingContractTests(unittest.TestCase):
    def test_dxgi_commands_keep_seek_friendly_gop_for_supported_encoders(self) -> None:
        with patch("app.services.recording_service.sys.platform", "win32"):
            for encoder in ("h264_amf", "h264_nvenc", "h264_qsv", "libx264"):
                command = build_ffmpeg_command(ffmpeg_path="ffmpeg.exe", output_path="capture.mp4",
                    quality="1080", video_bitrate=8000, capture_desktop=True,
                    monitor_index=1, video_encoder=encoder)
                self.assertIn("ddagrab=output_idx=1:framerate=60:draw_mouse=0", command)
                self.assertEqual(command[command.index("-c:v") + 1], encoder)
                self.assertEqual(command[command.index("-g") + 1], "120")
                self.assertIn("+faststart", command)

    def test_backend_lists_and_deletes_recording_and_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "match.mp4"
            video.write_bytes(b"video")
            video.with_suffix(".json").write_text(json.dumps({"duration_seconds": 91, "complete": True}), encoding="utf-8")
            library = RecordingLibrary(root)
            rows = library.list_recordings()
            self.assertEqual(rows[0]["name"], video.name)
            self.assertEqual(rows[0]["duration"], 91)
            self.assertTrue(rows[0]["complete"])
            self.assertTrue(library.delete(video))
            self.assertFalse(video.exists())
            self.assertFalse(video.with_suffix(".json").exists())

    def test_electron_recording_list_is_json_safe_and_delete_rejects_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "match.mp4"
            video.write_bytes(b"video")
            app = Application()
            app.settings.load = lambda: {"recording_output_dir": str(root)}
            try:
                rows = app.dispatch("recordings.list")
                self.assertEqual(rows[0]["name"], "match.mp4")
                self.assertNotIn("path", rows[0])
                with self.assertRaises(ValueError):
                    app.dispatch("recordings.delete", {"name": "..\\outside.mp4"})
            finally:
                app.close()

    def test_recording_date_uses_capture_start_and_title_uses_local_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "game.mp4"
            video.write_bytes(b"original video bytes")
            started = "2026-10-20T08:43:00+00:00"
            video.with_suffix(".json").write_text(json.dumps({
                "started_at": started, "champion": "Briar", "game_mode": "SoloQ",
                "position": "jungle", "kda": [15, 10, 6], "opponent_champion": "Lee Sin",
            }), encoding="utf-8")
            rows = RecordingLibrary(root).list_recordings()
            expected = datetime.fromisoformat(started).astimezone()
            self.assertEqual(rows[0]["created_at"], expected.timestamp())
            self.assertEqual(rows[0]["title"], f"Briar - {expected.strftime('%Y-%m-%d_%H-%M')}")
            self.assertEqual(rows[0]["size_bytes"], len(b"original video bytes"))
            self.assertEqual(video.read_bytes(), b"original video bytes")

    def test_thumbnail_extracts_initial_valid_frame_and_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "capture.mp4"
            video.write_bytes(b"video")
            runtime = RecordingRuntime.__new__(RecordingRuntime)
            runtime.settings = SimpleNamespace(load=lambda: {"recording_output_dir": str(root)})
            runtime.lock = threading.RLock()
            runtime.process = None
            runtime.output_path = None
            runtime.state = "inactive"
            runtime.thumbnail_lock = threading.Lock()
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if "-f" in command and command[command.index("-f") + 1] == "null":
                    return subprocess.CompletedProcess(command, 0, "", "black_start:0.000 black_end:0.240")
                Path(command[-1]).write_bytes(b"x" * 200)
                return subprocess.CompletedProcess(command, 0, b"", b"")

            with patch("backend.recordings.find_ffmpeg", return_value="ffmpeg.exe"), \
                    patch("backend.recordings.subprocess.run", side_effect=run), \
                    patch("backend.recordings.Path.home", return_value=root), \
                    patch("backend.recordings.get_storage_manager", return_value=SimpleNamespace(
                        recording_thumbnails_dir=root / ".solralol" / "recording-thumbnails")), \
                    patch("app.services.recording_service.get_storage_manager", return_value=SimpleNamespace(
                        recording_thumbnails_dir=root / ".solralol" / "recording-thumbnails")):
                first = runtime.thumbnail(video.name)
                second = runtime.thumbnail(video.name)
                self.assertEqual(video.read_bytes(), b"video")
                self.assertEqual(first["state"], "ready")
                self.assertEqual(base64.b64decode(first["data"]), b"x" * 200)
                self.assertEqual(second, first)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[1][calls[1].index("-ss") + 1], "0.260")
                thumbnails = list((root / ".solralol" / "recording-thumbnails").glob("*.jpg"))
                self.assertEqual(len(thumbnails), 1)
                self.assertTrue(RecordingLibrary(root).delete(video))
                self.assertFalse(thumbnails[0].exists())

    def test_exact_saved_session_supplies_lane_opponent_and_real_kda(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "capture.mp4"
            video.write_bytes(b"video")
            video.with_suffix(".json").write_text(json.dumps({
                "started_at": "2026-10-20T08:43:00+00:00", "session_id": "session-1",
                "champion": "Briar", "game_mode": "CLASSIC",
            }), encoding="utf-8")
            session = {
                "session_id": "session-1", "local_player_key": "local", "game_mode": "CLASSIC",
                "players": {
                    "local": {"champion_name": "Briar", "role": "JUNGLE", "win": True},
                    "enemy": {"champion_name": "Lee Sin"},
                },
                "lane_matchups": {"JUNGLE": {"ally_key": "local", "enemy_key": "enemy"}},
                "final_scoreboard": {"local": {"kills": 15, "deaths": 10, "assists": 6, "win": True}},
                "performance_scoring": {"state": "POSTGAME_FINAL", "players": []},
            }
            app = Application.__new__(Application)
            app._storage_condition = threading.Condition(threading.RLock())
            app._storage_migration = {"state": "idle"}
            app._active_requests = 0
            app.settings = SimpleNamespace(load=lambda: {"recording_output_dir": str(root)})
            app._recordings = SimpleNamespace(snapshot=lambda: {"recordingName": None})
            app._recording_history_tracker = SimpleNamespace(load_saved_sessions=lambda: [session])
            app._catalog = [{"id": "Briar", "key": "233", "name": "Briar"}]
            row = app.dispatch("recordings.list")[0]
            self.assertEqual(row["champion"], "Briar")
            local_start = datetime.fromisoformat("2026-10-20T08:43:00+00:00").astimezone()
            self.assertEqual(row["title"], f"Briar - {local_start.strftime('%Y-%m-%d_%H-%M')}")
            self.assertEqual(row["position"], "jungle")
            self.assertEqual(row["opponent_champion"], "Lee Sin")
            self.assertEqual(row["kda"], [15, 10, 6])
            self.assertEqual(row["game_mode"], "CLASSIC")


if __name__ == "__main__":
    unittest.main()
