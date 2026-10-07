"""Smoke: actualizar un campeón real y comprobar build + skill_order por página de runas."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.champion_scraper_service import ChampionScraperService  # noqa: E402

RANK = "emerald_plus"
NAME = "Aatrox"

svc = ChampionScraperService(rank=RANK)
from app.services.repositorio_campeones import RepositorioCampeones

profiles = RepositorioCampeones().perfiles()
profile = next(p for p in profiles if str(p.get("character")) == NAME)
profile.setdefault("basic_info", {})["flex_potential"] = ["Top"]

changed = svc.update_champion(profile)
print("update_champion ->", changed)

print("\nskill_order:", json.dumps(profile.get("skill_order"), ensure_ascii=False))
print("most_played_build:", profile.get("most_played_build"))
for index, page in enumerate(profile.get("runes", []), 1):
    print(
        f"página {index} [{page.get('source')}] keystone={page.get('keystone')} "
        f"games={page.get('games')} build={page.get('build')} "
        f"skill={'sí' if page.get('skill_order') else 'no'}"
    )
