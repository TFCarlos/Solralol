"""Verifica la normalización y la resolución local de hechizos LIVE."""

from __future__ import annotations

from pathlib import Path

import pytest

import data_dragon


@pytest.mark.parametrize(
    ("spell", "canonical"),
    [
        ("Flash", "flash"),
        ("Ignite", "ignite"),
        ("Smite", "smite"),
        ("Unleashed Smite", "smite"),
        ("Primal Smite", "smite"),
        ("Teleport", "teleport"),
        ("Unleashed Teleport", "teleport"),
        ("Ghost", "ghost"),
        ("Heal", "heal"),
        ("Barrier", "barrier"),
        ("Exhaust", "exhaust"),
        ("Cleanse", "cleanse"),
        ("SummonerFlash", "flash"),
        ("SummonerDot", "ignite"),
        (4, "flash"),
        (11, "smite"),
        (12, "teleport"),
        (
            {
                "displayName": "Flash",
                "rawDisplayName": "GeneratedTip_SummonerSpell_SummonerFlash_DisplayName",
                "id": 4,
            },
            "flash",
        ),
    ],
)
def test_normaliza_nombres_ids_y_variantes(spell: object, canonical: str) -> None:
    """Normaliza las formas documentadas y alias habituales de LIVE/DD."""
    assert data_dragon.normalizar_hechizo_invocador(spell) == canonical


def test_resuelve_los_nueve_hechizos_comunes_desde_assets_locales() -> None:
    """Comprueba rutas locales para todos los hechizos pedidos por LIVE."""
    for spell in (
        "Flash",
        "Ignite",
        "Smite",
        "Teleport",
        "Ghost",
        "Heal",
        "Barrier",
        "Exhaust",
        "Cleanse",
    ):
        resultado = data_dragon.resolver_icono_hechizo_invocador(
            {"displayName": spell}, "test", download=False
        )
        assert resultado.estado == "resuelto", spell
        assert resultado.ruta is not None and resultado.ruta.is_file(), spell


@pytest.mark.parametrize(
    ("spell", "state"),
    [(None, "sin_datos"), ("UnknownSpell", "sin_resolver")],
)
def test_distingue_datos_ausentes_de_identificador_desconocido(
    spell: object, state: str
) -> None:
    """Mantiene diagnóstico separado para datos ausentes e IDs no reconocidos."""
    resultado = data_dragon.resolver_icono_hechizo_invocador(
        spell, "test", download=False
    )
    assert resultado.estado == state


def test_informa_asset_ausente_sin_iniciar_descarga(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Clasifica el asset ausente sin hacer solicitudes de red desde la UI."""
    monkeypatch.setattr(data_dragon, "SPELL_ICON_DIR", tmp_path)
    resultado = data_dragon.resolver_icono_hechizo_invocador(
        "Flash", "test", download=False
    )
    assert resultado.estado == "asset_ausente"
    assert resultado.identificador_normalizado == "flash"
    assert resultado.ruta is None
