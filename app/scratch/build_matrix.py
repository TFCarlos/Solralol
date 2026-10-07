"""Genera y valida la matriz COMPLETA rango x línea de un campeón.

Descarga todas las combinaciones con muestra suficiente, las guarda en
`data/champion_data/<campeón>.json` y las relee desde disco para comprobar integridad.

Uso:  python app/scratch/build_matrix.py <Campeón>
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.champion_scraper_service import ChampionScraperService
from app.services.champion_variant_service import (
    LANE_STATS_KEY,
    ChampionVariantService,
)
from app.services.rangos_campeones import OPCIONES_RANGO

champion = sys.argv[1] if len(sys.argv) > 1 else "Aatrox"
svc = ChampionScraperService()  # request_delay por defecto: no satura las fuentes
champions = svc.repositorio.perfiles()
profile = next(
    (
        c
        for c in champions
        if str(c.get("character", "")).casefold() == champion.casefold()
    ),
    None,
)
if profile is None:
    raise SystemExit(f"campeon no encontrado: {champion}")

store = ChampionVariantService()


failures: list[str] = []
started = time.time()
seen: list[str] = []
matrix = svc.fetch_matrix(
    profile, progress_callback=lambda cur, tot, name: seen.append(f"{cur}/{tot} {name}")
)
elapsed = time.time() - started

combos = sum(
    len([k for k in block if k != LANE_STATS_KEY]) for block in matrix.values()
)
print(f"\n=== {champion} ===")
print(
    f"rangos: {len(matrix)}/{len(OPCIONES_RANGO)} | combinaciones: {combos} | tiempo: {elapsed:.0f}s"
)
print("progreso (ultimo):", seen[-1] if seen else "-")

from app.services.preparador_datos_campeon import PreparadorDatosCampeon

store.repositorio.guardar(
    champion,
    PreparadorDatosCampeon(svc.champions_path.parent).preparar(profile, matrix),
)
path = store.path_for(champion)
print(f"archivo: {path.name} ({path.stat().st_size / 1024:.0f} KB)")
print(
    f"estimado para {len(champions)} campeones: {path.stat().st_size / 1024 * len(champions) / 1024:.1f} MB"
)

fresh = ChampionVariantService()
total = 0
for rank, block in matrix.items():
    lanes = [k for k in block if k != LANE_STATS_KEY]
    total += len(lanes)
    print(f"  {rank:16s} {len(lanes)} linea(s) {lanes}")
    for lane in lanes:
        got = fresh.get(champion, lane, rank)
        if (
            not isinstance(got, dict)
            or got.get("role") != lane
            or got.get("rank") != rank
        ):
            failures.append(f"{rank}/{lane}: no relee del disco")
            continue
        for page in got.get("runes") or []:
            if (
                len(page.get("slots") or []) != 3
                or len(page.get("secondary_slots") or []) != 2
            ):
                failures.append(f"{rank}/{lane}: pagina de runas incompleta")
    if not fresh.lane_stats(champion, rank):
        failures.append(f"{rank}: lane_stats vacio")

if total != combos:
    failures.append("descuadre de combinaciones")
if combos == 0:
    failures.append("matriz vacia")

print("\nFALLOS:", failures if failures else "ninguno")
print("RESULTADO:", "OK" if not failures else "ERROR")
sys.exit(1 if failures else 0)
