"""Verifica el salto automático a «Partida en vivo» cuando termina el draft.

Secuencia real: el draft termina (champ select) -> pantalla de carga (la API
local aún no responde, los snapshots son None) -> partida en curso (llega el
primer snapshot).

1. Al terminar el draft todavía no se navega, pero queda el aviso pendiente y
   la herramienta de draft se cierra para poder ver el panel.
2. La pantalla de carga (snapshots None) no navega.
3. Con el primer snapshot el panel salta a la pestaña «Partida en vivo» y la
   marca como activa en la barra de navegación.
4. La navegación ocurre una sola vez: si el usuario cambia de pestaña durante
   la partida, los siguientes snapshots no lo devuelven a ella.
5. Un nuevo draft reinicia el aviso.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from app.ui.main_window import MainWindow  # noqa: E402

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


SNAPSHOT = {
    "game_time": 35.0,
    "game_mode": "CLASSIC",
    "local_team": "ORDER",
    "local_player": {
        "riotId": "Solrasar#000",
        "summonerName": "Solrasar",
        "championName": "Briar",
        "level": 3,
    },
    "all_players": [],
    "enemies": [],
    "local_live_stats": {},
}

SESSION = {
    "localPlayerCellId": 1,
    "myTeam": [
        {"cellId": 1, "championId": 233, "assignedPosition": "jungle"},
        {"cellId": 2, "championId": 0, "assignedPosition": "top"},
    ],
    "theirTeam": [{"cellId": 6, "championId": 0}],
    "actions": [[{"type": "ban", "actorCellId": 1, "championId": 24, "isAllyAction": True}]],
}

window = MainWindow(version="16.17.1", item_catalog={"items": {}})
window.poll_timer.stop()  # el test controla los snapshots a mano

check("el panel arranca en Inicio", window.pages.currentIndex() == 0)
check("pestaña Partida en vivo en el índice esperado", MainWindow.LIVE_PAGE_INDEX == 2)

# 1. Termina el draft (champ select): se cierra la herramienta y queda el aviso.
window._on_champ_select_started(SESSION)
check("el draft abre la herramienta", window.draft_tool_dialog is not None)
check("nuevo draft limpia el aviso", window.pending_live_navigation is False)

window._on_champ_select_ended()
check("draft terminado marca el aviso", window.pending_live_navigation is True)
check("la herramienta de draft se cierra", not window.draft_tool_dialog.isVisible())

# 2. Pantalla de carga: la API local todavía no responde.
window.receive_snapshot(None)
check("la pantalla de carga no navega", window.pages.currentIndex() == 0,
      str(window.pages.currentIndex()))
check("el aviso sigue pendiente tras la pantalla de carga",
      window.pending_live_navigation is True)

# 3. La partida arranca: primer snapshot de la API local.
window.receive_snapshot(SNAPSHOT)
check("la partida navega a Partida en vivo",
      window.pages.currentIndex() == MainWindow.LIVE_PAGE_INDEX,
      str(window.pages.currentIndex()))
check("la pestaña queda marcada en la barra", window.live_button.isChecked())
check("el aviso se consume", window.pending_live_navigation is False)

# 4. Si el usuario se va a otra pestaña, no se le devuelve a la fuerza.
window.pages.setCurrentIndex(0)
window.receive_snapshot(SNAPSHOT)
check("los snapshots siguientes no fuerzan la pestaña",
      window.pages.currentIndex() == 0, str(window.pages.currentIndex()))

window.close()
print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("SALTO AUTOMÁTICO A PARTIDA EN VIVO VERIFICADO")