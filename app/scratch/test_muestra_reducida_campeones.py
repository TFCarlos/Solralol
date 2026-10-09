"""Regresión de muestras reducidas U.GG, persistencia local y presentación Qt."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.services.calidad_muestra import EstadoMuestra, clasificar_muestra
from app.services.champion_scraper_service import ChampionScraperService
from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones


@pytest.fixture
def entorno_muestra(tmp_path: Path) -> tuple[ChampionScraperService, Path]:
    """Prepara catálogos reales copiados y almacenamiento aislado para Aatrox."""
    datos = tmp_path / "data"
    (datos / "champion_data").mkdir(parents=True)
    for nombre in (
        "champion_catalog.json",
        "items.json",
        "legendary_items_strict.json",
    ):
        shutil.copy(Path("data") / nombre, datos / nombre)
    servicio = ChampionScraperService(
        champions_path=datos / "champion_data", request_delay=0, rank="emerald_plus"
    )
    return servicio, datos


def test_clasificacion_muestra_reducida_y_datos_parciales() -> None:
    """Distingue muestra reducida, parcial y ausencia de muestra."""
    assert clasificar_muestra(7, True) == EstadoMuestra.LOW_SAMPLE
    assert clasificar_muestra(450, True) == EstadoMuestra.NORMAL_SAMPLE
    assert clasificar_muestra(0, True) == EstadoMuestra.PARTIAL_DATA
    assert clasificar_muestra(None, False) == EstadoMuestra.NO_DATA


def test_pagina_de_runas_de_baja_muestra_se_conserva(
    entorno_muestra: tuple[ChampionScraperService, Path],
) -> None:
    """Mantiene runas y conteo propio de una configuración con 127 partidas."""
    servicio, _ = entorno_muestra
    perks = [8010, 9101, 9104, 9105, 8451, 8453]
    bloque_runas = [127, 69, 8000, 8400, perks]
    data = {
        "12": {
            "17": {
                "5": [
                    [
                        bloque_runas,
                        [127, 69, [4, 11]],
                        [127, 69, [1055, 2003]],
                        [127, 69, [6632, 3047, 3053]],
                    ]
                ]
            }
        }
    }

    pagina = servicio._archetype_page(data, "mid", "Letalidad")

    assert pagina is not None
    assert pagina["games"] == 127
    assert pagina["sample_status"] == EstadoMuestra.LOW_SAMPLE.value
    assert pagina["keystone"] == "Conqueror"


def test_actualizacion_se_acepta_con_estadisticas_sin_build(
    entorno_muestra: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acepta estadísticas reales aunque falten secciones opcionales."""
    servicio, _ = entorno_muestra
    overview = {"12": {"17": {"5": [[None, None, None, None, None, None, [3, 7]]]}}}
    for nombre, valor in (
        ("_overview", overview),
        ("_parse_overview", {}),
        ("_parse_opgg", {}),
        ("_parse_lolalytics", {}),
        ("_ugg_archetype_pages", []),
        ("_lolalytics_page", None),
        ("_get", None),
        ("_scrape_damage_breakdown", None),
        ("_scrape_winrate_vs_game_length", None),
    ):
        monkeypatch.setattr(servicio, nombre, Mock(return_value=valor))
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
        "power_curve_and_scaling": {},
    }

    assert servicio.update_champion(perfil)
    assert perfil["lane_stats"]["lanes"]["mid"]["games"] == 7
    assert perfil["lane_stats"]["lanes"]["mid"]["sample_status"] == "LOW_SAMPLE"


def test_aatrox_mid_emerald_plus_se_normaliza_y_persiste(
    entorno_muestra: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guarda como baja una variante real aunque falten secciones opcionales."""
    servicio, datos = entorno_muestra
    overview = {"12": {"17": {"5": [[None, None, None, None, None, None, [3, 7]]]}}}
    servicio._versiones_fuente["U.GG overview"] = "16.20"
    monkeypatch.setattr(servicio, "_overview", Mock(return_value=overview))
    monkeypatch.setattr(
        servicio,
        "fetch_variant",
        Mock(
            side_effect=lambda perfil, linea: {
                "role": linea,
                "rank": servicio.rank,
                "updated": False,
                "lane_stats": {"games": 7, "win_rate": 3 / 7},
                "runes": [
                    {
                        "name": "Página U.GG",
                        "keystone": "Conqueror",
                        "primary_tree": "Precision",
                        "secondary_tree": "Resolve",
                        "slots": [],
                        "secondary_slots": [],
                        "games": 12,
                        "win_rate": 5 / 12,
                        "sample_status": "LOW_SAMPLE",
                    }
                ],
                "summoner_spells": ["Flash", "Smite"],
                "skill_order": ["Q", "W", "E"],
                "starter_items": ["Doran's Blade", "Health Potion"],
                "most_played_build": ["Youmuu's Ghostblade", "Mercury's Treads"],
                "matchups": {
                    "counters": [{"champion": "Yasuo", "games": 4}],
                    "good_against": [{"champion": "Orianna", "games": 3}],
                },
            }
        ),
    )
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
        "power_curve_and_scaling": {},
    }

    matriz = servicio.fetch_matrix(perfil)
    variante = matriz["emerald_plus"]["mid"]
    assert set(matriz["emerald_plus"]) == {"__lane_stats__", "mid"}
    assert matriz["diamond"] == {}
    assert variante["role"] == "mid"
    assert variante["rank"] == "emerald_plus"
    assert variante["sample_size"] == 7
    assert variante["source_patch"] == "16.20"
    assert variante["retrieved_at"]
    assert variante["sample_status"] == EstadoMuestra.LOW_SAMPLE.value
    assert variante["data_status"] == EstadoMuestra.LOW_SAMPLE.value
    assert variante["section_sample_sizes"]["champion_lane"] == 7

    documento = PreparadorDatosCampeon(datos).preparar(perfil, matriz)
    repositorio = RepositorioCampeones(datos / "champion_data")
    repositorio.guardar("Aatrox", documento)
    consulta = repositorio.consultar("Aatrox", "mid", "emerald_plus")

    assert consulta.estado == EstadoDatos.DISPONIBLE
    assert consulta.datos["sample_status"] == EstadoMuestra.LOW_SAMPLE.value
    assert consulta.datos["sample_size"] == 7
    assert consulta.datos["rank"] == "emerald_plus"
    assert consulta.datos["role"] == "mid"
    assert consulta.datos["runes"][0]["games"] == 12
    assert consulta.datos["summoner_spells"] == ["Flash", "Smite"]
    assert consulta.datos["skill_order"] == ["Q", "W", "E"]
    assert consulta.datos["starter_items"] == ["Doran's Blade", "Health Potion"]
    assert consulta.datos["matchups"]["counters"][0]["champion"] == "Yasuo"


def test_muestra_baja_reemplaza_entrada_vacia_y_se_lee_de_cache(
    entorno_muestra: tuple[ChampionScraperService, Path],
) -> None:
    """Permite que una respuesta útil reemplace un registro completo sin variantes."""
    _, datos = entorno_muestra
    repositorio = RepositorioCampeones(datos / "champion_data")
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut"},
        "power_curve_and_scaling": {},
    }
    vacio = RepositorioCampeones.documento(perfil, {"emerald_plus": {}}, "complete")
    repositorio.guardar("Aatrox", vacio)
    valido = RepositorioCampeones.documento(
        perfil,
        {
            "emerald_plus": {
                "__lane_stats__": {
                    "rank": "emerald_plus",
                    "lanes": {"mid": {"games": 7, "win_rate": 3 / 7}},
                },
                "mid": {
                    "role": "mid",
                    "rank": "emerald_plus",
                    "updated": True,
                    "lane_stats": {"games": 7, "win_rate": 3 / 7},
                    "sample_size": 7,
                    "sample_status": "LOW_SAMPLE",
                },
            }
        },
    )
    repositorio.guardar("Aatrox", valido)

    lectura = repositorio.consultar("Aatrox", "mid", "emerald_plus")
    assert lectura.estado == EstadoDatos.DISPONIBLE
    assert lectura.datos["sample_size"] == 7
    assert lectura.lineas["mid"]["games"] == 7


def test_resumen_heredado_de_linea_sirve_como_variante_parcial(
    tmp_path: Path,
) -> None:
    """Recupera métricas antiguas del mismo rango sin esperar a una reimportación."""
    repositorio = RepositorioCampeones(tmp_path)
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut"},
        "power_curve_and_scaling": {},
        "lane_stats": {
            "rank": "emerald_plus",
            "lanes": {"mid": {"games": 7, "win_rate": 0.4286}},
        },
    }
    documento = RepositorioCampeones.documento(perfil, {"emerald_plus": {}})
    repositorio.guardar("Aatrox", documento)

    consulta = repositorio.consultar("Aatrox", "mid", "emerald_plus")

    assert consulta.estado == EstadoDatos.DISPONIBLE
    assert consulta.datos["sample_status"] == "LOW_SAMPLE"
    assert consulta.datos["sample_size"] == 7
    assert consulta.datos["lane_stats"]["lanes"]["mid"]["win_rate"] == 0.4286
    assert (
        repositorio.consultar("Aatrox", "mid", "diamond").estado
        == EstadoDatos.SIN_DATOS_FUENTE
    )
