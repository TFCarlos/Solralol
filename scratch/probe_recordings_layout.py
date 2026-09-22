"""Sonda offscreen de la pestaña Grabaciones: geometría y tarjeta ESTADÍSTICAS.

Ejecutar: .venv\\Scripts\\python.exe scratch/probe_recordings_layout.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.recording_service import RecordingLibrary  # noqa: E402
from app.ui.recordings_page import RecordingsPage  # noqa: E402
from app.ui.styles import CONTROL_WINDOW_STYLE  # noqa: E402

MARKERS = [
    {"time": 10.0, "kind": "kill", "label": "Asesinato 1", "detail": "x"},
    {"time": 20.0, "kind": "death", "label": "Muerte 1", "detail": "x"},
    {"time": 30.0, "kind": "assist", "label": "Asistencia 1", "detail": "x"},
    {"time": 40.0, "kind": "dragon", "label": "Dragón", "detail": "x"},
]


def make_page(with_markers: bool) -> tuple[RecordingsPage, Path]:
    directory = Path(tempfile.mkdtemp()) / "recs"
    directory.mkdir(parents=True, exist_ok=True)
    library = RecordingLibrary(directory)

    video = directory / "Solralol_probe.mp4"
    make_real_video(video)
    library.write_metadata(
        video,
        {
            "champion": "Briar",
            "game_mode": "CLASSIC",
            "duration_seconds": 125,
            "complete": True,
            "markers": MARKERS if with_markers else [],
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
    page.setStyleSheet(CONTROL_WINDOW_STYLE)
    page.resize(1600, 1000)
    page.show()
    for _ in range(6):
        app.processEvents()
    return page, directory


def make_real_video(path: Path) -> None:
    """Genera un MP4 válido de 1 s con ffmpeg (color plano)."""
    import shutil
    import subprocess

    import imageio_ffmpeg  # type: ignore

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "color=c=blue:s=320x240:d=1",
            "-pix_fmt", "yuv420p",
            "-y",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if not path.exists():
        raise RuntimeError(result.stderr[-400:])


def geometry_report(page: RecordingsPage) -> dict[str, tuple[int, int, int, int]]:
    from PySide6.QtCore import QPoint

    def rect(widget) -> str:
        r = widget.rect()
        return f"({r.left()},{r.top()},{r.width()}x{r.height()})"

    card = page.video_widget.parentWidget()
    vr = page.video_widget.mapTo(page, QPoint(0, 0))
    vsize = page.video_widget.size()
    cr = card.mapTo(page, QPoint(0, 0))
    csize = card.size()
    kda = page.kda_value.parentWidget()

    return {
        "page": str(page.rect().width()) + "x" + str(page.rect().height()),
        "player_card": f"({cr.x()},{cr.y()},{csize.width()}x{csize.height()})",
        "video": f"({vr.x()},{vr.y()},{vsize.width()}x{vsize.height()})",
        "video_dentro_tarjeta": str(
            vr.x() >= cr.x()
            and vr.y() >= cr.y()
            and vr.x() + vsize.width() <= cr.x() + csize.width()
            and vr.y() + vsize.height() <= cr.y() + csize.height()
        ),
        "video_bottom_vs_card": f"video={vr.y() + vsize.height()} card={cr.y() + csize.height()}",
        "kda_card_size": f"{kda.size().width()}x{kda.size().height()}",
        "kda_title_height": str(kda.findChildren(type(page.kda_value))[0].size().height()),
        "marker_list": str(page.marker_list.size().height()),
        "slider": str(page.position_slider.size().height()),
    }



if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])

    def show(report: dict[str, str]) -> None:
        for key, value in report.items():
            print(f"  {key:24s} {value}")

    def run_case(width: int, height: int, with_markers: bool) -> None:
        page, _directory = make_page(with_markers)
        page.resize(width, height)
        for _ in range(6):
            app.processEvents()
        entries = page.entries
        page.play_entry(Path(entries[0]["path"]))
        for _ in range(4):
            app.processEvents()

        card = page.video_widget.parentWidget()
        vr = page.video_widget.mapTo(page, QPoint(0, 0))
        vsize = page.video_widget.size()
        cr = card.mapTo(page, QPoint(0, 0))
        csize = card.size()
        dentro_tarjeta = (
            vr.x() >= cr.x()
            and vr.y() >= cr.y()
            and vr.x() + vsize.width() <= cr.x() + csize.width()
            and vr.y() + vsize.height() <= cr.y() + csize.height()
        )
        card_dentro_pagina = cr.y() + csize.height() <= height

        print(f"--- {width}x{height} con_marcadores={with_markers} ---")
        show(geometry_report(page))
        print(f"  kda_text = {page.kda_value.text()!r}")
        print(f"  VIDEO_DENTRO_TARJETA={dentro_tarjeta}")
        print(f"  TARJETA_DENTRO_PAGINA={card_dentro_pagina} (card_bottom={cr.y() + csize.height()} > page={height}?)")

        page.close()
        page.deleteLater()
        app.processEvents()

    run_case(1600, 1000, True)
    run_case(1600, 1000, False)
    # Menos altura (pestañas más apretadas) y escala de DPI 150 %.
    run_case(1400, 760, False)
    run_case(1400, 760, True)

    QTimer.singleShot(0, app.quit)
    print("PROBE OK")
