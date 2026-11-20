"""Game snapshots carry observed ability ranks without guessing the local player."""

from app.services.game_service import GameService


def test_game_snapshot_keeps_ability_ranks_and_unique_local_identity(monkeypatch):
    game = GameService()
    data = {"gameData": {"gameTime": 32, "gameMode": "CLASSIC"},
            "activePlayer": {"riotId": "Local#EUW", "abilities": {slot: {"abilityLevel": 1} for slot in "QWER"}},
            "allPlayers": [
                {"riotId": "Enemy#EUW", "championName": "Darius", "team": "CHAOS"},
                {"riotId": "Local#EUW", "championName": "Ahri", "team": "ORDER"},
            ]}
    monkeypatch.setattr(game, "request_data", lambda endpoint: data if endpoint == "allgamedata" else {"Events": []})
    snapshot = game.get_game_snapshot()
    assert snapshot["local_player"]["championName"] == "Ahri"
    assert snapshot["local_abilities"]["Q"]["abilityLevel"] == 1
    assert [row["championName"] for row in snapshot["enemies"]] == ["Darius"]


def test_game_snapshot_does_not_choose_first_player_when_identity_unknown(monkeypatch):
    game = GameService()
    data = {"gameData": {"gameTime": 32}, "activePlayer": {"riotId": "Unknown#EUW"},
            "allPlayers": [{"riotId": "Enemy#EUW", "championName": "Darius", "team": "CHAOS"}]}
    monkeypatch.setattr(game, "request_data", lambda endpoint: data if endpoint == "allgamedata" else {"Events": []})
    snapshot = game.get_game_snapshot()
    assert snapshot["local_player"] == {}
    assert snapshot["enemies"] == []


def test_lightweight_snapshot_exposes_only_observed_active_ability_ranks(monkeypatch):
    game = GameService()
    active = {"riotId": "Local#EUW", "level": 4,
              "abilities": {slot: {"abilityLevel": rank} for slot, rank in zip("QWER", (2, 1, 1, 0), strict=True)}}
    responses = {"activeplayer": active,
                 "playerlist": [{"riotId": "Local#EUW", "team": "ORDER", "championName": "Ahri"}],
                 "gamestats": {"gameTime": 30, "gameMode": "CLASSIC"},
                 "eventdata": {"Events": []}, "activeplayerrunes": {}}
    monkeypatch.setattr(game, "request_data", lambda endpoint: responses[endpoint])
    snapshot = game.get_live_snapshot()
    assert snapshot["local_abilities"]["Q"]["abilityLevel"] == 2
    assert snapshot["local_live_stats"]["level"] == 4
