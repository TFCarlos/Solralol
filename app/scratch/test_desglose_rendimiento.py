"""Smoke tests offscreen del marcador y el desglose de rendimiento."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QProgressBar, QPushButton
from pytest import MonkeyPatch

from app.services.servicio_puntuacion_rendimiento import (
    EntradaRendimientoJugador,
    puntuar_jugador,
)
from app.ui.desglose_rendimiento_dialogo import DialogoDesgloseRendimiento
from app.ui.postgame_sidebar import PostgameSidebar


def test_marcador_y_desglose_grafico_se_pintan_offscreen(
    monkeypatch: MonkeyPatch,
) -> None:
    """Construye diez tarjetas y verifica cinco barras con excedente visible."""
    aplicacion = QApplication.instance() or QApplication([])
    jugadores = {
        f"p{indice}": {
            "champion_name": f"Champ{indice}",
            "role": ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")[indice % 5],
            "team": "blue" if indice < 5 else "red",
        }
        for indice in range(10)
    }
    puntos = {
        f"p{indice}": {
            "kills": 1,
            "deaths": 2,
            "assists": 3,
            "cs": 80,
            "estimated_gold": 5000,
            "level": 12,
        }
        for indice in range(10)
    }
    sesion = {
        "players": jugadores,
        "snapshots": [{"time": 900, "players": puntos}],
        "duration": 900,
        "winning_team": "blue",
        "local_player_key": "p0",
    }
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    sidebar = PostgameSidebar(sesion)
    assert len(sidebar.performance_scores["players"]) == 10
    assert sidebar.ally_column.findChildren(QPushButton, "postgamePerformanceScore")

    resultado = puntuar_jugador(
        EntradaRendimientoJugador(
            "p",
            "Campeon",
            "blue",
            "TOP",
            {
                "kills": 20,
                "deaths": 0,
                "assists": 0,
                "team_kills": 20,
                "damage_champions": 100000,
                "team_damage_champions": 100000,
            },
        ),
        900,
    )
    resultado["categories"]["economia"]["final"] = 150
    resultado["categories"]["objetivos"]["final"] = 125
    resultado["categories"]["vision"]["final"] = 180
    resultado.update(
        {
            "champion": "Jinx",
            "riot_id": "Marqq#BLACK",
            "global_rank": 3,
            "awards": ["SVP"],
            "awards_finalized": True,
            "finalization_state": "POSTGAME_FINAL",
        }
    )
    dialogos = []

    def capturar_dialogo(dialogo: QDialog) -> int:
        """Captura el diálogo real sin bloquear el test con su loop modal."""
        dialogos.append(dialogo)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", capturar_dialogo)
    sidebar._show_performance_breakdown(resultado)
    dialogos[0].show()
    aplicacion.processEvents()

    barras = dialogos[0].findChildren(QProgressBar)
    assert len(barras) == 5
    assert all(barra.format() == "" for barra in barras)
    porcentajes = dialogos[0].findChildren(QLabel, "performancePercentage")
    assert len(porcentajes) == 5
    assert float(dialogos[0].porcentajes["combate"].text().removesuffix("%")) > 100
    assert dialogos[0].porcentajes["economia"].text() == "100.0%"
    assert dialogos[0].porcentajes["objetivos"].text() == "50.0%"
    assert dialogos[0].porcentajes["vision"].text() == "120.0%"
    assert dialogos[0].barras["objetivos"].value() == 50
    assert dialogos[0].barras["vision"].value() == 100
    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        dialogos[0].resize(ancho, alto)
        aplicacion.processEvents()
        assert all(not tarjeta.isHidden() for tarjeta in dialogos[0].tarjetas.values())
        assert dialogos[0].scroll_area.verticalScrollBar().maximum() == 0
        assert dialogos[0].scroll_area.horizontalScrollBar().maximum() == 0
        assert dialogos[0].findChild(QLabel, "performanceAwardValue").isVisible()
        assert dialogos[0].findChild(QLabel, "performanceAwardValue").text() == "SVP"
        assert dialogos[0].findChild(QPushButton, "performanceCloseButton").isVisible()
    dialogos[0].resize(460, 420)
    aplicacion.processEvents()
    combatida = dialogos[0].tarjetas["combate"]
    economia = dialogos[0].tarjetas["economia"]
    combatida_altura = combatida.height()
    economia_altura = economia.height()
    dialogos[0].botones_detalle["combate"].click()
    aplicacion.processEvents()
    assert combatida.height() > combatida_altura
    assert economia.height() == economia_altura
    assert dialogos[0].scroll_area.verticalScrollBar().maximum() > 0
    assert (
        dialogos[0].scroll_area.verticalScrollBar().value()
        <= dialogos[0].scroll_area.verticalScrollBar().maximum()
    )
    dialogos[0].botones_detalle["economia"].click()
    aplicacion.processEvents()
    assert dialogos[0].botones_detalle["combate"].isChecked()
    assert dialogos[0].botones_detalle["economia"].isChecked()
    dialogos[0].botones_detalle["combate"].click()
    aplicacion.processEvents()
    assert combatida.height() == combatida_altura
    assert (
        dialogos[0].scroll_area.verticalScrollBar().value()
        <= dialogos[0].scroll_area.verticalScrollBar().maximum()
    )
    assert dialogos[0].botones_detalle["economia"].isChecked()
    assert dialogos[0].findChild(QLabel, "performancePlayerName") is not None
    assert (
        dialogos[0].findChild(QLabel, "performancePlayerName").text() == "Marqq#BLACK"
    )
    assert dialogos[0].findChild(QLabel, "performanceChampionName").text() == "Jinx"
    assert dialogos[0].findChild(QLabel, "performanceTotal") is not None
    assert len(dialogos[0].findChildren(QPushButton, "performanceDetailsButton")) == 5
    boton_detalle = dialogos[0].findChildren(QPushButton, "performanceDetailsButton")[0]
    boton_detalle.click()
    assert boton_detalle.isChecked()
    assert dialogos[0].scroll_area is not None
    assert dialogos[0].botones_detalle["combate"].height() >= 30
    etiquetas_combate = [
        etiqueta.text()
        for etiqueta in dialogos[0].detalles["combate"].findChildren(QLabel)
    ]
    titulo_contribucion = "CONTRIBUCI\u00d3N AL RENDIMIENTO"
    titulo_calculo = "C\u00c1LCULO DE PUNTUACI\u00d3N"
    assert etiquetas_combate.index(titulo_contribucion) < etiquetas_combate.index(
        titulo_calculo
    )
    assert etiquetas_combate.index("Bajas y asistencias") < etiquetas_combate.index(
        titulo_calculo
    )
    dialogos[0].botones_detalle["objetivos"].click()
    assert any(
        etiqueta.text() == "Da\u00f1o a objetivos"
        for etiqueta in dialogos[0].detalles["objetivos"].findChildren(QLabel)
    )
    assert any(
        etiqueta.text() == "No disponible"
        for etiqueta in dialogos[0].detalles["objetivos"].findChildren(QLabel)
    )
    for categoria in ("combate", "economia", "objetivos", "vision", "supervivencia"):
        control = dialogos[0].botones_detalle[categoria]
        if not control.isChecked():
            control.click()
        aplicacion.processEvents()
        assert control.isChecked()
        assert dialogos[0].detalles[categoria].isVisible()
        control.click()
        aplicacion.processEvents()
        assert not control.isChecked()
    assert all(barra.property("category") for barra in barras)
    dialogos[0].close()
    sidebar.close()
    aplicacion.processEvents()


def test_desglose_muestra_dano_objetivos_medido_cero_y_ausente() -> None:
    """Verifica las tres presentaciones de daño épico en el diálogo Qt."""
    aplicacion = QApplication.instance() or QApplication([])
    textos = []
    for dano in (9000, 0, None):
        datos = {} if dano is None else {"damage_objectives": dano}
        resultado = puntuar_jugador(
            EntradaRendimientoJugador("p", "Briar", "blue", "JUNGLE", datos),
            1800,
            "postgame",
        )
        dialogo = DialogoDesgloseRendimiento(resultado)
        dialogo.botones_detalle["objetivos"].click()
        aplicacion.processEvents()
        valores = dialogo.detalles["objetivos"].findChildren(
            QLabel, "performanceMetricValue"
        )
        textos.append([etiqueta.text() for etiqueta in valores])
        dialogo.close()
    assert "75.0 p" in textos[0]
    assert "0.0 p" in textos[1]
    assert "No disponible" in textos[2]
