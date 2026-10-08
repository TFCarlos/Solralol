"""Validación aislada del flujo Qt, cachés y carga sin bloquear filtros."""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox

from app.services.analisis_local_service import AnalisisLocalService
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.champion_variant_service import ChampionVariantService
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones
from app.ui.analisis_local_worker import AnalisisLocalWorker
from app.ui.local_analysis_dialog import LocalAnalysisDialog


@pytest.fixture(scope="module")
def aplicacion() -> QApplication:
    """Devuelve Qt en modo sin ventanas nativas."""
    return QApplication.instance() or QApplication([])


@pytest.fixture
def perfil() -> dict:
    """Devuelve un campeón de prueba con identidad y datos de build."""
    return {
        "character": "Prueba",
        "basic_info": {"play_style": "Juggernaut", "flex_potential": ["Support"]},
        "common_runes": [],
        "summoner_spells": ["Destello"],
        "most_played_build": ["Espada"],
        "power_curve_and_scaling": {},
    }


@pytest.fixture
def catalogo() -> CatalogoAnalisisLocal:
    """Devuelve un catálogo local pequeño con alias y objeto legendario."""
    return CatalogoAnalisisLocal(
        {
            "1": {
                "name": "Espada",
                "name_en": "Sword",
                "colloq": "hoja",
                "gold": {"total": 3000},
                "stats": {},
            }
        },
        [],
        {"blade": "espada"},
    )


@pytest.fixture
def servicio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, catalogo: CatalogoAnalisisLocal
) -> AnalisisLocalService:
    """Crea un servicio con red y ajustes simulados y devuelve su instancia."""
    import app.services.analisis_local_service as modulo

    ajustes = Mock()
    ajustes.load.return_value = {}
    for funcion in (
        "get_item_icon_path",
        "get_champion_icon_path",
        "get_rune_icon_path",
        "get_spell_icon_path",
        "get_ability_icon_path",
    ):
        monkeypatch.setattr(modulo.data_dragon, funcion, Mock(return_value=None))
    monkeypatch.setattr(
        modulo.data_dragon, "get_champion_data", Mock(return_value={"title": "Prueba"})
    )
    instancia = AnalisisLocalService(catalogo, tmp_path / "campeones.json", "16.17.1")
    instancia.variantes = ChampionVariantService(tmp_path / "variantes")
    return instancia


def test_catalogo(catalogo: CatalogoAnalisisLocal) -> None:
    """Comprueba reglas heredadas, alias y reutilización del conjunto recomendable."""
    assert catalogo.normalizar_nombre("Blade") == "espada"
    assert catalogo.id_por_nombre("", {}) == ""
    assert catalogo.id_por_nombre("1", catalogo.catalogo) == "1"
    assert catalogo.id_por_nombre("blade", catalogo.catalogo) == "1"
    assert catalogo.id_por_nombre("Sword", catalogo.catalogo) == "1"
    assert catalogo.id_por_nombre("hoja", catalogo.catalogo) == "1"
    assert catalogo.id_por_nombre("nada", catalogo.catalogo) == ""
    objetos = catalogo.objetos_recomendables()
    assert "1" in objetos
    assert catalogo.objetos_recomendables() is objetos


def test_carga_y_cache(
    servicio: AnalisisLocalService, perfil: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifica aislamiento de filtros, recursos compartidos y ninguna descarga repetida."""
    import app.services.analisis_local_service as modulo

    variante = {
        "role": "support",
        "rank": "emerald_plus",
        "updated": True,
        "most_played_build": ["Espada"],
        "power_spike_items": ["Espada"],
        "lane_stats": {"lanes": {"support": {"games": 100, "win_rate": 0.5}}},
    }
    servicio.variantes.repositorio.guardar(
        "Prueba",
        RepositorioCampeones.documento(
            perfil, {"emerald_plus": {"support": variante}}, "partial"
        ),
    )
    primero = servicio.cargar(perfil, "support", "emerald_plus", {}, lambda: False)
    segundo = servicio.cargar(perfil, "support", "emerald_plus", {}, lambda: False)
    assert primero["variante"] == segundo["variante"]
    assert modulo.data_dragon.get_champion_data.call_count == 1
    assert modulo.data_dragon.get_champion_icon_path.call_count == 1
    assert perfil.get("power_spike_items") is None
    ausente = servicio.cargar(perfil, "mid", "diamond", {}, lambda: False)
    assert ausente["estado"] == EstadoDatos.SIN_DATOS_LOCALES.value
    assert servicio.textos({"a": ["b", 1], "c": {"d": "e"}}) == {"b", "e"}


def test_recursos_bytes_y_cancelacion(
    servicio: AnalisisLocalService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comprueba bytes leídos en preparación y cancelación entre recursos."""
    import app.services.analisis_local_service as modulo

    ruta = tmp_path / "imagen.png"
    ruta.write_bytes(b"imagen")
    funcion = Mock(return_value=ruta)
    monkeypatch.setattr(modulo.data_dragon, "get_item_icon_path", funcion)
    assert servicio.recurso("item", "1", lambda: False) == (ruta, b"imagen")
    assert servicio.recurso("item", "1", lambda: False) == (ruta, b"imagen")
    assert funcion.call_count == 1
    with pytest.raises(InterruptedError):
        servicio.recurso("item", "2", lambda: True)


def test_error_fuente(
    servicio: AnalisisLocalService, perfil: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evita guardar datos heredados como si una descarga fallida hubiera sido válida."""

    datos = servicio.cargar(perfil, "support", "diamond", {}, lambda: False)
    assert datos["estado"] == EstadoDatos.SIN_DATOS_LOCALES.value
    assert servicio.variantes.get("Prueba", "support", "diamond") is None


@pytest.fixture
def dialogo(
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    perfil: dict,
    tmp_path: Path,
) -> LocalAnalysisDialog:
    """Construye el diálogo real con catálogos simulados sin leer archivos externos."""
    perfiles = [perfil, dict(copy.deepcopy(perfil), character="Otro")]
    repositorio = RepositorioCampeones(tmp_path / "champion_data")
    for entrada in perfiles:
        repositorio.guardar_perfil(entrada)
    monkeypatch.setattr(repositorio, "perfiles", lambda: copy.deepcopy(perfiles))
    monkeypatch.setattr(
        "app.ui.local_analysis_dialog.RepositorioCampeones", lambda raiz: repositorio
    )
    monkeypatch.setattr("app.ui.local_analysis_dialog.DATA_DIR", tmp_path)
    monkeypatch.setattr(LocalAnalysisDialog, "_load", staticmethod(lambda ruta: []))
    monkeypatch.setattr(
        LocalAnalysisDialog, "_load_analysis_lane", staticmethod(lambda: "")
    )
    instancia = LocalAnalysisDialog(
        item_catalog={
            "version": "16.17.1",
            "items": {"1": {"name": "Espada", "gold": {"total": 3000}}},
        }
    )
    instancia._temporizador_analisis.stop()
    yield instancia
    instancia._temporizador_analisis.stop()
    if instancia._worker_analisis is not None:
        instancia._worker_analisis.requestInterruption()
        instancia._worker_analisis.wait(3000)
        aplicacion.processEvents()
    instancia.close()


def test_estilos_compartidos(dialogo: LocalAnalysisDialog) -> None:
    """Verifica los cinco selectores y que comparten el tema del popup."""
    selectores = dialogo.findChildren(QComboBox)
    assert len(selectores) == 5
    for selector in selectores:
        assert selector.view().window().objectName() == "localSelectorPopup"
        assert selector.view().window().styleSheet() == dialogo.styleSheet()
    assert "QComboBox#analysisLaneCombo" not in dialogo.styleSheet()


def test_selector_seis_rangos(dialogo: LocalAnalysisDialog) -> None:
    """Verifica las seis etiquetas reales y el rango inicial del selector Qt."""
    from app.services.rangos_campeones import OPCIONES_RANGO, RANGO_PREDETERMINADO

    selector = dialogo.analysis_rank_combo
    assert selector.count() == 6
    assert (
        tuple(
            (selector.itemData(indice), selector.itemText(indice))
            for indice in range(selector.count())
        )
        == OPCIONES_RANGO
    )
    assert selector.currentData() == RANGO_PREDETERMINADO


def test_obsoletos_y_errores(dialogo: LocalAnalysisDialog) -> None:
    """Comprueba generaciones, errores vigentes y selección de campeón/rango."""
    generacion = dialogo._generacion_analisis
    clave = dialogo._active_variant_key
    dialogo._recibir_analisis(generacion - 1, clave, {})
    assert dialogo._datos_preparados == {}
    dialogo._fallar_analisis(generacion - 1, clave)
    assert "Cargando" in dialogo.status.text()
    dialogo._fallar_analisis(generacion, clave)
    assert "No se pudieron" in dialogo.status.text()
    assert dialogo.analysis_loading_bar.isHidden()
    dialogo.champion_combo.setCurrentIndex(dialogo.champion_combo.findText("Otro"))
    dialogo.analysis_rank_combo.setCurrentIndex(
        dialogo.analysis_rank_combo.findData("diamond")
    )
    assert dialogo._generacion_analisis > generacion
    assert dialogo._active_variant_key == "otro|support|diamond"
    assert dialogo.analysis_rank_combo.isEnabled()
    assert not dialogo.analysis_loading_bar.isHidden()


def test_heartbeat_y_ultima_seleccion(
    dialogo: LocalAnalysisDialog,
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retiene una carga en worker y comprueba que Qt responde y solo aplica la última."""
    inicio_carga = threading.Event()
    liberar = threading.Event()
    hilos = []

    def cargar(
        perfil: dict, linea: str, rango: str, pagina: dict, cancelado: object
    ) -> dict:
        """Simula una fuente bloqueada y devuelve datos asociados a los filtros capturados."""
        hilos.append(threading.get_ident())
        inicio_carga.set()
        liberar.wait(2)
        return {
            "perfil": perfil,
            "variante": {
                "role": linea,
                "rank": rango,
                "lane_stats": {"lanes": {linea: {"games": 100, "win_rate": 0.5}}},
            },
            "recomendaciones": [],
            "objetos": {},
            "metadatos": {},
            "rutas": {},
            "imagenes": {},
        }

    monkeypatch.setattr(dialogo._servicio_analisis, "cargar", cargar)
    dialogo._iniciar_carga_analisis()
    assert inicio_carga.wait(1)
    latidos = []
    reloj = QTimer()
    reloj.timeout.connect(lambda: latidos.append(perf_counter()))
    reloj.start(1)
    inicio = perf_counter()
    dialogo.analysis_lane_combo.setCurrentIndex(
        dialogo.analysis_lane_combo.findData("mid")
    )
    dialogo.analysis_lane_combo.setCurrentIndex(
        dialogo.analysis_lane_combo.findData("jungle")
    )
    dialogo.analysis_rank_combo.setCurrentIndex(
        dialogo.analysis_rank_combo.findData("diamond")
    )
    despacho_ms = (perf_counter() - inicio) * 1000
    for _ in range(100):
        aplicacion.processEvents()
    assert dialogo._worker_analisis.isRunning()
    QTimer.singleShot(0, lambda: latidos.append(perf_counter()))
    aplicacion.processEvents()
    assert latidos
    liberar.set()
    limite = perf_counter() + 3
    while perf_counter() < limite and (
        dialogo._worker_analisis is not None or dialogo._carga_pendiente
    ):
        aplicacion.processEvents()
    reloj.stop()
    assert dialogo._active_variant["role"] == "jungle"
    assert dialogo._active_variant["rank"] == "diamond"
    assert dialogo.status.text() == "Análisis actualizado"
    assert len(hilos) == 2
    assert all(hilo != threading.get_ident() for hilo in hilos)
    assert dialogo.analysis_loading_bar.isHidden()
    print(
        f"Filtros rápidos: {despacho_ms:.2f} ms; workers: {len(hilos)}; latidos Qt: {len(latidos)}"
    )


def test_render_sin_red(
    dialogo: LocalAnalysisDialog, perfil: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ejercita widgets reales, runas y charts sin ninguna operación de red en Qt."""
    import requests

    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("Red en UI")))
    datos = {
        "perfil": perfil,
        "variante": {"role": "support"},
        "recomendaciones": [],
        "objetos": {},
        "metadatos": {},
        "rutas": {},
        "imagenes": {},
    }
    inicio = perf_counter()
    dialogo._recibir_analisis(
        dialogo._generacion_analisis, dialogo._active_variant_key, datos
    )
    assert dialogo._current_profile["character"] == "Prueba"
    assert dialogo.status.text() == "Análisis actualizado"
    assert dialogo._pixmap_analisis(Path("inexistente")).isNull()
    assert dialogo._recurso_analisis("ability", "Prueba", "Q") is None
    dialogo._update_rune_page_selection()
    dialogo._refresh_analysis()
    assert dialogo._carga_pendiente
    print(f"Renderizado real aislado: {(perf_counter() - inicio) * 1000:.2f} ms")


def test_worker_error_y_cierre(
    dialogo: LocalAnalysisDialog,
    servicio: AnalisisLocalService,
    perfil: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifica errores del worker, cancelación y cierre sin destruir un hilo activo."""
    monkeypatch.setattr(
        servicio, "cargar", Mock(side_effect=ValueError("detalle privado"))
    )
    worker = AnalisisLocalWorker(servicio, 4, "clave", perfil, "mid", "diamond", {})
    errores = []
    worker.analisis_fallido.connect(
        lambda generacion, clave: errores.append((generacion, clave))
    )
    worker.run()
    assert errores == [(4, "clave")]
    monkeypatch.setattr(servicio, "cargar", Mock(side_effect=InterruptedError()))
    worker.run()
    assert len(errores) == 1
    dialogo._worker_analisis = Mock()
    evento = QCloseEvent()
    dialogo.closeEvent(evento)
    assert not evento.isAccepted()
    dialogo._worker_analisis.requestInterruption.assert_called_once()
    dialogo._terminar_carga_analisis()
    assert dialogo._worker_analisis is None


def test_medicion_comparativa(
    dialogo: LocalAnalysisDialog, perfil: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Compara renderizado real con iconos síncronos simulados de 10 ms y con memoria."""
    consultas = []
    datos = {
        "perfil": perfil,
        "variante": {"role": "support"},
        "recomendaciones": [],
        "objetos": {},
        "metadatos": {},
        "rutas": {},
        "imagenes": {},
    }
    recurso_memoria = dialogo._recurso_analisis

    def recurso_lento(tipo: str, nombre: object, *argumentos: object) -> None:
        """Simula la latencia de un recurso que antes se descargaba en el hilo gráfico."""
        consultas.append((tipo, nombre))
        threading.Event().wait(0.01)

    monkeypatch.setattr(dialogo, "_recurso_analisis", recurso_lento)
    inicio = perf_counter()
    dialogo._recibir_analisis(
        dialogo._generacion_analisis, dialogo._active_variant_key, datos
    )
    antes = (perf_counter() - inicio) * 1000
    monkeypatch.setattr(dialogo, "_recurso_analisis", recurso_memoria)
    inicio = perf_counter()
    dialogo._recibir_analisis(
        dialogo._generacion_analisis, dialogo._active_variant_key, datos
    )
    despues = (perf_counter() - inicio) * 1000
    assert consultas
    assert antes > despues
    dialogo._limpiar_estado_analisis(dialogo._generacion_analisis - 1)
    assert dialogo.status.text() == "Análisis actualizado"
    dialogo._limpiar_estado_analisis(dialogo._generacion_analisis)
    assert not dialogo.status.text()
    print(
        f"Escenario controlado (10 ms/recurso, {len(consultas)} consultas): antes {antes:.2f} ms, ahora {despues:.2f} ms"
    )


def test_actualizacion_manual_no_borra_matriz(
    dialogo: LocalAnalysisDialog, servicio: AnalisisLocalService, perfil: dict
) -> None:
    """Comprueba invalidación manual sin destruir la matriz recién actualizada."""
    servicio.variantes.repositorio.guardar(
        "Prueba",
        RepositorioCampeones.documento(
            perfil,
            {
                "diamond": {
                    "support": {"role": "support", "most_played_build": ["Espada"]}
                }
            },
        ),
    )
    ruta = servicio.variantes.path_for("Prueba")
    anterior = dialogo._servicio_analisis
    dialogo._on_winrate_finished(1, 1)
    assert ruta.exists()
    assert dialogo._servicio_analisis is not anterior
    assert dialogo._carga_pendiente
    assert dialogo.champion_combo.isEnabled()
    dialogo._fallar_analisis(dialogo._generacion_analisis, dialogo._active_variant_key)
    assert dialogo.update_single_champ_btn.isEnabled()
    assert dialogo.update_winrates_btn.isEnabled()


def test_helpers_recursos(
    dialogo: LocalAnalysisDialog, aplicacion: QApplication, tmp_path: Path
) -> None:
    """Ejercita tarjetas, retratos y caché de pixmaps con bytes ya preparados."""
    from app.services.synergy_recommendation_service import ItemRecommendation

    ruta = tmp_path / "icono.png"
    imagen = QPixmap(8, 8)
    imagen.fill()
    imagen.save(str(ruta))
    dialogo._imagenes_recursos[str(ruta)] = ruta.read_bytes()
    for tipo, nombre in [
        ("item", "1"),
        ("rune", "Conqueror"),
        ("spell", "Destello"),
        ("champion", "Prueba"),
        ("ability", "Prueba|Q"),
    ]:
        dialogo._rutas_recursos[tipo, nombre] = ruta
    assert not dialogo._pixmap_analisis(ruta).isNull()
    assert dialogo._pixmap_analisis(ruta) is dialogo._pixmap_analisis(ruta)
    assert dialogo._ability_pixmap("Prueba", "Q", 16) is not None
    assert dialogo._rune_selection("Conqueror") is not None
    assert dialogo._rune_row("RUNA", "Conqueror", "Precision") is not None
    assert dialogo._item_cell("Espada", "1") is not None
    catalogo = dialogo._catalog_items()["items"]
    assert dialogo._clean_item_row("Espada", catalogo, "16.17.1") is not None
    assert dialogo._clean_item_card_large("Espada", catalogo, "16.17.1") is not None
    assert dialogo._clean_spell_row("Destello", "16.17.1") is not None
    assert dialogo._clean_spell_card_large("Destello", "16.17.1") is not None
    recomendacion = ItemRecommendation("1", "Espada", 1.0, (), ())
    dialogo.bar.iconos_preparados = {"1": dialogo._pixmap_analisis(ruta)}
    dialogo.bar.set_values([("Espada", 1.0, "1")])
    assert not dialogo.bar.grab().isNull()
    assert dialogo._core_item_card(recomendacion, 1) is not None
    assert (
        dialogo._create_matchup_card("Prueba", 0.5, 0.5, "", is_counter=True)
        is not None
    )


def test_error_manual_y_render(
    dialogo: LocalAnalysisDialog, perfil: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comprueba restauración manual y cierre de carga si el renderizado falla."""
    dialogo._on_winrate_error("detalle técnico")
    assert dialogo.champion_combo.isEnabled()
    assert dialogo.analysis_rank_combo.isEnabled()
    assert dialogo.analysis_lane_combo.isEnabled()
    monkeypatch.setattr(
        dialogo, "_renderizar_analisis", Mock(side_effect=ValueError("fallo interno"))
    )
    datos = {"perfil": perfil, "variante": {}, "rutas": {}, "imagenes": {}}
    dialogo._recibir_analisis(
        dialogo._generacion_analisis, dialogo._active_variant_key, datos
    )
    assert "No se pudo mostrar" in dialogo.status.text()
    assert "fallo interno" not in dialogo.status.text()
    assert dialogo.analysis_loading_bar.isHidden()
    assert dialogo.update_single_champ_btn.isEnabled()
    assert dialogo.updatesEnabled()


def test_ausencia_oculta_datos(dialogo: LocalAnalysisDialog, perfil: dict) -> None:
    """No muestra datos de filtros anteriores cuando falta una combinación local."""
    datos = {
        "perfil": perfil,
        "variante": {"role": "support"},
        "recomendaciones": [],
        "objetos": {},
        "metadatos": {},
        "rutas": {},
        "imagenes": {},
    }
    dialogo._recibir_analisis(
        dialogo._generacion_analisis, dialogo._active_variant_key, datos
    )
    dialogo._recibir_analisis(
        dialogo._generacion_analisis,
        dialogo._active_variant_key,
        {"estado": EstadoDatos.SIN_DATOS_LOCALES.value},
    )
    assert not dialogo._current_profile
    assert all(componente.isHidden() for componente in dialogo._secciones_analisis)
    assert "No hay datos guardados" in dialogo.status.text()
    assert dialogo.update_single_champ_btn.isEnabled()
    assert not dialogo.update_single_champ_btn.isHidden()
    assert not dialogo.analysis_lane_combo.isHidden()
    assert dialogo.analysis_loading_bar.isHidden()


def test_actualizador_duplicado_y_cierre(dialogo: LocalAnalysisDialog) -> None:
    """Evita segundo trabajo manual y espera cancelación del actualizador al cerrar."""
    actualizador = Mock()
    actualizador.isRunning.return_value = True
    dialogo._winrate_worker = actualizador
    dialogo._start_winrate_update("Prueba")
    assert dialogo.status.text() == "Actualización en curso"
    evento = QCloseEvent()
    dialogo.closeEvent(evento)
    assert not evento.isAccepted()
    actualizador.cancel.assert_called_once()
    actualizador.isRunning.return_value = False
    dialogo._terminar_actualizacion()
    assert dialogo._winrate_worker is None
    actualizador.deleteLater.assert_called_once()


def test_worker_actualizacion_responde(
    aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El actualizador bloqueado deja procesar eventos Qt y publica totales reales al terminar."""
    from app.ui.champion_scraper_worker import ChampionScraperWorker

    iniciado = threading.Event()
    liberar = threading.Event()
    servicio = Mock()

    def actualizar(**parametros: object) -> tuple[int, int]:
        """Simula generación remota retenida y devuelve totales independientes de éxitos."""
        iniciado.set()
        liberar.wait(2)
        return 2, 1

    servicio.actualizar_todo.side_effect = actualizar
    monkeypatch.setattr(
        "app.ui.champion_scraper_worker.ChampionScraperService",
        lambda **parametros: servicio,
    )
    trabajador = ChampionScraperWorker()
    resultados = []
    trabajador.finished_scraping.connect(
        lambda total, exitos: resultados.append((total, exitos))
    )
    trabajador.start()
    assert iniciado.wait(1)
    eventos = []
    QTimer.singleShot(0, lambda: eventos.append(True))
    aplicacion.processEvents()
    assert eventos and trabajador.isRunning()
    liberar.set()
    assert trabajador.wait(3000)
    aplicacion.processEvents()
    assert resultados == [(2, 1)]
    trabajador.cancel()
    assert trabajador._cancelled
