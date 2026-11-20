from app.services.home_history_service import LCUHomeProvider
from app.services.home_history_service import HomeHistoryRepository
from backend.saved_matches import _matches_profile_identity, _participant_sides, _refresh_selected_lcu_detail, _saved_participant_cs


def test_lcu_participant_cs_uses_lane_plus_neutral_minions_and_preserves_missing():
    game = {
        "gameId": 7001,
        "gameCreation": 1_792_000_000_000,
        "gameDuration": 1800,
        "queueId": 420,
        "participants": [
            {
                "participantId": 1,
                "teamId": 100,
                "puuid": "local-puuid",
                "championId": 233,
                "stats": {
                    "minionsKilled": 23,
                    "totalMinionsKilled": 23,
                    "neutralMinionsKilled": 109,
                    "kills": 4,
                    "deaths": 2,
                    "assists": 8,
                },
            },
            {
                "participantId": 2,
                "teamId": 200,
                "championId": 7,
                "stats": {
                    "totalMinionsKilled": 160,
                    "neutralMinionsKilled": 35,
                    "kills": 2,
                    "deaths": 3,
                    "assists": 5,
                },
            },
            {
                "participantId": 3,
                "teamId": 200,
                "championId": 21,
                "stats": {
                    "minionsKilled": 0,
                    "neutralMinionsKilled": 0,
                    "kills": 0,
                    "deaths": 0,
                    "assists": 0,
                },
            },
            {"participantId": 4, "teamId": 200, "championId": 89, "stats": {"kills": 1}},
            {"participantId": 5, "teamId": 100, "championId": 122, "stats": {"minionsKilled": 80, "neutralMinionsKilled": 5}},
            {"participantId": 6, "teamId": 100, "championId": 64, "stats": {"totalMinionsKilled": 12, "neutralMinionsKilled": 101}},
            {"participantId": 7, "teamId": 100, "championId": 22, "stats": {"minionsKilled": 175, "neutralMinionsKilled": 3}},
            {"participantId": 8, "teamId": 200, "championId": 24, "stats": {"minionsKilled": 160, "neutralMinionsKilled": 20}},
            {"participantId": 9, "teamId": 200, "championId": 11, "stats": {"totalMinionsKilled": 9, "neutralMinionsKilled": 110}},
            {"participantId": 10, "teamId": 200, "championId": 67, "stats": {"minionsKilled": 180, "neutralMinionsKilled": 0}},
        ],
        "participantIdentities": [{"participantId": 1, "player": {"puuid": "local-puuid"}}],
    }

    match = LCUHomeProvider._normalize(game, {"puuid": "local-puuid"})

    assert match["cs"] == 132
    assert match["cs_source_version"] == 2
    by_participant = {item["participant_id"]: item for item in match["participants"]}
    assert by_participant[1]["cs"] == 132
    assert by_participant[1]["final_stats"]["cs"] == 132
    assert (by_participant[1]["cs_lane_minions"], by_participant[1]["cs_neutral_minions"]) == (23, 109)
    assert by_participant[2]["cs"] == 195
    assert by_participant[2]["final_stats"]["cs"] == 195
    assert by_participant[3]["cs"] == 0
    assert by_participant[4]["cs"] is None
    assert by_participant[4]["final_stats"]["cs"] is None
    assert len(by_participant) == 10
    assert [by_participant[index]["cs"] for index in range(5, 11)] == [85, 113, 178, 180, 119, 180]


def test_legacy_cached_participant_cs_is_unknown_but_local_summary_is_preserved():
    legacy_participant = {"is_local": False, "cs": 0}
    local_participant = {"is_local": True, "cs": 0}
    legacy_match = {"cs": 132}
    assert _saved_participant_cs(legacy_participant, legacy_match) is None
    assert _saved_participant_cs(local_participant, legacy_match) == 132


def test_versioned_cached_participant_keeps_real_zero_and_missing_null():
    match = {"cs_source_version": 2}
    assert _saved_participant_cs({"cs_source_version": 2, "cs": 0}, match) == 0
    assert _saved_participant_cs({"cs_source_version": 2, "cs": None}, match) is None


def test_history_sync_replaces_legacy_participants_with_reparsed_cs(tmp_path):
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "profile-for-cs-test"}
    legacy = {
        "stable_match_id": "LCU-test-match",
        "participants": [
            {"participant_id": 1, "champion_id": 233, "team_id": 100, "cs": 0},
            {"participant_id": 2, "champion_id": 7, "team_id": 200, "cs": 8},
        ],
        "enrichment": {"participants_complete": True},
    }
    repository.merge(profile, [legacy])

    reparsed = {
        "stable_match_id": "LCU-test-match",
        "cs_source_version": 2,
        "participants": [
            {"participant_id": 1, "champion_id": 233, "team_id": 100, "cs": 132, "cs_source_version": 2},
            {"participant_id": 2, "champion_id": 7, "team_id": 200, "cs": 195, "cs_source_version": 2},
        ],
        "enrichment": {"participants_complete": True},
    }
    repository.merge(profile, [reparsed])

    stored = repository.load(profile)["matches"][0]
    assert stored["cs_source_version"] == 2
    assert [participant["cs"] for participant in stored["participants"]] == [132, 195]


def test_history_sync_clears_legacy_zero_when_reparse_confirms_cs_is_missing(tmp_path):
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "profile-for-cs-null-test"}
    repository.merge(profile, [{
        "stable_match_id": "LCU-null-test-match",
        "cs": 0,
        "cs_source_version": 1,
        "participants": [{"participant_id": 1, "champion_id": 233, "cs": 0}],
    }])

    repository.merge(profile, [{
        "stable_match_id": "LCU-null-test-match",
        "cs": None,
        "cs_per_min": None,
        "cs_source_version": 2,
        "participants": [{"participant_id": 1, "champion_id": 233, "cs": None, "cs_source_version": 2}],
    }])

    stored = repository.load(profile)["matches"][0]
    assert stored["cs"] is None
    assert stored["cs_per_min"] is None
    assert stored["cs_source_version"] == 2


def test_selected_cached_match_refreshes_real_lcu_cs_and_marks_local_team(tmp_path, monkeypatch):
    profile = {"puuid": "local-puuid", "summonerId": "local-summoner"}
    repository = HomeHistoryRepository(tmp_path)
    legacy = {
        "stable_match_id": "LCU-7002",
        "game_id": "7002",
        "queue_id": 420,
        "champion_id": 233,
        "champion_name": "Briar",
        "kills": 15,
        "deaths": 10,
        "assists": 6,
        "cs": 132,
        "participants": [
            {"participant_id": index, "team_id": 100 if index <= 5 else 200,
             "champion_id": champion, "champion_name": name, "cs": 0,
             "kills": kills, "deaths": deaths, "assists": assists, "lane": "jungle"}
            for index, (champion, name, kills, deaths, assists) in enumerate([
                (39, "Irelia", 13, 6, 7), (62, "Wukong", 4, 6, 8), (246, "Qiyana", 13, 7, 4),
                (21, "Miss Fortune", 7, 9, 11), (80, "Pantheon", 12, 3, 17),
                (122, "Darius", 2, 12, 2), (233, "Briar", 15, 10, 6), (7, "LeBlanc", 9, 9, 8),
                (18, "Tristana", 4, 7, 5), (89, "Leona", 1, 11, 18),
            ], start=1)
        ],
        "enrichment": {"participants_complete": True, "detail_attempted": True, "opponent_resolved": True},
    }
    repository.merge(profile, [legacy])

    rows = [
        (39, 100, "JUNGLE", "NONE", [14, 4], 239, 0),
        (62, 100, "JUNGLE", "NONE", [4, 11], 15, 176),
        (246, 100, "MIDDLE", "SOLO", [14, 4], 169, 8),
        (21, 100, "BOTTOM", "CARRY", [21, 4], 173, 8),
        (80, 100, "BOTTOM", "SUPPORT", [14, 4], 53, 0),
        (122, 200, "JUNGLE", "NONE", [4, 14], 176, 16),
        (233, 200, "JUNGLE", "NONE", [4, 11], 23, 132),
        (7, 200, "MIDDLE", "DUO", [4, 14], 164, 0),
        (18, 200, "MIDDLE", "DUO", [4, 21], 297, 0),
        (89, 200, "BOTTOM", "SOLO", [4, 14], 19, 0),
    ]
    raw = {
        "gameId": 7002,
        "gameCreation": 1_792_000_000_000,
        "gameDuration": 1800,
        "queueId": 420,
        "participants": [
            {"participantId": index, "teamId": team, "championId": champion,
             "spell1Id": spells[0], "spell2Id": spells[1],
             "timeline": {"lane": lane, "role": role},
             "stats": {"totalMinionsKilled": lane_cs, "neutralMinionsKilled": neutral_cs,
                       "kills": legacy["participants"][index - 1]["kills"],
                       "deaths": legacy["participants"][index - 1]["deaths"],
                       "assists": legacy["participants"][index - 1]["assists"]}}
            for index, (champion, team, lane, role, spells, lane_cs, neutral_cs) in enumerate(rows, start=1)
        ],
        "participantIdentities": [
            {"participantId": index, "player": {"puuid": "local-puuid" if index == 7 else f"player-{index}"}}
            for index in range(1, 11)
        ],
    }

    class FakeClient:
        @staticmethod
        def refresh_connection():
            return True

    monkeypatch.setattr(LCUHomeProvider, "__init__", lambda self: setattr(self, "cliente", FakeClient()))
    monkeypatch.setattr(LCUHomeProvider, "_get", lambda self, _route: raw)

    refreshed = _refresh_selected_lcu_detail(repository, profile, "7002", legacy)
    participants = refreshed["participants"]
    by_name = {item["champion_name"]: item for item in participants}

    assert refreshed["cs"] == 155
    assert refreshed["participant_data_version"] == 4
    assert by_name["Briar"]["cs"] == 155
    assert by_name["Briar"]["is_local"] is True
    assert [item["source_index"] for item in participants] == list(range(10))
    assert [item["team_id"] for item in participants] == [100] * 5 + [200] * 5
    assert by_name["Qiyana"]["display_role"] == "mid"
    assert by_name["Miss Fortune"]["display_role"] == "bot"
    assert by_name["Pantheon"]["display_role"] == "support"
    assert by_name["Briar"]["display_role"] == ""
    assert _matches_profile_identity(by_name["Briar"], profile)
    participants, team_known = _participant_sides([
        {**item, "participantId": item["participant_id"], "teamId": item["team_id"], "local": item["is_local"]}
        for item in participants
    ])
    assert team_known is True
    assert sum(item["side"] == "allied" for item in participants) == 5
    assert sum(item["side"] == "enemy" for item in participants) == 5
    # Role guesses remain metadata only and may be absent or duplicated; they never
    # alter the participant sequence returned by the source.
