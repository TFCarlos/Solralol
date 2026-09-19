"""Pruebas del reparto de líneas en el draft: hipótesis, nunca certezas.

Durante la selección solo se conoce el orden de pickeo: el cliente publica la
posición asignada de los aliados (``assignedPosition``) pero nunca la de los
rivales. Estas pruebas comprueban que:

1. El servicio reparte las cinco líneas sin repetir y sin inventarlas: un
   campeón sin encaje se queda sin línea.
2. La interfaz marca con «~» toda línea que no venga del cliente.
3. Las líneas publicadas por LCU se muestran tal cual, sin marca.
4. La curva de poder y las importaciones usan la línea efectiva, no el texto
   con la marca de hipótesis.
5. Al volver al modo manual no quedan marcas de hipótesis en los selectores.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import app.ui.draft_tool_dialog as ui  # noqa: E402
from app.ui.draft_tool_dialog import DraftToolDialog  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def clean(roles: list[str]) -> list[str]:
    """Líneas efectivas de un reparto: quita las cadenas vacías."""
    return [role for role in roles if role]


class FakeLCU:
    """Cliente simulado: solo interesa con qué rol se importa la build."""

    def __init__(self) -> None:
        self.build: tuple | None = None

    def is_connected(self) -> bool:
        return True

    def import_item_set(self, champion_id, champion_name, role, item_ids,
                        boots_id=None, situational=None):
        self.build = (champion_id, champion_name, role, list(item_ids), boots_id)
        return True, "build ok"

    def import_rune_page(self, **kwargs):
        return True, "runes ok"

    def import_summoner_spells(self, spell1, spell2):
        return True, "spells ok"


# Sin cliente real ni descargas de iconos: el diálogo se construye en memoria.
with patch.object(ui.DraftToolDialog, "_check_lcu_status"), \
        patch.object(ui, "get_champion_icon_path", return_value=None), \
        patch.object(ui, "get_item_icon_path", return_value=None), \
        patch.object(ui, "get_rune_icon_path", return_value=None), \
        patch.object(ui, "get_spell_icon_path", return_value=None):
    dialog = DraftToolDialog()

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)

analyzer = dialog.analyzer

# 1. Reparto en el servicio: sin repeticiones y sin líneas inventadas.
team = analyzer.assign_likely_roles(["Aatrox", "Briar", "Ahri", "Jinx", "Leona"])
check("reparto completo de las cinco líneas",
      team == ["Top", "Jungle", "Mid", "Bot", "Support"], str(team))
check("líneas sin repetir", len(set(clean(team))) == len(clean(team)), str(team))
check("dos supports: el segundo se queda sin línea",
      analyzer.assign_likely_roles(["Leona", "Thresh"]) == ["Support", ""],
      str(analyzer.assign_likely_roles(["Leona", "Thresh"])))
check("no inventa líneas ya ocupadas",
      analyzer.assign_likely_roles(["Ahri", "Zed"], exclude=["Mid"]) == ["", ""],
      str(analyzer.assign_likely_roles(["Ahri", "Zed"], exclude=["Mid"])))
check("con líneas ocupadas usa las libres",
      analyzer.assign_likely_roles(
          ["Aatrox", "Briar", "Ahri", "Jinx", "Leona"],
          exclude=["Top", "Jungle", "Mid"]) == ["", "", "", "Bot", "Support"],
      str(analyzer.assign_likely_roles(
          ["Aatrox", "Briar", "Ahri", "Jinx", "Leona"],
          exclude=["Top", "Jungle", "Mid"])))
check("campeón sin datos no recibe línea",
      analyzer.assign_likely_roles(["ChampionInexistente", "", "Ahri"]) == ["", "", "Mid"])
check("en empate manda el orden de pickeo",
      analyzer.assign_likely_roles(["Aatrox", "Zed"]) == ["Top", "Mid"],
      str(analyzer.assign_likely_roles(["Aatrox", "Zed"])))
check("todas las líneas repartidas son líneas reales",
      set(clean(analyzer.assign_likely_roles(["Yasuo", "Lux", "Amumu"]))) <= set(dialog.ROLES))

# 2. Modo manual: los rivales son hipótesis y las llevan marcadas.
for combo, name in zip(dialog.enemy_team_combo_widgets,
                       ["Garen", "Amumu", "Lux", "Caitlyn", "Leona"]):
    combo.setCurrentText(name)
dialog._update_analytics()
check("hipótesis rivales marcadas con «~»",
      [label.text() for label in dialog.enemy_team_role_labels]
      == ["~Top", "~Jungle", "~Mid", "~Bot", "~Support"],
      str([label.text() for label in dialog.enemy_team_role_labels]))
check("línea efectiva del rival sin marca", dialog.enemy_team_roles == dialog.ROLES,
      str(dialog.enemy_team_roles))
check("hipótesis rivales sin repetir",
      len(set(clean(dialog.enemy_team_roles))) == len(clean(dialog.enemy_team_roles)))
check("el tooltip avisa de que es probable",
      all("probable" in label.toolTip() for label in dialog.enemy_team_role_labels))
check("en manual las líneas aliadas son las declaradas",
      [combo.currentText() for combo in dialog.my_team_role_combos] == dialog.ROLES,
      str([combo.currentText() for combo in dialog.my_team_role_combos]))
check("en manual no se marca ninguna línea aliada",
      all("~" not in combo.currentText() for combo in dialog.my_team_role_combos))

# 3. Sin rivales no se afirma nada: guion y sin línea efectiva.
for combo in dialog.enemy_team_combo_widgets:
    combo.setCurrentText("-- Vacío --")
dialog._update_analytics()
check("sin rivales no se inventa línea",
      [label.text() for label in dialog.enemy_team_role_labels] == ["—"] * 5,
      str([label.text() for label in dialog.enemy_team_role_labels]))
check("sin rivales no hay línea efectiva", dialog.enemy_team_roles == [""] * 5)

# 4. Sesión LCU real: la posición de los aliados es un dato, la del rival no.
session = {
    "localPlayerCellId": 0,
    "myTeam": [
        {"cellId": 0, "championId": 266, "assignedPosition": "top"},
        {"cellId": 1, "championId": 233, "assignedPosition": "jungle"},
        {"cellId": 2, "championId": 103, "assignedPosition": "middle"},
        {"cellId": 3, "championId": 222, "assignedPosition": "bottom"},
        {"cellId": 4, "championId": 89, "assignedPosition": "utility"},
    ],
    "theirTeam": [
        {"cellId": 5, "championId": 86}, {"cellId": 6, "championId": 32},
        {"cellId": 7, "championId": 99}, {"cellId": 8, "championId": 51},
        {"cellId": 9, "championId": 412},
    ],
    "actions": [],
}
dialog.update_from_lcu_session(session)
check("líneas aliadas publicadas por el cliente",
      [combo.currentText() for combo in dialog.my_team_role_combos] == dialog.ROLES,
      str([combo.currentText() for combo in dialog.my_team_role_combos]))
check("las líneas confirmadas no llevan marca",
      all("~" not in combo.currentText() for combo in dialog.my_team_role_combos))
check("cabecera con la línea del cliente", dialog.local_role_combo.currentText() == "Top",
      dialog.local_role_combo.currentText())
check("el rival sigue siendo hipótesis",
      [label.text() for label in dialog.enemy_team_role_labels]
      == ["~Top", "~Jungle", "~Mid", "~Bot", "~Support"],
      str([label.text() for label in dialog.enemy_team_role_labels]))
check("línea efectiva del rival tras la sesión", dialog.enemy_team_roles == dialog.ROLES,
      str(dialog.enemy_team_roles))
check("picks aliados leídos del cliente",
      [combo.currentText() for combo in dialog.my_team_combo_widgets]
      == ["Aatrox", "Briar", "Ahri", "Jinx", "Leona"])

# 5. Modo sin posiciones (ARAM/blind): los aliados también son hipótesis.
no_positions = dict(session)
no_positions["myTeam"] = [
    {key: value for key, value in player.items() if key != "assignedPosition"}
    for player in session["myTeam"]
]
dialog.update_from_lcu_session(no_positions)
ally_texts = [combo.currentText() for combo in dialog.my_team_role_combos]
check("sin posición publicada los aliados van marcados",
      all(text.startswith("~") for text in ally_texts), str(ally_texts))
check("reparto aliado sin repetir y completo",
      sorted(dialog.my_team_roles) == sorted(dialog.ROLES), str(dialog.my_team_roles))
check("la cabecera acompaña la hipótesis del jugador",
      dialog.local_role_combo.currentText().startswith("~"),
      dialog.local_role_combo.currentText())
check("línea efectiva del jugador sin marca",
      dialog._current_local_role() in dialog.ROLES, dialog._current_local_role())

# 6. Curva de poder e importaciones usan la línea efectiva, no el texto pintado.
seen: list[list[str]] = []
curve = dialog.analyzer.calculate_team_power_curve


def spy_curve(champions):
    seen.append(list(champions))
    return curve(champions)


dialog.analyzer.calculate_team_power_curve = spy_curve
dialog.curve_scope = "Support"
dialog._update_analytics()
check("la curva aliada filtra por línea aunque el texto lleve marca",
      seen[-2] == ["Leona"], str(seen[-2:]))
check("la curva rival filtra por su hipótesis marcada",
      seen[-1] == ["Thresh"], str(seen[-1]))
dialog.curve_scope = "Jungle"
dialog._update_analytics()
check("filtro de jungla con líneas marcadas", seen[-2:] == [["Briar"], ["Amumu"]],
      str(seen[-2:]))
dialog.curve_scope = "Equipo vs equipo"
dialog.analyzer.calculate_team_power_curve = curve

fake_lcu = FakeLCU()
dialog.lcu_service = fake_lcu
dialog._import_build()
check("la build se importa con la línea efectiva",
      fake_lcu.build is not None and fake_lcu.build[2] in dialog.ROLES,
      str(fake_lcu.build and fake_lcu.build[2]))

# 7. Al volver al modo manual no quedan marcas de hipótesis.
dialog._set_lcu_managed_controls(False)
texts = [combo.currentText() for combo in dialog.my_team_role_combos]
texts.append(dialog.local_role_combo.currentText())
check("sin residuos de hipótesis al volver a manual",
      all(text in dialog.ROLES for text in texts), str(texts))
check("las líneas manuales siguen siendo las cinco",
      [combo.currentText() for combo in dialog.my_team_role_combos] == dialog.ROLES,
      str([combo.currentText() for combo in dialog.my_team_role_combos]))
check("cada selector vuelve a ofrecer solo las cinco líneas",
      all(combo.count() == 5 for combo in dialog.my_team_role_combos)
      and dialog.local_role_combo.count() == 5,
      str([combo.count() for combo in dialog.my_team_role_combos]))
check("el rival sigue marcado como hipótesis en manual",
      all(label.text().startswith("~") for label in dialog.enemy_team_role_labels),
      str([label.text() for label in dialog.enemy_team_role_labels]))

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("REPARTO DE LÍNEAS DEL DRAFT VERIFICADO")
