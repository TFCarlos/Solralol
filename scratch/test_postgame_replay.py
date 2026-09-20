"""Ventana independiente de repaso post-partida (vídeo + desglose).

Comprueba, sin red, sin partidas reales y sin ffmpeg:

1. El desglose se construye **siempre con la telemetría local**: aunque la
   sesión esté sincronizada con Riot y traiga eventos/valores oficiales
   distintos, el marcador, los sucesos y el radar salen de los snapshots y
   eventos locales.
2. El botón «Re-desglosar» recarga la sesión de disco y reconstruye todo.
3. La barra de reproducción coloca los indicadores de la partida y salta al
   suceso pulsado (con el desfase entre vídeo y partida respetado).
4. La ventana abre desde MainWindow (fila de partida guardada y pestaña
   Grabaciones) y localiza el vídeo por ``session_id``.

Ejecutar: python -m unittest scratch.test_postgame_replay
"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
)

from app.services.recording_service import (  # noqa: E402
    RecordingLibrary,
    parse_iso_timestamp,
    session_matches_video_metadata,
)
from app.ui.postgame_replay_window import PostgameReplayWindow  # noqa: E402
from app.ui.postgame_sidebar import (  # noqa: E402
    PostgameSidebar,
    build_review_events,
    kind_glyph,
    normalise_objective_kind,
    objective_side,
    player_final_stats,
    radar_values,
)


def local_session() -> dict:
    """Sesión de ejemplo: telemetría local + datos de Riot contradictorios."""
    return {
        "schema_version": 2,
        "session_id": "sesion-local-1",
        "champion_name": "Briar",
        "game_mode": "CLASSIC",
        "duration": 1800.0,
        "local_player_key": "local",
        "local_team": "ORDER",
        "players": {
            "local": {
                "champion_name": "Briar",
                "riot_id": "Solrasar#000",
                "role": "JUNGLE",
                "team": "ORDER",
                "win": True,
            },
            "ally": {
                "champion_name": "Ahri",
                "role": "MIDDLE",
                "team": "ORDER",
                "win": True,
            },
            "enemy": {
                "champion_name": "Lee Sin",
                "role": "JUNGLE",
                "team": "CHAOS",
                "win": False,
            },
            "enemy2": {
                "champion_name": "Ahri",
                "role": "MIDDLE",
                "team": "CHAOS",
                "win": False,
            },
        },
        "lane_matchups": {
            "JUNGLE": {"ally_key": "local", "enemy_key": "enemy"},
        },
        "snapshots": [
            {
                "time": 300.0,
                "players": {
                    "local": {
                        "kills": 1,
                        "deaths": 0,
                        "assists": 1,
                        "cs": 40,
                        "level": 6,
                        "estimated_gold": 3200,
                        "stats": {"vision_score": 6},
                    }
                },
            },
            {
                "time": 900.0,
                "players": {
                    "local": {
                        "kills": 7,
                        "deaths": 2,
                        "assists": 5,
                        "cs": 150,
                        "level": 12,
                        "estimated_gold": 12500,
                        "stats": {"vision_score": 24},
                    }
                },
            },
        ],
        "final_sync": {"status": "synced", "source": "riot_match_v5"},
    }


def with_events(session: dict) -> dict:
    """Añade los eventos locales y los datos oficiales contradictorios."""
    session["events"] = [
        {
            "time": 600.0,
            "order": 1,
            "type": "kill_exact",
            "player_key": "local",
            "killer_key": "local",
            "victim_key": "enemy",
            "assister_keys": [],
            "team": "ORDER",
            "label": "Asesinato 1",
        },
        {
            "time": 650.0,
            "order": 2,
            "type": "kill_exact",
            "player_key": "ally",
            "killer_key": "ally",
            "victim_key": "enemy2",
            "assister_keys": [],
            "team": "ORDER",
            "label": "Asesinato de Ahri",
        },
        {
            "time": 700.0,
            "order": 3,
            "type": "kill_exact",
            "player_key": "enemy",
            "killer_key": "enemy",
            "victim_key": "ally",
            "assister_keys": ["local"],
            "team": "CHAOS",
            "label": "Asistencia 1",
        },
        {
            "time": 800.0,
            "order": 4,
            "type": "death_exact",
            "player_key": "local",
            "killer_key": "enemy",
            "victim_key": "local",
            "team": "ORDER",
            "label": "Muerte 1",
        },
        {
            "time": 900.0,
            "order": 5,
            "type": "objective",
            "player_key": None,
            "team": "ORDER",
            "objective": "dragon",
            "label": "Equipo aliado consiguió Dragón",
        },
        {
            "time": 1200.0,
            "order": 6,
            "type": "objective",
            "player_key": None,
            "team": "CHAOS",
            "objective": "baron",
            "label": "Equipo enemigo consiguió Barón",
        },
        {
            "time": 1400.0,
            "order": 7,
            "type": "objective",
            "player_key": None,
            "team": "ORDER",
            "objective": "rift_herald",
            "label": "Equipo aliado consiguió Heraldo",
        },
        {
            "time": 1500.0,
            "order": 8,
            "type": "item_purchase",
            "player_key": "local",
            "team": "ORDER",
            "label": "Filo de la infinito",
        },
    ]
    # Datos oficiales de Riot: el desglose NO debe usarlos.
    session["official_events"] = [
        {
            "time": 120.0,
            "type": "kill",
            "player_key": "local",
            "label": "Evento oficial de Riot",
        }
    ]
    session["riot_match"] = {
        "info": {
            "participants": [
                {
                    "championName": "Briar",
                    "kills": 3,
                    "deaths": 9,
                    "assists": 1,
                    "totalMinionsKilled": 10,
                }
            ]
        }
    }

    return session


def sample_session() -> dict:
    return with_events(local_session())


def scoreboard_cards(sidebar) -> list:
    """Tarjetas del marcador VS (una por jugador)."""
    return sidebar.findChildren(QFrame, "postgamePlayerCard")


def card_labels(card, object_name: str) -> list[str]:
    return [label.text() for label in card.findChildren(QLabel, object_name)]


class SidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        for widget in getattr(self, "_widgets", []):
            widget.close()
            widget.deleteLater()

        self.app.processEvents()

    def track(self, widget):
        self._widgets = getattr(self, "_widgets", [])
        self._widgets.append(widget)

        return widget

    def test_scoreboard_lists_the_local_team_first(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        cards = scoreboard_cards(sidebar)

        self.assertEqual(len(cards), 4)
        self.assertEqual(card_labels(cards[0], "postgameChampionName"), ["Briar"])
        self.assertEqual(card_labels(cards[0], "postgameStatKda"), ["7 / 2 / 5"])
        self.assertEqual(card_labels(cards[0], "postgameStatCs"), ["150"])
        self.assertEqual(sidebar.player_key, "local")
        self.assertEqual(sidebar.player_combo.currentData(), "local")

    def test_scoreboard_groups_teams_side_by_side(self):
        sidebar = self.track(PostgameSidebar(sample_session()))

        ally_cards = sidebar.ally_column.findChildren(QFrame, "postgamePlayerCard")
        enemy_cards = sidebar.enemy_column.findChildren(QFrame, "postgamePlayerCard")

        self.assertEqual(len(ally_cards), 2)
        self.assertEqual(len(enemy_cards), 2)
        self.assertIn("(", sidebar.team_header.text())
        ally_names = [
            label.text()
            for card in sidebar.ally_column.findChildren(
                QFrame, "postgamePlayerCard"
            )
            for label in card.findChildren(QLabel, "postgameChampionName")
        ]
        enemy_names = [
            label.text()
            for card in sidebar.enemy_column.findChildren(
                QFrame, "postgamePlayerCard"
            )
            for label in card.findChildren(QLabel, "postgameChampionName")
        ]

        self.assertEqual(sorted(ally_names), ["Ahri", "Briar"])
        self.assertEqual(sorted(enemy_names), ["Ahri", "Lee Sin"])

    def test_review_markers_mirror_the_current_filter(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        markers = sidebar.review_markers(30.0)
        marker_kinds = {marker["kind"] for marker in markers}

        # item_purchase existe en la revisión pero no sale en la barra.
        self.assertEqual(
            len(markers),
            len(sidebar.review_events)
            - sum(
                1
                for event in sidebar.review_events
                if event["kind"] == "item_purchase"
            ),
        )
        self.assertEqual(
            [marker["time"] for marker in markers],
            [
                round(max(0.0, event["time"] - 30.0), 1)
                for event in sidebar.review_events
                if event["kind"] != "item_purchase"
            ],
        )
        self.assertNotIn("item_purchase", {m["kind"] for m in markers})

        sidebar.set_scope(PostgameSidebar.SCOPE_ALL)
        markers = sidebar.review_markers(30.0)

        self.assertEqual(len(markers), len(sidebar.review_events))
        self.assertIn("dragon", {marker["kind"] for marker in markers})

    def test_radar_is_painted_without_errors(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        sidebar.radar.resize(320, 240)

        pixmap = QPixmap(320, 240)
        sidebar.radar.render(pixmap)

        self.assertFalse(pixmap.isNull())
        self.assertEqual(sidebar.radar.player_label, "Briar")
        self.assertEqual(sidebar.radar.enemy_label, "Lee Sin")

    def test_selecting_another_player_updates_radar_and_timeline(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        sidebar.set_player("enemy")

        self.assertEqual(sidebar.player_key, "enemy")
        self.assertEqual(sidebar.player_combo.currentData(), "enemy")
        self.assertEqual(sidebar.radar.player_label, "Lee Sin")
        self.assertEqual(sidebar.radar.enemy_label, "Briar")
        kinds = [event["kind"] for event in sidebar.review_events]
        self.assertEqual(
            kinds, ["kill", "dragon", "baron", "rift_herald"]
        )
        self.assertTrue(
            all(
                event["player_key"] in {None, "enemy"}
                for event in sidebar.review_events
            )
        )

    def test_local_scope_keeps_only_the_selected_player_events(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        kinds = [event["kind"] for event in sidebar.review_events]

        self.assertEqual(kinds.count("kill"), 1)
        self.assertEqual(kinds.count("assist"), 1)
        self.assertIn("item_purchase", kinds)

        sidebar.set_scope(PostgameSidebar.SCOPE_ALL)
        kinds = [event["kind"] for event in sidebar.review_events]

        self.assertEqual(kinds.count("kill"), 3)
        self.assertNotIn("item_purchase", kinds)
        self.assertIn("(7)", sidebar.tabs.tabText(1))

    def test_event_rows_emit_the_game_second(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        received: list[float] = []
        sidebar.event_activated.connect(received.append)

        self.assertTrue(sidebar.event_rows)
        row = sidebar.event_rows[0]
        self.assertEqual(row.data["kind"], "kill")
        row.activated.emit(float(row.data["time"]))

        self.assertEqual(received, [600.0])
        self.assertTrue(
            sidebar.findChildren(QLabel, "postgameEventTitle")
        )

    def test_event_rows_show_the_owner_champion(self):
        sidebar = self.track(PostgameSidebar(sample_session()))
        badges = [
            label.text()
            for label in sidebar.findChildren(QLabel, "postgameEventPlayer")
        ]

        self.assertTrue(badges)
        self.assertTrue(any("Briar" in text for text in badges))


class LocalTelemetryTests(unittest.TestCase):
    """El desglose sale siempre de los datos locales, nunca de Riot."""

    def test_player_stats_come_from_local_snapshots(self):
        stats = player_final_stats(sample_session(), "local")

        self.assertEqual(
            (stats["kills"], stats["deaths"], stats["assists"]),
            (7, 2, 5),
        )
        self.assertEqual(stats["cs"], 150)
        self.assertEqual(stats["vision"], 24)
        self.assertEqual(stats["level"], 12)
        self.assertEqual(stats["gold"], 12500)
        self.assertAlmostEqual(stats["cspm"], 5.0, places=3)
        self.assertAlmostEqual(stats["gpm"], 12500 / 30.0, places=3)
        self.assertAlmostEqual(stats["kda"], 6.0, places=3)

    def test_radar_values_are_normalised(self):
        values = radar_values(player_final_stats(sample_session(), "local"))

        self.assertEqual(len(values), 5)

        for value in values:
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

        self.assertGreater(values[0], 0.0)

    def test_review_events_ignore_official_riot_events(self):
        events = build_review_events(sample_session(), "local")
        kinds = [event["kind"] for event in events]

        self.assertEqual(
            kinds,
            [
                "kill",
                "assist",
                "death",
                "dragon",
                "baron",
                "rift_herald",
                "item_purchase",
            ],
        )
        details = [event["detail"] for event in events]
        self.assertNotIn("Evento oficial de Riot", details)

        by_kind = {event["kind"]: event for event in events}
        # Valoración por bando: lo que hace mi equipo es bueno y lo que hace
        # el rival (o perder un objetivo propio) es malo.
        self.assertEqual(by_kind["kill"]["evaluation"], 1)
        self.assertEqual(by_kind["death"]["evaluation"], -1)
        self.assertEqual(by_kind["dragon"]["evaluation"], 1)
        self.assertEqual(by_kind["baron"]["evaluation"], -1)
        self.assertEqual(by_kind["rift_herald"]["evaluation"], 1)
        # Esa asistencia es del jugador local en una kill del rival: mala.
        self.assertEqual(by_kind["assist"]["evaluation"], -1)
        self.assertTrue(by_kind["kill"]["feedback"])

    def test_all_scope_keeps_every_kill_and_drops_purchases(self):
        events = build_review_events(sample_session())
        kinds = [event["kind"] for event in events]

        self.assertEqual(kinds.count("kill"), 3)
        self.assertNotIn("item_purchase", kinds)
        self.assertIn("death", kinds)
        self.assertIn(
            "Asesinato de Ahri", [event["detail"] for event in events]
        )

    def test_observed_counters_are_used_without_exact_events(self):
        session = local_session()
        session["events"] = [
            {
                "time": 300.0,
                "order": 1,
                "type": "kill",
                "player_key": "local",
                "team": "ORDER",
                "label": "Asesinato 1",
            },
            {
                "time": 900.0,
                "order": 2,
                "type": "death",
                "player_key": "local",
                "team": "ORDER",
                "label": "Muerte 1",
            },
        ]
        events = build_review_events(session, "local")

        self.assertEqual([event["kind"] for event in events], ["kill", "death"])

    def test_objectives_are_marked_for_both_two_teams(self):
        session = local_session()
        session["events"] = [
            {
                "time": 600.0,
                "order": 1,
                "type": "objective",
                "player_key": None,
                "team": "ORDER",
                "objective": "tower",
                "label": "Torre aliada",
            },
            {
                "time": 700.0,
                "order": 2,
                "type": "objective",
                "player_key": None,
                "team": "CHAOS",
                "objective": "inhibitor",
                "label": "Inhibidor aliado",
            },
        ]
        events = build_review_events(session, "local")

        self.assertEqual([event["kind"] for event in events], ["tower", "inhibitor"])
        self.assertEqual([event["evaluation"] for event in events], [1, -1])

    def test_tower_building_label_is_canonicalised(self):
        self.assertEqual(normalise_objective_kind("Tower Building"), "tower")
        self.assertEqual(normalise_objective_kind("Inhibitor Building"), "inhibitor")
        self.assertEqual(normalise_objective_kind("Baron Nashor"), "baron")
        self.assertEqual(normalise_objective_kind("Horde"), "horde")
        self.assertEqual(normalise_objective_kind("rift_herald"), "rift_herald")
        self.assertEqual(normalise_objective_kind("tower"), "tower")

    def test_tower_keeps_the_conquering_team(self):
        session = local_session()
        session["events"] = [
            {
                "time": 600.0,
                "order": 1,
                "type": "objective",
                "player_key": None,
                "killer_key": "enemy",
                "team": "CHAOS",
                "objective": "Tower Building",
                "label": "Bando no identificado consiguió Tower Building",
            },
        ]
        events = build_review_events(session, "local")
        tower = next(event for event in events if event["kind"] == "tower")

        self.assertEqual(tower["side"], "enemy")
        self.assertEqual(tower["evaluation"], -1)
        self.assertEqual(tower["label"], "Torre")
        self.assertIn("rival", tower["detail"])
        self.assertNotIn("no identificado", tower["detail"].casefold())

    def test_tower_falls_back_to_the_killer_team(self):
        session = local_session()
        session["events"] = [
            {
                "time": 600.0,
                "order": 1,
                "type": "objective",
                "player_key": None,
                "killer_key": "enemy",
                "team": "",
                "objective": "Tower Building",
                "label": "Bando no identificado consiguió Tower Building",
            },
        ]
        events = build_review_events(session, "local")
        tower = next(event for event in events if event["kind"] == "tower")

        self.assertEqual(tower["side"], "enemy")
        self.assertIn("rival", tower["detail"])

    def test_tower_uses_the_owner_team_when_nothing_else_is_known(self):
        session = local_session()
        session["events"] = [
            {
                "time": 600.0,
                "order": 1,
                "type": "objective",
                "player_key": None,
                "team": "",
                "objective": "Tower Building",
                "owner_team": "ORDER",
                "label": "Bando no identificado consiguió Tower Building",
            },
        ]
        events = build_review_events(session, "local")
        tower = next(event for event in events if event["kind"] == "tower")

        self.assertEqual(tower["side"], "enemy")
        self.assertIn("rival", tower["detail"])

    def test_unknown_team_stays_explicit_but_canonical(self):
        session = local_session()
        session["events"] = [
            {
                "time": 600.0,
                "order": 1,
                "type": "objective",
                "player_key": None,
                "team": "",
                "objective": "Tower Building",
                "label": "Bando no identificado consiguió Tower Building",
            },
        ]
        events = build_review_events(session, "local")
        tower = next(event for event in events if event["kind"] == "tower")

        self.assertEqual(tower["side"], "")
        self.assertEqual(tower["evaluation"], 0)
        self.assertIn("sin identificar", tower["detail"].casefold())

    def test_objective_side_reads_synced_events(self):
        session = local_session()

        self.assertEqual(
            objective_side(session, {"team": "ORDER"}), "ally"
        )
        self.assertEqual(
            objective_side(
                session, {"team": "", "objective_team": "CHAOS"}
            ),
            "enemy",
        )
        self.assertEqual(
            objective_side(
                session, {"team": "", "objective_team": "", "owner_team": "ORDER"}
            ),
            "enemy",
        )
        self.assertEqual(
            objective_side(
                session, {"team": "", "objective_team": "", "owner_team": "CHAOS"}
            ),
            "ally",
        )
        self.assertEqual(
            objective_side(session, {"team": "", "owner_team": ""}), ""
        )


class EventGlyphTests(unittest.TestCase):
    """Cada tipo de suceso tiene un icono identificativo propio."""

    def test_kinds_have_distinctive_glyphs(self):
        self.assertEqual(kind_glyph("kill"), "⚔️")
        self.assertEqual(kind_glyph("death"), "💀")
        self.assertEqual(kind_glyph("tower"), "🏰")
        self.assertEqual(kind_glyph("Tower Building"), "🏰")
        self.assertEqual(kind_glyph("Baron Nashor"), "👑")
        self.assertEqual(kind_glyph("dragon"), "🐉")
        self.assertEqual(kind_glyph("rift_herald"), "👁️")
        self.assertEqual(kind_glyph("inhibitor"), "💠")
        self.assertNotEqual(kind_glyph("kill"), kind_glyph("death"))

    def test_review_events_carry_their_glyph(self):
        events = build_review_events(sample_session(), "local")

        self.assertTrue(events)

        for event in events:
            self.assertTrue(event.get("glyph"))
            self.assertEqual(event["glyph"], kind_glyph(event["kind"]))


class SessionMatchingTests(unittest.TestCase):
    """Emparejamiento vídeo ↔ sesión (sidecars sin ``session_id``)."""

    def test_parse_iso_timestamp(self):
        stamp = parse_iso_timestamp("2026-09-20T10:00:05+00:00")

        self.assertIsNotNone(stamp)
        self.assertIsNotNone(stamp.tzinfo)
        self.assertIsNone(parse_iso_timestamp(""))
        self.assertIsNone(parse_iso_timestamp("no-es-fecha"))

    def test_session_matches_video_metadata_by_window(self):
        session = {
            "started_at": "2026-09-20T10:00:00+00:00",
            "ended_at": "2026-09-20T10:30:00+00:00",
        }

        # Arranque casi simultáneo (el vídeo arranca 5 s después).
        self.assertTrue(
            session_matches_video_metadata(
                session, {"started_at": "2026-09-20T10:00:05+00:00"}
            )
        )
        # Grabación iniciada a mitad de partida (game_time_offset > 0).
        self.assertTrue(
            session_matches_video_metadata(
                session, {"started_at": "2026-09-20T10:12:00+00:00"}
            )
        )
        # Fuera de la ventana (y del margen de tolerancia).
        self.assertFalse(
            session_matches_video_metadata(
                session, {"started_at": "2026-09-20T11:30:00+00:00"}
            )
        )
        self.assertFalse(session_matches_video_metadata(session, {}))
        self.assertFalse(
            session_matches_video_metadata(
                None, {"started_at": "2026-09-20T10:00:05+00:00"}
            )
        )


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        window = getattr(self, "window", None)

        if window is not None:
            window.close()
            window.deleteLater()
            self.window = None

        self.app.processEvents()

    def make_library(
        self,
        session_id: str = "sesion-local-1",
        offset: float = 30.0,
        duration: float = 600.0,
        name: str = "Solralol_partida.mp4",
        extra: dict | None = None,
    ):
        directory = Path(tempfile.mkdtemp()) / "recs"
        directory.mkdir(parents=True, exist_ok=True)
        library = RecordingLibrary(directory)
        video = directory / name
        video.write_bytes(b"x" * 4096)
        metadata = {
            "schema_version": 1,
            "file": video.name,
            "duration_seconds": duration,
            "game_time_offset": offset,
            "champion": "Briar",
            "game_mode": "CLASSIC",
            "quality": "1080",
            "video_bitrate": 8000,
            "complete": True,
            "session_id": session_id,
            "local_player_key": "local",
            "markers": [
                {
                    "time": 570.0,
                    "kind": "kill",
                    "label": "Asesinato",
                    "detail": "Asesinato 1",
                },
                {
                    "time": 870.0,
                    "kind": "dragon",
                    "label": "Dragón",
                    "detail": "Dragón",
                },
            ],
            "local_team": "ORDER",
            "players": {
                "local": {"team": "ORDER"},
            },
        }

        if extra:
            metadata.update(extra)

        library.write_metadata(video, metadata)
        return library, video

    def build_window(self, session=None, library=None, video=None, tracker=None):
        self.window = PostgameReplayWindow(
            session=session,
            video_path=video,
            library=library,
            tracker=tracker,
        )

        return self.window

    def test_window_is_independent_and_loads_session_markers(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )

        self.assertIsNone(window.parent())
        self.assertEqual(window.video_path, video)
        self.assertEqual(window.game_time_offset, 30.0)
        self.assertTrue(window.markers)
        self.assertEqual(
            len(window.marker_slider.markers), len(window.markers)
        )
        self.assertIn("marcador", window.marker_summary.text())
        self.assertEqual(len(scoreboard_cards(window.sidebar)), 4)
        self.assertIn("Briar", window.title_label.text())

    def test_markers_are_shifted_by_the_game_offset(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        times = [marker["time"] for marker in window.markers]

        # El asesinato local es en el segundo 600 de partida y la grabación
        # empieza 30 s después: en el vídeo queda en el 570.
        self.assertIn(570.0, times)

    def test_markers_follow_the_review_filter(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        sidebar = window.sidebar
        # Por defecto: alcance del jugador + objetivos → la barra refleja la
        # revisión, no solo asesinatos del local.
        self.assertEqual(len(window.markers), len(sidebar.review_markers(30.0)))
        self.assertNotIn("item_purchase", {m["kind"] for m in window.markers})
        first_count = len(window.markers)

        sidebar.set_scope(PostgameSidebar.SCOPE_ALL)
        self.app.processEvents()

        self.assertEqual(len(window.markers), len(sidebar.review_events))
        self.assertGreaterEqual(len(window.markers), first_count)
        self.assertIn("Dragón", window.marker_summary.text())
        self.assertIn("marcador", window.marker_summary.text())

        # Al volver a un jugador concreto solo quedan sus sucesos (+objetivos).
        sidebar.set_player("ally")
        sidebar.set_scope(PostgameSidebar.SCOPE_PLAYER)
        self.app.processEvents()

        self.assertTrue(
            all(
                marker["kind"]
                in {"kill", "death", "assist", "dragon", "baron", "herald",
                    "rift_herald", "horde", "tower", "inhibitor", "objective"}
                for marker in window.markers
            )
        )

    def test_markers_show_all_of_the_chosen_champion(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        sidebar = window.sidebar
        received: list[int] = []
        sidebar.events_changed.connect(lambda: received.append(1))

        sidebar.set_scope(PostgameSidebar.SCOPE_ALL)
        self.app.processEvents()

        self.assertTrue(received)
        kinds = {marker["kind"] for marker in window.markers}
        self.assertIn("kill", kinds)
        self.assertIn("dragon", kinds)
        self.assertIn("baron", kinds)
        # La torre rival también aparece como indicador.
        self.assertTrue(
            any(marker["kind"] == "tower" for marker in window.markers)
            or "tower" not in {
                event["kind"] for event in sidebar.review_events
            }
        )

    def test_recording_is_located_by_session_id(self):
        library, _other = self.make_library(
            session_id="otra-sesion", name="Solralol_otra.mp4"
        )
        second, _source = self.make_library(
            session_id="sesion-local-1", name="Solralol_buena.mp4"
        )
        target = library.directory / "Solralol_buena.mp4"
        target.write_bytes(b"x" * 4096)
        library.write_metadata(
            target, second.load_metadata(second.directory / "Solralol_buena.mp4")
        )

        window = self.build_window(session=sample_session(), library=library)

        self.assertIsNotNone(window.video_path)
        self.assertEqual(window.video_path.name, "Solralol_buena.mp4")

    def test_video_for_session_falls_back_to_the_newest_file(self):
        library, newest = self.make_library(session_id="")
        window = self.build_window(session=local_session(), library=library)

        self.assertEqual(window.video_path, newest)

    def timed_disk_session(self) -> dict:
        """Sesión de disco con ventana temporal explícita."""
        session = sample_session()
        session["started_at"] = "2026-09-20T10:00:00+00:00"
        session["ended_at"] = "2026-09-20T10:30:00+00:00"

        return session

    def test_session_is_matched_by_time_window_when_sidecar_has_no_id(self):
        library, video = self.make_library(
            session_id="",
            extra={
                "started_at": "2026-09-20T10:00:05+00:00",
                "ended_at": "2026-09-20T10:30:20+00:00",
            },
        )
        tracker = SimpleNamespace(
            load_saved_sessions=lambda: [self.timed_disk_session()]
        )
        window = self.build_window(
            library=library, video=video, tracker=tracker
        )

        self.assertEqual(window.session["session_id"], "sesion-local-1")
        self.assertEqual(len(scoreboard_cards(window.sidebar)), 4)
        self.assertTrue(window.sidebar.review_events)
        self.assertIn(
            "Briar",
            [event["player_name"] for event in window.sidebar.review_events],
        )

    def test_load_video_adopts_the_richer_disk_session(self):
        library, video = self.make_library(
            session_id="",
            extra={"started_at": "2026-09-20T10:00:05+00:00"},
        )
        tracker = SimpleNamespace(
            load_saved_sessions=lambda: [self.timed_disk_session()]
        )
        window = self.build_window(
            session={}, library=library, video=video, tracker=tracker
        )

        self.assertEqual(window.session["session_id"], "sesion-local-1")
        self.assertEqual(len(window.session.get("players") or {}), 4)
        self.assertTrue(window.sidebar.review_events)
        self.assertEqual(len(scoreboard_cards(window.sidebar)), 4)

    def test_video_for_session_falls_back_to_time_window(self):
        library, _old = self.make_library(
            session_id="vieja", name="Solralol_vieja.mp4"
        )
        second, _new = self.make_library(
            session_id="",
            name="Solralol_nueva.mp4",
            extra={
                "started_at": "2026-09-20T10:00:05+00:00",
                "ended_at": "2026-09-20T10:30:20+00:00",
            },
        )
        target = library.directory / "Solralol_nueva.mp4"
        target.write_bytes(b"x" * 4096)
        library.write_metadata(
            target,
            second.load_metadata(second.directory / "Solralol_nueva.mp4"),
        )

        window = self.build_window(
            session=self.timed_disk_session(), library=library
        )

        self.assertIsNotNone(window.video_path)
        self.assertEqual(window.video_path.name, "Solralol_nueva.mp4")

    def test_reload_breakdown_uses_local_data_from_disk(self):
        library, video = self.make_library()
        tracker = SimpleNamespace(load_saved_sessions=lambda: [sample_session()])
        stale = local_session()
        window = self.build_window(
            session=stale, library=library, video=video, tracker=tracker
        )

        self.assertEqual(window.session["session_id"], "sesion-local-1")
        self.assertTrue(window.sidebar.review_events)
        self.assertEqual(
            player_final_stats(window.session, "local")["kills"], 7
        )
        window.rebuild_button.click()

        self.assertIn("telemetría local", window.status_label.text())
        self.assertEqual(
            [event["kind"] for event in window.sidebar.review_events],
            [
                "kill",
                "assist",
                "death",
                "dragon",
                "baron",
                "rift_herald",
                "item_purchase",
            ],
        )

    def test_reload_breakdown_keeps_the_local_session_without_tracker(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        window.reload_breakdown()

        self.assertIn("telemetría local", window.status_label.text())
        self.assertEqual(
            player_final_stats(window.session, "local")["kills"], 7
        )

    def test_transport_seeks_translating_the_game_time(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        seen: list[int] = []
        window.seek_to_ms = seen.append

        window.jump_to_game_time(600.0)

        self.assertEqual(seen, [570000])

    def test_duration_updates_slider_range_and_markers(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        window._on_duration(600000)

        self.assertEqual(window.marker_slider.maximum(), 600000)
        self.assertEqual(
            len(window.marker_slider.markers), len(window.markers)
        )

    def test_sidebar_event_click_jumps_the_video(self):
        library, video = self.make_library()
        window = self.build_window(
            session=sample_session(), library=library, video=video
        )
        seen: list[int] = []
        window.seek_to_ms = seen.append

        window.sidebar.event_activated.emit(900.0)

        self.assertEqual(seen, [870000])

    def test_transport_is_safe_without_a_loaded_video(self):
        # Carpeta de grabaciones vacía: sin vídeo que cargar.
        directory = Path(tempfile.mkdtemp()) / "vacia"
        directory.mkdir(parents=True, exist_ok=True)
        window = self.build_window(
            session=sample_session(), library=RecordingLibrary(directory)
        )

        self.assertIsNone(window.video_path)
        window.toggle_play()

        self.assertIn("No hay ninguna grabación", window.status_label.text())
        window.seek_relative(10)
        window.exit_fullscreen()
        window.load_video(Path(tempfile.gettempdir()) / "no-existe.mp4")

        self.assertIn("No se encontró el vídeo", window.status_label.text())

    def test_setting_a_new_session_refreshes_the_sidebar(self):
        library, video = self.make_library()
        window = self.build_window(library=library, video=video)
        window.set_session(sample_session())

        self.assertEqual(len(scoreboard_cards(window.sidebar)), 4)
        self.assertTrue(window.markers)


class MainWindowReplayTests(unittest.TestCase):
    """La ventana de repaso también se abre desde la aplicación."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.saved: dict = {}

        def fake_settings_factory():
            saved = self.saved

            class FakeSettingsService:
                def __init__(self, *args, **kwargs) -> None:
                    pass

                def load(self) -> dict:
                    return {}

                def save(self, settings: dict) -> None:
                    saved.clear()
                    saved.update(settings)

            return FakeSettingsService

        self.settings_patcher = patch(
            "app.ui.main_window.SettingsService",
            new=fake_settings_factory(),
        )
        self.settings_patcher.start()

        from app.ui.main_window import MainWindow

        self.MainWindow = MainWindow
        self.window = MainWindow(version="test", item_catalog={"items": {}})
        self.app.processEvents()
        self.window.poll_timer.stop()
        self.window.live_match_tracker.sessions_path = (
            Path(tempfile.mkdtemp()) / "live_match_sessions.json"
        )
        directory = Path(tempfile.mkdtemp()) / "recs"
        directory.mkdir(parents=True, exist_ok=True)
        self.window.recording_library.set_directory(directory)

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.settings_patcher.stop()

    def write_recording(self, session_id: str = "sesion-local-1") -> Path:
        library = self.window.recording_library
        video = library.directory / "Solralol_2026-09-19_Briar.mp4"
        video.write_bytes(b"x" * 2048)
        library.write_metadata(
            video,
            {
                "schema_version": 1,
                "file": video.name,
                "duration_seconds": 900.0,
                "game_time_offset": 0.0,
                "champion": "Briar",
                "game_mode": "CLASSIC",
                "quality": "1080",
                "video_bitrate": 8000,
                "complete": True,
                "session_id": session_id,
                "local_player_key": "local",
                "markers": [],
            },
        )

        return video

    def test_saved_game_row_offers_the_replay_window(self):
        host = SimpleNamespace(
            postgame_sync_in_progress=False,
            format_match_duration=self.MainWindow.format_match_duration,
            format_saved_session_date=lambda value: "19/09/2026 12:00",
            request_saved_session_sync=Mock(),
            request_resync_session=Mock(),
            open_saved_game_analysis=Mock(),
            delete_saved_game_session=Mock(),
            open_replay_window=Mock(),
        )
        session = sample_session()
        row = self.MainWindow.create_saved_game_row(host, session)
        button = next(
            button
            for button in row.findChildren(QPushButton)
            if button.text() == "Repaso con vídeo"
        )
        button.click()

        host.open_replay_window.assert_called_once_with(session=session)
        row.close()
        row.deleteLater()
        self.app.processEvents()

    def test_open_replay_window_matches_the_video_and_is_reused(self):
        video = self.write_recording()
        session = sample_session()
        self.window.open_replay_window(session=session)
        replay = self.window.replay_window

        self.assertIsNotNone(replay)
        self.assertEqual(replay.video_path, video)
        self.assertEqual(len(scoreboard_cards(replay.sidebar)), 4)
        self.assertEqual(
            player_final_stats(replay.session, "local")["kills"], 7
        )

        self.window.open_replay_window(session=session)

        self.assertIs(self.window.replay_window, replay)

        replay.close()
        self.app.processEvents()

        self.assertIsNone(self.window.replay_window)

    def test_recordings_page_window_button_opens_the_replay(self):
        video = self.write_recording()
        page = self.window.recordings_page
        page.refresh()
        self.app.processEvents()

        button = next(
            button
            for button in page.findChildren(QPushButton)
            if button.text() == "🗔 Ventana"
        )
        button.click()
        self.app.processEvents()

        self.assertIsNotNone(self.window.replay_window)
        self.assertEqual(self.window.replay_window.video_path, video)

    def test_find_recording_for_session_returns_empty_without_match(self):
        self.write_recording(session_id="otra-sesion")

        self.assertEqual(
            self.window.find_recording_for_session(sample_session()), ""
        )


if __name__ == "__main__":
    unittest.main()
