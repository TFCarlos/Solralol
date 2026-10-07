"""Pruebas de la herramienta de draft: bans, selectores, páginas de runas e importación."""

from __future__ import annotations

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.rangos_campeones import RANGO_PREDETERMINADO
from app.ui.draft_tool_dialog import DraftToolDialog

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


@pytest.fixture
def herramienta(
    aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch
) -> DraftToolDialog:
    """Construye la herramienta sin red en iconos ni conexión LCU."""
    monkeypatch.setattr(DraftToolDialog, "_check_lcu_status", Mock())
    return DraftToolDialog()


def _sesion_baneos(aliados: list[int], enemigos: list[int]) -> dict[str, object]:
    """Devuelve una sesión LCU mínima con los baneos recibidos en orden."""
    acciones = [
        {
            "type": "ban",
            "championId": identificador,
            "actorCellId": indice,
            "isAllyAction": True,
        }
        for indice, identificador in enumerate(aliados)
    ]
    acciones += [
        {
            "type": "ban",
            "championId": identificador,
            "actorCellId": 100 + indice,
            "isAllyAction": False,
        }
        for indice, identificador in enumerate(enemigos)
    ]
    return {
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": indice} for indice in range(5)],
        "theirTeam": [{"cellId": 100 + indice} for indice in range(5)],
        "actions": [acciones],
    }


def test_bans_diez_huecos_y_sin_guiones(herramienta: DraftToolDialog) -> None:
    """Hay diez huecos explícitos por equipo, sin guiones ni líneas decorativas."""
    assert len(herramienta.my_header_ban_cards) == 5
    assert len(herramienta.enemy_header_ban_cards) == 5
    tarjetas = herramienta.my_header_ban_cards + herramienta.enemy_header_ban_cards
    assert all(t.property("equipo") in ("aliado", "enemigo") for t in tarjetas)
    assert all("—" not in t.toolTip() and "_" not in t.toolTip() for t in tarjetas)


def test_bans_lcu_pueblan_huecos_y_manual_limpia(
    herramienta: DraftToolDialog,
) -> None:
    """Los bans reales llenan los huecos en orden; al salir quedan vacíos."""
    herramienta.analyzer.champ_by_id.update({1: "Annie", 2: "Ashe"})
    herramienta.update_from_lcu_session(_sesion_baneos([1], [2]))
    aliado = herramienta.my_header_ban_cards[0]
    rival = herramienta.enemy_header_ban_cards[0]
    assert "Annie" in aliado.toolTip()
    assert "Ashe" in rival.toolTip()
    assert aliado.property("ocupado") is True
    assert herramienta.my_header_ban_cards[1].property("ocupado") is False
    herramienta._limpiar_bans_header()
    assert all(
        t.property("ocupado") is False
        for t in (herramienta.my_header_ban_cards + herramienta.enemy_header_ban_cards)
    )


def test_selectores_linea_legibles(
    herramienta: DraftToolDialog, aplicacion: QApplication
) -> None:
    """Los selectores de línea muestran el nombre completo sin recortes."""
    combos = herramienta.my_team_role_combos
    assert len(combos) == 5
    herramienta.resize(1500, 920)
    herramienta.show()
    for _ in range(5):
        aplicacion.processEvents()
    for combo in combos:
        assert combo.minimumWidth() >= 96
        assert combo.width() >= combo.minimumWidth()
        assert len(combo.currentText()) > 1
    herramienta.close()


def test_sin_linea_vertical_entre_equipos(herramienta: DraftToolDialog) -> None:
    """No queda ningún separador vertical dibujado entre las composiciones."""
    from PySide6.QtWidgets import QFrame

    lineas = [
        marco
        for marco in herramienta.findChildren(QFrame)
        if marco.frameShape() == QFrame.Shape.VLine
    ]
    assert not lineas


def test_wr_sin_borde_y_con_color(
    herramienta: DraftToolDialog, aplicacion: QApplication
) -> None:
    """El WR se muestra como texto coloreado, sin borde lateral heredado."""
    from app.ui.sistema_visual import PALETA

    herramienta.my_team_combo_widgets[0].setCurrentText("Aatrox")
    herramienta._update_analytics()
    etiqueta = herramienta.my_team_matchup_labels[0]
    assert "%" in etiqueta.text()
    assert etiqueta.property("estado") in ("exito", "error", "normal")
    etiqueta.show()
    for _ in range(3):
        aplicacion.processEvents()
    imagen = etiqueta.grab().toImage()
    borde = {
        imagen.pixelColor(0, y).name()
        for y in range(imagen.height())
        if imagen.pixelColor(0, y).alpha() > 0
    }
    assert PALETA["ventaja"] not in borde
    assert PALETA["desventaja"] not in borde


def test_paginas_runas_desde_datos_locales(herramienta: DraftToolDialog) -> None:
    """Las dos páginas salen de la variante local del contexto y nada de red."""
    herramienta.local_role_combo.setCurrentText("Top")
    herramienta.my_team_combo_widgets[0].setCurrentText("Aatrox")
    herramienta._update_analytics()
    assert set(herramienta.rune_page_rows) == {1, 2}
    assert len(herramienta._datos_importacion.get("paginas", [])) == 2
    assert herramienta._contexto_activo == ("Aatrox", "top", RANGO_PREDETERMINADO)
    assert herramienta._pagina_runas_activa in (1, 2)


def test_seleccion_pagina_actualiza_build_y_resetea(
    herramienta: DraftToolDialog,
) -> None:
    """Cambiar de página actualiza la build asociada e invalida el estado previo."""
    herramienta.local_role_combo.setCurrentText("Top")
    herramienta.my_team_combo_widgets[0].setCurrentText("Aatrox")
    herramienta._update_analytics()
    herramienta._seleccionar_pagina_runas(2)
    assert herramienta._pagina_runas_activa == 2
    assert herramienta.rune_page_rows[2]["card"].property("seleccionado") is True
    assert herramienta.rune_page_rows[1]["card"].property("seleccionado") is False
    assert herramienta.rune_page_rows[2]["check"].isVisibleTo(
        herramienta.rune_page_rows[2]["card"]
    )
    build = herramienta._datos_importacion.get("build")
    assert build and len(build["items"]) == 6
    assert herramienta.btn_import_build_runes.text() == "↓  Importar build + runas"
    herramienta._seleccionar_pagina_runas(1)
    assert herramienta._pagina_runas_activa == 1


def test_datos_ausentes_con_mensaje_claro(
    herramienta: DraftToolDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin variante local hay mensaje explicativo y acciones desactivadas."""
    from app.services.repositorio_campeones import ConsultaCampeon, EstadoDatos

    monkeypatch.setattr(
        herramienta._repositorio_local,
        "consultar",
        lambda *a, **k: ConsultaCampeon(EstadoDatos.SIN_DATOS_LOCALES),
    )
    herramienta.local_role_combo.setCurrentText("Top")
    herramienta.my_team_combo_widgets[0].setCurrentText("Aatrox")
    herramienta._contexto_activo = ("otro", "top", RANGO_PREDETERMINADO)
    herramienta._update_analytics()
    assert herramienta._datos_importacion == {}
    assert "No hay datos locales" in herramienta.import_status.text()
    assert "Análisis" in herramienta.import_status.text()
    assert not herramienta.btn_import_build_runes.isEnabled()
    assert not herramienta.btn_import_spells.isEnabled()


def test_normalizar_hechizos() -> None:
    """Las reglas de hechizos por línea se conservan tras la extracción."""
    from app.services.draft_analyzer_service import DraftAnalyzerService

    assert DraftAnalyzerService.normalizar_hechizos(
        ["Destello", "Aplastar"], "Top"
    ) == ("Destello", "Teleportación")
    assert DraftAnalyzerService.normalizar_hechizos(
        ["Destello", "Ignición"], "Jungle"
    ) == ("Destello", "Aplastar")
    assert DraftAnalyzerService.normalizar_hechizos(None, "Bot") == (
        "Destello",
        "Curación",
    )
