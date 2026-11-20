from __future__ import annotations

import itertools
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from _paths import DATA_DIR
from app.services.storage_manager import get_storage_manager
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.champion_variant_service import ChampionVariantService
from app.services.curador_recomendaciones_build import CuradorRecomendacionesBuild
from app.services.repositorio_campeones import RepositorioCampeones
from app.services.identidad_campeon import cargar_indice_campeones
from app.services.synergy_recommendation_service import SynergyRecommendationService


class DraftAnalyzerService:
    """Servicio de análisis en tiempo real para fase de Draft (Champ Select)."""

    TIME_BRACKETS = ("0-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40+")

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

    def __init__(
        self,
        ruta_campeones: Path | None = None,
        perfiles: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        """Inicializa perfiles y catálogos locales.

        Parámetros: raíz de campeones opcional y perfiles de prueba opcionales.
        Retorno: None; prepara índices, variantes y curador sin acceso remoto.
        """
        self.path = ruta_campeones or (get_storage_manager().cache_dir / "champions")
        self.identities = cargar_indice_campeones(self.path.parent / "champion_catalog.json")
        self.champions: dict[str, dict[str, Any]] = {}
        self.profiles_by_id: dict[str, dict[str, Any]] = {}
        self.resolved_profiles: dict[tuple[str, str], dict[str, Any]] = {}
        self.champ_by_id: dict[int, str] = {}
        if perfiles is None:
            self._load_data()
        else:
            self.champions = {
                str(perfil.get("character", "")).casefold(): perfil
                for perfil in perfiles
                if perfil.get("character")
            }
        for profile in self.champions.values():
            champion_id = self.identities.resolve(profile.get("character"))
            if champion_id:
                self.profiles_by_id[champion_id] = profile
        self.version = "16.17.1"
        try:
            raw_items = json.loads(
                ((self.path.parent / "items.json") if (self.path.parent / "items.json").is_file() else (DATA_DIR / "items.json")).read_text(encoding="utf-8")
            )
            self.items = raw_items.get("items", {})
            self.version = str(raw_items.get("version") or self.version)
        except (OSError, ValueError):
            self.items = {}
        try:
            objetos_estrictos = json.loads(
                (((self.path.parent / "legendary_items_strict.json") if (self.path.parent / "legendary_items_strict.json").is_file() else (DATA_DIR / "legendary_items_strict.json")).read_text(
                    encoding="utf-8"
                ))
            )
        except (OSError, ValueError):
            objetos_estrictos = []
        self.variantes = ChampionVariantService(self.path)
        catalogo = CatalogoAnalisisLocal(
            self.items,
            objetos_estrictos,
            SynergyRecommendationService.ITEM_NAME_ALIASES,
            self.version,
        )
        self.curador = CuradorRecomendacionesBuild(
            catalogo,
            {
                str(objeto.get("id")): objeto
                for objeto in objetos_estrictos
                if isinstance(objeto, dict) and objeto.get("id")
            },
        )
        self.item_names = {}
        for item_id, item in self.items.items():
            if item.get("maps", {}).get("11", True) and not item.get("requiredAlly"):
                for key in ("name", "name_es", "name_en"):
                    if item.get(key):
                        self.item_names.setdefault(
                            item[key].strip().casefold(), item_id
                        )

    def _load_data(self) -> None:
        """Carga perfiles del repositorio y correspondencias de Data Dragon; retorna None."""
        for entry in RepositorioCampeones(self.path).perfiles_globales():
            name = entry.get("character")
            if name:
                self.champions[name.casefold()] = entry

        catalog_path = self.path.parent / "champion_catalog.json"
        if not catalog_path.is_file():
            catalog_path = DATA_DIR / "champion_catalog.json"
        if catalog_path.exists():
            try:
                cat = json.loads(catalog_path.read_text(encoding="utf-8"))
                for c_info in cat.get("data", {}).values():
                    key_str = c_info.get("key")
                    c_name = c_info.get("name")
                    if key_str and c_name:
                        self.champ_by_id[int(key_str)] = c_name
            except (TypeError, ValueError):
                self.champ_by_id.clear()

    def get_champion_name_by_id(self, champ_id: int) -> str:
        return self.champ_by_id.get(champ_id, "")

    def get_champion_profile(self, champion_name: str, role: str | None = None) -> dict[str, Any] | None:
        champion_id = self.identities.resolve(champion_name)
        if not champion_id:
            return self.champions.get(str(champion_name).casefold())
        role_key = {"bot": "adc", "bottom": "adc", "middle": "mid", "utility": "support"}.get(str(role or "").casefold(), str(role or "").casefold())
        cache_key = (champion_id, role_key)
        cached = self.resolved_profiles.get(cache_key)
        if cached is not None:
            return cached
        profile = self.profiles_by_id.get(champion_id)
        if not profile:
            return None
        fields = ("most_played_build", "situational_items", "matchups", "damage_breakdown", "win_rate_vs_game_length")
        if all(profile.get(field) for field in fields):
            self.resolved_profiles[cache_key] = profile
            return profile
        document = self.variantes.repositorio.obtener_campeon(champion_id).datos or {}
        ranks = document.get("ranks", {})
        rank = ranks.get("emerald_plus", {}) if isinstance(ranks, dict) else {}
        roles = profile.get("basic_info", {}).get("flex_potential", [])
        preferred = [role_key, *(str(value).casefold().replace("bot", "adc") for value in roles if value)]
        available = [key for key in rank if key != "__lane_stats__"] if isinstance(rank, dict) else []
        selected = next((role for role in preferred if role in available), available[0] if available else None)
        variant = rank.get(selected, {}) if selected else {}
        self.resolved_profiles[cache_key] = {
            **profile,
            **{field: variant[field] for field in fields if not profile.get(field) and variant.get(field)},
        }
        return self.resolved_profiles[cache_key]

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
            "adc": "Bot",
            "bottom": "Bot",
            "bot": "Bot",
            "middle": "Mid",
            "mid": "Mid",
            "top": "Top",
            "jungle": "Jungle",
            "support": "Support",
            "utility": "Support",
        }
        roles: list[str] = []
        for raw_role in raw_roles:
            role = role_aliases.get(str(raw_role or "").casefold())
            if role and role not in roles:
                roles.append(role)
        return roles

    def assign_likely_roles(
        self, champion_names: list[str], exclude: Iterable[str] = ()
    ) -> list[str]:
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
            index
            for index, roles in enumerate(likely)
            if any(self._role_confidence(roles, role) > 0 for role in candidates)
        ]
        candidates = [
            role
            for role in candidates
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
                        if index in chosen
                        else 0.0
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

    def calculate_team_damage_breakdown(
        self, team_champions: list[str], roles: dict[str, str] | None = None
    ) -> dict[str, float]:
        """Calcula el desglose porcentual de daño físico, mágico y verdadero del equipo."""
        total_ad = 0.0
        total_ap = 0.0
        total_true = 0.0
        count = 0

        for champ in team_champions:
            prof = self.get_champion_profile(champ, (roles or {}).get(champ))
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
        opponent_id = self.identities.resolve(opponent_name)
        if not opponent_id:
            return 50.0
        matchups = profile.get("matchups", {})
        for group_name in ("counters", "good_against"):
            for matchup in matchups.get(group_name, []):
                if not isinstance(matchup, dict):
                    continue
                if self.identities.resolve(matchup.get("champion")) != opponent_id:
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

        El repositorio local almacena las curvas como una lista en
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

    def calculate_team_power_curve_with_samples(
        self, team_champions: list[str]
    ) -> dict[str, dict[str, float | int]]:
        """Return observed bracket means and their actual sample counts.

        Unlike the legacy comparison helper, this view does not fill missing
        brackets with 50%; absent profile data remains absent in the Draft UI.
        """
        sums = {bracket: 0.0 for bracket in self.TIME_BRACKETS}
        samples = {bracket: 0 for bracket in self.TIME_BRACKETS}
        for champion in team_champions:
            profile = self.get_champion_profile(champion)
            if not isinstance(profile, dict):
                continue
            values = profile.get("win_rate_vs_game_length")
            by_bracket: dict[str, Any] = {}
            if isinstance(values, list):
                by_bracket = {
                    str(point.get("label", "")).replace("m", ""): point.get("winrate")
                    for point in values if isinstance(point, dict)
                }
            elif isinstance(profile.get("win_rate_by_game_length"), dict):
                by_bracket = profile["win_rate_by_game_length"]
            for bracket in self.TIME_BRACKETS:
                raw = by_bracket.get(bracket)
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value):
                    continue
                if 0.0 <= value <= 1.0:
                    value *= 100.0
                if not 0.0 <= value <= 100.0:
                    continue
                sums[bracket] += value
                samples[bracket] += 1
        return {
            "values": {b: round(sums[b] / samples[b], 2) for b in self.TIME_BRACKETS if samples[b]},
            "samples": {b: samples[b] for b in self.TIME_BRACKETS if samples[b]},
        }

    def analyze_power_spike_phase(
        self, my_curve: dict[str, float], enemy_curve: dict[str, float]
    ) -> str:
        """Determina la ventana de Power Spike del equipo aliado en comparación con el enemigo."""
        diffs = {
            b: my_curve.get(b, 50.0) - enemy_curve.get(b, 50.0)
            for b in self.TIME_BRACKETS
        }
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

    def get_recommended_bans(
        self, local_champion: str, top_n: int = 3
    ) -> list[dict[str, Any]]:
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
            results.append(
                {
                    "champion": c.get("champion"),
                    "win_rate": round(wr_pct, 1),
                    "games": c.get("lane_games") or c.get("overall_games", 0),
                    "tip": c.get("tip", f"Counter severo para {local_champion}"),
                }
            )
        return results

    @staticmethod
    def normalizar_hechizos(spells: Any, role: str) -> tuple[str, str]:
        """Valida los hechizos recibidos para la línea dada; devuelve el par listo para el cliente.

        La jungla siempre fuerza Aplastar en segundo lugar; en el resto de
        líneas se reemplaza cualquier Aplastar con el hechizo habitual de la
        línea. Sin dos hechizos válidos se devuelven los de la línea.
        """
        rol = str(role or "").strip().casefold()
        fallback = {"support": "Extenuación", "bot": "Curación", "mid": "Ignición"}.get(
            rol, "Teleportación"
        )
        crudos = list(spells) if isinstance(spells, (list, tuple)) else []
        crudos = [hechizo for hechizo in crudos if isinstance(hechizo, str)][:2]
        if len(crudos) != 2:
            crudos = ["Destello", fallback]
        smite = {"smite", "aplastar"}
        if rol in {"jungle", "jungla", "jgl"}:
            primero = next(
                (hechizo for hechizo in crudos if hechizo.casefold() not in smite),
                "Destello",
            )
            crudos = [primero, "Aplastar"]
        else:
            crudos = [
                fallback if hechizo.casefold() in smite else hechizo
                for hechizo in crudos
            ]
            if crudos[0].casefold() == crudos[1].casefold():
                crudos = ["Destello", fallback]
        return crudos[0], crudos[1]

    def get_champion_runes_and_summoners(
        self, champion_name: str, role: str = ""
    ) -> dict[str, Any]:
        """No atribuye una página a otra fuente. El rol activo manda sobre el perfil."""
        prof = self.get_champion_profile(champion_name) or {}
        pages = prof.get("common_runes") or prof.get("runes") or []
        sources = {
            str(p.get("source", "")).casefold(): p for p in pages if isinstance(p, dict)
        }
        roles = self.get_likely_roles(champion_name)
        role = (role or (roles[0] if roles else "Top")).casefold()
        return {
            "page_1": sources.get("u.gg"),
            "page_2": sources.get("lolalytics"),
            "spells": self.normalizar_hechizos(prof.get("summoner_spells"), role),
        }

    def get_situational_items(self, champion_name: str) -> list[dict[str, Any]]:
        """Devuelve alternativas curadas para la l?nea principal disponible.

        Par?metros: nombre can?nico o visible del campe?n.
        Retorno: grupos con hasta tres objetos locales y elegibles por categor?a.
        """
        prof = self.get_champion_profile(champion_name) or {}
        variante = self._variante_recomendaciones_curada(champion_name, prof)
        situational = variante.get(
            "situational_items", prof.get("situational_items", {})
        )
        if not isinstance(situational, dict):
            return []
        groups: list[dict[str, Any]] = []
        for cat_key, cat_label in self.SITUATIONAL_CATEGORIES:
            names = situational.get(cat_key, [])
            if not isinstance(names, list):
                continue
            items: list[dict[str, str]] = []
            seen: set[str] = set()
            for name in names[:3]:
                item_id = self.item_names.get(str(name).strip().casefold(), "")
                item = self.items.get(item_id, {})
                if not item or item_id in seen or "Boots" in item.get("tags", []):
                    continue
                seen.add(item_id)
                items.append({"id": item_id, "name": item.get("name", item_id)})
            if items:
                groups.append({"key": cat_key, "label": cat_label, "items": items})
        return groups

    def _variante_recomendaciones_curada(
        self,
        champion_name: str,
        perfil: dict[str, Any],
        pagina_runas: dict[str, Any] | None = None,
        rol: str | None = None,
    ) -> dict[str, Any]:
        """Carga y cura la variante local de rango y línea más representativos.

        Parámetros: campeón solicitado y perfil global del repositorio.
        Retorno: variante curada o diccionario vacío si no hay datos locales.
        """
        rangos = self.variantes.available_ranks(champion_name)
        if not rangos:
            return {}
        rango = "emerald_plus" if "emerald_plus" in rangos else rangos[0]
        lineas = self.variantes.available_lanes(champion_name, rango)
        if not lineas:
            return {}
        lineas_por_rol = {
            "top": "top",
            "jungle": "jungle",
            "jung": "jungle",
            "jgl": "jungle",
            "mid": "mid",
            "bot": "adc",
            "adc": "adc",
            "support": "support",
            "utility": "support",
        }
        roles = [rol] if rol else self.get_likely_roles(champion_name)
        linea_preferida = next(
            (
                lineas_por_rol.get(rol.casefold(), "")
                for rol in roles
                if lineas_por_rol.get(rol.casefold(), "") in lineas
            ),
            lineas[0],
        )
        variante = self.variantes.get(champion_name, linea_preferida, rango) or {}
        candidatos = (
            variante.get("item_candidates")
            or variante.get("recommendations")
            or variante.get("situational_item_candidates", [])
        )
        if not isinstance(candidatos, list):
            candidatos = []
        return self.curador.curar(variante, perfil, candidatos, pagina_runas)

    def get_starter_items(
        self, champion_name: str, role: str, *, profile: dict | None = None,
        variant: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Reuse curated starting purchases, retaining quantities and a 500g budget."""
        profile = profile if profile is not None else self.get_champion_profile(champion_name) or {}
        variant = variant if variant is not None else self._variante_recomendaciones_curada(champion_name, profile, rol=role or None)
        source = next((data.get(key) for data in (variant, profile)
                       for key in ("starter_item_entries", "starter_item_ids", "starter_items")
                       if isinstance(data.get(key), list) and data[key]), [])
        role_key = str(role).strip().casefold()
        jungle = role_key in {"jungle", "jungla", "jung", "jgl"}
        support = role_key in {"support", "utility", "apoyo", "sup"}
        companions = {"1101", "1102", "1103"}
        catalog = self.curador.catalogo

        def eligible(item_id: str) -> bool:
            if not catalog.validar_objeto_inicial(item_id, champion_name).elegible:
                return False
            if item_id in companions and not jungle:
                return False
            if "GoldPer" in self.items[item_id].get("tags", []) and not support:
                return False
            return 0 < self.items[item_id]["gold"]["total"] <= 500

        entries: list[tuple[str, int]] = []
        for raw in source:
            value = str(raw.get("id") or raw.get("item_id") or raw.get("name") or "") if isinstance(raw, dict) else str(raw)
            item_id = value if value in self.items else self.item_names.get(value.strip().casefold(), "")
            try:
                count = int(raw.get("count", raw.get("quantity", 1))) if isinstance(raw, dict) else 1
            except (ValueError, TypeError, OverflowError):
                continue
            if eligible(item_id) and 1 <= count <= 6:
                entries.append((item_id, count))

        basic = profile.get("basic_info") or {}
        damage = str(basic.get("damage_type", "")).casefold()
        resource = str(basic.get("resource_type", "mana")).casefold()
        ap = damage in {"ap", "magic", "mágico", "magical"}
        fallback = "1056" if ap and resource in {"mana", "maná"} else "1054" if ap else "1055"
        if jungle:
            primary = next((item_id for item_id, _ in entries if item_id in companions), "1101")
            entries = [(primary, 1)] + [(item_id, count) for item_id, count in entries if item_id not in companions and "Consumable" in self.items[item_id].get("tags", [])]
        elif support:
            primary = "3865"
            entries = [(primary, 1)] + [(item_id, count) for item_id, count in entries if "Consumable" in self.items[item_id].get("tags", [])]
        else:
            # A profile scraped from another lane can contain only potions
            # after its jungle/support item is removed. Restore a lane start.
            primary = next((item_id for item_id, _ in entries if "Consumable" not in self.items[item_id].get("tags", [])), fallback)
            if not any(item_id == primary for item_id, _ in entries):
                entries.insert(0, (primary, 1))

        selected: dict[str, int] = {}
        spent = 0
        for item_id, count in entries:
            if not eligible(item_id):
                continue
            if item_id in {"1054", "1055", "1056"} and any(i in selected for i in {"1054", "1055", "1056"}):
                continue
            price = self.items[item_id]["gold"]["total"]
            count = min(count, int((500 - spent) // price))
            if count > 0:
                selected[item_id] = selected.get(item_id, 0) + count
                spent += price * count
        if not any("Consumable" in self.items[item_id].get("tags", []) for item_id in selected) and eligible("2003"):
            count = min(2, int((500 - spent) // self.items["2003"]["gold"]["total"]))
            if count > 0 and not source:
                selected["2003"] = count
        return [{"id": item_id, "name": self.items[item_id].get("name", item_id), "count": count}
                for item_id, count in selected.items()]

    def get_champion_build(
        self, champion_name: str, enemies: list[str], role: str = ""
    ) -> dict[str, Any]:
        """Devuelve la progresión curada de seis objetos y las botas seleccionadas.

        Parámetros: campeón propio y nombres de enemigos conocidos.
        Retorno: build, botas, motivos defensivos y objetos situacionales.
        """
        prof = self.get_champion_profile(champion_name) or {}
        core = []
        boots_id = ""
        unresolved = []
        variante = self._variante_recomendaciones_curada(champion_name, prof, rol=role or None)
        recomendada = variante.get("recommended_build", [])
        secuencia = (
            [
                str(item.get("name", ""))
                for item in recomendada
                if isinstance(item, dict)
            ]
            if recomendada
            else prof.get("most_played_build", [])
        )
        for name in secuencia:
            item_id = self.item_names.get(str(name).strip().casefold(), "")
            if not item_id and str(name).isdigit() and str(name) in self.items:
                item_id = str(name)
            item = self.items.get(item_id, {})
            if not item:
                unresolved.append(str(name))
            elif "Boots" in item.get("tags", []):
                boots_id = item_id
            elif item_id not in core:
                core.append(item_id)
        main_count = len(core)
        # para completar el núcleo y además viajan a la build importada.
        situational = self.get_situational_items(champion_name)
        known_enemies = [e for e in enemies if self.get_champion_profile(e)]
        damage = self.calculate_team_damage_breakdown(known_enemies)
        if not known_enemies:
            reason = "Sin enemigos conocidos: botas de la build del campeón."
        elif damage["true"] > max(damage["physical"], damage["magic"]):
            reason = f"Daño verdadero predominante ({damage['true']:.1f}%): las resistencias no lo reducen; se conservan las botas de la build."
        elif damage["physical"] == damage["magic"]:
            reason = (
                "Daño físico y mágico equilibrado: se conservan las botas de la build."
            )
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

        starters = self.get_starter_items(champion_name, role, profile=prof, variant=variante)

        return {
            "items": [describe(i) for i in core[:6]],
            "boots": describe(boots_id) if boots_id in self.items else None,
            "boots_reason": reason,
            "note": "La sexta compra es una alternativa tardía; solo hay 6 huecos de inventario."
            if main_count < 6 and len(core) >= 6
            else "",
            "unresolved": unresolved,
            "situational": situational,
            "starter_items": starters,
            "champion_id": self.identities.numeric_key(champion_name) or 0,
        }
