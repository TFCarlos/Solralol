"""Pruebas de integración de puntuaciones finales con ambos historiales."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.services.home_history_service import (
    HomeHistoryRepository,
    cross_reference_saved_matches,
)
from app.services.resumen_rendimiento_historial import (
    asegurar_puntuacion_guardada,
    etiqueta_puntuacion,
    puntuacion_historial_vigente,
    resumen_puntuacion_local,
)
from app.services.servicio_puntuacion_rendimiento import VERSION_PUNTUACION
from app.ui.main_window import MainWindow, TarjetaPartidaGuardada
from app.ui.sistema_visual import PALETA
from app.ui.tema import instalar_sistema_visual

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


def _sesion_final() -> dict:
    """Crea una sesión mínima con ranking final guardado para el jugador local."""
    return {
        "session_id": "sesion-12345",
        "local_player_key": "participant-local",
        "local_puuid": "account-puuid",
        "final_sync": {"status": "synced", "match_id": "EUW1_12345"},
        "performance_scoring": {
            "version": VERSION_PUNTUACION,
            "calibration_version": "2026.10",
            "state": "POSTGAME_FINAL",
            "awards_finalized": True,
            "players": [
                {
                    "participant_id": "participant-local",
                    "total": 1105,
                    "global_rank": 1,
                    "awards": ["MVP/SVP"],
                    "completeness": 1.0,
                }
            ],
        },
    }


def test_resumen_final_exige_version_completitud_y_sincronizacion() -> None:
    """Acepta solo puntuaciones vigentes y confirmadas de la identidad local."""
    session = _sesion_final()
    resumen = resumen_puntuacion_local(session)
    assert resumen is not None
    assert resumen["participant_id"] == "participant-local"
    assert resumen["points"] == 1105
    assert resumen["award"] == "MVP/SVP"
    assert etiqueta_puntuacion(resumen) == "1.105p · 1º · MVP/SVP"
    assert puntuacion_historial_vigente(resumen)
    resumen_antiguo = dict(resumen, version=VERSION_PUNTUACION - 1)
    assert not puntuacion_historial_vigente(resumen_antiguo)
    session["final_sync"]["status"] = "pending"
    assert resumen_puntuacion_local(session) is None
    session["final_sync"]["status"] = "synced"
    session["performance_scoring"]["state"] = "POSTGAME_PENDING"
    assert resumen_puntuacion_local(session) is None


def test_puntuacion_antigua_se_recalcula_y_persistible(monkeypatch) -> None:
    """Una versión obsoleta se sustituye con la salida central del motor."""
    import app.services.resumen_rendimiento_historial as modulo

    session = _sesion_final()
    session["performance_scoring"]["version"] = VERSION_PUNTUACION - 1
    ranking = {
        "version": VERSION_PUNTUACION,
        "calibration_version": "2026.10",
        "metric_sources": {},
        "finalization_state": "POSTGAME_FINAL",
        "awards_finalized": True,
        "multiplicador_duracion": 1.0,
        "players": session["performance_scoring"]["players"],
        "teams": {},
    }
    puntuar = Mock(return_value=ranking)
    monkeypatch.setattr(modulo, "puntuar_sesion", puntuar)

    assert asegurar_puntuacion_guardada(session) is True
    puntuar.assert_called_once_with(session, "postgame")
    assert resumen_puntuacion_local(session)["points"] == 1105
    assert asegurar_puntuacion_guardada(session) is False


def test_resultado_live_actual_se_recalcula_al_finalizar(monkeypatch) -> None:
    """La caché provisional LIVE no bloquea el cálculo final postpartida."""
    import app.services.resumen_rendimiento_historial as modulo

    session = _sesion_final()
    session["performance_scoring"]["state"] = "LIVE_PROVISIONAL"
    ranking = {
        "version": VERSION_PUNTUACION,
        "calibration_version": "2026.10",
        "metric_sources": {},
        "finalization_state": "POSTGAME_FINAL",
        "awards_finalized": True,
        "multiplicador_duracion": 1.0,
        "players": session["performance_scoring"]["players"],
        "teams": {},
    }
    puntuar = Mock(return_value=ranking)
    monkeypatch.setattr(modulo, "puntuar_sesion", puntuar)

    assert asegurar_puntuacion_guardada(session) is True
    puntuar.assert_called_once_with(session, "postgame")
    assert resumen_puntuacion_local(session)["state"] == "POSTGAME_FINAL"


def test_home_vincula_puntuacion_solo_con_id_de_partida_exacto() -> None:
    """No comparte puntuaciones entre partidas parecidas sin ID coincidente."""
    session = _sesion_final()
    matches = [
        {
            "game_id": "12345",
            "stable_match_id": "12345",
            "champion_name": "Briar",
            "participants": [{"puuid": "account-puuid"}],
        },
        {"game_id": "12346", "stable_match_id": "12346", "champion_name": "Briar"},
    ]
    linked = cross_reference_saved_matches(matches, [session])
    assert linked[0]["performance_summary"]["points"] == 1105
    assert linked[0]["saved_match_link"]["saved_match_id"] == "sesion-12345"
    assert linked[1].get("performance_summary") is None


def test_id_de_partida_no_comparte_puntuacion_de_otra_cuenta() -> None:
    """El ID exacto no basta si el participante local tiene otro PUUID."""
    session = _sesion_final()
    match = {
        "game_id": "12345",
        "stable_match_id": "12345",
        "participants": [{"puuid": "other-account"}],
    }
    linked = cross_reference_saved_matches([match], [session])
    assert linked[0]["saved_match_link"]["matched"] is True
    assert linked[0].get("performance_summary") is None


def test_home_usa_puuid_del_perfil_si_el_recuerdo_no_incluye_participantes() -> None:
    """El PUUID activo valida el puntaje aunque el historial sea compacto."""
    session = _sesion_final()
    match = {"game_id": "12345", "stable_match_id": "12345"}

    linked = cross_reference_saved_matches([match], [session], "account-puuid")
    assert linked[0]["performance_summary"]["points"] == 1105


def test_home_reutiliza_enlace_analizable_persistido_para_partida_antigua() -> None:
    """Las filas antiguas reutilizan el enlace de análisis ya confirmado."""
    session = _sesion_final()
    match = {
        "game_id": "legacy-game-id",
        "stable_match_id": "legacy-game-id",
        "saved_match_link": {
            "matched": True,
            "saved_match_id": "sesion-12345",
            "confidence": 1.0,
        },
    }

    linked = cross_reference_saved_matches([match], [session], "account-puuid")

    assert linked[0]["analyzable"] is True
    assert linked[0]["performance_summary"]["points"] == 1105
    assert linked[0]["saved_match_link"]["saved_match_id"] == "sesion-12345"


def test_home_reutiliza_enlace_analizable_sin_metadatos_de_confianza() -> None:
    """Un ID de sesión ya asociado basta si resuelve la partida concreta."""
    session = _sesion_final()
    match = {
        "game_id": "legacy-game-id",
        "analyzable": True,
        "saved_match_link": {"saved_match_id": "sesion-12345"},
    }

    linked = cross_reference_saved_matches([match], [session], "account-puuid")

    assert linked[0]["performance_summary"]["points"] == 1105
    assert linked[0]["saved_match_link"]["saved_match_id"] == "sesion-12345"


def test_home_acepta_puuid_de_cuenta_con_riot_id_local_si_falla_id_participante() -> (
    None
):
    """El Riot ID local valida el perfil cuando el ID oficial está mal asociado."""
    session = _sesion_final()
    session["local_puuid"] = ""
    session["players"] = {
        "participant-local": {
            "riot_id": "Marqq#BLACK",
            "official_participant_id": 7,
        }
    }
    session["riot_match"] = {
        "info": {"participants": [{"participantId": 7, "puuid": "other-account"}]}
    }
    session["performance_scoring"]["players"] = [
        {
            "participant_id": "participant-local",
            "total": 724,
            "global_rank": 2,
            "awards": [],
            "completeness": 1.0,
        }
    ]
    match = {
        "game_id": "legacy-game-id",
        "participants": [
            {"puuid": "account-puuid", "game_name": "Marqq", "tag_line": "BLACK"},
            {"puuid": "other-account", "game_name": "Enemy", "tag_line": "EUW"},
        ],
        "saved_match_link": {"saved_match_id": "sesion-12345"},
    }

    linked = cross_reference_saved_matches([match], [session], "account-puuid")

    assert linked[0]["performance_summary"]["points"] == 724
    assert linked[0]["performance_summary"]["global_rank"] == 2


def test_home_no_acepta_puuid_activo_con_riot_id_distinto_del_local() -> None:
    """La recuperación por Riot ID no filtra puntuaciones entre cuentas."""
    session = _sesion_final()
    session["local_puuid"] = ""
    session["players"] = {
        "participant-local": {
            "riot_id": "Marqq#BLACK",
            "official_participant_id": 7,
        }
    }
    session["riot_match"] = {
        "info": {"participants": [{"participantId": 7, "puuid": "other-account"}]}
    }
    match = {
        "game_id": "legacy-game-id",
        "participants": [
            {"puuid": "account-puuid", "game_name": "Different", "tag_line": "EUW"}
        ],
        "saved_match_link": {"saved_match_id": "sesion-12345"},
    }

    linked = cross_reference_saved_matches([match], [session], "account-puuid")

    assert linked[0].get("performance_summary") is None


def test_home_no_muestra_puntaje_si_el_perfil_activo_es_otra_cuenta() -> None:
    """Un ID de partida exacto no filtra puntos entre perfiles LCU."""
    linked = cross_reference_saved_matches(
        [{"game_id": "12345"}], [_sesion_final()], "different-account"
    )
    assert linked[0]["saved_match_link"]["matched"] is True
    assert linked[0].get("performance_summary") is None


def test_home_muestra_puntuacion_del_jugador_local_no_del_mvp_global() -> None:
    """El rango local se conserva aunque otro participante sea MVP."""
    session = _sesion_final()
    session["performance_scoring"]["players"] = [
        {
            "participant_id": "participant-mvp",
            "total": 1105,
            "global_rank": 1,
            "awards": ["MVP"],
            "completeness": 1.0,
        },
        {
            "participant_id": "participant-local",
            "total": 724,
            "global_rank": 2,
            "awards": [],
            "completeness": 1.0,
        },
    ]
    linked = cross_reference_saved_matches(
        [{"game_id": "12345"}], [session], "account-puuid"
    )
    summary = linked[0]["performance_summary"]
    assert summary["points"] == 724
    assert summary["global_rank"] == 2
    assert summary["award"] == ""


def test_inicio_reconcilia_partida_antigua_sin_conexion_lcu(
    aplicacion: QApplication, monkeypatch
) -> None:
    """El worker enlaza filas antiguas con sesiones locales aunque League esté cerrado."""
    import app.ui.main_window as modulo

    profile = {"puuid": "account-puuid"}
    old_match = {
        "game_id": "legacy-game-id",
        "stable_match_id": "legacy-game-id",
        "analyzable": True,
        "saved_match_link": {
            "matched": True,
            "saved_match_id": "sesion-12345",
            "confidence": 1.0,
        },
    }
    matches = [
        {"game_id": str(indice), "stable_match_id": str(indice)} for indice in range(40)
    ]
    matches[30] = old_match
    session = _sesion_final()

    class Repository:
        """Repositorio local mínimo para el ensayo offline."""

        def load_last_profile(self):
            """Devuelve el perfil persistido."""
            return profile

        def load(self, _profile):
            """Devuelve todo el historial, incluidos los registros antiguos."""
            return {
                "matches": [dict(partida) for partida in matches],
                "last_sync": "saved",
            }

        def merge(self, _profile, matches):
            """Devuelve la lista reconciliada sin recortar el historial."""
            return {"matches": matches, "last_sync": "saved"}

    class Provider:
        """Proveedor sin conexión durante el ensayo."""

        def synchronize(self, _repository, _progress):
            """Simula que League Client no está disponible."""
            raise ConnectionError("offline")

    class Tracker:
        """Lector de las partidas guardadas localmente."""

        def __init__(self, *_args, **_kwargs):
            """Acepta la configuración del worker sin iniciar servicios."""

        def load_saved_sessions(self):
            """Devuelve la sesión postgame existente."""
            return [session]

        def _save_sessions(self, _sessions):
            """No necesita persistir cambios en esta prueba."""

    monkeypatch.setattr(modulo, "HomeHistoryRepository", Repository)
    monkeypatch.setattr(modulo, "LCUHomeProvider", Provider)
    monkeypatch.setattr(modulo, "LiveMatchTracker", Tracker)
    monkeypatch.setattr(MainWindow, "__init__", lambda self, *args, **kwargs: None)
    window = MainWindow()
    window.home_profile = profile
    window.item_catalog = Mock()
    window.version = "16.20"

    result = window.synchronize_home_background()

    assert result["connection"] == "offline"
    assert result["history"]["matches"][30]["performance_summary"]["points"] == 1105


def test_json_de_inicio_conserva_puntos_tras_borrar_sesion_guardada(
    tmp_path: Path,
) -> None:
    """La puntuación ligera permanece tras desaparecer la partida detallada."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-puuid"}
    performance_summary = {
        "participant_id": "participant-local",
        "points": 1105,
        "global_rank": 1,
        "award": "MVP/SVP",
        "version": VERSION_PUNTUACION,
        "state": "POSTGAME_FINAL",
        "completeness": 1.0,
    }
    first_match = {
        "game_id": "12345",
        "stable_match_id": "12345",
        "champion_name": "Briar",
        "performance_summary": performance_summary,
    }
    repository.merge(profile, [first_match])

    refreshed_without_saved_session = cross_reference_saved_matches(
        [{"game_id": "12345", "stable_match_id": "12345", "champion_name": "Briar"}],
        [],
    )
    repository.merge(profile, refreshed_without_saved_session)
    persisted = repository.load(profile)

    assert persisted["matches"][0]["performance_summary"] == performance_summary


def test_home_conserva_identidad_local_y_desglosa_premio() -> None:
    """No toma una puntuación de otro participante del mismo marcador."""
    session = _sesion_final()
    session["local_player_key"] = "otro-participante"
    assert resumen_puntuacion_local(session) is None


def test_fila_guardada_muestra_puntuacion_y_mantiene_acciones(
    aplicacion: QApplication, monkeypatch
) -> None:
    """La insignia comparte la fila sin reemplazar análisis ni sincronización."""
    monkeypatch.setattr(MainWindow, "__init__", lambda self, *args, **kwargs: None)
    window = MainWindow()
    window.data_dragon_assets = Mock()
    window.postgame_sync_in_progress = False
    window.find_recording_for_session = Mock(return_value=None)
    window.format_match_duration = MainWindow.format_match_duration
    window.format_saved_session_date = lambda value: (
        MainWindow.format_saved_session_date(window, value)
    )
    window.open_saved_game_analysis = Mock()
    session = _sesion_final()
    session.update(
        {
            "champion_name": "Briar",
            "game_mode": "CLASSIC",
            "duration": 1800,
            "events": [],
            "players": {
                "participant-local": {"role": "JUNGLE", "win": True},
                "enemy": {"role": "JUNGLE", "side": "enemy", "champion_name": "Diana"},
            },
        }
    )
    row = window.create_saved_game_row(session, recording="")
    badge = row.findChild(QLabel, "savedGamePerformance")
    assert badge is not None and badge.text() == "1.105p · 1º · MVP/SVP"
    assert {button.text() for button in row.findChildren(QPushButton)} >= {
        "Re-sincronizar",
        "Abrir análisis",
        "Eliminar",
    }
    analysis = next(
        button
        for button in row.findChildren(QPushButton)
        if button.text() == "Abrir análisis"
    )
    analysis.click()
    window.open_saved_game_analysis.assert_called_once_with(session)
    assert row.result_state == "win"


def test_home_pinta_insignia_y_mantiene_analizable(aplicacion: QApplication) -> None:
    """Muestra el mismo resultado junto a la acción ANALIZABLE existente."""
    from app.ui.home_dashboard import HomeDashboard

    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        None,
        {
            "matches": [
                {
                    "stable_match_id": "12345",
                    "game_id": "12345",
                    "result": "victory",
                    "champion_name": "Briar",
                    "analyzable": True,
                    "saved_match_link": {"saved_match_id": "sesion-12345"},
                    "performance_summary": {
                        "points": 859,
                        "global_rank": 1,
                        "award": "MVP",
                        "version": VERSION_PUNTUACION,
                        "calibration_version": "2026.10",
                        "state": "POSTGAME_FINAL",
                    },
                }
            ]
        },
        {"total": 1, "played": 1, "teammates": [], "matchups": []},
        "Local",
    )
    badge = dashboard.findChild(QLabel, "homePerformanceScore")
    analyzable = dashboard.findChild(QPushButton, "homeAnalyzableBadge")
    assert badge is not None and badge.text() == "859p · 1º · MVP"
    assert analyzable is not None and analyzable.isEnabled()
    requested: list[str] = []
    dashboard.saved_match_requested.connect(requested.append)
    analyzable.click()
    assert requested == ["sesion-12345"]
    dashboard.show()
    for ancho in (1366, 1600, 1920, 2560):
        dashboard.resize(ancho, 900)
        aplicacion.processEvents()
        assert badge.isVisible()
        assert analyzable.isVisible()
    dashboard.close()


def test_regresion_partida_analizable_riot_sincronizada_muestra_puntaje_final(
    aplicacion: QApplication,
) -> None:
    """Recorre enlace, sesión Riot, selección local y renderizado real del historial."""
    from app.ui.home_dashboard import HomeDashboard

    session = _sesion_final()
    session["players"] = {
        "participant-local": {
            "riot_id": "Marqq#BLACK",
            "official_participant_id": 1,
        }
    }
    session["local_puuid"] = ""
    session["riot_match"] = {
        "info": {"participants": [{"participantId": 1, "puuid": "wrong-derived-id"}]}
    }
    session["performance_scoring"]["players"] = [
        {
            "participant_id": "participant-mvp",
            "total": 1105,
            "global_rank": 1,
            "awards": ["MVP"],
            "completeness": 1.0,
        },
        {
            "participant_id": "participant-local",
            "total": 724,
            "global_rank": 2,
            "awards": [],
            "completeness": 1.0,
        },
    ]
    home_entry = {
        "game_id": "legacy-game-id",
        "stable_match_id": "legacy-game-id",
        "result": "victory",
        "champion_name": "Briar",
        "analyzable": True,
        "saved_match_link": {"saved_match_id": "sesion-12345"},
        "participants": [
            {"puuid": "active-account", "game_name": "Marqq", "tag_line": "BLACK"}
        ],
    }
    linked = cross_reference_saved_matches([home_entry], [session], "active-account")
    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        {"puuid": "active-account"},
        {"matches": linked},
        {"total": 1, "played": 1, "teammates": [], "matchups": []},
        "Local",
    )
    badge = dashboard.findChild(QLabel, "homePerformanceScore")
    assert badge is not None
    assert badge.text() == "724p · 2º"
    assert dashboard.findChild(QPushButton, "homeAnalyzableBadge").isEnabled()
    dashboard.close()


def test_home_oculta_puntuacion_archivada_de_version_obsoleta(
    aplicacion: QApplication,
) -> None:
    """Una puntuación archivada antigua no se presenta como resultado actual."""
    from app.ui.home_dashboard import HomeDashboard

    dashboard = HomeDashboard()
    dashboard.set_dashboard_data(
        None,
        {
            "matches": [
                {
                    "stable_match_id": "12345",
                    "game_id": "12345",
                    "analyzable": True,
                    "saved_match_link": {"saved_match_id": "sesion-12345"},
                    "performance_summary": {
                        "points": 900,
                        "global_rank": 1,
                        "award": "MVP",
                        "version": VERSION_PUNTUACION - 1,
                        "calibration_version": "2026.10",
                        "state": "POSTGAME_FINAL",
                    },
                }
            ]
        },
        {"total": 1, "played": 1, "teammates": [], "matchups": []},
        "Local",
    )
    assert dashboard.findChild(QLabel, "homePerformanceScore") is None
    assert dashboard.findChild(QPushButton, "homeAnalyzableBadge") is not None
    dashboard.close()


def test_actualizar_puntuacion_conserva_filtro_y_lote_visible(
    aplicacion: QApplication,
) -> None:
    """La llegada de puntajes no reinicia el filtro ni el lote del historial."""
    from app.ui.home_dashboard import HomeDashboard

    dashboard = HomeDashboard()
    dashboard.resize(1000, 760)
    partidas = [
        {
            "stable_match_id": str(indice),
            "game_id": str(indice),
            "mode": "normal",
            "champion_name": "Briar",
        }
        for indice in range(40)
    ]
    analitica = {"total": 40, "played": 40, "teammates": [], "matchups": []}
    dashboard.set_dashboard_data(
        None,
        {"last_sync": "a", "matches": partidas},
        analitica,
        "Local",
    )
    dashboard.show()
    aplicacion.processEvents()
    dashboard.filter_combo.setCurrentIndex(4)
    dashboard._visible_count = 40
    dashboard.render_matches()
    aplicacion.processEvents()
    barra = dashboard.history_scroll.verticalScrollBar()
    barra.setValue(barra.maximum())
    posicion = barra.value()

    actualizadas = [dict(partida) for partida in partidas]
    actualizadas[0]["performance_summary"] = {
        "points": 724,
        "global_rank": 2,
        "award": "",
    }
    dashboard.set_dashboard_data(
        None,
        {"last_sync": "b", "matches": actualizadas},
        analitica,
        "Local",
    )
    aplicacion.processEvents()

    assert dashboard.filter_combo.currentData() == "normal"
    assert dashboard._visible_count == 40
    assert barra.value() == posicion
    dashboard.close()


def test_tintes_de_resultado_y_acento_respetan_el_marco_redondeado(
    aplicacion: QApplication,
) -> None:
    """Las victorias y derrotas tiñen la tarjeta y recortan el acento."""
    instalar_sistema_visual(aplicacion)
    muestras = {}
    for resultado in ("win", "loss", "unknown"):
        tarjeta = TarjetaPartidaGuardada(resultado)
        tarjeta.setProperty("result", resultado)
        tarjeta.resize(180, 80)
        tarjeta.show()
        aplicacion.processEvents()
        imagen = tarjeta.grab().toImage()
        muestras[resultado] = (
            imagen.pixelColor(90, 40),
            imagen.pixelColor(2, 40),
            imagen.pixelColor(2, 0),
        )
        tarjeta.close()
    assert muestras["win"][0] != muestras["unknown"][0]
    assert muestras["loss"][0] != muestras["unknown"][0]
    assert muestras["win"][1].name() != muestras["unknown"][1].name()
    assert muestras["loss"][1].name() != muestras["unknown"][1].name()
    assert muestras["win"][2] != muestras["win"][1]
    assert muestras["loss"][2] != muestras["loss"][1]
    assert PALETA["superficie_victoria"] != PALETA["superficie_derrota"]
