import sys
from typing import Any
from pathlib import Path

from PySide6.QtCore import QProcess, Signal, QObject
from PySide6.QtWidgets import QApplication

from app.ui.recordings_page import RecordingsPage, RecordingLibrary


class MinimalRecordingService(QObject):
    started = Signal(str)
    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._recording = False

    def is_recording(self) -> bool:
        return self._recording

    def elapsed_seconds(self) -> float:
        return 0.0

    def record(self, path: str, session: dict[str, Any] | None = None) -> None:
        self._recording = True

    def stop(self) -> None:
        self._recording = False


def main() -> None:
    APP = QApplication(sys.argv)

    library = RecordingLibrary()
    service = MinimalRecordingService()
    page = RecordingsPage(library=library, service=service)

    # 1) KDA card build
    kda_card = page._build_kda_card()
    assert kda_card.objectName() == "recordingKdaCard"
    assert kda_card.width() == 120

    # 2) Empty KDA (marcador de «sin datos», nunca texto vacío)
    page._update_kda_card()
    assert page.kda_value.text() == "—"
    assert not page.kda_objectives.isVisibleTo(page)

    # 3) With markers (set them on the slider because _update_kda_card reads from it)
    from app.ui.recordings_page import MarkerSlider

    slider = MarkerSlider()
    page.position_slider = slider
    slider.set_markers(
        [
            {"time": 60.0, "kind": "kill"},
            {"time": 70.0, "kind": "kill"},
            {"time": 90.0, "kind": "death"},
            {"time": 100.0, "kind": "assist"},
            {"time": 110.0, "kind": "assist"},
            {"time": 120.0, "kind": "assist"},
        ],
        0,
    )
    from collections import Counter
    counts = Counter(m.get("kind") for m in slider.markers if isinstance(m, dict))
    assert counts["kill"] == 2
    assert counts["death"] == 1
    assert counts["assist"] == 3

    page._update_kda_card()
    text = page.kda_value.text()
    assert "⚔ 2" in text and "✖ 1" in text and "✚ 3" in text, text

    # 4) Sync slider markers (no crash) and KDA still consistent
    slider.set_markers(
        [
            {"time": 10.0, "kind": "kill"},
            {"time": 20.0, "kind": "kill"},
            {"time": 30.0, "kind": "kill"},
            {"time": 40.0, "kind": "kill"},
            {"time": 50.0, "kind": "kill"},
            {"time": 60.0, "kind": "kill"},
            {"time": 70.0, "kind": "kill"},
        ],
        0,
    )
    counts = Counter(m.get("kind") for m in slider.markers if isinstance(m, dict))
    assert counts["kill"] == 7

    page._update_kda_card()
    text = page.kda_value.text()
    assert "⚔ 7" in text

    print("recordings page smoke ok")


if __name__ == "__main__":
    main()
