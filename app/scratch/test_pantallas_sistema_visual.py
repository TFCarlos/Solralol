"""Construcción y navegación de pantallas reales con integraciones externas simuladas."""

import os
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFontDatabase, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QTabWidget, QWidget

from app.services.settings_service import SettingsService
from app.services.tab_hotkey_service import TabHotkeyService
from app.ui.draft_icon_cache import DraftIconCache
from app.ui.draft_tool_dialog import DraftToolDialog
from app.ui.live_match_analysis_dialog import LiveMatchAnalysisDialog
from app.ui.main_window import MainWindow
from app.ui.match_inspector_dialog import MatchInspectorDialog
from app.ui.postgame_replay_window import PostgameReplayWindow
from app.ui.postgame_sidebar import EventRow, PostgameSidebar
from app.ui.startup_window import StartupWindow
from app.ui.tema import instalar_sistema_visual

pytest_plugins = ["app.scratch.test_carga_analisis_local"]


class RecursosPrueba(QObject):
    """Contrato de recursos gráficos sin descargas ni credenciales."""

    image_ready = Signal(str, QPixmap)
    version = "16.17.1"

    def champion_url(self, nombre: str) -> str:
        """Devuelve identificador vacío para el campeón recibido."""
        return ""

    def item_url(self, identificador: object) -> str:
        """Devuelve identificador vacío para el objeto recibido."""
        return ""

    def set_label_image(self, label: QLabel, *args: object, **kwargs: object) -> None:
        """Conserva el fallback del label recibido sin acceder a red."""
        return None


@pytest.fixture
def ventana_global(
    aplicacion: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> MainWindow:
    """Construye todas las páginas reales aislando workers, ajustes y LCU."""
    for fuente in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + fuente)
    instalar_sistema_visual(aplicacion)
    monkeypatch.setattr(
        SettingsService, "load", lambda self: {"recording_output_dir": str(tmp_path)}
    )
    monkeypatch.setattr(SettingsService, "save", Mock())
    monkeypatch.setattr(TabHotkeyService, "start", Mock())
    monkeypatch.setattr(TabHotkeyService, "stop", Mock())
    for metodo in (
        "_start_background_ffmpeg_check",
        "setup_live_data_worker",
        "synchronize_home_history",
        "setup_postgame_sync_worker",
        "setup_champ_select_worker",
        "request_snapshot",
        "refresh_saved_games",
        "refresh_recording_devices",
        "refresh_system_audio_devices",
        "showMaximized",
    ):
        monkeypatch.setattr(MainWindow, metodo, Mock())
    monkeypatch.setattr(
        "app.services.home_history_service.HomeHistoryRepository.load_last_profile",
        lambda self: None,
    )
    monkeypatch.setattr("app.ui.main_window.DataDragonAssetService", RecursosPrueba)
    monkeypatch.setattr(DraftToolDialog, "_check_lcu_status", Mock())
    monkeypatch.setattr(DraftIconCache, "assign", Mock())
    monkeypatch.setattr(PostgameSidebar, "_warm_icons", Mock())
    ventana = MainWindow("16.17.1", {})
    ventana.poll_timer.stop()
    ventana.resize(1500, 1000)
    ventana.show()
    for _ in range(15):
        aplicacion.processEvents()
    yield ventana
    ventana.hide()
    for dialogo in ventana.findChildren(QWidget):
        if isinstance(dialogo, LiveMatchAnalysisDialog):
            dialogo._refresh_timer.stop()
    ventana.overlay.close()
    ventana.pages.widget(1).close()
    ventana.recordings_page.player.stop()
    ventana.deleteLater()
    aplicacion.processEvents()


def test_shell_completo_y_draft(
    ventana_global: MainWindow, aplicacion: QApplication
) -> None:
    """Verifica siete destinos, draft único incrustado y actualización LCU oculta."""
    ventana = ventana_global
    assert ventana.pages.count() == 7
    for indice in range(6):
        ventana.pages.setCurrentIndex(indice)
        for _ in range(10):
            aplicacion.processEvents()
        assert not ventana.grab().isNull()
    ventana.open_draft_tool_dialog()
    draft = ventana.draft_tool_dialog
    assert draft is ventana.pages.widget(6) and not draft.isWindow()
    ventana.open_draft_tool_dialog()
    assert ventana.pages.count() == 7 and ventana.draft_tool_dialog is draft
    assert ventana.draft_nav_button.isChecked()
    assert len(draft.my_team_combo_widgets) == len(draft.enemy_team_combo_widgets) == 5
    assert all(
        isinstance(control, QCheckBox) for control in draft.my_team_pick_state_widgets
    )
    ventana.pages.setCurrentIndex(0)
    draft.update_from_lcu_session = Mock()
    ventana._on_champ_select_updated({"test": True})
    draft.update_from_lcu_session.assert_called_once()
    ventana._on_champ_select_ended()
    ajustes = ventana.pages.widget(5).findChild(QTabWidget, "settingsTabs")
    assert ajustes.count() == 4
    for indice in range(4):
        ajustes.setCurrentIndex(indice)
        assert ajustes.widget(indice).widget().layout().count() == 2


@pytest.mark.parametrize(
    "ancho,alto", [(1000, 700), (1500, 1000), (1920, 1080), (2560, 1080)]
)
def test_tamanos_shell(
    ventana_global: MainWindow, aplicacion: QApplication, ancho: int, alto: int
) -> None:
    """Revisa geometría del shell y reflujo en mínimo, escritorio y ultrawide."""
    ventana = ventana_global
    ventana.resize(ancho, alto)
    for _ in range(15):
        aplicacion.processEvents()
    assert ventana.width() == ancho
    assert ventana.pages.width() > 500
    assert ventana.pages.geometry().right() <= ventana.pages.parentWidget().width()
    assert not ventana.grab().isNull()


def test_ventanas_secundarias(
    ventana_global: MainWindow,
    aplicacion: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Renderiza arranque, inspector, análisis live, postpartida y evento valorado."""
    recursos = RecursosPrueba()
    monkeypatch.setattr(LiveMatchAnalysisDialog, "_prepare_session", Mock())
    inspector = MatchInspectorDialog(
        {"champion_name": "Aatrox", "allies": [], "enemies": []}, assets=recursos
    )
    live = LiveMatchAnalysisDialog({}, recursos, {})
    repaso = PostgameReplayWindow(library=ventana_global.recording_library)
    arranque = StartupWindow("Preparando interfaz", "Datos locales")
    fila = EventRow(
        {
            "kind": "death",
            "side": "ally",
            "time": 90,
            "label": "Muerte",
            "detail": "Retírate sin visión",
        }
    )
    for componente in (inspector, live, repaso, arranque, fila):
        componente.show()
        for _ in range(10):
            aplicacion.processEvents()
        assert not componente.grab().isNull()
    assert fila.property("estado") == "error"
    arranque.stop()
    inspector.close()
    live._refresh_timer.stop()
    live.hide()
    repaso.player.stop()
    repaso.hide()
    fila.close()
