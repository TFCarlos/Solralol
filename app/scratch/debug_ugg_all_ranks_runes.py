"""Muestra pd[0] de todos los rank buckets de U.GG para Ahri mid, con árboles."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import (
    ChampionScraperService,
)
from app.services.rangos_campeones import RANGOS_COMPATIBLES

TREE = {
    8000: "Prec",
    8100: "Dom",
    8200: "Sor",
    8300: "Insp",
    8400: "Res",
}


def tree_of(perk: int) -> str:
    if 8000 <= perk < 8100:
        return "Prec"
    if 8100 <= perk < 8200:
        return "Dom"
    if 8200 <= perk < 8300:
        return "Sor"
    if 8300 <= perk < 8400:
        return "Insp"
    if 8400 <= perk < 8500:
        return "Res"
    return f"?{perk}"


svc = ChampionScraperService(rank="emerald_plus")
raw = svc._overview(103)
region = raw.get("12", {})
print("chains:")
for key in (rango.ugg for rango in RANGOS_COMPATIBLES):
    bucket = region[key]
    if not isinstance(bucket, dict):
        continue
    entry = bucket.get("5")
    pd = entry[0] if isinstance(entry, list) and entry else None
    if not isinstance(pd, list) or len(pd) < 5 or not isinstance(pd[0], list):
        continue
    blk = pd[0]
    if len(blk) < 5 or not isinstance(blk[4], list):
        print(key, "SIN BLOQUE RUNAS:", blk[:4])
        continue
    t1, t2 = TREE.get(blk[2], blk[2]), TREE.get(blk[3], blk[3])
    perks = blk[4]
    splits = [tree_of(p) for p in perks]
    print(f"key={key:>2} t1={t1:<4} t2={t2:<4} perks={perks} trees={splits}")
