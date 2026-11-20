"""Headless recording lifecycle used by Electron.

The existing recording module remains the source of FFmpeg configuration,
DXGI capture, validation and library semantics. This adapter owns FFmpeg in a
dedicated subprocess and monitors the actual League game window without Qt.
"""
from __future__ import annotations

import logging
import base64
import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.recording_service import (
    RecordingConfig,
    RecordingLibrary,
    build_ffmpeg_command,
    find_ffmpeg,
    find_game_window,
    _monitor_area_of_window,
    _monitor_index_of_window,
    validar_contenedor_mp4,
    audio_mode_uses_mic,
    audio_mode_uses_system,
    audio_mode_uses_game,
    list_audio_devices,
    pick_microphone_device,
    pick_system_audio_device,
    sanitize_filename_part,
)
from app.services.storage_manager import atomic_write_bytes, get_storage_manager

LOG = logging.getLogger(__name__)
_ENCODER_CACHE: dict[str, tuple[float, tuple[str, ...]]] = {}
_ENCODER_PROBE_CACHE: dict[str, tuple[float, tuple[str, ...], dict[str, str]]] = {}


def _available_encoders(ffmpeg: str) -> tuple[str, ...]:
    """Prefer hardware encoders compiled into FFmpeg, then a CPU fallback."""
    now = time.monotonic()
    cached = _ENCODER_CACHE.get(ffmpeg)
    if cached and now - cached[0] < 600:
        return cached[1]
    try:
        result = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=8,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        output = result.stdout + result.stderr
        listed = {parts[1] for line in output.splitlines() if len(parts := line.split()) >= 2}
        available = tuple(name for name in ("h264_amf", "h264_nvenc", "h264_qsv", "h264_mf", "libx264")
                          if name in listed)
    except (OSError, subprocess.SubprocessError):
        available = ()
    _ENCODER_CACHE[ffmpeg] = (now, available)
    return available


def _probe_encoders(ffmpeg: str) -> tuple[tuple[str, ...], dict[str, str]]:
    """Smoke-test listed encoders, including their device/driver initialization."""
    now = time.monotonic()
    cached = _ENCODER_PROBE_CACHE.get(ffmpeg)
    if cached and now - cached[0] < 300:
        return cached[1], dict(cached[2])
    working: list[str] = []
    failures: dict[str, str] = {}
    for encoder in _available_encoders(ffmpeg):
        command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   "color=c=black:s=128x128:r=2", "-frames:v", "1", "-pix_fmt", "yuv420p",
                   "-c:v", encoder, "-f", "null", "-"]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=4,
                                    check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                working.append(encoder)
            else:
                failures[encoder] = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()[-700:]
        except (OSError, subprocess.SubprocessError) as error:
            failures[encoder] = str(error)[:700]
    _ENCODER_PROBE_CACHE[ffmpeg] = (now, tuple(working), dict(failures))
    return tuple(working), failures


def _validate_capture_output(ffmpeg: str, path: Path) -> bool:
    """Require a finalized MP4 plus decodable, non-black samples at both ends."""
    try:
        if not path.is_file() or path.stat().st_size <= 2048 or not validar_contenedor_mp4(path):
            return False
        black_results: list[bool] = []
        for start in (True, False):
            command = [ffmpeg, "-hide_banner", "-v", "info"]
            if not start:
                command.extend(["-sseof", "-4"])
            command.extend(["-i", str(path)])
            if start:
                command.extend(["-t", "4"])
            command.extend(["-map", "0:v:0", "-vf", "blackdetect=d=3:pix_th=0.02:pic_th=0.98", "-an", "-f", "null", "-"])
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=12, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                return False
            detail = result.stderr or ""
            black_results.append(any(float(value) >= 3.5 for value in re.findall(r"black_duration:([0-9.]+)", detail)))
        return not all(black_results)
    except (OSError, subprocess.SubprocessError, ValueError):
        LOG.exception("No se pudo validar el contenido capturado de %s", path.name)
        return False


class RecordingRuntime:
    """One backend-wide monitor and one FFmpeg process at most."""

    def __init__(self, settings_service: Any) -> None:
        self.settings = settings_service
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self._closing = False
        self._close_started = False
        self._closed = False
        self.thumbnail_lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.output_path: Path | None = None
        self.started_at: datetime | None = None
        self.state = "inactive"
        self.recording_automatic = False
        self.active_monitor_index = -1
        self.game_monitor_index = -1
        self.active_capture_area: tuple[int, int, int, int] | None = None
        self.active_encoder = ""
        self._watch_thread: threading.Thread | None = None
        self.failed_encoders: set[str] = set()
        self.next_auto_retry = 0.0
        self.auto_paused_after_failure = False
        self.validation_failures = 0
        self._settings_signature: tuple[Any, ...] | None = None
        self.stop_reason = ""
        self.active_session_id: str | None = None
        self.live_metadata: dict[str, str] = {}
        self.message = "Grabación automática preparada; esperando League of Legends."
        self.last_error = ""
        self.ffmpeg_diagnostic = ""
        self.storage_paused = False
        self._monitor_thread = threading.Thread(target=self._monitor, name="recording-monitor")
        self._monitor_thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            elapsed = max(0, int((datetime.now(UTC) - self.started_at).total_seconds())) if self.started_at else 0
            try:
                current_size = self.output_path.stat().st_size if self.output_path and self.output_path.is_file() else 0
            except OSError:
                current_size = 0
            return {"state": self.state, "message": self.message, "error": self.last_error,
                    "elapsedSeconds": elapsed, "recordingName": self.output_path.name if self.output_path else None,
                    "fileSizeBytes": current_size, "sessionId": self.active_session_id,
                    "currentChampion": self.live_metadata.get("champion", ""),
                    "currentGameMode": self.live_metadata.get("gameMode", ""),
                    "currentRole": self.live_metadata.get("role", ""),
                    "gameMonitorIndex": self.game_monitor_index}

    def associate_live_session(self, session_id: str | None, metadata: dict[str, Any] | None = None) -> None:
        """Attach the current live session to the one active FFmpeg capture."""
        with self.lock:
            if self.process is not None and session_id:
                self.active_session_id = str(session_id)[:160]
                if isinstance(metadata, dict):
                    self.live_metadata = {key: str(metadata.get(source) or "")[:80]
                                          for key, source in (("champion", "champion"), ("gameMode", "gameMode"), ("role", "role"))}

    def start_manual(self) -> dict[str, Any]:
        return self._start(automatic=False)

    def stop_manual(self) -> dict[str, Any]:
        return self._stop("Detenida manualmente")

    def thumbnail(self, name: str) -> dict[str, Any]:
        """Create/reuse a small first-frame thumbnail without touching video."""
        saved = self.settings.load()
        config = RecordingConfig.from_settings(saved)
        library = RecordingLibrary(config.output_dir)
        if not name or Path(name).name != name or Path(name).suffix.casefold() not in {".mp4", ".mkv"}:
            raise ValueError("Identificador de grabación no válido.")
        source = (library.directory / name).resolve()
        if source.parent != library.directory.resolve() or not source.is_file():
            return {"state": "unavailable", "data": None}
        try:
            stat = source.stat()
        except OSError:
            return {"state": "unavailable", "data": None}
        key = hashlib.sha256(str(source).casefold().encode("utf-8")).hexdigest()
        cache_dir = get_storage_manager().recording_thumbnails_dir
        cache = cache_dir / f"{key}.{stat.st_size:x}.{stat.st_mtime_ns:x}.jpg"
        if cache.is_file():
            try:
                return {"state": "ready", "data": base64.b64encode(cache.read_bytes()).decode("ascii")}
            except OSError:
                pass
        with self.lock:
            if self.process is not None and self.output_path == source:
                return {"state": "deferred", "data": None}
            if self.state in {"preparing", "recording", "stopping", "finalizing"}:
                return {"state": "deferred", "data": None}
        # Limit thumbnail work to one file at a time and keep it away from the
        # active capture session. Calls run on the backend RPC worker, never UI.
        with self.thumbnail_lock:
            if cache.is_file():
                try:
                    return {"state": "ready", "data": base64.b64encode(cache.read_bytes()).decode("ascii")}
                except OSError:
                    pass
            with self.lock:
                if self.state in {"preparing", "recording", "stopping", "finalizing"}:
                    return {"state": "deferred", "data": None}
            ffmpeg = find_ffmpeg(config.ffmpeg_path)
            if not ffmpeg:
                return {"state": "unavailable", "data": None}
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Detect an initial black interval and seek to its first valid end;
            # otherwise frame zero is the loading screen and is kept intact.
            scan = subprocess.run(
                [ffmpeg, "-hide_banner", "-v", "info", "-t", "90", "-i", str(source),
                 "-map", "0:v:0", "-an", "-vf", "blackdetect=d=0.1:pix_th=0.04:pic_th=0.98",
                 "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=45, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if scan.returncode != 0:
                return {"state": "unavailable", "data": None}
            frame_at = 0.0
            detail = scan.stderr or ""
            starts = re.findall(r"black_start:([0-9.]+)", detail)
            ends = re.findall(r"black_end:([0-9.]+)", detail)
            if starts and ends and float(starts[0]) <= 0.02:
                frame_at = float(ends[0]) + 0.02
            temporary = cache.with_name(f".{cache.stem}.{uuid.uuid4().hex}.tmp.jpg")
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{frame_at:.3f}",
                 "-i", str(source), "-map", "0:v:0", "-frames:v", "1", "-vf", "scale='min(480,iw)':-2",
                 "-q:v", "5", "-y", str(temporary)], stdin=subprocess.DEVNULL,
                capture_output=True, timeout=18, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size < 128:
                temporary.unlink(missing_ok=True)
                return {"state": "unavailable", "data": None}
            atomic_write_bytes(cache, temporary.read_bytes())
            temporary.unlink(missing_ok=True)
            for old in cache_dir.glob(f"{key}.*.jpg"):
                if old != cache:
                    old.unlink(missing_ok=True)
            return {"state": "ready", "data": base64.b64encode(cache.read_bytes()).decode("ascii")}

    def _monitor(self) -> None:
        absent_since: float | None = None
        while not self.stop_event.wait(2.5):
            try:
                if self.storage_paused:
                    if self.process is not None:
                        self._stop("Pausa temporal para trasladar los datos de Solralol")
                    continue
                settings = self.settings.load()
                signature = tuple(str(settings.get(key, "")) for key in (
                    "ffmpeg_path", "recording_output_dir", "recording_quality", "recording_bitrate",
                    "recording_audio_mode", "recording_mic_device", "recording_system_audio_device"))
                if signature != self._settings_signature:
                    self._settings_signature = signature
                    self.failed_encoders.clear()
                    self.validation_failures = 0
                    self.auto_paused_after_failure = False
                if not settings.get("recording_auto", True):
                    if self.process is not None and self.recording_automatic:
                        self._stop("Grabación automática desactivada")
                    continue
                game = find_game_window()
                if game:
                    absent_since = None
                    monitor = _monitor_index_of_window(game[0])
                    with self.lock:
                        self.game_monitor_index = max(0, int(monitor))
                    area = _monitor_area_of_window(game[0])
                    changed_display = monitor != self.active_monitor_index or (area and self.active_capture_area and area[2:] != self.active_capture_area[2:])
                    if self.process is not None and self.recording_automatic and changed_display:
                        self._stop("League cambió de monitor o resolución; cerrando el segmento para reiniciar la captura.")
                    elif self.process is None and not self.auto_paused_after_failure and time.monotonic() >= self.next_auto_retry:
                        self._start(automatic=True, game=game)
                    elif self.process is not None and self.output_path and shutil.disk_usage(self.output_path.parent).free < 256 * 1024 * 1024:
                        self.auto_paused_after_failure = True
                        self._stop("Espacio en disco insuficiente; se detuvo la captura para finalizar el MP4.")
                elif self.process is not None and self.recording_automatic:
                    absent_since = absent_since or time.monotonic()
                    # Brief window transitions are common; require a sustained
                    # disappearance before closing the MP4.
                    if time.monotonic() - absent_since >= 12:
                        self._stop("La sesión de juego ha terminado")
                else:
                    absent_since = None
            except Exception:
                LOG.exception("Fallo en el supervisor de grabación")
                with self.lock:
                    self.last_error = "No se pudo comprobar el estado de League of Legends."
                    if self.state != "recording": self.state = "failed"

    def _start(self, *, automatic: bool, game: tuple[int, int, str] | None = None) -> dict[str, Any]:
        with self.lock:
            if self._closing or self.process is not None or self.state == "preparing":
                return self.snapshot()
            self.state, self.last_error = "preparing", ""
            self.message = "Preparando captura DXGI del monitor…"
            self.stop_reason = ""
        try:
            saved = self.settings.load()
            config = RecordingConfig.from_settings(saved)
            if automatic and not config.enabled:
                with self.lock: self.state = "inactive"
                return self.snapshot()
            ffmpeg = find_ffmpeg(config.ffmpeg_path, force=True)
            if not ffmpeg:
                raise RuntimeError("No se encontró FFmpeg. Revisa la configuración de Grabaciones.")
            library = RecordingLibrary(config.output_dir)
            directory = library.ensure_directory()
            if shutil.disk_usage(directory).free < 512 * 1024 * 1024:
                if automatic: self.auto_paused_after_failure = True
                raise RuntimeError("Quedan menos de 512 MB libres en la carpeta de grabaciones.")
            started_at = datetime.now().astimezone()
            title_part = sanitize_filename_part("") or "Partida"
            output = directory / f"{title_part} - {started_at.strftime('%Y-%m-%d_%H-%M')}.mp4"
            suffix = 2
            while output.exists():
                output = directory / f"{title_part} - {started_at.strftime('%Y-%m-%d_%H-%M')} ({suffix}).mp4"
                suffix += 1
            monitor = _monitor_index_of_window(game[0]) if game else max(0, config.monitor_index)
            capture_area = _monitor_area_of_window(game[0]) if game else None
            mode = config.audio_mode
            audio_devices = list_audio_devices(ffmpeg) if audio_mode_uses_mic(mode) or audio_mode_uses_system(mode) else []
            mic = ""
            if audio_mode_uses_mic(mode):
                mic = config.mic_device if config.mic_device in audio_devices else pick_microphone_device(audio_devices)
            system = ""
            if audio_mode_uses_system(mode):
                preferred = config.effective_system_audio_device
                system = preferred if preferred in audio_devices else pick_system_audio_device(audio_devices, exclude={mic})
            # Per-process League loopback is not available; never substitute a
            # different source for a mode explicitly requesting game audio.
            encoders, probe_failures = _probe_encoders(ffmpeg)
            encoder = next((item for item in encoders if item not in self.failed_encoders), "")
            if not encoder:
                if automatic: self.auto_paused_after_failure = True
                details = "; ".join(f"{name}: {detail}" for name, detail in probe_failures.items())
                self.ffmpeg_diagnostic = details[:1200]
                raise RuntimeError("No se pudo iniciar un codificador H.264. " + (details[:900] if details else "FFmpeg no anuncia codificadores compatibles."))
            cmd = build_ffmpeg_command(ffmpeg_path=ffmpeg, output_path=output, quality=config.quality,
                video_bitrate=config.video_bitrate, mic_device=mic, system_audio_device=system,
                capture_desktop=True, monitor_index=monitor, video_encoder=encoder)
            with self.lock:
                if self._closing:
                    self.state = "inactive"
                    self.message = "Cierre de la aplicación."
                    return self.snapshot()
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
                    cwd=str(Path(ffmpeg).parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.process, self.output_path = proc, output
                self.active_session_id = None
                self.live_metadata = {}
                self.started_at = started_at.astimezone(UTC)
                self.recording_automatic = automatic
                self.active_monitor_index = monitor
                self.active_capture_area = capture_area
                self.active_encoder = encoder
                self.state = "preparing"
                audio_note = " El audio del juego por proceso no está disponible; se respeta la fuente de audio configurada." if audio_mode_uses_game(mode) else ""
                encoder_note = " (codificación por CPU de respaldo)" if encoder == "libx264" else " (codificación por hardware)"
                self.message = f"Iniciando captura DXGI del monitor {monitor + 1}{encoder_note}.{audio_note}"
            self._watch_thread = threading.Thread(target=self._watch_process, args=(proc, output, config, automatic, ffmpeg),
                name="recording-ffmpeg-watch")
            self._watch_thread.start()
            return self.snapshot()
        except Exception as error:
            LOG.exception("No se pudo iniciar la grabación")
            with self.lock:
                self.state, self.last_error, self.message = "failed", str(error), str(error)
                if automatic:
                    self.next_auto_retry = time.monotonic() + 15
            return self.snapshot()

    def _watch_process(self, proc: subprocess.Popen[str], output: Path, config: RecordingConfig, automatic: bool, ffmpeg: str) -> None:
        saw_frame = False
        diagnostic_lines: list[str] = []
        try:
            if proc.stdout:
                for line in proc.stdout:
                    if line.strip():
                        diagnostic_lines.append(line.strip()[:500])
                        del diagnostic_lines[:-8]
                    if line.startswith("frame=") and line.split("=", 1)[1].strip().isdigit():
                        saw_frame = int(line.split("=", 1)[1].strip()) > 0
                        if saw_frame:
                            with self.lock:
                                if self.process is proc: self.state = "recording"
                    if "Error" in line or "error" in line:
                        LOG.warning("FFmpeg recording: %s", line.strip()[:400])
            code = proc.wait()
        except Exception:
            LOG.exception("Error leyendo la salida de FFmpeg")
            code = proc.poll() if proc.poll() is not None else -1
        valid = code == 0 and saw_frame and _validate_capture_output(ffmpeg, output)
        with self.lock:
            if self.process is not proc: return
            started = self.started_at or datetime.now(UTC)
            self.process = None
            self.output_path = None
            self.started_at = None
            self.recording_automatic = False
            self.active_capture_area = None
            if valid:
                elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())
                metadata_written = RecordingLibrary(config.output_dir).write_metadata(output, {
                    "schema_version": 1, "started_at": started.isoformat(), "ended_at": datetime.now(UTC).isoformat(),
                    "duration_seconds": elapsed, "complete": True, "stopped_cleanly": True,
                    "capture_backend": "FFmpeg DXGI Desktop Duplication", "encoder": self.active_encoder,
                    "monitor_index": max(0, self.active_monitor_index), "automatic": automatic,
                    **({"session_id": self.active_session_id} if self.active_session_id else {}),
                })
                if metadata_written:
                    RecordingLibrary(config.output_dir).enforce_storage_limit(config.size_limit_bytes, keep_path=output)
                    suffix = f" Motivo: {self.stop_reason}." if self.stop_reason else ""
                    self.state, self.message, self.last_error = "completed", "Grabación finalizada, validada y añadida a la biblioteca." + suffix, ""
                else:
                    self.state, self.message = "failed", "El vídeo es reproducible, pero no se pudieron guardar sus metadatos. El archivo se conservó."
                    self.last_error = self.message
            else:
                if self.active_encoder and (code != 0 or not saw_frame):
                    self.failed_encoders.add(self.active_encoder)
                self.ffmpeg_diagnostic = "\n".join(diagnostic_lines)[-1600:]
                self.next_auto_retry = time.monotonic() + (1.0 if automatic and not saw_frame else 15.0)
                self.validation_failures += 1
                available = _available_encoders(ffmpeg)
                exhausted_encoders = bool(available) and len(self.failed_encoders) >= len(available)
                invalid_capture_repeated = code == 0 and saw_frame and self.validation_failures >= 2
                if automatic and (exhausted_encoders or invalid_capture_repeated):
                    self.auto_paused_after_failure = True
                self.state, self.message = "failed", "La grabación no se finalizó o no pasó la validación del MP4."
                technical = self.ffmpeg_diagnostic.strip()
                self.last_error = (self.message + (" Detalle FFmpeg: " + technical[-900:] if technical else f" CÃ³digo de salida: {code}; fotogramas recibidos: {'sÃ­' if saw_frame else 'no'}."))[:1200]
            self.active_session_id = None
            self.live_metadata = {}

    def _stop(self, reason: str) -> dict[str, Any]:
        with self.lock:
            proc = self.process
            if proc is None:
                if self.state not in {"failed", "completed"}: self.state, self.message = "inactive", reason
                return self.snapshot()
            if self.state in {"stopping", "finalizing"}:
                return self.snapshot()
            self.state, self.message = "stopping", reason
            self.stop_reason = reason
        try:
            if proc.stdin:
                proc.stdin.write("q\n"); proc.stdin.flush()
            with self.lock: self.state = "finalizing"
            proc.wait(timeout=18)
        except (OSError, subprocess.TimeoutExpired):
            try: proc.terminate(); proc.wait(timeout=4)
            except Exception: proc.kill()
        return self.snapshot()

    def close(self) -> None:
        with self.lock:
            if self._close_started or self._closed:
                return
            self._close_started = True
            self._closing = True
        LOG.info("[Shutdown] Stopping recording monitor and finalizing FFmpeg")
        self.stop_event.set()
        self._stop("Cierre de Solralol")
        with self.lock:
            proc = self.process
            watcher = self._watch_thread
        if proc:
            try: proc.wait(timeout=18)
            except subprocess.TimeoutExpired:
                try: proc.terminate(); proc.wait(timeout=3)
                except Exception:
                    proc.kill()
                    try: proc.wait(timeout=2)
                    except subprocess.TimeoutExpired: LOG.error("[Shutdown] FFmpeg pid=%s could not be reaped after kill", proc.pid)
        if watcher and watcher is not threading.current_thread():
            watcher.join(timeout=30)
            if watcher.is_alive():
                LOG.error("[Shutdown] FFmpeg finalization worker did not finish within 30 seconds")
        monitor = self._monitor_thread
        if monitor is not threading.current_thread():
            monitor.join(timeout=12)
            if monitor.is_alive():
                LOG.error("[Shutdown] Recording monitor did not finish within 12 seconds")
        with self.lock:
            self._closed = True

