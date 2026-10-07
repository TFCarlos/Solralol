"""Pruebas para las tarjetas y el modelo de partidas guardadas."""

from __future__ import annotations

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from app.ui.main_window import TarjetaPartidaGuardada, MainWindow

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


@pytest.fixture
def ventana(aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    """Construye MainWindow sin inicializar servicios pesados."""
    monkeypatch.setattr(MainWindow, "__init__", lambda self, *a, **kw: None)
    w = MainWindow()
    w.data_dragon_assets = Mock()
    w.postgame_sync_in_progress = False
    w.find_recording_for_session = Mock(return_value=None)
    w.format_match_duration = MainWindow.format_match_duration
    w.format_saved_session_date = lambda val: MainWindow.format_saved_session_date(w, val)
    return w


def test_extraer_oponente_linea_exito() -> None:
    """Verifica que se obtenga el campeón rival de la misma posición."""
    session = {
        "local_player_key": "player_1",
        "players": {
            "player_1": {
                "player_key": "player_1",
                "side": "ally",
                "role": "TOP",
                "champion_name": "Aatrox",
            },
            "player_2": {
                "player_key": "player_2",
                "side": "enemy",
                "role": "TOP",
                "champion_name": "Darius",
            },
        },
    }
    oponente = TarjetaPartidaGuardada.extraer_oponente_linea(session)
    assert oponente == "Darius"


def test_extraer_oponente_linea_desde_lane_matchups() -> None:
    """Verifica que se use lane_matchups cuando esté presente."""
    session = {
        "local_player_key": "player_1",
        "players": {
            "player_1": {
                "player_key": "player_1",
                "side": "ally",
                "role": "MIDDLE",
                "champion_name": "Ahri",
            },
            "player_enemy_mid": {
                "player_key": "player_enemy_mid",
                "side": "enemy",
                "role": "MIDDLE",
                "champion_name": "Syndra",
            },
        },
        "lane_matchups": {
            "MIDDLE": {
                "ally_key": "player_1",
                "enemy_key": "player_enemy_mid",
            }
        },
    }
    oponente = TarjetaPartidaGuardada.extraer_oponente_linea(session)
    assert oponente == "Syndra"


def test_extraer_oponente_linea_no_disponible() -> None:
    """Verifica el fallback '—' cuando no se puede determinar el oponente."""
    session = {
        "local_player_key": "player_1",
        "players": {
            "player_1": {
                "player_key": "player_1",
                "side": "ally",
                "role": "UNKNOWN",
                "champion_name": "Aatrox",
            },
        },
    }
    oponente = TarjetaPartidaGuardada.extraer_oponente_linea(session)
    assert oponente == "—"


def test_crear_fila_partida_guardada(ventana: MainWindow) -> None:
    """Verifica que create_saved_game_row instancie correctamente el widget."""
    session = {
        "session_id": "test_session_123",
        "champion_name": "Garen",
        "game_mode": "CLASSIC",
        "started_at": "2026-10-06T12:00:00",
        "duration": 1500,
        "local_player_key": "p1",
        "players": {
            "p1": {
                "player_key": "p1",
                "side": "ally",
                "role": "TOP",
                "champion_name": "Garen",
                "win": True,
            },
            "p2": {
                "player_key": "p2",
                "side": "enemy",
                "role": "TOP",
                "champion_name": "Renekton",
            },
        },
    }

    row = ventana.create_saved_game_row(session)
    assert isinstance(row, TarjetaPartidaGuardada)
    assert row.result_state == "win"
    enemy_icon = row.findChild(QLabel, "savedGameEnemyIcon")
    assert enemy_icon is not None
    assert enemy_icon.toolTip() == "Renekton"
    result_label = row.findChild(QLabel, "savedGameResult")
    assert result_label is not None
    assert result_label.text() == "VICTORIA"
