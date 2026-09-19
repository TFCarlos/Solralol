"""Vista previa offscreen de los tres paneles del overlay.

Genera PNG en scratch/overlay_preview_gold.png, overlay_preview_alerts.png y
overlay_preview_threat.png sobre un snapshot sintético con oro, una compra
reciente de objeto completo y un Dragón a punto de aparecer.

Ejecutar:
    .venv\\Scripts\\python.exe scratch/preview_overlays.py
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONIOENCODING"] = "utf-8"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import requests  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.ui.overlay_window import (  # noqa: E402
    GoldPanel,
    AlertsPanel,
    ThreatPanel,
    OverlayWindow,
)
from scratch.test_overlays import (  # noqa: E402
    ITEMS,
    item,
    snapshot,
    FULL_ORDER,
    FULL_CHAOS,
)


class _MemorySettings:
    """Ajustes en memoria: la vista previa no debe tocar settings.json."""

    def __init__(self):
        self.settings: dict = {}

    def load(self):
        return dict(self.settings)

    def save(self, settings):
        self.settings = dict(settings)


def main() -> int:
    app = QApplication.instance() or QApplication([])

    # El modo offscreen puede quedarse sin fuentes: carga una del sistema solo
    # para que la vista previa sea legible (la app real usa las del SO).
    for candidate in (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        if (
            Path(candidate).exists()
            and QFontDatabase.addApplicationFont(candidate) >= 0
        ):
            print("fuente cargada:", candidate)
            break

    with patch.object(
        requests, "get", side_effect=AssertionError("sin red")
    ):
        overlay = OverlayWindow(
            {"items": ITEMS},
            settings_service=_MemorySettings(),
            settings={},
        )
        # La vista previa es silenciosa: no interesa oír los pitidos.
        overlay.set_sound_enabled(False)

        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        aatrox = dict(changed[0])
        aatrox["items"] = list(aatrox["items"]) + [item(3078, 3)]
        changed[0] = aatrox
        jinx = dict(changed[8])
        jinx["items"] = list(jinx["items"]) + [item(3085, 2)]
        changed[8] = jinx

        overlay.update_snapshot(snapshot(240.0))
        app.processEvents()
        overlay.update_snapshot(
            snapshot(242.0, all_players=changed)
        )
        app.processEvents()

        gold = overlay.panels["gold"]
        alerts = overlay.panels["alerts"]
        threat = overlay.panels["threat"]

        for name, panel in (
            ("gold", gold),
            ("alerts", alerts),
            ("threat", threat),
        ):
            panel.show()
            app.processEvents()
            panel.adjustSize()
            app.processEvents()
            pixmap = panel.grab()
            path = ROOT / "scratch" / f"overlay_preview_{name}.png"
            pixmap.save(str(path))
            print(
                f"{name}: {path} "
                f"({pixmap.width()}x{pixmap.height()}) "
                f"visible={panel.isVisible()}"
            )
            print(
                f"  filas: {len(getattr(panel, 'rows', []))} | "
                f"alto panel: {panel.height()} | card: {panel.card.height()}"
            )

        overlay.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
