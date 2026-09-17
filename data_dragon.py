import json
import re
from pathlib import Path

import requests

DD_BASE_URL = "https://ddragon.leagueoflegends.com"

DATA_DIR = Path("data")
ITEM_CACHE_FILE = DATA_DIR / "items.json"
ICON_DIR = DATA_DIR / "item_icons"
CHAMPION_ICON_DIR = DATA_DIR / "champion_icons"
CHAMPION_DATA_DIR = DATA_DIR / "champion_data"
CHAMPION_MEMORY_CACHE: dict[str, dict] = {}
RUNE_ICON_CATALOG_CACHE: dict[str, str] = {}


def get_latest_version() -> str:
    response = requests.get(f"{DD_BASE_URL}/api/versions.json", timeout=10)
    response.raise_for_status()
    return response.json()[0]


def download_items(version: str) -> dict:
    url_es = f"{DD_BASE_URL}/cdn/{version}/data/es_ES/item.json"
    url_en = f"{DD_BASE_URL}/cdn/{version}/data/en_US/item.json"

    DATA_DIR.mkdir(exist_ok=True)

    try:
        response_es = requests.get(url_es, timeout=20)
        response_es.raise_for_status()
        items_es = response_es.json().get("data", {})
    except requests.RequestException:
        if ITEM_CACHE_FILE.exists():
            try:
                cached = json.loads(ITEM_CACHE_FILE.read_text(encoding="utf-8"))
                return cached.get("items", {})
            except (json.JSONDecodeError, OSError):
                pass
        raise

    try:
        response_en = requests.get(url_en, timeout=20)
        response_en.raise_for_status()
        items_en = response_en.json().get("data", {})
    except requests.RequestException:
        items_en = {}

    items: dict[str, dict] = {}
    for item_id, item_data in items_es.items():
        merged = dict(item_data)
        merged["id"] = str(item_id)
        merged["name_es"] = item_data.get("name", "")
        merged["description_es"] = item_data.get("description", "")
        en_item = items_en.get(item_id, {})
        en_name = en_item.get("name", "")
        merged["name_en"] = en_name
        merged["description_en"] = en_item.get("description", "")

        # Combinar términos de búsqueda (colloq) en español e inglés
        colloq_parts = [
            item_data.get("colloq", ""),
            en_item.get("colloq", ""),
            en_name,
            item_data.get("name", ""),
        ]
        merged["colloq"] = ";".join(p for p in colloq_parts if p)
        items[str(item_id)] = merged

    # Agregar cualquier objeto que pudiera estar solo en en_US
    for item_id, en_item in items_en.items():
        str_id = str(item_id)
        if str_id not in items:
            merged = dict(en_item)
            merged["id"] = str_id
            merged["name_es"] = en_item.get("name", "")
            merged["name_en"] = en_item.get("name", "")
            merged["description_es"] = en_item.get("description", "")
            merged["description_en"] = en_item.get("description", "")
            items[str_id] = merged

    ITEM_CACHE_FILE.write_text(
        json.dumps(
            {
                "version": version,
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return items


def load_item_catalog() -> tuple[str, dict]:
    try:
        version = get_latest_version()
    except Exception:
        if ITEM_CACHE_FILE.exists():
            try:
                cached = json.loads(ITEM_CACHE_FILE.read_text(encoding="utf-8"))
                return cached.get("version", "16.17.1"), cached.get("items", {})
            except Exception:
                pass
        version = "16.17.1"

    try:
        items = download_items(version)
    except Exception:
        if ITEM_CACHE_FILE.exists():
            try:
                cached = json.loads(ITEM_CACHE_FILE.read_text(encoding="utf-8"))
                items = cached.get("items", {})
            except Exception:
                items = {}
        else:
            items = {}

    ICON_DIR.mkdir(exist_ok=True)
    CHAMPION_ICON_DIR.mkdir(exist_ok=True)
    CHAMPION_DATA_DIR.mkdir(exist_ok=True)

    return version, items


def get_item_total_gold(item_id: int | str, item_catalog: dict) -> int:
    if isinstance(item_catalog, dict) and "items" in item_catalog and isinstance(item_catalog["items"], dict):
        item_catalog = item_catalog["items"]
    item = item_catalog.get(str(item_id)) if isinstance(item_catalog, dict) else None

    if item is None:
        return 0

    return int(item.get("gold", {}).get("total", 0))


def get_item_icon_path(
    item_id: int | str,
    item_catalog: dict,
    version: str,
    *,
    download: bool = True,
) -> Path | None:
    ICON_DIR.mkdir(exist_ok=True)
    item_id = str(item_id)
    if isinstance(item_catalog, dict) and "items" in item_catalog and isinstance(item_catalog["items"], dict):
        item_catalog = item_catalog["items"]

    item = item_catalog.get(item_id) if isinstance(item_catalog, dict) else None

    image_name = item.get("image", {}).get("full") if isinstance(item, dict) else None
    if not image_name:
        image_name = f"{item_id}.png"

    local_path = ICON_DIR / image_name

    if local_path.exists():
        return local_path

    if not download:
        fallback_path = ICON_DIR / f"{item_id}.png"
        return fallback_path if fallback_path.exists() else None

    icon_url = f"{DD_BASE_URL}/cdn/{version}/img/item/{image_name}"

    try:
        response = requests.get(icon_url, timeout=10)
        response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except requests.RequestException:
        # Intento con ID estándar si falló el nombre original
        if image_name != f"{item_id}.png":
            fallback_path = ICON_DIR / f"{item_id}.png"
            if fallback_path.exists():
                return fallback_path
            try:
                response = requests.get(f"{DD_BASE_URL}/cdn/{version}/img/item/{item_id}.png", timeout=10)
                response.raise_for_status()
                fallback_path.write_bytes(response.content)
                return fallback_path
            except requests.RequestException:
                pass
        return None


CHAMPION_IMAGE_NAME_ALIASES: dict[str, str] = {
    "wukong": "MonkeyKing",
    "monkeyking": "MonkeyKing",
    "nunu & willump": "Nunu",
    "nunu y willump": "Nunu",
    "nunu": "Nunu",
    "renata glasc": "Renata",
    "renata": "Renata",
    "cho'gath": "Chogath",
    "chogath": "Chogath",
    "kai'sa": "Kaisa",
    "kaisa": "Kaisa",
    "kha'zix": "Khazix",
    "khazix": "Khazix",
    "kog'maw": "KogMaw",
    "kogmaw": "KogMaw",
    "leblanc": "Leblanc",
    "rek'sai": "RekSai",
    "reksai": "RekSai",
    "vel'koz": "Velkoz",
    "velkoz": "Velkoz",
    "k'sante": "KSante",
    "ksante": "KSante",
    "bel'veth": "Belveth",
    "belveth": "Belveth",
    "dr. mundo": "DrMundo",
    "dr mundo": "DrMundo",
    "drmundo": "DrMundo",
    "jarvan iv": "JarvanIV",
    "jarvaniv": "JarvanIV",
    "twisted fate": "TwistedFate",
    "twistedfate": "TwistedFate",
    "miss fortune": "MissFortune",
    "missfortune": "MissFortune",
    "master yi": "MasterYi",
    "masteryi": "MasterYi",
    "tahm kench": "TahmKench",
    "tahmkench": "TahmKench",
    "aurelion sol": "AurelionSol",
    "aurelionsol": "AurelionSol",
    "xin zhao": "XinZhao",
    "xinzhao": "XinZhao",
}


def get_champion_icon_path(
    champion_name: str,
    version: str,
    *,
    download: bool = True,
) -> Path | None:
    CHAMPION_ICON_DIR.mkdir(parents=True, exist_ok=True)
    raw_key = champion_name.strip().lower()
    
    if raw_key in CHAMPION_IMAGE_NAME_ALIASES:
        safe_name = CHAMPION_IMAGE_NAME_ALIASES[raw_key]
    else:
        safe_name = champion_name.replace(" ", "").replace(".", "").replace("'", "").replace("&", "")

    local_path = CHAMPION_ICON_DIR / f"{safe_name}.png"
    if local_path.exists():
        return local_path

    if not download:
        fallback_path = CHAMPION_ICON_DIR / f"{safe_name.capitalize()}.png"
        return fallback_path if fallback_path.exists() else None

    icon_url = f"{DD_BASE_URL}/cdn/{version}/img/champion/{safe_name}.png"
    try:
        response = requests.get(icon_url, timeout=10)
        response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except requests.RequestException:
        # Intento con primera letra mayúscula
        capitalized = safe_name.capitalize()
        if capitalized != safe_name:
            cap_path = CHAMPION_ICON_DIR / f"{capitalized}.png"
            if cap_path.exists():
                return cap_path
            try:
                response = requests.get(f"{DD_BASE_URL}/cdn/{version}/img/champion/{capitalized}.png", timeout=10)
                response.raise_for_status()
                cap_path.write_bytes(response.content)
                return cap_path
            except requests.RequestException:
                pass
        return None


def get_rune_icon_path(
    rune_name: str,
    version: str,
    *,
    download: bool = True,
) -> Path | None:
    """Obtiene el icono de una runa desde los assets de Data Dragon."""
    paths = {
        "Press the Attack": "Styles/Precision/PressTheAttack/PressTheAttack.png",
        "Lethal Tempo": "Styles/Precision/LethalTempo/LethalTempoTemp.png",
        "Fleet Footwork": "Styles/Precision/FleetFootwork/FleetFootwork.png",
        "Conquistador": "Styles/Precision/Conqueror/Conqueror.png",
        "Conqueror": "Styles/Precision/Conqueror/Conqueror.png",
        "Overheal": "Styles/Precision/Overheal/Overheal.png",
        "Triumph": "Styles/Precision/Triumph/Triumph.png",
        "Triunfo": "Styles/Precision/Triumph/Triumph.png",
        "Presence of Mind": "Styles/Precision/PresenceOfMind/PresenceOfMind.png",
        "Legend: Alacrity": "Styles/Precision/LegendAlacrity/LegendAlacrity.png",
        "Leyenda: Presteza": "Styles/Precision/LegendAlacrity/LegendAlacrity.png",
        "Legend: Tenacity": "Styles/Precision/LegendTenacity/LegendTenacity.png",
        "Legend: Bloodline": "Styles/Precision/LegendBloodline/LegendBloodline.png",
        "Coup de Grace": "Styles/Precision/CoupDeGrace/CoupDeGrace.png",
        "Golpe de gracia": "Styles/Precision/CoupDeGrace/CoupDeGrace.png",
        "Cut Down": "Styles/Precision/CutDown/CutDown.png",
        "Last Stand": "Styles/Precision/LastStand/LastStand.png",
        "Demolish": "Styles/Resolve/Demolish/Demolish.png",
        "Font of Life": "Styles/Resolve/FontOfLife/FontOfLife.png",
        "Shield Bash": "Styles/Resolve/ShieldBash/ShieldBash.png",
        "Conditioning": "Styles/Resolve/Conditioning/Conditioning.png",
        "Second Wind": "Styles/Resolve/SecondWind/SecondWind.png",
        "Bone Plating": "Styles/Resolve/BonePlating/BonePlating.png",
        "Overgrowth": "Styles/Resolve/Overgrowth/Overgrowth.png",
        "Revitalize": "Styles/Resolve/Revitalize/Revitalize.png",
        "Unflinching": "Styles/Resolve/Unflinching/Unflinching.png",
        "Electrocutar": "Styles/Domination/Electrocute/Electrocute.png",
        "Electrocute": "Styles/Domination/Electrocute/Electrocute.png",
        "Predator": "Styles/Domination/Predator/Predator.png",
        "Dark Harvest": "Styles/Domination/DarkHarvest/DarkHarvest.png",
        "Cheap Shot": "Styles/Domination/CheapShot/CheapShot.png",
        "Taste of Blood": "Styles/Domination/TasteOfBlood/TasteOfBlood.png",
        "Sudden Impact": "Styles/Domination/SuddenImpact/SuddenImpact.png",
        "Impacto repentino": "Styles/Domination/SuddenImpact/SuddenImpact.png",
        "Zombie Ward": "Styles/Domination/ZombieWard/ZombieWard.png",
        "Eyeball Collection": "Styles/Domination/EyeballCollection/EyeballCollection.png",
        "Colección de globos": "Styles/Domination/EyeballCollection/EyeballCollection.png",
        "Treasure Hunter": "Styles/Domination/TreasureHunter/TreasureHunter.png",
        "Cazador de tesoros": "Styles/Domination/TreasureHunter/TreasureHunter.png",
        "Summon Aery": "Styles/Sorcery/SummonAery/SummonAery.png",
        "Arcane Comet": "Styles/Sorcery/ArcaneComet/ArcaneComet.png",
        "Cometa": "Styles/Sorcery/ArcaneComet/ArcaneComet.png",
        "Phase Rush": "Styles/Sorcery/PhaseRush/PhaseRush.png",
        "Manaflow Band": "Styles/Sorcery/ManaflowBand/ManaflowBand.png",
        "Nimbus Cloak": "Styles/Sorcery/NimbusCloak/NimbusCloak.png",
        "Transcendence": "Styles/Sorcery/Transcendence/Transcendence.png",
        "Celerity": "Styles/Sorcery/Celerity/Celerity.png",
        "Absolute Focus": "Styles/Sorcery/AbsoluteFocus/AbsoluteFocus.png",
        "Scorch": "Styles/Sorcery/Scorch/Scorch.png",
        "Waterwalking": "Styles/Sorcery/Waterwalking/Waterwalking.png",
        "Gathering Storm": "Styles/Sorcery/GatheringStorm/GatheringStorm.png",
        "Glacial Augment": "Styles/Inspiration/GlacialAugment/GlacialAugment.png",
        "First Strike": "Styles/Inspiration/FirstStrike/FirstStrike.png",
        "Unsealed Spellbook": "Styles/Inspiration/UnsealedSpellbook/UnsealedSpellbook.png",
        "Magical Footwear": "Styles/Inspiration/MagicalFootwear/MagicalFootwear.png",
        "Cash Back": "Styles/Inspiration/CashBack/CashBack.png",
        "Future's Market": "Styles/Inspiration/FuturesMarket/FuturesMarket.png",
        "Minion Dematerializer": "Styles/Inspiration/MinionDematerializer/MinionDematerializer.png",
        "Biscuit Delivery": "Styles/Inspiration/BiscuitDelivery/BiscuitDelivery.png",
        "Cosmic Insight": "Styles/Inspiration/CosmicInsight/CosmicInsight.png",
        "Approach Velocity": "Styles/Inspiration/ApproachVelocity/ApproachVelocity.png",
        # Los fragmentos usan subcarpetas propias; no la ruta plana de runas.
        "Adaptive Force": "StatMods/StatModsAdaptiveForceIcon/StatModsAdaptiveForceIcon.png",
        "Attack Speed": "StatMods/StatModsAttackSpeedIcon/StatModsAttackSpeedIcon.png",
        "Ability Haste": "StatMods/StatModsCDRScalingIcon/StatModsCDRScalingIcon.png",
        "Movement Speed": "StatMods/StatModsMovementSpeedIcon/StatModsMovementSpeedIcon.png",
        "Health Scaling": "StatMods/StatModsHealthScalingIcon/StatModsHealthScalingIcon.png",
        "Health": "StatMods/StatModsHealthPlusIcon/StatModsHealthPlusIcon.png",
        "Tenacity and Slow Resist": "StatMods/StatModsTenacityIcon/StatModsTenacityIcon.png",
        "Dominación": "Styles/Domination/Domination.png",
        "Precision": "Styles/Precision/Precision.png",
        "Resolve": "Styles/Resolve/Resolve.png",
        "Inspiration": "Styles/Inspiration/Inspiration.png",
    }
    aliases = {
        "Conquistador": "Conqueror",
        "Triunfo": "Triumph",
        "Leyenda: Presteza": "Legend: Alacrity",
        "Golpe de gracia": "Coup de Grace",
        "Electrocutar": "Electrocute",
        "Impacto repentino": "Sudden Impact",
        "Colección de globos": "Eyeball Collection",
        "Cazador de tesoros": "Treasure Hunter",
        "Cometa": "Arcane Comet",
    }
    lookup_name = aliases.get(rune_name, rune_name)
    asset_path = paths.get(rune_name) or paths.get(lookup_name)
    local_name = re.sub(r"[^A-Za-z0-9._-]+", "_", lookup_name).strip("_")
    local_path = DATA_DIR / "rune_icons" / f"{local_name}.png"
    if local_path.exists():
        return local_path

    if not download:
        return None

    if not asset_path:
        asset_path = _rune_icon_catalog(version).get(lookup_name.lower())
    if asset_path:
        try:
            url_path = asset_path if asset_path.startswith("perk-images/") else f"perk-images/{asset_path}"
            response = requests.get(f"{DD_BASE_URL}/cdn/img/{url_path}", timeout=10)
            response.raise_for_status()
            local_path.parent.mkdir(exist_ok=True)
            local_path.write_bytes(response.content)
            return local_path
        except requests.RequestException:
            # Las rutas estáticas pueden quedar obsoletas; reintentar con el catálogo oficial.
            dynamic_path = _rune_icon_catalog(version).get(lookup_name.lower())
            if dynamic_path and dynamic_path != asset_path:
                try:
                    url_path = dynamic_path if dynamic_path.startswith("perk-images/") else f"perk-images/{dynamic_path}"
                    response = requests.get(f"{DD_BASE_URL}/cdn/img/{url_path}", timeout=10)
                    response.raise_for_status()
                    local_path.parent.mkdir(exist_ok=True)
                    local_path.write_bytes(response.content)
                    return local_path
                except requests.RequestException:
                    pass
    return None


def _rune_icon_catalog(version: str) -> dict[str, str]:
    if RUNE_ICON_CATALOG_CACHE:
        return RUNE_ICON_CATALOG_CACHE
    try:
        response = requests.get(
            f"{DD_BASE_URL}/cdn/{version}/data/en_US/runesReforged.json",
            timeout=10,
        )
        response.raise_for_status()
        for style in response.json():
            RUNE_ICON_CATALOG_CACHE[str(style.get("name", "")).lower()] = style.get("icon", "")
            for slot in style.get("slots", []):
                for rune in slot.get("runes", []):
                    name = str(rune.get("name", "")).lower()
                    if name:
                        RUNE_ICON_CATALOG_CACHE[name] = rune.get("icon", "")
    except (requests.RequestException, ValueError, TypeError):
        return {}
    return RUNE_ICON_CATALOG_CACHE


def download_all_rune_icons(version: str) -> int:
    """Descarga en caché todos los iconos de runas y fragmentos oficiales."""
    catalog = _rune_icon_catalog(version)
    downloaded = 0
    # El catálogo cubre runas y árboles; los fragmentos no figuran en él.
    names = set(catalog) | {
        "Adaptive Force", "Attack Speed", "Ability Haste", "Movement Speed",
        "Health Scaling", "Health", "Tenacity and Slow Resist",
    }
    for name in names:
        before = get_rune_icon_path(name, version)
        downloaded += int(before is not None)
    return downloaded


def get_champion_data(
    champion_name: str,
    version: str,
) -> dict:
    safe_name = champion_name.replace(" ", "").replace(".", "")

    if safe_name in CHAMPION_MEMORY_CACHE:
        return CHAMPION_MEMORY_CACHE[safe_name]

    cache_path = CHAMPION_DATA_DIR / f"{safe_name}.json"

    if cache_path.exists():
        try:
            cached_data = json.loads(cache_path.read_text(encoding="utf-8"))
            champion_data = cached_data.get("data", {}).get(
                safe_name,
                {},
            )
            CHAMPION_MEMORY_CACHE[safe_name] = champion_data
            return champion_data
        except (json.JSONDecodeError, OSError):
            return {}

    url = (
        f"{DD_BASE_URL}/cdn/{version}/data/es_ES/champion/"
        f"{safe_name}.json"
    )

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        raw_data = response.json()

        CHAMPION_DATA_DIR.mkdir(exist_ok=True)
        cache_path.write_text(
            json.dumps(raw_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        champion_data = raw_data.get("data", {}).get(safe_name, {})
        CHAMPION_MEMORY_CACHE[safe_name] = champion_data
        return champion_data

    except requests.RequestException:
        return {}


SPELL_ICON_DIR = DATA_DIR / "spell_icons"

SPELL_NAME_TO_FILE = {
    "destello": "SummonerFlash.png",
    "flash": "SummonerFlash.png",
    "teleportación": "SummonerTeleport.png",
    "teleport": "SummonerTeleport.png",
    "aplastar": "SummonerSmite.png",
    "smite": "SummonerSmite.png",
    "ignición": "SummonerDot.png",
    "ignite": "SummonerDot.png",
    "curación": "SummonerHeal.png",
    "heal": "SummonerHeal.png",
    "barrera": "SummonerBarrier.png",
    "barrier": "SummonerBarrier.png",
    "fantasmal": "SummonerHaste.png",
    "ghost": "SummonerHaste.png",
    "extenuación": "SummonerExhaust.png",
    "exhaust": "SummonerExhaust.png",
    "purificar": "SummonerBoost.png",
    "cleanse": "SummonerBoost.png",
    "claridad": "SummonerMana.png",
}


def get_spell_icon_path(spell_name: str, version: str, *, download: bool = True) -> Path | None:
    SPELL_ICON_DIR.mkdir(parents=True, exist_ok=True)
    raw_key = spell_name.strip().lower()
    file_name = SPELL_NAME_TO_FILE.get(raw_key)
    if not file_name:
        file_name = f"Summoner{spell_name.capitalize()}.png"

    local_path = SPELL_ICON_DIR / file_name
    if local_path.exists():
        return local_path

    if not download:
        return None

    url = f"{DD_BASE_URL}/cdn/{version}/img/spell/{file_name}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except requests.RequestException:
        return None
