"""Playstyles modulares para la puntuación de sinergias de objetos.

Define estilos de juego como datos declarativos:

* ``buffs``: coeficientes **positivos** que multiplican la afinidad de las
  estadísticas afines al estilo (ej. ``armor: +0.5`` → ×1.5).
* ``nerfs``: coeficientes **negativos** que penalizan estadísticas
  incompatibles (ej. ``attack_power: 1.2`` → resta afinidad y, además,
  penaliza al objeto según lo mucho que invierta en esa estadística).
* ``favored_classes`` / ``disfavored_classes``: clases de objeto afines o
  incompatibles con el rol.

Ponderación inteligente por escalados reales
--------------------------------------------
El sistema distingue entre escalados *principales* y *secundarios* del
campeón (``primary_attributes``):

1. Un escalado **principal** (top de atributos del perfil) recibe sus buffs y
   queda **exento** de los nerfs → Mordekaiser (AP principal) sigue pudiendo
   construir objetos AP con un playstyle de peleador.
2. Un escalado **secundario/residual** (ej. Ornn con ``attack_power: 6``)
   **no recibe buffs** y **sí recibe nerfs** → Eco de Luden cae al no ser
   viable en su rol.
3. Las clases ``disfavored`` solo penalizan si la estadística que las
   sustenta no es principal en el campeón.

Registro modular
----------------
``register_playstyle`` permite añadir nuevos playstyles (o aliases de las
claves legacy ``tank``/``burst_ap``/...) sin tocar el resto del código.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Playstyle",
    "NEUTRAL",
    "PLAYSTYLES",
    "register_playstyle",
    "resolve_playstyle",
    "primary_attributes",
    "item_emphasis",
    "canonical_stat",
    "stat_label",
    "DAMAGE_KEYS",
    "STAT_LABELS",
]

# ---------------------------------------------------------------------------
# Normalización de claves de estadística (objeto -> atributo del campeón)
# ---------------------------------------------------------------------------
STAT_ALIASES: dict[str, str] = {
    "ability_power": "attack_power",
    "attack_speed": "attack_speed",
    "attack_speed_percent": "attack_speed",
    "crit": "critic",
    "critical_strike_chance": "critic",
    "critical_strike_chance_percent": "critic",
    "magic_pen": "magic_pen",
    "magic_penetration_flat": "magic_pen",
    "magic_penetration_percent": "magic_pen",
    "armor_pen": "armor_pen",
    "armor_penetration_percent": "armor_pen",
    "health": "durability",
    "heal_and_shield_power_percent": "heal_shield_power",
    "life_steal_percent": "sustain",
    "omnivamp_percent": "sustain",
    "movement_speed_percent": "mobility",
}


def canonical_stat(key) -> str:
    """Devuelve la clave canónica de una estadística (objeto o campeón)."""
    name = str(key).strip().lower()
    return STAT_ALIASES.get(name, name)


# Escala de referencia de cada estadística de objeto para normalizarla a un
# énfasis comparable [0, 2.0] (1.0 ≈ un legendario medio dedicado a esa stat).
ITEM_STAT_SCALES: dict[str, float] = {
    "ability_power": 80.0,
    "attack_damage": 60.0,
    "attack_speed_percent": 40.0,
    "critical_strike_chance_percent": 25.0,
    "lethality": 20.0,
    "magic_penetration_flat": 20.0,
    "magic_penetration_percent": 20.0,
    "armor_penetration_percent": 20.0,
    "armor": 60.0,
    "magic_resistance": 60.0,
    "health": 400.0,
    "ability_haste": 30.0,
    "mana": 600.0,
    "movement_speed_percent": 6.0,
    "life_steal_percent": 10.0,
    "omnivamp_percent": 10.0,
    "heal_shield_power_percent": 20.0,
    "tenacity": 30.0,
}

# Estadísticas ofensivas: su buff solo aplica si el escalado es principal.
DAMAGE_KEYS: frozenset[str] = frozenset(
    {"attack_power", "attack_damage", "lethality", "critic",
     "attack_speed", "magic_pen", "armor_pen"}
)

# Clase de objeto -> escalados que la justifican (para gate de disfavor).
CLASS_SCALING: dict[str, tuple[str, ...]] = {
    "Mage": ("attack_power",),
    "Marksman": ("attack_damage", "critic", "attack_speed"),
    "Assassin": ("lethality", "attack_damage", "attack_power"),
    "Tank": ("durability", "armor", "magic_resistance"),
    "Warden": ("durability", "armor", "magic_resistance"),
    "Support": ("heal_shield_power", "utility"),
    "Enchanter": ("heal_shield_power", "utility"),
    "Fighter": ("attack_damage", "durability"),
    "Bruiser": ("attack_damage", "durability"),
    "Juggernaut": ("attack_damage", "durability"),
}

# Etiquetas legibles para los motivos mostrados en la interfaz.
STAT_LABELS: dict[str, str] = {
    "attack_power": "Poder de Habilidad (AP)",
    "attack_damage": "Daño de Ataque (AD)",
    "lethality": "Letalidad",
    "critic": "Probabilidad de Impacto Crítico",
    "attack_speed": "Velocidad de Ataque",
    "magic_pen": "Penetración Mágica",
    "armor_pen": "Penetración de Armadura",
    "armor": "Armadura",
    "magic_resistance": "Resistencia Mágica",
    "durability": "Vida / Durabilidad",
    "ability_haste": "Aceleración de Habilidad",
    "crowd_control": "Control de Masas",
    "utility": "Utilidad",
    "wave_clear": "Limpieza de Oleadas",
    "hypercarry": "Escala Hiper carry",
    "sustain": "Sostenimiento",
    "mobility": "Movilidad",
    "heal_shield_power": "Curación y Escudos",
    "mana": "Maná",
    "team_fight": "Peleas de Equipo",
    "objective_control": "Control de Objetivos",
    "survivability_vs_damage": "Supervivencia al Daño",
    "survivability_vs_armor": "Supervivencia a la Armadura",
    "survivability_vs_cc": "Supervivencia al Control",
}


def stat_label(key) -> str:
    """Etiqueta en español de una estadística canónica."""
    name = canonical_stat(key)
    return STAT_LABELS.get(name, name.replace("_", " "))


# ---------------------------------------------------------------------------
# Escalados principales del campeón
# ---------------------------------------------------------------------------
def primary_attributes(attributes: dict[str, float], top: int = 3,
                       ratio: float = 0.75) -> frozenset[str]:
    """Atributos *principales* del campeón (su identidad de escalado real).

    Un atributo es principal si supera a la 3ª cifra distinta más alta del
    perfil **y** alcanza al menos ``ratio`` (75 %) del máximo. Esto prioriza
    el rol principal y los escalados defensivos relevantes sobre escalados
    residuales (p. ej. el AP residual de Ornn: 6 frente a un máximo de 9).
    """
    positive = [value for value in attributes.values() if value > 0]
    if not positive:
        return frozenset()
    distinct = sorted(set(positive), reverse=True)
    cutoff = distinct[min(top, len(distinct)) - 1]
    floor = max(cutoff, ratio * max(positive))
    return frozenset(key for key, value in attributes.items() if value >= floor)


def item_emphasis(stats: dict | None, multipliers: dict | None) -> dict[str, float]:
    """Énfasis [0, 2.0] de un objeto por estadística, en clave canónica.

    Combina las stats crudas del objeto (normalizadas contra
    ``ITEM_STAT_SCALES``) con sus ``synergy_multipliers`` (ya vienen en una
    escala ~[1, 2]), conservando el mayor valor de ambos orígenes.
    """
    emphasis: dict[str, float] = {}

    def put(key, value) -> None:
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return
        if amount != amount:  # NaN
            return
        name = canonical_stat(key)
        amount = max(0.0, min(2.0, amount))
        if amount > emphasis.get(name, 0.0):
            emphasis[name] = amount

    for key, value in (multipliers or {}).items():
        put(key, value)
    for key, value in (stats or {}).items():
        scale = ITEM_STAT_SCALES.get(str(key).lower())
        if scale:
            put(key, float(value) / scale)
    return emphasis


# ---------------------------------------------------------------------------
# Playstyle
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Playstyle:
    """Definición declarativa de un estilo de juego.

    ``buffs`` y ``nerfs`` usan claves de atributo canónicas (ver
    ``STAT_ALIASES``). Los valores de ``nerfs`` son magnitudes >= 0 que se
    restan al coeficiente final (1 + buff − nerf).
    """

    key: str
    label: str
    favored_classes: frozenset[str]
    disfavored_classes: frozenset[str] = frozenset()
    buffs: dict[str, float] = field(default_factory=dict)
    nerfs: dict[str, float] = field(default_factory=dict)
    description: str = ""

    def buff_for(self, stat: str, primary: frozenset[str]) -> float:
        """Buff efectivo: las stats ofensivas solo buffean escalados principales."""
        value = self.buffs.get(stat, 0.0)
        if value and stat in DAMAGE_KEYS and stat not in primary:
            return 0.0
        return value

    def effective_nerfs(self, primary: frozenset[str]) -> dict[str, float]:
        """Nerfs vigentes: no aplican a escalados principales ni a stats con buff."""
        return {
            key: value
            for key, value in self.nerfs.items()
            if key not in primary and self.buffs.get(key, 0.0) <= 0.0
        }

    def effective_disfavored(self, intended: set[str],
                             primary: frozenset[str]) -> set[str]:
        """Clases incompatibles vigentes (gate por escalado real del campeón)."""
        return {
            cls for cls in (self.disfavored_classes & intended)
            if not any(scaling in primary for scaling in CLASS_SCALING.get(cls, ()))
        }


# Sin estilo conocido: se conserva el comportamiento histórico (sin buffs/nerfs).
NEUTRAL = Playstyle(
    key="neutral",
    label="Neutral",
    favored_classes=frozenset(),
    description="Sin playstyle definido; el servicio recurre a STYLE_CLASSES.",
)

_REGISTRY: dict[str, Playstyle] = {}


def register_playstyle(style: Playstyle, *aliases: str) -> Playstyle:
    """Registra (o sobrescribe) un playstyle y sus alias, indexado en minúsculas."""
    for name in (style.key, style.label, *aliases):
        _REGISTRY[str(name).strip().casefold()] = style
    return style


def resolve_playstyle(key: str | None) -> Playstyle:
    """Resuelve un playstyle por clave, etiqueta o alias legacy (``tank``, ...)."""
    if key is None:
        return NEUTRAL
    return _REGISTRY.get(str(key).strip().casefold(), NEUTRAL)


def _cs(*values: str) -> frozenset[str]:
    return frozenset(values)


# --- Vanguardia (tanque de engage) ----------------------------------------
register_playstyle(Playstyle(
    key="Vanguard",
    label="Vanguardia",
    favored_classes=_cs("Tank", "Vanguard", "Warden", "Juggernaut"),
    disfavored_classes=_cs("Mage", "Marksman", "Assassin"),
    buffs={
        "durability": 0.5, "tankiness": 0.5, "armor": 0.5,
        "magic_resistance": 0.5, "survivability_overall": 0.5,
        "survivability_vs_damage": 0.4, "survivability_vs_armor": 0.4,
        "survivability_vs_cc": 0.4, "crowd_control": 0.4,
        "ability_haste": 0.3, "utility": 0.3, "team_fight": 0.3,
        "objective_control": 0.2, "wave_clear": 0.1,
    },
    nerfs={
        "attack_power": 1.2, "attack_damage": 0.9, "lethality": 1.2,
        "critic": 1.2, "attack_speed": 0.9, "magic_pen": 1.2,
        "armor_pen": 0.8, "hypercarry": 0.6,
    },
    description="Tanque de engage: prioriza vida, resistencias y control; "
                "el daño AP/AD, el crítico y la velocidad de ataque son escalados residuales.",
), "vanguardia", "tank")

# --- Guardián (tanque protector) -------------------------------------------
register_playstyle(Playstyle(
    key="Warden",
    label="Guardián",
    favored_classes=_cs("Tank", "Warden", "Enchanter", "Support"),
    disfavored_classes=_cs("Marksman", "Assassin"),
    buffs={
        "durability": 0.5, "tankiness": 0.4, "armor": 0.4,
        "magic_resistance": 0.4, "survivability_overall": 0.4,
        "survivability_vs_damage": 0.3, "survivability_vs_cc": 0.4,
        "heal_shield_power": 0.6, "utility": 0.5, "ability_haste": 0.4,
        "crowd_control": 0.4, "team_fight": 0.3,
    },
    nerfs={
        "attack_power": 0.8, "attack_damage": 0.9, "lethality": 1.2,
        "critic": 1.0, "attack_speed": 0.7, "magic_pen": 1.0,
        "hypercarry": 0.6,
    },
    description="Protector: escudos, control y resistencias por delante del daño propio.",
), "guardian")

# --- Juggernaut (bruiser pesado) -------------------------------------------
register_playstyle(Playstyle(
    key="Juggernaut",
    label="Juggernaut",
    favored_classes=_cs("Fighter", "Juggernaut", "Bruiser", "Skirmisher"),
    disfavored_classes=_cs("Mage", "Marksman", "Assassin"),
    buffs={
        "attack_damage": 0.5, "durability": 0.4, "tankiness": 0.3,
        "armor": 0.3, "magic_resistance": 0.2, "sustain": 0.4,
        "crowd_control": 0.2, "lethality": 0.1, "attack_speed": 0.2,
    },
    nerfs={
        "attack_power": 1.2, "magic_pen": 1.2, "attack_speed": 0.3,
        "heal_shield_power": 0.8, "critic": 0.3,
    },
    description="Peleador pesado de una vía: daño físico y durabilidad; el AP es residual salvo escalado real.",
), "split_push")

# --- Bruiser ----------------------------------------------------------------
register_playstyle(Playstyle(
    key="Bruiser",
    label="Bruiser",
    favored_classes=_cs("Bruiser", "Fighter", "Juggernaut"),
    disfavored_classes=_cs("Mage", "Marksman", "Assassin"),
    buffs={
        "attack_damage": 0.4, "durability": 0.3, "sustain": 0.3,
        "armor": 0.2, "lethality": 0.2, "ability_haste": 0.2,
        "crowd_control": 0.2, "attack_speed": 0.2,
    },
    nerfs={
        "attack_power": 1.0, "magic_pen": 1.0, "critic": 0.3,
        "attack_speed": 0.2, "heal_shield_power": 0.8,
    },
    description="Daño físico con durabilidad intermedia.",
), "bruiser_ad", "bruiser_ap")

# --- Diver ------------------------------------------------------------------
register_playstyle(Playstyle(
    key="Diver",
    label="Diver",
    favored_classes=_cs("Diver", "Fighter", "Bruiser", "Skirmisher", "Juggernaut"),
    disfavored_classes=_cs("Mage", "Marksman", "Enchanter"),
    buffs={
        "attack_damage": 0.4, "durability": 0.3, "mobility": 0.4,
        "crowd_control": 0.3, "lethality": 0.3, "sustain": 0.2,
        "attack_speed": 0.2,
    },
    nerfs={
        "attack_power": 1.0, "magic_pen": 1.0, "critic": 0.4,
        "attack_speed": 0.2, "heal_shield_power": 0.8,
    },
    description="Entrada al objetivo con daño físico y algo de durabilidad.",
))

# --- Skirmisher / on-hit ----------------------------------------------------
register_playstyle(Playstyle(
    key="Skirmisher",
    label="Escaramuzador",
    favored_classes=_cs("Skirmisher", "Fighter", "Bruiser", "Marksman"),
    disfavored_classes=_cs("Mage", "Enchanter", "Support"),
    buffs={
        "attack_damage": 0.4, "attack_speed": 0.4, "critic": 0.5,
        "durability": 0.3, "sustain": 0.4, "mobility": 0.3,
    },
    nerfs={
        "attack_power": 1.0, "magic_pen": 1.0, "lethality": 0.6,
        "heal_shield_power": 0.8,
    },
    description="Duelo sostenido: velocidad de ataque, crítico y sustain.",
), "on_hit")

# --- Assassin ---------------------------------------------------------------
register_playstyle(Playstyle(
    key="Assassin",
    label="Asesino",
    favored_classes=_cs("Assassin", "Mage"),
    disfavored_classes=_cs("Tank", "Warden", "Enchanter", "Support"),
    buffs={
        "lethality": 0.6, "attack_damage": 0.4, "attack_power": 0.3,
        "mobility": 0.5, "armor_pen": 0.4, "wave_clear": 0.2,
        "magic_pen": 0.2,
    },
    nerfs={
        "durability": 0.4, "tankiness": 0.4, "heal_shield_power": 1.0,
        "critic": 0.3, "attack_speed": 0.2, "utility": 0.3,
    },
    description="Burst sobre un objetivo; la durabilidad es secundaria.",
), "assassin_ap", "assassin_lethality")

# --- Marksman ---------------------------------------------------------------
register_playstyle(Playstyle(
    key="Marksman",
    label="Tirador",
    favored_classes=_cs("Marksman", "Fighter", "Skirmisher"),
    disfavored_classes=_cs("Mage", "Tank", "Warden", "Enchanter", "Support"),
    buffs={
        "attack_damage": 0.5, "attack_speed": 0.6, "critic": 0.6,
        "hypercarry": 0.5, "mobility": 0.2, "lethality": 0.3,
        "sustain": 0.3, "armor_pen": 0.2,
    },
    nerfs={
        "attack_power": 1.0, "magic_pen": 1.0, "heal_shield_power": 0.8,
    },
    description="Daño básico sostenido: AD, velocidad de ataque y crítico.",
), "crit_ad", "poke_ad")

# --- Mage -------------------------------------------------------------------
register_playstyle(Playstyle(
    key="Mage",
    label="Mago",
    favored_classes=_cs("Mage", "Assassin"),
    disfavored_classes=_cs("Marksman", "Tank", "Warden"),
    buffs={
        "attack_power": 0.5, "magic_pen": 0.6, "ability_haste": 0.4,
        "wave_clear": 0.4, "mana": 0.2, "team_fight": 0.3,
        "mobility": 0.2, "hypercarry": 0.2,
    },
    nerfs={
        "attack_damage": 1.0, "lethality": 1.2, "critic": 1.0,
        "attack_speed": 0.8, "armor_pen": 1.0,
    },
    description="Daño mágico y aceleración; el AD/crítico/letalidad no encajan.",
), "burst_ap", "poke_ap")

# --- Enchanter --------------------------------------------------------------
register_playstyle(Playstyle(
    key="Enchanter",
    label="Encantador",
    favored_classes=_cs("Enchanter", "Support", "Warden"),
    disfavored_classes=_cs("Marksman", "Assassin", "Tank"),
    buffs={
        "heal_shield_power": 0.8, "utility": 0.6, "ability_haste": 0.5,
        "attack_power": 0.4, "crowd_control": 0.4, "mana": 0.2,
        "durability": 0.2, "mobility": 0.2,
    },
    nerfs={
        "attack_damage": 1.0, "lethality": 1.2, "critic": 1.0,
        "attack_speed": 0.5, "armor_pen": 1.0, "magic_pen": 0.5,
    },
    description="Potencia aliados: curación, escudos y utilidad.",
), "utility")

# Todos los playstyles registrados, en orden de definición (dedupe por id,
# ya que el dataclass contiene dicts y no es hasheable).
_UNIQUE: dict[int, Playstyle] = {}
for _style in _REGISTRY.values():
    _UNIQUE.setdefault(id(_style), _style)
PLAYSTYLES: tuple[Playstyle, ...] = tuple(_UNIQUE.values())
