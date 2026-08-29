from __future__ import annotations

from typing import Any


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def get_kda(player: dict) -> str:
    """Devuelve el KDA con formato kills/deaths/assists."""
    scores = player.get("scores", {})

    if not isinstance(scores, dict):
        scores = {}

    return (
        f"{scores.get('kills', 0)}/"
        f"{scores.get('deaths', 0)}/"
        f"{scores.get('assists', 0)}"
    )


def _catalog_items(
    item_catalog: dict[str, Any],
) -> dict[str, Any]:
    """
    Acepta ambos formatos usados por SolraLoL:

    - {"items": {"1055": {...}}}
    - {"1055": {...}}
    """
    items = item_catalog.get(
        "items",
        item_catalog,
    )

    return items if isinstance(items, dict) else {}


def _item_id(item: Any) -> str:
    if isinstance(item, dict):
        value = (
            item.get("itemID")
            or item.get("itemId")
            or item.get("id")
            or 0
        )
    else:
        value = item

    try:
        return str(int(value))
    except (TypeError, ValueError):
        return ""


def get_inventory_value(
    player: dict,
    item_catalog: dict,
) -> int:
    """
    Calcula el valor total de los objetos en inventario.

    Se utiliza el precio expuesto por la API local cuando exista;
    en caso contrario, se consulta el catálogo Data Dragon.
    """
    total = 0
    catalog = _catalog_items(item_catalog)

    for live_item in player.get("items", []):
        item_id = _item_id(live_item)

        if not item_id:
            continue

        price = (
            live_item.get("price")
            if isinstance(live_item, dict)
            else None
        )

        if isinstance(price, (int, float)) and price > 0:
            total += int(price)
            continue

        catalog_item = catalog.get(
            item_id,
            {},
        )

        gold = catalog_item.get(
            "gold",
            {},
        )

        if isinstance(gold, dict):
            total += int(
                _number(
                    gold.get(
                        "total",
                        gold.get("base", 0),
                    )
                )
            )

    return total


def get_item_description(item: dict) -> str:
    """Une textos de objeto para detectar efectos como antiheal."""
    parts = (
        item.get("name", ""),
        item.get("description", ""),
        item.get("plaintext", ""),
    )

    return " ".join(
        str(part)
        for part in parts
        if part
    ).casefold()


def calculate_item_stats(
    player: dict,
    item_catalog: dict,
) -> dict[str, float | bool]:
    """
    Calcula solo estadísticas procedentes del inventario.

    No incluye estadísticas base, nivel, runas ni buffs.
    La suma de base + nivel + objetos se hace con
    calculate_champion_total_stats().

    Data Dragon no siempre utiliza el mismo nombre para campos de
    penetración según objeto o versión. Por ello se consultan las
    variantes conocidas y se conserva también un flag de detección.
    """
    stats = {
        "hp": 0.0,
        "ad": 0.0,
        "ap": 0.0,
        "armor": 0.0,
        "mr": 0.0,
        "crit": 0.0,
        "lethality": 0.0,
        "armor_pen_percent": 0.0,
        "life_steal_percent": 0.0,
        "attack_speed_percent": 0.0,
        "move_speed": 0.0,
        "grievous_wounds": False,
        "has_armor_penetration": False,
    }

    antiheal_terms = (
        "grievous wounds",
        "heridas graves",
        "antiheal",
        "anti-curación",
    )

    armor_penetration_terms = (
        "armor penetration",
        "armor pen",
        "penetración de armadura",
        "penetracion de armadura",
        "letalidad",
        "lethality",
    )

    catalog = _catalog_items(item_catalog)

    def read_stat(
        item_stats: dict,
        *keys: str,
    ) -> float:
        for key in keys:
            if key in item_stats:
                return _number(item_stats[key])

        return 0.0

    for live_item in player.get("items", []):
        item_id = _item_id(live_item)

        if not item_id:
            continue

        item = catalog.get(
            item_id,
            {},
        )

        if not isinstance(item, dict):
            continue

        item_stats = item.get("stats", {})

        if not isinstance(item_stats, dict):
            item_stats = {}

        stats["hp"] += read_stat(
            item_stats,
            "FlatHPPoolMod",
            "FlatHPMod",
        )

        stats["ad"] += read_stat(
            item_stats,
            "FlatPhysicalDamageMod",
        )

        stats["ap"] += read_stat(
            item_stats,
            "FlatMagicDamageMod",
        )

        stats["armor"] += read_stat(
            item_stats,
            "FlatArmorMod",
        )

        stats["mr"] += read_stat(
            item_stats,
            "FlatSpellBlockMod",
        )

        stats["crit"] += read_stat(
            item_stats,
            "FlatCritChanceMod",
            "PercentCritChanceMod",
        )

        stats["lethality"] += read_stat(
            item_stats,
            "FlatArmorPenetrationMod",
            "FlatArmorPenetration",
            "flatArmorPenetration",
        )

        stats["armor_pen_percent"] += read_stat(
            item_stats,
            "PercentArmorPenetrationMod",
            "PercentArmorPenetration",
            "percentArmorPenetration",
        )
        stats["life_steal_percent"] += read_stat(
            item_stats,
            "PercentLifeStealMod",
            "PercentLifeSteal",
            "percentLifeSteal",
            "FlatLifeStealMod",
        )

        # Data Dragon moderno deja algunos efectos en `description` y no en
        # `stats`. Lord Dominik's Regards es penetración porcentual en ese caso.
        # Los porcentajes se almacenan como fracción: 0.35 representa 35%.
        description = get_item_description(item)

        if item_id in {"3036", "3033"}:
            stats["armor_pen_percent"] += 0.35
            stats["has_armor_penetration"] = True

        stats["attack_speed_percent"] += read_stat(
            item_stats,
            "PercentAttackSpeedMod",
        )

        stats["move_speed"] += read_stat(
            item_stats,
            "FlatMovementSpeedMod",
        )

        if any(
            term in description
            for term in antiheal_terms
        ):
            stats["grievous_wounds"] = True

        if any(
            term in description
            for term in armor_penetration_terms
        ):
            stats["has_armor_penetration"] = True

    stats["has_armor_penetration"] = bool(
        stats["has_armor_penetration"]
        or _number(stats["lethality"]) > 0
        or _number(stats["armor_pen_percent"]) > 0
    )

    return stats

def calculate_champion_total_stats(
    champion_data: dict,
    level: int | float,
    item_stats: dict[str, float | bool],
    live_stats: dict | None = None,
) -> dict[str, float | bool]:
    """
    Estima estadísticas totales:

    estadística base
    + crecimiento por nivel
    + objetos

    Las runas, buffs, pasivas temporales y bonificaciones de modo no
    se incluyen para enemigos hasta que la fuente las exponga.

    Para el jugador local, los valores recibidos desde championStats
    tienen prioridad porque ya incluyen runas, buffs y pasivas activas.
    """
    champion_stats = champion_data.get(
        "stats",
        {},
    )

    if not isinstance(champion_stats, dict):
        champion_stats = {}

    try:
        current_level = max(1, int(level))
    except (TypeError, ValueError):
        current_level = 1

    levels_gained = current_level - 1

    estimated = {
        "hp": (
            _number(champion_stats.get("hp"))
            + _number(champion_stats.get("hpperlevel"))
            * levels_gained
            + _number(item_stats.get("hp"))
        ),
        "ad": (
            _number(champion_stats.get("attackdamage"))
            + _number(
                champion_stats.get(
                    "attackdamageperlevel",
                )
            )
            * levels_gained
            + _number(item_stats.get("ad"))
        ),
        "ap": _number(item_stats.get("ap")),
        "armor": (
            _number(champion_stats.get("armor"))
            + _number(champion_stats.get("armorperlevel"))
            * levels_gained
            + _number(item_stats.get("armor"))
        ),
        "mr": (
            _number(champion_stats.get("spellblock"))
            + _number(
                champion_stats.get(
                    "spellblockperlevel",
                )
            )
            * levels_gained
            + _number(item_stats.get("mr"))
        ),
        "crit": _number(item_stats.get("crit")),
        "lethality": _number(item_stats.get("lethality")),
        "armor_pen_percent": _number(
            item_stats.get(
                "armor_pen_percent",
            )
        ),
        "life_steal_percent": _number(
            item_stats.get(
                "life_steal_percent",
                0,
            )
        ),
        "attack_speed_percent": _number(
            item_stats.get(
                "attack_speed_percent",
            )
        ),
        "move_speed": (
            _number(champion_stats.get("movespeed"))
            + _number(item_stats.get("move_speed"))
        ),
        "grievous_wounds": bool(
            item_stats.get(
                "grievous_wounds",
                False,
            )
        ),
        "has_armor_penetration": bool(
            item_stats.get(
                "has_armor_penetration",
                False,
            )
        ),
    }

    if not isinstance(live_stats, dict):
        return estimated

    local_overrides = {
        "hp": (
            "maxHealth",
            "maxhealth",
            "healthMax",
        ),
        "ad": (
            "attackDamage",
            "attackdamage",
        ),
        "ap": (
            "abilityPower",
            "abilitypower",
        ),
        "armor": ("armor",),
        "mr": (
            "magicResist",
            "magicresist",
            "spellBlock",
        ),
        "crit": (
            "critChance",
            "critchance",
        ),
        "lethality": (
            "lethality",
            "armorPenetrationFlat",
        ),
        "armor_pen_percent": (
            "armorPenetrationPercent",
            "percentArmorPenetration",
        ),
        "move_speed": (
            "moveSpeed",
            "movespeed",
        ),
    }

    for output_key, source_keys in local_overrides.items():
        for source_key in source_keys:
            if source_key not in live_stats:
                continue

            value = _number(live_stats.get(source_key))

            if value > 0:
                estimated[output_key] = value

            break

    return estimated


def calculate_estimated_enemy_stats(
    player: dict,
    champion_data: dict,
    item_catalog: dict,
) -> dict[str, float | bool]:
    """
    Compatibilidad con el resto de la aplicación.

    Estima estadística de rival desde campeón, nivel e inventario.
    """
    level = player.get(
        "level",
        player.get(
            "championLevel",
            1,
        ),
    )

    item_stats = calculate_item_stats(
        player,
        item_catalog,
    )

    return calculate_champion_total_stats(
        champion_data,
        level,
        item_stats,
    )


def normalize_live_stats(
    raw_stats: dict,
) -> dict[str, float]:
    """Normaliza championStats del jugador local."""
    if not isinstance(raw_stats, dict):
        raw_stats = {}

    def read(*keys: str) -> float:
        for key in keys:
            if key in raw_stats:
                return _number(raw_stats[key])
        return 0.0

    return {
        "hp": read(
            "maxHealth",
            "maxhealth",
            "healthMax",
        ),
        "ap": read(
            "abilityPower",
            "abilitypower",
        ),
        "ad": read(
            "attackDamage",
            "attackdamage",
        ),
        "armor": read("armor"),
        "mr": read(
            "magicResist",
            "magicresist",
            "spellBlock",
        ),
        "crit": read(
            "critChance",
            "critchance",
        ),
        "lethality": read(
            "lethality",
            "armorPenetrationFlat",
        ),
        "armor_pen_percent": read(
            "armorPenetrationPercent",
            "percentArmorPenetration",
        ),
    }


def get_stat_chips(
    stats: dict,
    estimated: bool,
) -> list[str]:
    """Convierte estadísticas en chips compactos."""
    prefix = "≈" if estimated else ""
    chips = []

    if _number(stats.get("hp")) > 0:
        chips.append(
            f"♥ {prefix}VIDA {int(_number(stats['hp']))}"
        )

    if _number(stats.get("ap")) > 0:
        chips.append(
            f"✦ {prefix}AP {int(_number(stats['ap']))}"
        )

    if _number(stats.get("ad")) > 0:
        chips.append(
            f"⚔ {prefix}AD {int(_number(stats['ad']))}"
        )

    if _number(stats.get("armor")) > 0:
        chips.append(
            f"🛡 {prefix}ARM {int(_number(stats['armor']))}"
        )

    if _number(stats.get("mr")) > 0:
        chips.append(
            f"◈ {prefix}MR {int(_number(stats['mr']))}"
        )

    crit = _number(stats.get("crit"))
    if crit > 0:
        crit = crit * 100 if crit <= 1 else crit
        chips.append(f"✹ {prefix}CRIT {int(crit)}%")

    if _number(stats.get("lethality")) > 0:
        chips.append(
            f"⚑ {prefix}LET "
            f"{int(_number(stats['lethality']))}"
        )

    penetration = _number(
        stats.get("armor_pen_percent")
    )

    if penetration > 0:
        penetration = (
            penetration * 100
            if penetration <= 1
            else penetration
        )
        chips.append(
            f"➟ {prefix}PEN ARM "
            f"{int(penetration)}%"
        )
        life_steal = _number(
            stats.get("life_steal_percent")
        )

        if life_steal > 0:
            life_steal = (
                life_steal * 100
                if life_steal <= 1
                else life_steal
            )

            chips.append(
                f"♥ {prefix}ROBO DE VIDA "
                f"{int(life_steal)}%"
            )
        
    if stats.get("grievous_wounds"):
        chips.append("☠ HERIDAS GRAVES")

    return chips


def get_rune_summary(player: dict) -> str:
    """Resume las runas visibles desde Live Client Data API."""
    runes = player.get("runes", {})

    if not isinstance(runes, dict):
        runes = {}

    keystone = runes.get(
        "keystone",
        {},
    ).get(
        "displayName",
        "Runa clave desconocida",
    )

    primary_tree = runes.get(
        "primaryRuneTree",
        {},
    ).get(
        "displayName",
        "Árbol primario desconocido",
    )

    secondary_tree = runes.get(
        "secondaryRuneTree",
        {},
    ).get(
        "displayName",
        "Árbol secundario desconocido",
    )

    return (
        f"{keystone} · "
        f"{primary_tree} / {secondary_tree}"
    )