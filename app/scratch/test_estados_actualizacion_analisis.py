"""Cobertura de estados de actualización: dimensiones fijas, progreso real y splash local."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import requests
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtWidgets import QApplication

from app.ui.local_analysis_dialog import (
    ALTO_ESTADO_ACTUALIZACION,
    ANCHO_ACCIONES_HEROE,
    LocalAnalysisDialog,
)

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


class ActualizadorFalso(QObject):
    """Sustituto del worker real que solo expone las señales para ensayar la UI."""

    progress = Signal(int, int, str)
    finished_scraping = Signal(int, int)
    error_occurred = Signal(str)
    finished = Signal()

    def __init__(self, **parametros: object) -> None:
        """Ignora los parámetros de construcción y crea el objeto Qt sin trabajo real."""
        super().__init__()
        self.parametros = parametros

    def start(self) -> None:
        """No realiza ninguna tarea; el test emite las señales a mano."""

    def isRunning(self) -> bool:
        """Devuelve False para que el diálogo admita nuevas llamadas."""
        return False

    def cancel(self) -> None:
        """Cancelación simulada sin efectos."""


def _instalar_actualizador(
    monkeypatch: pytest.MonkeyPatch,
) -> list[ActualizadorFalso]:
    """Sustituye el worker del diálogo por fábricas registradas y devuelve las creadas."""
    creados: list[ActualizadorFalso] = []

    def fabrica(**parametros: object) -> ActualizadorFalso:
        """Crea y registra un actualizador falso con los parámetros recibidos."""
        trabajador = ActualizadorFalso(**parametros)
        creados.append(trabajador)
        return trabajador

    monkeypatch.setattr("app.ui.local_analysis_dialog.ChampionScraperWorker", fabrica)
    return creados


def test_botones_dimensiones_estables_durante_actualizacion(
    dialogo: LocalAnalysisDialog,
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los botones y el héroe conservan geometría en reposo, carga, éxito y error."""
    dialogo.resize(1180, 900)
    dialogo.show()
    for _ in range(5):
        aplicacion.processEvents()
    botones = (dialogo.update_single_champ_btn, dialogo.update_winrates_btn)
    geometrias = [boton.geometry() for boton in botones]
    heroe = dialogo.champion_banner.geometry()
    estado = dialogo._estado_actualizacion.geometry()
    assert all(ancho.width() == ANCHO_ACCIONES_HEROE for ancho in geometrias)
    assert estado.size() == QSize(ANCHO_ACCIONES_HEROE, ALTO_ESTADO_ACTUALIZACION)
    assert (
        dialogo.winrate_progress_label.parentWidget() is dialogo._estado_actualizacion
    )
    assert dialogo.winrate_progress_bar.parentWidget() is dialogo._estado_actualizacion

    creados = _instalar_actualizador(monkeypatch)
    dialogo._start_winrate_update("Prueba")
    trabajador = creados[0]
    trabajador.progress.emit(4, 100, "Prueba actualizando...")
    trabajador.progress.emit(
        45, 100, "Prueba · Esmeralda+ · 3/6 · texto largo de estado"
    )
    for _ in range(5):
        aplicacion.processEvents()
    assert [boton.geometry() for boton in botones] == geometrias
    assert dialogo.champion_banner.geometry() == heroe
    assert dialogo._estado_actualizacion.geometry() == estado
    assert dialogo.update_single_champ_btn.property("cargando") == "true"
    assert not dialogo.update_single_champ_btn.isEnabled()
    assert not dialogo.winrate_progress_bar.isHidden()

    trabajador.finished_scraping.emit(1, 1)
    trabajador.finished.emit()
    for _ in range(5):
        aplicacion.processEvents()
    assert [boton.geometry() for boton in botones] == geometrias
    assert dialogo.champion_banner.geometry().size() == heroe.size()
    assert dialogo._estado_actualizacion.geometry() == estado
    assert dialogo.update_single_champ_btn.property("cargando") == "false"


def test_ciclo_vida_progreso_un_campeon(
    dialogo: LocalAnalysisDialog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El progreso de un campeón usa porcentajes reales, no retrocede y cierra al 100 %."""
    creados = _instalar_actualizador(monkeypatch)
    dialogo._start_winrate_update("Prueba")
    trabajador = creados[0]
    barra = dialogo.winrate_progress_bar
    etiqueta = dialogo.winrate_progress_label
    assert not barra.isHidden()
    assert barra.value() == 0
    assert (barra.minimum(), barra.maximum()) == (0, 100)
    assert not etiqueta.isHidden()
    assert etiqueta.text() == "Iniciando..."

    trabajador.progress.emit(4, 100, "Prueba actualizando...")
    trabajador.progress.emit(40, 100, "Prueba · Esmeralda+ · 3/6")
    trabajador.progress.emit(30, 100, "Prueba · etapa anterior")
    assert barra.value() == 40
    assert etiqueta.text().startswith("40%")
    trabajador.progress.emit(88, 100, "Prueba · Descargando recursos")
    trabajador.progress.emit(96, 100, "Prueba · Guardando datos")
    assert barra.value() == 96

    trabajador.finished_scraping.emit(1, 1)
    assert barra.value() == 100
    assert not barra.isHidden()
    assert "correctamente" in etiqueta.text()
    dialogo._ocultar_barra_progreso()
    assert barra.isHidden()
    assert not etiqueta.isHidden()
    assert dialogo.update_single_champ_btn.property("cargando") == "false"
    trabajador.finished.emit()
    assert dialogo._winrate_worker is None


def test_progreso_todos_por_campeones(
    dialogo: LocalAnalysisDialog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El modo global cuenta campeones sin reiniciar la barra en cada uno."""
    creados = _instalar_actualizador(monkeypatch)
    dialogo._start_winrate_update()
    trabajador = creados[0]
    barra = dialogo.winrate_progress_bar
    etiqueta = dialogo.winrate_progress_label
    assert (barra.minimum(), barra.maximum()) == (0, max(1, len(dialogo.champions)))

    trabajador.progress.emit(0, 2, "Prueba actualizando...")
    trabajador.progress.emit(0, 2, "Prueba · Esmeralda+ · 3/6")
    trabajador.progress.emit(1, 2, "Prueba completado")
    trabajador.progress.emit(1, 2, "Otro · Descargando recursos")
    trabajador.progress.emit(2, 2, "Otro completado")
    assert barra.value() == 2
    assert etiqueta.text().startswith("2/2")
    trabajador.finished_scraping.emit(2, 2)
    assert barra.value() == barra.maximum()
    trabajador.finished.emit()


def test_error_detiene_progreso_y_restaura(
    dialogo: LocalAnalysisDialog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un error detiene la barra, presenta estado propio y devuelve los botones."""
    creados = _instalar_actualizador(monkeypatch)
    dialogo._start_winrate_update("Prueba")
    trabajador = creados[0]
    trabajador.progress.emit(50, 100, "Prueba · Esmeralda+ · 3/6")
    trabajador.error_occurred.emit("timeout de la fuente")
    assert dialogo.winrate_progress_bar.isHidden()
    assert not dialogo.winrate_progress_label.isHidden()
    assert "Error" in dialogo.winrate_progress_label.text()
    assert dialogo.update_single_champ_btn.isEnabled()
    assert dialogo.update_winrates_btn.isEnabled()
    assert dialogo.update_single_champ_btn.property("cargando") == "false"
    trabajador.finished.emit()
    assert dialogo._winrate_worker is None


def test_cancelacion_reinicia_estado(
    dialogo: LocalAnalysisDialog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Una tarea obsoleta sin resultado reinicia barra, etiqueta y botones."""
    creados = _instalar_actualizador(monkeypatch)
    dialogo._start_winrate_update("Prueba")
    trabajador = creados[0]
    trabajador.progress.emit(30, 100, "Prueba · Esmeralda+ · 3/6")
    trabajador.finished.emit()
    assert dialogo.winrate_progress_bar.isHidden()
    assert dialogo.winrate_progress_bar.value() <= 0
    assert dialogo.winrate_progress_label.isHidden()
    assert dialogo.update_single_champ_btn.isEnabled()
    assert dialogo.update_single_champ_btn.property("cargando") == "false"
    assert dialogo._winrate_worker is None


def test_splash_descarga_local_y_sin_red_repetida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Descarga el splash una vez, lo guarda localmente y reutiliza el archivo."""
    import data_dragon

    monkeypatch.setattr(data_dragon, "DATA_DIR", tmp_path)
    respuesta = Mock()
    respuesta.content = b"\xff\xd8\xff" + b"0" * 4096
    respuesta.raise_for_status = Mock()
    peticion = Mock(return_value=respuesta)
    monkeypatch.setattr(data_dragon.requests, "get", peticion)

    ruta = data_dragon.get_champion_splash_path("PruebaSplash")
    esperada = tmp_path / "champion_splashes" / "PruebaSplash_0.jpg"
    assert ruta == esperada
    assert ruta is not None and ruta.is_file()
    assert peticion.call_count == 1
    assert "splash/PruebaSplash_0.jpg" in peticion.call_args.args[0]
    origenes = json.loads(
        (tmp_path / "champion_splashes" / "origenes.json").read_text(encoding="utf-8")
    )
    assert "PruebaSplash_0.jpg" in origenes

    assert data_dragon.get_champion_splash_path("PruebaSplash") == esperada
    assert peticion.call_count == 1


def test_splash_fallido_o_invalido_devuelve_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo de red o contenido inválido devuelve None sin crear archivos."""
    import data_dragon

    monkeypatch.setattr(data_dragon, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        data_dragon.requests,
        "get",
        Mock(side_effect=requests.RequestException("sin red")),
    )
    assert data_dragon.get_champion_splash_path("Prueba") is None

    respuesta = Mock(content=b"<html>" * 512)
    respuesta.raise_for_status = Mock()
    monkeypatch.setattr(data_dragon.requests, "get", Mock(return_value=respuesta))
    assert data_dragon.get_champion_splash_path("Prueba") is None
    assert not (tmp_path / "champion_splashes" / "Prueba_0.jpg").exists()

    peticion = Mock()
    monkeypatch.setattr(data_dragon.requests, "get", peticion)
    assert data_dragon.get_champion_splash_path("Prueba", download=False) is None
    peticion.assert_not_called()
