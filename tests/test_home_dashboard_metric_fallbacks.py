"""Regression coverage for Home metrics sourced from legacy LCU match rows."""

import unittest

from app.services.home_dashboard_analytics import (
    _match_kill_participation,
    _performance_evolution,
    _ranked_stats,
    _local_stats,
    gold_difference_at_15,
)


def _match() -> dict:
    participants = []
    for index in range(10):
        local = index == 0
        team_id = 100 if index < 5 else 200
        lane = ("top", "jungle", "mid", "adc", "support")[index % 5]
        participants.append({
            "participant_id": index + 1,
            "puuid": f"player-{index}",
            "team_id": team_id,
            "champion_id": 233 if local else 1000 + index,
            "lane": lane,
            "kills": 8 if local else (6 if index < 5 else 0),
            "deaths": 5 if local else (2 if index >= 5 else 4),
            "assists": 12 if local else 2,
            "win": True if index < 5 else False,
            "final_stats": {"total_damage_dealt_to_champions": 12000 if local else 5000,
                            "vision_score": 30, "cs": 180},
        })
    # Make the opposing team's deaths explicitly equal 40; its denominator
    # differs from the current allied kills in this incomplete legacy sample.
    for participant in participants[5:]:
        participant["deaths"] = 8
    return {
        "stable_match_id": "EUW1_test",
        "game_id": "EUW1_test",
        "queue_id": 420,
        "started_at": "2026-10-18T12:00:00+00:00",
        "duration_seconds": 1800,
        "result": "victory",
        "champion_id": 233,
        "lane": "top",
        "kills": 8,
        "deaths": 5,
        "assists": 12,
        "cs": 180,
        "participants": participants,
        "opponent_resolution": {"confidence": 0.9, "champion_id": 1005},
    }


class HomeDashboardMetricFallbackTests(unittest.TestCase):
    def test_legacy_participant_resolution_and_kp_use_enemy_deaths(self):
        match = _match()
        local = _local_stats(match)
        self.assertEqual(local["participant_id"], 1)
        self.assertEqual(_match_kill_participation(match, local), 50.0)

    def test_damage_per_minute_uses_local_champion_damage_and_seconds(self):
        match = _match()
        series = _performance_evolution([match], metadata={})
        stats = _ranked_stats([match], "all", 1, series)
        self.assertEqual(series[0]["damage_per_minute"], 400.0)
        self.assertEqual(stats["damage_per_minute"]["value"], 400)
        self.assertEqual(stats["damage_per_minute"]["sample"], 1)

    def test_gold_difference_uses_minute_15_local_and_direct_opponent_frames(self):
        match = _match()
        timeline = {
            "metadata": {"participants": [f"riot-player-{index}" for index in range(10)]},
            "info": {"frames": [{
                "timestamp": 900352,
                "participantFrames": {
                    **{str(index + 1): {"totalGold": 6000 + index * 100} for index in range(10)},
                    "1": {"totalGold": 7000},
                    "6": {"totalGold": 6500},
                },
            }]},
        }
        self.assertEqual(gold_difference_at_15(match, timeline), 500)

