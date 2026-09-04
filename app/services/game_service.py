from __future__ import annotations

import urllib3
import requests


urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


class GameService:
    """Cliente de la Live Client Data API local de League of Legends."""

    BASE_URL = "https://127.0.0.1:2999/liveclientdata"

    def __init__(self) -> None:
        self.timeout = 2

    def request_data(
        self,
        endpoint: str,
    ) -> dict | list | None:
        """
        Realiza una petición a la API local de League.

        La API usa un certificado local autofirmado, por eso se usa
        verify=False y se silencian sus avisos al principio del archivo.
        """

        response = requests.get(
            f"{self.BASE_URL}/{endpoint}",
            verify=False,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return response.json()

    def is_in_game(self) -> bool:
        """
        Devuelve True cuando la API local responde con datos de partida.
        """

        try:
            data = self.request_data("gamestats")
        except requests.RequestException:
            return False

        return isinstance(data, dict)

    def get_game_snapshot(self) -> dict | None:
        """
        Devuelve los datos normalizados que consume la interfaz.

        Incluye allgamedata y, cuando esté disponible, eventdata
        de la Live Client Data API local.
        """

        try:
            data = self.request_data("allgamedata")
        except requests.RequestException:
            return None

        if not isinstance(data, dict):
            return None

        try:
            event_data = self.request_data("eventdata")
        except requests.RequestException:
            event_data = {}

        if not isinstance(event_data, dict):
            event_data = {}

        game_data = data.get("gameData", {})
        active_player = data.get("activePlayer", {})
        all_players = data.get("allPlayers", [])

        if not isinstance(game_data, dict):
            game_data = {}

        if not isinstance(active_player, dict):
            active_player = {}

        if not isinstance(all_players, list):
            all_players = []

        active_name = active_player.get(
            "summonerName",
            "",
        )

        local_player = next(
            (
                player
                for player in all_players
                if (
                    player.get("summonerName") == active_name
                    or player.get("riotId") == active_name
                )
            ),
            None,
        )

        if local_player is None:
            local_player = next(
                (
                    player
                    for player in all_players
                    if not player.get("isBot", False)
                ),
                {},
            )

        local_team = local_player.get(
            "team",
            "",
        )

        enemies = [
            player
            for player in all_players
            if (
                local_team
                and player.get("team") != local_team
            )
        ]

        champion_stats = active_player.get("championStats", {})
        if not isinstance(champion_stats, dict):
            champion_stats = {}
        local_live_stats = {
            **champion_stats,
            **{
                key: active_player[key]
                for key in ("currentGold", "gold", "goldCurrent")
                if key in active_player
            },
        }

        game_time = float(
            game_data.get(
                "gameTime",
                0,
            )
        )

        events = event_data.get(
            "Events",
            [],
        )

        if not isinstance(events, list):
            events = []

        return {
            "game_mode": game_data.get(
                "gameMode",
                "UNKNOWN",
            ),
            "game_status": "IN_PROGRESS",
            "game_time": game_time,
            "champion_id": local_player.get(
                "championName",
                "",
            ),
            "item_ids": [
                item.get("itemID")
                for item in local_player.get(
                    "items",
                    [],
                )
                if (
                    isinstance(item, dict)
                    and item.get("itemID")
                )
            ],
            "local_player": local_player,
            "local_team": local_team,
            "enemies": enemies,
            "all_players": all_players,
            "local_live_stats": local_live_stats,
            "game_events": events,
        }