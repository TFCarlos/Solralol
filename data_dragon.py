import json
from pathlib import Path

import requests

DD_BASE_URL = "https://ddragon.leagueoflegends.com"

DATA_DIR = Path("data")
ITEM_CACHE_FILE = DATA_DIR / "items.json"
ICON_DIR = DATA_DIR / "item_icons"
CHAMPION_ICON_DIR = DATA_DIR / "champion_icons"
CHAMPION_DATA_DIR = DATA_DIR / "champion_data"
CHAMPION_MEMORY_CACHE: dict[str, dict] = {}


def get_latest_version() -> str:
    response = requests.get(f"{DD_BASE_URL}/api/versions.json", timeout=10)
    response.raise_for_status()
    return response.json()[0]


def download_items(version: str) -> dict:
    url = f"{DD_BASE_URL}/cdn/{version}/data/es_ES/item.json"

    response = requests.get(url, timeout=20)
    response.raise_for_status()

    items = response.json()["data"]

    DATA_DIR.mkdir(exist_ok=True)

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
    version = get_latest_version()
    items = download_items(version)

    ICON_DIR.mkdir(exist_ok=True)
    CHAMPION_ICON_DIR.mkdir(exist_ok=True)
    CHAMPION_DATA_DIR.mkdir(exist_ok=True)

    return version, items


def get_item_total_gold(item_id: int | str, item_catalog: dict) -> int:
    item = item_catalog.get(str(item_id))

    if item is None:
        return 0

    return int(item.get("gold", {}).get("total", 0))


def get_item_icon_path(
    item_id: int | str,
    item_catalog: dict,
    version: str,
) -> Path | None:
    item_id = str(item_id)
    item = item_catalog.get(item_id)

    if item is None:
        return None

    image_name = item.get("image", {}).get("full")

    if not image_name:
        return None

    local_path = ICON_DIR / image_name

    if local_path.exists():
        return local_path

    icon_url = f"{DD_BASE_URL}/cdn/{version}/img/item/{image_name}"

    try:
        response = requests.get(icon_url, timeout=10)
        response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except requests.RequestException:
        return None


def get_champion_icon_path(
    champion_name: str,
    version: str,
) -> Path | None:
    safe_name = champion_name.replace(" ", "").replace(".", "")

    local_path = CHAMPION_ICON_DIR / f"{safe_name}.png"

    if local_path.exists():
        return local_path

    icon_url = (
        f"{DD_BASE_URL}/cdn/{version}/img/champion/{safe_name}.png"
    )

    try:
        response = requests.get(icon_url, timeout=10)
        response.raise_for_status()
        local_path.write_bytes(response.content)
        return local_path
    except requests.RequestException:
        return None


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