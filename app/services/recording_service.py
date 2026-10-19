"""Grabación de partidas y biblioteca local de grabaciones.

El vídeo usa FFmpeg con Desktop Duplication (DXGI) y codificación AMD AMF
H.264. El monitor se fija al iniciar, usando League of Legends.exe cuando
está visible y el monitor elegido como alternativa. DirectShow no aísla el
audio del juego; el modo Solo juego se diagnostica como no disponible.

El módulo sólo depende de Qt en ``RecordingService``, que usa ``QProcess``
para no bloquear la interfaz mientras dura la grabación. Todo lo demás
(presets, orden de ffmpeg, marcadores y gestión de la carpeta) son funciones
puras que se pueden probar sin interfaz ni partidas reales.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Presets de calidad y bitrate (Ajustes → Grabaciones)
# --------------------------------------------------------------------------

#: Resoluciones disponibles: de 1080p a 420p. La altura fija la escala y el
#: ancho se calcula solo (-2) para no deformar la imagen.
QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "1080": {"label": "1080p · 60 FPS", "height": 1080, "fps": 60},
    "108030": {"label": "1080p · 30 FPS", "height": 1080, "fps": 30},
    "900": {"label": "900p · 60 FPS", "height": 900, "fps": 60},
    "90030": {"label": "900p · 30 FPS", "height": 900, "fps": 30},
    "720": {"label": "720p · 60 FPS", "height": 720, "fps": 60},
    "72030": {"label": "720p · 30 FPS", "height": 720, "fps": 30},
    "540": {"label": "540p · 30 FPS", "height": 540, "fps": 30},
    "480": {"label": "480p · 30 FPS", "height": 480, "fps": 30},
    "420": {"label": "420p · 30 FPS", "height": 420, "fps": 30},
}

DEFAULT_QUALITY = "1080"

#: Bitrate de vídeo en kbps.
BITRATE_PRESETS: dict[int, str] = {
    16000: "16 Mbps (máxima)",
    12000: "12 Mbps (muy alta)",
    8000: "8 Mbps (alta)",
    6000: "6 Mbps (recomendada)",
    4000: "4 Mbps (media)",
    2500: "2,5 Mbps (baja)",
    1500: "1,5 Mbps (mínima)",
}

DEFAULT_BITRATE = 8000

#: Límites de concurrencia para que la grabación no monopolice los núcleos.
RECORDING_ENCODER_THREADS = 8
RECORDING_FILTER_THREADS = 4

#: El audio (partida + micrófono) siempre se codifica igual: es lo que menos
#: pesa y AAC a 160 kbps es más que suficiente para el juego.
AUDIO_BITRATE_KBPS = 160

#: Ajustes de audio de DirectShow: menos búfer = menos desfase con el vídeo.
AUDIO_BUFFER_MS = 100

#: Cuánto se recuerda la lista de dispositivos de audio de ffmpeg. Sondeos
#: repetidos (Ajustes, inicio de partida, inicio de grabación) sumaban varios
#: segundos de espera en el hilo de la interfaz sin cambiar el resultado.
AUDIO_DEVICE_CACHE_SECONDS = 120.0

_AUDIO_DEVICE_CACHE: dict[str, tuple[float, tuple[str, ...]]] = {}

#: Cuánto se recuerda el resultado de buscar ffmpeg en el sistema.
FFMPEG_LOOKUP_CACHE_SECONDS = 60.0

_FFMPEG_CACHE: dict[str, tuple[float, str | None]] = {}

LIMIT_MIN_GB = 1
LIMIT_MAX_GB = 500
LIMIT_DEFAULT_GB = 50

#: Nombres habituales de las fuentes de audio que capturan el sonido del
#: sistema en Windows (mezcla estéreo, capturadores virtuales, etc.).
GAME_AUDIO_HINTS = (
    "stereo mix",
    "mezcla estéreo",
    "mezcla estereo",
    "what u hear",
    "loopback",
    "virtual-audio-capturer",
    "cable output",
    "wave out mix",
)

MIC_HINTS = (
    "microphone",
    "micrófono",
    "mic ",
    "(mic",
    "headset",
    "auricular",
    "webcam",
)

#: Dispositivos que capturan la mezcla completa del sistema (Discord,
#: YouTube, etc.) además del juego: capturadores virtuales y cables.
SYSTEM_AUDIO_HINTS = (
    "virtual-audio-capturer",
    "vb-cable",
    "voicemeeter",
    "loopback",
    "cable output",
    "stereo mix",
    "mezcla estéreo",
    "mezcla estereo",
    "what u hear",
)

#: Qué audio se mezcla en la grabación. ``none`` solo vídeo; ``game`` la
#: fuente elegida para el sonido del juego; ``mic`` solo el micrófono;
#: ``game_mic`` los dos; ``all`` añade además un capturador de la mezcla
#: del sistema (Discord, YouTube...) cuando hay un dispositivo disponible.
AUDIO_MODES = ("none", "game", "mic", "game_mic", "all", "full")
DEFAULT_AUDIO_MODE = "game"

AUDIO_MODE_LABELS = {
    "none": "Sin sonido (solo vídeo)",
    "game": "Solo juego",
    "mic": "Solo micrófono",
    "game_mic": "Solo juego y micrófono",
    "all": "Juego + micrófono + resto del PC (Discord, YouTube, etc.)",
    "full": "Juego + micrófono + todo el resto del sistema",
}

VIDEO_SUFFIXES = (".mp4", ".mkv")

#: Qué fuente se graba. ``game`` captura la ventana verificada del proceso
#: League of Legends.exe; ``all`` es una elección explícita del usuario.
CAPTURE_MODES = ("game", "all", "monitor")
DEFAULT_CAPTURE_MODE = "monitor"

CAPTURE_MODE_LABELS = {
    "game": "Monitor de League of Legends (DXGI)",
    "all": "Monitor configurado (DXGI)",
    "monitor": "Monitor de League of Legends (DXGI)",
}

#: Título exacto de la ventana de la partida (la del cliente de lobby se
#: llama «League of Legends» a secas, por eso el orden de los pistas importa).
GAME_WINDOW_TITLE = "League of Legends (TM) Client"
GAME_WINDOW_HINTS = ("League of Legends (TM) Client", "League of Legends")


def default_recordings_dir() -> Path:
    """Carpeta de grabaciones por defecto (Vídeos del usuario)."""
    return Path.home() / "Videos" / "Solralol"


def validar_contenedor_mp4(path: str | Path) -> bool:
    """Comprueba que un MP4 tenga una tabla de película finalizada.

    Parámetros: ruta del archivo que produjo FFmpeg.
    Retorno: True solo si los átomos superiores incluyen ``moov``.
    """
    try:
        size_total = Path(path).stat().st_size
        with Path(path).open("rb") as archivo:
            posicion = 0
            while posicion + 8 <= size_total:
                archivo.seek(posicion)
                cabecera = archivo.read(8)
                if len(cabecera) != 8:
                    return False
                size_atom = int.from_bytes(cabecera[:4], "big")
                tipo = cabecera[4:8]
                cabecera_size = 8
                if size_atom == 1:
                    extendido = archivo.read(8)
                    if len(extendido) != 8:
                        return False
                    size_atom = int.from_bytes(extendido, "big")
                    cabecera_size = 16
                elif size_atom == 0:
                    size_atom = size_total - posicion
                if size_atom < cabecera_size or posicion + size_atom > size_total:
                    return False
                if tipo == b"moov":
                    return True
                posicion += size_atom
    except OSError:
        _LOGGER.exception("[Recording] No se pudo validar el contenedor MP4: %s", path)
    return False


# --------------------------------------------------------------------------
# Emparejamiento vídeo ↔ sesión de telemetría
# --------------------------------------------------------------------------

#: Margen (segundos) al comparar la marca temporal del vídeo con la ventana
#: [started_at, ended_at] de la sesión guardada. Cubre los sidecars antiguos
#: que no declaran ``session_id`` y el arranque del grabador antes/después
#: de que el tracker dé con la partida.
SESSION_VIDEO_TOLERANCE_SECONDS = 180.0


def parse_iso_timestamp(value: Any) -> datetime | None:
    """Convierte una marca ISO 8601 (sidecar o sesión) en ``datetime`` UTC."""
    text = str(value or "").strip()

    if not text:
        return None

    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)

    return stamp.astimezone(UTC)


def session_matches_video_metadata(
    session: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    tolerance: float = SESSION_VIDEO_TOLERANCE_SECONDS,
) -> bool:
    """¿Puede ser esa sesión la partida grabada en ese vídeo?

    Empareja por tiempo cuando el sidecar no declara ``session_id``: el
    inicio del vídeo debe coincidir con el inicio de la sesión (± margen)
    o caer dentro de su ventana [started_at, ended_at] (con margen al final,
    porque el grabador puede seguir grabando unos segundos tras la partida).
    """
    if not isinstance(session, dict) or not isinstance(metadata, dict):
        return False

    video_start = parse_iso_timestamp(
        metadata.get("started_at") or metadata.get("recorded_at")
    )

    if video_start is None:
        return False

    session_start = parse_iso_timestamp(session.get("started_at"))

    if session_start is None:
        return False

    margin = abs(float(tolerance or 0.0))

    if abs((video_start - session_start).total_seconds()) <= margin:
        return True

    session_end = parse_iso_timestamp(session.get("ended_at"))

    if session_end is None:
        return False

    return session_start <= video_start <= session_end + timedelta(seconds=margin)


def find_video_for_session(
    videos: list[Path],
    session: dict[str, Any] | None,
    metadata_loader,
    tolerance: float = SESSION_VIDEO_TOLERANCE_SECONDS,
) -> Path | None:
    """Grabación que corresponde a esa sesión de telemetría.

    Primero por ``session_id`` declarado en el sidecar; si ningún sidecar lo
    trae (sidecars antiguos), por ventana temporal. Devuelve ``None`` si no
    hay coincidencia y el llamante decide el respaldo (normalmente el vídeo
    más reciente de la carpeta).
    """
    if not videos:
        return None

    wanted = str((session or {}).get("session_id") or "")

    if wanted:
        for path in reversed(videos):
            metadata = metadata_loader(path)

            if (
                isinstance(metadata, dict)
                and str(metadata.get("session_id") or "") == wanted
            ):
                return path

    for path in reversed(videos):
        metadata = metadata_loader(path)

        if session_matches_video_metadata(session, metadata, tolerance):
            return path

    return None


def quality_label(key: str) -> str:
    preset = QUALITY_PRESETS.get(str(key)) or QUALITY_PRESETS[DEFAULT_QUALITY]
    return str(preset["label"])


def quality_height(key: str) -> int:
    preset = QUALITY_PRESETS.get(str(key)) or QUALITY_PRESETS[DEFAULT_QUALITY]
    return int(preset["height"])


def quality_fps(key: str) -> int:
    preset = QUALITY_PRESETS.get(str(key)) or QUALITY_PRESETS[DEFAULT_QUALITY]
    return int(preset["fps"])


def normalize_quality(value: Any) -> str:
    key = str(value or "")

    return key if key in QUALITY_PRESETS else DEFAULT_QUALITY


def bitrate_label(value: Any) -> str:
    key = normalize_bitrate(value)

    return BITRATE_PRESETS.get(key) or f"{key} kbps"


def normalize_bitrate(value: Any) -> int:
    """Deja el bitrate en un preset válido (el más cercano por debajo)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_BITRATE

    if number in BITRATE_PRESETS:
        return number

    candidates = [key for key in BITRATE_PRESETS if key <= number]

    return max(candidates) if candidates else min(BITRATE_PRESETS)


# --------------------------------------------------------------------------
# Configuración de grabación
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordingConfig:
    """Todo lo que necesita una grabación, ya resuelto desde Ajustes."""

    output_dir: Path = field(default_factory=default_recordings_dir)
    enabled: bool = True
    quality: str = DEFAULT_QUALITY
    video_bitrate: int = DEFAULT_BITRATE
    mic_enabled: bool = False
    mic_device: str = ""
    game_audio_device: str = ""
    mic_capture_enabled: bool = False
    mic_capture_device: str = ""
    #: Tercer insumo («Todo el resto: Discord, YouTube…»). La UI moderna lo
    #: guarda en ``recording_system_audio_device``; se conserva
    #: ``mic_capture_device`` por compatibilidad con ajustes antiguos.
    system_audio_device: str = ""
    size_limit_gb: float = float(LIMIT_DEFAULT_GB)
    ffmpeg_path: str = ""
    capture_mode: str = DEFAULT_CAPTURE_MODE
    capture_window_title: str = ""
    monitor_index: int = -1
    audio_mode: str = DEFAULT_AUDIO_MODE

    @property
    def height(self) -> int:
        return quality_height(self.quality)

    @property
    def fps(self) -> int:
        return quality_fps(self.quality)

    @property
    def size_limit_bytes(self) -> int:
        try:
            gigabytes = float(self.size_limit_gb)
        except (TypeError, ValueError):
            gigabytes = float(LIMIT_DEFAULT_GB)

        gigabytes = max(
            float(LIMIT_MIN_GB),
            min(gigabytes, float(LIMIT_MAX_GB)),
        )

        return int(gigabytes * 1024**3)

    @property
    def effective_system_audio_device(self) -> str:
        """Tercer insumo efectivo (nuevo campo o el antiguo por compatibilidad)."""
        return str(self.system_audio_device or self.mic_capture_device or "")

    @property
    def effective_system_enabled(self) -> bool:
        """Si hay que capturar «Todo el resto» en este config.

        Vale para «all» y para «full» (el nombre nuevo del mismo modo).
        """
        mode = normalize_audio_mode(self.audio_mode)
        return bool(
            audio_mode_uses_system(mode)
            and (self.mic_capture_enabled or self.effective_system_audio_device)
        )

    @classmethod
    def from_settings(cls, settings: dict | None) -> RecordingConfig:
        data = settings if isinstance(settings, dict) else {}
        output_dir = str(data.get("recording_output_dir") or "").strip()

        try:
            limit_value = float(data.get("recording_size_limit_gb", LIMIT_DEFAULT_GB))
        except (TypeError, ValueError):
            limit_value = float(LIMIT_DEFAULT_GB)

        mic_enabled = bool(data.get("recording_mic_enabled", False))
        # Compatibilidad: el tercer insumo se guardó con dos nombres
        # distintos a lo largo del tiempo (clave antigua
        # ``recording_mic_capture_device`` y clave de la UI actual
        # ``recording_system_audio_device``). Se aceptan ambas y gana la
        # moderna si trae valor.
        system_audio_device = str(
            data.get("recording_system_audio_device")
            or data.get("recording_mic_capture_device")
            or ""
        )
        mic_capture_enabled = bool(data.get("recording_mic_capture_enabled", False))
        # Los modos nuevos ("all"/"full" y el futuro "system") ya implican
        # captura del sistema aunque el flag antiguo no exista en ajustes
        # viejos: se deriva aquí para que el arranque no pierda el insumo.
        _raw_audio_mode = str(data.get("recording_audio_mode") or "").strip()
        if _raw_audio_mode in ("all", "full", "system"):
            mic_capture_enabled = True
        game_audio_device = str(data.get("recording_game_audio_device") or "")

        # Migración: los ajustes antiguos no tienen modo de audio, se
        # deduce del micrófono, del capturador de sistema y del dispositivo
        # del juego guardados para no cambiar el comportamiento de nadie.
        audio_mode = derive_audio_mode(
            data.get("recording_audio_mode"),
            mic_enabled=mic_enabled,
            mic_capture_enabled=mic_capture_enabled,
            game_audio_device=game_audio_device,
        )

        return cls(
            output_dir=(
                Path(output_dir).expanduser()
                if output_dir
                else default_recordings_dir()
            ),
            enabled=bool(data.get("recording_auto", True)),
            quality=normalize_quality(data.get("recording_quality")),
            video_bitrate=normalize_bitrate(
                data.get("recording_bitrate", DEFAULT_BITRATE)
            ),
            mic_enabled=mic_enabled,
            mic_capture_enabled=mic_capture_enabled,
            mic_capture_device=system_audio_device,
            system_audio_device=system_audio_device,
            mic_device=str(data.get("recording_mic_device") or ""),
            game_audio_device=game_audio_device,
            size_limit_gb=limit_value,
            ffmpeg_path=str(data.get("ffmpeg_path") or ""),
            capture_mode=normalize_capture_mode(data.get("recording_capture")),
            capture_window_title=str(data.get("recording_capture_window") or ""),
            monitor_index=normalize_monitor_index(
                data.get("recording_monitor_index", -1)
            ),
            audio_mode=audio_mode,
        )


def recording_settings_defaults() -> dict[str, Any]:
    """Valores por defecto de las claves de grabación de settings.json.

    ``recording_audio_mode`` NO va aquí a propósito: si se precargara con
    ``setdefault``, taparía la migración de ``derive_audio_mode`` para los
    ajustes antiguos. Se escribe la primera vez que el usuario cambia el
    modo de audio en Ajustes.
    """
    return {
        "recording_auto": True,
        "recording_quality": DEFAULT_QUALITY,
        "recording_bitrate": DEFAULT_BITRATE,
        "recording_mic_enabled": False,
        "recording_mic_capture_enabled": False,
        "recording_mic_capture_device": "",
        "recording_system_audio_device": "",
        "recording_mic_device": "",
        "recording_game_audio_device": "",
        "recording_output_dir": str(default_recordings_dir()),
        "recording_size_limit_gb": float(LIMIT_DEFAULT_GB),
        "recording_monitor_index": -1,
        "ffmpeg_path": "",
    }


# --------------------------------------------------------------------------
# Localización de ffmpeg y de los dispositivos de audio
# --------------------------------------------------------------------------


#: Aviso que se muestra cuando no hay ningún ffmpeg utilizable.
FFMPEG_MISSING_HINT = (
    "No se encontró ffmpeg. Es necesario para grabar: "
    "instala imageio-ffmpeg "
    "(pip install -r requirements.txt) o coloca "
    "ffmpeg.exe en la carpeta del proyecto."
)


def find_ffmpeg(
    configured_path: str = "",
    *,
    force: bool = False,
) -> str | None:
    """Devuelve la ruta de ffmpeg.exe o None si no hay ninguno usable.

    El resultado se recuerda un minuto: la búsqueda recorre el ``PATH`` y
    comprueba cada candidato en disco, y se hace al arrancar, al abrir Ajustes
    y al empezar cada partida (unas décimas de segundo cada vez).
    """
    key = str(configured_path or "")
    now = time.monotonic()
    started = now

    if not force:
        cached = _FFMPEG_CACHE.get(key)

        if cached is not None and now - cached[0] < FFMPEG_LOOKUP_CACHE_SECONDS:
            _LOGGER.debug(
                "Búsqueda FFmpeg en caché: disponible=%s, hilo=%s (%s)",
                bool(cached[1]),
                threading.current_thread().name,
                threading.get_ident(),
            )
            return cached[1]

    found = _search_ffmpeg(key)
    _FFMPEG_CACHE[key] = (now, found)
    _LOGGER.debug(
        "Búsqueda FFmpeg finalizada: disponible=%s, duración_ms=%.1f, hilo=%s (%s)",
        bool(found),
        (time.monotonic() - started) * 1000,
        threading.current_thread().name,
        threading.get_ident(),
    )

    return found


def _search_ffmpeg(configured_path: str) -> str | None:
    candidates: list[Path] = []

    if configured_path:
        candidates.append(Path(configured_path).expanduser())

    which = shutil.which("ffmpeg")

    if which:
        candidates.append(Path(which))

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    program_data = os.environ.get("ProgramData", "")

    candidates.append(Path.home() / ".solralol" / "ffmpeg" / "ffmpeg.exe")
    candidates.append(Path("C:/ffmpeg/bin/ffmpeg.exe"))
    candidates.append(Path("C:/ffmpeg/ffmpeg.exe"))

    if local_appdata:
        candidates.append(Path(local_appdata) / "ffmpeg" / "bin" / "ffmpeg.exe")
        candidates.append(
            Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        )

    if program_data:
        candidates.append(Path(program_data) / "chocolatey" / "bin" / "ffmpeg.exe")

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue

    # imageio-ffmpeg incluye un binario estático listo para usar.
    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())

        if bundled.is_file():
            return str(bundled)
    except Exception:  # noqa: BLE001 - dependencia opcional
        pass

    return None


def list_audio_devices(
    ffmpeg_path: str,
    *,
    force: bool = False,
) -> list[str]:
    """Dispositivos de entrada de audio DirectShow disponibles.

    La consulta lanza ffmpeg con ``-list_devices``, que sondea todos los
    dispositivos del sistema y puede tardar varios segundos. El resultado se
    recuerda unos minutos para no repetir la espera al abrir Ajustes, al
    empezar cada partida o al arrancar la grabación; los botones de «buscar
    dispositivos» pasan ``force=True`` para volver a preguntar.
    """
    if not ffmpeg_path:
        return []

    now = time.monotonic()

    if not force:
        cached = _AUDIO_DEVICE_CACHE.get(ffmpeg_path)

        if cached is not None and now - cached[0] < AUDIO_DEVICE_CACHE_SECONDS:
            return list(cached[1])

    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    output = f"{result.stderr or ''}\n{result.stdout or ''}"
    devices: list[str] = []

    for line in output.splitlines():
        match = re.search(r'"([^"]+)"\s*\((audio|video)\)', line)

        if match and match.group(2) == "audio":
            name = match.group(1).strip()

            if name and name not in devices:
                devices.append(name)

    _AUDIO_DEVICE_CACHE[ffmpeg_path] = (now, tuple(devices))

    return devices


def obtener_dispositivos_audio_cacheados(ffmpeg_path: str) -> list[str]:
    """Devuelve el último sondeo de audio sin lanzar procesos externos.

    Parámetros:
        ffmpeg_path: Ruta del ejecutable asociado a la caché.

    Retorno:
        Lista de dispositivos del último sondeo, o una lista vacía.
    """
    cached = _AUDIO_DEVICE_CACHE.get(ffmpeg_path)

    return list(cached[1]) if cached is not None else []


def matches_any(name: str, hints: tuple[str, ...]) -> bool:
    lowered = str(name).casefold()

    return any(hint in lowered for hint in hints)


def pick_game_audio_device(devices: list[str]) -> str:
    """Mejor candidato para capturar el sonido del juego."""
    for device in devices:
        if matches_any(device, GAME_AUDIO_HINTS):
            return device

    return ""


def pick_microphone_device(devices: list[str]) -> str:
    """Mejor candidato para el micrófono (sin coger la mezcla)."""
    candidates = [
        device for device in devices if not matches_any(device, GAME_AUDIO_HINTS)
    ]

    for device in candidates:
        if matches_any(device, MIC_HINTS):
            return device

    return candidates[0] if candidates else ""


# --------------------------------------------------------------------------
# Área de captura: solo la pantalla donde está el juego
# --------------------------------------------------------------------------

CaptureArea = tuple[int, int, int, int]  # (x, y, ancho, alto)


def normalize_capture_mode(value: Any) -> str:
    """Normaliza ajustes antiguos al modo actual de captura de monitor.

    Parámetros: valor persistido de modo de captura.
    Retorno: modo DXGI válido, conservando modos heredados como monitor.
    """
    mode = str(value or "")
    if mode in {"game", "all", "monitor"}:
        return "monitor"
    return DEFAULT_CAPTURE_MODE


def normalize_monitor_index(value: Any) -> int:
    """Normaliza el monitor guardado; -1 representa selección automática.

    Parámetros: valor persistido en ajustes.
    Retorno: índice DXGI no negativo o -1 para modo automático.
    """
    try:
        return max(-1, int(value))
    except (TypeError, ValueError):
        return -1


def normalize_audio_mode(value: Any) -> str:
    """Modo de audio válido desde cualquier valor guardado."""
    mode = str(value or "").strip()

    return mode if mode in AUDIO_MODES else DEFAULT_AUDIO_MODE


def derive_audio_mode(
    value: Any,
    *,
    mic_enabled: bool = False,
    mic_capture_enabled: bool = False,
    game_audio_device: str = "",
) -> str:
    """Modo de audio de un ajuste, migrando configuraciones antiguas.

    Si ``recording_audio_mode`` no existe o no es válido, se deduce de las
    claves que usaban las versiones anteriores (dispositivo del juego, checkbox
    del micrófono y, si existía, captura de mezcla del sistema) para no cambiar
    el comportamiento de nadie.
    """
    mode = str(value or "").strip()

    if mode in AUDIO_MODES:
        return mode

    uses_game = bool(str(game_audio_device or "").strip())
    uses_mic = bool(mic_enabled)
    uses_system_capture = bool(mic_capture_enabled)

    if uses_system_capture:
        if uses_game and uses_mic:
            return "full"
        if uses_mic:
            return "full"
        return "full"

    if uses_game and uses_mic:
        return "game_mic"

    if uses_mic:
        return "mic"

    if uses_game:
        return "game"

    return "none"


def audio_mode_label(mode: Any) -> str:
    return AUDIO_MODE_LABELS.get(
        normalize_audio_mode(mode),
        AUDIO_MODE_LABELS[DEFAULT_AUDIO_MODE],
    )


def audio_mode_uses_game(mode: Any) -> bool:
    return normalize_audio_mode(mode) in {"game", "game_mic", "all", "full"}


def audio_mode_uses_mic(mode: Any) -> bool:
    return normalize_audio_mode(mode) in {"mic", "game_mic", "all", "full"}


def audio_mode_uses_system(mode: Any) -> bool:
    return normalize_audio_mode(mode) in {"all", "full"}


def audio_mode_uses_full_system(mode: Any) -> bool:
    return normalize_audio_mode(mode) == "full"


def pick_system_audio_device(
    devices: list[str],
    exclude: set[str] | None = None,
) -> str:
    """Dispositivo que captura la mezcla del sistema, distinto del elegido.

    Para el modo «Todo»: si el sonido del juego ya sale de una mezcla
    (Stereo Mix, capturador virtual...) ese mismo ya incluye Discord y
    YouTube, y no se añade nada más. Si hay otro capturador libre
    (VB-Cable, Voicemeeter...), se usa como fuente adicional.
    """
    skip = {str(value) for value in (exclude or set()) if str(value or "").strip()}

    for device in devices:
        if device in skip:
            continue

        if matches_any(device, SYSTEM_AUDIO_HINTS):
            return device

    return ""


def capture_mode_label(mode: Any) -> str:
    key = normalize_capture_mode(mode)

    return CAPTURE_MODE_LABELS.get(key, CAPTURE_MODE_LABELS[DEFAULT_CAPTURE_MODE])


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    SM_CXSCREEN = 0
    SM_CYSCREEN = 1
    MONITOR_DEFAULTTONEAREST = 2

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _RECT),
            ("rcWork", _RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32 = ctypes.windll.user32
    # En 64 bits los handles son punteros: sin estos prototipos el valor se
    # truncaría a 32 bits y las llamadas fallarían de forma intermitente.
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = ctypes.c_void_p
    _user32.GetMonitorInfoW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_MONITORINFO),
    ]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        ctypes.c_void_p,
        wintypes.HDC,
        ctypes.POINTER(_RECT),
        wintypes.LPARAM,
    )
    _user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(_RECT),
        _MONITORENUMPROC,
        wintypes.LPARAM,
    ]
    _user32.EnumDisplayMonitors.restype = wintypes.BOOL
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _kernel32 = ctypes.windll.kernel32
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int


def _rect_area(rect: Any) -> CaptureArea:
    return (
        int(rect.left),
        int(rect.top),
        max(1, int(rect.right) - int(rect.left)),
        max(1, int(rect.bottom) - int(rect.top)),
    )


def _monitor_area_of_window(hwnd: Any) -> CaptureArea | None:
    """Pantalla (monitor completo) que contiene la ventana dada."""
    monitor = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)

    if monitor:
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)

        if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return _rect_area(info.rcMonitor)

    rect = _RECT()

    if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return _rect_area(rect)

    return None


def _monitor_index_of_window(hwnd: Any) -> int:
    """Obtiene el índice de monitor DXGI asociado a una ventana.

    Parámetros: HWND validado de la ventana del juego.
    Retorno: ordinal de monitor o cero si no puede resolverse.
    """
    if sys.platform != "win32":
        return 0
    target = _user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not target:
        return 0
    monitors: list[int] = []

    def collect(monitor: Any, _dc: Any, _rect: Any, _data: Any) -> bool:
        monitors.append(int(monitor))
        return True

    callback = _MONITORENUMPROC(collect)
    _user32.EnumDisplayMonitors(None, None, callback, 0)
    try:
        return monitors.index(int(target))
    except ValueError:
        return 0


def _game_process_path(pid: int) -> str:
    """Devuelve la ruta del ejecutable del PID o una cadena vacía si falla.

    Parámetros: pid es el identificador del proceso asociado a la ventana.
    Retorno: ruta completa obtenida mediante QueryFullProcessImageNameW.
    """
    if sys.platform != "win32" or pid <= 0:
        return ""
    handle = _kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if _kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(length)
        ):
            return buffer.value
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def find_game_window() -> tuple[int, int, str] | None:
    """Localiza una ventana visible propiedad de League of Legends.exe.

    Parámetros: ninguno.
    Retorno: tupla HWND, PID y titulo, o None si no hay coincidencia.
    """
    if sys.platform != "win32":
        return None
    candidates: list[tuple[int, int, Any, int, str]] = []

    def _callback(handle: Any, _lparam: Any) -> bool:
        length = _user32.GetWindowTextLengthW(handle)

        if length <= 0 or not _user32.IsWindowVisible(handle):
            return True

        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        path = _game_process_path(int(pid.value))
        if Path(path).name.casefold() != "league of legends.exe":
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(handle, buffer, length + 1)
        title = buffer.value

        for index, hint in enumerate(GAME_WINDOW_HINTS):
            if hint not in title:
                continue

            rect = _RECT()
            area = 0

            if _user32.GetWindowRect(handle, ctypes.byref(rect)):
                area = max(
                    0,
                    (rect.right - rect.left) * (rect.bottom - rect.top),
                )

            candidates.append((index, -area, handle, int(pid.value), title))
            break

        return True

    enum_proc = _WNDENUMPROC(_callback)
    _user32.EnumWindows(enum_proc, 0)

    if not candidates:
        return None

    candidates.sort()

    selected = candidates[0]
    _LOGGER.info(
        "[Recording] Proceso de juego detectado: pid=%s, hwnd=%s, title=%s",
        selected[3],
        selected[2],
        selected[4],
    )
    return selected[2], selected[3], selected[4]


def find_game_capture_area() -> CaptureArea | None:
    """Compatibilidad heredada: devuelve None y nunca habilita escritorio.

    Parámetros: ninguno.
    Retorno: None; la captura segura requiere el título de una ventana verificada.
    """
    return None


def _get_game_capture_title() -> str:
    """Obtiene el título de una ventana visible del proceso real del juego.

    Parámetros: ninguno.
    Retorno: título exacto admitido por gdigrab o cadena vacía.
    """
    if sys.platform != "win32":
        return ""

    try:
        window = find_game_window()
        return window[2] if window else ""
    except Exception:
        _LOGGER.exception("No se pudo validar la ventana de League of Legends")
        return ""


# --------------------------------------------------------------------------
# Orden de ffmpeg
# --------------------------------------------------------------------------


def build_ffmpeg_command(
    *,
    ffmpeg_path: str,
    output_path: str | Path,
    quality: str = DEFAULT_QUALITY,
    video_bitrate: int = DEFAULT_BITRATE,
    game_audio_device: str = "",
    mic_device: str = "",
    system_audio_device: str = "",
    capture_window_title: str = "",
    capture_desktop: bool = False,
    capture_area: CaptureArea | None = None,
    monitor_index: int = 0,
) -> list[str]:
    """Construye una orden DXGI de monitor y codificación H.264 por AMF.

    Parámetros: rutas, calidad y fuentes de audio explícitamente elegidas.
    Retorno: argumentos FFmpeg con un único monitor fijado para la sesión.
    """
    if sys.platform != "win32":
        raise ValueError("La captura DXGI solo está disponible en Windows.")
    height = quality_height(quality)
    fps = quality_fps(quality)
    bitrate = normalize_bitrate(video_bitrate)
    input_args = [
        "-f",
        "lavfi",
        "-i",
        f"ddagrab=output_idx={max(0, int(monitor_index))}:framerate={fps}:draw_mouse=0",
    ]
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-y",
        "-filter_complex_threads",
        str(RECORDING_FILTER_THREADS),
        *input_args,
    ]

    audio_devices: list[str] = []

    # Se mezclan los dispositivos que el llamante ha resuelto: decide él,
    # según el modo de audio y los dispositivos disponibles, cuáles hay que
    # capturar (el modo ya se aplicó al resolverlos).
    for device in (
        game_audio_device,
        mic_device,
        system_audio_device,
    ):
        name = str(device or "").strip()

        if name and name not in audio_devices:
            audio_devices.append(name)

    for device in audio_devices:
        command.extend(
            [
                "-f",
                "dshow",
                "-audio_buffer_size",
                str(AUDIO_BUFFER_MS),
                "-i",
                f"audio={device}",
            ]
        )

    height = quality_height(quality)
    chains = [
        f"[0:v]hwdownload,format=bgra,scale=-2:{height}:flags=bicubic,format=nv12[v]"
    ]
    maps = ["-map", "[v]"]

    if audio_devices:
        audio_labels = []

        for index in range(len(audio_devices)):
            label = f"a{index}"
            chains.append(f"[{index + 1}:a]aresample=async=1[{label}]")
            audio_labels.append(f"[{label}]")

        if len(audio_labels) > 1:
            mix = "".join(audio_labels)
            mix += f"amix=inputs={len(audio_labels)}"
            mix += ":duration=longest:dropout_transition=0:normalize=0[a]"
            chains.append(mix)
        else:
            chains.append(f"{audio_labels[0]}anull[a]")

        maps.extend(["-map", "[a]"])

    command.extend(["-filter_complex", ";".join(chains)])
    command.extend(maps)

    bitrate = normalize_bitrate(video_bitrate)
    fps = quality_fps(quality)

    command.extend(
        [
            "-c:v",
            "h264_amf",
            "-usage",
            # AMF's lowlatency usage on the tested driver ignores the GOP
            # interval and emits an infinite GOP (only the first IDR). That
            # makes random seeks decode from the beginning of long MP4s.
            # Transcoding usage honors -g; the explicit low-latency switch
            # retains prompt capture without disabling periodic IDR frames.
            "transcoding",
            "-latency",
            "1",
            "-quality",
            "speed",
            "-rc",
            "vbr_peak",
            "-profile:v",
            "high",
            "-b:v",
            f"{bitrate}k",
            "-maxrate",
            f"{bitrate}k",
            "-bufsize",
            f"{bitrate * 2}k",
            "-g",
            str(fps * 2),
            "-pix_fmt",
            "nv12",
        ]
    )

    if audio_devices:
        command.extend(
            [
                "-c:a",
                "aac",
                "-b:a",
                f"{AUDIO_BITRATE_KBPS}k",
                "-ar",
                "48000",
                "-ac",
                "2",
            ]
        )
    else:
        command.append("-an")

    command.extend(
        [
            "-progress",
            "pipe:1",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(output_path),
        ]
    )

    return command


def run_recording_diagnostic(
    config: RecordingConfig,
    ffmpeg_path: str,
    *,
    duration_seconds: int = 4,
) -> dict[str, Any]:
    """Graba y valida un clip breve del monitor seleccionado.

    Parámetros: configuración activa, ruta de FFmpeg y duración acotada.
    Retorno: diagnóstico independiente de vídeo, audio y salida final.
    """
    diagnostico: dict[str, Any] = {
        "backend": "FFmpeg DXGI Desktop Duplication",
        "video_ok": False,
        "audio_ok": False,
        "audio_state": "No solicitado",
        "message": "",
    }
    _LOGGER.info("[Recording] Prueba solicitada; duración=%s s", duration_seconds)

    if not ffmpeg_path or not Path(ffmpeg_path).is_file():
        diagnostico["stage"] = "ffmpeg"
        diagnostico["message"] = "No se encontró un ejecutable FFmpeg válido."
        _LOGGER.error("[Recording] Prueba fallida: binario FFmpeg no disponible")
        return diagnostico

    mode = normalize_audio_mode(config.audio_mode)
    audio_error = ""
    if audio_mode_uses_game(mode):
        audio_error = (
            "El backend actual no ofrece loopback por proceso; "
            "no se puede validar el audio de League of Legends."
        )
        diagnostico["audio_state"] = audio_error
        _LOGGER.error("[Recording] Prueba de audio fallida: %s", audio_error)
    elif mode == "none":
        diagnostico["audio_state"] = "Sin audio solicitado."
    else:
        diagnostico["audio_state"] = (
            "No se pudo comprobar audio sin la ventana del juego."
        )

    window = find_game_window()
    capture_area = _monitor_area_of_window(window[0]) if window else None
    monitor_index = _monitor_index_of_window(window[0]) if window else 0
    if window:
        hwnd, pid, title = window
        diagnostico.update({"hwnd": int(hwnd), "window": title, "pid": pid})
        _LOGGER.info(
            "[Recording] Monitor de prueba asociado al juego: pid=%s hwnd=%s index=%s",
            pid,
            hwnd,
            monitor_index,
        )
    else:
        diagnostico["message"] = (
            "League of Legends no está activo; se probará el monitor principal "
            "y no se validará gameplay."
        )
        _LOGGER.warning("[Recording] Prueba de monitor: League no detectado")

    audio_devices: dict[str, str] = {"mic_device": "", "system_audio_device": ""}
    if audio_mode_uses_mic(mode):
        audio_devices["mic_device"] = config.mic_device
    if audio_mode_uses_system(mode):
        audio_devices["system_audio_device"] = config.effective_system_audio_device

    library = RecordingLibrary(config.output_dir)
    try:
        directory = library.ensure_directory()
        with tempfile.NamedTemporaryFile(
            prefix="solralol-prueba-", suffix=".mp4", dir=directory, delete=False
        ) as temporal:
            output = Path(temporal.name)
    except OSError as error:
        diagnostico["stage"] = "salida"
        diagnostico["message"] = (
            f"No se puede preparar la carpeta de grabaciones: {error}"
        )
        _LOGGER.exception("[Recording] Prueba fallida al preparar salida")
        return diagnostico

    try:
        command = build_ffmpeg_command(
            ffmpeg_path=ffmpeg_path,
            output_path=output,
            quality=config.quality,
            video_bitrate=config.video_bitrate,
            capture_area=capture_area,
            monitor_index=monitor_index,
            capture_desktop=True,
            game_audio_device="",
            mic_device=audio_devices["mic_device"],
            system_audio_device=audio_devices["system_audio_device"],
        )
        command[command.index("-loglevel") + 1] = "info"
        output_index = len(command) - 1
        command[output_index:output_index] = [
            "-t",
            str(max(2, min(10, int(duration_seconds)))),
            "-stats",
        ]
        diagnostico["stage"] = "captura"
        diagnostico["encoder"] = "AMD AMF H.264 (hardware)"
        _LOGGER.info(
            "[Recording] Prueba DXGI del monitor %s con AMF H.264",
            monitor_index,
        )
        resultado = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(15, duration_seconds + 12),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        diagnostico["returncode"] = resultado.returncode
        detalle = (resultado.stderr or "").strip()
        if detalle:
            _LOGGER.info("[Recording] Salida técnica de FFmpeg: %s", detalle[-1200:])
        archivo_valido = output.is_file() and output.stat().st_size > 2048
        detalle_salida_ffmpeg = detalle.partition("Output #0")[2]
        tiene_video = bool(re.search(r"Stream #\d+:\d+.*Video:", detalle_salida_ffmpeg))
        cuadros = re.findall(
            r"frame=\s*(\d+)",
            f"{resultado.stdout or ''}\n{resultado.stderr or ''}",
        )
        cuadros_codificados = max((int(valor) for valor in cuadros), default=0)
        decode = (
            subprocess.run(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-v",
                    "info",
                    "-i",
                    str(output),
                    "-map",
                    "0:v:0",
                    "-f",
                    "null",
                    "-",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            if archivo_valido
            else None
        )
        frames_decodificados = bool(decode and decode.returncode == 0)
        detalle_salida = "\n".join(
            parte for parte in (detalle, decode.stderr if decode else "") if parte
        )
        duracion_coincidencia = re.search(
            r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", detalle_salida
        )
        duracion_s = 0.0
        if duracion_coincidencia:
            horas, minutos, segundos = duracion_coincidencia.groups()
            duracion_s = int(horas) * 3600 + int(minutos) * 60 + float(segundos)
        negro = False
        if frames_decodificados:
            analisis_negro = subprocess.run(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-i",
                    str(output),
                    "-vf",
                    "blackdetect=d=3:pix_th=0.02:pic_th=0.98",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            duraciones_negras = re.findall(
                r"black_duration:([0-9.]+)", analisis_negro.stderr or ""
            )
            negro = any(
                float(valor) >= max(2, duration_seconds) - 0.25
                for valor in duraciones_negras
            )
        diagnostico["video_ok"] = bool(
            resultado.returncode == 0
            and archivo_valido
            and tiene_video
            and duracion_s >= min(2.0, max(2, duration_seconds) * 0.75)
            and cuadros_codificados > 0
            and frames_decodificados
            and not negro
        )
        diagnostico["frames"] = cuadros_codificados
        diagnostico["duration_seconds"] = round(duracion_s, 2)
        diagnostico["file_bytes"] = output.stat().st_size if output.exists() else 0
        diagnostico["black"] = negro
        diagnostico["audio_stream"] = bool(
            re.search(r"Stream #\d+:\d+.*Audio:", detalle_salida_ffmpeg)
        )
        if diagnostico["audio_stream"] and not audio_error:
            lectura_audio = subprocess.run(
                [
                    ffmpeg_path,
                    "-hide_banner",
                    "-i",
                    str(output),
                    "-map",
                    "0:a:0",
                    "-af",
                    "volumedetect",
                    "-f",
                    "null",
                    "-",
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            volumen = re.search(
                r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB",
                lectura_audio.stderr or "",
            )
            diagnostico["audio_ok"] = bool(lectura_audio.returncode == 0 and volumen)
            diagnostico["audio_state"] = (
                f"Señal de audio detectada ({volumen.group(1)} dB)."
                if diagnostico["audio_ok"] and volumen
                else "Hay una pista, pero no se detectó señal de audio."
            )
        elif not audio_error and mode != "none":
            diagnostico["audio_state"] = "No se detectó una pista de audio en el clip."
        if diagnostico["video_ok"]:
            diagnostico["stage"] = "completada"
            diagnostico["message"] = (
                "Vídeo del monitor donde está League grabado y decodificado."
                if window
                else "Monitor principal capturado; no se validó gameplay."
            )
            _LOGGER.info(
                "[Recording] Prueba de vídeo validada: frames=%s, bytes=%s",
                cuadros_codificados,
                diagnostico["file_bytes"],
            )
        else:
            diagnostico["stage"] = "validación de vídeo"
            diagnostico["message"] = "La prueba no obtuvo vídeo de juego válido. " + (
                "Se detectó imagen negra persistente." if negro else detalle[-500:]
            )
            _LOGGER.error(
                "[Recording] Prueba fallida al validar vídeo: returncode=%s, "
                "archivo=%s, stream=%s, frames=%s, decodificable=%s, negro=%s",
                resultado.returncode,
                archivo_valido,
                tiene_video,
                cuadros_codificados,
                frames_decodificados,
                negro,
            )
        if audio_error:
            diagnostico["message"] += " " + audio_error
        return diagnostico
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        diagnostico["stage"] = diagnostico.get("stage", "captura")
        diagnostico["message"] = f"Falló la prueba de captura: {error}"
        _LOGGER.exception("[Recording] Excepción durante la prueba de captura")
        return diagnostico
    finally:
        output.unlink(missing_ok=True)


def format_duration(seconds: Any) -> str:
    """Segundos a ``mm:ss`` (o ``h:mm:ss`` en partidas largas)."""
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0

    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes:02d}:{secs:02d}"


def format_size(bytes_value: Any) -> str:
    """Tamaño legible en MB/GB."""
    try:
        size = float(bytes_value)
    except (TypeError, ValueError):
        size = 0.0

    if size >= 1024**3:
        return f"{size / 1024**3:.2f} GB".replace(".", ",")

    return f"{size / 1024**2:.1f} MB".replace(".", ",")


def sanitize_filename_part(value: Any) -> str:
    """Quita de un texto lo que Windows no admite en un nombre de archivo."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(value or ""))
    text = text.strip().strip(".")

    return text[:40] or "partida"


# --------------------------------------------------------------------------
# Marcadores de la partida (asesinatos, muertes, asistencias y objetivos)
# --------------------------------------------------------------------------

#: Tipos de objetivo que se marcan en la barra del reproductor.
OBJECTIVE_MARKERS: dict[str, str] = {
    "dragon": "Dragón",
    "baron": "Barón (Nashor)",
    "rift_herald": "Heraldo",
    "horde": "Grumos",
    "tower": "Torre",
    "inhibitor": "Inhibidor",
}

MARKER_LABELS: dict[str, str] = {
    "kill": "Asesinato",
    "teamfight": "Teamfight",
    "death": "Muerte",
    "assist": "Asistencia",
    "dragon": "Dragón",
    "baron": "Barón (Nashor)",
    "herald": "Heraldo",
    "rift_herald": "Heraldo",
    "horde": "Grumos",
    "tower": "Torre",
    "inhibitor": "Inhibidor",
    "objective": "Objetivo",
}

#: ``LiveMatchTracker`` guarda el heraldo como ``rift_herald``; la barra del
#: reproductor lo dibuja con el nombre corto ``herald``.
#:
#: Además se normalizan los nombres que la Riot API y el Live Client usan
#: para los edificios ("Tower Building", "Inhibitor Building"...) y que
#: quedaron guardados tal cual en sesiones antiguas: sin esta traducción la
#: barra y la revisión no reconocían esas torres/inhibidores.
MARKER_ALIASES: dict[str, str] = {
    "rift_herald": "herald",
    "tower building": "tower",
    "tower_building": "tower",
    "turret": "tower",
    "torre": "tower",
    "inhibitor building": "inhibitor",
    "inhibitor_building": "inhibitor",
    "barracks": "inhibitor",
    "inhibidor": "inhibitor",
    "baron nashor": "baron",
    "nashor": "baron",
    "barón": "baron",
    "rift herald": "herald",
    "riftherald": "herald",
    "heraldo": "herald",
    "void_grub": "horde",
    "voidgrub": "horde",
    "grumos": "horde",
}


def normalise_marker_kind(kind: Any) -> str:
    """Tipo de marcador canónico (traduce los nombres antiguos/oficiales)."""
    text = str(kind or "").strip().casefold()

    if not text:
        return ""

    return MARKER_ALIASES.get(text, text)


EXACT_KILL_TYPES = ("kill_exact", "death_exact")


def _marker_time(value: Any, offset: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0

    return max(0.0, number - offset)


def build_markers(
    session: dict[str, Any] | None,
    game_time_offset: float = 0.0,
) -> list[dict[str, Any]]:
    """Marcadores del jugador local a partir de la sesión del tracker.

    Los asesinatos, muertes y asistencias se toman de los eventos exactos de
    la API local si existen; en caso contrario se usan los contadores
    observados. Los objetivos (torres, dragones, heraldos y barones) se
    marcan siempre, sea cual sea el equipo que los consiga.
    """
    if not isinstance(session, dict):
        return []

    events = session.get("events") or []
    local_key = str(session.get("local_player_key") or "")
    exact = any(
        isinstance(event, dict) and str(event.get("type")) in EXACT_KILL_TYPES
        for event in events
    )

    markers: list[dict[str, Any]] = []

    for order, event in enumerate(events):
        if not isinstance(event, dict):
            continue

        event_type = str(event.get("type") or "")
        player_key = str(event.get("player_key") or "")
        kind = ""

        if exact:
            if event_type == "kill_exact" and local_key:
                if player_key == local_key:
                    kind = "kill"
                elif local_key in [
                    str(key) for key in (event.get("assister_keys") or [])
                ]:
                    kind = "assist"
            elif event_type == "death_exact" and local_key:
                if player_key == local_key:
                    kind = "death"
        else:
            if event_type in ("kill", "death", "assist") and local_key:
                if player_key == local_key:
                    kind = event_type

        if not kind and event_type == "objective":
            kind = str(event.get("objective") or event.get("objective_label") or "")

        kind = normalise_marker_kind(kind)

        if not kind or kind not in MARKER_LABELS:
            continue

        markers.append(
            {
                "time": round(_marker_time(event.get("time"), game_time_offset), 1),
                "kind": kind,
                "category": kind,
                "source_event_id": event.get("event_id"),
                "source_type": event_type,
                "player_key": local_key or None,
                "label": MARKER_LABELS[kind],
                "detail": str(
                    event.get("label")
                    or event.get("objective_label")
                    or MARKER_LABELS[kind]
                ),
                # El bando puede venir en el campo antiguo u objetivo resuelto.
                "team": str(event.get("team") or event.get("objective_team") or ""),
                "order": int(event.get("order") or order),
            }
        )

    markers.sort(key=lambda marker: (marker["time"], marker["order"]))

    return markers


def marker_counts(markers: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta marcadores por tipo (para los resúmenes de la pestaña)."""
    counts: dict[str, int] = {}

    for marker in markers:
        kind = normalise_marker_kind(marker.get("kind"))

        if kind:
            counts[kind] = counts.get(kind, 0) + 1

    return counts


def markers_summary(markers: list[dict[str, Any]]) -> str:
    """Resumen corto de los marcadores, en orden de importancia."""
    counts = marker_counts(markers)
    order = (
        "kill",
        "death",
        "assist",
        "dragon",
        "baron",
        "herald",
        "horde",
        "tower",
        "inhibitor",
        "objective",
    )
    parts = [
        f"{counts[kind]} {MARKER_LABELS[kind].lower()}"
        for kind in order
        if counts.get(kind)
    ]

    return " · ".join(parts)


# --------------------------------------------------------------------------
# Biblioteca local de grabaciones
# --------------------------------------------------------------------------


class RecordingLibrary:
    """Lee, borra y ordena los vídeos de la carpeta de grabaciones.

    Cada vídeo lleva junto a él un JSON con el mismo nombre (el "sidecar")
    con los metadatos de la partida: campeón, duración y marcadores.
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = (
            Path(directory).expanduser() if directory else default_recordings_dir()
        )

    def set_directory(self, directory: str | Path | None) -> None:
        self.directory = (
            Path(directory).expanduser()
            if str(directory or "").strip()
            else default_recordings_dir()
        )

    def ensure_directory(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory

    def metadata_path(self, video_path: str | Path) -> Path:
        return Path(video_path).with_suffix(".json")

    def optimized_playback_path(self, video_path: str | Path) -> Path:
        """Devuelve el proxy con GOP corto asociado a una grabación, si existe.

        El original siempre se conserva. La clave de caché cambia si el vídeo
        original cambia de tamaño o fecha de modificación.
        """
        source = Path(video_path)
        try:
            stat = source.stat()
        except OSError:
            return source
        cache = self.directory / ".seek_cache"
        candidate = cache / (
            f"{source.name}.{stat.st_size:x}.{stat.st_mtime_ns:x}.seek.mp4"
        )
        return candidate if candidate.is_file() else source

    def seek_cache_path(self, video_path: str | Path) -> Path:
        """Ruta de caché determinista para crear el proxy de una grabación."""
        source = Path(video_path)
        stat = source.stat()
        return self.directory / ".seek_cache" / (
            f"{source.name}.{stat.st_size:x}.{stat.st_mtime_ns:x}.seek.mp4"
        )

    def _delete_seek_cache(self, video_path: str | Path) -> bool:
        source = Path(video_path)
        cache = self.directory / ".seek_cache"
        try:
            matches = (
                entry
                for entry in cache.iterdir()
                if entry.is_file()
                and entry.name.startswith(f"{source.name}.")
                and entry.name.endswith(".seek.mp4")
            ) if cache.exists() else ()
            success = True
            for match in matches:
                success = self._unlink_with_retry(match) and success
            if not success:
                return False
            if cache.exists() and not any(cache.iterdir()):
                cache.rmdir()
            return True
        except OSError:
            _LOGGER.exception("No se pudo limpiar la caché de reproducción de %s", source.name)
            return False

    def load_metadata(self, video_path: str | Path) -> dict[str, Any]:
        sidecar = self.metadata_path(video_path)

        try:
            with sidecar.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}

        return data if isinstance(data, dict) else {}

    def write_metadata(self, video_path: str | Path, payload: dict[str, Any]) -> bool:
        sidecar = self.metadata_path(video_path)

        try:
            with sidecar.open("w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
        except OSError:
            return False

        return True

    def video_files(self) -> list[Path]:
        """Vídeos ordenados de más antiguo a más nuevo."""
        try:
            files = list(self.directory.iterdir())
        except OSError:
            return []

        videos = [
            path
            for path in files
            if path.is_file() and path.suffix.casefold() in VIDEO_SUFFIXES
        ]

        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        videos.sort(key=mtime)

        return videos

    def total_size_bytes(self) -> int:
        """Peso total de la carpeta (vídeos + sidecars JSON)."""
        try:
            entries = list(self.directory.iterdir())
        except OSError:
            return 0

        total = 0

        for entry in entries:
            if not entry.is_file():
                continue

            suffix = entry.suffix.casefold()

            if suffix in VIDEO_SUFFIXES or suffix == ".json":
                try:
                    total += entry.stat().st_size
                except OSError:
                    continue

        cache = self.directory / ".seek_cache"
        try:
            total += sum(
                entry.stat().st_size
                for entry in cache.iterdir()
                if entry.is_file() and entry.suffix.casefold() == ".mp4"
            )
        except OSError:
            pass

        return total

    #: Windows suelta los handles de fichero con retraso (reproductor,
    #: antivirus, indexador): se reintenta unas veces antes de rendirse.
    DELETE_ATTEMPTS = 3
    DELETE_RETRY_DELAY = 0.15

    def delete(self, video_path: str | Path) -> bool:
        """Borra un vídeo y su sidecar JSON.

        True solo cuando los dos ficheros desaparecen (o ya no existían).
        Si Windows tiene el fichero bloqueado —por ejemplo porque se está
        reproduciendo— se reintenta antes de rendirse.
        """
        path = Path(video_path)
        if not self._delete_seek_cache(path):
            return False
        ok = True

        for target in (path, self.metadata_path(path)):
            if self._unlink_with_retry(target):
                continue

            ok = False

        return ok

    @classmethod
    def _unlink_with_retry(
        cls,
        target: Path,
        attempts: int | None = None,
        delay: float | None = None,
    ) -> bool:
        """Borra un fichero reintentando si está bloqueado (WinError 32)."""
        tries = int(attempts or cls.DELETE_ATTEMPTS)
        pause = float(cls.DELETE_RETRY_DELAY if delay is None else delay)

        for attempt in range(max(1, tries)):
            try:
                if target.is_file():
                    target.unlink()

                return True
            except OSError:
                if attempt + 1 >= max(1, tries):
                    return False

                time.sleep(pause)

        return False

    def _file_and_sidecar_size(self, video_path: Path) -> int:
        """Bytes del vídeo más los de su sidecar JSON (0 si no se pueden leer)."""
        total = 0

        for target in (video_path, self.metadata_path(video_path)):
            try:
                total += target.stat().st_size
            except OSError:
                continue

        return total

    def enforce_storage_limit(
        self,
        limit_bytes: int,
        keep_path: str | Path | None = None,
    ) -> list[Path]:
        """Hace hueco: borra las más antiguas hasta caber en el límite.

        La grabación más reciente (la que se acaba de guardar) nunca se
        borra: si ella sola ya supera el límite, se queda y se devuelve una
        lista vacía.
        """
        try:
            limit = int(limit_bytes)
        except (TypeError, ValueError):
            return []

        if limit <= 0:
            return []

        videos = self.video_files()

        if keep_path is not None:
            keep = Path(keep_path)
        elif videos:
            keep = videos[-1]
        else:
            return []

        # Los tamaños se leen una sola vez: recalcular el total de la carpeta
        # después de cada borrado volvía a recorrerla entera y a hacer stat de
        # todos los ficheros, y con la carpeta llena esa limpieza bloqueaba la
        # interfaz varios segundos al terminar cada partida.
        sizes = {path: self._file_and_sidecar_size(path) for path in videos}
        total = self.total_size_bytes()
        removed: list[Path] = []

        for path in videos:
            if total <= limit:
                break

            if path == keep:
                continue

            if self.delete(path):
                removed.append(path)
                total -= sizes.get(path, 0)

        return removed

    def list_recordings(self) -> list[dict[str, Any]]:
        """Grabaciones de más nueva a más vieja, listas para la pestaña."""
        entries: list[dict[str, Any]] = []

        for path in reversed(self.video_files()):
            metadata = self.load_metadata(path)
            markers = (
                metadata.get("markers")
                if isinstance(metadata.get("markers"), list)
                else []
            )
            duration = metadata.get("duration_seconds", 0)

            try:
                size_bytes = path.stat().st_size
            except OSError:
                size_bytes = 0

            try:
                created = path.stat().st_mtime
            except OSError:
                created = 0.0

            entries.append(
                {
                    "path": path,
                    "name": path.name,
                    "title": self.title_for(path, metadata),
                    "subtitle": self.subtitle_for(metadata),
                    "created_at": created,
                    "date_label": format_recording_date(created),
                    "size_bytes": size_bytes,
                    "size_label": format_size(size_bytes),
                    "duration": duration,
                    "duration_label": format_duration(duration),
                    "markers": markers,
                    "counts": marker_counts(markers),
                    "summary": markers_summary(markers),
                    "complete": bool(
                        metadata.get(
                            "complete",
                            metadata.get("stopped_cleanly", False),
                        )
                    ),
                    "champion": str(metadata.get("champion") or ""),
                    "game_mode": str(metadata.get("game_mode") or ""),
                    "metadata": metadata,
                }
            )

        return entries

    @staticmethod
    def title_for(path: Path, metadata: dict[str, Any] | None = None) -> str:
        data = metadata if isinstance(metadata, dict) else {}
        champion = str(data.get("champion") or "").strip()

        if champion:
            return champion

        stem = path.stem

        if stem.startswith("Solralol_"):
            parts = stem.split("_")

            if len(parts) >= 4:
                return sanitize_filename_part(parts[-1])

        return stem

    @staticmethod
    def subtitle_for(metadata: dict[str, Any] | None = None) -> str:
        data = metadata if isinstance(metadata, dict) else {}
        mode = str(data.get("game_mode") or "").strip()
        pieces = []

        if mode and mode != "UNKNOWN":
            pieces.append(mode.replace("_", " ").title())

        quality = str(data.get("quality") or "").strip()

        if quality:
            pieces.append(quality_label(quality))

        bitrate = data.get("video_bitrate")

        if bitrate:
            pieces.append(bitrate_label(bitrate))

        return " · ".join(pieces) or "Grabación de partida"


def format_recording_date(timestamp: float) -> str:
    try:
        moment = datetime.fromtimestamp(float(timestamp)).astimezone()
    except (OSError, OverflowError, TypeError, ValueError):
        return "Fecha desconocida"

    return moment.strftime("%d/%m/%Y %H:%M")


def suggest_recording_name(
    when: datetime | None = None,
    champion: str = "",
) -> str:
    """Nombre de archivo: Solralol_AAAA-MM-DD_HH-MM-SS_campeon.mp4."""
    moment = when.astimezone() if when else datetime.now().astimezone()
    stamp = moment.strftime("%Y-%m-%d_%H-%M-%S")
    part = sanitize_filename_part(champion)

    return f"Solralol_{stamp}_{part}.mp4"


# --------------------------------------------------------------------------
# Motor de grabación (QProcess)
# --------------------------------------------------------------------------


class RecordingService(QObject):
    """Arranca y para ffmpeg sin bloquear la interfaz.

    La grabación empieza con ``start()`` (la llama la ventana cuando detecta
    que hay partida) y termina con ``stop()`` (al terminar la partida o al
    cerrar la app). Al cerrar ffmpeg de forma limpia se escribe el sidecar
    JSON con los marcadores y se aplica el límite de peso de la carpeta.
    """

    started = Signal(str)
    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)
    audio_status = Signal(str)

    #: Espera a que ffmpeg cierre el MP4 tras pedirle "q".
    STOP_TIMEOUT_MS = 15000

    def __init__(
        self,
        library: RecordingLibrary | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.library = library or RecordingLibrary()
        self.process: QProcess | None = None
        self.pending_process: QProcess | None = None
        self.output_path: Path | None = None
        self.config: RecordingConfig | None = None
        self.ffmpeg_path: str = ""
        self.ffmpeg_available: bool = False
        self.ffmpeg_hint: str = ""
        self.started_monotonic: float = 0.0
        self.game_time_offset: float = 0.0
        self.champion: str = ""
        self.game_mode: str = ""
        self.session: dict[str, Any] | None = None
        self.stop_reason: str = ""
        self.stop_requested: bool = False
        self.last_error: str = ""
        self.first_video_frame_received: bool = False
        self.process_output_buffer: str = ""
        self.process_output_tail: str = ""
        self.capture_start_error_reported: bool = False
        self.active_monitor_index: int = -1
        self.capture_start_timer = QTimer(self)
        self.capture_start_timer.setSingleShot(True)
        self.capture_start_timer.setInterval(15000)
        self.capture_start_timer.timeout.connect(self._on_capture_start_timeout)
        self.audio_status_text: str = (
            "Captura por proceso no disponible en este backend"
        )
        self.started_at = datetime.now(UTC)

    # -- estado ---------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """Indica si FFmpeg ha producido al menos un fotograma codificado."""
        return self.process is not None and self.first_video_frame_received

    @property
    def is_starting_or_recording(self) -> bool:
        return self.process is not None or self.pending_process is not None

    def elapsed_seconds(self) -> float:
        if not self.is_recording:
            return 0.0

        return max(0.0, time.monotonic() - self.started_monotonic)

    def apply_ffmpeg_result(self, found: str | None) -> None:
        """Publica el resultado de una búsqueda hecha fuera del hilo de Qt.

        ``find_ffmpeg`` recorre el ``PATH`` y comprueba cada candidato en
        disco, así que la búsqueda se delega a un worker (``AsyncTask``);
        aquí solo se guarda lo que encontró, en el hilo de la interfaz.
        """
        self.ffmpeg_path = found or ""
        self.ffmpeg_available = bool(found)
        self.ffmpeg_hint = "" if found else FFMPEG_MISSING_HINT

    def refresh_ffmpeg(self, configured_path: str = "") -> str | None:
        """Vuelve a buscar ffmpeg y guarda el resultado.

        Bloquea (recorre el ``PATH`` y hace ``stat`` de cada candidato):
        desde la interfaz se usa ``find_ffmpeg`` en un ``AsyncTask`` y se
        publica con ``apply_ffmpeg_result``.
        """
        found = find_ffmpeg(configured_path)
        self.apply_ffmpeg_result(found)

        return found

    # -- arranque -------------------------------------------------------

    def start(
        self,
        config: RecordingConfig,
        *,
        game_time: float = 0.0,
        champion: str = "",
        game_mode: str = "",
        session: dict[str, Any] | None = None,
        recording_source: str = "automatic",
    ) -> bool:
        """Inicia una captura autom?tica o manual con el FFmpeg resuelto.

        Par?metros: configuraci?n, contexto de partida y origen de la orden.
        Retorno: True si se solicit? el arranque; False si se rechaz?.
        """
        if self.is_starting_or_recording:
            return False

        origen = "manual" if str(recording_source).lower() == "manual" else "automatic"
        if not config.enabled and origen != "manual":
            _LOGGER.info("[Recording] Inicio omitido: grabación desactivada")
            return False

        self.last_error = ""
        _LOGGER.info(
            "[Recording] Solicitud de inicio: captura=%s, audio=%s, ffmpeg_disponible=%s",
            normalize_capture_mode(config.capture_mode),
            normalize_audio_mode(config.audio_mode),
            bool(self.ffmpeg_available and self.ffmpeg_path),
        )

        if not self.ffmpeg_available or not self.ffmpeg_path:
            self.last_error = self.ffmpeg_hint

            if not self.last_error:
                self.last_error = (
                    "FFmpeg todavía no está listo. Espera a que termine "
                    "la comprobación en segundo plano."
                )

            self.failed.emit(self.last_error)
            _LOGGER.error(
                "[Recording] Fallo en comprobación de FFmpeg: %s", self.last_error
            )

            return False

        mode = normalize_audio_mode(config.audio_mode)
        if mode in {"game", "game_mic"}:
            self.audio_status_text = (
                "Error: no se está capturando el sonido del juego. "
                "Este equipo no tiene un capturador de audio por proceso "
                "conectado al grabador."
            )
            self.audio_status.emit(self.audio_status_text)
            _LOGGER.error(
                "[Recording] Audio no inicializado: modo=%s requiere "
                "loopback de Windows por proceso; no se sustituirá por audio del sistema",
                mode,
            )
        else:
            self.audio_status_text = (
                "Sin captura de audio solicitada"
                if mode == "none"
                else "Fuente de audio configurada; esperando muestras confirmadas"
            )

        self.library.set_directory(config.output_dir)

        try:
            directory = self.library.ensure_directory()
        except OSError as error:
            self.last_error = (
                "No se puede crear la carpeta de grabaciones "
                f"({self.library.directory}): {error}"
            )
            self.failed.emit(self.last_error)
            _LOGGER.exception("[Recording] Fallo al crear el directorio de salida")

            return False

        _LOGGER.info("[Recording] Directorio de salida disponible: %s", directory)
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".solralol-test-", dir=directory, delete=True
            ):
                pass
        except OSError as error:
            self.last_error = (
                f"No se puede escribir en la carpeta de grabaciones: {error}"
            )
            _LOGGER.exception("[Recording] Fallo al validar escritura en salida")
            self.failed.emit(self.last_error)
            return False
        _LOGGER.info("[Recording] Escritura en el destino validada")

        output = directory / suggest_recording_name(champion=champion)
        counter = 1

        while output.exists():
            output = directory / suggest_recording_name(
                champion=f"{champion} {counter}"
            )
            counter += 1

        capture_title = ""
        game_window = find_game_window()
        capture_area = None
        monitor_index = 0
        if game_window:
            hwnd, pid, capture_title = game_window
            capture_area = _monitor_area_of_window(hwnd)
            monitor_index = _monitor_index_of_window(hwnd)
            _LOGGER.info(
                "[Recording] Monitor seleccionado por juego: pid=%s hwnd=%s "
                "índice_dxgi=%s área=%s",
                pid,
                hwnd,
                monitor_index,
                capture_area,
            )
        else:
            monitor_index = max(0, normalize_monitor_index(config.monitor_index))
            _LOGGER.warning(
                "[Recording] No se detectó League; se usará el monitor DXGI configurado (%s)",
                monitor_index,
            )
        self.active_monitor_index = monitor_index

        # Resolución de dispositivos según el modo de audio: el juego y el
        # micrófono se auto-detectan si no hay uno guardado; el modo «Todo»
        # añade además un capturador de la mezcla del sistema distinto del
        # ya usado (si el juego ya se captura con Stereo Mix, ese mismo ya
        # incluye Discord/YouTube y no se añade un segundo).
        # Fallback: si el dispositivo guardado ya no existe (desconectado o
        # renombrado) se cae al mejor candidato disponible para no grabar
        # en silencio; si no hay ningún dispositivo, se sigue con vídeo.
        game_device = ""
        mic_device = ""
        system_device = ""

        if mode != "none":
            available = obtener_dispositivos_audio_cacheados(self.ffmpeg_path)
            available_set = {name for name in available if name}

            def _resolve(saved: str, picker) -> str:
                name = str(saved or "").strip()
                if name and name in available_set:
                    return name
                if name and available_set:
                    # Guardado pero ya no visible: mejor candidato.
                    fallback = picker(list(available))
                    if fallback:
                        return str(fallback)
                if not name:
                    return str(picker(list(available)) or "")
                # Sin lista de dispositivos (ffmpeg no los enumeró): se
                # intenta igualmente con el nombre guardado; dshow dirá si
                # falla y el watcher degradará a vídeo.
                return name

            if audio_mode_uses_mic(mode):
                mic_device = _resolve(
                    config.mic_device,
                    lambda devs: pick_microphone_device(devs, exclude={game_device}),
                )

            if audio_mode_uses_system(mode):
                # El dispositivo elegido en «Todo el resto» manda: si el
                # guardado sigue existiendo se respeta tal cual (no se
                # sustituye por otro «mejor»). Solo si está vacío o ya no
                # existe se busca otro capturador distinto de los ya usados
                # (juego/micrófono). Sin lista disponible pero con
                # preferencia guardada se intenta de todos modos (mejor
                # intentarlo que silenciar).
                preferred = config.effective_system_audio_device
                if preferred and preferred in available_set:
                    candidate = preferred
                elif preferred and not available_set:
                    candidate = preferred
                else:
                    candidate = pick_system_audio_device(
                        available,
                        exclude={game_device, mic_device},
                    )
                if candidate and candidate not in {game_device, mic_device}:
                    system_device = candidate

        command = build_ffmpeg_command(
            ffmpeg_path=self.ffmpeg_path,
            output_path=output,
            quality=config.quality,
            video_bitrate=config.video_bitrate,
            game_audio_device=game_device,
            mic_device=mic_device,
            system_audio_device=system_device,
            capture_area=capture_area,
            capture_window_title=capture_title,
            capture_desktop=True,
            monitor_index=monitor_index,
        )
        _LOGGER.info(
            "[Recording] Backend de vídeo seleccionado: FFmpeg ddagrab (DXGI monitor %s), encoder=h264_amf hardware; audio=%s",
            monitor_index,
            "sin audio de juego" if mode in {"game", "game_mic"} else mode,
        )

        process = QProcess(self)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        workdir = Path(self.ffmpeg_path).parent
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert(
            "PATH", f"{workdir}{os.pathsep}{environment.value('PATH', '')}"
        )
        process.setProcessEnvironment(environment)
        process.started.connect(self._on_process_started)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_process_finished)
        process.readyReadStandardOutput.connect(self._on_process_output)
        self.pending_process = process
        self.output_path = output
        self.config = config
        self.game_time_offset = max(0.0, float(game_time or 0.0))
        self.champion = str(champion or "")
        self.game_mode = str(game_mode or "")
        self.recording_source = origen
        self.session = session
        self.stop_reason = ""
        self.stop_requested = False
        self.last_error = ""
        self.first_video_frame_received = False
        self.process_output_buffer = ""
        self.process_output_tail = ""
        self.capture_start_error_reported = False
        self.started_at = datetime.now(UTC)
        process.start()
        _LOGGER.info(
            "[Recording] Solicitud enviada a QProcess; esperando confirmación de FFmpeg (salida=%s)",
            output,
        )

        return True

    # -- parada ---------------------------------------------------------

    def stop(
        self,
        reason: str = "game_end",
        session: dict[str, Any] | None = None,
    ) -> bool:
        """Solicita el cierre de ffmpeg y conserva la grabación si puede.

        Parámetros:
            reason: Motivo de cierre guardado en los metadatos.
            session: Telemetría final opcional para los marcadores.

        Retorno:
            True si el cierre quedó solicitado; False si no hay proceso.
        """
        process = self.process or self.pending_process

        if process is None:
            return False

        if session is not None:
            self.session = session

        self.stop_reason = str(reason or "game_end")
        self.stop_requested = True
        self.state_changed.emit("stopping")

        if self.process is None:
            return True

        try:
            process.write(b"q")
        except RuntimeError:
            pass

        return True

    def abort(self) -> None:
        """Termina ffmpeg sin finalizar el vídeo durante un cierre forzado.

        Parámetros:
            None.

        Retorno:
            None.
        """
        process = self.process or self.pending_process

        if process is None:
            return

        self.stop_reason = self.stop_reason or "abort"
        self.stop_requested = True

        try:
            process.kill()
        except RuntimeError:
            self._reset()

    def wait_for_stop(self, timeout_ms: int | None = None) -> bool:
        process = self.process or self.pending_process

        if process is None:
            return True

        return bool(process.waitForFinished(timeout_ms or 3000))

    def _on_process_started(self) -> None:
        """Confirma el arranque asíncrono del proceso y publica su estado.

        Parámetros:
            None.

        Retorno:
            None.
        """
        process = self.pending_process

        if process is None:
            return

        self.pending_process = None
        self.process = process
        self.capture_start_timer.start()
        self.state_changed.emit("starting")

        _LOGGER.info(
            "[Recording] Proceso FFmpeg iniciado: pid=%s; aún no se validan fotogramas ni audio (codificador_hilos=%s, filtros_hilos=%s)",
            process.processId(),
            RECORDING_ENCODER_THREADS,
            RECORDING_FILTER_THREADS,
        )

        _LOGGER.warning(
            "[Recording] FFmpeg abrió proceso; esperando el primer fotograma codificado"
        )

        if self.stop_requested:
            self.stop(reason=self.stop_reason, session=self.session)

    def _on_process_output(self) -> None:
        """Lee el progreso de FFmpeg y confirma el primer fotograma codificado.

        Parámetros: ninguno; consume la salida asíncrona del proceso activo.
        Retorno: None; actualiza el estado al confirmarse un fotograma.
        """
        process = self.process
        if process is None:
            return
        try:
            recibido = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
        except RuntimeError:
            return
        if not recibido:
            return
        self.process_output_tail = (self.process_output_tail + recibido)[-8000:]
        self.process_output_buffer += recibido
        lineas = self.process_output_buffer.splitlines(keepends=True)
        self.process_output_buffer = ""
        if lineas and not lineas[-1].endswith(("\n", "\r")):
            self.process_output_buffer = lineas.pop()
        for linea in lineas:
            coincidencia = re.match(r"\s*frame=\s*(\d+)", linea)
            if not coincidencia or int(coincidencia.group(1)) <= 0:
                continue
            if not self.first_video_frame_received:
                self.first_video_frame_received = True
                self.capture_start_timer.stop()
                self.started_monotonic = time.monotonic()
                self.state_changed.emit("recording")
                _LOGGER.info(
                    "[Recording] Primer fotograma de vídeo codificado: frame=%s",
                    coincidencia.group(1),
                )
                if self.output_path is not None:
                    self.started.emit(str(self.output_path))
            return

    def _on_capture_start_timeout(self) -> None:
        """Detiene una captura que no produjo ningún fotograma inicial.

        Parámetros: ninguno; usa el proceso y diagnóstico activos.
        Retorno: None; notifica el fallo y cierra FFmpeg para evitar falsos
        estados de grabación prolongados.
        """
        if self.process is None or self.first_video_frame_received:
            return
        self.last_error = (
            "FFmpeg no recibió fotogramas de vídeo en 15 segundos. "
            "Comprueba que la ventana de League siga visible y que la captura "
            "de esa ventana sea compatible."
        )
        self.capture_start_error_reported = True
        _LOGGER.error(
            "[Recording] Fallo en primer fotograma: pid=%s, salida_ffmpeg=%s",
            self.process.processId(),
            self.process_output_tail[-1200:] or "sin salida del backend",
        )
        self.failed.emit(self.last_error)
        self.process.kill()

    def _on_process_error(self, _error: Any) -> None:
        """Limpia una captura cuyo proceso terminó antes de forma inesperada.

        Parámetros:
            _error: Código de error emitido por QProcess.

        Retorno:
            None.
        """
        process = self.process or self.pending_process

        if process is None:
            return

        if process.state() != QProcess.NotRunning:
            return

        if self.capture_start_error_reported:
            self._reset()
            return

        self._on_process_output()
        try:
            detail = self.process_output_tail + bytes(
                process.readAllStandardOutput()
            ).decode("utf-8", "replace")
        except RuntimeError:
            detail = ""

        try:
            detalle_qprocess = str(process.errorString())
        except (AttributeError, RuntimeError):
            detalle_qprocess = ""
        self.last_error = (
            f"FFmpeg no pudo mantener la captura (error QProcess {_error}). "
            f"{detalle_qprocess}"
        ).strip()

        if detail:
            self.last_error += f" Detalle: {detail[-300:]}"

        finished_path = self.output_path
        self._reset()
        _LOGGER.error("[Recording] Fallo al iniciar FFmpeg: %s", self.last_error)
        self.failed.emit(self.last_error)
        self._cleanup_empty_file(finished_path)

    def _on_process_finished(self, exit_code: int, _exit_status: Any) -> None:
        """Persiste metadatos al terminar el proceso de captura.

        Parámetros:
            exit_code: Código de salida de FFmpeg.
            _exit_status: Estado de salida definido por Qt.

        Retorno:
            None.
        """
        process = self.process or self.pending_process

        if process is None:
            return

        output = self.output_path
        config = self.config
        self._on_process_output()
        duration = self.elapsed_seconds()
        try:
            process_output = (
                self.process_output_tail
                + bytes(process.readAllStandardOutput())
                .decode("utf-8", "replace")
                .strip()
            )
        except RuntimeError:
            process_output = ""
        try:
            file_valid = bool(
                output is not None
                and output.is_file()
                and output.stat().st_size > 0
                and validar_contenedor_mp4(output)
            )
        except OSError:
            file_valid = False
            _LOGGER.exception("[Recording] No se pudo comprobar el archivo de salida")
        stopped_cleanly = (
            self.stop_requested
            and exit_code == 0
            and output is not None
            and file_valid
            and self.first_video_frame_received
        )
        _LOGGER.info(
            "[Recording] FFmpeg finalizado: exit_code=%s, exit_status=%s, "
            "parada_solicitada=%s, contenedor_finalizado=%s, duración_s=%.1f",
            exit_code,
            _exit_status,
            self.stop_requested,
            file_valid,
            duration,
        )

        if not stopped_cleanly:
            if self.capture_start_error_reported:
                self._reset()
                return
            detail = process_output[-600:] if process_output else ""
            reason = (
                f"El proceso de grabación terminó inesperadamente "
                f"(código {exit_code}; archivo válido: {file_valid})."
            )
            if output is not None and output.is_file() and not file_valid:
                reason += " El MP4 no contiene una tabla moov finalizada."
            self.last_error = f"{reason} {detail}".strip()
            _LOGGER.error(
                "[Recording] Fallo al finalizar: exit_code=%s, exit_status=%s, "
                "archivo=%s, primer_fotograma=%s, salida_ffmpeg=%s",
                exit_code,
                _exit_status,
                output,
                self.first_video_frame_received,
                detail or "sin detalle de FFmpeg",
            )
            self._reset()
            self.failed.emit(self.last_error)
            return

        _LOGGER.info(
            "[Recording] Salida finalizada correctamente: %s",
            output,
        )
        self._reset()

        if output is None:
            return

        if stopped_cleanly:
            markers = build_markers(
                self.session if isinstance(self.session, dict) else {},
                self.game_time_offset,
            )
            session_dict = self.session
            session_dict = session_dict if isinstance(session_dict, dict) else {}
            game_duration = 0.0

            try:
                game_duration = max(
                    0.0,
                    float(session_dict.get("duration", 0)) - self.game_time_offset,
                )
            except (TypeError, ValueError):
                pass

            metadata = {
                "schema_version": 1,
                "file": output.name,
                "started_at": self.started_at.isoformat(),
                "ended_at": datetime.now(UTC).isoformat(),
                "duration_seconds": round(duration, 1),
                "game_duration_seconds": round(game_duration, 1),
                "game_time_offset": round(self.game_time_offset, 1),
                "champion": self.champion,
                "game_mode": self.game_mode,
                "recording_source": self.recording_source,
                "audio_capture_status": self.audio_status_text,
                "quality": config.quality if config else DEFAULT_QUALITY,
                "video_bitrate": (config.video_bitrate if config else DEFAULT_BITRATE),
                "mic": bool(config.mic_enabled) if config else False,
                "stop_reason": self.stop_reason or "game_end",
                "complete": True,
                "markers": markers,
                # Enlace con la sesión de telemetría guardada: la ventana
                # de repaso abre el desglose de esta misma partida.
                "session_id": str(session_dict.get("session_id") or ""),
                "local_player_key": str(session_dict.get("local_player_key") or ""),
            }
            library = self.library

            if config is not None:
                library.set_directory(config.output_dir)

            library.write_metadata(output, metadata)
            library.enforce_storage_limit(
                config.size_limit_bytes if config else 0,
                keep_path=output,
            )

        self.session = None
        self.finished.emit(str(output))

    def _reset(self) -> None:
        """Libera el proceso activo y devuelve el servicio al estado inactivo.

        Parámetros:
            None.

        Retorno:
            None.
        """
        process = self.process or self.pending_process
        self.capture_start_timer.stop()
        self.process = None
        self.pending_process = None
        self.output_path = None
        self.stop_requested = False
        self.first_video_frame_received = False
        self.process_output_buffer = ""
        self.process_output_tail = ""

        if process is not None:
            try:
                process.deleteLater()
            except RuntimeError:
                pass

        self.state_changed.emit("idle")

    @staticmethod
    def _cleanup_empty_file(path: Path | None) -> None:
        if path is None:
            return

        try:
            if path.is_file() and path.stat().st_size == 0:
                path.unlink()
        except OSError:
            pass
