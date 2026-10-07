import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests

from _paths import DATA_DIR

DD_BASE_URL = "https://ddragon.leagueoflegends.com"

ITEM_CACHE_FILE = DATA_DIR / "items.json"
ICON_DIR = DATA_DIR / "item_icons"
CHAMPION_ICON_DIR = DATA_DIR / "champion_icons"
CHAMPION_DATA_DIR = DATA_DIR / "champion_metadata"
CHAMPION_MEMORY_CACHE: dict[str, dict] = {}
RUNE_ICON_CATALOG_CACHE: dict[str, str] = {}
#: La descarga del catálogo de runas ya falló en esta ejecución (sin red).
RUNE_ICON_CATALOG_FAILED = False


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


def load_cached_item_catalog() -> tuple[str, dict]:
    """Catálogo local sin tocar la red (respaldo de arranque sin conexión)."""
    try:
        cached = json.loads(ITEM_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "16.17.1", {}

    return (
        str(cached.get("version") or "16.17.1"),
        cached.get("items") or {},
    )


def load_item_catalog() -> tuple[str, dict]:
    """Versión y catálogo de objetos, de la red si se puede.

    Bloquea (varias peticiones HTTP), así que la interfaz lo llama desde un
    worker (``StartupWindow``) y no desde el hilo de la GUI. Ante cualquier
    fallo devuelve la última copia cacheada en disco.
    """
    try:
        version = get_latest_version()
    except Exception:
        cached_version, cached_items = load_cached_item_catalog()

        if cached_items:
            return cached_version, cached_items

        version = "16.17.1"

    try:
        items = download_items(version)
    except Exception:
        items = load_cached_item_catalog()[1]

    ICON_DIR.mkdir(exist_ok=True)
    CHAMPION_ICON_DIR.mkdir(exist_ok=True)
    CHAMPION_DATA_DIR.mkdir(exist_ok=True)

    return version, items


def get_item_total_gold(item_id: int | str, item_catalog: dict) -> int:
    if (
        isinstance(item_catalog, dict)
        and "items" in item_catalog
        and isinstance(item_catalog["items"], dict)
    ):
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
    if (
        isinstance(item_catalog, dict)
        and "items" in item_catalog
        and isinstance(item_catalog["items"], dict)
    ):
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
                response = requests.get(
                    f"{DD_BASE_URL}/cdn/{version}/img/item/{item_id}.png", timeout=10
                )
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


def champion_asset_name(champion_name: str) -> str:
    """
    Nombre de campeón tal y como lo usan los assets de Data Dragon.

    La API local devuelve nombres como "Renata Glasc" o "Kog'Maw" mientras que
    Data Dragon los indexa como "Renata" y "KogMaw": el nombre del retrato, el
    del archivo de datos y el de la URL deben coincidir.
    """
    raw_key = str(champion_name or "").strip().lower()

    if raw_key in CHAMPION_IMAGE_NAME_ALIASES:
        return CHAMPION_IMAGE_NAME_ALIASES[raw_key]

    return (
        str(champion_name)
        .replace(" ", "")
        .replace(".", "")
        .replace("'", "")
        .replace("&", "")
    )


def get_champion_icon_path(
    champion_name: str,
    version: str,
    *,
    download: bool = True,
) -> Path | None:
    CHAMPION_ICON_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = champion_asset_name(champion_name)

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
                response = requests.get(
                    f"{DD_BASE_URL}/cdn/{version}/img/champion/{capitalized}.png",
                    timeout=10,
                )
                response.raise_for_status()
                cap_path.write_bytes(response.content)
                return cap_path
            except requests.RequestException:
                pass
        return None


def _imagen_splash_valida(contenido: bytes) -> bool:
    """Comprueba cabecera JPEG/PNG/WebP y tamaño mínimo; devuelve True si es imagen válida."""
    if len(contenido) < 1024:
        return False
    return contenido.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or (
        contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP"
    )


def _registrar_origen_splash(nombre_archivo: str, url: str) -> None:
    """Anota la URL de origen del splash en origenes.json sin bloquear la descarga; retorna None."""
    ruta = DATA_DIR / "champion_splashes" / "origenes.json"
    try:
        origenes = {}
        if ruta.is_file():
            cargado = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(cargado, dict):
                origenes = cargado
        origenes[nombre_archivo] = url
        ruta.write_text(
            json.dumps(origenes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except (OSError, ValueError):
        logging.getLogger(__name__).debug(
            "[assets] no se pudo registrar el origen de %s", nombre_archivo
        )


def get_champion_splash_path(
    champion_name: str, *, download: bool = True
) -> Path | None:
    """Devuelve la ruta local del splash del campeón, descargándolo solo si falta.

    El archivo se resuelve en `data/champion_splashes/<identificador>_0.jpg`
    (admite PNG/WebP ya presentes) con el identificador normalizado de Data
    Dragon, que es la misma referencia que consulta el análisis local al
    seleccionar un campeón. Si el arte local existe se devuelve sin red; si
    falta y `download` es verdadero se descarga, se valida por cabecera y se
    guarda de forma atómica, registrando la URL de origen en `origenes.json`.

    Devuelve `None` cuando no hay arte local y la descarga falla o el
    contenido no es una imagen válida: nunca propaga la excepción para que un
    fallo de recursos no descarte la actualización de datos.
    """
    identificador = "".join(
        caracter
        for caracter in champion_asset_name(champion_name)
        if caracter.isalnum()
    )
    if not identificador:
        return None
    registro = logging.getLogger(__name__)
    directorio = DATA_DIR / "champion_splashes"
    directorio.mkdir(parents=True, exist_ok=True)
    for extension in ("jpg", "png", "webp"):
        candidata = directorio / f"{identificador}_0.{extension}"
        if candidata.is_file():
            return candidata
    if not download:
        return None
    url = f"{DD_BASE_URL}/cdn/img/champion/splash/{identificador}_0.jpg"
    registro.debug("[assets] splash ausente: %s", champion_name)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        registro.warning(
            "[assets] splash no disponible para %s", champion_name, exc_info=True
        )
        return None
    contenido = response.content
    if not _imagen_splash_valida(contenido):
        registro.warning("[assets] splash inválido descargado para %s", champion_name)
        return None
    destino = directorio / f"{identificador}_0.jpg"
    temporal = directorio / f".{identificador}_0.{os.getpid()}.tmp"
    try:
        temporal.write_bytes(contenido)
        os.replace(temporal, destino)
    except OSError:
        temporal.unlink(missing_ok=True)
        registro.warning(
            "[assets] splash no guardado para %s", champion_name, exc_info=True
        )
        return None
    _registrar_origen_splash(destino.name, url)
    registro.debug("[assets] splash guardado: %s", destino)
    return destino


RUNE_ICON_DIR = DATA_DIR / "rune_icons"
_RUNE_ICON_INDEX: dict[str, Path] = {}
_RUNE_ICON_INDEX_STAMP: int | None = None

#: Runas cuyo icono ya se intentó descargar sin éxito. Sin esta memoria, cada
#: diálogo de análisis repetía las mismas peticiones fallidas en el hilo de
#: interfaz (varias décimas de segundo por icono, en el arranque).
_RUNE_ICON_MISSES: set[str] = set()


def _normalize_rune_key(name: str) -> str:
    """Clave tolerante a mayúsculas, espacios, apóstrofos y acentos."""
    ascii_name = (
        unicodedata.normalize("NFKD", str(name))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.casefold()).strip("_")


def _rune_icon_local_index() -> dict[str, Path]:
    """
    Indexa los iconos de runas ya descargados en ``data/rune_icons``.

    La carpeta mezcla dos convenciones de nombre (la de las rutas fijas y la
    del catálogo oficial), así que se indexa por nombre normalizado. El índice
    se reconstruye solo si la carpeta cambia.
    """
    global _RUNE_ICON_INDEX, _RUNE_ICON_INDEX_STAMP

    try:
        stamp = RUNE_ICON_DIR.stat().st_mtime_ns
    except OSError:
        stamp = None

    if stamp is not None and stamp == _RUNE_ICON_INDEX_STAMP:
        return _RUNE_ICON_INDEX

    index: dict[str, Path] = {}

    try:
        entries = list(RUNE_ICON_DIR.iterdir())
    except OSError:
        entries = []

    for path in entries:
        if path.suffix.lower() != ".png" or not path.is_file():
            continue
        index.setdefault(_normalize_rune_key(path.stem), path)

    _RUNE_ICON_INDEX = index
    _RUNE_ICON_INDEX_STAMP = stamp
    return index


def find_local_rune_icon(*names: str) -> Path | None:
    """Devuelve el icono local de una runa sin usar la red."""
    index = _rune_icon_local_index()

    for name in names:
        if not name:
            continue
        path = index.get(_normalize_rune_key(name))
        if path is not None:
            return path

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
        # Los fragmentos (stat mods) van planos bajo StatMods/, no en
        # subcarpeta propia: con la subcarpeta el CDN devolvía 403 y la app
        # repetía la descarga fallida en cada diálogo de análisis (cada
        # intento bloqueaba la interfaz ~0,3 s).
        "Adaptive Force": "StatMods/StatModsAdaptiveForceIcon.png",
        "Attack Speed": "StatMods/StatModsAttackSpeedIcon.png",
        "Ability Haste": "StatMods/StatModsCDRScalingIcon.png",
        "Movement Speed": "StatMods/StatModsMovementSpeedIcon.png",
        "Health Scaling": "StatMods/StatModsHealthScalingIcon.png",
        "Health": "StatMods/StatModsHealthPlusIcon.png",
        "Tenacity and Slow Resist": "StatMods/StatModsTenacityIcon.png",
        # Iconos de árbol: en el CDN van por id (7201_Precision.png, ...).
        "Precision": "Styles/7201_Precision.png",
        "Domination": "Styles/7200_Domination.png",
        "Sorcery": "Styles/7202_Sorcery.png",
        "Resolve": "Styles/7204_Resolve.png",
        "Inspiration": "Styles/7203_Whimsy.png",
        "Dominación": "Styles/7200_Domination.png",
        "Grasp of the Undying": "Styles/Resolve/GraspOfTheUndying/GraspOfTheUndying.png",
        "Aftershock": "Styles/Resolve/VeteranAftershock/VeteranAftershock.png",
        "Guardian": "Styles/Resolve/Guardian/Guardian.png",
        "Hail of Blades": "Styles/Domination/HailOfBlades/HailOfBlades.png",
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
        "Phase Rush": "Stormraider's Surge",
    }
    lookup_name = aliases.get(rune_name, rune_name)
    cache_key = _normalize_rune_key(lookup_name)
    asset_path = paths.get(rune_name) or paths.get(lookup_name)
    local_name = re.sub(r"[^A-Za-z0-9._-]+", "_", lookup_name).strip("_")
    local_path = RUNE_ICON_DIR / f"{local_name}.png"
    if local_path.exists():
        return local_path

    # La caché local mezcla nombres con espacios, guiones y minúsculas: se
    # consulta por nombre normalizado antes de gastar una descarga.
    cached_path = find_local_rune_icon(rune_name, lookup_name)
    if cached_path is not None:
        return cached_path

    if not download:
        return None

    # Ya se intentó sin éxito: reintentarlo en cada diálogo añadía una
    # espera de red por icono sin ninguna posibilidad de mejorar.
    if cache_key in _RUNE_ICON_MISSES:
        return None

    if not asset_path:
        asset_path = _rune_icon_catalog(version).get(lookup_name.lower())

    if asset_path:
        try:
            url_path = (
                asset_path
                if asset_path.startswith("perk-images/")
                else f"perk-images/{asset_path}"
            )
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
                    url_path = (
                        dynamic_path
                        if dynamic_path.startswith("perk-images/")
                        else f"perk-images/{dynamic_path}"
                    )
                    response = requests.get(
                        f"{DD_BASE_URL}/cdn/img/{url_path}", timeout=10
                    )
                    response.raise_for_status()
                    local_path.parent.mkdir(exist_ok=True)
                    local_path.write_bytes(response.content)
                    return local_path
                except requests.RequestException:
                    pass

    _RUNE_ICON_MISSES.add(cache_key)
    return None


def _rune_icon_catalog(version: str) -> dict[str, str]:
    """Catálogo oficial de runas del CDN (una sola petición por ejecución).

    Si la primera petición falla se recuerda el fallo: sin conexión, este
    método se llamaba una vez por cada runa que había que pintar y cada
    llamada volvía a esperar el timeout de red.
    """
    global RUNE_ICON_CATALOG_FAILED

    if RUNE_ICON_CATALOG_CACHE or RUNE_ICON_CATALOG_FAILED:
        return RUNE_ICON_CATALOG_CACHE

    try:
        response = requests.get(
            f"{DD_BASE_URL}/cdn/{version}/data/en_US/runesReforged.json",
            timeout=10,
        )
        response.raise_for_status()
        for style in response.json():
            RUNE_ICON_CATALOG_CACHE[str(style.get("name", "")).lower()] = style.get(
                "icon", ""
            )
            for slot in style.get("slots", []):
                for rune in slot.get("runes", []):
                    name = str(rune.get("name", "")).lower()
                    if name:
                        RUNE_ICON_CATALOG_CACHE[name] = rune.get("icon", "")
    except (requests.RequestException, ValueError, TypeError):
        RUNE_ICON_CATALOG_FAILED = True
        return RUNE_ICON_CATALOG_CACHE

    return RUNE_ICON_CATALOG_CACHE


def download_all_rune_icons(version: str) -> int:
    """Descarga en caché todos los iconos de runas y fragmentos oficiales."""
    catalog = _rune_icon_catalog(version)
    downloaded = 0
    # El catálogo cubre runas y árboles; los fragmentos no figuran en él.
    names = set(catalog) | {
        "Adaptive Force",
        "Attack Speed",
        "Ability Haste",
        "Movement Speed",
        "Health Scaling",
        "Health",
        "Tenacity and Slow Resist",
    }
    for name in names:
        before = get_rune_icon_path(name, version)
        downloaded += int(before is not None)
    return downloaded


def get_champion_data(
    champion_name: str,
    version: str,
    *,
    download: bool = True,
) -> dict:
    """Devuelve metadatos del campe?n; download controla si se permite red."""
    safe_name = champion_asset_name(champion_name)

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

    if not download:
        return {}

    url = f"{DD_BASE_URL}/cdn/{version}/data/es_ES/champion/{safe_name}.json"

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

SPELL_CANONICAL_TO_FILE = {
    "flash": "SummonerFlash.png",
    "ignite": "SummonerDot.png",
    "smite": "SummonerSmite.png",
    "teleport": "SummonerTeleport.png",
    "cleanse": "SummonerBoost.png",
    "heal": "SummonerHeal.png",
    "barrier": "SummonerBarrier.png",
    "ghost": "SummonerHaste.png",
    "exhaust": "SummonerExhaust.png",
    "clarity": "SummonerMana.png",
    "mark": "SummonerSnowball.png",
    "poro recall": "SummonerPoroRecall.png",
    "poro throw": "SummonerPoroThrow.png",
}

SPELL_ID_TO_CANONICAL = {
    1: "cleanse",
    2: "clarity",
    3: "exhaust",
    4: "flash",
    6: "ghost",
    7: "heal",
    11: "smite",
    12: "teleport",
    13: "clarity",
    14: "ignite",
    21: "barrier",
    32: "mark",
}

SPELL_ALIAS_TO_CANONICAL = {
    "flash": "flash",
    "destello": "flash",
    "summonerflash": "flash",
    "ignite": "ignite",
    "ignition": "ignite",
    "ignicion": "ignite",
    "summonerdot": "ignite",
    "smite": "smite",
    "aplastar": "smite",
    "summonersmite": "smite",
    "unleashedsmite": "smite",
    "primalsmite": "smite",
    "summonersmiteavataroffensive": "smite",
    "summonersmiteavatardefensive": "smite",
    "summonersmiteavatarutility": "smite",
    "teleport": "teleport",
    "teleportation": "teleport",
    "teleportacion": "teleport",
    "teleportaciondesatada": "teleport",
    "unleashedteleport": "teleport",
    "summonerteleport": "teleport",
    "cleanse": "cleanse",
    "purificar": "cleanse",
    "summonerboost": "cleanse",
    "heal": "heal",
    "curacion": "heal",
    "summonerheal": "heal",
    "barrier": "barrier",
    "barrera": "barrier",
    "summonerbarrier": "barrier",
    "ghost": "ghost",
    "haste": "ghost",
    "fantasmal": "ghost",
    "summonerhaste": "ghost",
    "exhaust": "exhaust",
    "extenuacion": "exhaust",
    "summonerexhaust": "exhaust",
    "clarity": "clarity",
    "claridad": "clarity",
    "summonermana": "clarity",
    "mark": "mark",
    "snowball": "mark",
    "snowballmark": "mark",
    "summonersnowball": "mark",
    "summonersnowballmark": "mark",
    "pororecall": "poro recall",
    "summonerpororecall": "poro recall",
    "porothrow": "poro throw",
    "summonerporothrow": "poro throw",
}


@dataclass(frozen=True)
class ResolucionIconoHechizo:
    """Describe el resultado de normalizar y resolver un hechizo de invocador."""

    identificador_crudo: str
    identificador_normalizado: str | None
    ruta: Path | None
    estado: str


def normalizar_hechizo_invocador(hechizo: object) -> str | None:
    """Convierte IDs, nombres y claves internas a un nombre canónico.

    Args:
        hechizo: Valor de Live Client Data o identificador individual.
    Returns:
        Nombre canónico, o None cuando el identificador no se reconoce.
    """
    campos = ("id", "displayName", "name", "rawDisplayName", "rawDescription")
    valores: list[object] = []
    if isinstance(hechizo, dict):
        valores.extend(hechizo.get(campo) for campo in campos)
    else:
        valores.append(hechizo)
    for valor in valores:
        if valor is None or isinstance(valor, bool):
            continue
        texto = str(valor).strip()
        if not texto:
            continue
        if texto.isdigit() and int(texto) in SPELL_ID_TO_CANONICAL:
            return SPELL_ID_TO_CANONICAL[int(texto)]
        limpio = unicodedata.normalize("NFKD", texto)
        limpio = "".join(
            caracter for caracter in limpio if not unicodedata.combining(caracter)
        )
        clave = re.sub(r"[^a-z0-9]", "", limpio.casefold())
        clave = re.sub(r"^generatedtipsummonerspell", "", clave)
        clave = re.sub(r"(?:displayname|description)$", "", clave)
        canonical = SPELL_ALIAS_TO_CANONICAL.get(clave)
        if canonical:
            return canonical
    return None


def resolver_icono_hechizo_invocador(
    hechizo: object,
    version: str,
    *,
    download: bool = False,
) -> ResolucionIconoHechizo:
    """Clasifica la ausencia de datos y la resolución del asset del hechizo.

    Args:
        hechizo: Registro LIVE, nombre, clave interna o ID numérico.
        version: Versión de Data Dragon para descargar si se autoriza.
        download: Permite descargar el asset cuando la caché local no lo tenga.
    Returns:
        Estado de resolución con identificador, ruta y estado de datos.
    """
    if isinstance(hechizo, dict):
        crudo = str(
            hechizo.get("displayName")
            or hechizo.get("name")
            or hechizo.get("rawDisplayName")
            or hechizo.get("id")
            or ""
        ).strip()
    else:
        crudo = "" if hechizo is None else str(hechizo).strip()
    if not crudo:
        return ResolucionIconoHechizo("", None, None, "sin_datos")
    canonical = normalizar_hechizo_invocador(hechizo)
    if canonical is None:
        return ResolucionIconoHechizo(crudo, None, None, "sin_resolver")
    ruta = get_spell_icon_path(canonical, version, download=download)
    if ruta is None or not ruta.exists():
        return ResolucionIconoHechizo(crudo, canonical, ruta, "asset_ausente")
    return ResolucionIconoHechizo(crudo, canonical, ruta, "resuelto")


def get_spell_icon_path(
    spell_name: object,
    version: str,
    *,
    download: bool = True,
) -> Path | None:
    """Resuelve un hechizo canónico al asset local de Data Dragon.

    Args:
        spell_name: Nombre, alias, ID o registro de hechizo.
        version: Versión de Data Dragon usada para una descarga opcional.
        download: Permite descargar el icono si no está en caché.
    Returns:
        Ruta existente del icono o None si no se pudo resolver.
    """
    SPELL_ICON_DIR.mkdir(parents=True, exist_ok=True)
    canonical = normalizar_hechizo_invocador(spell_name)
    if canonical is None:
        return None
    file_name = SPELL_CANONICAL_TO_FILE.get(canonical)
    if not file_name:
        return None

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


#: Iconos de las habilidades (Q/W/E/R) de cada campeón.
ABILITY_ICON_DIR = DATA_DIR / "ability_icons"
#: Caché del JSON completo del campeón. Va en su propia carpeta (y no en
#: `champion_data/`) para no colisionar con las matrices de `ChampionVariantService`.
CHAMPION_ABILITIES_DIR = DATA_DIR / "champion_abilities"
CHAMPION_ABILITIES_CACHE: dict[str, dict[str, dict]] = {}

#: Orden de las habilidades según aparecen en los `spells` de Data Dragon.
ABILITY_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")


def get_champion_abilities(
    champion_name: str, version: str, *, download: bool = True
) -> dict[str, dict[str, str]]:
    """Habilidades Q/W/E/R del campeón (nombre e imagen) desde Data Dragon.

    Devuelve ``{"Q": {"name": .., "id": .., "image": "AatroxQ.png"}, ...}``.
    El JSON completo del campeón se memoriza y se guarda en
    ``data/champion_abilities`` para no chocar con las matrices de variantes.
    """
    safe_name = champion_asset_name(champion_name)
    cached = CHAMPION_ABILITIES_CACHE.get(safe_name)
    if cached is not None:
        return cached

    cache_path = CHAMPION_ABILITIES_DIR / f"{safe_name}.json"
    raw: dict = {}
    if cache_path.exists():
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}

    if not raw and not download:
        return {}
    if not raw:
        url = f"{DD_BASE_URL}/cdn/{version}/data/es_ES/champion/{safe_name}.json"
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            raw = response.json()
            CHAMPION_ABILITIES_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except requests.RequestException:
            return {}

    champion = raw.get("data", {}).get(safe_name, {}) if isinstance(raw, dict) else {}
    spells = champion.get("spells", []) if isinstance(champion, dict) else []

    result: dict[str, dict[str, str]] = {}
    for key, spell in zip(ABILITY_KEYS, spells):
        if not isinstance(spell, dict):
            continue
        image = spell.get("image", {})
        result[key] = {
            "name": str(spell.get("name", "")),
            "id": str(spell.get("id", "")),
            "image": str(image.get("full", "")) if isinstance(image, dict) else "",
        }

    CHAMPION_ABILITIES_CACHE[safe_name] = result
    return result


def get_ability_icon_path(
    champion_name: str,
    key: str,
    version: str,
    *,
    download: bool = True,
) -> Path | None:
    """Icono de la habilidad ``key`` (``Q``/``W``/``E``/``R``) del campeón."""
    ability_key = str(key).strip().upper()
    if ability_key not in ABILITY_KEYS:
        return None

    ability = get_champion_abilities(champion_name, version, download=download).get(
        ability_key
    )
    image = str(ability.get("image", "")) if isinstance(ability, dict) else ""
    if not image:
        return None

    ABILITY_ICON_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = champion_asset_name(champion_name)
    local_path = ABILITY_ICON_DIR / f"{safe_name}{ability_key}.png"
    if local_path.exists():
        return local_path

    if not download:
        return None

    url = f"{DD_BASE_URL}/cdn/{version}/img/spell/{image}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except requests.RequestException:
        return None
