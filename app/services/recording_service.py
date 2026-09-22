"""Grabación de partidas y biblioteca local de grabaciones.

El motor de captura es **ffmpeg**: graba la pantalla, mezcla el sonido del
sistema (el audio de la partida) con el micrófono cuando se activa y escribe
un MP4 con la calidad y el bitrate elegidos en Ajustes.

El módulo sólo depende de Qt en ``RecordingService``, que usa ``QProcess``
para no bloquear la interfaz mientras dura la grabación. Todo lo demás
(presets, orden de ffmpeg, marcadores y gestión de la carpeta) son funciones
puras que se pueden probar sin interfaz ni partidas reales.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal


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

#: El audio (partida + micrófono) siempre se codifica igual: es lo que menos
#: pesa y AAC a 160 kbps es más que suficiente para el juego.
AUDIO_BITRATE_KBPS = 160

#: Ajustes de audio de DirectShow: menos búfer = menos desfase con el vídeo.
AUDIO_BUFFER_MS = 100

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

#: Qué parte de la pantalla se graba. ``game`` (por defecto) localiza la
#: ventana de League y graba solo el monitor donde está; ``all`` reproduce el
#: comportamiento antiguo (todo el escritorio, con todos los monitores).
CAPTURE_MODES = ("game", "all")
DEFAULT_CAPTURE_MODE = "game"

CAPTURE_MODE_LABELS = {
    "game": "Solo la pantalla del juego (recomendado)",
    "all": "Toda la pantalla (todos los monitores)",
}

#: Título exacto de la ventana de la partida (la del cliente de lobby se
#: llama «League of Legends» a secas, por eso el orden de los pistas importa).
GAME_WINDOW_TITLE = "League of Legends (TM) Client"
GAME_WINDOW_HINTS = ("League of Legends (TM) Client", "League of Legends")


def default_recordings_dir() -> Path:
    """Carpeta de grabaciones por defecto (Vídeos del usuario)."""
    return Path.home() / "Videos" / "Solralol"


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

    return (
        session_start
        <= video_start
        <= session_end + timedelta(seconds=margin)
    )


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

            if isinstance(metadata, dict) and str(
                metadata.get("session_id") or ""
            ) == wanted:
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
    mic_capture_enabled: bool = False
    size_limit_gb: float = float(LIMIT_DEFAULT_GB)
    ffmpeg_path: str = ""
    capture_mode: str = DEFAULT_CAPTURE_MODE
    capture_window_title: str = ""
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

    @classmethod
    def from_settings(cls, settings: dict | None) -> RecordingConfig:
        data = settings if isinstance(settings, dict) else {}
        output_dir = str(data.get("recording_output_dir") or "").strip()

        try:
            limit_value = float(
                data.get("recording_size_limit_gb", LIMIT_DEFAULT_GB)
            )
        except (TypeError, ValueError):
            limit_value = float(LIMIT_DEFAULT_GB)

        mic_enabled = bool(data.get("recording_mic_enabled", False))
        mic_capture_enabled = bool(
            data.get("recording_mic_capture_enabled", False)
        )
        game_audio_device = str(
            data.get("recording_game_audio_device") or ""
        )

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
            mic_capture_device=str(data.get("recording_mic_capture_device") or ""),
            mic_device=str(data.get("recording_mic_device") or ""),
            game_audio_device=game_audio_device,
            size_limit_gb=limit_value,
            ffmpeg_path=str(data.get("ffmpeg_path") or ""),
            capture_mode=normalize_capture_mode(
                data.get("recording_capture")
            ),
            capture_window_title=str(
                data.get("recording_capture_window") or ""
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
        "recording_mic_device": "",
        "recording_game_audio_device": "",
        "recording_output_dir": str(default_recordings_dir()),
        "recording_size_limit_gb": float(LIMIT_DEFAULT_GB),
        "ffmpeg_path": "",
    }


# --------------------------------------------------------------------------
# Localización de ffmpeg y de los dispositivos de audio
# --------------------------------------------------------------------------


def find_ffmpeg(configured_path: str = "") -> str | None:
    """Devuelve la ruta de ffmpeg.exe o None si no hay ninguno usable."""
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
        candidates.append(
            Path(local_appdata) / "ffmpeg" / "bin" / "ffmpeg.exe"
        )
        candidates.append(
            Path(local_appdata) / "Microsoft" / "WinGet" / "Links"
            / "ffmpeg.exe"
        )

    if program_data:
        candidates.append(
            Path(program_data) / "chocolatey" / "bin" / "ffmpeg.exe"
        )

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


def list_audio_devices(ffmpeg_path: str) -> list[str]:
    """Dispositivos de entrada de audio DirectShow disponibles."""
    if not ffmpeg_path:
        return []

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

    return devices


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
        device
        for device in devices
        if not matches_any(device, GAME_AUDIO_HINTS)
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
    mode = str(value or "")

    return mode if mode in CAPTURE_MODES else DEFAULT_CAPTURE_MODE


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
    skip = {
        str(value)
        for value in (exclude or set())
        if str(value or "").strip()
    }

    for device in devices:
        if device in skip:
            continue

        if matches_any(device, SYSTEM_AUDIO_HINTS):
            return device

    return ""


def capture_mode_label(mode: Any) -> str:
    key = normalize_capture_mode(mode)

    return CAPTURE_MODE_LABELS.get(
        key, CAPTURE_MODE_LABELS[DEFAULT_CAPTURE_MODE]
    )


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

    _WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

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


def _find_game_window() -> int | None:
    """Handle de la ventana de la partida (título exacto, luego a pistas).

    Entre candidatos con la misma pista gana el de mayor área: la ventana
    del juego a pantalla completa es mayor que la del lobby.
    """
    hwnd = _user32.FindWindowW(None, GAME_WINDOW_TITLE)

    if hwnd:
        return hwnd

    candidates: list[tuple[int, int, Any]] = []

    def _callback(handle: Any, _lparam: Any) -> bool:
        length = _user32.GetWindowTextLengthW(handle)

        if length <= 0 or not _user32.IsWindowVisible(handle):
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

            candidates.append((index, -area, handle))
            break

        return True

    enum_proc = _WNDENUMPROC(_callback)
    _user32.EnumWindows(enum_proc, 0)

    if not candidates:
        return None

    candidates.sort()

    return candidates[0][2]


def find_game_capture_area() -> CaptureArea | None:
    """Área a grabar: el monitor donde está la ventana de League.

    Orden de intención: ventana del juego (por título) → ventana en primer
    plano → monitor principal. Devuelve ``None`` si no se puede determinar
    (fuera de Windows o fallo de la API); en ese caso se graba el escritorio
    completo, como hasta ahora. Nunca lanza: un fallo de la API de Windows
    no puede impedir la grabación.
    """
    if sys.platform != "win32":
        return None

    try:
        hwnd = _find_game_window()

        if hwnd:
            area = _monitor_area_of_window(hwnd)

            if area is not None:
                return area

        foreground = _user32.GetForegroundWindow()

        if foreground:
            area = _monitor_area_of_window(foreground)

            if area is not None:
                return area

        width = _user32.GetSystemMetrics(SM_CXSCREEN)
        height = _user32.GetSystemMetrics(SM_CYSCREEN)

        if width > 0 and height > 0:
            return (0, 0, width, height)
    except Exception:  # noqa: BLE001 - la grabación no puede depender de Win32
        return None

    return None


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
    capture_desktop: bool = True,
    capture_area: CaptureArea | None = None,
    audio_mode: str = DEFAULT_AUDIO_MODE,
) -> list[str]:
    """Construye la orden completa de ffmpeg para una grabación.

    - El vídeo sale de ``gdigrab`` (pantalla completa o una ventana concreta).
      Con ``capture_area`` (x, y, ancho, alto) se limita a ese rectángulo del
      escritorio virtual, que es como se graba únicamente el monitor donde
      está el juego sin arrastrar el resto de pantallas.
    - El sonido del juego sale de una fuente DirectShow (mezcla estéreo).
    - El micrófono y, si se pide, un capturador de la mezcla del sistema
      (modo «Todo»: Discord, YouTube...) se mezclan con ``amix`` sobre el
      audio del juego para que todos queden en la misma pista.
    - El modo ``full`` incluye el sonido del juego, del micrófono y un
      capturador de mezcla del sistema (por ejemplo Discord, navegadores,
      Voicemeeter, Stereo Mix, etc.) si hay dispositivo disponible.
    """
    window_title = capture_window_title.strip()
    framerate = str(quality_fps(quality))

    mode = normalize_audio_mode(audio_mode)
    include_system_audio = audio_mode_uses_full_system(mode) or audio_mode_uses_system(mode)

    if include_system_audio and not system_audio_device:
        # Si el usuario eligió modo que captura el sistema pero no eligió
        # dispositivo, se intenta deducirlo después; aquí no se añade nada
        # hasta que haya dispositivo efectivo.
        pass
    window_title = capture_window_title.strip()
    framerate = str(quality_fps(quality))

    if window_title and not capture_desktop:
        input_args = [
            "-f",
            "gdigrab",
            "-framerate",
            framerate,
            "-i",
            f"title={window_title}",
        ]
    else:
        area = None

        if capture_area is not None:
            try:
                area = (
                    int(capture_area[0]),
                    int(capture_area[1]),
                    max(1, int(capture_area[2])),
                    max(1, int(capture_area[3])),
                )
            except (TypeError, ValueError, IndexError):
                area = None

        if area is not None:
            input_args = [
                "-f",
                "gdigrab",
                "-framerate",
                framerate,
                "-offset_x",
                str(area[0]),
                "-offset_y",
                str(area[1]),
                "-video_size",
                f"{area[2]}x{area[3]}",
                "-i",
                "desktop",
            ]
        else:
            input_args = [
                "-f",
                "gdigrab",
                "-framerate",
                framerate,
                "-i",
                "desktop",
            ]

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-y",
        *input_args,
    ]

    audio_devices: list[str] = []

    for device in (
        game_audio_device,
        mic_device,
        system_audio_device if audio_mode_uses_system(mode) else "",
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
    chains = [f"[0:v]scale=-2:{height}:flags=bicubic,format=yuv420p[v]"]
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
            "libx264",
            "-preset",
            "veryfast",
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
            "yuv420p",
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
        ["-movflags", "+faststart", "-f", "mp4", str(output_path)]
    )

    return command


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
        isinstance(event, dict)
        and str(event.get("type")) in EXACT_KILL_TYPES
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
            kind = str(
                event.get("objective") or event.get("objective_label") or ""
            )

        kind = normalise_marker_kind(kind)

        if not kind or kind not in MARKER_LABELS:
            continue

        markers.append(
            {
                "time": round(
                    _marker_time(event.get("time"), game_time_offset), 1
                ),
                "kind": kind,
                "label": MARKER_LABELS[kind],
                "detail": str(
                    event.get("label")
                    or event.get("objective_label")
                    or MARKER_LABELS[kind]
                ),
                # El bando puede venir en el campo antiguo u objetivo resuelto.
                "team": str(
                    event.get("team")
                    or event.get("objective_team")
                    or ""
                ),
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
            Path(directory).expanduser()
            if directory
            else default_recordings_dir()
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

    def load_metadata(self, video_path: str | Path) -> dict[str, Any]:
        sidecar = self.metadata_path(video_path)

        try:
            with sidecar.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            return {}

        return data if isinstance(data, dict) else {}

    def write_metadata(
        self, video_path: str | Path, payload: dict[str, Any]
    ) -> bool:
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
            if path.is_file()
            and path.suffix.casefold() in VIDEO_SUFFIXES
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

        candidates = [path for path in videos if path != keep]
        removed: list[Path] = []

        while candidates and self.total_size_bytes() > limit:
            oldest = candidates.pop(0)

            if self.delete(oldest):
                removed.append(oldest)

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
    def title_for(
        path: Path, metadata: dict[str, Any] | None = None
    ) -> str:
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
        self.started_at = datetime.now(UTC)

    # -- estado ---------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self.process is not None

    @property
    def is_starting_or_recording(self) -> bool:
        return self.process is not None or self.pending_process is not None

    def elapsed_seconds(self) -> float:
        if not self.is_recording:
            return 0.0

        return max(0.0, time.monotonic() - self.started_monotonic)

    def refresh_ffmpeg(self, configured_path: str = "") -> str | None:
        """Vuelve a buscar ffmpeg y guarda el resultado."""
        found = find_ffmpeg(configured_path)
        self.ffmpeg_path = found or ""
        self.ffmpeg_available = bool(found)

        if not found:
            self.ffmpeg_hint = (
                "No se encontró ffmpeg. Es necesario para grabar: "
                "instala imageio-ffmpeg "
                "(pip install -r requirements.txt) o coloca "
                "ffmpeg.exe en la carpeta del proyecto."
            )
        else:
            self.ffmpeg_hint = ""

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
    ) -> bool:
        """Arranca una grabación. False si no se puede (ya grabando, sin
        ffmpeg, sin carpeta escribible...)."""
        if self.is_recording:
            return False

        if not config.enabled:
            return False

        self.refresh_ffmpeg(config.ffmpeg_path)

        if not self.ffmpeg_available:
            self.last_error = self.ffmpeg_hint
            self.failed.emit(self.last_error)

            return False

        self.library.set_directory(config.output_dir)

        try:
            directory = self.library.ensure_directory()
        except OSError as error:
            self.last_error = (
                "No se puede crear la carpeta de grabaciones "
                f"({self.library.directory}): {error}"
            )
            self.failed.emit(self.last_error)

            return False

        output = directory / suggest_recording_name(champion=champion)
        counter = 1

        while output.exists():
            output = directory / suggest_recording_name(
                champion=f"{champion} {counter}"
            )
            counter += 1

            if counter > 99:
                break

        # Resolución de dispositivos según el modo de audio: el juego y el
        # micrófono se auto-detectan si no hay uno guardado; el modo «Todo»
        # añade además un capturador de la mezcla del sistema distinto del
        # ya usado (si el juego ya se captura con Stereo Mix, ese mismo ya
        # incluye Discord/YouTube y no se añade un segundo).
        mode = normalize_audio_mode(config.audio_mode)
        game_device = ""
        mic_device = ""
        system_device = ""

        if mode != "none":
            available = list_audio_devices(self.ffmpeg_path)

            if audio_mode_uses_game(mode):
                game_device = (
                    config.game_audio_device
                    or pick_game_audio_device(available)
                )

            if audio_mode_uses_mic(mode):
                mic_device = (
                    config.mic_device
                    or pick_microphone_device(available)
                )

            if audio_mode_uses_system(mode):
                system_device = pick_system_audio_device(
                    available,
                    exclude={game_device, mic_device},
                )

        command = build_ffmpeg_command(
            ffmpeg_path=self.ffmpeg_path,
            output_path=output,
            quality=config.quality,
            video_bitrate=config.video_bitrate,
            game_audio_device=game_device,
            mic_device=mic_device,
            system_audio_device=system_device,
            capture_area=(
                find_game_capture_area()
                if config.capture_mode == "game"
                else None
            ),
        )

        process = QProcess(self)
        process.setProgram(command[0])
        process.setArguments(command[1:])
        process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        workdir = Path(self.ffmpeg_path).parent
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert(
            "PATH", f"{workdir}{os.pathsep}{environment.value('PATH', '')}"
        )
        process.setProcessEnvironment(environment)
        process.errorOccurred.connect(self._on_process_error)
        process.finished.connect(self._on_process_finished)
        self.pending_process = process
        process.start()

        if not process.waitForStarted(8000):
            self.last_error = (
                "ffmpeg no arrancó. Revisa el dispositivo de audio "
                "elegido en Ajustes → Grabaciones."
            )
            process.deleteLater()
            self.failed.emit(self.last_error)
            self.pending_process = None

            return False

        self.process = process
        self.pending_process = None
        self.output_path = output
        self.config = config
        self.game_time_offset = max(0.0, float(game_time or 0.0))
        self.champion = str(champion or "")
        self.game_mode = str(game_mode or "")
        self.session = session
        self.stop_reason = ""
        self.stop_requested = False
        self.last_error = ""
        self.started_monotonic = time.monotonic()
        self.started_at = datetime.now(UTC)
        self.state_changed.emit("recording")
        self.started.emit(str(output))

        return True



    # -- parada ---------------------------------------------------------

    def stop(
        self,
        reason: str = "game_end",
        session: dict[str, Any] | None = None,
    ) -> bool:
        """Pide a ffmpeg que cierre la grabación de forma limpia.

        La señal ``finished`` llegará sola con la ruta del vídeo cuando el
        MP4 esté escrito, con los marcadores y el límite de peso aplicados.
        """
        process = self.process

        if process is None:
            return False

        if session is not None:
            self.session = session

        self.stop_reason = str(reason or "game_end")
        self.stop_requested = True

        try:
            process.write(b"q")
        except RuntimeError:
            pass

        return True

    def abort(self) -> None:
        """Para ffmpeg en seco (solo al cerrar la app si no sale solo)."""
        process = self.process

        if process is None:
            return

        self.stop_reason = self.stop_reason or "abort"
        self.stop_requested = True

        try:
            process.kill()
        except RuntimeError:
            self._reset()

    def wait_for_stop(self, timeout_ms: int | None = None) -> bool:
        process = self.process

        if process is None:
            return True

        return bool(process.waitForFinished(timeout_ms or 3000))

    def _on_process_error(self, _error: Any) -> None:
        process = self.process

        if process is None:
            return

        if self.stop_requested or process.state() != QProcess.NotRunning:
            return

        try:
            detail = (
                bytes(process.readAllStandardError()).decode(
                    "utf-8", "replace"
                ).strip()
            )
        except RuntimeError:
            detail = ""

        self.last_error = (
            "ffmpeg se detuvo al arrancar. Revisa el dispositivo de "
            "audio elegido en Ajustes → Grabaciones."
        )

        if detail:
            self.last_error += f" Detalle: {detail[-300:]}"

        finished_path = self.output_path
        self._reset()
        self.failed.emit(self.last_error)
        self._cleanup_empty_file(finished_path)

    def _on_process_finished(
        self, exit_code: int, _exit_status: Any
    ) -> None:
        process = self.process

        if process is None:
            return

        output = self.output_path
        config = self.config
        duration = self.elapsed_seconds()
        stopped_cleanly = (
            self.stop_requested
            and output is not None
            and output.is_file()
            and output.stat().st_size > 0
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
            session_dict = (
                session_dict if isinstance(session_dict, dict) else {}
            )
            game_duration = 0.0

            try:
                game_duration = max(
                    0.0,
                    float(session_dict.get("duration", 0))
                    - self.game_time_offset,
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
                "quality": config.quality if config else DEFAULT_QUALITY,
                "video_bitrate": (
                    config.video_bitrate if config else DEFAULT_BITRATE
                ),
                "mic": bool(config.mic_enabled) if config else False,
                "stop_reason": self.stop_reason or "game_end",
                "complete": True,
                "markers": markers,
                # Enlace con la sesión de telemetría guardada: la ventana
                # de repaso abre el desglose de esta misma partida.
                "session_id": str(session_dict.get("session_id") or ""),
                "local_player_key": str(
                    session_dict.get("local_player_key") or ""
                ),
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
        process, self.process = self.process, None
        self.output_path = None
        self.stop_requested = False

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
