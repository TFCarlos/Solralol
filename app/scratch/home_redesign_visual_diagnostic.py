"""Captura una maqueta local del nuevo dashboard para revisar la composición."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QVBoxLayout

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.ui.home_dashboard import HomeDashboard
from app.ui.main_window import Backdrop
from app.ui.tema import aplicar_tema


def main() -> int:
    """Guarda una captura amplia con datos visuales sintéticos, sin tocar cuentas."""
    app = QApplication.instance() or QApplication([])
    backdrop = Backdrop()
    backdrop.establecer_modo_home(True)
    aplicar_tema(backdrop)
    backdrop.resize(1600, 1000)
    layout = QVBoxLayout(backdrop)
    layout.setContentsMargins(24, 20, 24, 20)
    dashboard = HomeDashboard()
    layout.addWidget(dashboard)
    splash = ROOT / "data" / "champion_splashes" / "Blitzcrank_0.jpg"
    if splash.is_file():
        backdrop._imagen_splash = QPixmap(str(splash))
    inicio = datetime(2026, 10, 11, 18, tzinfo=timezone.utc)
    matches = [
        {
            "stable_match_id": f"demo-{index}",
            "result": "victory" if index % 3 else "defeat",
            "champion_name": ("Briar", "Kayn", "Gragas")[index % 3],
            "lane": ("jungle", "mid", "support")[index % 3],
            "kills": 8 + index % 5,
            "deaths": 2 + index % 4,
            "assists": 5 + index % 7,
            "cs": 150 + index,
            "duration_seconds": 1800 + index * 10,
            "items": [],
            "mode": "Normal",
            "queue_id": 420,
            "lp_delta": 15 if index % 3 else -20,
            "started_at": (inicio + timedelta(minutes=index)).isoformat(),
        }
        for index in range(20)
    ]
    from app.services.home_history_service import analyze_home_history

    history = {"matches": matches, "last_sync": "diagnostic"}
    analytics = analyze_home_history(matches)
    dashboard.set_dashboard_data(
        {
            "gameName": "Solrasar",
            "tagLine": "EUW",
            "summonerLevel": 365,
            "region": "EUW",
            "ranked": [
                {
                    "queue": "RANKED_SOLO_5x5",
                    "tier": "PLATINUM",
                    "division": "III",
                    "league_points": 64,
                    "wins": 12,
                    "losses": 8,
                }
            ],
        },
        history,
        analytics,
        "Cliente local conectado · listo para sincronizar",
    )
    backdrop.show()
    dashboard.resize(1540, 950)
    app.processEvents()
    destino = Path(__file__).with_name("home_redesign_preview.png")
    if not backdrop.grab().save(str(destino)):
        return 2
    print(f"preview={destino}")
    backdrop.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
