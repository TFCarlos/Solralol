"""Sonda: grupos completos de 'builds' (U.GG) con nombres de runas."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService  # noqa: E402

svc = ChampionScraperService(rank="emerald_plus")
names = ChampionScraperService._PERK_NAMES
cid = svc.champion_ids.get("aatrox")
url = f"https://stats2.u.gg/lol/1.5/builds/16_17/ranked_solo_5x5/{cid}/1.5.0.json"
data = svc.session.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://u.gg/"}, timeout=20).json()
groups = data["12"]["17"]["4"][0]
print("grupos:", len(groups))
rows = []
for group in groups:
    keystone, sec_tree, wins, games, pri_tree, variants = group[:6]
    variants = variants if isinstance(variants, list) else []
    sum_a = sum(v[3] for v in variants if isinstance(v, list) and len(v) >= 5 and isinstance(v[3], int))
    sum_b = sum(v[4] for v in variants if isinstance(v, list) and len(v) >= 5 and isinstance(v[4], int))
    rows.append((games, keystone, sec_tree, wins, games, pri_tree, variants, sum_a, sum_b))

rows.sort(reverse=True, key=lambda r: r[0] if isinstance(r[0], (int, float)) else 0)
for _, keystone, sec_tree, wins, games, pri_tree, variants, sum_a, sum_b in rows:
    wr = wins / games if games else 0
    print(f"\nkeystone={keystone} {names.get(keystone, '?')} | pri={pri_tree} sec={sec_tree} wins={wins} games={games} wr={wr:.3f} | variantes={len(variants)} sum_a={sum_a} sum_b={sum_b}")
    for variant in variants[:3]:
        if isinstance(variant, list) and len(variant) >= 6:
            perks = variant[2] if isinstance(variant[2], list) else []
            print(f"   v: pri={variant[0]} sec={variant[1]} a={variant[3]} b={variant[4]} perks={perks}")
            print(f"      -> {[names.get(p, p) for p in perks]}")
