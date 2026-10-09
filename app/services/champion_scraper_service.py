"""Sincronización de builds, runas y matchups públicos desde U.GG y Lolalytics."""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from _paths import DATA_DIR
from app.services.calidad_muestra import (
    UMBRAL_MUESTRA_NORMAL,
    EstadoMuestra,
    clasificar_muestra,
)
from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.rangos_campeones import (
    OPCIONES_RANGO,
    POR_CLAVE,
    RANGO_PREDETERMINADO,
    normalizar_rango,
)
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones

_ROLE = {
    "top": "top",
    "jungle": "jungle",
    "mid": "mid",
    "middle": "mid",
    "adc": "adc",
    "bot": "adc",
    "bottom": "adc",
    "support": "support",
    "utility": "support",
}
#: Nombre que espera `flex_potential` en los perfiles para cada línea normalizada.
_ROLE_NAMES = {
    "top": "Top",
    "jungle": "Jungle",
    "mid": "Mid",
    "adc": "ADC",
    "support": "Support",
}
_TREES = {"Precision", "Domination", "Sorcery", "Resolve", "Inspiration"}
#: Muestra mínima por tramo de duración / por línea para publicar un winrate.
#: Por debajo de estos umbrales un porcentaje es ruido estadístico (p. ej. 100% con 1 partida).
_MIN_CURVE_GAMES = 20
_MIN_LANE_GAMES = UMBRAL_MUESTRA_NORMAL
_KEYSTONES = {
    "Press the Attack",
    "Lethal Tempo",
    "Fleet Footwork",
    "Conqueror",
    "Electrocute",
    "Dark Harvest",
    "Hail of Blades",
    "Arcane Comet",
    "Summon Aery",
    "Phase Rush",
    "Stormraider's Surge",
    "Deathfire Touch",
    "Grasp of the Undying",
    "Aftershock",
    "Guardian",
    "Glacial Augment",
    "First Strike",
    "Unsealed Spellbook",
}


class SinMuestraFuente(ValueError):
    """Indica descarga válida sin combinaciones con muestra suficiente."""


class ChampionScraperService:
    """No usa APIs privadas de U.GG; interpreta las páginas públicas visibles."""

    def __init__(
        self,
        champions_path: Path | None = None,
        request_delay: float = 0.8,
        rank: str = RANGO_PREDETERMINADO,
    ) -> None:
        """Inicializa proveedor remoto con raíz local y rango; retorna None."""
        self.champions_path = champions_path or DATA_DIR / "champion_data"
        self.repositorio = RepositorioCampeones(self.champions_path)
        self.request_delay = max(0.0, request_delay)
        self.rank = normalizar_rango(rank) or RANGO_PREDETERMINADO
        self.session = requests.Session()
        self.session.headers.update(
            {
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
            }
        )
        self._live_patches: list[str] | None = None
        # U.GG sirve todos los rangos y líneas en un único JSON por campeón, así que
        # se memoizan: la matriz rango x línea completa sale de dos descargas.
        self._overview_cache: dict[int, Any] = {}
        self._builds_cache: dict[int, Any] = {}
        self._archetype_cache: dict[tuple[int, str], Any] = {}
        self._versiones_fuente: dict[str, str] = {}
        self._errores_parciales: list[str] = []
        root = self.champions_path.parent
        catalog = json.loads(
            (root / "champion_catalog.json").read_text(encoding="utf-8")
        )
        self.champion_ids = {
            str(value.get("name", "")).casefold(): int(value["key"])
            for value in catalog.get("data", {}).values()
            if value.get("key")
        }
        self.champion_names = {
            int(value["key"]): str(value.get("name", ""))
            for value in catalog.get("data", {}).values()
            if value.get("key")
        }
        items = json.loads((root / "items.json").read_text(encoding="utf-8"))
        self.items_data = items.get("items", {})
        self.item_names = {
            str(item_id): str(value.get("name", item_id))
            for item_id, value in self.items_data.items()
        }
        self.boot_item_names = {
            str(value.get("name", "")).casefold()
            for value in self.items_data.values()
            if "Boots" in value.get("tags", [])
        }

    @staticmethod
    def _slug(name: str) -> str:
        aliases = {
            "wukong": "monkeyking",
            "nunu & willump": "nunu",
            "nunu y willump": "nunu",
            "dr. mundo": "drmundo",
            "jarvan iv": "jarvaniv",
            "aurelion sol": "aurelionsol",
            "cho'gath": "chogath",
            "kai'sa": "kaisa",
            "kha'zix": "khazix",
            "kog'maw": "kogmaw",
            "rek'sai": "reksai",
            "vel'koz": "velkoz",
            "k'sante": "ksante",
        }
        clean = name.strip().lower()
        return aliases.get(clean, re.sub(r"[^a-z0-9]", "", clean))

    @staticmethod
    def _loly_slug(slug: str) -> str:
        """Lolalytics usa slugs distintos a Data Dragon para algunos campeones."""
        return {"monkeyking": "wukong", "renataglasc": "renata"}.get(slug, slug)

    @staticmethod
    def _role(profile: dict[str, Any]) -> str:
        flex = profile.get("basic_info", {}).get("flex_potential", [])
        raw = flex[0] if isinstance(flex, list) and flex else "mid"
        return _ROLE.get(str(raw).lower(), "mid")

    def _get(self, url: str) -> BeautifulSoup | None:
        try:
            response = self.session.get(url, timeout=20)
            return (
                BeautifulSoup(response.content, "html.parser")
                if response.status_code == 200
                else None
            )
        except requests.RequestException:
            return None

    def _get_json(self, url: str, headers: dict[str, str] | None = None) -> Any | None:
        try:
            response = self.session.get(url, timeout=20, headers=headers)
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
        """Lee el JSON público que alimenta la página de build de U.GG.

        Trae todos los rangos y todas las líneas a la vez, por eso se memoiza
        para no repetir la descarga al recorrer la matriz rango x línea.
        """
        if champion_id in self._overview_cache:
            return self._overview_cache[champion_id]
        local_version = json.loads(
            (self.champions_path.parent / "champion_catalog.json").read_text(
                encoding="utf-8"
            )
        ).get("version", "")
        patches = [patch.replace(".", "_") for patch in self._patches()]
        patches.append(str(local_version).rsplit(".", 1)[0].replace(".", "_"))
        patch_base = self._versiones_fuente.get("U.GG overview")
        if patch_base:
            patches = [patch_base.replace(".", "_")]
        for patch in dict.fromkeys(patches):
            for version in ("1.5.0", "1.4.0"):
                url = f"https://stats2.u.gg/lol/1.5/overview/{patch}/ranked_solo_5x5/{champion_id}/{version}.json"
                data = self._get_json(url)
                if data:
                    self._overview_cache[champion_id] = data
                    self._versiones_fuente["U.GG overview"] = patch.replace("_", ".")
                    return data
        return None

    def _without_build_items(
        self,
        situational: dict[str, Any],
        *build_lists: Any,
    ) -> dict[str, list[str]]:
        """Quita de los situacionales los objetos que ya se compran en la build.

        OP.GG, U.GG y Lolalytics no coinciden en la build final, así que el filtro
        se aplica al final, con la build definitiva ya resuelta.
        """
        excluded: set[str] = set()
        for names in build_lists:
            if isinstance(names, list):
                excluded.update(str(name).strip().casefold() for name in names)

        result: dict[str, list[str]] = {}
        for key, names in situational.items() if isinstance(situational, dict) else []:
            if not isinstance(names, list):
                continue
            kept = [
                str(name)
                for name in names
                if str(name).strip().casefold() not in excluded
            ]
            if kept:
                result[str(key)] = kept
        return result

    def _position_entry(self, data: Any, role: str) -> list[Any] | None:
        """Bloques completos de la posición pedida para el rango actual.

        U.GG usa claves string: región '12', posiciones '1'..'5', rangos '1'..'17'.
        El primer bloque son los grupos de runas; los siguientes, hechizos,
        objetos iniciales, core, orden de habilidades, botas y complementos.
        """
        if not isinstance(data, dict):
            return None
        region = data.get("12")
        if not isinstance(region, dict):
            return None
        position = {
            "jungle": "1",
            "support": "2",
            "adc": "3",
            "top": "4",
            "mid": "5",
        }.get(role, "5")
        bucket = region.get(POR_CLAVE[self.rank].ugg)
        if isinstance(bucket, dict):
            entry = bucket.get(position)
            if isinstance(entry, list) and entry:
                return entry
        return None

    def _position_blocks(self, data: Any, role: str) -> list[Any] | None:
        """Bloques de la posición pedida para el rango actual (o la primera con datos).

        U.GG usa claves string: región '12', posiciones '1'..'5', rangos '1'..'17'.
        """
        entry = self._position_entry(data, role)
        if not isinstance(entry, list) or not entry:
            return None
        blocks = entry[0]
        if isinstance(blocks, list) and blocks:
            return blocks
        return None

    def _position_data(self, data: Any, role: str) -> Any | None:
        """Compatibilidad: devuelve el primer bloque de la posición pedida."""
        return self._position_blocks(data, role)

    def _builds(self, champion_id: int) -> Any | None:
        """Lee el JSON público de builds de U.GG (contiene todas las páginas de runas).

        Igual que `_overview`, trae todos los rangos y líneas, así que se memoiza.
        """
        if champion_id in self._builds_cache:
            return self._builds_cache[champion_id]
        local_version = json.loads(
            (self.champions_path.parent / "champion_catalog.json").read_text(
                encoding="utf-8"
            )
        ).get("version", "")
        patches = [patch.replace(".", "_") for patch in self._patches()]
        patches.append(str(local_version).rsplit(".", 1)[0].replace(".", "_"))
        headers = {"Referer": "https://u.gg/"}
        patch_base = self._versiones_fuente.get("U.GG overview")
        if patch_base:
            patches = [patch_base.replace(".", "_")]
        for patch in dict.fromkeys(patches):
            for version in ("1.5.0", "1.4.0"):
                url = f"https://stats2.u.gg/lol/1.5/builds/{patch}/ranked_solo_5x5/{champion_id}/{version}.json"
                data = self._get_json(url, headers=headers)
                if data:
                    self._builds_cache[champion_id] = data
                    self._versiones_fuente["U.GG builds"] = patch.replace("_", ".")
                    return data
        return None

    #: Arquetipos de build que publica U.GG, con su endpoint propio. Cada uno trae
    #: runas, build, orden de habilidades y objetos situacionales YA emparejados.
    #: (El endpoint `builds` general no los empareja; ver `_archetype_overview`.)
    _UGG_ARCHETYPES: tuple[tuple[str, str], ...] = (
        ("", "Recommended"),
        ("lethality-", "Letalidad"),
        ("ap-", "AP"),
        ("ad-", "AD"),
        ("tank-", "Tanque"),
        ("crit-", "Crítico"),
        ("onhit-", "On-hit"),
    )

    #: Un arquetipo se publica solo con muestra decente: por debajo de esto el
    #: winrate es ruido y no merece una página propia.
    _ARCHETYPE_MIN_GAMES = 200

    def _archetype_overview(self, champion_id: int, kind: str) -> Any | None:
        """Descarga el JSON de un arquetipo (`overview`, `lethality-overview`, ...).

        A diferencia del endpoint `builds`, este SÍ trae la build emparejada con las
        runas de ese arquetipo (bloques: runas, hechizos, iniciales, core, skills...).
        """
        key = (champion_id, kind)
        if key in self._archetype_cache:
            return self._archetype_cache[key]
        local_version = json.loads(
            (self.champions_path.parent / "champion_catalog.json").read_text(
                encoding="utf-8"
            )
        ).get("version", "")
        patches = [patch.replace(".", "_") for patch in self._patches()]
        patches.append(str(local_version).rsplit(".", 1)[0].replace(".", "_"))
        headers = {"Referer": "https://u.gg/"}
        # `kind` es el prefijo: "" da "overview", "lethality-" da "lethality-overview".
        endpoint = f"{kind}overview"
        patch_base = self._versiones_fuente.get("U.GG overview")
        if patch_base:
            patches = [patch_base.replace(".", "_")]
        for patch in dict.fromkeys(patches):
            for version in ("1.5.0", "1.4.0"):
                url = f"https://stats2.u.gg/lol/1.5/{endpoint}/{patch}/ranked_solo_5x5/{champion_id}/{version}.json"
                data = self._get_json(url, headers=headers)
                if data:
                    self._archetype_cache[key] = data
                    self._versiones_fuente[f"U.GG {kind}overview"] = patch.replace(
                        "_", "."
                    )
                    return data
        return None

    def _archetype_page(
        self, data: Any, role: str, label: str
    ) -> dict[str, Any] | None:
        """Convierte un arquetipo de U.GG en página de runas con SU build real.

        Cada bloque del endpoint es ``[partidas, victorias, datos...]``: runas,
        hechizos, objetos iniciales, core, orden de habilidades y opciones.
        """
        blocks = self._position_blocks(data, role)
        if not isinstance(blocks, list) or len(blocks) < 4:
            return None

        rune_block = blocks[0]
        if not (isinstance(rune_block, list) and len(rune_block) >= 5):
            return None
        games, wins = rune_block[0], rune_block[1]
        primary_tree, secondary_tree, perks = (
            rune_block[2],
            rune_block[3],
            rune_block[4],
        )
        if not isinstance(games, (int, float)) or games <= 0:
            return None
        if not isinstance(perks, list):
            return None

        page = self._rune_page(primary_tree, secondary_tree, perks)
        if not page or not self._valid_rune_page(page):
            return None

        page["name"] = f"Página · {label}"
        page["source"] = f"U.GG {label}"
        page["win_rate"] = round(float(wins) / float(games), 4)
        page["games"] = int(games)
        page["sample_status"] = clasificar_muestra(
            games, True, self._ARCHETYPE_MIN_GAMES
        ).value
        page["sample_threshold"] = self._ARCHETYPE_MIN_GAMES

        # Objetos iniciales (bloque 2) y core (bloque 3).
        starters = self._ids_to_names(blocks[2][2] if len(blocks) > 2 else None)
        core = self._ids_to_names(blocks[3][2] if len(blocks) > 3 else None)
        if starters:
            page["starter_items"] = starters
        if core:
            page["power_spike_items"] = core[:3]

        # Orden de habilidades propio del arquetipo (bloque 4).
        if (
            len(blocks) > 4
            and isinstance(blocks[4], list)
            and isinstance(blocks[4][2], list)
        ):
            order = [
                str(v).upper()
                for v in blocks[4][2]
                if str(v).upper() in {"Q", "W", "E", "R"}
            ]
            if order:
                priority = (
                    blocks[4][3]
                    if len(blocks[4]) > 3 and isinstance(blocks[4][3], str)
                    else ""
                )
                page["skill_order"] = {
                    "order": order,
                    "priority": str(priority).upper(),
                }

        if core:
            page["build"] = list(core[:3])
        options: dict[str, list[dict[str, Any]]] = {}
        if len(blocks) > 5 and isinstance(blocks[5], list):
            for slot, choices in enumerate(blocks[5][:3], start=4):
                if not isinstance(choices, list):
                    continue
                slot_options = []
                for choice in choices:
                    if not isinstance(choice, list) or len(choice) < 3:
                        continue
                    item_id, wins, games = choice[:3]
                    if (
                        str(item_id) not in self.item_names
                        or not isinstance(games, (int, float))
                        or games <= 0
                    ):
                        continue
                    slot_options.append(
                        {
                            "item_id": int(item_id),
                            "name": self.item_names[str(item_id)],
                            "slot": slot,
                            "wins": int(wins),
                            "games": int(games),
                            "win_rate": round(float(wins) / float(games), 4)
                            if isinstance(wins, (int, float))
                            else None,
                        }
                    )
                if slot_options:
                    options[str(slot)] = slot_options
        if options:
            page["item_options"] = options
        return page

    def _ugg_archetype_pages(self, champion_id: int, role: str) -> list[dict[str, Any]]:
        """Páginas de runas de U.GG, cada una con la build REAL de su arquetipo.

        Varios arquetipos comparten las mismas runas y se diferencian solo en los
        objetos (Recommended vs Letalidad en Aatrox, por ejemplo), así que la
        deduplicación es por build, no por runas.
        """
        pages: list[dict[str, Any]] = []
        seen: set[tuple[str, ...]] = set()
        for kind, label in self._UGG_ARCHETYPES:
            data = self._archetype_overview(champion_id, kind)
            if not data:
                continue
            page = self._archetype_page(data, role, label)
            if not page:
                continue
            signature = tuple(sorted(page.get("build", [])))
            if not signature or signature in seen:
                continue
            seen.add(signature)
            pages.append(page)

        pages.sort(key=lambda page: int(page.get("games") or 0), reverse=True)

        # Si el endpoint overview trae shard_ids globales, poblar shards si faltan
        overview = self._overview(champion_id)
        if overview:
            parsed = self._parse_overview(overview, role)
            shard_ids = parsed.get("shard_ids") if isinstance(parsed, dict) else None
            if isinstance(shard_ids, list) and shard_ids:
                shards = [
                    self._PERK_NAMES.get(value, str(value)) for value in shard_ids[:3]
                ]
                for page in pages:
                    referencia = next(
                        (
                            candidato
                            for candidato in parsed.get("runes", [])
                            if isinstance(candidato, dict)
                            and candidato.get("games") == page.get("games")
                            and candidato.get("keystone_id") == page.get("keystone_id")
                        ),
                        None,
                    )
                    if referencia:
                        page["shards"] = shards
                        page["shard_ids"] = list(shard_ids[:3])
                    elif not page.get("shards"):
                        page["shards"] = shards

        return pages

    def _ids_to_names(self, ids: Any) -> list[str]:
        """Traduce una lista de ids de objeto a nombres del catálogo."""
        if not isinstance(ids, list):
            return []
        return [
            self.item_names[str(value)]
            for value in ids
            if str(value) in self.item_names
        ]

    def _starter_item_entries(self, item_ids: list[int]) -> list[dict[str, Any]]:
        """Agrupa objetos iniciales repetidos y conserva su cantidad y orden.

        Parámetros:
            item_ids: IDs canónicos en el orden recibido de la fuente.

        Retorna:
            Entradas únicas con nombre, ID y cantidad observada.
        """
        cantidades: dict[int, int] = {}
        for item_id in item_ids:
            cantidades[item_id] = cantidades.get(item_id, 0) + 1
        return [
            {
                "item_id": item_id,
                "name": self.item_names[str(item_id)],
                "quantity": cantidad,
            }
            for item_id, cantidad in cantidades.items()
            if str(item_id) in self.item_names
        ]

    def _situational_ids(self, block: Any) -> list[str]:
        """Objeto más jugado de cada ranura del bloque de opciones.

        Cada ranura es ``[[id, ganadas, partidas], ...]`` y las ranuras vacías son
        listas: se ignoran. Se toma la opción con más partidas de cada ranura.
        """
        if not isinstance(block, list):
            return []
        chosen: list[str] = []
        for slot in block:
            if not isinstance(slot, list):
                continue
            best: tuple[float, str] | None = None
            for option in slot:
                # La opción es plana: [id, ganadas, partidas].
                if not (
                    isinstance(option, list) and option and isinstance(option[0], int)
                ):
                    continue
                item_id = str(option[0])
                if item_id not in self.item_names or not self._is_finished_item(
                    item_id
                ):
                    continue
                played = (
                    option[2]
                    if len(option) > 2 and isinstance(option[2], (int, float))
                    else 0
                )
                if best is None or float(played) > best[0]:
                    best = (float(played), item_id)
            if best is not None and best[1] not in chosen:
                chosen.append(best[1])
        return [self.item_names[item_id] for item_id in chosen]

    @staticmethod
    def _is_rune_group(node: Any) -> bool:
        """Comprueba si un nodo del endpoint `builds` es un grupo de páginas de runas."""
        return (
            isinstance(node, list)
            and len(node) >= 6
            and isinstance(node[0], int)
            and isinstance(node[2], (int, float))
            and isinstance(node[3], (int, float))
            and isinstance(node[4], int)
            and isinstance(node[5], list)
        )

    #: Una segunda página se conserva con una muestra positiva y relativa al
    #: arquetipo principal; su confianza se comunica en la propia página.
    #: No se exige que mejore el winrate: U.GG muestra las dos páginas más
    #: jugadas aunque la segunda rinda igual o peor.
    _MIN_ALT_GAMES = 1
    _MIN_ALT_RATIO = 0.02

    def _ugg_rune_pages(
        self, builds: Any, role: str, shards: list[int] | None = None
    ) -> list[dict[str, Any]]:
        """Devuelve las páginas de runas reales de U.GG para una línea y un rango.

        El endpoint ``builds`` agrupa por keystone: cada grupo es
        ``[keystone, rama secundaria, victorias, partidas, rama principal, [variantes]]``
        y cada variante ``[rama principal, rama secundaria, [6 runas], victorias, partidas]``.

        Se aplanan todas las variantes y se agrupan por *arquetipo* (keystone +
        árbol principal + árbol secundario) para quedarse con la variante más
        jugada de cada uno. La segunda página solo aparece si ese arquetipo rival
        tiene volumen suficiente y un winrate claramente mejor; si no, se publica
        una única página, porque una build marginal no es una segunda build.
        """
        shards = shards if isinstance(shards, list) else []
        blocks = self._position_blocks(builds, role)
        if not isinstance(blocks, list):
            return []
        groups = [row for row in blocks if self._is_rune_group(row)]
        if not groups and blocks and isinstance(blocks[0], list):
            groups = [row for row in blocks[0] if self._is_rune_group(row)]

        best: dict[tuple[str, str, str], dict[str, Any]] = {}
        for group in groups:
            if not (
                isinstance(group, list)
                and len(group) >= 6
                and isinstance(group[5], list)
            ):
                continue
            for variant in group[5]:
                if not (
                    isinstance(variant, list)
                    and len(variant) >= 5
                    and isinstance(variant[2], list)
                ):
                    continue
                wins, games = variant[3], variant[4]
                if (
                    not isinstance(wins, (int, float))
                    or not isinstance(games, (int, float))
                    or games <= 0
                ):
                    continue
                perks = self._flat_perks(variant[2])
                if len(perks) < 6:
                    continue
                page = self._rune_page(variant[0], variant[1], perks)
                if not page or not self._valid_rune_page(page):
                    continue
                signature = (
                    str(page["keystone"]),
                    str(page["primary_tree"]),
                    str(page["secondary_tree"]),
                )
                current = best.get(signature)
                if current is not None and games <= current["games"]:
                    continue
                if shards and len(page.get("shards") or []) < 3:
                    page["shards"] = [
                        self._PERK_NAMES.get(value, str(value)) for value in shards[:3]
                    ]
                best[signature] = {
                    "page": page,
                    "wins": float(wins),
                    "games": float(games),
                }

        if not best:
            return []

        def finalize(entry: dict[str, Any], name: str) -> dict[str, Any]:
            page = dict(entry["page"])
            page["win_rate"] = round(entry["wins"] / entry["games"], 4)
            page["games"] = int(entry["games"])
            page["name"] = name
            page["source"] = "U.GG"
            page["sample_status"] = clasificar_muestra(
                entry["games"], True, self._ARCHETYPE_MIN_GAMES
            ).value
            page["sample_threshold"] = self._ARCHETYPE_MIN_GAMES
            return page

        candidates = sorted(
            best.values(), key=lambda entry: entry["games"], reverse=True
        )
        pages = [finalize(candidates[0], "Página 1 U.GG")]
        # La segunda página es el siguiente arquetipo por volumen, no el de mejor
        # winrate: U.GG muestra las dos páginas más jugadas aunque la segunda tenga
        # un WR igual o menor. Solo se descarta si su muestra es ruido estadístico.
        floor = max(
            float(self._MIN_ALT_GAMES), candidates[0]["games"] * self._MIN_ALT_RATIO
        )
        alternatives = [entry for entry in candidates[1:] if entry["games"] >= floor]
        if alternatives:
            runner_up = max(alternatives, key=lambda entry: entry["games"])
            pages.append(finalize(runner_up, "Página 2 U.GG"))
        return pages

    def _lane_stats(self, overview: Any) -> dict[str, dict[str, Any]]:
        """Winrate y partidas por línea del rango actual (bloque ``[partidas, victorias, hechizos]``)."""
        stats: dict[str, dict[str, Any]] = {}
        region = overview.get("12") if isinstance(overview, dict) else None
        if not isinstance(region, dict):
            return stats
        bucket = region.get(POR_CLAVE[self.rank].ugg)
        if not isinstance(bucket, dict):
            return stats
        for position, lane in (
            ("1", "jungle"),
            ("2", "support"),
            ("3", "adc"),
            ("4", "top"),
            ("5", "mid"),
        ):
            entry = bucket.get(position)
            blocks = entry[0] if isinstance(entry, list) and entry else None
            summary = (
                blocks[6] if isinstance(blocks, list) and len(blocks) > 6 else None
            )
            if not (isinstance(summary, list) and len(summary) >= 2):
                continue
            wins, games = summary[0], summary[1]
            if (
                not isinstance(games, (int, float))
                or not games
                or not isinstance(wins, (int, float))
            ):
                continue
            stats[lane] = {
                "win_rate": round(float(wins) / float(games), 4),
                "games": int(games),
                "sample_status": clasificar_muestra(games, True, _MIN_LANE_GAMES).value,
                "sample_threshold": _MIN_LANE_GAMES,
            }
        return stats

    #: Claves que forman una variante (línea + rango) mostrable en la UI.
    _VARIANT_FIELDS = (
        "runes",
        "common_runes",
        "most_played_build",
        "starter_items",
        "starter_item_entries",
        "summoner_spells",
        "situational_items",
        "matchups",
        "damage_breakdown",
        "win_rate_vs_game_length",
        "lane_stats",
        "skill_order",
        "overall_matches",
        "overall_win_rate",
        "section_sample_sizes",
        "section_status",
        "source_patch",
        "patch_label",
        "item_options",
        "situational_item_pipeline",
        "core_build",
        "core_build_matches",
        "core_build_win_rate",
        "skill_priority_matches",
        "skill_priority_win_rate",
        "starting_item_matches",
        "starting_item_win_rate",
        "summoner_spell_matches",
        "summoner_spell_win_rate",
        "summoner_spell_ids",
        "starter_item_ids",
        "starting_items_source_status",
        "starting_items_provenance",
        "rune_page_matches",
    )

    def fetch_variant(self, profile: dict[str, Any], role: str) -> dict[str, Any]:
        """Descarga runas, ítems, matchups y curva de un campeón para una línea del rango actual."""
        role_key = _ROLE.get(str(role).lower(), "mid")
        variant = copy.deepcopy(profile)
        for campo in self._VARIANT_FIELDS:
            variant.pop(campo, None)
        variant.setdefault("power_curve_and_scaling", {}).pop("power_spike_items", None)
        basic = variant.setdefault("basic_info", {})
        basic["flex_potential"] = [_ROLE_NAMES[role_key]]
        updated = self.update_champion(variant)
        scaling = variant.get("power_curve_and_scaling")
        data: dict[str, Any] = {
            "role": role_key,
            "rank": self.rank,
            "updated": bool(updated),
            "power_spike_items": scaling.get("power_spike_items")
            if isinstance(scaling, dict)
            else None,
        }
        for field in self._VARIANT_FIELDS:
            if variant.get(field) is not None:
                data[field] = variant[field]
        return data

    @contextmanager
    def _for_rank(self, rank: str) -> Iterator[None]:
        """Cambia temporalmente al rango compatible recibido y devuelve un contexto reversible."""
        previous = self.rank
        compatible = normalizar_rango(rank)
        if compatible is None:
            raise ValueError("Rango no compatible")
        self.rank = compatible
        try:
            yield
        finally:
            self.rank = previous

    def fetch_matrix(
        self,
        profile: dict[str, Any],
        progress_callback: Callable[[int, int, str], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
        min_games: int = _MIN_LANE_GAMES,
    ) -> dict[str, Any]:
        """Genera líneas disponibles para los seis rangos compatibles del campeón.

        Devuelve ``{"rank": {"line": {..variante..}}}`` listo para persistir en el JSON
        del campeón. ``min_games`` clasifica la confianza; toda muestra positiva se
        conserva para que los datos de baja frecuencia sigan siendo consultables.

        Las dos descargas grandes de U.GG (`overview` y `builds`) cubren todos los
        rangos y líneas a la vez y están memoizadas, así que el coste real está en las
        fuentes que sí dependen de la combinación (OP.GG y Lolalytics).
        """
        name = str(profile.get("character", "")).strip()
        if not name:
            return {}

        matrix: dict[str, Any] = {}
        self._errores_parciales = []
        ranks = [key for key, _ in OPCIONES_RANGO]
        overview = self._overview(self.champion_ids.get(name.casefold() or ""))
        if not isinstance(overview, dict) or not isinstance(overview.get("12"), dict):
            raise TypeError("No se pudieron descargar las estadísticas del campeón")
        total = len(ranks)
        for rank_index, rank_key in enumerate(ranks, 1):
            if stop_check and stop_check():
                break
            rank_label = dict(OPCIONES_RANGO).get(rank_key, rank_key)
            if progress_callback:
                progress_callback(rank_index, total, f"{name} · {rank_label}")
            with self._for_rank(rank_key):
                stats = self._lane_stats(overview)
                lanes = [
                    lane
                    for lane, entry in stats.items()
                    if isinstance(entry, dict) and int(entry.get("games") or 0) > 0
                ]
                if not lanes:
                    # Sin muestra por línea en este rango: se conserva el resumen de WR
                    # por línea para que el selector siga siendo informativo.
                    if stats:
                        matrix[rank_key] = {
                            "__lane_stats__": {"rank": rank_key, "lanes": stats}
                        }
                    else:
                        matrix[rank_key] = {}
                    continue
                block: dict[str, Any] = {}
                if stats:
                    block["__lane_stats__"] = {"rank": rank_key, "lanes": stats}
                for lane in lanes:
                    if stop_check and stop_check():
                        break
                    muestra = stats.get(lane, {}).get("games")
                    muestra_valida = isinstance(muestra, (int, float)) and muestra > 0
                    try:
                        variant = self.fetch_variant(profile, lane)
                    except (
                        ValueError,
                        TypeError,
                        KeyError,
                        IndexError,
                        OSError,
                        requests.RequestException,
                    ) as error:
                        self._errores_parciales.append(f"{rank_key}/{lane}: {error}")
                        consulta_previa = self.repositorio.consultar(
                            name, lane, rank_key
                        )
                        variant = copy.deepcopy(consulta_previa.datos or {})
                        patch_actual = self._versiones_fuente.get("U.GG overview")
                        if patch_actual and variant.get("source_patch") != patch_actual:
                            variant = {}
                        variant.update(
                            {"role": lane, "rank": rank_key, "updated": True}
                        )
                        if not variant:
                            variant = {"role": lane, "rank": rank_key, "updated": True}
                        variant["lane_stats"] = {
                            "rank": rank_key,
                            "lanes": copy.deepcopy(stats),
                        }
                        variant["data_status"] = EstadoMuestra.PARTIAL_DATA.value
                        variant["overall_matches"] = (
                            int(muestra) if muestra_valida else None
                        )
                        variant["overall_win_rate"] = stats.get(lane, {}).get(
                            "win_rate"
                        )
                        variant["sample_size"] = (
                            int(muestra) if muestra_valida else None
                        )
                        variant["sample_status"] = (
                            EstadoMuestra.LOW_SAMPLE.value
                            if muestra_valida and muestra < min_games
                            else EstadoMuestra.NORMAL_SAMPLE.value
                            if muestra_valida
                            else EstadoMuestra.PARTIAL_DATA.value
                        )
                    estado_iniciales = str(
                        variant.get("starting_items_source_status") or "NOT_PROVIDED"
                    )
                    if estado_iniciales in {"NOT_PROVIDED", "PARTIAL_DATA"}:
                        parche_nuevo = str(
                            variant.get("source_patch")
                            or self._versiones_fuente.get("U.GG overview")
                            or ""
                        )
                        consulta_previa = self.repositorio.consultar(
                            name, lane, rank_key
                        )
                        anterior = consulta_previa.datos or {}
                        parche_anterior = str(anterior.get("source_patch") or "")
                        if (
                            parche_nuevo
                            and parche_nuevo == parche_anterior
                            and anterior.get("starter_items")
                        ):
                            for campo in (
                                "starter_items",
                                "starter_item_ids",
                                "starter_item_entries",
                                "starting_item_matches",
                                "starting_item_win_rate",
                                "starting_items_provenance",
                            ):
                                if campo in anterior:
                                    variant[campo] = copy.deepcopy(anterior[campo])
                            variant["starting_items_source_status"] = "AVAILABLE"
                            variant.setdefault("section_status", {})[
                                "starting_items"
                            ] = "AVAILABLE"
                    if variant.get("updated") is not True and not muestra_valida:
                        raise ValueError(f"No se pudo generar {name}/{lane}/{rank_key}")
                    if muestra_valida:
                        variant["updated"] = True
                    variant["overall_matches"] = muestra if muestra_valida else None
                    variant["overall_win_rate"] = stats.get(lane, {}).get("win_rate")
                    secciones = any(
                        variant.get(campo)
                        for campo in (
                            "runes",
                            "most_played_build",
                            "matchups",
                            "summoner_spells",
                            "skill_order",
                            "starter_items",
                        )
                    )
                    estado = clasificar_muestra(muestra, secciones)
                    variant["sample_size"] = muestra
                    variant["sample_status"] = (
                        estado.value
                        if estado
                        not in {EstadoMuestra.PARTIAL_DATA, EstadoMuestra.NO_DATA}
                        else (
                            EstadoMuestra.LOW_SAMPLE.value
                            if muestra_valida and muestra < min_games
                            else EstadoMuestra.NORMAL_SAMPLE.value
                            if muestra_valida
                            else EstadoMuestra.NO_DATA.value
                        )
                    )
                    variant["data_status"] = estado.value
                    variant["sample_threshold"] = min_games
                    variant["section_sample_sizes"] = {
                        "overall": muestra,
                        "champion_lane": muestra,
                        "runes": [
                            int(pagina["games"])
                            for pagina in variant.get("runes", [])
                            if isinstance(pagina, dict)
                            and isinstance(pagina.get("games"), int)
                        ],
                        "summoner_spells": variant.get("summoner_spell_matches"),
                        "skill_priority": variant.get("skill_priority_matches"),
                        "starting_items": variant.get("starting_item_matches"),
                        "core_build": variant.get("core_build_matches"),
                    }
                    variant["source_patch"] = self._versiones_fuente.get(
                        "U.GG overview"
                    )
                    variant["retrieved_at"] = datetime.now(timezone.utc).isoformat()
                    if secciones or muestra_valida:
                        block[lane] = variant
                    if stop_check is None:
                        time.sleep(self.request_delay)
                if block:
                    matrix[rank_key] = block
        if stop_check and stop_check():
            raise InterruptedError("Actualización cancelada")
        return matrix

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
        return (
            item.get("gold", {}).get("total", 0) >= 1400
            or "Depth3" in tags
            or "Legendary" in tags
        )

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

        if (
            str(item_id) in self._ANTIHEAL_IDS
            or "heridas graves" in description
            or "grievous wounds" in description
        ):
            return "corta_curas"
        if (
            "Armor" in tags
            or "SpellBlock" in tags
            or stats.get("FlatArmorMod", 0) > 0
            or stats.get("FlatSpellBlockMod", 0) > 0
            or stats.get("FlatHPPoolMod", 0) >= 350
        ):
            return "tanque"
        if (
            "ArmorPenetration" in tags
            or "MagicPenetration" in tags
            or "lethality" in description
            or stats.get("FlatPhysicalDamageMod", 0) >= 50
            or stats.get("FlatMagicDamageMod", 0) >= 70
        ):
            return "asesino"
        return "utilidad_y_defensa"

    def _parse_opgg(self, slug: str, role: str) -> dict[str, Any]:
        """Obtiene build remoto para campeón y línea recibidos usando el filtro OP.GG actual."""
        result: dict[str, Any] = {}
        lane = {
            "mid": "mid",
            "adc": "adc",
            "top": "top",
            "jungle": "jungle",
            "support": "support",
        }.get(role, role)
        url = f"https://lol-api-champion.op.gg/api/global/champions/ranked/{slug}/{lane}?tier={POR_CLAVE[self.rank].opgg}"
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

        core_ids = [
            str(i)
            for i in (
                cores[0].get("ids", []) if cores and isinstance(cores[0], dict) else []
            )
            if self._is_finished_item(str(i))
        ]
        boot_ids = [
            str(i)
            for i in (
                boots[0].get("ids", []) if boots and isinstance(boots[0], dict) else []
            )
            if self._is_finished_item(str(i))
        ]

        if boot_ids:
            boot_entry = boots[0] if boots and isinstance(boots[0], dict) else {}
            boot_games = boot_entry.get("play") or boot_entry.get("games")
            boot_wins = boot_entry.get("win") or boot_entry.get("wins")
            result["boots"] = [
                {
                    "item_id": item_id,
                    "name": self.item_names[item_id],
                    "origin": "OP.GG",
                    "source": "OP.GG",
                    "rank": self.rank,
                    "lane": role,
                    "games": int(boot_games)
                    if isinstance(boot_games, (int, float))
                    else None,
                    "win_rate": round(float(boot_wins) / float(boot_games), 4)
                    if isinstance(boot_games, (int, float))
                    and boot_games > 0
                    and isinstance(boot_wins, (int, float))
                    else None,
                }
                for item_id in boot_ids
                if item_id in self.item_names
            ]

        full_ids: list[str] = []
        for i in core_ids:
            if i not in full_ids:
                full_ids.append(i)
        if boot_ids and boot_ids[0] not in full_ids:
            full_ids.append(boot_ids[0])
        for entry in lasts if isinstance(lasts, list) else []:
            if isinstance(entry, dict):
                for i in [str(x) for x in entry.get("ids", [])]:
                    if i not in full_ids and self._is_finished_item(i):
                        full_ids.append(i)
                    if len(full_ids) >= 6:
                        break
            if len(full_ids) >= 6:
                break

        core_names = [self.item_names[i] for i in core_ids[:3] if i in self.item_names]
        if core_names:
            result["items"] = core_names[:3]

        if starters and isinstance(starters, list) and isinstance(starters[0], dict):
            s_ids = starters[0].get("ids", [])
            starter_names = [
                self.item_names[str(i)] for i in s_ids if str(i) in self.item_names
            ]
            if starter_names:
                result["starter_items"] = starter_names

        if spells and isinstance(spells, list) and isinstance(spells[0], dict):
            sp_ids = spells[0].get("ids", [])
            spell_names = [
                self._SUMMONER_SPELLS.get(i, f"Hechizo {i}")
                for i in sp_ids
                if i in self._SUMMONER_SPELLS
            ]
            if spell_names:
                result["summoner_spells"] = spell_names

        situational: dict[str, list[str]] = {
            "corta_curas": [],
            "tanque": [],
            "asesino": [],
            "utilidad_y_defensa": [],
        }
        # `last_items` de OP.GG incluye los objetos de la propia build final: un objeto
        # que ya se compra no es "situacional", así que se excluye para que las dos
        # tarjetas no muestren lo mismo.
        build_ids = {str(item_id) for item_id in core_ids}
        build_ids.update(str(item_id) for item_id in full_ids)
        if starters and isinstance(starters[0], dict):
            build_ids.update(str(value) for value in starters[0].get("ids", []))
        for entry in lasts if isinstance(lasts, list) else []:
            if isinstance(entry, dict):
                for i in entry.get("ids", []):
                    sid = str(i)
                    if sid in build_ids:
                        continue
                    if self._is_finished_item(sid) and sid in self.item_names:
                        item_name = self.item_names[sid]
                        cat = self._categorize_situational_item(sid)
                        if (
                            item_name not in situational[cat]
                            and len(situational[cat]) < 4
                        ):
                            situational[cat].append(item_name)

        if any(situational.values()):
            result["situational_items"] = situational

        # Página de runas estándar del rango seleccionado (?tier=...)
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
                trees = {
                    8000: "Precision",
                    8100: "Domination",
                    8200: "Sorcery",
                    8300: "Inspiration",
                    8400: "Resolve",
                }
                result["runes"] = [
                    {
                        "name": "Página 1 OP.GG",
                        "source": "OP.GG",
                        "primary_tree": trees.get(pri_tree_id, "Precision"),
                        "secondary_tree": trees.get(sec_tree_id, "Resolve"),
                        "keystone": self._PERK_NAMES.get(pri_ids[0], str(pri_ids[0])),
                        "slots": [
                            self._PERK_NAMES.get(i, str(i)) for i in pri_ids[1:4]
                        ],
                        "secondary_slots": [
                            self._PERK_NAMES.get(i, str(i)) for i in sec_ids[:2]
                        ],
                        "shards": shards,
                        "win_rate": round(wins / games, 4) if games > 0 else 0.0,
                        "games": games,
                    }
                ]

        return result

    def _normalizar_build_completa(self, nombres: Any) -> list[str]:
        """Normaliza una secuencia de objetos completos y elimina repeticiones accidentales."""
        if not isinstance(nombres, list):
            return []
        ids_por_nombre = {
            nombre.casefold(): item_id for item_id, nombre in self.item_names.items()
        }
        resultado: list[str] = []
        vistos: set[str] = set()
        for valor in nombres:
            nombre = str(valor).strip()
            clave = ids_por_nombre.get(nombre.casefold(), nombre.casefold())
            if not nombre or clave in vistos:
                continue
            vistos.add(clave)
            resultado.append(nombre)
        return resultado[:6]

    def _parse_overview(
        self, data: Any, role: str, champion: str = ""
    ) -> dict[str, Any]:
        """Normaliza bloques U.GG por alcance y conserva los conteos de cada secci\u00f3n."""
        blocks = self._position_blocks(data, role)
        if not isinstance(blocks, list):
            return {}
        result: dict[str, Any] = {}
        if len(blocks) > 6 and isinstance(blocks[6], list) and len(blocks[6]) >= 2:
            wins, games = blocks[6][:2]
            if (
                isinstance(games, (int, float))
                and games > 0
                and isinstance(wins, (int, float))
            ):
                result["overall_matches"] = int(games)
                result["overall_win_rate"] = round(float(wins) / float(games), 4)
        if len(blocks) > 0:
            page_data = blocks[0]
            candidates = self._perk_candidates(page_data)
            pages: list[dict[str, Any]] = []
            for candidate in candidates:
                if len(candidate) < 5 or not isinstance(candidate[4], list):
                    continue
                page = self._rune_page(
                    candidate[2], candidate[3], self._flat_perks(candidate[4])
                )
                games, wins = candidate[0], candidate[1]
                if not page or not isinstance(games, (int, float)) or games <= 0:
                    continue
                page.update(
                    {
                        "name": "Recomendada \u00b7 U.GG",
                        "source": "U.GG",
                        "games": int(games),
                        "win_rate": round(float(wins) / float(games), 4),
                        "sample_status": clasificar_muestra(
                            games, True, self._ARCHETYPE_MIN_GAMES
                        ).value,
                        "sample_threshold": self._ARCHETYPE_MIN_GAMES,
                    }
                )
                page["shard_ids"] = [
                    int(value)
                    for value in (
                        blocks[8][2]
                        if len(blocks) > 8
                        and isinstance(blocks[8], list)
                        and len(blocks[8]) > 2
                        and isinstance(blocks[8][2], list)
                        else []
                    )
                    if str(value).isdigit()
                ][:3]
                page["shards"] = [
                    self._PERK_NAMES.get(value, str(value))
                    for value in page["shard_ids"]
                ]
                page["games"] = int(games)
                pages.append(page)
            if pages:
                result["runes"] = pages[:2]
                result["rune_page_matches"] = pages[0]["games"]
        if len(blocks) > 1 and isinstance(blocks[1], list) and len(blocks[1]) >= 3:
            games, wins, ids = blocks[1][:3]
            if isinstance(ids, list):
                spells = [
                    self._SUMMONER_SPELLS[int(value)]
                    for value in ids
                    if str(value).isdigit() and int(value) in self._SUMMONER_SPELLS
                ]
                if spells:
                    result["summoner_spells"] = spells
                    result["summoner_spell_ids"] = [
                        int(value)
                        for value in ids
                        if str(value).isdigit() and int(value) in self._SUMMONER_SPELLS
                    ]
                    result["summoner_spell_matches"] = (
                        int(games) if isinstance(games, (int, float)) else None
                    )
                    result["summoner_spell_win_rate"] = (
                        round(float(wins) / float(games), 4)
                        if isinstance(games, (int, float))
                        and games > 0
                        and isinstance(wins, (int, float))
                        else None
                    )
        if len(blocks) > 2 and isinstance(blocks[2], list) and len(blocks[2]) >= 3:
            games, wins, ids = blocks[2][:3]
            if isinstance(ids, list):
                starter_ids = [
                    int(value)
                    for value in ids
                    if str(value).isdigit() and str(value) in self.item_names
                ]
                names = self._ids_to_names(starter_ids)
                if names:
                    result["starter_items"] = names
                    result["starter_item_ids"] = starter_ids
                    result["starter_item_entries"] = self._starter_item_entries(
                        starter_ids
                    )
                    result["starting_items_provenance"] = {
                        "source": "U.GG",
                        "rank": self.rank,
                        "lane": role,
                        "patch": self._versiones_fuente.get("U.GG overview"),
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    }
                    result["starting_item_matches"] = (
                        int(games) if isinstance(games, (int, float)) else None
                    )
                    result["starting_item_win_rate"] = (
                        round(float(wins) / float(games), 4)
                        if isinstance(games, (int, float))
                        and games > 0
                        and isinstance(wins, (int, float))
                        else None
                    )
                result["starting_items_source_status"] = (
                    "AVAILABLE" if names else "EMPTY" if not ids else "PARTIAL_DATA"
                )
            else:
                result["starting_items_source_status"] = "PARTIAL_DATA"
        else:
            result["starting_items_source_status"] = "NOT_PROVIDED"
        if len(blocks) > 3 and isinstance(blocks[3], list) and len(blocks[3]) >= 3:
            games, wins, ids = blocks[3][:3]
            normalized_ids = (
                list(
                    dict.fromkeys(
                        str(value)
                        for value in ids
                        if str(value) in self.item_names
                        and self._is_finished_item(str(value))
                    )
                )
                if isinstance(ids, list)
                else []
            )
            names = [self.item_names[value] for value in normalized_ids]
            if names:
                result["core_build"] = [
                    {
                        "item_id": int(value),
                        "name": self.item_names[str(value)],
                        "slot": index + 1,
                    }
                    for index, value in enumerate(normalized_ids)
                    if str(value) in self.item_names
                ]
                botas = [
                    item
                    for item in result["core_build"]
                    if "Boots"
                    in self.items_data.get(str(item["item_id"]), {}).get("tags", [])
                ]
                if botas:
                    result["boots"] = [
                        {
                            **item,
                            "source": "U.GG",
                            "origin": "U.GG",
                            "rank": self.rank,
                            "lane": role,
                            "context": "core_build",
                        }
                        for item in botas
                    ]
                result["items"] = names[:3]
                result["most_played_build"] = self._normalizar_build_completa(names[:3])
                result["core_build_matches"] = (
                    int(games) if isinstance(games, (int, float)) else None
                )
                result["core_build_win_rate"] = (
                    round(float(wins) / float(games), 4)
                    if isinstance(games, (int, float))
                    and games > 0
                    and isinstance(wins, (int, float))
                    else None
                )
        if len(blocks) > 4 and isinstance(blocks[4], list) and len(blocks[4]) >= 3:
            games, wins, order = blocks[4][:3]
            if isinstance(order, list):
                abilities = [
                    str(value).upper()
                    for value in order
                    if str(value).upper() in {"Q", "W", "E", "R"}
                ]
                priority = (
                    str(blocks[4][3]).upper()
                    if len(blocks[4]) > 3 and isinstance(blocks[4][3], str)
                    else ""
                )
                if abilities:
                    result["skill_order"] = {"order": abilities, "priority": priority}
                    result["skill_priority_matches"] = (
                        int(games) if isinstance(games, (int, float)) else None
                    )
                    result["skill_priority_win_rate"] = (
                        round(float(wins) / float(games), 4)
                        if isinstance(games, (int, float))
                        and games > 0
                        and isinstance(wins, (int, float))
                        else None
                    )
        options: dict[str, list[dict[str, Any]]] = {}
        raw_options = (
            blocks[5] if len(blocks) > 5 and isinstance(blocks[5], list) else None
        )
        raw_count = (
            sum(
                len(choices) for choices in raw_options[:3] if isinstance(choices, list)
            )
            if raw_options is not None
            else 0
        )
        parsed_count = 0
        situational_items = {
            "corta_curas": [],
            "tanque": [],
            "asesino": [],
            "utilidad_y_defensa": [],
        }
        if raw_options is not None:
            for offset, choices in enumerate(raw_options[:3], start=4):
                if not isinstance(choices, list):
                    continue
                slot_options = []
                for choice in choices:
                    if not isinstance(choice, list) or len(choice) < 3:
                        continue
                    item_id, wins, games = choice[:3]
                    if (
                        str(item_id) not in self.item_names
                        or not isinstance(games, (int, float))
                        or games <= 0
                    ):
                        continue
                    categoria = self._categorize_situational_item(str(item_id))
                    slot_options.append(
                        {
                            "item_id": int(item_id),
                            "name": self.item_names[str(item_id)],
                            "slot": offset,
                            "wins": int(wins),
                            "games": int(games),
                            "win_rate": round(float(wins) / float(games), 4)
                            if isinstance(wins, (int, float))
                            else None,
                            "source": "U.GG",
                            "source_patch": self._versiones_fuente.get("U.GG overview"),
                            "champion": champion,
                            "lane": role,
                            "rank": self.rank,
                            "situational_category": categoria,
                            "sample_status": clasificar_muestra(
                                games, True, self._ARCHETYPE_MIN_GAMES
                            ).value,
                        }
                    )
                    parsed_count += 1
                    nombre = self.item_names[str(item_id)]
                    if nombre not in situational_items[categoria]:
                        situational_items[categoria].append(nombre)
                if slot_options:
                    options[str(offset)] = slot_options
        if raw_options is not None:
            result["item_options"] = options
            result["situational_items"] = situational_items
            result["situational_item_pipeline"] = {
                "source": "U.GG",
                "source_options": raw_count,
                "parsed": parsed_count,
                "normalized": parsed_count,
                "classified": sum(len(items) for items in situational_items.values()),
                "rank": self.rank,
                "lane": role,
                "patch": self._versiones_fuente.get("U.GG overview"),
            }
        if (
            len(blocks) > 8
            and isinstance(blocks[8], list)
            and len(blocks[8]) > 2
            and isinstance(blocks[8][2], list)
        ):
            result["shard_ids"] = [
                int(value) for value in blocks[8][2] if str(value).isdigit()
            ][:3]
        result["section_sample_sizes"] = {
            key: result.get(value)
            for key, value in {
                "overall": "overall_matches",
                "runes": "rune_page_matches",
                "summoner_spells": "summoner_spell_matches",
                "skill_priority": "skill_priority_matches",
                "starting_items": "starting_item_matches",
                "core_build": "core_build_matches",
            }.items()
            if result.get(value) is not None
        }
        if result.get("item_options"):
            result["section_sample_sizes"]["item_options"] = {
                slot: [item["games"] for item in entries]
                for slot, entries in result["item_options"].items()
            }
        result["section_status"] = {
            "overall": "AVAILABLE" if result.get("overall_matches") else "NOT_PROVIDED",
            "runes": "AVAILABLE" if result.get("runes") else "NOT_PROVIDED",
            "summoner_spells": "AVAILABLE"
            if result.get("summoner_spells")
            else "NOT_PROVIDED",
            "skill_order": "AVAILABLE" if result.get("skill_order") else "NOT_PROVIDED",
            "starting_items": "AVAILABLE"
            if result.get("starter_items")
            else result.get("starting_items_source_status", "NOT_PROVIDED"),
            "core_build": "AVAILABLE" if result.get("core_build") else "NOT_PROVIDED",
            "item_options": "AVAILABLE"
            if result.get("item_options")
            else (
                "EMPTY"
                if len(blocks) > 5 and isinstance(blocks[5], list)
                else "NOT_PROVIDED"
            ),
        }
        return result

    def _item_ids_in_order(self, value: Any) -> list[int]:
        result: list[int] = []

        def visit(node: Any) -> None:
            if (
                isinstance(node, (int, str))
                and str(node).isdigit()
                and str(node) in self.item_names
            ):
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
        if (
            len(value) >= 5
            and isinstance(value[2], int)
            and isinstance(value[3], int)
            and isinstance(value[4], list)
        ):
            found.append(value)
        for child in value:
            found.extend(ChampionScraperService._perk_candidates(child))
        return found

    def _rune_page(
        self, primary: int, secondary: int, perks: list[int]
    ) -> dict[str, Any] | None:
        """Construye una página de runas agrupando sus IDs por árbol.

        El orden de los perks varía según la fuente y el rango, así que la rama
        principal se determina con el keystone y cada grupo se filtra por árbol
        en vez de por posición. `primary`/`secondary` solo se usan de respaldo.
        """
        trees = self._TREE_NAMES
        keystone_id = next((value for value in perks if value in self._KEYSTONE_IDS), 0)
        primary_id = self._PERK_TREE.get(keystone_id, primary)
        if primary_id not in trees:
            return None
        secondary_id = 0
        for value in perks:
            tree = self._PERK_TREE.get(value)
            if tree and tree != primary_id:
                secondary_id = tree
                break
        if not secondary_id and secondary in trees and secondary != primary_id:
            secondary_id = secondary
        if secondary_id not in trees:
            return None
        primary_group = [
            value for value in perks if self._PERK_TREE.get(value) == primary_id
        ]
        secondary_group = [
            value for value in perks if self._PERK_TREE.get(value) == secondary_id
        ]
        if not keystone_id:
            keystone_id = primary_group[0] if primary_group else 0
        slots = [value for value in primary_group if value != keystone_id][:3]
        secondary_slots = [value for value in secondary_group if value != keystone_id][
            :2
        ]
        shards = [value for value in perks if 5000 <= value <= 5015][:3]
        if not keystone_id or len(slots) < 3 or len(secondary_slots) < 2:
            return None
        return {
            "keystone": self._PERK_NAMES.get(keystone_id, str(keystone_id)),
            "keystone_id": keystone_id,
            "primary_tree": trees[primary_id],
            "primary_tree_id": primary_id,
            "slots": [self._PERK_NAMES.get(value, str(value)) for value in slots],
            "slot_ids": slots,
            "secondary_tree": trees[secondary_id],
            "secondary_tree_id": secondary_id,
            "secondary_slots": [
                self._PERK_NAMES.get(value, str(value)) for value in secondary_slots
            ],
            "secondary_slot_ids": secondary_slots,
            "shards": [self._PERK_NAMES.get(value, str(value)) for value in shards],
            "shard_ids": shards,
        }

    def _lolalytics(self, endpoint: str, slug: str, role: str) -> Any | None:
        """Consulta endpoint remoto con campeón, línea y filtro Lolalytics independiente."""
        local = json.loads(
            (self.champions_path.parent / "champion_catalog.json").read_text(
                encoding="utf-8"
            )
        ).get("version", "16.17")
        local_patch = str(local).rsplit(".", 1)[0]
        patches = [*self._patches(), local_patch, ""]
        slug = self._loly_slug(slug)
        lane = {"mid": "middle", "adc": "bottom"}.get(role, role)
        headers = {
            "Referer": "https://lolalytics.com/",
            "Origin": "https://lolalytics.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        }
        for patch in dict.fromkeys(patches):
            url = "https://a1.lolalytics.com/mega/"
            params = {
                "ep": endpoint,
                "v": "1",
                "patch": patch,
                "c": slug,
                "tier": POR_CLAVE[self.rank].lolalytics,
                "queue": "ranked",
                "region": "all",
                "lane": lane,
            }
            expected = {
                "rune": "summary",
                "build-itemset": "itemSets",
                "counter": "counters",
            }.get(endpoint)
            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=12
                )
                if response.status_code == 200 and response.content:
                    payload = response.json()
                    # Ignora errores {"status": 4043,...} y sigue probando otros patches.
                    if isinstance(payload, dict) and (
                        expected is None or expected in payload
                    ):
                        return payload
            except (requests.RequestException, ValueError):
                continue
        return None

    @staticmethod
    def _ids(value: Any) -> list[int]:
        return (
            [
                int(x)
                for x in value
                if isinstance(x, (int, float, str)) and str(x).isdigit()
            ]
            if isinstance(value, list)
            else []
        )

    def _tree_for_perks(self, perks: list[int], fallback: int = 0) -> int:
        for item in perks:
            tree = self._PERK_TREE.get(item)
            if tree:
                return tree
        return (8000, 8100, 8200, 8300, 8400)[fallback % 5]

    def _rune_page_from_set(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        primary, secondary, shards = (
            self._ids(value.get("pri")),
            self._ids(value.get("sec")),
            self._ids(value.get("mod")),
        )
        if len(primary) < 4 or len(secondary) < 2:
            return None
        page = value.get("page", {})
        return self._rune_page(
            self._tree_for_perks(
                primary, int(page.get("pri", 0)) if isinstance(page, dict) else 0
            ),
            self._tree_for_perks(
                secondary, int(page.get("sec", 1)) if isinstance(page, dict) else 1
            ),
            primary + secondary + shards,
        )

    def _parse_lolalytics(
        self,
        rune_data: Any,
        build_data: Any,
        counter_data: Any,
        role: str,
        champion: str = "",
    ) -> dict[str, Any]:
        """Procesa las respuestas JSON de Lolalytics (ep=rune|build-itemset|counter)."""
        output: dict[str, Any] = {}

        # --- Runas: summary.runes.pick (más jugada) y summary.runes.win (mayor WR) ---
        if isinstance(rune_data, dict):
            runes_block = rune_data.get("summary")
            runes_block = (
                runes_block.get("runes") if isinstance(runes_block, dict) else None
            )
            pages: list[dict[str, Any]] = []
            seen: set[tuple[Any, ...]] = set()
            if isinstance(runes_block, dict):
                for key, label in (
                    ("pick", "Más jugada · Lolalytics"),
                    ("win", "Mayor winrate · Lolalytics"),
                ):
                    entry = runes_block.get(key)
                    if not isinstance(entry, dict):
                        continue
                    value = entry.get("set")
                    if isinstance(value, dict) and isinstance(entry.get("page"), dict):
                        value = {**value, "page": entry["page"]}
                    page = self._rune_page_from_set(value)
                    if not page or not self._valid_rune_page(page):
                        continue
                    signature = (
                        page.get("keystone"),
                        tuple(page.get("slots", [])),
                        page.get("secondary_tree"),
                        tuple(page.get("secondary_slots", [])),
                    )
                    if signature in seen:
                        continue
                    seen.add(signature)
                    try:
                        games = int(entry.get("n") or 0)
                    except (TypeError, ValueError):
                        games = 0
                    try:
                        rate = float(entry.get("wr") or 0.0)
                    except (TypeError, ValueError):
                        rate = 0.0
                    page["name"] = label
                    page["source"] = "Lolalytics"
                    page["win_rate"] = (
                        round(rate / 100.0, 4) if rate > 1 else round(rate, 4)
                    )
                    page["games"] = games
                    pages.append(page)
            if pages:
                output["runes"] = pages

        # --- Ítems: itemSets (itemSet3 = core, itemBootSet6 = build completa) ---
        if isinstance(build_data, dict) and isinstance(
            build_data.get("itemSets"), dict
        ):
            sets = build_data["itemSets"]

            def sorted_sets(key: str) -> list[list[Any]]:
                rows = [
                    row
                    for row in sets.get(key, [])
                    if isinstance(row, list) and len(row) >= 3 and str(row[0]).strip()
                ]
                return sorted(
                    rows,
                    key=lambda row: row[1] if isinstance(row[1], (int, float)) else 0,
                    reverse=True,
                )

            for row in sorted_sets("itemSet3"):
                ids = [value for value in str(row[0]).split("_") if value]
                names = [
                    self.item_names[i]
                    for i in ids
                    if i in self.item_names and self._is_finished_item(i)
                ]
                if len(names) >= 3:
                    output["items"] = names[:3]
                    break
            for source_set in ("itemBootSet6", "itemSet5"):
                if output.get("full_build"):
                    break
                for row in sorted_sets(source_set):
                    ids = [value for value in str(row[0]).split("_") if value]
                    names = [
                        self.item_names[i]
                        for i in ids
                        if i in self.item_names and self._is_finished_item(i)
                    ]
                    if len(names) >= 5:
                        output["full_build"] = names[:6]
                        break

        # --- Matchups: counters (cid, vsWr, n por campeón) ---
        if isinstance(counter_data, dict) and isinstance(
            counter_data.get("counters"), list
        ):
            rows: list[dict[str, Any]] = []
            seen_champions: set[str] = set()
            for entry in counter_data["counters"]:
                if not isinstance(entry, dict):
                    continue
                try:
                    enemy_id = int(entry.get("cid"))
                    rate = float(entry.get("vsWr"))
                    games = int(entry.get("n") or 0)
                except (TypeError, ValueError):
                    continue
                enemy = self.champion_names.get(enemy_id)
                if not enemy or enemy in seen_champions or games <= 0:
                    continue
                seen_champions.add(enemy)
                win_rate = rate / 100.0 if rate > 1 else rate
                rows.append(
                    {
                        "champion": enemy,
                        "win_rate": round(win_rate, 4),
                        "overall_win_rate": round(win_rate, 4),
                        "lane_games": games,
                        "overall_games": games,
                        "primary_role": role.title(),
                        "tip": "",
                    }
                )
            usable = [row for row in rows if row["lane_games"] >= 20] or rows
            if len(usable) >= 6:
                good = sorted(usable, key=lambda row: row["win_rate"], reverse=True)[:5]
                hard = sorted(usable, key=lambda row: row["win_rate"])[:5]
                for entry in hard:
                    entry["tip"] = (
                        f"{champion} gana el {entry['win_rate']:.1%} de {entry['lane_games']:,} partidas frente a {entry['champion']}. Juega la fase de líneas con cautela.".replace(
                            ",", "."
                        )
                    )
                for entry in good:
                    entry["tip"] = (
                        f"{champion} gana el {entry['win_rate']:.1%} de {entry['lane_games']:,} partidas frente a {entry['champion']}. Puedes buscar presión en línea.".replace(
                            ",", "."
                        )
                    )
                total_games = sum(row["lane_games"] for row in usable)
                average = sum(row["win_rate"] for row in usable) / len(usable)
                output["matchups"] = {
                    "counters": hard,
                    "good_against": good,
                    "summary": {
                        "total_games_analyzed": total_games,
                        "primary_role": role.title(),
                        "lane_win_rate": average,
                        "lane_total_games": total_games,
                        "overall_win_rate": average,
                        "overall_total_games": total_games,
                    },
                }

        return output

    def _parse_lolalytics_html(
        self, soup: BeautifulSoup, champion: str, role: str
    ) -> dict[str, Any]:
        """
        Extrae la información completa de Lolalytics desde el HTML/Qwik cuando la API falla o da 403.
        Mantiene el parseo completo de Runas (Árboles, Keystone, Slots y Shards), métricas y Objetos.
        """
        output: dict[str, Any] = {}
        raw_html = str(soup)

        # 1. Mapeo extendido de IDs de runas (Keystones, Slots y Shards)
        known_perks = {
            # Keystones
            8005,
            8008,
            8021,
            8010,
            8112,
            8128,
            9923,
            8214,
            8229,
            8230,
            8351,
            8360,
            8369,
            8437,
            8439,
            8465,
            # Slots Principales y Secundarios
            9111,
            8009,
            9104,
            9105,
            9103,
            9102,
            8014,
            8017,
            8299,
            8126,
            8139,
            8143,
            8137,
            8135,
            8105,
            8233,
            8210,
            8226,
            8236,
            8232,
            8446,
            8444,
            8473,
            8451,
            8453,
            8242,
            8304,
            8345,
            8347,
            # Fragmentos / Shards de estadísticas
            5001,
            5002,
            5003,
            5005,
            5007,
            5008,
        }
        keystones = {
            8005,
            8008,
            8021,
            8010,
            8112,
            8128,
            9923,
            8214,
            8229,
            8230,
            8351,
            8360,
            8369,
            8437,
            8439,
            8465,
        }

        # 2. Extracción de IDs (Buscando en imágenes HTML y en el estado Qwik)
        rune_ids = [
            int(x)
            for x in re.findall(
                r"(?:rune|runes|perk)/(\d+)(?:\.png)?", raw_html, re.IGNORECASE
            )
        ]

        if not rune_ids:
            qwik_match = re.search(
                r'<script type="qwik/json">(.*?)</script>', raw_html, re.DOTALL
            )
            if qwik_match:
                # Buscar números aislados dentro del estado Qwik que correspondan a IDs de runas válidos
                found_tokens = re.findall(
                    r"\b(500\d|8\d{3}|9\d{3})\b", qwik_match.group(1)
                )
                rune_ids = [int(x) for x in found_tokens if int(x) in known_perks]

        # 3. Procesamiento de Páginas de Runas Completas (9 perks: 4 Rama Principal + 2 Secundaria + 3 Shards)
        pages = []
        seen_signatures: set[tuple[Any, ...]] = set()

        for index, perk_id in enumerate(rune_ids):
            if perk_id not in keystones:
                continue

            # Tomamos la ventana completa de 9 runas
            perks_window = rune_ids[index : index + 9]
            if len(perks_window) < 9:
                # Intentar fallback si faltan shards
                if len(perks_window) >= 6:
                    perks_window = perks_window[:6] + [5007, 5008, 5001]
                else:
                    continue

            primary_tree = self._tree_for_perks(perks_window[:4])
            secondary_tree = self._tree_for_perks(perks_window[4:6], fallback=1)

            page = self._rune_page(primary_tree, secondary_tree, perks_window)
            if page and self._valid_rune_page(page):
                signature = (
                    page.get("keystone"),
                    tuple(page.get("slots", [])),
                    page.get("secondary_tree"),
                    tuple(page.get("secondary_slots", [])),
                )
                if signature not in seen_signatures:
                    page["name"] = (
                        "Más jugada · Lolalytics"
                        if not pages
                        else "Mayor winrate · Lolalytics"
                    )
                    pages.append(page)
                    seen_signatures.add(signature)

            if len(pages) == 2:
                break

        if pages:
            output["runes"] = pages

        # 4. Extracción de Ítems / Builds desde HTML
        item_ids = [
            str(x)
            for x in re.findall(r"(?:item|items)/(\d+)\.png", raw_html, re.IGNORECASE)
        ]
        if item_ids:
            valid_items = [
                self.item_names[i]
                for i in item_ids
                if i in self.item_names and self._is_finished_item(i)
            ]
            # Eliminar duplicados manteniendo el orden
            unique_items = list(dict.fromkeys(valid_items))
            if len(unique_items) >= 3:
                output["most_played_build"] = unique_items[:6]

        return output

    def _lolalytics_page(
        self, slug: str, role: str, section: str = "build"
    ) -> BeautifulSoup | None:
        """Consulta sección remota recibida con línea y parámetro Lolalytics del rango actual."""
        lane = {"mid": "middle", "adc": "bottom"}.get(role, role)
        slug = self._loly_slug(slug)
        return self._get(
            f"https://lolalytics.com/lol/{slug}/{section}/?lane={lane}&tier={POR_CLAVE[self.rank].lolalytics}"
        )

    def _parse_lolalytics_html(
        self, soup: BeautifulSoup, champion: str, role: str
    ) -> dict[str, Any]:
        output: dict[str, Any] = {}
        core = self._heading(soup, "core build")
        if core:
            ids = []
            for image in core.find_all_next("img", limit=8):
                match = re.search(
                    r"item\d+/(\d+)", str(image.get("srcset", image.get("src", "")))
                )
                if match and match.group(1) not in ids:
                    ids.append(match.group(1))
            names = [
                self.item_names[item_id]
                for item_id in ids
                if item_id in self.item_names
            ]
            if len(names) >= 3:
                output["items"] = names[:3]
        raw_html = str(soup)
        rune_ids = [int(value) for value in re.findall(r"rune\d+/(\d+)", raw_html)]
        keystones = set(self._KEYSTONE_IDS)
        pages = []
        seen_pages: set[tuple[int, ...]] = set()
        for index, perk_id in enumerate(rune_ids):
            if perk_id not in keystones:
                continue
            perks = rune_ids[index : index + 9]
            if len(perks) < 6:
                continue
            if any(value in keystones for value in perks[1:4]):
                continue
            page = self._rune_page(
                self._tree_for_perks(perks[:4]),
                self._tree_for_perks(perks[4:6], 1),
                perks,
            )
            signature = tuple(perks)
            if page and signature not in seen_pages:
                page["name"] = (
                    "Más jugada · Lolalytics"
                    if not pages
                    else "Mayor winrate · Lolalytics"
                )
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
            rows.append(
                {
                    "champion": enemy,
                    "win_rate": rate,
                    "overall_win_rate": rate,
                    "lane_games": games,
                    "overall_games": games,
                    "primary_role": role.title(),
                    "tip": "",
                }
            )
        if len(rows) >= 10:
            rows.sort(key=lambda row: row["win_rate"])
            average = sum(row["win_rate"] for row in rows) / len(rows)
            counters, good = rows[:5], rows[-5:][::-1]
            for entry in counters:
                entry["tip"] = (
                    f"{champion} gana el {entry['win_rate']:.1%} de {entry['lane_games']:,} partidas frente a {entry['champion']}. Juega la fase de líneas con cautela.".replace(
                        ",", "."
                    )
                )
            for entry in good:
                entry["tip"] = (
                    f"{champion} gana el {entry['win_rate']:.1%} de {entry['lane_games']:,} partidas frente a {entry['champion']}. Puedes buscar presión en línea.".replace(
                        ",", "."
                    )
                )
            total_games = sum(entry["lane_games"] for entry in rows)
            output["matchups"] = {
                "counters": counters,
                "good_against": good,
                "summary": {
                    "total_games_analyzed": total_games,
                    "primary_role": role.title(),
                    "lane_win_rate": average,
                    "lane_total_games": total_games,
                    "overall_win_rate": average,
                    "overall_total_games": total_games,
                },
            }
        return output

    @staticmethod
    def _heading(soup: BeautifulSoup, *names: str) -> Tag | None:
        wanted = set(names)
        return soup.find(
            lambda tag: (
                tag.name in {"h1", "h2", "h3", "div"}
                and tag.get_text(" ", strip=True).lower() in wanted
            )
        )

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
        trees = [
            value for kind, value in rune_labels if kind == "tree" and value in _TREES
        ]
        key_index = next(
            (
                i
                for i, (kind, value) in enumerate(rune_labels)
                if kind == "key" and value in _KEYSTONES
            ),
            -1,
        )
        if len(trees) >= 2 and key_index >= 0:
            minor = [
                value for kind, value in rune_labels[key_index + 1 :] if kind == "rune"
            ]
            data["runes"] = {
                "keystone": rune_labels[key_index][1],
                "primary_tree": trees[0],
                "slots": minor[:3],
                "secondary_tree": next(
                    (x for x in trees[1:] if x != trees[0]), trees[1]
                ),
                "secondary_slots": minor[3:5],
                "shards": [],
            }
        return data

    def _parse_matchups(
        self, soup: BeautifulSoup, role: str, champion: str = ""
    ) -> dict[str, list[dict[str, Any]]]:
        """Extrae los enfrentamientos visibles en U.GG con su tasa y muestra."""
        result: dict[str, list[dict[str, Any]]] = {}
        for field, headings in {
            "counters": ("toughest matchups", "worst matchups"),
            "good_against": ("best matchups", "easiest matchups"),
        }.items():
            section_name = (
                "toughest-matchups" if field == "counters" else "best-matchups"
            )
            section = soup.select_one(f".content-section.{section_name}")
            title = self._heading(soup, *headings)
            if section is None and title is None:
                continue
            rows: list[dict[str, Any]] = []
            links = (
                section.select("a[href]")
                if section is not None
                else title.find_all_next("a", href=True, limit=35)
            )
            for link in links:
                found = re.search(
                    r"/lol/champions/([^/]+)/(?:build|counter)", str(link["href"])
                )
                if not found:
                    continue
                slug = found.group(1)
                name = next(
                    (
                        champion
                        for champion in self.champion_names.values()
                        if self._slug(champion) == slug
                    ),
                    "",
                )
                if not name:
                    continue
                values = re.findall(
                    r"(\d{1,2}(?:\.\d+)?)\s*%",
                    link.get_text(" ", strip=True)
                    or link.parent.get_text(" ", strip=True),
                )
                if not values or any(x["champion"] == name for x in rows):
                    continue
                rate = float(values[0]) / 100
                text_link = link.get_text(" ", strip=True)
                match_count = re.search(r"([\d.,]+)\s+Matches?\b", text_link)
                games = (
                    int(match_count.group(1).replace(",", "").replace(".", ""))
                    if match_count
                    else 0
                )
                rows.append(
                    {
                        "champion": name,
                        "win_rate": rate,
                        "overall_win_rate": rate,
                        "lane_games": games,
                        "overall_games": games,
                        "primary_role": role.title(),
                        "tip": f"{champion} gana el {rate:.1%} de {games} partidas frente a {name}."
                        if games
                        else "Datos de matchup actualizados desde U.GG.",
                    }
                )
                if len(rows) == 10:
                    break
            if rows:
                result[field] = rows
        return result

    def _clean_matchups(self, matchups: Any, role: str) -> dict[str, Any]:
        """Normaliza nombres y métricas de enfrentamientos sin alterar tasas de cero."""
        if not isinstance(matchups, dict):
            return {}
        canonical = {self._slug(name): name for name in self.champion_names.values()}

        def resolve(value: Any) -> str:
            raw = str(value or "")
            if direct := canonical.get(self._slug(raw)):
                return direct
            match = re.search(
                r"Games\s+vs\s+(.+?)(?:\s+(?:the|wins)\b|$)", raw, re.IGNORECASE
            )
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
                    valor_tasa = entry.get("win_rate", 0.5)
                    win_rate = float(0.5 if valor_tasa is None else valor_tasa)
                except (TypeError, ValueError):
                    win_rate = 0.5
                win_rate = (
                    win_rate / 100 if win_rate > 1 else max(0.0, min(win_rate, 1.0))
                )
                rows.append(
                    {
                        "champion": champion,
                        "win_rate": win_rate,
                        "overall_win_rate": win_rate,
                        "lane_games": int(entry.get("lane_games", 0) or 0),
                        "overall_games": int(entry.get("overall_games", 0) or 0),
                        "primary_role": role.title(),
                        "tip": str(entry.get("tip", ""))[:240],
                    }
                )
            if rows:
                output[field] = rows[:5]
        if isinstance(matchups.get("summary"), dict):
            output["summary"] = matchups["summary"]
        return output

    def _merge_matchups(self, role: str, *fuentes: tuple[str, Any]) -> dict[str, Any]:
        """Combina counters y ventajas por separado, priorizando la primera fuente válida."""
        resultado: dict[str, Any] = {"counters": [], "good_against": []}
        vistos: dict[str, set[str]] = {"counters": set(), "good_against": set()}
        for nombre_fuente, datos in fuentes:
            normalizados = self._clean_matchups(datos, role)
            for grupo, vistos_grupo in vistos.items():
                for entrada in normalizados.get(grupo, []):
                    campeon = str(entrada.get("champion", ""))
                    if not campeon or campeon.casefold() in vistos_grupo:
                        continue
                    vistos_grupo.add(campeon.casefold())
                    resultado[grupo].append({**entrada, "source": nombre_fuente})
        if not resultado["counters"] and not resultado["good_against"]:
            return {}
        return resultado

    def _without_boots(self, names: Any) -> list[str]:
        if not isinstance(names, list):
            return []
        return [
            str(name)
            for name in names
            if str(name).casefold() not in self.boot_item_names
        ][:3]

    def update_champion(self, profile: dict[str, Any]) -> bool:
        """Actualiza secciones disponibles y acepta estadísticas de baja muestra."""
        name, role = str(profile.get("character", "")).strip(), self._role(profile)
        role_key = role
        if not name:
            return False
        slug = self._slug(name)
        champion_id = self.champion_ids.get(name.casefold())
        overview = self._overview(champion_id) if champion_id else None
        parsed = self._parse_overview(overview, role, name) if champion_id else {}
        if parsed and self._versiones_fuente.get("U.GG overview"):
            parsed["source_patch"] = self._versiones_fuente["U.GG overview"]
            version_actual = self._patches()[0] if self._patches() else ""
            version_fuente = parsed["source_patch"]
            parsed["patch_label"] = (
                version_actual
                if version_actual.startswith("26.")
                and version_actual.rsplit(".", 1)[-1]
                == version_fuente.rsplit(".", 1)[-1]
                else version_fuente
            )

        opgg_data = self._parse_opgg(slug, role)

        supplemental = self._parse_lolalytics(
            self._lolalytics("rune", slug, role),
            self._lolalytics("build-itemset", slug, role),
            self._lolalytics("counter", slug, role),
            role,
            name,
        )
        html_build = self._lolalytics_page(slug, role, "build")
        html_counter = self._lolalytics_page(slug, role, "counters")
        html_data = (
            self._parse_lolalytics_html(html_build, name, role) if html_build else {}
        )
        html_counter_matchups: dict[str, Any] = {}
        if html_counter:
            html_counter_matchups = self._parse_lolalytics_html(
                html_counter, name, role
            ).get("matchups", {})

        for source in (opgg_data, supplemental, html_data):
            for key, value in source.items():
                if value and key not in parsed:
                    parsed[key] = value

        patch_label = str(parsed.get("patch_label") or "")
        if not patch_label and self._versiones_fuente.get("U.GG overview"):
            patch_label = self._versiones_fuente["U.GG overview"]
        url_matchups = (
            f"https://u.gg/lol/champions/{slug}/build/{role}"
            f"?rank={self.rank}&patch={patch_label.replace('.', '_')}"
        )
        pagina_matchups = self._get(url_matchups) if patch_label else None
        matchups_ugg = (
            self._parse_matchups(pagina_matchups, role, name) if pagina_matchups else {}
        )
        matchups = self._merge_matchups(
            role,
            ("U.GG", matchups_ugg),
            ("Lolalytics", supplemental.get("matchups", {})),
            ("Lolalytics", html_data.get("matchups", {})),
            ("Lolalytics", html_counter_matchups),
        )
        if matchups and matchups_ugg:
            matchups["source_scope"] = {
                "source": "U.GG",
                "rank": self.rank,
                "patch": self._versiones_fuente.get("U.GG overview"),
                "role": role,
            }

        items = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        full_build = (
            parsed.get("full_build")
            if isinstance(parsed.get("full_build"), list)
            else []
        )

        changed = False
        imported_build_data = False

        for field in (
            "overall_matches",
            "overall_win_rate",
            "rune_page_matches",
            "summoner_spells",
            "summoner_spell_ids",
            "summoner_spell_matches",
            "summoner_spell_win_rate",
            "starter_items",
            "starter_item_entries",
            "starter_item_ids",
            "starting_item_matches",
            "starting_item_win_rate",
            "starting_items_source_status",
            "starting_items_provenance",
            "core_build",
            "core_build_matches",
            "core_build_win_rate",
            "item_options",
            "boots",
            "skill_priority_matches",
            "skill_priority_win_rate",
            "section_sample_sizes",
            "section_status",
            "source_patch",
            "patch_label",
            "situational_item_pipeline",
        ):
            if field in parsed:
                profile[field] = parsed[field]
                changed = True
        if parsed.get("starting_items_source_status") == "EMPTY":
            profile["starter_items"] = []
            profile["starter_item_ids"] = []
            profile["starter_item_entries"] = []
            profile["starting_item_matches"] = parsed.get("starting_item_matches")
            profile["starting_item_win_rate"] = parsed.get("starting_item_win_rate")
            changed = True
        if parsed.get("overall_matches"):
            profile["sample_size"] = parsed["overall_matches"]
            profile["sample_status"] = "NORMAL_SAMPLE"
        if parsed.get("overall_win_rate") is not None:
            profile["champion_win_rate"] = parsed["overall_win_rate"]

        # 1. Guardar Power Spike Core (3 ítems)
        if items:
            profile.setdefault("power_curve_and_scaling", {})["power_spike_items"] = (
                items[:3]
            )
            changed = True
            imported_build_data = True

        # 2. Guardar Build Completa de compra (hasta 6 ítems)
        if full_build:
            profile["most_played_build"] = self._normalizar_build_completa(full_build)
            changed = True
            imported_build_data = True
        elif parsed.get("most_played_build"):
            profile["most_played_build"] = self._normalizar_build_completa(
                parsed["most_played_build"]
            )
            changed = True
            imported_build_data = True

        # 3. Guardar Runas: hasta dos páginas de U.GG, cada una con la build real
        # de su arquetipo (`overview`, `lethality-overview`, `ap-overview`, ...).
        ugg_runes = (
            parsed.get("runes", []) if isinstance(parsed.get("runes"), list) else []
        )
        shard_ids = (
            parsed.get("shard_ids") if isinstance(parsed.get("shard_ids"), list) else []
        )
        archetype_pages = (
            self._ugg_archetype_pages(champion_id, role) if champion_id else []
        )
        if len(archetype_pages) < 2:
            # Respaldo: los grupos de keystone del endpoint `builds` (sin build propia).
            primary = archetype_pages[0].get("build") if archetype_pages else None
            for page in (
                self._ugg_rune_pages(self._builds(champion_id), role, shard_ids)
                if champion_id
                else []
            ):
                if len(archetype_pages) >= 2:
                    break
                if not page.get("build") and primary:
                    page["build"] = list(primary)[:6]
                archetype_pages.append(page)

        combined_runes: list[dict[str, Any]] = []
        for index, page in enumerate(archetype_pages[:2], start=1):
            if not page.get("source"):
                page["name"] = f"Página {index} U.GG"
                page["source"] = "U.GG"
            combined_runes.append(page)

        if not combined_runes:
            # Respaldo: página del endpoint de overview (U.GG/OP.GG) o la ya guardada.
            if ugg_runes and self._valid_rune_page(ugg_runes[0]):
                p_main = dict(ugg_runes[0])
                p_main["name"] = f"Página 1 {p_main.get('source') or 'U.GG'}"
                p_main["source"] = str(p_main.get("source") or "U.GG")
                combined_runes.append(p_main)
            elif isinstance(profile.get("runes"), list) and profile["runes"]:
                p_saved = dict(profile["runes"][0])
                p_saved["name"] = "Página 1 U.GG"
                p_saved["source"] = "U.GG"
                combined_runes.append(p_saved)

        if len(combined_runes) < 2:
            # Segunda página de respaldo (Lolalytics) si U.GG no ofrece la matriz de runas.
            supplemental_runes = (
                supplemental.get("runes")
                if isinstance(supplemental.get("runes"), list)
                else []
            )
            lola_page = next(
                (
                    dict(candidate)
                    for candidate in supplemental_runes
                    if self._valid_rune_page(candidate)
                ),
                None,
            )
            if not lola_page:
                lola_page = self._scrape_lolalytics_runes(
                    slug, role, str(html_build) if html_build else None
                )
            if lola_page:
                lola_page["name"] = "Página 2 Lolalytics"
                lola_page["source"] = "Lolalytics"
                combined_runes.append(lola_page)
            elif len(ugg_runes) > 1 and self._valid_rune_page(ugg_runes[1]):
                p_second = dict(ugg_runes[1])
                p_second["name"] = f"Página 2 {p_second.get('source') or 'U.GG'}"
                p_second["source"] = str(p_second.get("source") or "U.GG")
                combined_runes.append(p_second)

        # 3b. Cada página conserva SU build y SU orden de habilidades (vienen
        # emparejados del arquetipo de U.GG). Si alguna no trae build propia
        # (respaldo del endpoint `builds`), se le asigna la general de la línea.
        if combined_runes:
            skill_order = (
                parsed.get("skill_order")
                if isinstance(parsed.get("skill_order"), dict)
                else None
            )
            if skill_order:
                profile["skill_order"] = skill_order
            primary_build = profile.get("most_played_build")
            primary_build = (
                [str(item) for item in primary_build]
                if isinstance(primary_build, list)
                else []
            )
            for page in combined_runes:
                if not isinstance(page.get("build"), list) or not page["build"]:
                    if primary_build:
                        page["build"] = list(primary_build)[:6]
                if not page.get("skill_order") and skill_order:
                    page["skill_order"] = skill_order

        if combined_runes:
            profile["runes"] = combined_runes[:2]
            profile["common_runes"] = combined_runes[:2]
            changed = True
            imported_build_data = True

        # 4. Guardar Objetos Iniciales (Starter Items)
        if parsed.get("starter_items"):
            profile["starter_items"] = parsed["starter_items"]
            changed = True

        if "item_options" in parsed:
            profile["item_options"] = parsed["item_options"]
            changed = True

        # 5. Guardar Hechizos de Invocador (Summoner Spells)
        if parsed.get("summoner_spells"):
            profile["summoner_spells"] = parsed["summoner_spells"]
            changed = True

        # 6. Guardar aparte la clasificación estadística de opciones tardías.
        if "situational_items" in parsed:
            situation_source = parsed["situational_items"]
            if isinstance(situation_source, list):
                grupos = {
                    "corta_curas": [],
                    "tanque": [],
                    "asesino": [],
                    "utilidad_y_defensa": [],
                }
                nombres_a_ids = {
                    nombre.casefold(): item_id
                    for item_id, nombre in self.item_names.items()
                }
                for nombre in situation_source:
                    item_id = nombres_a_ids.get(str(nombre).casefold())
                    categoria = (
                        self._categorize_situational_item(item_id)
                        if item_id
                        else "utilidad_y_defensa"
                    )
                    if nombre not in grupos[categoria]:
                        grupos[categoria].append(str(nombre))
                situation_source = grupos
            situational_persisted = (
                situation_source if isinstance(situation_source, dict) else {}
            )
            profile["source_situational_items"] = situational_persisted
            pipeline = parsed.get("situational_item_pipeline")
            pipeline = dict(pipeline) if isinstance(pipeline, dict) else {}
            pipeline["classified"] = (
                sum(len(names) for names in situation_source.values())
                if isinstance(situation_source, dict)
                else 0
            )
            pipeline["persisted"] = sum(
                len(names) for names in situational_persisted.values()
            )
            profile["situational_item_pipeline"] = pipeline
            logging.getLogger(__name__).info(
                "Flujo de objetos situacionales: fuente=%s analizados=%s normalizados=%s "
                "clasificados=%s guardados=%s",
                pipeline.get("source_options", 0),
                pipeline.get("parsed", 0),
                pipeline.get("normalized", 0),
                pipeline.get("classified", 0),
                pipeline.get("persisted", 0),
            )
            changed = True

        # 7. Guardar Matchups
        if matchups.get("counters") or matchups.get("good_against"):
            profile["matchups"] = matchups
            changed = True

        # 8. Guardar Desglose Exacto de Daño (% AD, % AP, % True) desde Lolalytics
        dmg_breakdown = self._scrape_damage_breakdown(
            slug, role, str(html_build) if html_build else None
        )
        if dmg_breakdown:
            profile["damage_breakdown"] = dmg_breakdown
            changed = True

        # 9. Guardar Gráfica de Poder (Win Rate vs Game Length) desde Lolalytics
        power_curve = self._scrape_winrate_vs_game_length(
            slug, role, str(html_build) if html_build else None
        )
        if power_curve:
            profile["win_rate_vs_game_length"] = power_curve
            changed = True

        # 10. Winrate y partidas por línea del rango (alimenta el selector de líneas de la UI)
        lane_stats = self._lane_stats(overview)
        if lane_stats:
            profile["lane_stats"] = {"rank": self.rank, "lanes": lane_stats}
            changed = True

        muestra_linea = lane_stats.get(role_key, {}) if lane_stats else {}
        muestra_linea_valida = (
            isinstance(muestra_linea, dict)
            and isinstance(muestra_linea.get("games"), (int, float))
            and muestra_linea["games"] > 0
        )
        if not changed or not (imported_build_data or muestra_linea_valida):
            return False

        profile["ugg_last_updated"] = datetime.now(timezone.utc).isoformat()
        return True

    def _scrape_winrate_vs_game_length(
        self, slug: str, role: str, html_content: str | None = None
    ) -> list[dict[str, Any]]:
        try:
            if not html_content:
                soup = self._lolalytics_page(slug, role, "build")
                html_content = str(soup) if soup else ""

            if html_content:
                m = re.search(
                    r'<script type="qwik/json">(.*?)</script>', html_content, re.DOTALL
                )
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

                    # Las series emerald/diamond_plus pertenecen a otras
                    # gráficas (p. ej. evolución por fecha), no a duración.
                    # Lolalytics publica partidas y victorias por tramo en
                    # time/timeWin, con claves 1..7 para 0-15 ... 40+.
                    labels = (
                        "0-15",
                        "15-20",
                        "20-25",
                        "25-30",
                        "30-35",
                        "35-40",
                        "40+",
                    )
                    for obj in objs:
                        if not isinstance(obj, dict) or "timeWin" not in obj:
                            continue
                        games = decode_val(obj.get("time"))
                        wins = decode_val(obj.get("timeWin"))
                        if not isinstance(games, dict) or not isinstance(wins, dict):
                            continue
                        curve = []
                        for index, label in enumerate(labels, 1):
                            played = decode_val(games.get(str(index)))
                            won = decode_val(wins.get(str(index)))
                            if (
                                isinstance(played, (int, float))
                                and isinstance(won, (int, float))
                                and played >= _MIN_CURVE_GAMES
                                and 0 <= won <= played
                            ):
                                curve.append(
                                    {
                                        "label": label,
                                        "winrate": round(100.0 * won / played, 2),
                                        "games": int(played),
                                    }
                                )
                        if curve:
                            return curve
        except Exception:
            pass
        return []

    _PERK_NAMES = {
        # Precision
        8005: "Press the Attack",
        8008: "Lethal Tempo",
        8021: "Fleet Footwork",
        8010: "Conqueror",
        9101: "Absorb Life",
        9111: "Triumph",
        8009: "Presence of Mind",
        9104: "Legend: Alacrity",
        9103: "Legend: Bloodline",
        9105: "Legend: Haste",
        9102: "Legend: Bloodline",
        8014: "Coup de Grace",
        8017: "Cut Down",
        8299: "Last Stand",
        # Domination
        8112: "Electrocute",
        8128: "Dark Harvest",
        9923: "Hail of Blades",
        8126: "Cheap Shot",
        8139: "Taste of Blood",
        8143: "Sudden Impact",
        8137: "Sixth Sense",
        8135: "Treasure Hunter",
        8105: "Relentless Hunter",
        8106: "Ultimate Hunter",
        8140: "Grisly Mementos",
        8141: "Deep Ward",
        8136: "Zombie Ward",
        8120: "Ghost Poro",
        # Sorcery
        8214: "Summon Aery",
        8229: "Arcane Comet",
        8230: "Stormraider's Surge",
        8992: "Deathfire Touch",
        8224: "Axiom Arcanist",
        8226: "Manaflow Band",
        8275: "Nimbus Cloak",
        8210: "Transcendence",
        8234: "Celerity",
        8233: "Absolute Focus",
        8237: "Scorch",
        8232: "Waterwalking",
        8236: "Gathering Storm",
        # Inspiration
        8351: "Glacial Augment",
        8360: "Unsealed Spellbook",
        8369: "First Strike",
        8306: "Hextech Flashtraption",
        8304: "Magical Footwear",
        8321: "Cash Back",
        8313: "Triple Tonic",
        8352: "Time Warp Tonic",
        8345: "Biscuit Delivery",
        8347: "Cosmic Insight",
        8316: "Jack of All Trades",
        8410: "Approach Velocity",
        8358: "Approach Velocity",
        # Resolve
        8437: "Grasp of the Undying",
        8439: "Aftershock",
        8465: "Guardian",
        8446: "Demolish",
        8463: "Font of Life",
        8401: "Shield Bash",
        8429: "Conditioning",
        8444: "Second Wind",
        8473: "Bone Plating",
        8451: "Overgrowth",
        8453: "Revitalize",
        8242: "Unflinching",
        # Stat Shards
        5001: "Health Scaling",
        5002: "Armor",
        5003: "Magic Resist",
        5005: "Attack Speed",
        5007: "Ability Haste",
        5008: "Adaptive Force",
        5010: "Movement Speed",
        5011: "Health",
        5013: "Tenacity and Slow Resist",
    }

    # Árbol al que pertenece cada runa (id -> id de rama). Incluye alias de
    # runas retiradas que aún pueden aparecer en datos guardados.
    _PERK_TREE = {
        # Precision
        8005: 8000,
        8008: 8000,
        8010: 8000,
        8021: 8000,
        9101: 8000,
        9111: 8000,
        8009: 8000,
        9104: 8000,
        9105: 8000,
        9103: 8000,
        9102: 8000,
        8014: 8000,
        8017: 8000,
        8299: 8000,
        # Domination
        8112: 8100,
        8128: 8100,
        9923: 8100,
        8126: 8100,
        8139: 8100,
        8143: 8100,
        8137: 8100,
        8140: 8100,
        8141: 8100,
        8135: 8100,
        8105: 8100,
        8106: 8100,
        8136: 8100,
        8120: 8100,
        # Sorcery
        8214: 8200,
        8229: 8200,
        8230: 8200,
        8992: 8200,
        8224: 8200,
        8226: 8200,
        8275: 8200,
        8210: 8200,
        8234: 8200,
        8233: 8200,
        8237: 8200,
        8232: 8200,
        8236: 8200,
        # Inspiration
        8351: 8300,
        8360: 8300,
        8369: 8300,
        8306: 8300,
        8304: 8300,
        8321: 8300,
        8313: 8300,
        8352: 8300,
        8345: 8300,
        8347: 8300,
        8410: 8300,
        8316: 8300,
        8358: 8300,
        # Resolve
        8437: 8400,
        8439: 8400,
        8465: 8400,
        8446: 8400,
        8463: 8400,
        8401: 8400,
        8429: 8400,
        8444: 8400,
        8473: 8400,
        8451: 8400,
        8453: 8400,
        8242: 8400,
    }

    # Keystones (ids) usados para identificar la rama principal de una página.
    _KEYSTONE_IDS = {
        8005,
        8008,
        8010,
        8021,
        8112,
        8128,
        9923,
        8214,
        8229,
        8230,
        8992,
        8351,
        8360,
        8369,
        8437,
        8439,
        8465,
    }

    _TREE_NAMES = {
        8000: "Precision",
        8100: "Domination",
        8200: "Sorcery",
        8300: "Inspiration",
        8400: "Resolve",
    }

    @staticmethod
    def _get_perk_tree(perk_id: int) -> str:
        return ChampionScraperService._TREE_NAMES.get(
            ChampionScraperService._PERK_TREE.get(perk_id, 0), "Precision"
        )

    def _scrape_lolalytics_runes(
        self, slug: str, role: str, html_content: str | None = None
    ) -> dict[str, Any] | None:
        """Extrae la página de runas #1 de Lolalytics (tier seleccionado)."""
        try:
            if not html_content:
                soup = self._lolalytics_page(slug, role, "build")
                html_content = str(soup) if soup else ""

            if html_content:
                m = re.search(
                    r'<script type="qwik/json">(.*?)</script>', html_content, re.DOTALL
                )
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
                        if isinstance(obj, dict) and "pri" in obj and "sec" in obj:
                            perk_list = []
                            for offset in range(1, 20):
                                if i + offset < len(objs):
                                    val = decode_val(objs[i + offset])
                                    if isinstance(val, int) and (
                                        8000 <= val <= 9999 or 5000 <= val <= 5015
                                    ):
                                        perk_list.append(val)

                            if len(perk_list) >= 8:
                                games = 0
                                win_rate = 0.0
                                for offset in range(-5, 15):
                                    if 0 <= i + offset < len(objs):
                                        item = decode_val(objs[i + offset])
                                        if (
                                            isinstance(item, dict)
                                            and "wr" in item
                                            and "n" in item
                                        ):
                                            games = decode_val(item["n"]) or 0
                                            win_rate = decode_val(item["wr"]) or 0.0
                                            break

                                keystone_id = perk_list[0]
                                primary_tree = self._get_perk_tree(keystone_id)
                                primary_slots = [
                                    self._PERK_NAMES.get(p, str(p))
                                    for p in perk_list[1:4]
                                ]

                                sec_perks = perk_list[4:6]
                                sec_tree = (
                                    self._get_perk_tree(sec_perks[0])
                                    if sec_perks
                                    else "Resolve"
                                )
                                if sec_tree == primary_tree and len(sec_perks) > 1:
                                    sec_tree = self._get_perk_tree(sec_perks[1])

                                sec_slots = [
                                    self._PERK_NAMES.get(p, str(p)) for p in sec_perks
                                ]
                                raw_shards = [
                                    self._PERK_NAMES.get(p, str(p))
                                    for p in perk_list[6:]
                                ]
                                if len(raw_shards) == 2:
                                    stat_shards = [
                                        raw_shards[0],
                                        raw_shards[0],
                                        raw_shards[1],
                                    ]
                                else:
                                    stat_shards = raw_shards[:3]

                                return {
                                    "name": "Página 2 Lolalytics",
                                    "source": "Lolalytics",
                                    "primary_tree": primary_tree,
                                    "secondary_tree": sec_tree,
                                    "keystone": self._PERK_NAMES.get(
                                        keystone_id, str(keystone_id)
                                    ),
                                    "slots": primary_slots,
                                    "secondary_slots": sec_slots,
                                    "shards": stat_shards,
                                    "win_rate": float(win_rate) / 100.0
                                    if win_rate > 1
                                    else float(win_rate),
                                    "games": int(games)
                                    if isinstance(games, (int, float))
                                    else 0,
                                }
        except Exception:
            pass
        return None

    def _scrape_damage_breakdown(
        self, slug: str, role: str, html_content: str | None = None
    ) -> dict[str, float]:
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
        return (
            isinstance(slots, list)
            and len(slots) == 3
            and isinstance(secondary, list)
            and len(secondary) == 2
            and page.get("keystone") not in slots
            and page.get("primary_tree") != page.get("secondary_tree")
        )

    def actualizar_todo(
        self,
        target_champion_name: str = "",
        progress_callback: Callable[[int, int, str], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> tuple[int, int]:
        """Regenera matrices completas para selección recibida; devuelve total y éxitos con progreso y cancelación.

        El progreso tiene dos unidades según la selección: al actualizar un
        campeón se publican porcentajes 0..100 basados en las etapas reales
        (rangos, recursos y guardado), y al actualizar todos se cuenta cada
        campeón tratado sobre el total, de forma monótona. Ninguna unidad se
        reinicia por campeón y el valor 100 se emite únicamente cuando la
        persistencia ha terminado.
        """
        registro = logging.getLogger(__name__)
        preparador = PreparadorDatosCampeon(self.champions_path.parent)
        target = self._slug(target_champion_name) if target_champion_name else ""
        if target:
            nombre_objetivo = next(
                (
                    nombre
                    for nombre in self.champion_names.values()
                    if self._slug(nombre) == target
                ),
                target_champion_name,
            )
            consulta = self.repositorio.obtener_campeon(nombre_objetivo)
            selected = [
                (consulta.datos or {}).get("profile")
                or {"character": nombre_objetivo, "basic_info": {}}
            ]
        else:
            selected = self.repositorio.perfiles()
        solo_uno = bool(target)
        updated = 0
        for index, original in enumerate(selected, 1):
            self._overview_cache.clear()
            self._builds_cache.clear()
            self._archetype_cache.clear()
            self._versiones_fuente.clear()
            if stop_check and stop_check():
                break
            nombre = str(original["character"])

            def notificar(
                valor: int,
                mensaje: str,
                *,
                completado: bool = False,
                indice: int = index,
            ) -> None:
                """Publica progreso en porcentaje (un campeón) o en cuenta global."""
                if not progress_callback:
                    return
                if solo_uno:
                    progress_callback(max(0, min(100, valor)), 100, mensaje)
                else:
                    progress_callback(
                        indice if completado else indice - 1, len(selected), mensaje
                    )

            registro.debug("[update] %s iniciado", nombre)
            notificar(4, f"{nombre} actualizando...")
            matrix: dict[str, Any] = {}
            try:
                profile = copy.deepcopy(original)
                matrix = self.fetch_matrix(
                    profile,
                    progress_callback=(
                        lambda cur, tot, name: notificar(
                            10 + (75 * max(0, cur - 1)) // max(1, tot),
                            f"{name} · {cur}/{tot}",
                        )
                    )
                    if progress_callback
                    else None,
                    stop_check=stop_check,
                )
                if stop_check and stop_check():
                    break
                if not matrix:
                    raise ValueError("La fuente no entregó una matriz válida")
                if not any(
                    lane != "__lane_stats__"
                    for block in matrix.values()
                    for lane in block
                ):
                    raise SinMuestraFuente("La fuente no dispone de muestra suficiente")
                documento = preparador.preparar(profile, matrix)
                documento["source_versions"] = dict(self._versiones_fuente)
                if self._errores_parciales:
                    documento["update_status"] = "PARTIAL_SUCCESS"
                    documento["update_errors"] = list(self._errores_parciales)
                notificar(88, f"{nombre} · Descargando recursos")
                preparador.descargar_recursos(documento, stop_check or (lambda: False))
                notificar(96, f"{nombre} · Guardando datos")
                self.repositorio.guardar(nombre, documento)
                updated += 1
                mensaje = (
                    f"{nombre} actualizado parcialmente · algunas secciones no están disponibles"
                    if self._errores_parciales
                    else f"{nombre} completado"
                )
            except InterruptedError:
                break
            except Exception as error:
                registro.exception("Falló la actualización de %s", nombre)
                try:
                    consulta = self.repositorio.obtener_campeon(nombre)
                    if consulta.estado == EstadoDatos.DISPONIBLE:
                        documento = consulta.datos or {}
                        documento["update_status"] = (
                            EstadoDatos.SIN_DATOS_FUENTE.value
                            if isinstance(error, SinMuestraFuente)
                            else EstadoDatos.ACTUALIZACION_FALLIDA.value
                        )
                        documento["last_attempt_at"] = datetime.now(
                            timezone.utc
                        ).isoformat()
                        self.repositorio.guardar(nombre, documento)
                    elif (
                        consulta.estado == EstadoDatos.SIN_DATOS_LOCALES
                        and isinstance(error, SinMuestraFuente)
                    ):
                        documento = self.repositorio.documento(original, matrix)
                        documento["update_status"] = EstadoDatos.SIN_DATOS_FUENTE.value
                        self.repositorio.guardar(nombre, documento)
                except (OSError, ValueError, TypeError):
                    logging.getLogger(__name__).exception(
                        "No se pudo registrar el fallo de %s", nombre
                    )
                mensaje = f"{nombre} con error: {error}"
            notificar(100, mensaje, completado=True)
            registro.debug("[update] %s: %s", nombre, mensaje)
        registro.info(
            "[update] actualización terminada: %s/%s campeones", updated, len(selected)
        )
        return len(selected), updated


if __name__ == "__main__":
    print(ChampionScraperService().actualizar_todo())
