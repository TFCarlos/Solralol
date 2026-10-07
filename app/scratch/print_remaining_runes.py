"""Imprime runas de Sorcery y Resolve desde el mapa ddragon descargado."""
import json
from pathlib import Path

m = json.loads(Path(r"app/scratch/ddragon_runes_map.json").read_text(encoding="utf-8-sig"))
for tree in ("Sorcery", "Resolve"):
    rows = sorted((i, n, s) for i, n, t, s in m["runes"] if t == tree)
    print(tree + ":")
    for i, n, s in rows:
        print(f"  slot{s} {i} {n}")
