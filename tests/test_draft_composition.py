"""Regressions for independently scoped Draft composition estimates."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.draft_analyzer_service import DraftAnalyzerService
from backend.draft import DraftRuntime


class DraftCompositionContractTests(unittest.TestCase):
    def test_power_curve_reports_only_observed_brackets_and_samples(self) -> None:
        analyzer = DraftAnalyzerService.__new__(DraftAnalyzerService)
        profiles = {
            "Ahri": {"win_rate_vs_game_length": [
                {"label": "0-15m", "winrate": 55},
                {"label": "15-20m", "winrate": 0.52},
            ]},
            "Lux": {"win_rate_by_game_length": {"0-15": 45}},
            "Garen": {"win_rate_vs_game_length": []},
        }
        analyzer.get_champion_profile = lambda name: profiles.get(name)

        result = analyzer.calculate_team_power_curve_with_samples(["Ahri", "Lux", "Garen"])

        self.assertEqual(result["values"], {"0-15": 50.0, "15-20": 52.0})
        self.assertEqual(result["samples"], {"0-15": 2, "15-20": 1})
        self.assertNotIn("20-25", result["values"])

    def test_team_composition_uses_only_that_teams_supported_damage_profiles(self) -> None:
        runtime = DraftRuntime.__new__(DraftRuntime)
        profiles = {
            "Ahri": {"basic_info": {"damage_type": "AP"}},
            "Garen": {"damage_breakdown": {
                "physical_damage_percent": 70,
                "magic_damage_percent": 20,
                "true_damage_percent": 10,
            }},
            "Unknown": {"basic_info": {}},
        }
        damage_call = Mock(return_value={"physical": 70.0, "magic": 20.0, "true": 10.0})
        runtime.analyzer = SimpleNamespace(
            get_champion_profile=lambda name: profiles.get(name),
            calculate_team_damage_breakdown=damage_call,
            calculate_team_power_curve_with_samples=lambda names: {
                "values": {"20-25": 54.0} if names == ["Ahri"] else {},
                "samples": {"20-25": 1} if names == ["Ahri"] else {},
            },
        )

        ally = runtime._team_composition(["Ahri"])
        enemy = runtime._team_composition(["Garen", "Unknown"])

        self.assertEqual(ally["damageSamples"], 1)
        self.assertEqual(enemy["damageSamples"], 1)
        self.assertEqual(ally["powerCurve"], {"20-25": 54.0})
        self.assertEqual(enemy["powerCurve"], {})
        self.assertEqual(damage_call.call_args_list[0].args[0], ["Ahri"])
        self.assertEqual(damage_call.call_args_list[1].args[0], ["Garen"])

    def test_missing_profiles_have_no_fabricated_damage_distribution(self) -> None:
        runtime = DraftRuntime.__new__(DraftRuntime)
        runtime.analyzer = SimpleNamespace(
            get_champion_profile=lambda _name: None,
            calculate_team_damage_breakdown=Mock(side_effect=AssertionError("must not estimate without profiles")),
            calculate_team_power_curve_with_samples=lambda _names: {"values": {}, "samples": {}},
        )

        result = runtime._team_composition(["Unknown"])

        self.assertIsNone(result["damage"])
        self.assertEqual(result["damageSamples"], 0)
        self.assertEqual(result["powerCurve"], {})


if __name__ == "__main__":
    unittest.main()
