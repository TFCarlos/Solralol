"""Genera data/passive_rules.json con el nuevo esquema determinista
(stat_bias / utility_tag / weight) a partir de las reglas builtin."""
"""Genera data/passive_rules.json con el esquema determinista v2
(stat_bias / utility_tag / weight) a partir de las reglas builtin."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.synergy_math import BUILTIN_PASSIVE_RULES  # noqa: E402

OUT = Path(r"d:\Accesos\Desktop\Solralol\data\passive_rules.json")

payload = {
    "schema": "v2-deterministic",
    "description": (
        "Reglas de pasivas resueltas SOLO por coincidencia exacta de nombre "
        "(casefold). Sin busquedas difusas. Cada regla declara stat_bias "
        "(arquetipo al que escala), utility_tag (mecanica funcional) y weight "
        "(intensidad 0..1, saturada por sigmoide). counter_keys alimenta "
        "counter_weights (0..1). overlap_with indica la cubeta de stats cuyo "
        "presupuesto ya puntuo ese mecanismo (anti double-dipping)."
    ),
    "passive_rules": {
        name: {
            "stat_bias": rule["stat_bias"],
            "utility_tag": rule["utility_tag"],
            "weight": rule["weight"],
            **({"dynamic": True} if rule.get("dynamic") else {}),
            **({"counter_keys": rule["counter_keys"]} if rule.get("counter_keys") else {}),
            **({"overlap_with": rule["overlap_with"]} if rule.get("overlap_with") else {}),
        }
        for name, rule in sorted(BUILTIN_PASSIVE_RULES.items())
    },
}

OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"escrito {OUT} con {len(payload['passive_rules'])} reglas")
