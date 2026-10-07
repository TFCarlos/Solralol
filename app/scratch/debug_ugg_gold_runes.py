"""Depura el parseo de runas U.GG para Ahri mid en emerald."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService
from app.services.rangos_campeones import POR_CLAVE

svc = ChampionScraperService(rank="emerald")
print("rango Esmeralda:", POR_CLAVE["emerald"].ugg)
raw = svc._overview(103)
pd = svc._position_data(raw, "mid")
print("pd[0] =", json.dumps(pd[0]) if pd else None)
print("candidatos perk:")
for item in pd:
    for cand in svc._perk_candidates(item):
        print("  ", json.dumps(cand)[:160])
out = svc._parse_overview(raw, "mid")
for page in out.get("runes", []):
    print("PAGE:", json.dumps(page, ensure_ascii=False)[:300])
