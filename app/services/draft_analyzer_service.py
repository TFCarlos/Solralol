from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Iterable

from _paths import DATA_DIR


class DraftAnalyzerService:
    """Servicio de análisis en tiempo real para fase de Draft (Champ Select)."""

    TIME_BRACKETS = ["0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40+"]

    # Líneas del draft en el orden que usa la herramienta.
    ROLES = ("Top", "Jungle", "Mid", "Bot", "Support")

    # Peso de cada línea según su posición entre los roles habituales del
    # campeón: la primera es su línea natural y el resto, alternativas.
    ROLE_CONFIDENCE = (1.0, 0.6, 0.4, 0.25, 0.15)

    # Mismas cuatro categorías y mismo orden que la tarjeta SITUACIONALES del
    # analizador local, para que la build importada y la vista coincidan.
    SITUATIONAL_CATEGORIES = (
        ("corta_curas", "Corta curas"),
        ("tanque", "Tanque / Resistencias"),
        ("asesino", "Asesino / Daño explosivo"),
        ("utilidad_y_defensa", "Utilidad y Defensa"),
    )

    def __init__(self, champions_strict_path: Path | None = None) -> None:
        self.path = champions_strict_path or DATA_DIR / "champions_strict.json"
        self.champions: dict[str, dict[str, Any]] = {}
        self.champ_by_id: dict[int, str] = {}
        self._load_data()
        self.version = "16.17.1"
        try:
            raw_items = json.loads((self.path.parent / "items.json").read_text(encoding="utf-8"))
            self.items = raw_items.get("items", {})
            self.version = str(raw_items.get("version") or self.version)
        except (OSError, ValueError):
            self.items = {}
        self.item_names = {}
        for item_id, item in self.items.items():
            if item.get("maps", {}).get("11", True) and not item.get("requiredAlly"):
                for key in ("name", "name_es", "name_en"):
                    if item.get(key):
                        self.item_names.setdefault(item[key].strip().casefold(), item_id)

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

    def assign_likely_roles(self, champion_names: list[str],
                            exclude: Iterable[str] = ()) -> list[str]:
        """Reparte las líneas entre los campeones: la hipótesis que mejor encaja.

        Durante el draft no se conoce la línea real de nadie (el cliente solo
        publica la posición asignada de los aliados y a veces ni eso), así que en
        lugar de afirmar una línea se propone la combinación **sin repeticiones**
        que maximiza la confianza con los roles habituales de cada campeón.

        Ante empates manda el orden recibido: el primer campeón conserva su línea
        natural antes que los siguientes. Un campeón sin datos de rol recibe una
        cadena vacía, porque de él no se puede decir nada; ``exclude`` reserva
        las líneas que ya están ocupadas (por ejemplo, las que sí publicó LCU).
        """
        candidates = [role for role in self.ROLES if role not in exclude]
        likely = [self.get_likely_roles(name) for name in champion_names]
        # Solo entran campeones y líneas con algún encaje posible: el resto no
        # altera el resultado y encarece la búsqueda.
        known = [
            index for index, roles in enumerate(likely)
            if any(self._role_confidence(roles, role) > 0 for role in candidates)
        ]
        candidates = [
            role for role in candidates
            if any(self._role_confidence(roles, role) > 0 for roles in likely)
        ]
        assignment = [""] * len(champion_names)
        if not known or not candidates:
            return assignment
        best_score: tuple[float, ...] = ()
        best_roles: dict[int, str] = {}
        # Se prueban todos los repartos parciales: un campeón puede quedarse sin
        # línea (nadie recibe una que no juega) y cada línea se usa una sola vez.
        for count in range(min(len(known), len(candidates)), -1, -1):
            for champions in itertools.combinations(known, count):
                for roles in itertools.permutations(candidates, count):
                    chosen = dict(zip(champions, roles))
                    scores = tuple(
                        self._role_confidence(likely[index], chosen[index])
                        if index in chosen else 0.0
                        for index in known
                    )
                    # Primero el total; después, menos líneas inventadas; y en
                    # empate, el orden recibido: el primer campeón conserva su
                    # línea natural antes que los siguientes.
                    score = (sum(scores), -count, *scores)
                    if score > best_score:
                        best_score, best_roles = score, chosen
        for champion, role in best_roles.items():
            assignment[champion] = role
        return assignment

    @classmethod
    def _role_confidence(cls, likely_roles: list[str], role: str) -> float:
        """Confianza de una línea para un campeón; 0 si no es uno de sus roles."""
        if role not in likely_roles:
            return 0.0
        index = likely_roles.index(role)
        if index < len(cls.ROLE_CONFIDENCE):
            return cls.ROLE_CONFIDENCE[index]
        return cls.ROLE_CONFIDENCE[-1]

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
            breakdown = prof.get("damage_breakdown", {})
            dmg_prof = {
                key: breakdown[f"{key}_percent"]
                for key in ("physical_damage", "magic_damage", "true_damage")
                if f"{key}_percent" in breakdown
            } or prof.get("damage_profile", {})
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

            if not values_by_bracket:
                # Sin datos de curva el campeón no participa en la media:
                # contarle como 50% aplana la evolución del equipo.
                continue

            # Todos los campeones con datos pesan igual. Si a un perfil
            # le falta un tramo, 50% conserva su peso en la media.
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

    def get_recommended_bans(self, local_champion: str, top_n: int = 3) -> list[dict[str, Any]]:
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

    def get_champion_runes_and_summoners(self, champion_name: str, role: str = "") -> dict[str, Any]:
        """No atribuye una página a otra fuente. El rol activo manda sobre el perfil."""
        prof = self.get_champion_profile(champion_name) or {}
        pages = prof.get("common_runes") or prof.get("runes") or []
        sources = {str(p.get("source", "")).casefold(): p for p in pages if isinstance(p, dict)}
        roles = self.get_likely_roles(champion_name)
        role = (role or (roles[0] if roles else "Top")).casefold()
        fallback = {"support": "Extenuación", "bot": "Curación", "mid": "Ignición"}.get(role, "Teleportación")
        spells = list(prof.get("summoner_spells") or ["Destello", fallback])[:2]
        if len(spells) != 2 or not all(isinstance(s, str) for s in spells):
            spells = ["Destello", fallback]
        smite = {"smite", "aplastar"}
        if role in {"jungle", "jungla", "jgl"}:
            first = next((s for s in spells if s.casefold() not in smite), "Destello")
            spells = [first, "Aplastar"]
        else:
            spells = [fallback if s.casefold() in smite else s for s in spells]
            if spells[0].casefold() == spells[1].casefold():
                spells = ["Destello", fallback]
        return {"page_1": sources.get("u.gg"), "page_2": sources.get("lolalytics"), "spells": tuple(spells)}

    def get_situational_items(self, champion_name: str) -> list[dict[str, Any]]:
        """Opciones situacionales del campeón por categoría, ya resueltas a objetos.

        Devuelve la misma información que la tarjeta SITUACIONALES del analizador
        local: las cuatro categorías conocidas en orden, y dentro de cada una los
        objetos comprables del campeón. Se omiten botas y nombres sin resolver en
        el catálogo para no inventar compras.
        """
        prof = self.get_champion_profile(champion_name) or {}
        situational = prof.get("situational_items", {})
        if not isinstance(situational, dict):
            return []
        groups: list[dict[str, Any]] = []
        for cat_key, cat_label in self.SITUATIONAL_CATEGORIES:
            names = situational.get(cat_key, [])
            if not isinstance(names, list):
                continue
            items: list[dict[str, str]] = []
            seen: set[str] = set()
            for name in names:
                item_id = self.item_names.get(str(name).strip().casefold(), "")
                item = self.items.get(item_id, {})
                if not item or item_id in seen or "Boots" in item.get("tags", []):
                    continue
                seen.add(item_id)
                items.append({"id": item_id, "name": item.get("name", item_id)})
            if items:
                groups.append({"key": cat_key, "label": cat_label, "items": items})
        return groups

    def get_champion_build(self, champion_name: str, enemies: list[str]) -> dict[str, Any]:
        """Seis compras principales y botas aparte; la sexta puede ser alternativa tardía."""
        prof = self.get_champion_profile(champion_name) or {}
        core = []
        boots_id = ""
        unresolved = []
        for name in prof.get("most_played_build", []):
            item_id = self.item_names.get(str(name).strip().casefold(), "")
            item = self.items.get(item_id, {})
            if not item:
                unresolved.append(str(name))
            elif "Boots" in item.get("tags", []):
                boots_id = item_id
            elif item_id not in core:
                core.append(item_id)
        main_count = len(core)
        # Alternativas situacionales del campeón, sin objetos inventados: se usan
        # para completar el núcleo y además viajan a la build importada.
        situational = self.get_situational_items(champion_name)
        for group in situational:
            for item in group["items"]:
                if item["id"] not in core:
                    core.append(item["id"])
        known_enemies = [e for e in enemies if self.get_champion_profile(e)]
        damage = self.calculate_team_damage_breakdown(known_enemies)
        if not known_enemies:
            reason = "Sin enemigos conocidos: botas de la build del campeón."
        elif damage["true"] > max(damage["physical"], damage["magic"]):
            reason = f"Daño verdadero predominante ({damage['true']:.1f}%): las resistencias no lo reducen; se conservan las botas de la build."
        elif damage["physical"] == damage["magic"]:
            reason = "Daño físico y mágico equilibrado: se conservan las botas de la build."
        elif damage["magic"] > damage["physical"]:
            boots_id = "3111"
            reason = f"Daño mágico predominante ({damage['magic']:.1f}%): resistencia mágica y tenacidad."
        else:
            boots_id = "3047"
            reason = f"Daño físico predominante ({damage['physical']:.1f}%): armadura y reducción de ataques básicos."
        if champion_name.casefold() == "cassiopeia":
            boots_id = ""
            reason = "Cassiopeia no puede comprar botas."
        def describe(item_id: str) -> dict[str, str]:
            return {"id": item_id, "name": self.items[item_id].get("name", item_id)}
        return {
            "items": [describe(i) for i in core[:6]],
            "boots": describe(boots_id) if boots_id in self.items else None,
            "boots_reason": reason,
            "note": "La sexta compra es una alternativa tardía; solo hay 6 huecos de inventario." if main_count < 6 and len(core) >= 6 else "",
            "unresolved": unresolved,
            "situational": situational,
            "champion_id": next((i for i, name in self.champ_by_id.items() if name.casefold() == champion_name.casefold()), 0),
        }
