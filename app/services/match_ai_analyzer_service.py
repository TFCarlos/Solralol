from __future__ import annotations

import json
from typing import Any
import requests

from app.services.match_log_service import MatchLogService


class MatchAIAnalyzerService:
    """
    Servicio para generar análisis post-partida detallados con IA (Gemini API)
    basándose en el fichero de log de la partida.
    """

    FALLBACK_MODELS = [
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
    ) -> tuple[str, str]:
        """
        Analiza la partida utilizando el log registrado y la API de Gemini.
        Devuelve una tupla (markdown_analysis, model_used).
        """
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("No se ha configurado la Gemini API Key. Por favor confígurala en Ajustes.")

        # Obtener o generar el log de la partida
        log_service = MatchLogService()
        log_data, formatted_log = log_service.get_match_log(session)

        # Construir el prompt para Gemini
        prompt = self._build_analysis_prompt(log_data, formatted_log)

        # Llamar a Gemini API
        markdown_response, model_used = self._call_gemini_api(prompt, api_key)

        return markdown_response, model_used

    def _build_analysis_prompt(
        self,
        log_data: dict[str, Any],
        formatted_log: str,
    ) -> str:
        metadata = log_data.get("metadata", {})
        user_stats = log_data.get("user_stats", {})
        champ = metadata.get("champion_name", "Campeón")

        return f"""Eres un Analista Profesional y Coach de Alto Nivel de League of Legends (Challenger).
Tu trabajo es realizar una evaluación táctica post-partida profunda, estructurada y constructiva para el jugador que ha jugado con el campeón '{champ}'.

A continuación tienes el REGISTRO OFICIAL Y COMPLETO DE LOG DE LA PARTIDA:

```text
{formatted_log}
```

INSTRUCCIONES OBLIGATORIAS DE FORMATO Y CONTENIDO:
Responde EXCLUSIVAMENTE en español con formato Markdown bien formateado, limpio y visual. 
DEBES incluir de forma clara y detallada las siguientes secciones exactas:

# 📊 Análisis de Partida con IA: {champ}

## 🎯 Resumen Ejecutivo
- **Resultado de la partida:** {metadata.get('result')} ({metadata.get('duration_formatted')})
- **KDA Final:** {user_stats.get('kills')}/{user_stats.get('deaths')}/{user_stats.get('assists')} | **Farmeo:** {user_stats.get('cs_total')} CS ({user_stats.get('cs_per_min')} CS/min)
- **Calificación Global:** [Asigna una nota: S+, S, A+, A, B, C, D]
- **Resumen táctico general:** Breve balance general de la partida y papel del jugador (3-4 frases).

## ⏳ Rendimiento por Fases de la Partida
### 🟢 Early Game (0-15 min)
- Evaluación de la fase de líneas, tradeos, nivel de farmeo inicial, primeras bajas y control de visión temprano.
### 🟡 Mid Game (15-25 min)
- Evaluación de rotaciones, peleas de equipo/escaramuzas, picos de poder de objetos y presión en el mapa.
### 🔴 Late Game (25+ min)
- Evaluación de teamfights decisivas, ejecución de condiciones de victoria y control de Barón/Dragón Anciano (si la partida duró menos de 25 min, analizar cómo se cerró o se perdió la partida).

## 🌾 Rendimiento del Farmeo (Farm / CS)
- Análisis de la eficiencia de CS por minuto ({user_stats.get('cs_per_min')} CS/min).
- Comparativa de farmeo con los rivales directos y ritmo de generación de oro a lo largo del tiempo.
- Consejos específicos para mejorar el farmeo en distintas etapas.

## ⚔️ Valoración de la Build vs Equipo Enemigo
- Análisis de los objetos comprados ({user_stats.get('items')}) frente a la composición de campeones enemigos (daño físico/mágico, curaciones enemigas, tanques, CC).
- Aciertos y fallos en la adaptación de la build (¿Faltó penetración de armadura/mágica, cortacuras, resistencia o protección?).

## ⏱️ Velocidad de Compra y Tempos de Receso (Recalls)
- Evaluación del timing de vuelta a base y compra de ítems principales.
- Análizar si las vueltas a base se hicieron aprovechando picos de poder (power spikes) o si se perdió tempo/oleadas innecesariamente.

## 🎯 Impacto de Asesinatos en Objetivos (Kills vs Objetivos / Kills "Vacías")
- Análisis de si las bajas (kills) conseguidas se tradujeron en capturas de dragones, heraldos, torres, barones o ventajas en el mapa.
- Identificación y evaluación de **"Kills Vacías"** (asesinatos logrados que no aportaron ningún objetivo ni ventaja táctica real posterior).

## 💀 Impacto de Muertes en Objetivos Perdidos
- Análisis de cómo las muertes del jugador facilitaron al equipo enemigo la pérdida de torres, dragones, barones o presión de líneas.
- Identificación de muertes críticas que cambiaron el tempo de la partida.

## 💡 Consejos Clave para la Siguiente Partida
- Proporciona 3 o 4 consejos accionables, claros y prioritarios para mejorar en las próximas partidas.
"""

    def _get_available_models(self, api_key: str) -> list[str]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
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
                    priority_keywords = ["flash-lite", "2.5-flash", "flash-latest", "2.0-flash-lite", "2.0-flash", "flash"]
                    sorted_models = []
                    for kw in priority_keywords:
                        for m in gen_models:
                            if kw in m and m not in sorted_models:
                                sorted_models.append(m)
                    for m in gen_models:
                        if m not in sorted_models:
                            sorted_models.append(m)
                    return sorted_models
        except Exception:
            pass

        return self.FALLBACK_MODELS

    def _call_gemini_api(self, prompt: str, api_key: str) -> tuple[str, str]:
        models = self._get_available_models(api_key)
        last_error = ""

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
            }
        }

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=35)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            if text and len(text.strip()) > 50:
                                return text, model
                elif resp.status_code in (400, 404):
                    last_error = f"HTTP {resp.status_code} ({model}): {resp.text[:150]}"
                    continue
                else:
                    resp.raise_for_status()
            except requests.RequestException as err:
                last_error = f"Error ({model}): {err}"
                continue

        raise RuntimeError(f"Error al llamar a la API de Gemini para el análisis: {last_error or 'Sin respuesta de la API'}")

