from __future__ import annotations

import json
import re
from urllib.request import urlopen
from pathlib import Path

ROOT = Path(__file__).parent
CHAMPION_DIR = ROOT / "champion_data"
ITEMS_PATH = ROOT / "items.json"

STYLE_MAP = {
    "Akali": ("Assassin", "AP", "Energy", ["Mid"]), "Alistar": ("Vanguard", "True", "Mana", ["Support"]),
    "Amumu": ("Vanguard", "AP", "Mana", ["Jungle", "Support"]), "Anivia": ("Mage", "AP", "Mana", ["Mid"]),
    "Annie": ("Mage", "AP", "Mana", ["Mid", "Support"]), "Aphelios": ("Marksman", "AD", "None", ["ADC"]),
    "Blitzcrank": ("Vanguard", "True", "Mana", ["Support"]), "Briar": ("Bruiser", "AD", "Health", ["Jungle", "Top"]),
    "Darius": ("Juggernaut", "AD", "Mana", ["Top"]), "Diana": ("Assassin", "AP", "Mana", ["Jungle", "Mid"]),
    "DrMundo": ("Juggernaut", "AD", "Health", ["Top", "Jungle"]), "Ekko": ("Assassin", "AP", "Mana", ["Jungle", "Mid"]),
    "Ezreal": ("Marksman", "AD", "Mana", ["ADC"]), "Gnar": ("Bruiser", "AD", "Rage", ["Top"]),
    "Hwei": ("Mage", "AP", "Mana", ["Mid", "Support"]), "Irelia": ("Skirmisher", "AD", "None", ["Top", "Mid"]),
    "Lissandra": ("Mage", "AP", "Mana", ["Mid"]), "Lucian": ("Marksman", "AD", "Mana", ["ADC"]),
    "Lulu": ("Enchanter", "AP", "Mana", ["Support"]), "Lux": ("Mage", "AP", "Mana", ["Mid", "Support"]),
    "Malphite": ("Vanguard", "AP", "Mana", ["Top", "Support"]), "Malzahar": ("Mage", "AP", "Mana", ["Mid"]),
    "Maokai": ("Vanguard", "AP", "Mana", ["Support", "Jungle"]), "Milio": ("Enchanter", "AP", "Mana", ["Support"]),
    "Mordekaiser": ("Juggernaut", "AP", "Shield", ["Top"]), "Morgana": ("Mage", "AP", "Mana", ["Support", "Mid"]),
    "Nasus": ("Juggernaut", "AD", "None", ["Top"]), "Pantheon": ("Bruiser", "AD", "Mana", ["Top", "Mid", "Support"]),
    "Poppy": ("Warden", "AD", "Courage", ["Top", "Jungle", "Support"]), "Qiyana": ("Assassin", "AD", "Mana", ["Mid"]),
    "Rammus": ("Warden", "AD", "Mana", ["Jungle"]), "Rengar": ("Assassin", "AD", "Ferocity", ["Jungle", "Top"]),
    "Rumble": ("Bruiser", "AP", "Heat", ["Top"]), "Seraphine": ("Enchanter", "AP", "Mana", ["Support", "Mid"]),
    "Swain": ("Bruiser", "AP", "Mana", ["Support", "Mid"]), "Sylas": ("Skirmisher", "AP", "Mana", ["Mid", "Top"]),
    "Syndra": ("Mage", "AP", "Mana", ["Mid"]), "Taric": ("Warden", "AP", "Mana", ["Support"]),
    "Teemo": ("Mage", "AP", "Mana", ["Top"]), "Thresh": ("Warden", "AP", "Mana", ["Support"]),
    "TwistedFate": ("Mage", "AP", "Mana", ["Mid"]), "Twitch": ("Marksman", "AD", "Mana", ["ADC"]),
    "Urgot": ("Juggernaut", "AD", "None", ["Top"]), "Varus": ("Marksman", "AD", "Mana", ["ADC"]),
    "Volibear": ("Bruiser", "AD", "Mana", ["Top", "Jungle"]), "Warwick": ("Bruiser", "AD", "Mana", ["Jungle", "Top"]),
    "Xayah": ("Marksman", "AD", "Mana", ["ADC"]), "Xerath": ("Mage", "AP", "Mana", ["Mid", "Support"]),
    "Yasuo": ("Skirmisher", "AD", "Flow", ["Mid", "Top"]), "Yunara": ("Marksman", "AD", "None", ["ADC"]),
    "Zoe": ("Mage", "AP", "Mana", ["Mid"]),
}

ALLOWED_STATS = {"attack_damage", "ability_power", "armor_penetration_percent", "magic_penetration_percent", "magic_penetration_flat", "lethality", "critical_strike_chance_percent", "attack_speed_percent", "life_steal_percent", "omnivamp_percent", "health", "mana", "armor", "magic_resistance", "ability_haste", "base_health_regeneration_percent", "base_mana_regeneration_percent", "movement_speed_flat", "movement_speed_percent", "heal_and_shield_power_percent"}


def clean(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value).casefold()


def champion_file(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    champion = raw["data"][path.stem]
    style, damage, resource, roles = STYLE_MAP.get(path.stem, ("Bruiser", "AD", "None", ["Top"]))
    stats = champion.get("stats", {})
    return {"character": champion["name"], "basic_info": {"play_style": style, "damage_type": damage, "resource_type": resource, "difficulty_floor": 5, "difficulty_ceiling": 8, "flex_potential": roles}, "combat_attributes": {"attack_damage": min(10, max(1, round(float(stats.get("attackdamage", 60)) / 15))), "attack_power": 7 if damage == "AP" else 2, "critic": 6 if style == "Marksman" else 2, "lethality": 5 if style == "Assassin" else 1}, "resistances_and_survivability": {"armor": 5, "magic_resistance": 5, "survivability_vs_damage": 5, "survivability_vs_armor": 5, "survivability_vs_cc": 5, "survivability_overall": 5}, "map_and_control": {"mobility": 5, "crowd_control": 5, "wave_clear": 5, "objective_control": 5, "side_lane_pressure": 5, "team_fight": 5, "utility": 5, "range": 5}, "power_curve_and_scaling": {"early_game": 5, "mid_game": 6, "late_game": 6, "hypercarry": 6 if style == "Marksman" else 3, "dependency_on_gold": 6, "power_spike_level": 6, "power_spike_items": []}, "common_runes": [], "matchups": {"good_against": [], "counters": []}, "strategy_and_macro": {"primary_combo": ["Q", "W", "E", "R"], "about": champion.get("title", "Campeón adaptable") + ". Ajusta las ventanas de combate a la composición enemiga."}}


def official_champion_paths() -> list[Path]:
    """Descarga la lista oficial completa; conserva el catálogo local si no hay red."""
    cache = ROOT / "champion_catalog.json"
    try:
        with urlopen("https://ddragon.leagueoflegends.com/cdn/16.17.1/data/en_US/champion.json", timeout=10) as response:
            cache.write_text(response.read().decode("utf-8"), encoding="utf-8")
    except OSError:
        pass
    if not cache.exists():
        return sorted(CHAMPION_DIR.glob("*.json"))
    catalog = json.loads(cache.read_text(encoding="utf-8")).get("data", {})
    paths = []
    for name, summary in catalog.items():
        path = CHAMPION_DIR / f"{name}.json"
        if path.exists():
            paths.append(path)
            continue
        try:
            with urlopen(f"https://ddragon.leagueoflegends.com/cdn/16.17.1/data/en_US/champion/{name}.json", timeout=10) as response:
                path.write_text(response.read().decode("utf-8"), encoding="utf-8")
            paths.append(path)
        except OSError:
            continue
    return sorted(paths)


def item_entry(item_id: str, item: dict) -> dict | None:
    gold = item.get("gold", {})
    if not isinstance(gold, dict) or gold.get("total", 0) < 2500 or item.get("into"):
        return None
    text = clean(str(item.get("name", "")) + " " + str(item.get("description", "")) + " " + str(item.get("name_en", "")))
    stats_raw = item.get("stats", {})
    mapping = {"FlatPhysicalDamageMod": "attack_damage", "FlatMagicDamageMod": "ability_power", "PercentArmorPenetrationMod": "armor_penetration_percent", "PercentMagicPenetrationMod": "magic_penetration_percent", "FlatArmorPenetrationMod": "lethality", "PercentCritChanceMod": "critical_strike_chance_percent", "PercentAttackSpeedMod": "attack_speed_percent", "PercentLifeStealMod": "life_steal_percent", "FlatHPPoolMod": "health", "FlatMPPoolMod": "mana", "FlatArmorMod": "armor", "FlatSpellBlockMod": "magic_resistance", "AbilityHasteMod": "ability_haste", "FlatMovementSpeedMod": "movement_speed_flat"}
    stats = {mapping[key]: value for key, value in stats_raw.items() if key in mapping and mapping[key] in ALLOWED_STATS}
    group = "Boots" if "boots" in text or "botas" in text else "Hydra" if "hydra" in text or "hidra" in text else "Lifeline" if "lifeline" in text or "salvavidas" in text else "Fatality" if "lethality" in text or "penetración de armadura" in text else "None"
    name_es = str(item.get("name", item.get("name_es", item_id)))
    name_en = str(item.get("name_en", ""))
    return {
        "id": str(item_id),
        "item": name_es,
        "name_en": name_en,
        "basic_info": {
            "id": str(item_id),
            "name": name_es,
            "name_en": name_en,
            "tier": "Legendary",
            "gold_cost": int(gold.get("total", 0)),
            "item_group": group,
        },
        "stats": stats,
        "functionality": {
            "has_passive": bool(item.get("description")),
            "has_active": "active" in text,
            "passive_names": [],
        },
        "classifications": {
            "intended_classes": ["Fighter"] if "attack_damage" in stats else ["Mage"],
            "counter_mechanics": ["High_Armor"] if "armor_penetration_percent" in stats or "lethality" in stats else ["None"],
        },
        "analysis": {
            "game_phase_power": "Linear",
            "about": "Comprar cuando sus estadísticas responden al plan activo.",
        },
        "synergy_multipliers": {key: 1.0 for key in stats if key in {"attack_damage", "ability_power", "critic", "lethality", "mobility", "wave_clear", "hypercarry"}},
        "counter_weights": {"armor": 1.5} if "armor_penetration_percent" in stats or "lethality" in stats else {},
    }


def main() -> None:
    champions = [champion_file(path) for path in official_champion_paths()]
    raw_items = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))["items"]
    items = [entry for item_id, item in raw_items.items() if (entry := item_entry(item_id, item))]
    (ROOT / "champions_strict.json").write_text(json.dumps(champions, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "legendary_items_strict.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"champions={len(champions)} legendary_items={len(items)}")


if __name__ == "__main__":
    main()
