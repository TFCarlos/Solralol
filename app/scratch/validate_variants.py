"""Valida `fetch_variant`: 2 páginas U.GG, winrate por línea y curva por rango."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService

CHAMP = sys.argv[1] if len(sys.argv) > 1 else "Aatrox"
CASES = [("emerald_plus", "top"), ("emerald_plus", "jungle"), ("diamond", "top")]

base_service = ChampionScraperService()
champions = base_service.repositorio.perfiles()
profile = next((entry for entry in champions if entry.get("character") == CHAMP), None)
if profile is None:
    raise SystemExit(f"no se encontró {CHAMP}")

failures: list[str] = []
for rank, lane in CASES:
    service = ChampionScraperService(rank=rank)
    data = service.fetch_variant(profile, lane)
    pages = data.get("runes") or []
    lanes = (data.get("lane_stats") or {}).get("lanes") or {}
    curve = data.get("win_rate_vs_game_length") or []
    print(f"\n=== {rank} / {lane} (updated={data.get('updated')})")
    for index, page in enumerate(pages, start=1):
        print(
            f"  Página {index}: {page.get('name')} [{page.get('source')}] "
            f"{page.get('primary_tree')}/{page.get('secondary_tree')} keystone={page.get('keystone')} "
            f"wr={page.get('win_rate')} games={page.get('games')} shards={page.get('shards')}"
        )
    print("  líneas:", {k: v.get("win_rate") for k, v in lanes.items()})
    print("  curva:", curve[:3])
    print(
        "  build:",
        (data.get("most_played_build") or [])[:4],
        "| spells:",
        data.get("summoner_spells"),
    )
    print(
        "  counters:",
        [
            c.get("champion")
            for c in ((data.get("matchups") or {}).get("counters") or [])
        ][:3],
    )

    # Si la línea no tiene muestra suficiente en ese rango, U.GG no publica
    # una segunda página: no es un fallo de la extracción.
    lane_games = ((data.get("lane_stats") or {}).get("lanes") or {}).get(lane, {})
    lane_sample = int(lane_games.get("games") or 0)
    if len(pages) < 2:
        if lane_sample >= 20:
            failures.append(
                f"{rank}/{lane}: solo {len(pages)} página(s) de runas con {lane_sample} partidas"
            )
        else:
            print(f"  (nota: línea con muestra mínima: {lane_sample} partidas)")
    elif not all(str(p.get("source")) == "U.GG" for p in pages[:2]):
        failures.append(
            f"{rank}/{lane}: fuentes {[p.get('source') for p in pages[:2]]}"
        )
    if len(lanes) < 3:
        failures.append(f"{rank}/{lane}: lane_stats insuficientes ({list(lanes)})")
    if not curve:
        failures.append(f"{rank}/{lane}: sin curva de duración")

print("\nRESULTADO:", "OK" if not failures else "FALLOS -> " + "; ".join(failures))
