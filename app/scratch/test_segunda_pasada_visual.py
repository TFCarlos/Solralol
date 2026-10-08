"""Regresión de identidad, superficies, arte local y jerarquía de la segunda pasada."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from _paths import DATA_DIR
from app.services.analisis_local_service import AnalisisLocalService
from app.ui.barra_lateral import BarraLateral
from app.ui.estilo_analisis import ESTILO_ANALISIS, ESTILO_BARRA
from app.ui.local_analysis_dialog import (
    BarWidget,
    DamageBarWidget,
    LocalAnalysisDialog,
    PowerCurveWidget,
    RadarWidget,
)
from app.ui.main_window import MainWindow
from app.ui.sistema_visual import DURACION_BARRA, PALETA, espaciar_tarjeta
from app.ui.superficies_analisis import FondoTecnologico, IconoEnmarcado, TarjetaCampeon

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


def test_paleta_y_logo(aplicacion: QApplication) -> None:
    """Comprueba píxeles del logo y ausencia de acentos lima en los estilos nuevos."""
    logo = QImage(str(DATA_DIR / "LogoApp.png"))
    assert not logo.isNull()
    colores = {
        logo.pixelColor(x, y).name()
        for x in range(logo.width())
        for y in range(logo.height())
        if logo.pixelColor(x, y).alpha() == 255
    }
    assert {PALETA["oro_logo"], PALETA["marfil"], PALETA["calida"]} <= colores
    assert "#edfa69" not in (ESTILO_ANALISIS + ESTILO_BARRA).lower()
    barra = BarraLateral([QPushButton() for _ in range(7)])
    barra.resize(barra.width(), 1000)
    barra.show()
    aplicacion.processEvents()
    assert not barra.logo.pixmap().isNull()
    assert barra.marca.isVisible()
    assert barra.control.y() > barra.botones[-1].y() + barra.botones[-1].height()
    assert barra.logo.geometry().left() >= 12
    barra.alternar()
    barra.animacion.setCurrentTime(DURACION_BARRA)
    aplicacion.processEvents()
    assert barra.marca.isHidden() and barra.categoria.isHidden()
    assert barra.logo.isVisible() and barra.control.text() == ""
    assert not barra.control.icon().isNull()
    assert barra.logo.geometry().right() < barra.width() - 8
    barra.close()


def test_cabecera_sin_marca_duplicada(aplicacion: QApplication) -> None:
    """Verifica que estado y cierre permanecen sin marca exterior a la barra."""
    ventana = MainWindow.__new__(MainWindow)
    from PySide6.QtWidgets import QMainWindow

    QMainWindow.__init__(ventana)
    cabecera = ventana.create_header()
    assert not cabecera.findChild(QLabel, "brandTitle")
    assert cabecera.findChild(QLabel, "connectionLabel") is ventana.connection_label
    cabecera.deleteLater()
    ventana.deleteLater()


def test_superficies_y_recorte(aplicacion: QApplication) -> None:
    """Verifica luz estática, superposición oscura y esquinas transparentes del bitmap."""
    fondo = FondoTecnologico()
    fondo.resize(800, 600)
    imagen_fondo = fondo.grab().toImage()
    assert imagen_fondo.pixelColor(120, 10) != imagen_fondo.pixelColor(790, 580)
    imagen = QPixmap(100, 100)
    imagen.fill(Qt.GlobalColor.white)
    tarjeta = TarjetaCampeon()
    tarjeta.resize(700, 260)
    tarjeta.establecer_imagen(imagen)
    captura = tarjeta.grab().toImage()
    assert captura.pixelColor(20, 120).lightness() < 50
    assert captura.pixelColor(600, 120).lightness() < 120
    tarjeta.establecer_imagen(QPixmap())
    assert tarjeta.imagen.isNull()
    icono = IconoEnmarcado()
    icono.setPixmap(imagen)
    assert icono.pixmap().toImage().pixelColor(0, 0).alpha() == 0
    assert icono.pixmap().toImage().pixelColor(50, 50).alpha() == 255
    icono.setPixmap(QPixmap())
    assert icono.pixmap().isNull()


@pytest.mark.parametrize("compacta,margen", [(False, 20), (True, 12)])
def test_espaciado_compartido(
    aplicacion: QApplication, compacta: bool, margen: int
) -> None:
    """Comprueba que el mismo token aplica relleno uniforme sin estilos por nodo."""
    disposicion = QVBoxLayout()
    espaciar_tarjeta(disposicion, compacta)
    assert disposicion.getContentsMargins() == (margen,) * 4
    assert disposicion.spacing() == 12


def test_splash_local(
    servicio: AnalisisLocalService, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Lee arte local opcional, admite ausencia y mantiene cancelación sin red."""
    monkeypatch.setattr("data_dragon.DATA_DIR", tmp_path)
    ruta = tmp_path / "champion_splashes" / "Prueba_0.jpg"
    ruta.parent.mkdir()
    ruta.write_bytes(b"arte local")
    assert servicio.recurso("splash", "Prueba", lambda: False) == (ruta, b"arte local")
    assert servicio.recurso("splash", "Ausente", lambda: False) == (None, b"")
    with pytest.raises(InterruptedError):
        servicio.recurso("splash", "Cancelado", lambda: True)
    servicio.recursos.clear()
    original = Path.read_bytes

    def leer(ruta_recibida: Path) -> bytes:
        """Simula fallo de lectura exclusivamente del arte opcional; devuelve bytes."""
        if ruta_recibida == ruta:
            raise OSError("archivo no disponible")
        return original(ruta_recibida)

    monkeypatch.setattr(Path, "read_bytes", leer)
    assert servicio.recurso("splash", "Prueba", lambda: False) == (None, b"")


def test_hero_y_paginas(
    dialogo: LocalAnalysisDialog, perfil: dict, aplicacion: QApplication
) -> None:
    """Comprueba jerarquía, dos páginas, acciones contenidas y estado vacío utilizable."""
    pagina = {
        "keystone": "Conqueror",
        "primary_tree": "Precision",
        "secondary_tree": "Resolve",
        "slots": ["Triumph", "Legend: Alacrity", "Last Stand"],
        "secondary_slots": ["Second Wind", "Revitalize"],
        "win_rate": 0.52,
        "games": 800,
        "build": ["Espada"],
        "skill_order": ["Q", "W", "E"],
    }
    datos = dict(
        perfil, runes=[pagina, dict(pagina, keystone="Otra", build=["Otro objeto"])]
    )
    dialogo.champion_combo.blockSignals(True)
    dialogo.champion_combo.setCurrentIndex(dialogo.champion_combo.findText("Prueba"))
    dialogo.champion_combo.blockSignals(False)
    dialogo._renderizar_analisis(datos)
    assert dialogo.champion_title.text() == "PRUEBA", (
        dialogo.champion_combo.currentText(),
        [
            dialogo.champion_combo.itemText(indice)
            for indice in range(dialogo.champion_combo.count())
        ],
    )
    assert "Dificultad" in dialogo.champion_meta.text()
    assert " WR" not in dialogo.champion_meta.text()
    assert "Conqueror" in dialogo.rune_summary.text()
    assert len(dialogo._rune_page_cards) == 2
    assert (
        dialogo._rune_page_cards[0].findChild(QLabel, "localRuneGamesBadge").text()
        == "800 partidas"
    )
    dialogo._rune_page_cards[1].clicked.emit()
    assert "Otra" in dialogo.rune_summary.text()
    assert dialogo._active_build(datos) == ["Otro objeto"]
    assert dialogo.update_single_champ_btn.parentWidget() is dialogo.champion_banner
    assert dialogo.update_winrates_btn.parentWidget() is dialogo.champion_banner
    dialogo._mostrar_contenido(True)
    dialogo.resize(916, 1000)
    dialogo.show()
    aplicacion.processEvents()
    assert dialogo._scroll_analisis.horizontalScrollBar().maximum() == 0
    dialogo._mostrar_contenido(False)
    assert not dialogo.champion_banner.isHidden()
    assert dialogo.champion_winrate.text() == "—"
    assert not dialogo.update_single_champ_btn.isHidden()
    dialogo.resize(800, 760)
    dialogo.show()
    aplicacion.processEvents()
    assert dialogo._disposicion_hero.direction() == QVBoxLayout.Direction.TopToBottom
    for tarjeta in dialogo.findChildren(QWidget):
        if tarjeta.objectName() in {
            "localRunePanel",
            "buildCard",
            "localChampionBanner",
        }:
            assert tarjeta.layout().getContentsMargins() == (20,) * 4


def test_graficos_conservan_valores(aplicacion: QApplication) -> None:
    """Ejercita gráficos vacíos y poblados sin transformar sus datos analíticos."""
    radar = RadarWidget([("Daño", 7), ("Control", 4), ("Movilidad", 6)])
    curva = PowerCurveWidget([("0-15", 54.3), ("15-20", 54.9), ("20-25", 52)])
    afinidad = BarWidget()
    afinidad.set_values([("Espada", 50.0, "1"), ("Arco", 40.0, "2")])
    dano = DamageBarWidget(70, 20, 10)
    for grafico in (radar, curva, afinidad, dano):
        grafico.resize(550, 260)
        assert not grafico.grab().isNull()
    assert curva.values[0][1] == 54.3
    assert radar.values[0][1] == 7
    assert afinidad._row_height() == 52
    radar.values = []
    curva.values = []
    afinidad.set_values([])
    for grafico in (radar, curva, afinidad):
        assert not grafico.grab().isNull()
