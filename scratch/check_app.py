"""Verificación de arranque y de los módulos del repaso.

Ejecutar:  python scratch/check_app.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FILES = [
    "app/ui/postgame_sidebar.py",
    "app/ui/postgame_replay_window.py",
    "app/ui/main_window.py",
    "app/services/recording_service.py",
    "app/ui/styles.py",
]

import py_compile

for path in FILES:
    full = os.path.join(REPO, path)
    try:
        py_compile.compile(full, doraise=True)
        print("COMPILE OK   ", path)
    except Exception as error:
        print("COMPILE FAIL ", path, "->", error)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except Exception as error:  # pragma: no cover
    print("QT IMPORT FAIL", error)
    raise SystemExit(1)

app = QApplication.instance() or QApplication([])

from app.ui.postgame_sidebar import (  # noqa: E402
    PostgameSidebar,
    player_build_items,
)
from app.ui.postgame_replay_window import PostgameReplayWindow  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.services.recording_service import (  # noqa: E402
    QUALITY_PRESETS,
    RecordingLibrary,
)

print("IMPORTS OK: sidebar, replay, main_window")

session = {
    "session_id": "sesion-local-1",
    "champion_name": "Briar",
    "game_mode": "CLASSIC",
    "duration": 1800.0,
    "local_player_key": "local",
    "local_team": "ORDER",
    "players": {
        "local": {"champion_name": "Briar", "role": "JUNGLE", "team": "ORDER"},
        "ally2": {"champion_name": "Ahri", "role": "MIDDLE", "team": "ORDER"},
        "enemy1": {"champion_name": "Lee Sin", "role": "JUNGLE", "team": "CHAOS"},
        "enemy2": {"champion_name": "Yasuo", "role": "MIDDLE", "team": "CHAOS"},
    },
    "final_scoreboard": {
        "local": {"items": [3008, 3153, 6672]},
    },
    "snapshots": [
        {
            "time": 900.0,
            "players": {
                "local": {
                    "kills": 7,
                    "deaths": 2,
                    "assists": 5,
                    "cs": 150,
                    "level": 12,
                    "estimated_gold": 12500,
                    "stats": {"vision_score": 24},
                    "items": [3008, 3153, 6672, 3006, 1031],
                }
            },
        }
    ],
    "events": [
        {
            "time": 600.0,
            "order": 1,
            "type": "kill_exact",
            "player_key": "local",
            "killer_key": "local",
            "victim_key": "enemy1",
            "team": "ORDER",
            "role": "JUNGLE",
            "label": "Briar asesino a Lee Sin",
        }
    ],
}

sidebar = PostgameSidebar(session)

from PySide6.QtWidgets import QFrame, QLabel  # noqa: E402

cards = sidebar.findChildren(QFrame, "postgamePlayerCard")
names = [label.text() for label in sidebar.findChildren(QLabel, "postgameChampionName")]
kdas = [label.text() for label in sidebar.findChildren(QLabel, "postgameStatKda")]

print("TARJETAS:", len(cards))
print("CAMPEONES:", names)
print("KDA:", kdas)
print("BUILD local:", player_build_items(session, "local"))

assert len(cards) == 4, "se esperaban 4 tarjetas (2 aliados + 2 enemigos)"
assert "Briar" in names, "falta el campeon local"
assert "7 / 2 / 5" in kdas, "KDA local inesperado"
assert player_build_items(session, "local")[0] == 3008, "build local inesperado"

print("SIDEBAR VS OK")

sidebar.close()
sidebar.deleteLater()
app.processEvents()

# --- 1) Pantalla completa: el vídeo conserva la barra de reproducción --
window = PostgameReplayWindow(session=session)

window.toggle_fullscreen()
fs_window = window._fs_window
assert fs_window is not None, "debe crearse la ventana de pantalla completa"
assert fs_window.isVisible(), "el vídeo debe pasar a pantalla completa"
assert window.video_widget.parent() is window._fs_video_host, (
    "el vídeo debe vivir en la ventana de pantalla completa"
)
assert window.marker_slider.window() is fs_window, (
    "la barra de reproducción debe acompañar al vídeo en pantalla completa"
)
assert window.transport_row.window() is fs_window, (
    "los controles (play/pausa, saltos, tiempo) deben seguir visibles"
)
assert "Salir" in window.fullscreen_button.text()
print("PANTALLA COMPLETA:", window.fullscreen_button.text())

window.toggle_fullscreen()
assert not fs_window.isVisible(), "se debe poder salir de pantalla completa"
assert window.marker_slider.window() is window, "la barra vuelve a la tarjeta"
layout = window._card_layout
assert layout.itemAt(0).widget() is window.video_widget
assert layout.itemAt(1).widget() is window.marker_slider
assert layout.itemAt(2).widget() is window.transport_row
print("PANTALLA COMPLETA CON BARRA VISIBLE OK")

window.close()
window.deleteLater()
app.processEvents()

# --- 2) Pestaña LIVE con datos y timers del diálogo LIVE -------------
from app.services.data_dragon_assets import DataDragonAssetService  # noqa: E402
from data_dragon import load_item_catalog  # noqa: E402

try:
    version, item_catalog = load_item_catalog()
except Exception:
    version, item_catalog = "15.16.1", {}

assets = DataDragonAssetService()
live_window = PostgameReplayWindow(
    session=session, assets=assets, item_catalog=item_catalog
)
tabs = live_window.sidebar.tabs
print("PESTANAS:", [tabs.tabText(index) for index in range(tabs.count())])
assert tabs.count() == 3, "debe existir la pestaña Análisis LIVE"
assert live_window.live_view is not None, "el diálogo LIVE debe ir incrustado"
assert live_window.live_view.session["session_id"] == "sesion-local-1"

updated = dict(session)
updated["duration"] = 1900.0
live_window.update_session(updated)

if getattr(live_window.live_view, "_pending_session", None) is not None:
    live_window.live_view._flush_session()

print("LIVE DURATION:", live_window.live_view.session.get("duration"))
assert float(live_window.live_view.session.get("duration") or 0) == 1900.0
print("PESTANA LIVE CON DATOS Y TIMERS OK")

live_window.close()
live_window.deleteLater()
app.processEvents()

# --- 3) Ajustes: 720p/900p/1080p a 30 FPS ---------------------------
for key, label in (
    ("72030", "720p · 30 FPS"),
    ("90030", "900p · 30 FPS"),
    ("108030", "1080p · 30 FPS"),
):
    assert QUALITY_PRESETS.get(key, {}).get("label") == label, key

print(
    "PRESETS 30FPS OK:",
    [QUALITY_PRESETS[key]["label"] for key in ("72030", "90030", "108030")],
)

main_window = None
try:
    main_window = MainWindow(version=version, item_catalog=item_catalog)
    labels = [
        main_window.recording_quality_combo.itemText(index)
        for index in range(main_window.recording_quality_combo.count())
    ]
    print("COMBO CALIDADES:", labels)
    for wanted in ("720p · 30 FPS", "900p · 30 FPS", "1080p · 30 FPS"):
        assert wanted in labels, wanted
    print("AJUSTES CON 30FPS OK")
except Exception as error:
    print("AJUSTES: no se pudo abrir MainWindow ->", error)
finally:
    if main_window is not None:
        main_window.close()
        main_window.deleteLater()
        app.processEvents()

# --- 4) Datos reales (si están en el equipo) ------------------------
real_dir = Path(r"D:\JuegosDudosos\VIDEOS_SOLRALOL")
real_video = real_dir / "Solralol_2026-09-20_02-36-07_Briar.mp4"

if real_video.is_file():
    real_window = PostgameReplayWindow(
        video_path=real_video, library=RecordingLibrary(real_dir)
    )
    real_cards = real_window.sidebar.findChildren(QFrame, "postgamePlayerCard")
    owners = [
        event["player_name"] for event in real_window.sidebar.review_events
    ]
    print("REAL session:", real_window.session.get("session_id"))
    print(
        "REAL jugadores:",
        len(real_window.session.get("players") or {}),
        "| eventos:",
        len(real_window.session.get("events") or []),
    )
    print(
        "REAL tarjetas:",
        len(real_cards),
        "| revision:",
        len(real_window.sidebar.review_events),
        "| duenos:",
        [name for name in owners if name][:5],
    )
    assert real_window.session.get("players"), "debe adoptar la sesión real"
    assert len(real_cards) >= 4, "el marcador real debe listar jugadores"
    assert any(owners), "la revisión debe identificar al jugador del suceso"
    print("DATOS REALES OK")
    real_window.close()
    real_window.deleteLater()
    app.processEvents()
else:
    print("REAL: vídeo no encontrado, se omite")

# Arranque real de la aplicación (se cierra sola pasados unos segundos).
python = sys.executable
env = dict(os.environ)
env.setdefault("QT_QPA_PLATFORM", "offscreen")
proc = subprocess.Popen(
    [python, os.path.join(REPO, "main.py")],
    cwd=REPO,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    env=env,
    creationflags=0x08000000,
)
time.sleep(6)
try:
    proc.kill()
except Exception:
    pass
output, _ = proc.communicate(timeout=5)

problems = [
    line
    for line in output.splitlines()
    if "Traceback" in line
    or "Error:" in line
    or "ImportError" in line
    or "NameError" in line
    or "SyntaxError" in line
    or "AttributeError" in line
]

if problems:
    print("ARRANQUE CON ERRORES:")
    for line in problems:
        print("  ", line)
else:
    print("ARRANQUE OK: main.py inicio sin errores en 6 s")
