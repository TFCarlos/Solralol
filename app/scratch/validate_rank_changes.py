"""Validación end-to-end de la selección de rango/elo en el scraper.

Para dos rangos distintos ejecuta update_champion() sobre una copia del perfil
de un campeón (sin escribir el JSON) y comprueba runas, ítems y matchups.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import (
    ChampionScraperService,
)
from app.services.rangos_campeones import OPCIONES_RANGO, RANGO_PREDETERMINADO

TARGET = sys.argv[1] if len(sys.argv) > 1 else "Ahri"
RANKS = (
    sys.argv[2].split(",") if len(sys.argv) > 2 else [RANGO_PREDETERMINADO, "diamond"]
)


def main() -> int:
    champions = ChampionScraperService().repositorio.perfiles()
    original = next((c for c in champions if c.get("character") == TARGET), None)
    if not original:
        print(f"Campeón no encontrado: {TARGET}")
        return 1

    valid_keys = dict(OPCIONES_RANGO)
    print(
        f"Campeón: {TARGET} | rangos válidos: {len(valid_keys)} | default: {RANGO_PREDETERMINADO}\n"
    )

    for rank in RANKS:
        assert rank in valid_keys, f"rank inválido: {rank}"
        profile = copy.deepcopy(original)
        service = ChampionScraperService(rank=rank)
        role = service._role(profile)
        ok = service.update_champion(profile)

        runes = profile.get("runes") or []
        page1 = runes[0] if runes else {}
        page2 = runes[1] if len(runes) > 1 else {}
        matchups = profile.get("matchups") or {}
        print(f"=== rank={rank} ({valid_keys[rank]}) rol={role} ok={ok}")
        print(
            f"  Página 1: {page1.get('name')} ({page1.get('source')}) keystone={page1.get('keystone')}"
        )
        print(
            f"  Página 2: {page2.get('name')} ({page2.get('source')}) keystone={page2.get('keystone')}"
        )
        print(
            f"  core={profile.get('power_curve_and_scaling', {}).get('power_spike_items')}"
        )
        print(f"  build={profile.get('most_played_build')}")
        print(
            f"  hechizos={profile.get('summoner_spells')} iniciales={profile.get('starter_items')}"
        )
        counters = matchups.get("counters") or []
        good = matchups.get("good_against") or []
        print(f"  counters={[c.get('champion') for c in counters]}")
        print(f"  good_against={[c.get('champion') for c in good]}")
        errors = []
        if not runes:
            errors.append("sin runas")
        if not profile.get("most_played_build"):
            errors.append("sin build")
        if not counters or not good:
            errors.append("sin matchups")
        if not profile.get("summoner_spells"):
            errors.append("sin hechizos")
        print(f"  -> {'OK' if not errors else 'FALLOS: ' + ', '.join(errors)}\n")
        if errors:
            return 1
    print("VALIDACIÓN OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
