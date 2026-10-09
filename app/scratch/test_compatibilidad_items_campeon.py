"""Regresiones de compatibilidad mecánica para recomendaciones de objetos."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.preparador_datos_campeon import PreparadorDatosCampeon
from app.services.synergy_recommendation_service import SynergyRecommendationService


def cargar_item(item_id: str) -> dict[str, Any]:
    """Devuelve el objeto de Data Dragon de la versión local comprobada."""
    datos = json.loads(Path("data/items.json").read_text(encoding="utf-8"))
    return datos["items"][item_id]


def test_aatrox_penaliza_critico_velocidad_y_on_hit_sin_perder_alternativas() -> None:
    """Deprioriza activadores de ataques y mantiene objetos de luchador y defensa."""
    documento = json.loads(
        Path("data/champion_data/aatrox.json").read_text(encoding="utf-8")
    )
    perfil = documento["profile"]
    motor = SynergyRecommendationService()
    runaan = motor.score_item(perfil, "Juggernaut", "3085", cargar_item("3085"), [])
    navori = motor.score_item(perfil, "Juggernaut", "6675", cargar_item("6675"), [])
    shojin = motor.score_item(perfil, "Juggernaut", "3161", cargar_item("3161"), [])
    baile = motor.score_item(perfil, "Juggernaut", "6333", cargar_item("6333"), [])

    assert runaan.compatibility_score <= -10
    assert runaan.compatibility_label == "Experimental"
    assert navori.compatibility_score < shojin.compatibility_score
    assert shojin.compatibility_score > 0
    assert baile.compatibility_score >= 0

    variante = documento["ranks"]["emerald_plus"]["mid"]
    preparado = PreparadorDatosCampeon(Path("data")).preparar(
        perfil, {"emerald_plus": {"mid": variante}}
    )["ranks"]["emerald_plus"]["mid"]
    assert len(preparado["item_candidates"]) > 100
    nombres = {valor["name"] for valor in preparado["situational_item_candidates"]}
    assert "Huracán de Runaan" not in nombres
    assert "Filofugaz de Navori" not in nombres
    assert len(preparado["situational_item_candidates"]) >= 30
    assert all(preparado["situational_items"].values())
    assert "Mecanoespada punki" in preparado["situational_items"]["corta_curas"]
    assert (
        "Mecanoespada punki" not in preparado["situational_items"]["utilidad_y_defensa"]
    )
    lanza = next(
        valor for valor in preparado["item_candidates"] if valor["item_id"] == "3161"
    )
    assert lanza["compatibility_score"] == 3
    assert "combo de habilidades" in " ".join(lanza["compatibility_reasons"])


def test_compatibilidad_responde_a_arquetipos_y_excepciones_de_ataque() -> None:
    """Ajusta activadores de crítico/ataque a perfiles diversos sin veto por clase."""
    motor = SynergyRecommendationService()
    objeto_critico = {
        "name": "Arma de crítico",
        "tags": ["AttackSpeed", "CriticalStrike", "OnHit"],
        "stats": {"attack_speed_percent": 30, "critical_strike_chance_percent": 25},
        "description": "Al impactar inflige daño adicional.",
    }
    objeto_haste = {
        "name": "Filo de habilidades",
        "tags": ["Damage", "AbilityHaste"],
        "stats": {"attack_damage": 50, "ability_haste": 20},
        "description": "Acelera las habilidades del campeón.",
    }
    perfiles = [
        (
            "Aatrox",
            "Juggernaut",
            {"attack_damage": 8, "critic": 1},
            {"primary_combo": ["Q", "W", "E"], "about": "Ability fighter"},
            True,
        ),
        (
            "TiradorAS",
            "Marksman",
            {"attack_damage": 8, "attack_speed": 8},
            {"primary_combo": ["Q"]},
            False,
        ),
        (
            "TiradorCritico",
            "Marksman",
            {"attack_damage": 8, "critic": 8},
            {"primary_combo": ["Q"]},
            False,
        ),
        (
            "Mago",
            "Mage",
            {"attack_power": 9},
            {"primary_combo": ["Q", "E"]},
            True,
        ),
        ("Tanque", "Vanguard", {"durability": 9, "armor": 8}, {}, False),
        (
            "Encantador",
            "Enchanter",
            {"heal_shield_power": 9, "utility": 8},
            {"primary_combo": ["W", "E"]},
            True,
        ),
        (
            "Hibrido",
            "Skirmisher",
            {"attack_speed": 7, "attack_damage": 8},
            {"primary_combo": ["Q", "E"]},
            False,
        ),
    ]

    resultados: dict[str, tuple[float, float]] = {}
    for nombre, estilo, atributos, estrategia, habilidad in perfiles:
        perfil: dict[str, Any] = {
            "character": nombre,
            "source_patch": "16.20",
            "combat_attributes": atributos,
            "strategy_and_macro": estrategia,
        }
        velocidad = motor.score_item(perfil, estilo, "critico", objeto_critico, [])
        haste = motor.score_item(perfil, estilo, "haste", objeto_haste, [])
        resultados[nombre] = (
            velocidad.compatibility_score,
            haste.compatibility_score,
        )
        if habilidad:
            assert haste.compatibility_score >= 0

    assert resultados["Aatrox"][0] <= -10
    assert resultados["TiradorAS"][0] > resultados["Aatrox"][0]
    assert resultados["TiradorCritico"][0] > resultados["Aatrox"][0]
    assert resultados["Hibrido"][0] >= resultados["Aatrox"][0]
    assert resultados["Mago"][1] > resultados["Mago"][0]
    assert resultados["Tanque"][0] == 0
    assert resultados["Encantador"][1] == 3


def test_bonificacion_de_build_no_compensa_incompatibilidad_mecanica() -> None:
    """Limita el peso de popularidad observada y no usa su propia salida como evidencia."""
    perfil = {"character": "Aatrox", "combat_attributes": {"critic": 1}}
    motor = SynergyRecommendationService()
    objeto = {
        "name": "Huracán de Runaan",
        "tags": ["AttackSpeed", "CriticalStrike", "OnHit"],
        "stats": {"attack_speed_percent": 30, "critical_strike_chance_percent": 25},
        "description": "Al impactar.",
    }
    recomendacion = motor.score_item(perfil, "Juggernaut", "3085", objeto, [])
    perfil["situational_items"] = {"asesino": [recomendacion.name]}
    sin_auto_sinergia = motor.score_item(perfil, "Juggernaut", "3085", objeto, [])
    con_build_observada = motor._apply_synergy_bonuses(
        recomendacion, set(), {"huracan de runaan"}
    )

    assert sin_auto_sinergia.score == recomendacion.score
    assert con_build_observada.score - recomendacion.score <= 6
    assert con_build_observada.compatibility_score == recomendacion.compatibility_score


def test_cache_cambia_con_parche_build_y_mecanicas_del_campeon() -> None:
    """Invalida la compatibilidad al cambiar entradas mecánicas relevantes."""
    motor = SynergyRecommendationService()
    perfil: dict[str, Any] = {
        "character": "Tirador variable",
        "source_patch": "16.20",
        "combat_attributes": {"attack_speed": 2, "critic": 1},
        "strategy_and_macro": {"primary_combo": ["Q"]},
    }
    objeto = {
        "tags": ["AttackSpeed", "CriticalStrike"],
        "stats": {"attack_speed_percent": 30, "critical_strike_chance_percent": 25},
        "description": "",
    }
    base = motor._compatibilidad_mecanica(perfil, "Fighter", "arma", objeto)
    repetido = motor._compatibilidad_mecanica(perfil, "Fighter", "arma", objeto)
    cantidad_cache = len(SynergyRecommendationService._compatibility_cache)
    perfil["combat_attributes"] = {"attack_speed": 8, "critic": 8}
    mejor_escalado = motor._compatibilidad_mecanica(perfil, "Fighter", "arma", objeto)
    perfil["source_patch"] = "16.21"
    nuevo_parche = motor._compatibilidad_mecanica(perfil, "Fighter", "arma", objeto)

    assert base[0] < mejor_escalado[0]
    assert repetido == base
    assert len(SynergyRecommendationService._compatibility_cache) == cantidad_cache + 2
    assert len(SynergyRecommendationService._compatibility_cache) >= 3
    assert nuevo_parche == mejor_escalado
