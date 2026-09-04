from __future__ import annotations

import json
import re
from typing import Any
import requests


class ChampionAIAnalyzerService:
    """Servicio para re-analizar atributos subjetivos de campeones de LoL mediante la API de Gemini (Google AI Studio)."""

    ALLOWED_PLAY_STYLES = {
        "Bruiser", "Diver", "Assassin", "Skirmisher", "Marksman",
        "Mage", "Enchanter", "Vanguard", "Warden", "Juggernaut"
    }
    ALLOWED_DAMAGE_TYPES = {"AD", "AP", "True", "Hybrid"}
    ALLOWED_RESOURCE_TYPES = {
        "Mana", "Energy", "Fury", "Health", "Rage",
        "Courage", "Shield", "None", "Flow", "Ferocity", "Heat"
    }
    ALLOWED_ROLES = {"Top", "Jungle", "Mid", "ADC", "Support"}

    MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

    def reanalyze_champion(self, champion_data: dict[str, Any], api_key: str) -> dict[str, Any]:
        """Envía el campeón a Gemini AI y devuelve el diccionario del campeón actualizado con los valores re-analizados."""
        api_key = api_key.strip()
        if not api_key:
            raise ValueError("No se ha configurado la Gemini API Key. Añádela en Ajustes.")

        character_name = champion_data.get("character", champion_data.get("basic_info", {}).get("name", "Campeón"))

        prompt = self._build_prompt(character_name, champion_data)

        raw_response = self._call_gemini_api(prompt, api_key)
        parsed_json = self._extract_json_from_response(raw_response)

        # Copia profunda del diccionario original para preservar campos no subjetivos
        updated_data = json.loads(json.dumps(champion_data))
        self._merge_and_sanitize(updated_data, parsed_json)

        return updated_data

    def _build_prompt(self, character_name: str, current_data: dict[str, Any]) -> str:
        basic = current_data.get("basic_info", {})
        combat = current_data.get("combat_attributes", {})
        resist = current_data.get("resistances_and_survivability", {})
        map_ctrl = current_data.get("map_and_control", {})
        scaling = current_data.get("power_curve_and_scaling", {})

        return f"""You are a League of Legends High-Elo Analyst and AI Data Model.
Your task is to re-analyze and evaluate the champion '{character_name}' for current competitive Summoner's Rift gameplay.

Analyze and return ONLY a valid JSON object containing the updated subjective fields for '{character_name}'.

STRICT RULES & CONSTRAINTS:

1. basic_info:
- play_style: MUST be strictly ONE of: {list(self.ALLOWED_PLAY_STYLES)}
- damage_type: MUST be strictly ONE of: {list(self.ALLOWED_DAMAGE_TYPES)}
- resource_type: MUST be strictly ONE of: {list(self.ALLOWED_RESOURCE_TYPES)}
- difficulty_floor: Integer from 1 to 10
- difficulty_ceiling: Integer from 1 to 10
- flex_potential: Array of strings containing primary/secondary roles allowed in competitive meta. Allowed values: {list(self.ALLOWED_ROLES)}

2. combat_attributes:
- attack_damage: Integer from 1 to 10
- attack_power: Integer from 1 to 10
- critic: Integer from 1 to 10
- lethality: Integer from 1 to 10

3. resistances_and_survivability:
- armor: Integer from 1 to 10
- magic_resistance: Integer from 1 to 10
- survivability_vs_damage: Integer from 1 to 10
- survivability_vs_armor: Integer from 1 to 10
- survivability_vs_cc: Integer from 1 to 10
- survivability_overall: Integer from 1 to 10

4. map_and_control:
- mobility: Integer from 1 to 10
- crowd_control: Integer from 1 to 10
- wave_clear: Integer from 1 to 10
- objective_control: Integer from 1 to 10
- side_lane_pressure: Integer from 1 to 10
- team_fight: Integer from 1 to 10
- utility: Integer from 1 to 10
- range: Integer from 1 to 10

5. power_curve_and_scaling:
- early_game: Integer from 1 to 10
- mid_game: Integer from 1 to 10
- late_game: Integer from 1 to 10
- hypercarry: Integer from 1 to 10
- dependency_on_gold: Integer from 1 to 10
- power_spike_level: Integer from 1 to 18

Current reference values for {character_name}:
{json.dumps({"basic_info": basic, "combat_attributes": combat, "resistances_and_survivability": resist, "map_and_control": map_ctrl, "power_curve_and_scaling": scaling}, ensure_ascii=False, indent=2)}

Respond with ONLY the JSON object matching this exact schema:
{{
  "basic_info": {{
    "play_style": "...",
    "damage_type": "...",
    "resource_type": "...",
    "difficulty_floor": 5,
    "difficulty_ceiling": 7,
    "flex_potential": ["Top"]
  }},
  "combat_attributes": {{
    "attack_damage": 7,
    "attack_power": 3,
    "critic": 2,
    "lethality": 2
  }},
  "resistances_and_survivability": {{
    "armor": 6,
    "magic_resistance": 5,
    "survivability_vs_damage": 6,
    "survivability_vs_armor": 6,
    "survivability_vs_cc": 4,
    "survivability_overall": 6
  }},
  "map_and_control": {{
    "mobility": 6,
    "crowd_control": 3,
    "wave_clear": 5,
    "objective_control": 5,
    "side_lane_pressure": 7,
    "team_fight": 7,
    "utility": 3,
    "range": 2
  }},
  "power_curve_and_scaling": {{
    "early_game": 5,
    "mid_game": 7,
    "late_game": 8,
    "hypercarry": 4,
    "dependency_on_gold": 7,
    "power_spike_level": 3
  }}
}}
"""

    def _get_available_models(self, api_key: str) -> list[str]:
        """Obtiene dinámicamente los modelos ligeros de Gemini disponibles en la cuenta del usuario."""
        fallback_models = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash",
            "gemini-1.5-flash-latest",
        ]
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

        return fallback_models

    def _call_gemini_api(self, prompt: str, api_key: str) -> str:
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
                "temperature": 0.2,
                "response_mime_type": "application/json"
            }
        }

        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
                elif resp.status_code in (400, 404):
                    last_error = f"HTTP {resp.status_code} ({model}): {resp.text[:150]}"
                    continue
                else:
                    resp.raise_for_status()
            except requests.RequestException as err:
                last_error = f"Error ({model}): {err}"
                continue

        simple_payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        for model in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json=simple_payload, headers={"Content-Type": "application/json"}, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            return parts[0].get("text", "")
            except requests.RequestException:
                pass

        raise RuntimeError(f"Error al llamar a la API de Gemini: {last_error or 'Respuesta vacía o error de red.'}")

    def _extract_json_from_response(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            text = match.group(0)

        try:
            val = json.loads(text)
            if isinstance(val, dict):
                return val
        except json.JSONDecodeError as err:
            raise ValueError(f"Gemini devolvió una respuesta que no es JSON válido: {err}")

        raise ValueError("No se pudo estructurar la respuesta JSON de Gemini.")

    def _merge_and_sanitize(self, target: dict[str, Any], ai_data: dict[str, Any]) -> None:
        """Sanitiza y fusiona los valores subjetivos de la IA en el objeto del campeón."""

        # 1. basic_info
        ai_basic = ai_data.get("basic_info", {})
        if isinstance(ai_basic, dict):
            target_basic = target.setdefault("basic_info", {})

            play_style = str(ai_basic.get("play_style", target_basic.get("play_style", "Juggernaut"))).strip()
            target_basic["play_style"] = play_style if play_style in self.ALLOWED_PLAY_STYLES else target_basic.get("play_style", "Juggernaut")

            dmg_type = str(ai_basic.get("damage_type", target_basic.get("damage_type", "AD"))).strip()
            target_basic["damage_type"] = dmg_type if dmg_type in self.ALLOWED_DAMAGE_TYPES else target_basic.get("damage_type", "AD")

            res_type = str(ai_basic.get("resource_type", target_basic.get("resource_type", "None"))).strip()
            target_basic["resource_type"] = res_type if res_type in self.ALLOWED_RESOURCE_TYPES else target_basic.get("resource_type", "None")

            target_basic["difficulty_floor"] = self._clamp_int(ai_basic.get("difficulty_floor"), target_basic.get("difficulty_floor", 5), 1, 10)
            target_basic["difficulty_ceiling"] = self._clamp_int(ai_basic.get("difficulty_ceiling"), target_basic.get("difficulty_ceiling", 7), 1, 10)

            raw_flex = ai_basic.get("flex_potential", target_basic.get("flex_potential", ["Top"]))
            if isinstance(raw_flex, list):
                clean_flex = [str(role).strip() for role in raw_flex if str(role).strip() in self.ALLOWED_ROLES]
                target_basic["flex_potential"] = clean_flex if clean_flex else target_basic.get("flex_potential", ["Top"])

        # 2. combat_attributes
        self._sanitize_section(target, ai_data, "combat_attributes", ["attack_damage", "attack_power", "critic", "lethality"], min_val=1, max_val=10)

        # 3. resistances_and_survivability
        self._sanitize_section(target, ai_data, "resistances_and_survivability", [
            "armor", "magic_resistance", "survivability_vs_damage",
            "survivability_vs_armor", "survivability_vs_cc", "survivability_overall"
        ], min_val=1, max_val=10)

        # 4. map_and_control
        self._sanitize_section(target, ai_data, "map_and_control", [
            "mobility", "crowd_control", "wave_clear", "objective_control",
            "side_lane_pressure", "team_fight", "utility", "range"
        ], min_val=1, max_val=10)

        # 5. power_curve_and_scaling
        ai_scaling = ai_data.get("power_curve_and_scaling", {})
        if isinstance(ai_scaling, dict):
            target_scaling = target.setdefault("power_curve_and_scaling", {})
            for field in ["early_game", "mid_game", "late_game", "hypercarry", "dependency_on_gold"]:
                if field in ai_scaling or field in target_scaling:
                    target_scaling[field] = self._clamp_int(ai_scaling.get(field), target_scaling.get(field, 5), 1, 10)
            target_scaling["power_spike_level"] = self._clamp_int(ai_scaling.get("power_spike_level"), target_scaling.get("power_spike_level", 6), 1, 18)

    def _sanitize_section(self, target: dict[str, Any], ai_data: dict[str, Any], section_name: str, fields: list[str], min_val: int, max_val: int) -> None:
        ai_sec = ai_data.get(section_name, {})
        target_sec = target.setdefault(section_name, {})
        if isinstance(ai_sec, dict):
            for field in fields:
                default_val = target_sec.get(field, 5)
                val = ai_sec.get(field) if field in ai_sec else default_val
                target_sec[field] = self._clamp_int(val, default_val, min_val, max_val)

    @staticmethod
    def _clamp_int(val: Any, default: int, min_val: int, max_val: int) -> int:
        try:
            num = int(round(float(val)))
            return max(min_val, min(max_val, num))
        except (TypeError, ValueError):
            try:
                num = int(round(float(default)))
                return max(min_val, min(max_val, num))
            except (TypeError, ValueError):
                return min_val

