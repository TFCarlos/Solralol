"""Rellena las curvas win_rate_vs_game_length que faltan en champions_strict.json.

Usa el extractor corregido de Lolalytics (time/timeWin) para recuperar la
evolución temporal real de los campeones que no tienen curva guardada.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from app.services.champion_scraper_service import ChampionScraperService

PATH = Path("data/champions_strict.json")


def main() -> None:
    service = ChampionScraperService(request_delay=0.4)
    champions = json.loads(PATH.read_text(encoding="utf-8"))

    pending = [
        profile for profile in champions
        if not profile.get("win_rate_vs_game_length") and str(profile.get("character", "")).strip()
    ]
    print(f"Campeones sin curva temporal: {len(pending)}")

    updated = 0
    failed: list[str] = []
    for index, profile in enumerate(pending, 1):
        name = str(profile.get("character", "")).strip()
        role = service._role(profile)
        slug = service._slug(name)
        curve = service._scrape_winrate_vs_game_length(slug, role)
        if curve and len(curve) == 7:
            profile["win_rate_vs_game_length"] = curve
            updated += 1
            print(f"[{index}/{len(pending)}] {name} ({role}): " + ", ".join(f"{p['label']}={p['winrate']}" for p in curve))
        else:
            failed.append(name)
            print(f"[{index}/{len(pending)}] {name} ({role}): SIN DATOS")
        time.sleep(service.request_delay)

    PATH.write_text(json.dumps(champions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nCurvas añadidas: {updated}/{len(pending)}")
    if failed:
        print("Sin datos para:", ", ".join(failed))


if __name__ == "__main__":
    main()