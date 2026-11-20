from __future__ import annotations

import pytest

from backend.combat_matchups import _local_participant, _validate_response, build_matchup_context, persist_status
from backend.soloq_analyses import get_ai_status


@pytest.fixture
def match_record():
    names = ["Briar", "Irelia", "Wukong", "Qiyana", "Miss Fortune", "Pantheon"]
    champion_keys = [233, 39, 62, 246, 21, 80]
    participants = [
        {
            "participantId": index + 1,
            "champion": name,
            "championId": champion_keys[index],
            "role": "JUNGLE" if index == 0 else "MIDDLE",
            "side": "allied" if index == 0 else "enemy",
            "local": index == 0,
        }
        for index, name in enumerate(names)
    ]
    return {
        "champion": "Briar",
        "champion_id": "233",
        "role": "JUNGLE",
        "patch": "16.20.1",
        "participants": participants,
        "events": [{"type": "CHAMPION_KILL", "victimId": 1, "killerId": 3, "timestamp": 123456}],
    }


def test_context_resolves_all_five_enemy_champions_and_local_abilities(match_record):
    result = build_matchup_context(match_record)

    assert result["available"] is True
    assert result["player"]["champion_id"] == "Briar"
    assert {item["champion_id"] for item in result["enemies"]} == {
        "Irelia", "MonkeyKing", "Qiyana", "MissFortune", "Pantheon"
    }
    assert all({"q", "w", "e", "r"}.issubset({ability["slot"] for ability in item["abilities"]}) for item in [result["player"], *result["enemies"]])


def test_context_attributes_only_confirmed_enemy_kill_events(match_record):
    result = build_matchup_context(match_record)
    by_id = {item["champion_id"]: item for item in result["enemies"]}

    assert by_id["MonkeyKing"]["match_observation"] == {
        "kind": "confirmed_deaths_by_enemy", "count": 1, "timestamps": ["2:03"]
    }
    assert by_id["Pantheon"]["match_observation"] is None


def test_context_requires_exactly_five_enemy_participants(match_record):
    match_record["participants"].append({"participantId": 7, "champion": "Nautilus", "side": "enemy"})

    result = build_matchup_context(match_record)

    assert result["available"] is False
    assert "cinco campeones" in result["reason"]


def test_local_resolution_does_not_match_empty_champion_metadata():
    assert _local_participant({}, [{"participantId": 1}, {"participantId": 2}]) is None


def test_matchup_response_rejects_ability_slots_missing_from_local_catalog(match_record):
    context = build_matchup_context(match_record)
    rows = []
    for enemy in context["enemies"]:
        rows.append({
            "enemy_champion_id": enemy["champion_id"], "difficulty": "medium",
            "difficulty_reason": "Orientación cualitativa basada en las herramientas disponibles.",
            "key_enemy_abilities": [{"slot": "q", "reason": "Amenaza relevante del kit."}],
            "relevant_player_abilities": [{"slot": "e", "use": "Respuesta posible si se cumplen las condiciones descritas."}],
            "combat_strategy": "Usa la respuesta solo cuando la interacción sea favorable.",
            "counterplay_windows": "Espera a observar el uso de la herramienta antes de buscar el intercambio.",
            "mistakes_to_avoid": ["No fuerces el intercambio en desventaja."],
            "target_priority": "Evalúa la amenaza y el acceso antes de elegir objetivo.",
            "teamfight_considerations": "La prioridad puede cambiar en una pelea de equipo.",
            "match_specific_observations": "",
            "strategic_tip": "Recuerda comprobar qué herramientas se han usado.",
        })
    rows[0]["key_enemy_abilities"] = [{"slot": "z", "reason": "No existe esa ranura."}]

    with pytest.raises(ValueError, match="incompleto"):
        _validate_response({"matchups": rows}, context)
    with pytest.raises(ValueError, match="exactamente cinco"):
        _validate_response({"matchups": rows + [rows[0]]}, context)


def test_failed_regeneration_status_keeps_saved_matchups(monkeypatch):
    import backend.soloq_analyses as saved

    matchups = {"schema_version": 1, "matchups": [{"enemy_champion_id": "Pantheon"}]}
    record = {"match_id": "EUW1_123", "combat_matchups": matchups}

    class Repository:
        def load_last_profile(self):
            return {"id": "profile"}

        def save_soloq_analysis(self, profile, updated):
            record.update(updated)

    monkeypatch.setattr(saved, "_records", lambda repository, profile: [record])
    persist_status(Repository(), "EUW1_123", "error", "No se pudo generar.")

    assert record["combat_matchups"] == matchups
    assert record["combat_generation_status"] == "error"


def test_ai_status_is_a_compact_read_of_saved_analysis(monkeypatch):
    import backend.soloq_analyses as saved

    record = {
        "match_id": "EUW1_123", "ai_generation_status": "generating",
        "ai_analysis": {"analysis": {"summary": {}}, "provider": "Gemini", "source_response": "large private payload"},
    }

    class Repository:
        def load_last_profile(self):
            return {"id": "profile"}

    monkeypatch.setattr(saved, "_records", lambda repository, profile: [record])
    status = get_ai_status(Repository(), "EUW1_123")

    assert status["ai_generation_status"] == "generating"
    assert status["ai_analysis"] == {"analysis": {"summary": {}}, "provider": "Gemini"}
