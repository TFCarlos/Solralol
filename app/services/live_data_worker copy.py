from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class LiveMatchSession:
    session_id: str
    started_at: str
    champion_name: str
    game_mode: str
    player_riot_id: str
    snapshots: list[dict[str, Any]] = field(
        default_factory=list
    )
    events: list[dict[str, Any]] = field(
        default_factory=list
    )
    last_items: list[int] = field(
        default_factory=list
    )
    last_objectives: dict[str, int] = field(
        default_factory=dict
    )
    last_values: dict[str, Any] = field(
        default_factory=dict
    )


class LiveMatchTracker:
    """Registra telemetría local de la partida actual."""

    SAMPLE_INTERVAL_SECONDS = 5.0
    MAX_SNAPSHOTS = 7200

    def __init__(
        self,
        item_catalog: dict,
    ) -> None:
        self.item_catalog = item_catalog
        self.sessions_path = (
            Path.home()
            / ".solralol"
            / "live_match_sessions.json"
        )
        self.session: LiveMatchSession | None = None
        self.last_sample_time = -1.0

    @property
    def is_tracking(self) -> bool:
        return self.session is not None

    def start(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        local_player = snapshot.get(
            "local_player",
            {},
        )

        champion_name = str(
            local_player.get(
                "championName",
                "Desconocido",
            )
        )

        riot_id = str(
            local_player.get("riotId")
            or local_player.get("summonerName")
            or "Jugador local"
        )

        started_at = datetime.now(UTC).isoformat()
        session_id = (
            f"{started_at.replace(':', '-').replace('.', '-')}"
            f"_{champion_name}"
        )

        self.session = LiveMatchSession(
            session_id=session_id,
            started_at=started_at,
            champion_name=champion_name,
            game_mode=str(
                snapshot.get(
                    "game_mode",
                    "UNKNOWN",
                )
            ),
            player_riot_id=riot_id,
        )

        self.last_sample_time = -1.0
        self.update(snapshot, force=True)

    def update(
        self,
        snapshot: dict[str, Any],
        force: bool = False,
    ) -> None:
        if self.session is None:
            return

        game_time = float(
            snapshot.get("game_time", 0)
        )

        if (
            not force
            and game_time - self.last_sample_time
            < self.SAMPLE_INTERVAL_SECONDS
        ):
            return

        point = self._build_point(snapshot)

        if len(self.session.snapshots) >= self.MAX_SNAPSHOTS:
            self.session.snapshots.pop(0)

        self.session.snapshots.append(point)
        self.last_sample_time = game_time

        self._detect_events(point)

    def finish(self) -> dict[str, Any] | None:
        if self.session is None:
            return None

        completed = self._serialize_session(
            self.session
        )

        sessions = self._load_sessions()
        sessions.append(completed)

        self._save_sessions(sessions)

        self.session = None
        self.last_sample_time = -1.0

        return completed

    def get_live_data(self) -> dict[str, Any]:
        if self.session is None:
            return {
                "active": False,
                "snapshots": [],
                "events": [],
            }

        return {
            "active": True,
            "session_id": self.session.session_id,
            "champion_name": self.session.champion_name,
            "game_mode": self.session.game_mode,
            "player_riot_id": self.session.player_riot_id,
            "snapshots": deepcopy(
                self.session.snapshots
            ),
            "events": deepcopy(
                self.session.events
            ),
        }

    def get_saved_sessions(self) -> list[dict[str, Any]]:
        return self._load_sessions()

    def _build_point(
        self,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        local_player = snapshot.get(
            "local_player",
            {},
        )
        local_stats = snapshot.get(
            "local_live_stats",
            {},
        )

        game_time = float(
            snapshot.get("game_time", 0)
        )

        items = self._extract_item_ids(
            local_player
        )

        item_value = sum(
            self._item_cost(item_id)
            for item_id in items
        )

        scores = local_player.get(
            "scores",
            {},
        )

        cs = self._number(
            scores.get(
                "creepScore",
                local_player.get(
                    "creepScore",
                    0,
                ),
            )
        )

        kills = self._number(
            scores.get("kills", 0)
        )
        deaths = self._number(
            scores.get("deaths", 0)
        )
        assists = self._number(
            scores.get("assists", 0)
        )

        current_gold = self._first_number(
            local_player,
            (
                "currentGold",
                "gold",
                "goldCurrent",
            ),
        )

        if current_gold is None:
            current_gold = self._first_number(
                local_stats,
                (
                    "currentGold",
                    "gold",
                    "goldCurrent",
                ),
            )

        objectives = self._extract_objectives(
            snapshot,
            local_player,
        )

        return {
            "time": round(game_time, 1),
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "cs": cs,
            "cs_per_min": round(
                cs / max(game_time / 60, 1 / 60),
                2,
            ),
            "level": self._number(
                local_player.get(
                    "level",
                    local_player.get(
                        "championLevel",
                        0,
                    ),
                )
            ),
            "current_gold": current_gold,
            "inventory_value": item_value,
            "estimated_total_value": (
                item_value + current_gold
                if current_gold is not None
                else item_value
            ),
            "items": items,
            "objectives": objectives,
            "stats": self._extract_stats(
                local_stats,
                local_player,
            ),
        }

    def _detect_events(
        self,
        point: dict[str, Any],
    ) -> None:
        if self.session is None:
            return

        time_value = point["time"]
        previous = self.session.last_values

        self._record_if_changed(
            previous,
            point,
            "kills",
            "Kill",
            time_value,
        )
        self._record_if_changed(
            previous,
            point,
            "deaths",
            "Death",
            time_value,
        )
        self._record_if_changed(
            previous,
            point,
            "assists",
            "Assist",
            time_value,
        )
        self._record_if_changed(
            previous,
            point,
            "level",
            "Nivel",
            time_value,
        )

        self._detect_item_changes(
            point["items"],
            time_value,
        )
        self._detect_objective_changes(
            point["objectives"],
            time_value,
        )

        self.session.last_values = {
            key: point[key]
            for key in (
                "kills",
                "deaths",
                "assists",
                "level",
            )
        }

    def _record_if_changed(
        self,
        previous: dict[str, Any],
        point: dict[str, Any],
        key: str,
        label: str,
        time_value: float,
    ) -> None:
        if self.session is None:
            return

        old_value = previous.get(key)
        new_value = point[key]

        if old_value is None or new_value == old_value:
            return

        direction = new_value - old_value

        if direction > 0:
            self.session.events.append(
                {
                    "time": time_value,
                    "type": key,
                    "label": (
                        f"{label}: {new_value}"
                    ),
                    "value": new_value,
                }
            )

    def _detect_item_changes(
        self,
        items: list[int],
        time_value: float,
    ) -> None:
        if self.session is None:
            return

        previous_items = self.session.last_items
        new_items = self._list_difference(
            items,
            previous_items,
        )

        for item_id in new_items:
            self.session.events.append(
                {
                    "time": time_value,
                    "type": "item",
                    "label": (
                        f"Compra: {self._item_name(item_id)}"
                    ),
                    "item_id": item_id,
                }
            )

        self.session.last_items = items.copy()

    def _detect_objective_changes(
        self,
        objectives: dict[str, int],
        time_value: float,
    ) -> None:
        if self.session is None:
            return

        labels = {
            "dragon": "Dragón",
            "baron": "Barón",
            "rift_herald": "Heraldo",
            "tower": "Torre",
            "inhibitor": "Inhibidor",
        }

        for key, value in objectives.items():
            old_value = self.session.last_objectives.get(
                key,
                value,
            )

            if value > old_value:
                self.session.events.append(
                    {
                        "time": time_value,
                        "type": "objective",
                        "label": (
                            f"{labels.get(key, key)}: "
                            f"{value}"
                        ),
                        "objective": key,
                        "value": value,
                    }
                )

        self.session.last_objectives = objectives.copy()

    @staticmethod
    def _list_difference(
        current: list[int],
        previous: list[int],
    ) -> list[int]:
        remaining = previous.copy()
        added = []

        for item_id in current:
            if item_id in remaining:
                remaining.remove(item_id)
            else:
                added.append(item_id)

        return added

    @staticmethod
    def _number(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _first_number(
        source: dict[str, Any],
        keys: tuple[str, ...],
    ) -> int | None:
        for key in keys:
            value = source.get(key)

            if value is None:
                continue

            try:
                return int(value)
            except (TypeError, ValueError):
                continue

        return None

    def _extract_item_ids(
        self,
        player: dict[str, Any],
    ) -> list[int]:
        items = player.get("items", [])
        item_ids = []

        for item in items:
            if isinstance(item, dict):
                value = item.get(
                    "itemID",
                    item.get("id", 0),
                )
            else:
                value = item

            try:
                item_id = int(value)
            except (TypeError, ValueError):
                continue

            if item_id > 0:
                item_ids.append(item_id)

        return item_ids

    def _item_cost(self, item_id: int) -> int:
        items = self.item_catalog.get("items", {})
        item = items.get(
            str(item_id),
            items.get(item_id, {}),
        )

        if not isinstance(item, dict):
            return 0

        gold = item.get("gold", {})

        if isinstance(gold, dict):
            return self._number(
                gold.get(
                    "total",
                    gold.get("base", 0),
                )
            )

        return self._number(
            item.get(
                "total_gold",
                item.get("goldTotal", 0),
            )
        )

    def _item_name(self, item_id: int) -> str:
        items = self.item_catalog.get("items", {})
        item = items.get(
            str(item_id),
            items.get(item_id, {}),
        )

        if isinstance(item, dict):
            return str(
                item.get(
                    "name",
                    f"Objeto {item_id}",
                )
            )

        return f"Objeto {item_id}"

    def _extract_objectives(
        self,
        snapshot: dict[str, Any],
        local_player: dict[str, Any],
    ) -> dict[str, int]:
        team = local_player.get("team")
        objectives = snapshot.get("objectives", {})

        if not isinstance(objectives, dict):
            return {
                "dragon": 0,
                "baron": 0,
                "rift_herald": 0,
                "tower": 0,
                "inhibitor": 0,
            }

        team_objectives = objectives.get(
            team,
            objectives.get("local", {}),
        )

        if not isinstance(team_objectives, dict):
            team_objectives = {}

        aliases = {
            "dragon": ("dragon", "dragons"),
            "baron": ("baron", "barons"),
            "rift_herald": (
                "rift_herald",
                "riftHerald",
                "herald",
            ),
            "tower": ("tower", "towers"),
            "inhibitor": (
                "inhibitor",
                "inhibitors",
            ),
        }

        result = {}

        for key, keys in aliases.items():
            value = 0

            for source_key in keys:
                if source_key in team_objectives:
                    value = self._number(
                        team_objectives[source_key]
                    )
                    break

            result[key] = value

        return result

    def _extract_stats(
        self,
        local_stats: dict[str, Any],
        local_player: dict[str, Any],
    ) -> dict[str, int | None]:
        sources = (
            local_stats,
            local_player.get("scores", {}),
            local_player,
        )

        fields = {
            "damage_to_champions": (
                "totalDamageToChampions",
                "damageToChampions",
            ),
            "damage_to_structures": (
                "damageDealtToTurrets",
                "damageToStructures",
                "turretDamage",
            ),
            "damage_physical": (
                "physicalDamageToChampions",
                "physicalDamageDealtToChampions",
            ),
            "damage_magic": (
                "magicDamageToChampions",
                "magicDamageDealtToChampions",
            ),
            "damage_true": (
                "trueDamageToChampions",
                "trueDamageDealtToChampions",
            ),
            "healing": (
                "totalHeal",
                "healing",
                "selfMitigatedDamage",
            ),
            "vision_score": (
                "visionScore",
                "vision",
            ),
        }

        result: dict[str, int | None] = {}

        for output_key, source_keys in fields.items():
            value = None

            for source in sources:
                if not isinstance(source, dict):
                    continue

                value = self._first_number(
                    source,
                    source_keys,
                )

                if value is not None:
                    break

            result[output_key] = value

        return result

    def _serialize_session(
        self,
        session: LiveMatchSession,
    ) -> dict[str, Any]:
        ended_at = datetime.now(UTC).isoformat()
        snapshots = session.snapshots

        final = snapshots[-1] if snapshots else {}
        first = snapshots[0] if snapshots else {}

        return {
            "session_id": session.session_id,
            "started_at": session.started_at,
            "ended_at": ended_at,
            "champion_name": session.champion_name,
            "game_mode": session.game_mode,
            "player_riot_id": session.player_riot_id,
            "duration": final.get("time", 0),
            "final": final,
            "first": first,
            "events": session.events,
            "snapshots": snapshots,
        }

    def _load_sessions(self) -> list[dict[str, Any]]:
        try:
            with self.sessions_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ):
            return []

        return data if isinstance(data, list) else []

    def _save_sessions(
        self,
        sessions: list[dict[str, Any]],
    ) -> None:
        self.sessions_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        sessions = sessions[-50:]

        temporary_path = self.sessions_path.with_suffix(
            ".tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                sessions,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temporary_path.replace(self.sessions_path)