"""Regresiones de opciones tardías, categorías y builds del análisis local."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from app.services.champion_scraper_service import ChampionScraperService
from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones


@pytest.fixture
def payload_aatrox() -> dict:
    """Carga el payload realista de U.GG con los filtros de la regresión."""
    return json.loads(
        Path("app/scratch/fixtures/ugg_aatrox_mid_emerald_plus_16_20.json").read_text(
            encoding="utf-8"
        )
    )["payload"]


@pytest.fixture
def servicio() -> ChampionScraperService:
    """Crea el scraper con catálogos locales y rango Emerald+."""
    return ChampionScraperService(Path("data/champion_data"), 0, "emerald_plus")


def configurar_fuentes(
    scraper: ChampionScraperService,
    payload: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aísla U.GG y desactiva fuentes externas ajenas a la prueba."""
    scraper._versiones_fuente["U.GG overview"] = "16.20"
    monkeypatch.setattr(scraper, "_patches", Mock(return_value=["26.20", "16.20"]))
    monkeypatch.setattr(scraper, "_overview", Mock(return_value=payload))
    monkeypatch.setattr(scraper, "_parse_opgg", Mock(return_value={}))
    monkeypatch.setattr(scraper, "_parse_lolalytics", Mock(return_value={}))
    monkeypatch.setattr(scraper, "_lolalytics", Mock(return_value=None))
    monkeypatch.setattr(scraper, "_lolalytics_page", Mock(return_value=None))
    monkeypatch.setattr(scraper, "_ugg_archetype_pages", Mock(return_value=[]))
    monkeypatch.setattr(scraper, "_builds", Mock(return_value=None))
    monkeypatch.setattr(scraper, "_get", Mock(return_value=None))
    monkeypatch.setattr(scraper, "_scrape_damage_breakdown", Mock(return_value=None))
    monkeypatch.setattr(
        scraper, "_scrape_winrate_vs_game_length", Mock(return_value=None)
    )


def perfil_aatrox() -> dict:
    """Genera un perfil mínimo del campeón seleccionado para normalizar una variante."""
    return {
        "character": "Aatrox",
        "basic_info": {
            "play_style": "Juggernaut",
            "flex_potential": ["Mid"],
        },
        "combat_attributes": {
            "attack_damage": 8,
            "attack_power": 2,
            "critic": 1,
            "lethality": 4,
        },
        "strategy_and_macro": {
            "about": "Ability fighter with empowered sword slams.",
            "primary_combo": ["Q1", "Q2", "W", "E"],
        },
        "power_curve_and_scaling": {},
    }


def opciones_de_cuatro_categorias(
    payload: dict, scraper: ChampionScraperService
) -> dict:
    """Amplía el bloque de opciones con objetos válidos para probar las cuatro categorías."""
    resultado = copy.deepcopy(payload)
    bloques = scraper._position_blocks(resultado, "mid")
    bloques[5] = [
        [[3033, 5, 10], [3156, 8, 12]],
        [[6694, 4, 8], [6694, 3, 6]],
        [[3158, 2, 3]],
    ]
    return resultado


def test_opciones_tardias_se_clasifican_y_conservan_procedencia(
    payload_aatrox: dict,
    servicio: ChampionScraperService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conserva alternativas y muestras, separadas de la build principal."""
    payload = opciones_de_cuatro_categorias(payload_aatrox, servicio)
    configurar_fuentes(servicio, payload, monkeypatch)
    perfil = perfil_aatrox()

    assert servicio.update_champion(perfil)

    assert [x["item_id"] for x in perfil["item_options"]["4"]] == [3033, 3156]
    assert [x["item_id"] for x in perfil["item_options"]["5"]] == [6694, 6694]
    assert perfil["item_options"]["5"][0]["games"] == 8
    assert perfil["item_options"]["5"][1]["games"] == 6
    assert all(
        x["source"] == "U.GG"
        for values in perfil["item_options"].values()
        for x in values
    )
    assert all(
        x["rank"] == "emerald_plus"
        for values in perfil["item_options"].values()
        for x in values
    )
    assert perfil["boots"][0]["item_id"] == 3008
    assert perfil["source_situational_items"]["corta_curas"] == ["Recordatorio letal"]
    assert perfil["source_situational_items"]["tanque"] == ["Fauces de Malmortius"]
    assert perfil["source_situational_items"]["asesino"] == ["Rencor de Serylda"]
    assert perfil["source_situational_items"]["utilidad_y_defensa"] == [
        "Botas jonias de la lucidez"
    ]
    assert perfil["situational_item_pipeline"]["source_options"] == 5
    assert perfil["situational_item_pipeline"]["parsed"] == 5
    assert perfil["situational_item_pipeline"]["persisted"] == 4
    assert len(perfil["most_played_build"]) == 3
    assert len({nombre.casefold() for nombre in perfil["most_played_build"]}) == 3
    assert servicio._normalizar_build_completa(
        ["Eclipse", "Firmamento desgarrado", "Firmamento desgarrado"]
    ) == ["Eclipse", "Firmamento desgarrado"]
    assert servicio._normalizar_build_completa(
        ["Grebas codiciosas", "Grebas codiciosas", "Eclipse"]
    ) == ["Grebas codiciosas", "Eclipse"]


def test_opciones_de_baja_muestra_se_conservan_y_no_se_aplanan_en_la_build(
    payload_aatrox: dict, servicio: ChampionScraperService
) -> None:
    """Mantiene alternativas repetidas entre puestos y no las convierte en secuencia."""
    payload = opciones_de_cuatro_categorias(payload_aatrox, servicio)
    servicio._versiones_fuente["U.GG overview"] = "16.20"
    datos = servicio._parse_overview(payload, "mid", "Aatrox")

    assert "full_build" not in datos
    assert datos["most_played_build"] == datos["items"]
    assert datos["item_options"]["5"][0]["games"] == 8
    assert datos["item_options"]["5"][1]["games"] == 6
    assert datos["item_options"]["5"][0]["sample_status"] == "LOW_SAMPLE"
    assert datos["item_options"]["5"][0]["source_patch"] == "16.20"


def test_refresh_parcial_preserva_categorias_anteriores(
    payload_aatrox: dict,
    servicio: ChampionScraperService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No elimina recomendaciones guardadas cuando la respuesta omite esa sección."""
    payload = copy.deepcopy(payload_aatrox)
    bloques = servicio._position_blocks(payload, "mid")
    bloques[5] = None
    configurar_fuentes(servicio, payload, monkeypatch)
    perfil = perfil_aatrox()
    anteriores = {
        "corta_curas": ["Recordatorio letal"],
        "tanque": ["Fauces de Malmortius"],
        "asesino": [],
        "utilidad_y_defensa": [],
    }
    perfil["situational_items"] = copy.deepcopy(anteriores)

    assert servicio.update_champion(perfil)
    assert perfil["situational_items"] == anteriores


def test_seccion_vacia_explicita_limpia_y_fallo_no_se_confunde(
    payload_aatrox: dict, servicio: ChampionScraperService
) -> None:
    """Distingue un bloque de opciones vacío de un bloque ausente por error."""
    vacio = copy.deepcopy(payload_aatrox)
    servicio._position_blocks(vacio, "mid")[5] = []
    datos_vacios = servicio._parse_overview(vacio, "mid", "Aatrox")
    sin_seccion = copy.deepcopy(payload_aatrox)
    servicio._position_blocks(sin_seccion, "mid")[5] = None
    datos_incompletos = servicio._parse_overview(sin_seccion, "mid", "Aatrox")

    assert datos_vacios["item_options"] == {}
    assert datos_vacios["section_status"]["item_options"] == "EMPTY"
    assert datos_vacios["situational_items"] == {
        "corta_curas": [],
        "tanque": [],
        "asesino": [],
        "utilidad_y_defensa": [],
    }
    assert "item_options" not in datos_incompletos
    assert "situational_items" not in datos_incompletos


def test_recomendaciones_se_persisten_y_se_recargan_sin_danar_otro_campeon(
    payload_aatrox: dict,
    servicio: ChampionScraperService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Guarda el flujo normalizado en el repositorio y verifica su recarga."""
    payload = opciones_de_cuatro_categorias(payload_aatrox, servicio)
    configurar_fuentes(servicio, payload, monkeypatch)
    variante = perfil_aatrox()
    assert servicio.update_champion(variante)
    variante.update(
        {
            "role": "mid",
            "rank": "emerald_plus",
            "updated": True,
            "sample_size": 450,
            "sample_status": "NORMAL_SAMPLE",
        }
    )
    perfil = perfil_aatrox()
    matriz = {"emerald_plus": {"mid": variante}}
    documento = PreparadorDatosCampeon(Path("data")).preparar(perfil, matriz)
    repositorio = RepositorioCampeones(tmp_path / "champion_data")
    otra_ruta = repositorio.ruta("Ahri")
    otra_ruta.write_text('{"registro":"intacto"}', encoding="utf-8")
    estado_ajeno = otra_ruta.read_bytes()
    repositorio.guardar("Aatrox", documento)
    lectura = repositorio.consultar("Aatrox", "mid", "emerald_plus")

    assert lectura.estado == EstadoDatos.DISPONIBLE
    assert lectura.datos["item_options"]["5"][0]["games"] == 8
    assert lectura.datos["source_situational_items"]["corta_curas"] == [
        "Recordatorio letal"
    ]
    assert len(lectura.datos["situational_item_candidates"]) > 10
    assert len(lectura.datos["item_candidates"]) > 30
    assert lectura.datos["recommended_build"]
    assert lectura.datos["situational_item_pipeline"]["persisted"] == 4
    assert otra_ruta.read_bytes() == estado_ajeno


def test_pool_contextual_completo_botas_validas_y_cuatro_categorias() -> None:
    """Genera opciones de afinidad desde el catálogo de la línea sin datos inventados."""
    preparado = PreparadorDatosCampeon(Path("data"))
    fuente = json.loads(
        Path("data/champion_data/aatrox.json").read_text(encoding="utf-8")
    )
    variante = fuente["ranks"]["emerald_plus"]["mid"]
    perfil = fuente["profile"]
    documento = preparado.preparar(perfil, {"emerald_plus": {"mid": variante}})
    datos = documento["ranks"]["emerald_plus"]["mid"]
    categorias = datos["situational_items"]

    assert len(datos["item_candidates"]) > 30
    assert len(datos["situational_item_candidates"]) > 10
    assert all(
        categorias[key]
        for key in ("corta_curas", "tanque", "asesino", "utilidad_y_defensa")
    )
    assert "Recordatorio letal" in categorias["corta_curas"]
    assert datos["recommendation_diagnostics"]["affinity_candidate_count"] == len(
        datos["item_candidates"]
    )
    assert datos["recommendation_diagnostics"]["synergy_candidate_count"] == len(
        datos["item_candidates"]
    )
    assert all(
        "11" not in preparado.catalogo.catalogo.get(item["item_id"], {}).get("maps", {})
        or preparado.catalogo.catalogo[item["item_id"]]["maps"]["11"]
        for item in datos["item_candidates"]
    )
    assert len(datos["recommended_build"]) == len(
        {str(item["item_id"]) for item in datos["recommended_build"]}
    )
    assert datos["recommended_build"]
    assert (
        sum(
            "Boots"
            in preparado.catalogo.catalogo.get(str(item["item_id"]), {}).get("tags", [])
            for item in datos["recommended_build"]
        )
        == 1
    )


def test_build_local_inserta_una_bota_valida_despues_del_primer_objeto() -> None:
    """Elige una bota legal del parche solo cuando el núcleo carece de ella."""
    preparado = PreparadorDatosCampeon(Path("data"))
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
        "power_curve_and_scaling": {},
    }
    variante = {
        "core_build": [
            {"item_id": 6692, "name": "Eclipse", "slot": 1},
            {"item_id": 6610, "name": "Firmamento desgarrado", "slot": 2},
        ],
        "most_played_build": ["Eclipse", "Firmamento desgarrado"],
    }
    documento = preparado.preparar(perfil, {"emerald_plus": {"mid": variante}})
    build = documento["ranks"]["emerald_plus"]["mid"]["recommended_build"]
    botas = [
        item
        for item in build
        if "Boots"
        in preparado.catalogo.catalogo.get(str(item["item_id"]), {}).get("tags", [])
    ]

    assert len(botas) == 1
    assert build[0]["name"] == "Eclipse"
    assert build[1]["item_id"] == botas[0]["item_id"]
    assert botas[0]["origin"] == "SOLRALOL"


def test_ventajas_y_counters_se_fusionan_por_separado(
    servicio: ChampionScraperService,
) -> None:
    """Conserva el grupo favorable aunque U.GG solo haya devuelto counters."""
    resultado = servicio._merge_matchups(
        "mid",
        (
            "U.GG",
            {"counters": [{"champion": "Sion", "win_rate": 0.22, "lane_games": 80}]},
        ),
        (
            "Lolalytics",
            {
                "good_against": [
                    {"champion": "Garen", "win_rate": 0.63, "lane_games": 120}
                ]
            },
        ),
    )

    assert resultado["counters"][0]["champion"] == "Sion"
    assert resultado["counters"][0]["win_rate"] == 0.22
    assert resultado["good_against"][0]["champion"] == "Garen"
    assert resultado["good_against"][0]["win_rate"] == 0.63
    assert resultado["good_against"][0]["source"] == "Lolalytics"


def test_matchup_favorable_de_muestra_pequena_se_persiste(
    payload_aatrox: dict,
    servicio: ChampionScraperService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persiste una ventaja fiable aunque su grupo tenga menos de tres filas."""
    configurar_fuentes(servicio, payload_aatrox, monkeypatch)
    monkeypatch.setattr(servicio, "_get", Mock(return_value=object()))
    monkeypatch.setattr(
        servicio,
        "_parse_matchups",
        Mock(
            return_value={
                "good_against": [
                    {"champion": "Garen", "win_rate": 0.61, "lane_games": 42}
                ]
            }
        ),
    )
    perfil = perfil_aatrox()

    assert servicio.update_champion(perfil)
    assert perfil["matchups"]["good_against"][0]["champion"] == "Garen"
    assert perfil["matchups"]["good_against"][0]["lane_games"] == 42


def test_afinidad_usa_el_pool_completo_persistido(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Carga todas las opciones calculadas en el servicio local, no solo las primeras treinta."""
    import app.services.analisis_local_service as modulo
    from app.services.analisis_local_service import AnalisisLocalService

    for nombre in (
        "get_item_icon_path",
        "get_champion_icon_path",
        "get_rune_icon_path",
        "get_spell_icon_path",
        "get_ability_icon_path",
    ):
        monkeypatch.setattr(modulo.data_dragon, nombre, Mock(return_value=None))
    monkeypatch.setattr(
        modulo.data_dragon, "get_champion_data", Mock(return_value={"title": ""})
    )
    fuente = json.loads(
        Path("data/champion_data/aatrox.json").read_text(encoding="utf-8")
    )
    variante = fuente["ranks"]["emerald_plus"]["mid"]
    perfil = perfil_aatrox()
    documento = PreparadorDatosCampeon(Path("data")).preparar(
        perfil, {"emerald_plus": {"mid": variante}}
    )
    pool_preparado = documento["ranks"]["emerald_plus"]["mid"]["item_candidates"]
    servicio_local = AnalisisLocalService(
        PreparadorDatosCampeon(Path("data")).catalogo,
        tmp_path / "variantes",
        "16.20.1",
    )
    servicio_local.variantes.repositorio.guardar("Aatrox", documento)

    resultado = servicio_local.cargar(perfil, "mid", "emerald_plus", {}, lambda: False)

    assert len(resultado["candidatos_afinidad"]) == len(pool_preparado)
    assert len(resultado["recomendaciones"]) == 30
    assert len(resultado["candidatos_afinidad"]) > len(resultado["recomendaciones"])


def test_build_ui_separa_botas_y_no_repite_el_nucleo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La vista mantiene los objetos del núcleo y coloca las botas una sola vez."""
    from app.ui.local_analysis_dialog import LocalAnalysisDialog

    app = QApplication.instance() or QApplication([])
    catalogo = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
        "recommended_build": [
            {"item_id": "6692", "name": "Eclipse"},
            {"item_id": "6610", "name": "Firmamento desgarrado"},
            {"item_id": "3047", "name": "Botas blindadas"},
            {"item_id": "6610", "name": "Firmamento desgarrado"},
        ],
        "recommended_build_details": [
            {"item_id": "3047", "name": "Botas blindadas", "origin": "SOLRALOL"}
        ],
        "core_build_matches": 11,
    }
    dialogo = LocalAnalysisDialog(item_catalog=catalogo)
    dialogo._temporizador_analisis.stop()
    dialogo._current_profile = perfil
    pixmap = QPixmap(24, 24)
    pixmap.fill(QColor("#b69a50"))
    monkeypatch.setattr(dialogo, "_recurso_analisis", lambda *_args: Path("icono.png"))
    monkeypatch.setattr(dialogo, "_pixmap_analisis", lambda _ruta: pixmap)
    dialogo._render_core_items(perfil, "Juggernaut")
    dialogo._render_full_build(perfil, "Juggernaut")
    app.processEvents()

    assert dialogo._build_slots(perfil) == (
        ["Eclipse", "Firmamento desgarrado"],
        ["Botas blindadas"],
    )
    assert dialogo.core_title.text() == "NÚCLEO DE LA BUILD"
    panel_botas = dialogo.build_grid.itemAtPosition(1, 0).widget()
    assert panel_botas is not None
    assert "BOTAS RECOMENDADAS" in [
        label.text() for label in panel_botas.findChildren(QLabel)
    ]
    dialogo.close()
    app.processEvents()


def test_ui_pinta_ventajas_favorables_del_registro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderiza el grupo favorable almacenado sin deducir rivales nuevos."""
    from app.ui.local_analysis_dialog import LocalAnalysisDialog

    app = QApplication.instance() or QApplication([])
    registro = json.loads(
        Path("data/champion_data/ahri.json").read_text(encoding="utf-8")
    )
    perfil = {
        "character": "Ahri",
        "basic_info": {"play_style": "Mage", "flex_potential": ["Mid"]},
        "matchups": registro["ranks"]["emerald_plus"]["mid"]["matchups"],
    }
    dialogo = LocalAnalysisDialog(
        item_catalog=json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    )
    dialogo._temporizador_analisis.stop()
    dialogo._current_profile = perfil
    pixmap = QPixmap(24, 24)
    pixmap.fill(QColor("#b69a50"))
    monkeypatch.setattr(dialogo, "_recurso_analisis", lambda *_args: Path("icono.png"))
    monkeypatch.setattr(dialogo, "_pixmap_analisis", lambda _ruta: pixmap)
    dialogo._render_matchups_panel(perfil)
    app.processEvents()

    assert len(perfil["matchups"]["good_against"]) == 5
    nombres = [
        etiqueta.text()
        for indice in range(dialogo.good_cards_layout.count())
        if (widget := dialogo.good_cards_layout.itemAt(indice).widget()) is not None
        for etiqueta in widget.findChildren(QLabel, "matchupChampName")
    ]
    assert nombres
    assert nombres[0] == perfil["matchups"]["good_against"][0]["champion"]
    dialogo.close()
    app.processEvents()


def test_listas_situacionales_muestran_cuatro_filas_completas_en_resoluciones_de_escritorio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comprueba el alto visible de cada categoría sin limitar sus recomendaciones."""
    from app.ui.local_analysis_dialog import LocalAnalysisDialog

    app = QApplication.instance() or QApplication([])
    catalogo = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    dialogo = LocalAnalysisDialog(item_catalog=catalogo)
    dialogo._temporizador_analisis.stop()
    dialogo.findChild(QWidget, "localAnalysisTabs").setCurrentIndex(0)
    monkeypatch.setattr(dialogo, "_recurso_analisis", lambda *_args: None)
    lista_objetos = dialogo.findChild(QWidget, "localAnalysisView")
    assert lista_objetos is not None

    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        dialogo.resize(ancho, alto)
        dialogo.show()
        for cantidad in (0, 1, 3, 4, 13, 21):
            nombres = [
                f"Alternativa defensiva de nombre largo {indice}"
                for indice in range(cantidad)
            ]
            categorias = (
                "corta_curas",
                "tanque",
                "asesino",
                "utilidad_y_defensa",
            )
            perfil = {
                "character": "Aatrox",
                "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
                "situational_items": {clave: nombres for clave in categorias},
                "most_played_build": [],
            }
            dialogo._render_situational_items(perfil)
            dialogo._mostrar_contenido(True)
            app.processEvents()
            dialogo._scroll_analisis.verticalScrollBar().setValue(
                dialogo._scroll_analisis.verticalScrollBar().maximum()
            )
            app.processEvents()
            for indice, clave in enumerate(categorias):
                columna = dialogo.situational_items_row.itemAtPosition(
                    indice // 2, indice % 2
                ).widget()
                scroll = columna.findChild(QScrollArea, f"situationalList_{clave}")
                assert (scroll is not None) == bool(cantidad)
                if not cantidad:
                    continue
                filas = scroll.widget().findChildren(QWidget, "localItemRow")
                assert len(filas) == cantidad
                viewport = scroll.viewport()
                visibles = [
                    fila
                    for fila in filas
                    if fila.mapTo(viewport, QPoint(0, 0)).y() >= 0
                    and fila.mapTo(viewport, QPoint(0, 0)).y() + fila.height()
                    <= viewport.height()
                ]
                assert len(visibles) >= min(4, cantidad)
                assert all(fila in visibles for fila in filas[: min(4, cantidad)])
                assert (
                    viewport.height()
                    >= sum(fila.height() for fila in filas[: min(4, cantidad)])
                    + max(0, min(4, cantidad) - 1) * 4
                )
                assert all(
                    etiqueta.wordWrap()
                    for fila in filas
                    for etiqueta in fila.findChildren(QLabel, "localItemName")
                )
                if cantidad > 4:
                    assert scroll.verticalScrollBar().maximum() > 0
                    scroll.verticalScrollBar().setValue(
                        scroll.verticalScrollBar().maximum()
                    )
                    app.processEvents()
                    assert (
                        len(scroll.widget().findChildren(QWidget, "localItemRow"))
                        == cantidad
                    )
                else:
                    assert len(visibles) == cantidad
    dialogo.close()
    app.processEvents()


def test_ui_renderiza_categorias_opciones_build_core_y_muestra_reducida(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Comprueba tarjetas de objetos y muestras en widgets Qt sin red."""
    from app.ui.local_analysis_dialog import LocalAnalysisDialog

    app = QApplication.instance() or QApplication([])
    catalogo = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    perfil = {
        "character": "Aatrox",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Mid"]},
        "most_played_build": [
            "Eclipse",
            "Firmamento desgarrado",
            "Firmamento desgarrado",
        ],
        "items": ["Eclipse", "Firmamento desgarrado"],
        "power_curve_and_scaling": {
            "power_spike_items": ["Eclipse", "Firmamento desgarrado"]
        },
        "core_build": [
            {"name": "Eclipse", "item_id": 6692},
            {"name": "Firmamento desgarrado", "item_id": 6610},
        ],
        "core_build_matches": 11,
        "item_options": {
            "4": [
                {
                    "item_id": 3033,
                    "name": "Recordatorio letal",
                    "slot": 4,
                    "games": 10,
                    "win_rate": 0.5,
                    "source": "U.GG",
                    "sample_status": "LOW_SAMPLE",
                }
            ]
        },
        "situational_items": {
            "corta_curas": ["Recordatorio letal"],
            "tanque": ["Fauces de Malmortius"],
            "asesino": ["Rencor de Serylda"],
            "utilidad_y_defensa": ["Botas jonias de la lucidez"],
        },
        "situational_item_candidates": [
            {
                "item_id": "3033",
                "name": "Recordatorio letal",
                "compatibility_label": "Situacional",
                "compatibility_reasons": [
                    "Las heridas graves responden a curaciones altas."
                ],
            }
        ],
        "situational_item_pipeline": {"source": "U.GG", "persisted": 4},
        "starter_items": ["Espada de Doran", "Poción de vida", "Poción de vida"],
        "starter_item_entries": [
            {"item_id": 1055, "name": "Espada de Doran", "quantity": 1},
            {"item_id": 2003, "name": "Poción de vida", "quantity": 2},
        ],
        "summoner_spells": ["Destello", "Ignición"],
        "runes": [],
    }
    dialogo = LocalAnalysisDialog(item_catalog=catalogo)
    dialogo._temporizador_analisis.stop()
    pixmap = QPixmap(24, 24)
    pixmap.fill(QColor("#b69a50"))
    monkeypatch.setattr(
        dialogo, "_recurso_analisis", lambda _tipo, _nombre, *_args: Path("icono.png")
    )
    monkeypatch.setattr(dialogo, "_pixmap_analisis", lambda _ruta: pixmap)
    dialogo._current_profile = perfil
    dialogo._render_core_items(perfil, "Juggernaut")
    dialogo._render_full_build(perfil, "Juggernaut")
    dialogo._render_situational_items(perfil)
    dialogo._render_starter_and_spells(perfil)
    assert dialogo.starters_row.count() == 2
    assert (
        dialogo.starters_row.itemAt(1)
        .widget()
        .findChild(QLabel, "localItemQuantity")
        .text()
        == "×2"
    )
    from app.services.synergy_recommendation_service import ItemRecommendation

    principales = [
        ItemRecommendation(str(indice), f"Objeto {indice}", 50 - indice, (), ())
        for indice in range(3)
    ]
    todos = principales + [
        ItemRecommendation(str(indice), f"Objeto {indice}", 50 - indice, (), ())
        for indice in range(3, 8)
    ]
    dialogo._datos_preparados = {
        "recomendaciones": principales,
        "candidatos_afinidad": todos,
    }
    monkeypatch.setattr(dialogo, "_item_cell", lambda *_args: QWidget())
    dialogo._renderizar_tabla_recomendaciones(principales)
    dialogo.recommendation_toggle.setVisible(True)
    assert dialogo.item_table.rowCount() == 3
    dialogo.recommendation_toggle.click()
    assert dialogo.item_table.rowCount() == 8
    assert dialogo.recommendation_toggle.text() == "Mostrar las 30 principales"
    dialogo.show()
    app.processEvents()

    assert dialogo.core_overview_row.count() == 2
    assert dialogo.core_title.text() == "NÚCLEO DE LA BUILD"
    assert "11 partidas" in dialogo.core_title.toolTip()
    assert dialogo._build_slots(perfil) == (["Eclipse", "Firmamento desgarrado"], [])
    assert dialogo.build_grid.itemAtPosition(1, 0).widget() is not None
    assert "muestra U.GG" in dialogo.situational_source_note.text()
    for fila, columna in ((0, 0), (0, 1), (1, 0), (1, 1)):
        tarjeta = dialogo.situational_items_row.itemAtPosition(fila, columna).widget()
        assert isinstance(tarjeta, QWidget)
        fila_objeto = tarjeta.findChild(QWidget, "localItemRow")
        assert fila_objeto is not None
        assert fila_objeto.findChild(QWidget, "localItemIcon") is not None
        etiqueta = fila_objeto.findChild(QLabel, "localItemName")
        assert etiqueta is not None and etiqueta.text()
        assert etiqueta.wordWrap()
        icono = fila_objeto.findChild(QLabel, "localItemIcon")
        assert icono is not None and not icono.pixmap().isNull()
        if etiqueta.text() == "Recordatorio letal":
            assert "Situacional" in fila_objeto.toolTip()
            assert "curaciones altas" in fila_objeto.toolTip()
    titulos_categorias = dialogo.situational_card.findChildren(
        QLabel, "situationalCategoryTitle"
    )
    descripciones_categorias = dialogo.situational_card.findChildren(
        QLabel, "situationalCategoryDescription"
    )
    assert len(titulos_categorias) == 4
    assert len(descripciones_categorias) == 4
    assert all(etiqueta.text() for etiqueta in titulos_categorias)
    assert all(etiqueta.wordWrap() for etiqueta in descripciones_categorias)
    assert dialogo.summoners_row.count() == 2
    assert dialogo.starters_row.count() == 2
    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        dialogo.resize(ancho, alto)
        app.processEvents()
        assert dialogo.width() == ancho
        assert dialogo.core_title.size().width() > 0
        assert dialogo.situational_source_note.size().width() > 0
        assert dialogo.build_grid.itemAtPosition(1, 0).widget().size().width() > 0
        if ancho == 1600:
            dialogo._scroll_analisis.verticalScrollBar().setValue(
                dialogo._scroll_analisis.verticalScrollBar().maximum()
            )
            app.processEvents()
            dialogo.grab().save(str(tmp_path / "local-analysis.png"))
    dialogo.close()
    app.processEvents()
