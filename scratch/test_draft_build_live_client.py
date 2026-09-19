"""Extremo a extremo contra el cliente REAL de League (si está abierto).

Es la única prueba que escribe en el cliente, porque eso es exactamente lo que
hace el botón: pulsar «Importar build al cliente» crea la página general. Si no
hay cliente conectado, la prueba se omite sin fallar.

1. El botón crea de verdad «Solralol - Briar Build» en los conjuntos del cliente.
2. La página es general (sin campeón asociado), disponible en SR y ARAM.
3. Lleva los 6 objetos, las botas y los bloques situacionales de la build calculada.
4. Los conjuntos propios del jugador siguen intactos.
5. Reimportar deja una sola página de Solralol.
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


def read_sets(service: LCUService) -> list[dict]:
    summoner = service.session.get(
        f"https://127.0.0.1:{service.port}/lol-summoner/v1/current-summoner", timeout=3
    )
    summoner_id = summoner.json().get("summonerId")
    response = service.session.get(
        f"https://127.0.0.1:{service.port}/lol-item-sets/v1/item-sets/{summoner_id}/sets",
        timeout=3,
    )
    return LCUService._item_set_container(response.json())[0]


probe = LCUService()
if not probe.is_connected():
    print("OMITIDA: no hay cliente de League conectado (abre el cliente y reintenta).")
    sys.exit(0)

before = read_sets(probe)
user_sets_before = [s for s in before if not str(s.get("uid", "")).startswith("solralol-")]
print(f"cliente conectado · conjuntos del jugador: {len(user_sets_before)}")

ENEMIES = ["Ahri", "Syndra", "Annie", "Zoe", "Seraphine"]
dialog = DraftToolDialog()
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
check("el cliente aceptó la importación",
      shown and shown[-1][0] == "info", str(shown[-1:]))
check("sin errores en pantalla", not any(kind == "crit" for kind, _ in shown))

after = read_sets(probe)
pages = [s for s in after if str(s.get("uid", "")).startswith("solralol-build-")]
check("una sola página de Solralol en el cliente", len(pages) == 1,
      str([s.get("uid") for s in pages]))
page = pages[0] if pages else {}
check("nombre exacto en el cliente", page.get("title") == "Solralol - Briar Build",
      str(page.get("title")))
check("página general (sin campeón asociado)", page.get("associatedChampions") == [],
      str(page.get("associatedChampions")))
check("mapa y modo abiertos",
      page.get("map") == "any" and page.get("mode") == "any",
      f"{page.get('map')}/{page.get('mode')}")
check("disponible en SR y ARAM", page.get("associatedMaps") == [11, 12],
      str(page.get("associatedMaps")))

build = dialog.analyzer.get_champion_build("Briar", ENEMIES)
expected_items = [item["id"] for item in build["items"]]
expected_boots = build["boots"]["id"] if build["boots"] else None
blocks = page.get("blocks", [])
check("6 objetos de la build calculada",
      blocks and [i["id"] for i in blocks[0]["items"]] == expected_items,
      str([i["id"] for i in blocks[0]["items"]] if blocks else None))
check("botas recomendadas incluidas",
      len(blocks) >= 2 and blocks[1]["items"] == [{"id": expected_boots, "count": 1}],
      str(blocks[1:2]))
expected_situational = build.get("situational", [])
check("bloques situacionales del campeón incluidos",
      [block.get("type") for block in blocks[2:]]
      == [group["label"] for group in expected_situational],
      str([block.get("type") for block in blocks[2:]]))
check("situacionales con los mismos objetos que la vista local",
      [[item["id"] for item in block["items"]] for block in blocks[2:]]
      == [[item["id"] for item in group["items"]] for group in expected_situational],
      str([[item["id"] for item in block["items"]] for block in blocks[2:]]))

user_sets_after = [s for s in after if not str(s.get("uid", "")).startswith("solralol-")]
check("conjuntos del jugador intactos",
      [s.get("uid") for s in user_sets_after] == [s.get("uid") for s in user_sets_before],
      f"{len(user_sets_after)} != {len(user_sets_before)}")

dialog._import_build()
final = read_sets(probe)
check("reimportar no duplica la página",
      sum(1 for s in final if str(s.get("uid", "")).startswith("solralol-")) == 1,
      str([s.get("uid") for s in final if str(s.get("uid", "")).startswith("solralol-")]))

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("PÁGINA «Solralol - Briar Build» CREADA Y VERIFICADA EN EL CLIENTE REAL")
