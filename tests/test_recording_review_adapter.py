from backend.recording_review import _public_session


def test_review_exposes_shared_participant_ids_radar_and_synced_events():
    session = {
        "local_player_key": "local",
        "local_team": "100",
        "champion_name": "Briar",
        "game_mode": "CLASSIC",
        "duration": 1200,
        "players": {
            "local": {"champion_name": "Briar", "team": "100", "role": "TOP"},
            "enemy": {"champion_name": "Diana", "team": "200", "role": "TOP"},
        },
        "snapshots": [{"players": {
            "local": {"kills": 5, "deaths": 2, "assists": 3, "cs": 180, "estimated_gold": 10000,
                      "level": 16, "stats": {"vision_score": 25}},
            "enemy": {"kills": 2, "deaths": 5, "assists": 3, "cs": 150, "estimated_gold": 9000,
                      "level": 15, "stats": {"vision_score": 20}},
        }}],
        "events": [
            {"type": "kill_exact", "time": 150, "event_id": "kill-1", "killer_key": "local",
             "victim_key": "enemy", "team": "100", "assister_keys": []},
            {"type": "death_exact", "time": 150, "event_id": "kill-1", "killer_key": "local",
             "victim_key": "enemy", "player_key": "enemy", "team": "200"},
            {"type": "kill_exact", "time": 199, "event_id": "broken-native", "killer_key": "unknown-key",
             "victim_key": "missing-key", "team": "100"},
            {"type": "kill", "time": 200, "player_key": "local", "team": "100", "label": "Asesinato 6"},
            {"type": "death", "time": 200, "player_key": "enemy", "team": "200", "label": "Muerte 4"},
            {"type": "item_purchase", "time": 160, "event_id": "item-full", "player_key": "local",
             "team": "100", "item_id": "3031", "label": "Compra: Filo infinito"},
            {"type": "item_purchase", "time": 161, "event_id": "item-component", "player_key": "local",
             "team": "100", "item_id": "3133", "label": "Compra: Martillo"},
            {"type": "item_purchased", "time": 162, "event_id": "item-pending", "player_key": "local",
             "team": "100", "item_id": "3089", "label": "Compró Sombrero"},
            {"type": "item_undo", "time": 163, "event_id": "undo", "player_key": "local", "item_id": "3089"},
            {"type": "item_sold", "time": 170, "event_id": "item-sale", "player_key": "enemy",
             "team": "200", "item_id": "3031", "label": "Vendió Filo infinito"},
            {"type": "objective", "time": 1200, "event_id": "nexus", "objective": "nexus",
             "team": "100", "owner_team": "200", "label": "Nexo destruido"},
        ],
    }

    result = _public_session(session, {"game_time_offset": 100, "duration_seconds": 1200})

    local, enemy = result["participants"]
    assert local["participantId"] != enemy["participantId"]
    assert local["side"] == "allied" and enemy["side"] == "enemy"
    assert local["radar"] == [0.9, 0.8333333333333334, 1.0, 0.5, 0.4]
    assert result["radarTeams"]["allied"] == local["radar"]
    assert result["winningTeam"] == "allied" and result["result"] is True
    kill = next(event for event in result["events"] if event["event_id"] == "kill-1")
    assert kill["video_time"] == 50
    assert set(kill["participants"]) == {local["participantId"], enemy["participantId"]}
    assert any(event["type"] == "kill" and event["time"] == 200 for event in result["events"])
    shared_fight = next(event for event in result["events"] if event["time"] == 200)
    assert shared_fight["side"] == "allied"
    assert {role["category"] for role in shared_fight["participant_roles"]} == {"kill", "death"}
    assert any(event["type"] == "item_purchase" for event in result["events"])
    assert not any(event.get("event_id") == "item-component" for event in result["events"])
    assert not any(event.get("event_id") == "item-pending" for event in result["events"])
    assert any(event.get("type") == "item_sale" and event.get("side") == "enemy" for event in result["events"])


def test_review_uses_champion_names_and_never_forwards_summoner_labels():
    session = {
        "local_player_key": "local", "local_team": "ORDER", "champion_name": "Briar",
        "players": {
            "local": {"champion_name": "Briar", "team": "ORDER"},
            "enemy": {"champion_name": "Jax", "team": "CHAOS"},
        },
        "events": [
            {"type": "kill", "time": 100, "event_id": "sampled-kill", "player_key": "local",
             "team": "ORDER", "label": "# asesinó a quiebratotas"},
            {"type": "kill_exact", "time": 101, "event_id": "unresolved-kill", "killer_key": "local",
             "victim_key": "unresolved-player", "label": "# asesinó a quiebratotas"},
            {"type": "objective", "time": 120, "event_id": "enemy-tower", "objective": "Torre",
             "structure": "Turret_T1_L_03_A"},
        ],
    }

    result = _public_session(session, {"game_time_offset": 0})
    sampled = next(event for event in result["events"] if event["event_id"] == "sampled-kill")
    assert sampled["label"] == "Briar asesinó a un campeón no identificado"
    assert sampled["champion"] == "Briar"
    assert "# asesinó a quiebratotas" not in str(result["events"])
    assert not any(event["event_id"] == "unresolved-kill" for event in result["events"])
    tower = next(event for event in result["events"] if event["event_id"] == "enemy-tower")
    assert tower["side"] == "enemy"
    assert tower["label"] == "Equipo rival consiguió Torre"


def test_exact_combat_is_one_event_with_stable_kill_death_and_assist_roles():
    session = {
        "local_player_key": "victim", "local_team": "100",
        "players": {
            "killer": {"champion_name": "Jax", "team": "200"},
            "victim": {"champion_name": "Briar", "team": "100"},
            "assister": {"champion_name": "Diana", "team": "200"},
        },
        "events": [
            {"type": "kill_exact", "event_id": "fight-1", "time": 54, "killer_key": "killer",
             "victim_key": "victim", "assister_keys": ["assister"], "team": "200"},
            {"type": "death_exact", "event_id": "fight-1", "time": 54, "killer_key": "killer",
             "victim_key": "victim", "assister_keys": ["assister"], "player_key": "victim", "team": "100"},
            {"type": "assist_exact", "event_id": "fight-1", "time": 54, "killer_key": "killer",
             "victim_key": "victim", "assister_keys": ["assister"], "player_key": "assister", "team": "200"},
        ],
    }

    result = _public_session(session, {"game_time_offset": 40})
    assert len(result["events"]) == 1
    event = result["events"][0]
    assert event["event_id"] == "fight-1"
    assert event["label"] == "Jax asesinó a Briar"
    assert event["side"] == "enemy"
    assert event["video_time"] == 14
    roles = {role["champion"]: role["category"] for role in event["participant_roles"]}
    assert roles == {"Jax": "kill", "Briar": "death", "Diana": "assist"}
    assert set(event["participants"]) == {p["participantId"] for p in result["participants"]}


def test_sampled_trades_at_same_timestamp_keep_direction_and_unique_events():
    session = {
        "local_player_key": "briar", "local_team": "ORDER",
        "players": {
            "briar": {"champion_name": "Briar", "team": "ORDER"},
            "jax": {"champion_name": "Jax", "team": "CHAOS"},
        },
        "events": [
            {"type": "kill", "time": 80, "player_key": "briar", "team": "ORDER"},
            {"type": "death", "time": 80, "player_key": "jax", "team": "CHAOS"},
            {"type": "kill", "time": 80, "player_key": "jax", "team": "CHAOS"},
            {"type": "death", "time": 80, "player_key": "briar", "team": "ORDER"},
        ],
    }

    events = _public_session(session, {"game_time_offset": 0})["events"]
    fights = [event for event in events if event["type"] in {"kill", "death"}]
    assert len(fights) == 2
    assert {event["label"] for event in fights} == {
        "Briar asesinó a Jax", "Jax asesinó a Briar"
    }

