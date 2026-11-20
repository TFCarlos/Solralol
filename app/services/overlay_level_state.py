"""Resolve a legal next skill from observed Live Client ability ranks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.identidad_campeon import normalizar_identidad_campeon

SLOTS = ("Q", "W", "E", "R")
# These transform champions receive their form switch without spending a point.
AUTO_ULTIMATE = frozenset({"elise", "nidalee", "jayce", "karma"})


def ability_ranks(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    ranks: dict[str, int] = {}
    for slot in SLOTS:
        entry = value.get(slot)
        rank = entry.get("abilityLevel") if isinstance(entry, dict) else None
        if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= 6:
            return None
        ranks[slot] = rank
    return ranks


def _legal(slot: str, ranks: dict[str, int], level: int, champion: str) -> bool:
    next_rank = ranks[slot] + 1
    if slot == "R" and champion in AUTO_ULTIMATE:
        return False
    maximum = 6 if champion == "udyr" else (3 if slot == "R" else 5)
    if next_rank > maximum:
        return False
    if slot == "R" and champion != "udyr":
        return level >= (6, 11, 16)[next_rank - 1]
    return level >= 2 * next_rank - 1


def next_ability(order: Any, ranks: dict[str, int], level: int, champion: Any = "") -> str | None:
    sequence = order.get("order") if isinstance(order, dict) else order
    if isinstance(order, dict) and order.get("status", "available") != "available":
        return None
    if not isinstance(sequence, list) or not sequence or len(sequence) > 18:
        return None
    canonical = normalizar_identidad_campeon(champion)
    normalized = [str(value).upper() for value in sequence]
    if any(value not in {*SLOTS, "-"} for value in normalized):
        return None
    desired = {slot: 0 for slot in SLOTS}
    for slot in normalized:
        if slot == "-" or (slot == "R" and canonical in AUTO_ULTIMATE):
            continue
        desired[slot] += 1
        if ranks[slot] < desired[slot] and _legal(slot, ranks, level, canonical):
            return slot
    return None


@dataclass
class PendingAbility:
    level: int | None = None
    allocated: int | None = None
    pending_level: int | None = None

    def reset(self) -> None:
        self.level = self.allocated = self.pending_level = None

    def update(self, level: Any, abilities: Any, order: Any, champion: Any = "") -> str | None:
        ranks = ability_ranks(abilities)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 18 or ranks is None:
            return None
        canonical = normalizar_identidad_campeon(champion)
        allocated = sum(rank for slot, rank in ranks.items() if slot != "R" or canonical not in AUTO_ULTIMATE)
        if allocated > level:
            return None
        self.level, self.allocated = level, allocated
        self.pending_level = level if allocated < level else None
        return next_ability(order, ranks, level, champion) if allocated < level else None
