"""Data adapter for the legacy postgame review workflow."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import math
from typing import Any
import threading

from app.services.live_match_tracker import LiveMatchTracker
from app.services.recording_service import RecordingLibrary, build_markers
from app.services.recording_service import find_video_for_session
from app.services.settings_service import SettingsService

_generation_lock = threading.Lock()


def _sort_seconds(event: dict[str, Any]) -> float:
    try:
        return float(event.get("time") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _number(value: Any) -> float:
    try:
        result = float(value)
        return result if result >= 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _metric(*values: Any) -> int | float | None:
    for value in values:
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            return value if value >= 0 else None
    return None


def _radar(stats: dict[str, Any]) -> list[float]:
    """Keep the five axes and ceilings used by PostgameSidebar.radar_values."""
    duration = _number(stats.get("duration"))
    minutes = duration / 60 if duration > 0 else 0
    def ratio(value: Any, ceiling: float) -> float:
        return max(0.0, min(1.0, _number(value) / ceiling)) if ceiling > 0 else 0.0
    vision_ceiling = max(15.0, minutes) if minutes else 30.0
    kills, assists = _number(stats.get("kills")), _number(stats.get("assists"))
    return [ratio(stats.get("cspm"), 10), ratio(stats.get("gpm"), 600), ratio(stats.get("vision"), vision_ceiling), ratio(stats.get("kda"), 8), ratio(kills + assists, 20)]


def _public_session(session: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    players = session.get("players") if isinstance(session.get("players"), dict) else {}
    local_key = str(session.get("local_player_key") or "")
    local_team = str(session.get("local_team") or "")
    final = session.get("final_scoreboard") if isinstance(session.get("final_scoreboard"), dict) else {}
    participants = []
    safe_ids: dict[str, str] = {}
    for key, player in players.items():
        if not isinstance(player, dict):
            continue
        stats = final.get(key) if isinstance(final.get(key), dict) else {}
        point = {}
        for snapshot in reversed(session.get("snapshots", []) if isinstance(session.get("snapshots"), list) else []):
            snapshot_players = snapshot.get("players") if isinstance(snapshot, dict) and isinstance(snapshot.get("players"), dict) else {}
            candidate = snapshot_players.get(key)
            if isinstance(candidate, dict) and candidate:
                point = candidate
                break
        stats = {**stats, **point}
        raw_stats = stats.get("stats") if isinstance(stats.get("stats"), dict) else {}
        cs = _metric(stats.get("cs"), stats.get("cs_total"), stats.get("total_minions_killed"))
        official = player.get("final") if isinstance(player.get("final"), dict) else {}
        final_sync = session.get("final_sync") if isinstance(session.get("final_sync"), dict) else {}
        if final_sync.get("status") == "synced":
            cs = _metric(official.get("cs_total"), cs)
        items = stats.get("items", player.get("items", []))
        if isinstance(items, dict):
            items = [items[key] for key in sorted(items, key=str)]
        if not isinstance(items, list):
            items = []
        item_ids = []
        for value in items:
            if isinstance(value, dict):
                value = value.get("itemID") or value.get("itemId") or value.get("id")
            if isinstance(value, (str, int)) and str(value).isdigit() and str(value) != "0":
                item_ids.append(str(value))
            if len(item_ids) >= 7:
                break
        matchup = session.get("lane_matchups", {}).get(str(player.get("role") or "").upper(), {}) if isinstance(session.get("lane_matchups"), dict) else {}
        opponent_key = str(matchup.get("enemy_key") or "") if isinstance(matchup, dict) and str(key) == local_key else ""
        opponent = players.get(opponent_key) if opponent_key else None
        kills, deaths, assists = (_metric(stats.get(field)) for field in ("kills", "deaths", "assists"))
        gold = _metric(stats.get("gold_earned"), stats.get("estimated_gold"))
        vision = _metric(stats.get("vision_score"), raw_stats.get("vision_score"))
        duration = _number(metadata.get("duration_seconds") or session.get("duration"))
        minutes = duration / 60 if duration else 0
        radar_stats = {"duration": duration, "kills": kills, "deaths": deaths, "assists": assists, "vision": vision,
            "cspm": cs / minutes if cs is not None and minutes else 0, "gpm": gold / minutes if gold is not None and minutes else 0,
            "kda": ((kills or 0) + (assists or 0)) / deaths if deaths else (kills or 0) + (assists or 0)}
        source_participant_id = player.get("participant_id", player.get("participantId"))
        participant_id = f"participant-{source_participant_id}" if source_participant_id not in (None, "", 0, "0") else f"participant-{len(safe_ids)}"
        if participant_id in safe_ids.values():
            participant_id = f"participant-{len(safe_ids)}"
        safe_ids[str(key)] = participant_id
        participants.append({
            "participantId": participant_id,
            "champion": str(player.get("champion_name") or "Campeón no disponible"),
            "championId": player.get("champion_id", player.get("championId")),
            "role": str(player.get("role") or ""),
            "team": str(player.get("team") or ""),
            "allied": True if str(key) == local_key else (str(player.get("team") or "") == local_team if local_team and player.get("team") else None),
            "local": str(key) == local_key,
            "opponentChampion": str(opponent.get("champion_name") or "") if isinstance(opponent, dict) else "",
            "level": _metric(stats.get("champion_level"), stats.get("level"), player.get("level")),
            "kills": kills, "deaths": deaths, "assists": assists,
            "cs": cs,
            "gold": gold, "vision": vision, "radar": _radar(radar_stats),
            "championDamageDealt": _metric(official.get("damage_to_champions"), stats.get("damage_to_champions"), raw_stats.get("damage_to_champions")),
            # Match-V5 totalDamageTaken mixes champion, minion, structure and
            # environmental sources. Keep it explicitly scoped and never
            # expose it through a champion-only "damage received" field.
            "championDamageReceived": None, "championDamageReceivedCoverage": "unavailable",
            "allSourceDamageReceived": _metric(official.get("total_damage_taken"), stats.get("total_damage_taken"), raw_stats.get("total_damage_taken")),
            "damageToStructures": _metric(official.get("damage_to_structures"), stats.get("damage_to_structures"), raw_stats.get("damage_to_structures")),
            "summonerSpells": deepcopy(player.get("summoner_spells")) if isinstance(player.get("summoner_spells"), (dict, list)) else None,
            "runes": deepcopy(player.get("runes")) if isinstance(player.get("runes"), dict) else None,
            "items": item_ids,
            "win": stats.get("win") if isinstance(stats.get("win"), bool) else player.get("win") if isinstance(player.get("win"), bool) else None,
        })
    teams: dict[str, dict[str, Any]] = {}
    for participant in participants:
        team = participant["team"] or "Equipo no disponible"
        slot = teams.setdefault(team, {"kills": 0, "win": participant["win"]})
        slot["kills"] += int(participant.get("kills") or 0)
    events = []
    raw_offset = metadata.get("game_time_offset")
    try:
        offset = float(raw_offset)
        offset_known = math.isfinite(offset) and offset >= 0
    except (TypeError, ValueError, OverflowError):
        offset = 0.0
        offset_known = False
    names_by_key = {str(key): str(value.get("champion_name") or "") for key, value in players.items() if isinstance(value, dict)}
    raw_events = session.get("events", []) if isinstance(session.get("events"), list) else []
    item_catalog: dict[str, Any] = {}
    try:
        import json
        from pathlib import Path
        catalog = json.loads((Path(__file__).resolve().parents[1] / "data" / "items.json").read_text(encoding="utf-8"))
        item_catalog = catalog.get("items", {}) if isinstance(catalog, dict) else {}
    except (OSError, ValueError, TypeError):
        pass
    exact_combat: list[tuple[str, str, float]] = []
    for exact_event in raw_events:
        if not isinstance(exact_event, dict):
            continue
        exact_type = str(exact_event.get("type") or "").lower()
        exact_kind = {"kill_exact": "kill", "death_exact": "death", "assist_exact": "assist"}.get(exact_type)
        # Exact LCU records with unresolved roster keys cannot safely replace the
        # local sampled event. In particular, their raw label may contain Riot IDs.
        if exact_kind:
            exact_time = _sort_seconds(exact_event)
            player_key = str(exact_event.get("player_key") or "")
            killer_key = str(exact_event.get("killer_key") or (player_key if exact_kind == "kill" else ""))
            victim_key = str(exact_event.get("victim_key") or (player_key if exact_kind == "death" else ""))
            if killer_key in players and victim_key in players and killer_key != victim_key:
                exact_combat.append(("kill", killer_key, exact_time))
                exact_combat.append(("death", victim_key, exact_time))
            assisters = exact_event.get("assister_keys") or exact_event.get("assists") or []
            if isinstance(assisters, str): assisters = [assisters]
            if killer_key in players and victim_key in players and killer_key != victim_key:
                for assister_key in {str(key) for key in assisters if str(key) in players}:
                    exact_combat.append(("assist", assister_key, exact_time))
            if exact_kind == "assist" and player_key in players and killer_key in players and victim_key in players:
                exact_combat.append(("assist", player_key, exact_time))
    undone_purchase_indexes: set[int] = set()
    for undo_index, candidate in enumerate(raw_events):
        if not isinstance(candidate, dict) or str(candidate.get("type") or "").lower() not in {"item_undo", "item_undone"}:
            continue
        undo_item = str(candidate.get("item_id") or candidate.get("itemid") or "")
        undo_player = str(candidate.get("player_key") or "")
        for purchase_index in range(undo_index - 1, -1, -1):
            purchase = raw_events[purchase_index]
            if (isinstance(purchase, dict) and purchase_index not in undone_purchase_indexes
                    and str(purchase.get("type") or "").lower() in {"item_purchase", "item_purchased"}
                    and str(purchase.get("player_key") or "") == undo_player
                    and str(purchase.get("item_id") or purchase.get("itemid") or "") == undo_item):
                undone_purchase_indexes.add(purchase_index)
                break
    for order, event in enumerate(raw_events):
        if not isinstance(event, dict):
            continue
        try:
            game_time = float(event.get("time"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(game_time) or game_time < 0:
            continue
        event_type = str(event.get("type") or "").lower()
        owner = str(event.get("player_key") or "")
        killer = str(event.get("killer_key") or (owner if event_type in {"kill", "kill_exact"} else ""))
        victim = str(event.get("victim_key") or (owner if event_type in {"death", "death_exact"} else ""))
        raw_assists = event.get("assister_keys") or event.get("assists") or []
        if isinstance(raw_assists, str): raw_assists = [raw_assists]
        assists = [str(key) for key in raw_assists if str(key) in players]
        kind = ""
        side = "unknown"
        team_value = event.get("team")
        focus: list[str] = []
        def side_for(key: str) -> str:
            p = players.get(key) if key else None
            team = str((p or {}).get("team") or "").upper()
            return "allied" if local_team and team == local_team.upper() else "enemy" if local_team and team else "unknown"
        if event_type in {"kill", "kill_exact"}:
            if not killer: continue
            if event_type == "kill_exact" and (killer not in players or victim not in players or killer == victim): continue
            if event_type == "kill" and any(kind == "kill" and key == killer and abs(moment-game_time) <= 2 for kind,key,moment in exact_combat): continue
            if event_type == "kill" and not victim:
                nearby_deaths = {str(e.get("player_key") or e.get("victim_key") or "") for e in raw_events
                                 if isinstance(e, dict) and str(e.get("type") or "").lower() == "death"
                                 and str(e.get("player_key") or e.get("victim_key") or "") in players
                                 and abs(_sort_seconds(e)-game_time) <= 1.5
                                 and side_for(str(e.get("player_key") or e.get("victim_key") or "")) != side_for(killer)}
                if len(nearby_deaths) == 1:
                    victim = next(iter(nearby_deaths))
            kind, focus, side = "kill", [killer, victim, *assists], side_for(killer)
        elif event_type in {"death", "death_exact"}:
            if not victim: continue
            if event_type == "death_exact" and (victim not in players or killer not in players or killer == victim): continue
            if event_type == "death" and any(kind == "death" and key == victim and abs(moment-game_time) <= 2 for kind,key,moment in exact_combat): continue
            kind, focus = "death", [victim, killer]
            side = side_for(killer) if killer else "unknown"
            if not killer:
                # The local tracker stores victim and killer as separate sampled events;
                # use a same-moment opposing kill only when telemetry links the teams by time.
                nearby_kills = {str(e.get("player_key") or e.get("killer_key") or "") for e in raw_events if isinstance(e, dict) and str(e.get("type") or "").lower() in {"kill", "kill_exact"}
                                and abs(_sort_seconds(e)-game_time) <= 1.5
                                and str(e.get("player_key") or e.get("killer_key") or "") in players
                                and side_for(str(e.get("player_key") or e.get("killer_key") or "")) != side_for(victim)}
                own_side = side_for(victim)
                if len(nearby_kills) == 1:
                    killer = next(iter(nearby_kills))
                    focus.append(killer)
                    killer_side = side_for(killer)
                    side = killer_side if killer_side != own_side else "unknown"
        elif event_type in {"assist", "assist_exact"}:
            if not owner: continue
            if event_type == "assist_exact" and (owner not in players or killer not in players or victim not in players): continue
            if event_type == "assist" and any(kind == "assist" and key == owner and abs(moment-game_time) <= 2 for kind,key,moment in exact_combat): continue
            kind, focus, side = "assist", [owner, killer, victim], side_for(killer) if killer else side_for(owner)
        elif event_type == "objective":
            raw_obj = str(event.get("objective") or event.get("objective_label") or event.get("label") or "").casefold().replace("_", " ")
            aliases = {"dragon":"dragon", "dragón":"dragon", "baron":"baron", "nashor":"baron", "rift herald":"rift_herald", "herald":"rift_herald", "heraldo":"rift_herald", "horde":"horde", "void grub":"horde", "larva":"horde", "grub":"horde", "tower":"tower", "torre":"tower", "turret":"tower", "inhibitor":"inhibitor", "inhibidor":"inhibitor", "nexus":"nexus", "nexo":"nexus"}
            kind = next((value for name,value in aliases.items() if name in raw_obj), "")
            team_value = event.get("team") or event.get("objective_team")
            if team_value and local_team: side = "allied" if str(team_value).upper() == local_team.upper() else "enemy"
            elif event.get("owner_team") and local_team:
                owner_side = "allied" if str(event["owner_team"]).upper() == local_team.upper() else "enemy"
                side = "enemy" if owner_side == "allied" else "allied"
            else:
                objective_actor = str(event.get("killer_key") or event.get("player_key") or "")
                actor_side = side_for(objective_actor)
                if actor_side != "unknown":
                    side = actor_side
                elif local_team:
                    killer_team = LiveMatchTracker._team_from_unit_name(str(event.get("killer_name") or ""))
                    if killer_team:
                        side = "allied" if killer_team.upper() == local_team.upper() else "enemy"
                    else:
                        structure_owner = LiveMatchTracker._structure_owner(str(event.get("structure") or ""))
                        if structure_owner:
                            owner_side = "allied" if structure_owner.upper() == local_team.upper() else "enemy"
                            side = "enemy" if owner_side == "allied" else "allied"
            focus = [str(k) for k in [event.get("killer_key"), event.get("player_key"), *assists] if k]
        elif event_type in {"item_purchase", "item_purchased", "item_sale", "item_sold"}:
            if event_type in {"item_purchase", "item_purchased"} and order in undone_purchase_indexes:
                continue
            item_id = str(event.get("item_id") or event.get("itemID") or "")
            item_meta = item_catalog.get(item_id) if item_id else None
            # Current patch catalog classifies complete build items by depth; consumables,
            # trinkets and items with an upgrade path are excluded from the review feed.
            tags = set(item_meta.get("tags") or []) if isinstance(item_meta, dict) else set()
            if (not isinstance(item_meta, dict) or item_meta.get("into") or int(item_meta.get("depth") or 0) < 2
                    or tags.intersection({"Consumable", "Trinket"})):
                continue
            kind, focus, side = ("item_purchase" if event_type in {"item_purchase", "item_purchased"} else "item_sale"), [owner], side_for(owner)
        else: continue
        if not kind: continue
        primary_key = killer if kind == "kill" else victim if kind == "death" else owner if kind in {"assist", "item_purchase", "item_sale"} else str(event.get("player_key") or "")
        primary_champion = names_by_key.get(primary_key, "")
        involved_champions = list(dict.fromkeys(names_by_key[key] for key in focus if key in names_by_key and names_by_key[key]))
        item_id = str(event.get("item_id") or event.get("itemID") or "") if kind in {"item_purchase", "item_sale"} else ""
        item_meta = item_catalog.get(item_id) if item_id else None
        participant_roles: dict[str, str] = {}
        if kind in {"kill", "death", "assist"}:
            if killer in safe_ids: participant_roles[killer] = "kill"
            if victim in safe_ids: participant_roles[victim] = "death"
            for assister in assists:
                if assister in safe_ids: participant_roles[assister] = "assist"
            if kind == "assist" and owner in safe_ids:
                participant_roles[owner] = "assist"
        elif kind in {"item_purchase", "item_sale"} and owner in safe_ids:
            participant_roles[owner] = kind
        elif kind and event_type == "objective":
            for participant_key in focus:
                if participant_key in safe_ids: participant_roles[participant_key] = kind
        if kind == "kill":
            label = f"{primary_champion} asesinó a {names_by_key.get(victim, 'un campeón no identificado')}" if primary_champion else "Asesinato · campeón no identificado"
        elif kind == "death":
            label = f"{primary_champion} murió a manos de {names_by_key.get(killer, 'un campeón no identificado')}" if primary_champion else "Muerte · campeón no identificado"
        elif kind == "assist":
            label = f"{primary_champion} asistió en una eliminación" if primary_champion else "Asistencia · campeón no identificado"
        elif kind in {"item_purchase", "item_sale"}:
            verb = "Compra" if kind == "item_purchase" else "Venta"
            item_name = str(item_meta.get("name") or "Objeto") if isinstance(item_meta, dict) else "Objeto"
            label = f"{verb}: {item_name}"
        else:
            objective_names = {"dragon":"Dragón", "baron":"Nashor", "rift_herald":"Heraldo", "horde":"Larvas", "tower":"Torre", "inhibitor":"Inhibidor", "nexus":"Nexo"}
            objective_name = objective_names.get(kind, "Objetivo")
            if side == "allied": label = f"Tu equipo consiguió {objective_name}"
            elif side == "enemy": label = f"Equipo rival consiguió {objective_name}"
            else: label = f"{objective_name} · equipo no identificado"
        role_entries = [{"participantId": safe_ids[key], "category": role, "champion": names_by_key.get(key, ""), "championId": (players.get(key) or {}).get("champion_id", (players.get(key) or {}).get("championId")), "side": side_for(key)} for key, role in participant_roles.items()]
        stable_event_id = str(event.get("event_id") or "")
        if kind in {"kill", "death", "assist"} and (not stable_event_id or stable_event_id.startswith("event-")):
            if killer in safe_ids and victim in safe_ids and killer != victim:
                stable_event_id = f"combat:{game_time:.1f}:{safe_ids[killer]}:{safe_ids[victim]}"
            else:
                stable_event_id = f"combat:{kind}:{game_time:.1f}:{safe_ids.get(primary_key, 'unknown')}:{order}"
        item = {"type": kind, "category": kind, "categories": list(dict.fromkeys(role["category"] for role in role_entries)) or [kind], "label": label, "team": str(team_value or ""), "side": side, "event_id": stable_event_id or f"event-{order}", "order": order, "participants": sorted({safe_ids[key] for key in focus if key in safe_ids}), "participant_roles": role_entries, "champion": primary_champion, "champions": involved_champions}
        if kind in {"kill", "death", "assist"}:
            # Explicit champion-only fields keep renderers from interpreting old
            # labels that may contain streamer-mode summoner IDs.
            item["killerChampion"] = names_by_key.get(killer, "")
            item["victimChampion"] = names_by_key.get(victim, "")
            item["assistingChampions"] = list(dict.fromkeys(names_by_key[key] for key in assists if key in names_by_key and names_by_key[key]))
        if item_id:
            item["itemId"] = item_id
        item["time"] = game_time
        involved = primary_key
        if involved:
            item["player_scope"] = "local" if str(involved) == local_key else "other"
        else:
            item["player_scope"] = ""
        if offset_known:
            item["video_time"] = max(0.0, game_time - offset)
        events.append(item)
    # Exact local telemetry stores one row per role (kill, death, assist) for the
    # same native event. Fold those into one stable event while retaining each
    # participant's perspective for filtering.
    merged_events: dict[str, dict[str, Any]] = {}
    for event in events:
        identity = str(event.get("event_id") or "")
        if identity.startswith("event-"):
            identity = f"{identity}:{event.get('type')}"
        previous = merged_events.get(identity)
        if previous is None:
            merged_events[identity] = event
            continue
        previous["participants"] = sorted(set(previous.get("participants", [])) | set(event.get("participants", [])))
        roles = {(role.get("participantId"), role.get("category")): role for role in previous.get("participant_roles", [])}
        roles.update({(role.get("participantId"), role.get("category")): role for role in event.get("participant_roles", [])})
        previous["participant_roles"] = list(roles.values())
        previous["categories"] = list(dict.fromkeys(role.get("category") for role in previous["participant_roles"] if role.get("category")))
        previous["champions"] = list(dict.fromkeys(role.get("champion") for role in previous["participant_roles"] if role.get("champion")))
        combat_roles = previous["participant_roles"]
        killers = list(dict.fromkeys(role["champion"] for role in combat_roles if role.get("category") == "kill" and role.get("champion")))
        victims = list(dict.fromkeys(role["champion"] for role in combat_roles if role.get("category") == "death" and role.get("champion")))
        if killers and victims:
            previous["killerChampion"] = killers[0]
            previous["victimChampion"] = victims[0]
            previous["label"] = f"{killers[0]} asesinó a {victims[0]}"
            previous["champion"] = killers[0]
        elif killers:
            previous["label"] = f"{killers[0]} consiguió una eliminación"
            previous["champion"] = killers[0]
        elif victims:
            previous["label"] = f"{victims[0]} murió; asesino no identificado"
            previous["champion"] = victims[0]
    events = sorted(merged_events.values(), key=_sort_seconds)
    for participant in participants:
        participant["side"] = "allied" if participant.get("allied") is True else "enemy" if participant.get("allied") is False else "unknown"
    role_order = {"TOP": 0, "JUNGLE": 1, "MIDDLE": 2, "MID": 2, "BOTTOM": 3, "ADC": 3, "UTILITY": 4, "SUPPORT": 4}
    participants.sort(key=lambda player: (role_order.get(str(player.get("role") or "").upper(), 9), not player["allied"]))
    if offset_known:
        markers = [{**marker, "player_key": "local"} for marker in build_markers(session, offset)]
    else:
        markers = []
        for marker in metadata.get("markers", []) if isinstance(metadata.get("markers"), list) else []:
            if not isinstance(marker, dict):
                continue
            try:
                video_time = float(marker.get("time"))
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(video_time) and video_time >= 0:
                markers.append({k: marker[k] for k in ("kind", "label", "detail", "game_time") if k in marker} | {"time": video_time, "player_key": "local"})
    saved_review = session.get("ai_match_review") if isinstance(session.get("ai_match_review"), dict) else None
    current_fingerprint = ""
    if saved_review:
        try:
            from app.services.match_review_ai_service import MatchReviewAIService
            _prepared, current_fingerprint = MatchReviewAIService().prepare_input(session)
        except (TypeError, ValueError, OSError):
            pass
    review_valid = bool(saved_review and current_fingerprint and saved_review.get("source_fingerprint") == current_fingerprint)
    radar_teams = {}
    for side_name in ("allied", "enemy"):
        roster = [p for p in participants if p.get("side") == side_name]
        radar_teams[side_name] = [
            (sum(p["radar"][axis] for p in roster if p.get("radar") and p["radar"][axis] is not None) /
             sum(1 for p in roster if p.get("radar") and p["radar"][axis] is not None))
            if any(p.get("radar") and p["radar"][axis] is not None for p in roster) else None
            for axis in range(5)
        ]
    winner = None
    for event in raw_events:
        if not isinstance(event, dict): continue
        description = str(event.get("objective") or event.get("objective_label") or event.get("label") or "").casefold()
        if "nexus" not in description: continue
        destroying_team = event.get("team") or event.get("objective_team")
        if destroying_team:
            winner = "allied" if str(destroying_team).upper() == local_team.upper() else "enemy" if local_team else None
        elif event.get("owner_team") and local_team:
            owner_side = "allied" if str(event["owner_team"]).upper() == local_team.upper() else "enemy"
            winner = "enemy" if owner_side == "allied" else "allied"
        if winner: break
    if winner is None:
        local_result = next((p.get("win") for p in participants if p["local"] and isinstance(p.get("win"), bool)), None)
        if local_result is not None: winner = "allied" if local_result else "enemy"
    return {
        "available": bool(participants or events),
        "champion": str(session.get("champion_name") or next((p["champion"] for p in participants if p["local"]), "")),
        "gameMode": str(session.get("game_mode") or metadata.get("game_mode") or ""),
        "duration": _number(metadata.get("duration_seconds") or session.get("duration")),
        "gameTimeOffset": offset,
        "syncAvailable": offset_known,
        "result": True if winner == "allied" else False if winner == "enemy" else next((p.get("win") for p in participants if p["local"]), None),
        "winningTeam": winner,
        "radarTeams": radar_teams,
        "teamAssignmentKnown": bool(local_team and all(p.get("team") for p in participants)),
        "participants": participants, "teams": teams, "events": events,
        "markers": markers,
        "analysis": deepcopy(saved_review.get("analysis")) if saved_review and isinstance(saved_review.get("analysis"), dict) else None,
        "analysisState": "saved" if review_valid else "stale" if saved_review else "none",
        "analysisSource": "telemetría de partida; no analiza fotogramas del vídeo",
    }


def review_recording(name: str, *, generate: bool = False) -> dict[str, Any]:
    settings = SettingsService().load()
    library = RecordingLibrary(settings.get("recording_output_dir") or None)
    path = library.directory / name
    if path.parent.resolve() != library.directory.resolve() or not path.is_file():
        raise ValueError("No se encontró la grabación seleccionada.")
    metadata = library.load_metadata(path)
    tracker = LiveMatchTracker({}, persist=False)
    session_id = str(metadata.get("session_id") or "")
    sessions = tracker.load_saved_sessions()
    session = next((item for item in sessions if isinstance(item, dict) and str(item.get("session_id") or "") == session_id), None)
    if session is None and not session_id:
        videos = library.video_files()
        session = next((item for item in sessions if isinstance(item, dict) and find_video_for_session(videos, item, library.load_metadata) == path), None)
        session_id = str(session.get("session_id") or "") if isinstance(session, dict) else ""
    if not isinstance(session, dict):
        safe_markers = []
        for marker in metadata.get("markers", []) if isinstance(metadata.get("markers"), list) else []:
            if not isinstance(marker, dict):
                continue
            safe_markers.append({key: marker[key] for key in ("time", "game_time", "kind") if key in marker} | {"player_key": "local"})
        return {"available": False, "champion": str(metadata.get("champion") or ""), "gameMode": str(metadata.get("game_mode") or ""), "duration": _number(metadata.get("duration_seconds")), "gameTimeOffset": _number(metadata.get("game_time_offset")), "syncAvailable": isinstance(metadata.get("game_time_offset"), (int, float)), "teamAssignmentKnown": False, "participants": [], "teams": {}, "events": [], "markers": safe_markers, "analysis": None, "analysisState": "unavailable", "analysisSource": "Sin telemetría asociada a esta grabación."}
    if not generate:
        return _public_session(session, metadata)
    from app.services.match_review_ai_service import MatchReviewAIService
    api_key = str(settings.get("gemini_api_key") or "").strip()
    if not api_key:
        raise ValueError("No hay una clave de Gemini configurada. Añádela en Ajustes.")
    if not _generation_lock.acquire(blocking=False):
        raise ValueError("Ya hay un análisis de partida en curso.")
    try:
        report, model, fingerprint = MatchReviewAIService().analyze_match(session, api_key)
        record = {"schema_version": 2, "saved_match_id": session_id, "recording_id": str(session.get("recording_id") or "") or None, "player_participant_id": str(session.get("local_player_key") or ""), "champion": str(session.get("champion_name") or ""), "provider": "Gemini", "model": model, "created_at": datetime.now(UTC).isoformat(), "source_fingerprint": fingerprint, "analysis": report}
        tracker.guardar_revision_ia(session_id, record)
        updated = dict(session)
        updated["ai_match_review"] = record
        result = _public_session(updated, metadata)
        result["analysisState"] = "saved"
        return result
    finally:
        _generation_lock.release()
