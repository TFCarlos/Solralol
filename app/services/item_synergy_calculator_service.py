"""Servicio para reconstruir y calcular matemáticamente las sinergias y contrapesos de los objetos de League of Legends.

Permite reconstruir los objetos legendarios y completados directamente desde la API oficial de Data Dragon,
extrayendo:
  - Precio actualizado (gold cost)
  - Estadísticas activas (AD, AP, Vida, Armadura, MR, Velocidad de ataque, Crítico, Robo de vida,
    Aceleración de habilidad, Letalidad, Penetraciones %, etc.)
  - Pasivas y activas oficiales
  - Clasificaciones de arquetipos y mecánicas counter
  - Multiplicadores de sinergia (`synergy_multipliers`) calculados con fórmulas cuantitativas
  - Contrapesos (`counter_weights`) calculados según penetraciones y mecánicas anti-tanque
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from data_dragon import download_items, get_latest_version, load_item_catalog


class ItemSynergyCalculatorService:
    """Calculadora cuantitativa y generador de objetos a partir de Data Dragon."""

    DEFAULT_RULES_PATH = Path(__file__).parents[2] / "data" / "passive_rules.json"
    DEFAULT_ITEMS_PATH = Path(__file__).parents[2] / "data" / "legendary_items_strict.json"

    def __init__(self, rules_path: Path | None = None) -> None:
        self.rules_path = rules_path or self.DEFAULT_RULES_PATH
        self.rules = self._load_rules()

    def _load_rules(self) -> dict[str, Any]:
        """Carga las reglas de pasivas desde el archivo de configuración JSON o usa reglas por defecto."""
        if self.rules_path and self.rules_path.exists():
            try:
                data = json.loads(self.rules_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "exact_passives": {
                "Giant Slayer": {"counter_weights": {"survivability_vs_damage": 0.3}},
                "Carve": {"counter_weights": {"armor": 0.3, "survivability_vs_armor": 0.3}},
                "Magical Opus": {"synergy_multipliers": {"attack_power": 0.3}},
                "Eminence": {"synergy_multipliers": {"attack_damage": 0.3}},
                "Rebirth": {"synergy_multipliers": {"hypercarry": 0.3}},
                "Lifeline": {"synergy_multipliers": {"hypercarry": 0.2, "durability": 0.2}},
                "Spellblade": {"dynamic_spellblade": True, "bonus": 0.2},
                "Immolate": {"synergy_multipliers": {"wave_clear": 0.1, "durability": 0.1}},
                "Cleave": {"synergy_multipliers": {"wave_clear": 0.2}},
                "Crescent": {"synergy_multipliers": {"wave_clear": 0.2}},
                "Cloudburst": {"synergy_multipliers": {"mobility": 0.2}},
                "Supersonic": {"synergy_multipliers": {"mobility": 0.2}},
                "Wraith Step": {"synergy_multipliers": {"mobility": 0.1}},
                "Soulrend": {"synergy_multipliers": {"mobility": 0.1}},
                "Stasis": {"synergy_multipliers": {"hypercarry": 0.3}},
                "Quicksilver": {"synergy_multipliers": {"hypercarry": 0.2}},
                "Purify": {"synergy_multipliers": {"hypercarry": 0.2}},
                "Consecration": {"synergy_multipliers": {"hypercarry": 0.2}},
                "Echo": {"synergy_multipliers": {"wave_clear": 0.1}},
                "Torment": {"counter_weights": {"survivability_vs_damage": 0.3}},
                "Azakana Gaze": {"counter_weights": {"survivability_vs_damage": 0.3}},
                "Dissolve": {"counter_weights": {"magic_resistance": 0.3, "survivability_vs_damage": 0.3}},
                "Grievous Wounds": {"synergy_multipliers": {"hypercarry": 0.1}},
                "Shield Reaver": {"synergy_multipliers": {"hypercarry": 0.1}},
                "Death and Taxes": {"synergy_multipliers": {"critic": 0.2}},
                "Bring It Down": {"synergy_multipliers": {"critic": 0.2}, "counter_weights": {"survivability_vs_damage": 0.3}},
                "Infinite Precision": {"synergy_multipliers": {"critic": 0.3}},
            },
            "keyword_rules": [
                {"keywords": ["slayer", "giant", "dominik", "percent health"], "counter_weights": {"survivability_vs_damage": 0.3}},
                {"keywords": ["cleave", "crescent"], "synergy_multipliers": {"wave_clear": 0.2}},
                {"keywords": ["spellblade", "sheen"], "dynamic_spellblade": True, "bonus": 0.2},
                {"keywords": ["lifeline", "sterak", "maw", "shieldbow"], "synergy_multipliers": {"hypercarry": 0.2, "durability": 0.2}},
                {"keywords": ["shield", "heal"], "synergy_multipliers": {"heal_shield_power": 0.2}},
                {"keywords": ["move", "speed", "dash", "step"], "synergy_multipliers": {"mobility": 0.1}},
                {"keywords": ["shred", "carve"], "counter_weights": {"armor": 0.3, "survivability_vs_armor": 0.3}},
                {"keywords": ["dissolve", "void"], "counter_weights": {"magic_resistance": 0.3, "survivability_vs_damage": 0.3}},
            ],
        }

    # ------------------------------------------------------------------
    # Fórmulas de cálculo de multiplicadores base
    # ------------------------------------------------------------------

    def calculate_base_multipliers(self, stats: dict[str, Any]) -> dict[str, float]:
        """Calcula los multiplicadores de sinergia base a partir de las estadísticas directas del objeto."""
        if not isinstance(stats, dict):
            return {}

        synergies: dict[str, float] = {}

        # 1. Attack Damage (AD)
        ad = float(stats.get("attack_damage", 0))
        if ad > 0:
            synergies["attack_damage"] = round(1.0 + (ad / 10.0) * 0.1, 2)

        # 2. Ability Power (AP)
        ap = float(stats.get("ability_power", 0))
        if ap > 0:
            synergies["attack_power"] = round(1.0 + (ap / 13.0) * 0.1, 2)

        # 3. Crítico
        crit = float(stats.get("critical_strike_chance_percent", 0))
        if crit > 0:
            synergies["critic"] = round(1.0 + (crit / 5.0) * 0.1, 2)

        # 4. Letalidad
        lethality = float(stats.get("lethality", 0))
        if lethality > 0:
            synergies["lethality"] = round(1.0 + (lethality / 5.0) * 0.1, 2)

        # 5. Velocidad de movimiento
        ms_pct = float(stats.get("movement_speed_percent", 0))
        ms_flat = float(stats.get("movement_speed_flat", 0))
        if ms_pct > 0 or ms_flat > 0:
            val = (ms_pct / 5.0) * 0.1 if ms_pct > 0 else (ms_flat / 25.0) * 0.1
            synergies["mobility"] = round(1.0 + val, 2)

        # 6. Hypercarry (Acumula aceleración de habilidad, velocidad de ataque, tenacidad)
        as_pct = float(stats.get("attack_speed_percent", 0))
        ah = float(stats.get("ability_haste", 0))
        tenacity = float(stats.get("tenacity", 0))

        hyper_inc = 0.0
        if as_pct > 0:
            hyper_inc += (as_pct / 8.0) * 0.1
        if ah > 0:
            hyper_inc += (ah / 3.0) * 0.1
        if tenacity > 0:
            hyper_inc += (tenacity / 10.0) * 0.1

        if hyper_inc > 0:
            synergies["hypercarry"] = round(1.0 + hyper_inc, 2)

        # 7. Sustain (Robo de vida, omnivampirismo, regeneración)
        ls = float(stats.get("life_steal_percent", 0))
        omni = float(stats.get("omnivamp_percent", 0))
        if ls > 0 or omni > 0:
            sustain_inc = (ls / 3.0) * 0.1 + (omni * 0.1)
            synergies["sustain"] = round(1.0 + sustain_inc, 2)

        # 8. Durability (Vida, Armadura, Resistencia Mágica)
        hp = float(stats.get("health", 0))
        armor = float(stats.get("armor", 0))
        mr = float(stats.get("magic_resistance", 0))

        durability_inc = 0.0
        if hp > 0:
            durability_inc += (hp / 100.0) * 0.1
        if armor > 0:
            durability_inc += (armor / 10.0) * 0.1
        if mr > 0:
            durability_inc += (mr / 10.0) * 0.1

        if durability_inc > 0:
            synergies["durability"] = round(1.0 + durability_inc, 2)

        # 9. Heal and Shield Power
        hsp = float(stats.get("heal_and_shield_power_percent", 0))
        if hsp > 0:
            synergies["heal_shield_power"] = round(1.0 + (hsp / 5.0) * 0.1, 2)

        return synergies

    # ------------------------------------------------------------------
    # Bonificaciones por pasivas y activas
    # ------------------------------------------------------------------

    def apply_passive_bonuses(
        self,
        passive_names: list[str],
        stats: dict[str, Any],
        synergies: dict[str, float],
        counter_weights: dict[str, float],
    ) -> None:
        """Aplica bonificaciones adicionales a las sinergias y contrapesos basadas en pasivas y activas."""
        if not isinstance(passive_names, list):
            return

        exact_rules: dict[str, Any] = self.rules.get("exact_passives", {})
        keyword_rules: list[dict[str, Any]] = self.rules.get("keyword_rules", [])

        ad = float(stats.get("attack_damage", 0))
        ap = float(stats.get("ability_power", 0))

        for passive in passive_names:
            p_name = str(passive).strip()
            p_lower = p_name.lower()

            matched = False

            # 1. Búsqueda exacta
            if p_name in exact_rules or p_lower in (k.lower() for k in exact_rules):
                matched_rule = next(
                    (v for k, v in exact_rules.items() if k.lower() == p_lower),
                    None,
                )
                if matched_rule:
                    self._apply_rule(matched_rule, ad, ap, synergies, counter_weights)
                    matched = True

            # 2. Búsqueda por palabras clave (si no hubo coincidencia exacta)
            if not matched:
                for kw_rule in keyword_rules:
                    keywords = kw_rule.get("keywords", [])
                    if any(kw in p_lower for kw in keywords):
                        self._apply_rule(kw_rule, ad, ap, synergies, counter_weights)

    def _apply_rule(
        self,
        rule: dict[str, Any],
        ad: float,
        ap: float,
        synergies: dict[str, float],
        counter_weights: dict[str, float],
    ) -> None:
        """Aplica una regla de pasiva individual."""
        for key, bonus in rule.get("synergy_multipliers", {}).items():
            current = synergies.get(key, 1.0)
            synergies[key] = round(current + float(bonus), 2)

        for key, bonus in rule.get("counter_weights", {}).items():
            current = counter_weights.get(key, 0.0)
            counter_weights[key] = round(current + float(bonus), 2)

        if rule.get("dynamic_spellblade"):
            bonus = float(rule.get("bonus", 0.2))
            if ad >= ap:
                current = synergies.get("attack_damage", 1.0)
                synergies["attack_damage"] = round(current + bonus, 2)
            else:
                current = synergies.get("attack_power", 1.0)
                synergies["attack_power"] = round(current + bonus, 2)

    # ------------------------------------------------------------------
    # Cálculo de contrapesos (counter_weights)
    # ------------------------------------------------------------------

    def calculate_counter_weights(
        self,
        stats: dict[str, Any],
        functionality: dict[str, Any],
        classifications: dict[str, Any],
    ) -> dict[str, float]:
        """Calcula los contrapesos (penetración, trituración y daño anti-tanque) de un objeto."""
        counter_weights: dict[str, float] = {}

        if not isinstance(stats, dict):
            stats = {}

        # 1. Penetración de armadura %
        armor_pen = float(stats.get("armor_penetration_percent", 0))
        if armor_pen > 0:
            val = round((armor_pen / 5.0) * 0.1, 2)
            counter_weights["armor"] = val
            counter_weights["survivability_vs_armor"] = val

        # 2. Penetración mágica %
        magic_pen_pct = float(stats.get("magic_penetration_percent", 0))
        if magic_pen_pct > 0:
            val = round((magic_pen_pct / 5.0) * 0.1, 2)
            counter_weights["magic_resistance"] = val
            counter_weights["survivability_vs_damage"] = val

        # 3. Penetración mágica plana
        magic_pen_flat = float(stats.get("magic_penetration_flat", 0))
        if magic_pen_flat > 0:
            val = round((magic_pen_flat / 5.0) * 0.05, 2)
            counter_weights["magic_resistance"] = round(counter_weights.get("magic_resistance", 0.0) + val, 2)

        # 4. Clasificaciones de counter_mechanics
        if isinstance(classifications, dict):
            mechanics = classifications.get("counter_mechanics", [])
            if isinstance(mechanics, list):
                for mech in mechanics:
                    m = str(mech).lower()
                    if "high health" in m or "max health" in m or "tanks" in m:
                        counter_weights["survivability_vs_damage"] = round(
                            counter_weights.get("survivability_vs_damage", 0.0) + 0.3, 2
                        )
                    elif "heavy armor" in m or "armor shred" in m:
                        counter_weights["armor"] = round(counter_weights.get("armor", 0.0) + 0.3, 2)
                        counter_weights["survivability_vs_armor"] = round(
                            counter_weights.get("survivability_vs_armor", 0.0) + 0.3, 2
                        )
                    elif "heavy mr" in m or "magic shred" in m:
                        counter_weights["magic_resistance"] = round(
                            counter_weights.get("magic_resistance", 0.0) + 0.3, 2
                        )
                    elif "shields" in m:
                        counter_weights["survivability_vs_damage"] = round(
                            counter_weights.get("survivability_vs_damage", 0.0) + 0.2, 2
                        )
                    elif "crowd control" in m or "cc" in m:
                        counter_weights["survivability_overall"] = round(
                            counter_weights.get("survivability_overall", 0.0) + 0.2, 2
                        )

        return counter_weights

    # ------------------------------------------------------------------
    # Actualización y reconstrucción completa desde Data Dragon
    # ------------------------------------------------------------------

    def update_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Recalcula y actualiza synergy_multipliers y counter_weights para un objeto individual."""
        if not isinstance(item, dict):
            return item

        stats = item.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}

        functionality = item.get("functionality", {})
        if not isinstance(functionality, dict):
            functionality = {}

        classifications = item.get("classifications", {})
        if not isinstance(classifications, dict):
            classifications = {}

        passive_names = functionality.get("passive_names", [])
        if not isinstance(passive_names, list):
            passive_names = []

        synergies = self.calculate_base_multipliers(stats)
        counter_weights = self.calculate_counter_weights(stats, functionality, classifications)
        self.apply_passive_bonuses(passive_names, stats, synergies, counter_weights)

        item["synergy_multipliers"] = synergies
        item["counter_weights"] = counter_weights

        return item

    def update_all_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Recalcula y actualiza todos los objetos de una lista."""
        if not isinstance(items, list):
            return []

        for item in items:
            self.update_item(item)

        return items

    def update_items_file(self, file_path: Path | str | None = None) -> tuple[int, list[dict[str, Any]]]:
        """Carga el archivo JSON de objetos legendarios, recalcula sinergias y contrapesos y lo guarda."""
        target_path = Path(file_path) if file_path else self.DEFAULT_ITEMS_PATH
        if not target_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo de objetos: {target_path}")

        items = json.loads(target_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError(f"El archivo {target_path} no contiene una lista de objetos.")

        updated_items = self.update_all_items(items)

        tmp_path = target_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(updated_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(target_path)

        return len(updated_items), updated_items

    def rebuild_all_items_from_datadragon(
        self,
        version: str | None = None,
        file_path: Path | str | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """
        Reconstruye completamente todo el catálogo de objetos legendarios desde Data Dragon API.
        
        Actualiza:
          - Coste en oro oficial (gold_cost)
          - Estadísticas oficiales completas (stats)
          - Pasivas oficiales (passive_names)
          - Sinergias matemáticas (synergy_multipliers)
          - Contrapesos (counter_weights)
        """
        try:
            ver = version or get_latest_version()
        except Exception:
            ver = "16.17.1"

        catalog = download_items(ver)

        rebuilt_items: list[dict[str, Any]] = []
        seen_names = set()

        # Priorizar objetos del mapa 11 (Summoner's Rift) y con IDs estándar
        sorted_keys = sorted(
            catalog.keys(),
            key=lambda k: (
                0 if catalog[k].get("maps", {}).get("11") is True else 1,
                len(k),
                k,
            ),
        )

        for item_id in sorted_keys:
            item_data = catalog[item_id]
            entry = self.parse_datadragon_item(str(item_id), item_data)
            if entry:
                item_name = entry.get("item", "")
                if item_name not in seen_names:
                    seen_names.add(item_name)
                    # Calcular sinergias y contrapesos matemáticamente
                    self.update_item(entry)
                    rebuilt_items.append(entry)

        # Ordenar alfabéticamente por nombre en español
        rebuilt_items.sort(key=lambda x: str(x.get("item", "")))

        target_path = Path(file_path) if file_path else self.DEFAULT_ITEMS_PATH
        tmp_path = target_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(rebuilt_items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(target_path)

        return len(rebuilt_items), rebuilt_items

    def parse_datadragon_item(self, item_id: str, item_data: dict[str, Any]) -> dict[str, Any] | None:
        """Parsea y estructura un objeto completo desde los datos brutos de Data Dragon."""
        if not isinstance(item_data, dict):
            return None

        gold = item_data.get("gold", {})
        total_gold = int(gold.get("total", 0)) if isinstance(gold, dict) else 0

        name_es = str(item_data.get("name_es", item_data.get("name", item_id))).strip()
        name_en = str(item_data.get("name_en", name_es)).strip()

        # Filtrar objetos no completados, consumibles o placeholders
        if (
            total_gold < 2200
            or item_data.get("into")
            or name_es.startswith("Objeto de ")
            or "Quick Charge" in name_en
            or "Consumir" in name_es
        ):
            return None

        # --- Filtro de ranked Summoner's Rift ---

        # 1. Excluir IDs de 6+ dígitos: son variantes de Arena/modos especiales
        if len(item_id) >= 6:
            return None

        # 2. Debe estar habilitado en el mapa 11 (Summoner's Rift)
        maps = item_data.get("maps", {})
        if isinstance(maps, dict) and maps.get("11") is not True:
            return None

        # 3. Debe ser comprable o un objeto de transformación legítimo
        #    (specialRecipe indica que se transforma de otro objeto, ej. Seraph's de Archangel's)
        purchasable = gold.get("purchasable", True) if isinstance(gold, dict) else True
        if purchasable is False:
            has_special_recipe = bool(item_data.get("specialRecipe"))
            if not has_special_recipe:
                return None

        desc_es = str(item_data.get("description_es", item_data.get("description", "")))
        desc_en = str(item_data.get("description_en", desc_es))
        combined_desc = f"{desc_es} {desc_en}"

        # 1. Estadísticas oficiales
        stats = self._extract_stats(item_data, desc_es, desc_en)

        # 2. Pasivas y activas oficiales
        passives = self._extract_passives(desc_es, desc_en)

        # 3. Clasificaciones
        classes = self._infer_classes(stats, item_data.get("tags", []))
        mechanics = self._infer_counter_mechanics(stats, passives, combined_desc)
        group = self._infer_group(name_es, name_en, combined_desc)

        return {
            "id": str(item_id),
            "item": name_es,
            "name_en": name_en,
            "basic_info": {
                "id": str(item_id),
                "name": name_es,
                "name_en": name_en,
                "tier": "Legendary",
                "gold_cost": total_gold,
                "item_group": group,
            },
            "stats": stats,
            "functionality": {
                "has_passive": bool(passives or "<passive>" in combined_desc.lower()),
                "has_active": "<active>" in combined_desc.lower() or "activa" in combined_desc.lower(),
                "passive_names": passives,
            },
            "classifications": {
                "intended_classes": classes,
                "counter_mechanics": mechanics,
            },
            "analysis": {
                "game_phase_power": "Linear",
                "about": f"Objeto legendario con valor de {total_gold} de oro. Aporta estadísticas clave para {', '.join(classes[:2])}.",
            },
            "synergy_multipliers": {},
            "counter_weights": {},
        }

    @staticmethod
    def _extract_stats(item_data: dict[str, Any], desc_es: str, desc_en: str) -> dict[str, int | float]:
        """Extrae todas las estadísticas activas del objeto combinando el payload numérico y el bloque <stats> del HTML."""
        stats_raw = item_data.get("stats", {})
        stats: dict[str, int | float] = {}

        if "FlatPhysicalDamageMod" in stats_raw:
            stats["attack_damage"] = int(stats_raw["FlatPhysicalDamageMod"])
        if "FlatMagicDamageMod" in stats_raw:
            stats["ability_power"] = int(stats_raw["FlatMagicDamageMod"])
        if "FlatHPPoolMod" in stats_raw:
            stats["health"] = int(stats_raw["FlatHPPoolMod"])
        if "FlatMPPoolMod" in stats_raw:
            stats["mana"] = int(stats_raw["FlatMPPoolMod"])
        if "FlatArmorMod" in stats_raw:
            stats["armor"] = int(stats_raw["FlatArmorMod"])
        if "FlatSpellBlockMod" in stats_raw:
            stats["magic_resistance"] = int(stats_raw["FlatSpellBlockMod"])
        if "PercentCritChanceMod" in stats_raw:
            stats["critical_strike_chance_percent"] = int(round(stats_raw["PercentCritChanceMod"] * 100))
        if "PercentAttackSpeedMod" in stats_raw:
            stats["attack_speed_percent"] = int(round(stats_raw["PercentAttackSpeedMod"] * 100))
        if "PercentLifeStealMod" in stats_raw:
            stats["life_steal_percent"] = int(round(stats_raw["PercentLifeStealMod"] * 100))
        if "FlatMovementSpeedMod" in stats_raw:
            stats["movement_speed_flat"] = int(stats_raw["FlatMovementSpeedMod"])
        if "PercentMovementSpeedMod" in stats_raw:
            stats["movement_speed_percent"] = int(round(stats_raw["PercentMovementSpeedMod"] * 100))

        # Extracción específica del bloque <stats>...</stats> para no capturar números de descripciones de pasivas
        stats_blocks = []
        for d in (desc_es, desc_en):
            m = re.search(r"<stats>(.*?)</stats>", d, re.DOTALL | re.IGNORECASE)
            if m:
                clean_text = re.sub(r"<[^>]+>", " ", m.group(1))
                stats_blocks.append(clean_text)

        combined_stats_text = " ".join(stats_blocks)

        patterns = {
            "attack_damage": r"(\d+)\s*(?:Attack Damage|de da[ñn]o de ataque)",
            "ability_power": r"(\d+)\s*(?:Ability Power|de poder de habilidad)",
            "health": r"(\d+)\s*(?:Health|de vida)",
            "armor": r"(\d+)\s*(?:Armor|de armadura)",
            "magic_resistance": r"(\d+)\s*(?:Magic Resist(?:ance)?|resistencia m[áa]gica)",
            "ability_haste": r"(\d+)\s*(?:Ability Haste|velocidad de habilidades|aceleraci[óo]n de habilidad)",
            "lethality": r"(\d+)\s*(?:Lethality|letalidad)",
            "armor_penetration_percent": r"(\d+)%\s*(?:Armor Penetration|penetraci[óo]n de armadura)",
            "magic_penetration_percent": r"(\d+)%\s*(?:Magic Penetration|penetraci[óo]n m[áa]gica)",
            "magic_penetration_flat": r"(\d+)\s*(?:Magic Penetration|penetraci[óo]n m[áa]gica)",
            "critical_strike_chance_percent": r"(\d+)%\s*(?:Critical Strike Chance|probabilidad de impacto cr[íi]tico)",
            "attack_speed_percent": r"(\d+)%\s*(?:Attack Speed|velocidad de ataque)",
            "life_steal_percent": r"(\d+)%\s*(?:Life Steal|robo de vida)",
            "omnivamp_percent": r"(\d+)%\s*(?:Omnivamp|omnivampirismo)",
            "heal_and_shield_power_percent": r"(\d+)%\s*(?:Heal and Shield Power|curaci[óo]n y escudos)",
            "movement_speed_percent": r"(\d+)%\s*(?:Movement Speed|velocidad de movimiento)",
            "base_health_regeneration_percent": r"(\d+)%\s*(?:Base Health Regen|regeneraci[óo]n de vida b[áa]sica)",
            "base_mana_regeneration_percent": r"(\d+)%\s*(?:Base Mana Regen|regeneraci[óo]n de man[áa] b[áa]sica)",
            "tenacity": r"(\d+)%\s*(?:Tenacity|tenacidad)",
        }

        for stat_key, pat in patterns.items():
            if stat_key not in stats or stats[stat_key] == 0:
                m = re.search(pat, combined_stats_text, re.IGNORECASE)
                if m:
                    stats[stat_key] = int(m.group(1))

        return stats

    @staticmethod
    def _extract_passives(desc_es: str, desc_en: str) -> list[str]:
        """Extrae los nombres de pasivas y activas en español e inglés."""
        passives = set()
        for text in (desc_es, desc_en):
            found = re.findall(r"<(?:passive|active|unique)>([^:<]+):?<\/", text, re.I)
            for p in found:
                clean_p = p.strip()
                if clean_p and len(clean_p) > 1 and not clean_p.lower().startswith("activa - consumir"):
                    passives.add(clean_p)
        return sorted(list(passives))

    @staticmethod
    def _infer_classes(stats: dict[str, Any], tags: list[str]) -> list[str]:
        """Determina los arquetipos de campeón previstos para el objeto."""
        classes = []
        if stats.get("attack_damage", 0) > 0 or stats.get("lethality", 0) > 0:
            if stats.get("lethality", 0) > 0:
                classes.append("Assassin")
            if stats.get("critical_strike_chance_percent", 0) > 0 or stats.get("attack_speed_percent", 0) > 0:
                classes.append("Marksman")
            classes.append("Fighter")
        if stats.get("ability_power", 0) > 0:
            classes.append("Mage")
            if stats.get("heal_and_shield_power_percent", 0) > 0 or stats.get("base_mana_regeneration_percent", 0) > 0:
                classes.append("Support")
        if stats.get("armor", 0) > 0 or stats.get("magic_resistance", 0) > 0 or stats.get("health", 0) >= 350:
            classes.append("Tank")
        if not classes:
            classes = ["Fighter"]
        return list(dict.fromkeys(classes))

    @staticmethod
    def _infer_counter_mechanics(stats: dict[str, Any], passives: list[str], text: str) -> list[str]:
        """Infiere las mecánicas counter que proporciona el objeto."""
        mechanics = []
        if (
            stats.get("armor_penetration_percent", 0) > 0
            or stats.get("lethality", 0) > 0
            or any("carve" in p.lower() or "shred" in p.lower() for p in passives)
        ):
            mechanics.append("Heavy_Armor")
        if (
            stats.get("magic_penetration_percent", 0) > 0
            or stats.get("magic_penetration_flat", 0) > 0
            or any("dissolve" in p.lower() or "void" in p.lower() for p in passives)
        ):
            mechanics.append("Heavy_MR")
        if any(
            k in text.lower()
            for k in ["giant slayer", "verdugo de gigantes", "percent health", "máxima vida", "max health", "cut down"]
        ):
            mechanics.append("High_Health")
        if any(k in text.lower() for k in ["shield", "escudo", "salvavidas", "lifeline"]):
            mechanics.append("Shields")
        if any(k in text.lower() for k in ["quicksilver", "purify", "cleanse", "fajín"]):
            mechanics.append("Crowd_Control")
        return mechanics or ["None"]

    @staticmethod
    def _infer_group(name_es: str, name_en: str, text: str) -> str:
        """Identifica el grupo de exclusión o categoría del objeto."""
        n = f"{name_es} {name_en} {text}".lower()
        if "boot" in n or "bota" in n:
            return "Boots"
        if "hydra" in n or "hidra" in n:
            return "Hydra"
        if "lifeline" in n or "salvavidas" in n:
            return "Lifeline"
        if "lethality" in n or "letalidad" in n or "fatality" in n:
            return "Fatality"
        if "void" in n or "vacío" in n or "blight" in n:
            return "Blight"
        if "annul" in n or "velo" in n or "banshee" in n:
            return "Annul"
        if "support" in n or "soporte" in n:
            return "Support"
        return "None"


if __name__ == "__main__":
    calculator = ItemSynergyCalculatorService()
    count, items = calculator.rebuild_all_items_from_datadragon()
    print(f"Reconstrucción completa: {count} objetos legendarios procesados y guardados con éxito.")
