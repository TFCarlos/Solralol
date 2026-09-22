"""Pruebas de la pestaña Grabaciones sin red ni partidas reales.

Ejecutar: python -m unittest scratch.test_recordings
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QMessageBox,
)

from app.services.recording_service import (
    BITRATE_PRESETS,
    DEFAULT_BITRATE,
    QUALITY_PRESETS,
    RecordingConfig,
    RecordingLibrary,
    audio_mode_label,
    audio_mode_uses_game,
    audio_mode_uses_full_system,
    audio_mode_uses_mic,
    audio_mode_uses_system,
    bitrate_label,
    build_ffmpeg_command,
    build_markers,
    derive_audio_mode,
    find_ffmpeg,
    format_duration,
    format_size,
    marker_counts,
    markers_summary,
    normalize_audio_mode,
    normalize_bitrate,
    pick_game_audio_device,
    pick_microphone_device,
    pick_system_audio_device,
    quality_label,
    recording_settings_defaults,
    sanitize_filename_part,
    suggest_recording_name,
)
from app.ui.recordings_page import MarkerSlider, RecordingsPage


def sample_session() -> dict:
    return {
        "local_player_key": "local",
        "events": [
            {
                "time": 130.0,
                "order": 1,
                "type": "kill_exact",
                "player_key": "local",
                "team": "ORDER",
                "label": "Yo asesinó a Rival",
                "killer_key": "local",
                "victim_key": "enemy",
                "assister_keys": [],
            },
            {
                "time": 200.0,
                "order": 2,
                "type": "kill_exact",
                "player_key": "enemy",
                "team": "CHAOS",
                "label": "Rival asesinó a Aliado",
                "killer_key": "enemy",
                "victim_key": "ally",
                "assister_keys": ["local"],
            },
            {
                "time": 250.0,
                "order": 3,
                "type": "death_exact",
                "player_key": "local",
                "team": "ORDER",
                "label": "Yo murió a manos de Rival",
                "killer_key": "enemy",
                "victim_key": "local",
            },
            {
                "time": 420.0,
                "order": 4,
                "type": "objective",
                "player_key": None,
                "team": "ORDER",
                "label": "Equipo aliado consiguió Dragón",
                "objective": "dragon",
            },
            {
                "time": 900.0,
                "order": 5,
                "type": "objective",
                "player_key": None,
                "team": "CHAOS",
                "label": "Equipo enemigo consiguió Barón",
                "objective": "baron",
            },
            {
                "time": 1100.0,
                "order": 6,
                "type": "objective",
                "player_key": None,
                "team": "ORDER",
                "label": "Equipo aliado consiguió Torre",
                "objective": "tower",
            },
        ],
    }


class PresetTests(unittest.TestCase):
    def test_quality_range_from_1080_to_420(self):
        self.assertEqual(
            sorted(QUALITY_PRESETS, key=int),
            ["420", "480", "540", "720", "900", "1080",
             "72030", "90030", "108030"],
        )
        self.assertEqual(quality_label("1080"), "1080p · 60 FPS")
        self.assertEqual(quality_label("108030"), "1080p · 30 FPS")
        self.assertEqual(quality_label("90030"), "900p · 30 FPS")
        self.assertEqual(quality_label("72030"), "720p · 30 FPS")
        self.assertEqual(quality_label("420"), "420p · 30 FPS")
        self.assertEqual(quality_label("rara"), "1080p · 60 FPS")

    def test_bitrate_normalizes_to_known_preset(self):
        self.assertEqual(normalize_bitrate(6000), 6000)
        self.assertEqual(normalize_bitrate(7000), 6000)
        self.assertEqual(normalize_bitrate("basura"), DEFAULT_BITRATE)
        self.assertIn("Mbps", bitrate_label(8000))

    def test_config_reads_settings_dict(self):
        config = RecordingConfig.from_settings(
            {
                "recording_auto": False,
                "recording_quality": "720",
                "recording_bitrate": 4000,
                "recording_mic_enabled": True,
                "recording_mic_device": "Mic",
                "recording_game_audio_device": "Stereo Mix",
                "recording_output_dir": "C:/Videos/X",
                "recording_size_limit_gb": 25,
            }
        )
        self.assertFalse(config.enabled)
        self.assertEqual(config.quality, "720")
        self.assertEqual(config.height, 720)
        self.assertEqual(config.fps, 60)
        self.assertEqual(config.video_bitrate, 4000)
        self.assertTrue(config.mic_enabled)
        self.assertEqual(config.mic_device, "Mic")
        self.assertEqual(config.game_audio_device, "Stereo Mix")
        self.assertEqual(config.size_limit_bytes, 25 * 1024**3)

    def test_audio_mode_migration_from_legacy_keys(self):
        # Ajustes antiguos: el modo se deduce del micro y del dispositivo.
        self.assertEqual(
            RecordingConfig.from_settings(
                {
                    "recording_game_audio_device": "Stereo Mix",
                    "recording_mic_enabled": True,
                }
            ).audio_mode,
            "game_mic",
        )
        self.assertEqual(
            RecordingConfig.from_settings(
                {"recording_mic_enabled": True}
            ).audio_mode,
            "mic",
        )
        self.assertEqual(
            RecordingConfig.from_settings(
                {"recording_game_audio_device": "Stereo Mix"}
            ).audio_mode,
            "game",
        )
        self.assertEqual(
            RecordingConfig.from_settings({}).audio_mode,
            "none",
        )

        # Ajustes nuevos: la clave manda y no se re-deduce.
        self.assertEqual(
            RecordingConfig.from_settings(
                {"recording_audio_mode": "all"}
            ).audio_mode,
            "all",
        )
        self.assertEqual(
            RecordingConfig.from_settings(
                {
                    "recording_audio_mode": "basura",
                    "recording_game_audio_device": "Stereo Mix",
                }
            ).audio_mode,
            "game",
        )
        # Con captura de sistema activada y micrófono → full.
        self.assertEqual(
            RecordingConfig.from_settings(
                {
                    "recording_audio_mode": "basura",
                    "recording_mic_enabled": True,
                    "recording_mic_capture_enabled": True,
                    "recording_game_audio_device": "Stereo Mix",
                }
            ).audio_mode,
            "full",
        )

    def test_audio_mode_helpers(self):
        self.assertEqual(normalize_audio_mode(None), "game")
        self.assertEqual(
            audio_mode_label("all"),
            "Juego + micrófono + resto del PC (Discord, YouTube, etc.)",
        )
        self.assertTrue(audio_mode_uses_game("game_mic"))
        self.assertFalse(audio_mode_uses_game("mic"))
        self.assertTrue(audio_mode_uses_mic("all"))
        self.assertFalse(audio_mode_uses_mic("game"))
        self.assertTrue(audio_mode_uses_system("all"))
        self.assertFalse(audio_mode_uses_system("game_mic"))
        self.assertTrue(audio_mode_uses_full_system("full"))
        self.assertFalse(audio_mode_uses_full_system("all"))
        self.assertTrue(audio_mode_uses_full_system("full"))
        self.assertFalse(audio_mode_uses_system("game"))


class AudioPickTests(unittest.TestCase):
    def test_picks_loopback_and_microphone(self):
        devices = ["Microfono (Realtek)", "Stereo Mix (Realtek)"]
        self.assertEqual(
            pick_game_audio_device(devices), "Stereo Mix (Realtek)"
        )
        self.assertEqual(
            pick_microphone_device(devices), "Microfono (Realtek)"
        )
        self.assertEqual(pick_game_audio_device([]), "")
        self.assertEqual(
            pick_microphone_device(["Altavoces"]), "Altavoces"
        )

    def test_system_device_skips_the_excluded_ones(self):
        devices = [
            "Stereo Mix (Realtek)",
            "VB-Cable Output (VB-Audio)",
            "Microfono (Realtek)",
        ]

        # El juego ya se captura con Stereo Mix: no se repite ese input.
        self.assertEqual(
            pick_system_audio_device(
                devices, exclude={"Stereo Mix (Realtek)"}
            ),
            "VB-Cable Output (VB-Audio)",
        )

        # Sin capturador libre, no se añade nada (el propio Stereo Mix ya
        # incluye la mezcla completa del sistema).
        self.assertEqual(
            pick_system_audio_device(
                ["Stereo Mix (Realtek)", "Microfono (Realtek)"],
                exclude={"Stereo Mix (Realtek)"},
            ),
            "",
        )

    def test_config_defaults_unknown_values(self):
        config = RecordingConfig.from_settings({})
        self.assertTrue(config.enabled)
        self.assertEqual(config.quality, "1080")
        self.assertEqual(config.video_bitrate, DEFAULT_BITRATE)
        self.assertFalse(config.mic_enabled)
        self.assertEqual(config.size_limit_bytes, 50 * 1024**3)
        self.assertEqual(
            set(recording_settings_defaults()),
            {
                "recording_auto",
                "recording_quality",
                "recording_bitrate",
                "recording_mic_enabled",
                "recording_mic_device",
                "recording_game_audio_device",
                "recording_output_dir",
                "recording_size_limit_gb",
                "ffmpeg_path",
            },
        )


class CommandTests(unittest.TestCase):
    def test_video_only_command(self):
        command = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="salida.mp4",
            quality="720",
            video_bitrate=6000,
        )
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("desktop", command)
        self.assertIn("gdigrab", command)
        self.assertIn("-an", command)
        self.assertIn("scale=-2:720", " ".join(command))
        self.assertIn("6000k", command)
        self.assertEqual(command[-1], "salida.mp4")

    def test_game_audio_and_microphone_are_mixed(self):
        command = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="salida.mp4",
            game_audio_device="Stereo Mix",
            mic_device="Microfono",
        )
        joined = " ".join(command)
        self.assertIn("audio=Stereo Mix", joined)
        self.assertIn("audio=Microfono", joined)
        self.assertIn("amix=inputs=2", joined)
        self.assertIn("-c:a", command)
        self.assertNotIn("-an", command)

    def test_microphone_only_still_records_audio(self):
        command = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="salida.mp4",
            mic_device="Microfono",
        )
        joined = " ".join(command)
        self.assertIn("audio=Microfono", joined)
        self.assertIn("-c:a", command)

    def test_system_audio_mode_mixes_a_third_device(self):
        command = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="salida.mp4",
            game_audio_device="Stereo Mix",
            mic_device="Microfono",
            system_audio_device="virtual-audio-capturer",
        )
        joined = " ".join(command)
        self.assertIn("audio=virtual-audio-capturer", joined)
        self.assertIn("amix=inputs=3", joined)

    def test_system_full_includes_third_device(self):
        command = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="salida.mp4",
            game_audio_device="Stereo Mix",
            mic_device="Microfono",
            system_audio_device="virtual-audio-capturar",
        )
        joined = " ".join(command)
        self.assertIn("audio=virtual-audio-capturar", joined)
        self.assertIn("amix=inputs=3", joined)

    def test_duplicated_devices_are_not_input_twice(self):
        command = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="salida.mp4",
            game_audio_device="Stereo Mix",
            system_audio_device="Stereo Mix",
        )
        joined = " ".join(command)
        self.assertEqual(joined.count("audio=Stereo Mix"), 1)
        self.assertNotIn("amix=inputs=", joined)

    def test_quality_changes_scale_and_framerate(self):
        low = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            output_path="x.mp4",
            quality="420",
            video_bitrate=1500,
        )
        self.assertIn("scale=-2:420", " ".join(low))
        self.assertIn("30", low)
        self.assertIn("1500k", low)


class MarkerTests(unittest.TestCase):
    def session(self):
        return sample_session()

    def test_exact_events(self):
        markers = build_markers(self.session(), game_time_offset=10.0)
        kinds = [marker["kind"] for marker in markers]

        self.assertEqual(
            kinds, ["kill", "assist", "death", "dragon", "baron", "tower"]
        )
        self.assertEqual(markers[0]["time"], 120.0)
        self.assertEqual(markers[0]["label"], "Asesinato")

    def test_enemy_kills_are_not_marked(self):
        session = self.session()
        session["events"].append(
            {
                "time": 300.0,
                "order": 9,
                "type": "kill_exact",
                "player_key": "enemy",
                "assister_keys": [],
                "label": "Rival asesinó a Otro",
            }
        )
        kinds = [marker["kind"] for marker in build_markers(session)]
        self.assertEqual(kinds.count("kill"), 1)
        self.assertEqual(kinds.count("death"), 1)

    def test_observed_counters_when_no_exact_events(self):
        session = {
            "local_player_key": "local",
            "events": [
                {
                    "time": 60.0,
                    "order": 1,
                    "type": "kill",
                    "player_key": "local",
                    "label": "Asesinato 1",
                },
                {
                    "time": 90.0,
                    "order": 2,
                    "type": "assist",
                    "player_key": "local",
                    "label": "Asistencia 1",
                },
                {
                    "time": 120.0,
                    "order": 3,
                    "type": "death",
                    "player_key": "local",
                    "label": "Muerte 1",
                },
            ],
        }
        kinds = [marker["kind"] for marker in build_markers(session)]
        self.assertEqual(kinds, ["kill", "assist", "death"])

    def test_herald_uses_the_tracker_objective_key(self):
        """El tracker guarda el heraldo como ``rift_herald``."""
        session = {
            "local_player_key": "local",
            "events": [
                {
                    "time": 400.0,
                    "order": 1,
                    "type": "objective",
                    "player_key": None,
                    "team": "ORDER",
                    "label": "Equipo aliado consiguió Heraldo",
                    "objective": "rift_herald",
                }
            ],
        }
        markers = build_markers(session)
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["kind"], "herald")
        self.assertEqual(markers[0]["label"], "Heraldo")
        self.assertEqual(marker_counts(markers), {"herald": 1})
        self.assertIn("heraldo", markers_summary(markers))

    def test_negative_video_times_are_clamped(self):
        session = {
            "local_player_key": "local",
            "events": [
                {
                    "time": 5.0,
                    "order": 1,
                    "type": "kill",
                    "player_key": "local",
                    "label": "Asesinato 1",
                }
            ],
        }
        markers = build_markers(session, game_time_offset=30.0)
        self.assertEqual(markers[0]["time"], 0.0)

    def test_counts_and_summary(self):
        markers = build_markers(self.session())
        counts = marker_counts(markers)
        self.assertEqual(counts["kill"], 1)
        self.assertEqual(counts["dragon"], 1)
        self.assertIn("asesinato", markers_summary(markers))
        self.assertIn("dragón", markers_summary(markers))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp()) / "recs"
        self.directory.mkdir(parents=True)
        self.library = RecordingLibrary(self.directory)

    def make_video(self, name: str, size: int, mtime: float) -> Path:
        path = self.directory / name
        path.write_bytes(b"x" * size)
        os.utime(path, (mtime, mtime))
        return path

    def test_limit_keeps_newest_and_removes_oldest(self):
        old = self.make_video("Solralol_a.mp4", 400, 1000.0)
        mid = self.make_video("Solralol_b.mp4", 400, 2000.0)
        new = self.make_video("Solralol_c.mp4", 400, 3000.0)

        removed = self.library.enforce_storage_limit(800, keep_path=new)

        self.assertEqual(removed, [old])
        self.assertFalse(old.exists())
        self.assertTrue(mid.exists())
        self.assertTrue(new.exists())
        self.assertLessEqual(self.library.total_size_bytes(), 800)

    def test_newest_is_never_deleted(self):
        only = self.make_video("unica.mp4", 5000, 1000.0)
        removed = self.library.enforce_storage_limit(10)
        self.assertEqual(removed, [])
        self.assertTrue(only.exists())

    def test_delete_removes_video_and_sidecar(self):
        video = self.make_video("x.mp4", 100, 1000.0)
        self.library.write_metadata(video, {"markers": []})
        self.assertTrue(video.with_suffix(".json").exists())
        self.assertTrue(self.library.delete(video))
        self.assertFalse(video.exists())
        self.assertFalse(video.with_suffix(".json").exists())

    def test_list_newest_first_with_metadata(self):
        old = self.make_video("Solralol_old.mp4", 100, 1000.0)
        new = self.make_video("Solralol_new.mp4", 100, 2000.0)
        self.library.write_metadata(
            new,
            {
                "champion": "Jinx",
                "game_mode": "CLASSIC",
                "duration_seconds": 125,
                "complete": True,
                "markers": [
                    {
                        "time": 30.0,
                        "kind": "kill",
                        "label": "Asesinato",
                        "detail": "Asesinato 1",
                    }
                ],
            },
        )
        entries = self.library.list_recordings()
        self.assertEqual(
            [entry["name"] for entry in entries],
            ["Solralol_new.mp4", "Solralol_old.mp4"],
        )
        first = entries[0]
        self.assertEqual(first["title"], "Jinx")
        self.assertEqual(first["duration_label"], "02:05")
        self.assertEqual(first["counts"], {"kill": 1})
        self.assertIn("asesinato", first["summary"])
        self.assertEqual(entries[1]["complete"], False)

    def test_names_and_formats(self):
        name = suggest_recording_name(champion='A:di/B?di"C*')
        self.assertTrue(name.startswith("Solralol_"))
        self.assertTrue(name.endswith(".mp4"))
        self.assertNotIn(":", name)
        self.assertEqual(sanitize_filename_part(""), "partida")
        self.assertEqual(format_duration(3725), "1:02:05")
        self.assertEqual(format_duration("nope"), "00:00")
        self.assertIn("GB", format_size(2 * 1024**3))
        self.assertIn("MB", format_size(1024**2))


class AudioPickTests(unittest.TestCase):
    def test_picks_loopback_and_microphone(self):
        devices = ["Microfono (Realtek)", "Stereo Mix (Realtek)"]
        self.assertEqual(
            pick_game_audio_device(devices), "Stereo Mix (Realtek)"
        )
        self.assertEqual(
            pick_microphone_device(devices), "Microfono (Realtek)"
        )
        self.assertEqual(pick_game_audio_device([]), "")
        self.assertEqual(
            pick_microphone_device(["Altavoces"]), "Altavoces"
        )


class SliderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_marker_positions_are_proportional(self):
        slider = MarkerSlider()
        slider.resize(400, 24)
        slider.set_markers(
            [
                {
                    "time": 60.0,
                    "kind": "kill",
                    "label": "Asesinato",
                    "detail": "Asesinato 1",
                },
                {"time": "mala", "kind": "kill"},
            ],
            120000,
        )
        self.assertEqual(len(slider.markers), 1)
        middle = slider._x_for_seconds(60.0)
        start = slider._x_for_seconds(0.0)
        end = slider._x_for_seconds(120.0)
        self.assertIsNotNone(middle)
        self.assertGreater(middle, start)
        self.assertLess(middle, end)
        slider.close()
        slider.deleteLater()
        self.app.processEvents()


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def refresh_page(self, page, timeout: float = 5.0) -> None:
        """Refresca la pestaña y espera a que el worker entregue la lista.

        El listado de grabaciones se lee en segundo plano (``AsyncTask``), así
        que tras ``refresh()`` ya no basta con procesar un par de eventos: hay
        que procesar hasta que el escaneo en curso termine y se pinten las
        filas.
        """
        page.refresh()
        self.wait_for_scan(page, timeout)

    def wait_for_scan(self, page, timeout: float = 5.0) -> None:
        """Procesa eventos hasta que el escaneo de grabaciones termine."""
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            self.app.processEvents()

            if page._scan_task is None and not page._scan_pending:
                return

            time.sleep(0.005)

        raise AssertionError("el refresco de grabaciones no terminó")

    def make_page(self):
        directory = Path(tempfile.mkdtemp()) / "recs"
        directory.mkdir(parents=True)
        library = RecordingLibrary(directory)
        video = directory / "Solralol_x.mp4"
        video.write_bytes(b"x" * 2048)
        library.write_metadata(
            video,
            {
                "champion": "Ahri",
                "game_mode": "CLASSIC",
                "duration_seconds": 65,
                "complete": True,
                "markers": [
                    {
                        "time": 10.0,
                        "kind": "death",
                        "label": "Muerte",
                        "detail": "Muerte 1",
                    }
                ],
            },
        )
        service = SimpleNamespace(
            is_recording=False,
            output_path=None,
            elapsed_seconds=lambda: 0.0,
            started=Mock(),
            finished=Mock(),
            failed=Mock(),
            state_changed=Mock(),
        )
        page = RecordingsPage(library, service)
        return page, directory

    def test_refresh_builds_rows(self):
        page, _directory = self.make_page()
        page.show()
        self.app.processEvents()
        self.refresh_page(page)
        titles = sorted(
            {
                label.text()
                for label in page.findChildren(QLabel, "recordingTitle")
            }
        )
        self.assertEqual(titles, ["Ahri"])
        self.assertGreaterEqual(len(page.entries), 1)
        page.play_entry(page.entries[0]["path"])
        self.app.processEvents()
        self.assertEqual(page.marker_list.count(), 1)
        self.assertIn("Muerte", page.marker_list.item(0).text())
        page.close()
        page.deleteLater()
        self.app.processEvents()

    def test_row_widgets_and_badge(self):
        page, _directory = self.make_page()
        page.show()
        self.app.processEvents()
        self.refresh_page(page)
        title = page.findChild(QLabel, "recordingTitle")
        row = title.parent()
        self.assertEqual(
            row.findChild(QLabel, "recordingBadge").text(), "Lista"
        )
        self.assertTrue(
            any(
                isinstance(child, QListWidget)
                for child in page.findChildren(QListWidget)
            )
        )
        page.close()
        page.deleteLater()
        self.app.processEvents()

    # -- borrado de grabaciones -------------------------------------------

    def confirm(self, answer):
        return patch.object(
            QMessageBox,
            "question",
            return_value=answer,
        )

    def test_delete_entry_removes_video_and_sidecar(self):
        page, _directory = self.make_page()
        page.show()
        self.app.processEvents()
        self.refresh_page(page)

        video = Path(page.entries[0]["path"])
        sidecar = video.with_suffix(".json")
        self.assertTrue(video.is_file())
        self.assertTrue(sidecar.is_file())

        with self.confirm(QMessageBox.StandardButton.Yes):
            page.delete_entry(video)
            self.app.processEvents()

        self.assertFalse(video.exists())
        self.assertFalse(sidecar.exists())
        self.wait_for_scan(page)
        self.assertEqual(page.entries, [])
        self.assertIsNone(page.current_path)

        page.close()
        page.deleteLater()
        self.app.processEvents()

    def test_delete_entry_cancelled_keeps_the_files(self):
        page, _directory = self.make_page()
        self.refresh_page(page)
        video = Path(page.entries[0]["path"])
        sidecar = video.with_suffix(".json")

        with self.confirm(QMessageBox.StandardButton.No):
            page.delete_entry(video)
            self.app.processEvents()

        self.assertTrue(video.is_file())
        self.assertTrue(sidecar.is_file())

        page.close()
        page.deleteLater()
        self.app.processEvents()

    def test_delete_entry_releases_the_player_and_resets_it(self):
        page, _directory = self.make_page()
        self.refresh_page(page)
        video = Path(page.entries[0]["path"])
        page.play_entry(video)
        self.app.processEvents()
        self.assertEqual(page.current_path, video)

        with self.confirm(QMessageBox.StandardButton.Yes):
            page.delete_entry(video)
            self.app.processEvents()

        self.assertFalse(video.exists())
        self.assertIsNone(page.current_path)
        self.assertFalse(page.play_button.isEnabled())
        self.assertEqual(page.marker_list.count(), 0)
        self.assertEqual(page.position_slider.markers, [])

        page.close()
        page.deleteLater()
        self.app.processEvents()

    def test_delete_entry_warns_when_the_file_is_locked(self):
        import sys

        if sys.platform != "win32":
            self.skipTest("bloqueo de ficheros propio de Windows")

        page, _directory = self.make_page()
        self.refresh_page(page)
        video = Path(page.entries[0]["path"])
        sidecar = video.with_suffix(".json")
        warnings: list[str] = []

        # Un handle abierto en Windows impide borrar el fichero.
        handle = open(video, "rb")
        try:
            with (
                self.confirm(QMessageBox.StandardButton.Yes),
                patch.object(
                    QMessageBox,
                    "warning",
                    side_effect=lambda *_a, **_k: warnings.append("w"),
                ),
            ):
                page.delete_entry(video)
                self.app.processEvents()
        finally:
            handle.close()

        self.assertTrue(video.is_file())
        self.assertFalse(sidecar.exists())
        self.assertEqual(len(warnings), 1)

        # Al soltar el fichero, el segundo intento ya borra.
        with self.confirm(QMessageBox.StandardButton.Yes):
            page.delete_entry(video)
            self.app.processEvents()

        self.assertFalse(video.exists())
        self.wait_for_scan(page)
        self.assertEqual(page.entries, [])

        page.close()
        page.deleteLater()
        self.app.processEvents()

    def test_delete_entry_refuses_the_recording_in_progress(self):
        page, directory = self.make_page()
        live = directory / "Solralol_live.mp4"
        live.write_bytes(b"y" * 1024)
        live_service = SimpleNamespace(
            is_recording=True,
            output_path=live,
            elapsed_seconds=lambda: 1.0,
            started=Mock(),
            finished=Mock(),
            failed=Mock(),
            state_changed=Mock(),
        )
        page.service = live_service
        self.refresh_page(page)

        asked: list[str] = []
        with (
            patch.object(
                QMessageBox,
                "question",
                side_effect=lambda *_a, **_k: asked.append("q")
                or QMessageBox.StandardButton.Yes,
            ),
            patch.object(
                QMessageBox,
                "information",
                side_effect=lambda *_a, **_k: asked.append("info"),
            ),
        ):
            page.delete_entry(live)
            self.app.processEvents()

        self.assertEqual(asked, ["info"])
        self.assertTrue(live.is_file())

        page.close()
        page.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
