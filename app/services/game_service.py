from __future__ import annotations

import requests
import time


class GameService:
    """Cliente de la Live Client Data API local de League of Legends."""

    BASE_URL = "https://127.0.0.1:2999/liveclientdata"

    def __init__(self) -> None:
        self.timeout = 2
        self._runes_cache: dict | None = None
        self._runes_cache_identity: tuple[str, str] | None = None
        self._runes_loaded_at = 0.0
        self._runes_retry_after = 0.0
        self._last_game_time: float | None = None

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

    def get_live_snapshot(self) -> dict | None:
        """Read only the documented lightweight Live Client endpoints.

        The self-signed certificate exception is scoped to each loopback
        request; certificate policy for any other connection is untouched.
        """
        try:
            active = self.request_data("activeplayer")
            players = self.request_data("playerlist")
            stats = self.request_data("gamestats")
        except requests.RequestException:
            return None
        if not isinstance(active, dict) or not isinstance(players, list) or not isinstance(stats, dict):
            return None
        try:
            game_time = float(stats.get("gameTime", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            game_time = 0.0
        if self._last_game_time is not None and game_time + 5 < self._last_game_time:
            # A new match can reuse the same player identity and champion but
            # have a different rune page. Never carry the previous game's page.
            self._runes_cache = None
            self._runes_cache_identity = None
            self._runes_loaded_at = 0.0
            self._runes_retry_after = 0.0
        self._last_game_time = game_time
        events: list = []
        try:
            data = self.request_data("eventdata")
            if isinstance(data, dict) and isinstance(data.get("Events"), list):
                events = data["Events"]
        except requests.RequestException:
            pass
        def identity_aliases(player: dict) -> set[str]:
            values = [player.get("summonerName"), player.get("riotId"),
                      player.get("riotIdGameName"),
                      f"{player.get('riotIdGameName', '')}#{player.get('riotIdTagLine', '')}"]
            aliases = set()
            for value in values:
                text = str(value or "").strip().casefold()
                if text:
                    aliases.add(text)
                    aliases.add(text.split("#", 1)[0])
            return aliases
        active_aliases = identity_aliases(active)
        matches = [p for p in players if isinstance(p, dict) and active_aliases.intersection(identity_aliases(p))]
        # If identity cannot be matched, keep local ownership unknown. Picking
        # the first non-bot can silently attribute the wrong champion/team.
        local = matches[0] if len(matches) == 1 else {}
        if local:
            # This documented lightweight endpoint is the only supported
            # source for the active player's full rune page (including shards).
            identity = (str(local.get("riotId") or local.get("summonerName") or
                             local.get("riotIdGameName") or "").casefold(),
                        str(local.get("championName") or local.get("rawChampionName") or "").casefold())
            if identity != self._runes_cache_identity:
                self._runes_cache = None
                self._runes_loaded_at = 0.0
                self._runes_retry_after = 0.0
                self._runes_cache_identity = identity
            cached = (self._runes_cache if identity == self._runes_cache_identity else None)
            now = time.monotonic()
            runes = cached if cached and (now - self._runes_loaded_at < 120 or now < self._runes_retry_after) else None
            if runes is None and now >= self._runes_retry_after:
                try:
                    response_runes = self.request_data("activeplayerrunes")
                    if isinstance(response_runes, dict) and response_runes:
                        runes = response_runes
                        self._runes_cache = response_runes
                        self._runes_cache_identity = identity
                        self._runes_loaded_at = now
                        self._runes_retry_after = 0.0
                    else:
                        self._runes_retry_after = now + 30
                except requests.RequestException:
                    # Retain a previous valid page through brief local API
                    # failures instead of blanking it or retrying every tick.
                    runes = cached
                    self._runes_retry_after = now + 30
            if isinstance(runes, dict):
                local = {**local, "runes": runes}
                local_index = next((index for index, player in enumerate(players)
                                    if player is matches[0]), None)
                if local_index is not None:
                    players[local_index] = local
        local_team = str(local.get("team") or "")
        champion_stats = active.get("championStats") if isinstance(active.get("championStats"), dict) else {}
        return {
            "game_mode": str(stats.get("gameMode") or "UNKNOWN"),
            "game_version": str(stats.get("gameVersion") or ""),
            "map_number": stats.get("mapNumber"),
            "game_status": "IN_PROGRESS", "game_time": stats.get("gameTime", 0),
            "local_player": local, "local_team": local_team,
            "all_players": players,
            "enemies": [p for p in players if isinstance(p, dict) and local_team and p.get("team") != local_team],
            "local_live_stats": {**champion_stats, **{k: active[k] for k in ("currentGold", "gold", "level") if k in active}},
            "local_abilities": active.get("abilities") if isinstance(active.get("abilities"), dict) else None,
            "game_events": events,
        }

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

        Args:
            None.
        Returns:
            Instantánea normalizada o None si la API no responde.
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

        def aliases(player: dict) -> set[str]:
            return {str(player.get(key)).strip().casefold() for key in
                    ("summonerName", "riotId", "riotIdGameName") if player.get(key)}

        active_aliases = aliases(active_player)
        if active_name:
            active_aliases.add(str(active_name).strip().casefold())
        matches = [player for player in all_players if isinstance(player, dict)
                   and aliases(player).intersection(active_aliases)]
        local_player = matches[0] if len(matches) == 1 else {}

        local_team = local_player.get(
            "team",
            "",
        )

        enemies = [
            player
            for player in all_players
            if (local_team and player.get("team") != local_team)
        ]

        champion_stats = active_player.get("championStats", {})
        if not isinstance(champion_stats, dict):
            champion_stats = {}
        local_live_stats = {
            **champion_stats,
            **{
                key: active_player[key]
                for key in ("currentGold", "gold", "goldCurrent", "level")
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
                if (isinstance(item, dict) and item.get("itemID"))
            ],
            "local_player": local_player,
            "local_team": local_team,
            "enemies": enemies,
            "all_players": all_players,
            "local_live_stats": local_live_stats,
            "local_abilities": active_player.get("abilities") if isinstance(active_player.get("abilities"), dict) else None,
            "game_events": events,
        }
