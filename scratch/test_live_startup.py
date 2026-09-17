"""Smoke con servicios reales y GUI nativa.

Ejecutar: .venv\\Scripts\\python.exe -m scratch.test_live_startup
Requiere el mismo acceso a red que main.py. No invoca Gemini ni guarda
la sesión sintética. Cierra únicamente las ventanas de este proceso.
"""
import os
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import main
from scratch.test_live_analysis import session_fixture

state = {"opened": False, "updated": False, "finished": False, "errors": []}


def fail(kind, value, tb):
    traceback.print_exception(kind, value, tb)
    state["errors"].append(str(value))
    QApplication.closeAllWindows()
    QApplication.instance().quit()


def check():
    window = next(w for w in QApplication.topLevelWidgets() if isinstance(w, main.MainWindow))
    assert window.isVisible(), "MainWindow no visible"
    # Use exactly the production entry point, not a parallel construction.
    window.current_live_session = session_fixture(1000, 120)
    window.open_live_analysis()
    state["window"] = window
    state["dialog"] = window.live_analysis_dialog
    state["opened"] = True
    state["deadline"] = time.monotonic() + 60
    QTimer.singleShot(500, update)


def update():
    d = state["dialog"]
    assert d.isVisible()
    assert d.timeline_view.model().rowCount() == 1001
    d.show_role("MIDDLE")
    d.show_role("TOP")
    d._change_timeline_mode("global")
    assert d.timeline_view.model().rowCount() == 2
    d.show_ai_analysis()
    d.update_session(session_fixture(1100, 130))
    assert d.current_view == "ai_analysis"
    d.show_role("TOP")
    d._change_timeline_mode("lane")
    assert d.timeline_view.model().rowCount() == 1101
    state["updated"] = True
    QTimer.singleShot(500, finish)


def finish():
    d = state["dialog"]
    if d._stats_task is not None and time.monotonic() < state["deadline"]:
        QTimer.singleShot(500, finish)
        return
    assert d._post_stats, "No llegaron estadísticas"
    assert d._post_stats["TOP_a"]["hp"] > 0
    state["finished"] = True
    print("SMOKE: ventana visible, diálogo LIVE, filtros, actualización y estadísticas OK", flush=True)
    QApplication.closeAllWindows()
    QApplication.instance().quit()


class SmokeApplication(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        QTimer.singleShot(1500, check)
        QTimer.singleShot(90000, self.quit)


def run():
    original_app, original_hook = main.QApplication, sys.excepthook
    main.QApplication = SmokeApplication
    sys.excepthook = fail
    try:
        code = main.main()
        assert code == 0, code
        assert all(state[k] for k in ("opened", "updated", "finished")), state
        assert not state["errors"], state["errors"]
        print("MAIN + LIVE DIALOG + UPDATE + CLEAN EXIT: OK", flush=True)
    finally:
        main.QApplication = original_app
        sys.excepthook = original_hook


if __name__ == "__main__":
    run()