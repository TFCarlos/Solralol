"""Pitidos del overlay de la partida en vivo.

Los sonidos se generan en memoria (onda senoidal, sin archivos externos) y se
reproducen de forma asíncrona para no bloquear la interfaz. Cada tipo de aviso
tiene un pitido distinto:

- ``objective``: aparición de Grumos, Heraldo o Barón (un pitido grave).
- ``dragon``: aparición del Dragón (un pitido agudo y más largo).
- ``enemy_buy``: un rival completa un objeto (doble pitido corto).

"""

from __future__ import annotations

import io
import math
import struct
import threading
import wave
from collections import deque

try:  # pragma: no cover - en Windows siempre está disponible
    import winsound
except ImportError:  # pragma: no cover - otros sistemas
    winsound = None


SAMPLE_RATE = 22_050
SAMPLE_WIDTH = 2  # 16 bits

# Patrón de cada pitido: pares (frecuencia en Hz, duración en ms).
# Una frecuencia de 0 equivale a silencio (separación entre pitidos).
SOUND_SPECS: dict[str, tuple[tuple[int, int], ...]] = {
    "objective": ((660, 190),),
    "dragon": ((990, 320),),
    "enemy_buy": ((520, 110), (0, 70), (520, 110)),
}

SOUND_KINDS = tuple(SOUND_SPECS)

VOLUME_MIN = 0.0
VOLUME_MAX = 1.0
DEFAULT_VOLUME = 0.6
MAX_PENDING_SOUNDS = 32


def build_beep_wav(kind: str, volume: float = DEFAULT_VOLUME) -> bytes:
    """Genera el WAV (16 bits mono) del pitido de ese tipo de aviso."""
    pattern = SOUND_SPECS.get(kind)

    if not pattern:
        raise ValueError(f"Tipo de sonido desconocido: {kind}")

    amplitude = int(
        32767 * max(VOLUME_MIN, min(float(volume), VOLUME_MAX))
    )
    frames = bytearray()

    for frequency, duration_ms in pattern:
        samples = int(SAMPLE_RATE * max(0, duration_ms) / 1000)

        for index in range(samples):
            if frequency <= 0 or amplitude <= 0:
                value = 0
            else:
                angle = 2 * math.pi * frequency * index / SAMPLE_RATE
                fade = min(
                    1.0,
                    index / max(1.0, SAMPLE_RATE * 0.01),
                    (samples - index) / max(1.0, SAMPLE_RATE * 0.02),
                )
                value = int(amplitude * fade * math.sin(angle))

            frames.extend(struct.pack("<h", value))

    buffer = io.BytesIO()

    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(SAMPLE_WIDTH)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(bytes(frames))

    return buffer.getvalue()


def play_wav(data: bytes) -> bool:
    """Reproduce un WAV en memoria. False si no hay forma de reproducirlo."""
    if winsound is None:
        return False

    try:
        winsound.PlaySound(data, winsound.SND_MEMORY)
    except Exception:  # noqa: BLE001 - sin audio o sonido desactivado
        return False

    return True


class OverlaySoundService:
    """Pitidos del overlay con activación y volumen configurables.

    ``player`` permite inyectar otra función de reproducción en las pruebas.
    """

    def __init__(
        self,
        enabled: bool = True,
        volume: float = DEFAULT_VOLUME,
        player=None,
        async_play: bool = True,
    ) -> None:
        self.enabled = bool(enabled)
        self.volume = self._clamp_volume(volume)
        self.player = player or play_wav
        self.async_play = bool(async_play)
        self._types = {kind: True for kind in SOUND_KINDS}
        self._cache: dict[tuple[str, int], bytes] = {}
        self._lock = threading.Lock()
        self._condition = threading.Condition()
        self._pending: deque[bytes] = deque()
        self._worker: threading.Thread | None = None
        self._closed = False

    @staticmethod
    def _clamp_volume(volume) -> float:
        try:
            value = float(volume)
        except (TypeError, ValueError):
            value = DEFAULT_VOLUME

        return max(VOLUME_MIN, min(value, VOLUME_MAX))

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def set_volume(self, volume) -> None:
        self.volume = self._clamp_volume(volume)

    def kind_enabled(self, kind: str) -> bool:
        """Preferencia propia del tipo (sin contar el interruptor general)."""
        return bool(self._types.get(kind, True))

    def set_kind_enabled(self, kind: str, enabled: bool) -> None:
        if kind in self._types:
            self._types[kind] = bool(enabled)

    def is_kind_enabled(self, kind: str) -> bool:
        """True solo si el tipo suena ahora mismo (general y propio)."""
        return self.enabled and self.kind_enabled(kind)

    def wav_for(self, kind: str) -> bytes:
        """WAV del pitido, cacheado por tipo y nivel de volumen."""
        key = (kind, int(round(self.volume * 100)))

        with self._lock:
            data = self._cache.get(key)

            if data is None:
                data = build_beep_wav(kind, self.volume)
                self._cache[key] = data

        return data

    def play(self, kind: str) -> bool:
        """Reproduce el pitido de ese tipo. False si no suena."""
        if self._closed or kind not in SOUND_SPECS or not self.is_kind_enabled(kind):
            return False

        try:
            data = self.wav_for(kind)
        except (ValueError, OSError):
            return False

        if self.async_play:
            with self._condition:
                if self._closed:
                    return False
                if len(self._pending) >= MAX_PENDING_SOUNDS:
                    return False
                self._pending.append(data)
                if self._worker is None:
                    self._worker = threading.Thread(target=self._run, name="solralol-overlay-sound")
                    self._worker.start()
                self._condition.notify()
        else:
            self._safe_play(data)

        return True

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                data = self._pending.popleft()
            self._safe_play(data)

    def _safe_play(self, data: bytes) -> None:
        try:
            self.player(data)
        except Exception:  # noqa: BLE001 - el audio nunca rompe el overlay
            pass

    def close(self) -> None:
        """Stop process-owned audio and wait briefly for sound workers to exit."""
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
            worker = self._worker
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except (ImportError, RuntimeError):
            pass
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2)

    def play_objective_spawn(self) -> bool:
        """Grumos, Heraldo o Barón a punto de aparecer."""
        return self.play("objective")

    def play_dragon_spawn(self) -> bool:
        """Dragón a punto de aparecer."""
        return self.play("dragon")

    def play_enemy_buy(self) -> bool:
        """Un rival ha completado un objeto."""
        return self.play("enemy_buy")

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "volume": self.volume,
            "types": dict(self._types),
        }
