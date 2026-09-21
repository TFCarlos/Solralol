"""Renderiza el panel de marcadores del postgame a PNG (revisión visual).

Genera ``scratch/postgame_cards_preview.png`` con las dos columnas y sus
tarjetas tal y como se ven en la app, aplicando el mismo stylesheet que la
ventana de repaso.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.ui.postgame_sidebar import PostgameSidebar
from app.ui.styles import CONTROL_WINDOW_STYLE

ROOT = Path(__file__).resolve().parent.parent

APP = QApplication(sys.argv)
APP.setStyleSheet(CONTROL_WINDOW_STYLE)


def load_catalog() -> dict:
    path = ROOT / "data" / "items.json"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


ORDER = {
    "a1": ("Camille", "TOP", [3074, 3153, 6333, 3071, 3053, 3143], 18, 9, 3, 6, 214, 16220, 41),
    "a2": ("Lee Sin", "JUNGLE", [6692, 3111, 6333, 3053, 3071, 3143], 17, 5, 6, 12, 168, 13480, 33),
    "a3": ("Ahri", "MIDDLE", [6655, 3020, 4645, 3157, 3089, 3135], 18, 11, 4, 9, 231, 17890, 28),
    "a4": ("Jinx", "BOTTOM", [6673, 3006, 3031, 3072, 3036, 3035], 18, 12, 2, 10, 245, 18420, 22),
    "a5": ("Thresh", "UTILITY", [3860, 3190, 3222, 3107, 3050, 3190], 16, 2, 8, 21, 48, 10240, 96),
}

CHAOS = {
    "e1": ("Aatrox", "TOP", [3074, 3153, 6333, 3053], 17, 3, 7, 4, 189, 12980, 18),
    "e2": ("Vi", "JUNGLE", [6692, 3111, 3071], 16, 4, 8, 7, 141, 11020, 15),
    "e3": ("Syndra", "MIDDLE", [6655, 3020, 4645, 3157], 17, 6, 5, 5, 205, 14100, 19),
    "e4": ("Kai'Sa", "BOTTOM", [6673, 3006, 3031], 17, 8, 4, 6, 210, 15640, 12),
    "e5": ("Nautilus", "UTILITY", [3860, 3190, 3222], 15, 1, 9, 14, 39, 8920, 74),
}


def build_session() -> dict:
    players: dict = {}
    scoreboard: dict = {}

    for key, (champ, role, items, level, k, d, a, cs, gold, vision) in (
        {**ORDER, **CHAOS}
    ).items():
        team = "ORDER" if key.startswith("a") else "CHAOS"
        players[key] = {
            "champion_name": champ,
            "team": team,
            "role": role,
            "riot_id": f"{champ}#EUW",
            "win": team == "ORDER",
        }
        scoreboard[key] = {
            "kills": k,
            "deaths": d,
            "assists": a,
            "cs": cs,
            "level": level,
            "estimated_gold": gold,
            "stats": {"vision_score": vision},
            "items": items,
        }

    return {
        "local_player_key": "a1",
        "local_team": "ORDER",
        "champion_name": "Camille",
        "duration": 1812.0,
        "game_mode": "CLASSIC",
        "game_version": "16.18.1",
        "players": players,
        "events": [],
        "snapshots": [],
        "final_scoreboard": scoreboard,
        "final_sync": {"status": "live_only"},
    }


def main() -> None:
    session = build_session()
    sidebar = PostgameSidebar(session)
    catalog = load_catalog()
    # El catálogo real llega del window padre; aquí se inyecta para el preview.
    sidebar._catalog = lambda: catalog
    sidebar.resize(660, 780)
    sidebar.show()
    APP.processEvents()

    output = ROOT / "scratch" / "postgame_cards_preview.png"
    pixmap = sidebar.grab()
    pixmap.save(str(output))
    print(f"saved {output} ({pixmap.width()}x{pixmap.height()})")


if __name__ == "__main__":
    main()
