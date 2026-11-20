"""Normalización compartida de identidades de campeones de League of Legends."""

from __future__ import annotations

import re
import unicodedata
import json
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from _paths import DATA_DIR


def normalizar_identidad_campeon(value: object) -> str:
    """Normaliza ID, nombre localizado o alias sin acentos ni puntuación."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]", "", text.encode("ascii", "ignore").decode().casefold())


# Solo alias de identidad documentados; el destino siempre se valida contra
# el catálogo Data Dragon del consumidor. No se infieren coincidencias difusas.
ALIAS_CAMPEONES: Mapping[str, str] = {
    "bardo": "bard",
    "wukong": "monkeyking",
    "monkeyking": "monkeyking",
    "maestroyi": "masteryi",
    "masteryi": "masteryi",
    "nunuywillump": "nunu",
    "nunuwillump": "nunu",
    "nunu": "nunu",
    "drmundo": "drmundo",
    "kaisa": "kaisa",
    "khazix": "khazix",
    "chogath": "chogath",
    "kogmaw": "kogmaw",
    "reksai": "reksai",
    "velkoz": "velkoz",
    "leesin": "leesin",
    "jarvaniv": "jarvaniv",
    "renataglasc": "renata",
}


def construir_indice_campeones(catalogue: Mapping[str, Mapping[str, object]]) -> dict[str, str]:
    """Indexa IDs, claves Riot y nombres canónicos; añade alias con destino válido."""
    return IndiceIdentidadCampeon(catalogue).by_alias.copy()


def resolver_identidad_campeon(value: object, index: Mapping[str, str]) -> str | None:
    """Resuelve únicamente coincidencias exactas tras normalizar."""
    return index.get(normalizar_identidad_campeon(value))


class IndiceIdentidadCampeon:
    """Identity, display name and numeric key from one Data Dragon catalog."""

    def __init__(self, catalogue: Mapping[str, Mapping[str, object]]) -> None:
        self.entries: dict[str, Mapping[str, object]] = {}
        self.by_alias: dict[str, str] = {}
        self.ambiguous: dict[str, set[str]] = {}
        for entry in catalogue.values():
            champion_id = str(entry.get("id") or "").strip()
            name = str(entry.get("name") or "").strip()
            key = str(entry.get("key") or "").strip()
            if not champion_id or not name or not key.isdecimal():
                continue
            self.entries[champion_id] = entry
            for value in (champion_id, name, key):
                self._register(value, champion_id)
        for alias, target in ALIAS_CAMPEONES.items():
            canonical = next((item for item in self.entries if item.casefold() == target.casefold()), None)
            if canonical:
                self._register(alias, canonical)

    def _register(self, value: object, champion_id: str) -> None:
        key = normalizar_identidad_campeon(value)
        if not key:
            return
        previous = self.by_alias.get(key)
        if previous and previous != champion_id:
            self.ambiguous.setdefault(key, {previous}).add(champion_id)
            self.by_alias.pop(key, None)
        elif key not in self.ambiguous:
            self.by_alias[key] = champion_id

    def resolve(self, value: object) -> str | None:
        return self.by_alias.get(normalizar_identidad_campeon(value))

    def display_name(self, value: object) -> str | None:
        champion_id = self.resolve(value)
        return str(self.entries[champion_id]["name"]) if champion_id else None

    def numeric_key(self, value: object) -> int | None:
        champion_id = self.resolve(value)
        return int(str(self.entries[champion_id]["key"])) if champion_id else None


@lru_cache(maxsize=8)
def _load_index(path: str, modified_ns: int, size: int) -> IndiceIdentidadCampeon:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return IndiceIdentidadCampeon(document.get("data", {}))


def cargar_indice_campeones(catalog_path: Path | None = None) -> IndiceIdentidadCampeon:
    """Use the active local catalog when present, otherwise the bundled one."""
    path = catalog_path if catalog_path and catalog_path.is_file() else DATA_DIR / "champion_catalog.json"
    if not path.is_file():
        return IndiceIdentidadCampeon({})
    stat = path.stat()
    return _load_index(str(path.resolve()), stat.st_mtime_ns, stat.st_size)
