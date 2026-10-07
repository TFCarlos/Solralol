"""Pruebas aisladas para la composición y curva del panel de recomendaciones."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QToolButton

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.ui.draft_tool_dialog import DraftPowerCurveWidget
from app.ui.local_analysis_dialog import DamageBarWidget
from app.ui.recommendation_panel import RecommendationPanel


@pytest.fixture
def panel() -> RecommendationPanel:
    """Crea el panel con una aplicación Qt fuera de pantalla."""
    aplicacion = QApplication.instance() or QApplication([])
    assert aplicacion is not None
    return RecommendationPanel()


def test_analizador_admite_perfiles_reutilizados_sin_releer_repositorio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los perfiles ya preparados evitan recorrer otra vez el repositorio local."""
    carga = Mock(side_effect=AssertionError("No debe releer el repositorio"))
    monkeypatch.setattr(DraftAnalyzerService, "_load_data", carga)
    perfiles = [
        {
            "character": "Ashe",
            "damage_breakdown": {
                "physical_damage_percent": 80,
                "magic_damage_percent": 15,
                "true_damage_percent": 5,
            },
        }
    ]

    analizador = DraftAnalyzerService(tmp_path / "champion_data", perfiles=perfiles)

    assert analizador.get_champion_profile("Ashe") is perfiles[0]
    assert analizador.calculate_team_damage_breakdown(["Ashe"]) == {
        "physical": 80.0,
        "magic": 15.0,
        "true": 5.0,
    }
    carga.assert_not_called()


def test_composicion_usa_equipos_observados_y_analizador_compartido(
    panel: RecommendationPanel,
) -> None:
    """Las barras y el gráfico reciben perfiles de aliados y rivales observados."""
    panel._last_session = {
        "local_player_key": "local",
        "players": {
            "local": {"team": "blue"},
            "ally": {"team": "blue", "champion_name": "Braum"},
            "enemy": {"team": "red", "champion_name": "Darius"},
        },
    }
    informe = {
        "champion": "Ashe",
        "threats": [{"champion": "Darius"}],
    }
    assert panel._team_champions(informe) == {
        "ally": ["Ashe", "Braum"],
        "enemy": ["Darius"],
    }

    analizador = Mock()
    analizador.calculate_team_damage_breakdown.side_effect = [
        {"physical": 60.0, "magic": 30.0, "true": 10.0},
        {"physical": 25.0, "magic": 70.0, "true": 5.0},
    ]
    analizador.calculate_team_power_curve.side_effect = [
        {"0-15": 51.0},
        {"0-15": 49.0},
    ]
    analizador.analyze_power_spike_phase.return_value = "Early Game"
    panel.draft_analyzer = analizador

    composicion = panel._damage_composition(informe)
    barras = composicion.findChildren(DamageBarWidget)
    assert len(barras) == 2
    assert (barras[0].ad_pct, barras[0].ap_pct, barras[0].true_pct) == (
        60.0,
        30.0,
        10.0,
    )
    assert (barras[1].ad_pct, barras[1].ap_pct, barras[1].true_pct) == (25.0, 70.0, 5.0)

    curva = panel._power_curve(informe)
    grafico = curva.findChild(DraftPowerCurveWidget)
    assert grafico is not None
    assert grafico.power_spike_label == "Early Game"
    assert analizador.calculate_team_power_curve.call_count == 2


def test_panel_muestra_cinco_rivales_y_plan_bajo_recomendaciones(
    panel: RecommendationPanel,
) -> None:
    """Mantiene disponibles los cinco rivales y expande el plan en la columna izquierda."""
    amenazas = [
        {
            "key": f"rival-{indice}",
            "champion": f"Campeón {indice}",
            "level": 18,
            "kda": "4/3/7",
            "strength": None,
            "strength_label": "",
            "inventory": {
                "value": 12000,
                "partial": False,
                "known": True,
                "badges": [],
            },
            "items": [],
            "signals": [],
            "stale": False,
        }
        for indice in range(5)
    ]
    rival_panel = panel._context({"threats": amenazas, "physical_share": 0.5})
    tarjetas = [
        widget
        for widget in rival_panel.findChildren(QFrame)
        if widget.objectName().startswith("enemyCard_")
    ]
    assert len(tarjetas) == 5

    seccion = panel._recommendations(
        {
            "recommendations": [],
            "purchases": [],
            "actions": [("Ventana", "Espera al control aliado.")],
        }
    )
    plan = seccion.findChild(QFrame, "actionPlan")
    assert plan is not None
    assert plan.parentWidget() is seccion
    assert plan.findChild(QToolButton, "actionPlanToggle").isChecked()


def test_actualiza_curva_si_cambia_el_equipo_con_el_mismo_informe(
    panel: RecommendationPanel,
) -> None:
    """Una composición nueva refresca el gráfico aunque las recomendaciones coincidan."""
    informe = {
        "champion": "Ashe",
        "role": "Bot",
        "level": 15,
        "time": 600,
        "gold": 500,
        "phase": "Medio juego",
        "ended": False,
        "purchase": {"status": "none", "text": "Sin compra sugerida."},
        "recommendations": [],
        "purchases": [],
        "owned": [],
        "threats": [],
        "physical_share": 0.5,
        "actions": [],
        "warnings": [],
    }
    panel.engine = Mock()
    panel.engine.analyze.return_value = informe
    panel.draft_analyzer = Mock()
    panel.draft_analyzer.calculate_team_damage_breakdown.return_value = {
        "physical": 50.0,
        "magic": 45.0,
        "true": 5.0,
    }
    panel.draft_analyzer.calculate_team_power_curve.return_value = {"0-15": 50.0}
    panel.draft_analyzer.analyze_power_spike_phase.return_value = "Equilibrado"

    panel.update_recommendations(
        {"local_player_key": "local", "players": {"local": {"team": "blue"}}}
    )
    panel.update_recommendations(
        {
            "local_player_key": "local",
            "players": {
                "local": {"team": "blue"},
                "aliado": {"team": "blue", "champion_name": "Braum"},
            },
        }
    )

    assert panel.engine.analyze.call_count == 2
    assert panel._last_composition["ally"] == ["Ashe", "Braum"]
