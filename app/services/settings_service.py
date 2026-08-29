from __future__ import annotations

import json
from pathlib import Path

import requests


class SettingsService:
    def __init__(self) -> None:
        self.settings_path = (
            Path.home()
            / ".solralol"
            / "settings.json"
        )

    def load(self) -> dict:
        try:
            with self.settings_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                settings = json.load(file)
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ):
            return {}

        if not isinstance(settings, dict):
            return {}

        return settings

    def save(self, settings: dict) -> None:
        self.settings_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.settings_path.with_suffix(
            ".tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                settings,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temporary_path.replace(self.settings_path)

    def save_riot_api_key(self, api_key: str) -> None:
        settings = self.load()
        settings["riot_api_key"] = api_key.strip()
        self.save(settings)

    def clear_riot_api_key(self) -> None:
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