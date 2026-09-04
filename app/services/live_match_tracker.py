from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LiveMatchTracker:
    """Registra telemetría local y guarda sesiones analizables."""

    SAMPLE_INTERVAL_SECONDS = 2.0
    MAX_SAVED_SESSIONS = 50
    ROLES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

    ROLE_ALIASES = {
        "TOP": "TOP",
        "JUNG": "JUNGLE",
        "JUNGLE": "JUNGLE",
        "MID": "MIDDLE",
        "MIDDLE": "MIDDLE",
        "BOTTOM": "BOTTOM",
        "BOT": "BOTTOM",
        "ADC": "BOTTOM",
        "APC": "BOTTOM",
        "UTILITY": "UTILITY",
        "SUP": "UTILITY",
        "SUPPORT": "UTILITY",
    }

    OBJECTIVE_EVENTS = {
        "dragonkill": ("dragon", "Dragón"),
        "baronkill": ("baron", "Barón"),
        "heraldkill": ("rift_herald", "Heraldo"),
        "turretkilled": ("tower", "Torre"),
        "inhibkilled": ("inhibitor", "Inhibidor"),
    }

    def __init__(self, item_catalog: dict[str, Any]) -> None:
        self.item_catalog = item_catalog
        self.sessions_path = (
            Path.home() / ".solralol" / "live_match_sessions.json"
        )
        self.session: dict[str, Any] | None = None
        self.last_sample_time = -1.0
        self.event_order = 0

    @property
    def is_tracking(self) -> bool:
        return self.session is not None

    def start(self, snapshot: dict[str, Any]) -> None:
        local_player = snapshot.get("local_player", {})
        started_at = datetime.now(UTC).isoformat()
        champion_name = str(
            local_player.get("championName", "Desconocido")
        )

        self.session = {
            "schema_version": 2,
            "session_id": self._make_session_id(
                started_at,
                champion_name,
            ),
            "started_at": started_at,
            "ended_at": None,
            "game_mode": snapshot.get("game_mode", "UNKNOWN"),
            "local_team": snapshot.get("local_team", ""),
            "local_player_key": "",
            "champion_name": champion_name,
            "player_riot_id": self._display_name(local_player),
            "duration": 0.0,
            "players": {},
            "lane_matchups": {
                role: {"ally_key": None, "enemy_key": None}
                for role in self.ROLES
            },
            "snapshots": [],
            "events": [],
            "player_timelines": {},
            "seen_event_ids": [],
            "last_player_state": {},
            "final_scoreboard": {},
            "final_sync": {
                "status": "live_only",
                "match_id": None,
                "synced_at": None,
            },
        }

        self.last_sample_time = -1.0
        self.event_order = 0
        self.update(snapshot, force=True)

    def update(
        self,
        snapshot: dict[str, Any],
        force: bool = False,
    ) -> None:
        if self.session is None:
            return

        game_time = self._float(snapshot.get("game_time", 0))
        if (
            not force
            and game_time - self.last_sample_time
            < self.SAMPLE_INTERVAL_SECONDS
        ):
            return

        self._index_players(snapshot)
        self._record_exact_events(snapshot)
        point = self._build_snapshot_point(snapshot)
        self.session["snapshots"].append(point)
        self.session["duration"] = game_time
        self.last_sample_time = game_time
        self._detect_player_changes(point)

    def finish(self) -> dict[str, Any] | None:
        if self.session is None:
            return None

        completed = deepcopy(self.session)
        completed["ended_at"] = datetime.now(UTC).isoformat()
        completed["final_scoreboard"] = self._build_final_scoreboard(
            completed
        )
        completed.pop("seen_event_ids", None)
        completed.pop("last_player_state", None)

        sessions = self.load_saved_sessions()
        sessions.append(completed)
        self._save_sessions(sessions[-self.MAX_SAVED_SESSIONS :])

        self.session = None
        self.last_sample_time = -1.0
        self.event_order = 0
        return completed

    def get_live_session(self) -> dict[str, Any] | None:
        return deepcopy(self.session) if self.session else None

    def load_saved_sessions(self) -> list[dict[str, Any]]:
        try:
            with self.sessions_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def delete_saved_session(self, session_id: str) -> None:
        sessions = [
            session
            for session in self.load_saved_sessions()
            if session.get("session_id") != session_id
        ]
        self._save_sessions(sessions)

    def _index_players(self, snapshot: dict[str, Any]) -> None:
        if self.session is None:
            return

        local_team = snapshot.get("local_team", "")
        local_player = snapshot.get("local_player", {})
        local_name = self._identity(local_player)
        role_candidates = {
            role: {"ally": [], "enemy": []}
            for role in self.ROLES
        }

        for index, player in enumerate(
            snapshot.get("all_players", [])
        ):
            if not isinstance(player, dict):
                continue

            key = self._player_key(player, index)
            role = self._role(player)
            team = str(player.get("team", ""))
            side = "ally" if team == local_team else "enemy"

            if key not in self.session["players"]:
                self.session["players"][key] = {
                    "player_key": key,
                    "team": team,
                    "side": side,
                    "role": role,
                    "riot_id": self._display_name(player),
                    "champion_name": player.get(
                        "championName", "Desconocido"
                    ),
                    "is_local_player": (
                        self._identity(player) == local_name
                    ),
                    "win": None,
                    "final": {},
                    "items": [],
                    "summoner_spells": player.get("summonerSpells", {}),
                    "runes": player.get("runes", {}),
                }
                self.session["player_timelines"][key] = []

            metadata = self.session["players"][key]
            metadata.update(
                {
                    "role": role,
                    "side": side,
                    "team": team,
                    "items": self._item_ids(player),
                    "summoner_spells": player.get("summonerSpells", {}),
                    "runes": player.get("runes", {}),
                }
            )

            if metadata.get("is_local_player"):
                self.session["local_player_key"] = key

            if role in role_candidates:
                role_candidates[role][side].append(key)

        for role, sides in role_candidates.items():
            matchup = self.session["lane_matchups"][role]
            if sides["ally"] and matchup["ally_key"] is None:
                matchup["ally_key"] = sides["ally"][0]
            if sides["enemy"] and matchup["enemy_key"] is None:
                matchup["enemy_key"] = sides["enemy"][0]

    def _build_snapshot_point(
        self,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        if self.session is None:
            return {}

        game_time = self._float(snapshot.get("game_time", 0))
        local_key = self.session.get("local_player_key", "")
        local_live_stats = snapshot.get("local_live_stats", {})
        players: dict[str, dict[str, Any]] = {}

        for index, player in enumerate(
            snapshot.get("all_players", [])
        ):
            if not isinstance(player, dict):
                continue
            key = self._player_key(player, index)
            players[key] = self._player_point(
                player,
                local_live_stats if key == local_key else {},
                key == local_key,
            )

        return {
            "time": round(game_time, 1),
            "players": players,
        }

    def _player_point(
        self,
        player: dict[str, Any],
        local_live_stats: dict[str, Any],
        is_local: bool,
    ) -> dict[str, Any]:
        scores = player.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}

        items = self._item_ids(player)
        inventory_value = sum(
            self._item_cost(item_id) for item_id in items
        )
        current_gold = self._first_int(
            (local_live_stats, player, scores),
            ("currentGold", "gold", "goldCurrent"),
        )
        stats = self._stats(
            player,
            local_live_stats,
            is_local,
        )

        return {
            "level": self._int(
                player.get(
                    "level",
                    player.get("championLevel", 0),
                )
            ),
            "kills": self._int(scores.get("kills", 0)),
            "deaths": self._int(scores.get("deaths", 0)),
            "assists": self._int(scores.get("assists", 0)),
            "cs": self._int(
                scores.get(
                    "creepScore",
                    player.get("creepScore", 0),
                )
            ),
            "items": items,
            "live_stats": local_live_stats if is_local else {},
            "inventory_value": inventory_value,
            "current_gold": current_gold,
            "estimated_gold": self._estimate_gold(
                player,
                inventory_value,
                current_gold,
            ),
            "stats": stats,
            "quality": {
                "estimated_gold": "live" if current_gold is not None else "estimated",
                "damage_to_champions": (
                    "api"
                    if stats["damage_to_champions"] is not None
                    else "unavailable"
                ),
                "damage_to_structures": (
                    "api"
                    if stats["damage_to_structures"] is not None
                    else "unavailable"
                ),
                "damage_taken": (
                    "api"
                    if stats["damage_taken"] is not None
                    else "unavailable"
                ),
                "healing": (
                    "api"
                    if stats["healing"] is not None
                    else "unavailable"
                ),
                "vision_score": (
                    "api"
                    if stats["vision_score"] is not None
                    else "unavailable"
                ),
            },
        }

    def _detect_player_changes(
        self,
        point: dict[str, Any],
    ) -> None:
        if self.session is None:
            return

        time_value = point.get("time", 0.0)
        previous_states = self.session["last_player_state"]

        for key, current in point.get("players", {}).items():
            previous = previous_states.get(key)
            metadata = self.session["players"].get(key, {})
            if previous is not None:
                self._record_counter_changes(
                    key,
                    metadata,
                    previous,
                    current,
                    time_value,
                )
                self._record_cs_milestones(
                    key,
                    metadata,
                    previous,
                    current,
                    time_value,
                )
                self._record_item_changes(
                    key,
                    metadata,
                    previous,
                    current,
                    time_value,
                )
            previous_states[key] = deepcopy(current)

    def _record_counter_changes(
        self,
        key: str,
        metadata: dict[str, Any],
        previous: dict[str, Any],
        current: dict[str, Any],
        time_value: float,
    ) -> None:
        definitions = (
            ("level", "level_up", "Nivel"),
            ("kills", "kill", "Asesinato"),
            ("deaths", "death", "Muerte"),
            ("assists", "assist", "Asistencia"),
        )

        for field, event_type, label in definitions:
            old = self._int(previous.get(field, 0))
            new = self._int(current.get(field, 0))
            if new <= old:
                continue
            for value in range(old + 1, new + 1):
                self._append_event(
                    time_value=time_value,
                    event_type=event_type,
                    player_key=key,
                    team=metadata.get("team", ""),
                    role=metadata.get("role", "UNKNOWN"),
                    precision="observed",
                    label=f"{label} {value}",
                    value=value,
                )

    def _record_cs_milestones(
        self,
        key: str,
        metadata: dict[str, Any],
        previous: dict[str, Any],
        current: dict[str, Any],
        time_value: float,
    ) -> None:
        old_bucket = self._int(previous.get("cs", 0)) // 10
        new_bucket = self._int(current.get("cs", 0)) // 10
        if new_bucket <= old_bucket:
            return
        for bucket in range(old_bucket + 1, new_bucket + 1):
            cs_value = bucket * 10
            self._append_event(
                time_value=time_value,
                event_type="cs_milestone",
                player_key=key,
                team=metadata.get("team", ""),
                role=metadata.get("role", "UNKNOWN"),
                precision="observed",
                label=f"{cs_value} CS",
                value=cs_value,
            )

    def _record_item_changes(
        self,
        key: str,
        metadata: dict[str, Any],
        previous: dict[str, Any],
        current: dict[str, Any],
        time_value: float,
    ) -> None:
        old_items = previous.get("items", [])
        new_items = current.get("items", [])
        added = self._multiset_added(new_items, old_items)
        removed = self._multiset_added(old_items, new_items)

        for item_id in added:
            self._append_event(
                time_value=time_value,
                event_type="item_purchase",
                player_key=key,
                team=metadata.get("team", ""),
                role=metadata.get("role", "UNKNOWN"),
                precision="observed",
                label=f"Compra: {self._item_name(item_id)}",
                item_id=item_id,
            )

        for item_id in removed:
            self._append_event(
                time_value=time_value,
                event_type="item_removed",
                player_key=key,
                team=metadata.get("team", ""),
                role=metadata.get("role", "UNKNOWN"),
                precision="observed",
                label=f"Retira: {self._item_name(item_id)}",
                item_id=item_id,
            )

    def _record_exact_events(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        if self.session is None:
            return

        seen_ids = set(self.session["seen_event_ids"])
        for index, raw_event in enumerate(
            snapshot.get("game_events", [])
        ):
            if not isinstance(raw_event, dict):
                continue
            event_id = raw_event.get(
                "EventID",
                raw_event.get("eventId", index),
            )
            event_key = str(event_id)
            if event_key in seen_ids:
                continue
            seen_ids.add(event_key)
            self.session["seen_event_ids"].append(event_key)
            self._normalize_exact_event(raw_event)

    def _normalize_exact_event(
        self,
        raw_event: dict[str, Any],
    ) -> None:
        if self.session is None:
            return

        event_name = str(
            raw_event.get("EventName", "")
        ).casefold()
        time_value = self._float(
            raw_event.get("EventTime", 0)
        )
        killer_name = str(raw_event.get("KillerName", ""))
        victim_name = str(raw_event.get("VictimName", ""))
        killer_key = self._key_from_identity(killer_name)
        victim_key = self._key_from_identity(victim_name)

        if event_name == "championkill":
            if killer_key:
                metadata = self.session["players"].get(
                    killer_key,
                    {},
                )
                self._append_event(
                    time_value=time_value,
                    event_type="kill_exact",
                    player_key=killer_key,
                    team=metadata.get("team", ""),
                    role=metadata.get("role", "UNKNOWN"),
                    precision="exact",
                    label=(
                        f"{self._display_from_key(killer_key)} "
                        f"asesinó a "
                        f"{self._display_from_key(victim_key, victim_name)}"
                    ),
                    killer_key=killer_key,
                    victim_key=victim_key,
                    assister_keys=self._assister_keys(raw_event),
                )

            if victim_key:
                metadata = self.session["players"].get(
                    victim_key,
                    {},
                )
                self._append_event(
                    time_value=time_value,
                    event_type="death_exact",
                    player_key=victim_key,
                    team=metadata.get("team", ""),
                    role=metadata.get("role", "UNKNOWN"),
                    precision="exact",
                    label=(
                        f"{self._display_from_key(victim_key)} "
                        f"murió a manos de "
                        f"{self._display_from_key(killer_key, killer_name)}"
                    ),
                    killer_key=killer_key,
                    victim_key=victim_key,
                )

            for assister_key in self._assister_keys(raw_event):
                metadata = self.session["players"].get(
                    assister_key,
                    {},
                )
                self._append_event(
                    time_value=time_value,
                    event_type="assist_exact",
                    player_key=assister_key,
                    team=metadata.get("team", ""),
                    role=metadata.get("role", "UNKNOWN"),
                    precision="exact",
                    label=(
                        f"{self._display_from_key(assister_key)} "
                        f"asistió en la muerte de "
                        f"{self._display_from_key(victim_key, victim_name)}"
                    ),
                    killer_key=killer_key,
                    victim_key=victim_key,
                )
            return

        objective = self.OBJECTIVE_EVENTS.get(event_name)
        if objective:
            objective_key, objective_label = objective
            team = self._team_from_key(killer_key)
            team_label = self._team_label(team)
            self._append_event(
                time_value=time_value,
                event_type="objective",
                player_key=killer_key,
                team=team,
                role=self._role_from_key(killer_key),
                precision="exact",
                label=f"{team_label} consiguió {objective_label}",
                objective=objective_key,
            )

    def _append_event(
        self,
        *,
        time_value: float,
        event_type: str,
        player_key: str | None,
        team: str,
        role: str,
        precision: str,
        label: str,
        **extra: Any,
    ) -> None:
        if self.session is None:
            return

        self.event_order += 1
        event = {
            "time": round(time_value, 1),
            "time_label": self.format_time(time_value),
            "order": self.event_order,
            "type": event_type,
            "precision": precision,
            "player_key": player_key,
            "team": team,
            "role": role,
            "label": label,
        }
        event.update(extra)
        self.session["events"].append(event)
        if player_key:
            self.session["player_timelines"].setdefault(
                player_key,
                [],
            ).append(event)

    def _build_final_scoreboard(
        self,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        snapshots = session.get("snapshots", [])
        if not snapshots:
            return result

        latest = snapshots[-1].get("players", {})
        for key, point in latest.items():
            metadata = session.get("players", {}).get(key, {})
            result[key] = {
                "kills": point.get("kills", 0),
                "deaths": point.get("deaths", 0),
                "assists": point.get("assists", 0),
                "cs": point.get("cs", 0),
                "level": point.get("level", 0),
                "estimated_gold": point.get("estimated_gold", 0),
                "stats": point.get("stats", {}),
                "items": point.get("items", []),
                "win": metadata.get("win"),
            }
        return result

    def _assister_keys(self, raw_event: dict[str, Any]) -> list[str]:
        values = raw_event.get("Assisters", [])
        if not isinstance(values, list):
            return []
        result = []
        for value in values:
            key = self._key_from_identity(str(value))
            if key:
                result.append(key)
        return result

    def _team_label(self, team: str) -> str:
        local_team = str(
            self.session.get("local_team", "")
            if self.session
            else ""
        )
        if team and team == local_team:
            return "Equipo aliado"
        if team:
            return "Equipo enemigo"
        return "Bando no identificado"

    def _display_from_key(
        self,
        key: str | None,
        fallback: str = "rival",
    ) -> str:
        if self.session and key:
            metadata = self.session["players"].get(key, {})
            return str(
                metadata.get(
                    "riot_id",
                    metadata.get("champion_name", fallback),
                )
            )
        return fallback or "rival"

    def _role(self, player: dict[str, Any]) -> str:
        raw = str(
            player.get("position")
            or player.get("teamPosition")
            or player.get("individualPosition")
            or ""
        ).upper()
        role = self.ROLE_ALIASES.get(raw, "UNKNOWN")
        if role != "UNKNOWN":
            return role

        spells = player.get("summonerSpells", {})
        if isinstance(spells, dict):
            names = [
                str(value.get("displayName", "")).casefold()
                for value in spells.values()
                if isinstance(value, dict)
            ]
            if any("smite" in value for value in names):
                return "JUNGLE"
        return "UNKNOWN"

    def _player_key(
        self,
        player: dict[str, Any],
        index: int,
    ) -> str:
        identity = self._identity(player) or f"player-{index}"
        team = str(player.get("team", "unknown")).casefold()
        return f"{team}:{identity.casefold()}"

    @staticmethod
    def _identity(player: dict[str, Any]) -> str:
        riot_id = player.get("riotId")
        if riot_id:
            return str(riot_id).strip()
        name = player.get("summonerName")
        if name:
            return str(name).strip()
        game_name = player.get("riotIdGameName", "")
        tag_line = player.get("riotIdTagLine", "")
        return f"{game_name}#{tag_line}".strip("# ")

    def _display_name(self, player: dict[str, Any]) -> str:
        return self._identity(player) or str(
            player.get("championName", "Desconocido")
        )

    def _key_from_identity(self, identity: str) -> str | None:
        if self.session is None or not identity:
            return None
        wanted = identity.casefold()
        for key, metadata in self.session["players"].items():
            candidates = {
                str(metadata.get("riot_id", "")).casefold(),
                str(metadata.get("champion_name", "")).casefold(),
            }
            if wanted in candidates:
                return key
        return None

    def _team_from_key(self, player_key: str | None) -> str:
        if self.session and player_key:
            return str(
                self.session["players"].get(player_key, {}).get(
                    "team",
                    "",
                )
            )
        return ""

    def _role_from_key(self, player_key: str | None) -> str:
        if self.session and player_key:
            return str(
                self.session["players"].get(player_key, {}).get(
                    "role",
                    "UNKNOWN",
                )
            )
        return "UNKNOWN"

    def _item_ids(self, player: dict[str, Any]) -> list[int]:
        result = []
        for item in player.get("items", []):
            value = (
                item.get("itemID", 0)
                if isinstance(item, dict)
                else item
            )
            item_id = self._int(value)
            if item_id > 0:
                result.append(item_id)
        return result

    def _catalog_item(self, item_id: int) -> dict[str, Any]:
        items = self.item_catalog.get(
            "items",
            self.item_catalog,
        )
        if not isinstance(items, dict):
            return {}
        item = items.get(str(item_id), items.get(item_id, {}))
        return item if isinstance(item, dict) else {}

    def _item_cost(self, item_id: int) -> int:
        item = self._catalog_item(item_id)
        gold = item.get("gold", {})
        if isinstance(gold, dict):
            return self._int(
                gold.get("total", gold.get("base", 0))
            )
        return self._int(item.get("price", 0))

    def _item_name(self, item_id: int) -> str:
        item = self._catalog_item(item_id)
        return str(item.get("name", f"Objeto {item_id}"))

    def _estimate_gold(
        self,
        player: dict[str, Any],
        inventory_value: int,
        current_gold: int | None,
    ) -> int:
        if current_gold is not None:
            return inventory_value + current_gold
        scores = player.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}
        kills = self._int(scores.get("kills", 0))
        assists = self._int(scores.get("assists", 0))
        cs = self._int(scores.get("creepScore", 0))
        return inventory_value + kills * 300 + assists * 75 + cs * 20

    def _stats(
        self,
        player: dict[str, Any],
        local_stats: dict[str, Any],
        is_local: bool,
    ) -> dict[str, int | None]:
        sources: list[dict[str, Any]] = []
        if is_local and isinstance(local_stats, dict):
            sources.append(local_stats)
        for source in (
            player.get("stats", {}),
            player.get("scores", {}),
            player,
        ):
            if isinstance(source, dict):
                sources.append(source)

        return {
            "damage_to_champions": self._first_int(
                sources,
                (
                    "totalDamageToChampions",
                    "damageToChampions",
                ),
            ),
            "damage_to_structures": self._first_int(
                sources,
                (
                    "damageDealtToTurrets",
                    "damageToStructures",
                    "turretDamage",
                ),
            ),
            "damage_taken": self._first_int(
                sources,
                ("totalDamageTaken", "damageTaken"),
            ),
            "healing": self._first_int(
                sources,
                ("totalHeal", "healing", "heal"),
            ),
            "vision_score": self._first_int(
                sources,
                ("visionScore", "wardScore", "vision"),
            ),
            "wards_placed": self._first_int(
                sources,
                ("wardsPlaced", "wards_placed"),
            ),
            "wards_killed": self._first_int(
                sources,
                ("wardsKilled", "wards_killed"),
            ),
        }

    @staticmethod
    def _multiset_added(
        current: list[int],
        previous: list[int],
    ) -> list[int]:
        before = Counter(previous)
        after = Counter(current)
        result = []
        for item_id, count in after.items():
            result.extend(
                [item_id] * max(0, count - before[item_id])
            )
        return result

    @staticmethod
    def format_time(value: float) -> str:
        total = max(0, int(value))
        minutes, seconds = divmod(total, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _first_int(
        self,
        sources: Any,
        keys: tuple[str, ...],
    ) -> int | None:
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in keys:
                if key not in source or source[key] is None:
                    continue
                try:
                    return int(source[key])
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _make_session_id(
        started_at: str,
        champion_name: str,
    ) -> str:
        safe_time = started_at.replace(":", "-").replace(".", "-")
        safe_champion = "".join(
            char
            for char in champion_name
            if char.isalnum() or char in "_-"
        )
        return f"{safe_time}_{safe_champion or 'match'}"

    def _save_sessions(
        self,
        sessions: list[dict[str, Any]],
    ) -> None:
        self.sessions_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        temporary_path = self.sessions_path.with_suffix(".tmp")
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(
                sessions,
                file,
                ensure_ascii=False,
                indent=2,
            )
        temporary_path.replace(self.sessions_path)
