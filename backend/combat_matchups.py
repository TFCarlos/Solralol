"""Match specific champion combat coaching backed by local Data Dragon data."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _paths import DATA_DIR
from app.services.settings_service import SettingsService

COMBAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "matchups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "enemy_champion_id": {"type": "string"},
                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                    "difficulty_reason": {"type": "string"},
                    "key_enemy_abilities": {"type": "array", "items": {"type": "object", "properties": {"slot": {"type": "string"}, "reason": {"type": "string"}}, "required": ["slot", "reason"]}},
                    "relevant_player_abilities": {"type": "array", "items": {"type": "object", "properties": {"slot": {"type": "string"}, "use": {"type": "string"}}, "required": ["slot", "use"]}},
                    "combat_strategy": {"type": "string"},
                    "baiting_strategy": {"type": "string"},
                    "counterplay_windows": {"type": "string"},
                    "mistakes_to_avoid": {"type": "array", "items": {"type": "string"}},
                    "target_priority": {"type": "string"},
                    "teamfight_considerations": {"type": "string"},
                    "match_specific_observations": {"type": "string"},
                    "strategic_tip": {"type": "string"},
                },
                "required": ["enemy_champion_id", "difficulty", "difficulty_reason", "key_enemy_abilities", "relevant_player_abilities", "combat_strategy", "baiting_strategy", "counterplay_windows", "mistakes_to_avoid", "target_priority", "teamfight_considerations", "match_specific_observations", "strategic_tip"],
            },
        }
    },
    "required": ["matchups"],
}


def _clean_description(value: Any) -> str:
    raw = html.unescape(str(value or ""))
    raw = re.sub(r"\{\{[^}]+}}", "[valor variable]", raw)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", raw)).strip()[:1800]


def _catalog_entry(champion_id: str) -> dict[str, Any]:
    for filename in ("champion_catalog.json", "champion_catalog_full.json"):
        try:
            catalog = json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))
            data = catalog.get("data", {})
            if isinstance(data, dict) and isinstance(data.get(champion_id), dict):
                item = data[champion_id]
                return {"tags": item.get("tags", []), "catalog_version": catalog.get("version") or item.get("version")}
        except (OSError, ValueError, AttributeError):
            continue
    return {}


def _patch_line(value: str) -> str:
    match = re.match(r"(\d+\.\d+)", value.strip())
    return match.group(1) if match else ""


def _champion(canonical_id: str, participant: dict[str, Any], game_patch: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9]+", canonical_id):
        raise ValueError("El catálogo no resolvió un identificador de campeón seguro.")
    path = DATA_DIR / "champion_abilities" / f"{canonical_id}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Faltan datos locales de habilidades para {participant.get('champion')}.") from error
    row = document.get("data", {}).get(canonical_id)
    if not isinstance(row, dict):
        raise ValueError(f"El catálogo local no contiene a {participant.get('champion')}.")
    catalog_version = str(document.get("version") or "")
    current = not game_patch or not catalog_version or _patch_line(game_patch) == _patch_line(catalog_version)
    abilities: list[dict[str, Any]] = []
    passive = row.get("passive")
    if isinstance(passive, dict):
        abilities.append({"slot": "passive", "name": str(passive.get("name") or "Pasiva"), "description": _clean_description(passive.get("description")), "image": str((passive.get("image") or {}).get("full") or ""), "cooldown_by_rank": []})
    spells = row.get("spells") if isinstance(row.get("spells"), list) else []
    for index, ability in enumerate(spells[:4]):
        if not isinstance(ability, dict):
            continue
        cooldown = ability.get("cooldown")
        cooldown_values = [value for value in cooldown if isinstance(value, (int, float)) and not isinstance(value, bool)] if isinstance(cooldown, list) else []
        abilities.append({
            "slot": "qwer"[index], "name": str(ability.get("name") or ""),
            "description": _clean_description(ability.get("description")),
            "image": str((ability.get("image") or {}).get("full") or ""),
            "cooldown_by_rank": cooldown_values if current else [],
        })
    profile = _catalog_entry(canonical_id)
    tags = [str(item) for item in profile.get("tags", []) if isinstance(item, str)]
    return {
        "champion_id": canonical_id, "champion": str(participant.get("champion") or row.get("name") or canonical_id),
        "role": str(participant.get("role") or ""), "damage_profile": tags,
        "abilities": abilities, "ability_catalog_version": catalog_version,
        "ability_data_matches_game_patch": current,
    }


def _local_participant(record: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any] | None:
    local = [item for item in participants if item.get("local") is True]
    if len(local) == 1:
        return local[0]
    if local:
        return None
    numeric = str(record.get("champion_id") or "").strip()
    name = str(record.get("champion") or "").casefold()
    if not numeric and not name:
        return None
    candidates = [item for item in participants if (numeric and str(item.get("championId", "")) == numeric)
                  or (name and str(item.get("champion") or "").casefold() == name)]
    role = str(record.get("role") or "").casefold()
    if len(candidates) > 1 and role:
        candidates = [item for item in candidates if str(item.get("role") or "").casefold() == role]
    return candidates[0] if len(candidates) == 1 else None


def build_matchup_context(record: dict[str, Any]) -> dict[str, Any]:
    """Return bounded roster, local ability descriptions and attributed deaths."""
    participants = record.get("participants") if isinstance(record.get("participants"), list) else []
    participants = [item for item in participants if isinstance(item, dict)]
    local = _local_participant(record, participants)
    if local is None:
        return {"available": False, "reason": "No se pudo identificar al jugador local con certeza.", "player": None, "enemies": []}
    enemies = [item for item in participants if item.get("side") == "enemy"]
    if len(enemies) != 5:
        return {"available": False, "reason": "La partida guardada no contiene los cinco campeones rivales.", "player": None, "enemies": []}
    from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
    resolver = MatchAnalysisEvidenceService._canonical_champion_id
    patch = str(record.get("patch") or "")
    try:
        player_id = resolver(str(local.get("champion") or ""))
        if not player_id:
            raise ValueError("No se pudo resolver el campeón del jugador en el catálogo local.")
        player = _champion(player_id, local, patch)
        enemy_rows = []
        for enemy in enemies:
            enemy_id = resolver(str(enemy.get("champion") or ""))
            if not enemy_id:
                raise ValueError(f"No se pudo resolver a {enemy.get('champion')} en el catálogo local.")
            enemy_rows.append(_champion(enemy_id, enemy, patch))
    except ValueError as error:
        return {"available": False, "reason": str(error), "player": None, "enemies": []}

    player_id_by_participant = int(local.get("participantId") or 0)
    enemy_by_participant = {int(item.get("participantId") or 0): item for item in enemies}
    deaths: dict[str, list[str]] = {item["champion_id"]: [] for item in enemy_rows}
    for event in record.get("events", []) if isinstance(record.get("events"), list) else []:
        if not isinstance(event, dict) or event.get("type") != "CHAMPION_KILL" or event.get("victimId") != player_id_by_participant:
            continue
        killer = enemy_by_participant.get(int(event.get("killerId") or 0))
        if not killer:
            continue
        canonical = resolver(str(killer.get("champion") or ""))
        if canonical in deaths:
            timestamp = event.get("timestamp")
            if isinstance(timestamp, (int, float)) and timestamp >= 0:
                seconds = int(timestamp // 1000)
                deaths[canonical].append(f"{seconds // 60}:{seconds % 60:02d}")
    for enemy in enemy_rows:
        times = deaths.get(enemy["champion_id"], [])
        enemy["match_observation"] = ({"kind": "confirmed_deaths_by_enemy", "count": len(times), "timestamps": times} if times else None)
    return {"available": True, "reason": "", "patch": patch, "player": player, "enemies": enemy_rows}


def context_response(repository: Any, match_id: str) -> dict[str, Any]:
    # Status polling must stay read-only: get_analysis also recalculates and
    # persists BattleScore from the saved timeline on every detail request.
    from backend.soloq_analyses import _records
    profile = repository.load_last_profile()
    if not profile:
        raise KeyError("No hay un perfil sincronizado para esta biblioteca.")
    record = next((item for item in _records(repository, profile)
                   if str(item.get("match_id") or "") == match_id), None)
    if record is None:
        raise KeyError("El análisis SoloQ no está guardado.")
    context = build_matchup_context(record)
    cache = record.get("combat_matchups")
    context["matchups"] = cache if isinstance(cache, dict) else None
    context["generation_status"] = str(record.get("combat_generation_status") or "idle")
    context["status_message"] = str(record.get("combat_status_message") or "")
    return context


def _validate_response(payload: Any, context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("matchups"), list):
        raise ValueError("La respuesta de enfrentamientos no tiene el formato requerido.")
    if len(payload["matchups"]) != 5:
        raise ValueError("La respuesta debe contener exactamente cinco enfrentamientos.")
    known_enemies = {item["champion_id"]: item for item in context["enemies"]}
    player_slots = {item["slot"] for item in context["player"]["abilities"] if item["slot"] in "qwer"}
    output: dict[str, Any] = {}
    for raw in payload["matchups"]:
        if not isinstance(raw, dict):
            raise ValueError("La respuesta incluye un enfrentamiento con formato no válido.")
        enemy_id = raw.get("enemy_champion_id")
        if enemy_id not in known_enemies or enemy_id in output:
            raise ValueError("La respuesta incluye un rival desconocido o repetido.")
        ability_slots = {item["slot"] for item in known_enemies[enemy_id]["abilities"] if item["slot"] in "qwer"}
        def valid_abilities(key: str, slot_key: str) -> list[dict[str, str]]:
            rows = raw.get(key) if isinstance(raw.get(key), list) else []
            valid = []
            seen = set()
            for item in rows:
                if not isinstance(item, dict):
                    continue
                slot = str(item.get("slot") or "").casefold()
                detail = _clean_description(item.get(slot_key))
                if slot not in (ability_slots if key == "key_enemy_abilities" else player_slots) or not detail or slot in seen:
                    continue
                seen.add(slot)
                valid.append({"slot": slot, slot_key: detail[:1000]})
            return valid[:4]
        difficulty = str(raw.get("difficulty") or "").casefold()
        if difficulty not in {"easy", "medium", "hard"}:
            raise ValueError(f"La dificultad de {known_enemies[enemy_id]['champion']} no es válida.")
        entry = {
            "player_champion_id": context["player"]["champion_id"], "enemy_champion_id": enemy_id,
            "difficulty": difficulty,
            "difficulty_reason": _clean_description(raw.get("difficulty_reason"))[:1200],
            "key_enemy_abilities": valid_abilities("key_enemy_abilities", "reason"),
            "relevant_player_abilities": valid_abilities("relevant_player_abilities", "use"),
            "combat_strategy": _clean_description(raw.get("combat_strategy"))[:2200],
            "baiting_strategy": _clean_description(raw.get("baiting_strategy"))[:1800],
            "counterplay_windows": _clean_description(raw.get("counterplay_windows"))[:1800],
            "mistakes_to_avoid": [_clean_description(x)[:700] for x in raw.get("mistakes_to_avoid", []) if isinstance(x, str) and _clean_description(x)][:5] if isinstance(raw.get("mistakes_to_avoid"), list) else [],
            "target_priority": _clean_description(raw.get("target_priority"))[:1200],
            "teamfight_considerations": _clean_description(raw.get("teamfight_considerations"))[:1600],
            # Match facts are rendered from Riot-attributed events below the card.
            # Do not rely on model prose to establish a cause or additional fact.
            "match_specific_observations": "",
            "strategic_tip": _clean_description(raw.get("strategic_tip"))[:1000],
        }
        required = ("difficulty_reason", "combat_strategy", "baiting_strategy", "counterplay_windows", "target_priority", "teamfight_considerations", "strategic_tip")
        if any(not entry[key] for key in required) or not entry["key_enemy_abilities"] or not entry["relevant_player_abilities"]:
            raise ValueError(f"El análisis de {known_enemies[enemy_id]['champion']} quedó incompleto.")
        output[enemy_id] = entry
    if set(output) != set(known_enemies):
        raise ValueError("La respuesta no incluye un análisis válido de los cinco campeones rivales.")
    return {"schema_version": 1, "player_champion_id": context["player"]["champion_id"], "enemy_champion_ids": [item["champion_id"] for item in context["enemies"]], "matchups": [output[item["champion_id"]] for item in context["enemies"]], "catalog_patch": max([context["player"]["ability_catalog_version"], *[item["ability_catalog_version"] for item in context["enemies"]]], default=""), "game_patch": context.get("patch") or "", "generated_at": datetime.now(UTC).isoformat()}


def generate(repository: Any, match_id: str) -> dict[str, Any]:
    from backend.soloq_analyses import get_analysis
    from app.services.match_ai_analyzer_service import MatchAIAnalyzerService
    record = get_analysis(repository, match_id)
    context = build_matchup_context(record)
    if not context.get("available"):
        raise ValueError(context.get("reason") or "No hay suficientes datos locales para analizar los enfrentamientos.")
    api_key = str(SettingsService().load().get("gemini_api_key") or "").strip()
    if not api_key:
        raise ValueError("No hay una clave de Gemini configurada en Ajustes.")
    prompt = f"""Eres un entrenador de League of Legends. Responde exclusivamente en español y con el JSON del esquema. Analiza exactamente cada emparejamiento entre el jugador y los cinco rivales del contexto.

Usa los campeones, roles, perfiles de daño, descripciones de habilidades y parche del catálogo local como fuente mecánica. No uses memoria del modelo para contradecir el catálogo. El campo damage_profile usa etiquetas de Data Dragon, no estadísticas de partida. No inventes porcentajes de victoria, enfriamientos, rangos de habilidad, objetos, hechizos de invocador ni información de posicionamiento. El cliente no confirma qué habilidades se lanzaron. Evalúa dificultad solo como orientación cualitativa contextual, justifícala con interacciones concretas y no la presentes como predicción estadística.

En cada duelo explica la amenaza enemiga, el recurso concreto del jugador que puede responder (slot Q/W/E/R), momento de entrada o retirada, ventana tras compromisos/enfriamientos cuando la descripción lo respalde, errores a evitar, prioridad del objetivo en pelea de equipo y un consejo memorizable. No sugieras una interacción imposible según las descripciones. No afirmes que un enfriamiento está disponible: explica la ventana como oportunidad condicionada a observar que se usó. Si la mecánica no está clara en los datos, expresa la limitación en vez de inventarla.

match_specific_observations solo puede contener hechos apoyados por el registro. El contexto incluye eliminaciones del jugador atribuidas al killerId Riot, con hora exacta. Si no hay observación fiable devuelve una cadena vacía. No concluyas que una habilidad causó la muerte. Separa esa observación factual del consejo general.

En baiting_strategy escribe una secuencia breve y específica para provocar que el rival gaste sus habilidades clave: indica qué habilidad del jugador usar como señuelo, qué respuesta rival podría provocar y qué habilidad propia reservar o usar después. Formula cada paso como posibilidad condicionada ("puede", "si responde", "cuando termine"), nunca como algo seguro. Usa solo interacciones verificables con las habilidades del contexto; si no existe una secuencia fiable, explica una forma prudente de presionar para invitar la respuesta y aclara la limitación. La interfaz mostrará junto al texto los iconos de las habilidades propias relevantes.

En todos los campos de prosa, identifica las habilidades solo por su tecla Q/W/E/R; nunca escribas el nombre completo de una habilidad, tampoco entre paréntesis. Las tarjetas ya muestran el icono de cada habilidad junto al consejo.

Contexto verificado:\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}\n\nDevuelve los cinco rivales, cada uno una sola vez, usando exactamente sus champion_id canónicos y solo slots de habilidad presentes en el catálogo."""
    service = MatchAIAnalyzerService()
    response, model = service._call_gemini_api(prompt, api_key, schema=COMBAT_SCHEMA, max_output_tokens=9000)
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError as error:
        raise ValueError("El proveedor devolvió un análisis de enfrentamientos inválido.") from error
    result = _validate_response(parsed, context)
    result["model"] = model
    return result


def persist_status(repository: Any, match_id: str, status: str, message: str, result: dict[str, Any] | None = None) -> None:
    from backend.soloq_analyses import _records
    profile = repository.load_last_profile()
    if not profile:
        return
    record = next((item for item in _records(repository, profile) if str(item.get("match_id")) == match_id), None)
    if not record:
        return
    if result is not None:
        record["combat_matchups"] = result
    record["combat_generation_status"] = status
    record["combat_status_message"] = message[:300]
    record["updated_at"] = datetime.now(UTC).isoformat()
    repository.save_soloq_analysis(profile, record)
