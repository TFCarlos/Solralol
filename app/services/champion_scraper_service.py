"""Sincronización de builds, runas y matchups públicos desde U.GG."""
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
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"})
        self._live_patches: list[str] | None = None
        root = self.champions_path.parent
        catalog = json.loads((root / "champion_catalog.json").read_text(encoding="utf-8"))
        self.champion_ids = {str(value.get("name", "")).casefold(): int(value["key"]) for value in catalog.get("data", {}).values() if value.get("key")}
        self.champion_names = {int(value["key"]): str(value.get("name", "")) for value in catalog.get("data", {}).values() if value.get("key")}
        items = json.loads((root / "items.json").read_text(encoding="utf-8"))
        self.item_names = {str(item_id): str(value.get("name", item_id)) for item_id, value in items.get("items", {}).items()}
        self.boot_item_names = {
            str(value.get("name", "")).casefold() for value in items.get("items", {}).values()
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
        """Obtiene primero el parche vivo, sin depender del catÃ¡logo local.

        U.GG publica la temporada como 26.xx; otras fuentes aÃºn pueden usar
        16.xx. Se prueban ambos formatos para el mismo nÃºmero de parche.
        """
        if self._live_patches is not None:
            return self._live_patches
        values: list[str] = []
        data = self._get_json("https://ddragon.leagueoflegends.com/api/versions.json")
        if isinstance(data, list) and data:
            match = re.match(r"(\d+)\.(\d+)", str(data[0]))
            if match:
                major, minor = match.groups()
                values.extend((f"26.{minor}", f"{major}.{minor}"))
        # Fallbacks only; the live result is always tried first.
        values.extend(("26.18", "16.18", "26.17", "16.17"))
        self._live_patches = list(dict.fromkeys(values))
        return self._live_patches

    def _overview(self, champion_id: int) -> Any | None:
        """Lee el JSON público que alimenta la página de build de U.GG."""
        # U.GG rota versiones con cada parche. Probamos las vigentes y una
        # basada en el catálogo local para que el scraper no quede acoplado.
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

    def _parse_overview(self, data: Any, role: str) -> dict[str, Any]:
        pd = self._position_data(data, role)
        if not isinstance(pd, list):
            return {}
        result: dict[str, Any] = {}
        core = pd[3] if len(pd) > 3 else []
        core_ids = core[2] if isinstance(core, list) and len(core) > 2 else []
        # U.GG puede poner botas al inicio. Continúa recorriendo el bloque
        # de compra hasta reunir tres objetos reales de power spike.
        item_ids = self._ids(core_ids)
        # El bloque siguiente de U.GG contiene los objetos de continuación
        # (el cuarto/quinto item), necesarios cuando el core incluye botas.
        item_names = [self.item_names[str(item_id)] for item_id in item_ids
                      if str(item_id) in self.item_names]
        if len(item_names) >= 3:
            result["items"] = item_names[:3]
        # pd[0] is U.GG's one visible Recommended rune page. Its nested
        # arrays are rune rows, not separate presets. Stat shards are pd[8][2].
        perks = pd[0] if pd else []
        if isinstance(perks, list) and len(perks) >= 5:
            primary, secondary = perks[2], perks[3]
            perk_ids = self._flat_perks(perks[4])
            shard_ids = self._ids(pd[8][2]) if len(pd) > 8 and isinstance(pd[8], list) and len(pd[8]) > 2 else []
            if isinstance(primary, int) and isinstance(secondary, int):
                page = self._rune_page(primary, secondary, perk_ids + shard_ids)
                if self._valid_rune_page(page):
                    games, wins = perks[0], perks[1]
                    page["name"] = "Recommended · U.GG"
                    page["win_rate"] = round(float(wins) / float(games), 4) if isinstance(games, (int, float)) and games and isinstance(wins, (int, float)) else 0.0
                    page["games"] = int(games) if isinstance(games, (int, float)) else 0
                    result["runes"] = [page]
        return result
        # pd[0] contiene las páginas de perks. Extraemos las dos primeras
        # variantes completas, no una página inventada ni IDs sin traducir.
        pages = []
        seen_pages: set[tuple[Any, ...]] = set()
        candidates = self._perk_candidates(pd[0]) if pd else []
        for candidate in candidates:
            if not isinstance(candidate, list) or len(candidate) < 5:
                continue
            primary, secondary = candidate[2], candidate[3]
            perk_ids = self._flat_perks(candidate[4])
            if not isinstance(primary, int) or not isinstance(secondary, int) or len(perk_ids) < 6:
                continue
            page = self._rune_page(primary, secondary, perk_ids)
            games, wins = candidate[0], candidate[1]
            signature = (page.get("keystone"), *page.get("slots", []), page.get("secondary_tree"), *page.get("secondary_slots", [])) if page else ()
            if self._valid_rune_page(page) and signature not in seen_pages and isinstance(games, (int, float)) and games:
                # Presets are ordered as displayed by U.GG: Recommended first,
                # followed by build variants (for example AP).
                page["name"] = "Recommended · U.GG" if not pages else "AP · U.GG"
                page["win_rate"] = round(float(wins) / float(games), 4) if isinstance(wins, (int, float)) else 0.0
                page["games"] = int(games)
                pages.append(page)
                seen_pages.add(signature)
        if self._valid_rune_pages(pages):
            result["runes"] = pages[:2]
        return result

    def _item_ids_in_order(self, value: Any) -> list[int]:
        """Lee IDs de objetos del bloque variable de U.GG en orden."""
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
        """Encuentra variantes de página sin asumir una profundidad concreta."""
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
        names = {8005: "Press the Attack", 8008: "Lethal Tempo", 8021: "Fleet Footwork", 8010: "Conqueror", 8112: "Electrocute", 8128: "Dark Harvest", 9923: "Hail of Blades", 8214: "Summon Aery", 8229: "Arcane Comet", 8230: "Phase Rush", 8437: "Grasp of the Undying", 8439: "Aftershock", 8465: "Guardian", 8351: "Glacial Augment", 8360: "Unsealed Spellbook", 8369: "First Strike", 9111: "Triumph", 8009: "Presence of Mind", 9104: "Legend: Alacrity", 9103: "Legend: Tenacity", 9102: "Legend: Bloodline", 8014: "Coup de Grace", 8017: "Cut Down", 8299: "Last Stand", 8126: "Cheap Shot", 8139: "Taste of Blood", 8143: "Sudden Impact", 8137: "Sixth Sense", 8135: "Treasure Hunter", 8105: "Relentless Hunter", 8233: "Absolute Focus", 8210: "Transcendence", 8226: "Manaflow Band", 8236: "Gathering Storm", 8232: "Waterwalking", 8446: "Demolish", 8444: "Second Wind", 8473: "Bone Plating", 8451: "Overgrowth", 8453: "Revitalize", 8242: "Unflinching", 8304: "Magical Footwear", 8345: "Biscuit Delivery", 8347: "Cosmic Insight"}
        if primary not in trees or secondary not in trees:
            return None
        readable = [names.get(value, str(value)) for value in perks]
        primary_runes = readable[:4]
        return {"keystone": primary_runes[0], "primary_tree": trees[primary], "slots": primary_runes[1:4], "secondary_tree": trees[secondary], "secondary_slots": readable[4:6], "shards": readable[6:9]}

    def _lolalytics(self, endpoint: str, slug: str, role: str) -> Any | None:
        """Fuente estructurada de respaldo para los datos que U.GG no publica.

        U.GG aporta su build principal; este endpoint aporta las dos variantes
        de runas y la tabla de enfrentamientos con muestras, que U.GG sólo
        renderiza en HTML protegido.
        """
        local = json.loads((self.champions_path.parent / "champion_catalog.json").read_text(encoding="utf-8")).get("version", "16.17")
        local_patch = str(local).rsplit(".", 1)[0]
        patches = [*self._patches(), local_patch]
        lane = {"mid": "middle", "adc": "bottom"}.get(role, role)
        for patch in dict.fromkeys(patches):
            url = "https://a1.lolalytics.com/mega/"
            params = {"ep": endpoint, "v": "1", "patch": patch, "c": slug, "tier": "e_plus", "queue": "ranked", "region": "all", "lane": lane}
            try:
                response = self.session.get(url, params=params, timeout=20)
                if response.status_code == 200:
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
        result: dict[str, Any] = {}
        summary = rune_data.get("summary", {}) if isinstance(rune_data, dict) else {}
        pages = []
        for label, variant in (("Más jugada", summary.get("runes", {}).get("pick")), ("Mayor winrate", summary.get("runes", {}).get("win"))):
            if not isinstance(variant, dict):
                continue
            page = self._rune_page_from_set({**variant.get("set", {}), "page": variant.get("page", {})})
            if page and page not in pages:
                page["name"] = label
                page["win_rate"] = float(variant.get("wr", 0) or 0) / (100 if float(variant.get("wr", 0) or 0) > 1 else 1)
                page["games"] = int(variant.get("n", 0) or 0)
                pages.append(page)
        if pages:
            result["runes"] = pages[:2]
        sets = build_data.get("itemSets", {}) if isinstance(build_data, dict) else {}
        # Cada itemSet es una combinación distinta. Se conserva el orden del
        # set principal y se continúa por los siguientes si las botas ocupan
        # una posición, hasta reunir siempre tres objetos no-botas.
        item_ids: list[str] = []
        ordered_sets = [sets[name] for name in ("itemSet5", "itemSet4", "itemSet3", "itemSet2", "itemSet1") if name in sets]
        ordered_sets.extend(value for name, value in sets.items() if name not in {"itemSet5", "itemSet4", "itemSet3", "itemSet2", "itemSet1"})
        for entries in ordered_sets:
            for entry in entries if isinstance(entries, list) else []:
                raw = entry[0] if isinstance(entry, list) and entry else entry
                for item_id in str(raw).split("_"):
                    if item_id in self.item_names and item_id not in item_ids:
                        item_ids.append(item_id)
        item_names = self._without_boots([self.item_names[item_id] for item_id in item_ids])
        if len(item_names) >= 3:
            result["items"] = item_names[:3]
        counters = counter_data.get("counters", []) if isinstance(counter_data, dict) else []
        parsed = []
        for row in counters:
            if not isinstance(row, dict) or int(row.get("n", 0) or 0) <= 0:
                continue
            champion = self.champion_names.get(int(row.get("cid", 0) or 0))
            if not champion:
                continue
            rate = float(row.get("vsWr", 0) or 0)
            rate = rate / 100 if rate > 1 else rate
            parsed.append({"champion": champion, "win_rate": rate, "overall_win_rate": rate, "lane_games": int(row.get("n", 0)), "overall_games": int(row.get("n", 0)), "primary_role": role.title(), "tip": "Estadísticas actuales de enfrentamiento por línea."})
        if len(parsed) >= 6:
            parsed.sort(key=lambda x: x["win_rate"])
            result["matchups"] = {"counters": parsed[:3], "good_against": parsed[-3:][::-1], "summary": {"primary_role": role.title(), "lane_win_rate": float(counter_data.get("stats", {}).get("wr", 0.5) or 0.5) / (100 if float(counter_data.get("stats", {}).get("wr", 0.5) or 0.5) > 1 else 1), "lane_total_games": int(counter_data.get("stats", {}).get("analysed", 0) or 0), "overall_win_rate": float(counter_data.get("stats", {}).get("wr", 0.5) or 0.5) / (100 if float(counter_data.get("stats", {}).get("wr", 0.5) or 0.5) > 1 else 1), "overall_total_games": int(counter_data.get("stats", {}).get("analysed", 0) or 0)}}
        return result

    def _lolalytics_page(self, slug: str, role: str, section: str = "build") -> BeautifulSoup | None:
        lane = {"mid": "middle", "adc": "bottom"}.get(role, role)
        return self._get(f"https://lolalytics.com/lol/{slug}/{section}/?lane={lane}")

    def _parse_lolalytics_html(self, soup: BeautifulSoup, champion: str, role: str) -> dict[str, Any]:
        """Fallback SSR: Lolalytics entrega el HTML completo incluso cuando
        su endpoint JSON interno cambia de versión."""
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
            # Descarta los selectores de la web (muestran todos los keystones)
            # y conserva sólo una configuración que contiene sus tres ranuras.
            if any(value in keystones for value in perks[1:4]):
                continue
            page = self._rune_page(self._tree_for_perks(perks[:4]), self._tree_for_perks(perks[4:6], 1), perks)
            signature = tuple(perks)
            if page and signature not in seen_pages:
                page["name"] = "Más jugada" if not pages else "Mayor winrate"
                pages.append(page)
                seen_pages.add(signature)
            if len(pages) == 2:
                break
        if pages:
            output["runes"] = pages
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        rows = []
        # El HTML SSR expone cada tarjeta como: "Gnar 46.08 % VS …
        # 102 Games vs Gnar". Sólo aceptamos nombres existentes en el catálogo:
        # así un texto explicativo nunca puede acabar como nombre de campeón.
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
        # U.GG identifica sus iconos como "The Rune …", "The Keystone …"
        # y "The Rune Tree …". Es más estable que sus clases CSS ofuscadas.
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
                # El texto de la tarjeta contiene estadísticas y explicaciones;
                # el slug del enlace es la única fuente válida del campeón.
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
        """Impone el esquema estricto y descarta texto accidental de HTML."""
        if not isinstance(matchups, dict):
            return {}
        canonical = {self._slug(name): name for name in self.champion_names.values()}

        def resolve(value: Any) -> str:
            raw = str(value or "")
            if direct := canonical.get(self._slug(raw)):
                return direct
            # Compatibilidad con JSON ya contaminado: el rival real aparece
            # en el patrón final "Games vs <campeón>".
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
        # La fuente estructurada complementa los huecos de U.GG: dos páginas
        # de runas, builds completos y counters con número de partidas.
        # U.GG es la fuente de verdad: los respaldos sólo rellenan huecos;
        # nunca pueden sustituir sus runas o su build.
        for source in (supplemental, html_data):
            for key, value in source.items():
                # U.GG has priority, but its JSON is periodically protected
                # by Cloudflare. In that case use a complete Lolalytics page;
                # do not leave the previous, unrelated page in the profile.
                if value and key not in parsed:
                    parsed[key] = value
        # El HTML es sólo respaldo: U.GG protege esta ruta con Cloudflare en
        # algunas redes, mientras stats2.u.gg es el feed de datos real.
            # El bloque visible "Core Items" es la combinación recomendada
            # de U.GG y tiene prioridad frente al agregado del endpoint.
        counter_page = self._get(f"https://u.gg/lol/champions/{slug}/counter/{role}")
        matchups = self._clean_matchups(
            html_data.get("matchups") or supplemental.get("matchups") or (self._parse_matchups(counter_page, role) if counter_page else {}), role
        )
        # Una actualización válida debe respetar por completo el contrato del
        # JSON: core de 3 objetos, DOS páginas de runas y ambos grupos de 3.
        # The three Core Items shown by U.GG are authoritative, including
        # boots when U.GG places them in that exact combination.
        items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        changed = False
        imported_build_data = False
        if len(items) >= 3:
            profile.setdefault("power_curve_and_scaling", {})["power_spike_items"] = items
            changed = True
            imported_build_data = True
        if self._valid_rune_pages(parsed.get("runes")):
            profile["common_runes"] = parsed["runes"][:2]
            changed = True
            imported_build_data = True
        if len(matchups.get("counters", [])) >= 3 and len(matchups.get("good_against", [])) >= 3:
            profile["matchups"] = matchups
            changed = True
        # Counters alone must not make the button report a successful build
        # sync: that hid failures to fetch either rune source.
        if not changed or not imported_build_data:
            return False
        profile["ugg_last_updated"] = datetime.now(timezone.utc).isoformat()
        return True

    @staticmethod
    def _valid_rune_pages(value: Any) -> bool:
        """Evita guardar selecciones agregadas/rotas como páginas de runas."""
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
            # Repara también descargas de versiones anteriores, incluso si la
            # fuente actual no devuelve suficientes datos para una actualización.
            profile["matchups"] = self._clean_matchups(profile.get("matchups"), self._role(profile))
            if index < len(selected):
                time.sleep(self.request_delay)
        self.champions_path.write_text(json.dumps(champions, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(selected), updated


if __name__ == "__main__":
    print(ChampionScraperService().actualizar_todo())
