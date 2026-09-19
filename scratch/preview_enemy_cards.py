"""Vista previa offscreen de las tarjetas de rivales con retrato del campeón.

Usa las imágenes ya cacheadas en ~/.solralol/ddragon, sin red.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from app.services.data_dragon_assets import DataDragonAssetService  # noqa: E402
from app.ui.recommendation_panel import RecommendationPanel  # noqa: E402

players = {"me": {"champion_name": "Tryndamere", "team": "ORDER", "role": "JUNGLE"},
           "e0": {"champion_name": "Shen", "team": "CHAOS", "side": "enemy"},
           "e1": {"champion_name": "Hecarim", "team": "CHAOS", "side": "enemy"},
           "e2": {"champion_name": "Ahri", "team": "CHAOS", "side": "enemy"},
           "e3": {"champion_name": "Caitlyn", "team": "CHAOS", "side": "enemy"},
           "e4": {"champion_name": "Nautilus", "team": "CHAOS", "side": "enemy"}}
points = {"me": {"items": [3074, 3047, 3035, 1001], "level": 5, "kills": 0, "deaths": 0,
                 "assists": 0, "current_gold": 803},
          "e0": {"items": [3075, 3083], "level": 4, "kills": 0, "deaths": 3, "assists": 0},
          "e1": {"items": [1036, 1001], "level": 4, "kills": 0, "deaths": 1, "assists": 0},
          "e2": {"items": [6655, 3157], "level": 5, "kills": 0, "deaths": 2, "assists": 0},
          "e3": {"items": [3072, 1036], "level": 4, "kills": 0, "deaths": 0, "assists": 0},
          "e4": {"items": [3190, 3047], "level": 4, "kills": 0, "deaths": 0, "assists": 0}}
session = {"local_player_key": "me", "local_team": "ORDER", "champion_name": "Tryndamere",
           "duration": 543, "game_mode": "CLASSIC", "players": players,
           "snapshots": [{"time": 543, "players": points}],
           "lane_matchups": {"JUNGLE": {"enemy_key": "e1"}}, "events": []}

app = QApplication.instance() or QApplication([])
# El modo offscreen de este entorno puede quedarse sin fuentes: carga una del sistema
# solo para que la vista previa sea legible (la app real usa las fuentes del SO).
from PySide6.QtGui import QFontDatabase  # noqa: E402

for candidate in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
    if Path(candidate).exists() and QFontDatabase.addApplicationFont(candidate) >= 0:
        print("fuente cargada:", candidate)
        break
with patch("app.services.data_dragon_assets.requests.get",
           side_effect=requests.RequestException("offline preview")):
    assets = DataDragonAssetService()
panel = RecommendationPanel()
host = QWidget()
panel.setParent(host)
panel.configure(assets, json.loads(Path("data/items.json").read_text(encoding="utf-8")))
panel.update_recommendations(session)
host.resize(1180, 900)
panel.resize(1180, 900)
host.show()
panel.show()
for _ in range(5):
    app.processEvents()

fallbacks = []
for threat in panel.report["threats"]:
    card = panel.right.findChild(QWidget, f"enemyCard_{threat['key']}")
    row = [card.findChild(QLabel, name) for name in
           ("enemyChampionIcon", "enemyLevel", "enemyChampionName", "enemyKda",
            "enemyStrengthBadge", "enemyBuildGold")]
    texts = [(w.objectName(), w.text()) for w in row if w is not None]
    print(f"{card.objectName()} alto={card.height()}px", texts)
    portrait = card.findChild(QLabel, "enemyChampionIcon")
    order = [w.mapTo(card, QPoint(0, 0)).x() for w in row if w is not None]
    assert order == sorted(order), (card.objectName(), order)
    # Sin red, los campeones que no están en la caché muestran el texto de respaldo.
    fallbacks.append(threat["champion"]) if portrait.pixmap().isNull() else None
print("sin imagen en caché (se descargarían en vivo):", fallbacks)
print("saved:", panel.grab().save("scratch/enemy_cards_preview.png"))
