"""Pruebas de los tres paneles del overlay y de sus ajustes.

Ejecutar:
    .venv\\Scripts\\python.exe -m unittest scratch.test_overlays -v

El modo offscreen renderiza los paneles sin ventana real y la red se bloquea
en setUp para que todo salga de la cache local (como en el equipo real).
"""

import io
import json
import os
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import requests  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.live_player_metrics_service import (  # noqa: E402
    build_gold_report,
    build_rival_ranking,
    estimate_gold,
    format_delta,
    format_gold,
    player_role,
)
from app.services.overlay_alert_service import (  # noqa: E402
    ALERT_LEAD_SECONDS,
    PURCHASE_ALERT_SECONDS,
    OverlayAlertTracker,
    format_clock,
    is_completed_item,
)
from app.services.overlay_sound_service import (  # noqa: E402
    SOUND_KINDS,
    OverlaySoundService,
    build_beep_wav,
)
from app.services.tab_hotkey_service import (  # noqa: E402
    TabHotkeyService,
)
from app.ui.overlay_window import (  # noqa: E402
    CHAMPION_ICON_SIZE,
    MAX_ALERT_ROWS,
    OverlayWindow,
    PANEL_KEYS,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "data" / "items.json").read_text(encoding="utf-8"))
ITEMS = CATALOG.get("items", {})


def price(item_id: int) -> int:
    entry = ITEMS.get(str(item_id), {})
    gold = entry.get("gold", {})

    return int(gold.get("total", gold.get("base", 0)) or 0)


def item(item_id: int, slot: int) -> dict:
    return {
        "itemID": item_id,
        "slot": slot,
        "count": 1,
        "price": price(item_id),
        "displayName": ITEMS.get(str(item_id), {}).get("name", f"Objeto {item_id}"),
    }


def player(
    champion: str,
    riot_id: str,
    team: str,
    position: str,
    level: int,
    kda: tuple[int, int, int],
    cs: int,
    items: list[dict],
    spells: dict | None = None,
) -> dict:
    return {
        "championName": champion,
        "riotId": riot_id,
        "summonerName": riot_id.split("#")[0],
        "team": team,
        "position": position,
        "level": level,
        "scores": {
            "kills": kda[0],
            "deaths": kda[1],
            "assists": kda[2],
            "creepScore": cs,
        },
        "items": items,
        "summonerSpells": spells or {},
    }


FULL_ORDER = [
    player("Aatrox", "Top#EUW", "ORDER", "TOP", 9, (2, 3, 1), 80,
           [item(3075, 0), item(3068, 1), item(1001, 2)]),
    player("Briar", "Jg#EUW", "ORDER", "JUNGLE", 8, (3, 1, 4), 60,
           [item(6692, 0), item(3111, 1)]),
    player("Ahri", "Mid#EUW", "ORDER", "MIDDLE", 9, (1, 2, 3), 95,
           [item(6655, 0), item(3020, 1)]),
    player("Caitlyn", "Adc#EUW", "ORDER", "BOTTOM", 8, (4, 1, 2), 110,
           [item(6672, 0), item(3006, 1)]),
    player("Leona", "Sup#EUW", "ORDER", "UTILITY", 7, (0, 4, 8), 20,
           [item(3850, 0), item(3047, 1)]),
]

FULL_CHAOS = [
    player("Garen", "Garen#EUW", "CHAOS", "TOP", 9, (1, 3, 2), 85,
           [item(3078, 0), item(3047, 1)]),
    player("LeeSin", "Lee#EUW", "CHAOS", "JUNGLE", 8, (4, 2, 3), 62,
           [item(6691, 0), item(3047, 1)]),
    player("Syndra", "Syn#EUW", "CHAOS", "MIDDLE", 10, (5, 1, 2), 105,
           [item(6655, 0), item(3089, 1)]),
    player("Jinx", "Jinx#EUW", "CHAOS", "BOTTOM", 8, (2, 3, 3), 100,
           [item(6672, 0), item(3006, 1)]),
    player("Thresh", "Thr#EUW", "CHAOS", "SUPPORT", 6, (0, 5, 6), 18,
           [item(3850, 0), item(1001, 1)]),
]


def snapshot(game_time: float, **overrides) -> dict:
    base = {
        "game_time": game_time,
        "game_mode": "CLASSIC",
        "local_team": "ORDER",
        "local_player": FULL_ORDER[1],
        "all_players": FULL_ORDER + FULL_CHAOS,
        "enemies": FULL_CHAOS,
        "local_live_stats": {"currentGold": 800},
        "game_events": [],
    }
    base.update(overrides)

    return base


class MetricsTests(unittest.TestCase):
    def test_format_gold(self):
        self.assertEqual(format_gold(900), "900")
        self.assertEqual(format_gold(0), "0")
        self.assertEqual(format_gold(1000), "1.0K")
        self.assertEqual(format_gold(3500), "3.5K")
        self.assertEqual(format_gold(12345), "12.3K")
        self.assertEqual(format_gold(250000), "250K")

    def test_format_delta(self):
        self.assertEqual(format_delta(400), "+400")
        self.assertEqual(format_delta(-100), "-100")
        self.assertEqual(format_delta(0), "0")
        self.assertEqual(format_delta(2500), "+2.5K")
        self.assertEqual(format_delta(-1375), "-1.4K")

    def test_player_role(self):
        self.assertEqual(player_role({"position": "TOP"}), "TOP")
        self.assertEqual(player_role({"position": "JUNG"}), "JUNGLE")
        self.assertEqual(player_role({"position": "ADC"}), "BOTTOM")
        self.assertEqual(player_role({"position": "SUP"}), "UTILITY")
        self.assertEqual(
            player_role(
                {
                    "position": "",
                    "summonerSpells": {"a": {"displayName": "Smite"}},
                }
            ),
            "JUNGLE",
        )
        self.assertEqual(player_role({}), "UNKNOWN")

    def test_estimate_gold_uses_build_for_everyone(self):
        catalog = {"items": ITEMS}
        local = FULL_ORDER[1]
        inventory = sum(price(i["itemID"]) for i in local["items"])
        expected = inventory + 3 * 300 + 4 * 75 + 60 * 20

        # El jugador local ya no usa su oro en el bolsillo: mide la build.
        self.assertEqual(estimate_gold(local, catalog), expected)
        self.assertEqual(
            estimate_gold(local, catalog, current_gold=800),
            expected,
        )

    def test_local_gold_does_not_drop_after_spending(self):
        """Comprar un objeto sube o mantiene el oro, nunca lo baja."""
        catalog = {"items": ITEMS}
        before = FULL_ORDER[1]
        after = dict(before)
        # El jugador gasta su oro en un objeto terminado más.
        after["items"] = list(before["items"]) + [item(3078, 2)]

        self.assertGreaterEqual(
            estimate_gold(after, catalog),
            estimate_gold(before, catalog),
        )

    def test_gold_report_local_player_matches_manual_build(self):
        report = build_gold_report(snapshot(600.0), {"items": ITEMS})
        jungle = next(
            lane for lane in report["lanes"] if lane["role"] == "JUNGLE"
        )
        local = FULL_ORDER[1]
        inventory = sum(price(i["itemID"]) for i in local["items"])

        self.assertEqual(
            jungle["ally"]["gold"],
            inventory + 3 * 300 + 4 * 75 + 60 * 20,
        )

    def test_gold_report_pairs_roles_and_totals(self):
        report = build_gold_report(snapshot(600.0), {"items": ITEMS})

        self.assertEqual(
            [lane["role"] for lane in report["lanes"]],
            ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"],
        )
        for lane in report["lanes"]:
            self.assertTrue(lane["paired"])
            self.assertEqual(
                lane["delta"],
                lane["ally"]["gold"] - lane["enemy"]["gold"],
            )

        team = report["team"]
        self.assertEqual(team["delta"], team["ally"] - team["enemy"])
        self.assertGreater(team["ally"], 0)
        self.assertGreater(team["enemy"], 0)

    def test_gold_report_missing_role(self):
        players = FULL_ORDER + [
            p for p in FULL_CHAOS if p["position"] != "SUPPORT"
        ]
        report = build_gold_report(
            snapshot(600.0, all_players=players), {"items": ITEMS}
        )
        support = next(
            lane for lane in report["lanes"] if lane["role"] == "UTILITY"
        )
        self.assertFalse(support["paired"])
        self.assertIsNotNone(support["ally"])
        self.assertIsNone(support["enemy"])
        self.assertEqual(support["delta"], 0)

    def test_rival_ranking_strongest_and_weakest(self):
        ranking = build_rival_ranking(snapshot(600.0), {"items": ITEMS})
        strongest = ranking["strongest"]
        weakest = ranking["weakest"]

        self.assertEqual(strongest["champion"], "Syndra")
        self.assertIn(
            weakest["champion"], {"Jinx", "Thresh", "Garen", "LeeSin"}
        )
        self.assertGreaterEqual(strongest["score"], weakest["score"])

    def test_rival_ranking_without_enemies(self):
        ranking = build_rival_ranking(
            snapshot(600.0, all_players=FULL_ORDER), {"items": ITEMS}
        )
        self.assertIsNone(ranking["strongest"])
        self.assertIsNone(ranking["weakest"])

    def test_rival_ranking_single_enemy(self):
        ranking = build_rival_ranking(
            snapshot(
                600.0,
                all_players=FULL_ORDER + [FULL_CHAOS[0]],
            ),
            {"items": ITEMS},
        )
        self.assertEqual(ranking["strongest"]["champion"], "Garen")
        self.assertIsNone(ranking["weakest"])


class AlertServiceTests(unittest.TestCase):
    def test_completed_items(self):
        catalog = {"items": ITEMS}
        # Legendarios sí avisan...
        self.assertTrue(is_completed_item(3078, catalog))  # Trinidad
        self.assertTrue(is_completed_item(3089, catalog))  # Sombrero
        self.assertTrue(is_completed_item(6655, catalog))  # Tempestad
        # ...los componentes, las botas evolucionables de este parche,
        # la tienda base y los consumibles no.
        self.assertFalse(is_completed_item(1001, catalog))  # Botas base
        self.assertFalse(is_completed_item(1036, catalog))  # Espada larga
        self.assertFalse(is_completed_item(3006, catalog))  # Grebas (con into)
        self.assertFalse(is_completed_item(2003, catalog))  # Poción
        self.assertFalse(is_completed_item(3340, catalog))  # Trinket
        self.assertFalse(is_completed_item(3850, catalog))  # Misión support
        self.assertFalse(is_completed_item(999999, catalog))  # Desconocido

    def test_no_purchase_alert_on_first_snapshot(self):
        tracker = OverlayAlertTracker({"items": ITEMS})
        alerts = tracker.update(snapshot(300.0))
        purchases = [a for a in alerts if a["kind"] == "purchase"]
        self.assertEqual(purchases, [])

    def test_purchase_alert_on_completed_item(self):
        tracker = OverlayAlertTracker({"items": ITEMS})
        tracker.update(snapshot(300.0))

        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        aatrox = dict(changed[0])
        aatrox["items"] = list(aatrox["items"]) + [item(3078, 3)]
        changed[0] = aatrox

        alerts = tracker.update(snapshot(305.0, all_players=changed))
        purchases = [a for a in alerts if a["kind"] == "purchase"]
        self.assertEqual(len(purchases), 1)
        self.assertEqual(purchases[0]["champion"], "Aatrox")
        self.assertEqual(purchases[0]["side"], "ally")
        self.assertEqual(purchases[0]["item_id"], 3078)
        self.assertIn("trinidad", purchases[0]["item_name"].casefold())

    def test_component_purchase_is_silent(self):
        tracker = OverlayAlertTracker({"items": ITEMS})
        tracker.update(snapshot(300.0))

        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        leona = dict(changed[4])
        leona["items"] = list(leona["items"]) + [item(1036, 2)]
        changed[4] = leona

        alerts = tracker.update(snapshot(305.0, all_players=changed))
        self.assertEqual(
            [a for a in alerts if a["kind"] == "purchase"], []
        )

    def test_purchases_expire(self):
        tracker = OverlayAlertTracker(
            {"items": ITEMS}, purchase_seconds=PURCHASE_ALERT_SECONDS
        )
        tracker.update(snapshot(300.0))

        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        jinx = dict(changed[8])
        jinx["items"] = list(jinx["items"]) + [item(3085, 2)]
        changed[8] = jinx

        alerts = tracker.update(snapshot(305.0, all_players=changed))
        self.assertEqual(
            len([a for a in alerts if a["kind"] == "purchase"]), 1
        )

        later = 305.0 + PURCHASE_ALERT_SECONDS + 1
        alerts = tracker.update(snapshot(later, all_players=changed))
        self.assertEqual(
            [a for a in alerts if a["kind"] == "purchase"], []
        )

    def test_dragon_countdown_one_minute_before(self):
        tracker = OverlayAlertTracker(
            {"items": ITEMS}, lead_seconds=ALERT_LEAD_SECONDS
        )
        alerts = tracker.update(snapshot(240.0))
        dragon = [
            a for a in alerts if a.get("key") == "objective:dragon"
        ]
        self.assertEqual(len(dragon), 1)
        self.assertEqual(dragon[0]["name"], "Dragón")
        self.assertAlmostEqual(dragon[0]["remaining"], 60.0, places=3)

        alerts = tracker.update(snapshot(200.0))
        self.assertEqual(
            [a for a in alerts if a["kind"] == "objective"], []
        )

    def test_objectives_follow_kill_events(self):
        tracker = OverlayAlertTracker({"items": ITEMS})
        first = snapshot(
            360.0,
            game_events=[
                {
                    "EventID": 7,
                    "EventName": "DragonKill",
                    "EventTime": 355.0,
                    "KillerName": "Lee",
                }
            ],
        )
        tracker.update(first)

        # 5 minutos después de la muerte: vuelve a avisar un minuto antes.
        alerts = tracker.update(snapshot(595.0))
        dragon = [
            a for a in alerts if a.get("key") == "objective:dragon"
        ]
        self.assertEqual(len(dragon), 1)
        self.assertAlmostEqual(dragon[0]["remaining"], 60.0, places=3)

    def test_elder_after_four_dragons(self):
        tracker = OverlayAlertTracker({"items": ITEMS})
        events = [
            {
                "EventID": index,
                "EventName": "DragonKill",
                "EventTime": 300.0 + index * 300.0,
                "KillerName": "Lee",
            }
            for index in range(4)
        ]
        tracker.update(snapshot(1210.0, game_events=events))

        self.assertTrue(tracker.elder_active)
        alerts = tracker.update(snapshot(1500.0))
        dragon = [
            a for a in alerts if a.get("key") == "objective:dragon"
        ]
        self.assertEqual(len(dragon), 1)
        self.assertEqual(dragon[0]["name"], "Anciano")

    def test_herald_single_spawn(self):
        tracker = OverlayAlertTracker({"items": ITEMS})
        alerts = tracker.update(snapshot(840.0))
        herald = [
            a for a in alerts if a.get("key") == "objective:herald"
        ]
        self.assertEqual(len(herald), 1)
        self.assertEqual(herald[0]["name"], "Heraldo")

        taken = snapshot(
            950.0,
            game_events=[
                {
                    "EventID": 12,
                    "EventName": "HeraldKill",
                    "EventTime": 945.0,
                    "KillerName": "Jg",
                }
            ],
        )
        tracker.update(taken)
        alerts = tracker.update(snapshot(1000.0))
        self.assertEqual(
            [a for a in alerts if a.get("key") == "objective:herald"], []
        )

    def test_format_clock(self):
        self.assertEqual(format_clock(47), "0:47")
        self.assertEqual(format_clock(60), "1:00")
        self.assertEqual(format_clock(0), "0:00")


class TabHotkeyServiceTests(unittest.TestCase):
    """El vigilante de TAB solo emite en cada flanco y nunca rompe nada."""

    def test_down_then_up_emits_each_edge_once(self):
        states = [False, False, True, True, True, False, False]
        service = TabHotkeyService(reader=lambda: states.pop(0))
        emitted: list[bool] = []
        service.tab_changed.connect(emitted.append)
        service.available = True

        for _ in range(len(states)):
            service._poll()

        self.assertEqual(emitted, [True, False])
        self.assertFalse(service.is_tab_down)

    def test_is_tab_down_tracks_state(self):
        service = TabHotkeyService(reader=lambda: True)
        service.available = True

        service._poll()

        self.assertTrue(service.is_tab_down)

    def test_broken_reader_is_ignored(self):
        def boom():
            raise RuntimeError("sin teclado")

        service = TabHotkeyService(reader=boom)
        emitted: list[bool] = []
        service.tab_changed.connect(emitted.append)

        service._poll()

        self.assertEqual(emitted, [])

    def test_unavailable_service_never_starts(self):
        service = TabHotkeyService()

        if not service.available:
            service.start()
            self.assertFalse(service._timer.isActive())


class SoundServiceTests(unittest.TestCase):
    """Pitidos emulados: distintos por tipo, con volumen y sin archivos."""

    def test_every_kind_has_its_own_pitido(self):
        wavs = {kind: build_beep_wav(kind) for kind in SOUND_KINDS}

        self.assertEqual(set(wavs), set(SOUND_KINDS))
        self.assertEqual(
            len(set(wavs.values())),
            len(SOUND_KINDS),
            "cada tipo de aviso debe sonar distinto",
        )

    def test_wav_is_valid_and_not_empty(self):
        for kind in SOUND_KINDS:
            data = build_beep_wav(kind)

            self.assertGreater(len(data), 44, kind)

            with wave.open(io.BytesIO(data), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1, kind)
                self.assertEqual(handle.getsampwidth(), 2, kind)
                self.assertEqual(handle.getframerate(), 22050, kind)
                self.assertGreater(handle.getnframes(), 0, kind)

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            build_beep_wav("no-existe")

    def test_zero_volume_is_silent(self):
        data = build_beep_wav("dragon", volume=0.0)

        with wave.open(io.BytesIO(data), "rb") as handle:
            frames = handle.readframes(handle.getnframes())

        self.assertFalse(any(frames))

    def test_volume_is_clamped(self):
        service = OverlaySoundService(volume=5)

        self.assertEqual(service.volume, 1.0)

        service.set_volume(-3)
        self.assertEqual(service.volume, 0.0)

        service.set_volume("no-numero")
        self.assertGreater(service.volume, 0.0)

    def test_service_plays_the_right_pitido(self):
        played = []
        service = OverlaySoundService(player=played.append, async_play=False)

        self.assertTrue(service.play_dragon_spawn())
        self.assertEqual(len(played), 1)
        self.assertEqual(played[0], service.wav_for("dragon"))

        service.play_objective_spawn()
        self.assertEqual(played[-1], service.wav_for("objective"))

        service.play_enemy_buy()
        self.assertEqual(played[-1], service.wav_for("enemy_buy"))

    def test_disabled_service_is_silent(self):
        played = []
        service = OverlaySoundService(player=played.append, async_play=False)
        service.set_enabled(False)

        self.assertFalse(service.play_dragon_spawn())
        self.assertEqual(played, [])

        service.set_enabled(True)
        self.assertTrue(service.play_dragon_spawn())
        self.assertEqual(len(played), 1)

    def test_disabled_kind_is_silent(self):
        played = []
        service = OverlaySoundService(player=played.append, async_play=False)
        service.set_kind_enabled("dragon", False)

        self.assertFalse(service.play_dragon_spawn())
        self.assertTrue(service.play_objective_spawn())
        self.assertEqual(len(played), 1)
        self.assertTrue(service.kind_enabled("objective"))
        self.assertFalse(service.kind_enabled("dragon"))

    def test_same_kind_is_throttled(self):
        played = []
        service = OverlaySoundService(player=played.append, async_play=False)

        self.assertTrue(service.play_dragon_spawn())
        self.assertFalse(service.play_dragon_spawn())
        self.assertEqual(len(played), 1)

    def test_player_errors_never_break_the_overlay(self):
        def boom(_data):
            raise RuntimeError("sin audio")

        service = OverlaySoundService(player=boom, async_play=False)

        self.assertTrue(service.play_dragon_spawn())


class _SoundRecorder:
    """Guarda los tipos de pitido reproducidos por un servicio."""

    def __init__(self, service):
        self.service = service
        self.kinds: list[str] = []

    def __call__(self, data: bytes) -> None:
        for kind in SOUND_KINDS:
            if data == self.service.wav_for(kind):
                self.kinds.append(kind)
                return


class OverlayWindowTests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        self.network_patcher = patch.object(
            requests, "get", side_effect=AssertionError("sin red")
        )
        self.network_patcher.start()
        self.settings = {}
        self.saved: dict = {}
        self.overlay = OverlayWindow(
            {"items": ITEMS},
            settings_service=self.FakeSettingsService(self),
            settings=self.settings,
        )
        self.app.processEvents()

    class FakeSettingsService:
        def __init__(self, test):
            self.test = test

        def load(self):
            return {}

        def save(self, settings):
            self.test.saved = dict(settings)

    def tearDown(self):
        self.network_patcher.stop()
        try:
            self.overlay.close()
        except RuntimeError:
            pass
        for _ in range(3):
            self.app.processEvents()

    def test_panels_visible_only_in_game(self):
        for key, panel in self.overlay.panels.items():
            self.assertFalse(panel.isVisible(), key)

        self.overlay.update_snapshot(snapshot(600.0))
        self.app.processEvents()

        for key in PANEL_KEYS:
            self.assertTrue(
                self.overlay.panels[key].isVisible(), key
            )

        self.overlay.clear()
        self.app.processEvents()

        for key, panel in self.overlay.panels.items():
            self.assertFalse(panel.isVisible(), key)

    def test_gold_panel_texts(self):
        self.overlay.update_snapshot(snapshot(600.0))
        panel = self.overlay.panels["gold"]

        report = build_gold_report(
            snapshot(600.0), {"items": ITEMS}
        )
        self.assertEqual(
            panel.total.ally_gold.text(),
            format_gold(report["team"]["ally"]),
        )
        self.assertEqual(
            panel.total.enemy_gold.text(),
            format_gold(report["team"]["enemy"]),
        )
        self.assertEqual(len(panel.rows), 5)
        self.assertEqual(panel.rows[0].role.text(), "TOP")
        self.assertEqual(panel.rows[0].delta.text()[0] in "+-0", True)

    def test_threat_panel_rows(self):
        self.overlay.update_snapshot(snapshot(600.0))
        panel = self.overlay.panels["threat"]

        self.assertTrue(panel.strongest.isVisible())
        self.assertTrue(panel.weakest.isVisible())
        self.assertEqual(panel.strongest.name.text(), "Syndra")
        self.assertEqual(panel.strongest.marker.text(), "▲")
        self.assertEqual(panel.weakest.marker.text(), "▼")

    def test_champion_icons_come_from_local_cache(self):
        self.overlay.update_snapshot(snapshot(600.0))
        panel = self.overlay.panels["gold"]
        icon = panel.rows[0].ally_icon

        self.assertFalse(icon.pixmap().isNull())
        self.assertLessEqual(icon.pixmap().width(), CHAMPION_ICON_SIZE)
        self.assertFalse(icon.text())

    def test_item_icons_come_from_local_cache(self):
        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        aatrox = dict(changed[0])
        aatrox["items"] = list(aatrox["items"]) + [item(3078, 3)]
        changed[0] = aatrox

        self.overlay.update_snapshot(snapshot(300.0))
        self.overlay.update_snapshot(snapshot(305.0, all_players=changed))
        panel = self.overlay.panels["alerts"]
        row = next(r for r in panel.rows if r.isVisible())

        self.assertIn("trinidad", row.text.toolTip().casefold())
        self.assertTrue(
            row.text.text().casefold().startswith("fuerza de"),
            row.text.text(),
        )
        self.assertFalse(row.slot_b.pixmap().isNull())
        self.assertFalse(row.slot_a.pixmap().isNull())

    def test_alerts_panel_renders_feed(self):
        self.overlay.update_snapshot(snapshot(840.0))
        panel = self.overlay.panels["alerts"]
        texts = [row.text.text() for row in panel.rows if row.isVisible()]
        self.assertIn("Heraldo", texts)

    def test_panel_toggles(self):
        self.overlay.set_panel_enabled("threat", False)
        self.assertFalse(self.overlay.is_panel_enabled("threat"))

        self.overlay.update_snapshot(snapshot(600.0))
        self.assertFalse(self.overlay.panels["threat"].isVisible())
        self.assertTrue(self.overlay.panels["gold"].isVisible())

        enabled = self.overlay.toggle_panel("threat")
        self.assertTrue(enabled)
        self.assertTrue(self.overlay.panels["threat"].isVisible())

    def test_toggle_all(self):
        self.assertTrue(self.overlay.any_enabled())
        enabled = self.overlay.toggle_all()
        self.assertFalse(enabled)
        self.assertFalse(self.overlay.any_enabled())

        enabled = self.overlay.toggle_all()
        self.assertTrue(enabled)
        self.assertTrue(self.overlay.any_enabled())

    def test_opacity_and_click_through(self):
        self.overlay.set_overlay_opacity(75)
        for panel in self.overlay.panels.values():
            self.assertAlmostEqual(panel.windowOpacity(), 0.75, places=2)

        self.overlay.set_click_through(True)
        self.assertTrue(self.overlay.click_through)
        for panel in self.overlay.panels.values():
            self.assertTrue(panel.click_through)

    def test_settings_are_persisted(self):
        self.overlay.set_panel_enabled("threat", False)
        self.overlay.set_overlay_opacity(80)
        self.overlay.set_alert_lead_seconds(45)

        self.assertEqual(
            self.saved["overlay_panels"],
            {"gold": True, "alerts": True, "threat": False},
        )
        self.assertEqual(self.saved["overlay_opacity"], 80)
        self.assertEqual(self.saved["overlay_alert_lead"], 45)

    def test_sound_settings_are_persisted(self):
        self.overlay.set_sound_enabled(False)
        self.overlay.set_sound_kind_enabled("dragon", False)
        self.overlay.set_sound_volume(0.35)

        self.assertFalse(self.saved["overlay_sound_enabled"])
        self.assertFalse(self.saved["overlay_sound_dragon"])
        self.assertTrue(self.saved["overlay_sound_objective"])
        self.assertTrue(self.saved["overlay_sound_enemy_buy"])
        self.assertAlmostEqual(self.saved["overlay_sound_volume"], 0.35, places=2)

    def test_sound_settings_are_restored(self):
        stored = {
            "overlay_sound_enabled": True,
            "overlay_sound_objective": True,
            "overlay_sound_dragon": False,
            "overlay_sound_enemy_buy": False,
            "overlay_sound_volume": 0.25,
        }
        overlay = OverlayWindow(
            {"items": ITEMS},
            settings_service=self.FakeSettingsService(self),
            settings=dict(stored),
        )
        self.app.processEvents()

        self.assertTrue(overlay.is_sound_enabled())
        self.assertTrue(overlay.sound_service.kind_enabled("objective"))
        self.assertFalse(overlay.sound_service.kind_enabled("dragon"))
        self.assertFalse(overlay.sound_service.kind_enabled("enemy_buy"))
        self.assertAlmostEqual(overlay.sound_service.volume, 0.25, places=2)
        overlay.close()

    def test_master_switch_stops_every_pitido(self):
        recorder = self.install_sound_recorder()
        self.overlay.set_sound_enabled(False)

        self.overlay.update_snapshot(snapshot(240.0))

        self.assertEqual(recorder.kinds, [])

    def test_dragon_alert_plays_dragon_pitido(self):
        recorder = self.install_sound_recorder()

        # A 4:00 el dragón aparece a las 5:00: aviso con 60 s de antelación.
        self.overlay.update_snapshot(snapshot(240.0))

        self.assertIn("dragon", recorder.kinds)
        self.assertNotIn("objective", recorder.kinds)

    def test_objective_alert_plays_objective_pitido(self):
        recorder = self.install_sound_recorder()

        # Grumos a las 8:00, con el aviso de un minuto por delante.
        self.overlay.update_snapshot(snapshot(420.0))

        self.assertIn("objective", recorder.kinds)
        self.assertNotIn("dragon", recorder.kinds)

    def test_pitido_sounds_once_per_alert(self):
        recorder = self.install_sound_recorder()

        self.overlay.update_snapshot(snapshot(240.0))
        played = len(recorder.kinds)
        self.overlay.update_snapshot(snapshot(241.0))

        self.assertEqual(len(recorder.kinds), played)

    def test_enemy_purchase_plays_pitido(self):
        recorder = self.install_sound_recorder()
        self.overlay.update_snapshot(snapshot(300.0))
        recorder.kinds.clear()

        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        garen = dict(changed[5])
        garen["items"] = list(garen["items"]) + [item(3078, 2)]
        changed[5] = garen

        self.overlay.update_snapshot(snapshot(305.0, all_players=changed))

        self.assertIn("enemy_buy", recorder.kinds)

    def test_ally_purchase_is_silent(self):
        recorder = self.install_sound_recorder()
        self.overlay.update_snapshot(snapshot(300.0))
        recorder.kinds.clear()

        changed = [dict(p) for p in FULL_ORDER + FULL_CHAOS]
        aatrox = dict(changed[0])
        aatrox["items"] = list(aatrox["items"]) + [item(3078, 3)]
        changed[0] = aatrox

        self.overlay.update_snapshot(snapshot(305.0, all_players=changed))

        self.assertEqual(recorder.kinds, [])

    def test_new_game_forgets_played_alerts(self):
        """Al empezar otra partida los avisos pueden volver a sonar."""
        self.overlay.update_snapshot(snapshot(240.0))
        self.assertIn("objective:dragon", self.overlay._last_sound_alerts)

        # El reloj retrocede más de cinco segundos: es otra partida.
        self.overlay.update_snapshot(snapshot(30.0))

        self.assertEqual(self.overlay._last_sound_alerts, set())

    def test_tab_only_hides_and_shows_panels(self):
        self.overlay.update_snapshot(snapshot(600.0))
        gold = self.overlay.panels["gold"]
        alerts = self.overlay.panels["alerts"]

        self.assertTrue(gold.isVisible())
        self.assertTrue(alerts.isVisible())

        self.overlay.set_tab_only("gold", True)
        self.overlay._on_tab_changed(False)

        self.assertFalse(gold.isVisible())
        self.assertTrue(alerts.isVisible())

        self.overlay._on_tab_changed(True)

        self.assertTrue(gold.isVisible())
        self.assertTrue(alerts.isVisible())

    def test_tab_only_outside_game_stays_hidden(self):
        self.overlay.set_tab_only("alerts", True)
        self.overlay._on_tab_changed(True)
        self.overlay.update_snapshot(snapshot(600.0))

        self.assertTrue(self.overlay.panels["alerts"].isVisible())

        self.overlay.clear()
        self.overlay._on_tab_changed(True)

        self.assertFalse(self.overlay.panels["alerts"].isVisible())

    def test_tab_only_settings_are_persisted(self):
        self.overlay.set_tab_only("threat", True)

        self.assertEqual(
            self.saved["overlay_tab_only"],
            {"gold": False, "alerts": False, "threat": True},
        )

    def test_tab_hotkey_service_drives_visibility(self):
        self.overlay.update_snapshot(snapshot(600.0))
        service = TabHotkeyService(reader=lambda: True)
        service.available = True
        service._poll()
        self.overlay.connect_tab_hotkey(service)

        self.overlay.set_tab_only("gold", True)
        self.assertTrue(self.overlay.tab_down)
        self.assertTrue(self.overlay.panels["gold"].isVisible())

        self.overlay._on_tab_changed(False)
        self.assertFalse(self.overlay.panels["gold"].isVisible())

    def install_sound_recorder(self) -> "_SoundRecorder":
        service = OverlaySoundService(async_play=False)
        recorder = _SoundRecorder(service)
        service.player = recorder
        self.overlay.sound_service = service

        return recorder

    def test_settings_are_restored(self):
        stored = {
            "overlay_panels": {
                "gold": True,
                "alerts": False,
                "threat": True,
            },
            "overlay_positions": {
                "gold": [40, 50],
                "alerts": [40, 300],
                "threat": [40, 500],
            },
            "overlay_opacity": 85,
            "overlay_click_through": True,
            "overlay_alert_lead": 30,
        }
        overlay = OverlayWindow(
            {"items": ITEMS},
            settings_service=self.FakeSettingsService(self),
            settings=dict(stored),
        )
        self.app.processEvents()

        self.assertFalse(overlay.is_panel_enabled("alerts"))
        self.assertTrue(overlay.click_through)
        self.assertEqual(overlay.opacity, 85)
        self.assertEqual(overlay.alert_lead_seconds, 30)
        self.assertEqual(
            (overlay.panels["gold"].x(), overlay.panels["gold"].y()),
            (40, 50),
        )
        overlay.close()


class SettingsPageSoundTests(unittest.TestCase):
    """Los ajustes de los pitidos viven en la página de Ajustes."""

    def setUp(self):
        self.app = QApplication.instance() or QApplication([])
        # La construcción de la ventana pinta iconos: se evita la red dejando
        # que los runes sin caché local se queden sin imagen.
        self.icon_patcher = patch(
            "app.ui.local_analysis_dialog.get_rune_icon_path",
            return_value=None,
        )
        self.icon_patcher.start()
        self.saved: dict = {}
        self.settings_patcher = patch(
            "app.ui.main_window.SettingsService",
            new=self.fake_settings_factory(),
        )
        self.settings_patcher.start()

        from app.ui.main_window import MainWindow

        self.window = MainWindow(version="test", item_catalog={"items": ITEMS})
        self.app.processEvents()

    def fake_settings_factory(self):
        saved = self.saved

        class FakeSettingsService:
            def __init__(self, *args, **kwargs):
                pass

            def load(self):
                return {}

            def save(self, settings):
                saved.clear()
                saved.update(settings)

        return FakeSettingsService

    def tearDown(self):
        try:
            self.window.close()
        except RuntimeError:
            pass

        for _ in range(3):
            self.app.processEvents()

        self.settings_patcher.stop()
        self.icon_patcher.stop()

    def test_sound_controls_exist_and_match_state(self):
        window = self.window

        self.assertTrue(window.sound_enabled_checkbox.isChecked())
        self.assertTrue(window.sound_objective_checkbox.isChecked())
        self.assertTrue(window.sound_dragon_checkbox.isChecked())
        self.assertTrue(window.sound_enemy_buy_checkbox.isChecked())
        self.assertGreater(window.sound_volume_slider.value(), 0)

    def test_master_checkbox_controls_the_overlay(self):
        window = self.window

        window.sound_enabled_checkbox.setChecked(False)
        self.app.processEvents()

        self.assertFalse(window.overlay.is_sound_enabled())
        self.assertFalse(window.sound_dragon_checkbox.isEnabled())
        self.assertFalse(window.sound_volume_slider.isEnabled())
        self.assertFalse(self.saved["overlay_sound_enabled"])

        window.sound_enabled_checkbox.setChecked(True)
        self.app.processEvents()

        self.assertTrue(window.overlay.is_sound_enabled())
        self.assertTrue(window.sound_dragon_checkbox.isEnabled())
        self.assertTrue(self.saved["overlay_sound_enabled"])

    def test_kind_checkboxes_are_saved(self):
        window = self.window

        window.sound_dragon_checkbox.setChecked(False)
        self.app.processEvents()

        self.assertFalse(window.overlay.sound_service.kind_enabled("dragon"))
        self.assertFalse(self.saved["overlay_sound_dragon"])
        self.assertTrue(self.saved["overlay_sound_objective"])
        self.assertTrue(self.saved["overlay_sound_enemy_buy"])

    def test_volume_slider_changes_the_overlay(self):
        window = self.window

        window.sound_volume_slider.setValue(30)
        self.app.processEvents()

        self.assertAlmostEqual(
            window.overlay.sound_service.volume, 0.30, places=2
        )
        self.assertAlmostEqual(self.saved["overlay_sound_volume"], 0.30, places=2)
        self.assertEqual(window.sound_volume_value.text(), "30%")

    def test_tab_only_checkboxes_exist_and_match_state(self):
        window = self.window

        self.assertEqual(
            set(window.overlay_tab_only_checkboxes),
            {"gold", "alerts", "threat"},
        )

        for key, checkbox in window.overlay_tab_only_checkboxes.items():
            self.assertFalse(checkbox.isChecked(), key)

    def test_tab_only_checkbox_toggles_overlay_and_persists(self):
        window = self.window

        window.overlay_tab_only_checkboxes["gold"].setChecked(True)
        self.app.processEvents()

        self.assertTrue(window.overlay.is_tab_only("gold"))
        self.assertFalse(window.overlay.is_tab_only("alerts"))
        self.assertEqual(
            self.saved["overlay_tab_only"],
            {"gold": True, "alerts": False, "threat": False},
        )

    def test_api_key_save_keeps_overlay_settings(self):
        window = self.window

        # Las claves no deben borrarse al persistir otros ajustes del overlay.
        window.settings.update(
            {
                "riot_api_key": "RGAPI-falso",
                "gemini_api_key": "AIza-falso",
            }
        )
        window.overlay.set_tab_only("alerts", True)

        self.assertEqual(self.saved["riot_api_key"], "RGAPI-falso")
        self.assertEqual(self.saved["gemini_api_key"], "AIza-falso")
        self.assertEqual(
            self.saved["overlay_tab_only"],
            {"gold": False, "alerts": True, "threat": False},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
