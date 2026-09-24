from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.services.playstyle_service import (
    item_emphasis,
    primary_attributes,
    resolve_playstyle,
    stat_label,
)


@dataclass(frozen=True)
class ItemRecommendation:
    item_id: str
    name: str
    score: float
    reasons: tuple[str, ...]
    counter_reasons: tuple[str, ...]


class SynergyRecommendationService:
    """Puntua objetos usando identidad del campeon, estadisticas y amenazas LIVE.

    La afinidad se pondera con el playstyle modular de ``playstyle_service``:
    buffs (+) para las estadísticas del rol, nerfs (−) para escalados
    residuales no viables y penalizaciones por clase incompatible, todo ello
    gateado por los escalados realmente principales del campeón.
    """

    # Puntos que resta cada unidad de énfasis × nerf de playstyle.
    PENALTY_PER_NERF = 6.0
    # Penalización plana cuando la clase del objeto es incompatible con el rol.
    CLASS_PENALTY = 6.0

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
        # 1. Core items set (+10)
        core_raw = []
        if isinstance(champion_profile.get("items"), list):
            core_raw.extend(champion_profile.get("items", []))
        scaling = champion_profile.get("power_curve_and_scaling", {})
        if isinstance(scaling, dict) and isinstance(scaling.get("power_spike_items"), list):
            core_raw.extend(scaling.get("power_spike_items", []))
        core_item_names = {self._normalise_item_name(n) for n in core_raw if n}

        # 2. Build items set (+10)
        build_raw = []
        if isinstance(champion_profile.get("most_played_build"), list):
            build_raw.extend(champion_profile.get("most_played_build", []))
        if isinstance(champion_profile.get("full_build"), list):
            build_raw.extend(champion_profile.get("full_build", []))
        build_item_names = {self._normalise_item_name(n) for n in build_raw if n}

        # 3. Situational items set (+5)
        situational_raw = []
        sit_dict = champion_profile.get("situational_items", {})
        if isinstance(sit_dict, dict):
            for cat_list in sit_dict.values():
                if isinstance(cat_list, list):
                    situational_raw.extend(cat_list)
        situational_item_names = {self._normalise_item_name(n) for n in situational_raw if n}

        recommendations = [
            self._apply_synergy_bonuses(
                self.score_item(champion_profile, style_key, item_id, item, threats),
                core_item_names,
                build_item_names,
                situational_item_names,
            )
            for item_id, item in items.items()
            if self._is_legendary(item)
        ]
        # Deduplicar por nombre normalizado: el mismo objeto puede llegar con IDs
        # distintos (strict vs Data Dragon). Se conserva la mejor puntuación.
        unique: dict[str, ItemRecommendation] = {}
        for rec in recommendations:
            key = self._normalise_item_name(rec.name)
            existing = unique.get(key)
            if existing is None or rec.score > existing.score:
                unique[key] = rec
        recommendations = list(unique.values())
        return sorted(recommendations, key=lambda value: value.score, reverse=True)[:limit]

    @staticmethod
    def _apply_synergy_bonuses(
        recommendation: ItemRecommendation,
        core_item_names: set[str],
        build_item_names: set[str],
        situational_item_names: set[str],
    ) -> ItemRecommendation:
        norm_name = SynergyRecommendationService._normalise_item_name(recommendation.name)
        bonus = 0.0
        extra_reasons: list[str] = []

        is_core = norm_name in core_item_names
        is_build = norm_name in build_item_names
        is_sit = norm_name in situational_item_names

        if is_core:
            bonus += 10.0
            extra_reasons.append("Sinergia Core Item (+10)")
        if is_build:
            bonus += 10.0
            extra_reasons.append("Sinergia en Build (+10)")
        if is_sit:
            bonus += 5.0
            extra_reasons.append("Sinergia Situacional (+5)")

        if bonus == 0.0:
            return recommendation

        all_reasons = tuple(extra_reasons + list(recommendation.reasons))
        return ItemRecommendation(
            item_id=recommendation.item_id,
            name=recommendation.name,
            score=round(recommendation.score + bonus, 1),
            reasons=all_reasons[:3],
            counter_reasons=recommendation.counter_reasons,
        )

    @classmethod
    def _normalise_item_name(cls, name: Any) -> str:
        value = str(name).casefold().strip()
        clean = re.sub(r"[^\w\s]", "", value)
        return cls.ITEM_NAME_ALIASES.get(value, cls.ITEM_NAME_ALIASES.get(clean, clean))

    def score_item(
        self,
        champion_profile: dict[str, Any],
        style_key: str,
        item_id: str,
        item: dict[str, Any],
        threats: list[tuple[str, str]],
    ) -> ItemRecommendation:
        """Fórmula ponderada por playstyle y escalados reales del campeón.

        score = base(8/2 por clase afín)
              + Σ (atributo × énfasis × (1 + buff − nerf))   ← afinidad
              − Σ (énfasis × nerf × PENALTY_PER_NERF)        ← stats incompatibles
              − CLASS_PENALTY                                ← clase incompatible
              + 3 por cada amenaza que responde el objeto
        y se trunca a 0 como suelo (los objetos incompatibles no pueden quedar
        con puntuación positiva solo por escalados residuales).
        """
        attributes = self._champion_attributes(champion_profile)
        stats = item.get("stats", {}) if isinstance(item.get("stats"), dict) else {}
        text = self._text(item)
        classifications = item.get("classifications", {}) if isinstance(item.get("classifications"), dict) else {}
        intended = {str(value) for value in item.get("intended_classes", classifications.get("intended_classes", []))}
        intended.update(self._class_hints(text))

        playstyle = resolve_playstyle(style_key)
        primary = primary_attributes(attributes)
        emphasis = item_emphasis(stats, self._multipliers(item))
        nerfs = playstyle.effective_nerfs(primary)

        # Base: clases afines al rol (fallback a STYLE_KEYS legacy si no hay playstyle).
        wanted = playstyle.favored_classes or self.STYLE_CLASSES.get(style_key, set())
        score = 8.0 if intended & wanted else 2.0
        reasons: list[str] = []
        penalties: list[str] = []
        counters: list[str] = []
        if intended & wanted:
            reasons.append(f"encaja con el estilo {style_key}")

        # 1) Nerfs de playstyle: el objeto invierte en estadísticas incompatibles.
        for stat, nerf in sorted(nerfs.items(), key=lambda pair: -pair[1]):
            factor = emphasis.get(stat, 0.0)
            if factor:
                score -= factor * nerf * self.PENALTY_PER_NERF
                penalties.append(f"{stat_label(stat)} incompatible con {playstyle.label}")

        # 2) Clases incompatibles con el rol (exentas si el escalado que las
        #    sustenta es principal en el campeón, p. ej. AP en Mordekaiser).
        disfavored = playstyle.effective_disfavored(intended, primary)
        if disfavored:
            score -= self.CLASS_PENALTY
            penalties.append(f"clase {'/'.join(sorted(disfavored))} fuera del rol {playstyle.label}")

        # 3) Afinidad ponderada: atributo × énfasis × coeficiente de playstyle.
        contributions: list[tuple[str, float]] = []
        for stat, factor in emphasis.items():
            value = float(attributes.get(stat, 0))
            if not value or not factor:
                continue
            coefficient = 1.0 + playstyle.buff_for(stat, primary) - nerfs.get(stat, 0.0)
            if coefficient:
                contributions.append((stat, value * factor * coefficient))
        contributions.sort(key=lambda pair: -abs(pair[1]))
        for stat, contribution in contributions:
            score += contribution
            if contribution > 0:
                reasons.append(f"sinergia con {stat_label(stat)}")

        # 4) Respuestas a amenazas del equipo rival.
        for threat_key, label in threats:
            if self._counters(threat_key, text):
                score += 3.0
                counters.append(label)

        all_reasons = penalties + reasons
        if not all_reasons:
            all_reasons.append("aporta estadisticas utiles al estilo del campeon")
        return ItemRecommendation(
            item_id=str(item_id),
            name=self._name(item, item_id),
            score=round(max(0.0, score), 1),
            reasons=tuple(all_reasons[:3]),
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
        # Escalados defensivos clave en objetos de tanque pero ausentes como
        # atributo propio del perfil: se derivan de survivability_overall.
        overall = attributes.get("survivability_overall", 0.0)
        attributes.setdefault("durability", overall)
        attributes.setdefault("tankiness", overall)
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
