"""Inspección rápida de los matchups de un campeón tras la migración."""
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))

name = sys.argv[1] if len(sys.argv) > 1 else "Aatrox"
with open(os.path.join("data", "champions_strict.json"), encoding="utf-8") as fh:
    champions = json.load(fh)
p = next(x for x in champions if x.get("character") == name)
m = p["matchups"]
print(f"{name} · counters (peores):")
for e in m["counters"]:
    print(f"   {e['champion']:<16} {e['win_rate']:.1%} · {e['lane_games']} games · {e['tip'][:60]}")
print(f"{name} · good_against (mejores):")
for e in m["good_against"]:
    print(f"   {e['champion']:<16} {e['win_rate']:.1%} · {e['lane_games']} games · {e['tip'][:60]}")
