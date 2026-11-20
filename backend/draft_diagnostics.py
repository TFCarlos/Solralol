"""Offline, read-only diagnostics for catalog and Draft source compatibility."""

from __future__ import annotations

from typing import Any

from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.identidad_campeon import IndiceIdentidadCampeon
from app.services.repositorio_campeones import EstadoDatos, RepositorioCampeones


def audit_draft_catalog(catalog: list[dict[str, Any]], repository: RepositorioCampeones,
                        analyzer: DraftAnalyzerService) -> list[dict[str, Any]]:
    """Diagnose identities and existing data without writing or importing records."""
    identities = IndiceIdentidadCampeon({str(row.get("id") or index): row for index, row in enumerate(catalog)})
    rows: list[dict[str, Any]] = []
    for entry in catalog:
        champion_id = str(entry.get("id") or "")
        name = str(entry.get("name") or "")
        key = str(entry.get("key") or "")
        row: dict[str, Any] = {"id": champion_id, "name": name, "key": key}
        if not champion_id or not key.isdecimal() or any(identities.resolve(value) != champion_id for value in (champion_id, name, key)):
            row["status"] = "invalid_champion_identity"
            rows.append(row)
            continue
        lookup = repository.obtener_campeon(champion_id)
        if lookup.estado == EstadoDatos.SIN_DATOS_LOCALES:
            row["status"] = "missing_database_record"
        elif lookup.estado in {EstadoDatos.CORRUPTOS, EstadoDatos.ESQUEMA_INCOMPATIBLE}:
            row["status"] = "incompatible_data_schema"
        elif lookup.estado == EstadoDatos.ACTUALIZACION_FALLIDA:
            row["status"] = "import_failure"
        elif lookup.estado != EstadoDatos.DISPONIBLE:
            row["status"] = "missing_source_data"
        else:
            document = lookup.datos or {}
            if document.get("update_status") == "UPDATE_FAILED":
                row["status"] = "import_failure"
            else:
                profile = analyzer.get_champion_profile(champion_id) or {}
                roles = analyzer.get_likely_roles(champion_id)
                role_keys = {"Top": "top", "Jungle": "jungle", "Mid": "mid", "Bot": "adc", "Support": "support"}
                ranks = analyzer.variantes.available_ranks(champion_id)
                rank = "emerald_plus" if "emerald_plus" in ranks else ranks[0] if ranks else ""
                lanes = analyzer.variantes.available_lanes(champion_id, rank) if rank else []
                lane = next((role_keys[role] for role in roles if role_keys.get(role) in lanes), lanes[0] if lanes else "")
                variant = repository.consultar(champion_id, lane, rank).datos if lane else {}
                variant = variant or {}
                row["sources"] = {
                    "build": bool(variant.get("most_played_build") or variant.get("runes") or profile.get("most_played_build")),
                    "runes": bool(variant.get("runes") or profile.get("common_runes") or profile.get("runes")),
                    "situational": bool(variant.get("situational_items") or profile.get("situational_items")),
                    "counters": bool((profile.get("matchups") or {}).get("counters") or (variant.get("matchups") or {}).get("counters")),
                    "damage": bool(profile.get("damage_breakdown") or variant.get("damage_breakdown")),
                    "curve": bool(profile.get("win_rate_vs_game_length") or variant.get("win_rate_vs_game_length")),
                }
                row["status"] = "available" if any(row["sources"].values()) else "missing_source_data"
        rows.append(row)
    return rows
