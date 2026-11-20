"""Bounded notifications derived from the shared Live Client snapshot.

All deadlines use game time. A missing structure identity or timer produces no
structure alert; the renderer never infers a purchase or a respawn.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from app.services.live_player_metrics_service import player_champion, player_identity, player_role


ALERT_LEAD_SECONDS = 60
DEFAULT_ALERT_SECONDS = 8
MAX_QUEUE_DELAY_SECONDS = 20
FINAL_COUNTDOWN_SECONDS = 10
INHIBITOR_SOON_SECONDS = 15
NEXUS_TURRET_RESPAWN_SECONDS = 180
COMPLETED_ITEM_MIN_GOLD = 1000

# Existing Summoner's Rift objective rules, restricted to modes with this map.
OBJECTIVE_RULES = (
    {"key": "dragon", "name": "Dragón", "first_spawn": 300.0, "respawn": 300.0},
    {"key": "voidgrubs", "name": "Grumos", "first_spawn": 480.0, "respawn": None, "despawn": 885.0},
    {"key": "herald", "name": "Heraldo", "first_spawn": 900.0, "respawn": None, "despawn": 1185.0},
    {"key": "baron", "name": "Barón", "first_spawn": 1200.0, "respawn": 360.0},
)
EVENT_TO_OBJECTIVE = {"dragonkill": "dragon", "hordekill": "voidgrubs",
                      "heraldkill": "herald", "baronkill": "baron"}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def item_catalog_entry(item_id: Any, catalog: dict) -> dict:
    items = catalog.get("items", catalog)
    entry = items.get(str(item_id), {}) if isinstance(items, dict) else {}
    return entry if isinstance(entry, dict) else {}


def item_name(item_id: Any, catalog: dict) -> str:
    entry = item_catalog_entry(item_id, catalog)
    return str(entry.get("name") or entry.get("name_es") or f"Objeto {item_id}")


def is_completed_item(item_id: Any, catalog: dict) -> bool:
    """Keep the existing relevant-item rule; automatic upgrades are excluded."""
    item = item_catalog_entry(item_id, catalog)
    gold = item.get("gold") or {}
    tags = item.get("tags") or []
    return bool(item and isinstance(gold, dict) and gold.get("purchasable") is True
                and (_number(gold.get("total")) or 0) >= COMPLETED_ITEM_MIN_GOLD
                and not item.get("into") and not ({"Consumable", "Trinket"} & set(tags)))


def structure_identity(raw: Any, kind: str) -> tuple[str, str, str, str] | None:
    """Return stable ID, owner, lane/individual turret, and human name.

    Barracks L/C/R means top/mid/bot. The number after L/C/R on a
    turret is its depth, not its lane (the old TOP/MID mix-up).
    """
    text = str(raw or "")
    if kind == "inhibitor":
        match = re.fullmatch(r"Barracks_T([12])_([LCR])1", text, re.I)
        if not match:
            return None
        owner = "ORDER" if match[1] == "1" else "CHAOS"
        lane = {"L": "TOP", "C": "MID", "R": "BOT"}[match[2].upper()]
        return text.upper(), owner, lane, f"Inhibidor de {lane}"
    match = re.fullmatch(r"Turret_T([12])_C_0([12])_A", text, re.I)
    if not match:
        return None
    owner = "ORDER" if match[1] == "1" else "CHAOS"
    lane = "TOP" if match[2] == "2" else "BOT"
    return text.upper(), owner, lane, f"Torre de nexo {lane}"


def supports_nexus_respawn(mode: str, version: str) -> bool:
    """Only use the documented SR rule when an actual game version is known."""
    match = re.match(r"^(\d+)\.(\d+)(?:\.|$)", version)
    return mode.upper() == "CLASSIC" and bool(match and (int(match[1]), int(match[2])) >= (15, 1))


class OverlayAlertTracker:
    MAX_VISIBLE = 3
    MAX_PENDING = 12

    def __init__(self, item_catalog: dict, lead_seconds: int = ALERT_LEAD_SECONDS,
                 purchase_seconds: int = DEFAULT_ALERT_SECONDS) -> None:
        self.item_catalog = item_catalog if isinstance(item_catalog, dict) else {}
        self.lead_seconds = max(15, min(int(lead_seconds), 180))
        self.purchase_seconds = max(3, min(int(purchase_seconds), 10))
        self.reset()

    def reset(self) -> None:
        self._known_items: dict[str, Counter[str]] = {}
        self._known_at: dict[str, float] = {}
        self._ever_owned: dict[str, set[str]] = {}
        self._temporary: list[dict] = []
        self._emitted: set[str] = set()
        self._killed_at: dict[str, float] = {}
        self._dragon_teams: Counter[str] = Counter()
        self._seen_events: set[str] = set()
        self._seen_structure_events: set[str] = set()
        self._grubs_killed = 0
        self._structures: dict[str, dict] = {}
        self._last_game_time = -1.0

    @property
    def elder_active(self) -> bool:
        return any(count >= 4 for count in self._dragon_teams.values())

    def update(self, snapshot: dict) -> list[dict]:
        if not isinstance(snapshot, dict):
            return []
        game_time = _number(snapshot.get("game_time"))
        if game_time is None:
            return []
        if game_time + 5 < self._last_game_time:
            self.reset()
        self._last_game_time = max(game_time, self._last_game_time)
        mode = str(snapshot.get("game_mode") or "")
        if mode.upper() in {"CLASSIC", "PRACTICETOOL"} and snapshot.get("map_number") in {None, 11, "11"}:
            self._record_objectives(snapshot)
            self._record_structures(snapshot, mode)
        self._record_purchases(snapshot, game_time)
        return self.active_alerts(game_time, str(snapshot.get("local_team") or ""),
                                  mode if snapshot.get("map_number") in {None, 11, "11"} else "")

    def _enqueue(self, row: dict, game_time: float) -> None:
        if row["key"] in self._emitted:
            return
        self._emitted.add(row["key"])
        row.update(time=game_time, expires_at=None, priority=2 if row["kind"] == "purchase" else 1)
        self._temporary.append(row)
        if len(self._temporary) > self.MAX_PENDING:
            self._temporary = self._temporary[-self.MAX_PENDING:]

    def active_alerts(self, game_time: float, local_team: str = "", game_mode: str = "") -> list[dict]:
        persistent: list[dict] = []
        valid_spawns: dict[str, float | None] = {}
        if game_mode.upper() in {"CLASSIC", "PRACTICETOOL"}:
            for rule in OBJECTIVE_RULES:
                spawn_at = self._spawn_time(rule, game_time)
                valid_spawns[rule["key"]] = spawn_at
                if spawn_at is None:
                    continue
                remaining = spawn_at - game_time
                if not 0 < remaining <= self.lead_seconds:
                    continue
                key = f"objective:{rule['key']}:{spawn_at:g}"
                name = "Anciano" if rule["key"] == "dragon" and self.elder_active else rule["name"]
                row = {"kind": "objective", "key": key, "name": name, "objective": rule["key"],
                       "remaining": remaining, "spawn_at": spawn_at}
                if remaining <= FINAL_COUNTDOWN_SECONDS:
                    persistent.append({**row, "key": f"{key}:final", "persistent": True})
                else:
                    self._enqueue({**row, "key": f"{key}:early", "persistent": False}, game_time)
            for structure in self._structures.values():
                remaining = structure["spawn_at"] - game_time
                if not 0 < remaining <= self.lead_seconds or not local_team:
                    continue
                side = "ally" if structure["owner"] == local_team else "enemy"
                key = f"structure:{structure['id']}:{structure['cycle']:g}"
                row = {"kind": "structure", "key": key, "name": structure["name"],
                       "structure": structure["type"], "structure_id": structure["id"],
                       "side": side, "lane": structure["lane"],
                       "remaining": remaining, "spawn_at": structure["spawn_at"]}
                if remaining <= FINAL_COUNTDOWN_SECONDS:
                    persistent.append({**row, "key": f"{key}:final", "persistent": True})
                else:
                    self._enqueue({**row, "key": f"{key}:early", "persistent": False}, game_time)
        superseded = {f"{row['key'].removesuffix(':final')}:early" for row in persistent}
        self._temporary = [row for row in self._temporary
                           if row["key"] not in superseded
                           and (row["kind"] != "objective" or row["spawn_at"] == valid_spawns.get(row["objective"]))
                           and (row["kind"] != "structure" or
                                row["spawn_at"] == self._structures.get(row["structure_id"], {}).get("spawn_at"))
                           and (row["expires_at"] is not None or game_time - row["time"] <= MAX_QUEUE_DELAY_SECONDS)
                           and (row["expires_at"] is None or row["expires_at"] > game_time)]
        persistent.sort(key=lambda row: (row["remaining"], row["key"]))
        slots = max(0, self.MAX_VISIBLE - len(persistent))
        selected = sorted(self._temporary, key=lambda row: (row["priority"], row["time"]))[:slots]
        selected_keys = {row["key"] for row in selected}
        for row in self._temporary:
            if row["key"] in selected_keys:
                if row["expires_at"] is None:
                    row["expires_at"] = game_time + self.purchase_seconds
            elif row["expires_at"] is not None:
                row["expires_at"] = None  # Resume after higher-priority notices.
        return (persistent + selected)[:self.MAX_VISIBLE]

    def _spawn_time(self, rule: dict, game_time: float) -> float | None:
        key = rule["key"]
        if key == "voidgrubs" and self._grubs_killed >= 3:
            return None
        killed = self._killed_at.get(key)
        if rule["respawn"] is None and killed is not None:
            return None
        if rule["respawn"] is None:
            spawn = rule["first_spawn"]
        elif killed is None:
            spawn = rule["first_spawn"]
        else:
            respawn = 360 if key == "dragon" and self.elder_active else rule["respawn"]
            spawn = killed + respawn
        if rule.get("despawn") is not None and game_time > rule["despawn"]:
            return None
        return spawn

    def _record_objectives(self, snapshot: dict) -> None:
        events = snapshot.get("game_events") or []
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict):
                continue
            key = EVENT_TO_OBJECTIVE.get(str(event.get("EventName") or "").casefold())
            when = _number(event.get("EventTime"))
            ident = event.get("EventID")
            if not key or when is None or ident is None:
                continue
            event_key = f"objective:{ident}"
            if event_key in self._seen_events:
                continue
            self._seen_events.add(event_key)
            if key == "voidgrubs":
                self._grubs_killed += 1
                if self._grubs_killed < 3:
                    continue
            self._killed_at[key] = max(when, self._killed_at.get(key, -1))
            if key == "dragon":
                killer = str(event.get("KillerName") or "").casefold()
                matches = {str(player.get("team") or "") for player in snapshot.get("all_players", [])
                           if isinstance(player, dict) and killer and killer == player_identity(player).casefold()}
                if len(matches) == 1:
                    self._dragon_teams[matches.pop()] += 1

    def _record_structures(self, snapshot: dict, mode: str) -> None:
        events = snapshot.get("game_events") or []
        version = str(snapshot.get("game_version") or "")
        ordered = sorted((event for event in events if isinstance(event, dict) and _number(event.get("EventTime")) is not None),
                         key=lambda event: _number(event["EventTime"])) if isinstance(events, list) else []
        for event in ordered:
            if not isinstance(event, dict) or event.get("EventID") is None:
                continue
            when = _number(event.get("EventTime"))
            if when is None:
                continue
            event_name = str(event.get("EventName") or "").casefold()
            event_key = f"{event_name}:{event['EventID']}"
            if event_key in self._seen_structure_events:
                continue
            if event_name in {"inhibkilled", "inhibrespawningsoon", "inhibrespawned"}:
                field = {"inhibkilled": "InhibKilled", "inhibrespawningsoon": "InhibRespawningSoon",
                         "inhibrespawned": "InhibRespawned"}[event_name]
                parsed = structure_identity(event.get(field) or (event.get("BarracksKilled") if event_name == "inhibkilled" else None), "inhibitor")
                if not parsed:
                    continue
                self._seen_structure_events.add(event_key)
                ident, owner, lane, name = parsed
                if event_name == "inhibkilled":
                    self._structures[ident] = {"id": ident, "owner": owner, "lane": lane, "name": name,
                                               "type": "inhibitor", "cycle": when, "spawn_at": math.inf}
                elif event_name == "inhibrespawned":
                    self._structures.pop(ident, None)
                elif event_name == "inhibrespawningsoon":
                    current = self._structures.get(ident)
                    if current is None:
                        self._structures[ident] = {"id": ident, "owner": owner, "lane": lane, "name": name,
                                                   "type": "inhibitor", "cycle": when,
                                                   "spawn_at": when + INHIBITOR_SOON_SECONDS}
                    elif when >= current["cycle"]:
                        current["spawn_at"] = when + INHIBITOR_SOON_SECONDS
            elif event_name == "turretkilled" and supports_nexus_respawn(mode, version):
                parsed = structure_identity(event.get("TurretKilled"), "nexus_turret")
                if not parsed:
                    continue
                self._seen_structure_events.add(event_key)
                ident, owner, lane, name = parsed
                event_key = f"turret:{event['EventID']}"
                if event_key in self._seen_events:
                    continue
                self._seen_events.add(event_key)
                self._structures[ident] = {"id": ident, "owner": owner, "lane": lane, "name": name,
                                           "type": "nexus_turret", "cycle": when,
                                           "spawn_at": when + NEXUS_TURRET_RESPAWN_SECONDS}

    def _record_purchases(self, snapshot: dict, game_time: float) -> None:
        local_team = str(snapshot.get("local_team") or "")
        players = snapshot.get("all_players") or []
        seen: set[str] = set()
        for player in players if isinstance(players, list) else []:
            if not isinstance(player, dict) or not isinstance(player.get("items"), list):
                continue
            identity = player_identity(player)
            team = str(player.get("team") or "")
            if not identity or not team:
                continue
            key = f"{team}:{identity}".casefold()
            seen.add(key)
            counts: Counter[str] = Counter()
            for item in player["items"]:
                if not isinstance(item, dict):
                    continue
                ident = _number(item.get("itemID", item.get("itemId")))
                count = _number(item.get("count", 1))
                if ident and ident.is_integer() and count and count.is_integer():
                    counts[str(int(ident))] += min(6, int(count))
            previous = self._known_items.get(key)
            previous_at = self._known_at.get(key)
            self._known_items[key] = counts
            self._known_at[key] = game_time
            ever_owned = self._ever_owned.setdefault(key, set())
            previously_seen = set(ever_owned)
            ever_owned.update(counts)
            if previous is None or previous_at is None or game_time - previous_at > 6:
                continue  # Initial inventory is never a new purchase.
            for item_id, amount in (counts - previous).items():
                # A returning old ID can be an undo or a missed inventory read.
                if item_id in previously_seen or not is_completed_item(item_id, self.item_catalog):
                    continue
                for serial in range(amount):
                    self._enqueue({"kind": "purchase", "key": f"purchase:{key}:{item_id}:{game_time:g}:{serial}",
                                   "champion": player_champion(player), "role": player_role(player),
                                   "side": "ally" if local_team and team == local_team else "enemy",
                                   "item_id": item_id, "item_name": item_name(item_id, self.item_catalog),
                                   "name": "Ha comprado", "persistent": False}, game_time)
        for key in list(self._known_items):
            if key not in seen:
                self._known_items.pop(key, None)
                self._known_at.pop(key, None)
