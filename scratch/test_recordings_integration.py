"""Integración de la pestaña «Grabaciones» dentro de MainWindow.

Comprueba, sin red ni partidas reales:
1. La pestaña existe en el índice esperado y el botón de la barra navega a ella.
2. La tarjeta de Ajustes → Grabaciones expone los desplegables de calidad
   (1080 → 420) y de bitrate, el interruptor de micrófono, la carpeta y el
   límite de peso.
3. Cambiar calidad/bitrate/límite se guarda y se refleja en la configuración.
4. La grabación arranca sola con la partida y recibe los datos del jugador.
5. Al terminar la partida se para la grabación con la sesión completada.
6. El botón «Detener grabación» para la grabación a mano.
7. El overlay de alertas muestra la fila «Grabando» mientras se graba.
8. Al cerrar la app, una grabación en curso se detiene.

Ejecutar: python -m unittest scratch.test_recordings_integration
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.recording_service import (  # noqa: E402
    BITRATE_PRESETS,
    LIMIT_DEFAULT_GB,
    LIMIT_MAX_GB,
    LIMIT_MIN_GB,
    QUALITY_PRESETS,
    normalize_quality,
)
from app.ui.main_window import MainWindow  # noqa: E402

SNAPSHOT = {
    "game_time": 35.0,
    "game_mode": "CLASSIC",
    "local_team": "ORDER",
    "local_player": {
        "riotId": "Solrasar#000",
        "summonerName": "Solrasar",
        "championName": "Briar",
        "level": 3,
    },
    "all_players": [],
    "enemies": [],
    "local_live_stats": {},
}


class FakeRecordingService:
    """Sustituye al motor real: apunta lo que le piden sin lanzar ffmpeg."""

    def __init__(self, signals=None, service=None) -> None:
        self.calls: list[tuple] = []
        self.is_recording = False
        self.output_path = None
        self.ffmpeg_available = True
        self.ffmpeg_hint = ""
        self.ffmpeg_path = "ffmpeg"
        self._signals = signals
        self._service = service

    def __getattr__(self, name: str):
        if name in {"started", "finished", "failed", "state_changed"}:
            if self._signals is not None:
                return getattr(self._signals, name)

            raise AttributeError(name)

        if self._service is not None and hasattr(self._service, name):
            return getattr(self._service, name)

        raise AttributeError(name)

    def refresh_ffmpeg(self, configured_path: str = "") -> str:
        return self.ffmpeg_path

    def start(self, config, **kwargs) -> bool:
        self.calls.append(("start", config, kwargs))
        self.is_recording = True

        return True

    def stop(self, reason: str = "game_end", session=None) -> bool:
        self.calls.append(("stop", reason, session))
        self.is_recording = False

        return True

    def abort(self) -> None:
        self.calls.append(("abort",))
        self.is_recording = False

    def wait_for_stop(self, timeout_ms: int | None = None) -> bool:
        return True

    def elapsed_seconds(self) -> float:
        return 0.0

    def _sync_overlay_recording(self, _state: str = "") -> None:
        self.calls.append(("sync", _state))


class RecordingsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

        # Ajustes en memoria: no se toca el settings.json del usuario.
        self.saved: dict = {}

        def fake_settings_factory():
            saved = self.saved

            class FakeSettingsService:
                def __init__(self, *args, **kwargs) -> None:
                    pass

                def load(self) -> dict:
                    return {}

                def save(self, settings: dict) -> None:
                    saved.clear()
                    saved.update(settings)

            return FakeSettingsService

        self.settings_patcher = patch(
            "app.ui.main_window.SettingsService",
            new=fake_settings_factory(),
        )
        self.settings_patcher.start()

        from app.ui.main_window import MainWindow

        self.window = MainWindow(version="test", item_catalog={"items": {}})
        self.app.processEvents()
        self.window.poll_timer.stop()

        # Las sesiones que cierre el test no deben acabar en el historial real.
        self.window.live_match_tracker.sessions_path = (
            Path(tempfile.mkdtemp()) / "live_match_sessions.json"
        )

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.settings_patcher.stop()

    def use_fake_service(self) -> FakeRecordingService:
        from PySide6.QtCore import QObject, Signal  # noqa: E402

        real = self.window.recording_service

        class RecordingSignals(QObject):
            started = Signal(str)
            finished = Signal(str)
            failed = Signal(str)
            state_changed = Signal(str)

        stub = FakeRecordingService(
            signals=RecordingSignals(self.window),
            service=real,
        )
        self.window.recording_service = stub
        self.window.recordings_page.service = stub
        self.window.recordings_page._wire_service()

        return stub

    # -- pestaña y navegación -------------------------------------------

    def test_page_index_and_navigation(self):
        self.assertEqual(MainWindow.RECORDINGS_PAGE_INDEX, 4)
        self.assertEqual(
            self.window.pages.indexOf(self.window.recordings_page),
            MainWindow.RECORDINGS_PAGE_INDEX,
        )

        self.window.recordings_button.click()
        self.app.processEvents()

        self.assertEqual(
            self.window.pages.currentIndex(),
            MainWindow.RECORDINGS_PAGE_INDEX,
        )
        self.assertTrue(self.window.recordings_button.isChecked())

    def test_page_uses_the_window_library_and_service(self):
        page = self.window.recordings_page

        self.assertIs(page.library, self.window.recording_library)
        self.assertIs(page.service, self.window.recording_service)

    # -- ajustes ---------------------------------------------------------

    def test_settings_card_exposes_the_recording_options(self):
        window = self.window

        quality = window.recording_quality_combo
        self.assertEqual(
            [quality.itemData(index) for index in range(quality.count())],
            [
                "1080",
                "108030",
                "900",
                "90030",
                "720",
                "72030",
                "540",
                "480",
                "420",
            ],
        )

        bitrate = window.recording_bitrate_combo
        self.assertEqual(
            [bitrate.itemData(index) for index in range(bitrate.count())],
            sorted(BITRATE_PRESETS),
        )

        self.assertTrue(window.recording_auto_checkbox.isChecked())

        # Audio: un solo desplegable de modo con las 5 opciones, y los
        # selectores de dispositivo visibles solo en los modos que los usan.
        audio_mode = window.recording_audio_mode_combo
        self.assertEqual(
            [audio_mode.itemData(i) for i in range(audio_mode.count())],
            ["none", "game", "mic", "game_mic", "all", "full"],
        )
        self.assertEqual(
            audio_mode.itemText(audio_mode.findData("all")),
            "Juego + micrófono + otros (Discord, YouTube…)",
        )

        current = audio_mode.currentData()
        self.assertEqual(
            window.recording_game_audio_combo.isVisibleTo(window),
            current in {"game", "game_mic", "all", "full"},
        )
        self.assertEqual(
            window.recording_mic_combo.isVisibleTo(window),
            current in {"mic", "game_mic", "all", "full"},
        )

        slider = window.recording_limit_slider
        self.assertEqual(slider.minimum(), LIMIT_MIN_GB)
        self.assertEqual(slider.maximum(), LIMIT_MAX_GB)
        self.assertEqual(slider.value(), int(LIMIT_DEFAULT_GB))

        self.assertEqual(
            window.recording_dir_input.text(),
            str(window.recording_config.output_dir),
        )

    def test_quality_bitrate_and_limit_changes_are_saved(self):
        window = self.window

        index = window.recording_quality_combo.findData("420")
        window.recording_quality_combo.setCurrentIndex(index)
        self.app.processEvents()

        self.assertEqual(self.saved.get("recording_quality"), "420")
        self.assertEqual(window.recording_config.quality, "420")
        self.assertEqual(window.recording_config.height, 420)

        index = window.recording_bitrate_combo.findData(1500)
        window.recording_bitrate_combo.setCurrentIndex(index)
        self.app.processEvents()

        self.assertEqual(self.saved.get("recording_bitrate"), 1500)
        self.assertEqual(window.recording_config.video_bitrate, 1500)

        window.recording_limit_slider.setValue(12)
        self.app.processEvents()

        self.assertEqual(self.saved.get("recording_size_limit_gb"), 12.0)
        self.assertEqual(window.recording_config.size_limit_gb, 12.0)
        self.assertEqual(window.recording_limit_value.text(), "12 GB")

    def test_invalid_quality_falls_back_to_a_known_preset(self):
        self.assertIn(normalize_quality("9999"), QUALITY_PRESETS)
        self.assertEqual(normalize_quality("9999"), normalize_quality(None))

    # -- arranque y parada automáticos ----------------------------------

    def test_recording_starts_with_the_match_and_receives_player_data(self):
        stub = self.use_fake_service()

        self.window.start_match_recording(SNAPSHOT)

        self.assertEqual(len(stub.calls), 1)
        kind, config, kwargs = stub.calls[0]
        self.assertEqual(kind, "start")
        self.assertIs(config, self.window.recording_config)
        self.assertEqual(kwargs["champion"], "Briar")
        self.assertEqual(kwargs["game_mode"], "CLASSIC")
        self.assertAlmostEqual(kwargs["game_time"], 35.0, places=1)

    def test_recording_does_not_start_twice(self):
        stub = self.use_fake_service()

        self.window.start_match_recording(SNAPSHOT)
        self.window.start_match_recording(SNAPSHOT)

        self.assertEqual(len(stub.calls), 1)

    def test_recording_stops_with_the_completed_session(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)

        session = {"session_id": "sesion-1", "events": []}
        self.window.stop_match_recording("game_end", session)

        self.assertEqual(stub.calls[-1], ("stop", "game_end", session))

    def test_stop_without_recording_is_a_noop(self):
        stub = self.use_fake_service()

        self.window.stop_match_recording("game_end", None)

        self.assertEqual(stub.calls, [])

    def test_manual_stop_keeps_the_live_session_open(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)
        self.window.was_in_game = True

        self.window.stop_recording_manually()

        self.assertEqual(len(stub.calls), 2)
        kind, config, _kwargs = stub.calls[0]
        self.assertEqual(kind, "start")
        self.assertEqual(stub.calls[-1][0], "stop")
        self.assertEqual(stub.calls[-1][1], "manual")
        self.assertTrue(self.window.was_in_game)
        self.assertFalse(self.window.live_session_finished)

    def test_manual_stop_is_a_noop_when_idle(self):
        stub = self.use_fake_service()

        self.window.stop_recording_manually()

        self.assertEqual(stub.calls, [])

    def test_manual_stop_emits_from_the_recordings_page(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)
        self.window.was_in_game = True
        emitted: list[str] = []
        self.window.recordings_page.stop_recording_requested.connect(
            lambda: emitted.append("stop")
        )

        self.window.recordings_page.stop_button.click()
        self.app.processEvents()

        self.assertEqual(emitted, ["stop"])

    def test_overlay_reflects_the_service_state(self):
        stub = self.use_fake_service()
        panel = self.window.overlay.panels["alerts"]

        self.assertFalse(panel.recording)
        self.assertFalse(panel.recording_row.isVisibleTo(panel))

        stub.is_recording = True
        self.window._sync_overlay_recording("recording")

        self.assertTrue(panel.recording)
        self.assertTrue(panel.recording_row.isVisibleTo(panel))

        stub.is_recording = False
        self.window._sync_overlay_recording("idle")

        self.assertFalse(panel.recording)
        self.assertFalse(panel.recording_row.isVisibleTo(panel))

    def test_overlay_reflects_manual_and_service_stops(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)
        self.window.was_in_game = True
        panel = self.window.overlay.panels["alerts"]

        self.window.stop_recording_manually()
        self.app.processEvents()

        self.assertFalse(panel.recording)
        self.assertFalse(panel.recording_row.isVisibleTo(panel))

    def test_worker_emits_game_ended_after_being_in_game(self):
        from app.services.live_data_worker import LiveDataWorker

        worker = LiveDataWorker()
        ended: list[bool] = []
        worker.game_ended.connect(lambda: ended.append(True))

        worker.read_snapshot()  # League cerrado: solo read_failed.
        self.assertEqual(ended, [])

        # Simula una partida en curso y su fin sin tocar la red.
        worker.was_in_game = True
        with patch.object(
            worker.game_service, "get_game_snapshot", return_value=None
        ):
            worker.read_snapshot()

        self.assertEqual(ended, [True])
        self.assertFalse(worker.was_in_game)

    def test_game_ended_stops_the_recording_and_closes_the_session(self):
        stub = self.use_fake_service()
        self.window.receive_snapshot(SNAPSHOT)
        self.window.was_in_game = True
        self.window.live_session_finished = False

        self.window.handle_game_ended()
        self.app.processEvents()

        stops = [call for call in stub.calls if call[0] == "stop"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][1], "game_end")
        self.assertTrue(self.window.live_session_finished)
        self.assertFalse(self.window.was_in_game)

    def test_game_ended_is_ignored_when_not_in_game(self):
        stub = self.use_fake_service()

        self.window.handle_game_ended()
        self.app.processEvents()

        self.assertEqual(stub.calls, [])

    def test_too_many_lost_snapshots_close_the_recording(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)
        self.window.was_in_game = True

        threshold = MainWindow.LIVE_LOST_POLLS_BEFORE_STOP
        for _ in range(threshold - 1):
            self.window.count_lost_snapshot()

        self.assertEqual([call[0] for call in stub.calls], ["start"])

        self.window.count_lost_snapshot()

        stops = [call for call in stub.calls if call[0] == "stop"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0][1], "game_end_lost")
        self.assertEqual(self.window.live_snapshots_lost, 0)

    def test_lost_snapshots_do_not_accumulate_outside_a_match(self):
        stub = self.use_fake_service()

        for _ in range(MainWindow.LIVE_LOST_POLLS_BEFORE_STOP + 5):
            self.window.count_lost_snapshot()

        self.assertEqual(stub.calls, [])
        self.assertEqual(self.window.live_snapshots_lost, 0)

    def test_finishing_twice_only_stops_once(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)
        self.window.was_in_game = True

        self.window.finish_live_session("game_end")
        self.window.finish_live_session("game_end")

        stops = [call for call in stub.calls if call[0] == "stop"]
        self.assertEqual(len(stops), 1)

    def test_closing_the_window_stops_an_active_recording(self):
        stub = self.use_fake_service()
        self.window.start_match_recording(SNAPSHOT)

        self.window.close()
        self.app.processEvents()

        reasons = [call[1] for call in stub.calls if call[0] == "stop"]
        self.assertIn("app_close", reasons)


if __name__ == "__main__":
    unittest.main()
