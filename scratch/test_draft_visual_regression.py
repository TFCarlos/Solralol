"""Regresión visual determinista: sin cliente LCU ni descargas.

Ejecutar desde la raíz:
    .venv/Scripts/python.exe -X utf8 scratch/test_draft_visual_regression.py

Las secciones inferiores se prueban a 1024 px de forma aislada.
La ventana completa conserva su mínimo de 1180 px.
"""
from __future__ import annotations

import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QFontDatabase, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from app.ui import draft_tool_dialog as ui

app = QApplication.instance() or QApplication([])
font = Path("C:/Windows/Fonts/segoeui.ttf")
if font.exists():
    QFontDatabase.addApplicationFont(str(font))

analyzer = MagicMock()
analyzer.champions = {"266": {"character": "Aatrox"}}
analyzer.items = {}
analyzer.calculate_team_damage_breakdown.return_value = {
    "physical": 80.0, "magic": 15.0, "true": 5.0,
}
analyzer.calculate_team_power_curve.return_value = {
    bracket: 50.0 for bracket in ui.DraftPowerCurveWidget.TIME_BRACKETS
}
analyzer.analyze_power_spike_phase.return_value = "Equilibrado"
analyzer.get_champion_overall_win_rate.return_value = 50.0
analyzer.get_recommended_bans.return_value = [
    {"champion": name, "win_rate": rate,
     "tip": f"Aatrox gana el {rate}% frente a {name}. Juega con cautela."}
    for name, rate in (("Naafiri", 42.2), ("Ahri", 44.2), ("Singed", 45.8))
]
analyzer.get_champion_build.return_value = {
    "items": [{"id": str(i), "name": f"Objeto {i}"} for i in range(6)],
    "boots": {"id": "3111", "name": "Botas de mercurio"},
    "boots_reason": "Resistencia mágica y tenacidad.",
    "note": "La sexta compra es una alternativa tardía.",
}
page = {
    "keystone": "Conqueror",
    "slots": ["Triumph", "Legend: Haste", "Last Stand"],
    "secondary_slots": ["Revitalize", "Bone Plating"],
    "shards": ["Adaptive Force", "Adaptive Force", "Health Scaling"],
}
analyzer.get_champion_runes_and_summoners.return_value = {
    "page_1": page, "page_2": page, "spells": ("Destello", "Ignición"),
}

with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
    icon_path = Path(temp) / "icon.png"
    icon = QPixmap(64, 64)
    icon.fill(QColor("#D9AE4F"))
    assert icon.save(str(icon_path))
    stack.enter_context(patch.object(ui, "DraftAnalyzerService", return_value=analyzer))
    stack.enter_context(patch.object(ui, "LCUService"))
    stack.enter_context(patch.object(ui, "get_latest_version", return_value="fixture"))
    stack.enter_context(patch.object(ui.DraftToolDialog, "_check_lcu_status"))
    for getter in ("get_champion_icon_path", "get_item_icon_path",
                   "get_rune_icon_path", "get_spell_icon_path"):
        stack.enter_context(patch.object(ui, getter, return_value=icon_path))

    dialog = ui.DraftToolDialog()
    host = QWidget()
    layout = QVBoxLayout(host)
    sections = [
        dialog.findChild(QFrame, name)
        for name in ("draftBansSection", "draftImportSection")
    ]
    for section in sections:
        assert section is not None
        layout.addWidget(section)
    host.show()

    for _ in range(3):
        dialog._update_analytics()
        assert all(not card["icon"].pixmap().isNull()
                   for card in dialog.ban_card_widgets)
    print("OK: retratos conservados tras tres recargas")

    for width in (1024, 1120, 1400):
        host.resize(width, 620)
        app.processEvents()
        assert host.width() == width, ("desbordamiento del contenedor", width)
        for section in sections:
            assert host.rect().contains(section.geometry())
            for widget in section.findChildren(QWidget):
                assert widget.parentWidget().rect().contains(widget.geometry()), (
                    width, widget.objectName(), widget.geometry(),
                )
            assert not section.grab().isNull()
        cards = [card["icon"].parentWidget() for card in dialog.ban_card_widgets]
        assert len({card.y() for card in cards}) == 1
        assert max(c.width() for c in cards) - min(c.width() for c in cards) <= 1
        for button in (dialog.btn_import_build, dialog.btn_import_ugg,
                       dialog.btn_import_lolalytics, dialog.btn_import_spells):
            assert button.width() >= button.sizeHint().width(), button.text()
        print(f"OK: secciones sin desbordamiento a {width} px")

    for section in sections:
        # Todos los selectores de contenedor son específicos; no hay una
        # declaración desnuda de QFrame que alcance también a sus QLabel.
        for frame in [section, *section.findChildren(QFrame)]:
            if isinstance(frame, QLabel):
                continue
            sheet = frame.styleSheet()
            assert "QFrame {" not in sheet
            assert not sheet.strip().startswith(("background:", "background-color:"))
        for label in section.findChildren(QLabel):
            if not label.objectName():
                assert label.frameWidth() == 0, label.text()
    assert all(len(row["icons"]) == 9 for row in dialog.rune_page_rows.values())
    print("OK: textos sin bordes heredados y nueve huecos por página")

    analyzer.get_recommended_bans.return_value = []
    dialog._update_analytics()
    assert all(card["icon"].pixmap().isNull() and card["icon"].text() == "—"
               for card in dialog.ban_card_widgets)
    print("OK: estado vacío sin retratos residuales")
    host.close()
    dialog.close()

print("TODAS LAS PRUEBAS VISUALES PASARON")