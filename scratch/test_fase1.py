"""Smoke test de la RecommendationPanel (Fase 1).

Ejecutar:  python scratch/test_fase1.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app.ui.recommendation_panel import RecommendationPanel

def test_panel_creation():
    app = QApplication.instance() or QApplication(sys.argv)
    panel = RecommendationPanel()
    assert panel is not None
    assert panel.objectName() == "recommendationPanel"
    panel.update_recommendations({})  # No debe fallar
    print("[OK] Fase 1 OK")

if __name__ == "__main__":
    test_panel_creation()