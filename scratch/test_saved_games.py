"""Pruebas sin red ni acceso a partidas reales: python -m unittest scratch.test_saved_games."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.ui.main_window import MainWindow
from app.ui.styles import CONTROL_WINDOW_STYLE


class SavedGamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = SimpleNamespace(
            postgame_sync_in_progress=False,
            format_match_duration=MainWindow.format_match_duration,
            format_saved_session_date=lambda value: "17/09/2026 00:24",
            request_saved_session_sync=Mock(),
            request_resync_session=Mock(),
            open_saved_game_analysis=Mock(),
            delete_saved_game_session=Mock(),
        )
        self.rows = []

    def tearDown(self):
        for row in self.rows:
            row.close()
            row.deleteLater()
        self.app.processEvents()

    def session(self, win=None, status="live_only", mode="CLASSIC"):
        return {
            "session_id": "test-session",
            "champion_name": "Briar",
            "game_mode": mode,
            "duration": 2319,
            "local_player_key": "local",
            "players": {"local": {"win": win}, "enemy": {"win": True}},
            "events": [{}, {}],
            "final_sync": {"status": status, "message": "Detalle de sincronización"},
        }

    def row(self, session):
        row = MainWindow.create_saved_game_row(self.host, session)
        row.setStyleSheet(CONTROL_WINDOW_STYLE)
        row.ensurePolished()
        self.rows.append(row)
        return row

    def button(self, row, text):
        return next(b for b in row.findChildren(QPushButton) if b.text() == text)

    def test_results_are_independent_from_sync(self):
        for win, state, text in (
            (True, "win", "VICTORIA"),
            (False, "loss", "DERROTA"),
            (None, "unknown", "Sin resultado"),
            ("false", "unknown", "Sin resultado"),
        ):
            for status in ("synced", "live_only", "pending", "failed", "not_found"):
                with self.subTest(win=win, status=status):
                    row = self.row(self.session(win, status))
                    badge = row.findChild(QLabel, "savedGameResult")
                    self.assertEqual(row.property("result"), state)
                    self.assertEqual(badge.text(), text)
                    self.assertEqual(badge.property("result"), state)

    def test_missing_local_player_does_not_use_enemy_result(self):
        session = self.session()
        session["local_player_key"] = "missing"
        self.assertEqual(self.row(session).property("result"), "unknown")
        session.pop("local_player_key")
        self.assertEqual(self.row(session).property("result"), "unknown")
        self.assertEqual(self.row({}).property("result"), "unknown")

    def test_actions_keep_original_arguments(self):
        session = self.session(True, "synced")
        row = self.row(session)
        self.button(row, "Re-sincronizar").click()
        self.button(row, "Abrir análisis").click()
        self.button(row, "Eliminar").click()
        self.host.request_resync_session.assert_called_once_with("test-session")
        self.host.open_saved_game_analysis.assert_called_once_with(session)
        self.host.delete_saved_game_session.assert_called_once_with("test-session")

        row = self.row(self.session())
        self.button(row, "Buscar Riot").click()
        self.host.request_saved_session_sync.assert_called_once_with("test-session")

    def test_disabled_actions(self):
        for mode in ("PRACTICETOOL", "TUTORIAL", "CUSTOM_GAME"):
            self.assertFalse(self.button(self.row(self.session(mode=mode)), "Buscar Riot").isEnabled())
        self.host.postgame_sync_in_progress = True
        self.assertFalse(self.button(self.row(self.session()), "Buscar Riot").isEnabled())
        self.assertFalse(self.button(self.row(self.session(status="synced")), "Re-sincronizar").isEnabled())
        self.assertFalse(self.button(self.row({}), "Eliminar").isEnabled())

    def test_layout_and_metadata(self):
        for width in (1000, 1400, 2400):
            row = self.row(self.session(True, "synced"))
            row.resize(width, row.sizeHint().height())
            row.show()
            self.app.processEvents()
            self.assertLessEqual(row.minimumSizeHint().width(), width)
            badge = row.findChild(QLabel, "savedGameResult")
            self.assertGreaterEqual(badge.width(), badge.sizeHint().width())
            self.assertEqual(row.findChild(QLabel, "savedGameSync").toolTip(), "Detalle de sincronización")
            self.assertEqual(row.findChild(QLabel, "savedGameTitle").textFormat(), Qt.TextFormat.PlainText)
            for button in row.findChildren(QPushButton):
                self.assertEqual(button.height(), 36)
                self.assertTrue(row.rect().contains(button.geometry()))
            for label in row.findChildren(QLabel):
                self.assertTrue(row.rect().contains(label.geometry()))


if __name__ == "__main__":
    unittest.main()