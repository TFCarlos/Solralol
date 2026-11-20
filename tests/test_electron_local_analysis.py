"""Integration checks for Electron's Local Analysis RPC contract."""

from __future__ import annotations

import unittest
import time
from unittest.mock import patch

from backend.application import Application


class ElectronLocalAnalysisContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = Application()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app.close()

    def request(self, champion: str, lane: str, rank: str = "master") -> dict:
        value = self.app.dispatch(
            "champions.analysis",
            {"champion": champion, "lane": lane, "rank": rank},
        )
        self.assertIsInstance(value, dict)
        return value

    def test_local_analysis_uses_emerald_plus_and_prepares_actual_content(self) -> None:
        result = self.request("Aatrox", "top")
        self.assertEqual(result["rank"], "emerald_plus")
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertTrue(result["data"]["most_played_build"])
        self.assertTrue(result["data"]["starter_items"])
        self.assertTrue(result["data"]["situational_items"])
        self.assertGreaterEqual(len(result["runeVariants"]), 1)
        self.assertTrue(result["runeVariants"][0]["page"].get("slots"))
        self.assertTrue(result["runeVariants"][0]["profile"].get("recommended_build"))
        self.assertTrue(result["items"])
        self.assertTrue(result["recommendations"])
        self.assertTrue(result["itemCandidates"])
        self.assertNotEqual(
            result["runeVariants"][0]["profile"].get("recommended_build"),
            result["runeVariants"][1]["profile"].get("recommended_build"),
            "Selecting a different rune archetype must retain its own curated build.",
        )

    def test_role_specific_profile_and_assets_are_returned(self) -> None:
        top = self.request("Aatrox", "top")
        mid = self.request("Aatrox", "mid")
        self.assertEqual(top["lane"], "top")
        self.assertEqual(mid["lane"], "mid")
        self.assertNotEqual(top["data"].get("matchups"), mid["data"].get("matchups"))
        self.assertIn("champion:Aatrox", top["assets"])
        self.assertTrue(any(key.startswith("item:") for key in top["assets"]))

    def test_other_champion_and_role_loads_from_existing_repository(self) -> None:
        result = self.request("Ahri", "mid")
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["champion"], "Ahri")
        self.assertTrue(result["data"].get("basic_info"))
        self.assertTrue(result["data"].get("matchups"))

    def test_analysis_is_advertised_as_available_and_rank_is_fixed(self) -> None:
        bootstrap = self.app.dispatch("app.bootstrap")
        feature = next(item for item in bootstrap["features"] if item["id"] == "analysis")
        self.assertEqual(feature["label"], "Análisis local")
        self.assertEqual(feature["status"], "available")
        with self.assertRaises(ValueError):
            self.app.dispatch("champions.analysis", {"champion": "Ahri", "lane": "mid", "rank": "all"})

    def test_electron_bridge_exposes_and_validates_refresh_rpcs(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        main = (root / "frontend/electron/main/index.cjs").read_text(encoding="utf-8")
        preload = (root / "frontend/electron/preload/index.cjs").read_text(encoding="utf-8")
        for method in ("champions.analysis.update", "champions.analysis.update.status", "champions.analysis.update.cancel"):
            self.assertIn(method, main)
            self.assertIn(method, preload)

    def test_manual_refresh_runs_in_background_with_fixed_rank(self) -> None:
        created = {}

        class FakeScraper:
            def __init__(self, **kwargs) -> None:
                created.update(kwargs)

            def actualizar_todo(self, target_champion_name="", progress_callback=None, stop_check=None):
                if progress_callback:
                    progress_callback(50, 100, "Aatrox · recursos")
                return 1, 1

        with patch("app.services.champion_scraper_service.ChampionScraperService", FakeScraper):
            started = self.app.dispatch("champions.analysis.update", {"champion": "Aatrox"})
            deadline = time.monotonic() + 2
            status = started
            while time.monotonic() < deadline:
                status = self.app.dispatch("champions.analysis.update.status")
                if status["state"] != "running":
                    break
                time.sleep(0.01)
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["updated"], 1)
        self.assertEqual(created["rank"], "emerald_plus")
        self.assertTrue(created["solo_rango_analisis_local"])


if __name__ == "__main__":
    unittest.main()
