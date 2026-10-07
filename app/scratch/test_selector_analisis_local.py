"""Pruebas aisladas del rango inicial y el resaltado de líneas."""

import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QVBoxLayout

from app.ui.local_analysis_dialog import _ANALYSIS_LANES, LocalAnalysisDialog


@pytest.fixture(scope="module")
def aplicacion() -> QApplication:
    """Crea Qt sin ventanas visibles y devuelve su aplicación."""
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("guardado", ["gold", "emerald_plus", "desconocido", None])
def test_rango_inicial(guardado: str | None) -> None:
    """Comprueba que el rango inicial es Esmeralda+ con cualquier preferencia previa."""
    with patch("app.ui.local_analysis_dialog.SettingsService") as ajustes:
        ajustes.return_value.load.return_value = {"analysis_rank": guardado}
        assert LocalAnalysisDialog._load_analysis_rank() == "emerald_plus"
        ajustes.assert_not_called()


def test_linea_comun_y_limpieza(aplicacion: QApplication) -> None:
    """Comprueba partidas, negrita, selección estable y limpieza al cambiar datos."""
    selector = QComboBox()
    for clave, etiqueta in _ANALYSIS_LANES:
        selector.addItem(etiqueta, clave)
    selector.setCurrentIndex(selector.findData("top"))
    datos = {
        "top": {"games": 20, "win_rate": 0.65},
        "mid": {"games": 100, "win_rate": 0.48},
    }
    panel = SimpleNamespace(
        analysis_lane_combo=selector, _profile_lane_stats=lambda variante: datos
    )
    LocalAnalysisDialog._apply_lane_labels(panel, None)
    medio = selector.findData("mid")
    superior = selector.findData("top")
    assert "Más común" in selector.itemText(medio)
    assert selector.itemText(medio) == "★ Mid · 48.0% · Más común"
    assert not selector.itemText(superior).startswith("★")
    assert "Línea con más" in selector.itemData(medio, Qt.ItemDataRole.ToolTipRole)
    assert selector.itemData(medio, Qt.ItemDataRole.FontRole).bold()
    assert not selector.itemData(superior, Qt.ItemDataRole.FontRole).bold()
    assert selector.currentData() == "top"
    datos["top"]["games"] = 200
    LocalAnalysisDialog._apply_lane_labels(panel, None)
    assert "Más común" in selector.itemText(superior)
    assert "Más común" not in selector.itemText(medio)
    assert not selector.itemData(medio, Qt.ItemDataRole.FontRole).bold()
    datos.clear()
    datos.update(
        {"mid": {"games": "muchas"}, "top": {"games": float("nan")}, "adc": None}
    )
    LocalAnalysisDialog._apply_lane_labels(panel, None)
    assert all("Más común" not in selector.itemText(i) for i in range(selector.count()))
    assert not selector.signalsBlocked()


@pytest.mark.parametrize("preferida", [clave for clave, _ in _ANALYSIS_LANES])
def test_seleccion_y_geometria(aplicacion: QApplication, preferida: str) -> None:
    """Verifica cada preferida, texto completo y recarga al seleccionar otra línea."""
    ventana = QDialog()
    selector = QComboBox(ventana)
    selector.setObjectName("analysisLaneCombo")
    disposicion = QVBoxLayout(ventana)
    disposicion.addWidget(selector)
    for clave, etiqueta in _ANALYSIS_LANES:
        selector.addItem(etiqueta, clave)
    datos = {
        clave: {"games": 100 if clave == preferida else 10, "win_rate": 0.507}
        for clave, _ in _ANALYSIS_LANES
    }
    panel = SimpleNamespace(
        analysis_lane_combo=selector,
        analysis_lane="top",
        _profile_lane_stats=lambda variante: datos,
        _persist_analysis_selection=Mock(),
        _ensure_variant=Mock(),
    )
    selector.currentIndexChanged.connect(
        lambda indice: LocalAnalysisDialog._on_lane_changed(panel)
    )
    ventana.analysis_lane_combo = selector
    LocalAnalysisDialog._apply_style(ventana)
    LocalAnalysisDialog._apply_lane_labels(panel, None)
    assert not panel._ensure_variant.called
    indice = selector.findData(preferida)
    assert selector.itemText(indice).startswith("★ ")
    assert (
        sum(selector.itemText(i).startswith("★ ") for i in range(selector.count())) == 1
    )
    selector.setCurrentIndex(indice)
    ventana.show()
    aplicacion.processEvents()
    assert selector.width() >= selector.minimumWidth()
    assert ventana.rect().contains(selector.geometry())
    assert (
        selector.fontMetrics().horizontalAdvance(selector.currentText())
        < selector.width() - 40
    )
    selector.showPopup()
    aplicacion.processEvents()
    assert selector.view().isVisible()
    assert selector.view().width() >= selector.minimumWidth() - 16
    selector.hidePopup()
    otro = (indice + 1) % selector.count()
    selector.setCurrentIndex(otro)
    assert panel.analysis_lane == selector.itemData(otro)
    panel._persist_analysis_selection.assert_not_called()
    panel._ensure_variant.assert_called()
    ventana.close()
