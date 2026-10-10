"""Pruebas del filtrado y la selección de builds locales."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.analisis_local_service import AnalisisLocalService
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.curador_recomendaciones_build import CuradorRecomendacionesBuild
from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.synergy_recommendation_service import ItemRecommendation

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def curador() -> CuradorRecomendacionesBuild:
    """Carga los catálogos locales incluidos en el repositorio para las pruebas."""
    datos = json.loads((RAIZ / "data" / "items.json").read_text(encoding="utf-8"))
    estrictos = json.loads(
        (RAIZ / "data" / "legendary_items_strict.json").read_text(encoding="utf-8")
    )
    catalogo = CatalogoAnalisisLocal(
        datos["items"], estrictos, {}, str(datos.get("version", ""))
    )
    return CuradorRecomendacionesBuild(
        catalogo, {str(objeto["id"]): objeto for objeto in estrictos}
    )


def _variante_local(campeon: str, linea: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lee una muestra persistida de campeón y línea sin realizar peticiones."""
    documento = json.loads(
        (RAIZ / "data" / "champion_data" / f"{campeon}.json").read_text(
            encoding="utf-8"
        )
    )
    return documento["profile"], documento["ranks"]["emerald_plus"][linea]


def _candidatos(variante: dict[str, Any]) -> list[ItemRecommendation]:
    """Convierte las recomendaciones guardadas al modelo usado por el servicio."""
    fuente = variante.get("item_candidates") or variante.get("recommendations", [])
    return [
        ItemRecommendation(
            str(item["item_id"]),
            str(item["name"]),
            float(item.get("score", 0)),
            tuple(item.get("reasons", [])),
            tuple(item.get("counter_reasons", [])),
            str(item.get("compatibility_label", "Situacional")),
            tuple(item.get("compatibility_reasons", [])),
            float(item.get("compatibility_score", 0)),
            float(item.get("matchup_score", 0)),
            float(item.get("build_synergy_score", 0)),
        )
        for item in fuente
    ]


@pytest.mark.parametrize(
    ("campeon", "linea"),
    [
        ("aatrox", "top"),
        ("briar", "jungle"),
        ("jinx", "adc"),
        ("lux", "mid"),
        ("ornn", "top"),
        ("janna", "support"),
    ],
)
def test_builds_de_arquetipos_mantienen_tres_items_y_limites(
    curador: CuradorRecomendacionesBuild, campeon: str, linea: str
) -> None:
    """Comprueba núcleo, elegibilidad, unicidad y límites para seis arquetipos."""
    perfil, variante = _variante_local(campeon, linea)
    resultado = curador.curar(variante, perfil, _candidatos(variante))
    nucleo = resultado["recommended_core_items"]
    build = resultado["recommended_build"]
    situacionales = resultado["situational_items"]
    ids_nucleo = [str(item["item_id"]) for item in nucleo]
    ids_build = [str(item["item_id"]) for item in build]
    assert len(nucleo) == 3
    assert ids_build[:3] == ids_nucleo
    assert len(build) <= 6
    assert len(ids_build) == len(set(ids_build))
    assert all(2 <= len(items) <= 5 for items in situacionales.values())
    assert not resultado["situational_coverage_failures"]
    nombres = [nombre for items in situacionales.values() for nombre in items]
    assert len(nombres) == len(set(nombres))
    for item_id in ids_build:
        objeto = curador.catalogo.catalogo[item_id]
        assert curador.catalogo.validar_elegibilidad(
            item_id, objeto, campeon.capitalize(), "SR_RANKED_SOLO_DUO"
        ).elegible
    arquetipo = curador._arquetipo_build(perfil, nucleo)
    for entrada in resultado["situational_item_candidates"]:
        item_id = str(entrada["item_id"])
        objeto = curador.catalogo.catalogo[item_id]
        assert item_id not in ids_nucleo
        assert entrada["compatibility_score"] > -12
        assert curador._categoria_situacional(item_id, arquetipo) == entrada["category"]
        assert curador.catalogo.validar_elegibilidad(
            item_id, objeto, campeon.capitalize(), "SR_RANKED_SOLO_DUO"
        ).elegible


def test_aatrox_usa_tres_objetos_de_nucleo_sin_botines(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Confirma que botas y objetos tardíos no desplazan el núcleo de Aatrox."""
    perfil, variante = _variante_local("aatrox", "top")
    resultado = curador.curar(variante, perfil, _candidatos(variante))
    assert [item["name"] for item in resultado["recommended_core_items"]] == [
        "Eclipse",
        "Firmamento desgarrado",
        "Baile de la muerte",
    ]
    assert "Boots" not in curador.catalogo.catalogo[
        resultado["recommended_core_items"][0]["item_id"]
    ].get("tags", [])


def test_briar_conserva_la_progresion_estadistica_del_proveedor(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Comprueba que los primeros tres objetos de Briar siguen el build guardado."""
    perfil, variante = _variante_local("briar", "jungle")
    resultado = curador.curar(variante, perfil, _candidatos(variante))
    assert [item["name"] for item in resultado["recommended_core_items"]] == [
        "Recaudadora",
        "Hidra titánica",
        "Recuerdos de lord Dominik",
    ]
    assert resultado["recommended_build"][:3] == resultado["recommended_core_items"]


def test_briar_cura_builds_separadas_segun_la_pagina_de_runas(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Usa build y opciones estadísticas condicionadas a cada página de Briar."""
    perfil, variante = _variante_local("briar", "jungle")
    candidatos = _candidatos(variante)
    pagina_letalidad, pagina_sostenida = variante["runes"][:2]
    letalidad = curador.curar(variante, perfil, candidatos, pagina_letalidad)
    sostenida = curador.curar(variante, perfil, candidatos, pagina_sostenida)
    letalidad_repetida = curador.curar(variante, perfil, candidatos, pagina_letalidad)
    assert [item["name"] for item in letalidad["recommended_core_items"]] == [
        "Soberbia",
        "Recaudadora",
        "Recuerdos de lord Dominik",
    ]
    assert [item["name"] for item in sostenida["recommended_core_items"]] == [
        "Recaudadora",
        "Hidra titánica",
        "Recuerdos de lord Dominik",
    ]
    assert letalidad["recommended_build"] != sostenida["recommended_build"]
    assert letalidad["situational_items"] != sostenida["situational_items"]
    assert letalidad["recommended_build"] == letalidad_repetida["recommended_build"]
    assert letalidad["situational_items"] == letalidad_repetida["situational_items"]
    assert letalidad["situational_coverage_failures"] == []
    assert sostenida["situational_coverage_failures"] == []


def test_identidad_de_pagina_incluye_runas_parche_campeon_y_rol(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Separa cachés de páginas distintas y de contextos de parche o rol."""
    _, variante = _variante_local("briar", "jungle")
    pagina = variante["runes"][0]
    clave = curador.clave_pagina_runas(
        pagina, "16.20.1", "Briar", "jungle", "emerald_plus"
    )
    cambiada = dict(pagina, secondary_slots=list(pagina["secondary_slots"]))
    cambiada["secondary_slots"][0] = "otra runa"
    assert clave != curador.clave_pagina_runas(
        cambiada, "16.20.1", "Briar", "jungle", "emerald_plus"
    )
    assert clave != curador.clave_pagina_runas(
        pagina, "16.21.1", "Briar", "jungle", "emerald_plus"
    )
    assert clave != curador.clave_pagina_runas(
        pagina, "16.20.1", "Briar", "top", "emerald_plus"
    )


def test_runas_menores_participan_si_no_hay_keystone_conocida(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Reconoce patrones de burst y combate sostenido en runas menores."""
    assert (
        curador._modo_runa({"keystone": "Runa desconocida", "slots": ["Sudden Impact"]})
        == "burst"
    )
    assert (
        curador._modo_runa({"keystone": "Runa desconocida", "slots": ["Alacrity"]})
        == "sostenido"
    )


def test_servicio_cachea_perfiles_por_pagina_de_runas(
    curador: CuradorRecomendacionesBuild, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Precalcula ambas páginas de Briar y las reutiliza al reabrir el análisis."""
    import app.services.analisis_local_service as modulo

    for funcion in (
        "get_item_icon_path",
        "get_ability_icon_path",
        "get_champion_icon_path",
        "get_rune_icon_path",
        "get_spell_icon_path",
    ):
        monkeypatch.setattr(modulo.data_dragon, funcion, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        modulo.data_dragon, "get_champion_data", lambda *args, **kwargs: {}
    )
    servicio = AnalisisLocalService(
        curador.catalogo, RAIZ / "data" / "champion_data", curador.catalogo.parche
    )
    perfil, variante = _variante_local("briar", "jungle")
    primera = servicio.cargar(
        perfil,
        "jungle",
        "emerald_plus",
        variante["runes"][0],
        lambda: False,
    )
    segunda = servicio.cargar(
        perfil,
        "jungle",
        "emerald_plus",
        variante["runes"][0],
        lambda: False,
    )
    claves = primera["rune_profile_keys"]
    cache = primera["rune_profiles_by_key"]
    assert len(claves) == 2
    assert len(cache) == 2
    assert (
        cache[claves[0]]["recommended_core_items"]
        != cache[claves[1]]["recommended_core_items"]
    )
    assert segunda["rune_profiles_by_key"] == cache
    assert segunda["tiempos"]["calculo_ms"] == 0.0


def test_briar_ad_bruiser_excluye_ap_y_crit_sin_sinergia_de_arquetipo(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Evita que estadísticas genéricas admitan AP o crítico en el AD de Briar."""
    perfil, variante = _variante_local("briar", "jungle")
    resultado = curador.curar(variante, perfil, _candidatos(variante))
    nucleo = resultado["recommended_core_items"]
    arquetipo = curador._arquetipo_build(perfil, nucleo)
    ids = {entrada["item_id"] for entrada in resultado["situational_item_candidates"]}
    assert arquetipo == "ad_bruiser"
    assert "3157" not in ids
    assert "3031" not in ids
    assert not curador._compatible_situacional(
        perfil, "3157", "utilidad_y_defensa", 100.0, arquetipo, {}, True
    )
    assert not curador._compatible_situacional(
        perfil, "3031", "asesino", 100.0, arquetipo, {}, True
    )


def test_arquetipo_de_letalidad_se_infiere_del_nucleo(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Reconoce una variante de letalidad sin excepciones por campeón."""
    perfil, _ = _variante_local("briar", "jungle")
    nucleo = [
        {"item_id": "6692"},
        {"item_id": "6698"},
        {"item_id": "3142"},
    ]
    assert curador._arquetipo_build(perfil, nucleo) == "ad_letalidad"
    assert curador._compatible_situacional(
        perfil, "3142", "asesino", 0.0, "ad_letalidad", {}, False
    )


def test_muestras_pequenas_se_suavizan_frente_a_muestras_grandes(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Evita que una tasa perfecta con pocas partidas domine el ranking."""
    poca_muestra = curador._puntuacion(
        {"item_id": "1", "games": 2, "wins": 2, "win_rate": 1.0}, {}
    )
    muestra_amplia = curador._puntuacion(
        {"item_id": "2", "games": 500, "wins": 250, "win_rate": 0.5}, {}
    )
    assert poca_muestra - muestra_amplia < 0.1
    assert curador._tiene_muestra({"games": 1})
    assert not curador._tiene_muestra({"games": 0})


def test_datos_situacionales_vacios_usan_el_pool_de_sinergia(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Mantiene categorías vacías cuando no hay candidato del conjunto fuente."""
    perfil, variante = _variante_local("janna", "support")
    variante["source_situational_items"] = {"tanque": ["objeto inexistente"]}
    variante["situational_items"] = {categoria: [] for categoria in curador.CATEGORIAS}
    variante["item_options"] = {}
    resultado = curador.curar(variante, perfil, _candidatos(variante))
    assert all(
        2 <= len(items) <= 5 for items in resultado["situational_items"].values()
    )
    assert all(
        item["recommendation_source"] == "champion_synergy"
        and "games" not in item
        and "win_rate" not in item
        for item in resultado["situational_item_candidates"]
        if not item["has_statistical_evidence"]
    )


def test_datos_fuente_se_conservan_sin_mutacion(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Preserva listas originales mientras devuelve recomendaciones filtradas."""
    perfil, variante = _variante_local("aatrox", "top")
    originales = json.loads(json.dumps(variante))
    resultado = curador.curar(variante, perfil, _candidatos(variante))
    assert variante == originales
    assert 2 <= len(resultado["situational_items"]["tanque"]) <= 5
    assert (
        originales["situational_items"]["tanque"]
        == variante["situational_items"]["tanque"]
    )


def test_curacion_repetida_es_idempotente(
    curador: CuradorRecomendacionesBuild,
) -> None:
    """Conserva las mismas selecciones al volver a preparar el mismo perfil."""
    perfil, variante = _variante_local("aatrox", "top")
    candidatos = _candidatos(variante)
    primera = curador.curar(variante, perfil, candidatos)
    segunda = curador.curar(primera, perfil, candidatos)
    assert primera["recommended_build"] == segunda["recommended_build"]
    assert primera["situational_items"] == segunda["situational_items"]


def test_herramienta_draft_usa_las_mismas_recomendaciones_curadas() -> None:
    """Mantiene límites y progresión al consumir builds desde la herramienta Draft."""
    servicio = DraftAnalyzerService()
    situacionales = servicio.get_situational_items("Aatrox")
    build = servicio.get_champion_build("Aatrox", [])
    assert all(2 <= len(grupo["items"]) <= 5 for grupo in situacionales)
    assert len(build["items"]) <= 6
    assert len({item["id"] for item in build["items"]}) == len(build["items"])
