import json
import re

from _paths import DATA_DIR
from backend.soloq_analyses import _recover_saved_rune_evaluation
from app.services.match_analysis_models import (
    _evaluar_runas,
    _validar_alternativa_runa,
    _validar_alternativas_objetos_modelo,
)


def test_rune_evaluation_includes_actual_localized_selection_details():
    catalog_path = DATA_DIR / "runes_reforged_16.20.1.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tree = catalog[0]
    keystone = tree["slots"][0]["runes"][0]

    result = _evaluar_runas(
        {
            "styles": [
                {
                    "selections": [
                        {"perk": keystone["id"]},
                    ]
                }
            ]
        },
        "16.20.1",
        "Build de prueba",
    )

    assert result is not None
    assert result["current"]["id"] == str(keystone["id"])
    assert len(result["selected_runes"]) == 1
    selected = result["selected_runes"][0]
    assert selected["id"] == str(keystone["id"])
    assert selected["name"] == keystone["name"]
    assert selected["tree"] == "Principal"
    assert selected["kind"] == "Clave"
    assert re.sub(r"<[^>]+>", "", selected["description"])


def test_model_rune_alternative_must_be_a_keystone_in_the_recorded_tree():
    catalog = json.loads((DATA_DIR / "runes_reforged_16.20.1.json").read_text(encoding="utf-8"))
    tree = catalog[0]
    keys = tree["slots"][0]["runes"]
    current, replacement = keys[0], keys[1]
    context = {
        "user_stats": {
            "runes": {
                "styles": [{"style": tree["id"], "selections": [{"perk": current["id"]}]}]
            }
        },
        "model_rune_alternatives": [{
            "rune_id": str(replacement["id"]),
            "replaces_rune_id": str(current["id"]),
            "reason": "Encaja mejor con el patrón de intercambios observado.",
            "tradeoff": "Pierde presión prolongada.",
        }],
    }

    result = _validar_alternativa_runa(
        context,
        {"patch": "16.20.1", "current": {"id": str(current["id"])}},
        compatible=True,
    )
    assert result is not None
    assert result["id"] == str(replacement["id"])
    assert result["tree_id"] == str(tree["id"])

    context["model_rune_alternatives"][0]["rune_id"] = str(catalog[1]["slots"][0]["runes"][0]["id"])
    assert _validar_alternativa_runa(
        context,
        {"patch": "16.20.1", "current": {"id": str(current["id"])}},
        compatible=True,
    ) is None


def test_model_item_alternative_requires_catalogued_summoners_rift_item_and_real_enemy():
    items = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))["items"]
    legal = next(
        item_id for item_id, item in items.items()
        if item.get("maps", {}).get("11") is True
        and item.get("gold", {}).get("purchasable") is True
        and item.get("gold", {}).get("total", 0) > 0
    )
    replaced = next(item_id for item_id in items if item_id != legal)
    candidate = {
        "item_id": legal,
        "replace_or_delay_item_id": replaced,
        "threat_champion_id": "Pantheon",
        "mechanical_advantage": "Aporta una respuesta concreta a la amenaza registrada.",
        "tradeoff": "Se retrasa el daño ofensivo.",
    }
    context = {
        "user_stats": {"items": [replaced]},
        "all_players": [{"champion": "Pantheon", "is_ally": False}],
        "analysis_evidence": {"notable_timeline": []},
        "model_item_alternatives": [candidate],
    }

    accepted = _validar_alternativas_objetos_modelo(context, [], compatible=True)
    assert len(accepted) == 1
    assert accepted[0]["item_id"] == legal
    assert accepted[0]["replace_or_delay_item_id"] == replaced

    context["model_item_alternatives"][0]["threat_champion_id"] = "UnknownChampion"
    assert _validar_alternativas_objetos_modelo(context, [], compatible=True) == []


def test_legacy_report_recovers_only_rune_evaluation_from_saved_match_data():
    catalog = json.loads((DATA_DIR / "runes_reforged_16.20.1.json").read_text(encoding="utf-8"))
    keystone = catalog[0]["slots"][0]["runes"][0]
    record = {
        "patch": "16.20.1",
        "ai_analysis": {"analysis": {"summary": {"short_summary": "Resumen existente"}, "game_phases": {"early": {"assessment": "Fase conservada"}}}},
        "participants": [{
            "local": True,
            "items": [],
            "runes": {"styles": [{"style": catalog[0]["id"], "selections": [{"perk": keystone["id"]}]}]},
        }],
    }

    assert _recover_saved_rune_evaluation(record)
    saved = record["ai_analysis"]["analysis"]
    assert saved["summary"]["short_summary"] == "Resumen existente"
    assert saved["game_phases"]["early"]["assessment"] == "Fase conservada"
    assert saved["rune_evaluation"]["current"]["id"] == str(keystone["id"])
    assert saved["rune_evaluation"]["assessment_source"] == "saved_match_reconstruction"
    assert not _recover_saved_rune_evaluation(record)
