from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton
from pytest import MonkeyPatch

from app.services.live_match_tracker import LiveMatchTracker
from app.services.match_ai_analyzer_service import MatchAIAnalyzerService
from app.services.match_review_ai_service import (
    ESQUEMA_REVISION_IA,
    MatchReviewAIService,
)
from app.services.recording_service import RecordingLibrary
from app.ui.postgame_ai_review import PostgameAIReview
from app.ui.postgame_replay_window import PostgameReplayWindow
from app.ui.postgame_sidebar import PostgameSidebar


def _sesion_ia() -> dict[str, Any]:
    """Prepara una sesiÃƒÂ³n pequeÃƒÂ±a con sucesos verificables del jugador local."""
    return {
        "session_id": "session-review-1",
        "champion_name": "Briar",
        "game_mode": "CLASSIC",
        "duration": 600,
        "local_player_key": "local-1",
        "local_team": "ORDER",
        "winning_team": "ORDER",
        "game_version": "15.16.1",
        "final_sync": {"match_id": "EUW1_12345", "status": "synced"},
        "players": {
            "local-1": {
                "champion_name": "Briar",
                "team": "ORDER",
                "role": "JUNGLE",
                "participant_id": 1,
                "win": True,
                "kills": 2,
                "deaths": 1,
                "assists": 3,
                "cs_total": 110,
            },
            "enemy-1": {
                "champion_name": "Ahri",
                "team": "CHAOS",
                "role": "MIDDLE",
            },
        },
        "events": [
            {
                "event_id": "kill-verified-1",
                "type": "kill_exact",
                "time": 120,
                "killer_key": "local-1",
                "victim_key": "enemy-1",
                "team": "ORDER",
            },
            {
                "event_id": "objective-verified-1",
                "type": "objective",
                "time": 180,
                "objective": "Dragon",
                "team": "ORDER",
            },
        ],
        "performance_scoring": {
            "players": [{"participant_id": "local-1", "total": 87}]
        },
    }


def _informe(event_id: str = "kill-verified-1") -> dict[str, Any]:
    """Devuelve un informe estructurado mÃƒÂ­nimo para probar validaciÃƒÂ³n y UI."""
    return {
        "summary": {
            "coverage_note": "El registro permite varios momentos verificables.",
            "overall_assessment": "Briar participÃƒÂ³ en una baja registrada.",
            "main_strength": "ParticipaciÃƒÂ³n confirmada en combate.",
            "main_improvement": "Revisar la conversiÃƒÂ³n posterior del mapa.",
            "turning_points": ["La eliminaciÃƒÂ³n de 02:00."],
        },
        "insights": [
            {
                "id": "briar-kill-1",
                "category": "standout",
                "evaluation": "good",
                "title": "ParticipaciÃƒÂ³n en una eliminaciÃƒÂ³n",
                "description": "Briar eliminÃƒÂ³ a un campeÃƒÂ³n rival segÃƒÂºn el registro.",
                "recommendation": "Revisa quÃƒÂ© ventaja concreta siguiÃƒÂ³ a la jugada.",
                "what_happened": "Briar eliminó a Ahri a 02:00.",
                "player_contribution": "El log confirma a Briar como autora de la baja.",
                "why_this_rating": "La eliminación redujo el número de rivales.",
                "consequence": "El equipo obtuvo superioridad numérica momentánea.",
                "learning": "Revisa si el equipo aprovechó la ventana creada.",
                "match_timestamp_seconds": 120,
                "related_event_ids": [event_id, "objective-verified-1"],
                "confidence": "high",
                "evidence": "El registro atribuye la baja a Briar a 02:00.",
            }
        ],
    }


def test_prepare_input_prioriza_campeon_local_y_conserva_hechos() -> None:
    """El paquete incluye mÃƒÂ©tricas, match ID y cronologÃƒÂ­a sin identidades."""
    payload, fingerprint = MatchReviewAIService().prepare_input(_sesion_ia())

    assert payload["match_id"] == "EUW1_12345"
    assert payload["player"]["champion"] == "Briar"
    assert payload["player"]["participant_id"] == "1"
    assert payload["player"]["battlescore"] == 87
    assert payload["events"][0]["event_id"] == "kill-verified-1"
    assert payload["events"][0]["killer"] == "Briar"
    assert payload["events"][0]["victim"] == "Ahri"
    assert payload["events"][0]["player_involved"] is True
    assert len(fingerprint) == 64
    assert "recording_id" not in payload


def test_validacion_descarta_eventos_y_tiempos_que_no_pertenecen_al_log() -> None:
    """Solo conserva observaciones enlazadas a timestamps del registro."""
    service = MatchReviewAIService()
    payload, _ = service.prepare_input(_sesion_ia())
    report = _informe()
    report["insights"].append(
        {
            **_informe()["insights"][0],
            "id": "falso",
            "match_timestamp_seconds": 500,
            "related_event_ids": ["id-inventado"],
        }
    )

    result = service.validate_report(report, payload)

    assert len(result["insights"]) == 1
    assert result["insights"][0]["related_event_ids"] == [
        "kill-verified-1",
        "objective-verified-1",
    ]
    assert result["insights"][0]["perspective"] == "player"


def test_analisis_reutiliza_cliente_gemini_y_esquema_configurado(
    monkeypatch: MonkeyPatch,
) -> None:
    """El nuevo anÃƒÂ¡lisis usa el transporte existente y su esquema propio."""
    captured: dict[str, Any] = {}

    def fake_call(
        _self: MatchAIAnalyzerService,
        prompt: str,
        api_key: str,
        schema: dict[str, Any] | None = None,
        system_instruction: str = "",
        max_output_tokens: int = 8192,
    ) -> tuple[str, str]:
        captured.update(
            prompt=prompt,
            api_key=api_key,
            schema=schema,
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
        )
        import json

        return json.dumps(_informe()), "modelo-configurado"

    monkeypatch.setattr(MatchAIAnalyzerService, "_call_gemini_api", fake_call)
    report, model, fingerprint = MatchReviewAIService().analyze_match(
        _sesion_ia(), "clave-configurada"
    )

    assert captured["api_key"] == "clave-configurada"
    assert captured["schema"] == ESQUEMA_REVISION_IA
    assert captured["max_output_tokens"] == 16384
    assert "Briar" in captured["prompt"]
    assert "datos no confiables" in captured["system_instruction"].casefold()
    assert model == "modelo-configurado"
    assert len(report["insights"]) == 1
    assert fingerprint


def test_tracker_persiste_el_informe_en_la_partida_canonica(tmp_path: Path) -> None:
    """El informe queda unido a la sesiÃƒÂ³n que se elimina como conjunto."""
    tracker = LiveMatchTracker(item_catalog={}, persist=False)
    tracker.sessions_path = tmp_path / "sessions.json"
    tracker._sessions_cache = []
    tracker._sessions_cache_stamp = tracker._path_stamp()
    tracker._save_sessions(
        [{"session_id": "session-review-1", "other_metadata": "keep"}]
    )
    registro = {
        "schema_version": 2,
        "saved_match_id": "session-review-1",
        "analysis": _informe(),
    }

    tracker.guardar_revision_ia("session-review-1", registro)

    guardada = tracker.load_saved_sessions()[0]
    assert guardada["ai_match_review"] == registro
    assert guardada["ai_match_review"]["schema_version"] == 2
    assert guardada["other_metadata"] == "keep"


def test_tarjeta_de_momento_emite_timestamp_y_resalta_sin_recargar(
    monkeypatch: MonkeyPatch,
) -> None:
    """Pulsar la marca solicita seek y conserva la tarjeta seleccionada."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "app.ui.postgame_ai_review.get_champion_icon_path",
        lambda *_args, **_kwargs: None,
    )
    view = PostgameAIReview()
    session = _sesion_ia()
    session["ai_match_review"] = {
        "source_fingerprint": MatchReviewAIService().prepare_input(session)[1],
        "analysis": {
            **MatchReviewAIService().validate_report(
                _informe(), MatchReviewAIService().prepare_input(session)[0]
            ),
            "no_useful_evidence": False,
        },
    }
    view.set_session(session)
    moments = []
    view.seek_requested.connect(moments.append)
    timestamp = view.findChild(QPushButton, "postgameAIInsightTimestamp")

    assert timestamp is not None
    timestamp.click()

    assert moments == [120.0]
    assert view._selected_card is not None
    assert view._selected_card.property("seleccionado") is True
    toggle = view.findChild(QPushButton, "postgameAIInsightToggle")
    assert toggle is not None and not toggle.isChecked()
    toggle.click()
    assert toggle.isChecked()
    assert view.report_count.text().startswith("1 jugadas analizadas")
    view.close()
    app.processEvents()


def test_ventana_reemplaza_analisis_live_y_conserva_las_otras_pestanas(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """La revisión expone Marcador, Revisión y la nueva experiencia IA."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", lambda _self: None)
    window = PostgameReplayWindow(
        session=_sesion_ia(), library=RecordingLibrary(tmp_path)
    )
    tabs = window.sidebar.tabs
    labels = [tabs.tabText(index) for index in range(tabs.count())]

    assert labels[0] == "Marcador"
    assert labels[1].startswith("Revisión")
    assert labels[2] == "Análisis con IA"
    assert not any("LIVE" in label for label in labels)
    assert isinstance(window.ai_review_view, PostgameAIReview)
    assert window.ai_review_view.champion_title.text() == "Análisis de Briar"
    window.close()
    app.processEvents()


def test_valida_jugadas_ampliadas_sin_limitar_lista_y_fases() -> None:
    """Conserva todas las jugadas completas ligadas a eventos reales."""
    service = MatchReviewAIService()
    session = _sesion_ia()
    session["duration"] = 1800
    session["events"] = [
        {
            "event_id": f"evt-{index}",
            "type": "kill_exact",
            "time": index * 120,
            "killer_key": "local-1",
            "victim_key": "enemy-1",
        }
        for index in range(1, 15)
    ] + [
        {
            "event_id": f"obj-{index}",
            "type": "objective",
            "time": index * 120 + 1,
            "objective": "Dragon",
            "team": "ORDER",
        }
        for index in range(1, 15)
    ]
    payload, _fingerprint = service.prepare_input(session)
    report = _informe()
    report["insights"] = [
        {
            **_informe()["insights"][0],
            "id": f"play-{index}",
            "match_timestamp_seconds": index * 120,
            "related_event_ids": [f"evt-{index}", f"obj-{index}"],
        }
        for index in range(1, 15)
    ]

    result = service.validate_report(report, payload)

    assert len(result["insights"]) == 14
    assert result["insights"][0]["evaluation"] == "good"
    assert result["insights"][-1]["match_timestamp_seconds"] == 1680


def test_validador_descarta_rating_y_secuencia_invalidos() -> None:
    """Rechaza ratings desconocidos y finales anteriores al inicio."""
    service = MatchReviewAIService()
    payload, _fingerprint = service.prepare_input(_sesion_ia())
    report = _informe()
    report["insights"][0]["evaluation"] = "maybe"

    assert service.validate_report(report, payload)["insights"] == []


def test_formatea_segundos_y_normaliza_prosa_sin_cambiar_estadisticas() -> None:
    """Corrige tiempos textuales y mantiene intactas las métricas numéricas."""
    service = MatchReviewAIService()

    assert service.formatear_timestamp(77.7) == "01:17"
    assert service.formatear_timestamp(629.9) == "10:29"
    assert service.formatear_timestamp(767.1) == "12:47"
    assert service.formatear_timestamp(3600) == "01:00:00"
    fixed = service.normalizar_tiempos_informe(
        {
            "summary": {"overall_assessment": "Briar elimina en el minuto 767.1."},
            "insights": [
                {
                    "what_happened": "Entre el minuto 629.9 y 640.1.",
                    "evidence": "La partida duró 33 minutos y obtuvo 1500 de oro.",
                    "match_timestamp_seconds": 767.1,
                }
            ],
        },
        2000,
    )

    assert fixed["summary"]["overall_assessment"] == "Briar elimina en el 12:47."
    assert fixed["insights"][0]["what_happened"] == "Entre el 10:29 y el 10:40."
    assert "33 minutos" in fixed["insights"][0]["evidence"]
    assert "1500 de oro" in fixed["insights"][0]["evidence"]
    assert fixed["insights"][0]["match_timestamp_seconds"] == 767.1


def test_secuencias_objetivo_enlazan_hechos_anteriores_sin_causalidad() -> None:
    """Incluye hechos reales próximos al objetivo y limita su interpretación."""
    service = MatchReviewAIService()
    payload, _fingerprint = service.prepare_input(_sesion_ia())

    sequence = payload["objective_sequences"][0]

    assert sequence["event_ids"] == [
        "kill-verified-1",
        "objective-verified-1",
    ]
    assert sequence["player_participation"] is True
    assert "no prueba causalidad" in sequence["causality_note"]
