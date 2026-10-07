"""Sonda: descriptor recursivo de la estructura de 'builds' de U.GG."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService  # noqa: E402

svc = ChampionScraperService(rank="emerald_plus")
cid = svc.champion_ids.get("aatrox")
url = f"https://stats2.u.gg/lol/1.5/builds/16_17/ranked_solo_5x5/{cid}/1.5.0.json"
data = svc.session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://u.gg/"}, timeout=20).json()
entry = data["12"]["17"]["4"]
print("entry len:", len(entry))


def describe(node, path="entry", depth=0, max_depth=4):
    pad = "  " * depth
    if isinstance(node, list):
        print(f"{pad}{path}: list[{len(node)}]")
        if depth >= max_depth:
            print(f"{pad}  ... (head={str(node[:6])[:160]})")
            return
        for i, child in enumerate(node[:4]):
            describe(child, f"{path}[{i}]", depth + 1, max_depth)
        if len(node) > 4:
            print(f"{pad}  ... +{len(node) - 4} más")
    elif isinstance(node, dict):
        print(f"{pad}{path}: dict[{len(node)}] keys={list(node)[:8]}")
    else:
        print(f"{pad}{path}: {type(node).__name__} = {str(node)[:80]}")


describe([entry[0]], "entry[0]", 0, 3)
