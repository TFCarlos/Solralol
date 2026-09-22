"""Mide el coste real de refrescar y borrar en «Partidas guardadas».

Uso: python scratch/perf_saved_games_delete.py
Genera N sesiones y M grabaciones sintéticas (sidecars con marcadores
realistas) y cronometra refresh_saved_games en frío/caliente y el borrado
completo de una partida con su vídeo.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

SESSIONS = 40
VIDEOS = 30

#: Carpeta de grabaciones del guion: los ajustes simulados la devuelven para
#: que los refrescos asíncronos (que releen el directorio desde los ajustes)
#: no apunten nunca a la carpeta real del usuario.
PERF_RECORDINGS_DIR = Path(tempfile.mkdtemp()) / "recs"
PERF_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def fake_settings_factory():
    class FakeSettingsService:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def load(self) -> dict:
            return {
                "recording_output_dir": str(PERF_RECORDINGS_DIR),
            }

        def save(self, settings: dict) -> None:
            pass

    return FakeSettingsService


def wait_for_saved_games(window, app, timeout: float = 15.0) -> None:
    """Procesa eventos hasta que el worker de «Partidas guardadas» termine.

    El refresco es asíncrono (``AsyncTask``): la llamada vuelve al instante y
    las filas aparecen cuando el worker entrega el resultado.
    """
    deadline = time.perf_counter() + timeout

    while time.perf_counter() < deadline:
        app.processEvents()

        if not window.saved_games_refreshing:
            return

        time.sleep(0.005)

    raise AssertionError("refresh_saved_games no terminó")


def make_session(index: int) -> dict:
    return {
        "session_id": f"sesion-{index:03d}",
        "champion_name": "Briar",
        "game_mode": "CLASSIC",
        "duration": 1800,
        "local_player_key": "local",
        "players": {"local": {"win": True}, "enemy": {"win": False}},
        "started_at": "2026-09-19T12:00:00",
        "ended_at": "2026-09-19T12:30:00",
        "final_sync": {"status": "synced", "message": "ok"},
        "events": [
            {"time": float(t), "type": "kill", "label": f"k{t}"}
            for t in range(200)
        ],
    }


def main() -> None:
    app = QApplication.instance() or QApplication([])

    with patch(
        "app.ui.main_window.SettingsService", new=fake_settings_factory()
    ):
        from app.ui.main_window import MainWindow

        window = MainWindow(version="perf", item_catalog={"items": {}})
        window.poll_timer.stop()
        window.live_match_tracker.sessions_path = (
            Path(tempfile.mkdtemp()) / "live_match_sessions.json"
        )
        # La biblioteca ya apunta a la carpeta temporal de los ajustes: se
        # reafirma por si algún refresco posterior releyera el directorio.
        recs = PERF_RECORDINGS_DIR
        window.recording_library.set_directory(recs)

        library = window.recording_library
        tracker = window.live_match_tracker

        sessions = [make_session(i) for i in range(SESSIONS)]
        tracker._save_sessions(sessions)

        for i in range(VIDEOS):
            video = recs / f"Solralol_perf_{i:03d}.mp4"
            video.write_bytes(b"x" * 4096)
            library.write_metadata(
                video,
                {
                    # La primera grabación pertenece a la primera sesión:
                    # así el borrado ejercita la cascada partida → vídeo.
                    "session_id": (
                        "sesion-000" if i == 0 else f"rec-{i:03d}"
                    ),
                    "champion": "Briar",
                    "game_mode": "CLASSIC",
                    "complete": True,
                    "duration_seconds": 1800.0,
                    "game_time_offset": 0.0,
                    "markers": [
                        {"time": float(t), "type": "kill", "label": "x"}
                        for t in range(120)
                    ],
                },
            )

        window.app = app

        app.processEvents()

        # La llamada vuelve al instante: solo encola el trabajo en un worker.
        start = time.perf_counter()
        window.refresh_saved_games()
        enqueue_ms = (time.perf_counter() - start) * 1000.0

        # Frío: primera pasada lee las sesiones y todos los sidecars.
        rows_before = window.saved_games_layout.count()
        start = time.perf_counter()
        wait_for_saved_games(window, app)
        cold = time.perf_counter() - start

        # Mientras tanto la interfaz siguió viva (filas anteriores
        # presentadas, sin congelarse en la llamada de arriba).
        window.refresh_saved_games()
        start = time.perf_counter()
        wait_for_saved_games(window, app)
        warm = time.perf_counter() - start

        print(f"refresh_saved_games encola: {enqueue_ms:8.1f} ms")
        print(f"refresh_saved_games frío   : {cold * 1000:8.1f} ms")
        print(f"refresh_saved_games caliente: {warm * 1000:8.1f} ms")

        # Coste puro de resolver el vídeo de las 40 sesiones, con y sin
        # caché de sidecars (lo que consumía cada fila del refresco).
        sessions_list = window.live_match_tracker.load_saved_sessions()

        start = time.perf_counter()
        for session in sessions_list:
            window.find_recording_for_session(session)
        cached = time.perf_counter() - start

        original_cached = window.recording_metadata_cached

        def uncached(path):
            window.invalidate_recording_metadata_cache()
            return original_cached(path)

        window.recording_metadata_cached = uncached

        start = time.perf_counter()
        for session in sessions_list:
            window.find_recording_for_session(session)
        uncached_ms = time.perf_counter() - start

        window.recording_metadata_cached = original_cached

        print(f"40×find_recording (caché)  : {cached * 1000:8.1f} ms")
        print(f"40×find_recording (sin caché): {uncached_ms * 1000:6.1f} ms")

        start = time.perf_counter()
        window.delete_saved_game_session("sesion-000")
        wait_for_saved_games(window, app)
        delete = time.perf_counter() - start
        print(f"delete_saved_game_session   : {delete * 1000:8.1f} ms")

        rows = window.saved_games_layout.count()
        print(f"filas tras borrar           : {rows}")
        assert not list(recs.glob("Solralol_perf_000*")), "vídeo no borrado"
        assert (
            not window.live_match_tracker.load_saved_sessions()
            or window.live_match_tracker.load_saved_sessions()[0][
                "session_id"
            ]
            != "sesion-000"
        )

        window.close()
        app.processEvents()

    print("PERF OK")


if __name__ == "__main__":
    main()
