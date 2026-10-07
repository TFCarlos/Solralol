"""Comprueba las correcciones de distribuciÃ³n en draft e interfaz en vivo."""

from __future__ import annotations

import os
from itertools import pairwise
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

pytest_plugins = [
    "app.scratch.test_carga_analisis_local",
    "app.scratch.test_draft_refinamiento",
]


def _jugador(indice: int, equipo: str, posicion: str = "UTILITY") -> dict:
    """Devuelve un jugador aislado con runas, inventario y marcador cero."""
    return {
        "championName": f"Campeon{indice}",
        "riotId": f"Identificador de jugador {indice} excesivamente largo#EUW123456",
        "team": equipo,
        "position": posicion,
        "level": 1 if indice == 0 else None,
        "scores": {"kills": 0, "deaths": 0, "assists": 0, "creepScore": 0},
        "items": [
            {"slot": ranura, "itemID": 1000 + ranura, "displayName": f"Objeto {ranura}"}
            for ranura in range(8)
        ],
        "runes": {
            "keystone": {"displayName": "Electrocute"},
            "primaryRuneTree": {"displayName": "Domination"},
            "secondaryRuneTree": {"displayName": "Precision"},
            "generalRunes": [
                {"displayName": "Electrocute"},
                {"displayName": "Cheap Shot"},
                {"displayName": "Taste of Blood"},
                {"displayName": "Sudden Impact"},
            ],
        },
        "summonerSpells": {
            "summonerSpellOne": {"displayName": "Flash"},
            "summonerSpellTwo": {"displayName": "Smite"},
        },
    }


@pytest.fixture(autouse=True)
def _iconos_sin_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evita lecturas de red o recursos externos en las vistas de prueba."""
    import app.ui.champion_card as tarjeta
    import app.ui.inventory as inventario

    monkeypatch.setattr(tarjeta, "champion_pixmap", lambda *args: tarjeta.QPixmap())
    monkeypatch.setattr(tarjeta, "rune_pixmap", lambda *args: tarjeta.QPixmap())
    monkeypatch.setattr(tarjeta, "spell_pixmap", lambda *args: tarjeta.QPixmap())
    monkeypatch.setattr(tarjeta, "get_champion_data", lambda *args: {})
    monkeypatch.setattr(
        tarjeta,
        "calculate_estimated_enemy_stats",
        lambda *args: {
            "hp": 1200,
            "ad": 80,
            "ap": 0,
            "armor": 50,
            "mr": 35,
            "crit": 0,
            "lethality": 0,
            "armor_pen_percent": 0,
            "life_steal_percent": 0,
            "grievous_wounds": False,
        },
    )
    monkeypatch.setattr(inventario, "get_item_icon_path", lambda *args: None)


def test_baneos_quedan_centrados_en_huecos_uniformes(
    herramienta,
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verifica el centrado geomÃ©trico de los diez huecos de baneo."""
    herramienta.resize(1280, 900)

    def pintar_icono(etiqueta: QLabel, *args: object, **kwargs: object) -> None:
        pixmap = QPixmap(24, 24)
        pixmap.fill(QColor("#b69a50"))
        etiqueta.setPixmap(pixmap)

    monkeypatch.setattr(herramienta._icon_cache, "assign", pintar_icono)
    for tarjetas, etiquetas, nombres, equipo in (
        (
            herramienta.my_header_ban_cards,
            herramienta.my_header_ban_labels,
            ("Ahri", "Lux", "Jinx"),
            "aliado",
        ),
        (
            herramienta.enemy_header_ban_cards,
            herramienta.enemy_header_ban_labels,
            ("Zed", "Yasuo"),
            "enemigo",
        ),
    ):
        for tarjeta, etiqueta, nombre in zip(tarjetas, etiquetas, nombres):
            herramienta._actualizar_slot_ban(tarjeta, etiqueta, nombre, equipo)
    herramienta.show()
    aplicacion.processEvents()
    slots = herramienta.my_header_ban_cards + herramienta.enemy_header_ban_cards
    assert len(slots) == 10
    assert {slot.size().toTuple() for slot in slots} == {(32, 32)}
    for slot, icono in zip(
        slots, herramienta.my_header_ban_labels + herramienta.enemy_header_ban_labels
    ):
        assert slot.rect().center() == icono.geometry().center()
    herramienta.grab().save(str(tmp_path / "draft_bans.png"))
    herramienta.close()


def test_build_botas_y_situacionales_no_se_solapan_ni_se_acumulan(
    herramienta,
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Comprueba botas separadas y limpieza de categorÃ­as con iconos largos."""
    herramienta.resize(1280, 900)
    herramienta.analyzer.get_situational_items = Mock(
        return_value=[
            {
                "label": f"CategorÃ­a {categoria}",
                "items": [
                    {"id": f"{categoria}{indice}", "name": f"Objeto {indice}"}
                    for indice in range(4)
                ],
            }
            for categoria in range(4)
        ]
    )

    def pintar_icono(etiqueta: QLabel, tipo: str, nombre: str, tamano: int) -> None:
        pixmap = QPixmap(tamano, tamano)
        pixmap.fill(QColor("#544326" if tipo == "item" else "#19202a"))
        etiqueta.setPixmap(pixmap)

    monkeypatch.setattr(herramienta, "_set_icon", pintar_icono)
    for indice, etiqueta in enumerate(herramienta.build_item_labels):
        pintar_icono(etiqueta, "item", str(indice + 1), 40)
    pintar_icono(herramienta.build_boots_label, "item", "3006", 40)
    herramienta._pintar_situacionales("Campeon")
    herramienta._pintar_situacionales("Campeon")
    aplicacion.processEvents()
    assert herramienta.situational_layout.count() == 4
    iconos = herramienta.situational_container.findChildren(QLabel, "importItemIcon")
    nombres = herramienta.situational_container.findChildren(
        QLabel, "situationalItemName"
    )
    assert len(iconos) == 16
    assert len(nombres) == 16
    assert all(nombre.text().startswith("Objeto ") for nombre in nombres)
    assert (
        herramienta.build_boots_label.parentWidget()
        is not herramienta.build_item_labels[0].parentWidget()
    )
    herramienta.show()
    aplicacion.processEvents()
    posicion_botas = herramienta.build_boots_label.mapTo(herramienta, QPoint(0, 0))
    geometria = QRect(posicion_botas, herramienta.build_boots_label.size())
    for icono in herramienta.build_item_labels:
        posicion = icono.mapTo(herramienta, QPoint(0, 0))
        assert not geometria.intersects(QRect(posicion, icono.size()))
    tarjeta_build = herramienta.build_boots_label.parentWidget().parentWidget()
    assert tarjeta_build.width() >= herramienta.build_boots_label.width()
    tarjeta_build.grab().save(str(tmp_path / "draft_build_situacionales.png"))
    herramienta.close()


def test_columnas_situacionales_se_refluyen_con_el_ancho(
    aplicacion: QApplication,
) -> None:
    """Comprueba cuatro, dos y una columna segÃºn el ancho del contenedor."""
    from app.ui.draft_tool_dialog import RejillaCategoriasSituacionales

    rejilla = RejillaCategoriasSituacionales()
    rejilla.establecer_columnas([QFrame() for _ in range(4)])
    assert rejilla.sizeHint().width() == 0
    for ancho, columnas in ((700, 4), (350, 2), (120, 1)):
        rejilla.resize(ancho, 200)
        rejilla.show()
        aplicacion.processEvents()
        assert rejilla._rejilla.itemAtPosition(0, columnas) is None
        if columnas < 4:
            assert rejilla._rejilla.itemAtPosition(1, 0) is not None
    rejilla.close()


def test_situacionales_ocultan_categorias_vacias_y_muestran_estado_neutro(
    herramienta,
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Omite categorÃ­as vacÃ­as y conserva un estado compacto sin recomendaciones."""
    herramienta.analyzer.get_situational_items = Mock(
        return_value=[
            {"label": "VacÃ­a", "items": []},
            {"label": "Activa", "items": [{"id": "1", "name": "Objeto"}]},
        ]
    )
    monkeypatch.setattr(
        herramienta,
        "_set_icon",
        lambda etiqueta, tipo, nombre, tamano: None,
    )
    herramienta._pintar_situacionales("Campeon")
    aplicacion.processEvents()
    assert herramienta.situational_layout.count() == 1
    titulos = herramienta.situational_container.findChildren(
        QLabel, "situationalCategoryTitle"
    )
    assert [titulo.text() for titulo in titulos] == ["ACTIVA"]

    herramienta.analyzer.get_situational_items.return_value = [
        {"label": "VacÃ­a", "items": []}
    ]
    herramienta._pintar_situacionales("Campeon")
    aplicacion.processEvents()
    estados = herramienta.situational_container.findChildren(QLabel)
    assert any(
        etiqueta.text() == "Sin objetos situacionales recomendados."
        for etiqueta in estados
    )
    herramienta.close()


def test_tarjetas_live_se_adaptan_y_conservan_identidad(
    aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Renderiza un 5v5 y comprueba alturas, elisiÃ³n e inventario adaptable."""
    from app.ui.champion_card import ChampionCard
    from app.ui.main_window import RejillaTarjetasEquipo

    aliadas = [
        ChampionCard(_jugador(indice, "ORDER"), indice == 0, {}, "test", 0, None)
        for indice in range(5)
    ]
    enemigas = [
        ChampionCard(_jugador(indice + 5, "CHAOS"), False, {}, "test", 0, None)
        for indice in range(5)
    ]
    contenedor = QWidget()
    paneles = QVBoxLayout(contenedor)
    rejilla = RejillaTarjetasEquipo(aliadas)
    rejilla_enemiga = RejillaTarjetasEquipo(enemigas)
    paneles.addWidget(rejilla)
    paneles.addWidget(rejilla_enemiga)
    contenedor.resize(1280, 1500)
    contenedor.show()
    aplicacion.processEvents()
    assert contenedor.width() >= 1280
    assert [rejilla.layout().getItemPosition(i)[1] for i in range(5)] == [0, 1, 2, 3, 4]
    aplicacion.processEvents()
    assert len({tarjeta.height() for tarjeta in aliadas}) == 1
    assert len({tarjeta.height() for tarjeta in enemigas}) == 1
    tarjetas = aliadas + enemigas
    aplicacion.processEvents()
    tarjeta = tarjetas[0]
    bloque_metricas = tarjeta.findChild(QFrame, "cardCombatStats")
    assert bloque_metricas is not None and bloque_metricas.height() >= 68
    kda = tarjeta.findChild(QLabel, "cardKDA")
    assert kda is not None and kda.text() == "0 / 0 / 0"
    etiqueta_id = tarjeta.findChild(QLabel, "cardPlayerId")
    assert etiqueta_id is not None and etiqueta_id.toolTip().startswith(
        "Identificador de jugador"
    )
    assert etiqueta_id.text() != etiqueta_id.toolTip()
    assert "NV 1" in [
        label.text() for label in tarjeta.findChildren(QLabel, "cardLevelBadge")
    ]
    inventario = tarjeta.findChild(QWidget, "cardInventory")
    assert inventario is not None
    assert len(tarjeta.findChildren(QLabel, "itemSlot")) == 6
    assert len(tarjeta.findChildren(QLabel, "trinketSlot")) == 1
    assert tarjeta.findChild(QFrame, "cardLoadout") is not None
    assert len(tarjeta.findChildren(QLabel, "cardSpellIcon")) == 2
    assert {
        icono.toolTip().removesuffix(" · recurso no disponible")
        for icono in tarjeta.findChildren(QLabel, "cardSpellIcon")
    } == {"Flash", "Smite"}
    assert all(
        icono.property("missing") is True
        for icono in tarjeta.findChildren(QLabel, "cardSpellIcon")
    )
    clave = tarjeta.findChild(QLabel, "cardRuneKeystoneIcon")
    assert clave is not None and clave.width() >= 26
    valores = tarjeta.findChildren(QLabel, "cardCombatValue")
    assert len(valores) == 6
    assert any("VIDA" in valor.text() for valor in valores)
    assert all("VIDA VIDA" not in valor.text() for valor in valores)
    assert all("ARM ARM" not in valor.text() for valor in valores)
    assert all("MR MR" not in valor.text() for valor in valores)
    assert all("AD AD" not in valor.text() for valor in valores)
    assert all(etiqueta.height() >= 20 for etiqueta in valores)
    runas = tarjeta.findChildren(QLabel, "cardRuneIcon")
    assert len(runas) == 3
    assert {
        runa.toolTip().removesuffix(" · icono no disponible") for runa in runas
    } >= {
        "Cheap Shot",
        "Taste of Blood",
        "Sudden Impact",
    }
    jugador_vacio = _jugador(20, "CHAOS", "TOP")
    jugador_vacio["items"] = []
    tarjeta_vacia = ChampionCard(jugador_vacio, False, {}, "test", 0, None)
    assert len(tarjeta_vacia.findChildren(QLabel, "emptyItemSlot")) == 7
    referencias_estables = (
        kda,
        tarjeta.findChild(QLabel, "cardPlayerId"),
        tarjeta.findChild(QLabel, "itemSlot"),
        tarjeta.findChild(QFrame, "cardLoadout"),
    )
    jugador_actualizado = _jugador(0, "ORDER")
    jugador_actualizado["scores"] = {
        "kills": 9,
        "deaths": 6,
        "assists": 3,
        "creepScore": 42,
    }
    jugador_actualizado["items"][0]["itemID"] = 9999
    tarjeta.actualizar_datos(jugador_actualizado, 60, None)
    aplicacion.processEvents()
    assert tarjeta is aliadas[0]
    assert len(tarjeta.findChildren(QLabel, "cardChampionName")) == 1
    assert tarjeta.findChild(QLabel, "cardKDA") is referencias_estables[0]
    assert tarjeta.findChild(QLabel, "cardKDA").text() == "9 / 6 / 3"
    assert tarjeta.findChild(QLabel, "cardPlayerId") is referencias_estables[1]
    assert tarjeta.findChild(QLabel, "itemSlot") is referencias_estables[2]
    assert tarjeta.findChild(QFrame, "cardLoadout") is referencias_estables[3]
    assert 270 <= tarjeta.height() <= 560
    geometries = [
        tarjeta.layout().itemAt(indice).geometry()
        for indice in range(tarjeta.layout().count())
    ]
    assert all(geometria.top() >= 0 for geometria in geometries)
    assert all(geometria.bottom() < tarjeta.height() for geometria in geometries)
    assert all(
        actual.top() > anterior.bottom() for anterior, actual in pairwise(geometries)
    ), (
        [geometria.getRect() for geometria in geometries],
        tarjeta.layout().spacing(),
        tarjeta.layout().contentsMargins(),
        tarjeta.contentsRect().getRect(),
        tarjeta.frameWidth(),
    )
    assert all(
        etiqueta.width() >= 26
        for etiqueta in tarjeta.findChildren(QLabel, "cardSpellIcon")
    )
    assert all(
        etiqueta.width() >= 24 for etiqueta in tarjeta.findChildren(QLabel, "itemSlot")
    )
    assert all(
        etiqueta.width() >= 24
        for etiqueta in tarjeta.findChildren(QLabel, "trinketSlot")
    )
    assert len({jugador.height() for jugador in aliadas}) == 1
    captura_ancha = contenedor.grab()
    assert not captura_ancha.isNull()
    captura_ancha.save(str(tmp_path / "live_5v5_ancho.png"))
    contenedor.resize(760, 1500)
    aplicacion.processEvents()
    assert contenedor.width() <= 760
    assert max(rejilla.layout().getItemPosition(i)[1] for i in range(5)) <= 2
    filas_live = {
        rejilla.layout().getItemPosition(i)[0]: rejilla.layout()
        .itemAt(i)
        .widget()
        .geometry()
        for i in range(rejilla.layout().count())
    }
    assert len(filas_live) >= 2
    assert all(
        filas_live[fila + 1].top() >= filas_live[fila].bottom()
        for fila in range(len(filas_live) - 1)
    )
    captura = contenedor.grab()
    assert not captura.isNull()
    captura.save(str(tmp_path / "live_5v5.png"))
    contenedor.close()


def test_nivel_ausente_se_muestra_como_no_disponible(aplicacion: QApplication) -> None:
    """Evita presentar nivel cero cuando Live Client Data no lo informa."""
    from app.ui.champion_card import ChampionCard

    tarjeta = ChampionCard(_jugador(1, "CHAOS"), False, {}, "test", 0, None)
    etiqueta = tarjeta.findChild(QLabel, "cardLevelBadge")
    assert etiqueta is not None and etiqueta.text().startswith("NV ")
    assert not any(caracter.isdigit() for caracter in etiqueta.text())
    assert etiqueta.toolTip() == "Nivel no disponible"


def test_nivel_local_usa_active_player_si_el_roster_no_lo_informa(
    aplicacion: QApplication,
) -> None:
    """Muestra el nivel activo observado cuando falta en la fila del jugador."""
    from app.ui.champion_card import ChampionCard

    jugador = _jugador(0, "ORDER")
    jugador["level"] = None
    tarjeta = ChampionCard(
        jugador, True, {}, "test", 0, {"level": 15, "currentGold": 1000}
    )
    nivel = tarjeta.findChild(QLabel, "cardLevelBadge")
    kda = tarjeta.findChild(QLabel, "cardKDA")
    yo = tarjeta.findChild(QLabel, "cardMeBadge")
    assert nivel is not None and nivel.text() == "NV 15"
    assert kda is not None and kda.text() == "0 / 0 / 0"
    assert yo is not None and yo.text() == "TÚ"


def test_iconos_live_se_reescalan_al_cambiar_el_tamano_de_tarjeta(
    aplicacion: QApplication,
) -> None:
    """Reescala loadout e inventario al crecer y reducir la tarjeta."""
    from app.ui.champion_card import ChampionCard

    tarjeta = ChampionCard(_jugador(0, "ORDER"), True, {}, "test", 0, None)
    tarjeta.resize(400, 500)
    tarjeta.show()
    aplicacion.processEvents()
    assert tarjeta.findChild(QLabel, "cardSpellIcon").width() == 32
    assert tarjeta.findChild(QLabel, "cardRuneKeystoneIcon").width() == 32
    assert tarjeta.findChild(QLabel, "cardRuneIcon").width() == 24
    assert tarjeta.findChild(QLabel, "itemSlot").width() == 32
    tarjeta.resize(260, 280)
    aplicacion.processEvents()
    assert tarjeta.findChild(QLabel, "cardSpellIcon").width() == 26
    assert tarjeta.findChild(QLabel, "cardRuneKeystoneIcon").width() == 26
    assert tarjeta.findChild(QLabel, "cardRuneIcon").width() == 20
    assert tarjeta.findChild(QLabel, "itemSlot").width() == 24
    tarjeta.close()


def test_nivel_live_conserva_tipografia_compacta_con_tema_global(
    aplicacion: QApplication,
) -> None:
    """Evita que la clasificación automática agrande o envuelva el nivel LIVE."""
    from app.ui.champion_card import ChampionCard
    from app.ui.tema import preparar_componente

    tarjeta = ChampionCard(_jugador(0, "ORDER"), True, {}, "test", 0, None)
    nivel = tarjeta.findChild(QLabel, "cardLevelBadge")
    assert nivel is not None
    preparar_componente(nivel)
    assert nivel.property("nivel") == "live_badge"
    assert not nivel.wordWrap()
    assert nivel.text() == "NV 1"
    tarjeta.close()


def test_loadout_alinea_iconos_sin_relleno_ni_margen_superfluo(
    aplicacion: QApplication,
) -> None:
    """Mantiene los iconos completos y juntos en una fila visible."""
    from app.ui.champion_card import ChampionCard
    from app.ui.tema import instalar_sistema_visual

    instalar_sistema_visual(aplicacion)
    jugador = _jugador(2, "ORDER")
    jugador["summonerSpells"] = {
        "summonerSpellOne": {"displayName": "Flash"},
        "summonerSpellTwo": {"displayName": "Teleport"},
    }
    tarjeta = ChampionCard(jugador, False, {}, "test", 0, None)
    tarjeta.resize(330, 360)
    tarjeta.show()
    aplicacion.processEvents()
    hechizos = tarjeta.findChildren(QLabel, "cardSpellIcon")
    clave = tarjeta.findChild(QLabel, "cardRuneKeystoneIcon")
    runa = tarjeta.findChild(QLabel, "cardRuneIcon")
    assert len(hechizos) == 2
    assert clave is not None and runa is not None
    assert all(icon.contentsMargins().left() == 2 for icon in hechizos)
    assert all(
        icon.pixmap().size() == icon.contentsRect().size()
        for icon in hechizos
        if icon.pixmap() is not None and not icon.pixmap().isNull()
    )
    assert tarjeta._loadout_layout.contentsMargins().left() == 0
    assert tarjeta._loadout_layout.spacing() == 1
    assert tarjeta._loadout_layout.itemAt(0).widget().geometry().left() < 8
    tarjeta.close()


def test_componente_icono_conserva_fuente_y_la_encaja_en_su_area(
    aplicacion: QApplication,
) -> None:
    """Conserva la fuente original al pintar tamaños distintos con Qt."""
    from app.ui.icono_pixmap import IconoPixmap

    icono = IconoPixmap()
    fuente = QPixmap(48, 48)
    fuente.fill(QColor("#b69a50"))
    icono.setFixedSize(32, 32)
    icono.establecer_pixmap_fuente(fuente)
    icono.show()
    aplicacion.processEvents()
    assert icono.obtener_pixmap_fuente().size().toTuple() == (48, 48)
    assert icono.pixmap().width() <= 32
    assert icono.pixmap().width() <= icono.contentsRect().width()
    icono.setFixedSize(20, 20)
    aplicacion.processEvents()
    assert icono.obtener_pixmap_fuente().size().toTuple() == (48, 48)
    assert icono.pixmap().width() <= 20
    icono.close()


def test_metricas_e_inventario_ausentes_se_muestran_como_no_disponibles(
    aplicacion: QApplication,
) -> None:
    """Mantiene vacÃ­os los datos ausentes en vez de presentarlos como cero."""
    from app.ui.champion_card import ChampionCard

    jugador = _jugador(1, "CHAOS")
    jugador.pop("items")
    jugador["scores"] = {}
    tarjeta = ChampionCard(jugador, False, {}, "test", 0, None)
    valores = tarjeta.findChildren(QLabel, "cardCombatValue")
    conteo = tarjeta.findChild(QLabel, "cardInventoryCount")
    kda = tarjeta.findChild(QLabel, "cardKDA")
    assert len(valores) == 6
    assert kda is not None and kda.text().count("/") == 2
    assert kda.text().count("/") == 2
    assert not any(caracter.isdigit() for caracter in kda.text())
    assert conteo is not None and conteo.text() == "Sin datos"


def test_game_service_conserva_nivel_de_active_player_en_stats_locales() -> None:
    """Incluye el nivel observado del jugador activo en la instantánea local."""
    from app.services.game_service import GameService

    servicio = GameService()
    servicio.request_data = Mock(
        side_effect=[
            {
                "gameData": {"gameTime": 60, "gameMode": "CLASSIC"},
                "activePlayer": {
                    "summonerName": "Local",
                    "level": 15,
                    "championStats": {"currentHealth": 1000},
                },
                "allPlayers": [
                    {
                        "summonerName": "Local",
                        "championName": "Briar",
                        "team": "ORDER",
                        "level": None,
                    }
                ],
            },
            {"Events": []},
        ]
    )
    instantanea = servicio.get_game_snapshot()

    assert instantanea is not None
    assert instantanea["local_live_stats"]["level"] == 15


def test_refresco_del_mismo_roster_conserva_tarjetas_sin_duplicar(
    aplicacion: QApplication,
) -> None:
    """Actualiza las mismas diez tarjetas mientras se mantiene el roster."""
    from app.ui.main_window import MainWindow

    ventana = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(ventana)
    ventana.item_catalog = {}
    ventana.version = "test"
    ventana.cards_widget = QWidget()
    ventana.cards_layout = QVBoxLayout(ventana.cards_widget)
    ventana.live_empty_label = QLabel()
    ventana.live_team_cards = {}
    ventana.live_team_summaries = {}
    ventana.live_team_signatures = {}
    ventana.live_team_order = ()
    jugadores = [_jugador(i, "ORDER") for i in range(5)] + [
        _jugador(i + 5, "CHAOS") for i in range(5)
    ]
    instantanea = {
        "all_players": jugadores,
        "local_team": "ORDER",
        "local_player": jugadores[0],
        "game_time": 30,
        "local_live_stats": None,
    }
    ventana.rebuild_cards(instantanea)
    tarjetas_iniciales = tuple(
        tarjeta
        for equipo in ("ORDER", "CHAOS")
        for tarjeta in ventana.live_team_cards[equipo]
    )
    assert ventana.cards_layout.count() == 2
    instantanea["game_time"] = 60
    ventana.rebuild_cards(instantanea)
    tarjetas_actualizadas = tuple(
        tarjeta
        for equipo in ("ORDER", "CHAOS")
        for tarjeta in ventana.live_team_cards[equipo]
    )
    assert tarjetas_actualizadas == tarjetas_iniciales
    assert ventana.cards_layout.count() == 2
    assert all(tarjeta.game_time == 60 for tarjeta in tarjetas_actualizadas)
    ventana.cards_widget.resize(1500, 1000)
    ventana.cards_widget.show()
    aplicacion.processEvents()
    for indice in range(2):
        panel = ventana.cards_layout.itemAt(indice).widget()
        assert panel is not None
        assert 440 <= panel.height() <= 580
        equipo = panel.layout()
        assert equipo is not None
        encabezado = equipo.itemAt(0).layout()
        fila = equipo.itemAt(1).widget()
        assert encabezado is not None and fila is not None
        assert fila.y() - encabezado.geometry().bottom() <= 18
        assert panel.height() - (fila.y() + fila.height()) <= 24
    for ancho, alto in ((1100, 590), (1340, 720), (1660, 900), (2300, 1240)):
        ventana.cards_widget.resize(ancho, alto)
        aplicacion.processEvents()
        paneles = [ventana.cards_layout.itemAt(i).widget() for i in range(2)]
        assert all(panel is not None for panel in paneles)
        alturas = [panel.height() for panel in paneles]
        assert abs(alturas[0] - alturas[1]) <= 2
        assert paneles[1].geometry().bottom() >= alto - 12
        filas = [panel.layout().itemAt(1).widget() for panel in paneles]
        assert all(250 <= fila.height() <= 570 for fila in filas)
        if ancho >= 1100:
            rejillas = [fila.layout() for fila in filas]
            assert all(rejilla.columnCount() == 5 for rejilla in rejillas)
        assert all(
            fila.y() - panel.layout().itemAt(0).layout().geometry().bottom() <= 18
            for panel, fila in zip(paneles, filas)
        )
    jugadores[0]["scores"] = {}
    resumen = ventana.format_team_summary(jugadores[:5])
    assert "ASESINATOS" in resumen
    assert not resumen.startswith("0 ASESINATOS")
    ventana.hide()
    ventana.deleteLater()
