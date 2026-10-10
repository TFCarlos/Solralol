"""Regresiones del inicio, el cierre y la prueba diagnóstica de grabación."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import recording_service


def test_fin_anormal_de_ffmpeg_no_se_publica_como_grabacion_finalizada(
    tmp_path: Path,
) -> None:
    """Un proceso FFmpeg con salida errónea conserva el archivo y avisa."""

    class ProcesoFalso:
        def readAllStandardOutput(self) -> bytes:
            return b"gdigrab: Error grabbing"

        def deleteLater(self) -> None:
            pass

    servicio = recording_service.RecordingService(
        recording_service.RecordingLibrary(tmp_path)
    )
    salida = tmp_path / "fallida.mp4"
    salida.write_bytes(b"partial")
    servicio.process = ProcesoFalso()
    servicio.output_path = salida
    servicio.stop_requested = True
    finalizadas: list[str] = []
    errores: list[str] = []
    servicio.finished.connect(finalizadas.append)
    servicio.failed.connect(errores.append)

    servicio._on_process_finished(1, "CrashExit")

    assert not finalizadas
    assert errores and "código 1" in errores[0]
    assert "gdigrab: Error grabbing" in errores[0]
    assert salida.exists()


def test_prueba_sin_juego_valida_monitor_principal_sin_afirmar_gameplay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La prueba distingue la falta de ventana de errores de encoder/audio."""
    binario = tmp_path / "ffmpeg.exe"
    binario.write_bytes(b"falso")
    llamadas = 0

    def ejecutar(*args, **kwargs):
        nonlocal llamadas
        llamadas += 1
        comando = args[0]
        if any("ddagrab=" in str(argumento) for argumento in comando):
            Path(comando[-1]).write_bytes(b"v" * 4096)
            return recording_service.subprocess.CompletedProcess(
                comando,
                0,
                stdout="frame=120\n",
                stderr=(
                    "Duration: 00:00:04.00\nOutput #0, mp4\nStream #0:0: Video: h264\n"
                ),
            )
        return recording_service.subprocess.CompletedProcess(
            comando, 0, stdout="", stderr="Duration: 00:00:04.00"
        )

    monkeypatch.setattr(recording_service, "find_game_window", lambda: None)
    monkeypatch.setattr(recording_service.subprocess, "run", ejecutar)

    resultado = recording_service.run_recording_diagnostic(
        recording_service.RecordingConfig(output_dir=tmp_path), str(binario)
    )

    assert resultado["stage"] == "completada"
    assert resultado["video_ok"]
    assert "no se validó gameplay" in resultado["message"]
    assert llamadas == 3


def test_prueba_valida_video_decodificado_de_ventana_identificada(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La prueba requiere frames codificados y decodificación correcta."""
    binario = tmp_path / "ffmpeg.exe"
    binario.write_bytes(b"falso")
    llamadas = 0

    def ejecutar(*args, **kwargs):
        nonlocal llamadas
        llamadas += 1
        comando = args[0] if args else kwargs["args"]
        if any("ddagrab=" in str(argumento) for argumento in comando):
            Path(comando[-1]).write_bytes(b"v" * 4096)
            return recording_service.subprocess.CompletedProcess(
                comando,
                0,
                stdout="frame=120\n",
                stderr=(
                    "Input #0, mov,mp4\nDuration: 00:00:04.00\n"
                    "Output #0, mp4\nStream #0:0: Video: h264, yuv420p\n"
                ),
            )
        if "blackdetect" in comando:
            return recording_service.subprocess.CompletedProcess(
                comando, 0, stdout="", stderr=""
            )
        return recording_service.subprocess.CompletedProcess(
            comando, 0, stdout="", stderr=""
        )

    monkeypatch.setattr(
        recording_service, "find_game_window", lambda: (123, 456, "LoL Match")
    )
    monkeypatch.setattr(recording_service.subprocess, "run", ejecutar)

    resultado = recording_service.run_recording_diagnostic(
        recording_service.RecordingConfig(
            output_dir=tmp_path,
            audio_mode="none",
            quality="540",
        ),
        str(binario),
    )

    assert resultado["video_ok"]
    assert not resultado["audio_ok"]
    assert resultado["frames"] == 120
    assert resultado["duration_seconds"] == 4
    assert resultado["hwnd"] == 123
    assert llamadas == 3


def test_estado_grabando_se_publica_al_recibir_frame_de_ffmpeg(
    tmp_path: Path,
) -> None:
    """Abrir QProcess no marca grabación hasta que llega frame mayor que cero."""

    class ProcesoFalso:
        def readAllStandardOutput(self) -> bytes:
            return b"frame=  1\n"

    servicio = recording_service.RecordingService(
        recording_service.RecordingLibrary(tmp_path)
    )
    servicio.process = ProcesoFalso()
    servicio.output_path = tmp_path / "en-curso.mp4"
    iniciadas: list[str] = []
    servicio.started.connect(iniciadas.append)

    servicio._on_process_output()

    assert servicio.is_recording
    assert iniciadas == [str(tmp_path / "en-curso.mp4")]


def test_inicio_manual_comparte_servicio_aunque_se_desactive_el_automatico(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El inicio manual usa el motor común aunque el automático esté apagado."""

    class SenalFalsa:
        def connect(self, _callback) -> None:
            pass

    class ProcesoFalso:
        class ProcessChannelMode:
            MergedChannels = object()

        started = SenalFalsa()
        errorOccurred = SenalFalsa()
        finished = SenalFalsa()
        readyReadStandardOutput = SenalFalsa()

        def __init__(self, _parent=None) -> None:
            self.arguments: list[str] = []

        def setProgram(self, _program: str) -> None:
            pass

        def setArguments(self, arguments: list[str]) -> None:
            self.arguments = arguments

        def setProcessChannelMode(self, _mode) -> None:
            pass

        def setProcessEnvironment(self, _environment) -> None:
            pass

        def start(self) -> None:
            pass

    class EntornoFalso:
        @staticmethod
        def systemEnvironment():
            return EntornoFalso()

        def insert(self, _key: str, _value: str) -> None:
            pass

        def value(self, _key: str, default: str = "") -> str:
            return default

    monkeypatch.setattr(recording_service, "QProcess", ProcesoFalso)
    monkeypatch.setattr(recording_service, "QProcessEnvironment", EntornoFalso)
    monkeypatch.setattr(
        recording_service, "_get_game_capture_title", lambda: "LoL Match"
    )
    monkeypatch.setattr(recording_service, "find_game_capture_area", lambda: None)

    servicio = recording_service.RecordingService(
        recording_service.RecordingLibrary(tmp_path)
    )
    servicio.ffmpeg_available = True
    servicio.ffmpeg_path = str(tmp_path / "ffmpeg.exe")
    configuracion = recording_service.RecordingConfig(
        output_dir=tmp_path,
        enabled=False,
        audio_mode="none",
    )

    assert servicio.start(configuracion, recording_source="manual")
    assert servicio.recording_source == "manual"
    assert servicio.is_starting_or_recording


def test_parada_publica_estado_finalizando(
    tmp_path: Path,
) -> None:
    """La interfaz recibe estado de finalización al pedir detener."""

    class ProcesoFalso:
        def write(self, _data: bytes) -> None:
            pass

    servicio = recording_service.RecordingService(
        recording_service.RecordingLibrary(tmp_path)
    )
    servicio.process = ProcesoFalso()
    estados: list[str] = []
    servicio.state_changed.connect(estados.append)

    assert servicio.stop(reason="manual")
    assert servicio.stop_requested
    assert estados == ["stopping"]


def test_validador_rechaza_mp4_interrumpido_sin_atom_moov(
    tmp_path: Path,
) -> None:
    """Un encabezado con mdat sin tabla final no pasa como salida válida."""
    interrumpido = tmp_path / "interrumpido.mp4"
    interrumpido.write_bytes(
        b"\x00\x00\x00\x10ftypisomiso2" + b"\x00\x00\x00\x00mdat" + b"datos parciales"
    )
    finalizado = tmp_path / "finalizado.mp4"
    finalizado.write_bytes(b"\x00\x00\x00\x0cftypisom" + b"\x00\x00\x00\x08moov")

    assert not recording_service.validar_contenedor_mp4(interrumpido)
    assert recording_service.validar_contenedor_mp4(finalizado)


def test_cierre_pospuesto_se_reanuda_al_finalizar_grabacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La ventana solo vuelve a cerrarse al quedar inactivo el servicio."""
    from PySide6.QtWidgets import QApplication, QMainWindow

    from app.ui import main_window

    QApplication.instance() or QApplication([])
    ventana = main_window.MainWindow.__new__(main_window.MainWindow)
    QMainWindow.__init__(ventana)
    ventana._close_after_recording_finalizes = True
    cerrada = Mock()
    ventana.close = cerrada
    monkeypatch.setattr(
        main_window.QTimer,
        "singleShot",
        lambda _delay, callback: callback(),
    )

    ventana._close_after_recording_state_change("recording")
    assert not cerrada.called
    ventana._close_after_recording_state_change("idle")

    cerrada.assert_called_once_with()
    assert not ventana._close_after_recording_finalizes
