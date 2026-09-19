"""Prueba el botón «Importar build al cliente» de la herramienta de draft.

Verifica el camino completo (diálogo -> LCUService -> HTTP LCU) con una sesión
HTTP simulada, porque el cliente real solo existe durante una partida:
1. El botón existe y avisa de lo que hace.
2. Con Briar seleccionada crea la página general «Solralol - Briar Build».
3. La página no queda ligada a ningún campeón (mapa y modo «any»).
4. Lleva los 6 objetos de la build calculada y las botas recomendadas.
5. Se conserva el conjunto propio del jugador y se reemplaza el de Solralol.
6. Se informa del éxito en pantalla.
7. Sin campeón seleccionado no se toca el cliente.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from app.services.lcu_service import LCUService  # noqa: E402
from app.ui.draft_tool_dialog import DraftToolDialog  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


class FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | list | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict | list:
        return self._payload


class FakeSession:
    """Cliente LCU simulado con un conjunto propio del jugador ya guardado."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, dict]] = []

    def get(self, url: str, timeout: float = 0) -> FakeResp:
        if "current-summoner" in url:
            return FakeResp(200, {"summonerId": "sum-1"})
        if "item-sets" in url:
            return FakeResp(200, {
                "accountId": 42,
                "itemSets": [{"uid": "user-own", "title": "Mi build"}],
                "timestamp": 3,
            })
        return FakeResp(404)

    def put(self, url: str, json: dict | None = None, timeout: float = 0) -> FakeResp:
        self.puts.append((url, json or {}))
        return FakeResp(204)

dialog = DraftToolDialog()
check("botón de importar build presente", hasattr(dialog, "btn_import_build"))
check("el botón anuncia la página general",
      "Solralol - [campeón] Build" in dialog.btn_import_build.toolTip(),
      dialog.btn_import_build.toolTip())

# El diálogo usa su propia instancia de LCU; se simula la sesión HTTP del cliente.
dialog.lcu_service = LCUService()
fake = FakeSession()
dialog.lcu_service.session = fake
dialog.lcu_service.port = 1234
dialog.lcu_service.auth_token = "x"

ENEMIES = ["Ahri", "Syndra", "Annie", "Zoe", "Seraphine"]
dialog.local_champ_combo.setCurrentText("Briar")
dialog.local_role_combo.setCurrentText("Jungle")
for combo, name in zip(dialog.enemy_team_combo_widgets, ENEMIES):
    combo.setCurrentText(name)
dialog._update_analytics()

shown: list[tuple[str, str]] = []
QMessageBox.information = staticmethod(lambda *a, **k: shown.append(("info", str(a))))
QMessageBox.critical = staticmethod(lambda *a, **k: shown.append(("crit", str(a))))
QMessageBox.warning = staticmethod(lambda *a, **k: shown.append(("warn", str(a))))

dialog._import_build()

check("se escribió en el cliente", len(fake.puts) == 1, str(len(fake.puts)))
check("éxito informado en pantalla", shown and shown[-1][0] == "info", str(shown[-1:]))
check("sin errores en pantalla", not any(kind == "crit" for kind, _ in shown))

url, payload = fake.puts[0]
check("endpoint del invocador local", "item-sets/sum-1/sets" in url, url)
sets = payload.get("itemSets", [])
page = next((s for s in sets if str(s.get("uid", "")).startswith("solralol-build-")), None)
check("página de Solralol creada", page is not None, str([s.get("uid") for s in sets]))
check("nombre exacto de la página", page["title"] == "Solralol - Briar Build", page["title"])
check("página general (sin campeón asociado)", page["associatedChampions"] == [],
      str(page["associatedChampions"]))
check("disponible en cualquier mapa y modo",
      page["map"] == "any" and page["mode"] == "any",
      f"{page['map']}/{page['mode']}")
check("mapas SR + ARAM", page["associatedMaps"] == [11, 12], str(page["associatedMaps"]))

build = dialog.analyzer.get_champion_build("Briar", ENEMIES)
expected_items = [item["id"] for item in build["items"]]
expected_boots = build["boots"]["id"] if build["boots"] else None
imported_items = [item["id"] for item in page["blocks"][0]["items"]]
check("6 objetos de la build calculada", imported_items == expected_items,
      f"importados={imported_items} esperados={expected_items}")
check("botas recomendadas incluidas",
      len(page["blocks"]) == 2 and page["blocks"][1]["items"] == [
          {"id": expected_boots, "count": 1}],
      str(page["blocks"][1:]))
check("conjunto propio del jugador intacto", any(s.get("uid") == "user-own" for s in sets))

# Reimportar no acumula páginas de Solralol.
dialog._import_build()
sets = fake.puts[-1][1]["itemSets"]
check("reimportar no duplica la página",
      sum(1 for s in sets if str(s.get("uid", "")).startswith("solralol-")) == 1,
      str([s.get("uid") for s in sets]))

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("BOTÓN IMPORTAR BUILD -> PÁGINA GENERAL VERIFICADO")