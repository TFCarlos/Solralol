import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.ui.postgame_replay_window import PostgameReplayWindow

APP = QApplication(sys.argv)

video_path = Path("scratch/data/test_video.mp4").resolve()
session = {
    "local_player_key": "local",
    "local_team": "ORDER",
    "champion_name": "Tryndamere",
    "duration_seconds": 120.0,
    "game_mode": "CLASSIC",
    "players": {
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
    },
    "events": [],
    "snapshots": [],
    "final_scoreboard": {},
    "version": "16.18.1",
    "lane_matchups": {},
    "metrics": {},
    "updated_at": "",
    "ended_at": "",
    "final_sync": {"status": "live_only"},
}

window = PostgameReplayWindow(
    video_path=str(video_path),
    session=session,
    item_catalog={},
    parent=None,
)
print("replay window opened ok")
