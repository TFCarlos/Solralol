from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

from app.services.match_history_cache import MatchHistoryCache


class RiotApiError(Exception):
    """Error controlado de la Riot API."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class RiotApiService:
    """Cliente Riot API con caché de historial y detalles de partida."""

    ACCOUNT_BASE_URLS = {
        "americas": "https://americas.api.riotgames.com",
        "asia": "https://asia.api.riotgames.com",
        "europe": "https://europe.api.riotgames.com",
    }

    PLATFORM_BASE_URLS = {
        "br1": "https://br1.api.riotgames.com",
        "eun1": "https://eun1.api.riotgames.com",
        "euw1": "https://euw1.api.riotgames.com",
        "jp1": "https://jp1.api.riotgames.com",
        "kr": "https://kr.api.riotgames.com",
        "la1": "https://la1.api.riotgames.com",
        "la2": "https://la2.api.riotgames.com",
        "na1": "https://na1.api.riotgames.com",
        "oc1": "https://oc1.api.riotgames.com",
        "ph2": "https://ph2.api.riotgames.com",
        "ru": "https://ru.api.riotgames.com",
        "sg2": "https://sg2.api.riotgames.com",
        "th2": "https://th2.api.riotgames.com",
        "tr1": "https://tr1.api.riotgames.com",
        "tw2": "https://tw2.api.riotgames.com",
        "vn2": "https://vn2.api.riotgames.com",
    }

    def __init__(
        self,
        api_key: str,
        account_region: str = "europe",
        platform_region: str = "euw1",
        cache: MatchHistoryCache | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.account_region = account_region.casefold()
        self.platform_region = platform_region.casefold()
        self.cache = cache or MatchHistoryCache()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Riot-Token": self.api_key,
                "Accept": "application/json",
            }
        )

        if self.account_region not in self.ACCOUNT_BASE_URLS:
            raise ValueError(
                "Región de cuenta no compatible: "
                f"{account_region}"
            )

        if self.platform_region not in self.PLATFORM_BASE_URLS:
            raise ValueError(
                "Región de plataforma no compatible: "
                f"{platform_region}"
            )

    def _request(
        self,
        base_url: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self.session.get(
                f"{base_url}{path}",
                params=params,
                timeout=10,
            )
        except requests.RequestException as error:
            raise RiotApiError(
                f"No se pudo conectar con Riot: {error}"
            ) from error

        if response.status_code == 401:
            raise RiotApiError(
                "La API key es inválida o ha caducado.",
                401,
            )

        if response.status_code == 403:
            raise RiotApiError(
                "La API key no tiene permisos suficientes.",
                403,
            )

        if response.status_code == 404:
            raise RiotApiError(
                "No se encontró el Riot ID, la cuenta o la partida.",
                404,
            )

        if response.status_code == 429:
            retry_after = self._retry_after_seconds(response)
            self.cache.activate_rate_limit_cooldown(
                retry_after
            )
            raise RiotApiError(
                "Riot ha limitado temporalmente las solicitudes.",
                429,
                retry_after,
            )

        if not response.ok:
            raise RiotApiError(
                f"Riot devolvió HTTP {response.status_code}.",
                response.status_code,
            )

        try:
            return response.json()
        except ValueError as error:
            raise RiotApiError(
                "Riot devolvió una respuesta no válida.",
                response.status_code,
            ) from error

    @staticmethod
    def _retry_after_seconds(
        response: requests.Response,
    ) -> int:
        value = response.headers.get("Retry-After", "")
        try:
            return max(1, int(float(value)))
        except (TypeError, ValueError):
            return MatchHistoryCache.RATE_LIMIT_COOLDOWN_SECONDS

    def get_account_by_riot_id(
        self,
        game_name: str,
        tag_line: str,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        game_name = game_name.strip()
        tag_line = tag_line.strip()

        if not game_name or not tag_line:
            raise RiotApiError(
                "Indica un Riot ID con formato Nombre#TAG."
            )

        if use_cache:
            cached = self.cache.get_account(
                game_name,
                tag_line,
                self.account_region,
            )
            if cached and cached.get("puuid"):
                return cached

        base_url = self.ACCOUNT_BASE_URLS[self.account_region]
        account = self._request(
            base_url,
            (
                "/riot/account/v1/accounts/by-riot-id/"
                f"{quote(game_name, safe='')}/"
                f"{quote(tag_line, safe='')}"
            ),
        )

        if not isinstance(account, dict) or not account.get("puuid"):
            raise RiotApiError(
                "Riot no devolvió un PUUID válido."
            )

        self.cache.save_account(
            game_name,
            tag_line,
            self.account_region,
            account,
        )
        return account

    def get_summoner_by_puuid(self, puuid: str) -> dict:
        base_url = self.PLATFORM_BASE_URLS[self.platform_region]
        result = self._request(
            base_url,
            f"/lol/summoner/v4/summoners/by-puuid/{puuid}",
        )
        if not isinstance(result, dict):
            raise RiotApiError(
                "Riot no devolvió un perfil de invocador válido."
            )
        return result

    def get_emerald_plus_puuids(self, limit_per_tier: int = 10) -> list[str]:
        """Obtiene una lista representativa de PUUIDs de jugadores en Esmeralda+ (Esmeralda, Diamante, Master, GM, Challenger)."""
        base_url = self.PLATFORM_BASE_URLS[self.platform_region]
        puuids: list[str] = []

        endpoints = [
            "/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5",
            "/lol/league/v4/grandmasterleagues/by-queue/RANKED_SOLO_5x5",
            "/lol/league/v4/masterleagues/by-queue/RANKED_SOLO_5x5",
            "/lol/league/v4/entries/RANKED_SOLO_5x5/DIAMOND/I?page=1",
            "/lol/league/v4/entries/RANKED_SOLO_5x5/EMERALD/I?page=1",
        ]

        for ep in endpoints:
            try:
                res = self._request(base_url, ep)
                entries = []
                if isinstance(res, dict):
                    entries = res.get("entries", [])
                elif isinstance(res, list):
                    entries = res

                for entry in entries[:limit_per_tier]:
                    p = entry.get("puuid")
                    if p:
                        puuids.append(str(p))
                    elif entry.get("summonerId"):
                        try:
                            summ = self._request(base_url, f"/lol/summoner/v4/summoners/{entry['summonerId']}")
                            if isinstance(summ, dict) and summ.get("puuid"):
                                puuids.append(str(summ["puuid"]))
                        except Exception:
                            pass
            except Exception:
                continue

        return puuids

    def get_match_ids(
        self,
        puuid: str,
        start: int = 0,
        count: int = 5,
    ) -> list[str]:
        base_url = self.ACCOUNT_BASE_URLS[self.account_region]
        result = self._request(
            base_url,
            f"/lol/match/v5/matches/by-puuid/{puuid}/ids",
            params={
                "start": max(0, start),
                "count": min(max(count, 1), 100),
            },
        )
        if not isinstance(result, list):
            return []
        return [str(match_id) for match_id in result]

    def get_match(self, match_id: str) -> dict:
        base_url = self.ACCOUNT_BASE_URLS[self.account_region]
        result = self._request(
            base_url,
            f"/lol/match/v5/matches/{quote(match_id, safe='')}",
        )
        if not isinstance(result, dict):
            raise RiotApiError(
                "El detalle de partida no tiene formato válido."
            )
        return result

    def get_match_timeline(
        self,
        match_id: str,
    ) -> dict[str, Any]:
        """
        Descarga la timeline oficial Match-V5 de una partida.

        Incluye frames, compras, ventas, asesinatos, asistencias,
        dragones, Barón, Heraldo, torres e inhibidores.
        """
        if not match_id:
            raise RiotApiError(
                "No se puede solicitar una timeline sin match_id."
            )

        cooldown = self.cache.rate_limit_remaining_seconds()

        if cooldown:
            raise RiotApiError(
                "Riot ha limitado las peticiones. "
                f"Vuelve a intentarlo dentro de {cooldown} s.",
                429,
                cooldown,
            )

        base_url = self.ACCOUNT_BASE_URLS[
            self.account_region
        ]

        result = self._request(
            base_url,
            (
                "/lol/match/v5/matches/"
                f"{quote(match_id, safe='')}/timeline"
            ),
        )

        if not isinstance(result, dict):
            raise RiotApiError(
                "La timeline de partida no tiene formato válido."
            )

        info = result.get(
            "info",
            {},
        )

        frames = info.get(
            "frames",
            [],
        )

        if not isinstance(frames, list):
            raise RiotApiError(
                "La timeline no contiene frames válidos."
            )

        return result

    def get_recent_matches(
        self,
        game_name: str,
        tag_line: str,
        count: int = 5,
    ) -> list[dict[str, Any]]:
        cooldown = self.cache.rate_limit_remaining_seconds()
        if cooldown:
            raise RiotApiError(
                "Riot ha limitado las peticiones. "
                f"Vuelve a intentarlo dentro de {cooldown} s.",
                429,
                cooldown,
            )

        account = self.get_account_by_riot_id(game_name, tag_line)
        puuid = str(account["puuid"])
        match_ids = self.get_match_ids(puuid, count=count)
        history = []

        for match_id in match_ids:
            cached_match = self.cache.get_match(match_id)
            if cached_match:
                history.append(cached_match)
                continue

            match = self.get_match(match_id)
            summary = self._create_match_summary(
                match,
                match_id,
                puuid,
            )
            self.cache.save_match(summary)
            history.append(summary)

        return history

    def get_match_detail(
        self,
        game_name: str,
        tag_line: str,
        match_id: str,
    ) -> dict[str, Any]:
        """Devuelve detalle completo desde caché o Riot, sin repetir descargas."""

        cached = self.cache.get_match(match_id)
        if cached and cached.get("detail_version") == 1:
            return cached

        cooldown = self.cache.rate_limit_remaining_seconds()
        if cooldown:
            raise RiotApiError(
                "Riot ha limitado las peticiones. "
                f"Vuelve a intentarlo dentro de {cooldown} s.",
                429,
                cooldown,
            )

        account = self.get_account_by_riot_id(game_name, tag_line)
        raw_match = self.get_match(match_id)
        detail = self._create_match_detail(
            raw_match,
            match_id,
            str(account["puuid"]),
        )
        self.cache.save_match(detail)
        return detail

    @staticmethod
    def _create_match_summary(
        match: dict[str, Any],
        match_id: str,
        puuid: str,
    ) -> dict[str, Any]:
        detail = RiotApiService._create_match_detail(
            match,
            match_id,
            puuid,
        )
        return {
            key: detail[key]
            for key in (
                "match_id",
                "game_creation",
                "game_duration",
                "queue_id",
                "game_mode",
                "champion_name",
                "win",
                "kills",
                "deaths",
                "assists",
                "cs",
                "items",
            )
        }

    @staticmethod
    def _create_match_detail(
        match: dict[str, Any],
        match_id: str,
        puuid: str,
    ) -> dict[str, Any]:
        info = match.get("info", {})
        participants = info.get("participants", [])
        teams = info.get("teams", [])

        if not isinstance(participants, list):
            raise RiotApiError(
                "La partida no contiene participantes válidos."
            )

        player = next(
            (
                item
                for item in participants
                if item.get("puuid") == puuid
            ),
            None,
        )
        if not isinstance(player, dict):
            raise RiotApiError(
                "No se encontró al invocador en la partida."
            )

        player_team_id = int(player.get("teamId", 0))
        allies = []
        enemies = []

        for participant in participants:
            if not isinstance(participant, dict):
                continue

            entry = RiotApiService._participant_detail(
                participant,
                is_player=participant.get("puuid") == puuid,
            )

            if int(participant.get("teamId", 0)) == player_team_id:
                allies.append(entry)
            else:
                enemies.append(entry)

        player_team = next(
            (
                team
                for team in teams
                if int(team.get("teamId", 0)) == player_team_id
            ),
            {},
        )
        enemy_team = next(
            (
                team
                for team in teams
                if int(team.get("teamId", 0)) != player_team_id
            ),
            {},
        )

        return {
            "detail_version": 1,
            "match_id": match_id,
            "game_creation": info.get("gameCreation"),
            "game_duration": info.get("gameDuration"),
            "queue_id": info.get("queueId"),
            "game_mode": info.get("gameMode"),
            "game_type": info.get("gameType"),
            "champion_name": player.get("championName"),
            "win": bool(player.get("win")),
            "kills": int(player.get("kills", 0)),
            "deaths": int(player.get("deaths", 0)),
            "assists": int(player.get("assists", 0)),
            "cs": (
                int(player.get("totalMinionsKilled", 0))
                + int(player.get("neutralMinionsKilled", 0))
            ),
            "items": [
                int(player.get(f"item{index}", 0))
                for index in range(7)
            ],
            "player_team_id": player_team_id,
            "allies": allies,
            "enemies": enemies,
            "objectives": {
                "allies": RiotApiService._objective_counts(
                    player_team
                ),
                "enemies": RiotApiService._objective_counts(
                    enemy_team
                ),
            },
        }

    def resolve_item(
        self,
        item_id: int,
        version: str | None = None,
        language: str = "es_ES",
    ) -> dict[str, Any]:
        """
        Convierte un ID de objeto en nombre e imagen usando Data Dragon.
        """
        if not item_id or item_id == 0:
            return {
                "id": 0,
                "name": "Objeto desconocido",
                "image": None,
            }

        # Si no se pasa versión, usamos "latest"
        if not version:
            version = "latest"

        base_url = (
            f"https://ddragon.leagueoflegends.com/cdn/"
            f"{version}/data/{language}/item.json"
        )

        try:
            response = self.session.get(
                base_url,
                timeout=5,  # <-- IMPORTANTE: timeout de 5 segundos
            )
            response.raise_for_status()
            data = response.json()

            item_data = data.get("data", {}).get(str(item_id))
            if not item_data:
                return {
                    "id": item_id,
                    "name": f"Objeto {item_id}",
                    "image": None,
                }

            image_url = (
                f"https://ddragon.leagueoflegends.com/cdn/"
                f"{version}/img/item/"
                f"{item_id}.png"
            )

            return {
                "id": item_id,
                "name": item_data.get("name", f"Objeto {item_id}"),
                "image": image_url,
            }

        except Exception:
            return {
                "id": item_id,
                "name": f"Objeto {item_id}",
                "image": None,
            }

    @staticmethod
    def _participant_detail(
        participant: dict[str, Any],
        is_player: bool,
    ) -> dict[str, Any]:
        return {
            "is_player": is_player,
            "riot_id_game_name": participant.get(
                "riotIdGameName"
            )
            or participant.get("summonerName")
            or "Desconocido",
            "riot_id_tag_line": participant.get(
                "riotIdTagline"
            )
            or "",
            "champion_name": participant.get("championName")
            or "Desconocido",
            "team_position": participant.get("teamPosition")
            or participant.get("individualPosition")
            or "",
            "win": bool(participant.get("win")),
            "kills": int(participant.get("kills", 0)),
            "deaths": int(participant.get("deaths", 0)),
            "assists": int(participant.get("assists", 0)),
            "cs": (
                int(participant.get("totalMinionsKilled", 0))
                + int(participant.get("neutralMinionsKilled", 0))
            ),
            "gold_earned": int(participant.get("goldEarned", 0)),
            "vision_score": int(participant.get("visionScore", 0)),
            "champ_level": int(participant.get("champLevel", 0)),
            "items": [
                int(participant.get(f"item{index}", 0))
                for index in range(7)
            ],
        }

    @staticmethod
    def _objective_counts(team: dict[str, Any]) -> dict[str, int]:
        objectives = team.get("objectives", {})

        def count(name: str) -> int:
            value = objectives.get(name, {})
            if not isinstance(value, dict):
                return 0
            return int(value.get("kills", 0))

        return {
            "baron": count("baron"),
            "dragon": count("dragon"),
            "rift_herald": count("riftHerald"),
            "tower": count("tower"),
            "inhibitor": count("inhibitor"),
        }
