"""Vista previa offscreen del panel de recomendaciones con afinidad en las compras."""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.ui.recommendation_panel import RecommendationPanel  # noqa: E402

players = {"me": {"champion_name": "Tryndamere", "team": "ORDER", "role": "JUNGLE"},
           "e0": {"champion_name": "Shen", "team": "CHAOS", "side": "enemy"},
           "e1": {"champion_name": "Hecarim", "team": "CHAOS", "side": "enemy"}}
points = {"me": {"items": [3074, 3047, 3035, 1001], "level": 5, "kills": 0, "deaths": 0, "assists": 0,
                 "current_gold": 803},
          "e0": {"items": [3075, 3083], "level": 4, "kills": 0, "deaths": 3, "assists": 0},
          "e1": {"items": [1036, 1001], "level": 4, "kills": 0, "deaths": 1, "assists": 0}}
session = {"local_player_key": "me", "local_team": "ORDER", "champion_name": "Tryndamere",
           "duration": 543, "game_mode": "CLASSIC", "players": players,
           "snapshots": [{"time": 543, "players": points}],
           "lane_matchups": {"JUNGLE": {"enemy_key": "e1"}}, "events": []}

app = QApplication.instance() or QApplication([])
panel = RecommendationPanel()
host = QWidget()
panel.setParent(host)
panel.configure(None, json.loads(open("data/items.json", encoding="utf-8").read()))
panel.update_recommendations(session)
host.resize(1160, 760)
panel.resize(1160, 760)
host.show()
panel.show()
app.processEvents()
for row in panel.report["purchases"]:
    print(row["id"], row["name"], "score:", row["score"], "afinidad:", row["affinity_percent"],
          "falta:", row["missing"], "oro:", row["cost"])
labels = [w.text() for w in panel.left.findChildren(type(panel.mode), "purchaseAffinity")]
print("badges:", labels)
print("saved:", panel.grab().save("scratch/purchases_affinity_preview.png"))