"""Live presentation of the established recommendation and Local Analysis data.

Ranking stays in LiveRecommendationService/SynergyRecommendationService. Rune
context selects an evidenced Local Analysis build; it never invents rune scores.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.live_recommendation_service import LiveRecommendationService, item_ids, number
from app.services.repositorio_campeones import RepositorioCampeones
from app.services.live_player_metrics_service import normalize_analysis_role


def rune_ids(runes: Any) -> tuple[str, ...]:
    if not isinstance(runes, dict):
        return ()
    general = runes.get("generalRunes")
    entries = list(general) if isinstance(general, list) else []
    if isinstance(runes.get("keystone"), dict):
        entries.append(runes["keystone"])
    return tuple(sorted({str(row.get("id", row.get("perkId", ""))) for row in entries if isinstance(row, dict)} - {""}))


class LivePreparationService:
    def __init__(self, catalog: dict[str, Any], *, engine=None, repository=None) -> None:
        self.engine = engine or LiveRecommendationService(catalog)
        self.repository = repository or RepositorioCampeones()

    def context(self, session: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        players, _ = self.engine.latest(session)
        local = players.get(session.get("local_player_key"), {})
        champion = str(local.get("champion_name") or session.get("champion_name") or "")
        role = normalize_analysis_role(local.get("role")) or normalize_analysis_role(local.get("position"))
        profile = deepcopy(self.engine.profile(champion))
        skill: dict[str, Any] = {"status": "unavailable", "order": [], "priority": "", "source": "local_analysis", "role": role}
        if not champion:
            return profile, skill
        if role is None:
            document = self.repository.obtener_campeon(str(profile.get("character") or champion))
            saved = (document.datos or {}).get("ranks", {}).get("emerald_plus", {})
            if isinstance(saved, dict):
                candidates = [lane for lane in ("top", "jungle", "mid", "adc", "support")
                              if isinstance(saved.get(lane), dict) and saved[lane].get("skill_order")]
                lane_stats = saved.get("__lane_stats__", {}).get("lanes", {})
                if candidates:
                    role = max(candidates, key=lambda lane: (number((lane_stats.get(lane) or {}).get("games")), -candidates.index(lane)))
                    skill.update(role=role, roleFallback=True)
        if role is None:
            return profile, skill
        query = self.repository.consultar(str(profile.get("character") or champion), role, "emerald_plus")
        variant = query.datos if isinstance(query.datos, dict) else {}
        if not (variant.get("skill_order") or any(isinstance(page, dict) and page.get("skill_order") for page in variant.get("runes", []) if isinstance(variant.get("runes"), list))):
            document = self.repository.obtener_campeon(str(profile.get("character") or champion))
            saved = (document.datos or {}).get("ranks", {}).get("emerald_plus", {})
            if isinstance(saved, dict):
                alternatives = [lane for lane in ("top", "jungle", "mid", "adc", "support")
                                if lane != role and isinstance(saved.get(lane), dict) and saved[lane].get("skill_order")]
                if alternatives:
                    stats = saved.get("__lane_stats__", {}).get("lanes", {})
                    role = max(alternatives, key=lambda lane: (number((stats.get(lane) or {}).get("games")), -alternatives.index(lane)))
                    skill.update(role=role, roleFallback=True)
                    query = self.repository.consultar(str(profile.get("character") or champion), role, "emerald_plus")
                    variant = query.datos if isinstance(query.datos, dict) else {}
        if not variant:
            return profile, skill
        profile = {**profile, **deepcopy(variant)}
        selected_ids = set(rune_ids(local.get("runes")))
        pages = variant.get("runes", [])
        pages = [page for page in pages if isinstance(page, dict)] if isinstance(pages, list) else []
        matching = [page for page in pages if str(page.get("keystone_id") or "") in selected_ids]
        def page_match(page):
            ids = {str(ident) for field in ("slot_ids", "secondary_slot_ids")
                   for ident in (page.get(field) if isinstance(page.get(field), list) else [])}
            return len(selected_ids & ids), number(page.get("games"))

        page = max(matching, key=page_match, default={})
        if page:
            # Reuse the existing engine's build-affinity bonuses for the page
            # matching the equipped keystone, preserving measured provenance.
            build = page.get("build") or page.get("power_spike_items")
            if isinstance(build, list) and build:
                profile["most_played_build"] = build
                profile["full_build"] = build
                profile["items"] = build
                profile["power_curve_and_scaling"] = {**(profile.get("power_curve_and_scaling") or {}), "power_spike_items": build}
        raw = page.get("skill_order") or variant.get("skill_order")
        sequence = raw.get("order") if isinstance(raw, dict) else raw
        if isinstance(sequence, list) and sequence and len(sequence) <= 18 and all(str(value).upper() in {"Q", "W", "E", "R", "-"} for value in sequence):
            skill.update(status="available", order=[str(value).upper() for value in sequence], priority=str(raw.get("priority") or "") if isinstance(raw, dict) else "", runeMatched=bool(page), patch=variant.get("source_patch"))
        return profile, skill

    def rank(self, session: dict[str, Any]) -> dict[str, Any]:
        profile, skill = self.context(session)
        if str(session.get("game_mode") or "").upper() not in {"CLASSIC", "PRACTICETOOL", "ARAM"}:
            return {"recommendations": [], "skillOrder": skill}
        result = self.engine.analyze(session, profile_override=profile, recommendation_limit=None)
        rows = [row for row in result.get("recommendations", []) if self.engine.catalog.get(row.get("id"), {}).get("name")]
        # Keep the engine's ranked alternatives so a purchase can be replaced
        # from the same scoring result while the next inventory-aware rank runs.
        return {"recommendations": [{key: row.get(key) for key in ("id", "name", "score", "synergy_score", "cost", "reasons", "responses")} for row in rows], "skillOrder": skill}

    def purchases(self, rows: list[dict[str, Any]], local: dict[str, Any], gold: Any, game_mode: str) -> list[dict[str, Any]]:
        owned = item_ids(local.get("items", []))
        available_gold = number(gold, None)
        if available_gold is not None:
            available_gold = max(0, available_gold)
        result = []
        for row in rows:
            # Hide old alternatives immediately when the inventory changes,
            # while the single ranking worker computes the replacement set.
            if not self.engine.compatible(row["id"], owned):
                continue
            buy = self.engine.purchase(row["id"], owned, available_gold, "12" if game_mode == "ARAM" else "11", occupied_slots=self.engine.inventory_slots(local.get("items", [])))
            next_purchase = {**buy, **({"name": self.engine.name(buy["id"])} if buy.get("id") else {})}
            result.append({**row, "nextPurchase": next_purchase})
            if len(result) == 3:
                break
        return result
