from __future__ import annotations

import requests


class LiveClient:
    """
    Cliente para la API local de League of Legends (puerto 2999, HTTPS).
    """

    def __init__(self, port: int = 2999) -> None:
        self.port = port
        self.base_url = f"https://127.0.0.1:{port}"

    @property
    def isingame(self) -> bool:
        try:
            response = requests.get(
                f"{self.base_url}/liveclientdata/activeplayer",
                timeout=2,
                verify=False
            )
            response.raise_for_status()
            return True
        except Exception:
            return False

    def getallgamedata(self) -> dict:
        response = requests.get(
            f"{self.base_url}/liveclientdata/allgamedata",
            timeout=2,
            verify=False
        )
        response.raise_for_status()
        return response.json()

    def getactiveplayer(self) -> dict:
        response = requests.get(
            f"{self.base_url}/liveclientdata/activeplayer",
            timeout=2,
            verify=False
        )
        response.raise_for_status()
        return response.json()

    def getgamestats(self) -> dict:
        response = requests.get(
            f"{self.base_url}/liveclientdata/gamestats",
            timeout=2,
            verify=False
        )
        response.raise_for_status()
        return response.json()

    def getchampionstats(self) -> dict:
        response = requests.get(
            f"{self.base_url}/liveclientdata/championstats",
            timeout=2,
            verify=False
        )
        response.raise_for_status()
        return response.json()