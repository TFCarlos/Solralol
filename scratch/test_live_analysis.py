"""Regresión LIVE sin red: python -m unittest scratch.test_live_analysis -v."""
import os
import threading
import time
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QWidget, QFrame

from app.ui.live_match_analysis_dialog import LiveMatchAnalysisDialog, VersusChart, RiotComparisonBar
from app.services.live_analysis_models_and_calculator import attach_achievements
from shiboken6 import isValid
from app.ui.live_timeline import TimelineModel, TimelineView
from app.ui.styles import CONTROL_WINDOW_STYLE


def session_fixture(count=1000, snapshots=120):
    players, matchups = {}, {}
    for role in LiveMatchAnalysisDialog.ROLE_LABELS:
        a, b = role + "_a", role + "_b"
        matchups[role] = {"ally_key": a, "enemy_key": b}
        for key, champion, team in ((a, "Ahri", "ORDER"), (b, "Sylas", "CHAOS")):
            players[key] = {"champion_name": champion, "riot_id": key,
                            "role": role, "team": team, "items": [1001]}
    events = [
        {"time": i * 2, "order": i, "type": "item_purchased", "item_id": 1001,
         "player_key": "TOP_a" if i % 2 == 0 else "TOP_b"}
        for i in range(count)
    ]
    events += [
        {"time": 600, "order": count, "type": "objective", "label": "Dragón", "scope": "global"},
        {"time": 650, "order": count + 1, "type": "objective", "label": "Torre", "player_key": "TOP_a"},
        {"time": 700, "order": count + 2, "type": "kill", "label": "Otra línea", "player_key": "MIDDLE_a"},
    ]
    history = [
        {"time": i * 20, "players": {
            key: {"estimated_gold": i * 100 + n, "cs": i * 5, "kills": i // 20,
                  "deaths": 2, "assists": 3, "level": min(18, 1 + i // 10),
                  "items": [1001], "stats": {"vision_score": i}}
            for n, key in enumerate(players)
        }}
        for i in range(snapshots)
    ]
    return {"session_id": "live-performance-test", "champion_name": "Ahri",
            "game_mode": "CLASSIC", "local_player_key": "TOP_a",
            "players": players, "lane_matchups": matchups, "events": events,
            "snapshots": history, "final_sync": {"status": "live_only"}}


class LiveAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widgets = []
        self.catalog = {"1001": {"name": "Botas", "stats": {}, "gold": {"total": 300}}}
        self.assets = SimpleNamespace(
            version="test", set_label_image=Mock(), champion_url=lambda x: x,
            item_url=lambda x: str(x), item_name=Mock(side_effect=AssertionError("No E/S por evento")),
        )
        self.patches = [
            patch("app.services.live_analysis_models_and_calculator.get_champion_data",
                  return_value={"stats": {"hp": 600, "attackdamage": 60}}),
            patch("requests.get", side_effect=AssertionError("Unexpected synchronous HTTP")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        self.drain()
        for widget in self.widgets:
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        for p in reversed(self.patches):
            p.stop()

    def drain(self):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            self.app.processEvents()
            if not any(getattr(w, "_stats_task", None) for w in self.widgets):
                break
            time.sleep(.005)
        self.assertTrue(QThreadPool.globalInstance().waitForDone(5000))
        self.app.processEvents()
        self.assertFalse(any(getattr(w, "_stats_task", None) for w in self.widgets))

    def dialog(self, session=None):
        d = LiveMatchAnalysisDialog(session if session is not None else session_fixture(),
                                    self.assets, self.catalog)
        self.widgets.append(d)
        d.setStyleSheet(CONTROL_WINDOW_STYLE)
        d.show()
        self.app.processEvents()
        return d

    def test_timeline_model_preserves_actions_time_and_text(self):
        model = TimelineModel({"items": {1001: {"name_es": "Botas"}}})
        events = [
            {"time": 60, "type": action, "item_id": 1001, "player_key": "a"}
            for action in model.ACTIONS
        ] + [{"time_label": "05:00", "type": "objective", "label": "Dragón"}]
        model.set_events(events, "a", "b")
        self.assertEqual(model.rowCount(), 5)
        self.assertEqual(model.rows[0], ("01:00", "Compró Botas", "ally"))
        self.assertEqual(model.rows[-1], ("05:00", "Dragón", "global"))
        self.assertIn("Dragón", model.data(model.index(4), Qt.ItemDataRole.ToolTipRole))
        self.assertEqual(model.rowCount(model.index(0)), 0)
        reset = QSignalSpy(model.modelReset)
        inserted = QSignalSpy(model.rowsInserted)
        model.set_events(events, "a", "b")
        self.assertEqual(reset.count(), 0)
        model.set_events(events + [{"label": "Nuevo"}], "a", "b")
        self.assertEqual(inserted.count(), 1)
        self.assertEqual(reset.count(), 0)
        model.set_events(events[:1], "a", "b")
        self.assertEqual(reset.count(), 1)

    def test_virtualization_10000_events(self):
        view = TimelineView(self.catalog)
        self.widgets.append(view)
        view.resize(600, 700)
        events = session_fixture(10000, 0)["events"]
        t = time.perf_counter()
        view.set_events(events, "TOP_a", "TOP_b")
        view.show()
        self.app.processEvents()
        elapsed = time.perf_counter() - t
        print(f"\nTimeline: {len(events)} eventos, {elapsed*1000:.1f} ms, "
              f"{len(view.findChildren(QWidget))} widgets")
        self.assertEqual(view.model().rowCount(), len(events))
        self.assertLess(len(view.findChildren(QWidget)), 20)
        self.assertLess(elapsed, 1.0)
        view.verticalScrollBar().setValue(500)
        view.set_events(events + [{"time": 30000, "label": "Nuevo"}], "TOP_a", "TOP_b")
        self.assertEqual(view.verticalScrollBar().value(), 500)

    def test_filters_do_not_rebuild_sides_and_keep_global_timestamp(self):
        d = self.dialog()
        self.drain()
        page = d.content.currentWidget()
        side = page.layout().itemAt(0).widget().widget()
        self.assertEqual(d.timeline_view.model().rowCount(), 1001)
        d._change_timeline_mode("global")
        self.assertEqual(d.timeline_view.model().rowCount(), 2)
        self.assertEqual(d.timeline_view.model().rows[0][0], "10:00")
        d._change_timeline_mode("all")
        self.assertEqual(d.timeline_view.model().rowCount(), 1002)
        self.assertIs(page.layout().itemAt(0).widget().widget(), side)
        self.assets.item_name.assert_not_called()

    def test_navigation_reuses_pages_and_keeps_scroll(self):
        d = self.dialog()
        self.drain()
        page = d.content.currentWidget()
        timeline = d.timeline_view
        timeline.verticalScrollBar().setValue(500)
        d.show_role("MIDDLE")
        d.show_role("TOP")
        self.assertIs(d.content.currentWidget(), page)
        self.assertIs(d.timeline_view, timeline)
        self.assertEqual(timeline.verticalScrollBar().value(), 500)
        with patch("app.ui.live_match_analysis_dialog.MatchLogService") as logs:
            d.show_ai_analysis()
            ai = d.content.currentWidget()
            self.assertTrue(all(not b.isChecked() for b in d.role_buttons.values()))
            d.show_role("TOP")
            d.show_ai_analysis()
            self.assertIs(d.content.currentWidget(), ai)
            logs.assert_not_called()

    def test_update_keeps_ai_tab_and_coalesces_latest_session(self):
        d = self.dialog()
        self.drain()
        d.show_ai_analysis()
        ai = d.content.currentWidget()
        new = deepcopy(d.session)
        d.update_session(new)
        self.drain()
        self.assertEqual(d.current_view, "ai_analysis")
        self.assertIs(d.content.currentWidget(), ai)
        new2 = deepcopy(new)
        new2["champion_name"] = "Latest"
        d.update_session(new2)
        self.assertTrue(d._refresh_timer.isActive())
        d._flush_session()
        self.drain()
        self.assertEqual(d.session["champion_name"], "Latest")
        self.assertIs(d.content.currentWidget(), ai)

    def test_sync_in_place_and_empty_matchup(self):
        d = self.dialog({})
        self.drain()
        self.assertNotIn("timeline", d._role_pages["TOP"])
        d.update_session(session_fixture(5, 2))
        self.drain()
        self.assertIn("timeline", d._role_pages["TOP"])
        d.session["final_sync"]["status"] = "synced"
        d.update_session(d.session)
        self.assertEqual(d._sync_status, "synced")
        self.assertEqual(d.header_badge.text(), "TELEMETRÍA POSTGAME")

    def displayed_cs(self, dialog, side_index):
        side = dialog.content.currentWidget().layout().itemAt(side_index).widget().widget()
        panel = side.findChild(QFrame, "liveMetricSummary")
        grid = panel.layout().itemAt(1).layout()
        self.assertEqual(grid.itemAtPosition(1, 0).widget().text(), "CS:")
        return grid.itemAtPosition(1, 1).widget().text()

    def test_cs_sync_refreshes_both_sides_and_preserves_live_history(self):
        session = session_fixture(5, 2)
        session["snapshots"][-1]["players"]["TOP_a"]["cs"] = 290
        session["snapshots"][-1]["players"]["TOP_b"]["cs"] = 100
        d = self.dialog(session)
        self.drain()
        self.assertEqual(self.displayed_cs(d, 0), "290")
        self.assertEqual(self.displayed_cs(d, 2), "100")
        history = deepcopy(session["snapshots"])
        synced = deepcopy(session)
        synced["final_sync"]["status"] = "synced"
        synced["players"]["TOP_a"]["final"] = {"cs_total": 312}
        synced["players"]["TOP_b"]["final"] = {"cs_minions": 100, "cs_jungle": 148}
        d._last_ui_refresh = time.monotonic()
        d.update_session(synced)
        # Must update immediately, without waiting for the attribute worker.
        self.assertEqual(self.displayed_cs(d, 0), "312")
        self.assertEqual(self.displayed_cs(d, 2), "248")
        self.drain()
        d.show_role("MIDDLE")
        d.show_role("TOP")
        self.assertEqual(self.displayed_cs(d, 0), "312")
        self.assertEqual(self.displayed_cs(d, 2), "248")
        bars = [b for b in d.content.currentWidget().findChildren(RiotComparisonBar) if b.title == "CS"]
        self.assertEqual(len(bars), 1)
        self.assertEqual((bars[0].ally_value, bars[0].enemy_value), (312, 248))
        self.assertEqual(d.session["snapshots"], history)
        self.assertEqual(d._player_series("TOP_b")["cs"][-1][1], 100)

    def test_saved_synced_cs_zero_fallback_and_missing_data(self):
        cases = [
            ("synced", {"cs_total": 0, "cs_minions": 50}, "0"),
            ("synced", {"cs_total": "248"}, "248"),
            ("synced", {"cs_minions": 100, "cs_jungle": 148}, "248"),
            ("synced", {"cs_total": "invalid", "cs_jungle": 148}, "148"),
            ("synced", {}, "5"),
            ("synced", None, "5"),
            ("synced", {"cs_total": "invalid"}, "5"),
            ("synced", {"cs_minions": "invalid"}, "5"),
            ("pending", {"cs_total": 248}, "5"),
            ("live_only", {"cs_total": 248}, "5"),
            ("failed", {"cs_total": 248}, "5"),
        ]
        for status, final, expected in cases:
            with self.subTest(status=status, final=final):
                session = session_fixture(0, 2)
                session["final_sync"]["status"] = status
                session["players"]["TOP_b"]["final"] = final
                d = self.dialog(session)
                self.drain()
                self.assertEqual(self.displayed_cs(d, 2), expected)

    def test_synced_cs_without_live_snapshots(self):
        session = session_fixture(0, 0)
        session["final_sync"]["status"] = "synced"
        session["players"]["TOP_a"]["final"] = {"cs_total": 312}
        session["players"]["TOP_b"]["final"] = {"cs_total": 248}
        d = self.dialog(session)
        self.drain()
        self.assertEqual(self.displayed_cs(d, 0), "312")
        self.assertEqual(self.displayed_cs(d, 2), "248")
        self.assertEqual(d._player_series("TOP_a")["cs"], [])

    def test_background_calculation_and_stale_results(self):
        main_thread = threading.get_ident()
        threads = []
        def calculate(session, key, catalog, version):
            threads.append(threading.get_ident())
            return {"hp": 1234}
        with patch("app.ui.live_match_analysis_dialog.calculate_post_stats", side_effect=calculate):
            d = self.dialog()
            d.update_session(session_fixture(10, 5))
            self.drain()
        self.assertTrue(threads)
        self.assertTrue(all(t != main_thread for t in threads))
        self.assertEqual(d._post_stats["TOP_a"]["hp"], 1234)
        self.assertEqual(d.timeline_view.model().rowCount(), 11)

    def test_open_and_warm_navigation_budget(self):
        t = time.perf_counter()
        d = self.dialog(session_fixture(10000, 1500))
        opening = time.perf_counter() - t
        self.drain()
        for role in d.ROLE_LABELS:
            d.show_role(role)
        self.app.processEvents()
        timings = []
        for role in list(d.ROLE_LABELS) * 3:
            t = time.perf_counter()
            d.show_role(role)
            self.app.processEvents()
            timings.append(time.perf_counter() - t)
        print(f"\nDiálogo 10000 eventos/1500 snapshots: apertura={opening*1000:.1f} ms; "
              f"navegación caliente máx={max(timings)*1000:.1f} ms")
        self.assertLess(opening, 2.0)
        self.assertLess(max(timings), .1)
        self.assertEqual(len(d._role_pages), 5)

    def test_compact_calculation_matches_full_history(self):
        original = session_fixture(0, 150)
        expected = deepcopy(original)
        attach_achievements(expected, self.catalog, self.assets.version)
        d = self.dialog(original)
        self.drain()
        self.assertEqual(d.session["achievements"], expected["achievements"])

    def test_recommendations_are_reused(self):
        d = self.dialog()
        self.drain()
        d.show_recommendations()
        panel = d.recommendation_panel
        d.show_role("TOP")
        d.show_ai_analysis()
        d.show_recommendations()
        self.assertIs(d.recommendation_panel, panel)
        self.assertIs(d.content.currentWidget(), panel)

    def test_close_disposes_dialog(self):
        d = self.dialog()
        self.drain()
        d._last_ui_refresh = time.monotonic()
        d.update_session(session_fixture(2, 2))
        self.assertTrue(d._refresh_timer.isActive())
        d.close()
        self.assertFalse(d._refresh_timer.isActive())
        self.widgets.remove(d)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(d))

    def test_chart_preserves_extrema_and_original_tooltip_values(self):
        points = [(i, 999 if i == 53 else -200 if i == 67 else i) for i in range(100)]
        sampled = VersusChart._bucket_extrema(points)
        self.assertEqual(sampled, [points[0], points[53], points[67], points[-1]])
        for t in (-1, 0, 15.3, 66.9, 1000):
            self.assertEqual(VersusChart._nearest(points, t),
                             min(points, key=lambda p: abs(p[0] - t)))
        chart = VersusChart("Test", points, [], "Aliado", "Enemigo")
        self.widgets.append(chart)
        chart.resize(400, 200)
        chart.show()
        self.app.processEvents()
        self.assertEqual(chart.ally_values, points)
        polygons = list(chart._geometry_cache.values())
        chart.repaint()
        self.assertEqual(list(chart._geometry_cache.values()), polygons)


if __name__ == "__main__":
    unittest.main()