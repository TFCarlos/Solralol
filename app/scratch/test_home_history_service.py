from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.services.home_history_service import (
    HomeHistoryRepository,
    LCUHomeProvider,
    _local_champion_metadata,
    _log_home_history_summary,
    _matchup_summary,
    analyze_home_history,
    cross_reference_saved_matches,
)


def test_home_repository_merges_and_keeps_accounts_separate(tmp_path) -> None:
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-a", "gameName": "Jugador"}
    another = {"puuid": "account-b", "gameName": "Jugador"}
    repository.merge(profile, [{"stable_match_id": "game-1", "champion_name": "Briar"}])
    result = repository.merge(
        profile, [{"stable_match_id": "game-1", "lane": "jungle"}]
    )
    repository.merge(another, [{"stable_match_id": "game-1", "champion_name": "Jinx"}])

    assert result["matches"] == [
        {"stable_match_id": "game-1", "champion_name": "Briar", "lane": "jungle"}
    ]
    assert len(repository.load(another)["matches"]) == 1
    assert repository.load_last_profile()["puuid"] in {"account-a", "account-b"}


def test_home_repository_does_not_downgrade_enriched_participants(tmp_path) -> None:
    """Conserva el detalle LCU frente a una fila posterior de resumen parcial."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-a"}
    full = {
        "stable_match_id": "77",
        "participants": [{"puuid": "ally"}],
        "teammates": [{"puuid": "ally"}],
        "enrichment": {"detail_attempted": True, "participants_complete": True},
    }
    summary = {
        "stable_match_id": "77",
        "participants": [{"puuid": "self"}],
        "teammates": [],
        "enrichment": {"detail_attempted": False, "participants_complete": False},
    }
    repository.merge(profile, [full])
    result = repository.merge(profile, [summary])["matches"][0]

    assert result["participants"] == [{"puuid": "ally"}]
    assert result["teammates"] == [{"puuid": "ally"}]
    assert result["enrichment"]["participants_complete"] is True


def test_home_repository_persists_offline_opponent_migration_without_duplicates(
    tmp_path,
) -> None:
    """Guarda estados nuevos de rival en sitio sin duplicar partidas antiguas."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-a"}
    original = {
        "stable_match_id": "77",
        "game_id": "77",
        "participants": [{"puuid": "self"}, {"puuid": "enemy"}],
        "enrichment": {"participants_complete": True},
        "opponent_state": "unavailable",
    }
    migrated = {
        **original,
        "enemy_team": [{"champion_name": "Zac"}],
        "opponent_state": "ambiguous",
        "opponent_resolution": {
            "champion_id": None,
            "confidence": 0,
            "method": "unknown",
            "state": "ambiguous",
        },
        "enrichment": {
            "participants_complete": True,
            "opponent_resolver_version": 3,
        },
    }
    repository.merge(profile, [original])

    result = repository.merge(profile, [migrated])

    assert len(result["matches"]) == 1
    assert result["matches"][0]["opponent_state"] == "ambiguous"
    assert result["matches"][0]["enemy_team"] == [{"champion_name": "Zac"}]
    assert result["matches"][0]["enrichment"]["participants_complete"] is True


def test_home_repository_clear_only_removes_selected_history(tmp_path) -> None:
    repository = HomeHistoryRepository(tmp_path)
    first = {"puuid": "first"}
    second = {"puuid": "second"}
    repository.merge(first, [{"stable_match_id": "a"}])
    repository.merge(second, [{"stable_match_id": "b"}])

    repository.clear(first)

    assert repository.load(first)["matches"] == []
    assert repository.load(second)["matches"] == [{"stable_match_id": "b"}]


def test_home_repository_preserves_an_unrecognized_schema(tmp_path) -> None:
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "future"}
    path = tmp_path / repository.account_key(profile) / "match_history.json"
    path.parent.mkdir(parents=True)
    original = {"schema_version": 99, "matches": [{"stable_match_id": "kept"}]}
    path.write_text(json.dumps(original), encoding="utf-8")

    try:
        repository.merge(profile, [{"stable_match_id": "new"}])
    except ValueError:
        pass
    else:
        raise AssertionError("Un esquema futuro no debe sobrescribirse")

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_lcu_normalization_uses_player_and_known_lane() -> None:
    profile = {"puuid": "mine", "summonerId": "17"}
    game = {
        "gameId": 42,
        "gameCreation": 1_760_000_000_000,
        "gameDuration": 1800,
        "queueId": 420,
        "participants": [
            {
                "championId": 233,
                "position": "JUNGLE",
                "participantId": 1,
                "teamId": 100,
                "stats": {
                    "win": True,
                    "kills": 4,
                    "deaths": 2,
                    "assists": 8,
                    "minionsKilled": 120,
                    "neutralMinionsKilled": 30,
                    "perk0": 8010,
                },
            },
            {
                "participantId": 2,
                "teamId": 200,
                "championId": 35,
                "position": "JUNGLE",
                "stats": {"kills": 2},
            },
        ],
        "participantIdentities": [{"participantId": 1, "player": {"summonerId": "17"}}],
    }

    match = LCUHomeProvider._normalize(game, profile)

    assert match["stable_match_id"] == "42"
    assert match["lane"] == "jungle"
    assert match["result"] == "victory"
    assert match["cs_per_min"] == 5.0
    assert match["champion_name"] == "Briar"
    assert match["opponent_champion_name"] == "Shaco"
    assert match["runes"] == [8010]


def test_lcu_normalization_extracts_only_allied_players_and_lane_rival() -> None:
    """Comprueba que los datos del cliente excluyen enemigos y al invocador."""
    profile = {"puuid": "self", "summonerId": "1", "gameName": "Yo"}
    game = {
        "gameId": 43,
        "gameDuration": 1500,
        "participants": [
            {
                "participantId": 1,
                "puuid": "self",
                "teamId": 100,
                "position": "TOP",
                "championId": 86,
                "stats": {"win": True},
            },
            {
                "participantId": 2,
                "puuid": "ally",
                "teamId": 100,
                "championId": 1,
                "stats": {"win": True},
            },
            {
                "participantId": 3,
                "puuid": "enemy",
                "teamId": 200,
                "position": "TOP",
                "championId": 122,
                "stats": {"win": False},
            },
        ],
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": "self", "summonerId": "1"}},
            {
                "participantId": 2,
                "player": {"puuid": "ally", "gameName": "Aliado", "tagLine": "EUW"},
            },
        ],
    }

    match = LCUHomeProvider._normalize(game, profile)

    assert len(match["teammates"]) == 1
    assert match["teammates"][0]["stable_player_id"] == "ally"
    assert match["teammates"][0]["game_name"] == "Aliado"
    assert match["teammates"][0]["result"] == "victory"
    assert match["participants"][1]["puuid"] == "ally"
    assert match["opponent_champion_id"] == 122
    assert match["opponent_champion_name"] == "Darius"


def test_five_full_matches_keep_four_allies_and_five_enemies_and_resolve_all_lanes() -> (
    None
):
    """Comprueba cinco partidas 5v5 y la correspondencia de las cinco posiciones."""
    lanes = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
    expected = ["top", "jungle", "mid", "bot", "support"]
    for index, (raw_lane, lane) in enumerate(zip(lanes, expected, strict=True)):
        participants = []
        identities = []
        for participant_id in range(1, 11):
            ally = participant_id <= 5
            position = (
                raw_lane
                if participant_id == 1 or participant_id == 6
                else f"ROLE_{participant_id}"
            )
            participant = {
                "participantId": participant_id,
                "teamId": 100 if ally else 200,
                "championId": 233 if participant_id == 1 else 35,
                "stats": {"teamPosition": position, "win": ally},
                "puuid": "self" if participant_id == 1 else f"player-{participant_id}",
            }
            participants.append(participant)
            identities.append(
                {
                    "participantId": participant_id,
                    "player": {"puuid": participant["puuid"]},
                }
            )
        match = LCUHomeProvider._normalize(
            {
                "gameId": 100 + index,
                "participants": participants,
                "participantIdentities": identities,
            },
            {"puuid": "self"},
        )
        assert len(match["teammates"]) == 4
        assert len(match["participants"]) == 10
        assert sum(item["team_id"] == 200 for item in match["participants"]) == 5
        assert match["lane"] == lane
        assert match["opponent"]["champion_id"] == 35
        assert match["opponent"]["lane"] == lane


def test_lane_resolution_uses_role_when_lane_only_says_bottom() -> None:
    """Distingue soporte y carry cuando el detalle solo marca carril inferior."""
    assert (
        LCUHomeProvider._participant_lane(
            {"timeline": {"lane": "BOTTOM", "role": "DUO_SUPPORT"}}
        )
        == "support"
    )
    assert (
        LCUHomeProvider._participant_lane(
            {"timeline": {"lane": "BOTTOM", "role": "DUO_CARRY"}}
        )
        == "bot"
    )


def test_position_normalizer_covers_common_lcu_role_variants() -> None:
    """Normaliza alias frecuentes y distingue carry y support del carril inferior."""
    for raw, expected in (
        ("TOP", "top"),
        ("top", "top"),
        ("TOP_LANE", "top"),
        ("JUNGLE", "jungle"),
        ("jungle", "jungle"),
        ("JGL", "jungle"),
        ("MID", "mid"),
        ("MIDDLE", "mid"),
        ("BOTTOM", "bot"),
        ("BOT", "bot"),
        ("ADC", "bot"),
        ("CARRY", "bot"),
        ("UTILITY", "support"),
        ("SUPPORT", "support"),
        ("SUP", "support"),
    ):
        assert LCUHomeProvider._normalize_position(raw) == expected
    assert LCUHomeProvider._normalize_position("BOTTOM", "SUPPORT") == "support"
    assert LCUHomeProvider._normalize_position("BOTTOM", "CARRY") == "bot"


def test_jungle_smite_is_supporting_fallback_and_opponent_is_confident() -> None:
    """Usa Smite solo cuando faltan posiciones y guarda método/confianza."""
    assert LCUHomeProvider._participant_position_evidence(
        {"summoner_spells": [4, 11]}
    ) == ("jungle", "inferred", 0.76)
    local = {"team_id": 100, "lane": "jungle"}
    enemies = [
        {
            "team_id": 200,
            "champion_id": 154,
            "champion_name": "Zac",
            "team_position": "JUNGLE",
        }
    ]
    resolved = LCUHomeProvider._resolve_opponent(enemies, local, game_id="42")
    assert resolved["champion_id"] == 154
    assert resolved["confidence"] == 0.78
    assert resolved["method"] == "inferred"
    assert LCUHomeProvider._participant_position_evidence(
        {"timeline": {"lane": "NONE", "role": "SUPPORT"}}
    ) == ("unknown", "unknown", 0.0)


def test_opponent_resolver_prefers_explicit_position_and_rejects_smite_ties() -> None:
    """Prioriza posiciones explícitas y no inventa rival ante Smite duplicado."""
    local = {"team_id": 100, "team_position": "JUNGLE"}
    enemies = [
        {"team_id": 200, "champion_id": 154, "team_position": "JUNGLE"},
        {"team_id": 200, "champion_id": 11, "summoner_spells": [11]},
    ]
    assert LCUHomeProvider._resolve_opponent(enemies, local)["champion_id"] == 154
    ambiguous = [
        {"team_id": 200, "champion_id": 154, "summoner_spells": [11]},
        {"team_id": 200, "champion_id": 11, "summoner_spells": [11]},
    ]
    assert LCUHomeProvider._resolve_opponent(ambiguous, local)["method"] == "unknown"
    stored_over_inference = LCUHomeProvider._resolve_opponent(
        [{"team_id": 200, "champion_id": 11, "summoner_spells": [11]}],
        local,
        {
            "opponent_resolution": {
                "champion_id": 122,
                "champion_name": "Darius",
                "confidence": 0.8,
                "method": "stored",
            }
        },
    )
    assert stored_over_inference["champion_id"] == 122
    assert stored_over_inference["method"] == "stored"
    stored = LCUHomeProvider._stored_opponent_resolution(
        {
            "opponent_resolution": {
                "champion_id": 154,
                "champion_name": "Zac",
                "confidence": 1.0,
                "method": "teamPosition",
            }
        }
    )
    assert stored["method"] == "teamPosition"


def test_opponent_resolver_accepts_individual_position_when_team_position_is_missing() -> (
    None
):
    """Usa individualPosition como segundo nivel de posición explícita."""
    result = LCUHomeProvider._resolve_opponent(
        [
            {
                "team_id": 200,
                "champion_id": 154,
                "individual_position": "JUNGLE",
            }
        ],
        {"team_id": 100, "individual_position": "JUNGLE"},
    )

    assert result["champion_id"] == 154
    assert result["confidence"] == 0.95
    assert result["method"] == "individualPosition"


def test_opponent_resolver_uses_enemy_pick_order_for_matching_role() -> None:
    """Selecciona el mismo índice posicional de los cinco picks enemigos."""
    lanes = ("top", "jungle", "mid", "bot", "support")
    shuffled_enemies = [
        {
            "participant_id": participant_id,
            "team_id": 200,
            "champion_id": champion_id,
            "champion_name": f"Rival {champion_id}",
        }
        for participant_id, champion_id in (
            (10, 50),
            (8, 30),
            (6, 10),
            (9, 40),
            (7, 20),
        )
    ]

    for index, lane in enumerate(lanes):
        result = LCUHomeProvider._resolve_opponent(
            shuffled_enemies,
            {"team_id": 100, "team_position": lane.upper()},
        )

        assert result["champion_id"] == (10, 20, 30, 40, 50)[index]
        assert result["method"] == "team_order"
        assert result["confidence"] == 0.9


def test_stored_match_migration_resolves_jungle_by_enemy_pick_order() -> None:
    """Enriquece rivales antiguos sin posiciones usando el orden de picks guardado."""
    participants = [
        {
            "participant_id": 1,
            "puuid": "self",
            "team_id": 100,
            "team_position": "JUNGLE",
            "champion_id": 233,
            "champion_name": "Briar",
        },
        *[
            {
                "participant_id": index + 6,
                "team_id": 200,
                "champion_id": index + 100,
                "champion_name": f"Rival {index}",
            }
            for index in range(5)
        ],
    ]
    match = {
        "game_id": "old-game",
        "lane": "jungle",
        "champion_id": 233,
        "participants": participants,
        "enrichment": {"opponent_resolver_version": 3},
    }

    assert LCUHomeProvider._refresh_stored_opponent(match, {"puuid": "self"})

    assert match["opponent_champion_id"] == 101
    assert match["opponent_resolution"]["method"] == "team_order"
    assert match["enrichment"]["opponent_resolver_version"] == 4


def test_stored_match_refresh_and_summary_diagnostics(caplog) -> None:
    """Actualiza resolución persistida y registra cobertura agregada del historial."""
    match = {
        "game_id": "42",
        "lane": "jungle",
        "participants": [
            {
                "puuid": "self",
                "team_id": 100,
                "team_position": "JUNGLE",
                "champion_id": 233,
                "champion_name": "Briar",
            },
            {
                "puuid": "enemy",
                "team_id": 200,
                "team_position": "JUNGLE",
                "champion_id": 154,
                "champion_name": "Zac",
            },
        ],
    }
    caplog.set_level(logging.INFO, logger="app.services.home_history_service")

    assert LCUHomeProvider._refresh_stored_opponent(match, {"puuid": "self"})
    assert match["opponent_resolution"]["method"] == "teamPosition"
    assert match["opponent_resolution"]["confidence"] == 1.0
    _log_home_history_summary([match])

    assert "[home] history=1" in caplog.text
    assert "opponent coverage: total=1 exact=1" in caplog.text
    assert "[home] matchup champions=1" in caplog.text


def test_matchup_aggregation_uses_champion_and_match_ids_and_disjoint_lists() -> None:
    """Deduplica versiones de partidas y excluye IDs repetidos entre columnas."""
    matches = [
        {
            "game_id": str(index),
            "stable_match_id": str(index),
            "result": result,
            "opponent_resolution": {
                "champion_id": champion_id,
                "champion_name": name,
                "confidence": 1.0,
                "method": "teamPosition",
            },
        }
        for index, (champion_id, name, result) in enumerate(
            [
                (122, "Darius", "defeat"),
                (122, "Darius", "defeat"),
                (35, "Shaco", "victory"),
                (35, "Shaco", "defeat"),
                (154, "Zac", "victory"),
                (154, "Zac", "victory"),
                (154, "Zac", "victory"),
                (1, "Annie", "victory"),
                (1, "Annie", "defeat"),
            ]
        )
    ]
    matches.append({**matches[0], "stable_match_id": "duplicate-import"})

    favorable, difficult = _matchup_summary(matches)

    assert next(item["champion_id"] for item in difficult) == 122
    assert {item["champion_id"] for item in difficult[1:]} == {1, 35}
    assert [item["games"] for item in difficult if item["champion_id"] == 122] == [2]
    assert [item["champion_id"] for item in favorable] == [154]
    assert not (
        {item["champion_id"] for item in favorable}
        & {item["champion_id"] for item in difficult}
    )


def test_local_champion_metadata_reads_names_and_classes(tmp_path) -> None:
    path = tmp_path / "briar.json"
    path.write_text(
        json.dumps(
            {"data": {"Briar": {"key": "233", "name": "Briar", "tags": ["Fighter"]}}}
        ),
        encoding="utf-8",
    )

    assert _local_champion_metadata(tmp_path)["233"] == {
        "name": "Briar",
        "tags": ["Fighter"],
    }


def test_lcu_provider_normalizes_optional_ranked_queues() -> None:
    result = LCUHomeProvider._ranked_snapshot(
        {
            "queues": [
                {
                    "queueType": "RANKED_SOLO_5x5",
                    "tier": "GOLD",
                    "division": "II",
                    "leaguePoints": 42,
                    "wins": "12",
                    "losses": 8,
                },
                {"queueType": "NORMAL", "tier": ""},
            ]
        }
    )

    assert result == [
        {
            "queue": "RANKED_SOLO_5x5",
            "tier": "GOLD",
            "division": "II",
            "league_points": 42,
            "wins": 12,
            "losses": 8,
        }
    ]


def test_home_analytics_does_not_invent_winrate_without_result() -> None:
    matches = [
        {
            "result": "victory",
            "champion_name": "Briar",
            "lane": "jungle",
            "started_at": datetime(2026, 10, 7, 19, tzinfo=UTC).isoformat(),
        },
        {
            "result": "defeat",
            "champion_name": "Briar",
            "lane": "jungle",
            "started_at": datetime(2026, 10, 6, 19, tzinfo=UTC).isoformat(),
        },
        {"result": "unknown", "champion_name": "Jinx", "lane": "bot", "started_at": ""},
    ]

    result = analyze_home_history(matches)

    assert result["total"] == 3
    assert result["played"] == 2
    assert result["winrate"] == 50
    assert result["top_champion"] == "Briar"
    assert (
        result["peak_hour"] == datetime(2026, 10, 7, 19, tzinfo=UTC).astimezone().hour
    )


def test_teammates_use_stable_identity_and_winrate_without_teammate() -> None:
    """Verifica identidad estable, WR compartido y comparación sin aliado."""
    matches = [
        {
            "stable_match_id": str(index),
            "result": "victory" if index < 3 else "defeat",
            "teammates": [
                {
                    "stable_player_id": "puuid-ally",
                    "game_name": "Aliado",
                    "tag_line": "EUW",
                    "result": "victory" if index < 3 else "defeat",
                }
            ],
        }
        if index < 3
        else {
            "stable_match_id": str(index),
            "result": "defeat",
            "teammates": [
                {
                    "stable_player_id": "other-ally",
                    "game_name": "Otro",
                    "tag_line": "EUW",
                    "result": "defeat",
                }
            ],
        }
        for index in range(5)
    ]

    teammate = analyze_home_history(matches)["teammates"][0]

    assert teammate["stable_player_id"] == "puuid-ally"
    assert teammate["games"] == 3
    assert teammate["wins"] == 3
    assert teammate["losses"] == 0
    assert teammate["winrate"] == 100
    assert teammate["winrate_without"] == 0
    assert teammate["winrate_delta"] == 100


def test_collection_normalization_keeps_optional_categories_independent() -> None:
    """Valida los campos fiables que se presentan de maestría y propiedad."""
    mastery = LCUHomeProvider._normalize_collection(
        "masteries",
        [{"championId": 233, "championPoints": 12345, "championLevel": 7}],
    )
    owned_champions = LCUHomeProvider._normalize_collection(
        "champions",
        [
            {"id": 233, "ownership": {"owned": True}},
            {"id": 1, "ownership": {"owned": False}},
        ],
    )

    assert mastery == [{"champion_id": 233, "points": 12345, "level": 7}]
    assert owned_champions == {"owned_count": 1, "total_count": 2}
    assert LCUHomeProvider._normalize_collection("champions", [{"id": 233}]) is None


def test_collection_normalization_uses_challenge_summary_and_confirmed_skins() -> None:
    """Lee la forma actual del resumen de desafíos y excluye aspectos no contables."""
    challenge = LCUHomeProvider._normalize_collection(
        "challenges",
        {
            "overallChallengeLevel": "PLATINUM",
            "totalChallengeScore": 12860,
            "categoryProgress": [{"category": "TEAMWORK"}] * 5,
            "title": {"name": "Jungla"},
        },
    )
    skins = LCUHomeProvider._normalize_collection(
        "skins",
        [
            {"id": 1, "ownership": {"owned": True}},
            {"id": 2, "ownership": {"owned": True}, "isBase": True},
            {"id": 3, "ownership": {"owned": False}},
        ],
    )

    assert challenge == {
        "count": 5,
        "points": 12860,
        "tier": "PLATINUM",
        "title": "Jungla",
    }
    assert skins == {"owned_count": 1, "total_count": None}


def test_collection_loading_keeps_successful_categories_when_one_route_fails() -> None:
    """Confirma que una ruta LCU fallida no descarta las demás categorías."""
    provider = LCUHomeProvider()

    def get(endpoint: str) -> object:
        if "champion-mastery" in endpoint:
            return [{"championId": 233, "championPoints": 9000}]
        if "owned-champions" in endpoint:
            return [{"id": 233, "ownership": {"owned": True}}]
        raise RuntimeError("Ruta opcional no disponible")

    provider._get = get
    result = provider._load_collection({"summonerId": "55"})

    assert result["masteries"][0]["points"] == 9000
    assert result["champions"]["owned_count"] == 1
    assert result["skins"] is None
    assert result["challenges"] is None


def test_collection_sync_refreshes_lcu_and_preserves_cached_categories(
    tmp_path,
) -> None:
    """Refresca la conexión aislada y conserva valores si fallan módulos opcionales."""

    class ClienteLocal:
        def refresh_connection(self) -> bool:
            """Simula que el cliente local está conectado."""
            return True

    repository = HomeHistoryRepository(tmp_path)
    profile = {
        "puuid": "cuenta-local",
        "collection": {
            "masteries": [{"champion_id": 233, "points": 1000}],
            "skins": {"owned_count": 12, "total_count": None},
        },
    }
    repository.merge(profile, [])
    provider = LCUHomeProvider(ClienteLocal())
    provider._load_collection = lambda _profile: {
        "masteries": None,
        "champions": None,
        "skins": None,
        "challenges": None,
        "titles": None,
    }

    result = provider.synchronize_collection(profile, repository)

    assert result["masteries"] == [{"champion_id": 233, "points": 1000}]
    assert result["skins"] == {"owned_count": 12, "total_count": None}
    assert result["champions"] is None


def test_cross_reference_uses_exact_id_and_rejects_champion_only_match() -> None:
    matches = [
        {"game_id": "1234", "stable_match_id": "1234", "champion_name": "Briar"},
        {"game_id": "5678", "stable_match_id": "5678", "champion_name": "Ahri"},
    ]
    sessions = [
        {
            "session_id": "session-1234",
            "final_sync": {"match_id": "EUW1_1234"},
            "champion_name": "Briar",
        },
        {"final_sync": {"match_id": "EUW1_9999"}, "champion_name": "Ahri"},
    ]

    result = cross_reference_saved_matches(matches, sessions)

    assert result[0]["analyzable"] is True
    assert result[0]["saved_match_confidence"] == 100
    assert result[0]["saved_match_link"] == {
        "matched": True,
        "saved_match_id": "session-1234",
        "confidence": 1.0,
    }
    assert result[1]["analyzable"] is False
