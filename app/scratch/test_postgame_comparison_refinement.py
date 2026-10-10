import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
from pytest import MonkeyPatch

from app.services.recording_service import RecordingLibrary
from app.ui.postgame_replay_window import PostgameReplayWindow
from app.ui.postgame_sidebar import (
    EventRow,
    PlayerCard,
    PostgameSidebar,
    _resumen_resultado_equipo,
    _rol_comparativo,
    build_review_events,
    team_kills,
)


def _session_comparativa() -> dict[str, Any]:
    """Prepara dos equipos con roles, resultado y estadísticas verificables.

    Returns:
        Sesión local compacta para probar el marcador del repaso.
    """
    ally_roles = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
    enemy_roles = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
    players: dict[str, dict[str, Any]] = {}
    snapshot_players: dict[str, dict[str, Any]] = {}
    lane_matchups: dict[str, dict[str, str]] = {}

    for index, (ally_role, enemy_role) in enumerate(zip(ally_roles, enemy_roles)):
        ally_key = f"ally-{index}"
        enemy_key = f"enemy-{index}"
        players[ally_key] = {
            "champion_name": ("Garen", "Lee Sin", "Ahri", "Ashe", "Janna")[index],
            "team": "ORDER",
            "role": ally_role,
            "win": False,
        }
        players[enemy_key] = {
            "champion_name": ("Darius", "Viego", "Yasuo", "Caitlyn", "Lulu")[index],
            "team": "CHAOS",
            "role": enemy_role,
            "win": True,
        }
        snapshot_players[ally_key] = {
            "kills": index + 1,
            "deaths": 2,
            "assists": 3,
            "cs": 180 + index,
            "estimated_gold": 10_000 + index * 100,
            "level": 16,
            "stats": {"vision_score": 20 + index},
        }
        snapshot_players[enemy_key] = {
            "kills": index + 3,
            "deaths": 1,
            "assists": 4,
            "cs": 200 + index,
            "estimated_gold": 12_000 + index * 100,
            "level": 17,
            "stats": {"vision_score": 25 + index},
        }
        lane_matchups[str(index)] = {
            "ally_key": ally_key,
            "enemy_key": enemy_key,
        }

    events = [
        {
            "event_id": "review-kill-ally",
            "type": "kill_exact",
            "time": 20.0,
            "player_key": "ally-3",
            "killer_key": "ally-3",
            "victim_key": "enemy-3",
            "assister_keys": [],
            "assist_data_complete": True,
            "team": "ORDER",
        },
        {
            "event_id": "review-kill-enemy",
            "type": "kill_exact",
            "time": 40.0,
            "player_key": "enemy-3",
            "killer_key": "enemy-3",
            "victim_key": "ally-3",
            "assister_keys": [],
            "assist_data_complete": True,
            "team": "CHAOS",
        },
        {
            "event_id": "review-kill-unrelated",
            "type": "kill_exact",
            "time": 60.0,
            "player_key": "enemy-0",
            "killer_key": "enemy-0",
            "victim_key": "ally-0",
            "assister_keys": [],
            "assist_data_complete": True,
            "team": "CHAOS",
        },
    ]
    return {
        "local_player_key": "ally-3",
        "local_team": "ORDER",
        "duration": 1800,
        "players": players,
        "lane_matchups": lane_matchups,
        "events": events,
        "snapshots": [{"players": snapshot_players}],
    }


def test_role_aliases_align_comparison_rows() -> None:
    """Normaliza las etiquetas de rol equivalentes entre fuentes."""
    assert _rol_comparativo("ADC") == "BOTTOM"
    assert _rol_comparativo("support") == "UTILITY"
    assert _rol_comparativo("MID") == "MIDDLE"
    assert _rol_comparativo("sin dato") == ""


def test_resultado_de_equipo_es_neutral_si_falta_o_se_contradice() -> None:
    """No inventa resultados cuando el marcador local no es concluyente."""
    session = _session_comparativa()
    assert _resumen_resultado_equipo(session, ["ally-0"]) == ("DERROTA", "loss")
    assert _resumen_resultado_equipo(session, ["enemy-0"]) == (
        "VICTORIA",
        "win",
    )
    assert _resumen_resultado_equipo(session, ["missing"]) == (
        "SIN RESULTADO",
        "unknown",
    )
    session["players"]["ally-0"]["win"] = True
    assert _resumen_resultado_equipo(session, ["ally-0", "ally-1"]) == (
        "SIN RESULTADO",
        "unknown",
    )


def test_clic_en_cualquiera_de_los_lados_selecciona_la_pareja_de_rol(
    monkeypatch: MonkeyPatch,
) -> None:
    """El campeón rival selecciona el mismo duelo por rol y resalta ambos."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    sidebar = PostgameSidebar(_session_comparativa())

    sidebar._on_card_clicked("ally-1")
    assert sidebar.player_key == "ally-1"
    assert sidebar.rival_key == "enemy-1"

    sidebar._on_card_clicked("enemy-3")

    assert sidebar.player_key == "enemy-3"
    assert sidebar.rival_key == "ally-3"
    cards = sidebar.findChildren(PlayerCard)
    assert {
        card._player_key for card in cards if card.property("seleccionado") is True
    } >= {"ally-3", "enemy-3"}
    assert "Ashe" in sidebar.stats_label.text()
    assert "Caitlyn" in sidebar.stats_label.text()
    assert "CS/min" in sidebar.stats_label.text()
    sidebar.close()
    app.processEvents()


def test_no_empareja_campeones_de_roles_distintos(
    monkeypatch: MonkeyPatch,
) -> None:
    """Deja la pareja vacía si no hay rol ni matchup compatible."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    session = _session_comparativa()
    session["lane_matchups"] = {}
    sidebar = PostgameSidebar(session)

    assert sidebar._partner_for("ally-3", "ADC") == "enemy-3"
    session["players"]["enemy-3"]["role"] = "SUPPORT"
    assert sidebar._partner_for("ally-3", "ADC") == ""
    sidebar.close()
    app.processEvents()


def test_resumen_muestra_estado_parcial_si_no_hay_pareja(
    monkeypatch: MonkeyPatch,
) -> None:
    """No oculta la falta de un segundo jugador comparable."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    session = _session_comparativa()
    session["players"].pop("enemy-3")
    session["lane_matchups"].pop("3")
    sidebar = PostgameSidebar(session)

    sidebar.set_player("ally-3")

    assert "Sin pareja de rol confirmada" in sidebar.stats_label.text()
    sidebar.close()
    app.processEvents()


def test_resumen_incluye_las_metricas_de_ambos_campeones(
    monkeypatch: MonkeyPatch,
) -> None:
    """Actualiza el detalle inferior con los dos integrantes del duelo."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    sidebar = PostgameSidebar(_session_comparativa())

    sidebar.set_player("enemy-3")
    summary = sidebar.stats_label.text()

    assert summary.count("KDA") == 2
    assert "Ashe" in summary
    assert "Caitlyn" in summary
    assert "Participación" in summary
    sidebar.close()
    app.processEvents()


def test_encabezados_muestran_resultado_y_bajas_de_cada_equipo(
    monkeypatch: MonkeyPatch,
) -> None:
    """Presenta los resultados textuales en las cabeceras del equipo."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    session = _session_comparativa()
    sidebar = PostgameSidebar(session)

    assert sidebar.ally_result.text() == "DERROTA"
    assert sidebar.enemy_result.text() == "VICTORIA"
    assert "bajas" in sidebar.ally_title.text()
    assert "bajas" in sidebar.enemy_title.text()
    sidebar.close()
    app.processEvents()


def test_contexto_todos_muestra_todos_los_eventos_en_la_barra(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """El selector de contexto amplía la cronología a ambos equipos."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    review = PostgameReplayWindow(
        session=_session_comparativa(), library=RecordingLibrary(tmp_path)
    )

    assert review.selector_contexto_cronologia.currentData() == "player"
    player_markers = review._build_markers()
    review.selector_contexto_cronologia.setCurrentIndex(1)
    all_markers = review._build_markers()

    assert review.sidebar.scope == PostgameSidebar.SCOPE_ALL
    assert len(all_markers) > len(player_markers)
    assert len(all_markers) == len(review.sidebar.timeline_events)
    assert review.selector_contexto_cronologia.currentText() == "Todos"
    assert review.marker_summary.text() != "Sin marcadores"
    review.selector_contexto_cronologia.setCurrentIndex(0)
    assert review.sidebar.scope == PostgameSidebar.SCOPE_PLAYER
    assert len(review._build_markers()) == len(player_markers)
    review.close()
    app.processEvents()


def test_no_se_recuperan_eventos_globales_si_el_contexto_de_jugador_esta_vacio() -> (
    None
):
    """No reemplaza una perspectiva vacía por los marcadores globales."""
    review = type("RepasoPrueba", (), {})()
    review.sidebar = type(
        "Desglose", (), {"review_markers": lambda _self, _offset: []}
    )()
    review.session = _session_comparativa()
    review.metadata = {"markers": [{"time": 5, "category": "kill"}]}
    review.game_time_offset = 0.0

    assert PostgameReplayWindow._build_markers(review) == []


def test_bajas_resumen_sigue_usando_el_total_de_equipo() -> None:
    """Comprueba el total observado que acompaña los resultados de equipo."""
    session = _session_comparativa()
    assert team_kills(session, "ally") == 15
    assert team_kills(session, "enemy") == 25


def test_teamfight_conserva_secuencia_verificada_de_killer_a_victima() -> None:
    """Agrupa la pelea sin perder el vínculo original entre campeones."""
    session = _session_comparativa()
    session["events"] = [
        {
            "type": "kill_exact",
            "time": 100 + index * 2,
            "killer_key": killer,
            "victim_key": victim,
            "team": team,
        }
        for index, (killer, victim, team) in enumerate(
            (
                ("ally-2", "enemy-2", "ORDER"),
                ("enemy-1", "ally-1", "CHAOS"),
                ("ally-3", "enemy-3", "ORDER"),
            )
        )
    ]

    events = build_review_events(session)
    teamfight = next(event for event in events if event["kind"] == "teamfight")

    assert teamfight["side"] == "ally"
    assert teamfight["kill_sequence"] == [
        {
            "killer_key": "ally-2",
            "killer_name": "Ahri",
            "victim_key": "enemy-2",
            "victim_name": "Yasuo",
        },
        {
            "killer_key": "enemy-1",
            "killer_name": "Viego",
            "victim_key": "ally-1",
            "victim_name": "Lee Sin",
        },
        {
            "killer_key": "ally-3",
            "killer_name": "Ashe",
            "victim_key": "enemy-3",
            "victim_name": "Caitlyn",
        },
    ]

    app = QApplication.instance() or QApplication([])
    row = EventRow(teamfight, session, "15.16.1")
    labels = [label.text() for label in row.findChildren(QLabel)]

    assert "Tu equipo ganó la pelea" in labels
    assert "Ahri" in labels and "Yasuo" in labels
    assert "Viego" in labels and "Lee Sin" in labels
    assert row.property("tono") == "positivo"
    row.close()
    app.processEvents()
