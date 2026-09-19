"""Regresión de rendimiento del draft, sin red ni cliente real."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel
from shiboken6 import delete

import data_dragon as dd
import app.ui.draft_tool_dialog as ui
from app.ui.draft_icon_cache import DraftIconCache

app = QApplication.instance() or QApplication([])


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate(), "La tarea no terminó"
    app.processEvents()


session = {
    "localPlayerCellId": 0,
    "myTeam": [
        {"cellId": i, "championId": cid, "assignedPosition": pos}
        for i, (cid, pos) in enumerate([
            (266, "top"), (64, "jungle"), (103, "middle"),
            (22, "bottom"), (12, "utility"),
        ])
    ],
    "theirTeam": [
        {"cellId": i + 5, "championId": cid}
        for i, cid in enumerate([86, 32, 99, 51, 89])
    ],
    "actions": [],
}

with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
    path = Path(temp) / "icon.png"
    icon = QPixmap(64, 64)
    icon.fill()
    assert icon.save(str(path))
    stack.enter_context(patch.object(ui.DraftToolDialog, "_check_lcu_status"))
    network = stack.enter_context(patch.object(
        dd.requests, "get", side_effect=AssertionError("Red no permitida")
    ))
    resolvers = []
    for name in ("get_champion_icon_path", "get_item_icon_path",
                 "get_rune_icon_path", "get_spell_icon_path"):
        resolvers.append(stack.enter_context(patch.object(ui, name, return_value=path)))

    dialog = ui.DraftToolDialog()
    with patch.object(dialog, "_update_analytics", wraps=dialog._update_analytics) as updates:
        start = time.perf_counter()
        dialog.update_from_lcu_session(session)
        print(f"Primera sesión: {updates.call_count} análisis, {(time.perf_counter()-start)*1000:.3f} ms")
        assert updates.call_count == 1
        assert dialog.local_champ_combo.currentText() == "Aatrox"
        # Las líneas aliadas vienen del cliente; las rivales son hipótesis.
        assert [c.currentText() for c in dialog.my_team_role_combos] == dialog.ROLES
        assert dialog.my_team_roles == dialog.ROLES
        assert [r.text() for r in dialog.enemy_team_role_labels] == [
            "~Top", "~Jungle", "~Mid", "~Bot", "~Support"]
        assert dialog.enemy_team_roles == dialog.ROLES
        for resolver in resolvers:
            resolver.reset_mock()
        updates.reset_mock()
        start = time.perf_counter()
        for _ in range(10):
            dialog.update_from_lcu_session(deepcopy(session))
        print(f"Diez sesiones idénticas: {updates.call_count} análisis, {(time.perf_counter()-start)*1000:.3f} ms")
        assert updates.call_count == 0
        assert not any(resolver.called for resolver in resolvers)

        changed = deepcopy(session)
        changed["timer"] = {"adjustedTimeLeftInPhase": 100}
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 0

        changed["myTeam"][0]["championId"] = 0
        changed["myTeam"][0]["championPickIntent"] = 103
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 1
        assert dialog.local_champ_combo.currentText() == "Ahri"
        assert not dialog.my_team_pick_state_widgets[0].isChecked()
        changed["myTeam"][0]["championId"] = 103
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 2
        assert dialog.my_team_pick_state_widgets[0].isChecked()

        changed["myTeam"][0]["assignedPosition"] = "middle"
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 3
        assert dialog.local_role_combo.currentText() == "Mid"

        changed["actions"] = [[{"type": "ban", "championId": 86, "actorCellId": 0}]]
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 4
        assert "Garen" in dialog.my_header_ban_labels[0].toolTip()

        changed["theirTeam"] = []
        changed["actions"] = []
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 5
        assert all(c.currentText() == "-- Vacío --" for c in dialog.enemy_team_combo_widgets)
        assert [r.text() for r in dialog.enemy_team_role_labels] == ["—"] * 5
        assert dialog.enemy_team_roles == [""] * 5
        assert dialog.my_header_ban_labels[0].text() == "—"

        dialog._set_lcu_managed_controls(False)
        dialog.update_from_lcu_session(changed)
        assert updates.call_count == 6, "Reconectar debe invalidar la sesión anterior"
        dialog._set_lcu_managed_controls(False)
        dialog.my_team_combo_widgets[0].setCurrentText("Aatrox")
        assert updates.call_count == 7, "Las señales manuales deben restaurarse"
    print("OK: temporizador ignorado; picks, roles, bans y reconexión actualizados")

    # La caché caliente evita tanto resolución de rutas como escalado.
    for resolver in resolvers:
        resolver.reset_mock()
    for _ in range(5):
        dialog._update_analytics()
    assert not any(resolver.called for resolver in resolvers)
    print("OK: cinco análisis con caché caliente sin cargar iconos")

    cache = DraftIconCache()
    label, other = QLabel(), QLabel()
    gate = threading.Event()
    started = threading.Event()
    worker_threads = []

    def delayed(*, download):
        if not download:
            return None
        worker_threads.append(threading.get_ident())
        started.set()
        assert gate.wait(5)
        return path

    try:
        cache.assign(label, ("old",), 32, delayed)
        cache.assign(other, ("old",), 32, delayed)
        wait_until(started.is_set)
        assert len(cache.pending) == 1
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait_until(lambda: bool(ticks))
        assert worker_threads == [worker_threads[0]]
        assert worker_threads[0] != threading.get_ident()
        cache.assign(label, None, 32)
    finally:
        gate.set()
    wait_until(lambda: not cache.pending)
    assert label.text() == "—" and label.pixmap().isNull()
    assert not other.pixmap().isNull()
    print("OK: descarga deduplicada fuera de GUI, event loop libre y respuesta obsoleta descartada")

    missing = Mock(return_value=None)
    cache.assign(label, ("missing",), 32, missing)
    wait_until(lambda: not cache.pending)
    count = missing.call_count
    for _ in range(10):
        cache.assign(label, ("missing",), 32, missing)
    assert missing.call_count == count
    cache.failed[("missing",)] -= cache.RETRY_SECONDS + 1
    cache.assign(label, ("missing",), 32, missing)
    wait_until(lambda: not cache.pending)
    assert missing.call_count == count + 2
    print("OK: fallo con pausa de reintento, no tormenta de peticiones")

    cache.LIMIT = 4
    for i in range(10):
        cache.assign(other, (i,), 32, lambda **kw: path)
    assert len(cache.pixmaps) <= cache.LIMIT

    # Destruir el receptor mientras el worker está activo no debe tocar Qt eliminado.
    gate.clear()
    started.clear()
    doomed = DraftIconCache()
    doomed.assign(label, ("closing",), 32, delayed)
    wait_until(started.is_set)
    delete(doomed)
    gate.set()
    assert QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    print("OK: caché acotada y destrucción con tarea pendiente")

    # Verificación del contrato local-only con todos los getters reales.
    for name, value in (
        ("DATA_DIR", Path(temp)), ("ICON_DIR", Path(temp)),
        ("CHAMPION_ICON_DIR", Path(temp)), ("SPELL_ICON_DIR", Path(temp)),
    ):
        stack.enter_context(patch.object(dd, name, value))
    assert dd.get_item_icon_path("absent", {}, "fixture", download=False) is None
    assert dd.get_champion_icon_path("Absent", "fixture", download=False) is None
    assert dd.get_rune_icon_path("Absent", "fixture", download=False) is None
    assert dd.get_spell_icon_path("Absent", "fixture", download=False) is None
    network.assert_not_called()
    dialog.close()

print("TODAS LAS PRUEBAS DE RENDIMIENTO PASARON")