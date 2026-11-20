"""Bounded League asset resolution for the desktop renderer."""

from __future__ import annotations

import base64
import json
import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests
import unicodedata

from _paths import DATA_DIR
from app.services.storage_manager import atomic_write_bytes, get_storage_manager
from app.services.identidad_campeon import IndiceIdentidadCampeon

_path_locks: dict[Path, threading.Lock] = {}
_path_locks_guard = threading.Lock()
_asset_misses: dict[Path, float] = {}
_version_index_lock = threading.Lock()
_version_lookup_failed: dict[str, float] = {}
_cdragon_item_catalog: dict[str, str] = {}
_cdragon_item_catalog_loaded_at = 0.0
_cdragon_item_catalog_lock = threading.Lock()
_cdragon_rune_catalog: dict[str, str] = {}
_cdragon_rune_catalog_loaded_at = 0.0
_cdragon_rune_catalog_lock = threading.Lock()
_STAT_SHARDS = {
    "adaptiveforce": "statmodsadaptiveforceicon.png",
    "5008": "statmodsadaptiveforceicon.png",
    "healthscaling": "statmodshealthscalingicon.png",
    "healthscalingrune": "statmodshealthscalingicon.png",
    "5001": "statmodshealthscalingicon.png",
    "5013": "statmodstenacityicon.png",
    "health": "statmodshealthplusicon.png",
    "5011": "statmodshealthplusicon.png",
    "armor": "statmodsarmoricon.png",
    "5002": "statmodsarmoricon.png",
    "magicresist": "statmodsmagicresicon.png",
    "5003": "statmodsmagicresicon.png",
    "attackspeed": "statmodsattackspeedicon.png",
    "5005": "statmodsattackspeedicon.png",
    "abilityhaste": "statmodscdrscalingicon.png",
    "5007": "statmodscdrscalingicon.png",
    "movementspeed": "statmodsmovementspeedicon.png",
    "5010": "statmodsmovementspeedicon.png",
    "tenacity": "statmodstenacityicon.png",
}
_STAT_SHARD_ALIASES = {
    "fuerzaadaptable": "adaptiveforce",
    "fuerzaadaptativa": "adaptiveforce",
    "fuerzaadaptablefragmento": "adaptiveforce",
    "vidaescalable": "healthscaling",
    "saludescalable": "healthscaling",
    "vida": "health",
    "armadura": "armor",
    "resistenciamagica": "magicresist",
    "velocidaddeataque": "attackspeed",
    "celeridaddehabilidades": "abilityhaste",
    "velocidaddemovimiento": "movementspeed",
    "tenacidad": "tenacity",
}


def _asset_label_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]", "", text.encode("ascii", "ignore").decode("ascii").casefold())


def _lock_for(path: Path) -> threading.Lock:
    with _path_locks_guard:
        return _path_locks.setdefault(path, threading.Lock())


def _version() -> str:
    # Champion icons and profile icons must match the locally loaded champion
    # catalog. Items may have been refreshed independently to another patch.
    for filename in ("champion_catalog.json", "items.json"):
        try:
            catalog = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
            version = str(catalog.get("version", ""))
            if re.fullmatch(r"\d+\.\d+\.\d+", version):
                return version
        except (OSError, ValueError, AttributeError):
            continue
    return ""


def _item_version() -> str:
    """Use the item catalog's patch for item images, independent of champion data."""
    try:
        catalog = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        version = str(catalog.get("version", ""))
        return version if re.fullmatch(r"\d+\.\d+\.\d+", version) else _version()
    except (OSError, ValueError, AttributeError):
        return _version()


def _version_for_patch(patch: str | None, root: Path) -> str:
    """Map a Match-V5 game build to a real Data Dragon version for that patch."""
    if not patch:
        return _item_version() or _version()
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.\d{1,10}){0,2}", patch)
    if not match:
        return ""
    prefix = f"{match[1]}.{match[2]}."
    local = (_item_version(), _version())
    for version in local:
        if version.startswith(prefix):
            return version
    with _version_index_lock:
        index_path = root / "versions.json"
        try:
            versions = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            versions = None
        found = next((value for value in versions if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value)
                      and value.startswith(prefix)), "") if isinstance(versions, list) else ""
        if found:
            return found
        if time.monotonic() < _version_lookup_failed.get(prefix, 0):
            return ""
        try:
            response = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=8)
            response.raise_for_status()
            candidate = response.json()
            if isinstance(candidate, list) and all(isinstance(value, str) for value in candidate):
                versions = candidate
                atomic_write_bytes(index_path, json.dumps(versions).encode("utf-8"))
        except (requests.RequestException, OSError, ValueError):
            pass
        found = next((value for value in versions if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value)
                      and value.startswith(prefix)), "") if isinstance(versions, list) else ""
        if not found:
            _version_lookup_failed[prefix] = time.monotonic() + 600
        return found


def _data_url(path: Path | None, *, max_bytes: int = 2_000_000) -> str | None:
    if not path:
        return None
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        return None
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


def _cached_or_download(url: str, path: Path) -> Path | None:
    with _lock_for(path):
        if path.is_file() and _data_url(path):
            return path
        if time.monotonic() < _asset_misses.get(path, 0):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = requests.get(url, timeout=8)
            response.raise_for_status()
            payload = response.content
            if not payload.startswith(b"\x89PNG\r\n\x1a\n") or len(payload) > 2_000_000:
                _asset_misses[path] = time.monotonic() + 300
                return None
            atomic_write_bytes(path, payload)
            _asset_misses.pop(path, None)
            return path
        except (requests.RequestException, OSError):
            _asset_misses[path] = time.monotonic() + 300
            return None


def _rune_icons_by_id(version: str) -> dict[str, str]:
    from data_dragon import _rune_icon_catalog
    return _rune_icon_catalog(version)


def _resolve_rune_image(value: str, rune_icons: dict[str, str], version: str, root: Path,
                        *, allow_latest: bool = True) -> str | None:
    """Resolve ordinary perks from Riot metadata and stat shards from their own catalog."""
    normalized = _asset_label_key(value)
    shard_key = _STAT_SHARD_ALIASES.get(normalized, normalized)
    shard_filename = _STAT_SHARDS.get(shard_key)
    if shard_filename:
        cache = root / "runes" / "shards" / shard_filename
        url = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/"
               f"v1/perk-images/statmods/{shard_filename}")
        return _data_url(_cached_or_download(url, cache))

    icon = rune_icons.get(value) or rune_icons.get(normalized)
    if not icon:
        return None
    relative = icon.lstrip("/")
    if not relative.startswith("perk-images/"):
        relative = f"perk-images/{relative}"
    # A numeric rune ID can be redefined between patches (9105 formerly named
    # Legend: Tenacity and now names Legend: Haste). Include the authoritative
    # Riot icon path in the cache identity so an old image can never satisfy a
    # newer definition that reuses the ID.
    from data_dragon import rune_icon_cache_path
    cache = rune_icon_cache_path(version, relative, root)
    path = _cached_or_download(f"https://ddragon.leagueoflegends.com/cdn/img/{relative}", cache)
    data = _data_url(path)
    if data:
        return data
    # The client data catalog sometimes has a more current icon path than the
    # localized Data Dragon bundle. Use CommunityDragon's stable perk ID entry.
    if allow_latest and value.isdigit():
        relative = _communitydragon_rune_paths().get(value)
        if relative:
            path_hash = hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()[:12]
            cd_cache = root / "runes" / "communitydragon-latest" / f"{value}-{path_hash}.png"
            cd_url = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/"
                      f"{relative}")
            return _data_url(_cached_or_download(cd_url, cd_cache))
    return None


def _communitydragon_rune_paths() -> dict[str, str]:
    global _cdragon_rune_catalog_loaded_at
    now = time.monotonic()
    if _cdragon_rune_catalog_loaded_at > 0 and now - _cdragon_rune_catalog_loaded_at < 21_600:
        return _cdragon_rune_catalog
    with _cdragon_rune_catalog_lock:
        now = time.monotonic()
        if _cdragon_rune_catalog_loaded_at > 0 and now - _cdragon_rune_catalog_loaded_at < 21_600:
            return _cdragon_rune_catalog
        try:
            response = requests.get(
                "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perks.json",
                timeout=8,
            )
            response.raise_for_status()
            rows = response.json()
            paths = {}
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                rune_id = str(row.get("id", ""))
                icon_path = str(row.get("iconPath", ""))
                prefix = "/lol-game-data/assets/"
                if rune_id.isdigit() and icon_path.startswith(prefix):
                    relative = icon_path[len(prefix):].strip("/").casefold()
                    if relative and ".." not in relative.split("/"):
                        paths[rune_id] = relative
            _cdragon_rune_catalog = paths
            _cdragon_rune_catalog_loaded_at = now
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            _cdragon_rune_catalog_loaded_at = now
        return _cdragon_rune_catalog


def _communitydragon_item_paths() -> dict[str, str]:
    """Load CommunityDragon's item ID to iconPath index only when DDragon misses."""
    global _cdragon_item_catalog_loaded_at
    now = time.monotonic()
    if _cdragon_item_catalog_loaded_at > 0 and now - _cdragon_item_catalog_loaded_at < 21_600:
        return _cdragon_item_catalog
    with _cdragon_item_catalog_lock:
        now = time.monotonic()
        if _cdragon_item_catalog_loaded_at > 0 and now - _cdragon_item_catalog_loaded_at < 21_600:
            return _cdragon_item_catalog
        try:
            response = requests.get(
                "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/items.json",
                timeout=8,
            )
            response.raise_for_status()
            rows = response.json()
            paths = {}
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                item_id = str(row.get("id", ""))
                icon_path = str(row.get("iconPath", ""))
                if item_id.isdigit() and icon_path.startswith("/lol-game-data/assets/"):
                    relative = icon_path.split("/lol-game-data/assets/", 1)[1].strip("/").casefold()
                    if relative and ".." not in relative.split("/"):
                        paths[item_id] = relative
            _cdragon_item_catalog = paths
            _cdragon_item_catalog_loaded_at = now
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            _cdragon_item_catalog_loaded_at = now
        return _cdragon_item_catalog


def _resolve_item_image(item_id: str, item_version: str, root: Path, *, allow_latest: bool = True) -> str | None:
    """Return the same ID's DDragon icon, with a metadata-verified CDragon fallback."""
    version = item_version or _version()
    if version:
        cache = root / "items" / version / f"{item_id}.png"
        path = _cached_or_download(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/img/item/{item_id}.png", cache
        )
        data = _data_url(path)
        if data:
            return data
    relative = _communitydragon_item_paths().get(item_id) if allow_latest else None
    if relative:
        cache = root / "items" / "communitydragon-latest" / f"{item_id}.png"
        path = _cached_or_download(
            f"https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/{relative}", cache
        )
        return _data_url(path)
    return None


def resolve_home_assets(champions: list[str], profile_icon_id: int | None,
                        catalog: list[dict[str, Any]],
                        splash_champions: list[str] | None = None) -> dict[str, Any]:
    """Resolve a bounded set of canonical champion and profile icons.

    Names are mapped against the local Data Dragon catalog. No caller-supplied
    path is accepted, and images are returned as small PNG data URLs.
    """
    version = _version()
    root = get_storage_manager().ddragon_dir
    def normalized(value: object) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        return re.sub(r"[^a-z0-9]", "", text.encode("ascii", "ignore").decode().casefold())

    by_name = {normalized(item.get("name")): str(item.get("id", ""))
               for item in catalog}
    by_id = {normalized(item.get("id")): str(item.get("id", ""))
             for item in catalog}
    by_key = {normalized(item.get("key")): str(item.get("id", ""))
              for item in catalog if str(item.get("key", "")).strip()}
    aliases = {"bardo": "Bard", "wukong": "MonkeyKing", "monkeyking": "MonkeyKing",
               "nunuywillump": "Nunu", "nunuwillump": "Nunu", "nunu": "Nunu", "kaisa": "KaiSa", "khazix": "Khazix"}
    canonical: list[str] = []
    requested: dict[str, str] = {}
    for name in champions[:20]:
        if not isinstance(name, str):
            continue
        key = normalized(name)
        champ_id = by_id.get(key) or by_name.get(key) or by_key.get(key)
        if not champ_id and key in aliases:
            champ_id = by_id.get(normalized(aliases[key])) or by_name.get(normalized(aliases[key]))
        if champ_id:
            requested[name] = champ_id
            if champ_id not in canonical:
                canonical.append(champ_id)

    def champion_image(champ_id: str) -> tuple[str, str | None]:
        cache = root / "champions" / f"{champ_id}.png"
        legacy = DATA_DIR / "champion_icons" / f"{champ_id}.png"
        path = cache if cache.is_file() else legacy if legacy.is_file() else None
        if path is None and version:
            path = _cached_or_download(
                f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champ_id}.png",
                cache,
            )
        return champ_id, _data_url(path)

    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="solralol-assets") as pool:
        icons = dict(pool.map(champion_image, canonical))

    profile: str | None = None
    try:
        icon_id = int(profile_icon_id) if profile_icon_id is not None else 0
    except (TypeError, ValueError, OverflowError):
        icon_id = 0
    if 0 < icon_id <= 100_000:
        cache = root / "profileicons" / f"{icon_id}.png"
        if not cache.is_file() and version:
            _cached_or_download(
                f"https://ddragon.leagueoflegends.com/cdn/{version}/img/profileicon/{icon_id}.png",
                cache,
            )
        profile = _data_url(cache)
    # The renderer can only request catalog-resolved champions. Read an already
    # cached splash; asset acquisition remains in the existing Data Dragon path.
    splashes: dict[str, str | None] = {}
    splash_dirs = (get_storage_manager().cache_dir / "champion_splashes", DATA_DIR / "champion_splashes")
    splash_ids = [
        by_id.get(normalized(name))
        or by_name.get(normalized(name))
        or by_key.get(normalized(name))
        for name in (splash_champions or [])[:3]
    ]
    for champ_id in dict.fromkeys(item for item in splash_ids if item):
        path = next((directory / f"{champ_id}_0.{ext}" for directory in splash_dirs for ext in ("jpg", "png", "webp")
                     if (directory / f"{champ_id}_0.{ext}").is_file()), None)
        splashes[champ_id] = _data_url(path, max_bytes=8_000_000)
    return {"champions": icons, "championAliases": requested, "splashes": splashes, "profileIcon": profile}


def resolve_meta_assets(champions: list[str], items: list[str], abilities: list[dict[str, str]],
                        catalog: list[dict[str, Any]], runes: list[str] | None = None,
                        spells: list[str] | None = None, patch: str | None = None) -> dict[str, str | None]:
    """Resolve bounded canonical assets for the Meta page through the shared DDragon cache."""
    version = _version()
    root = get_storage_manager().ddragon_dir
    identities = IndiceIdentidadCampeon({str(item.get("id") or index): item for index, item in enumerate(catalog)})
    resolved: dict[str, str | None] = {}

    def canonical(value: str) -> str | None:
        return identities.resolve(value)

    def image(key: str, url: str, path: Path) -> None:
        resolved[key] = _data_url(_cached_or_download(url, path)) if version else _data_url(path if path.is_file() else None)

    champion_ids = list(dict.fromkeys(canonical(value) for value in champions[:20]))
    for champion_id in (value for value in champion_ids if value):
        cache = root / "champions" / f"{champion_id}.png"
        legacy = DATA_DIR / "champion_icons" / f"{champion_id}.png"
        source = cache if cache.is_file() else legacy
        if source.is_file():
            resolved[f"champion:{champion_id}"] = _data_url(source)
        else:
            image(f"champion:{champion_id}", f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champion_id}.png", cache)

    item_version = _version_for_patch(patch, root)
    historical = bool(patch and item_version and item_version != _item_version())
    valid_item_ids = [raw_id for raw_id in dict.fromkeys(str(value) for value in items[:100])
                      if raw_id.isdigit() and int(raw_id) > 0]
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="solralol-item-assets") as pool:
        item_images = pool.map(lambda raw_id: (raw_id, _resolve_item_image(raw_id, item_version, root,
                                                                          allow_latest=not historical) if item_version else None), valid_item_ids)
        resolved.update({f"item:{raw_id}": image_data for raw_id, image_data in item_images})

    for entry in abilities[:20]:
        champion_id = canonical(str(entry.get("champion", "")))
        slot = str(entry.get("slot", "")).casefold()
        if not champion_id or slot not in {"passive", "q", "w", "e", "r"}:
            continue
        key = f"ability:{champion_id}|{slot}"
        if key in resolved:
            continue
        try:
            document = json.loads((DATA_DIR / "champion_abilities" / f"{champion_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            resolved[key] = None
            continue
        champion = document.get("data", {}).get(champion_id, {})
        if slot == "passive":
            group, ability = "passive", champion.get("passive", {})
        else:
            champion_spells = champion.get("spells", [])
            index = "qwer".index(slot)
            group, ability = "spell", champion_spells[index] if isinstance(champion_spells, list) and len(champion_spells) > index else {}
        filename = str((ability.get("image") or {}).get("full") or "").strip()
        if not filename or not version:
            resolved[key] = None
            continue
        cache = root / "abilities" / filename
        image(key, f"https://ddragon.leagueoflegends.com/cdn/{version}/img/{group}/{filename}", cache)

    # Match-V5 exposes perk and summoner spell IDs, not renderer-ready image
    # URLs. Resolve only known Riot IDs here; the renderer never supplies paths.
    rune_version = item_version
    rune_icons = _rune_icons_by_id(rune_version) if rune_version else {}
    rune_values = list(dict.fromkeys(str(value) for value in (runes or [])[:100]))
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="solralol-rune-assets") as pool:
        rune_images = pool.map(lambda value: (value, _resolve_rune_image(value, rune_icons, rune_version, root,
                                                                         allow_latest=not historical) if rune_version else None), rune_values)
        resolved.update({f"rune:{value}": image_data for value, image_data in rune_images})

    if spells:
        try:
            from data_dragon import SPELL_CANONICAL_TO_FILE, SPELL_ICON_DIR, normalizar_hechizo_invocador
            def spell_image(spell_id: str) -> tuple[str, str | None]:
                canonical_spell = normalizar_hechizo_invocador(spell_id)
                filename = SPELL_CANONICAL_TO_FILE.get(canonical_spell) if canonical_spell else None
                if not filename or not item_version:
                    return spell_id, None
                cache = root / "spells" / item_version / filename
                legacy = SPELL_ICON_DIR / filename
                path = cache if _data_url(cache) else legacy if not historical and _data_url(legacy) else None
                if path is None:
                    path = _cached_or_download(f"https://ddragon.leagueoflegends.com/cdn/{item_version}/img/spell/{filename}", cache)
                return spell_id, _data_url(path)
            spell_values = list(dict.fromkeys(str(value) for value in spells[:20]))
            with ThreadPoolExecutor(max_workers=5, thread_name_prefix="solralol-spell-assets") as pool:
                resolved.update({f"spell:{value}": image_data for value, image_data in pool.map(spell_image, spell_values)})
        except (ImportError, OSError, ValueError):
            pass
    return resolved
