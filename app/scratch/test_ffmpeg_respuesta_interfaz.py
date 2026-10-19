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
        capture_window_title="League of Legends (TM) Client",
    )

    assert orden[orden.index("-filter_complex_threads") + 1] == str(
        recording_service.RECORDING_FILTER_THREADS
    )
    assert orden[orden.index("-c:v") + 1] == "h264_amf"
    assert orden[orden.index("-usage") + 1] == "transcoding"
    assert orden[orden.index("-latency") + 1] == "1"
    assert orden[orden.index("-g") + 1] == str(
        recording_service.quality_fps("1080") * 2
    )
    assert orden[orden.index("-quality") + 1] == "speed"
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
        capture_window_title="League of Legends (TM) Client",
    )

    assert aplicacion.overrideCursor() is None


def test_captura_usa_duplication_del_monitor_y_encoder_amf() -> None:
    """La ruta DXGI captura un monitor y evita gdigrab/libx264."""
    orden = recording_service.build_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        output_path="partida.mp4",
        capture_window_title="League of Legends (TM) Client",
    )

    entrada = orden[orden.index("-i") + 1]
    assert entrada.startswith("ddagrab=output_idx=0:")
    assert "video_size" not in entrada
    assert "scale=-2:1080:flags=bicubic" in orden[orden.index("-filter_complex") + 1]
    assert "-f" in orden and orden[orden.index("-f") + 1] == "lavfi"
    assert "gdigrab" not in orden
    assert "libx264" not in orden


def test_monitor_dxgi_se_fija_al_indice_configurado() -> None:
    """La sesión usa siempre el monitor detectado al iniciar."""
    orden = recording_service.build_ffmpeg_command(
        ffmpeg_path="ffmpeg",
        output_path="partida.mp4",
        capture_area=(0, 0, 1920, 1080),
        monitor_index=1,
    )

    assert "ddagrab=output_idx=1:" in orden[orden.index("-i") + 1]


def test_indice_de_monitor_persistido_se_normaliza() -> None:
    """Rechaza valores corruptos y conserva selección automática."""
    assert recording_service.normalize_monitor_index("2") == 2
    assert recording_service.normalize_monitor_index(-4) == -1
    assert recording_service.normalize_monitor_index("inválido") == -1
    configuracion = recording_service.RecordingConfig.from_settings(
        {"recording_monitor_index": "1"}
    )
    assert configuracion.monitor_index == 1


def test_solo_juego_inicia_video_y_reporta_audio_no_disponible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No genera una grabación aparentemente correcta sin audio del juego."""
    from app.services.recording_service import RecordingConfig, RecordingService

    class FakeSignal:
        def connect(self, _callback) -> None:
            pass

    class FakeProcess:
        ProcessChannelMode = recording_service.QProcess.ProcessChannelMode

        def __init__(self, _parent) -> None:
            self.started = FakeSignal()
            self.errorOccurred = FakeSignal()
            self.finished = FakeSignal()
            self.readyReadStandardOutput = FakeSignal()

        def setProgram(self, _program: str) -> None:
            pass

        def setArguments(self, _arguments: list[str]) -> None:
            pass

        def setProcessChannelMode(self, _mode) -> None:
            pass

        def setProcessEnvironment(self, _environment) -> None:
            pass

        def start(self) -> None:
            pass

    servicio = RecordingService(recording_service.RecordingLibrary(tmp_path))
    servicio.ffmpeg_available = True
    servicio.ffmpeg_path = "ffmpeg"
    monkeypatch.setattr(recording_service, "QProcess", FakeProcess)
    errores: list[str] = []
    estados_audio: list[str] = []
    servicio.failed.connect(errores.append)
    servicio.audio_status.connect(estados_audio.append)
    monkeypatch.setattr(
        recording_service, "_get_game_capture_title", lambda: "League of Legends"
    )
    comandos: list[list[str]] = []
    original_builder = recording_service.build_ffmpeg_command

    def build_command(**arguments):
        command = original_builder(**arguments)
        comandos.append(command)
        return command

    monkeypatch.setattr(recording_service, "build_ffmpeg_command", build_command)

    iniciado = servicio.start(
        RecordingConfig(enabled=True, output_dir=tmp_path, audio_mode="game")
    )

    assert iniciado
    assert not errores
    assert estados_audio and "capturador de audio por proceso" in estados_audio[0]
    assert "Audio no inicializado" in caplog.text
    assert "no se sustituirá por audio del sistema" in caplog.text
    assert comandos
    assert "-an" in comandos[0]
    assert "dshow" not in comandos[0]
    assert "ddagrab=" in comandos[0][comandos[0].index("-i") + 1]
