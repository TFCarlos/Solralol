from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ItemRecommendation:
    item_id: str
    name: str
    score: float
    reasons: tuple[str, ...]
    counter_reasons: tuple[str, ...]


class SynergyRecommendationService:
    """Puntua objetos usando identidad del campeon, estadisticas y amenazas LIVE."""

    STYLE_CLASSES = {
        "Diver": {"Bruiser", "Fighter", "Skirmisher", "Juggernaut"},
        "bruiser_ad": {"Bruiser", "Fighter", "Juggernaut"},
        "bruiser_ap": {"Bruiser", "Fighter", "Mage"},
        "tank": {"Tank", "Juggernaut", "Vanguard", "Warden"},
        "on_hit": {"Bruiser", "Fighter", "Marksman", "Skirmisher"},
        "crit_ad": {"Marksman", "Fighter", "Skirmisher"},
        "poke_ad": {"Marksman", "Assassin"},
        "poke_ap": {"Mage", "Assassin"},
        "burst_ap": {"Mage", "Assassin"},
        "assassin_ap": {"Assassin", "Mage"},
        "assassin_lethality": {"Assassin", "Marksman"},
        "split_push": {"Fighter", "Juggernaut", "Skirmisher"},
        "utility": {"Enchanter", "Warden", "Vanguard"},
    }
    ITEM_NAME_ALIASES = {
        "abyssal mask": "máscara abisal",
        "ardent censer": "incensario ardiente",
        "black cleaver": "cuchilla negra",
        "blade of the ruined king": "hoja del rey arruinado",
        "botrk": "hoja del rey arruinado",
        "death's dance": "baile de la muerte",
        "danza de la muerte": "baile de la muerte",
        "duskblade": "filoscuro de draktharr",
        "duskblade of draktharr": "filoscuro de draktharr",
        "eclipse": "eclipse",
        "essence reaver": "segador de esencia",
        "everfrost": "escarcha eterna",
        "glaciar eterno": "escarcha eterna",
        "frostfire gauntlet": "guantelete de hielo",
        "galeforce": "viento huracanado",
        "fuerza del viento": "viento huracanado",
        "guinsoo's rageblade": "hoja de furia de guinsoo",
        "rageblade": "hoja de furia de guinsoo",
        "heartsteel": "corazón de acero",
        "hextech rocketbelt": "cintomisil hextech",
        "iceborn gauntlet": "guantelete de hielo",
        "immortal shieldbow": "arcoescudo inmortal",
        "infinity edge": "filo infinito",
        "knight's vow": "promesa de caballero",
        "kraken slayer": "verdugo de krakens",
        "liandry's torment": "tormento de liandry",
        "locket of the iron solari": "medallón de los solari de hierro",
        "luden's companion": "eco de luden",
        "luden's tempest": "eco de luden",
        "luden's echo": "eco de luden",
        "manamune": "manamune",
        "moonstone renewer": "renovación de piedra lunar",
        "nashor's tooth": "diente de nashor",
        "navori quickblades": "filofugaz de navori",
        "navori flickerblade": "filofugaz de navori",
        "rabadon's deathcap": "sombrero mortal de rabadon",
        "rapid firecannon": "cañón de fuego rápido",
        "redemption": "redención",
        "riftmaker": "creagrietas",
        "runaan's hurricane": "huracán de runaan",
        "rylai's crystal scepter": "cetro de cristal de rylai",
        "rylai": "cetro de cristal de rylai",
        "shadowflame": "llamasombría",
        "shurelya's battlesong": "canción de batalla de shurelya",
        "statikk shiv": "puñal de statikk",
        "sterak's gage": "calibrador de sterak",
        "sterak": "calibrador de sterak",
        "stormrazor": "navaja de asalto",
        "stridebreaker": "cortasendas",
        "rompeavances": "cortasendas",
        "sundered sky": "firmamento desgarrado",
        "sunfire aegis": "égida de fuego solar",
        "thornmail": "malla de espinas",
        "titanic hydra": "hidra titánica",
        "trinity force": "fuerza de trinidad",
        "umbral glaive": "guja sombría",
        "youmuu's ghostblade": "filo fantasmal de youmuu",
        "zeke's convergence": "convergencia de zeke",
        "zhonya's hourglass": "reloj de arena de zhonya",
    }

    def rank_items(
        self,
        champion_profile: dict[str, Any],
        style_key: str,
        items: dict[str, dict[str, Any]],
        threats: list[tuple[str, str]],
        limit: int = 10,
    ) -> list[ItemRecommendation]:
        champion = self._champion_attributes(champion_profile)
        scaling = champion_profile.get("power_curve_and_scaling", {})
        power_spike_names = {
            self._normalise_item_name(value)
            for value in scaling.get("power_spike_items", [])
        } if isinstance(scaling, dict) else set()
        recommendations = [
            self._add_power_spike_bonus(
                self.score_item(champion_profile, style_key, item_id, item, threats),
                power_spike_names,
            )
            for item_id, item in items.items()
            if self._is_legendary(item)
        ]
        return sorted(recommendations, key=lambda value: value.score, reverse=True)[:limit]

    @staticmethod
    def _add_power_spike_bonus(
        recommendation: ItemRecommendation,
        power_spike_names: set[str],
    ) -> ItemRecommendation:
        if SynergyRecommendationService._normalise_item_name(recommendation.name) not in power_spike_names:
            return recommendation
        return ItemRecommendation(
            item_id=recommendation.item_id,
            name=recommendation.name,
            score=round(recommendation.score + 3.0, 1),
            reasons=("power spike del campeón", *recommendation.reasons[:2]),
            counter_reasons=recommendation.counter_reasons,
        )

    @classmethod
    def _normalise_item_name(cls, name: Any) -> str:
        value = str(name).casefold().strip()
        return cls.ITEM_NAME_ALIASES.get(value, value)

    def score_item(
        self,
        champion_profile: dict[str, Any],
        style_key: str,
        item_id: str,
        item: dict[str, Any],
        threats: list[tuple[str, str]],
    ) -> ItemRecommendation:
        attributes = self._champion_attributes(champion_profile)
        stats = item.get("stats", {}) if isinstance(item.get("stats"), dict) else {}
        text = self._text(item)
        classifications = item.get("classifications", {}) if isinstance(item.get("classifications"), dict) else {}
        intended = {str(value) for value in item.get("intended_classes", classifications.get("intended_classes", []))}
        intended.update(self._class_hints(text))
        wanted = self.STYLE_CLASSES.get(style_key, set())
        base = 8.0 if intended & wanted else 2.0
        reasons: list[str] = []
        counters: list[str] = []
        if intended & wanted:
            reasons.append(f"encaja con el estilo {style_key}")
        for stat, multiplier in self._multipliers(item).items():
            value = float(attributes.get(stat, 0))
            if value and multiplier:
                base += value * multiplier
                reasons.append(f"sinergia con {stat.replace('_', ' ')}")
        for threat_key, label in threats:
            if self._counters(threat_key, text):
                base += 3.0
                counters.append(label)
        if not reasons:
            reasons.append("aporta estadisticas utiles al estilo del campeon")
        return ItemRecommendation(
            item_id=str(item_id),
            name=self._name(item, item_id),
            score=round(base, 1),
            reasons=tuple(reasons[:3]),
            counter_reasons=tuple(counters[:2]),
        )

    @staticmethod
    def _is_legendary(item: dict[str, Any]) -> bool:
        basic = item.get("basic_info", {}) if isinstance(item.get("basic_info"), dict) else {}
        tier = str(item.get("tier", basic.get("tier", "")))
        if tier:
            return tier == "Legendary"
        gold = item.get("gold", {})
        return bool(isinstance(gold, dict) and gold.get("purchasable") and gold.get("total", 0) >= 2500 and not item.get("into"))

    @staticmethod
    def _champion_attributes(profile: dict[str, Any]) -> dict[str, float]:
        attributes: dict[str, float] = {}
        for section in ("combat_attributes", "resistances_and_survivability", "map_and_control", "power_curve_and_scaling"):
            values = profile.get(section, {})
            if isinstance(values, dict):
                for key, value in values.items():
                    try:
                        attributes[key] = float(value)
                    except (TypeError, ValueError):
                        continue
        return attributes

    @staticmethod
    def _multipliers(item: dict[str, Any]) -> dict[str, float]:
        values = item.get("synergy_multipliers", {})
        if not values and isinstance(item.get("synergy_multipliers"), dict):
            values = item["synergy_multipliers"]
        if isinstance(values, dict):
            result = {}
            for key, value in values.items():
                try:
                    result[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
            if result:
                return result
        stats = item.get("stats", {}) if isinstance(item.get("stats"), dict) else item
        return {key: 0.15 for key in stats if key in {"attack_damage", "ability_power", "critic", "lethality", "mobility", "wave_clear", "hypercarry"}}

    @staticmethod
    def _counters(threat: str, text: str) -> bool:
        terms = {
            "curacion": ("healing", "grievous", "heridas", "life steal"),
            "armadura": ("armor penetration", "penetración de armadura", "lethality"),
            "resistencia_magica": ("magic penetration", "penetración mágica"),
            "critico": ("armor", "armadura"),
            "vida": ("current health", "vida actual", "max health"),
        }
        return any(term in text for term in terms.get(threat, ()))

    @staticmethod
    def _class_hints(text: str) -> set[str]:
        classes = set()
        if any(term in text for term in ("attack damage", "daño de ataque", "critical")):
            classes.update(("Fighter", "Marksman"))
        if any(term in text for term in ("ability power", "poder de habilidad", "magic penetration")):
            classes.add("Mage")
        if any(term in text for term in ("health", "vida", "armor", "armadura")):
            classes.update(("Tank", "Juggernaut"))
        return classes

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        basic = item.get("basic_info", {}) if isinstance(item.get("basic_info"), dict) else {}
        analysis = item.get("analysis", {}) if isinstance(item.get("analysis"), dict) else {}
        return re.sub(r"<[^>]+>", " ", " ".join(str(item.get(key, basic.get(key, analysis.get(key, "")))) for key in ("name", "description", "plaintext", "tags", "item"))).casefold()

    @staticmethod
    def _name(item: dict[str, Any], fallback: str) -> str:
        basic = item.get("basic_info", {}) if isinstance(item.get("basic_info"), dict) else {}
        return str(item.get("name", basic.get("name", item.get("item", fallback))))
