"""Pruebas de extracci\u00f3n por alcance para el payload p\u00fablico de U.GG."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.champion_scraper_service import ChampionScraperService
from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones


@pytest.fixture
def fuente_aatrox() -> dict:
    """Carga el extracto realista del endpoint U.GG filtrado a Aatrox Mid Emerald+."""
    return json.loads(
        Path("app/scratch/fixtures/ugg_aatrox_mid_emerald_plus_16_20.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def servicio_aatrox(tmp_path: Path) -> tuple[ChampionScraperService, Path]:
    """Copia catálogos locales y prepara el servicio con un repositorio aislado."""
    datos = tmp_path / "data"
    (datos / "champion_data").mkdir(parents=True)
    for nombre in (
        "champion_catalog.json",
        "items.json",
        "legendary_items_strict.json",
    ):
        shutil.copy(Path("data") / nombre, datos / nombre)
    return ChampionScraperService(datos / "champion_data", 0, "emerald_plus"), datos


def test_payload_ugg_separa_muestras_y_recupera_secciones(
    fuente_aatrox: dict, servicio_aatrox: tuple[ChampionScraperService, Path]
) -> None:
    """Normaliza conteos generales y subsecciones desde sus bloques originales."""
    servicio, _ = servicio_aatrox
    payload = fuente_aatrox["payload"]
    assert servicio._position_entry(payload, "mid") == payload["12"]["17"]["5"]
    estadisticas = servicio._lane_stats(payload)["mid"]
    datos = servicio._parse_overview(payload, "mid")
    assert estadisticas["games"] == datos["overall_matches"] == 450
    assert datos["overall_win_rate"] == pytest.approx(0.4467)
    assert datos["rune_page_matches"] == 127
    assert datos["summoner_spell_matches"] == 375
    assert datos["skill_priority_matches"] == 359
    assert datos["starting_item_matches"] == 213
    assert datos["starting_items_source_status"] == "AVAILABLE"
    assert datos["starter_item_entries"] == [
        {"item_id": 1055, "name": "Espada de Doran", "quantity": 1},
        {"item_id": 2003, "name": "Poción de vida", "quantity": 1},
    ]
    assert datos["starting_items_provenance"]["rank"] == "emerald_plus"
    assert datos["starting_items_provenance"]["lane"] == "mid"
    assert datos["core_build_matches"] == 11
    assert datos["summoner_spell_ids"] == [4, 14]
    assert datos["skill_order"]["priority"] == "QEW"
    assert len(datos["skill_order"]["order"]) == 18
    assert datos["starter_item_ids"] == [1055, 2003]
    assert [item["item_id"] for item in datos["core_build"]] == [6697, 3008, 6699]
    assert set(datos["item_options"]) == {"4", "5", "6"}
    assert datos["item_options"]["4"][0]["games"] == 24
    assert datos["section_sample_sizes"]["item_options"]["6"] == [2, 2]
    assert datos["shard_ids"] == [5008, 5001, 5001]
    pagina = datos["runes"][0]
    assert pagina["keystone_id"] == 8010
    assert pagina["keystone"] == "Conqueror"
    assert pagina["primary_tree"] == "Precision"
    assert pagina["secondary_tree"] == "Resolve"
    assert pagina["shard_ids"] == [5008, 5001, 5001]
    pagina_arquetipo = servicio._archetype_page(payload, "mid", "Recomendada")
    assert pagina_arquetipo is not None
    assert len(pagina_arquetipo["build"]) == 3
    assert set(pagina_arquetipo["item_options"]) == {"4", "5", "6"}
    assert fuente_aatrox["selection"]["rank"] == "emerald_plus"
    assert fuente_aatrox["selection"]["lane"] == "mid"
    assert fuente_aatrox["source_patch"] == "16.20"


def test_matchups_ugg_dom_guarda_muestras_por_enfrentamiento(
    servicio_aatrox: tuple[ChampionScraperService, Path],
) -> None:
    """Extrae contadores y partidas desde la sección pública real de U.GG."""
    servicio, _ = servicio_aatrox
    html = Path(
        "app/scratch/fixtures/ugg_aatrox_mid_emerald_plus_matchups.html"
    ).read_text(encoding="utf-8")
    datos = servicio._parse_matchups(
        BeautifulSoup(html, "html.parser"), "mid", "Aatrox"
    )
    sion = next(fila for fila in datos["counters"] if fila["champion"] == "Sion")
    lux = next(fila for fila in datos["counters"] if fila["champion"] == "Lux")
    assert len(datos["counters"]) == 10
    assert sion["lane_games"] == 4 and sion["win_rate"] == 0
    assert lux["lane_games"] == 6 and lux["win_rate"] == pytest.approx(0.167)
    assert "Aatrox" in sion["tip"]
    normalizados = servicio._clean_matchups(datos, "mid")
    sion_normalizado = next(
        fila for fila in normalizados["counters"] if fila["champion"] == "Sion"
    )
    assert sion_normalizado["win_rate"] == 0


def test_pagina_arquetipo_conserva_ids_de_fragmentos(
    fuente_aatrox: dict,
    servicio_aatrox: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Añade los IDs estadísticos al arquetipo que coincide con la página fuente."""
    servicio, _ = servicio_aatrox
    payload = fuente_aatrox["payload"]
    monkeypatch.setattr(
        servicio,
        "_archetype_overview",
        Mock(side_effect=lambda _champion_id, kind: payload if kind == "" else None),
    )
    monkeypatch.setattr(servicio, "_overview", Mock(return_value=payload))
    paginas = servicio._ugg_archetype_pages(servicio.champion_ids["aatrox"], "mid")
    assert paginas[0]["games"] == 127
    assert paginas[0]["shard_ids"] == [5008, 5001, 5001]


def test_flujo_real_de_normalizacion_y_cache_conserva_el_payload(
    fuente_aatrox: dict,
    servicio_aatrox: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persiste y recarga el resultado normalizado con sus conteos independientes."""
    servicio, datos = servicio_aatrox
    payload = fuente_aatrox["payload"]
    servicio._versiones_fuente["U.GG overview"] = fuente_aatrox["source_patch"]
    monkeypatch.setattr(servicio, "_patches", Mock(return_value=["26.20", "16.20"]))
    monkeypatch.setattr(servicio, "_overview", Mock(return_value=payload))
    for nombre, valor in (
        ("_parse_opgg", {}),
        ("_parse_lolalytics", {}),
        ("_ugg_archetype_pages", []),
        ("_builds", None),
        ("_lolalytics", None),
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
    matriz = servicio.fetch_matrix(perfil)
    assert matriz["emerald_plus"]["__lane_stats__"]["lanes"]["mid"]["games"] == 450
    variante = matriz["emerald_plus"]["mid"]
    assert variante["summoner_spell_ids"] == [4, 14]
    assert variante["starter_item_ids"] == [1055, 2003]
    assert variante["most_played_build"] and len(variante["skill_order"]["order"]) == 18
    assert variante["sample_size"] == 450
    documento = PreparadorDatosCampeon(datos).preparar(perfil, matriz)
    repositorio = RepositorioCampeones(datos / "champion_data")
    repositorio.guardar("Aatrox", documento)
    lectura = repositorio.consultar("Aatrox", "mid", "emerald_plus")
    assert lectura.estado == EstadoDatos.DISPONIBLE
    assert lectura.datos["sample_size"] == lectura.datos["overall_matches"] == 450
    assert lectura.datos["patch_label"] == "26.20"
    assert lectura.datos["section_sample_sizes"]["core_build"] == 11
    assert lectura.datos["section_sample_sizes"]["summoner_spells"] == 375
    assert len(lectura.datos["item_options"]["6"]) == 2
    assert lectura.datos["starter_item_entries"] == variante["starter_item_entries"]
    assert lectura.datos["starting_items_provenance"]["patch"] == "16.20"


def test_actualizacion_parcial_conserva_objetos_iniciales_del_mismo_parche(
    fuente_aatrox: dict,
    servicio_aatrox: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retiene compras iniciales anteriores ante una respuesta parcial del mismo parche."""
    servicio, datos = servicio_aatrox
    servicio._versiones_fuente["U.GG overview"] = fuente_aatrox["source_patch"]
    monkeypatch.setattr(
        servicio, "_overview", Mock(return_value=fuente_aatrox["payload"])
    )
    previa = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut"},
        "power_curve_and_scaling": {},
    }
    variante_previa = {
        "role": "mid",
        "rank": "emerald_plus",
        "updated": True,
        "runes": [],
        "source_patch": fuente_aatrox["source_patch"],
        "starter_items": ["Espada de Doran", "Poción de vida"],
        "starter_item_ids": [1055, 2003],
        "starter_item_entries": [
            {"item_id": 1055, "name": "Espada de Doran", "quantity": 1},
            {"item_id": 2003, "name": "Poción de vida", "quantity": 2},
        ],
        "starting_item_matches": 213,
        "starting_item_win_rate": 0.4601,
    }
    repositorio = RepositorioCampeones(datos / "champion_data")
    repositorio.guardar(
        "Aatrox",
        repositorio.documento(previa, {"emerald_plus": {"mid": variante_previa}}),
    )
    monkeypatch.setattr(
        servicio,
        "fetch_variant",
        Mock(
            return_value={
                "role": "mid",
                "rank": "emerald_plus",
                "updated": True,
                "source_patch": fuente_aatrox["source_patch"],
                "starting_items_source_status": "NOT_PROVIDED",
            }
        ),
    )

    matriz = servicio.fetch_matrix(previa)

    recuperada = matriz["emerald_plus"]["mid"]
    assert recuperada["starter_item_ids"] == [1055, 2003]
    assert recuperada["starter_item_entries"][1]["quantity"] == 2
    assert recuperada["starting_item_matches"] == 213
    assert recuperada["starting_items_source_status"] == "AVAILABLE"


def test_ui_muestra_conteo_general_build_y_habilidades(
    fuente_aatrox: dict,
    servicio_aatrox: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verifica en Qt que cabecera y paneles usan datos extra\u00eddos de U.GG."""
    from app.ui.local_analysis_dialog import LocalAnalysisDialog

    app = QApplication.instance() or QApplication([])
    servicio, _ = servicio_aatrox
    variante = servicio._parse_overview(fuente_aatrox["payload"], "mid")
    variante.update(
        {
            "role": "mid",
            "rank": "emerald_plus",
            "updated": True,
            "sample_size": 450,
            "sample_status": "NORMAL_SAMPLE",
            "patch_label": "26.20",
            "lane_stats": {
                "rank": "emerald_plus",
                "lanes": {"mid": {"games": 450, "win_rate": 0.4467}},
            },
        }
    )
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
        **variante,
        "common_runes": variante["runes"],
        "power_curve_and_scaling": {},
    }
    dialogo = LocalAnalysisDialog(
        item_catalog={
            "version": "16.20.1",
            "items": json.loads(Path("data/items.json").read_text(encoding="utf-8"))[
                "items"
            ],
        }
    )
    dialogo._temporizador_analisis.stop()
    dialogo.analysis_lane_combo.setCurrentIndex(
        dialogo.analysis_lane_combo.findData("mid")
    )
    dialogo._active_variant = variante
    dialogo._datos_preparados = {"rutas": {}, "recomendaciones": [], "metadatos": {}}
    dialogo._renderizar_analisis(perfil)
    dialogo.show()
    app.processEvents()
    assert dialogo.champion_winrate.text() == "44.7% WR"
    assert "450 partidas" in dialogo.champion_lane.text()
    assert "44.7% WR" in dialogo.champion_lane.text()
    assert "26.20" in dialogo.champion_meta.text()
    assert dialogo.skill_order_grid.count() >= 18
    assert dialogo.summoners_row.count() == 2
    assert dialogo.starters_row.count() == 2
    assert dialogo.build_grid.count() >= 3
    etapa_cuatro = dialogo.build_grid.itemAtPosition(1, 1).widget()
    assert etapa_cuatro is not None and etapa_cuatro.layout().count() == 3
    assert dialogo.core_title.text() == "NÚCLEO DE LA BUILD"
    assert "11 partidas" in dialogo.core_title.toolTip()
    assert dialogo.champion_sample_badge.isHidden()
    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        dialogo.resize(ancho, alto)
        app.processEvents()
        assert dialogo.width() == ancho
        assert dialogo._scroll_analisis.width() > 0
    dialogo._scroll_analisis.verticalScrollBar().setValue(
        dialogo._scroll_analisis.verticalScrollBar().maximum()
    )
    app.processEvents()
    dialogo.grab().save(str(tmp_path / "analysis-screen.png"))
    dialogo.close()
    app.processEvents()


def test_error_de_seccion_conserva_estadistica_general_como_parcial(
    fuente_aatrox: dict,
    servicio_aatrox: tuple[ChampionScraperService, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No transforma un fallo de una sección en descarte de las estadísticas válidas."""
    servicio, _ = servicio_aatrox
    monkeypatch.setattr(
        servicio, "_overview", Mock(return_value=fuente_aatrox["payload"])
    )
    monkeypatch.setattr(
        servicio,
        "fetch_variant",
        Mock(side_effect=ValueError("sección temporalmente indisponible")),
    )
    matriz = servicio.fetch_matrix({"character": "Aatrox"})
    variante = matriz["emerald_plus"]["mid"]
    assert variante["overall_matches"] == 450
    assert variante["sample_size"] == 450
    assert variante["data_status"] == "PARTIAL_DATA"
    assert servicio._errores_parciales
