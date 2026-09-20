"""Prueba de extremo a extremo del motor con un entorno offscreen.

Genera una grabación real con ffmpeg (sin dispositivos de audio) para
comprobar que el ciclo start/stop escribe el MP4 y su sidecar.
Ejecutar: python -m unittest scratch.test_recordings_engine
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.recording_service import RecordingConfig, RecordingService


class RecordingEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def pump(self, seconds: float) -> None:
        deadline = time.time() + seconds

        while time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.05)

    def test_start_stop_real_ffmpeg(self):
        directory = Path(tempfile.mkdtemp()) / "recs"
        config = RecordingConfig(
            output_dir=directory,
            enabled=True,
            quality="420",
            video_bitrate=1500,
        )
        service = RecordingService()
        failures = []
        finished = []
        service.failed.connect(failures.append)
        service.finished.connect(finished.append)

        self.assertTrue(
            service.start(
                config,
                game_time=5.0,
                champion="Prueba",
                game_mode="CLASSIC",
            ),
            msg=service.last_error,
        )
        self.assertTrue(service.is_recording)
        self.pump(3.0)
        self.assertGreater(service.elapsed_seconds(), 1.0)

        self.assertTrue(
            service.stop(
                reason="game_end",
                session={
                    "local_player_key": "a",
                    "events": [],
                    "duration": 120.0,
                },
            )
        )

        deadline = time.time() + 20

        while not finished and time.time() < deadline:
            self.pump(0.2)

        self.assertEqual(len(finished), 1, msg=f"fallos: {failures}")
        self.assertFalse(service.is_recording)

        video = Path(finished[0])
        self.assertTrue(video.is_file())
        self.assertGreater(video.stat().st_size, 10_000)

        import json

        metadata = json.loads(
            video.with_suffix(".json").read_text(encoding="utf-8")
        )
        self.assertTrue(metadata.get("complete"))
        self.assertEqual(metadata.get("markers"), [])
        self.assertEqual(metadata.get("quality"), "420")
        self.assertEqual(metadata.get("video_bitrate"), 1500)
        self.assertEqual(metadata.get("champion"), "Prueba")

    def tearDown(self):
        if QApplication.instance() is not None:
            QApplication.instance().processEvents()


if __name__ == "__main__":
    unittest.main()
