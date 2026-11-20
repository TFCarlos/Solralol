"""Validación del análisis interpretativo generado para una partida guardada."""

from __future__ import annotations

import json
import re
import logging
from typing import Any

VERSION_ESQUEMA_ANALISIS = 3
VERSIONES_COMPATIBLES = {1, 2, VERSION_ESQUEMA_ANALISIS}
TIPO_ANALISIS_GENERAL = "general_match_analysis"
MAX_DETERMINISTIC_KEY_EVENTS = 120
logger = logging.getLogger(__name__)


def _limpiar_disclaimer_cronologia(value: Any) -> str:
    text = str(value or "")
    for pattern in (
        r"(?i)La secuencia y los participantes est[aá]n confirmados;\s*no demuestra causalidad\.?",
        r"(?i)La secuencia y los participantes compartidos est[aá]n confirmados;\s*no demuestra causalidad\.?",
        r"(?i)La secuencia y los participantes est[aá]n confirmados;\s*no demuestra que la baja causara el objetivo\.?",
        r"(?i)La secuencia confirma participantes y orden temporal;\s*no demuestra causalidad\.?",
    ):
        text = re.sub(pattern, "", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _texto_opcional(valor: Any, ruta: str) -> str | None:
    """Valida texto opcional sin convertir otros tipos en contenido visible."""
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise TypeError(f"El campo {ruta} debe ser texto.")
    limpio = valor.strip()
    if len(limpio) > 6000:
        raise ValueError(f"El campo {ruta} supera el límite permitido.")
    return limpio


def _lista_textos_opcional(valor: Any, ruta: str) -> list[str] | None:
    """Valida una lista opcional de textos breves."""
    if valor is None:
        return None
    if not isinstance(valor, list) or len(valor) > 40:
        raise ValueError(f"El campo {ruta} debe ser una lista válida.")
    resultado = []
    for indice, elemento in enumerate(valor):
        texto = _texto_opcional(elemento, f"{ruta}[{indice}]")
        if texto:
            resultado.append(texto)
    return resultado


def validar_analisis_partida(payload: Any) -> dict[str, Any]:
    """Valida informes v1 y v2 y conserva el contenido admitido."""
    if not isinstance(payload, dict):
        raise TypeError("El análisis debe ser un objeto JSON.")
    if payload.get("schema_version") not in VERSIONES_COMPATIBLES:
        raise ValueError("La versión del análisis no es compatible.")
    if payload.get("analysis_type") != TIPO_ANALISIS_GENERAL:
        raise ValueError("El tipo de análisis no es compatible.")
    resumen = payload.get("summary")
    if not isinstance(resumen, dict):
        raise TypeError("El análisis no incluye un resumen estructurado.")
    resultado: dict[str, Any] = {
        "schema_version": int(payload["schema_version"]),
        "analysis_type": TIPO_ANALISIS_GENERAL,
        "summary": {},
    }
    for campo in ("overall_grade", "short_summary", "key_takeaway"):
        texto = _texto_opcional(resumen.get(campo), f"summary.{campo}")
        if texto is not None:
            resultado["summary"][campo] = texto
    for campo in ("strengths", "weaknesses"):
        lista = _lista_textos_opcional(resumen.get(campo), f"summary.{campo}")
        if lista is not None:
            resultado["summary"][campo] = lista
    for campo in ("main_error", "core_priority", "champion_name", "player_name"):
        texto = _texto_opcional(resumen.get(campo), f"summary.{campo}")
        if texto is not None:
            resultado["summary"][campo] = texto
    for campo in ("game_phases",):
        valor = payload.get(campo)
        if valor is None:
            continue
        if not isinstance(valor, dict):
            raise TypeError(f"El campo {campo} debe ser un objeto.")
        fases: dict[str, Any] = {}
        for clave in ("early", "mid", "late"):
            fase = valor.get(clave)
            if fase is None:
                continue
            if not isinstance(fase, dict):
                raise TypeError(f"La fase {clave} debe ser un objeto.")
            fases[clave] = {}
            for propiedad in ("assessment", "strengths", "mistakes", "recommendations"):
                normalizador = (
                    _lista_textos_opcional
                    if propiedad != "assessment"
                    else _texto_opcional
                )
                dato = normalizador(fase.get(propiedad), f"{campo}.{clave}.{propiedad}")
                if dato is not None:
                    fases[clave][propiedad] = dato
        resultado[campo] = fases
    eventos_clave = payload.get("key_events")
    if eventos_clave is not None:
        # Optional provider output must not invalidate an otherwise usable report.
        # Invalid event lists are reconstructed from deterministic timeline evidence.
        if not isinstance(eventos_clave, list):
            logger.warning("[AI timeline] provider key_events was not a list; rebuilding from evidence")
            eventos_clave = []
        elif len(eventos_clave) > 40:
            logger.warning("[AI timeline] provider key_events capped from %d to 40", len(eventos_clave))
            eventos_clave = eventos_clave[:40]
        resultado["key_events"] = []
        for indice, evento in enumerate(eventos_clave):
            ruta = f"key_events[{indice}]"
            if not isinstance(evento, dict):
                logger.debug("[AI timeline] skipped malformed %s", ruta)
                continue
            refs = evento.get("event_ids")
            # Teamfight summaries can legitimately cite more than six kills.
            # Keep a bounded list, but do not discard the whole fight for that.
            if not isinstance(refs, list) or not 1 <= len(refs) <= 40:
                continue
            ids = [str(ref).strip()[:100] for ref in refs if isinstance(ref, str) and ref.strip()]
            try:
                titulo = _texto_opcional(evento.get("title"), f"{ruta}.title") or ""
                descripcion = _texto_opcional(evento.get("description"), f"{ruta}.description") or ""
                impacto = _texto_opcional(evento.get("why_it_matters"), f"{ruta}.why_it_matters") or ""
            except (TypeError, ValueError):
                logger.debug("[AI timeline] skipped invalid text in %s", ruta)
                continue
            if ids and titulo and descripcion and impacto:
                normalized_event = {
                    "event_ids": list(dict.fromkeys(ids)), "title": titulo,
                    "description": descripcion, "why_it_matters": impacto,
                }
                event_kind = evento.get("event_kind")
                if isinstance(event_kind, str) and event_kind.strip()[:80]:
                    normalized_event["event_kind"] = event_kind.strip()[:80]
                for optional_field in ("player_contribution", "recommendation"):
                    try:
                        optional_text = _texto_opcional(evento.get(optional_field), f"{ruta}.{optional_field}")
                    except (TypeError, ValueError):
                        optional_text = None
                        logger.debug("[AI timeline] ignored malformed optional %s.%s", ruta, optional_field)
                    if optional_text:
                        normalized_event[optional_field] = optional_text
                resultado["key_events"].append(normalized_event)
    for campo in (
        "farming",
        "itemization",
        "purchase_timing",
        "objective_conversion",
        "death_impact",
    ):
        valor = payload.get(campo)
        if valor is None:
            continue
        if not isinstance(valor, dict):
            raise TypeError(f"El campo {campo} debe ser un objeto.")
        normalizado: dict[str, Any] = {}
        for propiedad, dato in valor.items():
            if propiedad in {"assessment", "short_summary"}:
                contenido = _texto_opcional(dato, f"{campo}.{propiedad}")
            elif propiedad in {
                "strengths",
                "mistakes",
                "recommendations",
                "alternative_items",
            }:
                contenido = _lista_textos_opcional(dato, f"{campo}.{propiedad}")
            else:
                continue
            if contenido is not None:
                normalizado[propiedad] = contenido
        resultado[campo] = normalizado
    enfrentamientos = payload.get("enemy_matchups")
    if enfrentamientos is not None:
        if not isinstance(enfrentamientos, list) or len(enfrentamientos) > 10:
            raise ValueError("La lista de enfrentamientos no es válida.")
        resultado["enemy_matchups"] = []
        for indice, enfrentamiento in enumerate(enfrentamientos):
            ruta = f"enemy_matchups[{indice}]"
            if not isinstance(enfrentamiento, dict):
                raise TypeError(f"El campo {ruta} debe ser un objeto.")
            normalizado = {}
            for propiedad in ("champion_id", "difficulty", "assessment"):
                dato = enfrentamiento.get(propiedad)
                if propiedad == "champion_id" and dato is not None:
                    if not isinstance(dato, (str, int)) or len(str(dato)) > 100:
                        raise ValueError(f"El campo {ruta}.{propiedad} no es válido.")
                    dato = str(dato)
                else:
                    dato = _texto_opcional(dato, f"{ruta}.{propiedad}")
                if dato is not None:
                    normalizado[propiedad] = dato
            for propiedad in ("counterplay", "mistakes", "recommendations"):
                dato = _lista_textos_opcional(
                    enfrentamiento.get(propiedad), f"{ruta}.{propiedad}"
                )
                if dato is not None:
                    normalizado[propiedad] = dato
            resultado["enemy_matchups"].append(normalizado)
    prioridades = payload.get("improvement_priorities")
    if prioridades is not None:
        if not isinstance(prioridades, list) or len(prioridades) > 20:
            raise ValueError("La lista de prioridades no es válida.")
        resultado["improvement_priorities"] = []
        for indice, prioridad in enumerate(prioridades):
            ruta = f"improvement_priorities[{indice}]"
            if not isinstance(prioridad, dict):
                raise TypeError(f"El campo {ruta} debe ser un objeto.")
            elemento = {}
            for propiedad in ("title", "explanation", "priority", "action"):
                dato = _texto_opcional(prioridad.get(propiedad), f"{ruta}.{propiedad}")
                if dato is not None:
                    elemento[propiedad] = dato
            resultado["improvement_priorities"].append(elemento)
    return resultado


def enriquecer_analisis_partida(
    payload: Any,
    contexto: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Valida el informe y completa rivales y prioridades con evidencia del log."""
    contexto = contexto if isinstance(contexto, dict) else {}
    resultado = validar_analisis_partida(payload)
    resultado["schema_version"] = VERSION_ESQUEMA_ANALISIS
    if not isinstance(payload, dict):
        return resultado
    if "analysis_evidence" not in contexto and (
        contexto.get("all_players") or contexto.get("events_chronology")
    ):
        from app.services.match_analysis_evidence_service import (
            MatchAnalysisEvidenceService,
        )

        contexto["analysis_evidence"] = MatchAnalysisEvidenceService().build_evidence(
            contexto
        )
    resumen_crudo = payload.get("summary", {})
    resumen = resultado["summary"]
    for campo in (
        "main_turning_point",
        "primary_strength",
        "primary_weakness",
        "evidence_refs",
    ):
        valor = resumen_crudo.get(campo)
        if isinstance(valor, str):
            texto = _texto_opcional(valor, f"summary.{campo}")
            if texto:
                resumen[campo] = texto
        elif campo == "evidence_refs" and isinstance(valor, list):
            resumen[campo] = [str(ref)[:100] for ref in valor[:20]]
    for destino, origen in (
        ("champion_name", "champion_name"),
        ("player_name", "player_name"),
        ("main_error", "main_error"),
        ("core_priority", "core_priority"),
    ):
        texto = _texto_opcional(resumen_crudo.get(origen), f"summary.{origen}")
        if texto:
            resumen[destino] = texto
    if not resumen.get("champion_name"):
        resumen["champion_name"] = str(contexto.get("champion_name") or "")
    if not resumen.get("player_name"):
        resumen["player_name"] = str(contexto.get("player_name") or "")
    if not resumen.get("main_error") and resumen.get("weaknesses"):
        resumen["main_error"] = resumen["weaknesses"][0]
    if not resumen.get("core_priority"):
        resumen["core_priority"] = str(
            resumen.get("key_takeaway") or resumen.get("main_error") or ""
        )

    fases_raw = payload.get("game_phases", {})
    fases = resultado.setdefault("game_phases", {})
    for clave in ("early", "mid", "late"):
        fase = fases.get(clave, {})
        fase_cruda = fases_raw.get(clave, {}) if isinstance(fases_raw, dict) else {}
        for destino, fuentes in {
            "title": ("title",),
            "summary": ("summary", "assessment"),
            "what_worked": ("what_worked", "strengths"),
            "what_failed": ("what_failed", "mistakes"),
            "adaptation": ("adaptation", "recommendations"),
        }.items():
            valor = next(
                (fase_cruda.get(k) for k in fuentes if fase_cruda.get(k)), None
            )
            if isinstance(valor, list):
                valor = " · ".join(str(item) for item in valor if item)
            texto = _texto_opcional(valor, f"game_phases.{clave}.{destino}")
            if texto:
                fase[destino] = texto
        if isinstance(fase_cruda.get("evidence_events"), list):
            fase["evidence_events"] = [
                dict(evento)
                for evento in fase_cruda["evidence_events"][:6]
                if isinstance(evento, dict)
            ]
        if fase:
            fase.setdefault(
                "title", {"early": "Inicio", "mid": "Mitad", "late": "Cierre"}[clave]
            )
            fases[clave] = fase
    eventos = contexto.get("events_chronology", [])
    if not isinstance(eventos, list):
        eventos = []
    limites = {"early": (0, 900), "mid": (900, 1500), "late": (1500, float("inf"))}
    for clave, (inicio, fin) in limites.items():
        fase_eventos = [
            evento
            for evento in eventos
            if isinstance(evento, dict)
            and inicio <= float(evento.get("time_seconds") or 0) < fin
        ]
        if fase_eventos:
            inferida = _inferir_fase(clave, fase_eventos, contexto)
            actual = fases.setdefault(clave, {})
            for campo, valor in inferida.items():
                actual.setdefault(campo, valor)
    for clave, titulo in (("early", "Early"), ("mid", "Mid"), ("late", "Late")):
        fases.setdefault(
            clave,
            {
                "title": titulo,
                "summary": "No hay eventos suficientes para valorar esta fase.",
                "adaptation": "Usa la cronología completa para identificar una decisión revisable.",
            },
        )
        fases[clave].setdefault(
            "what_worked", "El registro no aporta evidencia suficiente para valorarlo."
        )
        fases[clave].setdefault(
            "what_failed", "El registro no permite confirmar un error concreto."
        )
        fases[clave].setdefault(
            "adaptation", "Revisa los eventos de esta fase antes de fijar un ajuste."
        )

    rendimiento_modelo = _normalizar_rendimiento(payload.get("performance"))
    resultado["performance"] = _inferir_rendimiento(contexto)
    resultado["performance"].update(rendimiento_modelo)
    resultado["build_assessment"] = _texto_opcional(
        payload.get("build_assessment"), "build_assessment"
    ) or str(resultado.get("itemization", {}).get("assessment") or "")
    resultado["itemization_notes"] = _lista_textos_opcional(
        payload.get("itemization_notes"), "itemization_notes"
    ) or list(resultado.get("itemization", {}).get("mistakes", []))
    resultado["situational_item_suggestions"] = _normalizar_sugerencias_objetos(
        payload.get("situational_item_suggestions")
    )
    resultado["rune_comments"] = (
        _lista_textos_opcional(payload.get("rune_comments"), "rune_comments") or []
    )
    build = _inferir_build(contexto)
    contexto["model_item_alternatives"] = payload.get("item_alternatives", [])
    contexto["model_rune_alternatives"] = payload.get("rune_alternatives", [])
    resultado["item_reviews"] = _incorporar_evaluaciones_modelo(
        payload.get("item_reviews"),
        build["item_reviews"],
        build["item_alternatives"],
        contexto,
    )
    resultado["item_alternatives"] = _validar_alternativas_objetos_modelo(
        contexto, build["item_alternatives"], compatible=bool(build.get("catalog_compatible"))
    )
    resultado["rune_evaluation"] = build.get("rune_evaluation")
    if isinstance(resultado.get("rune_evaluation"), dict):
        alternativa_runa = _validar_alternativa_runa(
            contexto, resultado["rune_evaluation"], compatible=bool(build.get("catalog_compatible"))
        )
        if alternativa_runa:
            resultado["rune_evaluation"]["alternative"] = alternativa_runa
    if isinstance(resultado.get("rune_evaluation"), dict) and resultado["rune_comments"]:
        resultado["rune_evaluation"]["matchup_assessment"] = resultado["rune_comments"][:3]
    resultado["build_archetype"] = build.get("archetype")
    resultado["build_assessment"] = (
        resultado.get("build_assessment") or build["assessment"]
    )
    resultado["itemization_notes"] = (
        resultado.get("itemization_notes") or build["notes"]
    )
    if not resultado["rune_comments"]:
        resultado["rune_comments"] = build["rune_comments"]
    resultado["match_evidence"] = contexto.get("analysis_evidence", {})

    rivales = _normalizar_rivales(payload.get("key_enemies"))
    if not rivales:
        rivales = _normalizar_rivales(resultado.get("enemy_matchups"))
    enemigos_contexto = contexto.get("all_players", [])
    nombres_observados = (
        {
            str(jugador.get("champion") or "").casefold()
            for jugador in enemigos_contexto
            if isinstance(jugador, dict)
            and not jugador.get("is_ally")
            and jugador.get("champion")
        }
        if isinstance(enemigos_contexto, list)
        else set()
    )
    if nombres_observados:
        rivales = [
            rival
            for rival in rivales
            if str(rival.get("champion_name") or "").casefold() in nombres_observados
        ]
    inferidos = _inferir_rivales(contexto)
    resultado["key_enemies"] = _combinar_rivales(rivales, inferidos)
    resultado.setdefault("enemy_matchups", [])

    prioridades = _normalizar_prioridades(payload.get("next_game_priorities"))
    anteriores = _normalizar_prioridades(resultado.get("improvement_priorities"))
    evidencia_cronologia = contexto.get("events_chronology", [])
    if isinstance(evidencia_cronologia, list) and evidencia_cronologia:
        ids_validos = {
            f"event-{evento.get('order', indice)}"
            for indice, evento in enumerate(evidencia_cronologia)
            if isinstance(evento, dict)
        }
        prioridades = [
            prioridad
            for prioridad in prioridades
            if any(ref in ids_validos for ref in prioridad.get("evidence_refs", []))
        ]
        anteriores = [
            prioridad
            for prioridad in anteriores
            if any(ref in ids_validos for ref in prioridad.get("evidence_refs", []))
        ]
    if len(prioridades) < 3:
        prioridades.extend(anteriores)
    prioridades = _combinar_prioridades(
        prioridades, _completar_prioridades([], resumen, contexto)
    )
    resultado["next_game_priorities"] = prioridades[:5]
    resultado.setdefault("improvement_priorities", [])
    resultado["match_evidence"] = contexto.get("analysis_evidence", {})
    if resultado["next_game_priorities"] and not resumen.get("core_priority"):
        resumen["core_priority"] = resultado["next_game_priorities"][0].get("title", "")
    if not resumen.get("overall_grade"):
        resumen["overall_grade"] = "Valoración de coaching basada en evidencia"
    resumen_evidencia = _resumen_desde_evidencia(contexto)
    if not resumen.get("short_summary"):
        resumen["short_summary"] = resumen_evidencia
    elif contexto.get("events_chronology") and resumen_evidencia:
        contenido_actual = str(resumen["short_summary"])
        estadisticas = contexto.get("user_stats", {})
        cifras = [
            str(estadisticas.get(campo))
            for campo in ("kills", "damage_to_champions", "cs")
            if estadisticas.get(campo) is not None
        ]
        if cifras and not any(cifra in contenido_actual for cifra in cifras):
            resumen["short_summary"] = (
                contenido_actual.rstrip(". ")
                + ". Hechos del registro: "
                + resumen_evidencia
            )
    if not resumen.get("main_error") and resultado["next_game_priorities"]:
        resumen["main_error"] = resultado["next_game_priorities"][0].get("evidence", "")
    if not resumen.get("strengths"):
        usuario = contexto.get("user_stats", {})
        if isinstance(usuario, dict) and usuario.get("damage_to_champions"):
            resumen["strengths"] = [
                f"Contribución ofensiva registrada: {int(usuario.get('kills') or 0)} bajas y {int(usuario['damage_to_champions']):,} de daño a campeones."
            ]
    if not resumen.get("weaknesses") and resultado["next_game_priorities"]:
        resumen["weaknesses"] = [
            resultado["next_game_priorities"][0].get("evidence", "")
        ]
    punto = resumen.get("main_turning_point")
    if not punto or "event-" in punto.casefold():
        resumen["main_turning_point"] = _punto_inflexion(contexto)
    resumen["decisive_events"] = _eventos_decisivos(contexto)
    raw_key_events = resultado.get("key_events", [])
    if not isinstance(raw_key_events, list):
        raw_key_events = []
    evidencia = contexto.get("analysis_evidence", {})
    notable = evidencia.get("notable_timeline", []) if isinstance(evidencia, dict) else []
    por_id = {
        str(evento.get("event_id")): evento
        for evento in notable
        if isinstance(evento, dict) and evento.get("event_id")
    }
    momentos_filtrados = []
    for evento in raw_key_events:
        referencias = list(dict.fromkeys(evento.get("event_ids", [])))
        hechos = [por_id.get(str(referencia)) for referencia in referencias]
        if (
            not referencias
            or any(hecho is None for hecho in hechos)
            or len(evento.get("why_it_matters", "")) < 18
        ):
            continue
        referenced = {str(ref) for ref in referencias}
        referenced_kills = {
            ref for ref in referenced
            if por_id[ref].get("category") == "kill"
        }
        referenced_objectives = {
            ref for ref in referenced
            if por_id[ref].get("category") in {"objective", "structure"}
        }
        if referenced_kills and referenced_objectives:
            personal_selection_for_pairs = evidencia.get("personal_event_selection", {})
            positive_relations = (
                personal_selection_for_pairs.get("kill_objective_correlations", [])
                if isinstance(personal_selection_for_pairs, dict)
                and personal_selection_for_pairs.get("version") in {1, 2}
                else evidencia.get("kill_objective_correlations", [])
            )
            accepted_pairs = {
                (str(item.get("kill_event_id") or ""), str(item.get("objective_event_id") or ""))
                for item in positive_relations
                if isinstance(item, dict) and item.get("status") == "accepted"
            }
            inverse_relations = (
                personal_selection_for_pairs.get("player_death_objective_correlations", [])
                if isinstance(personal_selection_for_pairs, dict)
                and personal_selection_for_pairs.get("version") in {1, 2}
                else evidencia.get("player_death_objective_correlations", [])
            )
            accepted_pairs.update(
                (str(item.get("death_event_id") or ""), str(item.get("objective_event_id") or ""))
                for item in inverse_relations
                if isinstance(item, dict) and item.get("status") == "accepted"
            )
            if any(
                not any((kill_ref, objective_ref) in accepted_pairs for kill_ref in referenced_kills)
                for objective_ref in referenced_objectives
            ):
                logger.info("[AI timeline] discarded unverified kill-objective relationship refs=%d", len(referencias))
                continue
        evento["event_ids"] = [str(ref) for ref in referencias]
        evento["why_it_matters"] = _limpiar_disclaimer_cronologia(evento.get("why_it_matters"))
        momentos_filtrados.append(evento)
    personal_selection = evidencia.get("personal_event_selection", {}) if isinstance(evidencia, dict) else {}
    personal_ids = {
        str(ref) for ref in personal_selection.get("personal_event_ids", []) if ref
    } if isinstance(personal_selection, dict) else set()
    if isinstance(personal_selection, dict) and personal_selection.get("version") in {1, 2}:
        before_personal = len(momentos_filtrados)
        momentos_filtrados = [
            event for event in momentos_filtrados
            if event.get("event_ids") and set(event["event_ids"]).issubset(personal_ids)
        ]
        if before_personal != len(momentos_filtrados):
            logger.info("[AI timeline] discarded non-personal interpretations=%d", before_personal - len(momentos_filtrados))
    ids_usados = {
        str(ref) for evento in momentos_filtrados for ref in evento.get("event_ids", [])
    }
    candidatos = evidencia.get("key_event_candidates", []) if isinstance(evidencia, dict) else []
    candidatos = [candidate for candidate in candidatos if isinstance(candidate, dict)]
    relevance_rank = {"low": 0, "medium": 1, "high": 2}
    for momento in momentos_filtrados:
        event_refs = set(str(ref) for ref in momento.get("event_ids", []))
        matched = [
            candidate for candidate in candidatos
            if event_refs.intersection(str(ref) for ref in candidate.get("event_ids", []))
        ]
        if matched:
            momento["relevance"] = max(
                (candidate.get("relevance", "low") for candidate in matched),
                key=lambda level: relevance_rank.get(str(level), 0),
            )
    candidatos.sort(key=lambda candidate: (
        0 if candidate.get("candidate_type") == "teamfight_cluster" else
        1 if candidate.get("candidate_type") in {"combat_then_objective", "single_kill_before_objective", "validated_kills_before_objective"} else
        2 if candidate.get("candidate_type") == "player_death_to_enemy_objective" else
        3 if candidate.get("candidate_type") in {"objective_trade_candidate", "consecutive_structure_captures"} else 4,
        float(candidate.get("seconds_between_last_kill_and_objective") or 0),
    ))
    retained_fallbacks = 0
    merged_cluster_events = 0
    for candidate in candidatos:
        if len(momentos_filtrados) >= MAX_DETERMINISTIC_KEY_EVENTS:
            break
        refs = list(dict.fromkeys(
            str(ref) for ref in candidate.get("event_ids", []) if str(ref) in por_id
        ))
        kind = candidate.get("candidate_type")
        if not refs:
            continue
        if kind == "player_death_to_enemy_objective":
            death_refs = [ref for ref in refs if por_id[ref].get("category") == "kill" and por_id[ref].get("victim_key") == "player_local"]
            objective_refs = [ref for ref in refs if por_id[ref].get("category") in {"objective", "structure"}]
            existing = next((
                item for item in momentos_filtrados
                if death_refs and set(str(ref) for ref in item.get("event_ids", [])).intersection(death_refs)
            ), None)
            if existing is not None and objective_refs:
                already_linked_conversion = existing.get("event_kind") == "player_death_to_enemy_objective"
                existing_refs = list(dict.fromkeys(map(str, existing.get("event_ids", []))))
                missing_objective_refs = [ref for ref in objective_refs if ref not in existing_refs]
                existing["event_ids"] = list(dict.fromkeys(
                    [*existing_refs, *missing_objective_refs]
                ))
                objective_facts = [str(por_id[ref].get("label") or "") for ref in missing_objective_refs]
                if objective_facts:
                    existing["description"] = (str(existing.get("description") or "").rstrip() + " " + " ".join(item for item in objective_facts if item)).strip()
                existing["event_kind"] = "player_death_to_enemy_objective"
                existing["relevance"] = "high"
                objective_name = str(candidate.get("objective") or "un objetivo")
                existing["title"] = (
                    "Tu muerte precedió a varias capturas rivales"
                    if already_linked_conversion
                    else f"Tu muerte precedió al objetivo rival: {objective_name}"
                )
                existing["why_it_matters"] = (str(existing.get("why_it_matters") or "").rstrip() + " " +
                    f"{candidate.get('death_killer') or 'Un rival'} participó en tu eliminación y {candidate.get('objective_finisher') or 'un rival'} aseguró {objective_name} {candidate.get('seconds_between_death_and_objective', 0)} s después.").strip()
                duplicate_events = [
                    item for item in momentos_filtrados
                    if item is not existing
                    and set(map(str, item.get("event_ids", []))).intersection(death_refs)
                    and set(map(str, item.get("event_ids", []))).intersection(objective_refs)
                ]
                for duplicate in duplicate_events:
                    existing["event_ids"] = list(dict.fromkeys([
                        *map(str, existing.get("event_ids", [])),
                        *map(str, duplicate.get("event_ids", [])),
                    ]))
                    momentos_filtrados.remove(duplicate)
                ids_usados.update(refs)
                merged_cluster_events += 1
                continue
        if kind in {"combat_then_objective", "single_kill_before_objective", "validated_kills_before_objective"}:
            objective_refs = [
                ref for ref in refs
                if por_id[ref].get("category") in {"objective", "structure"}
            ]
            existing = next((
                item for item in momentos_filtrados
                if set(str(ref) for ref in item.get("event_ids", [])).intersection(objective_refs)
            ), None)
            if existing is not None:
                existing_refs = list(dict.fromkeys(
                    str(ref) for ref in existing.get("event_ids", []) + refs
                ))
                missing = [por_id[ref] for ref in refs if ref not in ids_usados]
                existing["event_ids"] = existing_refs
                if missing:
                    details = " ".join(str(item.get("label") or "") for item in missing).strip()
                    if details:
                        existing["description"] = (
                            str(existing.get("description") or "").rstrip() + " " + details
                        ).strip()
                    shared = candidate.get("shared_participants") or [
                        candidate.get("shared_participant") or candidate.get("objective_finisher") or "El rematador"
                    ]
                    shared_text = ", ".join(str(value) for value in shared)
                    objective = str(candidate.get("objective") or "el objetivo")
                    gap = int(candidate.get("seconds_between_last_kill_and_objective") or 0)
                    existing["why_it_matters"] = (
                        str(existing.get("why_it_matters") or "").rstrip()
                        + f" La cronologia confirma que {shared_text} participo en la baja y que despues se registro {objective}, {gap} s mas tarde."
                    )
                ids_usados.update(refs)
                merged_cluster_events += 1
                continue
        if kind == "teamfight_cluster":
            existing = next((
                item for item in momentos_filtrados
                if set(str(ref) for ref in item.get("event_ids", [])).intersection(refs)
            ), None)
            if existing is not None:
                existing_refs = list(dict.fromkeys(
                    str(ref) for ref in existing.get("event_ids", []) + refs
                ))
                missing = [por_id[ref] for ref in refs if ref not in ids_usados]
                existing["event_ids"] = existing_refs
                if missing:
                    details = " ".join(str(item.get("label") or "") for item in missing).strip()
                    if details:
                        existing["description"] = (str(existing.get("description") or "").rstrip() + " " + details).strip()
                    count = int(candidate.get("combat_kill_count") or len(refs))
                    existing["why_it_matters"] = (
                        str(existing.get("why_it_matters") or "").rstrip()
                        + f" La detección determinista agrupa {count} bajas en esta secuencia; los eventos se conservan aunque la interpretación de IA citara solo parte de ellos."
                    )
                ids_usados.update(refs)
                merged_cluster_events += 1
                continue
        if all(ref in ids_usados for ref in refs):
            continue
        facts = [por_id[ref] for ref in refs]
        kills = int(candidate.get("combat_kill_count") or 0)
        times = list(dict.fromkeys(
            str(fact.get("time_label") or "") for fact in facts if fact.get("time_label")
        ))
        labels = [str(fact.get("label") or "") for fact in facts if fact.get("label")]
        if kind == "teamfight_cluster":
            if kills < 4 or not candidate.get("local_player_involved"):
                continue
            title = f"Combate agrupado con {kills} bajas"
            description = " ".join(labels)
            allied, enemy = candidate.get("allied_deaths"), candidate.get("enemy_deaths")
            distribution = (
                f" Se registraron {allied} bajas aliadas y {enemy} rivales."
                if isinstance(allied, int) and isinstance(enemy, int) else ""
            )
            reason = (
                f"El combate agrupado se extendio de {times[0] if times else 'hora no disponible'} "
                f"a {times[-1] if times else 'hora no disponible'} y registro {kills} bajas.{distribution} "
                f"Tu contribucion confirmada: {candidate.get('player_kills', 0)} "
                f"{'baja' if candidate.get('player_kills', 0) == 1 else 'bajas'}, "
                f"{candidate.get('player_assists', 0)} "
                f"{'asistencia' if candidate.get('player_assists', 0) == 1 else 'asistencias'} y "
                f"{candidate.get('player_deaths', 0)} "
                f"{'muerte' if candidate.get('player_deaths', 0) == 1 else 'muertes'}."
            )
        elif kind in {"combat_then_objective", "single_kill_before_objective", "validated_kills_before_objective"}:
            objective = str(candidate.get("objective") or "el objetivo")
            title = f"Combate previo a {objective}" if kills > 1 else f"Eliminacion previa a {objective}"
            description = " ".join(labels)
            gap = int(candidate.get("seconds_between_last_kill_and_objective") or 0)
            shared = candidate.get("shared_participants") or [candidate.get("shared_participant") or "El rematador"]
            shared_text = ", ".join(str(value) for value in shared)
            team = str(candidate.get("objective_team") or "el equipo beneficiado")
            kill_word = "eliminacion" if kills == 1 else "eliminaciones"
            title = f"{kill_word.capitalize()} seguida de {objective}" if kills == 1 else f"{kills} {kill_word} seguidas de {objective}"
            reason = (
                f"{shared_text} participo en {kill_word} y despues {candidate.get('objective_finisher') or 'el rematador'} "
                f"aseguro {objective} para {team}, {gap} s despues de la ultima baja."
            )
        elif kind == "player_death_to_enemy_objective":
            objective = str(candidate.get("objective") or "el objetivo")
            finisher = str(candidate.get("objective_finisher") or "Un campeon rival")
            killer = str(candidate.get("death_killer") or "Un campeon rival")
            assisters = [str(item) for item in candidate.get("death_assisters", []) if item]
            death_description = str(facts[0].get("label") or "Tu personaje fue eliminado")
            title = f"Tu muerte precedió al objetivo rival: {objective}"
            description = f"{death_description}"
            if assisters:
                description += f" Con la asistencia de {', '.join(assisters)}."
            description += f" Posteriormente, {finisher} aseguró {objective}."
            gap = int(candidate.get("seconds_between_death_and_objective") or 0)
            contributors = list(dict.fromkeys([killer, *assisters]))
            contributor_text = ", ".join(contributors)
            participation_verb = "participó" if len(contributors) == 1 else "participaron"
            reason = (
                f"{contributor_text} {participation_verb} en tu eliminación; "
                f"{finisher} aseguró {objective} {gap} s después. Es una secuencia potencialmente costosa para tu equipo. "
                "En una situacion similar, sopesa el riesgo de exponerte cuando una baja pueda dejar al rival en condiciones de disputar objetivos."
            )
        elif kind == "objective_capture":
            objective = str(candidate.get("objective") or (labels[-1] if labels else "objetivo"))
            team = str(candidate.get("objective_team") or "equipo no identificado")
            title = f"Objetivo asegurado: {objective}"
            description = " ".join(labels) or objective
            reason = f"El registro confirma que {team} aseguro {objective} en {candidate.get('time') or (times[0] if times else 'un momento sin hora disponible')}."
        elif kind == "objective_trade_candidate":
            objectives = candidate.get("objectives", [])
            title = "Capturas cercanas de equipos distintos"
            description = " ".join(labels)
            reason = (
                f"Se registraron {', '.join(str(item) for item in objectives)} con {candidate.get('seconds_apart', 0)} s de diferencia. "
                "La secuencia puede reflejar un intercambio de mapa; no confirma que fuera intencional."
            )
        elif kind == "consecutive_structure_captures":
            count = int(candidate.get("structure_count") or len(facts))
            title = f"{count} estructuras en una secuencia"
            description = " ".join(labels)
            reason = (
                f"La cronologia registra estas estructuras entre {times[0] if times else 'horas no disponibles'} "
                f"y {times[-1] if times else 'horas no disponibles'}, dentro de una ventana de 120 s."
            )
        elif kind == "potential_swing_kill":
            signals = candidate.get("recorded_signals", [])
            if not any(signal in signals for signal in ("recorded_shutdown_or_bounty", "late_game_kill")):
                continue
            title = "Baja con senal de impacto registrada"
            description = " ".join(labels)
            signal_text = "una recompensa o shutdown registrada" if "recorded_shutdown_or_bounty" in signals else "una baja en los ultimos 120 segundos"
            reason = f"La telemetria marca {signal_text}. La cronologia no mide por si sola el cambio de oro o la consecuencia posterior."
        elif kind == "confirmed_700_shutdown":
            participation = candidate.get("player_participation")
            title = "Shutdown conseguido" if participation == "secured" else "Participacion en shutdown"
            description = " ".join(labels)
            action = "conseguiste" if participation == "secured" else "participaste con una asistencia en"
            reason = f"El registro confirma una recompensa de shutdown de 700 de oro y que {action} la eliminacion de {candidate.get('victim_champion') or 'un campeon rival'}."
        else:
            continue
        momentos_filtrados.append({
            "event_ids": refs,
            "title": title,
            "description": description or title,
            "why_it_matters": reason,
            "source": "deterministic_fallback",
            "relevance": candidate.get("relevance", "medium"),
            "event_kind": kind,
        })
        ids_usados.update(refs)
        retained_fallbacks += 1
    resultado["key_events"] = momentos_filtrados
    logger.info(
        "[AI timeline] model_events=%d deterministic_candidates=%d retained_fallbacks=%d merged_cluster_events=%d final_events=%d limit=%d",
        len(raw_key_events), len(candidatos), retained_fallbacks, merged_cluster_events, len(momentos_filtrados),
        MAX_DETERMINISTIC_KEY_EVENTS,
    )
    from app.services.match_analysis_grading import calcular_grados_rendimiento

    evidencia_puntuacion = resultado.get("match_evidence", {}).get(
        "performance_scoring"
    )
    resultado["coaching_grades"] = calcular_grados_rendimiento(evidencia_puntuacion)
    return resultado


def _punto_inflexion(contexto: dict[str, Any]) -> str:
    """Localiza una muerte próxima a un gran objetivo sin afirmar causalidad."""
    eventos = contexto.get("events_chronology", [])
    usuario = contexto.get("user_stats", {})
    local = str(contexto.get("local_player_key") or "")
    equipo = str(contexto.get("metadata", {}).get("local_team") or "").upper()
    if not isinstance(eventos, list):
        return "No hay un giro de partida identificable con los eventos disponibles."
    muertes = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and evento.get("victim_key") == local
        and "kill" in str(evento.get("type", "")).casefold()
    ]
    barones = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and "bar"
        in str(evento.get("objective") or evento.get("label") or "").casefold()
    ]
    for muerte in reversed(muertes):
        for baron in barones:
            diferencia = float(baron.get("time_seconds") or 0) - float(
                muerte.get("time_seconds") or 0
            )
            if (
                0 <= diferencia <= 180
                and str(baron.get("team") or "").upper() != equipo
            ):
                asesino = _nombre_campeon(contexto, muerte.get("killer_key"))
                campeon = str(
                    contexto.get("champion_name")
                    or usuario.get("champion")
                    or "El jugador"
                )
                return (
                    f"{campeon} fue eliminado por {asesino} a {muerte.get('time_label')}; "
                    f"{_equipo_legible(baron.get('team'), equipo)} consiguió el Barón Nashor "
                    f"a {baron.get('time_label')}, {int(diferencia)} s después. "
                    "La proximidad invita a revisar la secuencia, pero no demuestra causalidad."
                )
    kills = usuario.get("kills")
    damage = usuario.get("damage_to_champions")
    if kills is not None and damage is not None:
        return f"La contribución de {kills} bajas y {int(damage):,} de daño coexistió con una derrota; revisa qué ventajas lograron convertirse en objetivos."
    return (
        "El registro no ofrece datos suficientes para identificar un momento decisivo."
    )


def _eventos_decisivos(contexto: dict[str, Any]) -> list[dict[str, Any]]:
    """Prepara una muerte y un objetivo cercanos como hitos legibles y verificables."""
    eventos = contexto.get("events_chronology", [])
    equipo = str(contexto.get("metadata", {}).get("local_team") or "").upper()
    local = str(contexto.get("local_player_key") or "")
    if not isinstance(eventos, list):
        return []
    barones = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and "bar"
        in str(evento.get("objective") or evento.get("label") or "").casefold()
        and str(evento.get("team") or "").upper() != equipo
    ]
    muertes = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and evento.get("victim_key") == local
        and "kill" in str(evento.get("type") or "").casefold()
    ]
    for baron in barones:
        anteriores = [
            muerte
            for muerte in muertes
            if 0
            <= float(baron.get("time_seconds") or 0)
            - float(muerte.get("time_seconds") or 0)
            <= 180
        ]
        if anteriores:
            muerte = max(
                anteriores, key=lambda valor: float(valor.get("time_seconds") or 0)
            )
            asesino = _nombre_campeon(contexto, muerte.get("killer_key"))
            datos_jugador = contexto.get("user_stats", {})
            campeon = str(
                contexto.get("champion_name")
                or (
                    datos_jugador.get("champion")
                    if isinstance(datos_jugador, dict)
                    else None
                )
                or "El jugador"
            )
            segundos = int(
                float(baron.get("time_seconds") or 0)
                - float(muerte.get("time_seconds") or 0)
            )
            return [
                {
                    "time_label": str(muerte.get("time_label") or ""),
                    "event_id": f"event-{muerte.get('order', '')}",
                    "kind": "player_death",
                    "description": f"{campeon} murió a manos de {asesino}",
                    "champion_id": MatchChampionResolver.resolver(asesino) or "",
                    "team_label": "Equipo aliado",
                },
                {
                    "time_label": str(baron.get("time_label") or ""),
                    "event_id": f"event-{baron.get('order', '')}",
                    "kind": "objective",
                    "description": f"{_equipo_legible(baron.get('team'), equipo)} consiguió el Barón Nashor",
                    "champion_id": "",
                    "team_label": _equipo_legible(baron.get("team"), equipo),
                    "seconds_after": segundos,
                },
            ]
    return []


def _nombre_campeon(contexto: dict[str, Any], clave: Any) -> str:
    """Resuelve una clave de participante al campeón visible del registro."""
    for jugador in contexto.get("all_players", []):
        if isinstance(jugador, dict) and str(jugador.get("player_key")) == str(clave):
            return str(jugador.get("champion") or "un rival")
    return "un rival"


def _equipo_legible(equipo: Any, equipo_local: str) -> str:
    """Traduce códigos internos de equipo a una etiqueta para el jugador."""
    if str(equipo or "").upper() == equipo_local:
        return "El equipo aliado"
    if str(equipo or "").strip():
        return "El equipo rival"
    return "Un equipo"


def _incorporar_evaluaciones_modelo(
    evaluaciones: Any,
    revisiones: list[dict[str, Any]],
    alternativas: list[dict[str, Any]],
    contexto: dict[str, Any],
) -> list[dict[str, Any]]:
    """Añade lecturas Gemini solo para objetos y eventos realmente registrados."""
    inventario = (
        {str(item) for item in contexto.get("user_stats", {}).get("items", [])}
        if isinstance(contexto.get("user_stats"), dict)
        else set()
    )
    eventos = contexto.get("events_chronology", [])
    ids_evento = (
        {
            f"event-{evento.get('order', indice)}"
            for indice, evento in enumerate(eventos)
            if isinstance(evento, dict)
        }
        if isinstance(eventos, list)
        else set()
    )
    por_item = {str(revision.get("item_id")): revision for revision in revisiones}
    if isinstance(evaluaciones, list):
        for valor in evaluaciones:
            if not isinstance(valor, dict):
                continue
            item_id = str(valor.get("item_id") or "")
            referencias = valor.get("evidence_refs")
            if item_id not in inventario or not isinstance(referencias, list):
                continue
            referencias_validas = [
                str(ref) for ref in referencias if str(ref) in ids_evento
            ]
            if not referencias_validas:
                continue
            comentario = _texto_opcional(
                valor.get("assessment"), "item_reviews.assessment"
            )
            if comentario:
                revision = por_item.get(item_id)
                if revision is not None:
                    revision["model_assessment"] = comentario
                    revision["model_verdict"] = (
                        _texto_opcional(valor.get("verdict"), "item_reviews.verdict")
                        or ""
                    )
                    revision["model_evidence_refs"] = referencias_validas[:8]
    alternativas_modelo = contexto.get("model_item_alternatives", [])
    if isinstance(alternativas_modelo, list):
        for valor in alternativas_modelo:
            if not isinstance(valor, dict):
                continue
            item_id = str(valor.get("item_id") or "")
            replace_id = str(valor.get("replace_or_delay_item_id") or "")
            referencias = valor.get("evidence_refs")
            validas = (
                [str(ref) for ref in referencias if str(ref) in ids_evento]
                if isinstance(referencias, list)
                else []
            )
            coincidente = next(
                (
                    alternativa
                    for alternativa in alternativas
                    if alternativa.get("item_id") == item_id
                    and alternativa.get("replace_or_delay_item_id") == replace_id
                ),
                None,
            )
            if coincidente and validas:
                coincidente["model_note"] = (
                    _texto_opcional(
                        valor.get("mechanical_advantage"),
                        "item_alternatives.mechanical_advantage",
                    )
                    or ""
                )
                coincidente["model_evidence_refs"] = validas[:8]
    return revisiones


def _resumen_desde_evidencia(contexto: dict[str, Any]) -> str:
    """Redacta un resumen factual con estadísticas, objetivos y giro de partida."""
    usuario = contexto.get("user_stats", {})
    usuario = usuario if isinstance(usuario, dict) else {}
    eventos = contexto.get("events_chronology", [])
    eventos = eventos if isinstance(eventos, list) else []
    local = str(contexto.get("local_player_key") or "")
    equipo = str(contexto.get("metadata", {}).get("local_team") or "").upper()
    muertes = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and evento.get("victim_key") == local
        and "kill" in str(evento.get("type", "")).casefold()
    ]
    barones = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and "bar"
        in str(evento.get("objective") or evento.get("label") or "").casefold()
    ]
    inhibidores = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and "inhib"
        in str(evento.get("objective") or evento.get("label") or "").casefold()
    ]
    partes = []
    kills = usuario.get("kills")
    dano = usuario.get("damage_to_champions")
    cs = usuario.get("cs")
    cs_min = usuario.get("cs_per_min")
    if kills is not None and dano is not None:
        partes.append(
            f"La producción ofensiva fue de {kills} bajas y {int(dano):,} de daño a campeones"
        )
    if cs is not None:
        partes.append(
            f"el farmeo llegó a {cs} súbditos ({cs_min} por minuto según el registro)"
        )
    if muertes:
        iniciales = [
            evento for evento in muertes if float(evento.get("time_seconds") or 0) < 420
        ]
        partes.append(
            f"se acumularon {len(iniciales)} muertes propias antes del minuto 7"
        )
    resumen = "; ".join(partes)
    if inhibidores:
        aliadas = [
            evento
            for evento in inhibidores
            if str(evento.get("team") or "").upper() == equipo
        ]
        if aliadas:
            resumen += (
                f". El equipo aliado tomó un inhibidor a {aliadas[0].get('time_label')}"
            )
    if barones:
        baron_enemigo = next(
            (
                evento
                for evento in barones
                if str(evento.get("team") or "").upper() != equipo
            ),
            None,
        )
        if baron_enemigo:
            campeon = str(
                contexto.get("champion_name") or usuario.get("champion") or "El jugador"
            )
            resumen += f"; {campeon} murió a {next((evento.get('time_label') for evento in reversed(muertes) if 0 <= float(baron_enemigo.get('time_seconds') or 0) - float(evento.get('time_seconds') or 0) <= 180), 'un momento anterior')} y el Barón enemigo llegó a {baron_enemigo.get('time_label')}"
    if not resumen:
        return "La valoración se limita a los participantes, estadísticas y eventos que conserva el registro."
    return (
        resumen
        + ". La cercanía de eventos permite señalar una ventana de revisión, no confirmar una causa táctica sin posición ni visión."
    )


def _inferir_build(contexto: dict[str, Any]) -> dict[str, Any]:
    """Evalúa la build completa, recetas posibles y runas del parche de partida."""
    import json

    from _paths import DATA_DIR

    usuario = contexto.get("user_stats", {})
    usuario = usuario if isinstance(usuario, dict) else {}
    inventario = [str(item) for item in usuario.get("items", [])]
    evidencia = contexto.get("analysis_evidence", {})
    cobertura = evidencia.get("coverage", {}) if isinstance(evidencia, dict) else {}
    compras = evidencia.get("purchases", []) if isinstance(evidencia, dict) else []
    jugador = evidencia.get("player", {}) if isinstance(evidencia, dict) else {}
    compra_jugador = [
        compra
        for compra in compras
        if isinstance(compra, dict)
        and compra.get("player_key") == jugador.get("player_key")
    ]
    try:
        catalogo_base = json.loads(
            (DATA_DIR / "items.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        catalogo_base = {}
    catalogo = catalogo_base.get("items", {})
    parche = str(catalogo_base.get("version") or "desconocido")
    parche_partida = str(contexto.get("metadata", {}).get("game_version") or "")
    compatible = not parche_partida or parche_partida == parche
    enemigos = [
        rival
        for rival in contexto.get("all_players", [])
        if isinstance(rival, dict) and not rival.get("is_ally")
    ]
    rivales_por_nombre = {str(r.get("champion") or "").casefold(): r for r in enemigos}
    relevantes = [item for item in inventario if item not in {"3340", "3363", "3364"}]
    tags = [
        tag
        for item_id in relevantes
        for tag in catalogo.get(item_id, {}).get("tags", [])
    ]
    identidad = (
        "Núcleo ofensivo de letalidad y daño físico"
        if sum(
            tag in {"Damage", "CriticalStrike", "Lethality", "ArmorPenetration"}
            for tag in tags
        )
        >= 6
        else "Build de luchador con inversión ofensiva y defensiva"
    )
    amenazas = []
    if "viktor" in rivales_por_nombre:
        amenazas.append(
            {
                "champion_id": "Viktor",
                "champion_name": "Viktor",
                "threat": "Daño de campeón alto; el registro no separa daño mágico y físico.",
            }
        )
    if "yasuo" in rivales_por_nombre:
        amenazas.append(
            {
                "champion_id": "Yasuo",
                "champion_name": "Yasuo",
                "threat": "Amenaza de daño físico/crítico respaldada por su presencia y eventos registrados.",
            }
        )
    reviews = []
    consejos = {
        "6676": (
            "Buena elección",
            "Encaja con el núcleo de daño físico: su ejecución y oro adicional premian remates confirmados. El coste es una ranura sin resistencia; el marcador no confirma qué remates habilitó.",
        ),
        "6699": (
            "Buena elección",
            "Refuerza la presión de letalidad y el golpe energizado junto a Recaudadora. La combinación concentra daño en ventanas cortas, pero deja menos margen si el objetivo sobrevive al primer ciclo.",
        ),
        "3036": (
            "Situacional",
            "La penetración puede ayudar contra una primera línea resistente; el registro no aporta armadura final de cada enemigo, así que no puede afirmarse que su compra fuese la respuesta óptima.",
        ),
        "6333": (
            "Buena elección",
            "Aporta una respuesta parcial contra daño físico y convierte bajas en una oportunidad de prolongar la pelea. No resuelve por sí sola el daño no desglosado de Viktor.",
        ),
        "3111": (
            "Buena elección",
            "La resistencia mágica y tenacidad son pertinentes ante Viktor y controles rivales; no contrarrestan el daño físico de Yasuo o Naafiri.",
        ),
        "1038": (
            "Situacional",
            "Es un componente ofensivo, pero el registro no confirma el objeto final previsto. Frente a Viktor y Yasuo, mantenerlo como daño adicional competía con cerrar una defensa específica.",
        ),
    }
    for item_id in relevantes:
        item = catalogo.get(item_id)
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("name_es") or item.get("name") or f"Objeto {item_id}")
        veredicto, lectura = consejos.get(
            item_id,
            (
                "Situacional",
                "Su valor debe leerse dentro del conjunto y del parche registrado; el log no confirma por sí solo su impacto en una pelea.",
            ),
        )
        if not compatible:
            veredicto = "Efecto no verificado"
            lectura = f"La partida es de {parche_partida}; el catálogo local es {parche}. No se puede validar esta compra en su parche."
        compra = next(
            (c for c in reversed(compra_jugador) if str(c.get("item_id")) == item_id),
            None,
        )
        reviews.append(
            {
                "item_id": item_id,
                "name": nombre,
                "verdict": veredicto,
                "assessment": lectura,
                "purchase_time": compra.get("time_label") if compra else None,
                "catalog_patch": parche,
                "gold_total": item.get("gold", {}).get("total"),
                "item_icon_ref": item_id,
                "threat_champion_ids": [a["champion_id"] for a in amenazas],
                "evidence_type": "catalog_and_match_log",
            }
        )
    alternativas = []
    planes = []
    if compatible and "viktor" in rivales_por_nombre:
        planes.append(
            (
                "3156",
                "1033",
                "1038",
                "Viktor",
                "El Manto de anulación de magia inicia una ruta válida hacia Sorbemaleficios y Fauces de Malmortius. Es una defensa dirigida al daño mágico, pero el registro no desglosa el daño de Viktor y se retrasa daño físico.",
            )
        )
    if compatible and "yasuo" in rivales_por_nombre:
        planes.append(
            (
                "3143",
                "3082",
                "1038",
                "Yasuo",
                "La Malla del guardián forma parte de la receta de Presagio de Randuin y orienta la compra contra daño físico crítico. A cambio se retrasa daño ofensivo y no cubre el daño mágico de Viktor.",
            )
        )
    for objetivo, componente, reemplazo, campeon, ventaja in planes:
        if (
            reemplazo not in inventario
            or not _componente_de_objetivo(catalogo, componente, objetivo)
            or not catalogo.get(objetivo, {}).get("gold", {}).get("purchasable")
            or not catalogo.get(objetivo, {}).get("maps", {}).get("11")
            or not catalogo.get(componente, {}).get("maps", {}).get("11")
        ):
            continue
        item_objetivo = catalogo.get(objetivo, {})
        item_componente = catalogo.get(componente, {})
        item_reemplazo = catalogo.get(reemplazo, {})
        costo_objetivo = item_objetivo.get("gold", {}).get("total")
        costo_componente = item_componente.get("gold", {}).get("total")
        alternativas.append(
            {
                "item_id": objetivo,
                "name": item_objetivo.get("name_es") or item_objetivo.get("name"),
                "description": re.sub(r"<[^>]+>", " ", str(item_objetivo.get("description_es") or item_objetivo.get("description") or "")).strip(),
                "stats": item_objetivo.get("stats", {}),
                "gold_total": costo_objetivo,
                "component_id": componente,
                "component_name": item_componente.get("name_es")
                or item_componente.get("name"),
                "replace_or_delay_item_id": reemplazo,
                "replace_or_delay_item": item_reemplazo.get("name_es")
                or item_reemplazo.get("name"),
                "replace_or_delay_item_description": re.sub(r"<[^>]+>", " ", str(item_reemplazo.get("description_es") or item_reemplazo.get("description") or "")).strip(),
                "replace_or_delay_item_stats": item_reemplazo.get("stats", {}),
                "replace_or_delay_item_gold_total": item_reemplazo.get("gold", {}).get("total"),
                "target_item_id": objetivo,
                "target_item_name": item_objetivo.get("name_es")
                or item_objetivo.get("name"),
                "threat_champion_id": campeon,
                "threat_champion": campeon,
                "mechanical_advantage": ventaja,
                "tradeoff": "Es una comparación de una ranura/compra futura, no prueba que el jugador pudiera comprarla entonces.",
                "timing": "Revisar al decidir entre el siguiente componente ofensivo y una respuesta directa a esta amenaza.",
                "affordability": f"Orientativo: coste total {costo_objetivo} frente a {costo_componente} del componente; el log no registra oro disponible en ese instante.",
                "gold_on_hand_confirmed": bool(cobertura.get("gold_on_hand_available")),
                "recipe_valid": True,
                "evidence_type": "patch_catalog_and_match_context",
            }
        )
    build_assessment = f"{identidad}: Recaudadora y Espada ciclovoltaica consolidan ventanas de daño físico; Recuerdos de Lord Dominik mantiene penetración, mientras Baile de la muerte y Botas de mercurio añaden respuestas defensivas parciales. La defensa mágica de las botas es útil frente a Viktor, pero no sustituye una decisión consciente sobre la amenaza que más condiciona la próxima pelea."
    runas = usuario.get("runes")
    rune_eval = _evaluar_runas(runas, parche, identidad)
    return {
        "item_reviews": reviews,
        "item_alternatives": alternativas,
        "archetype": identidad,
        "assessment": build_assessment
        if compatible
        else f"Build observada: {identidad}. Los efectos no se comparan porque el catálogo no coincide con el parche de la partida.",
        "notes": [f"{r['name']}: {r['verdict']}. {r['assessment']}" for r in reviews],
        "rune_comments": [rune_eval["conclusion"]]
        if rune_eval
        else [
            "La partida no conserva una configuración de runas identificable; no se recomienda cambiarla."
        ],
        "rune_evaluation": rune_eval,
        "catalog_compatible": compatible,
    }


def _validar_alternativas_objetos_modelo(
    contexto: dict[str, Any], inferidas: list[dict[str, Any]], *, compatible: bool
) -> list[dict[str, Any]]:
    """Keep model item alternatives only when IDs, patch, slot replacement and threat are verified."""
    resultado = list(inferidas)
    if not compatible:
        return resultado
    from _paths import DATA_DIR

    try:
        documento = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return resultado
    catalogo = documento.get("items", {}) if isinstance(documento, dict) else {}
    usuario = contexto.get("user_stats", {})
    usuario = usuario if isinstance(usuario, dict) else {}
    inventario = {str(item) for item in usuario.get("items", []) if str(item).isdigit()}
    jugadores = contexto.get("all_players", [])
    amenazas = {
        str(jugador.get("champion") or "").casefold(): str(jugador.get("champion") or "")
        for jugador in jugadores
        if isinstance(jugador, dict) and not jugador.get("is_ally") and jugador.get("champion")
    }
    evidencia = contexto.get("analysis_evidence", {})
    eventos = evidencia.get("notable_timeline", []) if isinstance(evidencia, dict) else []
    cobertura = evidencia.get("coverage", {}) if isinstance(evidencia, dict) else {}
    gold_on_hand_confirmed = bool(cobertura.get("gold_on_hand_available")) if isinstance(cobertura, dict) else False
    event_ids = {str(event.get("event_id")) for event in eventos if isinstance(event, dict)}
    modelos = contexto.get("model_item_alternatives", [])
    if not isinstance(modelos, list):
        return resultado
    existing = {(str(item.get("item_id")), str(item.get("replace_or_delay_item_id"))) for item in resultado}
    for candidate in modelos:
        if not isinstance(candidate, dict):
            continue
        item_id = str(candidate.get("item_id") or "")
        replace_id = str(candidate.get("replace_or_delay_item_id") or "")
        item = catalogo.get(item_id) if isinstance(catalogo, dict) else None
        threat = amenazas.get(str(candidate.get("threat_champion_id") or "").casefold())
        if not item_id.isdigit() or not replace_id.isdigit() or replace_id not in inventario:
            continue
        if not isinstance(item, dict) or item_id in inventario:
            continue
        if item.get("maps", {}).get("11") is not True or item.get("gold", {}).get("purchasable") is not True:
            continue
        advantage = str(candidate.get("mechanical_advantage") or "").strip()
        tradeoff = str(candidate.get("tradeoff") or "").strip()
        if not threat or not advantage or not tradeoff or (item_id, replace_id) in existing:
            continue
        refs = candidate.get("evidence_refs")
        valid_refs = [str(ref) for ref in refs if str(ref) in event_ids][:8] if isinstance(refs, list) else []
        resultado.append({
            "item_id": item_id,
            "name": item.get("name_es") or item.get("name") or f"Objeto {item_id}",
            "description": re.sub(r"<[^>]+>", " ", str(item.get("description_es") or item.get("description") or "")).strip(),
            "stats": item.get("stats", {}),
            "gold_total": item.get("gold", {}).get("total"),
            "replace_or_delay_item_id": replace_id,
            "replace_or_delay_item": (catalogo.get(replace_id) or {}).get("name_es") or (catalogo.get(replace_id) or {}).get("name") or f"Objeto {replace_id}",
            "replace_or_delay_item_description": re.sub(r"<[^>]+>", " ", str((catalogo.get(replace_id) or {}).get("description_es") or (catalogo.get(replace_id) or {}).get("description") or "")).strip(),
            "replace_or_delay_item_stats": (catalogo.get(replace_id) or {}).get("stats", {}),
            "replace_or_delay_item_gold_total": (catalogo.get(replace_id) or {}).get("gold", {}).get("total"),
            "threat_champion_id": threat,
            "threat_champion": threat,
            "mechanical_advantage": advantage,
            "tradeoff": tradeoff,
            "timing": str(candidate.get("timing") or "Considera el cambio al elegir la siguiente ranura de objetos."),
            "affordability": str(candidate.get("affordability") or "Asequibilidad confirmada con el oro disponible al comprar." if gold_on_hand_confirmed else "El oro disponible al comprar no se puede confirmar con estos datos."),
            "gold_on_hand_confirmed": gold_on_hand_confirmed,
            "evidence_refs": valid_refs,
            "evidence_type": "ai_advice_validated_against_local_patch_catalog",
            "catalog_patch": documento.get("version"),
        })
        existing.add((item_id, replace_id))
    return resultado


def _validar_alternativa_runa(
    contexto: dict[str, Any], evaluacion: dict[str, Any], *, compatible: bool
) -> dict[str, str] | None:
    """Allow only a catalogued keystone swap within the player's recorded primary tree."""
    if not compatible:
        return None
    from _paths import DATA_DIR

    runas = contexto.get("user_stats", {})
    runas = runas.get("runes") if isinstance(runas, dict) else None
    if not isinstance(runas, dict):
        return None
    styles = runas.get("styles")
    if not isinstance(styles, list) or not styles or not isinstance(styles[0], dict):
        return None
    style = styles[0]
    tree_id = str(style.get("style") or style.get("primary_tree_id") or "")
    selections = style.get("selections")
    current_id = ""
    if isinstance(selections, list) and selections and isinstance(selections[0], dict):
        current_id = str(selections[0].get("perk") or "")
    if not current_id:
        current_id = str((evaluacion.get("current") or {}).get("id") or "")
    if not tree_id or not current_id:
        return None
    try:
        documento = json.loads((DATA_DIR / f"runes_reforged_{evaluacion.get('patch')}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    tree = next((entry for entry in documento if isinstance(entry, dict) and str(entry.get("id")) == tree_id), None)
    if not tree:
        return None
    slots = tree.get("slots")
    if not isinstance(slots, list) or not slots or not isinstance(slots[0], dict):
        return None
    keystones = slots[0].get("runes", [])
    if not isinstance(keystones, list):
        return None
    if not any(str(entry.get("id")) == current_id for entry in keystones if isinstance(entry, dict)):
        return None
    models = contexto.get("model_rune_alternatives", [])
    if not isinstance(models, list):
        return None
    for candidate in models[:1]:
        if not isinstance(candidate, dict) or str(candidate.get("replaces_rune_id") or "") != current_id:
            continue
        replacement_id = str(candidate.get("rune_id") or "")
        replacement = next((entry for entry in keystones if isinstance(entry, dict) and str(entry.get("id")) == replacement_id), None)
        reason = str(candidate.get("reason") or "").strip()
        tradeoff = str(candidate.get("tradeoff") or "").strip()
        if not replacement or replacement_id == current_id or not reason or not tradeoff:
            continue
        return {
            "id": replacement_id,
            "name": str(replacement.get("name") or "Runa alternativa"),
            "icon_ref": str(replacement.get("icon") or ""),
            "mechanics": re.sub(r"<[^>]+>", " ", str(replacement.get("shortDesc") or "")).strip(),
            "reason": reason,
            "tradeoff": tradeoff,
            "tree_id": tree_id,
            "replaces_rune_id": current_id,
        }
    return None


def _componente_de_objetivo(
    catalogo: dict[str, Any], componente: str, objetivo: str
) -> bool:
    """Comprueba si un objeto forma parte recursivamente de la receta final."""
    pendientes = list(catalogo.get(objetivo, {}).get("from", []))
    vistos: set[str] = set()
    while pendientes:
        actual = str(pendientes.pop())
        if actual == componente:
            return True
        if actual not in vistos:
            vistos.add(actual)
            pendientes.extend(catalogo.get(actual, {}).get("from", []))
    return False


def _evaluar_runas(runas: Any, parche: str, arquetipo: str) -> dict[str, Any] | None:
    """Compara la runa observada y una opción de ráfaga según datos del parche."""
    from html import unescape

    if not isinstance(runas, dict):
        return None
    identificador = runas.get("keystone_id") or runas.get("keystoneId")
    estilos = runas.get("styles")
    if not identificador and isinstance(estilos, list) and estilos:
        estilo_principal = estilos[0]
        if isinstance(estilo_principal, dict):
            selecciones = estilo_principal.get("selections")
            if isinstance(selecciones, list) and selecciones and isinstance(selecciones[0], dict):
                identificador = selecciones[0].get("perk")
    keystone = runas.get("keystone")
    if isinstance(keystone, dict):
        identificador = identificador or keystone.get("id")
    elif isinstance(keystone, (int, str)) and str(keystone).isdigit():
        identificador = identificador or keystone
    if not identificador:
        return None
    try:
        import json

        from _paths import DATA_DIR

        documento = json.loads(
            (DATA_DIR / f"runes_reforged_{parche}.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    runas_catalogo = [
        runa
        for arbol in documento
        for slot in arbol.get("slots", [])
        for runa in slot.get("runes", [])
    ]
    actual = next(
        (runa for runa in runas_catalogo if str(runa.get("id")) == str(identificador)),
        None,
    )
    alternativa = next(
        (runa for runa in runas_catalogo if runa.get("id") == 9923), None
    )
    if not actual:
        return None
    catalog_by_id = {str(runa.get("id")): runa for runa in runas_catalogo}
    selected_runes: list[dict[str, str]] = []
    if isinstance(estilos, list):
        for style_index, style in enumerate(estilos[:2]):
            if not isinstance(style, dict):
                continue
            selections = style.get("selections")
            if not isinstance(selections, list):
                continue
            for selection_index, selection in enumerate(selections[:4]):
                if not isinstance(selection, dict):
                    continue
                rune = catalog_by_id.get(str(selection.get("perk") or ""))
                if not rune:
                    continue
                selected_runes.append({
                    "id": str(rune.get("id")),
                    "name": str(rune.get("name") or "Runa"),
                    "description": unescape(re.sub(r"<[^>]+>", " ", str(rune.get("longDesc") or rune.get("shortDesc") or ""))).strip(),
                    "tree": "Principal" if style_index == 0 else "Secundaria",
                    "kind": "Clave" if style_index == 0 and selection_index == 0 else "Menor",
                })
    evaluacion = "Buena sinergia" if actual.get("id") == 9923 else "Situacional"
    mecanica_actual = unescape(
        re.sub(r"<[^>]+>", "", str(actual.get("shortDesc") or ""))
    )
    conclusion = f"{actual['name']} {mecanica_actual}"
    if actual.get("id") == 8005 and alternativa and "letalidad" in arquetipo.casefold():
        evaluacion = "Mejorable para la orientación de ráfaga"
        conclusion = "Ataque intensificado recompensa tres ataques consecutivos y mejora el daño mientras continúa el combate. Lluvia de cuchillas adelanta tres ataques y su daño de impacto, lo que puede encajar mejor con la ventana corta de una build de letalidad; se pierde la amplificación prolongada y el daño adaptable de Ataque intensificado. La ventaja depende de poder conectar esos ataques y no constituye una simulación de daño."
    return {
        "patch": parche,
        "selected_runes": selected_runes,
        "current": {
            "id": str(actual["id"]),
            "name": actual["name"],
            "icon_ref": actual["icon"],
        },
        "verdict": evaluacion,
        "alternative": (
            {
                "id": str(alternativa["id"]),
                "name": alternativa["name"],
                "icon_ref": alternativa["icon"],
                "mechanics": unescape(
                    re.sub(r"<[^>]+>", "", str(alternativa.get("shortDesc") or ""))
                ),
            }
            if alternativa
            and actual["id"] == 8005
            and "letalidad" in arquetipo.casefold()
            else None
        ),
        "conclusion": conclusion,
    }


def _combinar_rivales(
    generados: list[dict[str, Any]], inferidos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Completa los cinco enemigos y prioriza evidencia local sobre texto ausente."""
    if not inferidos:
        return generados[:5]
    resultado = []
    for inferido in inferidos:
        resultado.append(dict(inferido))
    return resultado[:5]


def _combinar_prioridades(
    generadas: list[dict[str, str]], inferidas: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Rellena prioridades ausentes con acciones ancladas a eventos verificables."""
    resultado = list(generadas)
    titulos = {str(valor.get("title", "")).casefold() for valor in resultado}
    for prioridad in inferidas:
        clave = prioridad.get("title", "").casefold()
        if clave not in titulos:
            resultado.append(prioridad)
            titulos.add(clave)
        if len(resultado) >= 5:
            break
    return resultado[:5]


def _inferir_fase(
    clave: str, eventos: list[dict[str, Any]], contexto: dict[str, Any]
) -> dict[str, Any]:
    """Resume eventos concretos de una fase con referencias de tiempo estables."""
    local = str(contexto.get("local_player_key") or "")
    jugadores = contexto.get("all_players", [])
    nombres = {
        str(valor.get("player_key")): str(valor.get("champion") or "")
        for valor in jugadores
        if isinstance(valor, dict)
    }
    kills = [
        evento for evento in eventos if "kill" in str(evento.get("type", "")).casefold()
    ]
    muertes = [evento for evento in kills if evento.get("victim_key") == local]
    bajas = [evento for evento in kills if evento.get("killer_key") == local]
    objetivos_todos = [
        evento
        for evento in eventos
        if evento.get("objective")
        or "objective" in str(evento.get("type", "")).casefold()
    ]
    objetivos = [
        evento
        for evento in objetivos_todos
        if any(
            token
            in str(evento.get("objective") or evento.get("label") or "").casefold()
            for token in (
                "bar",
                "dragon",
                "drag",
                "herald",
                "herald",
                "grub",
                "grum",
                "inhib",
                "nexus",
            )
        )
    ]
    estructuras = [
        evento
        for evento in objetivos
        if "inhib"
        in str(evento.get("objective") or evento.get("label") or "").casefold()
    ]
    equipo_local = str(contexto.get("metadata", {}).get("local_team") or "").upper()
    aliados = [
        evento
        for evento in objetivos
        if str(evento.get("team") or "").upper() == equipo_local
    ]
    enemigos = [evento for evento in objetivos if evento not in aliados]
    inhibidor_aliado = next(
        (
            evento
            for evento in estructuras
            if str(evento.get("team") or "").upper() == equipo_local
        ),
        None,
    )
    baron_enemigo = next(
        (
            evento
            for evento in enemigos
            if "bar"
            in str(evento.get("objective") or evento.get("label") or "").casefold()
        ),
        None,
    )
    selecciones: list[dict[str, Any]] = []
    if clave == "early":
        selecciones.extend(muertes[:3])
        selecciones.extend(aliados[-1:] or enemigos[:1])
    elif clave == "mid":
        selecciones.extend(bajas[-2:])
        selecciones.extend(aliados[-1:])
        selecciones.extend(muertes[-1:])
    else:
        if inhibidor_aliado:
            selecciones.append(inhibidor_aliado)
        selecciones.extend(muertes[-3:-1])
        if baron_enemigo:
            selecciones.append(baron_enemigo)
    unicos = {str(evento.get("order", "")): evento for evento in selecciones}
    principales = sorted(
        unicos.values(), key=lambda evento: float(evento.get("time_seconds") or 0)
    )[-4:]
    evidencias = []
    for indice, evento in enumerate(principales):
        etiqueta = str(evento.get("label") or "Evento registrado")
        for campo in ("killer_key", "victim_key", "player_key"):
            clave_jugador = str(evento.get(campo) or "")
            campeon = nombres.get(clave_jugador)
            if campeon and campeon.casefold() not in etiqueta.casefold():
                etiqueta = etiqueta.replace(clave_jugador, campeon)
        ids_campeon = [
            MatchChampionResolver.resolver(
                nombres.get(str(evento.get(campo) or ""), "")
            )
            for campo in ("killer_key", "victim_key", "player_key")
            if nombres.get(str(evento.get(campo) or ""))
        ]
        evidencias.append(
            {
                "event_id": f"event-{evento.get('order', indice)}",
                "time_label": str(evento.get("time_label") or "Tiempo no disponible"),
                "label": etiqueta,
                "evidence_type": "confirmed",
                "event_type": str(evento.get("type") or "unknown"),
                "champion_ids": list(
                    dict.fromkeys(valor for valor in ids_campeon if valor)
                ),
                "objective": str(evento.get("objective") or ""),
            }
        )
    if not evidencias:
        return {
            "title": {"early": "Inicio", "mid": "Mitad", "late": "Cierre"}[clave],
            "summary": "No hay eventos de combate u objetivos detallados para esta fase.",
            "evidence_events": [],
            "what_worked": "Sin contribución individual verificable en los eventos disponibles.",
            "what_failed": "No se puede confirmar un error concreto con este registro.",
            "adaptation": "Completa el registro de eventos para valorar decisiones de esta fase.",
        }
    grupos = []
    if muertes:
        grupos.append(
            "muertes propias a "
            + ", ".join(str(evento.get("time_label") or "") for evento in muertes)
        )
    if bajas:
        grupos.append(
            "bajas propias a "
            + ", ".join(str(evento.get("time_label") or "") for evento in bajas[-4:])
        )
    if objetivos:
        hitos = [
            f"{evento.get('time_label')} {evento.get('objective') or evento.get('label', '')}"
            for evento in objetivos
        ]
        grupos.append("objetivos neutrales/estructuras clave: " + "; ".join(hitos[:6]))
    resumen = (
        ". ".join(grupos)
        if grupos
        else " · ".join(f"{dato['time_label']} {dato['label']}" for dato in evidencias)
    )
    funciono = (
        f"La cronología confirma {len(bajas)} baja(s) propia(s) en esta fase."
        if bajas
        else "La cronología registra participación en objetivos."
        if objetivos and aliados
        else "La cronología confirma eventos de combate, sin baja propia atribuida."
    )
    preocupacion = (
        f"Se registran {len(muertes)} muerte(s) propia(s) en la fase; el log no confirma su causa posicional."
        if muertes
        else "No hay una muerte propia atribuida en esta fase; la cronología no explica por sí sola toda la toma de decisiones."
    )
    return {
        "title": {"early": "Inicio", "mid": "Mitad", "late": "Cierre"}[clave],
        "summary": resumen,
        "evidence_events": evidencias,
        "what_worked": funciono,
        "what_failed": preocupacion,
        "adaptation": "En la repetición, pausa en cada marca temporal y compara participantes y objetivo registrado; el log no contiene posición ni visión para atribuir una causa.",
    }


def _normalizar_rendimiento(payload: Any) -> dict[str, dict[str, str]]:
    """Valida evaluaciones breves para las categorías de rendimiento visibles."""
    if not isinstance(payload, dict):
        payload = {}
    resultado = {}
    for clave in (
        "farming",
        "combat",
        "objectives",
        "vision",
        "survivability",
        "decision_making",
    ):
        valor = payload.get(clave)
        if not isinstance(valor, dict):
            continue
        elemento = {}
        for propiedad in ("assessment", "tip"):
            texto = _texto_opcional(
                valor.get(propiedad), f"performance.{clave}.{propiedad}"
            )
            if texto:
                elemento[propiedad] = texto
        if elemento:
            resultado[clave] = elemento
    return resultado


def _inferir_rendimiento(contexto: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Genera lecturas por métrica usando estadísticas y eventos disponibles."""
    usuario = contexto.get("user_stats", {})
    if not isinstance(usuario, dict):
        return {}
    eventos = contexto.get("events_chronology", [])
    eventos = eventos if isinstance(eventos, list) else []
    local = str(contexto.get("local_player_key") or "")
    muertes = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and evento.get("victim_key") == local
        and "kill" in str(evento.get("type", "")).casefold()
    ]
    bajas = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and evento.get("killer_key") == local
        and "kill" in str(evento.get("type", "")).casefold()
    ]
    objetivos = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and (
            evento.get("objective")
            or "objective" in str(evento.get("type", "")).casefold()
        )
    ]
    muertes_tiempos = ", ".join(
        str(evento.get("time_label"))
        for evento in muertes[:6]
        if evento.get("time_label")
    )
    resultado: dict[str, dict[str, str]] = {}
    cs_min = usuario.get("cs_per_min")
    if isinstance(cs_min, (int, float)) and cs_min > 0:
        resultado["farming"] = {
            "assessment": f"Farmeo observado: {usuario.get('cs')} súbditos, a {cs_min} por minuto.",
            "tip": "Cruza tus rotaciones con el estado de las oleadas en la repetición; el log de eventos no registra cada oportunidad de farmeo.",
        }
    kda = [usuario.get(clave) for clave in ("kills", "deaths", "assists")]
    if all(isinstance(valor, (int, float)) for valor in kda) and any(kda):
        referencia = (
            f" Bajas propias registradas a {', '.join(str(evento.get('time_label')) for evento in bajas[-4:] if evento.get('time_label'))}."
            if bajas
            else ""
        )
        resultado["combat"] = {
            "assessment": f"El marcador confirma {kda[0]} bajas, {kda[1]} muertes y {kda[2]} asistencias; se observan {len(bajas)} eventos de baja propia.{referencia}",
            "tip": "Revisa qué bajas quedaron seguidas por un objetivo o una estructura antes de valorar su conversión.",
        }
    dano_objetivos = usuario.get("damage_dealt_to_objectives") or usuario.get(
        "damage_to_objectives"
    )
    if isinstance(dano_objetivos, (int, float)) and dano_objetivos > 0:
        resultado["objectives"] = {
            "assessment": f"Daño registrado a objetivos: {dano_objetivos:,}; hay {len(objetivos)} eventos de objetivo en la cronología.",
            "tip": "Compara las capturas de Dragón, Heraldo/Grubs y Barón con las bajas y compras que las precedieron; los eventos no incluyen posición.",
        }
    vision = usuario.get("vision_score")
    if isinstance(vision, (int, float)) and vision > 0:
        resultado["vision"] = {
            "assessment": f"Puntuación de visión registrada: {vision}. No se dispone de cobertura ni colocaciones por zona.",
            "tip": "Usa la repetición para comprobar la visión antes de cada objetivo; esta puntuación no permite concluir dónde faltaba cobertura.",
        }
    muertes_total = usuario.get("deaths")
    if isinstance(muertes_total, (int, float)) and muertes_total > 0:
        resultado["survivability"] = {
            "assessment": f"El marcador registra {muertes_total} muertes; los eventos detallados sitúan {len(muertes)} de ellas{': ' + muertes_tiempos if muertes_tiempos else '.'}",
            "tip": "Reproduce diez segundos antes de cada muerte y anota información visible, recursos disponibles y si un aliado podía acompañar; estos factores no constan en el log.",
        }
        resultado["decision_making"] = {
            "assessment": _punto_inflexion(contexto),
            "tip": "Antes de comprometerte cerca de un objetivo, confirma con el equipo si puede seguir la jugada; valida el ajuste revisando una repetición, sin asumir posiciones ausentes.",
        }
    return resultado


def _normalizar_sugerencias_objetos(payload: Any) -> list[dict[str, str]]:
    """Conserva sugerencias de objetos con nombre e identificador opcional."""
    if not isinstance(payload, list):
        return []
    resultado = []
    for valor in payload[:8]:
        if isinstance(valor, str):
            valor = {"name": valor}
        if not isinstance(valor, dict):
            continue
        nombre = _texto_opcional(valor.get("name"), "situational_item_suggestions.name")
        if not nombre:
            continue
        elemento = {"name": nombre}
        for clave in ("item_id", "reason"):
            texto = _texto_opcional(
                valor.get(clave), f"situational_item_suggestions.{clave}"
            )
            if texto:
                elemento[clave] = texto
        resultado.append(elemento)
    return resultado


def _normalizar_rivales(payload: Any) -> list[dict[str, Any]]:
    """Normaliza formatos Gemini nuevos y antiguos para tarjetas de enemigos."""
    if not isinstance(payload, list):
        return []
    resultado = []
    for valor in payload[:10]:
        if not isinstance(valor, dict):
            continue
        campeon = next(
            (
                valor.get(clave)
                for clave in ("champion_name", "champion_id", "champion")
                if valor.get(clave)
            ),
            None,
        )
        nombre = _texto_opcional(
            str(campeon) if campeon is not None else None, "key_enemies.champion_name"
        )
        if not nombre:
            continue
        elemento: dict[str, Any] = {"champion_name": nombre}
        for clave in (
            "role",
            "threat_level",
            "why_it_was_a_problem",
            "how_to_play_against",
            "matchup_note",
            "difficulty",
            "assessment",
            "recommendations",
        ):
            crudo = valor.get(clave)
            if clave == "recommendations" and isinstance(crudo, list):
                crudo = " · ".join(str(elemento) for elemento in crudo if elemento)
            texto = _texto_opcional(crudo, f"key_enemies.{clave}")
            if texto:
                elemento[clave] = texto
        for destino, fuentes in {
            "dangerous_tools": ("dangerous_tools",),
            "strengths": ("strengths",),
        }.items():
            lista = _lista_textos_opcional(
                next(
                    (
                        valor.get(clave)
                        for clave in fuentes
                        if valor.get(clave) is not None
                    ),
                    None,
                ),
                f"key_enemies.{destino}",
            )
            if lista:
                elemento[destino] = lista
        if "why_it_was_a_problem" not in elemento and elemento.get("assessment"):
            elemento["why_it_was_a_problem"] = elemento["assessment"]
        if "how_to_play_against" not in elemento and elemento.get("recommendations"):
            elemento["how_to_play_against"] = " · ".join(elemento["recommendations"])
        if "how_to_play_against" not in elemento and valor.get("counterplay"):
            consejo = _lista_textos_opcional(
                valor.get("counterplay"), "key_enemies.counterplay"
            )
            if consejo:
                elemento["how_to_play_against"] = " · ".join(consejo)
        resultado.append(elemento)
    return resultado


def _inferir_rivales(contexto: dict[str, Any]) -> list[dict[str, Any]]:
    """Construye una tarjeta por enemigo usando roles, marcador y duelos registrados."""
    jugadores = contexto.get("all_players")
    if not isinstance(jugadores, list):
        return []
    usuario = contexto.get("user_stats", {})
    usuario = usuario if isinstance(usuario, dict) else {}
    rol_local = str(usuario.get("role") or "").casefold()
    eventos = contexto.get("events_chronology", [])
    eventos = eventos if isinstance(eventos, list) else []
    evidencia = contexto.get("analysis_evidence", {})
    catalogo_habilidades = (
        evidencia.get("ability_catalog", []) if isinstance(evidencia, dict) else []
    )
    habilidades_por_campeon = {
        str(campeon.get("champion_name") or "").casefold(): campeon.get("abilities", [])
        for campeon in catalogo_habilidades
        if isinstance(campeon, dict)
        and campeon.get("compatible_with_match_patch") is not False
    }
    clave_local = str(contexto.get("local_player_key") or "")
    enemigos = [
        jugador
        for jugador in jugadores
        if isinstance(jugador, dict)
        and not jugador.get("is_ally")
        and jugador.get("champion")
        and jugador.get("champion") != "Desconocido"
    ]
    resultado = []
    for enemigo in enemigos:
        nombre = str(enemigo.get("champion") or "")
        rol = str(enemigo.get("role") or "")
        clave = str(enemigo.get("player_key") or "")
        eventos_personales = [
            evento
            for evento in eventos
            if isinstance(evento, dict)
            and (
                (
                    evento.get("killer_key") == clave
                    and evento.get("victim_key") == clave_local
                )
                or (
                    evento.get("killer_key") == clave_local
                    and evento.get("victim_key") == clave
                )
                or clave in (evento.get("assister_keys") or [])
            )
        ]
        asesinatos_al_jugador = [
            evento
            for evento in eventos_personales
            if evento.get("killer_key") == clave
            and evento.get("victim_key") == clave_local
        ]
        asesinatos_por_jugador = [
            evento
            for evento in eventos_personales
            if evento.get("killer_key") == clave_local
            and evento.get("victim_key") == clave
        ]
        kda = {
            campo: int(enemigo.get(campo) or 0)
            for campo in ("kills", "deaths", "assists")
        }
        dano = int(enemigo.get("damage_to_champions") or 0)
        mismo_rol = bool(rol_local and rol.casefold() == rol_local)
        prioridad = (
            (4 if mismo_rol else 0)
            + 3 * len(asesinatos_al_jugador)
            + 0.7 * kda["kills"]
            + 0.35 * kda["assists"]
            + dano / 10000
        )
        amenaza = "alta" if prioridad >= 8 else "media" if prioridad >= 3 else "baja"
        razon = []
        if mismo_rol:
            razon.append(f"Comparte tu rol registrado ({rol}).")
        if asesinatos_al_jugador:
            razon.append(
                f"Te eliminó {len(asesinatos_al_jugador)} vez/veces según la cronología."
            )
        if kda["kills"]:
            razon.append(f"Terminó con {kda['kills']} bajas confirmadas.")
        if kda["assists"] >= 10:
            razon.append(
                f"Sus {kda['assists']} asistencias indican participación frecuente en bajas de su equipo."
            )
        if dano:
            razon.append(f"El marcador registra {dano:,} de daño a campeones.")
        herramientas = _herramientas_campeon(
            nombre, habilidades_por_campeon.get(nombre.casefold(), [])
        )
        referencias = [
            str(evento.get("time_label") or "")
            for evento in asesinatos_al_jugador + asesinatos_por_jugador
            if evento.get("time_label")
        ]
        resultado.append(
            {
                "champion_name": nombre,
                "champion_id": MatchChampionResolver.resolver(nombre),
                "role": rol or "Desconocido",
                "threat_level": amenaza,
                "kda": kda,
                "why_it_was_a_problem": " ".join(razon)
                or "El marcador confirma su presencia; no hay evidencia individual adicional.",
                "strengths": [
                    texto
                    for texto in (
                        f"Producción ofensiva: {kda['kills']} bajas y {kda['assists']} asistencias."
                        if kda["kills"] or kda["assists"]
                        else "Sin ventaja de bajas/asistencias en el marcador.",
                        f"Daño registrado: {dano:,}."
                        if dano
                        else "Daño individual no disponible.",
                    )
                ],
                "dangerous_tools": [
                    f"{habilidad['slot']} · {habilidad['name']}"
                    for habilidad in herramientas
                ],
                "dangerous_abilities": herramientas,
                "how_to_play_against": _contrajuego_campeon(nombre, herramientas),
                "matchup_note": "Enfrentamiento directo por rol registrado."
                if mismo_rol
                else "Amenaza de equipo; no se clasifica como rival directo.",
                "interactions": [
                    {
                        "time_label": str(evento.get("time_label") or ""),
                        "event_id": f"event-{evento.get('order', index)}",
                        "label": str(evento.get("label") or ""),
                    }
                    for index, evento in enumerate(eventos_personales[:8])
                ],
                "interaction_references": referencias,
                "itemization_interaction": _interaccion_itemizacion(nombre, dano, kda),
                "evidence_type": "confirmed_and_derived",
            }
        )
    resultado.sort(
        key=lambda rival: (
            -(4 if str(rival["role"]).casefold() == rol_local else 0),
            -_amenaza_numerica(rival),
            rival["champion_name"],
        )
    )
    return resultado


class MatchChampionResolver:
    """Resuelve identificadores canónicos desde metadatos locales de campeón."""

    @staticmethod
    def resolver(nombre: str) -> str | None:
        """Devuelve el identificador interno de Data Dragon para un nombre."""
        from app.services.match_analysis_evidence_service import (
            MatchAnalysisEvidenceService,
        )

        return MatchAnalysisEvidenceService._canonical_champion_id(nombre)


def _amenaza_numerica(rival: dict[str, Any]) -> int:
    """Convierte la etiqueta de amenaza a un orden estable para las tarjetas."""
    return {"alta": 3, "media": 2, "baja": 1}.get(str(rival.get("threat_level")), 0)


def _herramientas_campeon(nombre: str, habilidades: list[Any]) -> list[dict[str, str]]:
    """Asocia habilidades del catálogo local con una precaución específica."""
    avisos = {
        "naafiri": {
            "Q": "Evita recibir repetidamente sus dagas; la descripción confirma daño adicional contra objetivos sangrantes.",
            "W": "Cuenta con su carrera dirigida a un campeón antes de separarte del equipo.",
            "R": "Su definitiva persigue a un campeón; reserva una respuesta de equipo antes de entrar en su alcance.",
        },
        "yasuo": {
            "Q": "Dos acumulaciones habilitan el tornado; evita comprometerte cuando su Q cargada pueda levantar objetivos.",
            "W": "Muro de viento bloquea proyectiles durante 4 s; espera a que termine antes de lanzar proyectiles relevantes.",
            "R": "Su definitiva requiere objetivos en el aire; evita que el equipo le ofrezca esa continuación.",
        },
        "viktor": {
            "W": "Campo gravitatorio ralentiza y puede aturdir si permaneces dentro; sal de su zona en vez de continuar la persecución.",
            "E": "Rayo Hextech atraviesa en línea recta; cambia el ángulo cuando lo veas canalizar o apuntar.",
            "R": "La tormenta inflige daño cerca de Viktor; no mantengas una pelea prolongada dentro de su zona.",
        },
        "lulu": {
            "W": "Banal puede polimorfizar a un enemigo; coordina el inicio contando con esa interrupción.",
            "R": "Crecimiento salvaje aumenta la vida y desplaza a los enemigos cercanos; espera su uso antes de calcular una eliminación.",
        },
        "tahmkench": {
            "Q": "Su Q ralentiza y aturde al acumular tres marcas; rompe la secuencia y evita prolongar el intercambio tras varias marcas.",
            "E": "Piel gruesa convierte daño recibido en escudo; considera el escudo antes de comprometer recursos para rematarlo.",
            "R": "Devorar puede proteger a un aliado; fuerza o espera esa herramienta antes de fijar un objetivo.",
        },
    }
    clave = nombre.casefold().replace(" ", "")
    resultado = []
    for habilidad in habilidades:
        if not isinstance(habilidad, dict):
            continue
        slot = str(habilidad.get("slot") or "")
        aviso = avisos.get(clave, {}).get(slot)
        if aviso:
            resultado.append(
                {
                    "slot": slot,
                    "name": str(habilidad.get("name") or slot),
                    "description": str(habilidad.get("description") or ""),
                    "counterplay": aviso,
                    "observed_cast": False,
                }
            )
    return resultado


def _contrajuego_campeon(nombre: str, herramientas: list[dict[str, str]]) -> str:
    """Resume contrajuego derivado de descripciones de campeón verificadas."""
    consejos = [
        str(herramienta.get("counterplay") or "") for herramienta in herramientas
    ]
    consejo = " ".join(consejo for consejo in consejos if consejo)
    return (
        consejo
        or f"Adapta el enfrentamiento a las herramientas de {nombre}; el registro no aporta datos para especificar una interacción segura."
    )


def _interaccion_itemizacion(nombre: str, dano: int, kda: dict[str, int]) -> str:
    """Relaciona estadísticas observadas con el tipo de amenaza sin adivinar daño."""
    if nombre.casefold() == "viktor" and dano:
        return f"Viktor registró {dano:,} de daño total a campeones. El log no separa daño mágico y físico; compara una ranura de resistencia mágica con daño ofensivo sin atribuir todo ese daño a magia."
    if kda["kills"] >= 10:
        return f"Sus {kda['kills']} bajas justifican revisar supervivencia y daño; el marcador por sí solo no determina un objeto ·óptimo."
    return "El registro no contiene desglose de daño por tipo para recomendar una resistencia concreta."


def _normalizar_prioridades(payload: Any) -> list[dict[str, str]]:
    """Normaliza prioridades de coaching conservando formato previo."""
    if not isinstance(payload, list):
        return []
    resultado = []
    for valor in payload[:10]:
        if not isinstance(valor, dict):
            continue
        elemento = {}
        for destino, fuentes in {
            "title": ("title",),
            "explanation": ("explanation",),
            "concrete_action": ("concrete_action", "action"),
            "context_type": ("context_type",),
            "reference": ("reference", "champion", "item", "ability"),
            "priority": ("priority",),
            "evidence": ("evidence",),
            "phase": ("phase",),
            "evidence_type": ("evidence_type",),
            "champion_id": ("champion_id",),
            "item_id": ("item_id",),
            "ability_slot": ("ability_slot",),
        }.items():
            texto = _texto_opcional(
                next((valor.get(clave) for clave in fuentes if valor.get(clave)), None),
                f"next_game_priorities.{destino}",
            )
            if texto:
                elemento[destino] = texto
        refs = valor.get("evidence_refs")
        if isinstance(refs, list):
            elemento["evidence_refs"] = [str(ref)[:100] for ref in refs[:12]]
        if elemento.get("title") and (
            elemento.get("explanation") or elemento.get("concrete_action")
        ):
            elemento.setdefault("explanation", elemento.get("concrete_action", ""))
            elemento.setdefault("concrete_action", elemento["explanation"])
            resultado.append(elemento)
    return resultado


def _completar_prioridades(
    prioridades: list[dict[str, str]],
    resumen: dict[str, Any],
    contexto: dict[str, Any],
) -> list[dict[str, str]]:
    """Propone ajustes de revisión vinculados a muertes, objetivos y compras."""
    resultado = list(prioridades)
    eventos = contexto.get("events_chronology", [])
    eventos = eventos if isinstance(eventos, list) else []
    local = str(contexto.get("local_player_key") or "")
    usuario = contexto.get("user_stats", {})
    usuario = usuario if isinstance(usuario, dict) else {}
    muertes = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and evento.get("victim_key") == local
        and "kill" in str(evento.get("type", "")).casefold()
    ]
    barones_enemigos = [
        evento
        for evento in eventos
        if isinstance(evento, dict)
        and (
            "bar"
            in str(evento.get("objective") or evento.get("label") or "").casefold()
        )
        and str(evento.get("team") or "").upper()
        != str(contexto.get("metadata", {}).get("local_team") or "").upper()
    ]
    muerte_baronesa = next(
        (
            (muerte, baron)
            for muerte in reversed(muertes)
            for baron in barones_enemigos
            if 0
            <= float(baron.get("time_seconds") or 0)
            - float(muerte.get("time_seconds") or 0)
            <= 180
        ),
        None,
    )
    if muerte_baronesa:
        muerte, baron = muerte_baronesa
        tiempo_muerte = str(muerte.get("time_label") or "la fase final")
        tiempo_baron = str(baron.get("time_label") or "después")
        resultado.append(
            {
                "title": "Reducir ausencias antes de objetivos decisivos",
                "priority": "high",
                "evidence": f"El registro sitúa una muerte propia a {tiempo_muerte} y el Barón enemigo a {tiempo_baron}; la cercanía temporal no demuestra causalidad.",
                "explanation": "Una muerte próxima a un objetivo puede reducir las opciones de disputa, aunque la telemetría no confirma posiciones ni capacidad real de contestar.",
                "concrete_action": "En la repetición, revisa esa ventana y acuerda con el equipo cuándo reagrupar; no inicies una persecución si el siguiente objetivo está disponible y tu equipo no puede seguirla.",
                "context_type": "objective",
                "phase": "late",
                "evidence_refs": [
                    f"event-{muerte.get('order', '')}",
                    f"event-{baron.get('order', '')}",
                ],
                "reference": "Barón Nashor",
                "evidence_type": "interpretation",
            }
        )
    muertes_iniciales = [
        evento for evento in muertes if float(evento.get("time_seconds") or 0) < 420
    ]
    if muertes_iniciales:
        referencias = [
            f"event-{evento.get('order', '')}" for evento in muertes_iniciales[:4]
        ]
        marcas = ", ".join(
            str(evento.get("time_label") or "") for evento in muertes_iniciales[:3]
        )
        resultado.append(
            {
                "title": "Encontrar el patrón detrás de las muertes iniciales",
                "priority": "high" if len(muertes_iniciales) >= 3 else "medium",
                "evidence": f"La cronología registra {len(muertes_iniciales)} muerte(s) propia(s) antes del minuto 7 ({marcas}).",
                "explanation": "La concentración temporal merece revisión; el log no registra posición, recursos ni quién podía acompañar cada jugada.",
                "concrete_action": "Revisa cada repetición desde 10 segundos antes de la muerte y anota qué información faltaba y qué condición habría cancelado la entrada.",
                "context_type": "early_game",
                "phase": "early",
                "evidence_refs": referencias,
                "evidence_type": "confirmed_and_interpretation",
            }
        )
    if len(resultado) < 3 and usuario.get("items"):
        compras = [
            evento
            for evento in eventos
            if isinstance(evento, dict)
            and evento.get("player_key") == local
            and "purchase" in str(evento.get("type", "")).casefold()
        ]
        refs = [f"event-{evento.get('order', '')}" for evento in compras[-2:]]
        resultado.append(
            {
                "title": "Comparar la siguiente compra defensiva con el pico rival",
                "priority": "medium",
                "evidence": "El marcador del rival y el inventario final están registrados; el oro disponible en cada compra no está confirmado.",
                "explanation": "La composición puede justificar una ranura de resistencia, pero la telemetría no establece cuánto oro tenías en base.",
                "concrete_action": "Al llegar a una compra tardía, compara en el catálogo del parche un componente de resistencia mágica con la siguiente pieza ofensiva y conserva la ruta elegida en la repetición.",
                "context_type": "item",
                "phase": "late",
                "evidence_refs": refs,
                "item_id": "1057",
                "reference": "Capa negatrón",
                "evidence_type": "interpretation",
            }
        )
    if len(resultado) < 5 and eventos:
        propios = [
            evento
            for evento in eventos
            if isinstance(evento, dict)
            and evento.get("killer_key") == local
            and "kill" in str(evento.get("type", "")).casefold()
        ]
        objetivos = [
            evento
            for evento in eventos
            if isinstance(evento, dict)
            and (
                evento.get("objective")
                or "objective" in str(evento.get("type", "")).casefold()
            )
        ]
        if propios and objetivos:
            resultado.append(
                {
                    "title": "Comprobar la conversión de ventajas en objetivos",
                    "priority": "medium",
                    "evidence": f"La cronología incluye {len(propios)} bajas propias y, entre los objetivos clave, {len([evento for evento in objetivos if any(token in str(evento.get('objective') or evento.get('label') or '').casefold() for token in ('bar', 'drag', 'herald', 'grub', 'inhib'))])} capturas/estructuras.",
                    "explanation": "La cronología permite comprobar si una baja abrió tiempo para un objetivo, pero no mide por sí sola la prioridad ni la posición.",
                    "concrete_action": "Después de cada baja, identifica el objetivo disponible más cercano y compara el tiempo de captura registrado.",
                    "context_type": "objective",
                    "phase": "mid",
                    "evidence_refs": [
                        f"event-{evento.get('order', '')}"
                        for evento in (propios[-1:] + objetivos[-1:])
                    ],
                    "evidence_type": "derived",
                }
            )
    usuario = contexto.get("user_stats", {})
    usuario = usuario if isinstance(usuario, dict) else {}
    if len(resultado) < 3 and int(usuario.get("deaths") or 0) > 0:
        resultado.append(
            {
                "title": "Revisar el coste de cada muerte",
                "priority": "medium",
                "evidence": f"El marcador registra {int(usuario.get('deaths') or 0)} muertes; el resumen no permite atribuirlas a una causa concreta.",
                "explanation": "Cada muerte supone tiempo fuera del mapa, pero sin posiciones ni secuencia completa no se puede calcular aquí su efecto exacto.",
                "concrete_action": "Revisa una muerte de cada fase y anota qué información observable habría cambiado la decisión.",
                "context_type": "teamfight",
                "phase": "match",
                "evidence_type": "confirmed_and_interpretation",
            }
        )
    if len(resultado) < 3 and usuario.get("cs_per_min") is not None:
        resultado.append(
            {
                "title": "Contrastar el ritmo de farmeo con la partida",
                "priority": "low",
                "evidence": f"El registro calcula {float(usuario['cs_per_min']):.1f} súbditos por minuto.",
                "explanation": "La cifra describe el ritmo, pero no establece por sí sola si se perdieron oleadas ni qué decisión las causó.",
                "concrete_action": "En la repetición, compara cada regreso a base y desplazamiento con las oleadas que llegaron a tu línea.",
                "context_type": "lane",
                "phase": "match",
                "evidence_type": "derived",
            }
        )
    if len(resultado) < 3 and usuario.get("vision_score") is not None:
        resultado.append(
            {
                "title": "Revisar el marcador de visión junto a los objetivos",
                "priority": "low",
                "evidence": f"El marcador final registra {int(usuario['vision_score'])} de puntuación de visión; no hay cobertura por zona ni colocaciones en este resumen.",
                "explanation": "La cifra final no demuestra qué zonas estaban cubiertas en un momento concreto.",
                "concrete_action": "En la repetición, contrasta las ventanas previas a Dragón y Barón con las oportunidades de colocar o retirar visión que sí aparezcan.",
                "context_type": "vision",
                "phase": "match",
                "evidence_type": "confirmed_and_unknown",
            }
        )
    return resultado
