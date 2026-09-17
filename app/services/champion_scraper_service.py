"""Sincronización de builds, runas y matchups públicos desde U.GG y Lolalytics."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from bs4 import BeautifulSoup, Tag

_ROLE = {"top": "top", "jungle": "jungle", "mid": "mid", "middle": "mid", "adc": "adc", "bot": "adc", "bottom": "adc", "support": "support", "utility": "support"}
_TREES = {"Precision", "Domination", "Sorcery", "Resolve", "Inspiration"}
_KEYSTONES = {"Press the Attack", "Lethal Tempo", "Fleet Footwork", "Conqueror", "Electrocute", "Dark Harvest", "Hail of Blades", "Arcane Comet", "Summon Aery", "Phase Rush", "Grasp of the Undying", "Aftershock", "Guardian", "Glacial Augment", "First Strike", "Unsealed Spellbook"}


class ChampionScraperService:
    """No usa APIs privadas de U.GG; interpreta las páginas públicas visibles."""

    def __init__(self, champions_path: Path | None = None, request_delay: float = 0.8) -> None:
        self.champions_path = champions_path or Path(__file__).resolve().parents[2] / "data" / "champions_strict.json"
        self.request_delay = max(0.0, request_delay)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://lolalytics.com/",
            "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        })
        self._live_patches: list[str] | None = None
        root = self.champions_path.parent
        catalog = json.loads((root / "champion_catalog.json").read_text(encoding="utf-8"))
        self.champion_ids = {str(value.get("name", "")).casefold(): int(value["key"]) for value in catalog.get("data", {}).values() if value.get("key")}
        self.champion_names = {int(value["key"]): str(value.get("name", "")) for value in catalog.get("data", {}).values() if value.get("key")}
        items = json.loads((root / "items.json").read_text(encoding="utf-8"))
        self.items_data = items.get("items", {})
        self.item_names = {str(item_id): str(value.get("name", item_id)) for item_id, value in self.items_data.items()}
        self.boot_item_names = {
            str(value.get("name", "")).casefold() for value in self.items_data.values()
            if "Boots" in value.get("tags", [])
        }

    @staticmethod
    def _slug(name: str) -> str:
        aliases = {"wukong": "monkeyking", "nunu & willump": "nunu", "nunu y willump": "nunu", "dr. mundo": "drmundo", "jarvan iv": "jarvaniv", "aurelion sol": "aurelionsol", "cho'gath": "chogath", "kai'sa": "kaisa", "kha'zix": "khazix", "kog'maw": "kogmaw", "rek'sai": "reksai", "vel'koz": "velkoz", "k'sante": "ksante"}
        clean = name.strip().lower()
        return aliases.get(clean, re.sub(r"[^a-z0-9]", "", clean))

    @staticmethod
    def _role(profile: dict[str, Any]) -> str:
        flex = profile.get("basic_info", {}).get("flex_potential", [])
        raw = flex[0] if isinstance(flex, list) and flex else "mid"
        return _ROLE.get(str(raw).lower(), "mid")

    def _get(self, url: str) -> BeautifulSoup | None:
        try:
            response = self.session.get(url, timeout=20)
            return BeautifulSoup(response.content, "html.parser") if response.status_code == 200 else None
        except requests.RequestException:
            return None

    def _get_json(self, url: str) -> Any | None:
        try:
            response = self.session.get(url, timeout=20)
            return response.json() if response.status_code == 200 else None
        except (requests.RequestException, ValueError):
            return None

    def _patches(self) -> list[str]:
        if self._live_patches is not None:
            return self._live_patches
        values: list[str] = []
        data = self._get_json("https://ddragon.leagueoflegends.com/api/versions.json")
        if isinstance(data, list) and data:
            match = re.match(r"(\d+)\.(\d+)", str(data[0]))
            if match:
                major, minor = match.groups()
                values.extend((f"26.{minor}", f"{major}.{minor}"))
        values.extend(("26.18", "16.18", "26.17", "16.17"))
        self._live_patches = list(dict.fromkeys(values))
        return self._live_patches

    def _overview(self, champion_id: int) -> Any | None:
        """Lee el JSON público que alimenta la página de build de U.GG."""
        local_version = json.loads((self.champions_path.parent / "champion_catalog.json").read_text(encoding="utf-8")).get("version", "")
        patches = [patch.replace(".", "_") for patch in self._patches()]
        patches.append(str(local_version).rsplit(".", 1)[0].replace(".", "_"))
        for patch in dict.fromkeys(patches):
            for version in ("1.5.0", "1.4.0"):
                url = f"https://stats2.u.gg/lol/1.5/overview/{patch}/ranked_solo_5x5/{champion_id}/{version}.json"
                data = self._get_json(url)
                if data:
                    return data
        return None

    @staticmethod
    def _position_data(data: Any, role: str) -> Any | None:
        position = {"jungle": 1, "support": 2, "adc": 3, "top": 4, "mid": 5}.get(role, 5)
        try:
            bucket = data[12][10]  # world + Emerald+; estructura estable de U.GG
            return bucket[position][0] or next((bucket[p][0] for p in range(1, 6) if bucket[p] and bucket[p][0]), None)
        except (KeyError, IndexError, TypeError):
            return None

    @staticmethod
    def _flat_perks(value: Any) -> list[int]:
        if not isinstance(value, list):
            return []
        result = []
        for entry in value:
            candidate = entry[0] if isinstance(entry, list) and entry else entry
            if isinstance(candidate, int):
                result.append(candidate)
        return result

    def _is_finished_item(self, item_id: str) -> bool:
        item = self.items_data.get(str(item_id))
        if not item:
            return False
        tags = item.get("tags", [])
        if "Consumable" in tags or "Trinket" in tags or "Lane" in tags:
            return False
        if "Boots" in tags:
            return item.get("gold", {}).get("total", 0) >= 900
        into = item.get("into", [])
        if into:
            return False
        return item.get("gold", {}).get("total", 0) >= 1400 or "Depth3" in tags or "Legendary" in tags

    _SUMMONER_SPELLS = {
        1: "Purificar",
        3: "Extenuación",
        4: "Destello",
        6: "Fantasmal",
        7: "Curación",
        11: "Aplastar",
        12: "Teleportación",
        14: "Ignición",
        21: "Barrera",
    }
    _ANTIHEAL_IDS = {"3033", "3075", "3123", "3165", "3076", "3907", "3074"}

    def _categorize_situational_item(self, item_id: str) -> str:
        item = self.items_data.get(str(item_id), {})
        description = item.get("description", "").lower()
        tags = item.get("tags", [])
        stats = item.get("stats", {})
        
        if str(item_id) in self._ANTIHEAL_IDS or "heridas graves" in description or "grievous wounds" in description:
            return "corta_curas"
        if "Armor" in tags or "SpellBlock" in tags or stats.get("FlatArmorMod", 0) > 0 or stats.get("FlatSpellBlockMod", 0) > 0 or stats.get("FlatHPPoolMod", 0) >= 350:
            return "tanque"
        if "ArmorPenetration" in tags or "MagicPenetration" in tags or "lethality" in description or stats.get("FlatPhysicalDamageMod", 0) >= 50 or stats.get("FlatMagicDamageMod", 0) >= 70:
            return "asesino"
        return "utilidad_y_defensa"

    def _parse_opgg(self, slug: str, role: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        lane = {"mid": "mid", "adc": "adc", "top": "top", "jungle": "jungle", "support": "support"}.get(role, role)
        url = f"https://lol-api-champion.op.gg/api/global/champions/ranked/{slug}/{lane}"
        data = self._get_json(url)
        if not isinstance(data, dict):
            return result
        opdata = data.get("data", {})
        if not isinstance(opdata, dict):
            return result

        cores = opdata.get("core_items", [])
        boots = opdata.get("boots", [])
        lasts = opdata.get("last_items", [])
        starters = opdata.get("starter_items", [])
        spells = opdata.get("summoner_spells", [])

        core_ids = [str(i) for i in (cores[0].get("ids", []) if cores and isinstance(cores[0], dict) else []) if self._is_finished_item(str(i))]
        boot_ids = [str(i) for i in (boots[0].get("ids", []) if boots and isinstance(boots[0], dict) else []) if self._is_finished_item(str(i))]

        full_ids: list[str] = []
        for i in core_ids:
            if i not in full_ids:
                full_ids.append(i)
        if boot_ids and boot_ids[0] not in full_ids:
            full_ids.append(boot_ids[0])
        for entry in (lasts if isinstance(lasts, list) else []):
            if isinstance(entry, dict):
                for i in [str(x) for x in entry.get("ids", [])]:
                    if i not in full_ids and self._is_finished_item(i):
                        full_ids.append(i)
                    if len(full_ids) >= 6:
                        break
            if len(full_ids) >= 6:
                break

        core_names = [self.item_names[i] for i in core_ids[:3] if i in self.item_names]
        full_names = [self.item_names[i] for i in full_ids[:6] if i in self.item_names]

        if core_names:
            result["items"] = core_names[:3]
        if full_names:
            result["full_build"] = full_names[:6]

        if starters and isinstance(starters, list) and isinstance(starters[0], dict):
            s_ids = starters[0].get("ids", [])
            starter_names = [self.item_names[str(i)] for i in s_ids if str(i) in self.item_names]
            if starter_names:
                result["starter_items"] = starter_names

        if spells and isinstance(spells, list) and isinstance(spells[0], dict):
            sp_ids = spells[0].get("ids", [])
            spell_names = [self._SUMMONER_SPELLS.get(i, f"Hechizo {i}") for i in sp_ids if i in self._SUMMONER_SPELLS]
            if spell_names:
                result["summoner_spells"] = spell_names

        situational: dict[str, list[str]] = {"corta_curas": [], "tanque": [], "asesino": [], "utilidad_y_defensa": []}
        for entry in (lasts if isinstance(lasts, list) else []):
            if isinstance(entry, dict):
                for i in entry.get("ids", []):
                    sid = str(i)
                    if self._is_finished_item(sid) and sid in self.item_names:
                        item_name = self.item_names[sid]
                        cat = self._categorize_situational_item(sid)
                        if item_name not in situational[cat] and len(situational[cat]) < 4:
                            situational[cat].append(item_name)

        if any(situational.values()):
            result["situational_items"] = situational

        # Parse Emerald+ Standard Rune Page
        runes_data = opdata.get("runes", [])
        if isinstance(runes_data, list) and runes_data:
            r = runes_data[0]
            pri_tree_id = r.get("primary_page_id")
            pri_ids = r.get("primary_rune_ids", [])
            sec_tree_id = r.get("secondary_page_id")
            sec_ids = r.get("secondary_rune_ids", [])
            shard_ids = r.get("stat_mod_ids", [])
            games = r.get("play", 0)
            wins = r.get("win", 0)
            if len(pri_ids) >= 4:
                shards = [self._PERK_NAMES.get(i, str(i)) for i in shard_ids[:3]]
                if len(shards) == 2:
                    shards = [shards[0], shards[0], shards[1]]
                trees = {8000: "Precision", 8100: "Domination", 8200: "Sorcery", 8300: "Inspiration", 8400: "Resolve"}
                result["runes"] = [{
                    "name": "Página 1 U.GG",
                    "source": "U.GG",
                    "primary_tree": trees.get(pri_tree_id, "Precision"),
                    "secondary_tree": trees.get(sec_tree_id, "Resolve"),
                    "keystone": self._PERK_NAMES.get(pri_ids[0], str(pri_ids[0])),
                    "slots": [self._PERK_NAMES.get(i, str(i)) for i in pri_ids[1:4]],
                    "secondary_slots": [self._PERK_NAMES.get(i, str(i)) for i in sec_ids[:2]],
                    "shards": shards,
                    "win_rate": round(wins / games, 4) if games > 0 else 0.0,
                    "games": games
                }]

        return result

    def _parse_overview(self, data: Any, role: str) -> dict[str, Any]:
        """
        Extrae la información completa del endpoint Overview de U.GG:
        - Hechizos de invocador (summoner_spells)
        - Ítems iniciales (starter_items)
        - Core items e Ítems finales / Full Build (most_played_build)
        - Páginas de runas (Recomendada y Mayor Winrate)
        """
        pd = self._position_data(data, role)
        if not isinstance(pd, list):
            return {}

        result: dict[str, Any] = {}

        # --- 1. HECHIZOS DE INVOCADOR (pd[2]) ---
        if len(pd) > 2 and isinstance(pd[2], list) and len(pd[2]) > 2:
            spells_block = pd[2]
            raw_spells = spells_block[2] if isinstance(spells_block[2], list) else []
            spell_names = [self.spell_names.get(str(s), str(s)) for s in raw_spells if str(s) in self.spell_names]
            if spell_names:
                result["summoner_spells"] = spell_names

        # --- 2. ÍTEMS INICIALES (pd[4]) ---
        if len(pd) > 4 and isinstance(pd[4], list) and len(pd[4]) > 2:
            starters_block = pd[4]
            raw_starters = starters_block[2] if isinstance(starters_block[2], list) else []
            starter_names = [self.item_names.get(str(i), str(i)) for i in raw_starters if str(i) in self.item_names]
            if starter_names:
                result["starter_items"] = starter_names

        # --- 3. CORE ITEMS Y FULL BUILD (pd[3] y pd[5]) ---
        core = pd[3] if len(pd) > 3 and isinstance(pd[3], list) else []
        core_ids = []
        if len(core) > 2 and isinstance(core[2], list):
            core_ids = [str(i) for i in core[2] if self._is_finished_item(str(i))]
        
        core_names = [self.item_names[i] for i in core_ids if i in self.item_names]
        if len(core_names) >= 2:
            result["items"] = core_names[:3]

        # Full build combinando core + opciones situacionales de pd[5]
        full_ids = list(core_ids)
        if len(pd) > 5 and isinstance(pd[5], list):
            for slot in pd[5]:
                if isinstance(slot, list):
                    for choice in slot:
                        if isinstance(choice, list) and choice:
                            raw_id = choice[0][0] if isinstance(choice[0], list) else choice[0]
                            item_id = str(raw_id)
                            if item_id not in full_ids and self._is_finished_item(item_id):
                                full_ids.append(item_id)

        full_build_names = [self.item_names[i] for i in full_ids if i in self.item_names]
        if len(full_build_names) >= 3:
            result["full_build"] = full_build_names[:6]
            result["most_played_build"] = full_build_names[:6]

        # --- 4. RUNAS U.GG (Extrae Recomendada y Mayor Winrate) ---
        pages = []
        seen_pages: set[tuple[Any, ...]] = set()

        candidates = []
        for item in pd:
            candidates.extend(self._perk_candidates(item))

        for candidate in candidates:
            if not isinstance(candidate, list) or len(candidate) < 5:
                continue
            
            primary, secondary = candidate[2], candidate[3]
            perk_ids = self._flat_perks(candidate[4])
            if not isinstance(primary, int) or not isinstance(secondary, int) or len(perk_ids) < 6:
                continue

            page = self._rune_page(primary, secondary, perk_ids)
            games, wins = candidate[0], candidate[1]
            
            if page:
                signature = (
                    page.get("keystone"),
                    tuple(page.get("slots", [])),
                    page.get("secondary_tree"),
                    tuple(page.get("secondary_slots", []))
                )
                if self._valid_rune_page(page) and signature not in seen_pages and isinstance(games, (int, float)) and games:
                    page["name"] = "Recomendada · U.GG" if not pages else "Mayor Winrate · U.GG"
                    page["win_rate"] = round(float(wins) / float(games), 4) if isinstance(wins, (int, float)) else 0.0
                    page["games"] = int(games)
                    pages.append(page)
                    seen_pages.add(signature)

            if len(pages) == 2:
                break

        if pages:
            result["runes"] = pages

        return result

    def _item_ids_in_order(self, value: Any) -> list[int]:
        result: list[int] = []
        def visit(node: Any) -> None:
            if isinstance(node, (int, str)) and str(node).isdigit() and str(node) in self.item_names:
                item_id = int(node)
                if item_id not in result:
                    result.append(item_id)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(value)
        return result

    @staticmethod
    def _perk_candidates(value: Any) -> list[list[Any]]:
        found: list[list[Any]] = []
        if not isinstance(value, list):
            return found
        if len(value) >= 5 and isinstance(value[2], int) and isinstance(value[3], int) and isinstance(value[4], list):
            found.append(value)
        for child in value:
            found.extend(ChampionScraperService._perk_candidates(child))
        return found

    def _rune_page(self, primary: int, secondary: int, perks: list[int]) -> dict[str, Any] | None:
        trees = {8000: "Precision", 8100: "Domination", 8200: "Sorcery", 8300: "Inspiration", 8400: "Resolve"}
        names = {
            8005: "Press the Attack", 8008: "Lethal Tempo", 8021: "Fleet Footwork", 8010: "Conqueror",
            8112: "Electrocute", 8128: "Dark Harvest", 9923: "Hail of Blades", 8214: "Summon Aery",
            8229: "Arcane Comet", 8230: "Phase Rush", 8437: "Grasp of the Undying", 8439: "Aftershock",
            8465: "Guardian", 8351: "Glacial Augment", 8360: "Unsealed Spellbook", 8369: "First Strike",
            9111: "Triumph", 8009: "Presence of Mind", 9104: "Legend: Alacrity", 9105: "Legend: Haste",
            9103: "Legend: Tenacity", 9102: "Legend: Bloodline", 8014: "Coup de Grace", 8017: "Cut Down",
            8299: "Last Stand", 8126: "Cheap Shot", 8139: "Taste of Blood", 8143: "Sudden Impact",
            8137: "Sixth Sense", 8135: "Treasure Hunter", 8105: "Relentless Hunter", 8233: "Absolute Focus",
            8210: "Transcendence", 8226: "Manaflow Band", 8236: "Gathering Storm", 8232: "Waterwalking",
            8446: "Demolish", 8444: "Second Wind", 8473: "Bone Plating", 8451: "Overgrowth",
            8453: "Revitalize", 8242: "Unflinching", 8304: "Magical Footwear", 8345: "Biscuit Delivery",
            8347: "Cosmic Insight", 5001: "Health Scaling", 5002: "Armor", 5003: "Magic Resist",
            5005: "Attack Speed", 5007: "Ability Haste", 5008: "Adaptive Force"
        }
        if primary not in trees or secondary not in trees:
            return None
        readable = [names.get(value, str(value)) for value in perks]
        primary_runes = readable[:4]
        return {
            "keystone": primary_runes[0],
            "primary_tree": trees[primary],
            "slots": primary_runes[1:4],
            "secondary_tree": trees[secondary],
            "secondary_slots": readable[4:6],
            "shards": readable[6:9]
        }
    
    def _lolalytics(self, endpoint: str, slug: str, role: str) -> Any | None:
        local = json.loads((self.champions_path.parent / "champion_catalog.json").read_text(encoding="utf-8")).get("version", "16.17")
        local_patch = str(local).rsplit(".", 1)[0]
        patches = [*self._patches(), local_patch, ""]
        lane = {"mid": "middle", "adc": "bottom"}.get(role, role)
        headers = {
            "Referer": "https://lolalytics.com/",
            "Origin": "https://lolalytics.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        }
        for patch in dict.fromkeys(patches):
            url = "https://a1.lolalytics.com/mega/"
            params = {"ep": endpoint, "v": "1", "patch": patch, "c": slug, "tier": "e_plus", "queue": "ranked", "region": "all", "lane": lane}
            try:
                response = self.session.get(url, params=params, headers=headers, timeout=12)
                if response.status_code == 200 and response.content:
                    return response.json()
            except (requests.RequestException, ValueError):
                continue
        return None
    
    @staticmethod
    def _ids(value: Any) -> list[int]:
        return [int(x) for x in value if isinstance(x, (int, float, str)) and str(x).isdigit()] if isinstance(value, list) else []

    def _tree_for_perks(self, perks: list[int], fallback: int = 0) -> int:
        by_tree = {
            8000: {8005, 8008, 8021, 8010, 9111, 8009, 9104, 9103, 9102, 8014, 8017, 8299},
            8100: {8112, 8128, 9923, 8126, 8139, 8143, 8137, 8135, 8105},
            8200: {8214, 8229, 8230, 8233, 8210, 8226, 8236, 8232},
            8300: {8351, 8360, 8369, 8304, 8345, 8347},
            8400: {8437, 8439, 8465, 8446, 8444, 8473, 8451, 8453, 8242},
        }
        return next((tree for tree, ids in by_tree.items() if any(item in ids for item in perks)), (8000, 8100, 8200, 8300, 8400)[fallback % 5])

    def _rune_page_from_set(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        primary, secondary, shards = self._ids(value.get("pri")), self._ids(value.get("sec")), self._ids(value.get("mod"))
        if len(primary) < 4 or len(secondary) < 2:
            return None
        page = value.get("page", {})
        return self._rune_page(self._tree_for_perks(primary, int(page.get("pri", 0)) if isinstance(page, dict) else 0), self._tree_for_perks(secondary, int(page.get("sec", 1)) if isinstance(page, dict) else 1), primary + secondary + shards)

    def _parse_lolalytics(self, rune_data: Any, build_data: Any, counter_data: Any, role: str) -> dict[str, Any]:
        """Procesa las respuestas de la API JSON de Lolalytics."""
        output: dict[str, Any] = {}
        
        # Runas
        if isinstance(rune_data, dict) and "perk" in rune_data:
            page = self._rune_page_from_set(rune_data.get("perk"))
            if page and self._valid_rune_page(page):
                page["name"] = "Más jugada · Lolalytics"
                output["runes"] = [page]

        # Builds / Ítems
        if isinstance(build_data, dict):
            core_ids = [str(x) for x in self._ids(build_data.get("core")) if self._is_finished_item(str(x))]
            names = [self.item_names[i] for i in core_ids if i in self.item_names]
            if len(names) >= 3:
                output["items"] = names[:3]

        return output

    def _parse_lolalytics_html(self, soup: BeautifulSoup, champion: str, role: str) -> dict[str, Any]:
        """
        Extrae la información completa de Lolalytics desde el HTML/Qwik cuando la API falla o da 403.
        Mantiene el parseo completo de Runas (Árboles, Keystone, Slots y Shards), métricas y Objetos.
        """
        output: dict[str, Any] = {}
        raw_html = str(soup)

        # 1. Mapeo extendido de IDs de runas (Keystones, Slots y Shards)
        known_perks = {
            # Keystones
            8005, 8008, 8021, 8010, 8112, 8128, 9923, 8214, 8229, 8230, 8351, 8360, 8369, 8437, 8439, 8465,
            # Slots Principales y Secundarios
            9111, 8009, 9104, 9105, 9103, 9102, 8014, 8017, 8299, 8126, 8139, 8143, 8137, 8135, 8105, 8233,
            8210, 8226, 8236, 8232, 8446, 8444, 8473, 8451, 8453, 8242, 8304, 8345, 8347,
            # Fragmentos / Shards de estadísticas
            5001, 5002, 5003, 5005, 5007, 5008
        }
        keystones = {8005, 8008, 8021, 8010, 8112, 8128, 9923, 8214, 8229, 8230, 8351, 8360, 8369, 8437, 8439, 8465}

        # 2. Extracción de IDs (Buscando en imágenes HTML y en el estado Qwik)
        rune_ids = [int(x) for x in re.findall(r"(?:rune|runes|perk)/(\d+)(?:\.png)?", raw_html, re.IGNORECASE)]
        
        if not rune_ids:
            qwik_match = re.search(r'<script type="qwik/json">(.*?)</script>', raw_html, re.DOTALL)
            if qwik_match:
                # Buscar números aislados dentro del estado Qwik que correspondan a IDs de runas válidos
                found_tokens = re.findall(r"\b(500\d|8\d{3}|9\d{3})\b", qwik_match.group(1))
                rune_ids = [int(x) for x in found_tokens if int(x) in known_perks]

        # 3. Procesamiento de Páginas de Runas Completas (9 perks: 4 Rama Principal + 2 Secundaria + 3 Shards)
        pages = []
        seen_signatures: set[tuple[Any, ...]] = set()

        for index, perk_id in enumerate(rune_ids):
            if perk_id not in keystones:
                continue

            # Tomamos la ventana completa de 9 runas
            perks_window = rune_ids[index:index + 9]
            if len(perks_window) < 9:
                # Intentar fallback si faltan shards
                if len(perks_window) >= 6:
                    perks_window = perks_window[:6] + [5007, 5008, 5001]
                else:
                    continue

            primary_tree = self._tree_for_perks(perks_window[:4])
            secondary_tree = self._tree_for_perks(perks_window[4:6], fallback_idx=1)

            page = self._rune_page(primary_tree, secondary_tree, perks_window)
            if page and self._valid_rune_page(page):
                signature = (
                    page.get("keystone"),
                    tuple(page.get("slots", [])),
                    page.get("secondary_tree"),
                    tuple(page.get("secondary_slots", []))
                )
                if signature not in seen_signatures:
                    page["name"] = "Más jugada · Lolalytics" if not pages else "Mayor winrate · Lolalytics"
                    pages.append(page)
                    seen_signatures.add(signature)

            if len(pages) == 2:
                break

        if pages:
            output["runes"] = pages

        # 4. Extracción de Ítems / Builds desde HTML
        item_ids = [str(x) for x in re.findall(r"(?:item|items)/(\d+)\.png", raw_html, re.IGNORECASE)]
        if item_ids:
            valid_items = [self.item_names[i] for i in item_ids if i in self.item_names and self._is_finished_item(i)]
            # Eliminar duplicados manteniendo el orden
            unique_items = list(dict.fromkeys(valid_items))
            if len(unique_items) >= 3:
                output["most_played_build"] = unique_items[:6]

        return output

    def _lolalytics_page(self, slug: str, role: str, section: str = "build") -> BeautifulSoup | None:
        lane = {"mid": "middle", "adc": "bottom"}.get(role, role)
        return self._get(f"https://lolalytics.com/lol/{slug}/{section}/?lane={lane}")

    def _parse_lolalytics_html(self, soup: BeautifulSoup, champion: str, role: str) -> dict[str, Any]:
        output: dict[str, Any] = {}
        core = self._heading(soup, "core build")
        if core:
            ids = []
            for image in core.find_all_next("img", limit=8):
                match = re.search(r"item\d+/(\d+)", str(image.get("srcset", image.get("src", ""))))
                if match and match.group(1) not in ids:
                    ids.append(match.group(1))
            names = [self.item_names[item_id] for item_id in ids if item_id in self.item_names]
            if len(names) >= 3:
                output["items"] = names[:3]
        raw_html = str(soup)
        rune_ids = [int(value) for value in re.findall(r"rune\d+/(\d+)", raw_html)]
        keystones = {8005, 8008, 8021, 8010, 8112, 8128, 9923, 8214, 8229, 8230, 8351, 8360, 8369, 8437, 8439, 8465}
        pages = []
        seen_pages: set[tuple[int, ...]] = set()
        for index, perk_id in enumerate(rune_ids):
            if perk_id not in keystones:
                continue
            perks = rune_ids[index:index + 9]
            if len(perks) < 6:
                continue
            if any(value in keystones for value in perks[1:4]):
                continue
            page = self._rune_page(self._tree_for_perks(perks[:4]), self._tree_for_perks(perks[4:6], 1), perks)
            signature = tuple(perks)
            if page and signature not in seen_pages:
                page["name"] = "Más jugada · Lolalytics" if not pages else "Mayor winrate · Lolalytics"
                pages.append(page)
                seen_pages.add(signature)
            if len(pages) == 2:
                break
        if pages:
            output["runes"] = pages
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        rows = []
        for enemy in self.champion_names.values():
            if enemy.casefold() == champion.casefold():
                continue
            pattern = re.compile(
                rf"\b{re.escape(enemy)}\s+(\d{{1,2}}(?:\.\d+)?)\s*%\s+VS.*?(\d[\d.,]*)\s+Games\s+vs\s+{re.escape(enemy)}\b",
                re.IGNORECASE,
            )
            match = pattern.search(text)
            if not match:
                continue
            rate = float(match.group(1)) / 100
            games = int(match.group(2).replace(".", "").replace(",", ""))
            rows.append({"champion": enemy, "win_rate": rate, "overall_win_rate": rate, "lane_games": games, "overall_games": games, "primary_role": role.title(), "tip": ""})
        if len(rows) >= 6:
            rows.sort(key=lambda row: row["win_rate"])
            average = sum(row["win_rate"] for row in rows) / len(rows)
            counters, good = rows[:3], rows[-3:][::-1]
            for entry in counters:
                entry["tip"] = f"{champion} gana el {entry['win_rate']:.1%} de {entry['lane_games']:,} partidas frente a {entry['champion']}. Juega la fase de líneas con cautela.".replace(",", ".")
            for entry in good:
                entry["tip"] = f"{champion} gana el {entry['win_rate']:.1%} de {entry['lane_games']:,} partidas frente a {entry['champion']}. Puedes buscar presión en línea.".replace(",", ".")
            total_games = sum(entry["lane_games"] for entry in rows)
            output["matchups"] = {"counters": counters, "good_against": good, "summary": {"total_games_analyzed": total_games, "primary_role": role.title(), "lane_win_rate": average, "lane_total_games": total_games, "overall_win_rate": average, "overall_total_games": total_games}}
        return output

    @staticmethod
    def _heading(soup: BeautifulSoup, *names: str) -> Tag | None:
        wanted = set(names)
        return soup.find(lambda tag: tag.name in {"h1", "h2", "h3", "div"} and tag.get_text(" ", strip=True).lower() in wanted)

    @staticmethod
    def _following_alts(heading: Tag, limit: int = 18) -> list[str]:
        result: list[str] = []
        for image in heading.find_all_next("img", limit=limit):
            value = str(image.get("alt", "")).replace("Image: ", "").strip()
            if value and value not in result:
                result.append(value)
        return result

    def _parse_build(self, soup: BeautifulSoup) -> dict[str, Any]:
        data: dict[str, Any] = {}
        core = self._heading(soup, "core items")
        if core:
            items = [x for x in self._following_alts(core) if "item" not in x.lower()]
            if len(items) >= 3:
                data["items"] = items[:3]
        rune_labels = []
        for image in soup.select("img[alt]"):
            label = str(image.get("alt", "")).replace("Image: ", "").strip()
            if label.startswith("The Rune Tree "):
                rune_labels.append(("tree", label.removeprefix("The Rune Tree ")))
            elif label.startswith("The Keystone "):
                rune_labels.append(("key", label.removeprefix("The Keystone ")))
            elif label.startswith("The Rune "):
                rune_labels.append(("rune", label.removeprefix("The Rune ")))
        trees = [value for kind, value in rune_labels if kind == "tree" and value in _TREES]
        key_index = next((i for i, (kind, value) in enumerate(rune_labels) if kind == "key" and value in _KEYSTONES), -1)
        if len(trees) >= 2 and key_index >= 0:
            minor = [value for kind, value in rune_labels[key_index + 1:] if kind == "rune"]
            data["runes"] = {"keystone": rune_labels[key_index][1], "primary_tree": trees[0], "slots": minor[:3], "secondary_tree": next((x for x in trees[1:] if x != trees[0]), trees[1]), "secondary_slots": minor[3:5], "shards": []}
        return data

    def _parse_matchups(self, soup: BeautifulSoup, role: str) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for field, headings in {"counters": ("toughest matchups", "worst matchups"), "good_against": ("best matchups", "easiest matchups")}.items():
            title = self._heading(soup, *headings)
            if not title:
                continue
            rows: list[dict[str, Any]] = []
            for link in title.find_all_next("a", href=True, limit=35):
                found = re.search(r"/lol/champions/([^/]+)/(?:build|counter)", str(link["href"]))
                if not found:
                    continue
                slug = found.group(1)
                name = next((champion for champion in self.champion_names.values() if self._slug(champion) == slug), "")
                if not name:
                    continue
                values = re.findall(r"(\d{1,2}(?:\.\d+)?)%", link.get_text(" ", strip=True) or link.parent.get_text(" ", strip=True))
                if not values or any(x["champion"] == name for x in rows):
                    continue
                rate = float(values[0]) / 100
                rows.append({"champion": name, "win_rate": rate, "overall_win_rate": rate, "lane_games": 0, "overall_games": 0, "primary_role": role.title(), "tip": "Datos de matchup actualizados desde U.GG."})
                if len(rows) == 3:
                    break
            if rows:
                result[field] = rows
        return result

    def _clean_matchups(self, matchups: Any, role: str) -> dict[str, Any]:
        if not isinstance(matchups, dict):
            return {}
        canonical = {self._slug(name): name for name in self.champion_names.values()}

        def resolve(value: Any) -> str:
            raw = str(value or "")
            if direct := canonical.get(self._slug(raw)):
                return direct
            match = re.search(r"Games\s+vs\s+(.+?)(?:\s+(?:the|wins)\b|$)", raw, re.IGNORECASE)
            return canonical.get(self._slug(match.group(1))) if match else ""

        output: dict[str, Any] = {}
        for field in ("counters", "good_against"):
            rows, seen = [], set()
            for entry in matchups.get(field, []):
                if not isinstance(entry, dict):
                    continue
                champion = resolve(entry.get("champion"))
                if not champion or champion in seen:
                    continue
                seen.add(champion)
                try:
                    win_rate = float(entry.get("win_rate", .5) or .5)
                except (TypeError, ValueError):
                    win_rate = .5
                win_rate = win_rate / 100 if win_rate > 1 else max(0.0, min(win_rate, 1.0))
                rows.append({"champion": champion, "win_rate": win_rate, "overall_win_rate": win_rate,
                             "lane_games": int(entry.get("lane_games", 0) or 0), "overall_games": int(entry.get("overall_games", 0) or 0),
                             "primary_role": role.title(), "tip": str(entry.get("tip", ""))[:240]})
            if rows:
                output[field] = rows[:3]
        if isinstance(matchups.get("summary"), dict):
            output["summary"] = matchups["summary"]
        return output

    def _without_boots(self, names: Any) -> list[str]:
        if not isinstance(names, list):
            return []
        return [str(name) for name in names if str(name).casefold() not in self.boot_item_names][:3]

    def update_champion(self, profile: dict[str, Any]) -> bool:
        name, role = str(profile.get("character", "")).strip(), self._role(profile)
        if not name:
            return False
        slug = self._slug(name)
        champion_id = self.champion_ids.get(name.casefold())
        parsed = self._parse_overview(self._overview(champion_id), role) if champion_id else {}
        
        opgg_data = self._parse_opgg(slug, role)
        
        supplemental = self._parse_lolalytics(
            self._lolalytics("rune", slug, role),
            self._lolalytics("build-itemset", slug, role),
            self._lolalytics("counter", slug, role),
            role,
        )
        html_build = self._lolalytics_page(slug, role, "build")
        html_counter = self._lolalytics_page(slug, role, "counters")
        html_data = self._parse_lolalytics_html(html_build, name, role) if html_build else {}
        if html_counter:
            html_data.update({"matchups": self._parse_lolalytics_html(html_counter, name, role).get("matchups", {})})
        
        for source in (opgg_data, supplemental, html_data):
            for key, value in source.items():
                if value and key not in parsed:
                    parsed[key] = value
                elif key == "full_build" and value and len(parsed.get("full_build", [])) < len(value):
                    parsed["full_build"] = value
                elif key == "items" and value and len(parsed.get("items", [])) < len(value):
                    parsed["items"] = value

        counter_page = self._get(f"https://u.gg/lol/champions/{slug}/counter/{role}")
        matchups = self._clean_matchups(
            html_data.get("matchups") or supplemental.get("matchups") or (self._parse_matchups(counter_page, role) if counter_page else {}), role
        )

        items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        full_build = parsed.get("full_build") if isinstance(parsed.get("full_build"), list) else []
        
        changed = False
        imported_build_data = False
        
        # 1. Guardar Power Spike Core (3 ítems)
        if items:
            profile.setdefault("power_curve_and_scaling", {})["power_spike_items"] = items[:3]
            changed = True
            imported_build_data = True
            
        # 2. Guardar Build Completa de compra (hasta 6 ítems)
        if full_build:
            profile["most_played_build"] = full_build[:6]
            changed = True
            imported_build_data = True

        # 3. Guardar Runas (Página 1: U.GG Esmeralda+, Página 2: Lolalytics Esmeralda+)
        ugg_runes = parsed.get("runes", []) if isinstance(parsed.get("runes"), list) else []

        combined_runes: list[dict[str, Any]] = []

        # Bloque 1: U.GG Principal (Página 1 U.GG)
        if ugg_runes and self._valid_rune_page(ugg_runes[0]):
            p_ugg = dict(ugg_runes[0])
            p_ugg["name"] = "Página 1 U.GG"
            p_ugg["source"] = "U.GG"
            combined_runes.append(p_ugg)
        elif profile.get("runes") and isinstance(profile["runes"], list) and len(profile["runes"]) > 0:
            p_ugg = dict(profile["runes"][0])
            p_ugg["name"] = "Página 1 U.GG"
            p_ugg["source"] = "U.GG"
            combined_runes.append(p_ugg)

        # Bloque 2: Lolalytics Principal (Página 2 Lolalytics)
        lola_page = self._scrape_lolalytics_runes(slug, role, str(html_build) if html_build else None)
        if lola_page:
            lola_page["name"] = "Página 2 Lolalytics"
            lola_page["source"] = "Lolalytics"
            combined_runes.append(lola_page)
        elif len(ugg_runes) > 1 and self._valid_rune_page(ugg_runes[1]):
            p_ugg2 = dict(ugg_runes[1])
            p_ugg2["name"] = "Página 2 Lolalytics"
            p_ugg2["source"] = "Lolalytics"
            combined_runes.append(p_ugg2)

        if combined_runes:
            profile["runes"] = combined_runes[:2]
            profile["common_runes"] = combined_runes[:2]
            changed = True
            imported_build_data = True

        # 4. Guardar Objetos Iniciales (Starter Items)
        if parsed.get("starter_items"):
            profile["starter_items"] = parsed["starter_items"]
            changed = True

        # 5. Guardar Hechizos de Invocador (Summoner Spells)
        if parsed.get("summoner_spells"):
            profile["summoner_spells"] = parsed["summoner_spells"]
            changed = True

        # 6. Guardar Objetos Situacionales (Corta curas, Tanque, Asesino, Utilidad)
        if parsed.get("situational_items"):
            profile["situational_items"] = parsed["situational_items"]
            changed = True
            
        # 7. Guardar Matchups
        if len(matchups.get("counters", [])) >= 3 and len(matchups.get("good_against", [])) >= 3:
            profile["matchups"] = matchups
            changed = True

        # 8. Guardar Desglose Exacto de Daño (% AD, % AP, % True) desde Lolalytics
        dmg_breakdown = self._scrape_damage_breakdown(slug, role, str(html_build) if html_build else None)
        if dmg_breakdown:
            profile["damage_breakdown"] = dmg_breakdown
            changed = True

        # 9. Guardar Gráfica de Poder (Win Rate vs Game Length) desde Lolalytics
        power_curve = self._scrape_winrate_vs_game_length(slug, role, str(html_build) if html_build else None)
        if power_curve:
            profile["win_rate_vs_game_length"] = power_curve
            changed = True

        if not changed or not imported_build_data:
            return False

        profile["ugg_last_updated"] = datetime.now(timezone.utc).isoformat()
        return True

    def _scrape_winrate_vs_game_length(self, slug: str, role: str, html_content: str | None = None) -> list[dict[str, Any]]:
        try:
            if not html_content:
                soup = self._lolalytics_page(slug, role, "build")
                html_content = str(soup) if soup else ""

            if html_content:
                m = re.search(r'<script type="qwik/json">(.*?)</script>', html_content, re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    objs = data.get("objs", [])
                    
                    def decode_val(x):
                        if isinstance(x, str):
                            try:
                                idx = int(x, 36)
                                if 0 <= idx < len(objs):
                                    return objs[idx]
                            except Exception:
                                pass
                        return x

                    target_dict = None
                    for obj in objs:
                        if isinstance(obj, dict):
                            keys = list(obj.keys())
                            if 'emerald' in keys or 'diamond_plus' in keys or 'all' in keys:
                                v_ref = obj.get('emerald') or obj.get('diamond_plus') or obj.get('all')
                                dv = decode_val(v_ref)
                                if isinstance(dv, list) and len(dv) >= 30:
                                    resolved = [decode_val(x) for x in dv]
                                    if all(isinstance(x, (int, float)) for x in resolved) and all(30 <= x <= 70 for x in resolved):
                                        target_dict = obj
                                        break
                    if target_dict:
                        arr_ref = target_dict.get('emerald') or target_dict.get('diamond_plus') or target_dict.get('all')
                        raw_35 = [decode_val(x) for x in decode_val(arr_ref)]
                        if len(raw_35) >= 35:
                            b0_15  = round(sum(raw_35[0:15]) / 15, 2)
                            b15_20 = round(sum(raw_35[15:20]) / 5, 2)
                            b20_25 = round(sum(raw_35[20:25]) / 5, 2)
                            b25_30 = round(sum(raw_35[25:30]) / 5, 2)
                            b30_35 = round(sum(raw_35[30:35]) / 5, 2)
                            b35_40 = round(raw_35[34], 2)
                            b40_plus = round(raw_35[34], 2)
                            return [
                                {"label": "0-15", "winrate": b0_15},
                                {"label": "15-20", "winrate": b15_20},
                                {"label": "20-25", "winrate": b20_25},
                                {"label": "25-30", "winrate": b25_30},
                                {"label": "30-35", "winrate": b30_35},
                                {"label": "35-40", "winrate": b35_40},
                                {"label": "40+", "winrate": b40_plus},
                            ]
        except Exception:
            pass
        return []

    _PERK_NAMES = {
        # Precision
        8005: "Press the Attack", 8008: "Lethal Tempo", 8021: "Fleet Footwork", 8010: "Conqueror",
        9111: "Triumph", 8009: "Presence of Mind", 9104: "Legend: Alacrity", 9103: "Legend: Bloodline",
        9105: "Legend: Haste", 9102: "Legend: Bloodline", 8014: "Coup de Grace", 8017: "Cut Down", 8299: "Last Stand",
        # Domination
        8112: "Electrocute", 8128: "Dark Harvest", 9923: "Hail of Blades", 8126: "Cheap Shot",
        8139: "Taste of Blood", 8143: "Sudden Impact", 8137: "Sixth Sense", 8135: "Treasure Hunter",
        8105: "Relentless Hunter", 8106: "Ultimate Hunter", 8140: "Eyeball Collection", 8136: "Zombie Ward", 8120: "Ghost Poro",
        # Sorcery
        8214: "Summon Aery", 8229: "Arcane Comet", 8230: "Phase Rush", 8224: "Nullifying Orb", 8226: "Manaflow Band",
        8275: "Nimbus Cloak", 8210: "Transcendence", 8234: "Celerity", 8233: "Absolute Focus", 8237: "Scorch",
        8232: "Waterwalking", 8236: "Gathering Storm",
        # Inspiration
        8351: "Glacial Augment", 8360: "Unsealed Spellbook", 8369: "First Strike", 8306: "Hextech Flashtraption",
        8304: "Magical Footwear", 8321: "Cash Back", 8313: "Triple Tonic", 8352: "Time Warp Tonic", 8345: "Biscuit Delivery",
        8347: "Cosmic Insight", 8316: "Jack of All Trades", 8358: "Approach Velocity",
        # Resolve
        8437: "Grasp of the Undying", 8439: "Aftershock", 8465: "Guardian", 8446: "Demolish", 8463: "Font of Life",
        8401: "Shield Bash", 8429: "Conditioning", 8444: "Second Wind", 8473: "Bone Plating", 8451: "Overgrowth",
        8453: "Revitalize", 8242: "Unflinching",
        # Stat Shards
        5001: "Health Scaling", 5002: "Armor", 5003: "Magic Resist", 5005: "Attack Speed",
        5007: "Ability Haste", 5008: "Adaptive Force", 5010: "Movement Speed", 5011: "Health", 5013: "Tenacity and Slow Resist"
    }

    @staticmethod
    def _get_perk_tree(perk_id: int) -> str:
        if perk_id in [8005, 8008, 8021, 8010, 9111, 8009, 9104, 9103, 9105, 9102, 8014, 8017, 8299]:
            return "Precision"
        if perk_id in [8112, 8128, 9923, 8126, 8139, 8143, 8137, 8135, 8105, 8106, 8140, 8136, 8120]:
            return "Domination"
        if perk_id in [8214, 8229, 8230, 8224, 8226, 8275, 8210, 8234, 8233, 8237, 8232, 8236]:
            return "Sorcery"
        if perk_id in [8351, 8360, 8369, 8306, 8304, 8321, 8313, 8352, 8345, 8347, 8316, 8358]:
            return "Inspiration"
        if perk_id in [8437, 8439, 8465, 8446, 8463, 8401, 8429, 8444, 8473, 8451, 8453, 8242]:
            return "Resolve"
        return "Precision"

    def _scrape_lolalytics_runes(self, slug: str, role: str, html_content: str | None = None) -> dict[str, Any] | None:
        """Extrae la página de runas #1 de Lolalytics en Esmeralda+."""
        try:
            if not html_content:
                soup = self._lolalytics_page(slug, role, "build")
                html_content = str(soup) if soup else ""

            if html_content:
                m = re.search(r'<script type="qwik/json">(.*?)</script>', html_content, re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    objs = data.get("objs", [])

                    def decode_val(x):
                        if isinstance(x, str):
                            try:
                                idx = int(x, 36)
                                if 0 <= idx < len(objs):
                                    return objs[idx]
                            except Exception:
                                pass
                        return x

                    for i, obj in enumerate(objs):
                        if isinstance(obj, dict) and 'pri' in obj and 'sec' in obj:
                            perk_list = []
                            for offset in range(1, 20):
                                if i + offset < len(objs):
                                    val = decode_val(objs[i+offset])
                                    if isinstance(val, int) and (8000 <= val <= 9999 or 5000 <= val <= 5015):
                                        perk_list.append(val)

                            if len(perk_list) >= 8:
                                games = 0
                                win_rate = 0.0
                                for offset in range(-5, 15):
                                    if 0 <= i + offset < len(objs):
                                        item = decode_val(objs[i+offset])
                                        if isinstance(item, dict) and 'wr' in item and 'n' in item:
                                            games = decode_val(item['n']) or 0
                                            win_rate = decode_val(item['wr']) or 0.0
                                            break

                                keystone_id = perk_list[0]
                                primary_tree = self._get_perk_tree(keystone_id)
                                primary_slots = [self._PERK_NAMES.get(p, str(p)) for p in perk_list[1:4]]

                                sec_perks = perk_list[4:6]
                                sec_tree = self._get_perk_tree(sec_perks[0]) if sec_perks else "Resolve"
                                if sec_tree == primary_tree and len(sec_perks) > 1:
                                    sec_tree = self._get_perk_tree(sec_perks[1])

                                sec_slots = [self._PERK_NAMES.get(p, str(p)) for p in sec_perks]
                                raw_shards = [self._PERK_NAMES.get(p, str(p)) for p in perk_list[6:]]
                                if len(raw_shards) == 2:
                                    stat_shards = [raw_shards[0], raw_shards[0], raw_shards[1]]
                                else:
                                    stat_shards = raw_shards[:3]

                                return {
                                    "name": "Página 2 Lolalytics",
                                    "source": "Lolalytics",
                                    "primary_tree": primary_tree,
                                    "secondary_tree": sec_tree,
                                    "keystone": self._PERK_NAMES.get(keystone_id, str(keystone_id)),
                                    "slots": primary_slots,
                                    "secondary_slots": sec_slots,
                                    "shards": stat_shards,
                                    "win_rate": float(win_rate) / 100.0 if win_rate > 1 else float(win_rate),
                                    "games": int(games) if isinstance(games, (int, float)) else 0
                                }
        except Exception:
            pass
        return None

    def _scrape_damage_breakdown(self, slug: str, role: str, html_content: str | None = None) -> dict[str, float]:
        try:
            if not html_content:
                soup = self._lolalytics_page(slug, role, "build")
                html_content = str(soup) if soup else ""

            if html_content:
                m_phys = re.search(r'"physicalDamage",\s*(\d+(?:\.\d+)?)', html_content)
                m_magic = re.search(r'"magicDamage",\s*(\d+(?:\.\d+)?)', html_content)
                m_true = re.search(r'"trueDamage",\s*(\d+(?:\.\d+)?)', html_content)

                phys_val = float(m_phys.group(1)) if m_phys else 0.0
                magic_val = float(m_magic.group(1)) if m_magic else 0.0
                true_val = float(m_true.group(1)) if m_true else 0.0

                tot = phys_val + magic_val + true_val
                if tot > 0:
                    phys_pct = round((phys_val / tot) * 100.0, 1)
                    magic_pct = round((magic_val / tot) * 100.0, 1)
                    true_pct = round(max(0.0, 100.0 - phys_pct - magic_pct), 1)
                    return {
                        "physical_damage_percent": phys_pct,
                        "magic_damage_percent": magic_pct,
                        "true_damage_percent": true_pct,
                    }
        except Exception:
            pass
        return {}

    @staticmethod
    def _valid_rune_pages(value: Any) -> bool:
        if not isinstance(value, list) or not value:
            return False
        for page in value[:2]:
            if not ChampionScraperService._valid_rune_page(page):
                return False
        return True

    @staticmethod
    def _valid_rune_page(page: Any) -> bool:
        if not isinstance(page, dict):
            return False
        slots, secondary = page.get("slots"), page.get("secondary_slots")
        return (isinstance(slots, list) and len(slots) == 3
                and isinstance(secondary, list) and len(secondary) == 2
                and page.get("keystone") not in slots
                and page.get("primary_tree") != page.get("secondary_tree"))

    def actualizar_todo(self, target_champion_name: str = "", progress_callback: Callable[[int, int, str], None] | None = None, stop_check: Callable[[], bool] | None = None) -> tuple[int, int]:
        champions = json.loads(self.champions_path.read_text(encoding="utf-8"))
        target = self._slug(target_champion_name) if target_champion_name else ""
        selected = [x for x in champions if not target or self._slug(str(x.get("character", ""))) == target]
        updated = 0
        for index, profile in enumerate(selected, 1):
            if stop_check and stop_check():
                break
            if progress_callback:
                progress_callback(index, len(selected), str(profile.get("character", "Campeón")))
            updated += int(self.update_champion(profile))
            profile["matchups"] = self._clean_matchups(profile.get("matchups"), self._role(profile))
            if index < len(selected):
                time.sleep(self.request_delay)
        self.champions_path.write_text(json.dumps(champions, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(selected), updated


if __name__ == "__main__":
    print(ChampionScraperService().actualizar_todo())