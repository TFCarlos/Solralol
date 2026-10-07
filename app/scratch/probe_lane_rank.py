"""Sonda: estructura U.GG por posición/rango y curva Lolalytics por tier."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import (
    ChampionScraperService,
)
from app.services.rangos_campeones import RANGOS_COMPATIBLES

CHAMP = sys.argv[1] if len(sys.argv) > 1 else "Aatrox"
LANES = sys.argv[2].split(",") if len(sys.argv) > 2 else ["top", "jungle"]

svc = ChampionScraperService(rank="emerald_plus")
cid = svc.champion_ids.get(CHAMP.casefold())
raw = svc._overview(cid)
region = raw.get("12", {}) if isinstance(raw, dict) else {}
print("buckets disponibles:", sorted(region.keys(), key=lambda k: int(k))[:20])
chain = {r.clave: (r.ugg,) for r in RANGOS_COMPATIBLES}["emerald_plus"]
print("cadena emerald_plus:", chain)
bucket_key = next((k for k in chain if k in region), None)
bucket = region.get(bucket_key) if bucket_key else None
print(
    "bucket usado:",
    bucket_key,
    "| posiciones:",
    sorted(bucket.keys()) if isinstance(bucket, dict) else None,
)

if isinstance(bucket, dict):
    for pos in ("4", "5", "1"):
        entry = bucket.get(pos)
        print(
            f"\n-- posición {pos}: entry tipo={type(entry).__name__} len={len(entry) if isinstance(entry, list) else '-'}"
        )
        if isinstance(entry, list):
            for i, part in enumerate(entry[:4]):
                head = part[:6] if isinstance(part, list) else part
                print(
                    f"   entry[{i}] tipo={type(part).__name__} head={json.dumps(head, ensure_ascii=False)[:220]}"
                )

print("\n=== candidatos de runas (U.GG) por rango y línea ===")
for rank in ("emerald_plus", "emerald"):
    s = ChampionScraperService(rank=rank)
    data = s._overview(cid)
    for lane in LANES:
        pd = s._position_data(data, lane)
        if not isinstance(pd, list):
            print(f"{rank:14s} {lane:7s} sin datos")
            continue
        cands = []
        for item in pd:
            cands.extend(s._perk_candidates(item))
        print(f"{rank:14s} {lane:7s} candidatos={len(cands)}")
        for cand in cands[:4]:
            perks = s._flat_perks(cand[4])
            print(
                f"    games={cand[0]} wins={cand[1]} pri={cand[2]} sec={cand[3]} perks={perks}"
            )

print("\n=== curva winrate vs duración (Lolalytics) por rango ===")
for rank in ("emerald_plus", "emerald"):
    s = ChampionScraperService(rank=rank)
    curve = s._scrape_winrate_vs_game_length("aatrox", "top")
    print(f"{rank:14s} ->", json.dumps(curve, ensure_ascii=False)[:400])
