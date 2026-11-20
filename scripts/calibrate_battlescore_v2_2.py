"""Fit and report BattleScore 2.2 against the sanitized local reference fixture.

The script is offline and read-only: it loads no Riot endpoints and writes
only the requested report file. Reference labels are never imported by the
production scoring engine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import battlescore_v2_2 as current
from backend import battlescore_v2_1 as previous

FAMILIES: dict[str, tuple[str, ...]] = {
    "kills": ("kill",),
    "assists": ("assist",),
    "economy": ("gold_per_1000", "experience_per_1000"),
    "damage": ("champion_damage_per_1000", "useful_damage_per_1000"),
    "objectives": (
        "epic_monster_damage_per_1000", "structure_damage_per_1000",
        "major_objective_secure", "major_objective_participation",
        "tower_destroyed", "structure_participation", "turret_plate", "objective_steal",
    ),
    "vision": ("ward_placed", "ward_destroyed", "final_vision_per_point"),
    "utility": ("allied_heal_shield_per_1000", "teamfight_participation", "first_blood", "shutdown"),
}
REGULARIZATION = .08


def _score(fixture: dict[str, Any], coefficients: dict[str, float]) -> list[dict[str, Any]]:
    current.COEFFICIENTS.clear()
    current.COEFFICIENTS.update(coefficients)
    result = current.calculate_match(
        "reference-fixture", fixture["participants"], fixture["events"], fixture["frames"],
        float(fixture["match_duration_seconds"]), fixture.get("calibration_baselines"),
    )
    return result.get("participants", [])


def _fit(fixture: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
    baseline = dict(previous.COEFFICIENTS)
    targets = {int(key): float(value) for key, value in fixture["targets"].items()}
    participant_ids = [int(item["participantId"]) for item in fixture["participants"]]

    def evaluate(scales: dict[str, float]) -> tuple[float, float, list[dict[str, Any]]]:
        coefficients = dict(baseline)
        for family, keys in FAMILIES.items():
            for key in keys:
                coefficients[key] *= scales[family]
        rows = _score(fixture, coefficients)
        by_id = {int(row["participantId"]): row for row in rows}
        errors = [float(by_id[pid]["finalScore"]) - targets[pid] for pid in participant_ids]
        mae = sum(abs(value) for value in errors) / len(errors)
        stability = sum((value - 1.0) ** 2 for value in scales.values()) / len(scales)
        return mae + REGULARIZATION * stability, mae, rows

    scales = {name: 1.0 for name in FAMILIES}
    coarse = [round(.15 + index * .05, 2) for index in range(18)] + [1.0]
    best = evaluate(scales)
    for _ in range(20):
        changed = False
        for family in FAMILIES:
            local_cost, local_value, local_result = best[0], scales[family], best
            for value in coarse:
                candidate = dict(scales)
                candidate[family] = value
                result = evaluate(candidate)
                if result[0] < local_cost - 1e-12:
                    local_cost, local_value, local_result = result[0], value, result
            if local_value != scales[family]:
                scales[family] = local_value
                best = local_result
                changed = True
        if not changed:
            break

    # Refine the bounded coarse optimum without adding new degrees of freedom.
    for _ in range(30):
        changed = False
        for family in FAMILIES:
            center = scales[family]
            choices = [max(.1, min(1.2, round(center + offset, 2)))
                       for offset in (-.05, -.03, -.02, -.01, 0, .01, .02, .03, .05)]
            choices = sorted(set(choices))
            local_cost, local_value, local_result = best[0], center, best
            for value in choices:
                candidate = dict(scales)
                candidate[family] = value
                result = evaluate(candidate)
                if result[0] < local_cost - 1e-12:
                    local_cost, local_value, local_result = result[0], value, result
            if local_value != center:
                scales[family] = local_value
                best = local_result
                changed = True
        if not changed:
            break

    fitted = dict(baseline)
    for family, keys in FAMILIES.items():
        for key in keys:
            fitted[key] *= scales[family]
    rows = _score(fixture, fitted)
    return scales, rows


def _metrics(rows: list[dict[str, Any]], fixture: dict[str, Any]) -> dict[str, Any]:
    targets = {int(key): float(value) for key, value in fixture["targets"].items()}
    by_id = {int(row["participantId"]): row for row in rows}
    errors = {pid: float(by_id[pid]["finalScore"]) - target for pid, target in targets.items()}
    n = len(errors)
    mae = sum(abs(value) for value in errors.values()) / n
    rmse = (sum(value * value for value in errors.values()) / n) ** .5
    order = sorted(targets, key=targets.get, reverse=True)
    predicted_order = sorted(targets, key=lambda pid: float(by_id[pid]["finalScore"]), reverse=True)
    rank = {pid: index for index, pid in enumerate(order)}
    predicted_rank = {pid: index for index, pid in enumerate(predicted_order)}
    squared_rank_distance = sum((rank[pid] - predicted_rank[pid]) ** 2 for pid in targets)
    spearman = 1.0 - (6.0 * squared_rank_distance / (n * (n * n - 1)))
    absolute = {pid: abs(value) for pid, value in errors.items()}
    by_role: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid, role = int(row["participantId"]), str(row.get("role") or "UNKNOWN")
        group = by_role.setdefault(role, {"participants": 0, "mae": 0.0, "rmse": 0.0})
        group["participants"] += 1
        group["mae"] += absolute[pid]
        group["rmse"] += errors[pid] ** 2
    for group in by_role.values():
        size = group["participants"]
        group["mae"] = round(group["mae"] / size, 4)
        group["rmse"] = round((group["rmse"] / size) ** .5, 4)
    return {
        "mae": round(mae, 4), "rmse": round(rmse, 4),
        "maximum_absolute_error": round(max(absolute.values()), 4),
        "spearman_rank_correlation": round(spearman, 4),
        "lower_cap_hits": sum(float(row["finalScore"]) <= current.MINIMUM_SCORE for row in rows),
        "upper_cap_hits": sum(float(row["finalScore"]) >= current.MAXIMUM_SCORE for row in rows),
        "per_role": by_role,
        "participants": [
            {
                "participantId": pid,
                "champion": by_id[pid].get("champion"),
                "role": by_id[pid].get("role"),
                "calculated": round(float(by_id[pid]["finalScore"]), 4),
                "previous_v2_1": round(float(by_id[pid].get("previousV2_1Score", 0.0)), 4),
                "change_from_v2_1": round(float(by_id[pid]["finalScore"]) - float(by_id[pid].get("previousV2_1Score", 0.0)), 4),
                "previous_v2_1_breakdown": by_id[pid].get("previousV2_1Breakdown"),
                "previous_v2_1_audit": by_id[pid].get("previousV2_1Audit"),
                "reference": targets[pid],
                "absolute_error": round(absolute[pid], 4),
                "audit": by_id[pid].get("audit"),
                "breakdown": by_id[pid].get("breakdown"),
                "context": by_id[pid].get("context"),
                "telemetry": by_id[pid].get("componentAvailability"),
                "estimated_allocations": by_id[pid].get("distributed", []),
            }
            for pid in sorted(targets)
        ],
    }


def build_report(fixture: dict[str, Any]) -> dict[str, Any]:
    source_coefficients = dict(previous.COEFFICIENTS)
    previous_rows = previous.calculate_match(
        "reference-fixture", fixture["participants"], fixture["events"], fixture["frames"],
        float(fixture["match_duration_seconds"]), fixture.get("calibration_baselines"),
    ).get("participants", [])
    scales, fitted_rows = _fit(fixture)
    default_coefficients = dict(current.COEFFICIENTS)
    try:
        current.COEFFICIENTS.clear()
        current.COEFFICIENTS.update(default_coefficients)
        current_rows = current.calculate_match(
            "reference-fixture", fixture["participants"], fixture["events"], fixture["frames"],
            float(fixture["match_duration_seconds"]), fixture.get("calibration_baselines"),
        ).get("participants", [])
    finally:
        current.COEFFICIENTS.clear()
        current.COEFFICIENTS.update(default_coefficients)
    # The committed configuration must be the deterministic constrained fit.
    actual = {int(row["participantId"]): float(row["finalScore"]) for row in current_rows}
    fitted = {int(row["participantId"]): float(row["finalScore"]) for row in fitted_rows}
    if any(abs(actual[pid] - fitted[pid]) > 1e-7 for pid in fitted):
        raise RuntimeError("La configuración activa no coincide con el ajuste reproducible.")
    old_by_id = {int(row["participantId"]): row for row in previous_rows}
    for row in fitted_rows:
        old = old_by_id[int(row["participantId"])]
        row["previousV2_1Score"] = old.get("finalScore")
        row["previousV2_1Breakdown"] = old.get("breakdown")
        row["previousV2_1Audit"] = old.get("audit")
    metrics = _metrics(fitted_rows, fixture)
    baseline_counts = {}
    for role, phases in (fixture.get("calibration_baselines", {}).get("metrics", {}) or {}).items():
        baseline_counts[role] = {
            phase: {metric: int(row.get("matches", 0)) for metric, row in values.items()}
            for phase, values in phases.items()
        }
    return {
        "version": current.VERSION,
        "reference_match": "EUW1_8016708982",
        "calibration_method": {
            "algorithm": "búsqueda coordenada determinista acotada, por familias de componentes",
            "families": FAMILIES,
            "family_multipliers": scales,
            "regularization": REGULARIZATION,
            "constraints": "factores entre 0.10 y 1.20 respecto de BattleScore 2.1; tabla de roles congelada; sin ajustes por campeón o participante",
            "target_population": "Una partida etiquetada, diez participantes; sobreajuste global no validado por esta sola muestra.",
        },
        "previous_coefficients_v2_1": source_coefficients,
        "final_coefficients_v2_2": dict(current.COEFFICIENTS),
        "role_multipliers": {key: dict(value) for key, value in current.ROLE_MULTIPLIERS.items()},
        "reference_baseline_sample_counts": baseline_counts,
        "decay": {
            "starts_at_ms": current.DECAY_START_MS,
            "normal_points_per_minute": current.DECAY_PER_MINUTE,
            "below_two_points_per_minute": current.PROTECTED_DECAY_PER_MINUTE,
            "initial_score": 5.0,
            "minimum": current.MINIMUM_SCORE,
            "maximum": current.MAXIMUM_SCORE,
            "recovery_bands": current.RECOVERY_BANDS,
        },
        "metrics": metrics,
        "limitations": [
            "Las etiquetas de referencia cubren una sola partida; no son evidencia suficiente de calibración global por rol.",
            "La validación local sin etiquetas mide distribución, no calidad independiente de rendimiento.",
            "La cobertura de daño útil sigue parcial donde Riot no proporciona daño recibido atribuible a campeones.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT / "docs/battlescore_v2_2_reference_fixture.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/battlescore_v2_2_calibration_report.json")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    report = build_report(fixture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"version": report["version"], "report": str(args.output), **report["metrics"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
