"""Validación de los matchups 5x5: disjunción, orden, cruce y tamaño."""
import json
import os
import sys

sys.path.insert(0, os.path.abspath("."))

with open(os.path.join("data", "champions_strict.json"), encoding="utf-8") as fh:
    champions = json.load(fh)

solapes = cruces = desordenes = cortos = 0
for p in champions:
    name = p.get("character", "?")
    m = p.get("matchups", {}) if isinstance(p.get("matchups"), dict) else {}
    cs = m.get("counters", [])
    gs = m.get("good_against", [])
    cn = [e["champion"] for e in cs if isinstance(e, dict)]
    gn = [e["champion"] for e in gs if isinstance(e, dict)]
    wc = [e["win_rate"] for e in cs if isinstance(e, dict)]
    wg = [e["win_rate"] for e in gs if isinstance(e, dict)]
    if set(cn) & set(gn):
        solapes += 1
        print("SOLAPE:", name, set(cn) & set(gn))
    if wc != sorted(wc) or wg != sorted(wg, reverse=True):
        desordenes += 1
        print("DESORDEN:", name)
    if wc and wg and max(wc) >= min(wg):
        cruces += 1
        print("CRUCE:", name, max(wc), min(wg))
    if len(cn) < 5 or len(gn) < 5:
        cortos += 1
        print(f"CORTO: {name} counters={len(cn)} good={len(gn)}")

print(f"perfiles: {len(champions)} · solapes: {solapes} · cruces: {cruces} · desordenes: {desordenes} · con menos de 5: {cortos}")
assert solapes == 0 and cruces == 0 and desordenes == 0 and cortos == 0, "Validación fallida"
print("VALIDACION OK")
