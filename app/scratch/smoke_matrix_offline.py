"""Verifica que, con la matriz completa ya generada, la UI sirve TODO sin descargar.

Recorre todas las combinaciones rango x línea guardadas de un campeón y comprueba
que ninguna lanza un hilo de descarga (es decir, que la carga es 100% local).

Uso:  python app/scratch/smoke_matrix_offline.py <Campeón>
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.champion_variant_service import ChampionVariantService  # noqa: E402
from app.ui.local_analysis_dialog import LocalAnalysisDialog  # noqa: E402

champion = sys.argv[1] if len(sys.argv) > 1 else "Aatrox"
store = ChampionVariantService()
ranks = store.available_ranks(champion)
if not ranks:
    raise SystemExit(f"no hay matriz para {champion}; ejecuta antes build_matrix.py")

app = QApplication.instance() or QApplication([])
dialog = LocalAnalysisDialog()
failures: list[str] = []
downloads: list[str] = []

# El diálogo arranca con el primer campeón: hay que seleccionar el que se va a probar.
champion_index = dialog.champion_combo.findText(champion)
if champion_index < 0:
    raise SystemExit(f"'{champion}' no aparece en el selector")
if dialog.champion_combo.currentIndex() != champion_index:
    dialog.champion_combo.setCurrentIndex(champion_index)
    app.processEvents()
    time.sleep(0.3)

total_lanes = sum(len(store.available_lanes(champion, r)) for r in ranks)
print(
    f"{champion}: {len(ranks)} rangos, {total_lanes} combinaciones en {store.path_for(champion).name}"
)

started = time.time()
for rank in ranks:
    rank_index = dialog.analysis_rank_combo.findData(rank)
    if rank_index < 0:
        failures.append(f"{rank}: no esta en el combo de rango")
        continue
    dialog.analysis_rank_combo.setCurrentIndex(rank_index)
    for lane in store.available_lanes(champion, rank):
        lane_index = dialog.analysis_lane_combo.findData(lane)
        if lane_index < 0:
            failures.append(f"{rank}/{lane}: no esta en el combo de linea")
            continue
        dialog.analysis_lane_combo.setCurrentIndex(lane_index)
        # Se dan unos eventos al bucle: si hubiera descarga, el worker arrancaria.
        deadline = time.time() + 0.4
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.005)
        variant = dialog._active_variant
        stored = dialog._servicio_analisis.variantes.get(
            dialog.champion_combo.currentText(), lane, rank
        )
        if not isinstance(stored, dict):
            failures.append(f"{rank}/{lane}: el almacen de la UI no lo tiene")
            continue
        if not isinstance(variant, dict):
            failures.append(f"{rank}/{lane}: no se cargo ninguna variante")
            continue
        if variant.get("role") != lane or variant.get("rank") != rank:
            failures.append(
                f"{rank}/{lane}: variante={variant.get('role')}/{variant.get('rank')}"
            )
        if not variant.get("runes"):
            failures.append(f"{rank}/{lane}: sin runas")
        if (
            getattr(dialog, "_winrate_worker", None) is not None
            and dialog._winrate_worker.isRunning()
        ):
            downloads.append(f"{rank}/{lane}")

elapsed = time.time() - started
print(f"Recorridas {total_lanes} combinaciones en {elapsed:.1f}s")
print(f"Descargas lanzadas: {len(downloads)} {downloads[:5]}")
if downloads:
    failures.append(
        f"{len(downloads)} combinaciones encore descargaron: {downloads[:5]}"
    )

print("\nFALLOS:", failures if failures else "ninguno")
print("RESULTADO:", "OK" if not failures else "ERROR")
raise SystemExit(0 if not failures else 1)
