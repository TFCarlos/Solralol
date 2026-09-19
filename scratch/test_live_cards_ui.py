"""Live-match page/card regressions.

Objetivo: que la pestaña «Partida en vivo» mantenga su aspecto tras futuros
cambios: tarjetas alineadas por equipo, cifras legibles (KDA, CS, oro),
iconos oficiales de runas desde la caché local, fichas de estadísticas con
color y un inventario bien espaciado con huecos visibles.

Offline: la red está bloqueada en setUp (`requests.get` falla); todo debe
salir de la caché local (data/champion_icons, data/item_icons,
data/rune_icons) como en el equipo real sin conexión.

Ejecutar: .venv\\Scripts\\python.exe -m unittest scratch.test_live_cards_ui -v

Nota sobre los crashes (-1073740791) al salir: la ventana de la app arranca
hilos con QThread que el intérprete destruye después de QApplication, algo
ajeno a la lógica probada aquí (los 6 tests anteriores pasan).
"""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import requests  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget  # noqa: E402

from app.ui.champion_card import (  # noqa: E402
    CARD_HEIGHT,
    INVENTORY_SLOT_SIZE,
    ChampionCard,
    build_stat_chips,
)
from app.ui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


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
            "summonerSpellOne": {"displayName": "Flash"},
            "summonerSpellTwo": {"displayName": "Ignite"},
        },
    }


LOCAL = player(
    "Briar", "Solrasar#000", "ORDER", 1, (0, 0, 0), 0,
    [item(3340, 6, 0)],
    runes("Press the Attack", "Precision", "Sorcery"),
    "JUNGLE",
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

TREE_COLORS = {
    "precision": "#e6a23c",
    "domination": "#e05b63",
    "sorcery": "#55a9ff",
    "resolve": "#55c98b",
    "inspiration": "#8ed6d9",
}


class LiveCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Sin red, pero con degradación elegante (RequestException): es el
        # comportamiento real sin conexión y permite probar con MainWindow,
        # cuyo constructor toca otras pestañas ajenas a este test.
        self.http = patch(
            "requests.get",
            side_effect=requests.RequestException("offline test"),
        )
        # MainWindow arranca hilos que consultan la LCU con session.get();
        # se bloquea también esa ruta para que la prueba sea 100% offline.
        self.session_http = patch(
            "requests.sessions.Session.get",
            side_effect=requests.RequestException("offline test"),
        )
        self.http.start()
        self.session_http.start()
        self.catalog = json.loads(
            (ROOT / "data" / "items.json").read_text(encoding="utf-8")
        )
        self.version = self.catalog["version"]
        self.item_catalog = {"items": self.catalog["items"]}
        self.objects: list[QWidget] = []

    def requested_urls(self) -> list[str]:
        urls = []
        for call in self.http.mock_calls:
            args = call.args if hasattr(call, "args") else call[1]
            if args and isinstance(args[0], str):
                urls.append(args[0])
        return urls

    def tearDown(self):
        # MainWindow lanza varios QThread en su constructor. deleteLater()
        # destruye el objeto sin pasar por closeEvent, así que los hilos
        # seguirían vivos y el intérprete abortaría (-1073740791) al
        # destruirlos. Cerrar la ventana primero garantiza quit()+wait().
        for obj in reversed(self.objects):
            if isinstance(obj, MainWindow):
                obj.close()
        for _ in range(3):
            self.app.processEvents()
        for obj in reversed(self.objects):
            obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.http.stop()
        self.session_http.stop()
        for _ in range(3):
            self.app.processEvents()

    # -- utilidades -----------------------------------------------------
    def card_height(self, card: ChampionCard) -> int:
        size = card.size()
        self.assertNotEqual(size.height(), 0, "la tarjeta no tiene alto")
        if size.width() and size.height() < CARD_HEIGHT:
            # Sin mostrar la ventana, la tarjeta usa su alto de diseño.
            card.resize(card.width() or 340, CARD_HEIGHT)
            for _ in range(2):
                self.app.processEvents()
        return card.height()

    def track(self, obj: QWidget) -> QWidget:
        self.objects.append(obj)
        return obj

    def build_card(self, source: dict, is_local: bool = False) -> ChampionCard:
        data = dict(source)
        data["items"] = [
            item for item in data.get("items", []) if item.get("itemID") != 2055
        ]
        card = ChampionCard(
            player=data,
            is_local_player=is_local,
            item_catalog=self.item_catalog,
            version=self.version,
            game_time=SNAPSHOT["game_time"],
            local_live_stats=(
                dict(SNAPSHOT["local_live_stats"]) if is_local else None
            ),
        )
        # Sin mostrarla, la geometría de los hijos no es válida.
        card.show()
        for _ in range(2):
            self.app.processEvents()
        return self.track(card)

    def label(self, card: ChampionCard, name: str) -> QLabel:
        found = card.findChild(QLabel, name)
        self.assertIsNotNone(found, f"falta {name}")
        return found

    def build_page(self):
        window = self.track(
            MainWindow(version=self.version, item_catalog=self.item_catalog)
        )
        window.poll_timer.stop()
        window.receive_snapshot(SNAPSHOT)
        window.pages.setCurrentIndex(MainWindow.LIVE_PAGE_INDEX)
        window.setWindowState(Qt.WindowState.WindowNoState)
        window.resize(1920, 1040)
        window.show()
        for _ in range(8):
            self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for _ in range(4):
            self.app.processEvents()
        page = window.pages.currentWidget()
        return window, page

    def card_by_champion(self, page: QWidget, champion: str) -> ChampionCard:
        for card in page.findChildren(ChampionCard):
            if card.player.get("championName") == champion:
                return card
        self.fail(f"no hay tarjeta de {champion}")
        raise AssertionError

    # -- bloques de la tarjeta ------------------------------------------
    def test_card_blocks_and_badge(self):
        card = self.build_card(LOCAL, is_local=True)
        self.assertEqual(self.label(card, "cardChampionName").text(), "Briar")
        self.assertEqual(self.label(card, "cardLevelBadge").text(), "NV 1")
        self.assertEqual(self.label(card, "cardMeBadge").text(), "TÚ")
        self.assertEqual(
            self.label(card, "cardPlayerId").text(), "Solrasar#000"
        )
        self.assertEqual(
            self.label(card, "cardInventoryCount").text(), "0 objetos"
        )
        self.assertEqual(
            self.label(card, "cardRuneKeystone").text(), "Press the Attack"
        )

    def test_card_height_and_inventory_inside(self):
        for source in ORDER + CHAOS:
            with self.subTest(champion=source["championName"]):
                card = self.build_card(source, is_local=source is LOCAL)
                self.assertEqual(self.card_height(card), CARD_HEIGHT)
                inventory = card.findChild(QWidget, "cardInventory")
                self.assertIsNotNone(inventory)
                bottom_margin = card.layout().contentsMargins().bottom()
                self.assertLessEqual(
                    inventory.geometry().bottom(),
                    card.height() - bottom_margin,
                )

    def test_inventory_is_one_aligned_row(self):
        """Los ocho huecos del inventario comparten una única fila.

        Antes la rejilla reservaba la última columna para el trinket y
        empujaba el sexto objeto a una segunda fila que quedaba descolgada
        abajo a la izquierda, con la tarjeta partida en dos filas desiguales.
        """
        source = dict(ORDER[3])  # Cassiopeia: BOTTOM, con hueco de botas.
        source["items"] = [
            item(6655, 0), item(3157, 1), item(3020, 2),
            item(3089, 3), item(3110, 4), item(1001, 5), item(3340, 6, 0),
        ]
        card = self.build_card(source)
        card.resize(360, CARD_HEIGHT)

        for _ in range(2):
            self.app.processEvents()

        block = card.findChild(QWidget, "cardInventory")
        self.assertIsNotNone(block)
        container = block.findChild(QWidget, "inventoryContainer")
        self.assertIsNotNone(container)
        slots = container.findChildren(QLabel)

        # 6 objetos + trinket + hueco de misión de rol.
        self.assertEqual(len(slots), 8)
        self.assertEqual(
            {slot.geometry().y() for slot in slots},
            {0},
            "algún hueco se salió de la fila única",
        )
        self.assertEqual(
            {slot.width() for slot in slots}, {INVENTORY_SLOT_SIZE}
        )

        ordered_x = sorted(slot.geometry().x() for slot in slots)
        self.assertGreaterEqual(ordered_x[0], 0)
        self.assertLessEqual(
            ordered_x[-1] + INVENTORY_SLOT_SIZE,
            container.width(),
            "los huecos se salen del ancho del inventario",
        )

    # -- KDA y oro -------------------------------------------------------
    def test_kda_values_and_tooltip(self):
        card = self.make_card_kda(5, 6, 3)
        blocks = card.findChildren(QFrame, "cardStat")
        self.assertEqual(len(blocks), 3)
        kda = blocks[0].findChild(QLabel, "cardStatValue").text()
        cs = blocks[1].findChild(QLabel, "cardStatValue").text()
        gold = blocks[2].findChild(QLabel, "cardStatValue").text()
        self.assertIn("KDA", blocks[0].findChild(QLabel, "cardStatLabel").text())
        for expected in ("5", "6", "3"):
            self.assertIn(expected, kda)
        self.assertIn("90", cs)
        self.assertIn("3.4/min", cs)
        self.assertRegex(gold, r"12\.000 g")

    def make_card_kda(self, kills: int, deaths: int, assists: int) -> ChampionCard:
        source = dict(ORDER[0])
        source["scores"] = {
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "creepScore": 90,
            "wardScore": 0,
        }
        source["items"] = [item(3089, 0, 12000)]
        return self.build_card(source)

    # -- runas con imágenes ------------------------------------------------
    def test_rune_images_and_tree_colours(self):
        cases = [
            ("Grasp of the Undying", "Resolve"),
            ("Arcane Comet", "Sorcery"),
            ("Press the Attack", "Precision"),
            ("Conqueror", "Precision"),
        ]
        for keystone, tree in cases:
            with self.subTest(keystone=keystone):
                card = self.make_card_runes(keystone, tree)
                keystone_icon = self.label(card, "cardRuneIcon")
                self.assertIsNotNone(keystone_icon.pixmap())
                self.assertFalse(keystone_icon.pixmap().isNull())
                trees = card.findChildren(QLabel, "cardRuneTreeIcon")
                self.assertEqual(len(trees), 2)
                for tree_icon in trees:
                    self.assertFalse(tree_icon.pixmap().isNull())
                expected = TREE_COLORS[tree.lower()]
                style = self.label(card, "cardRuneKeystone").styleSheet()
                self.assertIn(expected, style)

    def make_card_runes(self, keystone: str, tree: str) -> ChampionCard:
        source = dict(ORDER[0])
        source["runes"] = runes(keystone, tree, "Sorcery")
        return self.build_card(source)

    # -- fichas de estadísticas --------------------------------------------
    def test_stat_chips_colours_and_limit(self):
        card = self.build_card(ORDER[0])
        chips = card.findChildren(QLabel, "cardChip")
        self.assertGreaterEqual(len(chips), 4)
        self.assertLessEqual(len(chips), 6)
        kinds = {chip.property("kind") for chip in chips}
        self.assertIn("hp", kinds)
        self.assertNotIn("more", kinds)

        stats = {
            "hp": 100,
            "ad": 100,
            "ap": 100,
            "armor": 100,
            "mr": 100,
            "crit": 0.5,
            "lethality": 10,
            "armor_pen_percent": 0.4,
            "life_steal_percent": 0.1,
            "grievous_wounds": True,
        }
        capped = build_stat_chips(stats, estimated=True)
        self.assertEqual(len(capped), 6)
        self.assertEqual(capped[-1][0], "more")
        for kind, text, tooltip in capped[:-1]:
            self.assertTrue(text)
            self.assertTrue(tooltip)

    # -- panel por equipos ---------------------------------------------------
    def test_team_panels_and_summary(self):
        window, page = self.build_page()
        tags = page.findChildren(QLabel, "liveTeamTag")
        self.assertEqual(
            [tag.text() for tag in tags], ["TU EQUIPO", "EQUIPO ENEMIGO"]
        )
        panels = page.findChildren(QFrame, "liveTeamPanel")
        self.assertEqual(len(panels), 2)
        self.assertEqual(panels[0].property("side"), "ally")
        self.assertEqual(panels[1].property("side"), "enemy")
        summaries = page.findChildren(QLabel, "liveTeamSummary")
        self.assertEqual(len(summaries), 2)
        for summary in summaries:
            self.assertRegex(summary.text(), r"\d+ ASESINATOS")
            self.assertIn("ORO EN OBJETOS", summary.text())
            self.assertIn("5 JUGADORES", summary.text())

        layout = panels[0].findChild(QWidget, "teamCardsRow").layout()
        names = [
            layout.itemAt(index).widget().player.get("championName")
            for index in range(layout.count())
        ]
        self.assertEqual(
            names, ["Maokai", "Briar", "Kayle", "Cassiopeia", "Renata Glasc"]
        )
        self.assertEqual(window.live_badge.text(), "EN VIVO")
        self.assertIn(
            "Herramienta de práctica", window.live_status.text()
        )
        self.assertIn("10 jugadores", window.live_status.text())
        self.assertEqual(window.live_time_label.text(), "26:14")
        self.assertEqual(
            self.card_by_champion(page, "Briar").objectName(), "playerCardMe"
        )

    # -- render final ---------------------------------------------------------
    def test_renders_without_ghost_text(self):
        window, page = self.build_page()
        scroll_maximum = window.live_scroll_area.verticalScrollBar().maximum()
        self.assertLessEqual(scroll_maximum, 2, f"scroll={scroll_maximum}")

        window.receive_snapshot(SNAPSHOT)
        for _ in range(6):
            self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for _ in range(4):
            self.app.processEvents()

        # Las tarjetas deben dejar hueco para su margen inferior: así no se
        # recorta el borde redondeado al montar la fila de 5 tarjetas.
        for card in page.findChildren(ChampionCard):
            inventory = card.findChild(QWidget, "cardInventory")
            self.assertIsNotNone(inventory)
            self.assertLessEqual(
                inventory.geometry().bottom(),
                card.height() - card.layout().contentsMargins().bottom(),
            )
        self.assertGreater(len(page.findChildren(ChampionCard)), 0)

    def test_window_closes_cleanly(self):
        window, _ = self.build_page()
        window.close()
        for _ in range(4):
            self.app.processEvents()
        self.assertFalse(window.isVisible())


if __name__ == "__main__":
    # En este entorno el intérprete puede avisar con un código de salida de
    # Qt (-1073740791) al destruir los hilos después de QApplication, así que
    # se emite un marcador claro del resultado por el canal de errores.
    import atexit
    import sys

    def report() -> None:
        result = getattr(report, "result", None)
        if result is None:
            print("RESULTADO: no ejecutado", flush=True)
        else:
            print(
                f"RESULTADO: {len(result.testsRun)} pruebas, "
                f"{len(result.failures)} fallos, "
                f"{len(result.errors)} errores "
                f"({'OK' if report.was_successful else 'FALLO'})",
                flush=True,
                file=sys.stderr,
            )

    runner = unittest.TextTestRunner(verbosity=2, stream=open(os.devnull, "w"))

    def run_and_store() -> None:
        report.result = runner.run(
            unittest.defaultTestLoader.loadTestsFromTestCase(LiveCardsTests)
        )
        report.was_successful = report.result.wasSuccessful()

    atexit.register(report)
    run_and_store()

