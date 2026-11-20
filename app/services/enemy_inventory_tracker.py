"""Shop-visit evidence from Live Client inventories, never a visibility/recall feed.

An unchanged API value is not a fresh sighting. The API has no documented
visibility bit: timestamps below refer to API observations only. No network,
wall clock, polling, or timeline events are owned by this component.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from typing import Any


def normalized_inventory(raw: Any) -> Counter[str] | None:
    if not isinstance(raw, list):
        return None
    result: Counter[str] = Counter()
    for row in raw:
        if not isinstance(row, dict):
            return None
        try:
            ident = float(row.get("itemID", row.get("itemId", row.get("id"))))
            count = float(row.get("count", 1))
        except (ValueError, TypeError):
            return None
        if not math.isfinite(ident) or not ident.is_integer() or ident < 0:
            return None
        if not math.isfinite(count) or not count.is_integer() or not 0 <= count <= 6:
            return None
        if ident and count:
            result[str(int(ident))] += int(count)
    return result


@dataclass
class EnemyInventoryState:
    inventory: Counter[str] | None = None
    first_observed: float | None = None
    last_observed: float | None = None
    last_change: float | None = None
    last_shop: float | None = None
    classification: str = "unavailable"
    needs_baseline: bool = False
    dead: bool = False
    paused_elapsed: int | None = None
    deaths: int | None = None


class EnemyInventoryTracker:
    # DDragon omits 'from' on several automatic transformations. Exceptions
    # are gated by catalog membership; ordinary paid upgrades remain purchases.
    AUTOMATIC_PAIRS = {"3040": {"3003"}, "3042": {"3004"}, "3121": {"3119"}}
    SUPPORT_STAGES = ({"3865"}, {"3866"}, {"3867"}, {"3869", "3870", "3871", "3876", "3877"})
    LEGACY_SUPPORT = ({"3850", "3854", "3858", "3862"}, {"3851", "3855", "3859", "3863"}, {"3853", "3857", "3860", "3864"})

    def __init__(self, catalog: dict[str, Any]) -> None:
        self.catalog = catalog
        self.reset("")

    def reset(self, session_id: str) -> None:
        self.session_id = session_id
        self.players: dict[str, EnemyInventoryState] = {}
        self.last_game_time: float | None = None

    def mark_gap(self) -> None:
        for state in self.players.values():
            state.needs_baseline = True

    def classify(self, before: Counter[str], after: Counter[str], champion: str) -> str:
        added, removed = after - before, before - after
        if not added and not removed:
            return "unchanged"
        if any(ident not in self.catalog for ident in before.keys() | after.keys()):
            return "unverified_change"
        paid, automatic, unknown = False, False, False
        for ident, count in added.items():
            item = self.catalog.get(ident)
            if not isinstance(item, dict):
                unknown = True
                continue
            tags, gold = item.get("tags", []), item.get("gold", {})
            if "Trinket" in tags or ident == "2422":
                # Slightly Magical Footwear cannot be purchased; rune data for
                # enemies is partial, so item identity is sufficient evidence.
                automatic = True
                continue
            sources = set(map(str, item.get("from", [])))
            auto_sources = self.AUTOMATIC_PAIRS.get(ident, set())
            support_sources: set[str] = set()
            for chain in (self.SUPPORT_STAGES, self.LEGACY_SUPPORT):
                for stage, ids in enumerate(chain):
                    if ident in ids and stage:
                        support_sources.update(set().union(*chain[:stage]))
            if support_sources and any(before[source] for source in support_sources):
                automatic = True
            elif auto_sources and any(removed[source] for source in auto_sources):
                automatic = True
            elif (gold.get("purchasable") is not True or item.get("inStore") is False
                  or gold.get("total", 0) <= 0):
                automatic = True
            elif sources and gold.get("base") == 0 and any(removed[source] for source in sources):
                automatic = True
            else:
                paid = True
        if unknown:
            return "unverified_change"
        if paid:
            return "field_crafting_unverified" if champion.casefold() == "ornn" else "purchase_inferred"
        if automatic:
            return "automatic_progression"
        # Removal alone can mean consumption, sale, expiry or transformation.
        # It cannot establish a visit to the shop.
        return "consumed_or_removed"

    def update(self, session_id: str, game_time: Any, enemies: list[tuple[str, dict[str, Any]]], *, fresh: bool = True) -> list[dict[str, Any]]:
        try:
            now = float(game_time)
        except (ValueError, TypeError):
            now = float("nan")
        if session_id != self.session_id:
            self.reset(session_id)
        valid_time = math.isfinite(now) and now >= 0
        if valid_time and self.last_game_time is not None and now < self.last_game_time:
            # Practice Tool rewind: all old timestamps lose their meaning.
            self.reset(session_id)
        advancing = valid_time and (self.last_game_time is None or now > self.last_game_time)
        result = []
        for key, player in enemies[:5]:
            state = self.players.setdefault(key, EnemyInventoryState())
            inventory = normalized_inventory(player.get("items"))
            dead_reading = player.get("isDead")
            reported_dead = dead_reading if isinstance(dead_reading, bool) else None
            scores = player.get("scores") if isinstance(player.get("scores"), dict) else {}
            death_count = scores.get("deaths")
            death_count = death_count if isinstance(death_count, int) and not isinstance(death_count, bool) and death_count >= 0 else None
            origin = state.last_shop if state.last_shop is not None else state.first_observed
            if fresh and advancing and reported_dead is True and not state.dead:
                state.paused_elapsed = max(0, int(now - origin)) if origin is not None else None
                state.dead = True
                state.needs_baseline = True
                state.classification = "dead"
            elif fresh and advancing and reported_dead is False and (state.dead or
                    (death_count is not None and state.deaths is not None and death_count > state.deaths)):
                # The first confirmed alive observation is the only defensible
                # respawn baseline after a missed or delayed playerlist read.
                state.dead = False
                state.paused_elapsed = None
                state.first_observed = now
                state.last_shop = None
                state.classification = "respawn_observed"
                state.needs_baseline = True
            elif fresh and advancing and reported_dead is False and state.inventory is None and death_count and death_count > 0:
                # The match was opened after an unobserved death/respawn.
                # The first live observation provides a safe baseline.
                state.classification = "first_observation"
            if fresh and advancing and death_count is not None:
                state.deaths = death_count
            if fresh and advancing and inventory is not None:
                if state.inventory is None or state.needs_baseline:
                    state.first_observed = now if state.first_observed is None else state.first_observed
                    if state.classification not in {"dead", "respawn_observed"}:
                        state.classification = "first_observation" if state.inventory is None else "gap_baseline"
                    state.needs_baseline = False
                else:
                    classification = self.classify(state.inventory, inventory, str(player.get("championName") or ""))
                    if classification != "unchanged" and not state.dead:
                        state.classification = classification
                        state.last_change = now
                    if classification == "purchase_inferred" and not state.dead:
                        state.last_shop = now
                state.inventory, state.last_observed = inventory, now
            elif inventory is None or not fresh:
                state.needs_baseline = True
            origin = state.last_shop if state.last_shop is not None else state.first_observed
            elapsed = state.paused_elapsed if state.dead else max(0, int(now - origin)) if valid_time and origin is not None else None
            from app.services.live_player_metrics_service import player_role
            result.append({
                "participantId": hashlib.sha256(f"{session_id}:{key}".encode()).hexdigest()[:16],
                "champion": str(player.get("championName") or ""), "role": player_role(player),
                "firstObservedAt": state.first_observed, "lastObservedAt": state.last_observed,
                "lastInventoryChangeAt": state.last_change, "lastInferredShopAt": state.last_shop,
                "elapsedSeconds": elapsed, "classification": state.classification,
                "origin": "inferred_purchase" if state.last_shop is not None else "respawn_observed" if state.classification == "respawn_observed" else "first_observation" if origin is not None else "unknown",
                "visibilityVerified": False, "observationSource": "live_client_inventory",
                "state": "dead" if state.dead else "unknown" if elapsed is None else "critical" if elapsed >= 240 else "warning" if elapsed >= 120 else "normal",
            })
        if valid_time and fresh:
            self.last_game_time = now
        return result
