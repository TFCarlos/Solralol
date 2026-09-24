from __future__ import annotations

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://127.0.0.1:2999/liveclientdata"


class LiveClient:
    """Cliente de solo lectura para la Live Client Data API local de LoL."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.verify = False

    def _get(self, endpoint: str) -> dict:
        response = self.session.get(
            f"{BASE_URL}/{endpoint}",
            timeout=2,
        )
        response.raise_for_status()
        return response.json()

    def is_in_game(self) -> bool:
        try:
            self._get("allgamedata")
            return True
        except requests.RequestException:
            return False

    def get_all_game_data(self) -> dict:
        return self._get("allgamedata")

    def get_active_player(self) -> dict:
        return self._get("activeplayer")

    def get_game_stats(self) -> dict:
        return self._get("gamestats")

    def get_champion_stats(self) -> dict:
        return self._get("championstats")