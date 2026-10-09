from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.services.home_history_service import (
    HomeHistoryRepository,
    LCUHomeProvider,
    _coincide_cuenta_local,
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


def test_lcu_participant_normalizes_defense_stats_and_preserves_absence() -> None:
    """Normaliza estadísticas LCU y distingue cero medido de campo ausente."""
    participant = LCUHomeProvider._normalize_participant(
        {
            "participantId": 1,
            "championId": 201,
            "stats": {
                "totalDamageTaken": 100_000,
                "damageSelfMitigated": 80_000,
                "kills": 12,
                "deaths": 7,
                "assists": 4,
                "goldEarned": 17_681,
                "totalDamageDealtToChampions": 33_386,
            },
        },
        {},
    )
    zero = LCUHomeProvider._normalize_participant(
        {
            "participantId": 2,
            "championId": 201,
            "stats": {"totalDamageTaken": 0, "damageSelfMitigated": 0},
        },
        {},
    )
    unavailable = LCUHomeProvider._normalize_participant(
        {"participantId": 3, "championId": 201, "stats": {}}, {}
    )
    assert participant["damage_taken"] == 100_000
    assert participant["damage_self_mitigated"] == 80_000
    assert participant["final_stats"]["damage_taken"] == 100_000
    assert participant["final_stats"]["kills"] == 12
    assert participant["final_stats"]["gold_earned"] == 17_681
    assert participant["final_stats"]["total_damage_dealt_to_champions"] == 33_386
    assert zero["damage_taken"] == 0
    assert zero["damage_self_mitigated"] == 0
    assert unavailable["damage_taken"] is None
    assert unavailable["damage_self_mitigated"] is None
    assert unavailable["final_stats"]["gold_earned"] is None


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


def test_home_repository_recovers_redundant_json_closers_with_verified_backup(
    tmp_path,
) -> None:
    """Recupera un documento completo con cierres duplicados tras respaldarlo."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "recovery-account"}
    path = tmp_path / repository.account_key(profile) / "match_history.json"
    path.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "profile_id": repository.account_key(profile),
        "last_sync": "2026-10-01T00:00:00+00:00",
        "unknown_metadata": {"kept": True},
        "matches": [
            {"stable_match_id": "old-1", "started_at": "2026-09-01T00:00:00Z"},
            {"stable_match_id": "old-2", "started_at": "2026-09-02T00:00:00Z"},
        ],
    }
    intact = json.dumps(original, ensure_ascii=False, indent=2).encode("utf-8")
    corrupt = intact + b"    }\n  ]\n}"
    path.write_bytes(corrupt)

    loaded = repository.load(profile)

    backups = list(path.parent.glob("match_history.json.recovery-*.bak"))
    assert [match["stable_match_id"] for match in loaded["matches"]] == [
        "old-1",
        "old-2",
    ]
    assert loaded["unknown_metadata"] == {"kept": True}
    assert len(backups) == 1
    assert backups[0].read_bytes() == corrupt
    assert (
        hashlib.sha256(backups[0].read_bytes()).hexdigest()
        == hashlib.sha256(corrupt).hexdigest()
    )
    assert (
        json.loads(path.read_text(encoding="utf-8"))["matches"] == original["matches"]
    )


def test_home_repository_keeps_valid_records_and_raw_malformed_records(
    tmp_path,
) -> None:
    """Muestra registros válidos y conserva intactas filas no interpretables."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "partial-account"}
    path = tmp_path / repository.account_key(profile) / "match_history.json"
    path.parent.mkdir(parents=True)
    original = {
        "schema_version": 1,
        "profile_id": repository.account_key(profile),
        "matches": [
            {"stable_match_id": "valid", "future_field": {"value": 4}},
            "raw malformed legacy row",
        ],
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    loaded = repository.load(profile)
    assert [match["stable_match_id"] for match in loaded["matches"]] == ["valid"]
    assert loaded["matches"][0]["future_field"] == {"value": 4}
    assert loaded["_unusable_match_records"] == ["raw malformed legacy row"]

    merged = repository.merge(profile, [{"stable_match_id": "new"}])
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert {match["stable_match_id"] for match in merged["matches"]} == {
        "valid",
        "new",
    }
    assert persisted["matches"][-1] == "raw malformed legacy row"


def test_home_repository_serializes_concurrent_merges_without_duplicates(
    tmp_path,
) -> None:
    """Serializa sincronizaciones simultáneas y conserva cada partido una vez."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "concurrent-account"}

    def guardar(indice: int) -> None:
        repository.merge(profile, [{"stable_match_id": f"game-{indice}"}])

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(guardar, range(32)))
    loaded = repository.load(profile)

    ids = [match["stable_match_id"] for match in loaded["matches"]]
    assert len(ids) == 32
    assert len(set(ids)) == 32


def test_home_repository_empty_sync_preserves_old_history_and_optional_scores(
    tmp_path,
) -> None:
    """Una respuesta vacía de LCU no borra partidas ni puntuaciones guardadas."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "offline-account"}
    original = {
        "stable_match_id": "saved-1",
        "champion_name": "Briar",
        "saved_match_link": {"matched": True, "saved_match_id": "session-1"},
        "performance_summary": {"points": 671, "rank": 6},
    }
    repository.merge(profile, [original])

    repository.merge(profile, [])
    loaded = repository.load(profile)

    assert loaded["matches"] == [original]


def test_legacy_history_v1_loads_for_home_analytics_without_battlescore(
    tmp_path,
) -> None:
    """Carga el formato v1 previo y restaura los KPIs sin exigir BattleScore."""
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "legacy-home-account", "gameName": "Jugador"}
    records = [
        {
            "stable_match_id": f"legacy-{index}",
            "game_id": f"legacy-{index}",
            "started_at": f"2026-09-0{index + 1}T18:30:00+00:00",
            "champion_id": 233 if index < 2 else 22,
            "champion_name": "Briar" if index < 2 else "Ashe",
            "champion_classes": ["Fighter"],
            "lane": "jungle" if index < 2 else "bot",
            "result": "victory" if index != 1 else "defeat",
            "kills": 8,
            "deaths": 3,
            "assists": 6,
            "cs": 180,
            "items": [6699, 3111, 6333],
            "participants": [{"puuid": "legacy-home-account"}],
            "teammates": [
                {
                    "stable_player_id": "teammate-1",
                    "game_name": "Aliado",
                    "tag_line": "EUW",
                    "champion_id": 22,
                    "champion_name": "Ashe",
                    "result": "victory" if index != 1 else "defeat",
                }
            ],
            "opponent_resolution": {
                "champion_id": 950,
                "champion_name": "Naafiri",
                "state": "exact",
                "confidence": 1,
            },
            "saved_match_link": {
                "matched": index != 2,
                "saved_match_id": f"session-{index}" if index != 2 else "",
            },
            **(
                {"performance_summary": {"points": 671, "rank": 6}}
                if index == 0
                else {}
            ),
        }
        for index in range(3)
    ]
    directory = tmp_path / repository.account_key(profile)
    directory.mkdir(parents=True)
    (directory / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (directory / "match_history.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile_id": repository.account_key(profile),
                "last_sync": "2026-09-04T00:00:00+00:00",
                "matches": records,
            }
        ),
        encoding="utf-8",
    )

    loaded = repository.load(profile)
    analytics = analyze_home_history(loaded["matches"])

    assert len(loaded["matches"]) == 3
    assert analytics["total"] == 3
    assert analytics["played"] == 3
    assert analytics["winrate"] == 67
    assert analytics["top_champion"] == "Briar"
    assert analytics["lanes"] == [("jungle", 2), ("bot", 1)]
    assert len(analytics["hours"]) == 1
    assert analytics["teammates"][0]["games"] == 3
    assert loaded["matches"][0]["saved_match_link"]["matched"] is True
    assert loaded["matches"][1].get("performance_summary") is None


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
            {"id": 233, "ownership": {"owned": True}},
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
        "association": "exact",
    }
    assert result[1]["analyzable"] is False


def test_cross_reference_prefers_existing_saved_link_for_local_battlescore() -> None:
    """Respeta el vínculo ANALIZABLE incluso si otro registro comparte el ID de juego."""
    from app.services.servicio_puntuacion_rendimiento import VERSION_PUNTUACION

    resumen = {
        "version": VERSION_PUNTUACION,
        "calibration_version": "2026.10",
        "state": "POSTGAME_FINAL",
        "awards_finalized": True,
        "players": [
            {
                "participant_id": "briar-local",
                "total": 671,
                "global_rank": 6,
                "awards": [],
                "completeness": 0.8,
            }
        ],
    }
    match = {
        "game_id": "1234",
        "stable_match_id": "1234",
        "champion_name": "Briar",
        "participants": [{"puuid": "cuenta-briar"}],
        "saved_match_link": {
            "matched": True,
            "saved_match_id": "sesion-briar",
            "confidence": 1.0,
        },
    }
    session_linked = {
        "session_id": "sesion-briar",
        "local_player_key": "briar-local",
        "local_puuid": "cuenta-briar",
        "champion_name": "Briar",
        "final_sync": {"status": "synced", "match_id": "EUW1_9999"},
        "performance_scoring": resumen,
    }
    session_same_game = {
        "session_id": "sesion-otra",
        "local_player_key": "otro-local",
        "local_puuid": "otra-cuenta",
        "champion_name": "Briar",
        "final_sync": {"status": "synced", "match_id": "EUW1_1234"},
        "performance_scoring": {
            **resumen,
            "players": [
                {
                    "participant_id": "otro-local",
                    "total": 999,
                    "global_rank": 1,
                    "awards": ["MVP"],
                    "completeness": 1.0,
                }
            ],
        },
    }

    result = cross_reference_saved_matches(
        [match], [session_same_game, session_linked], "cuenta-briar"
    )[0]

    assert result["saved_match_link"]["saved_match_id"] == "sesion-briar"
    assert result["performance_summary"]["points"] == 671
    assert result["performance_summary"]["global_rank"] == 6
    assert result["performance_summary"]["award"] == ""


def test_local_identity_uses_exact_saved_link_and_unique_riot_id_fallback() -> None:
    """Resuelve PUUID heredado solo si el vínculo exacto y el Riot ID coinciden."""
    match = {
        "saved_match_link": {
            "matched": True,
            "saved_match_id": "session-briar",
            "association": "exact",
        },
        "participants": [
            {
                "puuid": "current-account",
                "game_name": "Solrasar",
                "tag_line": "000",
            }
        ],
    }
    session = {
        "session_id": "session-briar",
        "local_player_key": "briar-local",
        "local_puuid": "older-puuid",
        "players": {"briar-local": {"riot_id": "Solrasar#000"}},
    }

    assert not _coincide_cuenta_local(match, session, "current-account")
    assert _coincide_cuenta_local(
        match,
        session,
        "current-account",
        asociacion_confirmada=True,
    )


def test_streamer_placeholders_require_verified_identity() -> None:
    """No une etiquetas genéricas y conserva identidades estables ocultas."""
    matches = []
    for indice in range(6):
        aliados = [
            {
                "stable_player_id": "Jugador",
                "game_name": "Jugador",
                "tag_line": "EUW",
                "result": "victory" if indice < 3 else "defeat",
            },
            {
                "puuid": "verified-hidden-a",
                "game_name": "Jugador",
                "result": "victory" if indice < 3 else "defeat",
            },
            {
                "puuid": "verified-hidden-b",
                "game_name": "Player",
                "result": "victory" if indice < 2 else "defeat",
            },
            {"game_name": "Anónimo", "result": "victory" if indice < 2 else "defeat"},
        ]
        matches.append(
            {
                "stable_match_id": f"game-{indice}",
                "result": "victory" if indice < 3 else "defeat",
                "teammates": aliados,
            }
        )

    resultado = analyze_home_history(matches)
    aliados_resumidos = {
        item["stable_player_id"]: item for item in resultado["teammates"]
    }

    assert "Jugador" not in aliados_resumidos
    assert aliados_resumidos["verified-hidden-a"]["games"] == 6
    assert aliados_resumidos["verified-hidden-a"]["name"] == "Jugador verificado"
    assert aliados_resumidos["verified-hidden-a"]["winrate"] == 50
    assert aliados_resumidos["verified-hidden-b"]["games"] == 6
    assert aliados_resumidos["verified-hidden-b"]["winrate"] == 33
    assert resultado["unresolved_teammate_count"] == 12


def test_teammate_identity_uses_stable_id_not_display_name() -> None:
    """Agrupa el mismo PUUID con alias cambiante y separa homónimos."""
    matches = [
        {
            "stable_match_id": "one",
            "result": "victory",
            "teammates": [
                {
                    "puuid": "account-a",
                    "game_name": "Nombre antiguo",
                    "result": "victory",
                },
                {
                    "puuid": "account-b",
                    "game_name": "Mismo nombre",
                    "result": "victory",
                },
            ],
        },
        {
            "stable_match_id": "two",
            "result": "defeat",
            "teammates": [
                {"puuid": "account-a", "game_name": "Nombre nuevo", "result": "defeat"},
                {"puuid": "account-b", "game_name": "Mismo nombre", "result": "defeat"},
            ],
        },
    ]

    resumen = analyze_home_history(matches)["teammates"]

    assert {item["stable_player_id"] for item in resumen} == {"account-a", "account-b"}
    assert all(item["games"] == 2 and item["winrate"] == 50 for item in resumen)
