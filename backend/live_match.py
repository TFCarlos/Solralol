"""Single authoritative Electron live-session monitor.

It owns LCU lifecycle sampling and Live Client telemetry independently of the
visible tab. The renderer reads a bounded snapshot; it never talks to Riot.
"""
from __future__ import annotations

import threading
import time
import json
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from app.services.game_service import GameService
from app.services.lcu_service import LCUService
from app.services.live_match_tracker import LiveMatchTracker
from app.services.live_player_metrics_service import build_inventory_report
from app.services.overlay_alert_service import OverlayAlertTracker
from app.services.overlay_sound_service import OverlaySoundService
from _paths import DATA_DIR
from app.services.live_event_normalizer import normalize_live_event
from app.services.enemy_inventory_tracker import EnemyInventoryTracker, normalized_inventory
from app.services.overlay_level_state import PendingAbility
from app.services.game_window_geometry import league_client_rect_pixels
from app.services.live_preparation_service import LivePreparationService, rune_ids
from app.services.live_recommendation_service import number

logger = logging.getLogger(__name__)


def _item_catalog() -> dict[str, Any]:
    try:
        value = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        return value.get("items", {}) if isinstance(value, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def calculate_kill_participation(players: list[dict[str, Any]], local_team: str, local_player: dict[str, Any] | None = None) -> float | None:
    """Compute KP from one roster snapshot and its actual local team."""
    import logging
    logger = logging.getLogger(__name__)
    team = str(local_team or "").strip().upper()
    own = [player for player in players if str(player.get("team") or "").strip().upper() == team]
    if not team or not own:
        return None
    identity = local_player if isinstance(local_player, dict) else {}
    local = next((player for player in own if player.get("isLocalPlayer") is True or player.get("is_local_player") is True or player.get("local") is True), None)
    # Match the active player by Riot identity fields, never by champion name.
    if local is None and identity:
        for field in ("puuid", "riotId", "summonerName", "summonerId"):
            value = str(identity.get(field) or "").strip().casefold()
            if value:
                local = next((player for player in own if str(player.get(field) or "").strip().casefold() == value), None)
                if local:
                    break
    if local is None and len(own) == 1:
        local = own[0]
    if local is None:
        return None
    def stat(player: dict[str, Any], name: str) -> int | None:
        scores = player.get("scores") if isinstance(player.get("scores"), dict) else {}
        value = scores.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
    kills = [stat(player, "kills") for player in own]
    player_kills, assists = stat(local, "kills"), stat(local, "assists")
    if player_kills is None or assists is None or any(value is None for value in kills):
        return None
    team_kills = sum(value for value in kills if value is not None)
    if team_kills == 0:
        return 0.0
    participation = player_kills + assists
    if participation > team_kills:
        logger.warning("Ignoring impossible live kill participation: player=%s team=%s", participation, team_kills)
        return None
    return participation / team_kills * 100


class LiveMatchRuntime:
    POLL_SECONDS = 2.0
    END_FAILURE_LIMIT = 3

    def __init__(self, catalog: dict[str, Any], recordings: Any, on_completed=None, settings_service: Any = None, lcu_service: LCUService | None = None) -> None:
        self.lcu = lcu_service or LCUService()
        self.game = GameService()
        self.items = _item_catalog()
        self.tracker = LiveMatchTracker(self.items, persist=True)
        self.alert_tracker = OverlayAlertTracker(self.items)
        self.settings_service = settings_service
        sound_settings = settings_service.load() if settings_service else {}
        self.alert_tracker.purchase_seconds = int(sound_settings.get("overlay_alert_duration", 8))
        self.alert_tracker.lead_seconds = int(sound_settings.get("overlay_alert_lead", 60))
        self.sound_service = OverlaySoundService(
            enabled=bool(sound_settings.get("overlay_sound_enabled", True)),
            volume=sound_settings.get("overlay_sound_volume", 0.6),
        )
        self.sound_service.set_kind_enabled("objective", bool(sound_settings.get("overlay_sound_objective", True)))
        self.sound_service.set_kind_enabled("dragon", bool(sound_settings.get("overlay_sound_dragon", True)))
        self.sound_service.set_kind_enabled("enemy_buy", bool(sound_settings.get("overlay_sound_enemy_buy", True)))
        self._played_sound_alerts: set[str] = set()
        self._sound_settings_checked_at = 0.0
        self._diagnosed_kill_events: set[str] = set()
        self._recommendation_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="live-recommendation")
        self._recommendation_future: Future | None = None
        self._recommendation_signature: tuple[Any, ...] | None = None
        self._recommendation_requested_at = 0.0
        self._recommendations: list[dict[str, Any]] = []
        self._recommendation_session_id: str | None = None
        self._preparation_service: LivePreparationService | None = None
        self._skill_order: dict[str, Any] = {"status": "unavailable", "order": []}
        self._skill_source_revision = None
        self._skill_revision_checked_at = 0.0
        self.enemy_inventory_tracker = EnemyInventoryTracker(self.items)
        self.pending_ability = PendingAbility()
        self.recordings = recordings
        self.on_completed = on_completed
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.state: dict[str, Any] = {
            "state": "disconnected", "connected": False, "telemetry": "unavailable",
            "snapshot": None, "sessionId": None, "lastUpdated": None,
            "message": "Esperando al cliente de League of Legends.", "source": "live",
        }
        self._draft_context: dict[str, Any] = {"connected": False, "phase": "Unknown", "session": None}
        self.failures = 0
        self._closing = False
        self.thread = threading.Thread(target=self._run, name="solralol-live-monitor")
        self.thread.start()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        logger.info("[Shutdown] Stopping live match polling and recommendation work")
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=15)
        if self.thread.is_alive():
            logger.error("[Shutdown] Live monitor did not stop within 15 seconds")
        self._recommendation_pool.shutdown(wait=True, cancel_futures=True)
        self.sound_service.close()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self.state)

    def draft_state(self) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self._draft_context)

    def _run(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self._tick()
            except Exception:
                with self.lock:
                    if self.state.get("snapshot"):
                        self.state.update({"telemetry": "stale", "message": "Se conserva la última lectura válida."})
                    else:
                        self.state.update({"state": "disconnected", "connected": False})
            self.stop_event.wait(max(0.1, self.POLL_SECONDS - (time.monotonic() - started)))

    def _tick(self) -> None:
        if not self.lcu.is_connected():
            with self.lock:
                self._draft_context = {"connected": False, "phase": "Unknown", "session": None}
            self._set_disconnected()
            return
        phase = self._gameflow_phase()
        champ_session = None
        if phase == "ChampSelect":
            try:
                champ_session = self.lcu.get_champ_select_session()
            except Exception:
                champ_session = None
        with self.lock:
            self._draft_context = {"connected": True, "phase": phase,
                                   "session": champ_session if isinstance(champ_session, dict) else None}
        if phase == "PreEndOfGame":
            with self.lock:
                self.state.update({"state": "game_ending", "connected": True,
                                   "message": "La partida está terminando; esperando el cierre seguro de telemetría."})
            return
        if phase in {"ChampSelect"}:
            if self.tracker.is_tracking:
                self._finish()
            self._set_state("champion_select", phase, "Selección de campeón")
            return
        if phase in {"Lobby", "Matchmaking", "ReadyCheck", "Found"}:
            if self.tracker.is_tracking:
                self._finish()
            self._set_state("lobby", phase, "Cliente conectado · esperando partida")
            return
        if phase in {"EndOfGame", "WaitingForStats"}:
            if self.tracker.is_tracking:
                self._finish()
            self._set_state("post_game", phase, "Partida finalizada · sincronización disponible en Partidas guardadas")
            return
        if phase in {"GameStart", "InProgress", "Reconnect"} or self.tracker.is_tracking:
            snap = self.game.get_live_snapshot()
            if snap is None:
                self.failures += 1
                if self.tracker.is_tracking:
                    self.tracker.mark_telemetry_gap()
                    self.enemy_inventory_tracker.mark_gap()
                with self.lock:
                    self.state.update({"connected": True, "state": "loading" if not self.tracker.is_tracking else "active",
                                       "telemetry": "stale" if self.tracker.is_tracking else "loading",
                                       "message": "Esperando a que Live Client Data esté disponible." if not self.tracker.is_tracking else "Conexión temporalmente interrumpida; conservando datos."})
                if self.tracker.is_tracking and self.failures >= self.END_FAILURE_LIMIT and phase in {"None", "EndOfGame"}:
                    self._finish()
                return
            self.failures = 0
            self._update(snap)
            return
        self._set_state("connected", phase, "Cliente de League conectado · listo para detectar una partida")

    def _gameflow_phase(self) -> str:
        try:
            if not self.lcu.port and not self.lcu.refresh_connection():
                return "Unknown"
            response = self.lcu.session.get(f"https://127.0.0.1:{self.lcu.port}/lol-gameflow/v1/gameflow-phase", timeout=1.2)
            if response.status_code == 200:
                value = response.json()
                return value if isinstance(value, str) else "Unknown"
        except (requests.RequestException, ValueError):
            self.lcu.port = None
            self.lcu.auth_token = None
        return "Unknown"

    def _update(self, snap: dict[str, Any]) -> None:
        if not self.tracker.is_tracking:
            self.alert_tracker.reset()
            self._played_sound_alerts.clear()
            if hasattr(self, "pending_ability"):
                self.pending_ability.reset()
            with self.lock:
                self.state.pop("postGame", None)
            self.tracker.start(snap)
        else:
            self.tracker.update(snap)
        session = self.tracker.session or {}
        self._schedule_recommendations(session, snap)
        gold = build_inventory_report(snap, self.items)
        if str(snap.get("game_mode") or "").upper() in {"CLASSIC", "PRACTICETOOL"}:
            alerts = self.alert_tracker.update({**snap, "game_version": snap.get("game_version") or self._current_game_version(str(session.get("session_id") or ""))})
        else:
            self.alert_tracker.reset()
            alerts = []
        self._update_overlay_sounds(alerts)
        recommendations = self._current_recommendations(snap)
        overlay = {
            "gold": {
                "team": {key: gold.get("team", {}).get(key) for key in ("ally", "enemy", "delta")},
                "lanes": [{"role": row.get("role"), "delta": row.get("delta"), "paired": row.get("paired"),
                           "ally": {key: (row.get("ally") or {}).get(key) for key in ("champion", "role", "gold")},
                           "enemy": {key: (row.get("enemy") or {}).get(key) for key in ("champion", "role", "gold")}}
                          for row in gold.get("lanes", []) if isinstance(row, dict)],
            },
            "alerts": [{key: alert.get(key) for key in ("key", "kind", "name", "objective", "structure", "lane", "remaining", "persistent", "champion", "item_id", "item_name", "side", "time")}
                       for alert in alerts if isinstance(alert, dict)],
            "recommendations": recommendations,
        }
        associate = getattr(self.recordings, "associate_live_session", None)
        if callable(associate):
            local = snap.get("local_player") if isinstance(snap.get("local_player"), dict) else {}
            associate(session.get("session_id"), {
                "champion": local.get("championName") or local.get("rawChampionName") or "",
                "gameMode": snap.get("game_mode") or "",
                "role": local.get("position") or local.get("role") or "",
            })
        players = snap.get("all_players", [])
        players = [player for player in players if isinstance(player, dict)] if isinstance(players, list) else []
        player_by_key = (session.get("players") or {}) if isinstance(session.get("players"), dict) else {}
        player_identity = {key: value for key, value in player_by_key.items() if isinstance(value, dict)}
        if not hasattr(self, "enemy_inventory_tracker"):
            self.enemy_inventory_tracker = EnemyInventoryTracker(self.items)
        enemies = [(self.tracker._player_key(player, index),
                    player if self.tracker._identity(player) or player.get("participantId") is not None else {**player, "items": None})
                   for index, player in enumerate(players)
                   if snap.get("local_team") and player.get("team") and player.get("team") != snap["local_team"]]
        enemy_timers = self.enemy_inventory_tracker.update(str(session.get("session_id") or ""), snap.get("game_time"), enemies)
        local_stats = snap.get("local_live_stats") if isinstance(snap.get("local_live_stats"), dict) else {}
        level = local_stats.get("level", (snap.get("local_player") or {}).get("level"))
        if isinstance(level, float) and level.is_integer():
            level = int(level)
        if not hasattr(self, "pending_ability"):
            self.pending_ability = PendingAbility()
        pending_slot = self.pending_ability.update(level, snap.get("local_abilities"), getattr(self, "_skill_order", None),
                                                   (snap.get("local_player") or {}).get("championName"))

        def public_player(player: dict[str, Any]) -> dict[str, Any]:
            return {key: value for key, value in player.items()
                    if key.casefold() not in {"summonername", "riotid", "riotidgamename", "riotidtagline", "puuid", "accountid", "summonerid"}}

        raw_events = snap.get("game_events", [])
        public_events = []
        if isinstance(raw_events, list):
            for event in raw_events[-100:]:
                if not isinstance(event, dict):
                    continue
                public_event_fields = {"eventid", "eventname", "eventtime", "isfirstblood", "killername", "victimname", "assisters",
                                       "multikill", "multikillcount", "killcount", "dragontype",
                                       "monstertype", "turretkilled", "inhibkilled", "barrackskilled", "inhibrespawned", "inhibrespawningsoon", "teamid",
                                       "stolen", "shutdown", "isshutdown", "bountyclaimed"}
                clean = {key: value for key, value in event.items() if key.casefold() in public_event_fields}
                killer_key = self.tracker._event_player_key(event, "killer")
                victim_key = self.tracker._event_player_key(event, "victim")
                killer = player_identity.get(killer_key, {})
                victim = player_identity.get(victim_key, {})
                if killer.get("champion_name"):
                    clean.update({"KillerChampion": killer["champion_name"], "KillerTeam": killer.get("team"),
                                  "KillerLocal": bool(killer.get("is_local_player"))})
                if victim.get("champion_name"):
                    clean.update({"VictimChampion": victim["champion_name"], "VictimTeam": victim.get("team")})
                if killer.get("team"):
                    clean["EventTeam"] = killer["team"]
                if str(event.get("EventName") or "").casefold() in {"dragonkill", "hordekill", "baronkill", "heraldkill", "turretkilled", "inhibkilled", "inhibrespawned", "inhibrespawningsoon"}:
                    # The tracker applies documented killer/unit/structure
                    # attribution rules and leaves uncertain ownership empty.
                    event_id = str(event.get("EventID") or "").strip()
                    normalized = next((row for row in reversed(session.get("events", []))
                                       if isinstance(row, dict) and row.get("precision") == "exact"
                                       and row.get("type") == "objective"
                                       and ((event_id and row.get("event_id") == f"native:{event_id}")
                                            or (not event_id and row.get("time") == round(float(event.get("EventTime") or 0), 1)))), None)
                    if normalized and normalized.get("team"):
                        clean["EventTeam"] = normalized["team"]
                clean["EventID"] = event.get("EventID")
                public = normalize_live_event(clean, killer.get("champion_name", ""), victim.get("champion_name", ""))
                if str(public.get("EventName") or "").casefold() == "championkill":
                    event_key = str(public.get("EventID") or f"{public.get('EventTime')}:{public.get('VictimChampion')}")
                    diagnosed = getattr(self, "_diagnosed_kill_events", set())
                    if logger.isEnabledFor(logging.DEBUG) and event_key not in diagnosed:
                        raw_killer = str(event.get("KillerName") or "")
                        safe_killer = raw_killer if any(token in raw_killer.casefold() for token in ("turret", "tower", "minion", "sru_")) else "<identidad de jugador omitida>"
                        logger.debug(
                            "Live Client kill attribution: %s",
                            {
                                "event_id": event_key,
                                "raw": {"EventName": public.get("EventName"), "EventTime": public.get("EventTime"),
                                        "KillerName": safe_killer, "VictimName": "<resuelto al campeón>" if victim_key else "<no resuelto>"},
                                "normalized": {"actor_type": public.get("KillerActorType"), "actor": public.get("KillerActorName"),
                                               "victim_type": public.get("VictimActorType"), "victim": public.get("VictimChampion")},
                                "assets": {"actor": "inline:turret-svg" if public.get("KillerActorType") == "tower" else "champion-or-generic",
                                           "victim": f"champion:{public.get('VictimChampion')}" if public.get("VictimChampion") else None},
                                "timestamp": LiveMatchTracker.format_time(float(public["EventTime"])) if public.get("EventTime") is not None else "--:--",
                            },
                        )
                        diagnosed.add(event_key)
                        self._diagnosed_kill_events = diagnosed if len(diagnosed) <= 200 else {event_key}
                # Raw names can be Riot IDs or account names. Keep only the
                # semantic actor classification in the renderer contract.
                for private_field in ("KillerName", "VictimName", "Assisters"):
                    public.pop(private_field, None)
                public_events.append(public)
        # The Live Client has no item purchase event. These are explicitly
        # marked as inventory observations by the existing session tracker.
        for event in session.get("events", []):
            if not isinstance(event, dict) or event.get("type") != "completed_item_acquired":
                continue
            owner = player_identity.get(event.get("player_key"), {})
            public_events.append({"EventID": event.get("event_id") or f"item:{event.get('order')}",
                                  "EventName": "CompletedItemAcquired", "EventTime": event.get("time"),
                                  "KillerChampion": owner.get("champion_name"), "KillerTeam": owner.get("team"),
                                  "EventTeam": event.get("team"), "ItemId": event.get("item_id"),
                                  "ItemName": event.get("item_name") or self.tracker._item_name(event.get("item_id")), "ObservedOnly": True})
        public_events.sort(key=lambda event: float(event.get("EventTime") or 0))
        local_player = snap.get("local_player", {})
        local_player = local_player if isinstance(local_player, dict) else {}
        payload = {
            "gameMode": snap.get("game_mode", "UNKNOWN"), "gameTime": snap.get("game_time", 0),
            "localTeam": snap.get("local_team", ""), "localPlayer": public_player(local_player),
            "localStats": snap.get("local_live_stats", {}), "players": snap.get("all_players", []),
            "events": public_events,
            "overlay": overlay,
            "gameMonitorIndex": (self.recordings.snapshot().get("gameMonitorIndex")
                                 if callable(getattr(self.recordings, "snapshot", None)) else None),
            "gameWindow": league_client_rect_pixels(),
            "sessionId": session.get("session_id"),
            "recommendations": recommendations,
            "skillOrder": deepcopy(getattr(self, "_skill_order", {"status": "unavailable", "order": []})),
            "enemyShopTimers": enemy_timers,
            "pendingAbility": {"slot": pending_slot, "source": "observed_ability_ranks"} if pending_slot else None,
        }
        payload["localStats"] = {**(payload["localStats"] if isinstance(payload["localStats"], dict) else {}),
                                 "killParticipation": calculate_kill_participation(players, str(snap.get("local_team") or ""), snap.get("local_player"))}
        payload["players"] = [public_player(player) for player in players]
        with self.lock:
            self.state.update({"state": "active", "connected": True, "telemetry": "current",
                               "snapshot": payload, "sessionId": session.get("session_id"),
                               "lastUpdated": datetime.now(UTC).isoformat(),
                               "message": "Telemetría Live Client activa", "source": "live"})

    def _schedule_recommendations(self, session: dict[str, Any], snap: dict[str, Any]) -> None:
        if self.stop_event.is_set():
            return
        local = snap.get("local_player") if isinstance(snap.get("local_player"), dict) else {}
        players = snap.get("all_players") if isinstance(snap.get("all_players"), list) else []
        def inventory(player):
            return tuple(sorted((normalized_inventory(player.get("items")) or {}).items()))
        now = time.monotonic()
        if now - getattr(self, "_skill_revision_checked_at", 0.0) >= 15:
            self._skill_revision_checked_at = now
            repository = getattr(getattr(self, "_preparation_service", None), "repository", None)
            champion = str(local.get("championName") or "")
            if repository is not None and champion:
                try:
                    path = repository.ruta(champion)
                    stamp = path.stat()
                    self._skill_source_revision = (stamp.st_mtime_ns, stamp.st_size)
                except OSError:
                    self._skill_source_revision = None
        signature = (str(session.get("session_id") or ""), str(local.get("championName") or ""),
                     str(local.get("position") or ""), (session.get("players", {}).get(session.get("local_player_key")) or {}).get("role"),
                     rune_ids(local.get("runes")), getattr(self, "_skill_source_revision", None), inventory(local),
                     snap.get("game_mode"), int(max(0, number(snap.get("game_time"))) // 300),
                     tuple(sorted((str(player.get("championName") or ""), inventory(player),
                                   tuple((player.get("scores") or {}).get(key) for key in ("kills", "deaths", "assists")))
                                  for player in players if isinstance(player, dict) and player.get("team") != snap.get("local_team"))))
        # CS and wall time do not alter build affinity; enemy threat changes do.
        # Gold is handled by the cheap recipe pass without rerunning scoring.
        self._latest_recommendation_signature = signature
        session_id = str(session.get("session_id") or "")
        if session_id != self._recommendation_session_id:
            self._recommendations = []
            self._skill_order = {"status": "unavailable", "order": []}
            self._recommendation_session_id = session_id
        if signature == self._recommendation_signature:
            return
        if self._recommendation_future is not None and not self._recommendation_future.done():
            return
        self._recommendation_signature = signature
        self._recommendation_requested_at = time.monotonic()
        current_players = deepcopy(session.get("players", {}))
        for index, player in enumerate(players):
            key = self.tracker._player_key(player, index)
            if key not in current_players:
                continue
            current_players[key].update({"items": player.get("items", []), "runes": player.get("runes", {}),
                                         "level": player.get("level"), "scores": player.get("scores", {})})
            if player.get("position"):
                current_players[key]["position"] = player["position"]
            scores = player.get("scores") or {}
            current_players[key].update({key: scores.get(key) for key in ("kills", "deaths", "assists")})
            current_players[key]["cs"] = scores.get("creepScore")
            if key == session.get("local_player_key"):
                current_players[key]["current_gold"] = (snap.get("local_live_stats") or {}).get("currentGold")
        context = {key: session.get(key) for key in ("session_id", "local_player_key", "champion_name", "local_team", "game_mode", "game_version", "lane_matchups")}
        context.update(players=current_players, duration=snap.get("game_time", 0),
                       snapshots=[{"time": snap.get("game_time", 0), "players": current_players}],
                       events=[event for event in session.get("events", [])[-20:] if event.get("type") == "objective"])
        future = self._recommendation_pool.submit(self._calculate_recommendations, context)
        self._recommendation_future = future
        future.add_done_callback(lambda completed, expected=session_id, version=signature: self._apply_recommendations(completed, expected, version))

    def _current_game_version(self, session_id: str) -> str:
        """Read the installed client patch once per live session when LCU is available."""
        if session_id != getattr(self, "_version_session_id", None):
            self._version_session_id = session_id
            self._version_checked = False
            self._installed_game_version = ""
        if getattr(self, "_version_checked", False):
            return self._installed_game_version
        client = getattr(self, "lcu", None)
        port = getattr(client, "port", None)
        request_session = getattr(client, "session", None)
        if not port or request_session is None:
            return ""
        self._version_checked = True
        try:
            response = request_session.get(f"https://127.0.0.1:{port}/lol-patch/v1/game-version", timeout=1.2)
            if response.status_code == 200:
                value = response.json()
                version = value if isinstance(value, str) else value.get("gameVersion", "") if isinstance(value, dict) else ""
                if re.match(r"^\d+\.\d+(?:\.|$)", str(version)):
                    self._installed_game_version = str(version)
        except (requests.RequestException, ValueError, TypeError):
            pass
        return self._installed_game_version

    def _update_overlay_sounds(self, alerts: list[dict[str, Any]]) -> None:
        now = time.monotonic()
        if self.settings_service is not None and now - self._sound_settings_checked_at >= 10:
            try:
                settings = self.settings_service.load()
                self._sound_settings_checked_at = now
                self.alert_tracker.purchase_seconds = int(settings.get("overlay_alert_duration", 8))
                self.alert_tracker.lead_seconds = int(settings.get("overlay_alert_lead", 60))
                self.sound_service.set_enabled(bool(settings.get("overlay_sound_enabled", True)))
                self.sound_service.set_volume(settings.get("overlay_sound_volume", 0.6))
                self.sound_service.set_kind_enabled("objective", bool(settings.get("overlay_sound_objective", True)))
                self.sound_service.set_kind_enabled("dragon", bool(settings.get("overlay_sound_dragon", True)))
                self.sound_service.set_kind_enabled("enemy_buy", bool(settings.get("overlay_sound_enemy_buy", True)))
            except (OSError, ValueError, TypeError):
                pass
        for alert in alerts:
            key = str(alert.get("key") or "")
            if not key or key in self._played_sound_alerts:
                continue
            # Alert keys identify one occurrence (including early/final phases).
            # Remember them for the whole session: a notice can disappear and
            # return when a higher-priority notice temporarily takes its slot.
            self._played_sound_alerts.add(key)
            if alert.get("kind") == "objective":
                if alert.get("objective") == "dragon": self.sound_service.play_dragon_spawn()
                else: self.sound_service.play_objective_spawn()
            elif alert.get("kind") == "purchase" and alert.get("side") == "enemy":
                self.sound_service.play_enemy_buy()

    def _calculate_recommendations(self, session: dict[str, Any]) -> dict[str, Any]:
        if getattr(self, "_preparation_service", None) is None:
            self._preparation_service = LivePreparationService(self.items)
        return self._preparation_service.rank(session)

    def _current_recommendations(self, snap: dict[str, Any]) -> list[dict[str, Any]]:
        service = getattr(self, "_preparation_service", None)
        rows = getattr(self, "_recommendations", [])
        if service is None:
            return rows
        stats = snap.get("local_live_stats") or {}
        return service.purchases(rows, snap.get("local_player") or {}, stats.get("currentGold"), str(snap.get("game_mode") or ""))

    def _apply_recommendations(self, future: Future, expected_session: str, expected_signature=None) -> None:
        try:
            result = future.result()
        except Exception:
            logger.exception("Live item preparation failed")
            result = {"recommendations": [], "skillOrder": {"status": "unavailable", "order": []}}
        with self.lock:
            if self.stop_event.is_set() or expected_session != self._recommendation_session_id:
                return
            if expected_signature is not None and expected_signature != self._latest_recommendation_signature:
                return
            self._recommendations = result["recommendations"]
            self._skill_order = result["skillOrder"]
            current = self.state.get("snapshot")
            if isinstance(current, dict) and current.get("sessionId") == expected_session:
                recommendations = self._current_recommendations({"local_player": current.get("localPlayer"), "local_live_stats": current.get("localStats"), "game_mode": current.get("gameMode")})
                overlay = current.get("overlay")
                if isinstance(overlay, dict):
                    overlay["recommendations"] = recommendations
                current["skillOrder"] = deepcopy(self._skill_order)
                current["recommendations"] = recommendations

    def _finish(self) -> None:
        self._version_session_id = None
        self._version_checked = False
        self._installed_game_version = ""
        if hasattr(self, "pending_ability"):
            self.pending_ability.reset()
        completed = self.tracker.finish()
        self.failures = 0
        self._recommendation_session_id = None
        self._recommendation_signature = None
        self._recommendations = []
        self._skill_order = {"status": "unavailable", "order": []}
        if hasattr(self, "enemy_inventory_tracker"):
            self.enemy_inventory_tracker.reset("")
        self.alert_tracker.reset()
        self._played_sound_alerts.clear()
        if completed:
            post_game = self._post_game_payload(completed)
            # RecordingRuntime independently supervises automatic capture and
            # remains the single owner of FFmpeg. This retains session metadata
            # in its existing sidecar association flow.
            with self.lock:
                self.state["completedSessionId"] = completed.get("session_id")
                self.state["postGame"] = post_game
            if self.on_completed:
                try:
                    self.on_completed()
                except RuntimeError:
                    pass

    def _post_game_payload(self, completed: dict[str, Any]) -> dict[str, Any]:
        """Build a renderer-safe final scoreboard from the canonical tracker session."""
        records = completed.get("players") if isinstance(completed.get("players"), dict) else {}
        final = completed.get("final_scoreboard") if isinstance(completed.get("final_scoreboard"), dict) else {}
        local_team = str(completed.get("local_team") or "")
        players: list[dict[str, Any]] = []
        champion_by_key: dict[str, str] = {}
        for key, meta in records.items():
            if not isinstance(meta, dict):
                continue
            champion = str(meta.get("champion_name") or "")
            if champion:
                champion_by_key[str(key)] = champion
            point = final.get(key) if isinstance(final.get(key), dict) else {}
            stats = point.get("stats") if isinstance(point.get("stats"), dict) else {}
            item_rows = [{"itemID": item_id, "displayName": str(self.items.get(str(item_id), {}).get("name") or "")}
                         for item_id in point.get("items", []) if str(item_id).isdigit()]
            players.append({"championName": champion, "team": str(meta.get("team") or ""),
                            "position": str(meta.get("role") or ""), "local": bool(meta.get("is_local_player")),
                            "win": meta.get("win") if isinstance(meta.get("win"), bool) else None,
                            "level": point.get("level"),
                            "scores": {"kills": point.get("kills"), "deaths": point.get("deaths"),
                                       "assists": point.get("assists"), "creepScore": point.get("cs"),
                                       "wardScore": stats.get("vision_score")},
                            "damageToChampions": stats.get("damage_to_champions"),
                            "items": item_rows, "summonerSpells": meta.get("summoner_spells") or {},
                            "runes": meta.get("runes") or {}})
        events: list[dict[str, Any]] = []
        allowed = {"kill_exact", "death_exact", "objective", "first_blood", "multikill", "shutdown", "completed_item_acquired"}
        for event in completed.get("events", []):
            if not isinstance(event, dict) or event.get("type") not in allowed:
                continue
            if event.get("type") == "death_exact" and event.get("killer_key"):
                continue
            kind = str(event.get("type"))
            killer_key = event.get("killer_key")
            if kind not in {"kill_exact", "death_exact"} and not killer_key:
                killer_key = event.get("player_key")
            killer = champion_by_key.get(str(killer_key or ""))
            victim = champion_by_key.get(str(event.get("victim_key") or ""))
            name = {"kill_exact": "ChampionKill", "objective": {
                        "dragon": "DragonKill", "baron": "BaronKill", "rift_herald": "HeraldKill", "void_grub": "HordeKill",
                        "tower": "TurretKilled", "inhibitor": "InhibKilled", "inhibitor_respawned": "InhibRespawned",
                        "inhibitor_respawning": "InhibRespawningSoon"}.get(str(event.get("objective")), "Objective"),
                    "death_exact": "ChampionKill", "first_blood": "FirstBlood", "multikill": "MultiKill", "shutdown": "Shutdown",
                     "completed_item_acquired": "CompletedItemAcquired"}.get(kind, "GameEvent")
            normalized = normalize_live_event({"EventID": event.get("event_id") or event.get("order"), "EventName": name,
                           "EventTime": event.get("time"), "KillerChampion": killer,
                           "VictimChampion": victim, "EventTeam": event.get("team"),
                           "DragonType": event.get("monster"), "Objective": event.get("objective_label"),
                           "TurretKilled": event.get("structure") if event.get("objective") == "tower" else None,
                           "InhibKilled": event.get("structure") if str(event.get("objective", "")).startswith("inhibitor") else None,
                           "InhibRespawned": event.get("structure") if event.get("objective") == "inhibitor_respawned" else None,
                           "InhibRespawningSoon": event.get("structure") if event.get("objective") == "inhibitor_respawning" else None,
                           "ItemId": event.get("item_id"), "ItemName": event.get("item_name") or self.items.get(str(event.get("item_id") or ""), {}).get("name"),
                           "ObservedOnly": kind == "completed_item_acquired",
                           "Count": event.get("count"), "MultiKill": event.get("multikill"),
                           "shutdown_confirmed": event.get("shutdown_confirmed") is True,
                           "Stolen": str(event.get("stolen", "")).casefold() == "true"}, killer or "", victim or "")
            if kind == "objective":
                objective = str(event.get("objective") or "")
                normalized["ObjectiveKind"] = objective
                normalized["ObjectiveLabel"] = str(normalized.get("ObjectiveLabel") or event.get("objective_label") or "Objetivo")
                normalized["TargetActorType"] = {"dragon":"dragon", "baron":"baron", "rift_herald":"rift_herald", "void_grub":"void_grub", "tower":"tower", "inhibitor":"inhibitor", "inhibitor_respawned":"inhibitor", "inhibitor_respawning":"inhibitor"}.get(objective, "environment")
                normalized["TargetActorName"] = normalized["ObjectiveLabel"]
            if event.get("killer_actor_type"):
                normalized["KillerActorType"] = event.get("killer_actor_type")
                normalized["KillerActorName"] = event.get("killer_actor_name") or ""
                if event.get("killer_actor_type") == "minion" and str(event.get("objective")) in {"tower", "inhibitor"}:
                    normalized["EventDescription"] = f"Los súbditos destruyeron {'una torre' if event.get('objective') == 'tower' else 'un inhibidor'}"
            if event.get("victim_actor_type"):
                normalized["VictimActorType"] = event.get("victim_actor_type")
                normalized["VictimActorName"] = event.get("victim_actor_name") or ""
            if kind == "death_exact":
                victim_name = victim or "El campeón"
                actor_type = str(event.get("killer_actor_type") or "environment")
                actor_labels = {"minion": "súbditos", "tower": "una torre", "neutral_monster": "un monstruo neutral",
                                "environment": "una causa no identificada", "unknown": "una causa no identificada"}
                if killer:
                    normalized["EventDescription"] = f"{victim_name} murió por {killer}"
                else:
                    normalized["EventDescription"] = f"{victim_name} murió por {actor_labels.get(actor_type, 'una causa no identificada')}"
            events.append(normalized)
        events.sort(key=lambda event: float(event.get("EventTime") or 0))
        local = next((row for row in players if row.get("local")), None)
        return {"sessionId": str(completed.get("session_id") or ""),
                "gameMode": str(completed.get("game_mode") or "UNKNOWN"),
                "duration": completed.get("duration"), "localTeam": local_team,
                "localChampion": (local or {}).get("championName"),
                "result": (local or {}).get("win"), "players": players, "events": events,
                "provisional": True}

    def _set_disconnected(self) -> None:
        if self.tracker.is_tracking:
            self.tracker.mark_telemetry_gap()
            if hasattr(self, "enemy_inventory_tracker"):
                self.enemy_inventory_tracker.mark_gap()
            self.failures += 1
            if self.failures < self.END_FAILURE_LIMIT:
                with self.lock:
                    self.state.update({"telemetry": "stale", "message": "El cliente perdió conexión; se conserva la partida durante la reconexión."})
                return
            self._finish()
        self._set_state("disconnected", "Unknown", "Cliente de League desconectado")

    def _set_state(self, state: str, phase: str, message: str) -> None:
        with self.lock:
            self.state.update({"state": state, "connected": state != "disconnected", "telemetry": "unavailable",
                               "phase": phase, "message": message,
                               "snapshot": self.state.get("snapshot") if state in {"post_game", "game_ending", "disconnected"} else None,
                               "lastUpdated": datetime.now(UTC).isoformat()})
