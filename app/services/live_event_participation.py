"""Clasificación pura de la participación en eventos de la partida LIVE."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TipoParticipacion = Literal["KILL", "DEATH", "ASSIST", "NONE"]


@dataclass(frozen=True)
class EventParticipation:
    """Resume qué jugador seleccionado participó en un evento canónico."""

    left: TipoParticipacion
    right: TipoParticipacion
    killer_id: str | None
    victim_id: str | None
    assist_ids: tuple[str, ...]
    timestamp: float
    shared: bool
    participation_complete: bool


def classify_event_participation(
    event: dict[str, Any], left_player_id: str | None, right_player_id: str | None
) -> EventParticipation:
    """Clasifica participación directa sin inferirla por equipo o nombres."""
    event_type = str(event.get("type", ""))
    killer_id = _identifier(event.get("killer_key"))
    victim_id = _identifier(event.get("victim_key"))
    player_id = _identifier(event.get("player_key"))
    if event_type == "kill_exact" and not killer_id:
        killer_id = player_id
    if event_type == "death_exact" and not victim_id:
        victim_id = player_id
    assists_raw = event.get("assister_keys")
    assists = (
        tuple(
            dict.fromkeys(
                _identifier(value) for value in assists_raw or [] if _identifier(value)
            )
        )
        if isinstance(assists_raw, (list, tuple, set))
        else ()
    )
    timestamp = _number(event.get("time", 0))
    complete = bool(event.get("assist_data_complete", assists_raw is not None))

    is_global = (
        event_type == "objective"
        or event.get("scope") == "global"
        or event.get("global") is True
    )
    if is_global:
        left = right = "NONE"
    elif event_type in {"kill_exact", "champion_kill", "assist_exact"}:
        left = _kill_role(left_player_id, killer_id, victim_id, assists)
        right = _kill_role(right_player_id, killer_id, victim_id, assists)
        if event_type == "assist_exact" and player_id:
            if player_id == left_player_id and left == "NONE":
                left = "ASSIST"
            if player_id == right_player_id and right == "NONE":
                right = "ASSIST"
    elif event_type == "death_exact":
        if killer_id or assists:
            left = _kill_role(left_player_id, killer_id, victim_id, assists)
            right = _kill_role(right_player_id, killer_id, victim_id, assists)
        else:
            left = "DEATH" if victim_id and victim_id == left_player_id else "NONE"
            right = "DEATH" if victim_id and victim_id == right_player_id else "NONE"
    else:
        left = right = "NONE"

    shared = left != "NONE" and right != "NONE"
    return EventParticipation(
        left=left,
        right=right,
        killer_id=killer_id,
        victim_id=victim_id,
        assist_ids=assists,
        timestamp=timestamp,
        shared=shared,
        participation_complete=complete,
    )


def filter_participating_events(
    events: list[dict[str, Any]],
    mode: str,
    left_player_id: str | None,
    right_player_id: str | None,
) -> list[dict[str, Any]]:
    """Filtra eventos por participante directo u objetivo global y deduplica."""
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        event_type = str(event.get("type", ""))
        is_global = (
            event_type == "objective"
            or event.get("scope") == "global"
            or event.get("global") is True
        )
        participation = classify_event_participation(
            event, left_player_id, right_player_id
        )
        is_player_event = participation.left != "NONE" or participation.right != "NONE"
        if not is_global and event_type not in {
            "kill_exact",
            "death_exact",
            "champion_kill",
            "assist_exact",
        }:
            is_player_event = event.get("player_key") in {
                left_player_id,
                right_player_id,
            }
        if mode == "lane" and not is_player_event:
            continue
        if mode == "global" and not is_global:
            continue
        if mode == "all" and not (is_player_event or is_global):
            continue
        identity = _event_identity(event, participation)
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(event)
    selected.sort(
        key=lambda value: (
            _number(value.get("time", 0)),
            int(value.get("order", 0) or 0),
        )
    )
    return selected


def _kill_role(
    player_id: str | None,
    killer_id: str | None,
    victim_id: str | None,
    assist_ids: tuple[str, ...],
) -> TipoParticipacion:
    """Devuelve el papel de un participante comparado en una baja."""
    if not player_id:
        return "NONE"
    if player_id == killer_id:
        return "KILL"
    if player_id == victim_id:
        return "DEATH"
    return "ASSIST" if player_id in assist_ids else "NONE"


def _event_identity(event: dict[str, Any], participation: EventParticipation) -> str:
    """Crea una identidad estable para deduplicar perspectivas del mismo evento."""
    native_id = event.get("event_id") or event.get("native_event_id")
    if native_id is not None:
        return f"native:{native_id}"
    if participation.killer_id or participation.victim_id:
        return (
            f"kill:{participation.killer_id}:{participation.victim_id}:"
            f"{participation.timestamp:.3f}"
        )
    return str(event.get("order", event.get("time", ""))) + str(event.get("type", ""))


def _identifier(value: Any) -> str | None:
    """Normaliza un identificador sin resolver nombres de presentación."""
    if value is None or isinstance(value, bool):
        return None
    normalized = str(value).strip()
    return normalized or None


def _number(value: Any) -> float:
    """Convierte timestamps numéricos y degrada valores ausentes a cero."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
