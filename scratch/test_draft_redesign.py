"""Pruebas del rediseño de la herramienta de draft.

Verifica:
1. Ya no existen picks recomendados (ni tabla de picks ni servicio asociado).
2. Los 3 baneos recomendados se pintan como tarjetas con nombre y WR.
3. La build muestra 6 objetos + botas elegidas por el daño enemigo.
4. Las páginas de runas U.GG/Lolalytics se previsualizan con keystone.
5. Los hechizos incluyen Smite en Jungla y se importan correctamente.
6. La importación de build envía 6 objetos distintos + botas + situacionales al LCU.
7. Validaciones de LCUService.import_item_set sin conexión.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from app.services.draft_analyzer_service import DraftAnalyzerService  # noqa: E402
from app.services.lcu_service import LCUService  # noqa: E402
from app.ui.draft_tool_dialog import DraftToolDialog  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


analyzer = DraftAnalyzerService()

# 1. La lógica de picks recomendados desapareció del servicio.
check("get_recommended_picks eliminado", not hasattr(analyzer, "get_recommended_picks"))

# El desglose de daño usa damage_breakdown cuando existe.
aatrox_dmg = analyzer.calculate_team_damage_breakdown(["Aatrox"])
check("damage_breakdown real de Aatrox", abs(aatrox_dmg["physical"] - 87.7) < 1.0, str(aatrox_dmg))

# 2. El diálogo se construye y ya no tiene tablas de bans/picks.
dialog = DraftToolDialog()
check("diálogo construido", dialog is not None)
check("sin bans_table", not hasattr(dialog, "bans_table"))
check("sin picks_table", not hasattr(dialog, "picks_table"))
check("sin runes_preview_lbl", not hasattr(dialog, "runes_preview_lbl"))
check("3 tarjetas de ban", len(dialog.ban_card_widgets) == 3)
check("6 huecos de build", len(dialog.build_item_labels) == 6)
check("botas separadas", dialog.build_boots_label is not None)
check("2 filas de runas", set(dialog.rune_page_rows) == {1, 2})
check("2 iconos de hechizo", len(dialog.spell_icon_labels) == 2)

# 3. Draft real: Aatrox contra un equipo muy AP.
for combo, name in zip(dialog.my_team_combo_widgets, ["Aatrox", "Briar", "Akshan", "Ashe", "Alistar"]):
    combo.setCurrentText(name)
ap_enemies = ["Ahri", "Syndra", "Annie", "Zoe", "Seraphine"]
for combo, name in zip(dialog.enemy_team_combo_widgets, ap_enemies):
    combo.setCurrentText(name)
dialog._update_analytics()

ban_names = [card["name"].text() for card in dialog.ban_card_widgets]
check("tarjetas de ban rellenas", all(n and n != "Sin dato" for n in ban_names), str(ban_names))
check("WR visible en tarjetas", all(card["wr"].text().startswith("WR ") for card in dialog.ban_card_widgets))

build = analyzer.get_champion_build("Aatrox", ap_enemies)
check("build con 6 objetos", len(build["items"]) == 6, str([i["id"] for i in build["items"]]))
check("objetos únicos", len({i["id"] for i in build["items"]}) == 6)
check("botas MR contra AP", build["boots"] and build["boots"]["id"] == "3111", str(build["boots"]))
situational = build.get("situational", [])
check("situacionales del servicio Aatrox", len(situational) >= 1,
      str([g["label"] for g in situational]))
check("categorías situacionales conocidas",
      {g["key"] for g in situational} <= {k for k, _ in analyzer.SITUATIONAL_CATEGORIES},
      str([g["key"] for g in situational]))
check("categorías situacionales en el orden de la vista",
      [g["key"] for g in situational]
      == [k for k, _ in analyzer.SITUATIONAL_CATEGORIES
          if any(g["key"] == k for g in situational)],
      str([g["key"] for g in situational]))
check("situacionales solo con objetos del catálogo",
      all(item["id"] in analyzer.items and item["name"] for g in situational for item in g["items"]),
      str(situational))
check("situacionales sin botas",
      all("Boots" not in analyzer.items[item["id"]].get("tags", [])
          for g in situational for item in g["items"]))
check("situacionales resueltos por nombre a ID",
      all(analyzer.item_names.get(item["name"].strip().casefold()) == item["id"]
          for g in situational for item in g["items"]))
check("tooltips de objetos", all(lbl.toolTip() for lbl in dialog.build_item_labels))
check("tooltip de botas con razón", "mágico" in dialog.build_boots_label.toolTip(), dialog.build_boots_label.toolTip())

# 4. Runas: keystone visible en ambas fuentes.
k1 = dialog.rune_page_rows[1]["keystone"].text()
k2 = dialog.rune_page_rows[2]["keystone"].text()
check("keystone U.GG visible", k1 and k1 != "—", k1)
check("keystone Lolalytics visible", k2 and k2 != "—", k2)
check("página 1 guardada para importar", dialog.rune_page_rows[1]["page"] is not None)
check("página 2 guardada para importar", dialog.rune_page_rows[2]["page"] is not None)

# 5. Hechizos: perfil Top y smite obligatorio en Jungla.
dialog.local_role_combo.setCurrentText("Top")
dialog._update_analytics()
top_spells = analyzer.get_champion_runes_and_summoners("Aatrox", "Top")["spells"]
check("hechizos Top del perfil", top_spells == ("Destello", "Ignición"), str(top_spells))
check("texto summoners sin nota jungla", "Jungla" not in dialog.spells_text_lbl.text(), dialog.spells_text_lbl.text())

dialog.local_role_combo.setCurrentText("Jungle")
dialog._update_analytics()
jgl_spells = analyzer.get_champion_runes_and_summoners("Aatrox", "Jungle")["spells"]
check("smite en jungla (servicio)", jgl_spells[1] == "Aplastar", str(jgl_spells))
check("nota de smite en jungla (UI)", "Smite" in dialog.spells_text_lbl.text(), dialog.spells_text_lbl.text())
dialog.local_role_combo.setCurrentText("Top")
dialog._update_analytics()

# 6. Importaciones con LCU simulado.
captured: dict[str, Any] = {}


class FakeLCU:
    def is_connected(self) -> bool:
        return True

    def import_item_set(self, champion_id, champion_name, role, item_ids, boots_id=None,
                        situational=None):
        captured["build"] = (champion_id, champion_name, role, list(item_ids), boots_id,
                             list(situational or []))
        return True, "build ok"

    def import_rune_page(self, **kwargs):
        captured.setdefault("runes", []).append(kwargs)
        return True, "runes ok"

    def import_summoner_spells(self, s1, s2):
        captured["spells"] = (s1, s2)
        return True, "spells ok"


real_lcu = dialog.lcu_service
dialog.lcu_service = FakeLCU()
shown: list[tuple[str, str]] = []
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(("info", str(a))))
QMessageBox.critical = staticmethod(lambda *a, **k: shown.append(("crit", str(a))))
QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(("warn", str(a))))

dialog._import_build()
champ_id, champ_name, role, item_ids, boots_id, sent_situational = captured["build"]
check("build: champion_id válido", champ_id > 0, str(champ_id))
check("build: 6 objetos distintos", len(item_ids) == 6 and len(set(item_ids)) == 6, str(item_ids))
check("build: botas incluidas", boots_id in {"3047", "3111", "3009", "3020", "3006", "3158"}, str(boots_id))
check("build: rol Top enviado", role == "Top", role)
check("build: situacionales enviados al LCU",
      [g["key"] for g in sent_situational]
      == [g["key"] for g in analyzer.get_situational_items("Aatrox")],
      str([g["key"] for g in sent_situational]))
check("build: situacionales con sus objetos",
      [[i["id"] for i in g["items"]] for g in sent_situational]
      == [[i["id"] for i in g["items"]] for g in analyzer.get_situational_items("Aatrox")],
      str([[i["id"] for i in g["items"]] for g in sent_situational]))

dialog._import_runes(page_index=1)
dialog._import_runes(page_index=2)
check("runas: 2 páginas capturadas", len(captured.get("runes", [])) == 2)
p1, p2 = captured["runes"]
check("runas: keystone Conqueror", p1["keystone_name"].casefold() == "conqueror", p1["keystone_name"])
check("runas: 3 slots primarios", len(p1["slots"]) == 3, str(p1["slots"]))
check("runas: 2 secundarias", len(p1["secondary_slots"]) == 2, str(p1["secondary_slots"]))
check("runas: 3 fragments", len(p1["shards"]) == 3, str(p1["shards"]))
check("runas: página 2 presente", p2["keystone_name"] != "", p2["keystone_name"])

dialog._import_spells()
check("hechizos importados", captured.get("spells") == ("Destello", "Ignición"), str(captured.get("spells")))

dialog.local_role_combo.setCurrentText("Jungle")
dialog._import_spells()
check("hechizos jungla con smite", captured.get("spells") == ("Destello", "Aplastar"), str(captured.get("spells")))
dialog.local_role_combo.setCurrentText("Top")

# 7. Validaciones de LCUService sin cliente conectado.
lcu = LCUService()
ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ["1", "2", "3", "4", "5", "5"])
check("item_set rechaza duplicados", not ok, msg)
ok, msg = lcu.import_item_set(0, "Aatrox", "Top", ["1", "2", "3", "4", "5", "6"])
check("item_set rechaza champion_id 0", not ok, msg)
# Nunca escribir en un cliente real desde una prueba: se simula "sin cliente".
lcu.port = None
lcu.auth_token = None
lcu.refresh_connection = lambda: False  # type: ignore[method-assign]
ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ["1", "2", "3", "4", "5", "6"])
check("item_set sin cliente falla limpio", not ok and "conectado" in msg.lower(), msg)

# 8. Casos límite del servicio de build.
cass = analyzer.get_champion_build("Cassiopeia", ap_enemies)
check("Cassiopeia sin botas", cass["boots"] is None, str(cass["boots"]))
unknown = analyzer.get_champion_build("ChampionInexistente", [])
check("campeón desconocido sin objetos", unknown["items"] == [] and unknown["boots"] is None)

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("TODAS LAS PRUEBAS PASARON")