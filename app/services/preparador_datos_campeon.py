"""Generación explícita de recomendaciones persistidas, separada de las consultas."""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import data_dragon
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.repositorio_campeones import RepositorioCampeones
from app.services.synergy_recommendation_service import SynergyRecommendationService

CAMPOS_VARIANTE = (
    "runes",
    "common_runes",
    "most_played_build",
    "starter_items",
    "summoner_spells",
    "situational_items",
    "matchups",
    "damage_breakdown",
    "win_rate_vs_game_length",
    "skill_order",
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
        )
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
                recomendaciones = SynergyRecommendationService().rank_items(
                    combinado,
                    str(combinado["basic_info"].get("play_style", "Adaptable")),
                    self.catalogo.objetos_recomendables(),
                    [],
                    30,
                )
                variante["recommendations"] = [
                    dict(
                        asdict(valor),
                        reasons=list(valor.reasons),
                        counter_reasons=list(valor.counter_reasons),
                    )
                    for valor in recomendaciones
                ]
                variante["role"] = linea
                variante["rank"] = rango
                variante["generated_at"] = documento["updated_at"]
                resumen = bloque.get("__lane_stats__", {}).get("lanes", {})
                muestra = resumen.get(linea, {}).get("games")
                variante["sample_size"] = muestra if isinstance(muestra, int) else None
                if cobertura == "complete":
                    variante.pop("lane_stats", None)
                    if variante.get("common_runes") == variante.get("runes"):
                        variante.pop("common_runes", None)
        return documento

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
