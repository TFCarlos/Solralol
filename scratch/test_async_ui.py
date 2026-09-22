"""Pruebas de la arquitectura asíncrona: la interfaz nunca se bloquea.

Comprueba que las operaciones pesadas (búsqueda de ffmpeg, sondeo de
dispositivos de audio, lectura de la carpeta de grabaciones y lectura de las
partidas guardadas) se ejecutan fuera del hilo principal, que la interfaz
muestra su estado «Cargando…» de inmediato y que el bucle de Qt sigue
atendiendo eventos —temporizadores, repintados, clics— mientras el worker
trabaja.

Uso::

    .venv\\Scripts\\python.exe -m unittest scratch.test_async_ui
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app.ui.async_task import TaskManager, run_async  # noqa: E402
from app.ui.recordings_page import RecordingsPage  # noqa: E402


class EventPump:
    """Procesa eventos de Qt y cuenta los latidos de un temporizador.

    Los latidos son la prueba objetiva de que el hilo principal estuvo vivo
    durante el trabajo de un worker: si el hilo se hubiera quedado bloqueado,
    el temporizador no se habría disparado.
    """

    def __init__(self, app: QApplication, interval_ms: int = 20) -> None:
        self.app = app
        self.ticks = 0
        self.timer = QTimer()
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self._on_tick)

    def _on_tick(self) -> None:
        self.ticks += 1

    def spin_until(self, predicate, timeout: float = 5.0) -> tuple[bool, int]:
        """Procesa eventos hasta que *predicate* se cumpla.

        Devuelve ``(cumplido, latidos)``.
        """
        before = self.ticks
        self.timer.start()
        deadline = time.monotonic() + timeout

        try:
            while time.monotonic() < deadline:
                self.app.processEvents()

                if predicate():
                    return True, self.ticks - before

                time.sleep(0.005)
        finally:
            self.timer.stop()

        return False, self.ticks - before

    def spin_for(self, seconds: float) -> int:
        """Procesa eventos durante *seconds* y devuelve los latidos."""
        return self.spin_until(lambda: False, timeout=seconds)[1]


class StubRecordingService(QObject):
    """Servicio de grabación mínimo para la pestaña de Grabaciones."""

    started = Signal(str)
    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)

    @property
    def is_recording(self) -> bool:
        return False

    def elapsed_seconds(self) -> float:
        return 0.0


class SlowLibrary:
    """Biblioteca de grabaciones cuyo listado tarda a propósito."""

    def __init__(self, entries: list[dict], delay: float = 0.3) -> None:
        self.entries = entries
        self.delay = delay
        self.calls = 0
        self.directory = Path(tempfile.mkdtemp())

    def list_recordings(self) -> list[dict]:
        self.calls += 1
        time.sleep(self.delay)

        return list(self.entries)

    def total_size_bytes(self) -> int:
        return 4096

    def load_metadata(self, _path) -> dict:
        return {}


def make_fake_settings(output_dir):
    """Servicio de ajustes en memoria que graba en *output_dir*.

    Así la ventana trabaja sobre una carpeta temporal (ni se lee ni se escribe
    nada de la carpeta real de grabaciones del usuario).
    """

    class FakeSettingsService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def load(self) -> dict:
            return {"recording_output_dir": str(output_dir)}

        def save(self, _settings: dict) -> None:
            pass

    return FakeSettingsService


class AsyncTaskTests(unittest.TestCase):
    """Infraestructura: entrega de resultados y descarte de sobrantes."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pump = EventPump(self.app)

    def test_result_arrives_on_the_gui_thread(self):
        seen = []

        run_async(
            lambda: 42,
            on_finished=lambda _token, result, error: seen.append(
                (result, error, threading.current_thread())
            ),
        )

        done, ticks = self.pump.spin_until(lambda: bool(seen))
        self.assertTrue(done, "el worker no entregó su resultado")
        self.assertGreaterEqual(ticks, 0)

        result, error, thread = seen[0]
        self.assertEqual(result, 42)
        self.assertIsNone(error)
        self.assertIs(thread, threading.main_thread())

    def test_worker_failure_is_reported_without_stopping_the_app(self):
        seen = []

        def boom():
            raise RuntimeError("fallo simulado del worker")

        run_async(
            boom,
            on_finished=lambda _token, result, error: seen.append(
                (result, error)
            ),
        )

        done, _ticks = self.pump.spin_until(lambda: bool(seen))
        self.assertTrue(done, "el error del worker no llegó a la GUI")

        result, error = seen[0]
        self.assertIsNone(result)
        self.assertIn("fallo simulado del worker", error or "")

    def test_event_loop_keeps_working_during_a_slow_task(self):
        seen = []
        ticks_at_arrival = None

        def heavy():
            time.sleep(0.4)

            return "listo"

        self.pump.timer.start()
        started = time.monotonic()

        run_async(
            heavy,
            on_finished=lambda _token, result, error: seen.append(result),
        )

        try:
            while time.monotonic() - started < 0.6:
                self.app.processEvents()

                if seen and ticks_at_arrival is None:
                    ticks_at_arrival = self.pump.ticks

                time.sleep(0.005)
        finally:
            self.pump.timer.stop()

        self.assertEqual(seen, ["listo"])
        # Mientras el worker dormía 400 ms, el temporizador de 20 ms siguió
        # latiendo: la interfaz pudo animar, repintar y atender clics.
        self.assertIsNotNone(ticks_at_arrival)
        self.assertGreaterEqual(ticks_at_arrival, 5)

    def test_task_manager_discards_superseded_results(self):
        manager = TaskManager()
        delivered = []

        def slow():
            time.sleep(0.3)

            return "viejo"

        def fast():
            return "nuevo"

        manager.start(
            "clave",
            slow,
            on_finished=lambda _token, result, _error: delivered.append(result),
        )
        manager.start(
            "clave",
            fast,
            on_finished=lambda _token, result, _error: delivered.append(result),
        )

        done, _ticks = self.pump.spin_until(lambda: bool(delivered))
        self.assertTrue(done)

        # Se le da tiempo al worker lento a terminar: su resultado llega
        # tarde y debe descartarse en vez de pisar el de la petición nueva.
        self.pump.spin_for(0.5)
        self.assertEqual(delivered, ["nuevo"])


class RecordingsPageAsyncTests(unittest.TestCase):
    """La pestaña Grabaciones lee la carpeta en un worker."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pump = EventPump(self.app)
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close()
            page.deleteLater()

        self.app.processEvents()

    def entry(self, name: str = "Solralol_test.mp4") -> dict:
        path = Path(tempfile.mkdtemp()) / name
        path.write_bytes(b"x" * 32)

        return {
            "path": path,
            "name": path.name,
            "title": "Briar",
            "subtitle": "Clásica",
            "summary": "",
            "date_label": "19/09/2026 12:00",
            "duration_label": "30:00",
            "size_label": "1,0 MB",
            "complete": True,
            "markers": [],
        }

    def build_page(self, library) -> RecordingsPage:
        page = RecordingsPage(
            library=library,
            service=StubRecordingService(),
        )
        self.pages.append(page)

        return page

    def test_refresh_returns_immediately_and_shows_loading(self):
        library = SlowLibrary([self.entry()], delay=0.3)
        page = self.build_page(library)

        start = time.perf_counter()
        page.refresh()
        elapsed = time.perf_counter() - start

        # La llamada vuelve al instante: el trabajo pesado está en el worker.
        self.assertLess(elapsed, 0.1)
        self.assertIn("Cargando", page.status_label.text())
        self.assertFalse(page.refresh_button.isEnabled())
        self.assertEqual(page.list_layout.count(), 0)

        done, ticks = self.pump.spin_until(lambda: page._scan_task is None)
        self.assertTrue(done, "el escaneo de grabaciones no terminó")
        # Mientras el worker leía el disco, el hilo principal siguió vivo.
        self.assertGreaterEqual(ticks, 3)

        self.assertEqual(library.calls, 1)
        self.assertEqual(len(page.entries), 1)
        self.assertGreater(page.list_layout.count(), 1)
        self.assertTrue(page.refresh_button.isEnabled())
        self.assertNotIn("Cargando grabaciones…", page.status_label.text())

    def test_extra_refreshes_are_coalesced(self):
        library = SlowLibrary([self.entry()], delay=0.25)
        page = self.build_page(library)

        page.refresh()
        started, _ticks = self.pump.spin_until(
            lambda: library.calls == 1, timeout=3.0
        )
        self.assertTrue(started, "el worker no llegó a arrancar")

        # Con el escaneo en vuelo, los refrescos extra se agrupan en uno solo.
        page.refresh()
        page.refresh()
        self.assertEqual(library.calls, 1)

        done, _ticks = self.pump.spin_until(
            lambda: page._scan_task is None and not page._scan_pending,
            timeout=5.0,
        )
        self.assertTrue(done)
        self.assertEqual(library.calls, 2)
        self.assertEqual(len(page.entries), 1)

    def test_scan_error_leaves_the_page_usable(self):
        class ExplodingLibrary(SlowLibrary):
            def list_recordings(self):
                self.calls += 1

                raise OSError("carpeta de grabaciones ilegible")

        page = self.build_page(ExplodingLibrary([]))
        page.refresh()

        done, _ticks = self.pump.spin_until(lambda: page._scan_task is None)
        self.assertTrue(done)
        self.assertIn(
            "No se pudieron leer las grabaciones",
            page.status_label.text(),
        )
        self.assertTrue(page.refresh_button.isEnabled())


class MainWindowAsyncTests(unittest.TestCase):
    """Arranque, Ajustes y Partidas guardadas sin bloquear el hilo de la GUI."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def slow_ffmpeg(*_args, **_kwargs) -> str:
        time.sleep(0.3)

        return "C:/ffmpeg/bin/ffmpeg.exe"

    @staticmethod
    def slow_devices(*_args, **_kwargs) -> list[str]:
        time.sleep(0.3)

        return ["Micrófono de prueba", "Altavoces de prueba"]

    def setUp(self):
        self.pump = EventPump(self.app)
        self.temp = Path(tempfile.mkdtemp())
        self.recordings_dir = self.temp / "recs"
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        patchers = [
            patch(
                "app.ui.main_window.SettingsService",
                new=make_fake_settings(self.recordings_dir),
            ),
            # Comprobaciones simuladas y lentas: deterministas y sin ffmpeg real.
            patch(
                "app.ui.main_window.find_ffmpeg",
                side_effect=self.slow_ffmpeg,
            ),
            patch(
                "app.ui.main_window.list_audio_devices",
                side_effect=self.slow_devices,
            ),
        ]

        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        from app.ui.main_window import MainWindow

        self.window = MainWindow(version="test", item_catalog={"items": {}})
        self.addCleanup(self.window.close)
        self.window.poll_timer.stop()

        # El registro de partidas también a una ruta temporal, antes de que el
        # QTimer.singleShot(0) del constructor dispare su lectura.
        self.window.live_match_tracker.sessions_path = (
            self.temp / "live_sessions.json"
        )
        self.window.invalidate_recording_metadata_cache()

    def settle(self, timeout: float = 20.0) -> tuple[bool, int]:
        """Procesa eventos hasta que la ventana no tenga trabajo en curso."""
        return self.pump.spin_until(
            lambda: self.window._devices_task is None
            and self.window._refresh_ffmpeg_task is None
            and not self.window.saved_games_refreshing,
            timeout=timeout,
        )

    def session(self, index: int) -> dict:
        return {
            "session_id": f"sesion-{index:03d}",
            "champion_name": "Briar",
            "game_mode": "CLASSIC",
            "duration": 1800,
            "local_player_key": "local",
            "players": {
                "local": {"win": True},
                "enemy": {"win": False},
            },
            "started_at": "2026-09-19T12:00:00",
            "ended_at": "2026-09-19T12:30:00",
            "final_sync": {"status": "synced", "message": "ok"},
            "events": [],
        }


    def test_startup_checks_do_not_block_the_window(self):
        window = self.window

        # Nada más construir la ventana, las dos comprobaciones están en vuelo
        # (búsqueda de ffmpeg recorriendo el PATH y sondeo de dispositivos).
        self.assertIsNotNone(window._refresh_ffmpeg_task)
        self.assertIsNotNone(window._devices_task)
        self.assertIn(
            "Buscando dispositivos de audio",
            window.recording_game_audio_combo.itemText(0),
        )
        self.assertFalse(window.recording_game_audio_combo.isEnabled())
        self.assertIn("Comprobando ffmpeg", window.recording_status.text())

        # Mientras los workers trabajan, la navegación sigue respondiendo.
        window.settings_button.click()
        self.assertEqual(
            window.pages.currentIndex(), window.SETTINGS_PAGE_INDEX
        )
        window.recordings_button.click()
        self.assertEqual(
            window.pages.currentIndex(), window.RECORDINGS_PAGE_INDEX
        )
        window.home_button.click()
        self.assertEqual(window.pages.currentIndex(), 0)

        done, ticks = self.settle()
        self.assertTrue(done, "las comprobaciones de arranque no terminaron")
        self.assertGreaterEqual(ticks, 5)

        self.assertNotIn(
            "Buscando",
            window.recording_game_audio_combo.itemText(0),
        )
        self.assertTrue(window.recording_game_audio_combo.isEnabled())
        self.assertNotIn("Comprobando ffmpeg", window.recording_status.text())
        self.assertIn("ffmpeg listo", window.recording_status.text())
        self.assertIn(
            "Micrófono de prueba",
            [
                window.recording_game_audio_combo.itemText(index)
                for index in range(
                    window.recording_game_audio_combo.count()
                )
            ],
        )

    def test_saved_games_are_gathered_in_the_background(self):
        self.settle()

        tracker = self.window.live_match_tracker
        tracker._save_sessions([self.session(i) for i in range(3)])

        # Grabación de la primera partida, con su sidecar.
        video = self.recordings_dir / "Solralol_2026-09-19_Briar.mp4"
        video.write_bytes(b"x" * 64)
        self.window.recording_library.write_metadata(
            video,
            {
                "session_id": "sesion-000",
                "champion": "Briar",
                "complete": True,
                "markers": [],
            },
        )
        self.window.invalidate_recording_metadata_cache()

        # Un fichero de sesiones enorme tardaría segundos en analizarse.
        original = tracker.load_saved_sessions

        def slow_load():
            time.sleep(0.3)

            return original()

        tracker.load_saved_sessions = slow_load

        # Si algo leyera el disco desde la GUI, este contador lo delataría.
        calls = []
        self.window.find_recording_for_session = (
            lambda session: calls.append(session) or ""
        )

        start = time.perf_counter()
        self.window.refresh_saved_games()
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 0.1)
        self.assertIn("Cargando", self.window.saved_games_status.text())
        self.assertEqual(calls, [])

        done, ticks = self.pump.spin_until(
            lambda: not self.window.saved_games_refreshing,
            timeout=10.0,
        )
        self.assertTrue(done, "la lectura de partidas guardadas no terminó")
        self.assertGreaterEqual(ticks, 3)

        self.assertEqual(
            self.window.saved_games_status.text(),
            "3 partida(s) guardada(s).",
        )
        self.assertEqual(
            self.window.session_recordings.get("sesion-000"), str(video)
        )
        # Las filas usan el vídeo ya resuelto por el worker.
        self.assertEqual(calls, [])
        self.assertGreaterEqual(self.window.saved_games_layout.count(), 4)

        buttons = [
            button.text()
            for button in self.window.saved_games_content.findChildren(
                QPushButton
            )
        ]
        self.assertIn("Repaso con vídeo", buttons)

    def test_saved_games_error_is_reported_without_stuck_state(self):
        self.settle()

        tracker = self.window.live_match_tracker

        def exploding():
            raise OSError("no se pudo leer el registro local")

        tracker.load_saved_sessions = exploding

        self.window.refresh_saved_games()

        done, _ticks = self.pump.spin_until(
            lambda: not self.window.saved_games_refreshing,
            timeout=10.0,
        )
        self.assertTrue(done)
        self.assertIn(
            "No se pudieron leer las partidas guardadas",
            self.window.saved_games_status.text(),
        )
        # El botón sigue operativo: la interfaz nunca se queda colgada.
        self.assertTrue(self.window.refresh_saved_games_button.isEnabled())


if __name__ == "__main__":
    unittest.main()

