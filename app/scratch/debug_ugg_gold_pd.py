"""Depura qué pd devuelve U.GG para Ahri mid en distintos rangos."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService
from app.services.rangos_campeones import RANGOS_COMPATIBLES

svc = ChampionScraperService(rank="emerald")
raw = svc._overview(103)
region = raw.get("12", {}) if isinstance(raw, dict) else {}
print(
    "rank keys con datos:", sorted(k for k, v in region.items() if isinstance(v, dict))
)
for rank_key in (rango.ugg for rango in RANGOS_COMPATIBLES):
    bucket = region.get(rank_key)
    if not isinstance(bucket, dict):
        continue
    entry = bucket.get("5")
    pd = entry[0] if isinstance(entry, list) and entry else None
    print(
        f"\n--- rank_key={rank_key} pd_len={len(pd) if isinstance(pd, list) else None}"
    )
    if isinstance(pd, list):
        for i, v in enumerate(pd):
            s = json.dumps(v, ensure_ascii=False)[:180]
            print(f"  [{i}] {s}")
