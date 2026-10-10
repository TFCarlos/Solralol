"""Regresiones para ordenación robusta de la biblioteca de grabaciones."""

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.services.recording_service import RecordingLibrary, RecordingService
from app.ui.recordings_page import RecordingsPage


@pytest.fixture(scope="module")
def aplicacion() -> QApplication:
    """Crea la aplicación Qt necesaria para las pruebas de la página."""
    return QApplication.instance() or QApplication([])


def _entrada(
    nombre: str,
    score: object = None,
    fecha: float = 0.0,
    *,
    incluir_score: bool = True,
    match: object = None,
    duracion: object = 0,
    tamano: object = 0,
) -> dict:
    """Genera una entrada pequeña de biblioteca para una prueba."""
    saved_match = match if match is not None else {}
    if incluir_score and isinstance(saved_match, dict):
        saved_match = {**saved_match, "battle_score": score}
    return {
        "name": nombre,
        "title": nombre,
        "champion": nombre,
        "game_mode": "CLASSIC",
        "summary": "",
        "created_at": fecha,
        "duration": duracion,
        "size_bytes": tamano,
        "path": Path(nombre),
        "saved_match": saved_match,
        "markers": [],
    }


def test_battlescore_ordena_numeros_cero_y_ausentes_al_final() -> None:
    """Ordena puntuaciones válidas de mayor a menor y conserva las ausentes."""
    entradas = [
        _entrada("score-671", 671, 30),
        _entrada("score-none", None, 100),
        _entrada("score-zero", 0, 20),
        _entrada("score-string", "750", 40),
        _entrada("score-invalid", "invalid", 90),
        _entrada("score-950", 950, 10),
        _entrada("score-empty", "", 80),
        _entrada("score-missing", incluir_score=False, fecha=70),
        _entrada("score-corrupt", match=["saved_match"], fecha=60),
    ]

    ordenadas = RecordingsPage._sort_recording_entries(entradas, 2)

    assert [item["name"] for item in ordenadas[:4]] == [
        "score-950",
        "score-string",
        "score-671",
        "score-zero",
    ]
    assert [item["name"] for item in ordenadas[4:]] == [
        "score-none",
        "score-invalid",
        "score-empty",
        "score-missing",
        "score-corrupt",
    ]


def test_battlescore_empatado_usa_fecha_y_luego_nombre() -> None:
    """Desempata puntuaciones iguales con fecha reciente y nombre."""
    entradas = [
        _entrada("B", 671, 10),
        _entrada("C", 671, 20),
        _entrada("A", 671, 20),
    ]

    ordenadas = RecordingsPage._sort_recording_entries(entradas, 2)

    assert [item["name"] for item in ordenadas] == ["A", "C", "B"]


def test_otros_ordenes_admiten_datos_ausentes_y_malformados() -> None:
    """Mantiene disponibles todas las entradas en cada modo de ordenación."""
    entradas = [
        _entrada(
            "sin-datos",
            incluir_score=False,
            fecha="inválida",
            duracion=None,
            tamano="bad",
        ),
        _entrada("larga", 10, 5, duracion="120", tamano="500"),
        _entrada("corta", 20, 15, duracion=30, tamano=100),
    ]

    assert [
        item["name"] for item in RecordingsPage._sort_recording_entries(entradas, 0)
    ] == [
        "corta",
        "larga",
        "sin-datos",
    ]
    assert [
        item["name"] for item in RecordingsPage._sort_recording_entries(entradas, 1)
    ] == [
        "larga",
        "corta",
        "sin-datos",
    ]
    assert [
        item["name"] for item in RecordingsPage._sort_recording_entries(entradas, 3)
    ] == [
        "larga",
        "corta",
        "sin-datos",
    ]
    assert [
        item["name"] for item in RecordingsPage._sort_recording_entries(entradas, 4)
    ] == [
        "larga",
        "corta",
        "sin-datos",
    ]


def test_filtros_no_eliminan_grabaciones_al_ordenar_score(
    aplicacion: QApplication, tmp_path: Path
) -> None:
    """Combina filtros con scores incompletos sin mutar la biblioteca."""
    biblioteca = RecordingLibrary(tmp_path)
    pagina = RecordingsPage(biblioteca, RecordingService(biblioteca))
    ahora = time.time()
    pagina.entries = [
        _entrada("Briar reciente", 671, ahora - 60),
        _entrada("Briar sin score", None, ahora - 30),
        _entrada("Briar victoria", 950, ahora - 90),
        _entrada("ChoGath", 1000, ahora - 90),
    ]
    pagina.entries[0]["saved_match"]["win"] = False
    pagina.entries[1]["saved_match"]["win"] = False
    pagina.entries[2]["saved_match"]["win"] = True
    pagina.entries[3]["saved_match"]["win"] = True
    pagina.entries[3]["game_mode"] = "ARAM"
    original_count = len(pagina.entries)
    pagina.search_input.setText("Briar")
    pagina.result_filter.setCurrentIndex(2)
    pagina.date_filter.setCurrentIndex(1)
    pagina.sort_filter.setCurrentIndex(2)

    resultados = pagina._filtered_entries()

    assert [item["name"] for item in resultados] == [
        "Briar reciente",
        "Briar sin score",
    ]
    assert len(pagina.entries) == original_count
    assert pagina.current_path is None

    pagina.result_filter.setCurrentIndex(1)
    assert [item["name"] for item in pagina._filtered_entries()] == ["Briar victoria"]
    pagina.result_filter.setCurrentIndex(0)
    pagina.search_input.setText("CLASSIC")
    assert [item["name"] for item in pagina._filtered_entries()] == [
        "Briar victoria",
        "Briar reciente",
        "Briar sin score",
    ]
    assert len(pagina.entries) == original_count
    pagina.player.stop()
    pagina.close()


def test_datos_guardados_corruptos_no_rompen_busqueda_y_orden(
    aplicacion: QApplication, tmp_path: Path
) -> None:
    """Tolera un saved_match no diccionario durante filtros y ordenación."""
    biblioteca = RecordingLibrary(tmp_path)
    pagina = RecordingsPage(biblioteca, RecordingService(biblioteca))
    pagina.entries = [
        _entrada("Briar corrupta", match=["corrupto"], fecha=2),
        _entrada("Briar válida", 0, fecha=1),
    ]
    pagina.search_input.setText("Briar")
    pagina.sort_filter.setCurrentIndex(2)

    resultados = pagina._filtered_entries()

    assert [item["name"] for item in resultados] == [
        "Briar válida",
        "Briar corrupta",
    ]
    pagina.player.stop()
    pagina.close()


def test_fallo_inesperado_de_ordenacion_registra_diagnostico_y_conserva_entradas(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Usa el orden seguro y deja diagnóstico si el extractor falla inesperadamente."""
    entradas = [_entrada("B"), _entrada("A")]

    def fallar(_entry: dict[str, object]) -> None:
        """Provoca un fallo inesperado al normalizar fechas."""
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(RecordingsPage, "_sort_timestamp", staticmethod(fallar))

    ordenadas = RecordingsPage._sort_recording_entries(entradas, 0)

    assert ordenadas == entradas
    assert "Falló la ordenación" in caplog.text
    assert "Falló también el orden seguro" in caplog.text
