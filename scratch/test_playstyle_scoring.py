"""Ejemplo y validación de la puntuación ponderada por playstyle.

Caso de uso pedido: Ornn (Vanguard) con ``Égida de fuego solar`` (alta
afinidad) frente a ``Eco de Luden`` / ``Puñal de Statikk`` / ``Diente de
Nashor`` (escalados residuales → deben hundirse). Contrasta además con
Mordekaiser (Juggernaut, AP principal), que sí debe poder construir AP.

Ejecutar desde la raíz:  python scratch/test_playstyle_scoring.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from _paths import DATA_DIR
from app.services.playstyle_service import (
    Playstyle,
    primary_attributes,
    register_playstyle,
    resolve_playstyle,
)
from app.services.synergy_recommendation_service import SynergyRecommendationService


def load_json(name: str):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as handle:
        return json.load(handle)


def champion(name: str) -> dict:
    for entry in load_json("champions_strict.json"):
        if entry.get("character") == name:
            return entry
    raise AssertionError(f"Campeón no encontrado: {name}")


def items_by_id(*ids: str) -> dict:
    wanted = set(ids)
    return {
        entry["id"]: entry
        for entry in load_json("legendary_items_strict.json")
        if entry.get("id") in wanted
    }


service = SynergyRecommendationService()

# --- 1. Resolución modular de playstyles -----------------------------------
assert resolve_playstyle("Vanguard").label == "Vanguardia"
assert resolve_playstyle("tank").label == "Vanguardia"          # alias legacy
assert resolve_playstyle("burst_ap").label == "Mago"            # alias legacy
assert resolve_playstyle("ClaveInventada").key == "neutral"     # fallback
print("OK 1 · resolución de playstyles y alias legacy")

# --- 2. Registro de un playstyle nuevo (modularidad) -----------------------
register_playstyle(Playstyle(
    key="Artillería",
    label="Artillería",
    favored_classes=frozenset({"Mage", "Marksman"}),
    disfavored_classes=frozenset({"Tank"}),
    buffs={"attack_power": 0.6, "range": 0.5},
    nerfs={"durability": 0.8},
    description="Ejemplo de estilo creado en tiempo de ejecución.",
))
assert resolve_playstyle("Artillería").buffs["attack_power"] == 0.6
print("OK 2 · registro dinámico de playstyles")

# --- 3. Escalados principales: Ornn vs Mordekaiser -------------------------
ornn = champion("Ornn")
morde = champion("Mordekaiser")
ornn_primary = primary_attributes(service._champion_attributes(ornn))
morde_primary = primary_attributes(service._champion_attributes(morde))
assert "attack_power" not in ornn_primary, ornn_primary  # AP residual
assert "attack_power" in morde_primary, morde_primary    # AP real
print(f"OK 3 · escalados principales · Ornn AP principal={('attack_power' in ornn_primary)}"
      f" · Morde AP principal={('attack_power' in morde_primary)}")

# --- 4. Ornn: tanque viable vs objetos incompatibles ------------------------
ids = ("3068", "6655", "3087", "3115")  # Égida, Luden, Statikk, Nashor
catalog = items_by_id(*ids)
assert len(catalog) == len(ids), catalog.keys()

style = ornn["basic_info"]["play_style"]  # "Vanguard"
ranked = service.rank_items(ornn, style, catalog, [], limit=10)
scores = {rec.item_id: rec.score for rec in ranked}
print("\n--- Ornn · afinidad de objetos (playstyle Vanguard/Vanguardia) ---")
for rec in ranked:
    print(f"  {rec.score:6.1f}  {rec.name}  | {'; '.join(rec.reasons)}")

egida = scores.get("3068", 0.0)
luden = scores.get("6655", 0.0)
statikk = scores.get("3087", 0.0)
nashor = scores.get("3115", 0.0)
assert ranked and ranked[0].item_id == "3068", ranked[0]
assert egida >= 15.0, egida                       # alta afinidad (antes ~37.8)
assert luden <= 5.0, luden                        # antes 24.5 con AP residual
assert statikk <= 5.0, statikk                    # antes 16.4
assert nashor <= 5.0, nashor                      # antes 16.9
assert egida - luden >= 15.0, (egida, luden)
print(f"OK 4 · Ornn: Égida {egida} ≫ Luden {luden} / Statikk {statikk} / Nashor {nashor}")

# --- 5. Gate por escalado real: Mordekaiser sí puede comprar AP -------------
style = morde["basic_info"]["play_style"]  # "Juggernaut"
morde_luden = service.score_item(morde, style, "6655", catalog["6655"], [])
print(f"\n--- Mordekaiser · Eco de Luden (AP principal, sin nerf) ---")
print(f"  {morde_luden.score:6.1f}  {morde_luden.name}  | {'; '.join(morde_luden.reasons)}")
assert morde_luden.score > 10.0, morde_luden.score
assert morde_luden.score > luden + 10.0, (morde_luden.score, luden)
print(f"OK 5 · Mordekaiser conserva AP ({morde_luden.score}) vs Ornn hunde Luden ({luden})")

# --- 6. Estilo legacy sin playstyle definido: sin nerfs (comportamiento viejo)
legacy = service.score_item(ornn, "ClaveInventada", "6655", catalog["6655"], [])
assert legacy.score >= 0.0
print(f"\nOK 6 · clave desconocida → playstyle Neutral, score {legacy.score} sin penalizaciones")

print("\nPLAYSTYLE SCORING OK")
