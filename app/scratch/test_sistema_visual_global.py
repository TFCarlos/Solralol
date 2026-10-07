"""Regresión del sistema global, estados interactivos y pantallas sin servicios externos."""

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.componentes_visuales import (
    EstadoVacio,
    Interruptor,
    MensajeEstado,
    PaginaDesplazable,
    Reflujo,
    TarjetaSistema,
)
from app.ui.estilo_global import ESTILO_GLOBAL
from app.ui.iconos import TRAZOS_ACCIONES, icono_accion, icono_trazo
from app.ui.sistema_visual import PALETA, TRANSICIONES
from app.ui.tema import (
    EstiloSolralol,
    actualizar_estilo,
    actualizar_texto_boton,
    aplicar_apariencia,
    aplicar_color,
    aplicar_estado,
    aplicar_tema,
    color_con_alfa,
    establecer_icono_accion,
    instalar_sistema_visual,
    preparar_componente,
)

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


@pytest.fixture(autouse=True)
def tema(aplicacion: QApplication) -> None:
    """Instala tema y fuentes reales en Qt offscreen para cada prueba."""
    for fuente in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + fuente)
    instalar_sistema_visual(aplicacion)


def procesar(aplicacion: QApplication) -> None:
    """Procesa cambios de geometría y señales pendientes de presentación."""
    for _ in range(15):
        aplicacion.processEvents()


def test_instalacion_paleta_y_metricas(aplicacion: QApplication) -> None:
    """Verifica instalación única, paleta, métricas y demora de tooltip."""
    assert instalar_sistema_visual(aplicacion) is aplicacion.sistema_visual
    assert aplicacion.palette().color(QPalette.ColorRole.Text).name() == PALETA["texto"]
    assert aplicacion.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    estilo = EstiloSolralol()
    assert estilo.pixelMetric(QStyle.PixelMetric.PM_SmallIconSize) == 20
    assert estilo.pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth) >= 0
    assert estilo.styleHint(QStyle.StyleHint.SH_ToolTip_WakeUpDelay) == 400
    assert estilo.styleHint(QStyle.StyleHint.SH_UnderlineShortcut) >= 0
    assert color_con_alfa("oro", 500).alpha() == 255
    assert color_con_alfa("oro", -1).alpha() == 0
    assert "#edfa69" not in ESTILO_GLOBAL


def test_roles_iconos_y_estados(aplicacion: QApplication) -> None:
    """Verifica variantes, iconos, colores semánticos y propiedades dinámicas."""
    tarjeta = TarjetaSistema("Sección")
    assert tarjeta.disposicion.contentsMargins().left() == 20
    compacta = TarjetaSistema(variante="compacta")
    assert compacta.disposicion.contentsMargins().left() == 12
    mensaje = MensajeEstado()
    mensaje.establecer("Datos guardados", "success")
    assert mensaje.text() == mensaje.accessibleDescription()
    assert mensaje.property("estado") == "exito"
    aplicar_color(mensaje, PALETA["desventaja"])
    assert mensaje.property("estado") == "error"
    aplicar_color(mensaje, PALETA["texto"])
    assert mensaje.property("estado") == "normal"
    aplicar_estado(mensaje, "loading")
    boton = QPushButton()
    establecer_icono_accion(boton, "play")
    assert boton.toolTip() == "Reproducir" and not boton.icon().isNull()
    actualizar_texto_boton(boton, "⏸ Pausar")
    assert boton.text() == "Pausar" and boton.accessibleName() == "Pausar"
    actualizar_texto_boton(boton, "Continuar")
    assert boton.text() == "Continuar"
    for nombre in TRAZOS_ACCIONES:
        assert not icono_accion(nombre).isNull()
    assert not icono_accion("desconocido").isNull()
    assert icono_trazo("M1 1h10").cacheKey() == icono_trazo("M1 1h10").cacheKey()
    vacio = EstadoVacio("Sin datos", "Selecciona una fuente", "Actualizar")
    assert vacio.accion is not None
    assert EstadoVacio("Vacío", "Explicación").accion is None
    tarjeta.show()
    procesar(aplicacion)
    aplicar_apariencia(tarjeta, "destacada")
    actualizar_estilo(tarjeta)
    assert tarjeta.property("superficie") == "destacada"
    tarjeta.close()


def test_controles_teclado_y_reflujo(aplicacion: QApplication) -> None:
    """Ejercita selector, slider, booleanos, foco y apilado sin cambiar valores."""
    ventana = QWidget()
    fila = QHBoxLayout(ventana)
    combo = QComboBox()
    combo.addItems(["Primero", "Segundo"])
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(50)
    interruptor = Interruptor("Activar")
    for control in (combo, slider, interruptor):
        fila.addWidget(control)
    reflujo = Reflujo(ventana, [fila], 700)
    ventana.resize(900, 250)
    ventana.show()
    procesar(aplicacion)
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 1
    combo.showPopup()
    procesar(aplicacion)
    assert combo.view().isVisible()
    combo.hidePopup()
    slider.setFocus()
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert slider.value() == 51
    interruptor.setFocus()
    QTest.keyClick(interruptor, Qt.Key.Key_Space)
    interruptor.animacion.setCurrentTime(TRANSICIONES["estado"])
    assert interruptor.isChecked() and interruptor.posicion == 1
    interruptor.setEnabled(False)
    interruptor.grab()
    interruptor.hide()
    interruptor.setChecked(False)
    assert interruptor.posicion == 0
    ventana.resize(500, 400)
    procesar(aplicacion)
    assert fila.direction() == QHBoxLayout.Direction.TopToBottom
    reflujo.actualizar(900)
    assert fila.direction() == QHBoxLayout.Direction.LeftToRight
    pagina = PaginaDesplazable(QLabel("Contenido completo"))
    assert pagina.widget().text() == "Contenido completo"
    ventana.close()


@pytest.mark.parametrize("tipo", [QPushButton, QLineEdit, QComboBox, QCheckBox,
    QRadioButton, QSlider, QSpinBox, QTextEdit, QTableWidget, QListWidget, QTabWidget, QProgressBar])
def test_catalogo_controles(tipo: type, aplicacion: QApplication) -> None:
    """Renderiza cada familia habilitada y deshabilitada con el mismo tema."""
    control = tipo()
    control.resize(300, 100)
    control.show()
    procesar(aplicacion)
    control.setFocus()
    QTest.mouseMove(control, control.rect().center())
    assert not control.grab().isNull()
    control.setEnabled(False)
    assert not control.grab().isNull()
    assert control.property("visualListo")
    control.close()


def test_dialogo_y_roles_heredados(aplicacion: QApplication) -> None:
    """Comprueba modales y mapeo de nombres y propiedades existentes."""
    dialogo = QMessageBox(QMessageBox.Icon.Warning, "Aviso", "No hay datos disponibles")
    dialogo.show()
    procesar(aplicacion)
    assert not dialogo.iconPixmap().isNull()
    dialogo.close()
    for nombre in ("heroTitle", "metricValue", "connectionLabel", "itemBadge", "sectionTitle", "heroCaption", "mutedText", "championName"):
        label = QLabel("Texto")
        label.setObjectName(nombre)
        preparar_componente(label)
        assert label.property("nivel")
    label = QLabel()
    label.setProperty("role", "title")
    preparar_componente(label)
    assert label.property("nivel") == "seccion"
    card = QFrame()
    QVBoxLayout(card)
    card.setProperty("card", "true")
    preparar_componente(card)
    assert card.property("superficie") == "tarjeta"
    card.setStyleSheet("color: red;")
    aplicar_tema(card)
    assert card.styleSheet() == ""


def test_sin_hojas_legacy() -> None:
    """Impide estilos locales nuevos y colores ajenos a tokens en pantallas."""
    permitidos = {"tema.py", "barra_lateral.py", "local_analysis_dialog.py"}
    for ruta in Path("app/ui").glob("*.py"):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        llamadas = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "setStyleSheet"]
        assert ruta.name in permitidos or not llamadas, ruta
