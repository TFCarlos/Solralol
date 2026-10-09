from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any, ClassVar

import requests

from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
from app.services.match_analysis_models import enriquecer_analisis_partida
from app.services.match_log_service import MatchLogService

ESQUEMA_ANALISIS_GEMINI = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer"},
        "analysis_type": {"type": "string"},
        "summary": {
            "type": "object",
            "properties": {
                "overall_grade": {"type": "string"},
                "short_summary": {"type": "string"},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "weaknesses": {"type": "array", "items": {"type": "string"}},
                "key_takeaway": {"type": "string"},
                "champion_name": {"type": "string"},
                "player_name": {"type": "string"},
                "main_error": {"type": "string"},
                "core_priority": {"type": "string"},
                "main_turning_point": {"type": "string"},
                "primary_strength": {"type": "string"},
                "primary_weakness": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
        },
        "game_phases": {
            "type": "object",
            "properties": {
                clave: {
                    "type": "object",
                    "properties": {
                        "assessment": {"type": "string"},
                        "strengths": {"type": "array", "items": {"type": "string"}},
                        "mistakes": {"type": "array", "items": {"type": "string"}},
                        "recommendations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "what_worked": {"type": "string"},
                        "what_failed": {"type": "string"},
                        "adaptation": {"type": "string"},
                        "evidence_events": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "event_id": {"type": "string"},
                                    "time_label": {"type": "string"},
                                    "claim": {"type": "string"},
                                    "evidence_type": {"type": "string"},
                                },
                            },
                        },
                    },
                }
                for clave in ("early", "mid", "late")
            },
        },
        **{
            clave: {
                "type": "object",
                "properties": {
                    propiedad: {"type": "array", "items": {"type": "string"}}
                    if propiedad
                    in {"strengths", "mistakes", "recommendations", "alternative_items"}
                    else {"type": "string"}
                    for propiedad in propiedades
                },
            }
            for clave, propiedades in {
                "farming": ("assessment", "recommendations"),
                "itemization": (
                    "strengths",
                    "mistakes",
                    "alternative_items",
                    "recommendations",
                ),
                "purchase_timing": ("assessment", "recommendations"),
                "objective_conversion": ("assessment", "recommendations"),
                "death_impact": ("assessment", "recommendations"),
            }.items()
        },
        "enemy_matchups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "champion_id": {"type": "string"},
                    "role": {"type": "string"},
                    "threat_level": {"type": "string"},
                    "kda": {
                        "type": "object",
                        "properties": {
                            "kills": {"type": "integer"},
                            "deaths": {"type": "integer"},
                            "assists": {"type": "integer"},
                        },
                    },
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "dangerous_abilities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "slot": {"type": "string"},
                                "name": {"type": "string"},
                                "why_it_matters": {"type": "string"},
                                "counterplay": {"type": "string"},
                            },
                        },
                    },
                    "itemization_interaction": {"type": "string"},
                    "difficulty": {"type": "string"},
                    "assessment": {"type": "string"},
                    **{
                        clave: {"type": "array", "items": {"type": "string"}}
                        for clave in ("counterplay", "mistakes", "recommendations")
                    },
                },
            },
        },
        "improvement_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "priority": {"type": "string"},
                    "action": {"type": "string"},
                },
            },
        },
        "performance": {
            "type": "object",
            "properties": {
                clave: {
                    "type": "object",
                    "properties": {
                        "assessment": {"type": "string"},
                        "tip": {"type": "string"},
                    },
                }
                for clave in (
                    "farming",
                    "combat",
                    "objectives",
                    "vision",
                    "survivability",
                    "decision_making",
                )
            },
        },
        "build_assessment": {"type": "string"},
        "itemization_notes": {"type": "array", "items": {"type": "string"}},
        "situational_item_suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "item_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "item_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "verdict": {"type": "string"},
                    "assessment": {"type": "string"},
                    "purchase_time": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "item_alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "replace_or_delay_item_id": {"type": "string"},
                    "threat_champion_id": {"type": "string"},
                    "mechanical_advantage": {"type": "string"},
                    "tradeoff": {"type": "string"},
                    "timing": {"type": "string"},
                    "affordability": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rune_comments": {"type": "array", "items": {"type": "string"}},
        "key_enemies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "champion_name": {"type": "string"},
                    "role": {"type": "string"},
                    "threat_level": {"type": "string"},
                    "why_it_was_a_problem": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}},
                    "dangerous_tools": {"type": "array", "items": {"type": "string"}},
                    "how_to_play_against": {"type": "string"},
                    "matchup_note": {"type": "string"},
                },
            },
        },
        "next_game_priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "concrete_action": {"type": "string"},
                    "context_type": {"type": "string"},
                    "reference": {"type": "string"},
                    "priority": {"type": "string"},
                    "phase": {"type": "string"},
                    "evidence": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "champion_id": {"type": "string"},
                    "item_id": {"type": "string"},
                    "ability_slot": {"type": "string"},
                },
            },
        },
    },
    "required": [
        "schema_version",
        "analysis_type",
        "summary",
        "game_phases",
        "performance",
        "build_assessment",
        "itemization_notes",
        "item_reviews",
        "item_alternatives",
        "rune_comments",
        "key_enemies",
        "next_game_priorities",
    ],
}


class ErrorSolicitudGemini(RuntimeError):
    """Conserva el diagnóstico seguro devuelto por una solicitud Gemini."""

    def __init__(self, diagnostico: dict[str, Any]) -> None:
        """Inicializa el error con detalles técnicos serializables."""
        self.diagnostico = diagnostico
        self.reintentable = diagnostico.get("http_status") != 400
        super().__init__(json.dumps(diagnostico, ensure_ascii=False))


class MatchAIAnalyzerService:
    """
    Servicio para generar análisis post-partida detallados con IA (Gemini API)
    basándose en el fichero de log de la partida.
    """

    FALLBACK_MODELS: ClassVar[list[str]] = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash-latest",
    ]

    def analyze_match(
        self,
        session: dict[str, Any],
        api_key: str,
    ) -> tuple[dict[str, Any], str, str, str]:
        """
        Analiza la partida utilizando el log registrado y la API de Gemini.
        Devuelve análisis validado, respuesta JSON original, modelo e huella del log.
        """
        api_key = api_key.strip()
        if not api_key:
            raise ValueError(
                "No se ha configurado la Gemini API Key. "
                "Por favor confígurala en Ajustes."
            )

        # Obtener o generar el log de la partida
        log_service = MatchLogService()
        log_data, formatted_log = log_service.get_match_log(session)

        # Construir evidencia reproducible antes de consultar Gemini.
        evidencia = MatchAnalysisEvidenceService().build_evidence(log_data)
        log_data["analysis_evidence"] = evidencia
        prompt = self._build_analysis_prompt(log_data, formatted_log)

        # Llamar a Gemini API
        respuesta, model_used = self._call_gemini_api(prompt, api_key)
        try:
            contexto = {
                **log_data,
                "champion_name": log_data.get("metadata", {}).get("champion_name"),
                "player_name": log_data.get("user_stats", {}).get("player_name"),
            }
            analisis = enriquecer_analisis_partida(json.loads(respuesta), contexto)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError(
                f"Gemini devolvió un análisis estructurado no válido: {error}"
            ) from error
        if len(respuesta) > 200_000:
            raise ValueError(
                "La respuesta estructurada de Gemini supera el tamaño permitido."
            )
        huella = sha256(formatted_log.encode("utf-8")).hexdigest()
        return analisis, respuesta, model_used, huella

    def _build_analysis_prompt(
        self,
        log_data: dict[str, Any],
        formatted_log: str,
    ) -> str:
        """Construye un prompt basado en hechos curados y eventos citables."""
        del formatted_log
        evidencia = log_data.get("analysis_evidence")
        if not isinstance(evidencia, dict):
            evidencia = MatchAnalysisEvidenceService().build_evidence(log_data)
        roster = evidencia.get("participants", [])
        rol = str(evidencia.get("player", {}).get("role") or "UNKNOWN")
        rivales_directos = [
            participante
            for participante in roster
            if not participante.get("is_ally")
            and str(participante.get("role") or "").casefold() == rol.casefold()
        ]
        return f"""Eres coach postpartida de League of Legends. Redacta toda la salida en español.

La evidencia JSON adjunta fue extraída determinísticamente del registro de SOLRALOL. Trátala como fuente de hechos: no inventes posiciones, visión, lanzamientos de habilidades, oro disponible ni causas tácticas. Distingue hechos confirmados, cálculos e interpretaciones. Cada afirmación importante debe citar uno o más event_id de notable_timeline o champion_id/item_id. El catálogo de habilidades y objetos es estático de Data Dragon; menciona herramientas como mecánicas conocidas, nunca como habilidades observadas en esta partida.

EVIDENCIA:
{json.dumps(evidencia, ensure_ascii=False, separators=(",", ":"))}

Devuelve únicamente JSON compatible con schema_version=3 y analysis_type="general_match_analysis". El resumen debe explicar decisiones y cambios de ritmo, sin repetir KDA/CS/oro como análisis. overall_grade debe ser una valoración verbal, no una nota del motor. Si performance_scoring contiene un resultado final, consérvalo como dato separado y no lo recalcules.

Incluye early, mid y late. En cada fase, cita entre 2 y 4 eventos relevantes, explica contribuciones y preocupaciones que sí se desprendan de ellos y da un ajuste concreto. No uses recuentos de eventos como evaluación.

Eval?a farming, combat, objectives, vision, survivability y decision_making con evidencia y consejos proporcionales. En build, analiza cada objeto final importante con su funci?n del catálogo y un veredicto razonado. Vincula compras con tiempos solo cuando purchase_events existan. Propón como máximo alternativas legales del catálogo; identifica una ranura/objeto que se retrasaría o cambiar?a, el beneficio y el coste de oportunidad. La cobertura gold_on_hand_available indica si la asequibilidad exacta se conoce; si es falsa, declara que la asequibilidad exacta no es confirmable. No inventes runas: si faltan, indícalo.

Devuelve un análisis de cada uno de los cinco enemigos observados en key_enemies, sin excluir apoyos o frontline. Ordena por importancia, pero incluye los cinco. Para cada uno incluye campeón, rol, amenaza, KDA, por qué importó, interacciones registradas, habilidades relevantes basadas solo en ability_catalog, contrajuego específico y relación de itemizaci?n. Identifica como rival directo solo a los campeones de roles coincidentes verificados; en este caso candidatos: {json.dumps(rivales_directos, ensure_ascii=False)}. Considera kills, muertes y asistencias al estimar amenaza; no ignores alto número de asistencias.

Devuelve entre 3 y 5 next_game_priorities, cada una con título, gravedad, evidence_refs, por qué importa, acción concreta, fase y referencias visuales mediante champion_id/item_id/ability_slot cuando existan. Si falta evidencia suficiente, formula una limitación explícita en vez de rellenar con ficción.
"""

    def _get_available_models(self, api_key: str) -> list[str]:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            resp = requests.get(
                url,
                headers={"Accept": "application/json", "x-goog-api-key": api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_models = data.get("models", [])
                gen_models = []
                for m in raw_models:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        name = str(m.get("name", "")).replace("models/", "").strip()
                        if name:
                            gen_models.append(name)

                if gen_models:
                    priority_keywords = [
                        "flash-lite",
                        "2.5-flash",
                        "flash-latest",
                        "2.0-flash-lite",
                        "2.0-flash",
                        "flash",
                    ]
                    sorted_models = []
                    for kw in priority_keywords:
                        for m in gen_models:
                            if kw in m and m not in sorted_models:
                                sorted_models.append(m)
                    for m in gen_models:
                        if m not in sorted_models:
                            sorted_models.append(m)
                    return sorted_models
        except (
            requests.RequestException,
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            return self.FALLBACK_MODELS

        return self.FALLBACK_MODELS

    def _call_gemini_api(self, prompt: str, api_key: str) -> tuple[str, str]:
        models = self._get_available_models(api_key)
        last_error = ""

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 8192,
                "responseFormat": {
                    "text": {
                        "mimeType": "APPLICATION_JSON",
                        "schema": ESQUEMA_ANALISIS_GEMINI,
                    }
                },
            },
        }

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": api_key,
                    },
                    timeout=35,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            if text and len(text.strip()) > 50:
                                return text, model
                elif resp.status_code == 400:
                    try:
                        respuesta_error = resp.json().get("error", {})
                    except (ValueError, AttributeError):
                        respuesta_error = {}
                    mensaje = str(respuesta_error.get("message") or resp.text)
                    ruta = re.search(r"Invalid value at '([^']+)'", mensaje)
                    cabeceras = getattr(resp, "headers", {}) or {}
                    diagnostico = {
                        "http_status": 400,
                        "api_code": respuesta_error.get("code"),
                        "category": str(
                            respuesta_error.get("status") or "INVALID_ARGUMENT"
                        ),
                        "message": mensaje,
                        "details": respuesta_error.get("details", []),
                        "field_path": ruta.group(1) if ruta else None,
                        "request_id": next(
                            (
                                cabeceras.get(nombre)
                                for nombre in (
                                    "x-request-id",
                                    "x-goog-request-id",
                                    "request-id",
                                )
                                if cabeceras.get(nombre)
                            ),
                            None,
                        ),
                        "model": model,
                        "retryable": False,
                    }
                    for clave, valor in diagnostico.items():
                        if isinstance(valor, str):
                            diagnostico[clave] = re.sub(
                                r"(?i)(AIza[0-9A-Za-z_-]{20,}|(?:key=)[^&\s]+)",
                                "[REDACTED]",
                                valor,
                            )
                    diagnostico["details"] = re.sub(
                        r"(?i)(AIza[0-9A-Za-z_-]{20,}|(?:key=)[^&\s]+)",
                        "[REDACTED]",
                        json.dumps(diagnostico["details"], ensure_ascii=False),
                    )
                    raise ErrorSolicitudGemini(diagnostico)
                elif resp.status_code == 404:
                    last_error = f"HTTP 404 ({model}): {resp.text}"
                    continue
                else:
                    resp.raise_for_status()
            except requests.RequestException as err:
                last_error = f"Error ({model}): {err}"
                continue

        raise RuntimeError(
            f"Error al llamar a la API de Gemini para el análisis: {last_error or 'Sin respuesta de la API'}"
        )
