"""Smoke test: sinergias sin duplicados y renderizado del nuevo BarWidget."""
import os
import sys

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.synergy_recommendation_service import SynergyRecommendationService
from app.ui.local_analysis_dialog import BarWidget, LocalAnalysisDialog

app = QApplication.instance() or QApplication([])

# 1. El servicio deduplica por nombre aunque lleguen IDs distintos (ES/EN).
service = SynergyRecommendationService()
profile = {
    "combat_attributes": {"attack_damage": 60},
    "situational_items": {"anti_tank": ["Malla de espinas"]},
}
items = {
    "3075": {"name": "Malla de espinas", "tier": "Legendary", "intended_classes": ["Tank"],
             "stats": {"armor": 5}, "synergy_multipliers": {"armor": 0.5}},
    "9999": {"name": "Thornmail", "tier": "Legendary", "intended_classes": ["Tank"],
             "stats": {"armor": 5}, "synergy_multipliers": {"armor": 0.3}},
    "3068": {"name": "Égida de fuego solar", "tier": "Legendary", "intended_classes": ["Tank"]},
    "6630": {"name": "Sunfire Aegis", "tier": "Legendary", "intended_classes": ["Tank"]},
}
ranked = service.rank_items(profile, "tank", items, [], 30)
names = [service._normalise_item_name(r.name) for r in ranked]
assert len(names) == len(set(names)), f"Duplicados en rank_items: {names}"
malla = [r for r in ranked if service._normalise_item_name(r.name) == "malla de espinas"]
assert len(malla) == 1 and malla[0].item_id == "3075" and malla[0].score >= 13.0, malla
egida = [r for r in ranked if r.item_id == "6630"]
assert not egida, "Sunfire Aegis debería fusionarse con Égida de fuego solar"
print("OK 1 · rank_items sin duplicados:", [(r.item_id, r.name, r.score) for r in ranked])

# 2. El catálogo del diálogo no repite nombres con IDs distintos.
dialog = LocalAnalysisDialog()
by_id = dialog._recommendation_items_by_id()
norm_names = [dialog._normalise_item_name(str(v.get("basic_info", {}).get("name", v.get("item", "")))) for v in by_id.values()]
dupes = sorted({n for n in norm_names if norm_names.count(n) > 1})
assert not dupes, f"Duplicados en _recommendation_items_by_id: {dupes}"
print(f"OK 2 · catálogo sin duplicados ({len(by_id)} objetos)")

# 3. BarWidget pinta sin errores y ajusta su altura al número de filas.
bar = BarWidget()
bar.item_catalog = dialog._catalog_items().get("items", {})
rows = [(r.name, r.score, r.item_id) for r in ranked[:8]]
bar.set_values(rows)
bar.resize(680, bar.sizeHint().height())
pix = bar.grab()
assert not pix.isNull() and pix.width() == 680, "pixmap inválido"
assert bar.sizeHint().height() >= bar._row_height() * len(rows), "altura no escala con filas"
bar.set_values([])
pix_empty = bar.grab()
assert not pix_empty.isNull(), "pixmap vacío inválido"
print("OK 3 · BarWidget renderiza", len(rows), "filas y el estado vacío")

print("SMOKE OK")
