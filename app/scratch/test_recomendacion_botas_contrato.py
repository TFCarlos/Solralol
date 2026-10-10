"""Regresiones del contrato tipado al puntuar botas locales."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.synergy_recommendation_service import ItemRecommendation


@pytest.mark.parametrize(
    ("estilo", "etiquetas", "esperada"),
    [
        ("Adaptable", [], 17.5),
        ("Bruiser", ["CooldownReduction"], 20.5),
        ("Marksman", ["AttackSpeed"], 20.5),
        ("Mage", ["MagicPenetration"], 19.5),
        ("Tank", ["Armor"], 19.5),
    ],
)
def test_puntuacion_bota_extrae_score_del_objeto_tipado_y_aplica_bonus(
    estilo: str, etiquetas: list[str], esperada: float
) -> None:
    """Conserva score y bonus por estilo recibidos en ItemRecommendation."""
    perfil = {"basic_info": {"play_style": estilo}}
    objeto = {"tags": etiquetas}
    motor = Mock()
    motor.score_item.return_value = ItemRecommendation(
        "3111", "Botas", 17.5, (), ()
    )

    puntuacion = PreparadorDatosCampeon._puntuar_botas_locales(
        perfil, "3111", objeto, motor
    )

    assert puntuacion == esperada
    motor.score_item.assert_called_once_with(perfil, estilo, "3111", objeto, [])


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), "17.5", True])
def test_puntuacion_bota_invalida_se_excluye(score: object) -> None:
    """No acepta una recomendación cuyo score no sea un número finito real."""
    motor = Mock()
    motor.score_item.return_value = ItemRecommendation(
        "3111", "Botas", score, (), ()
    )

    puntuacion = PreparadorDatosCampeon._puntuar_botas_locales(
        {"basic_info": {"play_style": "Adaptable"}},
        "3111",
        {"tags": []},
        motor,
    )

    assert puntuacion is None


def test_tipo_distinto_de_item_recommendation_se_excluye() -> None:
    """Rechaza tipos inesperados sin convertirlos ni puntuarlos a ciegas."""
    motor = Mock()
    motor.score_item.return_value = 17.5

    puntuacion = PreparadorDatosCampeon._puntuar_botas_locales(
        {"basic_info": {"play_style": "Adaptable"}},
        "3111",
        {"tags": []},
        motor,
    )

    assert puntuacion is None
