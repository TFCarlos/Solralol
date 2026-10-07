"""Pruebas del rediseño y navegación sin servicios externos."""

import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QWidget,
)

from app.ui.barra_lateral import TRAZOS, BarraLateral, crear_icono
from app.ui.local_analysis_dialog import LocalAnalysisDialog
from app.ui.main_window import MainWindow
from app.ui.sistema_visual import ANCHO_BARRA, ANCHO_BARRA_COMPACTA, DURACION_BARRA

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


@pytest.fixture(autouse=True)
def fuentes(aplicacion: QApplication) -> None:
    """Carga la fuente Windows para el renderizado Qt sin pantalla; retorna None."""
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")


def test_iconos_y_plegado(aplicacion: QApplication) -> None:
    """Verifica iconos, señales, selección y reversibilidad de la transición."""
    botones = [QPushButton(str(i)) for i in range(7)]
    botones[1].setCheckable(True)
    botones[1].setChecked(True)
    accion = Mock()
    botones[1].clicked.connect(accion)
    barra = BarraLateral(botones)
    for trazo in TRAZOS:
        assert not crear_icono(trazo).isNull()
    barra.control.click()
    barra.animacion.setCurrentTime(DURACION_BARRA)
    assert barra.width() == ANCHO_BARRA_COMPACTA
    assert all(not boton.text() and boton.toolTip() for boton in botones)
    assert botones[1].isChecked()
    botones[1].click()
    accion.assert_called_once()
    barra.control.click()
    barra.animacion.setCurrentTime(DURACION_BARRA)
    assert barra.width() == ANCHO_BARRA
    assert [boton.text() for boton in botones] == barra.etiquetas
    assert barra.animacion.state() == QAbstractAnimation.State.Stopped
    barra.close()


def test_destinos_originales(aplicacion: QApplication) -> None:
    """Comprueba páginas originales y acción de draft conservadas al plegar."""
    ventana = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(ventana)
    ventana.pages = QStackedWidget()
    for _ in range(6):
        ventana.pages.addWidget(QWidget())
    ventana.open_draft_tool_dialog = Mock()
    barra = ventana.create_navigation()
    ventana.pages.currentChanged.connect(ventana._handle_page_changed)
    barra.alternar()
    for indice, boton in enumerate(barra.botones[:6]):
        boton.setEnabled(True)
        boton.click()
        assert ventana.pages.currentIndex() == indice
        assert boton.isChecked()
    ventana.draft_nav_button.click()
    ventana.open_draft_tool_dialog.assert_called_once()
    ventana.pages.setCurrentIndex(1)
    assert ventana.analysis_button.isChecked()
    barra.animacion.stop()
    ventana.deleteLater()


def test_estructura_global(
    aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comprueba que la barra y las siete páginas comparten la fila principal."""
    ventana = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(ventana)
    for nombre in (
        "create_header",
        "create_home_page",
        "create_analysis_page",
        "create_live_page",
        "create_saved_games_page",
        "create_settings_page",
    ):
        setattr(ventana, nombre, QWidget)
    ventana.showMaximized = Mock()
    ventana.recording_library = Mock()
    ventana.recording_service = Mock()
    grabaciones = QWidget()
    for nombre in (
        "open_folder_requested",
        "stop_recording_requested",
        "open_window_requested",
        "recordings_changed",
    ):
        setattr(grabaciones, nombre, Mock())
    monkeypatch.setattr("app.ui.main_window.RecordingsPage", lambda *args: grabaciones)
    ventana.build_ui()
    cuerpo = ventana.backdrop.layout().itemAt(0).layout()
    assert isinstance(cuerpo.itemAt(0).widget(), BarraLateral)
    assert cuerpo.itemAt(1).layout().itemAt(1).widget() is ventana.pages
    assert ventana.pages.count() == 7
    ventana.deleteLater()


def test_contenido_y_adaptacion(
    dialogo: "LocalAnalysisDialog", aplicacion: QApplication
) -> None:
    """Verifica paneles conservados, retrato contenido y apilado según ancho."""
    dialogo._mostrar_contenido(True)
    dialogo.resize(1000, 760)
    dialogo.show()
    aplicacion.processEvents()
    assert all(
        fila.direction() == QBoxLayout.Direction.TopToBottom
        for fila in dialogo._filas_adaptables
    )
    for nombre in (
        "champion_banner",
        "skill_order_panel",
        "counter_panel",
        "advice_panel",
        "radar",
        "power_curve",
        "rune_panel",
        "summoners_card",
        "starters_card",
        "core_overview_card",
        "build_card",
        "situational_card",
        "damage_bar",
        "bar",
        "matchups_panel",
        "item_table",
    ):
        assert not getattr(dialogo, nombre).isHidden()
    assert dialogo.champion_portrait.contentsRect().width() == 88
    dialogo.resize(800, 760)
    aplicacion.processEvents()
    assert dialogo.rune_pages_layout.direction() == QBoxLayout.Direction.TopToBottom
    assert (
        dialogo._filtros_analisis.itemAtPosition(3, 1).widget() is dialogo.style_value
    )
    dialogo.resize(1500, 900)
    aplicacion.processEvents()
    assert all(
        fila.direction() == QBoxLayout.Direction.LeftToRight
        for fila in dialogo._filas_adaptables
    )
