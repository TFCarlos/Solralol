"""Generación explícita de recomendaciones persistidas, separada de las consultas."""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import data_dragon
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.elegibilidad_objetos import (
    MODO_SOLOQ,
    ValidadorElegibilidadObjetos,
)
from app.services.repositorio_campeones import RepositorioCampeones
from app.services.synergy_recommendation_service import SynergyRecommendationService

CAMPOS_VARIANTE = (
    "runes",
    "common_runes",
    "most_played_build",
    "starter_items",
    "starter_item_entries",
    "starter_item_ids",
    "starting_items_source_status",
    "starting_items_provenance",
    "summoner_spells",
    "situational_items",
    "situational_item_candidates",
    "source_situational_items",
    "matchups",
    "damage_breakdown",
    "win_rate_vs_game_length",
    "skill_order",
    "overall_matches",
    "overall_win_rate",
    "section_sample_sizes",
    "section_status",
    "source_patch",
    "patch_label",
    "item_options",
    "boots",
    "recommended_build",
    "recommended_build_details",
    "item_candidates",
    "recommendation_diagnostics",
    "recommendation_mode",
    "recommendation_catalog_version",
    "situational_item_pipeline",
    "core_build",
    "core_build_matches",
    "core_build_win_rate",
    "rune_page_matches",
    "summoner_spell_ids",
    "summoner_spell_matches",
    "summoner_spell_win_rate",
    "starter_item_ids",
    "starting_item_matches",
    "starting_item_win_rate",
    "skill_priority_matches",
    "skill_priority_win_rate",
)


def combinar_perfil(perfil: dict[str, Any], variante: dict[str, Any]) -> dict[str, Any]:
    """Combina perfil global y variante recibidos sin reutilizar campos de otro filtro."""
    combinado = copy.deepcopy(perfil)
    for campo in CAMPOS_VARIANTE:
        combinado.pop(campo, None)
        if campo in variante:
            combinado[campo] = copy.deepcopy(variante[campo])
    combinado.pop("lane_stats", None)
    combinado.setdefault("power_curve_and_scaling", {}).pop("power_spike_items", None)
    if variante.get("power_spike_items"):
        combinado["power_curve_and_scaling"]["power_spike_items"] = list(
            variante["power_spike_items"]
        )
    return combinado


class PreparadorDatosCampeon:
    """Calcula recomendaciones una vez al migrar o actualizar, nunca al navegar."""

    def __init__(self, raiz_datos: Path) -> None:
        """Carga catálogos locales de raíz recibida; retorna None y no realiza red."""
        objetos = json.loads((raiz_datos / "items.json").read_text(encoding="utf-8"))
        legendarios = json.loads(
            (raiz_datos / "legendary_items_strict.json").read_text(encoding="utf-8")
        )
        self.catalogo = CatalogoAnalisisLocal(
            objetos.get("items", {}),
            legendarios,
            SynergyRecommendationService.ITEM_NAME_ALIASES,
            str(objetos.get("version") or "16.17.1"),
        )
        self.objetos_estrictos = {
            str(item.get("id")): item
            for item in legendarios
            if isinstance(item, dict) and item.get("id")
        }
        self.version = str(objetos.get("version") or "16.17.1")

    def preparar(
        self,
        perfil: dict[str, Any],
        matriz: dict[str, Any],
        cobertura: str = "complete",
    ) -> dict[str, Any]:
        """Valida perfil/matriz y genera recomendaciones serializables; devuelve documento listo para guardar."""
        documento = RepositorioCampeones.documento(perfil, matriz, cobertura)
        documento["catalog_version"] = self.version
        RepositorioCampeones.validar(documento, perfil["character"])
        for rango, bloque in documento["ranks"].items():
            for linea, variante in bloque.items():
                if linea == "__lane_stats__":
                    continue
                combinado = combinar_perfil(perfil, variante)
                motor = SynergyRecommendationService()
                candidatos = motor.rank_candidates(
                    combinado,
                    str(combinado["basic_info"].get("play_style", "Adaptable")),
                    self.catalogo.objetos_recomendables(),
                    [],
                    game_mode=MODO_SOLOQ,
                    catalog_patch=self.version,
                )
                recomendaciones = candidatos[:30]
                variante["recommendations"] = [
                    dict(
                        asdict(valor),
                        reasons=list(valor.reasons),
                        counter_reasons=list(valor.counter_reasons),
                        compatibility_reasons=list(valor.compatibility_reasons),
                    )
                    for valor in recomendaciones
                ]
                variante["item_candidates"] = [
                    dict(
                        asdict(valor),
                        reasons=list(valor.reasons),
                        counter_reasons=list(valor.counter_reasons),
                        compatibility_reasons=list(valor.compatibility_reasons),
                    )
                    for valor in candidatos
                ]
                self._preparar_recomendaciones_situacionales(
                    variante,
                    candidatos,
                    combinado,
                    ValidadorElegibilidadObjetos.diagnosticar_catalogo(
                        self.catalogo.catalogo,
                        str(combinado.get("character") or ""),
                        MODO_SOLOQ,
                        self.version,
                    ),
                )
                self._preparar_build_recomendada(variante, combinado)
                variante["role"] = linea
                variante["rank"] = rango
                variante["generated_at"] = documento["updated_at"]
                resumen = bloque.get("__lane_stats__", {}).get("lanes", {})
                muestra = variante.get("overall_matches") or resumen.get(linea, {}).get(
                    "games"
                )
                variante["sample_size"] = muestra if isinstance(muestra, int) else None
                if cobertura == "complete" and any(
                    variante.get(campo)
                    for campo in ("runes", "most_played_build", "matchups")
                ):
                    variante.pop("lane_stats", None)
                    if variante.get("common_runes") == variante.get("runes"):
                        variante.pop("common_runes", None)
        return documento

    def _preparar_recomendaciones_situacionales(
        self,
        variante: dict[str, Any],
        candidatos: list[Any],
        perfil: dict[str, Any],
        diagnostico_elegibilidad: dict[str, Any],
    ) -> None:
        """Clasifica el catálogo elegible y guarda el pool contextual completo."""
        grupos: dict[str, list[dict[str, Any]]] = {
            "corta_curas": [],
            "tanque": [],
            "asesino": [],
            "utilidad_y_defensa": [],
        }
        core_ids = {
            str(item.get("item_id"))
            for item in variante.get("core_build", [])
            if isinstance(item, dict)
        }
        source_options = {
            str(item.get("item_id"))
            for opciones in variante.get("item_options", {}).values()
            if isinstance(opciones, list)
            for item in opciones
            if isinstance(item, dict)
        }
        entries: list[dict[str, Any]] = []
        rejected: dict[str, int] = {}
        style = str(perfil.get("basic_info", {}).get("play_style", "")).casefold()
        clases_compatibles = {
            "juggernaut": {"fighter", "juggernaut"},
            "fighter": {"fighter", "juggernaut", "tank"},
            "assassin": {"assassin", "fighter"},
            "mage": {"mage", "support"},
            "tank": {"tank", "fighter", "support"},
            "marksman": {"marksman", "fighter"},
            "support": {"support", "tank", "mage"},
        }.get(style, set())
        for candidato in candidatos:
            item_id = str(candidato.item_id)
            item = dict(self.catalogo.catalogo.get(item_id, {}))
            item.update(
                {
                    key: value
                    for key, value in self.objetos_estrictos.get(item_id, {}).items()
                    if value is not None
                }
            )
            description = re.sub(
                r"<[^>]+>", " ", str(item.get("description", ""))
            ).casefold()
            description = re.sub(r"\s+", " ", description)
            tags = set(item.get("tags", []))
            classifications = item.get("classifications", {})
            mechanics = {
                str(value).casefold()
                for value in classifications.get("counter_mechanics", [])
            }
            intended = {
                str(value).casefold()
                for value in classifications.get("intended_classes", [])
            }
            compatible = not intended or bool(intended & clases_compatibles)
            antihealing = (
                "heridas graves" in description
                or "grievous wounds" in description
                or re.search(r"aplica (?:un )?\d+(?:[.,]\d+)?% de heridas", description)
                is not None
            )
            if antihealing:
                category = "corta_curas"
            elif mechanics.intersection({"shields", "crowd_control"}) or any(
                word in description
                for word in (
                    "cleanse",
                    "limpia",
                    "shield",
                    "escudo",
                    "revive",
                    "resucita",
                    "slow",
                    "ralentiza",
                    "damage reduction",
                    "reduces damage",
                    "reducciÃ³n de daÃ±o",
                    "heal and shield power",
                    "poder de curaciones y escudos",
                    "spell shield",
                    "escudo de hechizos",
                )
            ):
                category = "utilidad_y_defensa"
            elif tags.intersection({"Armor", "SpellBlock"}):
                category = "tanque"
            elif (
                tags.intersection({"ArmorPenetration", "MagicPenetration"})
                or "lethality" in description
                or "letalidad" in description
                or (
                    "CriticalStrike" in tags
                    and (
                        float(perfil.get("combat_attributes", {}).get("critic", 0) or 0)
                        >= 5
                        or "marksman" in style
                    )
                )
            ):
                category = "asesino"
            elif "Health" in tags and not tags.intersection(
                {
                    "Damage",
                    "SpellDamage",
                    "AttackSpeed",
                    "CriticalStrike",
                    "ArmorPenetration",
                    "MagicPenetration",
                    "LifeSteal",
                    "OnHit",
                }
            ):
                category = "tanque"
            else:
                rejected["sin_categoria"] = rejected.get("sin_categoria", 0) + 1
                continue
            umbral_valido = candidato.score >= 8 or (
                compatible and category == "corta_curas"
            )
            incompatibilidad_severa = (
                candidato.compatibility_score <= -5 and not candidato.counter_reasons
            )
            if not umbral_valido or item_id in core_ids:
                motivo = "puntuacion_o_core"
                rejected[motivo] = rejected.get(motivo, 0) + 1
                continue
            entry = {
                "item_id": item_id,
                "name": candidato.name,
                "score": candidato.score,
                "category": category,
                "origin": "SOLRALOL",
                "source_option": item_id in source_options,
                "reasons": list(candidato.reasons),
                "compatibility_label": (
                    "Experimental"
                    if incompatibilidad_severa
                    else candidato.compatibility_label
                ),
                "compatibility_reasons": list(candidato.compatibility_reasons),
                "situational_reason": {
                    "corta_curas": "Considerar cuando la curación rival sea una amenaza relevante.",
                    "tanque": "Elegir frente al tipo de daño que realmente deba resistirse.",
                    "asesino": "Priorizar si la penetración o el remate encajan con el plan de daño.",
                    "utilidad_y_defensa": "Reservar para una amenaza o necesidad defensiva concreta.",
                }[category],
                "compatibility_score": candidato.compatibility_score,
                "matchup_score": candidato.matchup_score,
                "build_synergy_score": candidato.build_synergy_score,
            }
            entries.append(entry)
            grupos[category].append(entry)
        for values in grupos.values():
            values.sort(
                key=lambda value: (
                    value["compatibility_label"] != "Experimental",
                    value["score"],
                ),
                reverse=True,
            )
        variante["situational_item_candidates"] = entries
        variante["situational_items"] = {
            category: [entry["name"] for entry in values]
            for category, values in grupos.items()
        }
        matchups = variante.get("matchups", {})
        options = variante.get("item_options", {})
        variante["recommendation_diagnostics"] = {
            "champion": perfil.get("character"),
            "lane": variante.get("role"),
            "rank": variante.get("rank"),
            "patch": variante.get("source_patch"),
            "overall_matches": variante.get("overall_matches"),
            "raw_core_entries": len(variante.get("core_build", [])),
            "normalized_core_entries": len(core_ids),
            "raw_boots_entries": len(variante.get("boots", [])),
            "normalized_boot_choices": int(bool(variante.get("boots"))),
            "raw_later_item_options": sum(
                len(values) for values in options.values() if isinstance(values, list)
            ),
            "eligible_situational_candidates": len(entries),
            "displayed_situational_candidates": len(entries),
            "affinity_candidate_count": len(candidatos),
            "synergy_candidate_count": len(candidatos),
            "raw_unfavorable_matchups": len(matchups.get("counters", [])),
            "raw_favorable_matchups": len(matchups.get("good_against", [])),
            "normalized_unfavorable_matchups": len(matchups.get("counters", [])),
            "normalized_favorable_matchups": len(matchups.get("good_against", [])),
            "rejected_entries": rejected,
            "eligibility": diagnostico_elegibilidad,
        }
        variante["recommendation_mode"] = MODO_SOLOQ
        variante["recommendation_catalog_version"] = self.version

    def _preparar_build_recomendada(
        self, variante: dict[str, Any], perfil: dict[str, Any]
    ) -> None:
        """Combina el núcleo confirmado con botas fuente o locales sin duplicar."""
        core = [
            dict(item)
            for item in variante.get("core_build", [])
            if isinstance(item, dict) and item.get("item_id")
        ]
        core_ids = {str(item["item_id"]) for item in core}
        tiene_botas = any(
            "Boots" in self.catalogo.catalogo.get(item_id, {}).get("tags", [])
            for item_id in core_ids
        )
        botas = variante.get("boots")
        seleccion = (
            next(
                (
                    dict(item)
                    for item in botas
                    if not tiene_botas
                    and isinstance(item, dict)
                    and str(item.get("item_id")) not in core_ids
                    and "Boots"
                    in self.catalogo.catalogo.get(str(item.get("item_id")), {}).get(
                        "tags", []
                    )
                    and self.catalogo.validar_elegibilidad(
                        str(item.get("item_id")),
                        self.catalogo.catalogo.get(str(item.get("item_id")), {}),
                        str(perfil.get("character") or ""),
                        MODO_SOLOQ,
                    ).elegible
                ),
                None,
            )
            if isinstance(botas, list)
            else None
        )
        if seleccion is None and not tiene_botas:
            motor = SynergyRecommendationService()
            for item_id, item in self.catalogo.catalogo.items():
                if "Boots" not in item.get("tags", []) or str(item_id) in core_ids:
                    continue
                if not self.catalogo.validar_elegibilidad(
                    str(item_id),
                    item,
                    str(perfil.get("character") or ""),
                    MODO_SOLOQ,
                ).elegible:
                    continue
                puntuacion = self._puntuar_botas_locales(
                    perfil, str(item_id), item, motor
                )
                if seleccion is None or puntuacion > float(seleccion.get("score", -1)):
                    seleccion = {
                        "item_id": str(item_id),
                        "name": item.get("name_es") or item.get("name", str(item_id)),
                        "score": puntuacion,
                        "origin": "SOLRALOL",
                        "source": "catalogo_local",
                        "basis": "Afinidad de estilo y propiedades del objeto",
                    }
        build = list(core)
        detalles = [{**item, "origin": "U.GG"} for item in core]
        if seleccion:
            seleccion.setdefault("origin", "U.GG")
            if not tiene_botas:
                posicion = min(1, len(build))
                build.insert(posicion, seleccion)
                detalles.insert(posicion, seleccion)
        variante["recommended_build"] = build[:6]
        variante["recommended_build_details"] = detalles[:6]

    @staticmethod
    def _puntuar_botas_locales(
        perfil: dict[str, Any],
        item_id: str,
        item: dict[str, Any],
        motor: SynergyRecommendationService,
    ) -> float:
        """Puntúa botas válidas según su equipo y el estilo general del campeón."""
        estilo = str(perfil.get("basic_info", {}).get("play_style", "Adaptable"))
        recomendacion = motor.score_item(perfil, estilo, item_id, item, [])
        etiquetas = set(item.get("tags", []))
        estilo_normalizado = estilo.casefold()
        if estilo_normalizado in {"juggernaut", "fighter", "bruise", "bruiser"}:
            recomendacion = recomendacion.score + (
                3.0 if "CooldownReduction" in etiquetas else 0.0
            )
        elif estilo_normalizado in {"marksman", "adc", "hypercarry"}:
            recomendacion = recomendacion.score + (
                3.0 if "AttackSpeed" in etiquetas else 0.0
            )
        elif estilo_normalizado in {"mage", "assassin"}:
            recomendacion = recomendacion.score + (
                2.0 if "MagicPenetration" in etiquetas else 0.0
            )
        elif estilo_normalizado in {"tank", "support"}:
            recomendacion = recomendacion.score + (
                2.0
                if etiquetas.intersection({"Armor", "SpellBlock", "Tenacity"})
                else 0.0
            )
        return round(float(recomendacion), 1)

    @staticmethod
    def _item_comprable(item: dict[str, Any]) -> bool:
        """Comprueba que un objeto sea comprable y final en el catálogo actual."""
        gold = item.get("gold", {})
        maps = item.get("maps", {})
        return bool(
            isinstance(gold, dict)
            and gold.get("purchasable")
            and int(gold.get("total", 0) or 0) >= 500
            and not item.get("into")
            and not (isinstance(maps, dict) and "11" in maps and not maps["11"])
        )

    def descargar_recursos(
        self, documento: dict[str, Any], cancelado: Callable[[], bool]
    ) -> None:
        """Prepara assets del documento durante actualización explícita; cancela antes de guardar.

        Además de iconos, runas y hechizos, asegura el splash del héroe en
        `data/champion_splashes/` para que la tarjeta del campeón pueda
        mostrarlo nada más persistir los datos. Un fallo del splash no aborta
        la actualización: los datos válidos se conservan y se usa el
        degradado de reserva.
        """
        from app.services.analisis_local_service import AnalisisLocalService

        campeon = documento["champion"]
        data_dragon.get_champion_data(campeon, self.version)
        if cancelado():
            raise InterruptedError("Actualización cancelada")
        try:
            data_dragon.get_champion_splash_path(campeon)
        except Exception:
            logging.getLogger(__name__).warning(
                "[assets] splash no disponible para %s", campeon, exc_info=True
            )
        referencias: set[tuple[str, str]] = {("champion", campeon)}
        for habilidad in ("Q", "W", "E", "R"):
            if cancelado():
                raise InterruptedError("Actualización cancelada")
            data_dragon.get_ability_icon_path(campeon, habilidad, self.version)
        for bloque in documento["ranks"].values():
            for linea, variante in bloque.items():
                if linea == "__lane_stats__":
                    continue
                referencias.update(
                    ("rune", nombre)
                    for nombre in AnalisisLocalService.textos(variante.get("runes"))
                )
                referencias.update(
                    ("spell", nombre)
                    for nombre in AnalisisLocalService.textos(
                        variante.get("summoner_spells")
                    )
                )
                for grupo in ("counters", "good_against"):
                    referencias.update(
                        ("champion", valor["champion"])
                        for valor in variante.get("matchups", {}).get(grupo, [])
                        if isinstance(valor, dict) and valor.get("champion")
                    )
                referencias.update(
                    ("item", str(valor["item_id"]))
                    for valor in variante.get("recommendations", [])
                )
                for campo in (
                    "most_played_build",
                    "starter_items",
                    "situational_items",
                    "runes",
                    "power_spike_items",
                ):
                    for nombre in AnalisisLocalService.textos(variante.get(campo)):
                        identificador = self.catalogo.id_por_nombre(
                            nombre, self.catalogo.catalogo
                        )
                        if identificador:
                            referencias.add(("item", identificador))
        for tipo, nombre in sorted(referencias):
            if cancelado():
                raise InterruptedError("Actualización cancelada")
            if tipo == "item":
                data_dragon.get_item_icon_path(
                    nombre, self.catalogo.catalogo, self.version
                )
            else:
                funcion = {
                    "champion": data_dragon.get_champion_icon_path,
                    "rune": data_dragon.get_rune_icon_path,
                    "spell": data_dragon.get_spell_icon_path,
                }[tipo]
                funcion(nombre, self.version)
