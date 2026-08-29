from __future__ import annotations


from copy import deepcopy
from datetime import UTC, datetime
from typing import Any


from app.services.match_history_cache import MatchHistoryCache
from app.services.riot_api_service import RiotApiError, RiotApiService



class PostgameSyncService:
    """Empareja una sesión LIVE finalizada con su Match-V5 oficial."""


    MAX_CANDIDATES = 10
    START_TOLERANCE_SECONDS = 12 * 60
    DURATION_TOLERANCE_SECONDS = 4 * 60


    def __init__(
        self,
        api_key: str,
        game_name: str,
        tag_line: str,
        account_region: str,
        platform_region: str,
        riot_api_service: RiotApiService | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.game_name = game_name.strip()
        self.tag_line = tag_line.strip()
        self.account_region = account_region
        self.platform_region = platform_region
        self.cache = MatchHistoryCache()
        self.riot_api_service = riot_api_service or RiotApiService(
            api_key=api_key,
            account_region=account_region,
            platform_region=platform_region,
            cache=self.cache,
        )


    def sync_session(
        self,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        """Devuelve una copia enriquecida o una sesión con estado pending."""
        updated = deepcopy(session)


        if not self._can_sync(updated):
            return self._set_status(
                updated,
                "live_only",
                "Sin Riot ID o API key: se conserva telemetría LIVE.",
            )


        try:
            service = RiotApiService(
                api_key=self.api_key,
                account_region=self.account_region,
                platform_region=self.platform_region,
                cache=self.cache,
            )
            account = service.get_account_by_riot_id(
                self.game_name,
                self.tag_line,
            )
            puuid = str(account["puuid"])
            match_ids = service.get_match_ids(
                puuid,
                count=self.MAX_CANDIDATES,
            )


            candidate = self._find_candidate(
                service,
                match_ids,
                puuid,
                updated,
            )
            if candidate is None:
                return self._set_status(
                    updated,
                    "pending",
                    "Esperando a que Riot procese la partida.",
                )


            match_id, raw_match = candidate
            timeline = service.get_match_timeline(match_id)
            return self._merge_riot_data(
                updated,
                raw_match,
                timeline,
                match_id,
                puuid,
            )


        except RiotApiError as error:
            status = "pending" if error.status_code in {404, 429} else "failed"
            return self._set_status(updated, status, str(error))
        except Exception as error:
            return self._set_status(
                updated,
                "failed",
                f"No se pudo sincronizar la partida: {error}",
            )


    def _can_sync(self, session: dict[str, Any]) -> bool:
        return bool(
            self.api_key
            and self.game_name
            and self.tag_line
            and session.get("local_player_key")
        )


    def _find_candidate(
        self,
        service: RiotApiService,
        match_ids: list[str],
        puuid: str,
        session: dict[str, Any],
    ) -> tuple[str, dict[str, Any]] | None:
        best: tuple[float, str, dict[str, Any]] | None = None


        for match_id in match_ids:
            raw_match = service.get_match(match_id)
            score = self._candidate_score(raw_match, puuid, session)
            if score is None:
                continue
            if best is None or score < best[0]:
                best = (score, match_id, raw_match)


        if best is None:
            return None
        return best[1], best[2]


    def _candidate_score(
        self,
        raw_match: dict[str, Any],
        puuid: str,
        session: dict[str, Any],
    ) -> float | None:
        info = raw_match.get("info", {})
        participants = info.get("participants", [])
        if not isinstance(info, dict) or not isinstance(participants, list):
            return None


        participant = next(
            (
                value
                for value in participants
                if isinstance(value, dict) and value.get("puuid") == puuid
            ),
            None,
        )
        if not isinstance(participant, dict):
            return None


        expected_champion = str(
            session.get("champion_name", "")
        ).casefold()
        actual_champion = str(
            participant.get("championName", "")
        ).casefold()
        if expected_champion and expected_champion != actual_champion:
            return None


        started_at = self._parse_time(session.get("started_at"))
        riot_start = self._number(info.get("gameStartTimestamp")) / 1000
        riot_creation = self._number(info.get("gameCreation")) / 1000
        game_start = riot_start or riot_creation
        duration = self._number(info.get("gameDuration"))
        local_duration = self._number(session.get("duration"))


        start_difference = abs(game_start - started_at.timestamp())
        duration_difference = abs(duration - local_duration)


        if start_difference > self.START_TOLERANCE_SECONDS:
            return None
        if local_duration and duration_difference > self.DURATION_TOLERANCE_SECONDS:
            return None


        return start_difference + duration_difference * 2


    def _merge_riot_data(
        self,
        session: dict[str, Any],
        raw_match: dict[str, Any],
        raw_timeline: dict[str, Any],
        match_id: str,
        puuid: str,
    ) -> dict[str, Any]:
        info = raw_match.get("info", {})
        participants = info.get("participants", [])
        if not isinstance(participants, list):
            return self._set_status(
                session,
                "failed",
                "Riot no devolvió participantes para la partida.",
            )


        local_participant = next(
            (
                value
                for value in participants
                if isinstance(value, dict) and value.get("puuid") == puuid
            ),
            {},
        )
        local_team_id = int(local_participant.get("teamId", 0))


        key_by_riot_id = {
            self._normalise_identity(meta.get("riot_id")): key
            for key, meta in session.get("players", {}).items()
        }
        key_by_champion_team = {
            (
                str(meta.get("champion_name", "")).casefold(),
                str(meta.get("team", "")).casefold(),
            ): key
            for key, meta in session.get("players", {}).items()
        }


        participant_key_map: dict[int, str] = {}
        official_scoreboard: dict[str, Any] = {}


        for participant in participants:
            if not isinstance(participant, dict):
                continue
            participant_id = int(participant.get("participantId", 0))
            name = self._participant_name(participant)
            team_name = "ORDER" if int(participant.get("teamId", 0)) == 100 else "CHAOS"
            key = key_by_riot_id.get(self._normalise_identity(name))
            if not key:
                key = key_by_champion_team.get(
                    (
                        str(participant.get("championName", "")).casefold(),
                        team_name.casefold(),
                    )
                )
            if not key:
                continue


            participant_key_map[participant_id] = key
            meta = session["players"][key]
            meta["win"] = bool(participant.get("win"))
            meta["final"] = self._official_player_stats(participant)
            meta["official_participant_id"] = participant_id
            official_scoreboard[key] = meta["final"]


        session["final_scoreboard"] = official_scoreboard
        session["winning_team"] = (
            "ORDER" if local_team_id == 100 and local_participant.get("win")
            else "CHAOS" if local_team_id == 200 and local_participant.get("win")
            else "CHAOS" if local_team_id == 100
            else "ORDER"
        )
        session["riot_match"] = raw_match
        session["riot_timeline"] = raw_timeline
        session["official_events"] = self._normalise_timeline_events(
            raw_timeline,
            participant_key_map,
            session,
        )
        session["events"] = session["official_events"] or session.get("events", [])
        session["postgame"] = True
        session["final_sync"] = {
            "status": "synced",
            "match_id": match_id,
            "synced_at": datetime.now(UTC).isoformat(),
            "source": "riot_match_v5",
            "message": "Partida sincronizada con Riot Match-V5.",
        }
        return session


    def _official_player_stats(
        self,
        participant: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            # KDA
            "kills": int(participant.get("kills", 0)),
            "deaths": int(participant.get("deaths", 0)),
            "assists": int(participant.get("assists", 0)),

            # CS
            "cs_minions": int(participant.get("minionsKilled", 0)),
            "cs_jungle": int(participant.get("neutralMinionsKilled", 0)),
            "cs_total": (
                int(participant.get("minionsKilled", 0))
                + int(participant.get("neutralMinionsKilled", 0))
            ),

            # Nivel
            "level": int(participant.get("champLevel", 0)),

            # Economía
            "gold_earned": int(participant.get("goldEarned", 0)),
            "gold_spent": int(participant.get("goldSpent", 0)),

            # Daño
            "damage_to_champions": int(
                participant.get("totalDamageDealtToChampions", 0)
            ),
            "damage_to_structures": int(
                participant.get("damageDealtToTurrets", 0)
            ),
            "damage_to_objectives": int(
                participant.get("damageDealtToObjectives", 0)
            ),
            "damage_taken": int(
                participant.get("totalDamageTaken", 0)
            ),

            # Utilidad / visión
            "healing": int(participant.get("totalHeal", 0)),
            "healing_from_teammates": int(
                participant.get("totalHealsOnTeammates", 0)
            ),
            "vision_score": int(participant.get("visionScore", 0)),
            "wards_placed": int(participant.get("wardsPlaced", 0)),
            "wards_killed": int(participant.get("wardsKilled", 0)),
            "control_wards_purchased": int(
                participant.get("detectorWardsPlaced", 0)
            ),
            "time_cc_dealt": int(
                participant.get("totalTimeCrowdControlDealt", 0)
            ),

            # Objetos (finales)
            "items": [
                int(participant.get(f"item{index}", 0))
                for index in range(7)
                if int(participant.get(f"item{index}", 0)) > 0
            ],

            # Runas / hechizos (útiles para análisis)
            "perk0": int(participant.get("perk0", 0)),
            "perk1": int(participant.get("perk1", 0)),
            "perk2": int(participant.get("perk2", 0)),
            "perk3": int(participant.get("perk3", 0)),
            "perk4": int(participant.get("perk4", 0)),
            "perk5": int(participant.get("perk5", 0)),
            "stat_perk_0": int(participant.get("statPerk0", 0)),
            "stat_perk_1": int(participant.get("statPerk1", 0)),
            "stat_perk_2": int(participant.get("statPerk2", 0)),
            "spell1_id": int(participant.get("spell1Id", 0)),
            "spell2_id": int(participant.get("spell2Id", 0)),

            # Resultado
            "win": bool(participant.get("win")),
        }


    def _normalise_timeline_events(
        self,
        timeline: dict[str, Any],
        key_map: dict[int, str],
        session: dict[str, Any],
    ) -> list[dict[str, Any]]:
        frames = timeline.get("info", {}).get("frames", [])
        if not isinstance(frames, list):
            return []
        events = []
        order = 0
        for frame in frames:
            for raw_event in frame.get("events", []):
                if not isinstance(raw_event, dict):
                    continue
                normalised = self._normalise_event(
                    raw_event,
                    key_map,
                    session,
                    order,
                )
                if normalised is not None:
                    events.append(normalised)
                    order += 1
        return events


    def _normalise_event(
        self,
        event: dict[str, Any],
        key_map: dict[int, str],
        session: dict[str, Any],
        order: int,
    ) -> dict[str, Any] | None:
        event_type = str(event.get("type", ""))
        timestamp = self._number(event.get("timestamp")) / 1000
        participant_key = key_map.get(int(event.get("participantId", 0)))
        killer_key = key_map.get(int(event.get("killerId", 0)))
        victim_key = key_map.get(int(event.get("victimId", 0)))

        if event_type == "CHAMPION_KILL":
            killer_champion = self._champion_name(session, killer_key)
            victim_champion = self._champion_name(session, victim_key)

            result = self._event(
                timestamp,
                order,
                "kill_exact",
                killer_key,
                session,
                f"{killer_champion} asesinó a {victim_champion}",
                killer_key=killer_key,
                victim_key=victim_key,
                assister_keys=[
                    key_map[value]
                    for value in event.get("assistingParticipantIds", [])
                    if value in key_map
                ],
            )
            
            print(f"[DEBUG] Kill event: {result['label']} at {result['time']}")
            
            return result
        
        if event_type in {
            "ITEM_PURCHASED",
            "ITEM_SOLD",
            "ITEM_DESTROYED",
            "ITEM_UNDO",
        }:
            actions = {
                "ITEM_PURCHASED": "Compró",
                "ITEM_SOLD": "Vendió",
                "ITEM_DESTROYED": "Retiró",
                "ITEM_UNDO": "Deshizo compra de",
            }
            item_id = int(event.get("itemId", 0))

            # Obtener versión de la partida (si existe)
            match_info = session.get("riot_match", {}).get("info", {})
            version = match_info.get("gameVersion", "").split(".")[0:3]
            version_str = ".".join(version) if len(version) >= 3 else None

            item_info = self.riot_api_service.resolve_item(
                item_id,
                version=version_str,
            )

            return self._event(
                timestamp,
                order,
                event_type.casefold(),
                participant_key,
                session,
                f"{actions[event_type]} {item_info['name']}",
                item_id=item_id,
                item_name=item_info["name"],
                item_image=item_info["image"],
            )


        if event_type == "BUILDING_KILL":
            team_id = int(event.get("killerTeamId", 0))
            killer_key = key_map.get(int(event.get("killerId", 0)))
            building = str(event.get("buildingType", "edificio")).replace("_", " ").title()
            return self._event(
                timestamp,
                order,
                "objective",
                killer_key,
                session,
                f"{self._team_label(session, team_id)} consiguió {building}",
                objective=building,
            )


        if event_type == "ELITE_MONSTER_KILL":
            team_id = int(event.get("killerTeamId", 0))
            monster = str(event.get("monsterType", "objetivo")).replace("_", " ").title()
            return self._event(
                timestamp,
                order,
                "objective",
                killer_key,
                session,
                f"{self._team_label(session, team_id)} consiguió {monster}",
                objective=monster,
            )
        return None


    def _event(self, time_value, order, event_type, player_key, session, label, **extra):
        meta = session.get("players", {}).get(player_key, {})
        result = {
            "time": round(time_value, 1),
            "time_label": self._format_time(time_value),
            "order": order,
            "type": event_type,
            "precision": "official",
            "player_key": player_key,
            "team": meta.get("team", ""),
            "role": meta.get("role", "UNKNOWN"),
            "label": label,
        }
        result.update(extra)
        return result


    def _team_label(
        self,
        session: dict[str, Any],
        riot_team_id: int,
    ) -> str:
        """Convierte teamId oficial de Riot a aliado/enemigo de la sesión."""
        local_team = str(
            session.get(
                "local_team",
                "",
            )
        ).upper()


        if riot_team_id == 100:
            event_team = "ORDER"
        elif riot_team_id == 200:
            event_team = "CHAOS"
        else:
            return "Bando no identificado"


        if local_team and event_team == local_team:
            return "Equipo aliado"


        return "Equipo enemigo"


    @staticmethod
    def _normalise_identity(value: Any) -> str:
        return str(value or "").replace(" ", "").casefold()


    @staticmethod
    def _participant_name(participant: dict[str, Any]) -> str:
        game_name = participant.get("riotIdGameName")
        tag_line = participant.get("riotIdTagline")
        if game_name and tag_line:
            return f"{game_name}#{tag_line}"
        return str(participant.get("summonerName", ""))


    @staticmethod
    def _name(session, key, fallback):
        return str(session.get("players", {}).get(key, {}).get("riot_id", fallback))

    @staticmethod
    def _champion_name(session: dict[str, Any], key: str | None) -> str:
        if not key:
            return "Un campeón"
        player = session.get("players", {}).get(key, {})
        champion = player.get("champion_name")
        if not champion:
            return "Un campeón"
        return str(champion)

    @staticmethod
    def _format_time(value: float) -> str:
        minutes, seconds = divmod(max(0, int(value)), 60)
        return f"{minutes:02d}:{seconds:02d}"


    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0


    @staticmethod
    def _parse_time(value: Any) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return datetime.now(UTC)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)


    @staticmethod
    def _set_status(session, status, message):
        session["final_sync"] = {
            "status": status,
            "match_id": session.get("final_sync", {}).get("match_id"),
            "synced_at": None,
            "source": "riot_match_v5" if status == "synced" else "live_client_data_api",
            "message": message,
        }
        return session