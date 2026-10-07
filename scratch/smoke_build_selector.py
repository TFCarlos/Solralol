"""Smoke: selector de build por página de runas + cuadrícula de habilidades."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.ui.local_analysis_dialog import LocalAnalysisDialog  # noqa: E402


def count_painted(dialog: LocalAnalysisDialog) -> int:
    """Celdas de la cuadrícula de habilidades con el icono de la habilidad."""
    return sum(
        1
        for row in range(0, 4)
        for col in range(1, 19)
        if (item := dialog.skill_order_grid.itemAtPosition(row, col))
        and item.widget()
        and item.widget().objectName() == "localSkillOrderCellActive"
    )


def grid_rows(dialog: LocalAnalysisDialog) -> list[str]:
    """Letra pintada por cada celda de la cuadrícula (fila Q/W/E/R)."""
    rows: list[str] = []
    for row in range(0, 4):
        letters = ""
        for col in range(1, 19):
            item = dialog.skill_order_grid.itemAtPosition(row, col)
            name = item.widget().objectName() if item and item.widget() else ""
            letters += "X" if name == "localSkillOrderCellActive" else "."
        rows.append(letters)
    return rows


def grid_cell_counts(dialog: LocalAnalysisDialog) -> list[int]:
    """Widgets por celda del grid de BUILD: debe ser 0 o 1 (nunca apilados)."""
    counts = [0] * 6
    for index in range(dialog.build_grid.count()):
        if dialog.build_grid.itemAt(index) is None:
            continue
        if dialog.build_grid.itemAt(index).widget() is None:
            continue
        row, col, _, _ = dialog.build_grid.getItemPosition(index)
        if 0 <= row < 2 and 0 <= col < 3:
            counts[row * 3 + col] += 1
    return counts


def build_names(dialog: LocalAnalysisDialog) -> list[str]:
    """Nombres de la build mostrada, para detectar duplicados."""
    found: list[str] = []
    for row in (0, 1):
        for col in range(3):
            item = dialog.build_grid.itemAtPosition(row, col)
            widget = item.widget() if item else None
            if widget is None:
                continue
            for label in widget.findChildren(QLabel):
                text = label.text().strip()
                if text:
                    found.append(text)
    return found


def situational_names(dialog: LocalAnalysisDialog) -> list[str]:
    found: list[str] = []
    for index in range(dialog.situational_items_row.count()):
        widget = dialog.situational_items_row.itemAt(index).widget()
        if widget is None:
            continue
        for label in widget.findChildren(QLabel):
            text = label.text().strip()
            if text:
                found.append(text)
    return found


app = QApplication.instance() or QApplication([])

# Perfil sintético con 2 páginas de runas, cada una con SU build y SU skill order.
dialog = LocalAnalysisDialog()
# Se aísla de la variante real en disco para que mande el perfil sintético.
dialog._active_variant = None
dialog._active_variant_key = ""
profile = {
    "character": "Aatrox",
    "basic_info": {"play_style": "Diver", "damage_type": "AD", "flex_potential": ["Top"]},
    "most_played_build": ["Perfil A1", "Perfil A2", "Perfil A3", "Perfil A4", "Perfil A5", "Perfil A6"],
    "skill_order": {"order": ["Q"] * 18, "priority": "Q"},
    "runes": [
        {
            "name": "Página 1 U.GG", "source": "U.GG", "keystone": "Conqueror",
            "primary_tree": "Precision", "secondary_tree": "Resolve",
            "slots": ["Triumph", "Legend: Alacrity", "Coup de Grace"],
            "secondary_slots": ["Overgrowth", "Revitalize"], "shards": ["Adaptive Force"] * 3,
            "win_rate": 0.51, "games": 1000,
            # Botas intercaladas + objeto repetido: reproduce el caso que fallaba.
            "build": ["Eclipse", "Botas blindadas", "Lanza de Shojin",
                      "Baile de la muerte", "Firmamento desgarrado", "Baile de la muerte"],
            "skill_order": {"order": ["Q", "E", "W"] * 6, "priority": "QEW"},
        },
        {
            "name": "Página 2 U.GG", "source": "U.GG", "keystone": "Grasp of the Undying",
            "primary_tree": "Resolve", "secondary_tree": "Sorcery",
            "slots": ["Conditioning", "Second Wind", "Overgrowth"],
            "secondary_slots": ["Nimbus Cloak", "Transcendence"], "shards": ["Health Scaling"] * 3,
            "win_rate": 0.53, "games": 500,
            "build": ["ALT1", "ALT2", "ALT3", "ALT4", "ALT5", "ALT6"],
            "skill_order": {"order": ["W", "Q", "E"] * 6, "priority": "WQE"},
        },
    ],
    "situational_items": {
        "corta_curas": ["Morellomicón"],
        # Eclipse y Baile de la muerte están en la build: no deben salir aquí.
        "tanque": ["Eclipse", "Malla de espinas", "Baile de la muerte"],
        "asesino": [],
        "utilidad_y_defensa": [],
    },
}
dialog._refresh_analysis(profile)

print("páginas detectadas:", len(dialog._rune_pages))
print("selección inicial:", dialog._selected_rune_page)
print("build inicial:", dialog._active_build(profile))
print("orden inicial:", dialog._active_rune_page_skill_order(profile))

# --- BUG 1: cada habilidad en SU fila (Q/W/E/R) y 18 columnas ---
print("\n=== habilidades (filas Q, W, E, R | 18 niveles) ===")
for key, letters in zip("QWER", grid_rows(dialog)):
    print(f"  {key}: {letters}")
print("celdas con icono (esperado 18):", count_painted(dialog))
print("prioridad:", dialog.skill_order_priority.text())
print("cabecera de niveles:", dialog.skill_order_levels.text()[:28], "...")
print("tamaño del panel:", dialog.skill_order_panel.sizeHint().width(), "x",
      dialog.skill_order_panel.sizeHint().height())

# --- BUG 2: sin widgets apilados en el grid de build ---
print("\n=== grid de build ===")
print("widgets por celda (esperado 0/1):", grid_cell_counts(dialog))
print("objetos mostrados:", build_names(dialog))

# --- BUG 3: sin objetos duplicados en la build ---
shown = build_names(dialog)
print("duplicados (esperado []):", [n for n in set(shown) if shown.count(n) > 1])

# --- BUG 4: los situacionales no repiten objetos de la build ---
sit = situational_names(dialog)
print("situacionales:", sit)
print("intersección con la build (esperada []):", [n for n in sit if n in shown])

# Click en la página 2 -> debe cambiar la build y el orden de habilidades.
print("\n--- click en página 2 ---")
dialog._on_rune_page_clicked(1)
print("selección:", dialog._selected_rune_page)
print("build tras click:", dialog._active_build(profile))
print("orden tras click:", dialog._active_rune_page_skill_order(profile))
print("celdas pintadas (esperado 18):", count_painted(dialog))
print("widgets por celda (esperado 0/1):", grid_cell_counts(dialog))
print("objetos tras click:", build_names(dialog))
after = build_names(dialog)
print("duplicados (esperado []):", [n for n in set(after) if after.count(n) > 1])
for key, letters in zip("QWER", grid_rows(dialog)):
    print(f"  {key}: {letters}")
print("resaltada:", [c.property("selected") for c in dialog._rune_page_cards])
print("status:", dialog.status.text())
