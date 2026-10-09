from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.services.postgame_lcu_sync import (
    RETRASOS_REINTENTO_LCU,
    actualizar_estado_sync_final,
    conservar_enriquecimiento_final,
    historial_contiene_enlace,
    incorporar_resultado_lcu,
    marcar_sincronizacion_lcu_completa,
    marcar_sincronizacion_lcu_pendiente,
    reconciliar_puntuaciones_home,
    siguiente_retraso_lcu,
)
from app.services.resumen_rendimiento_historial import resumen_puntuacion_local
from app.ui.main_window import MainWindow


def test_postgame_lcu_sync_state_survives_retry_and_completion() -> None:
    """Mantiene pendiente una sesión y permite recuperarla con una asociación exacta."""
    sesion = {"session_id": "sesion-briar"}

    marcar_sincronizacion_lcu_pendiente(sesion)
    sesion["lcu_postgame_sync"]["attempts"] = 3
    marcar_sincronizacion_lcu_pendiente(sesion)

    assert sesion["lcu_postgame_sync"] == {
        "state": "pending",
        "attempts": 3,
        "session_id": "sesion-briar",
    }
    assert not historial_contiene_enlace({"matches": []}, "sesion-briar")
    assert historial_contiene_enlace(
        {
            "matches": [
                {
                    "saved_match_link": {
                        "matched": True,
                        "saved_match_id": "sesion-briar",
                    }
                }
            ]
        },
        "sesion-briar",
    )

    marcar_sincronizacion_lcu_completa(sesion)

    assert sesion["lcu_postgame_sync"]["state"] == "synced"
    assert sesion["lcu_postgame_sync"]["attempts"] == 3


def test_postgame_lcu_retry_policy_is_bounded_then_recovers_slowly() -> None:
    """Aplica esperas acotadas y un intervalo de recuperación sin sondeo continuo."""
    assert [siguiente_retraso_lcu(index) for index in range(5)] == list(
        RETRASOS_REINTENTO_LCU
    )
    assert siguiente_retraso_lcu(5) == 300
    assert siguiente_retraso_lcu(50) == 300


def test_briar_naafiri_lcu_reconciliation_calculates_authoritative_home_score() -> None:
    """Calcula BattleScore para Briar con la telemetría de la fixture guardada."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "briar_regression_match.json").read_text(
            encoding="utf-8"
        )
    )
    metadata = fixture["metadata"]
    roster = fixture["all_players"]
    puuid_por_jugador = {
        str(jugador["player_key"]): f"fixture-puuid-{indice}"
        for indice, jugador in enumerate(roster)
    }
    jugadores = {
        str(jugador["player_key"]): {
            "player_key": str(jugador["player_key"]),
            "puuid": puuid_por_jugador[str(jugador["player_key"])],
            "team": str(jugador["team"]),
            "role": str(jugador.get("role") or "UNKNOWN"),
            "champion_name": str(jugador["champion"]),
            "riot_id": f"{jugador['player_key']}#FIXTURE",
            "final": {},
        }
        for jugador in roster
    }
    puuid_local = puuid_por_jugador[fixture["local_player_key"]]
    sesion = {
        "session_id": str(metadata["session_id"]),
        "local_player_key": str(fixture["local_player_key"]),
        "local_puuid": puuid_local,
        "champion_name": str(metadata["champion_name"]),
        "duration": int(metadata["duration_seconds"]),
        "postgame": True,
        "players": jugadores,
        "final_scoreboard": {},
        "final_sync": {"status": "live_only"},
    }
    participantes = []
    for indice, jugador in enumerate(roster, start=1):
        estadisticas = {
            "kills": jugador["kills"],
            "deaths": jugador["deaths"],
            "assists": jugador["assists"],
            "cs": jugador["cs"],
            "gold_earned": jugador.get("gold"),
            "vision_score": jugador.get("vision_score"),
            "total_damage_dealt_to_champions": jugador.get("damage_to_champions"),
            "damage_dealt_to_turrets": None,
            "turret_kills": None,
            "inhibitor_kills": None,
            "objectives_stolen": None,
            "objectives_stolen_assists": None,
            "damage_dealt_to_objectives": jugador.get("damage_to_objectives"),
            "damage_taken": jugador.get("damage_taken"),
            "damage_self_mitigated": jugador.get("damage_self_mitigated"),
            "total_time_crowd_control_dealt": None,
            "wards_placed": None,
            "wards_killed": None,
            "total_heal": None,
            "total_heals_on_teammates": None,
            "total_damage_shielded_on_teammates": None,
        }
        participantes.append(
            {
                "participant_id": indice,
                "puuid": puuid_por_jugador[str(jugador["player_key"])],
                "team_id": 100 if jugador["team"] == "ORDER" else 200,
                "champion_name": jugador["champion"],
                "game_name": jugador["player_key"],
                "tag_line": "FIXTURE",
                "win": jugador["team"] == metadata["winning_team"],
                "kills": jugador["kills"],
                "deaths": jugador["deaths"],
                "assists": jugador["assists"],
                "cs": jugador["cs"],
                "items": jugador["items"],
                "final_stats": estadisticas,
            }
        )
    partida = {
        "game_id": "987654321",
        "started_at": "2026-10-08T18:00:00+00:00",
        "duration_seconds": int(metadata["duration_seconds"]),
        "saved_match_link": {
            "matched": True,
            "saved_match_id": str(metadata["session_id"]),
            "confidence": 1.0,
        },
        "participants": participantes,
        "stable_match_id": "987654321",
        "champion_name": "Briar",
        "result": "defeat",
    }

    home, changed = reconciliar_puntuaciones_home([partida], [sesion], puuid_local)

    score = resumen_puntuacion_local(sesion)
    assert changed
    assert score is not None
    assert score["participant_id"] == fixture["local_player_key"]
    assert score["points"] == home[0]["performance_summary"]["points"]
    assert score["global_rank"] == home[0]["performance_summary"]["global_rank"]
    assert score["award"] == home[0]["performance_summary"]["award"]
    assert home[0]["saved_match_link"]["saved_match_id"] == sesion["session_id"]


def test_lcu_result_rejects_unlinked_or_incomplete_match() -> None:
    """Evita convertir un partido parecido o incompleto en un resultado final."""
    sesion = {
        "session_id": "saved-1",
        "players": {},
        "final_sync": {"status": "live_only"},
    }
    assert not incorporar_resultado_lcu(sesion, {"participants": []})
    assert sesion["final_sync"]["status"] == "live_only"


def test_stale_sync_cannot_replace_a_final_score_or_lcu_completion() -> None:
    """Conserva el resultado final reciente frente a una copia vieja de postpartida."""
    actual = {
        "final_sync": {"status": "synced", "source": "lcu_match_history"},
        "final_scoreboard": {"briar": {"kills": 12}},
        "performance_scoring": {"state": "POSTGAME_FINAL", "players": ["final"]},
        "lcu_postgame_sync": {"state": "synced", "attempts": 2},
    }
    entrante = {
        "final_sync": {"status": "pending"},
        "final_scoreboard": {},
        "performance_scoring": {"state": "POSTGAME_PENDING"},
        "lcu_postgame_sync": {"state": "pending", "attempts": 0},
    }

    resultado = conservar_enriquecimiento_final(actual, entrante)

    assert resultado["final_sync"]["source"] == "lcu_match_history"
    assert resultado["final_scoreboard"] == {"briar": {"kills": 12}}
    assert resultado["performance_scoring"]["state"] == "POSTGAME_FINAL"
    assert resultado["lcu_postgame_sync"]["state"] == "synced"


def test_failed_riot_attempt_does_not_hide_an_existing_lcu_final_score() -> None:
    """Una respuesta Riot fallida conserva el resultado final obtenido por LCU."""
    sesion = {
        "final_sync": {
            "status": "synced",
            "source": "lcu_match_history",
            "match_id": "LCU_1234",
        }
    }

    aplicado = actualizar_estado_sync_final(sesion, "failed", "Riot API no disponible")

    assert not aplicado
    assert sesion["final_sync"]["status"] == "synced"
    assert sesion["final_sync"]["source"] == "lcu_match_history"


def test_game_finish_schedules_one_persisted_lcu_home_sync(
    monkeypatch,
) -> None:
    """El fin de partida crea una tarea durable y deduplica señales repetidas."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "__init__", lambda self: None)
    llamadas: list[tuple[int, object]] = []
    monkeypatch.setattr(
        QTimer,
        "singleShot",
        lambda demora, callback: llamadas.append((demora, callback)),
    )
    sesion = {"session_id": "session-finished"}
    tracker = Mock()
    tracker.load_saved_sessions.return_value = [sesion]
    ventana = MainWindow()
    ventana.live_match_tracker = tracker
    ventana.pending_postgame_session_id = ""
    ventana._postgame_lcu_scheduled = set()
    ventana.riot_api_key = ""
    ventana.riot_game_name = ""
    ventana.riot_tag_line = ""

    ventana.schedule_postgame_sync(sesion)
    ventana.schedule_postgame_sync(sesion)

    assert sesion["lcu_postgame_sync"]["state"] == "pending"
    assert tracker._save_sessions.call_count == 2
    assert len(llamadas) == 1
    assert llamadas[0][0] == 2_000


def test_live_session_finish_is_idempotent_after_active_to_postgame_transition(
    monkeypatch,
) -> None:
    """Finaliza telemetría y programa sincronización una sola vez por partida."""
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(MainWindow, "__init__", lambda self: None)
    ventana = MainWindow()
    ventana.live_session_finished = False
    ventana.live_snapshots_lost = 0
    ventana.recording_service = SimpleNamespace(is_recording=False)
    ventana.live_match_tracker = SimpleNamespace(
        is_tracking=True,
        finish=Mock(return_value={"session_id": "session-finished"}),
    )
    ventana.stop_match_recording = Mock()
    ventana.schedule_postgame_sync = Mock()

    ventana.finish_live_session("game_end")
    ventana.finish_live_session("game_end")

    ventana.stop_match_recording.assert_called_once()
    ventana.schedule_postgame_sync.assert_called_once_with(
        {"session_id": "session-finished"}
    )
