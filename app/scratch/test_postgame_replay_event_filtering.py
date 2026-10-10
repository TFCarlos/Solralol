import os
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from pytest import MonkeyPatch

from app.services.live_match_tracker import LiveMatchTracker
from app.services.recording_service import build_markers
from app.ui.postgame_replay_window import (
    PostgameReplayWindow,
    filter_replay_markers,
    game_time_to_video_position_ms,
    marker_filter_group,
    marker_filter_summary,
)
from app.ui.postgame_sidebar import PostgameSidebar, build_review_events


def _session_with_shared_kill() -> dict[str, Any]:
    """Crea una sesión con roles de baja y asistentes identificados por clave."""
    players = {
        key: {"champion_name": key.title(), "team": team}
        for key, team in (
            ("local", "ORDER"),
            ("victim", "CHAOS"),
            ("assist-one", "ORDER"),
            ("assist-two", "ORDER"),
            ("other-killer", "CHAOS"),
            ("other-victim", "ORDER"),
        )
    }
    common = {
        "event_id": "native:100",
        "time": 10.0,
        "killer_key": "local",
        "victim_key": "victim",
        "assister_keys": ["assist-one", "assist-two"],
        "assist_data_complete": True,
        "team": "ORDER",
    }
    events = [
        {**common, "type": "kill_exact", "player_key": "local", "order": 1},
        {**common, "type": "death_exact", "player_key": "victim", "order": 2},
        {
            **common,
            "type": "assist_exact",
            "player_key": "assist-one",
            "order": 3,
        },
        {
            **common,
            "type": "assist_exact",
            "player_key": "assist-two",
            "order": 4,
        },
        {
            "event_id": "native:101",
            "type": "kill_exact",
            "time": 25.0,
            "player_key": "other-killer",
            "killer_key": "other-killer",
            "victim_key": "other-victim",
            "assister_keys": [],
            "assist_data_complete": True,
            "team": "CHAOS",
            "order": 5,
        },
        {
            "event_id": "native:102",
            "type": "kill_exact",
            "time": 40.0,
            "player_key": "local",
            "killer_key": "local",
            "team": "ORDER",
            "order": 6,
        },
    ]
    return {
        "local_player_key": "local",
        "local_team": "ORDER",
        "players": players,
        "events": events,
    }


def test_shared_kill_is_classified_for_the_selected_player_only() -> None:
    """Separa verdugo, víctima y asistentes sin atribuir kills ajenas."""
    session = _session_with_shared_kill()

    assert [
        event["category"]
        for event in build_review_events(session, "local", group_teamfights_rows=False)
    ] == [
        "kill",
        "kill",
    ]
    victim_events = build_review_events(session, "victim", group_teamfights_rows=False)
    assert [event["category"] for event in victim_events] == ["death"]
    assert victim_events[0]["source_event_id"] == "native:100"

    for assister in ("assist-one", "assist-two"):
        assist_events = build_review_events(
            session, assister, group_teamfights_rows=False
        )
        assert [event["category"] for event in assist_events] == ["assist"]

    assert build_review_events(session, "uninvolved", group_teamfights_rows=False) == []
    assert session["events"][0]["type"] == "kill_exact"


def test_recording_markers_include_explicit_perspective_categories() -> None:
    """Mantiene separados kill, death y assist al serializar marcadores."""
    session = _session_with_shared_kill()

    for player_key in ("local", "victim", "assist-one"):
        session["local_player_key"] = player_key
        markers = build_markers(session)
        expected = {
            "local": "kill",
            "victim": "death",
            "assist-one": "assist",
        }[player_key]
        assert markers
        assert {marker["category"] for marker in markers} == {expected}
        assert all(marker["player_key"] == player_key for marker in markers)
        assert all(marker["source_event_id"] for marker in markers)


def test_riot_champion_kill_parser_flows_to_each_verified_role() -> None:
    """Verifica ChampionKill nativo hasta las categorías de cada participante."""
    players = {
        key: {
            "participant_id": participant_id,
            "riot_id": riot_id,
            "champion_name": champion,
            "team": team,
        }
        for key, participant_id, riot_id, champion, team in (
            ("killer", 1, "Killer#EUW", "Aatrox", "ORDER"),
            ("victim", 2, "Victim#EUW", "Ahri", "CHAOS"),
            ("assist-one", 3, "AssistOne#EUW", "Jinx", "ORDER"),
            ("assist-two", 4, "AssistTwo#EUW", "Lulu", "ORDER"),
            ("uninvolved", 5, "Other#EUW", "Garen", "CHAOS"),
        )
    }
    session = {
        "local_team": "ORDER",
        "players": players,
        "events": [],
        "player_timelines": {},
        "seen_event_ids": [],
    }
    tracker = LiveMatchTracker({}, persist=False)
    tracker.session = session
    tracker._record_exact_events(
        {
            "game_events": [
                {
                    "EventID": 501,
                    "EventName": "ChampionKill",
                    "EventTime": 52.0,
                    "KillerParticipantId": 1,
                    "VictimParticipantId": 2,
                    "Assisters": [3, 4],
                }
            ]
        }
    )

    expected = {
        "killer": "kill",
        "victim": "death",
        "assist-one": "assist",
        "assist-two": "assist",
    }
    for player_key, category in expected.items():
        events = build_review_events(session, player_key, group_teamfights_rows=False)
        assert [event["category"] for event in events] == [category]

    assert build_review_events(session, "uninvolved", group_teamfights_rows=False) == []


def test_all_players_and_player_without_identity_are_separate_modes() -> None:
    """Solo «Todos» expone roles globales; una identidad ausente no los inventa."""
    session = _session_with_shared_kill()
    all_events = build_review_events(session, None, group_teamfights_rows=False)
    categories = [event["category"] for event in all_events]

    assert categories.count("kill") == 3
    assert categories.count("death") == 1
    assert categories.count("assist") == 2
    assert build_review_events(session, "", group_teamfights_rows=False) == []


def test_legacy_persisted_combat_events_keep_explicit_categories() -> None:
    """Lee marcadores antiguos tipados sin derivar roles de datos ausentes."""
    session = {
        "players": {"local": {"champion_name": "Briar", "team": "ORDER"}},
        "events": [
            {"type": "kill", "player_key": "local", "time": 1},
            {"type": "death", "player_key": "local", "time": 3},
            {"type": "assist", "player_key": "local", "time": 5},
            {"type": "assist", "time": 7},
        ],
    }

    events = build_review_events(session, "local", group_teamfights_rows=False)
    assert [event["category"] for event in events] == ["kill", "death", "assist"]


def test_legacy_sidecar_markers_restore_categories_without_fabrication() -> None:
    """Restaura categorías explícitas antiguas y omite marcadores sin tipo."""
    source_events = PostgameReplayWindow._events_from_metadata_markers(
        {
            "local_player_key": "local",
            "markers": [
                {"kind": "kill", "time": 2.0, "detail": "Asesinato"},
                {"kind": "death", "time": 4.0, "detail": "Muerte"},
                {"kind": "assist", "time": 6.0, "detail": "Asistencia"},
                {"time": 8.0, "detail": "Sin categoría"},
                {"kind": "ChampionKill", "time": 9.0, "detail": "Evento ambiguo"},
            ],
        }
    )
    session = {
        "players": {"local": {"champion_name": "Briar", "team": "ORDER"}},
        "events": source_events,
    }

    events = build_review_events(session, "local", group_teamfights_rows=False)
    assert [event["category"] for event in events] == ["kill", "death", "assist"]


def test_teamfight_rows_do_not_replace_timeline_marker_categories() -> None:
    """Conserva las categorías individuales aunque la revisión agrupe la pelea."""
    session = _session_with_shared_kill()
    session["events"] = [
        {
            "event_id": f"cluster:{index}",
            "type": "kill_exact",
            "time": 10.0 + index * 4,
            "player_key": "local",
            "killer_key": "local",
            "victim_key": f"victim-{index}",
            "assister_keys": [],
            "assist_data_complete": True,
            "team": "ORDER",
        }
        for index in range(3)
    ]

    timeline_events = build_review_events(session, "local", group_teamfights_rows=False)
    review_rows = build_review_events(session, "local")

    assert [event["category"] for event in timeline_events] == [
        "kill",
        "kill",
        "kill",
    ]
    assert [event["kind"] for event in review_rows] == ["teamfight"]


def test_sidebar_uses_individual_categories_for_timeline_markers(
    monkeypatch: MonkeyPatch,
) -> None:
    """La barra conserva categorías individuales en una pelea agrupada.

    Returns:
        None.
    """
    application = QApplication.instance() or QApplication([])
    assert application is not None
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    session = _session_with_shared_kill()
    session["events"] = [
        {
            "event_id": f"sidebar:{index}",
            "type": "kill_exact",
            "time": 10.0 + index * 4,
            "player_key": "local",
            "killer_key": "local",
            "victim_key": f"victim-{index}",
            "assister_keys": [],
            "assist_data_complete": True,
            "team": "ORDER",
        }
        for index in range(3)
    ]

    sidebar = PostgameSidebar(session)
    markers = sidebar.review_markers()

    assert [marker["category"] for marker in markers] == ["kill", "kill", "kill"]
    assert [event["kind"] for event in sidebar.review_events] == ["teamfight"]
    sidebar.close()


def test_combat_filters_are_independent_and_counts_match_visible_markers() -> None:
    """Comprueba filtros individuales, combinados, vacíos y sus contadores."""
    markers = [
        {"category": "kill", "kind": "kill", "time": 10},
        {"category": "death", "kind": "death", "time": 20},
        {"category": "assist", "kind": "assist", "time": 30},
        {"category": "dragon", "kind": "dragon", "time": 40},
    ]

    for category in ("kill", "death", "assist"):
        visible = filter_replay_markers(markers, {category})
        assert [marker_filter_group(marker) for marker in visible] == [category]
        assert marker_filter_summary(markers, {category}) == (
            "1 de 4 marcadores · 1 categoría activa"
        )

    two = filter_replay_markers(markers, {"kill", "death"})
    assert [marker["category"] for marker in two] == ["kill", "death"]
    assert marker_filter_summary(markers, {"kill", "death"}) == (
        "2 de 4 marcadores · 2 categorías activas"
    )
    assert filter_replay_markers(markers, set()) == []
    assert marker_filter_summary(markers, set()) == (
        "0 de 4 marcadores · 0 categorías activas"
    )
    assert (
        filter_replay_markers(markers, {"kill", "death", "assist", "dragon"}) == markers
    )


def test_category_is_not_inferred_from_raw_riot_event_type() -> None:
    """No convierte un ChampionKill ambiguo en kill, death o asistencia."""
    assert marker_filter_group({"kind": "ChampionKill"}) == "unclassified"
    assert filter_replay_markers([{"kind": "kill_exact"}], {"kill", "other"}) == []


def test_marker_seeking_preserves_match_to_video_offset() -> None:
    """Convierte el timestamp del marcador a milisegundos del vídeo."""
    assert game_time_to_video_position_ms(650.0, 610.0) == 40_000
    assert game_time_to_video_position_ms(600.0, 610.0) == 0
