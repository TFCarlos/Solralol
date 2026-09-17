"""Offline engine/UI regression: python -m unittest scratch.test_live_recommendations -v."""
import json
import os
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from app.services.live_recommendation_service import LiveRecommendationService, canonical
from app.ui.recommendation_panel import RecommendationPanel
from app.ui.styles import CONTROL_WINDOW_STYLE


def fixture(champion="Briar", enemies=("Soraka", "Lux", "Darius", "Jinx", "Malphite")):
    players = {"me": {"champion_name": champion, "team": "ORDER", "role": "JUNGLE"},
               "ally": {"champion_name": "Leona", "team": "ORDER", "side": "ally"}}
    for index, name in enumerate(enemies):
        players[f"e{index}"] = {"champion_name": name, "team": "CHAOS", "side": "enemy"}
    points = {key: {"items": [], "level": 12, "kills": 2, "deaths": 1, "assists": 4}
              for key in players}
    points["me"].update(items=[1036, 1001], current_gold=2810)
    return {"local_player_key": "me", "local_team": "ORDER", "champion_name": champion,
            "players": players, "duration": 1200, "game_mode": "CLASSIC",
            "snapshots": [{"time": 1200, "players": points}],
            "lane_matchups": {"JUNGLE": {"ally_key": "me", "enemy_key": "e0"}},
            "events": []}


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
        cls.engine = LiveRecommendationService(cls.catalog)

    def test_real_champions_coverage_and_compatible_results(self):
        for name in ("Briar", "Lux", "Lulu", "Aatrox", "Ornn", "Ahri", "Jinx", "Cassiopeia", "Dr. Mundo"):
            with self.subTest(champion=name):
                s = fixture(name)
                result = self.engine.analyze(s)
                self.assertTrue(result["profile"], name)
                self.assertTrue(result["recommendations"], name)
                for rec in result["recommendations"]:
                    self.assertTrue(self.engine.available(rec["id"]))
                    self.assertTrue(self.engine.compatible(rec["id"], result["owned"]))
                    self.assertTrue(rec["reasons"])
                    if name == "Briar":
                        self.assertEqual(self.engine.stat(rec["id"], "ability_power"), 0)
                        self.assertEqual(self.engine.stat(rec["id"], "mana"), 0)
                    if name == "Cassiopeia":
                        self.assertNotIn("Boots", self.engine.catalog[rec["id"]].get("tags", []))

    def test_no_network_no_mutation_and_determinism(self):
        s = fixture()
        before = deepcopy(s)
        with patch("requests.get", side_effect=AssertionError("Network forbidden")):
            a, b = self.engine.analyze(s), self.engine.analyze(s)
        self.assertEqual(a, b)
        self.assertEqual(s, before)

    def test_enemy_classification_does_not_include_allies_or_unknowns(self):
        s = fixture(enemies=())
        s.pop("local_team")
        s["players"]["me"].pop("team")
        s["players"]["unknown"] = {"champion_name": "Soraka"}
        r = self.engine.analyze(s)
        self.assertEqual(r["threats"], [])

    def test_armor_threshold_and_healing_evidence(self):
        s = fixture(enemies=("Garen",))
        p = s["snapshots"][0]["players"]["e0"]
        p["items"] = [1029]  # cloth armor should not imply heavy armor
        self.assertNotIn("armor", [x["kind"] for x in self.engine.analyze(s)["threats"][0]["signals"]])
        p["items"] = [3075, 3143]
        signals = self.engine.analyze(s)["threats"][0]["signals"]
        self.assertIn("armor", [x["kind"] for x in signals])
        self.assertNotIn("healing", [x["kind"] for x in signals])  # antiheal is not healing
        p["items"] = [3153]
        signals = self.engine.analyze(s)["threats"][0]["signals"]
        self.assertIn("healing", [x["kind"] for x in signals])

    def test_context_changes_scores(self):
        base = self.engine.analyze(fixture(enemies=("Garen",)))
        healing = self.engine.analyze(fixture(enemies=("Soraka", "Vladimir", "Warwick")))
        scores = lambda r: {x["id"]: x["score"] for x in r["recommendations"]}
        self.assertIn("3033", scores(healing))
        self.assertGreater(scores(healing)["3033"], scores(base).get("3033", 0))
        magic = self.engine.analyze(fixture(enemies=("Lux", "Syndra", "Veigar")))
        physical = self.engine.analyze(fixture(enemies=("Darius", "Jinx", "Draven")))
        self.assertLess(magic["physical_share"], .4)
        self.assertGreater(physical["physical_share"], .6)
        self.assertNotEqual(magic["recommendations"], physical["recommendations"])

    def test_unknown_missing_and_nonfinite_gold(self):
        self.assertFalse(self.engine.analyze({})["recommendations"])
        self.assertFalse(self.engine.analyze(fixture("UnknownChampion"))["recommendations"])
        for gold in (None, "invalid", float("nan"), float("inf")):
            s = fixture()
            s["snapshots"][0]["players"]["me"]["current_gold"] = gold
            s["snapshots"][0]["players"]["me"]["estimated_gold"] = 99999
            result = self.engine.analyze(s)
            self.assertIsNone(result["gold"])
            self.assertNotEqual(result["purchase"]["status"], "buy")

    def test_postgame_stale_empty_inventory(self):
        s = fixture()
        s["ended_at"] = "2026-09-17"
        self.assertEqual(self.engine.analyze(s)["purchase"]["status"], "postgame")
        s.pop("ended_at")
        s["duration"] = 1300
        self.assertEqual(self.engine.analyze(s)["purchase"]["status"], "stale")
        s["snapshots"].append({"time": 1300, "players": {"me": {"items": [], "current_gold": 0}}})
        r = self.engine.analyze(s)
        self.assertEqual(r["owned"], [])
        self.assertNotEqual(r["purchase"]["status"], "buy")

    def test_phase_allied_synergy_health_and_objectives(self):
        s = fixture()
        s["events"] = [{"type": "objective", "time": 1190, "label": "Dragón aliado"}]
        s["snapshots"][0]["players"]["me"]["live_stats"] = {"currentHealth": 100, "maxHealth": 1000}
        result = self.engine.analyze(s)
        text = str(result["actions"])
        for word in ("Leona", "Dragón aliado", "Vida baja", "E para cortar"):
            self.assertIn(word, text)
        for seconds, expected in ((800, "Inicio"), (1500, "Medio juego"), (2100, "Juego tardío")):
            s["duration"] = seconds
            s["snapshots"][0]["time"] = seconds
            self.assertEqual(self.engine.analyze(s)["phase"], expected)

    def test_exclusive_and_owned(self):
        for owned, rejected in ((["3053"], "3156"), (["3071"], "3036"), (["3748"], "3074"), (["3111"], "3047")):
            self.assertFalse(self.engine.compatible(rejected, owned))
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3053, 3071, 3748, 3111]
        r = self.engine.analyze(s)
        self.assertFalse({"3156", "3036", "3033", "3074", "3047"}.intersection(x["id"] for x in r["recommendations"]))

    def recipe_engine(self):
        def item(cost, children=(), tags=()):
            return {"name": str(cost), "gold": {"purchasable": True, "total": cost}, "from": list(children), "tags": list(tags)}
        return LiveRecommendationService({"1": item(350), "2": item(1000, ("1", "1")),
                                          "3": item(2500, ("2", "1")), "4": item(200),
                                          "5": item(0, tags=("Trinket",))})

    def test_recipe_multiset_remaining_and_upgrade_full_inventory(self):
        engine = self.recipe_engine()
        self.assertEqual(engine._recipe("3", ["1", "1"])[0], 1800)
        self.assertEqual(engine._recipe("3", ["2", "1"])[0], 1150)
        result = engine.purchase("3", ["2", "1", "4", "4", "4", "4", "5"], 1150)
        self.assertEqual((result["status"], result["id"], result["cost"]), ("buy", "3", 1150))
        self.assertEqual(engine.purchase("3", ["4"] * 6, 9999)["status"], "full")

    def test_recipe_second_copy_is_buyable(self):
        result = self.recipe_engine().purchase("2", ["1"], 350)
        self.assertEqual((result["status"], result.get("id"), result.get("cost")), ("buy", "1", 350))

    def test_recipe_no_gold_unknown_and_cycles(self):
        engine = self.recipe_engine()
        self.assertEqual(engine.purchase("3", [], 0)["status"], "save")
        self.assertEqual(engine.purchase("3", [], None)["status"], "unknown")
        engine.catalog["1"]["from"] = ["3"]
        self.assertGreaterEqual(engine._recipe("3", [])[0], 0)

    def test_enemy_inventory_badges_value_and_duplicates(self):
        ids = [3075, 3031, 3111, 3153, 3083, 1036, 3340]
        result = self.engine.inventory_summary({"items": ids})
        self.assertEqual(result["value"], sum(self.engine.cost(str(i)) for i in ids))
        self.assertFalse(result["partial"])
        self.assertEqual({b["kind"] for b in result["badges"]},
                         {"antiheal", "armor", "crit", "mr", "lifesteal", "health"})
        duplicate = self.engine.inventory_summary({"items": [{"itemID": 1029, "count": 2}]})
        self.assertEqual(duplicate["value"], self.engine.cost("1029") * 2)
        self.assertEqual([b["label"] for b in duplicate["badges"]], ["Armadura"])
        for ident in self.engine.ANTIHEAL:
            with self.subTest(item=ident):
                badges = self.engine.inventory_summary({"items": [ident]})["badges"]
                self.assertEqual(sum(b["kind"] == "antiheal" for b in badges), 1)

    def test_enemy_inventory_unknown_empty_and_kit_not_badges(self):
        self.assertIsNone(self.engine.inventory_summary({})["value"])
        self.assertEqual(self.engine.inventory_summary({"items": []})["value"], 0)
        summary = self.engine.inventory_summary({"items": [1036, 999999]})
        self.assertTrue(summary["partial"])
        self.assertEqual(summary["value"], self.engine.cost("1036"))
        result = self.engine.analyze(fixture(enemies=("Soraka",)))
        self.assertTrue(result["threats"][0]["signals"])
        self.assertEqual(result["threats"][0]["inventory"]["badges"], [])

    def test_enemy_inventory_updates_purchase_sale_and_stale(self):
        s = fixture(enemies=("Garen",))
        s["snapshots"][0]["players"]["e0"]["items"] = [3075, 3031]
        before = self.engine.analyze(s)["threats"][0]
        self.assertIn("Cortacura", [b["label"] for b in before["inventory"]["badges"]])
        s["snapshots"].append({"time": 1210, "players": {"e0": {"items": [1036]}}})
        after = self.engine.analyze(s)["threats"][0]
        self.assertEqual(after["items"], ["1036"])
        self.assertEqual(after["inventory"]["badges"], [])
        self.assertEqual(after["inventory"]["value"], self.engine.cost("1036"))
        s["duration"] = 1300
        self.assertTrue(self.engine.analyze(s)["threats"][0]["stale"])

    def test_strength_inventory_level_and_bounded_kda(self):
        s = fixture(enemies=("Lux", "Garen", "Jinx"))
        p = s["snapshots"][0]["players"]
        p["e0"].update(items=[3083, 3031], level=16, kills=0, deaths=10)
        p["e1"].update(items=[1036], level=10, kills=100)
        p["e2"].update(items=[], level=6)
        rows = self.engine.analyze(s)["threats"]
        self.assertEqual([r["key"] for r in rows], ["e0", "e1", "e2"])
        self.assertEqual([r["strength_label"] for r in rows], ["MÁS FUERTE", "", "MÁS DÉBIL"])
        before = rows[0]["strength"]
        p["e0"]["level"] += 1
        self.assertAlmostEqual(self.engine.analyze(s)["threats"][0]["strength"] - before, .6)

    def test_strength_ties_and_single_enemy(self):
        s = fixture(enemies=("Lux", "Garen", "Jinx"))
        rows = self.engine.analyze(s)["threats"]
        self.assertTrue(all(r["strength_label"] == "FUERZA SIMILAR" for r in rows))
        s["snapshots"][0]["players"]["e2"]["level"] = 1
        rows = self.engine.analyze(s)["threats"]
        self.assertEqual(sum(r["strength_label"] == "MÁS FUERTE · EMPATE" for r in rows), 2)
        self.assertEqual(rows[-1]["strength_label"], "MÁS DÉBIL")
        self.assertEqual(self.engine.analyze(fixture(enemies=("Lux",)))["threats"][0]["strength_label"], "")
        self.assertEqual(self.engine.analyze(fixture(enemies=()))["threats"], [])

    def test_strength_incomplete_data_is_unmarked_but_others_still_compare(self):
        for changes in ({"items": None}, {"items": [999999]}, {"level": None},
                        {"level": float("nan")}, {"kills": None}, {"deaths": -1}):
            with self.subTest(changes=changes):
                s = fixture(enemies=("Lux", "Garen", "Jinx"))
                players = s["snapshots"][0]["players"]
                players["e0"].update(changes)
                players["e1"]["level"] = 12
                players["e2"]["level"] = 10
                rows = self.engine.analyze(s)["threats"]
                broken = next(r for r in rows if r["key"] == "e0")
                self.assertIsNone(broken["strength"])
                self.assertEqual(broken["strength_label"], "")
                self.assertEqual(next(r for r in rows if r["key"] == "e1")["strength_label"], "MÁS FUERTE")
                self.assertEqual(next(r for r in rows if r["key"] == "e2")["strength_label"], "MÁS DÉBIL")

    def test_strength_survives_high_levels_and_old_snapshots(self):
        s = fixture(enemies=("Lux", "Garen", "Jinx"))
        players = s["snapshots"][0]["players"]
        for key, level in (("e0", 20), ("e1", 12), ("e2", 10)):
            players[key]["level"] = level
        s["duration"] += 31
        rows = self.engine.analyze(s)["threats"]
        self.assertTrue(all(r["stale"] for r in rows))
        self.assertTrue(all(r["strength"] is not None for r in rows))
        self.assertEqual([r["strength_label"] for r in rows], ["MÁS FUERTE", "", "MÁS DÉBIL"])


    def test_full_inventory_recommends_three_elixirs(self):
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3083, 3031, 3123, 3035, 1018, 1001]
        r = self.engine.analyze(s)
        self.assertEqual([x["id"] for x in r["recommendations"]], ["2138", "2139", "2140"])
        for rec in r["recommendations"]:
            self.assertIn("Inventario completo", rec["reasons"][0])
            self.assertIn("Comprable ya", rec["next_buy"])
        s["snapshots"][0]["players"]["me"]["items"] = [3083, 3031, 3123, 3035, 1018, 2139]
        r = self.engine.analyze(s)
        self.assertEqual([x["id"] for x in r["recommendations"]], ["2138", "2140"])

    def test_purchases_suggest_upgrades_from_owned_components(self):
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3123, 1001]
        r = self.engine.analyze(s)
        by_id = {p["id"]: p for p in r["purchases"]}
        self.assertIn("3033", by_id)
        self.assertEqual(self.engine._missing_parts("3033", ["3123"]), ["3035", "1018"])
        self.assertEqual(len(by_id["3033"]["missing"]), 2)
        self.assertEqual(by_id["3033"]["cost"], 2200)
        self.assertIn(self.engine.name("3123"), by_id["3033"]["reason"])
        self.assertLessEqual(len(r["purchases"]), 3)

    def test_purchases_share_the_affinity_scale_and_percentage(self):
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3123, 1001]
        r = self.engine.analyze(s)
        candidates = r["recommendations"] + r["purchases"]
        best = max(row["score"] for row in candidates)
        self.assertEqual([row["affinity_percent"] for row in candidates if row["score"] == best],
                         [100.0])
        for row in candidates:
            self.assertIsNotNone(row["affinity_percent"])
            self.assertGreaterEqual(row["affinity_percent"], 0)
            self.assertLessEqual(row["affinity_percent"], 100)
            self.assertEqual(row["affinity_percent"], round(100.0 * row["score"] / best, 1))
        by_id = {p["id"]: p for p in r["purchases"]}
        self.assertIn("3033", by_id)
        self.assertLess(by_id["3033"]["affinity_percent"], 100)
        # Las compras usan exactamente la misma afinidad que las recomendaciones.
        top = r["recommendations"][0]
        item = {**self.engine.catalog[top["id"]], **self.engine.strict.get(top["id"], {}),
                "name": self.engine.catalog[top["id"]].get("name", top["id"]), "tier": "Legendary"}
        scored = self.engine._score_candidate(top["id"], item, r["profile"], r["champion"],
                                              r["owned"], r["threats"], r["physical_share"])
        self.assertEqual(scored["score"], top["score"])

    def test_purchases_without_champion_profile_report_no_affinity(self):
        engine = LiveRecommendationService(self.catalog, champions={})
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3123, 1001]
        r = engine.analyze(s)
        self.assertEqual(r["recommendations"], [])
        self.assertTrue(r["purchases"])
        for entry in r["purchases"]:
            self.assertIsNone(entry["score"])
            self.assertIsNone(entry["affinity_percent"])

    def test_next_buy_respects_current_gold(self):
        self.assertIsNone(self.engine._next_buy("3123", ["1036"], None))
        self.assertIn("Comprable ya (450", self.engine._next_buy("3123", ["1036"], 10**6))
        self.assertIn("Ya puedes comprar", self.engine._next_buy("3123", [], 500))
        self.assertIn("Faltan", self.engine._next_buy("3123", [], 0))

    def test_budget(self):
        start = time.perf_counter()
        for _ in range(20):
            self.engine.analyze(fixture())
        mean = (time.perf_counter() - start) / 20
        print(f"\nLIVE recommendation engine mean: {mean*1000:.1f} ms")
        self.assertLess(mean, .1)


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.catalog = json.loads(Path("data/items.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.panel = RecommendationPanel()
        self.host = QWidget()
        self.host.setStyleSheet(CONTROL_WINDOW_STYLE)
        self.panel.setParent(self.host)
        self.panel.configure(None, self.catalog)

    def tearDown(self):
        self.panel.close()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def render(self, width, height=800):
        self.host.resize(width, height)
        self.panel.resize(width, height)
        self.host.show()
        self.panel.show()
        self.app.processEvents()

    def test_enemy_cards_follow_lane_order_after_refresh(self):
        s = fixture()
        # Deliberately shuffled: ADC, jungle, mid, support, top.
        assignments = {"BOTTOM": "e0", "JUNGLE": "e1", "MIDDLE": "e2",
                       "UTILITY": "e3", "TOP": "e4"}
        s["lane_matchups"] = {role: {"enemy_key": key}
                              for role, key in assignments.items()}
        # Matchup assignments take precedence over outdated player roles.
        for key in assignments.values():
            s["players"][key]["role"] = "TOP"
        expected = ["enemyCard_e4", "enemyCard_e1", "enemyCard_e2",
                    "enemyCard_e0", "enemyCard_e3"]
        for level in (16, 18):
            s["snapshots"][0]["players"]["e0"]["level"] = level
            self.panel.update_recommendations(s)
            self.render(1160)
            layout = self.panel.right.layout()
            cards = [layout.itemAt(i).widget() for i in range(layout.count())]
            cards = [w for w in cards if w and w.objectName().startswith("enemyCard_")]
            self.assertEqual([w.objectName() for w in cards], expected)
            self.assertEqual([w.y() for w in cards], sorted(w.y() for w in cards))

    def test_enemy_order_uses_player_roles_and_keeps_unknowns_last(self):
        self.panel._last_session = {"players": {
            "top": {"role": "TOP"}, "jungle": {"role": "JUNGLE"},
            "mid": {"role": "MID"}, "bot": {"role": "BOT"},
            "support": {"role": "SUPPORT"}}}
        threats = [{"key": key} for key in
                   ("unknown1", "support", "bot", "mid", "jungle", "top", "unknown2")]
        original = deepcopy(threats)
        self.assertEqual([t["key"] for t in self.panel._ordered_threats(threats)],
                         ["top", "jungle", "mid", "bot", "support", "unknown1", "unknown2"])
        self.assertEqual(threats, original)
        self.assertEqual(self.panel._ordered_threats([]), [])

    def test_purchases_section_and_next_buy_hint(self):
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3123, 1001]
        self.panel.update_recommendations(s)
        self.render(1160)
        hints = self.panel.left.findChildren(QLabel, "synergyNextBuy")
        expected = sum(1 for rec in self.panel.report["recommendations"][:3] if rec.get("next_buy"))
        self.assertGreaterEqual(expected, 1)
        self.assertEqual(len(hints), expected)
        for hint in hints:
            self.assertTrue(hint.isVisible())
            self.assertTrue(hint.text().startswith("Próxima compra:"))
        titles = [l.text() for l in self.panel.left.findChildren(QLabel)]
        self.assertIn("Según tus compras", titles)
        cards = [w for w in self.panel.left.findChildren(QWidget)
                 if w.objectName().startswith("purchaseItem_")]
        self.assertTrue({w.objectName() for w in cards} & {"purchaseItem_3033", "purchaseItem_6609"})
        self.assertLessEqual(len(cards), 3)

    def test_purchases_render_their_affinity_percentage(self):
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3123, 1001]
        self.panel.update_recommendations(s)
        self.render(1160)
        report = {entry["id"]: entry for entry in self.panel.report["purchases"]}
        self.assertTrue(report)
        cards = [w for w in self.panel.left.findChildren(QWidget)
                 if w.objectName().startswith("purchaseItem_")]
        self.assertEqual(len(cards), len(report))
        badges = self.panel.left.findChildren(QLabel, "purchaseAffinity")
        self.assertEqual(len(badges), len(report))
        for card in cards:
            ident = card.objectName().split("_", 1)[1]
            percent = report[ident]["affinity_percent"]
            self.assertIsNotNone(percent)
            badge = card.findChild(QLabel, "purchaseAffinity")
            self.assertTrue(badge.isVisible())
            self.assertEqual(badge.text(), f"Afinidad {percent:.1f} %")
            self.assertIn(f"{percent:.1f} %", badge.toolTip())
            self.assertIn("Afinidad", badge.toolTip())
            self.assertTrue(card.rect().contains(badge.mapTo(card, badge.rect().topLeft())))
            self.assertTrue(card.rect().contains(badge.mapTo(card, badge.rect().bottomRight())))

    def test_purchases_without_percentage_hide_the_badge(self):
        s = fixture()
        s["snapshots"][0]["players"]["me"]["items"] = [3123, 1001]
        self.panel.engine.champions = {}
        self.panel.update_recommendations(s)
        self.render(1160)
        self.assertTrue(self.panel.report["purchases"])
        for entry in self.panel.report["purchases"]:
            self.assertIsNone(entry["affinity_percent"])
        self.assertEqual(self.panel.left.findChildren(QLabel, "purchaseAffinity"), [])

    def test_compact_panel_end_to_end(self):
        from PySide6.QtWidgets import QToolButton

        s = fixture(enemies=("Lux", "Garen", "Jinx"))
        points = s["snapshots"][0]["players"]
        points["e0"].update(items=[3083, 3031], level=16)
        points["e1"].update(items=[1036], level=10)
        points["e2"].update(items=[], level=6)
        self.panel.update_recommendations(s)
        self.render(1160)

        recommendations = self.panel.report["recommendations"]
        self.assertGreater(len(recommendations), 3)
        cards = [w for w in self.panel.left.findChildren(QWidget)
                 if w.objectName().startswith("synergyItem_")]
        self.assertEqual([w.objectName() for w in cards],
                         [f"synergyItem_{r['id']}" for r in recommendations[:3]])
        for card, rec in zip(cards, recommendations):
            score = card.findChild(QLabel, "synergyScore")
            self.assertTrue(score.isVisible())
            self.assertEqual(score.text(), f"{rec['score']:g} pts")
            self.assertLessEqual(card.height(), 96)
            self.assertTrue(card.toolTip())
            reason = card.findChild(QLabel, "synergyReason")
            self.assertTrue(reason.isVisible())
            candidates = list(dict.fromkeys(rec["responses"] + rec["reasons"]))
            expected = " ".join(candidates[0].split()) if candidates else ""
            if len(expected) > 72:
                expected = expected[:71].rstrip(" ,;:.") + "…"
            self.assertEqual(reason.text(), expected)
        for key, expected in (("e0", "MÁS FUERTE"), ("e2", "MÁS DÉBIL")):
            card = self.panel.right.findChild(QWidget, f"enemyCard_{key}")
            badge = card.findChild(QLabel, "enemyStrengthBadge")
            self.assertTrue(badge.isVisible())
            self.assertEqual(badge.text(), expected)
        middle = self.panel.right.findChild(QWidget, "enemyCard_e1")
        self.assertIsNone(middle.findChild(QLabel, "enemyStrengthBadge"))
        points["e0"].update(items=None, level=None)
        self.panel.update_recommendations(s)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.render(1160)
        strong = self.panel.right.findChild(QWidget, "enemyCard_e1")
        self.assertEqual(strong.findChild(QLabel, "enemyStrengthBadge").text(), "MÁS FUERTE")
        note = self.panel.right.findChild(QLabel, "enemyPartialNote")
        self.assertIsNotNone(note)
        self.assertIn("Comparación parcial", note.text())
        broken_card = self.panel.right.findChild(QWidget, "enemyCard_e0")
        self.assertIsNone(broken_card.findChild(QLabel, "enemyStrengthBadge"))
        for name, title in (("actionPlan", "Plan y coordinación"),
                            ("qualityCard", "Datos y limitaciones")):
            toggle = self.panel.findChild(QToolButton, name + "Toggle")
            text = self.panel.findChild(QLabel, name + "Text")
            self.assertEqual(toggle.text(), title)
            self.assertFalse(toggle.isChecked())
            self.assertTrue(text.isHidden())
            toggle.click()
            self.app.processEvents()
            self.assertTrue(text.isVisible())
            toggle.click()


    def test_strength_and_expanded_details_survive_live_refresh(self):
        from PySide6.QtWidgets import QToolButton

        s = fixture(enemies=("Lux", "Garen"))
        points = s["snapshots"][0]["players"]
        points["e0"]["level"] = 16
        points["e1"]["level"] = 6
        self.panel.update_recommendations(s)
        self.render(1160)
        self.panel.findChild(QToolButton, "actionPlanToggle").click()
        s["snapshots"].append({"time": 1210, "players": {
            "e0": {"level": 16}, "e1": {"level": 18, "items": [3083, 3031]}}})
        self.panel.update_recommendations(s)
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertTrue(self.panel.findChild(QToolButton, "actionPlanToggle").isChecked())
        self.assertTrue(self.panel.findChild(QLabel, "actionPlanText").isVisible())
        for key, expected in (("e0", "MÁS DÉBIL"), ("e1", "MÁS FUERTE")):
            card = self.panel.right.findChild(QWidget, f"enemyCard_{key}")
            self.assertEqual(card.findChild(QLabel, "enemyStrengthBadge").text(), expected)
        self.assertEqual(len(self.panel.left.findChildren(QLabel, "synergyScore")), 3)
        s["duration"] = 1300
        self.panel.update_recommendations(s)
        self.app.processEvents()
        # Stale data is surfaced as a warning; the strength marks persist.
        badges = self.panel.right.findChildren(QLabel, "enemyStrengthBadge")
        self.assertEqual(len(badges), 2)
        for key, expected in (("e0", "MÁS DÉBIL"), ("e1", "MÁS FUERTE")):
            card = self.panel.right.findChild(QWidget, f"enemyCard_{key}")
            self.assertEqual(card.findChild(QLabel, "enemyStrengthBadge").text(), expected)

    def test_fewer_than_three_candidates_are_not_padded(self):
        report = self.panel.engine.analyze(fixture())
        for count in (0, 1, 2):
            with self.subTest(count=count):
                limited = {**report, "recommendations": report["recommendations"][:count]}
                with patch.object(self.panel.engine, "analyze", return_value=limited):
                    self.panel.update_recommendations(fixture())
                self.render(800)
                self.assertEqual(len(self.panel.left.findChildren(QLabel, "synergyScore")), count)

    def test_no_routes_layout_resizing_and_plain_text(self):
        self.panel.update_recommendations(fixture())
        for width in (1580, 1160, 800):
            self.render(width)
            self.assertEqual(self.panel._columns, 1 if width < 980 else 2)
            self.assertEqual(self.panel.scroll.horizontalScrollBar().maximum(), 0)
            self.assertFalse(self.panel.findChildren(QPushButton))
            self.assertLessEqual(self.panel.content.width(), self.panel.scroll.viewport().width())
            self.assertTrue(all(l.textFormat() == Qt.TextFormat.PlainText for l in self.panel.findChildren(QLabel)))
            self.assertFalse(self.panel.grab().isNull())

    def test_refresh_preserves_scroll_and_same_data_widgets(self):
        s = fixture()
        self.panel.update_recommendations(s)
        self.render(1160, 500)
        position = min(250, self.panel.scroll.verticalScrollBar().maximum())
        self.assertGreater(position, 0)
        self.panel.scroll.verticalScrollBar().setValue(position)
        card = self.panel.findChild(QWidget, "priorityCard")
        self.panel.update_recommendations(s)
        self.assertIs(card, self.panel.findChild(QWidget, "priorityCard"))
        self.assertEqual(self.panel.scroll.verticalScrollBar().value(), position)
        s["snapshots"][0]["players"]["me"]["current_gold"] = 42
        self.panel.update_recommendations(s)
        self.app.processEvents()
        self.assertEqual(self.panel.report["gold"], 42)
        self.assertEqual(self.panel.scroll.verticalScrollBar().value(), position)

    def test_enemy_cards_icons_badges_gold_and_live_refresh(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from PySide6.QtGui import QPixmap, QColor

        def paint(label, url, key, size):
            image = QPixmap(size, size)
            image.fill(QColor("#55aa88"))
            label.setPixmap(image)
        assets = SimpleNamespace(item_url=lambda i: str(i), champion_url=lambda c: c,
                                 set_label_image=Mock(side_effect=paint))
        self.panel.configure(assets, self.catalog)
        s = fixture()
        ids = [3075, 3031, 3111, 3153, 3083, 1036, 3340]
        for key, point in s["snapshots"][0]["players"].items():
            if key.startswith("e"):
                point["items"] = ids
        self.panel.update_recommendations(s)
        for width in (1580, 1160, 980, 800):
            self.render(width)
            card = self.panel.right.findChild(QWidget, "enemyCard_e0")
            icons = card.findChildren(QLabel, "enemyItemIcon")
            self.assertEqual([i.property("itemId") for i in icons], list(map(str, ids)))
            self.assertTrue(all(not i.pixmap().isNull() and i.toolTip() for i in icons))
            badges = card.findChildren(QLabel, "enemyInventoryBadge")
            self.assertEqual(len(badges), 6)
            self.assertTrue({"Armadura", "Cortacura", "Crítico"} <= {b.text() for b in badges})
            self.assertTrue(all(b.toolTip() for b in badges))
            expected_gold = sum(self.panel.engine.cost(str(i)) for i in ids)
            self.assertEqual(card.findChild(QLabel, "enemyBuildGold").text(), f"Build: {expected_gold:,} oro")
            for widget in icons + badges:
                self.assertTrue(card.rect().contains(widget.mapTo(card, widget.rect().topLeft())))
                self.assertTrue(card.rect().contains(widget.mapTo(card, widget.rect().bottomRight())))
            self.assertEqual(self.panel.scroll.horizontalScrollBar().maximum(), 0)
            self.assertFalse(self.panel.grab().isNull())
        s["snapshots"].append({"time": 1210, "players": {"e0": {"items": []}}})
        self.panel.update_recommendations(s)
        self.app.processEvents()
        card = self.panel.right.findChild(QWidget, "enemyCard_e0")
        self.assertFalse(card.findChildren(QLabel, "enemyItemIcon"))
        self.assertFalse(card.findChildren(QLabel, "enemyInventoryBadge"))
        self.assertEqual(card.findChild(QLabel, "enemyBuildGold").text(), "Build: 0 oro")

    def test_enemy_card_unknown_and_partial_value(self):
        s = fixture(enemies=("Lux",))
        s["snapshots"][0]["players"]["e0"].pop("items")
        self.panel.update_recommendations(s)
        self.render(1160)
        card = self.panel.right.findChild(QWidget, "enemyCard_e0")
        self.assertEqual(card.findChild(QLabel, "enemyBuildGold").text(), "Build: oro desconocido")
        s["snapshots"][0]["players"]["e0"]["items"] = [999999]
        self.panel.update_recommendations(s)
        self.app.processEvents()
        card = self.panel.right.findChild(QWidget, "enemyCard_e0")
        self.assertIn("catálogo incompleto", card.findChild(QLabel, "enemyBuildGold").text())
        self.assertEqual(card.findChild(QLabel, "enemyItemIcon").toolTip(), "Objeto 999999")

    def test_empty_postgame_champion_switch(self):
        for session in ({}, fixture(), fixture("Lux"), {**fixture(), "ended_at": "done"}):
            self.panel.update_recommendations(session)
            self.render(1160)
        self.assertEqual(self.panel.mode.text(), "REVISIÓN POSTGAME")


if __name__ == "__main__":
    unittest.main()