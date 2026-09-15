import sys
from PySide6.QtWidgets import QApplication
from app.services.match_log_service import MatchLogService
from app.ui.live_match_analysis_dialog import LiveMatchAnalysisDialog
from app.services.data_dragon_assets import DataDragonAssetService

app = QApplication.instance() or QApplication(sys.argv)

mock_session = {
    "session_id": "2026-09-15T09-50-00_Ahri",
    "started_at": "2026-09-15T09:50:00.000000+00:00",
    "ended_at": "2026-09-15T10:15:00.000000+00:00",
    "duration": 1500.0,
    "game_mode": "CLASSIC",
    "champion_name": "Ahri",
    "player_riot_id": "Solra#EUW",
    "local_team": "ORDER",
    "winning_team": "ORDER",
    "local_player_key": "player_1",
    "players": {
        "player_1": {
            "champion_name": "Ahri",
            "riot_id": "Solra#EUW",
            "team": "ORDER",
            "role": "MIDDLE",
            "win": True,
            "kills": 8,
            "deaths": 2,
            "assists": 10,
            "cs": 185,
            "estimated_gold": 12500,
            "final": {
                "kills": 8,
                "deaths": 2,
                "assists": 10,
                "cs_total": 185,
                "gold_earned": 12500,
                "total_damage_dealt_to_champions": 24500,
                "damage_dealt_to_objectives": 8500,
                "total_damage_taken": 12000,
                "vision_score": 28,
                "items": [3006, 6655, 3089, 3135],
                "win": True,
            }
        },
        "player_2": {
            "champion_name": "Sylas",
            "riot_id": "Rival#EUW",
            "team": "CHAOS",
            "role": "MIDDLE",
            "win": False,
            "kills": 3,
            "deaths": 7,
            "assists": 4,
            "cs": 150,
            "estimated_gold": 9200,
            "final": {
                "kills": 3,
                "deaths": 7,
                "assists": 4,
                "cs_total": 150,
                "gold_earned": 9200,
                "total_damage_dealt_to_champions": 18000,
                "items": [3152, 3100],
                "win": False,
            }
        }
    },
    "lane_matchups": {
        "MIDDLE": {"ally_key": "player_1", "enemy_key": "player_2"},
        "TOP": {"ally_key": None, "enemy_key": None},
        "JUNGLE": {"ally_key": None, "enemy_key": None},
        "BOTTOM": {"ally_key": None, "enemy_key": None},
        "UTILITY": {"ally_key": None, "enemy_key": None},
    },
    "events": [
        {
            "time": 210.0,
            "time_label": "03:30",
            "order": 1,
            "type": "kill_exact",
            "player_key": "player_1",
            "killer_key": "player_1",
            "victim_key": "player_2",
            "label": "Ahri asesinó a Sylas",
        },
        {
            "time": 240.0,
            "time_label": "04:00",
            "order": 2,
            "type": "item_purchased",
            "player_key": "player_1",
            "item_name": "Capítulo Perdido",
            "label": "Compró Capítulo Perdido",
        },
        {
            "time": 600.0,
            "time_label": "10:00",
            "order": 3,
            "type": "objective",
            "player_key": "player_1",
            "label": "Equipo aliado consiguió Heraldo",
            "objective": "Heraldo",
        }
    ]
}

log_service = MatchLogService()
log_service.save_match_log(mock_session)
log_data, log_txt = log_service.get_match_log(mock_session)

print("--- CONTENIDO DEL LOG ---")
print(log_txt)
print("-------------------------")

assert "Ahri" in log_txt
assert "Sylas" in log_txt
assert "VICTORIA" in log_txt
assert "DERROTA" in log_txt

assets = DataDragonAssetService()
dialog = LiveMatchAnalysisDialog(mock_session, assets, {})
dialog.show_ai_analysis()
assert dialog.current_view == "ai_analysis"

print("[EXITO] Todas las comprobaciones y verificaciones del log han pasado.")
