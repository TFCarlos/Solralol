from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from app.services.resolucion_hitos_fases import (
    hitos_relevantes_fase,
    resolver_hito_fase,
)


@pytest.fixture(scope="module")
def cronologia_briar() -> dict:
    """Carga cronología de regresión con telemetría observada de Briar."""
    ruta = Path(__file__).parent / "fixtures" / "briar_regression_match.json"
    return json.loads(ruta.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("orden", "hora", "campeon"),
    ((35, "01:20", "Yasuo"), (49, "03:24", "Naafiri"), (104, "06:31", "Viktor")),
)
def test_resuelve_muertes_tempranas_con_atacante_real(
    cronologia_briar: dict, orden: int, hora: str, campeon: str
) -> None:
    """Verifica la identidad del asesino y la hora de cada baja temprana."""
    hito = resolver_hito_fase({"event_id": f"event-{orden}"}, cronologia_briar)

    assert hito["time_label"] == hora
    assert hito["title"] == f"{campeon} eliminó a Briar"
    assert hito["evidence_status"] == "confirmed"
    assert hito["event_id"] == f"event-{orden}"


def test_resuelve_referencias_antiguas_por_hora_si_es_univoca(
    cronologia_briar: dict,
) -> None:
    """Enriquece informes históricos que solo guardaban timestamp."""
    hito = resolver_hito_fase({"time_label": "03:24"}, cronologia_briar)

    assert hito["title"] == "Naafiri eliminó a Briar"
    assert hito["evidence_status"] == "confirmed"


def test_hora_ambigua_no_se_asocia_a_un_evento_incorrecto(
    cronologia_briar: dict,
) -> None:
    """Evita atribuir un hito cuando varios eventos comparten timestamp."""
    duplicado = next(
        evento
        for evento in cronologia_briar["events_chronology"]
        if evento.get("order") == 35
    ).copy()
    duplicado["order"] = 9999
    cronologia = {
        **cronologia_briar,
        "events_chronology": [*cronologia_briar["events_chronology"], duplicado],
    }
    hito = resolver_hito_fase({"time_label": "01:20"}, cronologia)

    assert hito["evidence_status"] == "ambiguous"
    assert "varios eventos" in hito["title"]
    assert "Yasuo" not in hito["title"]


@pytest.mark.parametrize(
    ("orden", "frase"),
    (
        (122, "dragón"),
        (396, "Barón Nashor"),
        (492, "inhibidor"),
    ),
)
def test_resuelve_objetivos_y_estructuras(
    cronologia_briar: dict, orden: int, frase: str
) -> None:
    """Representa objetivos y estructuras mediante sus eventos confirmados."""
    hito = resolver_hito_fase({"event_id": f"event-{orden}"}, cronologia_briar)

    assert frase.casefold() in hito["title"].casefold()
    assert hito["category"] in {"objective", "structure"}
    assert hito["time_label"]


def test_resuelve_compra_con_referencia_de_objeto(cronologia_briar: dict) -> None:
    """Conserva el identificador del objeto para mostrar su icono real."""
    compra = next(
        evento
        for evento in cronologia_briar["events_chronology"]
        if evento.get("type") == "ITEM_PURCHASED"
    )
    hito = resolver_hito_fase(
        {"event_id": f"event-{compra['order']}"}, cronologia_briar
    )

    assert hito["category"] == "purchase"
    assert hito["item_id"]
    assert "compró" in hito["title"]


def test_hito_ausente_muestra_limitacion_sin_inventar_evento() -> None:
    """Degrada una referencia no resuelta con un mensaje factual seguro."""
    hito = resolver_hito_fase({"event_id": "event-999", "time_label": "07:10"}, {})

    assert hito["title"] == "Evento registrado a las 07:10 · Detalles no disponibles"
    assert hito["evidence_status"] == "unknown"


def test_fase_sin_referencias_se_completa_con_eventos_locales(
    cronologia_briar: dict,
) -> None:
    """Incluye una selección cronológica útil para informes antiguos vacíos."""
    hitos = hitos_relevantes_fase({}, "early", cronologia_briar)

    assert hitos
    assert any("Briar" in hito["title"] for hito in hitos)
    assert all(hito["evidence_status"] == "confirmed" for hito in hitos)


def test_pestana_fases_pinta_descripciones_y_conserva_las_seis_pestanas(
    monkeypatch: pytest.MonkeyPatch, cronologia_briar: dict
) -> None:
    """Comprueba el renderizado accesible de hitos y las seis pestañas existentes."""
    from app.services.match_log_service import MatchLogService
    from app.ui.analisis_partida_ia import AnalisisPartidaIA

    aplicacion = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        MatchLogService,
        "build_match_log",
        lambda _servicio, _sesion: cronologia_briar,
    )
    analisis = {
        "schema_version": 1,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Inicio con varias bajas."},
        "game_phases": {
            "early": {
                "title": "Inicio complicado",
                "summary": "Tres muertes registradas antes del minuto siete.",
                "what_worked": "Participó en las escaramuzas.",
                "strengths": ["Participó en las escaramuzas."],
                "what_failed": "Tres muertes tempranas.",
                "mistakes": ["Tres muertes tempranas."],
                "adaptation": "Revisa los duelos previos a objetivos.",
                "recommendations": ["Revisa los duelos previos a objetivos."],
                "evidence_events": [
                    {"event_id": f"event-{orden}"} for orden in (35, 49, 104)
                ],
            },
            "mid": {
                "title": "Recuperación",
                "summary": "Briar participó en una captura aliada de Barón.",
                "evidence_events": [{"event_id": "event-396"}],
            },
            "late": {
                "title": "Cierre crítico",
                "summary": "La partida terminó tras una secuencia de bajas y objetivos.",
                "evidence_events": [
                    {"event_id": "event-492"},
                    {"event_id": "event-541"},
                ],
            },
        },
    }
    registro = {
        "saved_match_id": "fixture-briar-2026-10-08",
        "analysis_type": "general_match_analysis",
        "schema_version": 1,
        "model": "gemini-flash-lite-latest",
        "analysis": analisis,
    }
    vista = AnalisisPartidaIA(
        {"session_id": "fixture-briar-2026-10-08", "champion_name": "Briar"},
        registro,
    )
    textos = [etiqueta.text() for etiqueta in vista.findChildren(QLabel)]

    assert "Yasuo eliminó a Briar" in textos
    assert "Naafiri eliminó a Briar" in textos
    assert "Viktor eliminó a Briar" in textos
    assert any(
        "barón nashor" in texto.casefold() and "equipo aliado" in texto.casefold()
        for texto in textos
    ), textos
    assert any("inhibidor" in texto.casefold() for texto in textos)
    assert any(
        "barón nashor" in texto.casefold() and "equipo rival" in texto.casefold()
        for texto in textos
    )
    assert not any(texto.startswith("event-") for texto in textos)
    assert not any(texto == "Bien" or texto == "Siguiente paso" for texto in textos)
    assert vista.pestanas.count() == 6
    assert any(
        etiqueta.objectName() == "matchAnalysisIcon"
        for etiqueta in vista.findChildren(QLabel)
    )
    vista.show()
    vista.pestanas.setCurrentIndex(1)
    aplicacion.processEvents()
    tarjetas = vista.pestanas.widget(1).findChildren(QFrame, "matchAnalysisCard")
    assert tarjetas
    assert all(
        tarjeta.sizePolicy().verticalPolicy().name == "Preferred"
        for tarjeta in tarjetas
    )
    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        vista.resize(ancho, alto)
        aplicacion.processEvents()
        assert vista.pestanas.widget(1).isVisible()
    vista.close()
    aplicacion.processEvents()
