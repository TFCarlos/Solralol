"""Migración (v3): regenera matchups 5 counters / 5 ventajas con el modelo de la app.

Para cada campeón evalúa a todos los rivales de su mismo rol con
WinrateCalculatorService._calculate_head_to_head, inyectando las observaciones
reales almacenadas (winrate + partidas) como datos observados. Resultado:
counters = 5 peores winrates, good_against = 5 mejores, disjuntos por
construcción y coherentes con la metodología de la aplicación.
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from app.services.winrate_calculator_service import (
    WinrateCalculatorService,
    match_v5_positions,
    normalize_champion_key,
    roles_for_champion,
)

PATH = os.path.join("data", "champions_strict.json")
LIMIT = 5

with open(PATH, encoding="utf-8") as fh:
    champions = json.load(fh)

service = WinrateCalculatorService(api_key="")

# Clave normalizada, roles y posiciones por campeón
key_of: dict[str, str] = {}
roles_of: dict[str, set[str]] = {}
positions_of: dict[str, list[str]] = {}
for profile in champions:
    name = str(profile.get("character", ""))
    key_of[name] = normalize_champion_key(name)
    roles_of[name] = set(roles_for_champion(profile))
    positions_of[name] = match_v5_positions(roles_of[name])

# 1. Observaciones reales almacenadas -> observed_lane / observed_overall
observed_lane: dict[tuple[str, str, str], list[int]] = {}
observed_overall: dict[tuple[str, str], list[int]] = {}
for profile in champions:
    name = str(profile.get("character", ""))
    key = key_of[name]
    pos = positions_of[name][0] if positions_of[name] else "MIDDLE"
    matchups = profile.get("matchups") if isinstance(profile.get("matchups"), dict) else {}
    for group in ("counters", "good_against"):
        rows = matchups.get(group, []) if isinstance(matchups.get(group), list) else []
        for e in rows:
            if not isinstance(e, dict):
                continue
            opp = str(e.get("champion", "")).strip()
            if not opp or opp == name:
                continue
            wr = e.get("win_rate")
            if not isinstance(wr, (int, float)) or wr <= 0:
                continue
            opp_key = key_of.get(opp)
            if not opp_key:
                continue
            lg = int(e.get("lane_games", 0) or 0)
            og = int(e.get("overall_games", 0) or 0)
            if lg > 0:
                pair = (key, pos, opp_key)
                existing = observed_lane.get(pair)
                if existing is None or lg > existing[1]:
                    observed_lane[pair] = [round(wr * lg), lg]
            if og > 0:
                pair = (key, opp_key)
                existing = observed_overall.get(pair)
                if existing is None or og > existing[1]:
                    observed_overall[pair] = [round(wr * og), og]

print(f"Observaciones cargadas: lane={len(observed_lane)} overall={len(observed_overall)}")

# 2. Evaluar con el modelo y reasignar top 5 / bottom 5
updated = 0
for profile in champions:
    name = str(profile.get("character", ""))
    key = key_of[name]
    positions = positions_of[name] or ["MIDDLE"]
    primary_role = sorted(roles_of[name] or {"Mid"})[0]

    candidates = []
    for opp_profile in champions:
        opp_name = str(opp_profile.get("character", ""))
        if opp_name == name:
            continue
        if roles_of[name] & roles_of[opp_name]:
            candidates.append(opp_profile)
    if not candidates:
        candidates = [p for p in champions if str(p.get("character", "")) != name]

    evaluated = []
    for opp_profile in candidates:
        wr, owr, tip, lg, og = service._calculate_head_to_head(
            profile, opp_profile, key, positions, observed_lane, observed_overall,
        )
        evaluated.append({
            "champion": str(opp_profile.get("character", "")),
            "win_rate": wr,
            "overall_win_rate": owr,
            "lane_games": lg,
            "overall_games": og,
            "primary_role": primary_role,
            "tip": tip,
        })

    if not evaluated:
        continue
    evaluated.sort(key=lambda e: e["win_rate"])
    counters = evaluated[:LIMIT]
    good_against = evaluated[-LIMIT:][::-1]

    matchups = profile.get("matchups") if isinstance(profile.get("matchups"), dict) else {}
    new_matchups: dict = {}
    if isinstance(matchups.get("summary"), dict):
        new_matchups["summary"] = matchups["summary"]
    new_matchups["counters"] = counters
    new_matchups["good_against"] = good_against
    profile["matchups"] = new_matchups
    updated += 1

print(f"Perfiles actualizados: {updated}/{len(champions)}")
with open(PATH, "w", encoding="utf-8") as fh:
    json.dump(champions, fh, ensure_ascii=False, indent=2)
print("Guardado:", PATH)
