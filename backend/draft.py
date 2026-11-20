"""Electron adapter for the original Draft analyzer and LCU workflow."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from _paths import DATA_DIR
from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.lcu_service import LCUService
from app.services.repositorio_campeones import RepositorioCampeones
from app.services.identidad_campeon import IndiceIdentidadCampeon
from backend.assets import resolve_meta_assets

_LOGGER = logging.getLogger(__name__)

ROLES = {"top": "Top", "jungle": "Jungle", "mid": "Mid", "adc": "Bot", "support": "Support"}
ROLE_ALIASES = {"top": "top", "jungle": "jungle", "jgl": "jungle", "mid": "mid", "middle": "mid", "adc": "adc", "bot": "adc", "bottom": "adc", "support": "support", "utility": "support"}


class DraftRuntime:
    """Reuses the established Python analysis, repository, and LCU services."""

    def __init__(self, champion_catalog: list[dict[str, Any]], lcu_service: LCUService | None = None) -> None:
        self.catalog = champion_catalog
        self.identities = IndiceIdentidadCampeon({str(row.get("id") or index): row for index, row in enumerate(champion_catalog)})
        self.by_id = {int(row["key"]): row["id"] for row in champion_catalog if str(row.get("key", "")).isdigit()}
        self.analyzer = DraftAnalyzerService()
        self.repository = RepositorioCampeones()
        self.lcu = lcu_service or LCUService()
        self._item_catalog = self._load_items()
        self._analysis_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
        self._asset_cache: dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], dict[str, str | None]] = {}

    @staticmethod
    def _load_items() -> dict[str, Any]:
        try:
            value = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
            return value.get("items", {})
        except (OSError, ValueError, AttributeError):
            return {}

    @staticmethod
    def _role(raw: Any) -> str | None:
        return ROLE_ALIASES.get(str(raw or "").strip().casefold())

    def _canonical(self, name: str) -> str | None:
        return self.identities.resolve(name)

    def _team(self, rows: list[Any], allied: bool, locked_cells: set[str] | None = None) -> list[dict[str, Any]]:
        rows = rows if isinstance(rows, list) else []
        locked_cells = locked_cells or set()
        result = []
        for index, source in enumerate(rows[:5]):
            entry = source if isinstance(source, dict) else {}
            champion_id = entry.get("championId") or entry.get("champion_id") or 0
            try:
                champ = self.by_id.get(int(champion_id)) if int(champion_id) else None
            except (TypeError, ValueError):
                champ = None
            raw_role = entry.get("assignedPosition") or entry.get("position") or entry.get("role")
            role = self._role(raw_role)
            cell = entry.get("cellId", index)
            locked = str(cell) in locked_cells
            is_local = bool(entry.get("localPlayerCellId") == cell or entry.get("isLocalPlayer"))
            result.append({
                "champion": champ, "role": role, "roleKnown": role is not None,
                "player": str(entry.get("summonerName") or entry.get("riotId") or "")[:64],
                "cellId": cell, "local": is_local,
                "locked": locked,
                "intent": self.by_id.get(int(entry.get("championPickIntent") or 0)) if str(entry.get("championPickIntent") or "0").isdigit() else None,
                "state": "locked" if locked else "hover" if entry.get("championId") or entry.get("championPickIntent") else "empty",
                "allied": allied,
            })
        while len(result) < 5:
            index = len(result)
            result.append({"champion": None, "role": list(ROLES)[index], "roleKnown": True, "player": "", "cellId": index, "local": False, "locked": False, "intent": None, "state": "empty", "allied": allied})
        return result

    def snapshot(self, params: dict[str, Any], lcu_state: dict[str, Any] | None = None) -> dict[str, Any]:
        requested_champion = str(params.get("champion", "Ahri"))
        champion = self._canonical(requested_champion)
        if champion is None:
            raise ValueError("Identidad de campeón no reconocida en el catálogo activo.")
        role = str(params.get("role", "mid"))
        role = role if role in ROLES else "mid"
        manual_ally = params.get("allies", []) if isinstance(params.get("allies"), list) else []
        manual_enemy = params.get("enemies", []) if isinstance(params.get("enemies"), list) else []
        allies = [{"champion": self._canonical(str(v.get("champion") or "")) if isinstance(v, dict) else None,
                   "role": self._role(v.get("role")) if isinstance(v, dict) else None,
                   "roleKnown": bool(isinstance(v, dict) and self._role(v.get("role"))),
                   "player": "", "cellId": i, "local": i == 0, "locked": bool(v.get("locked")) if isinstance(v, dict) else False, "intent": None,
                   "state": "picked" if isinstance(v, dict) and self._canonical(str(v.get("champion") or "")) else "empty", "allied": True}
                  for i, v in enumerate(manual_ally[:5])]
        enemies = [{"champion": self._canonical(str(v.get("champion") or "")) if isinstance(v, dict) else None,
                    "role": self._role(v.get("role")) if isinstance(v, dict) else None,
                    "roleKnown": bool(isinstance(v, dict) and self._role(v.get("role"))),
                    "player": "", "cellId": i, "local": False, "locked": bool(v.get("locked")) if isinstance(v, dict) else False, "intent": None,
                    "state": "picked" if isinstance(v, dict) and self._canonical(str(v.get("champion") or "")) else "empty", "allied": False}
                   for i, v in enumerate(manual_enemy[:5])]
        while len(allies) < 5:
            i = len(allies); allies.append({"champion": None, "role": list(ROLES)[i], "roleKnown": True, "player": "", "cellId": i, "local": i == 0, "locked": False, "intent": None, "state": "empty", "allied": True})
        while len(enemies) < 5:
            i = len(enemies); enemies.append({"champion": None, "role": None, "roleKnown": False, "player": "", "cellId": i, "local": False, "locked": False, "intent": None, "state": "empty", "allied": False})
        connected = bool(lcu_state.get("connected")) if isinstance(lcu_state, dict) else self.lcu.is_connected()
        phase = "Disconnected" if not connected else "Lobby"
        live = False
        raw_manual_bans = params.get("manualBans", {}) if isinstance(params.get("manualBans"), dict) else {}
        bans: dict[str, list[str]] = {
            side: [canonical for value in raw_manual_bans.get(side, [])[:5]
                   if isinstance(value, str) and (canonical := self._canonical(value))]
            for side in ("allies", "enemies")
        }
        if connected and isinstance(lcu_state, dict):
            phase = str(lcu_state.get("phase") or "Unknown")
            session = lcu_state.get("session") if isinstance(lcu_state.get("session"), dict) else None
            if session:
                live = True
                phase = "ChampSelect"
                my_team = session.get("myTeam") if isinstance(session.get("myTeam"), list) else []
                their_team = session.get("theirTeam") if isinstance(session.get("theirTeam"), list) else []
                action_groups = session.get("actions") if isinstance(session.get("actions"), list) else []
                pick_actions = {str(action.get("actorCellId")) for group in action_groups if isinstance(group, list)
                                for action in group if isinstance(action, dict) and action.get("type") == "pick"
                                and action.get("completed") is True and action.get("championId")}
                allies = self._team(my_team, True, pick_actions)
                enemies = self._team(their_team, False, pick_actions)
                local_cell = session.get("localPlayerCellId")
                for player in allies:
                    player["local"] = local_cell is not None and str(player.get("cellId")) == str(local_cell)
                for action_group in action_groups:
                    for action in action_group if isinstance(action_group, list) else []:
                        if not isinstance(action, dict) or action.get("type") != "ban" or not action.get("championId"):
                            continue
                        cid = self.by_id.get(int(action.get("championId") or 0))
                        ally_ban = action.get("isAllyAction")
                        if ally_ban is None:
                            ally_ban = action.get("actorCellId") in {p.get("cellId") for p in my_team if isinstance(p, dict)}
                        if cid: bans["allies" if ally_ban else "enemies"].append(cid)
                for team in (allies, enemies):
                    unknown = [player for player in team if player["champion"] and not player["role"]]
                    inferred = self.analyzer.assign_likely_roles([player["champion"] for player in unknown])
                    for player, proposed in zip(unknown, inferred):
                        player["role"] = self._role(proposed)
                        player["roleKnown"] = False
            elif phase.casefold() == "champselect":
                phase = "SessionUnavailable"
        elif connected:
            try:
                response = self.lcu.session.get(f"https://127.0.0.1:{self.lcu.port}/lol-gameflow/v1/gameflow-phase", timeout=1.5)
                if response.status_code == 200:
                    phase = str(response.json())
            except Exception:
                pass
            session = self.lcu.get_champ_select_session()
            if isinstance(session, dict):
                live = True
                phase = "ChampSelect"
                my_team = session.get("myTeam") if isinstance(session.get("myTeam"), list) else []
                their_team = session.get("theirTeam") if isinstance(session.get("theirTeam"), list) else []
                action_groups = session.get("actions") if isinstance(session.get("actions"), list) else []
                pick_actions = {
                    str(action.get("actorCellId"))
                    for group in action_groups if isinstance(group, list)
                    for action in group
                    if isinstance(action, dict) and action.get("type") == "pick"
                    and action.get("completed") is True and action.get("championId")
                }
                allies = self._team(my_team, True, pick_actions)
                enemies = self._team(their_team, False, pick_actions)
                # Riot's localPlayerCellId is already the champion-select cell
                # id. summonerId is a separate identity and must not be used
                # to resolve the local player.
                local_cell = session.get("localPlayerCellId")
                for action_group in action_groups:
                    for action in action_group if isinstance(action_group, list) else []:
                        if not isinstance(action, dict) or action.get("type") != "ban" or not action.get("championId"):
                            continue
                        cid = self.by_id.get(int(action.get("championId") or 0))
                        ally_ban = action.get("isAllyAction")
                        if ally_ban is None:
                            ally_ban = action.get("actorCellId") in {p.get("cellId") for p in my_team if isinstance(p, dict)}
                        key = "allies" if ally_ban else "enemies"
                        if cid: bans[key].append(cid)
                # Infer only likely role hints; roleKnown remains false for inferred enemies.
                for team in (allies, enemies):
                    unknown = [p for p in team if p["champion"] and not p["role"]]
                    inferred = self.analyzer.assign_likely_roles([p["champion"] for p in unknown])
                    for player, proposed in zip(unknown, inferred):
                        player["role"] = self._role(proposed)
                        player["roleKnown"] = False
                for player in allies:
                    player["local"] = local_cell is not None and str(player.get("cellId")) == str(local_cell)
            elif phase.casefold() == "champselect":
                # The gameflow endpoint may briefly lag after the selection session 404s.
                phase = "SessionUnavailable"
        ally_names = [p["champion"] for p in allies if p.get("champion")]
        enemy_names = [p["champion"] for p in enemies if p.get("champion")]
        for player in allies + enemies:
            player["winRate"] = self._champion_win_rate(player.get("champion"))
        local_player = next((p for p in allies if p.get("local")), None)
        # In a live LCU session, only prepare for the champion selected by the
        # local cell. A renderer's manual default (usually Ahri) must never
        # leak into the live player's build while intent/lock data is absent.
        local_champion = ((local_player or {}).get("champion") if (local_player or {}).get("locked") else None) if live else champion
        if live and not local_champion:
            local_champion = (local_player or {}).get("intent") or (local_player or {}).get("champion")
        local_role_known = bool((local_player or {}).get("roleKnown")) if live else True
        local_role = (((local_player or {}).get("role") if local_role_known else None) or role) if live else role
        build_enemies = [p["champion"] for p in enemies if p.get("champion")]
        analysis = self._analysis(local_champion, local_role, build_enemies, allies, enemies) if local_champion else self._empty_analysis(local_role)
        asset_champs = list(dict.fromkeys(ally_names + [str(p["intent"]) for p in allies if p.get("intent")] + enemy_names + bans.get("allies", []) + bans.get("enemies", []) + ([local_champion] if local_champion else []) + [str(x["champion"]) for x in analysis.get("bans", []) if x.get("champion")]))[:20]
        all_builds = analysis.get("builds") or [analysis.get("build", {})]
        asset_items = list(dict.fromkeys([x["id"] for build in all_builds for x in build.get("items", [])] + [build["boots"]["id"] for build in all_builds if build.get("boots")] + [i["id"] for g in analysis.get("situational", []) for i in g.get("items", [])]))[:20]
        rune_names = tuple(str(name) for page in analysis.get("runes", []) for name in ([page.get("keystone"), *page.get("slots", []), *page.get("secondary_slots", []), *page.get("shards", [])]) if name)
        spell_names = tuple(str(name) for name in analysis.get("spells", []))
        asset_key = (tuple(asset_champs), tuple(asset_items), rune_names + spell_names)
        assets = self._asset_cache.get(asset_key)
        if assets is None:
            try:
                assets = resolve_meta_assets(asset_champs, asset_items, [], self.catalog)
                self._rune_assets(analysis.get("runes", []), analysis.get("spells", []), assets)
                if len(self._asset_cache) >= 64:
                    self._asset_cache.pop(next(iter(self._asset_cache)))
                self._asset_cache[asset_key] = assets
            except Exception:
                _LOGGER.exception("No se pudieron resolver todos los recursos de Draft champion=%s", local_champion)
                assets = {}
        return {"connection": "connected" if connected else "disconnected", "phase": phase, "live": live,
                "allies": allies, "enemies": enemies, "bans": bans, "localChampion": local_champion or "",
                "localRole": local_role, "localRoleKnown": local_role_known, "analysis": analysis, "assets": assets,
                "rank": "emerald_plus"}

    @staticmethod
    def _empty_analysis(role: str) -> dict[str, Any]:
        return {"champion": "", "role": role, "roleLabel": ROLES.get(role, role),
                "profileAvailable": False, "variantStatus": "NO_CHAMPION_SELECTED", "runes": [],
                "spells": [], "build": {"items": [], "boots": None, "situational": []},
                "builds": [], "situational": [], "bans": [], "damage": {}, "powerCurve": {},
                "matchups": [], "warnings": ["Selecciona un campeón para cargar la preparación."] ,
                "composition": {"allies": 0, "enemies": 0, "damageSamples": 0,
                                "teams": {"allies": {"damage": None, "damageSamples": 0, "selected": 0, "powerCurve": {}, "powerCurveSamples": {}},
                                          "enemies": {"damage": None, "damageSamples": 0, "selected": 0, "powerCurve": {}, "powerCurveSamples": {}}}}}

    @staticmethod
    def _has_complete_damage_profile(profile: Any) -> bool:
        if not isinstance(profile, dict):
            return False
        breakdown = profile.get("damage_breakdown")
        detailed = isinstance(breakdown, dict) and any(
            key in breakdown for key in (
                "physical_damage_percent", "magic_damage_percent", "true_damage_percent"
            )
        )
        raw_profile = profile.get("damage_profile")
        if not detailed and isinstance(raw_profile, dict) and raw_profile:
            breakdown = raw_profile
            detailed = True
            suffix = ""
        else:
            suffix = "_percent"
        if detailed:
            values = []
            for key in ("physical_damage", "magic_damage", "true_damage"):
                try:
                    value = float(breakdown.get(f"{key}{suffix}"))
                except (TypeError, ValueError, OverflowError):
                    return False
                if not 0 <= value <= 100:
                    return False
                values.append(value)
            return sum(values) > 0
        info = profile.get("basic_info")
        damage_type = str(info.get("damage_type", "")).strip().casefold() if isinstance(info, dict) else ""
        return damage_type in {"ad", "ap", "physical", "magic", "magical", "true", "true damage"}

    def _team_composition(self, champions: list[str], roles: dict[str, str] | None = None) -> dict[str, Any]:
        roles = roles or {}
        damage_champions = [
            name for name in champions
            if self._has_complete_damage_profile(
                self.analyzer.get_champion_profile(name, roles[name]) if roles.get(name)
                else self.analyzer.get_champion_profile(name)
            )
        ]
        try:
            damage = (self.analyzer.calculate_team_damage_breakdown(damage_champions, roles) if roles
                      else self.analyzer.calculate_team_damage_breakdown(damage_champions)) if damage_champions else None
        except Exception:
            _LOGGER.exception("No se pudo estimar daño para la composición champions=%s", champions)
            damage = None
        try:
            curve_data = self.analyzer.calculate_team_power_curve_with_samples(champions)
        except Exception:
            _LOGGER.exception("No se pudo calcular la curva por duración champions=%s", champions)
            curve_data = {"values": {}, "samples": {}}
        return {
            "damage": damage,
            "damageSamples": len(damage_champions),
            "selected": len(champions),
            "powerCurve": curve_data.get("values", {}),
            "powerCurveSamples": curve_data.get("samples", {}),
        }

    def _analysis(self, champion: str, role: str, enemies: list[str], allies: list[dict[str, Any]], opposing: list[dict[str, Any]]) -> dict[str, Any]:
        cache_key = (champion, role, tuple((p.get("champion"), p.get("role"), p.get("roleKnown")) for p in allies), tuple((p.get("champion"), p.get("role"), p.get("roleKnown")) for p in opposing))
        cached = self._analysis_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 15:
            return cached[1]
        role_key = {"Top": "top", "Jungle": "jungle", "Mid": "mid", "Bot": "adc", "Support": "support"}.get(role, role)
        profile = self.analyzer.get_champion_profile(champion) or {}
        result = self.repository.consultar(champion, role_key, "emerald_plus")
        variant = result.datos if result.estado.value == "AVAILABLE" and isinstance(result.datos, dict) else {}
        pages = [p for p in variant.get("runes", []) if isinstance(p, dict)][:2]
        warnings: list[str] = []
        try:
            base_build = self.analyzer.get_champion_build(champion, enemies, role_key)
        except Exception:
            _LOGGER.exception("No se pudo calcular la build Draft champion=%s role=%s", champion, role_key)
            base_build = {"items": [], "boots": None, "situational": []}
            warnings.append("No se pudo preparar la build local.")
        try:
            builds = [self._build_for_page(champion, page, enemies, role_key, base_build) for page in pages] or [base_build]
        except Exception:
            _LOGGER.exception("No se pudo asociar la build a la variante de runas champion=%s role=%s", champion, role_key)
            builds = [base_build]
            warnings.append("La build asociada a runas no está disponible; se muestra la build local general.")
        role_matchups = []
        try:
            for enemy in opposing:
                if not enemy.get("champion") or not enemy.get("roleKnown") or not enemy.get("role"):
                    continue
                for ally in allies:
                    if ally.get("local") and ally.get("role") == enemy.get("role"):
                        src = self.analyzer.get_champion_profile(ally.get("champion") or champion) or {}
                        groups = (src.get("matchups") or {})
                        for group in ("counters", "good_against"):
                            for entry in groups.get(group, []) if isinstance(groups.get(group), list) else []:
                                if isinstance(entry, dict) and self._canonical(str(entry.get("champion", ""))) == enemy["champion"]:
                                    role_matchups.append({"champion": enemy["champion"], "role": enemy["role"], "kind": group, "winRate": entry.get("win_rate"), "games": entry.get("lane_games") or entry.get("overall_games"), "tip": entry.get("tip")})
        except Exception:
            _LOGGER.exception("No se pudieron resolver matchups Draft champion=%s", champion)
            warnings.append("No se pudieron cargar algunos emparejamientos.")
        curve_names = [p["champion"] for p in allies if p.get("champion")]
        enemy_names = [p["champion"] for p in opposing if p.get("champion")]
        try:
            team_compositions = {
                "allies": self._team_composition(curve_names, {p["champion"]: p.get("role") or "" for p in allies if p.get("champion")}),
                "enemies": self._team_composition(enemy_names, {p["champion"]: p.get("role") or "" for p in opposing if p.get("champion")}),
            }
        except Exception:
            _LOGGER.exception("No se pudo calcular la curva de composición Draft champion=%s", champion)
            team_compositions = {
                side: {"damage": None, "damageSamples": 0, "selected": len(names), "powerCurve": {}, "powerCurveSamples": {}}
                for side, names in (("allies", curve_names), ("enemies", enemy_names))
            }
            warnings.append("No se pudo calcular la comparación de composición local.")
        try:
            bans = self.analyzer.get_recommended_bans(champion, 3)
        except Exception:
            _LOGGER.exception("No se pudieron calcular counters Draft champion=%s", champion)
            bans = []
            warnings.append("No se pudieron cargar los baneos recomendados.")
        result = {"champion": champion, "role": role_key, "roleLabel": ROLES.get(role_key, role), "profileAvailable": bool(profile),
                "variantStatus": result.estado.value, "runes": pages, "spells": list(self.analyzer.normalizar_hechizos(variant.get("summoner_spells") or profile.get("summoner_spells"), role_key)),
                "build": builds[0] if profile else {"items": [], "boots": None, "situational": []}, "builds": builds if profile else [],
                "situational": (builds[0].get("situational", []) if builds else []) if profile else [], "bans": bans,
                "damage": team_compositions["allies"]["damage"] or {}, "powerCurve": team_compositions["allies"]["powerCurve"],
                "matchups": role_matchups, "warnings": warnings, "composition": {"allies": len(curve_names), "enemies": len(enemy_names), "damageSamples": team_compositions["allies"]["damageSamples"], "teams": team_compositions}}
        if len(self._analysis_cache) >= 64:
            self._analysis_cache.pop(next(iter(self._analysis_cache)))
        self._analysis_cache[cache_key] = (time.monotonic(), result)
        return result

    def _build_for_page(self, champion: str, page: dict[str, Any], enemies: list[str], role: str, base: dict[str, Any]) -> dict[str, Any]:
        """Use the selected role/rune page's build first, then the existing curated fallback."""
        profile = self.analyzer.get_champion_profile(champion) or {}
        raw = page.get("build") if isinstance(page.get("build"), list) else profile.get("most_played_build", [])
        ids: list[str] = []
        boots_id: str | None = None
        for value in raw if isinstance(raw, list) else []:
            name = str(value.get("name") or value.get("item") or value.get("id") or "") if isinstance(value, dict) else str(value)
            item_id = str(value.get("id")) if isinstance(value, dict) and str(value.get("id", "")).isdigit() else self.analyzer.item_names.get(name.strip().casefold(), "")
            item = self._item_catalog.get(item_id, {})
            if not self._eligible_item(item_id):
                continue
            if "Boots" in item.get("tags", []):
                boots_id = item_id
            elif item_id not in ids:
                ids.append(item_id)
        for entry in base.get("items", []):
            item_id = str(entry.get("id", ""))
            if len(ids) >= 6:
                break
            if item_id not in ids and self._eligible_item(item_id):
                ids.append(item_id)
        items = [{"id": item_id, "name": str(self._item_catalog[item_id].get("name") or item_id)} for item_id in ids[:6]]
        boots = {"id": boots_id, "name": str(self._item_catalog[boots_id].get("name") or boots_id)} if boots_id else base.get("boots")
        starters = []
        starter_source = base.get("starter_items", [])
        if any(page.get(key) for key in ("starter_item_entries", "starter_item_ids", "starter_items")):
            starter_source = self.analyzer.get_starter_items(champion, role, profile=profile, variant=page)
        for entry in starter_source:
            item_id = str(entry.get("id", "")) if isinstance(entry, dict) else str(entry)
            if self._eligible_item(item_id) and item_id not in {item.get("id") for item in starters}:
                starters.append({"id": item_id, "name": str(self._item_catalog[item_id].get("name") or item_id), "count": int(entry.get("count", 1)) if isinstance(entry, dict) else 1})
        return {**base, "items": items, "boots": boots, "starter_items": starters, "situational": base.get("situational") or self.analyzer.get_situational_items(champion), "role": role}

    def _champion_win_rate(self, champion: str | None) -> float | None:
        profile = self.analyzer.get_champion_profile(champion or "") or {}
        summary = (profile.get("matchups") or {}).get("summary", {})
        value = summary.get("overall_win_rate") if isinstance(summary, dict) else None
        if value is None:
            value = profile.get("overall_win_rate")
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not 0 <= parsed <= 100:
            return None
        return round(parsed * 100 if parsed <= 1 else parsed, 1)

    def _rune_assets(self, pages: list[dict[str, Any]], spells: list[str], assets: dict[str, Any]) -> None:
        try:
            values = []
            for page in pages:
                values.extend([page.get("primary_tree_id"), page.get("primary_tree"),
                               page.get("secondary_tree_id"), page.get("secondary_tree"),
                               page.get("keystone_id"), page.get("keystone")])
                for field in ("slot_ids", "slots", "secondary_slot_ids", "secondary_slots", "shard_ids", "shards"):
                    candidate = page.get(field, [])
                    values.extend(candidate if isinstance(candidate, list) else [])
            runes = list(dict.fromkeys(str(value) for value in values if value))
            assets.update(resolve_meta_assets([], [], [], self.catalog, runes=runes, spells=spells))
        except Exception:
            return

    def import_selection(self, params: dict[str, Any]) -> dict[str, Any]:
        champion = self._canonical(str(params.get("champion", "")))
        role = str(params.get("role", ""))
        kind = str(params.get("kind", ""))
        page_index = params.get("pageIndex", 0)
        if not champion or role not in ROLES or kind not in {"runes", "build", "spells", "all"} or not isinstance(page_index, int) or isinstance(page_index, bool) or page_index not in (0, 1):
            raise ValueError("Selección de preparación no válida.")
        result = self.repository.consultar(champion, role, "emerald_plus")
        variant = result.datos if result.estado.value == "AVAILABLE" and isinstance(result.datos, dict) else {}
        pages = [p for p in variant.get("runes", []) if isinstance(p, dict)][:2]
        page = pages[page_index] if page_index < len(pages) else None
        profile = self.analyzer.get_champion_profile(champion) or {}
        if not profile:
            return {"ok": False, "message": "No hay perfil local suficiente para preparar esta importación."}
        if kind in {"runes", "all"}:
            if not page:
                return {"ok": False, "message": "No hay una página de runas válida para este campeón y posición."}
            ok, message = self.lcu.import_rune_page(str(page.get("name") or f"Solralol · {champion}"), page.get("primary_tree_id") or page.get("primary_tree", ""), page.get("secondary_tree_id") or page.get("secondary_tree", ""), page.get("keystone_id") or page.get("keystone", ""), page.get("slots", []), page.get("secondary_slots", []), page.get("shards", []), keystone_id=page.get("keystone_id"), slot_ids=page.get("slot_ids"), secondary_slot_ids=page.get("secondary_slot_ids"), shard_ids=page.get("shard_ids"))
            if not ok or kind == "runes": return {"ok": bool(ok), "message": message}
        enemies = [self._canonical(str(v)) for v in params.get("enemies", []) if isinstance(v, str)] if isinstance(params.get("enemies", []), list) else []
        if kind in {"build", "all"}:
            base_build = self.analyzer.get_champion_build(champion, [x for x in enemies if x], role)
            build = self._build_for_page(champion, page or {}, [x for x in enemies if x], role, base_build)
            item_ids = [str(item["id"]) for item in build.get("items", []) if str(item.get("id", "")).isdigit() and self._eligible_item(str(item["id"]))]
            boots = build.get("boots") or {}
            boots_id = str(boots.get("id")) if str(boots.get("id", "")).isdigit() and self._eligible_item(str(boots.get("id"))) else None
            if item_ids:
                starter_ids = [str(item.get("id", "")) for item in build.get("starter_items", []) if isinstance(item, dict) for _ in range(item.get("count", 1))]
                ok, message = self.lcu.import_item_set(int(build.get("champion_id") or 0), champion, role, item_ids[:6], boots_id, build.get("situational", []), starter_ids=starter_ids or None)
                if not ok or kind == "build": return {"ok": bool(ok), "message": message}
        spells = DraftAnalyzerService.normalizar_hechizos(variant.get("summoner_spells") or profile.get("summoner_spells"), role)
        ok, message = self.lcu.import_summoner_spells(*spells)
        return {"ok": bool(ok), "message": message}

    def _eligible_item(self, item_id: str) -> bool:
        item = self._item_catalog.get(item_id)
        if not isinstance(item, dict) or not item.get("maps", {}).get("11", True) or item.get("requiredAlly"):
            return False
        return True
