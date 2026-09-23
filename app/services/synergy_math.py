"""Arquitectura matemática de sinergias y contrapesos para objetos de League of Legends.

Modelo cuantitativo usado por `ItemSynergyCalculatorService`:

1. Normalización por Valor de Oro: cada stat se convierte a oro con las
   paridades del juego, eliminando divisores hardcodeados (ad / 10, hp / 100...).

2. Perfil de presupuesto relativo: el oro se reparte en 3 cubetas ortogonales
   (Ofensiva / Defensiva / Utilidad) como porcentaje (suma = 1.0), de modo que
   la puntuación es invariante al coste: puntúa la *concentración* del gasto.

3. Escala homogénea: `synergy_multipliers` en [1.0, 2.0] y `counter_weights`
   en [0.0, 1.0]. Toda contribución pasa por una sigmoide logística
   S(x) = 1/(1+e^(-k(x-x0))), monótona y acotada: acumular pasivas o stats
   nunca supera el techo (anti-explosión).

4. Modelo ortogonal anti Double Dipping: Base Stat Score (solo stats directas)
   y Passive Value Modifiers (solo mecanismos funcionales). Cuando una pasiva
   repite un mecanismo ya puntuado vía stats, su aporte se multiplica por
   (1 - overlap): solo puntúa la diferencia funcional.

5. Categorización determinista: pasivas resueltas por nombre exacto con reglas
   `stat_bias` / `utility_tag` / `weight`. Sin búsquedas difusas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final

# ---------------------------------------------------------------------------
# 1. Paridad de oro: oro que cuesta 1 unidad de cada stat, derivada de objetos
#    básicos (Long Sword 350g/10AD=35, Ruby Crystal 400g/150HP~2.67, Cloth
#    Armor 300g/15=20, Cloak of Agility 600g/15%=40, AH oficial ~31.25...).
# ---------------------------------------------------------------------------
GOLD_PARITY: Final[dict[str, float]] = {
    "attack_damage": 35.0,
    "ability_power": 20.0,
    "health": 2.67,
    "armor": 20.0,
    "magic_resistance": 20.0,
    "attack_speed_percent": 25.0,
    "critical_strike_chance_percent": 40.0,
    "ability_haste": 31.25,
    "lethality": 30.0,
    "armor_penetration_percent": 31.25,
    "magic_penetration_percent": 31.25,
    "magic_penetration_flat": 24.0,
    "life_steal_percent": 37.5,
    "omnivamp_percent": 46.0,
    "heal_and_shield_power_percent": 37.5,
    "movement_speed_flat": 12.0,
    "movement_speed_percent": 39.0,
    "base_health_regeneration_percent": 9.0,
    "base_mana_regeneration_percent": 10.0,
    "tenacity": 20.0,
}

# Cubeta ortogonal de presupuesto a la que pertenece cada stat.
STAT_BUCKETS: Final[dict[str, str]] = {
    "attack_damage": "offensive",
    "ability_power": "offensive",
    "critical_strike_chance_percent": "offensive",
    "lethality": "offensive",
    "armor_penetration_percent": "offensive",
    "magic_penetration_percent": "offensive",
    "magic_penetration_flat": "offensive",
    "attack_speed_percent": "offensive",
    "health": "defensive",
    "armor": "defensive",
    "magic_resistance": "defensive",
    "tenacity": "defensive",
    "ability_haste": "utility",
    "movement_speed_flat": "utility",
    "movement_speed_percent": "utility",
    "life_steal_percent": "utility",
    "omnivamp_percent": "utility",
    "heal_and_shield_power_percent": "utility",
    "base_health_regeneration_percent": "utility",
    "base_mana_regeneration_percent": "utility",
}

BUCKETS: Final[tuple[str, ...]] = ("offensive", "defensive", "utility")

# ---------------------------------------------------------------------------
# 2. Saturación. S(x) = 1 / (1 + e^(-k(x - x0))) -> [0, 1].
#    x0 = 0.5 (equilibrio) y k = 6 (pendiente suave; sobre ~0.85 la ganancia
#    marginal es < 0.05, impidiendo que acumular inputs dispare los valores).
# ---------------------------------------------------------------------------
SATURATION_K: Final[float] = 6.0
SATURATION_X0: Final[float] = 0.5

# Las pasivas, como máximo, igualan al Base Stat Score (nunca lo duplican).
PASSIVE_CEILING: Final[float] = 1.0

# Rangos de salida homogéneos.
SYNERGY_MIN: Final[float] = 1.0
SYNERGY_MAX: Final[float] = 2.0
COUNTER_MAX: Final[float] = 1.0

# Fracción de presupuesto esperada como máximo razonable para un arquetipo
# monodireccional (un objeto de AD puro dedica ~60% de su oro a AD).
MAX_EXPECTED_SHARE: Final[float] = 0.6


def saturate(x: float, k: float = SATURATION_K, x0: float = SATURATION_X0) -> float:
    """Sigmoide logística reescalada a [0, 1]: S(x) = 1 / (1 + e^(-k(x - x0))).

    Monótona, acotada y con derivada máxima en x0. Ninguna acumulación de
    inputs puede superar 1.0 (anti-explosión).
    """
    return 1.0 / (1.0 + math.exp(-k * (x - x0)))


def clamp01(value: float) -> float:
    """Min-max clamp al rango [0, 1]."""
    return max(0.0, min(1.0, value))


def gold_value(stats: dict[str, Any]) -> dict[str, float]:
    """Convierte cada stat activa a oro con las paridades: {stat: oro}."""
    out: dict[str, float] = {}
    for key, raw in stats.items():
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        parity = GOLD_PARITY.get(key)
        if value > 0 and parity:
            out[key] = value * parity
    return out


def gold_budget_profile(stats: dict[str, Any]) -> dict[str, float]:
    """Perfil de presupuesto: % del oro en cada cubeta (suma = 1.0, o 0.0)."""
    gold = gold_value(stats)
    totals = {b: 0.0 for b in BUCKETS}
    for key, gold_amount in gold.items():
        totals[STAT_BUCKETS.get(key, "utility")] += gold_amount
    total = sum(totals.values())
    if total <= 0:
        return {b: 0.0 for b in BUCKETS}
    return {b: totals[b] / total for b in BUCKETS}


@dataclass
class SynergyScore:
    """Resultado tipado del cálculo para un objeto.

    - `synergy_multipliers`: escala pura en [1.0, 2.0] (1.0 = neutro).
    - `counter_weights`: intensidad de mecánica counter en [0.0, 1.0].
    - `gold_profile`: % de presupuesto por cubeta (trazabilidad/explicabilidad).
    """

    synergy_multipliers: dict[str, float] = field(default_factory=dict)
    counter_weights: dict[str, float] = field(default_factory=dict)
    gold_profile: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. Base Stat Score: claves de sinergia y su fracción de presupuesto.
# ---------------------------------------------------------------------------
# Cada clave de sinergia mapea a las stats activas que la alimentan.
SYNERGY_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "attack_damage": ("attack_damage",),
    "attack_power": ("ability_power",),
    "critic": ("critical_strike_chance_percent",),
    "lethality": ("lethality", "armor_penetration_percent"),
    "magic_pen": ("magic_penetration_percent", "magic_penetration_flat"),
    "mobility": ("movement_speed_flat", "movement_speed_percent"),
    "hypercarry": ("attack_speed_percent", "ability_haste"),
    "sustain": ("life_steal_percent", "omnivamp_percent", "base_health_regeneration_percent"),
    "durability": ("health", "armor", "magic_resistance"),
    "heal_shield_power": ("heal_and_shield_power_percent",),
    "wave_clear": (),  # mecánica puramente funcional (solo vía pasivas)
    "tankiness": ("tenacity",),
}


def base_stat_score(stats: dict[str, Any], key: str) -> float:
    """Base Stat Score para una clave de sinergia, en [0, 1].

    share  = (oro de las stats de la clave) / (oro total del objeto)
    input  = share / MAX_EXPECTED_SHARE   (normalizado a la concentración
             máxima razonable de un arquetipo monodireccional)
    output = S(input)                     (sigmoide, acotada en [0, 1])

    Justificación: dos objetos de distinto coste y rol reciben intensidades
    comparables porque lo que puntúa es el reparto del presupuesto, no la
    cantidad absoluta de oro. Un objeto de AD puro invierte ~60% de su oro en
    AD => input ~1.0 => intensidad saturada ~0.82. Un híbrido con 30% AD =>
    input 0.5 => 0.5. La sigmoide evita que un objeto con muchas stats
    simultáneas supere el techo.
    """
    keys = SYNERGY_KEYS.get(key, ())
    if not keys:
        return 0.0
    gold = gold_value(stats)
    total = sum(gold.values())
    if total <= 0:
        return 0.0
    gold_in_key = sum(gold.get(k, 0.0) for k in keys)
    if gold_in_key <= 0:
        return 0.0  # sin inversión real de oro: la clave no participa
    share = gold_in_key / total
    return saturate(share / MAX_EXPECTED_SHARE)


# ---------------------------------------------------------------------------
# 4. Contrapesos (counter weights): paridad de oro de las mecánicas anti-tanque
#    y saturación conjunta de penetraciones + mecánicas declaradas.
# ---------------------------------------------------------------------------
# Mecánicas counter declaradas (deterministas, no por subcadena difusa).
COUNTER_MECHANIC_WEIGHTS: Final[dict[str, tuple[tuple[str, ...], float]]] = {
    "Heavy_Armor": (("armor", "survivability_vs_armor"), 0.35),
    "Heavy_MR": (("magic_resistance", "survivability_vs_damage"), 0.35),
    "High_Health": (("survivability_vs_damage",), 0.35),
    "Shields": (("survivability_vs_damage",), 0.20),
    "Crowd_Control": (("survivability_overall",), 0.20),
}


def counter_weights_score(
    stats: dict[str, Any],
    counter_mechanics: list[str] | None = None,
) -> dict[str, float]:
    """Contrapesos en [0, 1] a partir de penetraciones y mecánicas counter.

    Las penetraciones aportan su fracción de oro (mismo modelo que las
    sinergias); las mecánicas declaradas aportan su peso fijo. Todo se
    combina de forma aditiva *antes* de la sigmoide, de modo que la suma
    queda acotada por saturación y no puede dispararse.
    """
    inputs: dict[str, float] = {}

    def add(keys: tuple[str, ...] | str, amount: float) -> None:
        if isinstance(keys, str):
            keys = (keys,)
        for k in keys:
            inputs[k] = inputs.get(k, 0.0) + amount

    # Penetraciones: fracción de oro relativa a MAX_EXPECTED_SHARE.
    gold = gold_value(stats)
    total = sum(gold.values())
    if total > 0:
        for pen_key, cw_keys in (
            ("lethality", ("armor", "survivability_vs_armor")),
            ("armor_penetration_percent", ("armor", "survivability_vs_armor")),
            ("magic_penetration_percent", ("magic_resistance", "survivability_vs_damage")),
            ("magic_penetration_flat", ("magic_resistance",)),
        ):
            share = gold.get(pen_key, 0.0) / total
            if share > 0:
                add(cw_keys, share / MAX_EXPECTED_SHARE)

    # Mecánicas counter declaradas (mapeo determinista).
    for mech in counter_mechanics or []:
        rule = COUNTER_MECHANIC_WEIGHTS.get(str(mech))
        if rule:
            add(rule[0], rule[1])

    return {k: round(saturate(v), 2) for k, v in inputs.items() if v > 0}


# ---------------------------------------------------------------------------
# 5. Passive Value Modifiers: reglas deterministas por nombre exacto de pasiva.
#
# Esquema de cada regla:
#   stat_bias   : arquetipo/cubeta hacia el que escala la pasiva
#                 (offensive | defensive | utility | hypercarry | wave_clear |
#                  mobility | sustain | anti_shield | anti_heal | counter...)
#   utility_tag : etiqueta mecánica explicativa (mobility, waveclear,
#                 anti_shield, anti_heal, spellblade, stasis, lifeline...)
#   weight      : intensidad base de la pasiva, 0.0 .. 1.0
#   counter_keys: claves de `counter_weights` a las que alimenta (opcional)
#   overlap_with: cubeta de stats que ya puntúa el mismo mecanismo (opcional).
#                 Si existe, el aporte se multiplica por (1 - overlap) para
#                 evitar el Double Dipping.
# ---------------------------------------------------------------------------
BUILTIN_PASSIVE_RULES: Final[dict[str, dict[str, Any]]] = {
    # --- Anti-tanque / counters ---
    "Giant Slayer": {"stat_bias": "counter", "utility_tag": "anti_health", "weight": 0.60,
                     "counter_keys": ["survivability_vs_damage"]},
    "Carve": {"stat_bias": "counter", "utility_tag": "armor_shred", "weight": 0.60,
              "counter_keys": ["armor", "survivability_vs_armor"]},
    "Dissolve": {"stat_bias": "counter", "utility_tag": "mr_shred", "weight": 0.60,
                 "counter_keys": ["magic_resistance", "survivability_vs_damage"]},
    "Torment": {"stat_bias": "counter", "utility_tag": "anti_health", "weight": 0.60,
                "counter_keys": ["survivability_vs_damage"]},
    "Azakana Gaze": {"stat_bias": "counter", "utility_tag": "anti_health", "weight": 0.60,
                     "counter_keys": ["survivability_vs_damage"]},
    "Bring It Down": {"stat_bias": "counter", "utility_tag": "anti_health", "weight": 0.50,
                      "counter_keys": ["survivability_vs_damage"]},
    # --- Offensivas ---
    "Magical Opus": {"stat_bias": "offensive", "utility_tag": "spellblade", "weight": 0.55},
    "Eminence": {"stat_bias": "offensive", "utility_tag": "spellblade", "weight": 0.55},
    "Spellblade": {"stat_bias": "offensive", "utility_tag": "spellblade", "weight": 0.55,
                   "dynamic": True},
    "Death and Taxes": {"stat_bias": "offensive", "utility_tag": "execute", "weight": 0.40},
    "Infinite Precision": {"stat_bias": "offensive", "utility_tag": "crit_scaling", "weight": 0.50},
    "Rebirth": {"stat_bias": "hypercarry", "utility_tag": "revive", "weight": 0.60},
    # --- Utilidad ---
    "Immolate": {"stat_bias": "wave_clear", "utility_tag": "waveclear", "weight": 0.45,
                 "overlap_with": "defensive"},
    "Cleave": {"stat_bias": "wave_clear", "utility_tag": "waveclear", "weight": 0.55},
    "Crescent": {"stat_bias": "wave_clear", "utility_tag": "waveclear", "weight": 0.55},
    "Echo": {"stat_bias": "wave_clear", "utility_tag": "waveclear", "weight": 0.45},
    "Cloudburst": {"stat_bias": "mobility", "utility_tag": "mobility", "weight": 0.45},
    "Supersonic": {"stat_bias": "mobility", "utility_tag": "mobility", "weight": 0.45},
    "Wraith Step": {"stat_bias": "mobility", "utility_tag": "mobility", "weight": 0.30},
    "Soulrend": {"stat_bias": "mobility", "utility_tag": "mobility", "weight": 0.30},
    "Stasis": {"stat_bias": "defensive", "utility_tag": "stasis", "weight": 0.60},
    "Quicksilver": {"stat_bias": "defensive", "utility_tag": "cc_cleanse", "weight": 0.50},
    "Purify": {"stat_bias": "defensive", "utility_tag": "cc_cleanse", "weight": 0.50},
    "Lifeline": {"stat_bias": "defensive", "utility_tag": "lifeline_shield", "weight": 0.55,
                 "overlap_with": "defensive"},
    "Consecration": {"stat_bias": "hypercarry", "utility_tag": "aura", "weight": 0.40},
    "Grievous Wounds": {"stat_bias": "counter", "utility_tag": "anti_heal", "weight": 0.50},
    "Shield Reaver": {"stat_bias": "counter", "utility_tag": "anti_shield", "weight": 0.50},
}


# Mapa: stat_bias -> claves de sinergia que recibe el aporte de la pasiva.
BIAS_TO_SYNERGY: Final[dict[str, str]] = {
    "offensive": "attack_damage",  # se resuelve dinámicamente AD/AP si procede
    "hypercarry": "hypercarry",
    "defensive": "durability",
    "mobility": "mobility",
    "wave_clear": "wave_clear",
    "sustain": "sustain",
}

# Cubeta usada para calcular el solapamiento (anti double dipping) según bias.
BIAS_OVERLAP_BUCKET: Final[dict[str, str]] = {
    "offensive": "offensive",
    "hypercarry": "offensive",
    "defensive": "defensive",
    "mobility": "utility",
    "wave_clear": "offensive",
    "sustain": "utility",
    "counter": "offensive",
}

# Umbral de solapamiento: si la cubeta ya concentra esta fracción de
# presupuesto, las pasivas del mismo mecanismo solo puntúan la diferencia
# funcional (mecanismo temporal/condicional), no la stat base ya contada.
OVERLAP_THRESHOLD: Final[float] = 0.25


def passive_modifier(
    rule: dict[str, Any],
    profile: dict[str, float],
    prefers_ad: bool,
) -> tuple[str, float]:
    """Valor ortogonal de una pasiva para una clave de sinergia.

    Devuelve (synergy_key, aporte en [0, PASSIVE_CEILING]).

    Double Dipping: si la cubeta asociada al stat_bias ya domina el
    presupuesto vía stats directas, el aporte se atenúa por el exceso:
        overlap = clamp01((profile[bucket] - TH) / (1 - TH))
        aporte *= (1 - overlap)
    Así, la vida de un escudo sobre un objeto tanque no vuelve a sumar sobre
    los HP ya puntuados; solo el mecanismo funcional añade la diferencia.
    """
    weight = clamp01(float(rule.get("weight", 0.0)))
    if weight <= 0:
        return "", 0.0

    bias = str(rule.get("stat_bias", "offensive"))

    # Spellblade/estilo dinámico: escala hacia la stat ofensiva dominante.
    if rule.get("dynamic") or bias == "offensive":
        synergy_key = "attack_damage" if prefers_ad else "attack_power"
    else:
        synergy_key = BIAS_TO_SYNERGY.get(bias, "")
    if not synergy_key:
        return "", 0.0

    value = weight
    bucket = BIAS_OVERLAP_BUCKET.get(bias, "")
    declared = rule.get("overlap_with")
    if declared:
        bucket = str(declared)
    if bucket:
        profile_share = float(profile.get(bucket, 0.0))
        if profile_share > OVERLAP_THRESHOLD:
            overlap = clamp01((profile_share - OVERLAP_THRESHOLD) / (1.0 - OVERLAP_THRESHOLD))
            value *= 1.0 - overlap

    return synergy_key, round(min(value, PASSIVE_CEILING), 2)


def resolve_passive_rule(
    rules: dict[str, dict[str, Any]],
    passive_name: str,
) -> dict[str, Any] | None:
    """Resolución determinista: solo coincidencia exacta (insensible a mayúsculas).

    Sin búsquedas por subcadena: evita falsos positivos.
    """
    return rules.get(str(passive_name).strip().casefold())


def compute_item_synergy(
    stats: dict[str, Any],
    passive_names: list[str] | None = None,
    counter_mechanics: list[str] | None = None,
    passive_rules: dict[str, dict[str, Any]] | None = None,
) -> SynergyScore:
    """Pipeline completo para un objeto.

    1. Perfil de oro (invariante al coste) -> Base Stat Score por clave.
    2. Passive Value Modifiers ortogonales (atenúan solapamientos).
    3. Combinación saturada: multiplier = 1 + S(bss + 0.5 * pasivas), en [1, 2].
    4. counter_weights saturados en [0, 1] (penetraciones + mecánicas + pasivas
       counter, todo saturado antes de devolver).

    Garantía de distribución justa: el input de la sigmoide es la *fracción de
    presupuesto* y los aportes de pasivas están acotados por PASSIVE_CEILING y
    atenuados por solapamiento: todos los objetos viven en [1.0, 2.0] sin
    importar su coste y la suma de pasivas converge (nunca diverge) al techo.
    """
    profile = gold_budget_profile(stats)

    # --- 1. Base Stat Score (solo stats directas) ---
    bss_inputs: dict[str, float] = {}
    for key in SYNERGY_KEYS:
        s = base_stat_score(stats, key)
        if s > 0.0:
            bss_inputs[key] = s

    # --- 2. Passive Value Modifiers (solo mecanismos funcionales) ---
    passive_inputs: dict[str, float] = {}
    rules = passive_rules or {
        name.casefold(): rule for name, rule in BUILTIN_PASSIVE_RULES.items()
    }
    ad = float(stats.get("attack_damage", 0) or 0)
    ap = float(stats.get("ability_power", 0) or 0)
    prefers_ad = ad >= ap
    for passive in passive_names or []:
        rule = resolve_passive_rule(rules, str(passive))
        if rule is None:
            continue
        key, value = passive_modifier(rule, profile, prefers_ad)
        if key and value > 0:
            passive_inputs[key] = passive_inputs.get(key, 0.0) + value

    # --- 3. Combinación saturada -> [1.0, 2.0] ---
    synergy_multipliers: dict[str, float] = {}
    for key in set(bss_inputs) | set(passive_inputs):
        bss = clamp01(bss_inputs.get(key, 0.0))
        pas = min(passive_inputs.get(key, 0.0), PASSIVE_CEILING)
        intensity = saturate(bss + 0.5 * pas)
        multiplier = round(SYNERGY_MIN + (SYNERGY_MAX - SYNERGY_MIN) * intensity, 2)
        if multiplier > SYNERGY_MIN:
            synergy_multipliers[key] = multiplier

    # --- 4. Contrapesos saturados -> [0.0, 1.0] ---
    weights = counter_weights_score(stats, counter_mechanics)
    for passive in passive_names or []:
        rule = resolve_passive_rule(rules, str(passive))
        if not rule:
            continue
        w = clamp01(float(rule.get("weight", 0.0)))
        for ck in rule.get("counter_keys", []) or []:
            current = weights.get(ck, 0.0)
            weights[ck] = saturate(current + w * 0.5)

    counter_weights = {k: round(v, 2) for k, v in weights.items() if v > 0}

    return SynergyScore(
        synergy_multipliers=synergy_multipliers,
        counter_weights=counter_weights,
        gold_profile={b: round(v, 4) for b, v in profile.items()},
    )

