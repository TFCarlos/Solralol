import sys
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