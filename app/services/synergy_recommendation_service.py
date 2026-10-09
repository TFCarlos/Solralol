from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, ClassVar

from app.services.elegibilidad_objetos import MODO_SOLOQ, ValidadorElegibilidadObjetos
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
    compatibility_label: str = "Situacional"
    compatibility_reasons: tuple[str, ...] = ()
    compatibility_score: float = 0.0
    matchup_score: float = 0.0
    build_synergy_score: float = 0.0


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
    _compatibility_cache: ClassVar[
        dict[tuple[str, ...], tuple[float, str, tuple[str, ...]]]
    ] = {}

    STYLE_CLASSES: ClassVar[dict[str, set[str]]] = {
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
    ITEM_NAME_ALIASES: ClassVar[dict[str, str]] = {
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
        game_mode: str = MODO_SOLOQ,
        catalog_patch: str = "",
    ) -> list[ItemRecommendation]:
        """Devuelve los candidatos mejor puntuados hasta el límite solicitado."""
        return self.rank_candidates(
            champion_profile,
            style_key,
            items,
            threats,
            game_mode=game_mode,
            catalog_patch=catalog_patch,
        )[: max(0, limit)]

    def rank_candidates(
        self,
        champion_profile: dict[str, Any],
        style_key: str,
        items: dict[str, dict[str, Any]],
        threats: list[tuple[str, str]],
        game_mode: str = MODO_SOLOQ,
        catalog_patch: str = "",
    ) -> list[ItemRecommendation]:
        """Puntúa y devuelve todos los objetos legendarios elegibles para afinidad y sinergia."""
        # 1. Core items set (+10)
        core_raw = []
        if isinstance(champion_profile.get("items"), list):
            core_raw.extend(champion_profile.get("items", []))
        scaling = champion_profile.get("power_curve_and_scaling", {})
        if isinstance(scaling, dict) and isinstance(
            scaling.get("power_spike_items"), list
        ):
            core_raw.extend(scaling.get("power_spike_items", []))
        core_item_names = {self._normalise_item_name(n) for n in core_raw if n}

        # 2. Build items set (+10)
        build_raw = []
        if isinstance(champion_profile.get("most_played_build"), list):
            build_raw.extend(champion_profile.get("most_played_build", []))
        if isinstance(champion_profile.get("full_build"), list):
            build_raw.extend(champion_profile.get("full_build", []))
        build_item_names = {self._normalise_item_name(n) for n in build_raw if n}

        campeon = str(champion_profile.get("character") or "")
        elegibles: dict[str, dict[str, Any]] = {}
        rechazados: dict[str, str] = {}
        for item_id, item in items.items():
            resultado = ValidadorElegibilidadObjetos.validar(
                str(item_id), item, campeon or None, game_mode, catalog_patch
            )
            if resultado.elegible:
                elegibles[str(item_id)] = item
            else:
                rechazados[str(item_id)] = resultado.motivo
        self.last_item_eligibility_diagnostics = {
            "mode": game_mode,
            "catalog_patch": catalog_patch,
            "input_entries": len(items),
            "eligible_entries": len(elegibles),
            "rejected_entries": rechazados,
        }
        perfil_puntuacion = {
            **champion_profile,
            "recommendation_catalog_patch": catalog_patch,
            "recommendation_mode": game_mode,
        }
        recommendations = [
            self._apply_synergy_bonuses(
                self.score_item(perfil_puntuacion, style_key, item_id, item, threats),
                core_item_names,
                build_item_names,
            )
            for item_id, item in elegibles.items()
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
        return sorted(recommendations, key=lambda value: value.score, reverse=True)

    @staticmethod
    def _apply_synergy_bonuses(
        recommendation: ItemRecommendation,
        core_item_names: set[str],
        build_item_names: set[str],
    ) -> ItemRecommendation:
        norm_name = SynergyRecommendationService._normalise_item_name(
            recommendation.name
        )
        bonus = 0.0
        extra_reasons: list[str] = []

        is_core = norm_name in core_item_names
        is_build = norm_name in build_item_names
        if is_core or is_build:
            bonus = 6.0
            extra_reasons.append("Presente en una build observada (+6)")

        if bonus == 0.0:
            return recommendation

        all_reasons = tuple(extra_reasons + list(recommendation.reasons))
        return ItemRecommendation(
            item_id=recommendation.item_id,
            name=recommendation.name,
            score=round(recommendation.score + bonus, 1),
            reasons=all_reasons[:3],
            counter_reasons=recommendation.counter_reasons,
            compatibility_label=recommendation.compatibility_label,
            compatibility_reasons=recommendation.compatibility_reasons,
            compatibility_score=recommendation.compatibility_score,
            matchup_score=recommendation.matchup_score,
            build_synergy_score=round(bonus, 1),
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
        classifications = (
            item.get("classifications", {})
            if isinstance(item.get("classifications"), dict)
            else {}
        )
        intended = {
            str(value)
            for value in item.get(
                "intended_classes", classifications.get("intended_classes", [])
            )
        }
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
                penalties.append(
                    f"{stat_label(stat)} incompatible con {playstyle.label}"
                )

        # 2) Clases incompatibles con el rol (exentas si el escalado que las
        #    sustenta es principal en el campeón, p. ej. AP en Mordekaiser).
        disfavored = playstyle.effective_disfavored(intended, primary)
        if disfavored:
            score -= self.CLASS_PENALTY
            penalties.append(
                f"clase {'/'.join(sorted(disfavored))} fuera del rol {playstyle.label}"
            )

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

        compatibilidad, etiqueta, motivos = self._compatibilidad_mecanica(
            champion_profile, style_key, item_id, item
        )
        score += compatibilidad
        (penalties if compatibilidad < 0 else reasons).extend(motivos[:2])

        # 4) Respuestas a amenazas del equipo rival.
        matchup_score = 0.0
        for threat_key, label in threats:
            if self._counters(threat_key, text):
                score += 3.0
                matchup_score += 3.0
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
            compatibility_label=etiqueta,
            compatibility_reasons=motivos,
            compatibility_score=compatibilidad,
            matchup_score=round(matchup_score, 1),
        )

    @classmethod
    def _compatibilidad_mecanica(
        cls, perfil: dict[str, Any], estilo: str, item_id: str, item: dict[str, Any]
    ) -> tuple[float, str, tuple[str, ...]]:
        """Puntúa mecánicas observables del objeto frente al patrón del campeón."""
        return cls._evaluar_compatibilidad(perfil, estilo, item_id, item)

    @staticmethod
    def _evaluar_compatibilidad(
        perfil: dict[str, Any], estilo: str, item_id: str, item: dict[str, Any]
    ) -> tuple[float, str, tuple[str, ...]]:
        """Evalúa y cachea kit, estadísticas, pasivas, build y parche sin red."""
        stats = item.get("stats", {}) if isinstance(item.get("stats"), dict) else {}
        tags = item.get("tags", []) if isinstance(item.get("tags"), list) else []
        texto = SynergyRecommendationService._text(item)
        build_cache = perfil.get("most_played_build", [])
        build_cache_key = (
            ",".join(sorted(str(value) for value in build_cache))
            if isinstance(build_cache, list)
            else ""
        )
        patch_cache = str(
            perfil.get("source_patch") or perfil.get("catalog_version") or ""
        )
        pattern_cache = "|".join(
            str(perfil.get(campo, ""))
            for campo in ("combat_pattern", "damage_pattern", "attack_pattern")
        )
        info_basica_cache = perfil.get("basic_info", {})
        if isinstance(info_basica_cache, dict):
            pattern_cache += "|basic:" + "|".join(
                str(info_basica_cache.get(clave, ""))
                for clave in ("damage_type", "play_style", "resource_type")
            )
        metricas_cache = "|".join(
            f"{seccion}:{clave}:{valor}"
            for seccion in (
                "combat_attributes",
                "resistances_and_survivability",
                "map_and_control",
                "power_curve_and_scaling",
            )
            for clave, valor in sorted(
                perfil.get(seccion, {}).items()
                if isinstance(perfil.get(seccion), dict)
                else []
            )
        )
        estrategia_cache = perfil.get("strategy_and_macro", {})
        if isinstance(estrategia_cache, dict):
            pattern_cache += "|" + str(estrategia_cache.get("about", ""))
            pattern_cache += "|" + repr(estrategia_cache.get("primary_combo", []))
        item_cache_key = "|".join(
            (
                str(item_id),
                ",".join(sorted(str(tag) for tag in tags)),
                ",".join(f"{key}:{stats[key]}" for key in sorted(stats)),
                texto,
            )
        )
        cache_key = (
            str(perfil.get("character") or ""),
            patch_cache + "|" + str(perfil.get("recommendation_catalog_patch") or ""),
            str(perfil.get("recommendation_mode") or MODO_SOLOQ),
            str(estilo).casefold(),
            build_cache_key,
            pattern_cache,
            metricas_cache,
            item_cache_key,
        )
        cached = SynergyRecommendationService._compatibility_cache.get(cache_key)
        if cached is not None:
            return cached
        atributos = SynergyRecommendationService._champion_attributes(perfil)
        combate = perfil.get("combat_attributes", {})
        combate = combate if isinstance(combate, dict) else {}
        estrategia = perfil.get("strategy_and_macro", {})
        estrategia = estrategia if isinstance(estrategia, dict) else {}
        clave_estilo = str(estilo or "").casefold()
        patron_explicito = " ".join(
            str(perfil.get(campo, ""))
            for campo in ("combat_pattern", "damage_pattern", "attack_pattern")
        ).casefold()
        about = str(estrategia.get("about", "")).casefold()
        combo = estrategia.get("primary_combo", [])
        usa_combo = isinstance(combo, list) and bool(combo)
        enfasis_ataques = (
            "marksman" in clave_estilo
            or "tirador" in clave_estilo
            or "auto-attack" in patron_explicito
            or "on-hit" in patron_explicito
            or float(combate.get("attack_speed", atributos.get("attack_speed", 0)) or 0)
            >= 6
            or float(combate.get("critic", atributos.get("critic", 0)) or 0) >= 6
            or float(atributos.get("hypercarry", 0) or 0) >= 7
        )
        usa_habilidades = (
            usa_combo
            or any(
                palabra in about
                for palabra in ("ability", "spell", "habilidad", "hechizo")
            )
            or any(
                token in clave_estilo
                for token in (
                    "juggernaut",
                    "fighter",
                    "bruiser",
                    "diver",
                    "mage",
                    "assassin",
                )
            )
        ) and not enfasis_ataques
        punt_ataques = float(
            combate.get("attack_speed", atributos.get("attack_speed", 0)) or 0
        )
        punt_critico = float(combate.get("critic", atributos.get("critic", 0)) or 0)
        velocidad = (
            "AttackSpeed" in tags
            or float(stats.get("attack_speed_percent", 0) or 0) >= 15
        )
        critico = (
            "CriticalStrike" in tags
            or float(stats.get("critical_strike_chance_percent", 0) or 0) >= 10
        )
        impacto = "OnHit" in tags or any(
            termino in texto
            for termino in ("on-hit", "on hit", "al impactar", "al golpear")
        )
        aceleracion = (
            "AbilityHaste" in tags or float(stats.get("ability_haste", 0) or 0) >= 10
        )
        valor = 0.0
        razones: list[str] = []
        if usa_habilidades:
            if velocidad and punt_ataques < 5:
                valor -= 7.0
                razones.append(
                    "Invierte en velocidad de ataque, poco respaldada por el perfil"
                )
            if critico and punt_critico < 5:
                valor -= 7.0
                razones.append(
                    "El crítico no aparece como escalado relevante del campeón"
                )
            if impacto and not velocidad:
                valor -= 5.0
                razones.append("Su efecto de impacto exige ataques básicos frecuentes")
            if aceleracion and usa_combo:
                valor += 3.0
                razones.append(
                    "La aceleración complementa el combo de habilidades registrado"
                )
        texto_normalizado = "".join(
            caracter
            for caracter in unicodedata.normalize("NFKD", texto.casefold())
            if not unicodedata.combining(caracter)
        )
        perfil_soporte = (
            any(
                token in clave_estilo
                for token in ("support", "enchanter", "warden", "soporte")
            )
            or float(atributos.get("heal_shield_power", 0) or 0) >= 6
            or float(atributos.get("utility", 0) or 0) >= 8
        )
        efecto_potencia_soporte = any(
            token in texto_normalizado
            for token in (
                "heal and shield power",
                "healing and shielding",
                "poder de curaciones y escudos",
                "potencia de curaci",
            )
        )
        efecto_dirigido_a_aliado = any(
            token in texto_normalizado for token in ("ally champion", "campeon aliado")
        )
        if efecto_potencia_soporte and not perfil_soporte:
            valor -= 8.0
            razones.append(
                "La potencia de curacion o escudo aporta poco al kit registrado"
            )
        if efecto_dirigido_a_aliado and not perfil_soporte:
            valor -= 5.0
            razones.append(
                "Su activa prioriza proteger a un aliado, no el patron de combate del campeon"
            )
        efecto_requiere_sanacion_aliada = any(
            frase in texto_normalizado
            for frase in (
                "al curar u otorgar un escudo a un aliado",
                "al curar o aplicar un escudo a un aliado",
                "when you heal or shield an ally",
            )
        )
        if efecto_requiere_sanacion_aliada and not perfil_soporte:
            valor -= 9.0
            razones.append("Su efecto principal requiere curar o escudar aliados")
        damage_type = str(
            perfil.get("basic_info", {}).get("damage_type", "")
            if isinstance(perfil.get("basic_info"), dict)
            else ""
        ).casefold()
        attack_power = float(
            combate.get("attack_power", atributos.get("attack_power", 0)) or 0
        )
        if (
            damage_type == "ad"
            and attack_power < 4
            and (
                "SpellDamage" in tags or float(stats.get("ability_power", 0) or 0) >= 30
            )
        ):
            valor -= 7.0
            razones.append(
                "El poder de habilidad no coincide con el da?o principal registrado"
            )
        if "LifeSteal" in tags and usa_habilidades and not enfasis_ataques:
            valor -= 3.0
            razones.append(
                "El robo de vida se aprovecha menos que la supervivencia durante habilidades"
            )
        passive_lifesteal_shield = (
            "LifeSteal" in tags
            and any(
                token in texto_normalizado
                for token in ("excess healing", "exceso de curacion")
            )
            and not enfasis_ataques
        )
        if passive_lifesteal_shield:
            valor -= 5.0
            razones.append(
                "Su escudo depende de aprovechar robo de vida mediante ataques"
            )
        elif enfasis_ataques and (
            (velocidad and punt_ataques >= 5) or (critico and punt_critico >= 5)
        ):
            valor += 2.0
            razones.append(
                "Sus estadísticas coinciden con el patrón de ataques del campeón"
            )
        if not razones:
            razones.append(
                "Sin interacción específica confirmada; se valoran estadísticas y clase"
            )
        valor = max(-14.0, min(6.0, valor))
        etiqueta = (
            "Experimental"
            if valor <= -8
            else "Situacional"
            if valor < -2
            else "Buena sinergia"
            if valor >= 3
            else "Afinidad alta"
            if valor > 0
            else "Situacional"
        )
        resultado = round(valor, 1), etiqueta, tuple(razones)
        cache = SynergyRecommendationService._compatibility_cache
        if len(cache) >= 2048:
            cache.clear()
        cache[cache_key] = resultado
        return resultado

    @staticmethod
    def _is_legendary(item: dict[str, Any]) -> bool:
        basic = (
            item.get("basic_info", {})
            if isinstance(item.get("basic_info"), dict)
            else {}
        )
        tier = str(item.get("tier", basic.get("tier", "")))
        if tier:
            return tier == "Legendary"
        gold = item.get("gold", {})
        return bool(
            isinstance(gold, dict)
            and gold.get("purchasable")
            and gold.get("total", 0) >= 2500
            and not item.get("into")
        )

    @staticmethod
    def _champion_attributes(profile: dict[str, Any]) -> dict[str, float]:
        attributes: dict[str, float] = {}
        for section in (
            "combat_attributes",
            "resistances_and_survivability",
            "map_and_control",
            "power_curve_and_scaling",
        ):
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
        return {
            key: 0.15
            for key in stats
            if key
            in {
                "attack_damage",
                "ability_power",
                "critic",
                "lethality",
                "mobility",
                "wave_clear",
                "hypercarry",
            }
        }

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
        if any(
            term in text for term in ("attack damage", "daño de ataque", "critical")
        ):
            classes.update(("Fighter", "Marksman"))
        if any(
            term in text
            for term in ("ability power", "poder de habilidad", "magic penetration")
        ):
            classes.add("Mage")
        if any(term in text for term in ("health", "vida", "armor", "armadura")):
            classes.update(("Tank", "Juggernaut"))
        return classes

    @staticmethod
    def _text(item: dict[str, Any]) -> str:
        basic = (
            item.get("basic_info", {})
            if isinstance(item.get("basic_info"), dict)
            else {}
        )
        analysis = (
            item.get("analysis", {}) if isinstance(item.get("analysis"), dict) else {}
        )
        return re.sub(
            r"<[^>]+>",
            " ",
            " ".join(
                str(item.get(key, basic.get(key, analysis.get(key, ""))))
                for key in ("name", "description", "plaintext", "tags", "item")
            ),
        ).casefold()

    @staticmethod
    def _name(item: dict[str, Any], fallback: str) -> str:
        basic = (
            item.get("basic_info", {})
            if isinstance(item.get("basic_info"), dict)
            else {}
        )
        return str(item.get("name", basic.get("name", item.get("item", fallback))))
