"""Regresión: con datos reales en disco, la build sigue a la página de runas."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.champion_variant_service import ChampionVariantService  # noqa: E402
from app.ui.local_analysis_dialog import LocalAnalysisDialog  # noqa: E402

app = QApplication.instance() or QApplication([])
dialog = LocalAnalysisDialog()

store = ChampionVariantService()
name = "Aatrox"
variant = store.get(name, "top", "emerald_plus") or {}
print("variante en disco:", name, "->", list(variant.keys()))
print("páginas:", [(p.get("name"), p.get("keystone"), p.get("build")) for p in variant.get("runes", [])])

dialog._active_variant = variant
dialog._current_profile = dict(variant)
dialog._refresh_analysis(dict(variant))
print("\npáginas renderizadas:", len(dialog._rune_pages))
for index in range(max(1, len(dialog._rune_pages))):
    dialog._selected_rune_page = index
    print(f"  página {index + 1} -> build (fallback al perfil):", dialog._active_build(variant))

# Y con el perfil real completo (sin variante) para comprobar que no revienta.
dialog._active_variant = None
dialog._selected_rune_page = 0
dialog._select_champion(0)
app.processEvents()
print("\ntras _select_champion(0): páginas =", len(dialog._rune_pages),
      "| build =", dialog._active_build(dialog._current_profile)[:3])

