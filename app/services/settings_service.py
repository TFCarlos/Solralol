from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import requests

from app.services.storage_manager import atomic_write_json, get_storage_manager, serialized_file_access

_QUALITY_KEYS = {"1080", "108030", "900", "90030", "720", "72030", "540", "480", "420"}
_BITRATE_VALUES = {16000, 12000, 8000, 6000, 4000, 2500, 1500}
_AUDIO_MODES = {"none", "game", "mic", "game_mic", "all", "full"}
_OVERLAY_PANELS = ("gold", "alerts", "purchase", "recall", "ability")


class SettingsService:
    def __init__(self) -> None:
        self.settings_path = get_storage_manager().settings_path
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            try:
                with self.settings_path.open("r", encoding="utf-8") as file:
                    settings = json.load(file)
            except (FileNotFoundError, OSError, json.JSONDecodeError):
                return {}

        if not isinstance(settings, dict):
            return {}

        return settings

    def load_settings(self) -> dict:
        """Alias de load() para compatibilidad."""
        return self.load()

    def save(self, settings: dict) -> None:
        with self._lock:
            atomic_write_json(self.settings_path, settings)

    def electron_snapshot(self) -> dict[str, Any]:
        """Return the settings supported by the desktop renderer, redacting secrets.

        Unknown keys remain in the file and are deliberately not round-tripped
        through the renderer. This prevents an old or partial UI payload from
        erasing preferences owned by other Solralol modules.
        """
        raw = self.load()
        default_output = str(get_storage_manager().recordings_dir)
        audio_mode = str(raw.get("recording_audio_mode") or "").strip()
        if audio_mode not in _AUDIO_MODES:
            uses_game = bool(str(raw.get("recording_game_audio_device") or "").strip())
            uses_mic = bool(raw.get("recording_mic_enabled"))
            uses_system = bool(raw.get("recording_mic_capture_enabled"))
            audio_mode = (
                "full" if uses_system else "game_mic" if uses_game and uses_mic
                else "mic" if uses_mic else "game" if uses_game else "none"
            )
        try:
            size_limit = min(500, max(1, float(raw.get("recording_size_limit_gb", 50))))
        except (TypeError, ValueError):
            size_limit = 50.0
        try:
            monitor_index = max(-1, int(raw.get("recording_monitor_index", -1)))
        except (TypeError, ValueError):
            monitor_index = -1
        try:
            bitrate = int(raw.get("recording_bitrate", 8000))
        except (TypeError, ValueError):
            bitrate = 8000
        if bitrate not in _BITRATE_VALUES:
            bitrate = 8000
        quality = str(raw.get("recording_quality", "1080"))
        if quality not in _QUALITY_KEYS:
            quality = "1080"
        defaults: dict[str, Any] = {
            "recording_auto": True,
            "recording_monitor_index": monitor_index,
            "recording_quality": quality,
            "recording_bitrate": bitrate,
            "recording_mic_enabled": False,
            "recording_mic_capture_enabled": False,
            "recording_mic_capture_device": "",
            "recording_system_audio_device": "",
            "recording_mic_device": "",
            "recording_game_audio_device": "",
            "recording_output_dir": default_output,
            "recording_size_limit_gb": size_limit,
            "recording_audio_mode": audio_mode,
            "overlay_panels": {key: True for key in _OVERLAY_PANELS},
            "overlay_tab_only": {key: False for key in _OVERLAY_PANELS},
            "overlay_panel_opacity": {key: 92 for key in _OVERLAY_PANELS},
            "overlay_panel_click_through": {key: False for key in _OVERLAY_PANELS},
            "overlay_panel_scales": {key: 1.0 for key in _OVERLAY_PANELS},
            "overlay_positions": {},
            "overlay_edit_shortcut": "Control+Alt+Shift+O",
            "overlay_ability_hud_anchor": {"x": 0.5, "y": 0.89},
            "overlay_ability_slot_spacing": 47,
            "overlay_alert_duration": 8,
            "overlay_alert_lead": 60,
            "overlay_sound_enabled": True,
            "overlay_sound_volume": 0.6,
            "overlay_sound_objective": True,
            "overlay_sound_dragon": True,
            "overlay_sound_enemy_buy": True,
            "overlay_click_through": False,
        }
        settings = {key: raw.get(key, value) for key, value in defaults.items()}
        for key in ("overlay_panels", "overlay_tab_only", "overlay_panel_opacity", "overlay_panel_click_through", "overlay_panel_scales", "overlay_positions"):
            settings[key] = {panel: value for panel, value in (settings[key] if isinstance(settings[key], dict) else {}).items() if panel in _OVERLAY_PANELS}
        settings.update({
            "recording_audio_mode": audio_mode,
            "recording_monitor_index": monitor_index,
            "recording_quality": quality,
            "recording_bitrate": bitrate,
            "recording_size_limit_gb": size_limit,
            "recording_output_dir": str(raw.get("recording_output_dir") or default_output),
        })
        settings["riot_api_key_configured"] = bool(raw.get("riot_api_key"))
        settings["gemini_api_key_configured"] = bool(raw.get("gemini_api_key"))
        return settings

    def update_electron_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Validate and merge renderer-owned preferences without replacing the file."""
        if not isinstance(changes, dict) or not changes:
            raise ValueError("No hay cambios de configuración válidos.")
        with self._lock, serialized_file_access(self.settings_path):
            existing = self.load()
            validated = _validate_electron_settings(changes)
            for key, value in validated.items():
                if isinstance(value, dict) and isinstance(existing.get(key), dict):
                    merged = dict(existing[key])
                    merged.update(value)
                    validated[key] = merged
            existing.update(validated)
            self.save(existing)
            return self.electron_snapshot()

    def store_validated_api_key(self, provider: str, api_key: str) -> tuple[bool, str, bool]:
        """Validate a credential before persisting; never return the secret."""
        key = api_key.strip()
        valid, message = (
            self.validate_riot_api_key(key)
            if provider == "riot"
            else self.validate_gemini_api_key(key)
            if provider == "gemini"
            else (False, "Proveedor de clave no válido.")
        )
        if provider not in {"riot", "gemini"}:
            raise ValueError("Proveedor de clave no válido.")
        with self._lock, serialized_file_access(self.settings_path):
            settings = self.load()
            if valid:
                settings[f"{provider}_api_key"] = key
                self.save(settings)
        return valid, message, bool(settings.get(f"{provider}_api_key"))

    def clear_api_key(self, provider: str) -> None:
        if provider not in {"riot", "gemini"}:
            raise ValueError("Proveedor de clave no válido.")
        with self._lock, serialized_file_access(self.settings_path):
            settings = self.load()
            settings.pop(f"{provider}_api_key", None)
            self.save(settings)

    def save_riot_api_key(self, api_key: str) -> None:
        with self._lock, serialized_file_access(self.settings_path):
            settings = self.load()
            settings["riot_api_key"] = api_key.strip()
            self.save(settings)

    def clear_riot_api_key(self) -> None:
        with self._lock, serialized_file_access(self.settings_path):
            settings = self.load()
            settings.pop("riot_api_key", None)
            self.save(settings)

    def validate_riot_api_key(
        self,
        api_key: str,
    ) -> tuple[bool, str]:
        api_key = api_key.strip()

        if not api_key:
            return (
                False,
                "Introduce una Riot API key antes de guardar.",
            )

        try:
            response = requests.get(
                "https://euw1.api.riotgames.com/"
                "lol/status/v4/platform-data",
                headers={
                    "X-Riot-Token": api_key,
                    "Accept": "application/json",
                },
                timeout=10,
            )
        except requests.RequestException as error:
            return (
                False,
                "No se pudo conectar con Riot: "
                f"{error}",
            )

        if response.status_code == 200:
            return (
                True,
                "API key válida y guardada.",
            )

        if response.status_code == 401:
            return (
                False,
                "API key inválida o caducada.",
            )

        if response.status_code == 403:
            return (
                False,
                "La API key no tiene permisos suficientes.",
            )

        if response.status_code == 429:
            return (
                False,
                "Riot ha limitado temporalmente "
                "las peticiones. Espera e inténtalo "
                "de nuevo.",
            )

        return (
            False,
            "Riot devolvió HTTP "
            f"{response.status_code} al validar la clave.",
        )

    def save_gemini_api_key(self, api_key: str) -> None:
        settings = self.load()
        settings["gemini_api_key"] = api_key.strip()
        self.save(settings)

    def clear_gemini_api_key(self) -> None:
        settings = self.load()
        settings.pop("gemini_api_key", None)
        self.save(settings)

    def validate_gemini_api_key(self, api_key: str) -> tuple[bool, str]:
        api_key = api_key.strip()

        if not api_key:
            return (
                False,
                "Introduce una Gemini API key antes de guardar.",
            )

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            response = requests.get(
                url,
                headers={"Accept": "application/json"},
                timeout=10,
            )
        except requests.RequestException as error:
            return (
                False,
                "No se pudo conectar con Google AI Studio (Gemini). Comprueba la conexión e inténtalo de nuevo.",
            )

        if response.status_code == 200:
            return (
                True,
                "Gemini API key válida y guardada correctamente.",
            )

        if response.status_code in (400, 401, 403):
            return (
                False,
                "Gemini API key inválida o no autorizada.",
            )

        if response.status_code == 429:
            return (
                False,
                "Límite de peticiones de Gemini excedido (Rate limit).",
            )

        return (
            False,
            f"Google AI Studio devolvió HTTP {response.status_code} al validar la clave.",
        )


def _validate_electron_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """Whitelist and validate settings editable in the Electron renderer."""
    panels = set(_OVERLAY_PANELS)
    scalar_types = {
        "recording_auto": bool,
        "recording_monitor_index": int,
        "recording_quality": str,
        "recording_bitrate": int,
        "recording_audio_mode": str,
        "recording_mic_device": str,
        "recording_system_audio_device": str,
        "recording_mic_capture_device": str,
        "recording_game_audio_device": str,
        "recording_output_dir": str,
        "recording_size_limit_gb": (int, float),
        "overlay_alert_duration": int,
        "overlay_alert_lead": int,
        "overlay_sound_enabled": bool,
        "overlay_sound_volume": (int, float),
        "overlay_sound_objective": bool,
        "overlay_sound_dragon": bool,
        "overlay_sound_enemy_buy": bool,
        "overlay_click_through": bool,
        "overlay_ability_slot_spacing": int,
        "overlay_edit_shortcut": str,
    }
    mapping_types = {
        "overlay_panels": bool,
        "overlay_tab_only": bool,
        "overlay_panel_opacity": int,
        "overlay_panel_click_through": bool,
        "overlay_panel_scales": (int, float),
    }
    result: dict[str, Any] = {}
    for key, value in changes.items():
        if key == "overlay_ability_hud_anchor":
            if (not isinstance(value, dict) or set(value) != {"x", "y"}
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values())
                or not 0.1 <= value["x"] <= 0.9 or not 0.6 <= value["y"] <= 0.98):
                raise ValueError("Ancla HUD no válida.")
            result[key] = value
            continue
        if key in scalar_types:
            expected = scalar_types[key]
            if isinstance(value, bool) and expected in (int, float, (int, float)):
                raise ValueError(f"Valor no válido para {key}.")
            if not isinstance(value, expected):
                raise ValueError(f"Valor no válido para {key}.")
            if isinstance(value, str) and len(value) > 1024:
                raise ValueError(f"El valor de {key} es demasiado largo.")
            result[key] = value
            continue
        if key == "overlay_positions":
            if (not isinstance(value, dict) or set(value) - panels or any(
                not isinstance(point, list) or len(point) != 2 or any(isinstance(n, bool) or not isinstance(n, int) or abs(n) > 100000 for n in point)
                for point in value.values()
            )):
                raise ValueError("Posición de overlay no válida.")
            result[key] = value
            continue
        if key in mapping_types:
            if not isinstance(value, dict) or set(value) - panels:
                raise ValueError(f"Mapa no válido para {key}.")
            expected = mapping_types[key]
            if any(
                not isinstance(item, expected)
                or (isinstance(item, bool) and expected != bool)
                for item in value.values()
            ):
                raise ValueError(f"Valor no válido para {key}.")
            result[key] = value
            continue
        raise ValueError(f"Ajuste no permitido: {key}.")

    if "recording_quality" in result and result["recording_quality"] not in _QUALITY_KEYS:
        raise ValueError("Calidad de grabación no válida.")
    if "recording_bitrate" in result and result["recording_bitrate"] not in _BITRATE_VALUES:
        raise ValueError("Bitrate de grabación no válido.")
    if "recording_audio_mode" in result and result["recording_audio_mode"] not in _AUDIO_MODES:
        raise ValueError("Modo de audio no válido.")
    if "recording_monitor_index" in result and result["recording_monitor_index"] < -1:
        raise ValueError("Monitor de grabación no válido.")
    if "recording_size_limit_gb" in result and not 1 <= result["recording_size_limit_gb"] <= 500:
        raise ValueError("El límite debe estar entre 1 y 500 GB.")
    if "overlay_alert_duration" in result and result["overlay_alert_duration"] not in {3, 5, 8, 10}:
        raise ValueError("Duración de aviso no válida.")
    if "overlay_ability_slot_spacing" in result and not 43 <= result["overlay_ability_slot_spacing"] <= 72:
        raise ValueError("La separación de habilidades debe estar entre 43 y 72 DIP.")
    if "overlay_alert_lead" in result and not 15 <= result["overlay_alert_lead"] <= 180:
        raise ValueError("La anticipación debe estar entre 15 y 180 segundos.")
    if "overlay_sound_volume" in result and not 0 <= result["overlay_sound_volume"] <= 1:
        raise ValueError("El volumen debe estar entre 0 y 1.")
    for key in ("overlay_panel_opacity",):
        if key in result and any(not 0 <= value <= 100 for value in result[key].values()):
            raise ValueError("La opacidad debe estar entre 0 y 100 %.")
    if "overlay_panel_scales" in result and any(not .5 <= value <= 1.5 for value in result["overlay_panel_scales"].values()):
        raise ValueError("El tamaño del overlay debe estar entre 50 y 150 %.")
    if "overlay_edit_shortcut" in result:
        import re
        if not re.fullmatch(r"Control\+Alt\+Shift\+[A-Z]", result["overlay_edit_shortcut"]):
            raise ValueError("Atajo de edición no válido.")
    return result
