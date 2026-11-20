"""Shared match-achievement registry and deterministic evaluation."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


# Thresholds retain the current medal rules where they existed. CS/min uses
# explicit role-neutral rates because the old total-CS thresholds were duration biased.
ACHIEVEMENT_REGISTRY: tuple[dict[str, Any], ...] = (
    {"id": "damage_sponge", "name": "Esponja de daño", "icon": "shield", "description": "Daño útil de campeones recibido", "metric": "useful_damage_received", "unit": "de daño útil recibido", "source": "BattleScore · daño de campeón observado en eventos de baja, ponderado por participación", "direction": "higher", "partial_policy": "Las medallas se calculan sobre el daño observado; la cobertura parcial se identifica en la tarjeta.", "decimal": False, "defaults": [20000, 30000, 40000, 50000]},
    {"id": "rift_nurse", "name": "Enfermero de la Grieta", "icon": "heart", "description": "Curación total", "metric": "healing", "unit": "de curación", "source": "Match-V5 · totalHeal", "direction": "higher", "decimal": False, "defaults": [5000, 10000, 20000, 30000]},
    {"id": "gold_machine", "name": "Máquina de hacer dinero", "icon": "coin", "description": "Oro total obtenido", "metric": "gold", "unit": "de oro", "source": "Match-V5 · goldEarned", "direction": "higher", "decimal": False, "defaults": [10000, 12000, 15000, 18000]},
    {"id": "artillery_ace", "name": "As de la artillería", "icon": "target", "description": "Daño infligido a campeones", "metric": "champion_damage", "unit": "de daño", "source": "Match-V5 · totalDamageDealtToChampions", "direction": "higher", "decimal": False, "defaults": [15000, 25000, 35000, 50000]},
    {"id": "executioner", "name": "El borrador", "icon": "swords", "description": "Asesinatos conseguidos", "metric": "kills", "unit": "asesinatos", "source": "Match-V5 · kills", "direction": "higher", "decimal": False, "defaults": [5, 8, 12, 16]},
    {"id": "rift_sentinel", "name": "Centinela de la Grieta", "icon": "eye", "description": "Puntuación de visión final", "metric": "vision", "unit": "de visión", "source": "Match-V5 · visionScore", "direction": "higher", "decimal": False, "defaults": [15, 25, 35, 50]},
    {"id": "scene_stealer", "name": "Robaescenas", "icon": "star", "description": "Objetivos robados al equipo rival", "metric": "objective_steals", "unit": "objetivos robados", "source": "Match-V5 · objectivesStolen; fallback challenges.epicMonsterSteals, sin sumarlos", "direction": "higher", "decimal": False, "defaults": [1, 1, 2, 3]},
    {"id": "key_player", "name": "Jugador clave", "icon": "crown", "description": "Asesinatos y asistencias", "metric": "kill_participations", "unit": "participaciones", "source": "Match-V5 · kills + assists", "direction": "higher", "decimal": False, "defaults": [8, 12, 18, 24]},
    {"id": "jungle_explorer", "name": "Explorador de la jungla", "icon": "jungle", "description": "Monstruos de jungla abatidos", "metric": "jungle_minions", "unit": "monstruos", "source": "Match-V5 Timeline · jungleMinionsKilled, última observación", "direction": "higher", "decimal": False, "defaults": [80, 120, 160, 200]},
    {"id": "zombie", "name": "Zombi", "icon": "skull", "description": "Resurrecciones registradas", "metric": "revives", "unit": "resurrecciones", "source": "Sin un campo o evento Riot fiable en Match-V5; no se infiere desde las muertes", "direction": "higher", "decimal": False, "defaults": [1, 2, 3, 4]},
    {"id": "ice_princess", "name": "Princesa de hielo", "icon": "snow", "description": "Tiempo de control de masas aplicado", "metric": "crowd_control", "unit": "seg. de control", "source": "Match-V5 · timeCCingOthers", "direction": "higher", "decimal": False, "defaults": [20, 35, 50, 70]},
    {"id": "last_hit_master", "name": "Maestro del último golpe", "icon": "minion", "description": "Súbditos y monstruos abatidos por minuto", "metric": "cs_per_minute", "unit": "CS/min", "source": "Match-V5 · totalMinionsKilled + neutralMinionsKilled, dividido por duración", "direction": "higher", "decimal": True, "defaults": [4.0, 5.5, 7.0, 9.0]},
    {"id": "lights_on", "name": "Luces encendidas", "icon": "lamp", "description": "Centinelas colocados", "metric": "wards_placed", "unit": "centinelas", "source": "Match-V5 · wardsPlaced", "direction": "higher", "decimal": False, "defaults": [10, 20, 30, 40]},
    {"id": "fast_forward", "name": "Avance rápido", "icon": "clock", "description": "Duración de una victoria", "metric": "winning_duration", "unit": "de duración", "source": "Match-V5 · duración; solo se obtiene con victoria", "direction": "lower", "decimal": False, "defaults": [2100, 1800, 1500, 1200]},
    {"id": "rift_specter", "name": "Espectro de la Grieta", "icon": "ghost", "description": "Objetivos épicos asegurados", "metric": "epic_objectives", "unit": "objetivos", "source": "Match-V5 Timeline · ELITE_MONSTER_KILL atribuido al participante", "direction": "higher", "decimal": False, "defaults": [1, 2, 3, 4]},
    {"id": "shadow_carry", "name": "Carry en la sombra", "icon": "shadow", "description": "Porcentaje del daño a campeones de tu equipo", "metric": "team_damage_share", "unit": "% del daño del equipo", "source": "Match-V5 · daño a campeones de los cinco participantes", "direction": "higher", "decimal": True, "defaults": [20, 25, 30, 35]},
    {"id": "lights_out", "name": "Luces apagadas", "icon": "eyeOff", "description": "Centinelas enemigos destruidos", "metric": "wards_killed", "unit": "centinelas destruidos", "source": "Match-V5 · wardsKilled", "direction": "higher", "decimal": False, "defaults": [3, 6, 9, 12]},
    {"id": "demolition_boss", "name": "Jefe de demoliciones", "icon": "hammer", "description": "Daño infligido a estructuras", "metric": "structure_damage", "unit": "de daño a estructuras", "source": "Match-V5 · damageDealtToBuildings; fallback damageDealtToTurrets", "direction": "higher", "decimal": False, "defaults": [3000, 6000, 10000, 15000]},
    {"id": "inhibitor_demolisher", "name": "Demoledor de inhibidores", "icon": "inhibitor", "description": "Inhibidores destruidos por el participante", "metric": "inhibitors", "unit": "inhibidores", "source": "Match-V5 Timeline · BUILDING_KILL con killerId atribuido", "direction": "higher", "decimal": False, "defaults": [1, 1, 2, 3]},
)

_BY_ID = {item["id"]: item for item in ACHIEVEMENT_REGISTRY}
_MEDAL_KEYS = ("bronze", "silver", "gold", "diamond")
_MEDAL_LABELS = ("Bronce", "Plata", "Oro", "Diamante")


def default_achievement_settings() -> dict[str, Any]:
    return {"show_unearned": False, "thresholds": {
        definition["id"]: dict(zip(_MEDAL_KEYS, definition["defaults"]))
        for definition in ACHIEVEMENT_REGISTRY
    }}


def public_achievement_registry(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    thresholds = (settings or default_achievement_settings()).get("thresholds", {})
    result = []
    for definition in ACHIEVEMENT_REGISTRY:
        item = {key: value for key, value in definition.items() if key not in {"defaults"}}
        item["thresholds"] = deepcopy(thresholds.get(definition["id"], dict(zip(_MEDAL_KEYS, definition["defaults"]))))
        result.append(item)
    return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _last_frame(frames: list[dict[str, Any]], participant_id: int, key: str) -> tuple[float | None, bool]:
    rows = [frame for frame in frames if isinstance(frame, dict) and frame.get("participantId") == participant_id]
    rows.sort(key=lambda frame: _number(frame.get("timestamp")) or -1)
    for frame in reversed(rows):
        value = _number(frame.get(key))
        if value is not None:
            return value, True
    return None, False


def _metrics(player: dict[str, Any], participants: list[dict[str, Any]], events: list[dict[str, Any]],
             frames: list[dict[str, Any]], duration_seconds: float, battle_score: dict[str, Any],
             timeline_available: bool) -> dict[str, tuple[float | None, str, bool]]:
    pid = player.get("participantId")
    declared_availability = player.get("achievementAvailability")
    def stat(key: str, metric: str | None = None) -> tuple[float | None, str, bool]:
        if isinstance(declared_availability, dict) and metric and declared_availability.get(metric) is False:
            return None, "unavailable", True
        value = _number(player.get(key))
        return value, "complete" if value is not None else "unavailable", True

    cs = None if isinstance(declared_availability, dict) and declared_availability.get("cs") is False else _number(player.get("cs"))
    if cs is None:
        lane_cs, lane_known = _last_frame(frames, pid, "minions")
        jungle_cs, jungle_known = _last_frame(frames, pid, "jungleMinions")
        if lane_known or jungle_known:
            cs = (lane_cs or 0.0) + (jungle_cs or 0.0)
    score_row = next((row for row in battle_score.get("participants", [])
                      if isinstance(row, dict) and row.get("participantId") == pid), {})
    useful_damage = _number(score_row.get("usefulDamageReceived"))
    useful_coverage = score_row.get("componentAvailability", {}).get("useful_damage", "unavailable")
    useful_state = useful_coverage if useful_coverage in {"complete", "partial"} else "unavailable"
    if useful_state == "unavailable":
        useful_damage = None
    steals = _number(player.get("objectivesStolen"))
    if steals is None:
        steals = _number(player.get("epicMonsterSteals"))
    if steals is None:
        explicit = [event for event in events if isinstance(event, dict) and event.get("type") == "ELITE_MONSTER_KILL"
                    and event.get("killerId") == pid and "STEAL" in str(event.get("monsterSubType") or "").upper()]
        if explicit:
            identities = {(event.get("timestamp"), event.get("monsterType"), event.get("monsterSubType"), event.get("killerId")) for event in explicit}
            steals = float(len(identities))
    duration = duration_seconds if duration_seconds > 0 else None
    jungle_cs, jungle_observed = _last_frame(frames, pid, "jungleMinions")
    epic_events = [event for event in events if isinstance(event, dict) and event.get("type") == "ELITE_MONSTER_KILL"]
    inhibitor_events = [event for event in events if isinstance(event, dict) and event.get("type") == "BUILDING_KILL"
                        and "INHIBITOR" in str(event.get("buildingType") or "").upper()]
    team = [item for item in participants if item.get("side") == player.get("side")]
    damage_values = [None if isinstance(item.get("achievementAvailability"), dict) and item["achievementAvailability"].get("champion_damage") is False else _number(item.get("championDamageDealt")) for item in team]
    share = None
    if team and all(value is not None for value in damage_values):
        total = sum(value or 0 for value in damage_values)
        if total > 0:
            share = ((_number(player.get("championDamageDealt")) or 0) / total) * 100
    structures = _number(player.get("damageToBuildings"))
    if structures is None:
        structures = _number(player.get("damageToTurrets"))
    champion_damage = stat("championDamageDealt", "champion_damage")[0]
    damage_coverage = "complete" if champion_damage is not None else "unavailable"
    return {
        "useful_damage_received": (useful_damage, useful_state, True),
        "healing": stat("totalHeal", "healing"), "gold": stat("gold", "gold"),
        "champion_damage": (champion_damage, damage_coverage, True),
        "kills": stat("kills", "kills"), "vision": stat("vision", "vision"),
        "objective_steals": (steals, "complete" if steals is not None else "unavailable", True),
        "kill_participations": (None if _number(player.get("kills")) is None or _number(player.get("assists")) is None else (_number(player.get("kills")) or 0) + (_number(player.get("assists")) or 0), "complete" if _number(player.get("kills")) is not None and _number(player.get("assists")) is not None else "unavailable", True),
        "jungle_minions": (jungle_cs, "complete" if jungle_observed else "unavailable", True),
        "revives": (None, "unavailable", True),
        "crowd_control": stat("timeCCingOthers", "crowd_control"),
        "cs_per_minute": (cs / (duration / 60) if cs is not None and duration else None, "complete" if cs is not None and duration else "unavailable", True),
        "wards_placed": stat("wardsPlaced", "wards_placed"),
        "winning_duration": (duration, "complete" if duration else "unavailable", player.get("win") is True),
        "epic_objectives": (float(sum(1 for event in epic_events if event.get("killerId") == pid)), "complete" if timeline_available else "unavailable", True),
        "team_damage_share": (share, "complete" if share is not None else "unavailable", True),
        "wards_killed": stat("wardsKilled", "wards_killed"),
        "structure_damage": (structures, "complete" if structures is not None else "unavailable", True),
        "inhibitors": (float(sum(1 for event in inhibitor_events if event.get("killerId") == pid)), "complete" if timeline_available else "unavailable", True),
    }


def _medal(value: float | None, thresholds: dict[str, float], direction: str, eligible: bool) -> str:
    if value is None:
        return "No disponible"
    if not eligible:
        return "Sin medalla"
    for key, label in reversed(tuple(zip(_MEDAL_KEYS, _MEDAL_LABELS))):
        threshold = thresholds[key]
        if value <= threshold if direction == "lower" else value >= threshold:
            return label
    return "Sin medalla"


def evaluate_match_achievements(participants: list[dict[str, Any]], events: list[dict[str, Any]],
                                frames: list[dict[str, Any]], duration_seconds: float,
                                battle_score: dict[str, Any], settings: dict[str, Any],
                                timeline_available: bool) -> dict[str, Any]:
    local = next((player for player in participants if player.get("local")), None)
    definitions = public_achievement_registry(settings)
    if not local:
        return {"showUnearned": bool(settings.get("show_unearned", False)), "items": []}
    metrics = _metrics(local, participants, events, frames, duration_seconds, battle_score, timeline_available)
    items = []
    for definition in definitions:
        value, coverage, eligible = metrics[definition["metric"]]
        tier = _medal(value, definition["thresholds"], definition["direction"], eligible)
        earned = tier in _MEDAL_LABELS
        if not settings.get("show_unearned", False) and not earned:
            continue
        items.append({**definition, "value": value, "coverage": coverage, "eligible": eligible,
                      "tier": tier, "earned": earned})
    return {"showUnearned": bool(settings.get("show_unearned", False)), "items": items}
