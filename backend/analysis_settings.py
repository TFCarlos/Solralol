"""Persistent, validated settings for match analysis and BattleScore."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import threading
import time
from typing import Any

from app.services.storage_manager import atomic_write_json, get_storage_manager

SCHEMA_VERSION = 3
_LOCK = threading.RLock()
_LAST_LOAD_WARNING: str | None = None

SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "gold": {"source": "Riot Match-V5 Timeline", "fields": ["participantFrames.totalGold"], "method": "Incrementos positivos; la primera observación es baseline."},
    "experience": {"source": "Riot Match-V5 Timeline", "fields": ["participantFrames.xp"], "method": "Incrementos positivos; la primera observación es baseline."},
    "champion_damage": {"source": "Riot Match-V5 + Timeline", "fields": ["totalDamageDealtToChampions", "championDamageDealt"], "method": "Daño a campeones; agregado final si falta progresión temporal."},
    "useful_damage": {"source": "Eventos Match-V5 Timeline", "fields": ["victimDamageReceived"], "method": "Daño recibido de campeones observado en eventos de baja, ponderado por participación."},
    "objective_damage": {"source": "Riot Match-V5", "fields": ["damageDealtToEpicMonsters"], "method": "Total final distribuido como estimación temporal."},
    "structure_damage": {"source": "Riot Match-V5", "fields": ["damageDealtToBuildings", "damageDealtToTurrets"], "method": "Total final distribuido como estimación temporal."},
    "vision": {"source": "Eventos Match-V5 Timeline / Match-V5", "fields": ["WARD_PLACED", "WARD_KILL", "visionScore"], "method": "Eventos verificados; visionScore como alternativa final."},
    "allied_heal_shield": {"source": "Riot Match-V5", "fields": ["totalHealsOnTeammates", "totalDamageShieldedOnTeammates"], "method": "Totales finales distribuidos como estimación temporal."},
    "combat_events": {"source": "Riot Match-V5 Timeline", "fields": ["CHAMPION_KILL", "ELITE_MONSTER_KILL", "BUILDING_KILL", "TURRET_PLATE_DESTROYED"], "method": "Eventos atribuidos a participantes y con marca temporal."},
}


def _defaults() -> dict[str, Any]:
    # The one-time migration seeds the file from the currently effective engine.
    from backend import battlescore_engine as engine
    rewards = {key: value for key, value in engine.COEFFICIENTS.items() if key != "death"}
    enabled = {
        "gold": True, "experience": True, "kills": True, "assists": True, "champion_damage": True,
        "useful_damage": True, "objective_damage": True, "structure_damage": True, "vision": True,
        "death": True, "allied_heal_shield": True, "objective_secure": True, "objective_participation": True,
        "objective_steal": True, "tower": True, "structure_participation": True, "turret_plate": True,
        "first_blood": True, "shutdown": True, "teamfight_participation": True,
    }
    from backend.match_achievements import default_achievement_settings
    from backend.negative_achievements import default_settings as default_negative_achievement_settings
    return {
        "schema_version": SCHEMA_VERSION, "scoring_engine": "battlescore", "configuration_version": 1,
        "general": {"initial_score": 5.0, "minimum_score": engine.MINIMUM_SCORE, "maximum_score": engine.MAXIMUM_SCORE},
        "decay": {"normal_per_minute": engine.DECAY_PER_MINUTE, "grace_period_seconds": engine.DECAY_START_MS / 1000,
                  "grace_per_minute": 0.0, "low_score_threshold": engine.PROTECTION_THRESHOLD,
                  "below_threshold_per_minute": engine.PROTECTED_DECAY_PER_MINUTE},
        "recovery": {"below_3_threshold": 3.0, "below_3_bonus": engine.RECOVERY_BANDS[0][1],
                     "below_4_threshold": 4.0, "below_4_bonus": engine.RECOVERY_BANDS[1][1]},
        "compression": {"threshold": engine.DIMINISHING_THRESHOLD, "multiplier": engine.DIMINISHING_MULTIPLIER},
        "rewards": rewards, "enabled_components": enabled, "penalties": {"death": engine.COEFFICIENTS["death"]},
        "role_multipliers": deepcopy(engine.ROLE_MULTIPLIERS),
        "neutral_role_multipliers": deepcopy(engine.NEUTRAL_ROLE_MULTIPLIERS),
        "normalization": {"same_role_opponent_weight": engine.SAME_ROLE_OPPONENT_CONTEXT_WEIGHT,
                          "deviation_weight": engine.CONTEXT_DEVIATION_WEIGHT,
                          "max_downside_fraction": engine.CONTEXT_MAX_DOWNSIDE_FRACTION,
                          "phase_bounds_minutes": [10, 20], "minimum_reference_matches": 20},
        "visualization": {"sample_interval_ms": 30_000, "smoothing_intensity": 0.20},
        "analysis_limits": {"max_active_matches": 10},
        "achievements": default_achievement_settings(),
        "negative_achievements": default_negative_achievement_settings(),
        "telemetry_sources": deepcopy(SOURCE_REGISTRY),
    }


def config_path():
    return get_storage_manager().analysis_dir / "analysis_settings.json"


def _migrate_configuration(raw: Any) -> tuple[Any, bool]:
    """Upgrade persisted analysis settings without resetting user preferences."""
    if not isinstance(raw, dict) or raw.get("schema_version") not in {1, 2}:
        return raw, False
    migrated = deepcopy(raw)
    migrated["schema_version"] = SCHEMA_VERSION
    # In schemas 1 and 2 this achievement was unsupported and its disabled
    # state was forced by the registry. It is now verifiable from attributed
    # dragon takedown events, so enable it once during migration; later user
    # choices are preserved in schema 3.
    rules = migrated.get("negative_achievements", {}).get("rules", {})
    dragon_rule = rules.get("forgotten_dragons") if isinstance(rules, dict) else None
    if isinstance(dragon_rule, dict) and dragon_rule.get("enabled") is False:
        dragon_rule["enabled"] = True
    return migrated, True


def _canonical_hash(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _number(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"El campo {field} debe ser un número finito.")
    result = float(value)
    if minimum is not None and result < minimum or maximum is not None and result > maximum:
        raise ValueError(f"El campo {field} está fuera del rango permitido.")
    return result


def validate_configuration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or value.get("scoring_engine") != "battlescore":
        raise ValueError("La configuración de análisis tiene una versión o estructura incompatible.")
    defaults = _defaults()
    # Strict sections prevent arbitrary provider fields and executable settings.
    if set(value) != set(defaults):
        raise ValueError("La estructura de la configuración de análisis no coincide con el esquema admitido.")
    result = deepcopy(value)
    for section in ("general", "decay", "recovery", "compression", "rewards", "penalties", "normalization", "visualization"):
        if not isinstance(result.get(section), dict) or set(result[section]) != set(defaults[section]):
            raise ValueError(f"La sección {section} está incompleta o contiene campos no admitidos.")
    for section, fields in (("general", {"initial_score": (0.1, 10), "minimum_score": (0.1, 10), "maximum_score": (0.2, 10)}),
                            ("decay", {"normal_per_minute": (0, 5), "grace_period_seconds": (0, 600), "grace_per_minute": (0, 5), "low_score_threshold": (0.1, 9.9), "below_threshold_per_minute": (0, 5)}),
                            ("recovery", {"below_3_threshold": (0.1, 9.9), "below_3_bonus": (0, 2),
                                          "below_4_threshold": (0.2, 10), "below_4_bonus": (0, 2)}),
                            ("compression", {"threshold": (0.1, 10), "multiplier": (0, 1)}),
                            ("normalization", {"same_role_opponent_weight": (0, 1), "deviation_weight": (0, 2), "max_downside_fraction": (0, 1)}),
                            ("visualization", {"sample_interval_ms": (1000, 300000), "smoothing_intensity": (0, 0.8)})):
        for key, (minimum, maximum) in fields.items():
            result[section][key] = _number(result[section][key], f"{section}.{key}", minimum=minimum, maximum=maximum)
    if not isinstance(result["normalization"]["minimum_reference_matches"], int) or isinstance(result["normalization"]["minimum_reference_matches"], bool) or not 1 <= result["normalization"]["minimum_reference_matches"] <= 500:
        raise ValueError("El mínimo de partidas de referencia debe ser un entero entre 1 y 500.")
    phase_bounds = result["normalization"]["phase_bounds_minutes"]
    if not isinstance(phase_bounds, list) or len(phase_bounds) != 2:
        raise ValueError("Los límites de fase deben contener dos minutos crecientes.")
    phase_bounds = [_number(item, "normalization.phase_bounds_minutes", minimum=1, maximum=60) for item in phase_bounds]
    if phase_bounds[0] >= phase_bounds[1]:
        raise ValueError("El límite final de fase debe ser posterior al inicial.")
    result["normalization"]["phase_bounds_minutes"] = phase_bounds
    if result["general"]["minimum_score"] >= result["general"]["maximum_score"]:
        raise ValueError("La puntuación mínima debe ser inferior a la máxima.")
    if not result["general"]["minimum_score"] <= result["general"]["initial_score"] <= result["general"]["maximum_score"]:
        raise ValueError("La puntuación inicial debe estar entre los límites mínimo y máximo.")
    if result["compression"]["threshold"] > result["general"]["maximum_score"]:
        raise ValueError("El umbral de compresión no puede superar la puntuación máxima.")
    if result["recovery"]["below_3_threshold"] >= result["recovery"]["below_4_threshold"]:
        raise ValueError("El segundo umbral de recuperación debe ser superior al primero.")
    for section in ("rewards", "penalties"):
        if set(result[section]) != set(defaults[section]):
            raise ValueError(f"La sección {section} contiene coeficientes no admitidos.")
        for key, current in result[section].items():
            result[section][key] = _number(current, f"{section}.{key}", minimum=0)
    if set(result["enabled_components"]) != set(defaults["enabled_components"]) or any(type(v) is not bool for v in result["enabled_components"].values()):
        raise ValueError("La lista de componentes habilitados no es válida.")
    if set(result["role_multipliers"]) != set(defaults["role_multipliers"]):
        raise ValueError("Falta una posición o hay una posición no admitida.")
    for role, multipliers in result["role_multipliers"].items():
        if not isinstance(multipliers, dict) or set(multipliers) != set(defaults["role_multipliers"][role]):
            raise ValueError(f"La tabla de multiplicadores de {role} no es válida.")
        for key, multiplier in multipliers.items():
            multipliers[key] = _number(multiplier, f"role_multipliers.{role}.{key}", minimum=0, maximum=5)
    if set(result["neutral_role_multipliers"]) != set(defaults["neutral_role_multipliers"]):
        raise ValueError("El fallback neutral de rol no es válido.")
    for key, multiplier in result["neutral_role_multipliers"].items():
        result["neutral_role_multipliers"][key] = _number(multiplier, f"neutral_role_multipliers.{key}", minimum=0, maximum=5)
    limits = result["analysis_limits"]
    if not isinstance(limits, dict) or set(limits) != {"max_active_matches"}:
        raise ValueError("La configuración del límite de análisis no es válida.")
    limit = limits["max_active_matches"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("El máximo de análisis activos debe ser un entero entre 1 y 100.")
    if result["telemetry_sources"] != SOURCE_REGISTRY:
        raise ValueError("Las fuentes de telemetría están fijadas al registro seguro compatible.")
    from backend.match_achievements import ACHIEVEMENT_REGISTRY
    achievements = result.get("achievements")
    if not isinstance(achievements, dict) or set(achievements) != {"show_unearned", "thresholds"} or type(achievements.get("show_unearned")) is not bool:
        raise ValueError("La configuración de logros de partida no es válida.")
    thresholds = achievements.get("thresholds")
    expected_ids = {item["id"] for item in ACHIEVEMENT_REGISTRY}
    if not isinstance(thresholds, dict) or set(thresholds) != expected_ids:
        raise ValueError("Faltan umbrales o hay logros desconocidos en la configuración.")
    definitions = {item["id"]: item for item in ACHIEVEMENT_REGISTRY}
    for achievement_id, medal_values in thresholds.items():
        if not isinstance(medal_values, dict) or set(medal_values) != {"bronze", "silver", "gold", "diamond"}:
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} están incompletos.")
        values = [_number(medal_values[key], f"achievements.thresholds.{achievement_id}.{key}", minimum=0, maximum=1_000_000_000) for key in ("bronze", "silver", "gold", "diamond")]
        if not definitions[achievement_id].get("decimal") and any(not value.is_integer() for value in values):
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} deben ser enteros.")
        ascending = values == sorted(values)
        descending = values == sorted(values, reverse=True)
        if definitions[achievement_id]["direction"] == "lower" and not descending:
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} deben ir de mayor a menor.")
        if definitions[achievement_id]["direction"] == "higher" and not ascending:
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} deben ir de menor a mayor.")
        achievements["thresholds"][achievement_id] = dict(zip(("bronze", "silver", "gold", "diamond"), values))
    from backend.negative_achievements import DEFINITIONS as NEGATIVE_DEFINITIONS, ROLES as NEGATIVE_ROLES, SEVERITIES
    negative = result.get("negative_achievements")
    negative_defaults = defaults["negative_achievements"]
    if not isinstance(negative, dict) or set(negative) != set(negative_defaults):
        raise ValueError("La configuraciÃ³n de oportunidades de mejora no es vÃ¡lida.")
    if type(negative.get("enabled")) is not bool or type(negative.get("show_mild")) is not bool or type(negative.get("role_aware")) is not bool:
        raise ValueError("Las opciones de visibilidad de oportunidades de mejora no son vÃ¡lidas.")
    for field, low, high in (("early_game_window_minutes", 3, 20), ("opponent_checkpoint_minutes", 5, 20)):
        number = _number(negative[field], f"negative_achievements.{field}", minimum=low, maximum=high)
        if not number.is_integer():
            raise ValueError(f"El campo negative_achievements.{field} debe ser un minuto entero.")
        negative[field] = int(number)
    rules = negative.get("rules")
    expected_negative_ids = {item["id"] for item in NEGATIVE_DEFINITIONS}
    if not isinstance(rules, dict) or set(rules) != expected_negative_ids:
        raise ValueError("Faltan reglas de oportunidades de mejora o hay identificadores desconocidos.")
    definitions = {item["id"]: item for item in NEGATIVE_DEFINITIONS}
    for achievement_id, rule in rules.items():
        if not isinstance(rule, dict) or set(rule) != {"enabled", "roles", "min_duration_minutes", "thresholds", "role_factors"}:
            raise ValueError(f"La regla {definitions[achievement_id]['name']} estÃ¡ incompleta.")
        if type(rule["enabled"]) is not bool or not isinstance(rule["roles"], list) or not rule["roles"] or any(role not in NEGATIVE_ROLES for role in rule["roles"]):
            raise ValueError(f"La elegibilidad por rol de {definitions[achievement_id]['name']} no es vÃ¡lida.")
        if not definitions[achievement_id].get("supported", True) and rule["enabled"]:
            raise ValueError(f"{definitions[achievement_id]['name']} no puede activarse: la telemetrÃ­a actual no lo atribuye de forma fiable.")
        if len(set(rule["roles"])) != len(rule["roles"]):
            raise ValueError(f"La lista de roles de {definitions[achievement_id]['name']} contiene duplicados.")
        rule["min_duration_minutes"] = _number(rule["min_duration_minutes"], f"negative_achievements.rules.{achievement_id}.min_duration_minutes", minimum=0, maximum=120)
        values = rule["thresholds"]
        if not isinstance(values, dict) or set(values) != set(SEVERITIES):
            raise ValueError(f"Los niveles de gravedad de {definitions[achievement_id]['name']} estÃ¡n incompletos.")
        thresholds_ordered = [_number(values[level], f"negative_achievements.rules.{achievement_id}.{level}", minimum=0, maximum=1_000_000_000) for level in SEVERITIES]
        if definitions[achievement_id]["direction"] == "lower" and thresholds_ordered != sorted(thresholds_ordered, reverse=True):
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} deben disminuir al aumentar la gravedad.")
        if definitions[achievement_id]["direction"] == "higher" and thresholds_ordered != sorted(thresholds_ordered):
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} deben aumentar al aumentar la gravedad.")
        if definitions[achievement_id].get("integer") and any(not value.is_integer() for value in thresholds_ordered):
            raise ValueError(f"Los umbrales de {definitions[achievement_id]['name']} deben ser enteros.")
        rule["thresholds"] = dict(zip(SEVERITIES, thresholds_ordered))
        factors = rule["role_factors"]
        if not isinstance(factors, dict) or set(factors) != set(NEGATIVE_ROLES):
            raise ValueError(f"Los factores por rol de {definitions[achievement_id]['name']} no son vÃ¡lidos.")
        rule["role_factors"] = {role: _number(factors[role], f"negative_achievements.rules.{achievement_id}.role_factors.{role}", minimum=0.1, maximum=3) for role in NEGATIVE_ROLES}
    if isinstance(result["configuration_version"], bool) or not isinstance(result["configuration_version"], int) or result["configuration_version"] < 1:
        raise ValueError("La revisión de configuración no es válida.")
    return result


def load_configuration() -> dict[str, Any]:
    global _LAST_LOAD_WARNING
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw, migrated = _migrate_configuration(raw)
            if isinstance(raw, dict) and raw.get("schema_version") == SCHEMA_VERSION:
                if "achievements" not in raw:
                    raw["achievements"] = _defaults()["achievements"]
                    migrated = True
                if "negative_achievements" not in raw:
                    raw["negative_achievements"] = _defaults()["negative_achievements"]
                    migrated = True
            config = validate_configuration(raw)
            if migrated:
                atomic_write_json(path.with_suffix(path.suffix + ".bak"), config)
                atomic_write_json(path, config)
            _LAST_LOAD_WARNING = None
        except FileNotFoundError:
            config = _defaults()
            atomic_write_json(path, config)
            _LAST_LOAD_WARNING = None
        except (OSError, ValueError, TypeError) as error:
            backup = path.with_suffix(path.suffix + ".bak")
            try:
                backup_raw, _ = _migrate_configuration(json.loads(backup.read_text(encoding="utf-8")))
                config = validate_configuration(backup_raw)
                if path.exists():
                    try:
                        path.replace(path.with_suffix(path.suffix + f".corrupt.{time.time_ns()}"))
                    except OSError:
                        pass
                atomic_write_json(path, config)
                _LAST_LOAD_WARNING = "El archivo de análisis estaba dañado; se recuperó la copia de seguridad válida."
            except (OSError, ValueError, TypeError):
                # Keep the damaged file for diagnosis/recovery, but allow startup
                # using known engine defaults and persist those defaults safely.
                if path.exists():
                    try:
                        path.replace(path.with_suffix(path.suffix + f".corrupt.{time.time_ns()}"))
                    except OSError:
                        pass
                config = _defaults()
                atomic_write_json(path, config)
                _LAST_LOAD_WARNING = "La configuración de análisis y su copia no eran válidas; se restauraron los valores predeterminados y se preservó el archivo dañado."
        config["configuration_hash"] = _canonical_hash({k: v for k, v in config.items() if k != "configuration_hash"})
        return config


def save_configuration(value: Any) -> dict[str, Any]:
    global _LAST_LOAD_WARNING
    if isinstance(value, dict):
        value = {key: item for key, item in value.items() if key != "configuration_hash"}
    validated = validate_configuration(value)
    path = config_path()
    with _LOCK:
        try:
            old = load_configuration()
            old.pop("configuration_hash", None)
            validated["configuration_version"] = int(old.get("configuration_version", 0)) + 1
            atomic_write_json(path.with_suffix(path.suffix + ".bak"), old)
        except (FileNotFoundError, ValueError):
            validated["configuration_version"] = max(1, validated["configuration_version"])
        atomic_write_json(path, validated)
        _LAST_LOAD_WARNING = None
    return load_configuration()


def engine_snapshot(value: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict) and "coefficients" in value and "configuration_hash" in value:
        return deepcopy(value)
    config = validate_configuration({k: v for k, v in (value or load_configuration()).items() if k != "configuration_hash"})
    # Recompute from the validated snapshot. A renderer draft may carry the
    # previous hash while its fields are being edited.
    scoring_config = {key: value for key, value in config.items() if key not in {"configuration_version", "achievements", "negative_achievements", "analysis_limits"}}
    config_hash = _canonical_hash(scoring_config)
    return {
        "version": config["configuration_version"], "configuration_hash": config_hash,
        "general": config["general"], "decay": config["decay"], "recovery": config["recovery"],
        "compression": config["compression"], "coefficients": {**config["rewards"], **config["penalties"]},
        "enabled_components": config["enabled_components"], "role_multipliers": config["role_multipliers"],
        "neutral_role_multipliers": config["neutral_role_multipliers"], "normalization": config["normalization"],
        "visualization": config["visualization"], "telemetry_sources": config["telemetry_sources"],
        "analysis_limits": config["analysis_limits"],
    }


def public_configuration(value: dict[str, Any] | None = None) -> dict[str, Any]:
    config = deepcopy(value or load_configuration())
    config["configuration_hash"] = _canonical_hash({k: v for k, v in config.items() if k != "configuration_hash"})
    return config


def default_configuration() -> dict[str, Any]:
    """Return a fresh validated copy of the currently shipped defaults."""
    config = _defaults()
    config["configuration_hash"] = _canonical_hash(config)
    return config


def configuration_load_warning() -> str | None:
    return _LAST_LOAD_WARNING
