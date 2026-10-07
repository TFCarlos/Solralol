"""Regresi?n de bordes, h?roe compacto y contenci?n con texto variable."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QLabel, QTableWidgetItem

from app.ui.contenedores_analisis import TablaRecomendaciones
from app.ui.local_analysis_dialog import LocalAnalysisDialog
from app.ui.sistema_visual import PALETA

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


@pytest.fixture(autouse=True)
def fuentes(aplicacion: QApplication) -> None:
    """Carga fuentes reales para medir texto en Qt sin pantalla."""
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeuib.ttf")


@pytest.mark.parametrize("ancho", [916, 1500, 1920])
def test_contencion_con_textos_largos(
    dialogo: LocalAnalysisDialog, perfil: dict, aplicacion: QApplication, ancho: int
) -> None:
    """Verifica filas completas, resumen interior y ajuste natural a tres anchuras."""
    dialogo._datos_preparados["recomendaciones"] = [
        SimpleNamespace(
            name="Objeto con nombre largo y descripci?n de su funci?n defensiva",
            score=75.2,
            item_id="1",
            reasons=["Recomendaci?n explicada para decisiones frente al rival. " * 12],
        )
        for _ in range(12)
    ]
    dialogo._renderizar_analisis(perfil)
    for disposicion in (dialogo.counters_cards_layout, dialogo.good_cards_layout):
        dialogo._clear_layout(disposicion)
        for _ in range(5):
            disposicion.addWidget(
                dialogo._create_matchup_card(
                    "Campe?n con un nombre especialmente largo",
                    0.47,
                    0.51,
                    "Informaci?n ?til del enfrentamiento",
                    True,
                    1234567,
                    2345678,
                    "top",
                )
            )
    dialogo.matchup_status.setText(
        "Resumen de la l?nea seleccionada y del rango. " * 12
    )
    dialogo._mostrar_contenido(True)
    dialogo.resize(ancho, 1000)
    dialogo.show()
    for _ in range(20):
        aplicacion.processEvents()
    assert dialogo._scroll_analisis.horizontalScrollBar().maximum() == 0
    for tarjeta in (dialogo.matchups_panel, dialogo.recommendations_panel):
        assert tarjeta.minimumHeight() == 0
        assert tarjeta.maximumHeight() > 100000
        for etiqueta in tarjeta.findChildren(QLabel):
            origen = etiqueta.mapTo(tarjeta, QPoint())
            assert origen.x() >= 0 and origen.y() >= 0
            assert origen.y() + etiqueta.height() <= tarjeta.height()
            assert origen.x() + etiqueta.width() <= tarjeta.width()
    assert dialogo.matchup_status.parentWidget() is dialogo.matchups_panel
    assert dialogo.matchup_status.wordWrap()
    tabla = dialogo.item_table
    assert tabla.wordWrap() and tabla.rowCount() == 12
    assert tabla.verticalScrollBar().maximum() == 0
    assert tabla.rowHeight(0) > 44
    assert tabla.verticalHeader().length() <= tabla.viewport().height()
    alto = tabla.sizeHint().height()
    tabla.setRowCount(1)
    tabla.ajustar_contenido()
    assert tabla.sizeHint().height() < alto
    tabla.programar_orden()
    assert tabla.ajuste.isActive()
    tabla.programar_ajuste(0, 200, 180)
    assert tabla.ajuste.isActive()


def test_hero_compacto_y_bordes(
    dialogo: LocalAnalysisDialog, perfil: dict, aplicacion: QApplication
) -> None:
    """Verifica m?tricas pr?ximas al t?tulo, acciones centradas y borde compartido."""
    dialogo._renderizar_analisis(perfil)
    dialogo._mostrar_contenido(True)
    dialogo.resize(1500, 1000)
    dialogo.show()
    for _ in range(10):
        aplicacion.processEvents()
    hero = dialogo.champion_banner
    assert hero.minimumHeight() == 0
    assert hero.height() < 242
    assert dialogo.champion_winrate.y() < dialogo.champion_meta.y()
    assert dialogo.champion_lane.y() == dialogo.champion_winrate.y()
    assert hero.rect().contains(dialogo.update_single_champ_btn.geometry())
    assert hero.rect().contains(dialogo.update_winrates_btn.geometry())
    for tarjeta in (
        dialogo.summoners_card,
        dialogo.starters_card,
        dialogo.core_overview_card,
    ):
        assert tarjeta.layout().contentsMargins().left() == 20
        assert tarjeta.layout().spacing() == 12
        imagen = tarjeta.grab().toImage()
        esperado = PALETA["oro_oscuro"]
        assert imagen.pixelColor(imagen.width() // 2, 0).name() == esperado
        assert (
            imagen.pixelColor(imagen.width() // 2, imagen.height() - 1).name()
            == esperado
        )
        assert imagen.pixelColor(0, imagen.height() // 2).name() == esperado
        assert (
            imagen.pixelColor(imagen.width() - 1, imagen.height() // 2).name()
            == esperado
        )


def test_orden_y_redimensionado_de_recomendaciones(aplicacion: QApplication) -> None:
    """Comprueba que ordenar y reducir el ancho conserva motivos completos."""
    tabla = TablaRecomendaciones()
    tabla.setWordWrap(True)
    tabla.setRowCount(2)
    tabla.setItem(0, 0, QTableWidgetItem("Z"))
    tabla.setItem(
        0, 2, QTableWidgetItem("Motivo muy extenso que debe permanecer visible. " * 15)
    )
    tabla.setItem(1, 0, QTableWidgetItem("A"))
    tabla.setItem(1, 2, QTableWidgetItem("Breve"))
    tabla.setColumnWidth(2, 500)
    tabla.resize(850, 1000)
    tabla.show()
    for _ in range(10):
        aplicacion.processEvents()
    alto = tabla.rowHeight(0)
    tabla.sortItems(0, Qt.SortOrder.AscendingOrder)
    for _ in range(10):
        aplicacion.processEvents()
    assert tabla.item(1, 0).text() == "Z"
    assert tabla.rowHeight(1) > tabla.rowHeight(0)
    tabla.setColumnWidth(2, 200)
    tabla.resize(550, 1000)
    for _ in range(10):
        aplicacion.processEvents()
    assert tabla.rowHeight(1) > alto
    tabla.close()
