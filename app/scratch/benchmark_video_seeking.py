"""Mide búsquedas FFmpeg en un MP4 sintético de dos horas.

No lee ni modifica grabaciones del usuario. Genera el vídeo en una carpeta
temporal y elimina automáticamente todos sus datos al finalizar.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg
from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QApplication


def benchmark_qt_player(video: Path) -> list[int]:
    """Mide llegada de un frame decodificado en el backend Qt de la app."""
    app = QApplication.instance() or QApplication([])
    player = QMediaPlayer()
    sink = QVideoSink()
    player.setVideoSink(sink)
    frame_times: list[int] = []
    sink.videoFrameChanged.connect(lambda frame: frame_times.append(frame.startTime()))
    player.setSource(QUrl.fromLocalFile(str(video)))

    def pump_until(predicate, timeout: float = 30.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.002)
        return False

    if not pump_until(lambda: player.duration() > 0):
        raise RuntimeError("Qt Multimedia no pudo leer la duración del MP4")
    print(f"Qt duration: {player.duration() / 1000:.1f}s")
    duration_seconds = player.duration() / 1000

    player.play()
    if not pump_until(lambda: bool(frame_times), timeout=10):
        raise RuntimeError("Qt Multimedia no entregó un frame inicial")

    # Reproduce la secuencia solicitada: 5 min -> 90 min -> 20 min -> cerca
    # del final, alternando adelante y atrás en la misma instancia de player.
    positions = sorted(
        {
            min(max(0, int(duration_seconds * fraction)), max(0, int(duration_seconds) - 1))
            for fraction in (0.125, 0.25, 0.5, 0.75, 0.95)
        }
    )
    # Orden no monótono para medir también backtracking, como al revisar
    # clips de partida: 5m -> 10m -> 20m -> atrás -> cerca del final.
    positions = [
        min(300, int(duration_seconds - 1)),
        min(900, int(duration_seconds - 1)),
        min(1200, int(duration_seconds - 1)),
        min(600, int(duration_seconds - 1)),
        min(5400, int(duration_seconds - 1)),
        *positions,
    ]
    measured: list[int] = []
    for seconds in dict.fromkeys(positions):
        frame_times.clear()
        requested_us = seconds * 1_000_000
        started = time.perf_counter()
        player.setPosition(seconds * 1000)
        arrived = pump_until(
            lambda target_us=requested_us: any(
                abs(frame_time - target_us) <= 3_000_000
                for frame_time in frame_times
                if frame_time >= 0
            ),
            timeout=15,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        frame_seconds = frame_times[-1] / 1_000_000 if frame_times else -1
        print(
            f"Qt decoded frame {seconds:4d}s: {elapsed_ms:.1f} ms; "
            f"frame={frame_seconds:.3f}s; arrived={arrived}"
        )
        measured.append(round(elapsed_ms))
    player.stop()
    player.setSource(QUrl())
    app.processEvents()
    return measured


def main() -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if len(sys.argv) > 1:
        video = Path(sys.argv[1]).expanduser().resolve(strict=True)
        print(f"Read-only test file: {video}; size={video.stat().st_size / 1024**3:.2f} GiB")
        info = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        print("\n".join(line.strip() for line in info.stderr.splitlines() if "Duration:" in line or "Video:" in line))
        benchmark_qt_player(video)
        return
    with tempfile.TemporaryDirectory(prefix="solralol-seek-bench-") as folder:
        video = Path(folder) / "synthetic-two-hours.mp4"
        generate = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30",
            "-t",
            "7200",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-g",
            "60",
            "-keyint_min",
            "60",
            "-sc_threshold",
            "0",
            "-b:v",
            "250k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ]
        started = time.perf_counter()
        subprocess.run(generate, check=True, timeout=300)
        print(f"Generated 2h MP4 in {time.perf_counter() - started:.2f}s; size={video.stat().st_size / 1024**2:.1f} MiB")

        for seconds in (300, 5400, 1200, 7180, 600):
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(seconds),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-f",
                "null",
                "-",
            ]
            started = time.perf_counter()
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=30, check=False
            )
            elapsed = (time.perf_counter() - started) * 1000
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            print(f"seek {seconds:4d}s: {elapsed:.1f} ms")

        benchmark_qt_player(video)


if __name__ == "__main__":
    main()
