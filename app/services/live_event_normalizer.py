"""Normalize Live Client events into renderer-safe actors and objectives."""
from __future__ import annotations

import re
import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


_OBJECTIVES = {
    "dragonkill": ("dragon", "Dragón eliminado"),
    "hordekill": ("void_grub", "Larva del Vacío eliminada"),
    "heraldkill": ("rift_herald", "Heraldo de la Grieta eliminado"),
    "baronkill": ("baron", "Barón Nashor eliminado"),
    "turretkilled": ("tower", "Torre destruida"),
    "inhibkilled": ("inhibitor", "Inhibidor destruido"),
    "inhibrespawned": ("inhibitor_respawned", "Inhibidor reaparecido"),
    "inhibrespawningsoon": ("inhibitor_respawning", "Inhibidor reaparecerá pronto"),
}


def classify_actor(raw_name: object, champion: str = "") -> tuple[str, str]:
    """Classify known Live Client unit names without treating them as champions."""
    value = str(raw_name or "").strip()
    folded = value.casefold()
    # Live Client unit IDs take precedence over a possible roster alias match.
    if "turret" in folded or "tower" in folded:
        return "tower", "torre"
    if folded.startswith("minion") or "minion_" in folded or "minion" in folded:
        return "minion", "súbditos"
    if "barracks" in folded or "inhibitor" in folded:
        return "inhibitor", "inhibidor"
    if "baron" in folded:
        return "baron", "Barón Nashor"
    if "herald" in folded:
        return "rift_herald", "Heraldo de la Grieta"
    if "dragon" in folded or "drake" in folded:
        return "dragon", "dragón"
    if folded.startswith("sru_"):
        return "neutral_monster", "monstruo neutral"
    if champion:
        return "champion", champion
    if not value:
        return "unknown", ""
    return "environment", "causa no identificada"


def normalize_event_time(value: object) -> float | None:
    """Keep Riot's in-game seconds and reject invalid source timestamps."""
    if value is None or isinstance(value, bool):
        logger.warning("Live Client event has no valid EventTime: %r", value)
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        logger.warning("Live Client event has invalid EventTime: %r", value)
        return None
    if not math.isfinite(result) or result < 0:
        logger.warning("Live Client event has out-of-range EventTime: %r", value)
        return None
    return result


def _structure_label(event: dict[str, Any], kind: str) -> str:
    raw = str(event.get("TurretKilled") or event.get("InhibKilled") or event.get("InhibRespawned")
              or event.get("InhibRespawningSoon") or event.get("BarracksKilled") or "")
    lane = ""
    if re.search(r"(?:_L_?1|_L1|_TOP|_TOPLANE)", raw, re.I):
        lane = "top"
    elif re.search(r"(?:_L_?2|_L2|_MID|_MIDDLE)", raw, re.I):
        lane = "medio"
    elif re.search(r"(?:_L_?3|_L3|_BOT|_BOTTOM)", raw, re.I):
        lane = "bot"
    if kind.startswith("inhibitor"):
        action = {"inhibitor": "destruido", "inhibitor_respawned": "reaparecido",
                  "inhibitor_respawning": "reaparecerá pronto"}.get(kind, "destruido")
        return f"Inhibidor de {lane} {action}" if lane else _OBJECTIVES.get(str(event.get("EventName", "")).casefold(), ("", "Inhibidor destruido"))[1]
    if lane:
        return f"Torre de {lane} destruida"
    return "Torre destruida"


def normalize_live_event(event: dict[str, Any], killer_champion: str = "", victim_champion: str = "") -> dict[str, Any]:
    """Return the original bounded event plus semantic actor/target fields."""
    result = dict(event)
    result["EventTime"] = normalize_event_time(event.get("EventTime"))
    name = str(event.get("EventName") or "")
    folded = name.casefold()
    killer_type, killer_label = classify_actor(event.get("KillerName"), killer_champion)
    victim_type, victim_label = classify_actor(event.get("VictimName"), victim_champion)
    if killer_type != "champion":
        killer_champion = ""
        for field in ("KillerChampion", "KillerTeam", "KillerLocal"):
            result.pop(field, None)
    result.update({"KillerActorType": killer_type, "KillerActorName": killer_label,
                   "VictimActorType": victim_type, "VictimActorName": victim_label})
    if victim_champion and victim_type == "champion":
        result["VictimChampion"] = victim_champion
    if killer_champion and killer_type == "champion":
        result["KillerChampion"] = killer_champion
    if folded in _OBJECTIVES:
        objective, label = _OBJECTIVES[folded]
        if objective in {"tower", "inhibitor", "inhibitor_respawned", "inhibitor_respawning"}:
            label = _structure_label(event, objective)
        target_type = "tower" if objective == "tower" else "inhibitor" if objective.startswith("inhibitor") else objective
        result.update({"ObjectiveKind": objective, "ObjectiveLabel": label,
                       "TargetActorType": target_type,
                       "TargetActorName": label.removesuffix(" eliminada").removesuffix(" eliminado")})
        if killer_champion:
            if objective in {"tower", "inhibitor"}:
                target = label.removesuffix(" destruida").removesuffix(" destruido").lower()
                article = "una" if objective == "tower" else "un"
                result["EventDescription"] = f"{killer_champion} destruyó {article} {target}"
            else:
                result["EventDescription"] = f"{killer_champion} consiguió {label[:1].lower()}{label[1:]}"
        elif killer_type == "minion" and objective in {"tower", "inhibitor"}:
            result["EventDescription"] = f"Los súbditos destruyeron {('una torre' if objective == 'tower' else 'un inhibidor')}"
        else:
            result["EventDescription"] = label
    elif folded == "championkill":
        cause = {"tower": "una torre", "minion": "súbditos", "neutral_monster": "un monstruo neutral"}.get(killer_type, killer_label)
        result["EventDescription"] = (f"{victim_champion} murió por una torre" if victim_champion and killer_type == "tower"
                                      else f"{killer_champion} eliminó a {victim_champion}" if killer_champion and victim_champion
                                      else f"{victim_champion} murió por {cause}" if victim_champion and killer_type != "unknown"
                                      else f"{victim_champion} murió por una causa no identificada" if victim_champion else "Eliminación")
    return result
