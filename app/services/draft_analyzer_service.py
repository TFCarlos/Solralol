from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DraftAnalyzerService:
    """Servicio de análisis en tiempo real para fase de Draft (Champ Select)."""

    TIME_BRACKETS = ["0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40+"]

    def __init__(self, champions_strict_path: Path | None = None) -> None:
        self.path = champions_strict_path or Path(__file__).resolve().parents[2] / "data" / "champions_strict.json"
        self.champions: dict[str, dict[str, Any]] = {}
        self.champ_by_id: dict[int, str] = {}
        self._load_data()

    def _load_data(self) -> None:
        if not self.path.exists():
            return
        try:
            raw_list = json.loads(self.path.read_text(encoding="utf-8"))
            for entry in raw_list:
                name = entry.get("character") or entry.get("basic_info", {}).get("name")
                if name:
                    self.champions[name.casefold()] = entry
        except (json.JSONDecodeError, OSError):
            pass

        # Cargar catálogo DataDragon para mapear championId -> nombre
        catalog_path = self.path.parent / "champion_catalog.json"
        if catalog_path.exists():
            try:
                cat = json.loads(catalog_path.read_text(encoding="utf-8"))
                for c_info in cat.get("data", {}).values():
                    key_str = c_info.get("key")
                    c_name = c_info.get("name")
                    if key_str and c_name:
                        self.champ_by_id[int(key_str)] = c_name
            except Exception:
                pass

    def get_champion_name_by_id(self, champ_id: int) -> str:
        return self.champ_by_id.get(champ_id, "")

    def get_champion_profile(self, champion_name: str) -> dict[str, Any] | None:
        return self.champions.get(champion_name.casefold())

    def get_likely_roles(self, champion_name: str) -> list[str]:
        """Devuelve los roles probables del campeón, ordenados por frecuencia.

        Los perfiles actuales codifican el rol más habitual como el primer
        elemento de ``flex_potential``. Normalizamos los nombres de Data
        Dragon/U.GG para que coincidan con los usados por la herramienta.
        """
        profile = self.get_champion_profile(champion_name)
        if not profile:
            return []
        info = profile.get("basic_info", {})
        raw_roles = [info.get("primary_role")] + list(info.get("flex_potential", []))
        role_aliases = {
            "adc": "Bot", "bottom": "Bot", "bot": "Bot",
            "middle": "Mid", "mid": "Mid", "top": "Top",
            "jungle": "Jungle", "support": "Support", "utility": "Support",
        }
        roles: list[str] = []
        for raw_role in raw_roles:
            role = role_aliases.get(str(raw_role or "").casefold())
            if role and role not in roles:
                roles.append(role)
        return roles

    def calculate_team_damage_breakdown(self, team_champions: list[str]) -> dict[str, float]:
        """Calcula el desglose porcentual de daño físico, mágico y verdadero del equipo."""
        total_ad = 0.0
        total_ap = 0.0
        total_true = 0.0
        count = 0

        for champ in team_champions:
            prof = self.get_champion_profile(champ)
            if not prof:
                continue
            dmg_prof = prof.get("damage_profile", {})
            if isinstance(dmg_prof, dict) and dmg_prof:
                total_ad += float(dmg_prof.get("physical_damage", 50))
                total_ap += float(dmg_prof.get("magic_damage", 40))
                total_true += float(dmg_prof.get("true_damage", 10))
                count += 1
            else:
                # Estimación por tipo de daño principal si no hay desglose detallado
                binfo = prof.get("basic_info", {})
                dtype = str(binfo.get("damage_type", "AD")).upper()
                if "AP" in dtype or "MAGIC" in dtype:
                    total_ap += 75.0
                    total_ad += 20.0
                    total_true += 5.0
                elif "TRUE" in dtype:
                    total_true += 60.0
                    total_ad += 30.0
                    total_ap += 10.0
                else:
                    total_ad += 75.0
                    total_ap += 20.0
                    total_true += 5.0
                count += 1

        if count == 0:
            return {"physical": 50.0, "magic": 45.0, "true": 5.0}

        grand_total = total_ad + total_ap + total_true
        if grand_total == 0:
            return {"physical": 50.0, "magic": 45.0, "true": 5.0}

        return {
            "physical": round((total_ad / grand_total) * 100, 1),
            "magic": round((total_ap / grand_total) * 100, 1),
            "true": round((total_true / grand_total) * 100, 1),
        }

    def get_matchup_win_rate(self, champion_name: str, opponent_name: str) -> float:
        """Obtiene el win rate de ``champion_name`` contra ``opponent_name``.

        Si la pareja todavía no está en los datos, comunica incertidumbre con
        50%, en vez de inventar una ventaja visual.
        """
        profile = self.get_champion_profile(champion_name)
        if not profile or not opponent_name:
            return 50.0
        matchups = profile.get("matchups", {})
        for group_name in ("counters", "good_against"):
            for matchup in matchups.get(group_name, []):
                if not isinstance(matchup, dict):
                    continue
                if str(matchup.get("champion", "")).casefold() != opponent_name.casefold():
                    continue
                try:
                    win_rate = float(matchup.get("win_rate", 0.5))
                    return round(win_rate * 100 if win_rate <= 1.0 else win_rate, 1)
                except (TypeError, ValueError):
                    return 50.0
        return 50.0

    def get_champion_overall_win_rate(self, champion_name: str) -> float:
        """Devuelve el win rate global del campeón, no el de un matchup puntual."""
        profile = self.get_champion_profile(champion_name)
        if not profile:
            return 50.0

        summary = profile.get("matchups", {}).get("summary", {})
        candidates = (
            summary.get("overall_win_rate") if isinstance(summary, dict) else None,
            profile.get("overall_win_rate"),
        )
        for candidate in candidates:
            try:
                value = float(candidate)
                return round(value * 100 if 0.0 <= value <= 1.0 else value, 1)
            except (TypeError, ValueError):
                continue
        return 50.0

    def calculate_team_power_curve(self, team_champions: list[str]) -> dict[str, float]:
        """Calcula la media de las curvas de win rate de los campeones del equipo.

        ``champions_strict.json`` almacena las curvas como una lista en
        ``win_rate_vs_game_length``. Conservamos compatibilidad con el formato
        antiguo de diccionario para los perfiles ya guardados.
        """
        curve_sums = {b: 0.0 for b in self.TIME_BRACKETS}
        counts = {b: 0 for b in self.TIME_BRACKETS}

        for champ in team_champions:
            prof = self.get_champion_profile(champ)
            if not prof:
                continue
            values_by_bracket: dict[str, Any] = {}
            current_format = prof.get("win_rate_vs_game_length", [])
            if isinstance(current_format, list):
                values_by_bracket = {
                    str(point.get("label", "")).replace("m", ""): point.get("winrate")
                    for point in current_format
                    if isinstance(point, dict)
                }
            else:
                legacy_format = prof.get("win_rate_by_game_length", {})
                if isinstance(legacy_format, dict):
                    values_by_bracket = legacy_format

            # Todos los campeones marcados o seleccionados pesan igual. Si a
            # un perfil le falta un tramo, 50% conserva su peso en la media.
            for bracket in self.TIME_BRACKETS:
                try:
                    value = float(values_by_bracket.get(bracket, 50.0))
                    if 0.0 <= value <= 1.0:  # fuentes que lo expresan como 0-1
                        value *= 100.0
                except (TypeError, ValueError):
                    value = 50.0
                curve_sums[bracket] += value
                counts[bracket] += 1

        result = {}
        for bracket in self.TIME_BRACKETS:
            if counts[bracket] > 0:
                result[bracket] = round(curve_sums[bracket] / counts[bracket], 2)
            else:
                result[bracket] = 50.0
        return result

    def analyze_power_spike_phase(self, my_curve: dict[str, float], enemy_curve: dict[str, float]) -> str:
        """Determina la ventana de Power Spike del equipo aliado en comparación con el enemigo."""
        diffs = {b: my_curve.get(b, 50.0) - enemy_curve.get(b, 50.0) for b in self.TIME_BRACKETS}
        early_diff = (diffs["0-15"] + diffs["15-20"]) / 2
        mid_diff = (diffs["20-25"] + diffs["25-30"] + diffs["30-35"]) / 3
        late_diff = (diffs["35-40"] + diffs["40+"]) / 2

        if early_diff >= mid_diff and early_diff >= late_diff and early_diff > 0.5:
            return f"Early Game (0-20 min) [Ventaja +{early_diff:.1f}%]"
        elif late_diff >= early_diff and late_diff >= mid_diff and late_diff > 0.5:
            return f"Late Game (35+ min) [Ventaja +{late_diff:.1f}%]"
        elif mid_diff > 0:
            return f"Mid Game (20-35 min) [Ventaja +{mid_diff:.1f}%]"
        else:
            return "Composición equilibrada / Escalado neutro"

    def get_recommended_bans(self, local_champion: str, top_n: int = 5) -> list[dict[str, Any]]:
        """Devuelve los peores counters para el campeón del jugador local."""
        prof = self.get_champion_profile(local_champion)
        if not prof:
            return []
        matchups = prof.get("matchups", {})
        counters = matchups.get("counters", [])
        if not isinstance(counters, list):
            return []

        # Ordenar por menor win_rate del jugador (mayor counter enemy)
        sorted_counters = sorted(
            [c for c in counters if isinstance(c, dict) and c.get("champion")],
            key=lambda x: float(x.get("win_rate", 0.5)),
        )

        results = []
        for c in sorted_counters[:top_n]:
            wr = float(c.get("win_rate", 0.5))
            if wr > 1.0:
                wr_pct = wr
            else:
                wr_pct = wr * 100
            results.append({
                "champion": c.get("champion"),
                "win_rate": round(wr_pct, 1),
                "games": c.get("lane_games") or c.get("overall_games", 0),
                "tip": c.get("tip", f"Counter severo para {local_champion}"),
            })
        return results

    def get_recommended_picks(
        self,
        assigned_role: str,
        enemy_champions: list[str],
        my_team_champions: list[str],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Recomienda campeones para el rol asignado según counters a los campeones enemigos fijados."""
        role_clean = assigned_role.capitalize()
        valid_enemies = [c for c in enemy_champions if c and c.casefold() in self.champions]

        candidates = []
        for name, prof in self.champions.items():
            binfo = prof.get("basic_info", {})
            flex = binfo.get("flex_potential", [])
            primary_role = binfo.get("primary_role", flex[0] if flex else "")
            
            # Filtrar por rol aproximado si se especificó
            if role_clean and role_clean not in flex and primary_role.casefold() != role_clean.casefold():
                continue

            champ_name = prof.get("character") or binfo.get("name") or name
            if champ_name in my_team_champions or champ_name in enemy_champions:
                continue

            # Calcular puntuación counter contra campeones enemigos conocidos
            counter_score = 0.0
            counter_details = []
            matchups = prof.get("matchups", {})
            easy_matchups = matchups.get("synergies") or matchups.get("easy_matchups") or []

            # Buscar en counters del enemigo
            for enemy in valid_enemies:
                e_prof = self.get_champion_profile(enemy)
                if not e_prof:
                    continue
                e_counters = e_prof.get("matchups", {}).get("counters", [])
                for ec in e_counters:
                    if isinstance(ec, dict) and str(ec.get("champion")).casefold() == champ_name.casefold():
                        # Si figura como counter del enemigo -> win_rate bajo del enemigo = alto para mi
                        e_wr = float(ec.get("win_rate", 0.5))
                        my_wr = (1.0 - e_wr) if e_wr <= 1.0 else (100.0 - e_wr)
                        counter_score += (my_wr - 50.0)
                        counter_details.append(f"Counter a {enemy}")

            base_wr = 50.0
            scaling = prof.get("power_curve_and_scaling", {})
            if isinstance(scaling, dict) and scaling.get("early_game"):
                base_wr += 1.0

            total_score = base_wr + counter_score
            candidates.append({
                "champion": champ_name,
                "score": round(total_score, 1),
                "role": primary_role or role_clean,
                "reason": ", ".join(counter_details) if counter_details else "Pick sólido para la composición",
            })

        return sorted(candidates, key=lambda x: x["score"], reverse=True)[:top_n]

    def get_champion_runes_and_summoners(self, champion_name: str) -> dict[str, Any]:
        """Devuelve las páginas de runas (Page 1 U.GG, Page 2 Lolalytics) y hechizos recomendados."""
        prof = self.get_champion_profile(champion_name)
        if not prof:
            return {
                "page_1": None,
                "page_2": None,
                "spells": ("Destello", "Teleportación"),
            }

        common_runes = prof.get("common_runes", [])
        page_1 = common_runes[0] if len(common_runes) > 0 else None
        page_2 = common_runes[1] if len(common_runes) > 1 else page_1

        # Hechizos recomendados por rol / perfil
        binfo = prof.get("basic_info", {})
        flex = binfo.get("flex_potential", [])
        primary_role = str(binfo.get("primary_role") or (flex[0] if flex else "")).capitalize()

        if primary_role == "Jungle":
            spells = ("Aplastar", "Destello")
        elif primary_role in ("Support", "Bot"):
            spells = ("Destello", "Extenuación") if primary_role == "Support" else ("Destello", "Curación")
        elif primary_role == "Mid":
            spells = ("Destello", "Ignición")
        else:
            spells = ("Destello", "Teleportación")

        return {
            "page_1": page_1,
            "page_2": page_2,
            "spells": spells,
        }
