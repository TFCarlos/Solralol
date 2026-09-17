"""Pruebas de regresión para la herramienta de draft.

Verifica:
1. La evolución de win rate por rol (Mid/Bot) usa curvas reales, no 50% plano.
2. Los campeones sin curva no aplanan la media a 50%.
3. El WR OVERALL agregado por equipo se calcula con los picks visibles.
4. El diálogo de draft se construye y actualiza sin errores (QT_QPA_PLATFORM=offscreen).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

from app.services.draft_analyzer_service import DraftAnalyzerService

analyzer = DraftAnalyzerService()
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


# 1. Curvas individuales reales para Mid y Bot
for champ in ("Akshan", "Akali", "Ashe", "Corki", "Ahri", "Jinx"):
    curve = analyzer.calculate_team_power_curve([champ])
    non_flat = any(abs(v - 50.0) > 0.01 for v in curve.values())
    check(f"curva individual {champ} no es 50% plano", non_flat, str(curve))

# 2. Curva por rol Mid (como la pinta el diálogo)
mid_champs = [
    combo_text
    for role, combo_text in (("Top", "Aatrox"), ("Mid", "Akshan"), ("Bot", "Ashe"))
    if role == "Mid" and combo_text != "-- Vacío --"
]
mid_curve = analyzer.calculate_team_power_curve(mid_champs)
check("curva Mid con datos reales", any(abs(v - 50.0) > 0.01 for v in mid_curve.values()), str(mid_curve))

bot_curve = analyzer.calculate_team_power_curve(["Ashe"])
check("curva Bot con datos reales", any(abs(v - 50.0) > 0.01 for v in bot_curve.values()), str(bot_curve))

# 3. Campeón sin perfil no aplana la media
curve_with_unknown = analyzer.calculate_team_power_curve(["Akshan", "CampeónInexistente"])
check("campeón desconocido no aplana la media", curve_with_unknown == analyzer.calculate_team_power_curve(["Akshan"]))

# 4. WR OVERALL agregado por equipo
my_rates = [analyzer.get_champion_overall_win_rate(c) for c in ("Aatrox", "Briar", "Akshan", "Ashe", "Alistar")]
en_rates = [analyzer.get_champion_overall_win_rate(c) for c in ("Cho'Gath", "Ambessa", "Akali", "Corki", "Blitzcrank")]
print(f"    WR OVERALL mi equipo: {my_rates} => media {round(sum(my_rates)/len(my_rates),1)}")
print(f"    WR OVERALL enemigos:  {en_rates} => media {round(sum(en_rates)/len(en_rates),1)}")
check("WR overall individual no es 50% para todos", any(r != 50.0 for r in my_rates + en_rates))

# 5. El diálogo se construye y actualiza sin errores
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
from app.ui.draft_tool_dialog import DraftToolDialog  # noqa: E402

dialog = DraftToolDialog()
check("diálogo construido", dialog is not None)
check("etiqueta WR mi equipo existe", hasattr(dialog, "my_team_overall_lbl"))
check("etiqueta WR enemigo existe", hasattr(dialog, "enemy_team_overall_lbl"))
check("etiqueta WR sin picks muestra 'WR —'", dialog.my_team_overall_lbl.text() == "WR —", dialog.my_team_overall_lbl.text())

# Simular el draft de la captura: pre-selecciones sin marcar
draft_my = ["Aatrox", "Briar", "Akshan", "Ashe", "Alistar"]
draft_en = ["Cho'Gath", "Ambessa", "Akali", "Corki", "Blitzcrank"]
for combo, name in zip(dialog.my_team_combo_widgets, draft_my):
    combo.setCurrentText(name)
for combo, name in zip(dialog.enemy_team_combo_widgets, draft_en):
    combo.setCurrentText(name)

check("WR mi equipo calculado", dialog.my_team_overall_lbl.text().startswith("WR 5"), dialog.my_team_overall_lbl.text())
check("WR enemigo calculado", dialog.enemy_team_overall_lbl.text().startswith("WR 5"), dialog.enemy_team_overall_lbl.text())

# 6. La gráfica por rol Mid ya no es plana
dialog.curve_scope = "Mid"
dialog._update_analytics()
mid_values = [dialog.power_curve_widget.my_team_curve[b] for b in dialog.power_curve_widget.TIME_BRACKETS]
check("gráfica Mid no plana", any(abs(v - 50.0) > 0.01 for v in mid_values), str(mid_values))

dialog.curve_scope = "Bot"
dialog._update_analytics()
bot_values = [dialog.power_curve_widget.my_team_curve[b] for b in dialog.power_curve_widget.TIME_BRACKETS]
check("gráfica Bot no plana", any(abs(v - 50.0) > 0.01 for v in bot_values), str(bot_values))

# 7. Equipo completo vs equipo completo
dialog.curve_scope = "Equipo vs equipo"
dialog._update_analytics()
my_curve = dict(dialog.power_curve_widget.my_team_curve)
en_curve = dict(dialog.power_curve_widget.enemy_team_curve)
print(f"    Curva mi equipo: {my_curve}")
print(f"    Curva enemigos:  {en_curve}")
check("curva equipo completo no plana (aliados)", any(abs(v - 50.0) > 0.01 for v in my_curve.values()))
check("curva equipo vs equipo no idéntica", my_curve != en_curve)

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("TODAS LAS PRUEBAS PASARON")