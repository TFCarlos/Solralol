"""
Postgame-only smoke: ensures one icon per card, one KDA in the top-right, etc.
"""
from __future__ import annotations

import sys
from typing import Any

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.ui.postgame_sidebar import PostgameSidebar

APP = QApplication(sys.argv)


def find_by_object_name(parent: QWidget, name: str) -> list[QLabel]:
    out: list[QLabel] = []
    for obj in parent.findChildren(QLabel):
        try:
            if obj.objectName() == name:
                out.append(obj)
        except Exception:
            continue
    return out


def minimal_session(
    players: dict[str, dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    local_player_key: str = "local",
    local_team: str = "ORDER",
    champion_name: str = "Tryndamere",
    duration_seconds: float = 120.0,
    game_mode: str = "CLASSIC",
) -> dict[str, Any]:
    session: dict[str, Any] = {
        "local_player_key": local_player_key,
        "local_team": local_team,
        "champion_name": champion_name,
        "duration_seconds": duration_seconds,
        "game_mode": game_mode,
        "players": players,
        "events": events or [],
        "snapshots": [],
        "final_scoreboard": {},
        "version": "16.18.1",
    }
    return session


def test_postgame_sidebar_builds_cards() -> None:
    players = {
        "local": {
            "champion_name": "Tryndamere",
            "team": "ORDER",
            "role": "TOP",
            "level": 18,
            "kills": 7,
            "deaths": 2,
            "assists": 5,
            "cs": 150,
            "estimated_gold": 12000,
            "win": True,
        },
        "enemy": {
            "champion_name": "Jinx",
            "team": "CHAOS",
            "role": "ADC",
            "level": 17,
            "kills": 5,
            "deaths": 3,
            "assists": 8,
            "cs": 140,
            "estimated_gold": 11500,
            "win": False,
        },
    }
    session = minimal_session(
        players=players,
        events=[
            {
                "time": 60.0,
                "type": "kill",
                "player_key": "local",
                "killer_key": "local",
                "victim_key": "enemy",
                "assister_keys": [],
                "team": "ORDER",
            }
        ],
    )

    sidebar = PostgameSidebar()
    sidebar.set_session(session)
    sidebar.refresh()

    names = find_by_object_name(sidebar, "postgameChampionName")
    assert len(names) >= 2, f"expected at least 2 name labels, got {len(names)}"
    for label in names:
        assert label.text(), f"name label empty: {label}"

    kdAs = find_by_object_name(sidebar, "postgameStatKda")
    assert len(kdAs) >= 2, f"expected at least 2 KDA labels, got {len(kdAs)}"
    for label in kdAs:
        assert label.text(), f"KDA label empty: {label}"
        # Expected format: "kills / deaths / assists"
        parts = label.text().split("/")
        assert len(parts) == 3, f"unexpected KDA format: {label.text()!r}"

    # One KDA per card, only above the role/level row.
    from PySide6.QtWidgets import QFrame

    cards = sidebar.findChildren(QFrame)
    cards = [c for c in cards if c.objectName() == "postgamePlayerCard"]
    assert len(kdAs) == len(cards), f"expected one KDA per card, got {len(kdAs)} KDA and {len(cards)} cards"

    # No small icon (single icon only).
    small_icons = find_by_object_name(sidebar, "postgameChampionIconSmall")
    assert len(small_icons) == 0, f"expected no small icons, got {len(small_icons)}"

    print("[OK] postgame-only smoke")


if __name__ == "__main__":
    test_postgame_sidebar_builds_cards()
