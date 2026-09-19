"""Vista previa offscreen de la pestaña «Partida en vivo» rediseñada.

Genera `scratch/live_page_preview.png` con una partida de ejemplo (la misma
composición que la herramienta de práctica: 5 aliados frente a 5 rivales) y
avisa de las imágenes que no están en la caché local.

Sin red: los iconos salen de `data/champion_icons`, `data/item_icons` y
`data/rune_icons`.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from app.ui.champion_card import ChampionCard  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scratch" / "live_page_preview.png"


def item(item_id: int, slot: int, price: int = 3000) -> dict:
    return {
        "itemID": item_id,
        "slot": slot,
        "count": 1,
        "price": price,
        "displayName": f"Objeto {item_id}",
    }


def runes(keystone: str, primary: str, secondary: str) -> dict:
    return {
        "keystone": {"displayName": keystone, "id": 0},
        "primaryRuneTree": {"displayName": primary, "id": 0},
        "secondaryRuneTree": {"displayName": secondary, "id": 0},
    }


def player(
    champion: str,
    riot_id: str,
    team: str,
    level: int,
    kda: tuple[int, int, int],
    cs: int,
    items: list[dict],
    rune_page: dict,
    position: str = "",
    spells: tuple[str, str] = ("Flash", "Ignite"),
) -> dict:
    return {
        "championName": champion,
        "riotId": riot_id,
        "summonerName": riot_id.split("#")[0],
        "team": team,
        "level": level,
        "position": position,
        "isBot": False,
        "scores": {
            "kills": kda[0],
            "deaths": kda[1],
            "assists": kda[2],
            "creepScore": cs,
            "wardScore": 4,
        },
        "items": items,
        "runes": rune_page,
        "summonerSpells": {
            "summonerSpellOne": {"displayName": spells[0]},
            "summonerSpellTwo": {"displayName": spells[1]},
        },
    }


LOCAL = player(
    "Briar", "Solrasar#000", "ORDER", 1, (0, 0, 0), 0,
    [item(3340, 6, 0)],
    runes("Press the Attack", "Precision", "Sorcery"),
    spells=("Flash", "Smite"),
)

ORDER = [
    player("Maokai", "Maokai#BOT", "ORDER", 13, (5, 6, 3), 90,
           [item(3075, 0), item(3068, 1), item(3110, 2), item(1001, 3),
            item(3340, 6, 0)],
           runes("Grasp of the Undying", "Resolve", "Sorcery"), "TOP"),
    LOCAL,
    player("Kayle", "Kayle#BOT", "ORDER", 12, (1, 6, 4), 80,
           [item(3116, 0), item(6653, 1), item(3020, 2), item(3340, 6, 0)],
           runes("Press the Attack", "Precision", "Sorcery"), "MIDDLE"),
    player("Cassiopeia", "Cassiopeia#BOT", "ORDER", 11, (6, 7, 3), 60,
           [item(6655, 0), item(3157, 1), item(3020, 2), item(3340, 6, 0)],
           runes("Arcane Comet", "Sorcery", "Domination"), "BOTTOM"),
    player("Renata Glasc", "Renata#BOT", "ORDER", 12, (3, 6, 6), 10,
           [item(3116, 0), item(3089, 1), item(3020, 2), item(3340, 6, 0),
            item(2055, 7, 75)],
           runes("Arcane Comet", "Sorcery", "Domination"), "UTILITY"),
]

CHAOS = [
    player("Teemo", "Teemo#BOT", "CHAOS", 14, (4, 4, 2), 90,
           [item(4645, 0), item(3116, 1), item(3020, 2), item(3340, 6, 0)],
           runes("Arcane Comet", "Sorcery", "Domination")),
    player("Amumu", "Amumu#BOT", "CHAOS", 9, (4, 0, 3), 30,
           [item(3075, 0), item(3110, 1), item(3020, 2), item(3340, 6, 0)],
           runes("Grasp of the Undying", "Resolve", "Sorcery")),
    player("Swain", "Swain#BOT", "CHAOS", 15, (12, 0, 5), 110,
           [item(6655, 0), item(3157, 1), item(3089, 2), item(3110, 3),
            item(3020, 4), item(3340, 6, 0)],
           runes("Conqueror", "Precision", "Resolve")),
    player("Kog'Maw", "KogMaw#BOT", "CHAOS", 9, (5, 7, 3), 30,
           [item(3153, 0), item(3006, 1), item(1001, 2), item(3340, 6, 0)],
           runes("Press the Attack", "Precision", "Sorcery"), "BOTTOM"),
    player("Sona", "Sona#BOT", "CHAOS", 10, (0, 5, 9), 20,
           [item(3116, 0), item(3020, 1), item(3089, 2), item(3340, 6, 0),
            item(2055, 7, 75)],
           runes("Arcane Comet", "Sorcery", "Domination"), "UTILITY"),
]

SNAPSHOT = {
    "game_mode": "PRACTICETOOL",
    "game_status": "IN_PROGRESS",
    "game_time": 1574.0,
    "champion_id": "Briar",
    "local_team": "ORDER",
    "local_player": LOCAL,
    "local_live_stats": {
        "maxHealth": 635.0,
        "attackDamage": 85.0,
        "abilityPower": 0.0,
        "armor": 30.0,
        "magicResist": 32.0,
    },
    "enemies": CHAOS,
    "all_players": ORDER + CHAOS,
    "game_events": [],
}


def main() -> int:
    app = QApplication.instance() or QApplication([])

    # El modo offscreen puede quedarse sin fuentes: carga una del sistema solo
    # para que la vista previa sea legible (la app real usa las del SO).
    for candidate in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        if Path(candidate).exists() and QFontDatabase.addApplicationFont(candidate) >= 0:
            print("fuente cargada:", candidate)
            break

    catalog = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))

    with patch("requests.get", side_effect=requests.RequestException("offline preview")):
        window = MainWindow(
            version=catalog["version"],
            item_catalog={"items": catalog["items"]},
        )

        window.poll_timer.stop()
        window.receive_snapshot(SNAPSHOT)
        window.pages.setCurrentIndex(MainWindow.LIVE_PAGE_INDEX)
        window.setWindowState(Qt.WindowState.WindowNoState)
        window.resize(1920, 1040)
        window.show()

        for _ in range(8):
            app.processEvents()

        from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

        # Las tarjetas reconstruidas con deleteLater() se destruyen aquí para
        # que ningún marcador anterior pueda seguir pintándose bajo el fondo
        # semitransparente de la tarjeta nueva.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        window.live_scroll_area.viewport().update()
        for _ in range(8):
            app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for _ in range(4):
            app.processEvents()

        page = window.pages.currentWidget()
        cards = page.findChildren(ChampionCard)
        tags = page.findChildren(QLabel, "liveTeamTag")
        missing_runes: list[str] = []

        for card in cards:
            for name in ("cardRuneIcon", "cardRuneTreeIcon"):
                for icon in card.findChildren(QLabel, name):
                    if icon.pixmap().isNull():
                        missing_runes.append(icon.toolTip())

        print("tarjetas:", len(cards), "| altos:", sorted({c.height() for c in cards}))
        print("paneles:", [tag.text() for tag in tags])

        for tag in tags:
            summary = tag.parentWidget().findChild(QLabel, "liveTeamSummary")
            print("  resumen:", summary.text() if summary else "—")

        for card in cards:
            layout = card.layout()
            inventory = card.findChild(QWidget, "cardInventory")
            print(
                " ",
                card.player.get("championName"),
                "sizeHint:", layout.sizeHint().height(),
                "alto:", card.height(),
                "fondo inventario:", inventory.geometry().bottom() if inventory else -1,
            )

        scrollbar = window.live_scroll_area.verticalScrollBar()
        print(
            "scroll max:", scrollbar.maximum(),
            "| contenido:", window.cards_widget.sizeHint().height(),
            "| viewport:", window.live_scroll_area.viewport().height(),
        )

        print("runas sin icono:", missing_runes or "ninguna")
        print("estado:", window.live_badge.text(), "|", window.live_status.text())
        print("tiempo:", window.live_time_label.text())

        saved = page.grab().save(str(OUT))
        print("vista previa guardada:", saved, OUT)

        window.close()

    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())