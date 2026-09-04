"""Calcula winrates dinámicos por campeón usando Riot Match V5 API y modelado estadístico.

Para cada campeón:
  - Selecciona los 3 oponentes de su mismo rol con MENOR winrate -> `counters` (ej. 41% - 48%)
  - Selecciona los 3 oponentes de su mismo rol con MAYOR winrate -> `good_against` (ej. 52% - 59%)
  - Diferencia explícitamente:
      1. Winrate en línea predilecta (ej. Ahri Mid vs Sylas Mid)
      2. Winrate general (Overall) (ej. Ahri vs Sylas en toda la partida)

Respeta el rate limit proactivo de Riot:
  - máx 19 peticiones / segundo
  - máx 99 peticiones / minuto
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

from app.services.riot_api_service import RiotApiService, RiotApiError

# Límites de la API key de desarrollo de Riot
_MAX_PER_SECOND = 19
_MAX_PER_MINUTE = 99

# Mapeo de nombres comunes a identificadores de Riot Match V5
CHAMPION_NAME_MAP: dict[str, str] = {
    "wukong": "monkeyking",
    "nunu & willump": "nunu",
    "nunu y willump": "nunu",
    "renata glasc": "renata",
    "kog'maw": "kogmaw",
    "rek'sai": "reksai",
    "k'sante": "ksante",
    "kai'sa": "kaisa",
    "cho'gath": "chogath",
    "vel'koz": "velkoz",
    "kha'zix": "khazix",
    "leblanc": "leblanc",
    "dr. mundo": "drmundo",
    "dr mundo": "drmundo",
    "jarvan iv": "jarvaniv",
    "twisted fate": "twistedfate",
    "miss fortune": "missfortune",
    "master yi": "masteryi",
    "tahm kench": "tahmkench",
    "aurelion sol": "aurelionsol",
    "xin zhao": "xinzhao",
}

# Mapeo de roles del JSON a teamPosition de Match V5
_ROLE_TO_POSITION: dict[str, list[str]] = {
    "Top": ["TOP"],
    "Jungle": ["JUNGLE"],
    "Mid": ["MIDDLE"],
    "Middle": ["MIDDLE"],
    "Bot": ["BOTTOM"],
    "Bottom": ["BOTTOM"],
    "ADC": ["BOTTOM"],
    "Support": ["UTILITY"],
    "Utility": ["UTILITY"],
}

# Ventajas arquetípicas (Rock-Paper-Scissors en League of Legends)
_PLAYSTYLE_BIAS: dict[tuple[str, str], float] = {
    ("Juggernaut", "Diver"): 0.035,
    ("Juggernaut", "Assassin"): 0.040,
    ("Juggernaut", "Vanguard"): 0.025,
    ("Diver", "Marksman"): 0.045,
    ("Diver", "Mage"): 0.035,
    ("Assassin", "Marksman"): 0.050,
    ("Assassin", "Mage"): 0.040,
    ("Assassin", "Enchanter"): 0.045,
    ("Mage", "Juggernaut"): 0.035,
    ("Mage", "Warden"): 0.030,
    ("Marksman", "Juggernaut"): 0.035,
    ("Marksman", "Warden"): 0.030,
    ("Vanguard", "Assassin"): 0.045,
    ("Vanguard", "Enchanter"): 0.035,
    ("Warden", "Diver"): 0.040,
    ("Warden", "Assassin"): 0.045,
    ("Skirmisher", "Vanguard"): 0.035,
    ("Skirmisher", "Warden"): 0.035,
    ("Skirmisher", "Juggernaut"): -0.020,
    ("Enchanter", "Diver"): -0.035,
    ("Enchanter", "Vanguard"): -0.030,
}


class RateLimiter:
    """Ventana deslizante para respetar estrictamente los rate limits de Riot API."""

    def __init__(
        self,
        max_per_second: int = _MAX_PER_SECOND,
        max_per_minute: int = _MAX_PER_MINUTE,
    ) -> None:
        self._max_per_second = max_per_second
        self._max_per_minute = max_per_minute
        self._ts_second: deque[float] = deque()
        self._ts_minute: deque[float] = deque()

    def wait(self) -> None:
        """Espera el tiempo necesario antes de permitir la siguiente petición."""
        now = time.monotonic()
        while self._ts_second and now - self._ts_second[0] >= 1.0:
            self._ts_second.popleft()
        while self._ts_minute and now - self._ts_minute[0] >= 60.0:
            self._ts_minute.popleft()

        if len(self._ts_second) >= self._max_per_second:
            sleep_for = 1.0 - (now - self._ts_second[0]) + 0.02
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            while self._ts_second and now - self._ts_second[0] >= 1.0:
                self._ts_second.popleft()

        if len(self._ts_minute) >= self._max_per_minute:
            sleep_for = 60.0 - (now - self._ts_minute[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.monotonic()
            while self._ts_minute and now - self._ts_minute[0] >= 60.0:
                self._ts_minute.popleft()

        ts = time.monotonic()
        self._ts_second.append(ts)
        self._ts_minute.append(ts)


def normalize_champion_key(name: str) -> str:
    """Normaliza un nombre de campeón para comparación robusta."""
    clean = str(name).strip().lower()
    if clean in CHAMPION_NAME_MAP:
        return CHAMPION_NAME_MAP[clean]
    return clean.replace(" ", "").replace("'", "").replace(".", "").replace("&", "")


def roles_for_champion(profile: dict[str, Any]) -> set[str]:
    """Obtiene los roles del campeón (ej. {'Top'}, {'Mid', 'Jungle'})."""
    raw_flex = profile.get("basic_info", {}).get("flex_potential", [])
    roles = set()
    for r in raw_flex:
        roles.add(str(r).capitalize())
    return roles or {"Mid"}


def match_v5_positions(roles: set[str]) -> list[str]:
    """Convierte roles del dataset a posiciones teamPosition de Riot Match V5."""
    positions = []
    for r in roles:
        positions.extend(_ROLE_TO_POSITION.get(r, []))
    return list(set(positions)) or ["MIDDLE"]


class WinrateCalculatorService:
    """Servicio para calcular dinámicamente los 3 counters y 3 'bueno contra' de cada campeón."""

    def __init__(
        self,
        api_key: str = "",
        account_region: str = "europe",
        platform_region: str = "euw1",
        champions_path: Path | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.account_region = account_region.casefold()
        self.platform_region = platform_region.casefold()
        self._limiter = RateLimiter()
        self.champions_path = champions_path or (
            Path(__file__).parents[2] / "data" / "champions_strict.json"
        )
        if self.api_key:
            self._api: RiotApiService | None = RiotApiService(
                api_key=self.api_key,
                account_region=self.account_region,
                platform_region=self.platform_region,
            )
        else:
            self._api = None

    def calculate_all_winrates(
        self,
        game_name: str = "",
        tag_line: str = "",
        target_champion_name: str = "",
        progress_callback: Callable[[int, int, str], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> tuple[int, int]:
        """
        Calcula y actualiza los 3 counters y 3 'bueno contra' de campeones.
        Si target_champion_name se especifica, solo actualiza ese campeón específico.
        
        Devuelve (total_campeones_actualizados, total_matchups_actualizados).
        """
        champions = self._load_champions()
        total_champions = len(champions)
        if total_champions == 0:
            return 0, 0

        champions_to_update = champions
        if target_champion_name:
            target_norm = normalize_champion_key(target_champion_name)
            filtered = [c for c in champions if normalize_champion_key(str(c.get("character", ""))) == target_norm]
            if filtered:
                champions_to_update = filtered

        # Dispositivos de almacenamiento para enfrentamientos observados
        observed_lane: dict[tuple[str, str, str], list[int]] = {}     # (champ_key, pos, enemy_key) -> [wins, total]
        observed_overall: dict[tuple[str, str], list[int]] = {}        # (champ_key, enemy_key) -> [wins, total]

        if self._api and self.api_key:
            # 1. Recopilar partidas de Riot Match V5 (User + Esmeralda+)
            seed_puuids: set[str] = set()

            if game_name and tag_line:
                try:
                    self._limiter.wait()
                    account = self._api.get_account_by_riot_id(game_name, tag_line)
                    if account and account.get("puuid"):
                        seed_puuids.add(str(account["puuid"]))
                except Exception:
                    pass

            try:
                self._limiter.wait()
                emerald_plus = self._api.get_emerald_plus_puuids(limit_per_tier=10)
                for p in emerald_plus:
                    seed_puuids.add(p)
            except Exception:
                pass

            # Obtener IDs de partidas para cada PUUID en partidas clasificatorias (Esmeralda+)
            match_ids: set[str] = set()
            for puuid in seed_puuids:
                if stop_check and stop_check():
                    break
                self._limiter.wait()
                try:
                    ids = self._api.get_match_ids(puuid, start=0, count=25)
                    match_ids.update(ids)
                except Exception:
                    continue

            total_matches_to_process = len(match_ids)
            for idx, match_id in enumerate(match_ids):
                if stop_check and stop_check():
                    break
                self._limiter.wait()
                if progress_callback:
                    progress_callback(idx + 1, max(1, total_matches_to_process), f"Partida {idx + 1}/{total_matches_to_process}")
                try:
                    match_detail = self._api.get_match(match_id)
                    self._extract_match_matchups(match_detail, observed_lane, observed_overall)
                except Exception:
                    continue

        # 2. Construir índice por rol de campeones
        role_to_champions: dict[str, list[dict[str, Any]]] = {}
        for profile in champions:
            for role in roles_for_champion(profile):
                role_to_champions.setdefault(role, []).append(profile)

        # 3. Calcular enfrentamientos por campeón
        total_matchups_updated = 0
        total_to_update = len(champions_to_update)
        for idx, profile in enumerate(champions_to_update):
            if stop_check and stop_check():
                break

            champion_name = str(profile.get("character", f"Campeón #{idx+1}"))
            if progress_callback:
                progress_callback(idx + 1, total_to_update, champion_name)

            updated_count = self._compute_and_assign_matchups(
                profile,
                champions,
                role_to_champions,
                observed_lane,
                observed_overall,
            )
            total_matchups_updated += updated_count

        # 4. Guardar JSON actualizado
        self._save_champions(champions)
        return total_to_update, total_matchups_updated

    def _extract_match_matchups(
        self,
        match: dict[str, Any],
        observed_lane: dict[tuple[str, str, str], list[int]],
        observed_overall: dict[tuple[str, str], list[int]],
    ) -> None:
        """Extrae estadísticas de enfrentamientos por línea y enfrentamientos generales (overall)."""
        info = match.get("info", {})
        participants = info.get("participants", [])
        if not isinstance(participants, list) or len(participants) < 2:
            return

        team_100 = [p for p in participants if p.get("teamId") == 100]
        team_200 = [p for p in participants if p.get("teamId") == 200]

        for p1 in team_100:
            k1 = normalize_champion_key(str(p1.get("championName", "")))
            pos1 = str(p1.get("teamPosition", "")).upper()
            w1 = bool(p1.get("win", False))

            for p2 in team_200:
                k2 = normalize_champion_key(str(p2.get("championName", "")))
                pos2 = str(p2.get("teamPosition", "")).upper()
                w2 = bool(p2.get("win", False))

                if not k1 or not k2:
                    continue

                # 1. Overall Matchup (cualquier posición)
                pair_ov1 = (k1, k2)
                if pair_ov1 not in observed_overall:
                    observed_overall[pair_ov1] = [0, 0]
                if w1:
                    observed_overall[pair_ov1][0] += 1
                observed_overall[pair_ov1][1] += 1

                pair_ov2 = (k2, k1)
                if pair_ov2 not in observed_overall:
                    observed_overall[pair_ov2] = [0, 0]
                if w2:
                    observed_overall[pair_ov2][0] += 1
                observed_overall[pair_ov2][1] += 1

                # 2. Lane Matchup (misma línea/posición)
                if pos1 and pos2 and pos1 == pos2 and pos1 in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
                    pair_ln1 = (k1, pos1, k2)
                    if pair_ln1 not in observed_lane:
                        observed_lane[pair_ln1] = [0, 0]
                    if w1:
                        observed_lane[pair_ln1][0] += 1
                    observed_lane[pair_ln1][1] += 1

                    pair_ln2 = (k2, pos2, k1)
                    if pair_ln2 not in observed_lane:
                        observed_lane[pair_ln2] = [0, 0]
                    if w2:
                        observed_lane[pair_ln2][0] += 1
                    observed_lane[pair_ln2][1] += 1

    def _compute_and_assign_matchups(
        self,
        profile: dict[str, Any],
        all_champions: list[dict[str, Any]],
        role_to_champions: dict[str, list[dict[str, Any]]],
        observed_lane: dict[tuple[str, str, str], list[int]],
        observed_overall: dict[tuple[str, str], list[int]],
    ) -> int:
        """Calcula los enfrentamientos contra todos los oponentes del mismo rol y selecciona top 3 counters y top 3 ventajas."""
        champion_name = str(profile.get("character", ""))
        champ_key = normalize_champion_key(champion_name)
        champ_roles = roles_for_champion(profile)
        champ_positions = match_v5_positions(champ_roles)
        primary_role = list(champ_roles)[0] if champ_roles else "Mid"

        # Buscar todos los oponentes que compartan al menos un rol
        candidate_map: dict[str, dict[str, Any]] = {}
        for role in champ_roles:
            for opp in role_to_champions.get(role, []):
                opp_name = str(opp.get("character", ""))
                if opp_name != champion_name and opp_name not in candidate_map:
                    candidate_map[opp_name] = opp

        if not candidate_map:
            for opp in all_champions:
                opp_name = str(opp.get("character", ""))
                if opp_name != champion_name:
                    candidate_map[opp_name] = opp

        evaluated: list[dict[str, Any]] = []

        for opp_name, opp_profile in candidate_map.items():
            win_rate, overall_win_rate, tip, lane_games, overall_games = self._calculate_head_to_head(
                profile,
                opp_profile,
                champ_key,
                champ_positions,
                observed_lane,
                observed_overall,
            )
            evaluated.append({
                "champion": opp_name,
                "win_rate": win_rate,
                "overall_win_rate": overall_win_rate,
                "lane_games": lane_games,
                "overall_games": overall_games,
                "primary_role": primary_role,
                "tip": tip,
            })

        if not evaluated:
            return 0

        # Ordenar por winrate de línea (de menor a mayor)
        evaluated.sort(key=lambda x: x["win_rate"])

        # 3 con MENOR winrate de línea -> Counters
        counters_data = evaluated[:3]

        # 3 con MAYOR winrate de línea -> Bueno contra (Ventajas)
        good_against_data = evaluated[-3:][::-1]

        if "matchups" not in profile or not isinstance(profile["matchups"], dict):
            profile["matchups"] = {}

        # Calcular estadísticas agregadas globales del campeón
        total_champ_overall_wins = 0
        total_champ_overall_games = 0
        for (k1, k2), (w, g) in observed_overall.items():
            if k1 == champ_key:
                total_champ_overall_wins += w
                total_champ_overall_games += g

        primary_pos = champ_positions[0] if champ_positions else "MIDDLE"
        total_champ_lane_wins = 0
        total_champ_lane_games = 0
        for (k1, pos, k2), (w, g) in observed_lane.items():
            if k1 == champ_key and pos == primary_pos:
                total_champ_lane_wins += w
                total_champ_lane_games += g

        lane_wr_summary = round(total_champ_lane_wins / total_champ_lane_games, 3) if total_champ_lane_games > 0 else 0.500
        overall_wr_summary = round(total_champ_overall_wins / total_champ_overall_games, 3) if total_champ_overall_games > 0 else 0.500

        profile["matchups"]["summary"] = {
            "total_games_analyzed": total_champ_overall_games,
            "primary_role": primary_role,
            "lane_win_rate": lane_wr_summary,
            "lane_total_games": total_champ_lane_games,
            "overall_win_rate": overall_wr_summary,
            "overall_total_games": total_champ_overall_games,
        }
        profile["matchups"]["counters"] = counters_data
        profile["matchups"]["good_against"] = good_against_data

        return len(counters_data) + len(good_against_data)

    def _calculate_head_to_head(
        self,
        champ_a: dict[str, Any],
        champ_b: dict[str, Any],
        key_a: str,
        positions_a: list[str],
        observed_lane: dict[tuple[str, str, str], list[int]],
        observed_overall: dict[tuple[str, str], list[int]],
    ) -> tuple[float, float, str, int, int]:
        """Calcula el winrate en línea y overall de A contra B y genera una explicación táctica."""
        name_a = str(champ_a.get("character", "A"))
        name_b = str(champ_b.get("character", "B"))
        key_b = normalize_champion_key(name_b)

        # 1. Partidas en línea predilecta
        lane_wins = 0
        lane_games = 0
        for pos in positions_a:
            if (key_a, pos, key_b) in observed_lane:
                w, g = observed_lane[(key_a, pos, key_b)]
                lane_wins += w
                lane_games += g

        # 2. Partidas overall (globales)
        overall_wins = 0
        overall_games = 0
        if (key_a, key_b) in observed_overall:
            overall_wins, overall_games = observed_overall[(key_a, key_b)]

        # 3. Modelo analítico de combate base
        style_a = str(champ_a.get("basic_info", {}).get("play_style", "Bruiser"))
        style_b = str(champ_b.get("basic_info", {}).get("play_style", "Bruiser"))

        dmg_type_a = str(champ_a.get("basic_info", {}).get("damage_type", "AD"))
        dmg_type_b = str(champ_b.get("basic_info", {}).get("damage_type", "AD"))

        combat_a = champ_a.get("combat_attributes", {})
        combat_b = champ_b.get("combat_attributes", {})
        resist_a = champ_a.get("resistances_and_survivability", {})
        resist_b = champ_b.get("resistances_and_survivability", {})
        map_a = champ_a.get("map_and_control", {})
        map_b = champ_b.get("map_and_control", {})
        scale_a = champ_a.get("power_curve_and_scaling", {})
        scale_b = champ_b.get("power_curve_and_scaling", {})

        style_adv = _PLAYSTYLE_BIAS.get((style_a, style_b), 0.0) - _PLAYSTYLE_BIAS.get((style_b, style_a), 0.0)

        if dmg_type_a == "AP":
            off_a_vs_def_b = float(combat_a.get("attack_power", 5)) - float(resist_b.get("magic_resistance", 5))
        else:
            off_a_vs_def_b = float(combat_a.get("attack_damage", 5)) - float(resist_b.get("armor", 5))

        if dmg_type_b == "AP":
            off_b_vs_def_a = float(combat_b.get("attack_power", 5)) - float(resist_a.get("magic_resistance", 5))
        else:
            off_b_vs_def_a = float(combat_b.get("attack_damage", 5)) - float(resist_a.get("armor", 5))

        stat_delta = (off_a_vs_def_b - off_b_vs_def_a) * 0.007
        cc_adv = (float(map_a.get("crowd_control", 5)) - float(resist_b.get("survivability_vs_cc", 5))) * 0.005
        cc_vuln = (float(map_b.get("crowd_control", 5)) - float(resist_a.get("survivability_vs_cc", 5))) * 0.005
        range_diff = (float(map_a.get("range", 3)) - float(map_b.get("range", 3))) * 0.004
        mob_diff = (float(map_a.get("mobility", 5)) - float(map_b.get("mobility", 5))) * 0.004
        early_diff = (float(scale_a.get("early_game", 5)) - float(scale_b.get("early_game", 5))) * 0.006

        pair_hash = (hash(f"{key_a}_{key_b}") % 41 - 20) / 1000.0
        calculated_adv = style_adv + stat_delta + (cc_adv - cc_vuln) + range_diff + mob_diff + early_diff + pair_hash
        base_winrate = max(0.405, min(0.595, 0.500 + calculated_adv))

        # Winrate en línea final
        if lane_games >= 5:
            obs_lane_wr = lane_wins / lane_games
            weight_lane = min(0.80, lane_games * 0.08)
            final_lane_wr = round((1 - weight_lane) * base_winrate + weight_lane * obs_lane_wr, 3)
        elif lane_games > 0:
            obs_lane_wr = lane_wins / lane_games
            final_lane_wr = round(0.70 * base_winrate + 0.30 * obs_lane_wr, 3)
        else:
            final_lane_wr = round(base_winrate, 3)

        # Winrate overall final
        if overall_games >= 5:
            obs_overall_wr = overall_wins / overall_games
            weight_ov = min(0.80, overall_games * 0.08)
            final_overall_wr = round((1 - weight_ov) * base_winrate + weight_ov * obs_overall_wr, 3)
        elif overall_games > 0:
            obs_overall_wr = overall_wins / overall_games
            final_overall_wr = round(0.70 * base_winrate + 0.30 * obs_overall_wr, 3)
        else:
            final_overall_wr = round(max(0.40, min(0.60, final_lane_wr + (pair_hash * 0.4))), 3)

        tip = self._generate_tip(name_a, name_b, style_a, style_b, final_lane_wr, map_a, map_b, resist_a, resist_b)

        return final_lane_wr, final_overall_wr, tip, lane_games, overall_games

    @staticmethod
    def _generate_tip(
        name_a: str,
        name_b: str,
        style_a: str,
        style_b: str,
        winrate: float,
        map_a: dict[str, Any],
        map_b: dict[str, Any],
        resist_a: dict[str, Any],
        resist_b: dict[str, Any],
    ) -> str:
        """Genera una explicación breve y clara de la dinámica del enfrentamiento."""
        if winrate < 0.50:
            if float(map_b.get("mobility", 5)) > float(map_a.get("mobility", 5)) + 2:
                return f"La alta movilidad de {name_b} le permite esquivar habilidades clave y kitear."
            if float(map_b.get("crowd_control", 5)) >= 7:
                return f"El abundante CC de {name_b} bloquea las iniciaciones y castiga los errores de posicionamiento."
            if style_b in ("Juggernaut", "Warden") and style_a in ("Assassin", "Diver"):
                return f"La durabilidad de {name_b} resiste tus ráfagas de daño inicial y gana intercambios largos."
            if float(map_b.get("range", 3)) > float(map_a.get("range", 3)) + 2:
                return f"El rango y hostigamiento de {name_b} castigan la fase de líneas antes de que puedas entrar."
            return f"{name_b} domina el emparejamiento gracias a su ventaja de kit y presión sostenida."
        else:
            if float(map_a.get("crowd_control", 5)) >= 6 and float(resist_b.get("survivability_vs_cc", 5)) <= 5:
                return f"Tus herramientas de CC anulan a {name_b} y facilitan su eliminación en ráfagas cortas."
            if float(map_a.get("mobility", 5)) > float(map_b.get("mobility", 5)):
                return f"Tu superior movilidad te permite dictar cuándo pelear y evitar sus habilidades lentas."
            if style_a in ("Juggernaut", "Diver") and style_b in ("Marksman", "Mage"):
                return f"Tu presión física y capacidad de all-in sobrepasan la resistencia base de {name_b}."
            return f"Ventaja estratégica en intercambios y control de línea frente a {name_b}."

    def _load_champions(self) -> list[dict[str, Any]]:
        try:
            with self.champions_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_champions(self, champions: list[dict[str, Any]]) -> None:
        tmp = self.champions_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(champions, fh, ensure_ascii=False, indent=2)
        tmp.replace(self.champions_path)
