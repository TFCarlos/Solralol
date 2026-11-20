from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
from app.services.match_analysis_models import enriquecer_analisis_partida, validar_analisis_partida
from app.services.storage_manager import get_storage_manager
from backend.soloq_analyses import _rebuild_saved_ai_timeline_index


def _match(events: list[dict], duration: int = 2400, local_index: int = 0) -> dict:
    players = []
    for index in range(10):
        allied = index < 5
        players.append({
            "player_key": f"p{index}",
            "champion": f"Champion{index}",
            "team": "BLUE" if allied else "RED",
            "is_ally": allied,
            "role": "JUNGLE" if index in {0, 5} else "UNKNOWN",
        })
    return {
        "metadata": {"local_team": "BLUE", "duration_seconds": duration},
        "local_player_key": f"p{local_index}",
        "user_stats": {"champion": f"Champion{local_index}", "items": []},
        "all_players": players,
        "events_chronology": events,
    }


def _kill(order: int, at: int, killer: int, victim: int, assists: list[int] | None = None, bounty: int | None = None) -> dict:
    result = {
        "order": order,
        "time_seconds": at,
        "time_label": f"{at // 60:02d}:{at % 60:02d}",
        "type": "CHAMPION_KILL",
        "killer_key": f"p{killer}",
        "victim_key": f"p{victim}",
        "assister_keys": [f"p{index}" for index in assists or []],
        "team": "BLUE" if killer < 5 else "RED",
        "label": f"Champion{killer} eliminó a Champion{victim}.",
    }
    if bounty is not None:
        result["bounty"] = bounty
        result["shutdown"] = True
    return result


def _objective(
    order: int, at: int, team: str = "BLUE", name: str = "DRAGON",
    kind: str = "ELITE_MONSTER_KILL", finisher: int | None = -1,
    *, owner_team: str | None = None, source_reference: str | None = None,
) -> dict:
    if finisher == -1 and team in {"BLUE", "RED"}:
        finisher = 0 if team == "BLUE" else 5
    return {
        "order": order,
        "event_id": f"event-{order}",
        "source_reference": source_reference or f"source-{order}",
        "time_seconds": at,
        "time_label": f"{at // 60:02d}:{at % 60:02d}",
        "type": kind,
        "team": team,
        "objective_team": team,
        "owner_team": owner_team,
        "team_source": "official",
        "player_key": f"p{finisher}" if finisher is not None else "",
        "objective": name,
        "label": f"Equipo {team} consiguio {name}.",
    }


def _analysis(evidence: dict, payload: dict | None = None) -> dict:
    source = payload or {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen anterior conservado."},
        "key_events": [],
    }
    return enriquecer_analisis_partida(source, {"analysis_evidence": evidence})


def test_three_deaths_with_consecutive_gaps_below_30_seconds_are_not_a_teamfight():
    events = [_kill(0, 600, 0, 5), _kill(1, 612, 1, 6), _kill(2, 627, 2, 7)]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert evidence["teamfights"] == []


def test_four_deaths_without_player_participation_are_globally_detected_but_personally_hidden():
    events = [_kill(0, 600, 1, 5), _kill(1, 612, 2, 6), _kill(2, 627, 6, 1), _kill(3, 640, 7, 2)]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert len(evidence["teamfights"]) == 1
    assert evidence["teamfights"][0]["local_player_involved"] is False
    assert evidence["personal_event_selection"]["teamfights"] == []
    assert not any(item["candidate_type"] == "teamfight_cluster" for item in evidence["key_event_candidates"])


def test_player_assist_or_death_makes_four_death_cluster_personal():
    assisted = [_kill(0, 600, 1, 5, assists=[0]), _kill(1, 612, 2, 6), _kill(2, 627, 6, 1), _kill(3, 640, 7, 2)]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(assisted))
    assert evidence["personal_event_selection"]["teamfights"][0]["player_assists"] == 1
    with_death = [_kill(0, 600, 1, 0), _kill(1, 612, 2, 6), _kill(2, 627, 6, 1), _kill(3, 640, 7, 2)]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(with_death))
    assert evidence["personal_event_selection"]["teamfights"][0]["player_deaths"] == 1


def test_four_deaths_with_consecutive_gaps_below_30_seconds_create_candidate():
    events = [_kill(0, 600, 0, 5), _kill(1, 612, 1, 6), _kill(2, 627, 2, 7), _kill(3, 640, 3, 8)]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert len(evidence["teamfights"]) == 1
    assert evidence["teamfights"][0]["death_count"] == 4
    assert evidence["teamfights"][0]["max_gap_seconds"] == 15


def test_two_deaths_do_not_create_a_teamfight():
    evidence = MatchAnalysisEvidenceService().build_evidence(
        _match([_kill(0, 600, 0, 5), _kill(1, 610, 1, 6)])
    )
    assert evidence["teamfights"] == []


def test_separate_combat_clusters_remain_separate():
    events = [
        _kill(0, 600, 0, 5), _kill(1, 610, 1, 6), _kill(2, 620, 2, 7), _kill(3, 630, 3, 8),
        _kill(4, 1000, 0, 5), _kill(5, 1010, 1, 6), _kill(6, 1020, 2, 7), _kill(7, 1030, 3, 8),
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert [(fight["start_seconds"], fight["death_count"]) for fight in evidence["teamfights"]] == [(600, 4), (1000, 4)]


def test_long_kill_chain_is_split_at_maximum_cluster_duration():
    events = [_kill(i, 100 + 25 * i, i % 5, 5 + (i % 5)) for i in range(10)]
    fights = MatchAnalysisEvidenceService().build_evidence(_match(events))["teamfights"]
    assert len(fights) == 2
    assert all(fight["duration_seconds"] <= 120 for fight in fights)
    assert [fight["death_count"] for fight in fights] == [5, 5]


def test_distant_kills_without_participant_overlap_do_not_merge_when_positions_exist():
    events = [
        {**_kill(0, 600, 0, 5), "position": {"x": 1000, "y": 1000}},
        {**_kill(1, 610, 1, 6), "position": {"x": 9000, "y": 9000}},
        {**_kill(2, 620, 2, 7), "position": {"x": 1000, "y": 1000}},
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert evidence["teamfights"] == []


def test_fight_is_correlated_with_baron_captured_45_seconds_later():
    events = [
        _kill(0, 1000, 0, 5), _kill(1, 1010, 1, 6),
        _kill(2, 1020, 2, 7), _kill(3, 1025, 3, 8),
        _objective(4, 1070, "BLUE", "BARON_NASHOR"),
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert len(evidence["teamfights"]) == 1
    assert any(
        relation["relationship"] == "fight_before_objective"
        and relation["seconds_between_fight_end_and_objective"] == 45
        for relation in evidence["fight_objective_correlations"]
    )


def test_objective_without_combat_is_still_extracted_and_retained():
    evidence = MatchAnalysisEvidenceService().build_evidence(
        _match([_objective(0, 1200, "BLUE", "DRAGON", finisher=0)])
    )
    assert len(evidence["objectives"]) == 1
    assert evidence["objectives"][0]["team"] == "Equipo aliado"
    report = _analysis(evidence)
    assert any("drag" in event["title"].casefold() for event in report["key_events"])


def test_objective_secured_by_unrelated_player_stays_global_but_is_hidden_personally():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([_objective(0, 1200, "RED", "DRAGON", finisher=5)]))
    assert len(evidence["objectives"]) == 1
    assert evidence["key_event_candidates"] == []


def test_single_kill_before_dragon_is_related_without_fabricating_a_fight():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 0, 5), _objective(1, 1220, "BLUE", "DRAGON"),
    ]))
    assert evidence["teamfights"] == []
    candidate = next(item for item in evidence["key_event_candidates"] if item["candidate_type"] == "validated_kills_before_objective")
    assert candidate["seconds_between_last_kill_and_objective"] == 20


def test_opposing_objectives_and_consecutive_structures_are_candidates():
    events = [
        _objective(0, 1000, "BLUE", "DRAGON"),
        _objective(1, 1050, "RED", "TOWER_BUILDING", "BUILDING_KILL"),
        _objective(2, 1080, "RED", "INHIBITOR_BUILDING", "BUILDING_KILL"),
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    types = {candidate["candidate_type"] for candidate in evidence["global_key_event_candidates"]}
    assert "objective_trade_candidate" in types
    assert "consecutive_structure_captures" in types


def test_objective_subtype_is_preserved_and_turret_plates_are_excluded():
    dragon = {**_objective(0, 900, "BLUE", "DRAGON"), "objective_subtype": "FIRE_DRAGON"}
    plate = {"order": 1, "time_seconds": 920, "time_label": "15:20",
             "type": "TURRET_PLATE_DESTROYED", "team": "BLUE", "player_key": "p0",
             "label": "TURRET_PLATE_DESTROYED"}
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([dragon, plate]))
    assert "Infernal" in evidence["objectives"][0]["objective"]
    assert len(evidence["objectives"]) == 1
    assert evidence["timeline_extraction"]["turret_plates_excluded"] == 1
    assert not any("plate" in str(candidate).casefold() for candidate in evidence["key_event_candidates"])


def test_empty_ai_event_analysis_keeps_deterministic_events():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 600, 0, 5), _kill(1, 612, 1, 6), _kill(2, 627, 2, 7), _kill(3, 638, 3, 8),
        _objective(4, 650, "BLUE", "DRAGON"),
    ]))
    report = _analysis(evidence)
    assert report["key_events"]
    assert any("Combate agrupado" in event["title"] for event in report["key_events"])
    assert any("drag" in event["title"].casefold() for event in report["key_events"])


def test_partial_ai_fight_reference_is_completed_without_duplicate_card():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 600, 0, 5, assists=[0]), _kill(1, 612, 1, 6), _kill(2, 627, 2, 7), _kill(3, 638, 3, 8),
    ]))
    refs = evidence["teamfights"][0]["event_ids"]
    report = _analysis(evidence, {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen existente."},
        "key_events": [{
            "event_ids": refs[:1], "title": "Pelea relevante",
            "description": "La cronología agrupa varias eliminaciones.",
            "why_it_matters": "El intercambio reunió bajas de ambos equipos en pocos segundos.",
        }],
    })
    assert len(report["key_events"]) == 1
    assert report["key_events"][0]["event_ids"] == refs


def test_previously_saved_report_can_rebuild_event_index_from_timeline():
    old_report = {
        "schema_version": 2,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen anterior conservado."},
        "key_events": [],
    }
    match = _match([_kill(0, 600, 0, 5), _objective(1, 620, "BLUE", "DRAGON")])
    report = enriquecer_analisis_partida(old_report, match)
    assert report["summary"]["short_summary"] == "Resumen anterior conservado."
    assert report["match_evidence"]["timeline_extraction"]["status"] == "available"
    assert report["key_events"]


def test_legacy_ai_record_rebuild_updates_only_timeline_fields():
    participants = [
        {"participantId": index + 1, "champion": f"Champion{index}",
         "teamId": 100 if index < 5 else 200,
         "side": "allied" if index < 5 else "enemy", "local": index == 0,
         "role": "JUNGLE"}
        for index in range(10)
    ]
    events = [
        {"id": "0:0:600000", "timestamp": 600000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 1, "victimId": 6, "assistingIds": [], "killerTeamId": 100},
        {"id": "0:1:612000", "timestamp": 612000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 2, "victimId": 7, "assistingIds": [], "killerTeamId": 100},
        {"id": "0:2:627000", "timestamp": 627000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 3, "victimId": 8, "assistingIds": [], "killerTeamId": 100},
        {"id": "0:3:638000", "timestamp": 638000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 4, "victimId": 9, "assistingIds": [], "killerTeamId": 100},
        {"id": "0:4:650000", "timestamp": 650000, "type": "ELITE_MONSTER_KILL", "side": "allied", "killerId": 1, "killerTeamId": 100, "monsterType": "DRAGON"},
    ]
    record = {
        "match_id": "EUW1_fixture", "duration": 1800, "win": True,
        "participants": participants, "ai_analysis": {"analysis": {
            "schema_version": 3, "analysis_type": "general_match_analysis",
            "summary": {"short_summary": "Resumen existente."}, "key_events": [],
        }},
    }
    assert _rebuild_saved_ai_timeline_index(record, events)
    updated = record["ai_analysis"]["analysis"]
    assert updated["summary"]["short_summary"] == "Resumen existente."
    assert updated["match_evidence"]["evidence_version"] == 6
    assert updated["match_evidence"]["coverage"]["champion_kills"] == 4
    assert len(updated["match_evidence"]["objectives"]) == 1
    assert any("Combate agrupado" in event["title"] for event in updated["key_events"])


def test_malformed_saved_key_events_are_rebuilt_from_local_timeline():
    participants = [
        {"participantId": index + 1, "champion": f"Champion{index}",
         "teamId": 100 if index < 5 else 200,
         "side": "allied" if index < 5 else "enemy", "local": index == 0,
         "role": "JUNGLE"}
        for index in range(10)
    ]
    events = [
        {"id": "kill-a", "timestamp": 600000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 1, "victimId": 6, "assistingIds": [], "killerTeamId": 100},
        {"id": "kill-b", "timestamp": 612000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 2, "victimId": 7, "assistingIds": [], "killerTeamId": 100},
        {"id": "kill-c", "timestamp": 627000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 3, "victimId": 8, "assistingIds": [], "killerTeamId": 100},
        {"id": "kill-d", "timestamp": 638000, "type": "CHAMPION_KILL", "side": "allied", "killerId": 4, "victimId": 9, "assistingIds": [], "killerTeamId": 100},
        {"id": "dragon", "timestamp": 650000, "type": "ELITE_MONSTER_KILL", "side": "allied", "killerId": 1, "killerTeamId": 100, "monsterType": "DRAGON"},
    ]
    record = {
        "match_id": "EUW1_legacy_index_fixture", "duration": 1800, "win": True,
        "participants": participants, "ai_analysis": {"analysis": {
            "schema_version": 3, "analysis_type": "general_match_analysis",
            "summary": {"short_summary": "Resumen que debe conservarse."},
            "match_evidence": {"evidence_version": 3, "coverage": {}},
            "key_events": "respuesta antigua malformada",
        }},
    }

    assert _rebuild_saved_ai_timeline_index(record, events)
    analysis = record["ai_analysis"]["analysis"]
    assert analysis["summary"]["short_summary"] == "Resumen que debe conservarse."
    assert isinstance(analysis["match_evidence"]["notable_timeline"], list)
    assert analysis["key_events"]
    assert any("Combate agrupado" in event["title"] for event in analysis["key_events"])


def test_invalid_provider_key_events_fall_back_to_deterministic_timeline():
    source = _match([
        _kill(0, 600, 0, 5), _kill(1, 612, 1, 6), _kill(2, 627, 2, 7),
        _objective(3, 650, name="DRAGON", finisher=0),
    ])
    evidence = MatchAnalysisEvidenceService().build_evidence(source)
    report = enriquecer_analisis_partida({
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Informe válido."},
        "key_events": {"not": "a list"},
    }, {"analysis_evidence": evidence})

    assert report["summary"]["short_summary"] == "Informe válido."
    assert report["key_events"]


def test_provider_key_events_above_six_do_not_invalidate_report():
    payload = {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Informe válido."},
        "key_events": [{
            "event_ids": [f"event-{index}"],
            "title": f"Momento {index}",
            "description": "Hecho registrado.",
            "why_it_matters": "Tiene contexto suficiente para su revisión.",
        } for index in range(7)],
    }

    report = validar_analisis_partida(payload)

    assert len(report["key_events"]) == 7


def test_teamfight_event_can_retain_more_than_six_evidence_references():
    refs = [f"event-{index}" for index in range(9)]
    report = validar_analisis_partida({
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {},
        "key_events": [{
            "event_ids": refs,
            "title": "Pelea de equipo",
            "description": "Se agruparon varias bajas.",
            "why_it_matters": "La secuencia puede cambiar el control del mapa.",
        }],
    })

    assert report["key_events"][0]["event_ids"] == refs


def test_one_malformed_key_event_does_not_discard_valid_siblings():
    valid = {
        "event_ids": ["event-good"], "title": "Objetivo registrado",
        "description": "El equipo asegura el dragón.",
        "why_it_matters": "El objetivo queda confirmado en la cronología.",
    }
    report = validar_analisis_partida({
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {},
        "key_events": [valid, None, {**valid, "title": 42}, {**valid, "event_ids": "event-bad"}],
    })

    assert report["key_events"] == [{
        "event_ids": ["event-good"], "title": "Objetivo registrado",
        "description": "El equipo asegura el dragón.",
        "why_it_matters": "El objetivo queda confirmado en la cronología.",
    }]


def test_timeline_index_keeps_more_than_forty_distinct_objective_events():
    events = [_objective(index, 100 + index * 200, name="DRAGON", finisher=0)
              for index in range(45)]
    source = _match(events, duration=12000)
    evidence = MatchAnalysisEvidenceService().build_evidence(source)
    report = enriquecer_analisis_partida({
        "schema_version": 3, "analysis_type": "general_match_analysis",
        "summary": {}, "key_events": [],
    }, {**source, "analysis_evidence": evidence})

    assert len(evidence["key_event_candidates"]) == 45
    assert len(report["key_events"]) == 45


def test_actual_saved_match_timeline_has_no_objective_or_fight_classification_loss():
    root = get_storage_manager().root
    candidates = sorted(
        (root / "match_logs").glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    source = None
    for path in candidates:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value.get("events_chronology"), list) and value["events_chronology"]:
            source = value
            break
    if source is None:
        pytest.skip("No hay una partida guardada con cronología local en este entorno.")

    evidence = MatchAnalysisEvidenceService().build_evidence(source)
    raw_events = source["events_chronology"]
    expected_kills = sum(event.get("type") == "CHAMPION_KILL" for event in raw_events)
    expected_objectives = sum(event.get("type") in {"ELITE_MONSTER_KILL", "BUILDING_KILL"} for event in raw_events)
    assert evidence["timeline_extraction"]["source_events"] == len(raw_events)
    assert evidence["coverage"]["champion_kills"] == expected_kills
    assert len(evidence["objectives"]) == expected_objectives
    report = _analysis(evidence)
    refs_renderable = {
        ref for item in report["key_events"] for ref in item.get("event_ids", [])
    }
    assert len(report["key_events"]) >= len(evidence["teamfights"])
    assert all(ref in {item["event_id"] for item in evidence["notable_timeline"]} for ref in refs_renderable)


@pytest.mark.parametrize("finisher,expected", [(1, True), (2, False)])
def test_turret_correlation_requires_killer_or_assistant(finisher, expected):
    tower = _objective(1, 1040, "BLUE", "TOWER_BUILDING", "BUILDING_KILL", finisher=finisher, owner_team="RED")
    tower["team"] = "RED"  # Simulate the structure owner field being passed as a generic team.
    events = [_kill(0, 1000, 0, 5, assists=[1]), tower]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert (len(evidence["kill_objective_correlations"]) == 1) is expected
    if expected:
        relation = evidence["kill_objective_correlations"][0]
        assert relation["shared_participant"] == "Champion1"
        assert relation["objective_team_id"] == relation["kill_team_id"] == "BLUE"


def test_kill_participant_can_validate_dragon_finisher():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 0, 5),
        _objective(1, 1240, "BLUE", "DRAGON", finisher=0),
    ]))
    assert len(evidence["kill_objective_correlations"]) == 1
    assert "drag" in evidence["kill_objective_correlations"][0]["objective"].casefold()


@pytest.mark.parametrize("local_index", [0, 1])
def test_personal_conversion_is_visible_for_killer_and_assisting_finisher(local_index):
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 0, 5, assists=[1]),
        _objective(1, 1240, "BLUE", "TOWER_BUILDING", "BUILDING_KILL", finisher=1),
    ], local_index=local_index))
    selection = evidence["personal_event_selection"]
    assert selection["objective_event_ids"] == ["event-1"]
    assert any(item["candidate_type"] == "validated_kills_before_objective" for item in selection["candidates"])


def test_unrelated_player_does_not_get_personal_kill_objective_conversion():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 0, 5, assists=[1]),
        _objective(1, 1240, "BLUE", "TOWER_BUILDING", "BUILDING_KILL", finisher=1),
    ], local_index=4))
    assert evidence["kill_objective_correlations"]
    assert evidence["personal_event_selection"]["objective_event_ids"] == []
    assert evidence["personal_event_selection"]["candidates"] == []


def test_player_death_followed_by_enemy_assistant_dragon_is_personal_negative_event():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]),
        _objective(1, 1260, "RED", "DRAGON", finisher=6),
    ]))
    relations = evidence["player_death_objective_correlations"]
    assert len(relations) == 1
    assert relations[0]["relationship"] == "player_death_to_enemy_objective"
    assert relations[0]["death_event_id"] == "event-0"
    assert relations[0]["objective_event_id"] == "event-1"
    assert relations[0]["objective_finisher_id"] == "enemy_2"
    selection = evidence["personal_event_selection"]
    assert selection["objective_event_ids"] == ["event-1"]
    assert {"event-0", "event-1"}.issubset(selection["personal_event_ids"])
    event = next(item for item in _analysis(evidence)["key_events"] if item.get("event_kind") == "player_death_to_enemy_objective")
    assert event["event_ids"] == ["event-0", "event-1"]
    assert "Posteriormente" in event["description"]


def test_ai_interpretation_of_verified_negative_conversion_survives_validation():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]),
        _objective(1, 1260, "RED", "DRAGON", finisher=6),
    ]))
    payload = {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen guardado."},
        "key_events": [{
            "event_ids": ["event-0", "event-1"],
            "title": "Tu muerte precedio al objetivo rival",
            "description": "Champion5 elimino al jugador y Champion6 aseguro el dragon.",
            "why_it_matters": "La muerte precedio una captura rival confirmada.",
            "event_kind": "player_death_to_enemy_objective",
        }],
    }
    report = _analysis(evidence, payload)
    assert len(report["key_events"]) == 1
    assert report["key_events"][0]["event_kind"] == "player_death_to_enemy_objective"


def test_player_death_followed_by_enemy_killer_turret_is_personal_negative_event():
    tower = _objective(1, 1260, "RED", "TOWER_BUILDING", "BUILDING_KILL", finisher=5, owner_team="BLUE")
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]), tower,
    ]))
    assert len(evidence["player_death_objective_correlations"]) == 1
    assert evidence["player_death_objective_correlations"][0]["objective_type"] == "structure"
    negative_event = next(item for item in _analysis(evidence)["key_events"] if item.get("event_kind") == "player_death_to_enemy_objective")
    assert "torre" in negative_event["description"].casefold()


def test_player_death_is_not_linked_to_uninvolved_enemy_objective_finisher():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]),
        _objective(1, 1260, "RED", "DRAGON", finisher=7),
    ]))
    assert evidence["player_death_objective_correlations"] == []
    assert not any(item["candidate_type"] == "player_death_to_enemy_objective" for item in evidence["key_event_candidates"])


def test_player_death_objective_requires_matching_enemy_beneficiary_team():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]),
        _objective(1, 1260, "BLUE", "DRAGON", finisher=6),
    ]))
    assert evidence["player_death_objective_correlations"] == []


def test_player_death_enemy_objective_requires_time_window_and_identified_finisher():
    outside_window = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]),
        _objective(1, 1321, "RED", "DRAGON", finisher=6),
    ]))
    missing_finisher = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]),
        _objective(1, 1260, "RED", "DRAGON", finisher=None),
    ]))
    assert outside_window["player_death_objective_correlations"] == []
    assert missing_finisher["player_death_objective_correlations"] == []


def test_player_death_objective_conversion_links_to_qualifying_teamfight_once():
    events = [
        _kill(0, 1200, 5, 0, assists=[6]),
        _kill(1, 1210, 1, 5),
        _kill(2, 1220, 6, 1),
        _kill(3, 1230, 2, 6),
        _objective(4, 1250, "RED", "BARON_NASHOR", finisher=6),
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert len(evidence["teamfights"]) == 1
    assert evidence["teamfights"][0]["local_player_involved"] is True
    assert len(evidence["player_death_objective_correlations"]) == 1
    assert len(evidence["personal_event_selection"]["player_death_objective_correlations"]) == 1
    fight_refs = [f"event-{index}" for index in range(4)]
    ai_payload = {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen guardado."},
        "key_events": [{
            "event_ids": fight_refs,
            "title": "Combate agrupado",
            "description": "Hubo bajas en ambos equipos.",
            "why_it_matters": "La pelea produjo varias bajas confirmadas.",
            "event_kind": "teamfight_cluster",
        }],
    }
    report = _analysis(evidence, ai_payload)
    assert len(report["key_events"]) == 1
    merged = report["key_events"][0]
    assert merged["event_kind"] == "player_death_to_enemy_objective"
    assert "event-4" in merged["event_ids"]


def test_player_death_objective_pair_deduplicates_duplicate_source_deaths():
    death = _kill(0, 1200, 5, 0, assists=[6])
    duplicate = {**death, "order": 8, "event_id": "event-8"}
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        death, duplicate, _objective(1, 1260, "RED", "DRAGON", finisher=6),
    ]))
    relations = evidence["player_death_objective_correlations"]
    assert len(relations) == 1
    assert relations[0]["correlation_id"] == "death_objective:event-0:event-1"


def test_player_death_followed_by_turret_plate_never_creates_objective_conversion():
    plate = {"order": 1, "time_seconds": 1260, "time_label": "21:00",
             "type": "TURRET_PLATE_DESTROYED", "team": "RED", "player_key": "p5",
             "label": "TURRET_PLATE_DESTROYED"}
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 5, 0, assists=[6]), plate,
    ]))
    assert evidence["player_death_objective_correlations"] == []
    assert not any(item["candidate_type"] == "player_death_to_enemy_objective" for item in evidence["key_event_candidates"])


def test_exact_700_shutdown_requires_personal_kill_or_assist():
    secured = MatchAnalysisEvidenceService().build_evidence(_match([_kill(0, 600, 0, 5, bounty=700)]))
    assisted = MatchAnalysisEvidenceService().build_evidence(_match([_kill(0, 600, 1, 5, assists=[0], bounty=700)]))
    lower = MatchAnalysisEvidenceService().build_evidence(_match([_kill(0, 600, 0, 5, bounty=500)]))
    unrelated = MatchAnalysisEvidenceService().build_evidence(_match([_kill(0, 600, 1, 5, bounty=700)]))
    assert secured["personal_event_selection"]["shutdowns"][0]["participation"] == "secured"
    assert assisted["personal_event_selection"]["shutdowns"][0]["participation"] == "assisted"
    assert lower["personal_event_selection"]["shutdowns"] == []
    assert unrelated["personal_event_selection"]["shutdowns"] == []


def test_large_gold_balance_without_explicit_shutdown_is_not_reward_event():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([_kill(0, 600, 0, 5)]))
    assert evidence["personal_event_selection"]["shutdowns"] == []
    assert not any(item["candidate_type"] == "confirmed_700_shutdown" for item in evidence["key_event_candidates"])


def test_unrelated_baron_finisher_is_not_correlated():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1200, 1, 5),
        _objective(1, 1240, "BLUE", "BARON_NASHOR", finisher=2),
    ]))
    assert evidence["kill_objective_correlations"] == []
    assert not any(item["candidate_type"] == "objective_capture" for item in evidence["key_event_candidates"])


def test_turret_plate_after_kill_creates_no_event_or_correlation():
    plate = {"order": 1, "time_seconds": 1040, "time_label": "17:20",
             "type": "TURRET_PLATE_DESTROYED", "team": "BLUE", "player_key": "p0",
             "source_reference": "plate-1", "label": "TURRET_PLATE_DESTROYED"}
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5), plate,
    ]))
    assert evidence["objectives"] == []
    assert evidence["kill_objective_correlations"] == []
    assert not any("plate" in str(candidate).casefold() for candidate in evidence["key_event_candidates"])


def test_turret_destroyed_without_player_finisher_remains_independent():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5),
        _objective(1, 1040, "BLUE", "TOWER_BUILDING", "BUILDING_KILL", finisher=None),
    ]))
    assert len(evidence["objectives"]) == 1
    assert evidence["kill_objective_correlations"] == []
    assert not any(item["candidate_type"] == "objective_capture" for item in evidence["key_event_candidates"])


def test_matching_finisher_with_mismatched_beneficiary_team_is_rejected():
    event = _objective(1, 1040, "RED", "TOWER_BUILDING", "BUILDING_KILL", finisher=0)
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5), event,
    ]))
    assert evidence["kill_objective_correlations"] == []
    assert evidence["timeline_extraction"]["correlation_diagnostics"]["invalid_team"] > 0


def test_matching_turret_finisher_outside_90_second_window_is_rejected():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5),
        _objective(1, 1091, "BLUE", "TOWER_BUILDING", "BUILDING_KILL", finisher=0),
    ]))
    assert evidence["kill_objective_correlations"] == []
    assert evidence["timeline_extraction"]["correlation_diagnostics"]["exceeded_time_window"] == 1


def test_teamfight_objective_requires_finisher_participation_and_fight_remains():
    events = [
        _kill(0, 1000, 0, 5), _kill(1, 1010, 1, 6), _kill(2, 1020, 2, 7), _kill(3, 1030, 3, 8),
        _objective(4, 1070, "BLUE", "BARON_NASHOR", finisher=4),
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert len(evidence["teamfights"]) == 1
    assert evidence["fight_objective_correlations"] == []
    assert any(item["candidate_type"] == "teamfight_cluster" for item in evidence["key_event_candidates"])


def test_teamfight_objective_link_is_valid_when_finisher_participated():
    events = [
        _kill(0, 1000, 0, 5), _kill(1, 1010, 1, 6), _kill(2, 1020, 2, 7), _kill(3, 1030, 3, 8),
        _objective(4, 1070, "BLUE", "BARON_NASHOR", finisher=0),
    ]
    evidence = MatchAnalysisEvidenceService().build_evidence(_match(events))
    assert len(evidence["teamfights"]) == 1
    assert len(evidence["fight_objective_correlations"]) == 1
    assert evidence["fight_objective_correlations"][0]["validation"] == "verified_finisher_participated_in_fight_kill"


def test_duplicate_objective_source_events_create_only_one_relationship():
    objective_a = _objective(1, 1040, "BLUE", "DRAGON", finisher=0, source_reference="riot-objective-1")
    objective_b = {**objective_a, "order": 2, "event_id": "event-2"}
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5), objective_a, objective_b,
    ]))
    assert len(evidence["objectives"]) == 1
    assert len(evidence["kill_objective_correlations"]) == 1
    assert sum(item["candidate_type"] == "validated_kills_before_objective" for item in evidence["key_event_candidates"]) == 1


def test_duplicate_kill_takedowns_do_not_duplicate_relationships():
    kill_a = _kill(0, 1000, 0, 5)
    kill_b = {**kill_a, "order": 1, "event_id": "duplicate-kill"}
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        kill_a, kill_b, _objective(2, 1040, "BLUE", "DRAGON", finisher=0),
    ]))
    assert len(evidence["kill_objective_correlations"]) == 1


def test_ai_cannot_keep_an_unvalidated_kill_objective_claim():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 1, 5),
        _objective(1, 1040, "BLUE", "BARON_NASHOR", finisher=2),
    ]))
    report = _analysis(evidence, {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen conservado."},
        "key_events": [{
            "event_ids": ["event-0", "event-1"],
            "title": "Relacion inventada",
            "description": "Una baja fue seguida por un objetivo.",
            "why_it_matters": "La proximidad de ambos eventos cambiaria el resultado del mapa.",
        }],
    })
    assert all(item["title"] != "Relacion inventada" for item in report["key_events"])


def test_ai_cannot_keep_event_that_does_not_personally_involve_analyzed_player():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 1, 5),
        _objective(1, 1040, "RED", "BARON_NASHOR", finisher=5),
    ]))
    report = _analysis(evidence, {
        "schema_version": 3, "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen conservado."},
        "key_events": [{
            "event_ids": ["event-1"], "title": "Baron rival",
            "description": "Un rival aseguró el Barón.",
            "why_it_matters": "El Barón fue asegurado por un jugador que no es quien se analiza.",
        }],
    })
    assert report["key_events"] == []


def test_shutdown_fallback_has_no_repetitive_causality_disclaimer():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([_kill(0, 600, 0, 5, bounty=700)]))
    report = _analysis(evidence)
    event = next(item for item in report["key_events"] if "Shutdown" in item["title"])
    assert "700 de oro" in event["why_it_matters"]
    assert "no demuestra causalidad" not in event["why_it_matters"].casefold()


def test_screenshot_0831_kill_multiple_plates_and_later_tower():
    match = _match([
        _kill(0, 511, 0, 5, assists=[1]),
        {"order": 1, "time_seconds": 520, "time_label": "08:40", "type": "TURRET_PLATE_DESTROYED", "team": "BLUE", "player_key": "p0", "source_reference": "plate-a"},
        {"order": 2, "time_seconds": 528, "time_label": "08:48", "type": "TURRET_PLATE_DESTROYED", "team": "BLUE", "player_key": "p0", "source_reference": "plate-b"},
        {"order": 3, "time_seconds": 531, "time_label": "08:51", "type": "TURRET_PLATE_DESTROYED", "team": "BLUE", "player_key": "p0", "source_reference": "plate-c"},
        _objective(4, 545, "BLUE", "TOWER_BUILDING", "BUILDING_KILL", finisher=1, owner_team="RED"),
    ])
    match["all_players"][0]["champion"] = "Briar"
    match["all_players"][1]["champion"] = "Darius"
    match["all_players"][5]["champion"] = "Irelia"
    evidence = MatchAnalysisEvidenceService().build_evidence(match)
    assert evidence["timeline_extraction"]["turret_plates_excluded"] == 3
    assert len(evidence["objectives"]) == 1
    assert len(evidence["kill_objective_correlations"]) == 1
    assert evidence["kill_objective_correlations"][0]["shared_participant"] == "Darius"
    assert len(evidence["key_event_candidates"]) == len({
        (item["candidate_type"], tuple(item.get("event_ids", [])))
        for item in evidence["key_event_candidates"]
    })


def test_invalid_timestamps_are_reported_without_correlation():
    event = _objective(1, 1040, "BLUE", "DRAGON", finisher=0)
    event["time_seconds"] = None
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5), event,
    ]))
    assert evidence["kill_objective_correlations"] == []
    assert evidence["timeline_extraction"]["correlation_diagnostics"]["invalid_timestamp"] > 0


def test_valid_objective_relation_merges_into_existing_objective_card():
    evidence = MatchAnalysisEvidenceService().build_evidence(_match([
        _kill(0, 1000, 0, 5),
        _objective(1, 1040, "BLUE", "DRAGON", finisher=0),
    ]))
    report = _analysis(evidence, {
        "schema_version": 3,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Resumen conservado."},
        "key_events": [{
            "event_ids": ["event-1"],
            "title": "Dragon secured",
            "description": "Se registro la captura del Dragon.",
            "why_it_matters": "La captura del objetivo modifica los recursos disponibles en el mapa.",
        }],
    })
    assert len(report["key_events"]) == 1
    assert set(report["key_events"][0]["event_ids"]) == {"event-0", "event-1"}
