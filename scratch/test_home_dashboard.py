import sys
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)

item_catalog = {"items": {}}
window = MainWindow(version="15.16.1", item_catalog=item_catalog)

# Datos de prueba de perfil
mock_profile = {
    "game_name": "Solrasar",
    "tag_line": "000",
    "riot_id": "Solrasar#000",
    "profile_icon_id": 1234,
    "summoner_level": 248,
    "ranked_solo": {
        "tier": "EMERALD",
        "rank": "II",
        "league_points": 65,
        "wins": 38,
        "losses": 26,
        "winrate": 59.4,
        "tier_formatted": "ESMERALDA II · 65 LP",
    }
}

# Datos de prueba de historial
mock_history = [
    {"champion_name": "Ahri", "win": True},
    {"champion_name": "Ahri", "win": True},
    {"champion_name": "Sylas", "win": False},
    {"champion_name": "Ahri", "win": True},
    {"champion_name": "Orianna", "win": False},
    {"champion_name": "Ahri", "win": True},
]

window.receive_summoner_profile(mock_profile)
print("[OK] Invocador perfil recibido y aplicado a la UI.")

window.update_soloq_dashboard_from_history(mock_history)
print("[OK] Gráfica de SoloQ y Campeón más jugado actualizados.")

assert window.summoner_riot_id_label.text() == "Solrasar#000"
assert "ESMERALDA II" in window.soloq_tier_badge.text()
assert "Ahri" in window.most_played_title.text()
print("[EXITO] Todas las comprobaciones del Dashboard del Invocador en Inicio han pasado.")

