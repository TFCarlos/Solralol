"""Regresiones del uso de FFmpeg sin acaparar los recursos del escritorio."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import imageio_ffmpeg
import pytest

from app.services import recording_service


def test_binario_existente_se_reutiliza_sin_instalarlo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reutiliza la ruta configurada y evita buscar o descargar otra copia."""
    ejecutable = tmp_path / "ffmpeg.exe"
    ejecutable.write_bytes(b"binario de prueba")
    buscar_en_path = Mock(return_value=None)
    obtener_binario_incluido = Mock(side_effect=AssertionError("innecesario"))
    monkeypatch.setattr(recording_service.shutil, "which", buscar_en_path)
    monkeypatch.setattr(imageio_ffmpeg, "get_ffmpeg_exe", obtener_binario_incluido)

    encontrado = recording_service._search_ffmpeg(str(ejecutable))

    assert encontrado == str(ejecutable)
    obtener_binario_incluido.assert_not_called()


def test_binario_ausente_no_inicia_descargas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La detección ausente devuelve None sin iniciar una descarga externa."""
    monkeypatch.setattr(recording_service.shutil, "which", lambda _nombre: None)
    monkeypatch.setattr(
        imageio_ffmpeg, "get_ffmpeg_exe", lambda: str(tmp_path / "no-existe.exe")
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "programa"))

    encontrado = recording_service._search_ffmpeg(str(tmp_path / "missing.exe"))

    assert encontrado is None


def test_orden_limita_hilos_de_codificacion_y_filtros() -> None:
    """Limita la concurrencia de captura para mantener ágil la interfaz."""
    orden = recording_service.build_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        output_path="partida.mp4",
        quality="1080",
        video_bitrate=8000,
    )

    assert orden[orden.index("-filter_complex_threads") + 1] == str(
        recording_service.RECORDING_FILTER_THREADS
    )
    assert orden[orden.index("-threads:v") + 1] == str(
        recording_service.RECORDING_ENCODER_THREADS
    )
    assert recording_service.RECORDING_ENCODER_THREADS <= 8


def test_inicio_usa_cache_de_audio_sin_sondeo_sincrono(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El inicio puede reutilizar dispositivos guardados sin lanzar FFmpeg."""
    ruta = "ffmpeg-cache-prueba"
    monkeypatch.setitem(
        recording_service._AUDIO_DEVICE_CACHE,
        ruta,
        (0.0, ("Micrófono de prueba",)),
    )

    dispositivos = recording_service.obtener_dispositivos_audio_cacheados(ruta)

    assert dispositivos == ["Micrófono de prueba"]


def test_iniciar_sin_ffmpeg_listo_no_hace_una_busqueda_sincrona(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Evita recorrer rutas desde la interfaz si aún no terminó el worker."""
    from app.services.recording_service import RecordingConfig, RecordingService

    buscar_ffmpeg = Mock(side_effect=AssertionError("búsqueda síncrona"))
    monkeypatch.setattr(recording_service, "find_ffmpeg", buscar_ffmpeg)
    servicio = RecordingService(recording_service.RecordingLibrary(tmp_path))
    errores: list[str] = []
    servicio.failed.connect(errores.append)

    iniciado = servicio.start(RecordingConfig(output_dir=tmp_path, enabled=True))

    assert not iniciado
    assert errores and "segundo plano" in errores[0]
    buscar_ffmpeg.assert_not_called()


def test_inicio_de_captura_no_cambia_el_cursor_global() -> None:
    """La creación de órdenes de captura no toma posesión del cursor Qt."""
    from PySide6.QtWidgets import QApplication

    aplicacion = QApplication.instance() or QApplication([])
    assert aplicacion.overrideCursor() is None

    recording_service.build_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        output_path="partida.mp4",
    )

    assert aplicacion.overrideCursor() is None
