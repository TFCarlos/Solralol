"""Extrae evidencia reproducible de una partida guardada para el análisis IA."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from _paths import DATA_DIR

logger = logging.getLogger(__name__)

EVENT_EXTRACTION_VERSION = 6
OBJECTIVE_CORRELATION_VERSION = 3
PERSONAL_EVENT_SELECTION_VERSION = 2


class MatchAnalysisEvidenceService:
    """Construye hechos y referencias verificables sin inferir causas tácticas."""

    def build_evidence(self, match_log: dict[str, Any]) -> dict[str, Any]:
        """Resume roster, estadísticas, inventarios y eventos relevantes.

        Args:
            match_log: Datos estructurados producidos por ``MatchLogService``.

        Returns:
            Evidencia JSON serializable separada por tipo de certeza.
        """
        metadata = match_log.get("metadata", {})
        jugadores = match_log.get("all_players", [])
        eventos_raw = match_log.get("events_chronology")
        timeline_available = isinstance(eventos_raw, list)
        eventos = eventos_raw if timeline_available else []
        usuario = match_log.get("user_stats", {})
        jugador_local = str(match_log.get("local_player_key") or "")
        indice_jugadores = {
            str(jugador.get("player_key")): jugador
            for jugador in jugadores
            if isinstance(jugador, dict)
        }
        aliases = self._aliases_participantes(jugadores, jugador_local)
        participantes = [
            {
                "player_key": aliases.get(str(jugador.get("player_key") or "")),
                "champion_name": jugador.get("champion"),
                "champion_id": self._canonical_champion_id(
                    str(jugador.get("champion") or "")
                ),
                "role": jugador.get("role"),
                "team": jugador.get("team"),
                "is_ally": bool(jugador.get("is_ally")),
                "kda": {
                    clave: jugador.get(clave)
                    for clave in ("kills", "deaths", "assists")
                },
                "cs": jugador.get("cs"),
                "cs_per_min": jugador.get("cs_per_min"),
                "gold_earned": jugador.get("gold"),
                "damage_to_champions": jugador.get("damage_to_champions"),
                "damage_to_objectives": jugador.get("damage_to_objectives"),
                "vision_score": jugador.get("vision_score"),
                "items": [str(item) for item in jugador.get("items", [])],
                "runes": jugador.get("runes"),
                "summoner_spells": jugador.get("summoner_spells"),
            }
            for jugador in jugadores
            if isinstance(jugador, dict)
        ]
        enemigos = [jugador for jugador in participantes if not jugador["is_ally"]]
        hechos_eventos = [
            self._normalizar_evento(evento, indice_jugadores, jugador_local, aliases)
            for evento in eventos
            if isinstance(evento, dict)
        ]
        hechos_eventos = [evento for evento in hechos_eventos if evento]
        equipo_local = str(metadata.get("local_team") or "").upper()
        for evento in hechos_eventos:
            evento["team_label"] = (
                "Equipo aliado"
                if str(evento.get("team") or "").upper() == equipo_local
                else "Equipo rival"
                if evento.get("team")
                else "Equipo no identificado"
            )
            evento["label"] = self._etiqueta_evento(evento)
        catalogo_objetos = self._load_item_catalog()
        inventario_final = {str(item) for item in usuario.get("items", [])}
        for evento in hechos_eventos:
            identificador = evento.get("item_id")
            if identificador and str(identificador) in catalogo_objetos:
                objeto = catalogo_objetos[str(identificador)]
                evento["item_name"] = objeto.get("name_es") or objeto.get("name")
                evento["item_catalog_patch"] = catalogo_objetos.get("version")
                evento["item_is_final_inventory"] = (
                    str(identificador) in inventario_final
                )
                evento["item_completed"] = bool(
                    int(objeto.get("depth") or 0) >= 3
                    and str(identificador) in inventario_final
                )
        muertes = [
            evento
            for evento in hechos_eventos
            if evento.get("category") == "kill"
            and evento.get("victim_key") == "player_local"
        ]
        bajas = [
            evento
            for evento in hechos_eventos
            if evento.get("category") == "kill"
            and evento.get("killer_key") == "player_local"
        ]
        amenazas = self._threat_indicators(enemigos, hechos_eventos, jugador_local)
        peleas = self._teamfights(
            hechos_eventos,
            aliases.get(jugador_local, "player_local"),
            equipo_local,
        )
        objetivos = self._objectives(hechos_eventos)
        correlaciones_baja_objetivo, diagnostico_correlaciones = self._validate_kill_objective_correlations(
            self._unique_takedowns(hechos_eventos), objetivos,
        )
        correlaciones_muerte_objetivo, diagnostico_correlaciones_muerte = self._validate_player_death_objective_correlations(
            self._unique_takedowns(hechos_eventos), objetivos,
            aliases.get(jugador_local, "player_local"), equipo_local,
        )
        correlaciones = self._correlate_fights_and_objectives(
            peleas, objetivos, correlaciones_baja_objetivo,
        )
        candidatos = self._key_event_candidates(
            hechos_eventos, aliases.get(jugador_local, "player_local"), equipo_local,
            metadata.get("duration_seconds"), teamfights=peleas, objectives=objetivos,
            kill_objective_correlations=correlaciones_baja_objetivo,
            fight_objective_correlations=correlaciones,
            player_death_objective_correlations=correlaciones_muerte_objetivo,
        )
        excluded_plates = sum(
            any("turret_plate_destroyed" in str(event.get(field) or "").casefold()
                for field in ("type", "objective", "objective_label", "label"))
            for event in eventos if isinstance(event, dict)
        )
        logger.info("[Timeline] Turret plates excluded from strategic events: %d", excluded_plates)
        personal_selection = self._personal_event_selection(
            hechos_eventos, peleas, objetivos, correlaciones_baja_objetivo,
            candidatos, aliases.get(jugador_local, "player_local"),
            death_objective_correlations=correlaciones_muerte_objetivo,
        )
        logger.info(
            "[Timeline] Evidence extracted: status=%s participants=%d source_events=%d normalized=%d kills=%d objectives=%d structures=%d unattributed_objectives=%d fights=%d correlations=%d candidates=%d",
            "available" if timeline_available else "unavailable",
            len(participantes), len(eventos), len(hechos_eventos),
            sum(event.get("category") == "kill" for event in hechos_eventos),
            sum(event.get("category") == "objective" for event in hechos_eventos),
            sum(event.get("category") == "structure" for event in hechos_eventos),
            sum(
                event.get("category") in {"objective", "structure"}
                and not event.get("team") for event in hechos_eventos
            ),
            len(peleas),
            len(correlaciones),
            len(candidatos),
        )
        logger.info(
            "[Timeline] Objective correlations: accepted=%d rejected=%d duplicate_relationships_removed=%d",
            diagnostico_correlaciones.get("accepted", 0),
            diagnostico_correlaciones.get("rejected", 0),
            diagnostico_correlaciones.get("duplicate", 0),
        )
        logger.info(
            "[Timeline] Player death-to-enemy-objective correlations: accepted=%d rejected=%d duplicates=%d",
            diagnostico_correlaciones_muerte.get("accepted", 0),
            diagnostico_correlaciones_muerte.get("rejected", 0),
            diagnostico_correlaciones_muerte.get("duplicate", 0),
        )
        return {
            "evidence_version": EVENT_EXTRACTION_VERSION,
            "correlation_version": OBJECTIVE_CORRELATION_VERSION,
            "personal_selection_version": PERSONAL_EVENT_SELECTION_VERSION,
            "timeline_extraction": {
                "version": EVENT_EXTRACTION_VERSION,
                "status": "available" if timeline_available else "unavailable",
                "source_events": len(eventos),
                "normalized_events": len(hechos_eventos),
                "turret_plates_excluded": excluded_plates,
                "correlation_diagnostics": diagnostico_correlaciones,
            },
            "source": "SOLRALOL_match_log",
            "coverage": {
                "participants": len(participantes),
                "events": len(hechos_eventos),
                "timeline_available": timeline_available,
                "champion_kills": sum(
                    evento.get("category") == "kill" for evento in hechos_eventos
                ),
                "purchase_events": sum(
                    evento["category"] == "purchase" for evento in hechos_eventos
                ),
                "runes_available": bool(usuario.get("runes")),
                "runes_source": metadata.get("runes_source") or "match_log",
                "summoner_spells_available": bool(usuario.get("summoner_spells")),
                "position_data_available": any(
                    isinstance(evento.get("position"), dict)
                    for evento in hechos_eventos
                ),
                "gold_on_hand_available": any(
                    evento.get("gold_on_hand") is not None for evento in hechos_eventos
                ),
            },
            "match": {
                "duration_seconds": metadata.get("duration_seconds"),
                "result": metadata.get("result"),
                "game_version": metadata.get("game_version"),
                "local_team": metadata.get("local_team"),
                "winning_team": metadata.get("winning_team"),
            },
            "player": {
                "player_key": "player_local",
                "champion_name": usuario.get("champion"),
                "champion_id": self._canonical_champion_id(
                    str(usuario.get("champion") or "")
                ),
                "role": usuario.get("role"),
                "kda": {
                    clave: usuario.get(clave)
                    for clave in ("kills", "deaths", "assists")
                },
                "cs": usuario.get("cs"),
                "cs_per_min": usuario.get("cs_per_min"),
                "gold_earned": usuario.get("gold"),
                "combat": {
                    clave: usuario.get(clave)
                    for clave in (
                        "damage_to_champions",
                        "damage_to_objectives",
                        "all_source_damage_received",
                        "damage_self_mitigated",
                        "vision_score",
                    )
                },
                "items_final": [str(item) for item in usuario.get("items", [])],
                "runes": usuario.get("runes"),
                "summoner_spells": usuario.get("summoner_spells"),
            },
            "participants": participantes,
            "player_deaths": muertes,
            "player_kills": bajas,
            "objective_events": [
                evento for evento in hechos_eventos if evento["category"] == "objective"
            ],
            "structure_events": [
                evento for evento in hechos_eventos if evento["category"] == "structure"
            ],
            "purchases": [
                evento for evento in hechos_eventos if evento["category"] == "purchase"
            ],
            "important_item_completions": [
                evento
                for evento in hechos_eventos
                if evento["category"] == "purchase" and evento.get("item_completed")
            ],
            "notable_timeline": self._notable_events(hechos_eventos, jugador_local),
            "teamfights": peleas,
            "objectives": objetivos,
            "kill_objective_correlations": correlaciones_baja_objetivo,
            "player_death_objective_correlations": correlaciones_muerte_objetivo,
            "fight_objective_correlations": correlaciones,
            "global_key_event_candidates": candidatos,
            "key_event_candidates": personal_selection["candidates"],
            "personal_event_selection": personal_selection,
            "enemy_threat_indicators": amenazas,
            "ability_catalog": self._ability_catalog(
                enemigos, str(metadata.get("game_version") or "")
            ),
            "item_catalog": self._item_catalog(usuario.get("items", [])),
            "item_option_catalog": self._item_option_catalog(catalogo_objetos),
            "performance_scoring": self._resumen_puntuacion(
                match_log.get("performance_scoring"), jugador_local
            ),
            "certainty": {
                "confirmed": "Hechos directamente registrados en el log o marcador.",
                "derived": "Cálculos efectuados únicamente a partir de hechos confirmados.",
                "interpretation": "Lectura estratégica que debe citar su evidencia.",
                "unknown": "Dato no disponible; no debe afirmarse como hecho.",
            },
        }

    def _normalizar_evento(
        self,
        evento: dict[str, Any],
        jugadores: dict[str, dict[str, Any]],
        clave_local: str,
        aliases: dict[str, str],
    ) -> dict[str, Any]:
        """Normaliza un evento y vincula participantes a campeones canónicos."""
        tipo = str(evento.get("type") or "").casefold()
        objetivo_raw = str(
            evento.get("objective") or evento.get("objective_label") or ""
        ).casefold()
        es_placa_torre = any(
            "turret_plate_destroyed" in str(evento.get(field) or "").casefold()
            for field in ("type", "objective", "objective_label")
        )
        es_estructura = any(
            texto in tipo or texto in objetivo_raw
            for texto in (
                "building_kill", "tower", "inhibitor", "structure",
                "inhibidor", "torre",
            )
        )
        categoria = (
            "turret_plate"
            if es_placa_torre
            else
            "structure"
            if es_estructura
            else "objective"
            if "elite_monster_kill" in tipo or "objective" in tipo or evento.get("objective")
            else "purchase"
            if "item_purchased" in tipo or "purchase" in tipo
            else "kill"
            if ("champion_kill" in tipo or "death" in tipo or "kill" in tipo)
            else "other"
        )
        resultado = {
            clave: evento.get(clave)
            for clave in (
                "order",
                "time_seconds",
                "time_label",
                "type",
                "team",
                "objective_team",
                "label",
                "objective",
                "objective_label",
                "objective_subtype",
                "owner_team",
                "team_source",
                "structure",
                "item_name",
                "source_reference",
                "timestamp_ms",
                "position",
            )
            if evento.get(clave) is not None
        }
        if categoria in {"objective", "structure"} and evento.get("objective_team"):
            # An objective's beneficiary side is distinct from a structure's owner side.
            resultado["team"] = evento.get("objective_team")
        if evento.get("label"):
            resultado["source_label"] = evento.get("label")
        for campo in ("precision", "shutdown", "bounty", "gold_value"):
            if evento.get(campo) is not None:
                resultado[campo] = evento[campo]
        resultado["category"] = categoria
        resultado["event_id"] = str(
            evento.get("event_id") or f"event-{evento.get('order', 'unknown')}"
        )
        for campo in ("player_key", "killer_key", "victim_key"):
            clave = str(evento.get(campo) or "")
            if not clave:
                continue
            resultado[campo] = aliases.get(clave, "")
            jugador = jugadores.get(clave, {})
            resultado[campo.replace("_key", "_champion")] = jugador.get("champion")
            resultado[campo.replace("_key", "_champion_id")] = (
                self._canonical_champion_id(str(jugador.get("champion") or ""))
            )
            if campo == "player_key" and jugador.get("team"):
                resultado["player_team"] = jugador.get("team")
            if campo == "killer_key" and jugador.get("team"):
                resultado["killer_team"] = jugador.get("team")
            if campo == "victim_key" and jugador.get("team"):
                resultado["victim_team"] = jugador.get("team")
        asistentes_origen = [str(clave) for clave in evento.get("assister_keys", [])]
        asistentes = [aliases.get(clave, "") for clave in asistentes_origen]
        asistentes = [clave for clave in asistentes if clave]
        resultado["assister_keys"] = asistentes
        resultado["assister_champions"] = [
            jugadores.get(clave, {}).get("champion")
            for clave in asistentes_origen
            if jugadores.get(clave, {}).get("champion")
        ]
        resultado["assister_teams"] = [
            jugadores.get(clave, {}).get("team")
            for clave in asistentes_origen
            if jugadores.get(clave, {}).get("team") is not None
        ]
        resultado["player_involved"] = "player_local" in {
            resultado.get("player_key"),
            resultado.get("killer_key"),
            resultado.get("victim_key"),
            *asistentes,
        }
        if categoria == "purchase":
            resultado["item_id"] = self._item_id_from_event(evento)
        resultado["label"] = self._etiqueta_evento(resultado)
        return resultado

    @staticmethod
    def _aliases_participantes(
        jugadores: list[dict[str, Any]], clave_local: str
    ) -> dict[str, str]:
        """Sustituye claves de participante por alias no identificables."""
        aliases: dict[str, str] = {}
        contadores = {True: 0, False: 0}
        for jugador in jugadores:
            if not isinstance(jugador, dict):
                continue
            clave = str(jugador.get("player_key") or "")
            if not clave:
                continue
            if clave == clave_local:
                aliases[clave] = "player_local"
                continue
            aliado = bool(jugador.get("is_ally"))
            contadores[aliado] += 1
            aliases[clave] = f"{'ally' if aliado else 'enemy'}_{contadores[aliado]}"
        return aliases

    @staticmethod
    def _etiqueta_evento(evento: dict[str, Any]) -> str:
        """Redacta una etiqueta factual del evento sin nombres de invocador."""
        categoria = evento.get("category")
        if categoria == "kill":
            killer = evento.get("killer_champion") or "Campeón sin identificar"
            victim = evento.get("victim_champion") or "Campeón sin identificar"
            return f"{killer} eliminó a {victim}."
        if categoria == "objective":
            objetivo = MatchAnalysisEvidenceService._nombre_objetivo(
                evento.get("objective_label") or evento.get("objective")
            ) or str(evento.get("objective_label") or evento.get("objective") or "objetivo no especificado")
            subtype = MatchAnalysisEvidenceService._nombre_subtipo_objetivo(
                evento.get("objective_subtype")
            )
            if subtype and "drag" in objetivo.casefold():
                objetivo = f"{objetivo} ({subtype})"
            return f"El {evento.get('team_label') or 'equipo no identificado'} aseguró {objetivo}."
        if categoria == "structure":
            if "turret_plate_destroyed" in str(evento.get("type") or "").casefold():
                return f"El {evento.get('team_label') or 'equipo no identificado'} derribó una placa de torre."
            estructura = (
                evento.get("objective_label")
                or MatchAnalysisEvidenceService._nombre_objetivo(evento.get("objective"))
                or "una estructura"
            )
            return f"El {evento.get('team_label') or 'equipo no identificado'} destruyó {estructura}."
        if categoria == "purchase":
            campeon = evento.get("player_champion") or "Campeón no identificado"
            objeto = (
                evento.get("item_id")
                or evento.get("item_name")
                or "objeto no identificado"
            )
            return f"{campeon} compró el objeto {objeto}."
        return "Evento registrado sin detalle adicional."

    @staticmethod
    def _nombre_objetivo(value: Any) -> str:
        """Devuelve un nombre de objetivo legible para IDs de Riot conocidos."""
        canonical = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
        return {
            "tower_building": "torre",
            "inhibitor_building": "inhibidor",
            "barracks": "inhibidor",
            "dragon": "dragón",
            "elder_dragon": "Dragón anciano",
            "turret_plate_destroyed": "placa de torre",
            "void_grub": "Larva del Vacío",
            "baron_nashor": "Barón Nashor",
            "rift_herald": "Heraldo de la Grieta",
            "riftherald": "Heraldo de la Grieta",
            "horde": "Larvas del Vacío",
            "atakhan": "Atakhan",
        }.get(canonical, "")

    @staticmethod
    def _nombre_subtipo_objetivo(value: Any) -> str:
        canonical = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")
        return {
            "fire_dragon": "Infernal",
            "infernal_dragon": "Infernal",
            "water_dragon": "Oceánico",
            "ocean_dragon": "Oceánico",
            "air_dragon": "Nublado",
            "cloud_dragon": "Nublado",
            "earth_dragon": "Montaña",
            "mountain_dragon": "Montaña",
            "hextech_dragon": "Hextech",
            "chemtech_dragon": "Quimtech",
        }.get(canonical, "")

    @staticmethod
    def _resumen_puntuacion(puntuacion: Any, clave_local: str) -> dict[str, Any] | None:
        """Conserva el resultado oficial local sin incluir identidades ajenas."""
        if not isinstance(puntuacion, dict):
            return None
        if puntuacion.get("version") != "battlescore_v2_0" or puntuacion.get("calibration_version") != "battlescore_v2_0":
            return None
        jugadores = puntuacion.get("players", [])
        jugador = (
            next(
                (
                    valor
                    for valor in jugadores
                    if isinstance(valor, dict)
                    and str(valor.get("participant_id") or "") == clave_local
                ),
                None,
            )
            if isinstance(jugadores, list)
            else None
        )
        if not isinstance(jugador, dict):
            return {
                clave: puntuacion.get(clave)
                for clave in ("version", "calibration_version", "state")
            }
        return {
            "version": puntuacion.get("version"),
            "calibration_version": puntuacion.get("calibration_version"),
            "state": puntuacion.get("state"),
            "awards_finalized": puntuacion.get("awards_finalized"),
            "local_player": {
                clave: jugador.get(clave)
                for clave in (
                    "total",
                    "global_rank",
                    "awards",
                    "completeness",
                    "categories",
                )
                if clave in jugador
            },
        }

    def _notable_events(
        self, eventos: list[dict[str, Any]], clave_local: str
    ) -> list[dict[str, Any]]:
        """Selecciona eventos de combate, objetivos, estructuras y compras."""
        notable = []
        seen: set[str] = set()
        for evento in eventos:
            if not (
                evento.get("category") in {"kill", "objective", "structure"}
                or evento.get("category") == "purchase" and evento.get("player_key") == clave_local
            ):
                continue
            stable_id = str(evento.get("source_reference") or evento.get("event_id") or "")
            if stable_id and stable_id in seen:
                logger.info("[Timeline] Duplicate notable source event removed: %s", stable_id)
                continue
            if stable_id:
                seen.add(stable_id)
            notable.append(evento)
        return notable

    @staticmethod
    def _unique_takedowns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Colapsa las filas kill/death/assist de una misma baja registrada."""
        unique: dict[tuple[float, str, str], dict[str, Any]] = {}
        for event in events:
            if event.get("category") != "kill":
                continue
            killer = str(event.get("killer_key") or "")
            victim = str(event.get("victim_key") or "")
            if not victim:
                continue
            try:
                time = round(float(event.get("time_seconds") or 0), 1)
            except (TypeError, ValueError):
                continue
            key = (time, killer, victim)
            current = unique.get(key)
            def dedupe_rank(item: dict[str, Any]) -> tuple[int, str]:
                event_type = str(item.get("type") or "").casefold()
                preferred_type = 0 if "champion_kill" in event_type else 1
                stable_reference = str(item.get("source_reference") or item.get("event_id") or "")
                return preferred_type, stable_reference

            if current is None or dedupe_rank(event) < dedupe_rank(current):
                unique[key] = event
        return sorted(unique.values(), key=lambda event: float(event.get("time_seconds") or 0))

    @classmethod
    def _teamfights(
        cls, events: list[dict[str, Any]], local_key: str, local_team: str
    ) -> list[dict[str, Any]]:
        """Detecta agrupaciones potenciales, separadas por huecos >=30 s o >120 s."""
        takedowns = cls._unique_takedowns(events)
        groups: list[list[dict[str, Any]]] = []
        for event in takedowns:
            at = float(event.get("time_seconds") or 0)
            if groups:
                previous = float(groups[-1][-1].get("time_seconds") or 0)
                start = float(groups[-1][0].get("time_seconds") or 0)
                previous_event = groups[-1][-1]
                shared_participants = {
                    str(value) for value in (
                        previous_event.get("killer_key"), previous_event.get("victim_key"),
                        *previous_event.get("assister_keys", []),
                    ) if value
                }.intersection({
                    str(value) for value in (
                        event.get("killer_key"), event.get("victim_key"),
                        *event.get("assister_keys", []),
                    ) if value
                })
                previous_position = previous_event.get("position")
                event_position = event.get("position")
                spatially_separated = False
                if (
                    not shared_participants
                    and isinstance(previous_position, dict)
                    and isinstance(event_position, dict)
                ):
                    try:
                        dx = float(previous_position["x"]) - float(event_position["x"])
                        dy = float(previous_position["y"]) - float(event_position["y"])
                        spatially_separated = dx * dx + dy * dy > 6000 * 6000
                    except (KeyError, TypeError, ValueError):
                        pass
                if at - previous < 30 and at - start <= 120 and not spatially_separated:
                    groups[-1].append(event)
                    continue
            groups.append([event])
        result = []
        for group in groups:
            if len(group) < 4:
                continue
            ally_team = str(local_team or "").upper()
            local_kills = sum(
                str(event.get("killer_team") or "").upper() == ally_team
                for event in group
            ) if ally_team else None
            local_deaths = sum(
                str(event.get("victim_team") or "").upper() == ally_team
                for event in group
            ) if ally_team else None
            enemy_deaths = len(group) - local_deaths if local_deaths is not None else None
            killer_champs = {event.get("killer_champion") for event in group if event.get("killer_champion")}
            victim_champs = {event.get("victim_champion") for event in group if event.get("victim_champion")}
            assister_champs = {
                champion for event in group
                for champion in event.get("assister_champions", []) if champion
            }
            participants = killer_champs | victim_champs | assister_champs
            both_sides = bool(local_team) and any(
                str(event.get("killer_team") or "").upper() == ally_team for event in group
            ) and any(
                str(event.get("killer_team") or "").upper() != ally_team
                and event.get("killer_team") for event in group
            )
            involvement = len(participants)
            classification = (
                "teamfight_candidate" if both_sides and involvement >= 6
                else "skirmish_candidate" if both_sides and involvement >= 3
                else "clustered_combat"
            )
            local_kill_events = [
                event for event in group
                if event.get("killer_key") == local_key
            ]
            local_death_events = [
                event for event in group
                if event.get("victim_key") == local_key
            ]
            local_assist_events = [
                event for event in group
                if local_key in event.get("assister_keys", [])
            ]
            result.append({
                "teamfight_id": f"teamfight-{group[0].get('event_id', '')}",
                "classification": classification,
                "confidence": "potential",
                "start_time": group[0].get("time_label"),
                "end_time": group[-1].get("time_label"),
                "start_seconds": group[0].get("time_seconds"),
                "end_seconds": group[-1].get("time_seconds"),
                "max_gap_seconds": max(
                    float(group[index].get("time_seconds") or 0)
                    - float(group[index - 1].get("time_seconds") or 0)
                    for index in range(1, len(group))
                ),
                "duration_seconds": round(
                    float(group[-1].get("time_seconds") or 0)
                    - float(group[0].get("time_seconds") or 0), 1
                ),
                "death_count": len(group),
                "allied_kills": local_kills,
                "enemy_kills": len(group) - local_kills if local_kills is not None else None,
                "allied_deaths": local_deaths,
                "enemy_deaths": enemy_deaths,
                "net_death_advantage": (
                    local_deaths - enemy_deaths
                    if local_deaths is not None and enemy_deaths is not None else None
                ),
                "team_with_fewer_deaths": (
                    "Equipo aliado" if local_deaths < enemy_deaths
                    else "Equipo rival" if enemy_deaths < local_deaths
                    else "Empate"
                ) if local_deaths is not None and enemy_deaths is not None else None,
                "participants": sorted(participants),
                "participants_by_team": {
                    "allied": sorted({
                        str(event.get("victim_champion") or "")
                        for event in group
                        if str(event.get("victim_team") or "").upper() == ally_team
                        and event.get("victim_champion")
                    } | {
                        str(event.get("killer_champion") or "")
                        for event in group
                        if str(event.get("killer_team") or "").upper() == ally_team
                        and event.get("killer_champion")
                    }) if local_team else [],
                    "enemy": sorted({
                        str(event.get("victim_champion") or "")
                        for event in group
                        if event.get("victim_team") and str(event.get("victim_team") or "").upper() != ally_team
                        and event.get("victim_champion")
                    } | {
                        str(event.get("killer_champion") or "")
                        for event in group
                        if event.get("killer_team") and str(event.get("killer_team") or "").upper() != ally_team
                        and event.get("killer_champion")
                    }) if local_team else [],
                },
                "local_player_involved": bool(local_kill_events or local_death_events or local_assist_events),
                "player_kills": len(local_kill_events),
                "player_deaths": len(local_death_events),
                "player_assists": len(local_assist_events),
                "event_ids": [event.get("event_id") for event in group if event.get("event_id")],
                "events": [
                    {
                        "event_id": event.get("event_id"),
                        "time": event.get("time_label"),
                        "time_seconds": event.get("time_seconds"),
                        "killer": event.get("killer_champion"),
                        "victim": event.get("victim_champion"),
                        "killer_team": event.get("killer_team"),
                        "victim_team": event.get("victim_team"),
                        "assisters": event.get("assister_champions", []),
                        "description": event.get("label"),
                    }
                    for event in group
                ],
                "evidence_ids": [event.get("event_id") for event in group if event.get("event_id")],
            })
        return result

    @staticmethod
    def _personal_event_selection(
        events: list[dict[str, Any]],
        fights: list[dict[str, Any]],
        objectives: list[dict[str, Any]],
        correlations: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        local_key: str,
        *, death_objective_correlations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Describe the selected player-only views over the shared factual index."""
        by_id = {str(event.get("event_id")): event for event in events if event.get("event_id")}
        combat_fights = [
            fight for fight in fights
            if int(fight.get("death_count") or 0) >= 4 and fight.get("local_player_involved")
        ]
        personal_relations = [
            relation for relation in correlations
            if relation.get("status") == "accepted"
            and local_key in relation.get("kill_participants", [])
        ]
        personal_objective_ids: set[str] = {
            str(relation.get("objective_event_id"))
            for relation in personal_relations if relation.get("objective_event_id")
        }
        for objective in objectives:
            if str(objective.get("finisher_id") or "") == local_key and objective.get("event_id"):
                personal_objective_ids.add(str(objective["event_id"]))
        direct_personal_objective_ids = set(personal_objective_ids)
        personal_death_relations = [
            relation for relation in (death_objective_correlations or [])
            if relation.get("status") == "accepted"
        ]
        for relation in personal_death_relations:
            if relation.get("objective_event_id"):
                personal_objective_ids.add(str(relation["objective_event_id"]))
        combat_ids = {
            str(ref) for fight in combat_fights for ref in fight.get("event_ids", []) if ref
        }
        qualifying_shutdowns = []
        reward_ids: set[str] = set()
        for event in events:
            if event.get("category") != "kill" or event.get("bounty") != 700:
                continue
            if local_key == event.get("killer_key"):
                participation = "secured"
            elif local_key in (event.get("assister_keys") or []):
                participation = "assisted"
            else:
                continue
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            reward_ids.add(event_id)
            qualifying_shutdowns.append({
                "event_id": event_id,
                "time": event.get("time_label"),
                "bounty": 700,
                "participation": participation,
                "killer": event.get("killer_champion"),
                "victim": event.get("victim_champion"),
                "description": event.get("label"),
            })
        # Only personally involved kills with a strong, deterministic reason are
        # selected: a qualifying cluster, verified conversion, or confirmed shutdown.
        personal_candidate_ids: set[str] = set(combat_ids | personal_objective_ids | reward_ids)
        for candidate in candidates:
            refs = [str(ref) for ref in candidate.get("event_ids", []) if ref]
            kind = candidate.get("candidate_type")
            if kind == "teamfight_cluster":
                if candidate.get("local_player_involved") and int(candidate.get("combat_kill_count") or 0) >= 4:
                    personal_candidate_ids.update(refs)
            elif kind in {"combat_then_objective", "validated_kills_before_objective"}:
                kills = [by_id[ref] for ref in refs if ref in by_id and by_id[ref].get("category") == "kill"]
                objective_refs = [ref for ref in refs if ref in personal_objective_ids]
                valid_personal_kills = {
                    str(relation.get("kill_event_id")) for relation in personal_relations
                    if str(relation.get("objective_event_id") or "") in objective_refs
                }
                if objective_refs and valid_personal_kills.intersection(refs) and any(
                    event.get("player_involved") for event in kills
                    if str(event.get("event_id") or "") in valid_personal_kills
                ):
                    personal_candidate_ids.update(valid_personal_kills.intersection(refs))
                    personal_candidate_ids.update(objective_refs)
            elif kind == "confirmed_700_shutdown":
                ref = refs[0] if refs else ""
                event = by_id.get(ref, {})
                if event.get("player_involved") and ref in reward_ids:
                    personal_candidate_ids.add(ref)
            elif kind == "player_death_to_enemy_objective":
                relation_id = str(candidate.get("correlation_id") or "")
                relation = next((item for item in personal_death_relations if item.get("correlation_id") == relation_id), None)
                if relation and set(refs) == set(str(ref) for ref in relation.get("event_ids", [])):
                    personal_candidate_ids.update(refs)
        selected_candidates = []
        for candidate in candidates:
            refs = {str(ref) for ref in candidate.get("event_ids", []) if ref}
            kind = candidate.get("candidate_type")
            if kind == "teamfight_cluster" and refs.intersection(combat_ids):
                selected_candidates.append(candidate)
            elif kind in {"combat_then_objective", "validated_kills_before_objective"} and refs.intersection(personal_objective_ids):
                valid_personal_kills = {
                    str(relation.get("kill_event_id")) for relation in personal_relations
                    if str(relation.get("objective_event_id") or "") in refs
                }
                if refs.intersection(valid_personal_kills):
                    relevant_objectives = sorted(refs.intersection(personal_objective_ids))
                    selected_candidates.append({
                        **candidate,
                        "event_ids": sorted(refs.intersection(valid_personal_kills)) + relevant_objectives,
                    })
            elif kind == "confirmed_700_shutdown" and refs.intersection(reward_ids):
                selected_candidates.append(candidate)
            elif kind == "objective_capture" and refs.intersection(direct_personal_objective_ids):
                selected_candidates.append(candidate)
            elif kind == "player_death_to_enemy_objective" and any(
                item.get("correlation_id") == candidate.get("correlation_id")
                for item in personal_death_relations
            ):
                selected_candidates.append(candidate)
        # The same raw fact may belong to a combat, conversion, and reward. Keep
        # one source record and let the UI filter its categories by these sets.
        return {
            "version": PERSONAL_EVENT_SELECTION_VERSION,
            "player_key": local_key,
            "combat_event_ids": sorted(combat_ids),
            "objective_event_ids": sorted(personal_objective_ids),
            "reward_event_ids": sorted(reward_ids),
            "personal_event_ids": sorted(personal_candidate_ids),
            "teamfights": combat_fights,
            "kill_objective_correlations": personal_relations,
            "player_death_objective_correlations": personal_death_relations,
            "shutdowns": qualifying_shutdowns,
            "candidates": selected_candidates,
            "counts": {
                "teamfight_candidates": sum(int(fight.get("death_count") or 0) >= 4 for fight in fights),
                "personal_teamfights": len(combat_fights),
                "personal_objectives": len(personal_objective_ids),
                "negative_death_objective_conversions": len(personal_death_relations),
                "confirmed_700_shutdowns": len(qualifying_shutdowns),
                "events_excluded_no_player_participation": len({
                    str(event.get("event_id")) for event in events
                    if event.get("category") == "kill" and not event.get("player_involved")
                    or event.get("category") in {"objective", "structure"}
                    and str(event.get("event_id") or "") not in personal_objective_ids
                }),
            },
        }

    @staticmethod
    def _objectives(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Enumerate strategic objectives and structures, excluding turret plates."""
        objectives = []
        seen: set[str] = set()
        for event in events:
            if (
                event.get("category") not in {"objective", "structure"}
                or str(event.get("type") or "").casefold() == "turret_plate_destroyed"
            ):
                continue
            stable_id = str(event.get("source_reference") or event.get("event_id") or "")
            if stable_id and stable_id in seen:
                logger.info("[Timeline] Duplicate objective source event removed: %s", stable_id)
                continue
            if stable_id:
                seen.add(stable_id)
            objective_name = (
                MatchAnalysisEvidenceService._nombre_objetivo(event.get("objective_label"))
                or event.get("objective_label")
                or MatchAnalysisEvidenceService._nombre_objetivo(event.get("objective"))
                or event.get("objective") or event.get("label")
            )
            subtype = MatchAnalysisEvidenceService._nombre_subtipo_objetivo(
                event.get("objective_subtype")
            )
            if subtype and "drag" in str(objective_name).casefold():
                objective_name = f"{objective_name} ({subtype})"
            objectives.append({
                "event_id": event.get("event_id"),
                "time": event.get("time_label"),
                "time_seconds": event.get("time_seconds"),
                "type": event.get("category"),
                "objective": objective_name,
                "subtype": event.get("objective_subtype"),
                "team": event.get("team_label"),
                "team_id": event.get("team"),
                "owner_team": event.get("owner_team"),
                "team_source": event.get("team_source"),
                "source_reference": event.get("source_reference"),
                "finisher_id": event.get("killer_key") or event.get("player_key") or None,
                "finisher": event.get("killer_champion") or event.get("player_champion"),
                "finisher_team": event.get("killer_team") or event.get("player_team"),
                "description": event.get("label"),
            })
        return sorted(objectives, key=lambda event: float(event.get("time_seconds") or 0))

    @staticmethod
    def _correlate_fights_and_objectives(
        fights: list[dict[str, Any]], objectives: list[dict[str, Any]],
        validated_correlations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Require the objective finisher to have participated in a kill in the fight."""
        correlations = []
        seen: set[tuple[str, str]] = set()
        accepted_pairs = {
            (str(item.get("kill_event_id") or ""), str(item.get("objective_event_id") or ""))
            for item in validated_correlations if item.get("status") == "accepted"
        }
        for fight in fights:
            try:
                end = float(fight.get("end_seconds"))
            except (TypeError, ValueError):
                continue
            fight_refs = {str(ref) for ref in fight.get("event_ids", []) if ref}
            for objective in objectives:
                try:
                    at = float(objective.get("time_seconds"))
                except (TypeError, ValueError):
                    continue
                delta = at - end
                if not (0 < delta <= 120):
                    continue
                pairs = [
                    pair for pair in accepted_pairs
                    if pair[0] in fight_refs and pair[1] == str(objective.get("event_id") or "")
                ]
                if not pairs:
                    continue
                key = (str(fight.get("teamfight_id") or ""), str(objective.get("event_id") or ""))
                if key in seen:
                    logger.info("[Timeline] Duplicate fight-objective relationship removed: fight=%s objective=%s", *key)
                    continue
                seen.add(key)
                correlations.append({
                    "fight_id": fight.get("teamfight_id"),
                    "objective_event_id": objective.get("event_id"),
                    "relationship": "fight_before_objective",
                    "seconds_between_fight_end_and_objective": round(delta, 1),
                    "kill_event_ids": [pair[0] for pair in pairs],
                    "objective_finisher_id": objective.get("finisher_id"),
                    "shared_participant": objective.get("finisher"),
                    "fight_team_death_counts": {
                        "allied": fight.get("allied_deaths"),
                        "enemy": fight.get("enemy_deaths"),
                    },
                    "objective_team": objective.get("team"),
                    "validation": "verified_finisher_participated_in_fight_kill",
                    "interpretation_limit": "El rematador del objetivo participo en una baja de esta pelea; la secuencia no demuestra causalidad.",
                })
        return correlations

    @staticmethod
    def _validate_kill_objective_correlations(
        kills: list[dict[str, Any]], objectives: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Require shared finisher, matching beneficiary teams and a valid time window."""
        validations: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        diagnostics = {
            "accepted": 0, "rejected": 0, "duplicate": 0,
            "invalid_timestamp": 0, "invalid_order": 0,
            "missing_finisher": 0, "invalid_team": 0,
            "exceeded_time_window": 0, "no_shared_participant": 0,
        }

        def reject(reason: str, message: str, *args: Any) -> None:
            diagnostics["rejected"] += 1
            diagnostics[reason] = diagnostics.get(reason, 0) + 1
            logger.info(message, *args)

        for objective in objectives:
            objective_id = str(objective.get("event_id") or "")
            if not objective_id:
                continue
            try:
                objective_time = float(objective.get("time_seconds"))
                if objective_time < 0:
                    raise ValueError
            except (TypeError, ValueError):
                reject("invalid_timestamp", "[Correlation] Objective %s rejected: INVALID_TIMESTAMP", objective_id)
                continue
            structure = objective.get("type") == "structure"
            window = 90 if structure else 120
            finisher_id = str(objective.get("finisher_id") or "")
            objective_team = str(objective.get("team_id") or "").strip().upper()
            finisher_team = str(objective.get("finisher_team") or "").strip().upper()
            for kill in kills:
                kill_id = str(kill.get("event_id") or "")
                try:
                    kill_time = float(kill.get("time_seconds"))
                except (TypeError, ValueError):
                    reject("invalid_timestamp", "[Correlation] Kill %s -> objective %s rejected: INVALID_TIMESTAMP", kill_id or "unknown", objective_id)
                    continue
                delta = objective_time - kill_time
                if delta < 0 and abs(delta) <= 120:
                    reject("invalid_order", "[Correlation] Kill %s -> objective %s rejected: OBJECTIVE_PRECEDES_KILL", kill_id, objective_id)
                    continue
                if delta <= 0 or delta > 120:
                    continue
                if not finisher_id:
                    reject("missing_finisher", "[Correlation] Kill %s -> objective %s rejected: MISSING_FINISHER", kill_id, objective_id)
                    continue
                if not objective_team or not finisher_team or objective_team != finisher_team:
                    reject(
                        "invalid_team",
                        "[Correlation] Kill %s -> objective %s rejected: INVALID_TEAM beneficiary=%s finisher_team=%s",
                        kill_id, objective_id, objective_team or "unknown", finisher_team or "unknown",
                    )
                    continue
                killer_team = str(kill.get("killer_team") or "").strip().upper()
                if not killer_team or killer_team != objective_team:
                    reject(
                        "invalid_team",
                        "[Correlation] Kill %s -> objective %s rejected: INVALID_TEAM kill_team=%s objective_team=%s",
                        kill_id, objective_id, killer_team or "unknown", objective_team,
                    )
                    continue
                if delta > window:
                    reject("exceeded_time_window", "[Correlation] Kill %s -> objective %s rejected: EXCEEDED_TIME_WINDOW delta=%.1f window=%d", kill_id, objective_id, delta, window)
                    continue
                kill_participants = {
                    str(value).strip() for value in [
                        kill.get("killer_key"), *(kill.get("assister_keys") or []),
                    ] if value is not None and str(value).strip() not in {"", "0", "None"}
                }
                if finisher_id not in kill_participants:
                    reject(
                        "no_shared_participant",
                        "[Correlation] Kill %s -> objective %s rejected: NO_SHARED_PARTICIPANT participants=%s finisher=%s",
                        kill_id, objective_id, sorted(kill_participants), finisher_id,
                    )
                    continue
                key = (kill_id, objective_id)
                if key in seen:
                    diagnostics["duplicate"] += 1
                    logger.info("[Correlation] Duplicate relationship removed: kill=%s objective=%s", kill_id, objective_id)
                    continue
                seen.add(key)
                shared_champion = (
                    kill.get("killer_champion") if kill.get("killer_key") == finisher_id
                    else next((champion for assister, champion in zip(
                        kill.get("assister_keys") or [], kill.get("assister_champions") or []
                    ) if assister == finisher_id), None)
                )
                logger.info(
                    "[Correlation] Kill %s -> %s %s; participants=%s finisher=%s shared=%s result=ACCEPTED",
                    kill.get("time_label"), objective.get("objective"), objective.get("time"),
                    sorted(kill_participants), finisher_id, shared_champion or finisher_id,
                )
                diagnostics["accepted"] += 1
                validations.append({
                    "kill_event_id": kill_id,
                    "objective_event_id": objective_id,
                    "event_ids": [kill_id, objective_id],
                    "kill_time": kill.get("time_label"),
                    "objective_time": objective.get("time"),
                    "seconds_between": round(delta, 1),
                    "association_window_seconds": window,
                    "kill_participants": sorted(kill_participants),
                    "objective_finisher_id": finisher_id,
                    "shared_participant": shared_champion or finisher_id,
                    "kill_team_id": killer_team,
                    "objective_team_id": objective_team,
                    "objective": objective.get("objective"),
                    "objective_type": objective.get("type"),
                    "status": "accepted",
                    "validation": "verified_finisher_participated_in_kill",
                    "interpretation_limit": "Participante compartido y secuencia confirmados; no demuestra que la baja causara el objetivo.",
                })
        return validations, diagnostics

    @staticmethod
    def _validate_player_death_objective_correlations(
        kills: list[dict[str, Any]], objectives: list[dict[str, Any]],
        player_key: str, player_team: str,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Link a player's confirmed death to an objective secured by its enemy contributor."""
        relations: list[dict[str, Any]] = []
        diagnostics = {"accepted": 0, "rejected": 0, "duplicate": 0}
        seen: set[tuple[str, str]] = set()
        local_team = str(player_team or "").strip().upper()
        for death in kills:
            if death.get("victim_key") != player_key:
                continue
            death_id = str(death.get("event_id") or "")
            try:
                death_time = float(death.get("time_seconds"))
            except (TypeError, ValueError):
                diagnostics["rejected"] += 1
                logger.info("[Correlation] Death %s rejected: INVALID_TIMESTAMP", death_id or "unknown")
                continue
            killer_team = str(death.get("killer_team") or "").strip().upper()
            victim_team = str(death.get("victim_team") or "").strip().upper()
            if not local_team or victim_team != local_team or not killer_team or killer_team == local_team:
                diagnostics["rejected"] += 1
                logger.info(
                    "[Correlation] Player death %s rejected: INVALID_TEAMS player=%s killer=%s",
                    death_id or "unknown", victim_team or "unknown", killer_team or "unknown",
                )
                continue
            enemy_participants: set[str] = set()
            killer_id = str(death.get("killer_key") or "").strip()
            if killer_id not in {"", "0", "None"} and killer_team != local_team:
                enemy_participants.add(killer_id)
            assister_keys = death.get("assister_keys") or []
            assister_teams = death.get("assister_teams") or []
            for assister_id, assister_team in zip(assister_keys, assister_teams):
                participant_id = str(assister_id or "").strip()
                team_id = str(assister_team or "").strip().upper()
                if participant_id not in {"", "0", "None"} and team_id == killer_team and team_id != local_team:
                    enemy_participants.add(participant_id)
            if not enemy_participants:
                continue
            for objective in objectives:
                objective_id = str(objective.get("event_id") or "")
                try:
                    objective_time = float(objective.get("time_seconds"))
                except (TypeError, ValueError):
                    diagnostics["rejected"] += 1
                    logger.info(
                        "[Correlation] Death %s -> objective %s rejected: INVALID_TIMESTAMP",
                        death_id or "unknown", objective_id or "unknown",
                    )
                    continue
                delta = objective_time - death_time
                structure = objective.get("type") == "structure"
                window = 90 if structure else 120
                if not (0 < delta <= window):
                    continue
                finisher_id = str(objective.get("finisher_id") or "").strip()
                objective_team = str(objective.get("team_id") or "").strip().upper()
                finisher_team = str(objective.get("finisher_team") or "").strip().upper()
                if not finisher_id or finisher_id in {"0", "None"}:
                    diagnostics["rejected"] += 1
                    logger.info(
                        "[Correlation] Death %s -> objective %s rejected: MISSING_FINISHER",
                        death_id or "unknown", objective_id or "unknown",
                    )
                    continue
                if (
                    not objective_team or objective_team == local_team
                    or objective_team != killer_team or finisher_team != objective_team
                ):
                    diagnostics["rejected"] += 1
                    logger.info(
                        "[Correlation] Death %s -> objective %s rejected: INVALID_TEAM player=%s killer=%s objective=%s finisher=%s",
                        death_id or "unknown", objective_id or "unknown", local_team,
                        killer_team, objective_team or "unknown", finisher_team or "unknown",
                    )
                    continue
                if finisher_id not in enemy_participants:
                    diagnostics["rejected"] += 1
                    logger.info(
                        "[Correlation] Death %s -> objective %s rejected: NO_SHARED_ENEMY_PARTICIPANT participants=%s finisher=%s",
                        death_id or "unknown", objective_id or "unknown",
                        sorted(enemy_participants), finisher_id,
                    )
                    continue
                pair = (death_id, objective_id)
                if pair in seen:
                    diagnostics["duplicate"] += 1
                    continue
                seen.add(pair)
                finisher_name = (
                    death.get("killer_champion") if death.get("killer_key") == finisher_id
                    else next((champion for key, champion in zip(
                        death.get("assister_keys") or [], death.get("assister_champions") or []
                    ) if key == finisher_id), finisher_id)
                )
                relation = {
                    "correlation_id": f"death_objective:{death_id}:{objective_id}",
                    "relationship": "player_death_to_enemy_objective",
                    "death_event_id": death_id,
                    "objective_event_id": objective_id,
                    "event_ids": [death_id, objective_id],
                    "death_time": death.get("time_label"),
                    "objective_time": objective.get("time"),
                    "seconds_between": round(delta, 1),
                    "association_window_seconds": window,
                    "player_id": player_key,
                    "player_team_id": local_team,
                    "killer_id": killer_id,
                    "killer_name": death.get("killer_champion"),
                    "enemy_participant_ids": sorted(enemy_participants),
                    "objective_finisher_id": finisher_id,
                    "objective_finisher": finisher_name,
                    "objective": objective.get("objective"),
                    "objective_team_id": objective_team,
                    "objective_type": objective.get("type"),
                    "status": "accepted",
                    "validation": "player_victim_enemy_contributor_secured_objective",
                    "interpretation_limit": "La muerte y la captura posterior están confirmadas; la secuencia no demuestra por sí sola causalidad.",
                }
                relations.append(relation)
                diagnostics["accepted"] += 1
                logger.info(
                    "[Correlation] Player death %s -> enemy objective %s; killer=%s finisher=%s contributors=%s delta=%.1fs result=ACCEPTED",
                    death.get("time_label"), objective.get("objective"), killer_id,
                    finisher_id, sorted(enemy_participants), delta,
                )
        return relations, diagnostics

    @staticmethod
    def _key_event_candidates(
        events: list[dict[str, Any]], local_key: str, local_team: str,
        duration_seconds: Any = None, *,
        teamfights: list[dict[str, Any]] | None = None,
        objectives: list[dict[str, Any]] | None = None,
        kill_objective_correlations: list[dict[str, Any]] | None = None,
        fight_objective_correlations: list[dict[str, Any]] | None = None,
        player_death_objective_correlations: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Prepara hechos candidatos; la interpretacion no depende del modelo."""
        kills = MatchAnalysisEvidenceService._unique_takedowns(events)
        candidates: list[dict[str, Any]] = []
        try:
            duration = float(duration_seconds or 0)
        except (TypeError, ValueError):
            duration = 0
        for index, event in enumerate(kills):
            signals = []
            if index == 0:
                signals.append("first_recorded_kill")
            if duration > 0 and duration - float(event.get("time_seconds") or 0) <= 120:
                signals.append("late_game_kill")
            if event.get("bounty") == 700:
                local_participation = (
                    "secured" if event.get("killer_key") == local_key
                    else "assisted" if local_key in event.get("assister_keys", [])
                    else None
                )
                if local_participation:
                    candidates.append({
                        "candidate_type": "confirmed_700_shutdown",
                        "event_ids": [event.get("event_id")],
                        "time": event.get("time_label"),
                        "bounty": 700,
                        "player_participation": local_participation,
                        "killer_champion": event.get("killer_champion"),
                        "victim_champion": event.get("victim_champion"),
                        "local_player_involved": True,
                        "relevance": "high",
                    })
            if signals:
                candidates.append({
                    "candidate_type": "potential_swing_kill",
                    "event_ids": [event.get("event_id")],
                    "time": event.get("time_label"),
                    "killer_champion": event.get("killer_champion"),
                    "victim_champion": event.get("victim_champion"),
                    "local_player_involved": local_key in {
                        event.get("killer_key"), event.get("victim_key"),
                        *event.get("assister_keys", []),
                    },
                    "recorded_signals": signals,
                    "shutdown_or_bounty_value": event.get("bounty", event.get("gold_value")),
                })

        event_by_id = {
            str(event.get("event_id")): event for event in events
            if event.get("event_id")
        }
        objectives = objectives or MatchAnalysisEvidenceService._objectives(events)
        teamfights = teamfights or MatchAnalysisEvidenceService._teamfights(
            events, local_key, local_team
        )

        # Only emit objective conversions that passed the deterministic participant,
        # beneficiary-team and timestamp checks above.
        kill_correlations = [
            item for item in (kill_objective_correlations or [])
            if isinstance(item, dict) and item.get("status") == "accepted"
        ]
        fight_correlations = [
            item for item in (fight_objective_correlations or [])
            if isinstance(item, dict)
        ]
        covered_pairs: set[tuple[str, str]] = set()
        seen_candidates: set[tuple[str, tuple[str, ...]]] = set()
        for relation in fight_correlations:
            fight = next((item for item in teamfights if item.get("teamfight_id") == relation.get("fight_id")), None)
            objective = next((item for item in objectives if str(item.get("event_id")) == str(relation.get("objective_event_id"))), None)
            if not fight or not objective:
                continue
            kill_refs = [str(ref) for ref in fight.get("event_ids", []) if str(ref) in event_by_id]
            objective_ref = str(objective.get("event_id") or "")
            if not kill_refs or not objective_ref:
                continue
            refs = list(dict.fromkeys([*kill_refs, objective_ref]))
            key = ("combat_then_objective", tuple(refs))
            if key in seen_candidates:
                logger.info("[Timeline] Duplicate strategic candidate removed: %s", key)
                continue
            seen_candidates.add(key)
            covered_pairs.update((str(kill_id), objective_ref) for kill_id in relation.get("kill_event_ids", []))
            candidates.append({
                "candidate_type": "combat_then_objective",
                "event_ids": refs,
                "start_time": fight.get("start_time"),
                "end_time": objective.get("time"),
                "combat_kill_count": len(kill_refs),
                "objective": objective.get("objective"),
                "objective_team": objective.get("team"),
                "objective_finisher": objective.get("finisher"),
                "shared_participant": relation.get("shared_participant"),
                "seconds_between_last_kill_and_objective": relation.get("seconds_between_fight_end_and_objective"),
                "correlation_validation": relation.get("validation"),
                "interpretation_limit": relation.get("interpretation_limit"),
            })

        grouped_relations: dict[str, list[dict[str, Any]]] = {}
        for relation in kill_correlations:
            kill_ref = str(relation.get("kill_event_id") or "")
            objective_ref = str(relation.get("objective_event_id") or "")
            if kill_ref and objective_ref and (kill_ref, objective_ref) not in covered_pairs:
                grouped_relations.setdefault(objective_ref, []).append(relation)
        for objective_ref, relations in grouped_relations.items():
            objective = next((item for item in objectives if str(item.get("event_id")) == objective_ref), None)
            kill_refs = list(dict.fromkeys(
                str(item.get("kill_event_id")) for item in relations
                if str(item.get("kill_event_id")) in event_by_id
            ))
            if not objective or not kill_refs:
                continue
            refs = [*kill_refs, objective_ref]
            key = ("validated_kills_before_objective", tuple(refs))
            if key in seen_candidates:
                logger.info("[Timeline] Duplicate strategic candidate removed: %s", key)
                continue
            seen_candidates.add(key)
            latest_relation = min(relations, key=lambda item: float(item.get("seconds_between") or 0))
            candidates.append({
                "candidate_type": "validated_kills_before_objective",
                "event_ids": refs,
                "start_time": event_by_id[kill_refs[0]].get("time_label"),
                "end_time": objective.get("time"),
                "combat_kill_count": len(kill_refs),
                "objective": objective.get("objective"),
                "objective_team": objective.get("team"),
                "objective_finisher": objective.get("finisher"),
                "shared_participants": list(dict.fromkeys(
                    str(item.get("shared_participant")) for item in relations
                    if item.get("shared_participant")
                )),
                "seconds_between_last_kill_and_objective": latest_relation.get("seconds_between"),
                "correlation_validation": "verified_finisher_participated_in_each_linked_kill",
                "interpretation_limit": "La secuencia y los participantes compartidos estan confirmados; no demuestra causalidad.",
            })

        event_ids_with_death_objective = set()
        for relation in player_death_objective_correlations or []:
            if relation.get("status") != "accepted":
                continue
            refs = [str(ref) for ref in relation.get("event_ids", []) if str(ref) in event_by_id]
            if len(refs) != 2:
                continue
            correlation_id = str(relation.get("correlation_id") or f"death_objective:{refs[0]}:{refs[1]}")
            if correlation_id in event_ids_with_death_objective:
                continue
            event_ids_with_death_objective.add(correlation_id)
            death = event_by_id[refs[0]]
            objective = next((item for item in objectives if str(item.get("event_id")) == refs[1]), None)
            if objective is None:
                continue
            candidates.append({
                "candidate_type": "player_death_to_enemy_objective",
                "correlation_id": correlation_id,
                "event_ids": refs,
                "start_time": death.get("time_label"),
                "end_time": objective.get("time"),
                "seconds_between_death_and_objective": relation.get("seconds_between"),
                "death_killer": relation.get("killer_name"),
                "death_assisters": [
                    champion for key, champion in zip(
                        death.get("assister_keys") or [], death.get("assister_champions") or []
                    ) if key in relation.get("enemy_participant_ids", [])
                ],
                "objective": relation.get("objective"),
                "objective_finisher": relation.get("objective_finisher"),
                "objective_team": "Equipo rival",
                "enemy_participant_ids": relation.get("enemy_participant_ids", []),
                "correlation_validation": relation.get("validation"),
                "interpretation_limit": relation.get("interpretation_limit"),
                "relevance": "high",
            })

        # Captures remain individually available even without combat around them.
        for objective in objectives:
            if not objective.get("event_id"):
                continue
            candidates.append({
                "candidate_type": "objective_capture",
                "event_ids": [objective["event_id"]],
                "time": objective.get("time"),
                "objective": objective.get("objective"),
                "objective_team": objective.get("team"),
                "objective_team_id": objective.get("team_id"),
                "objective_type": objective.get("type"),
                "team_source": objective.get("team_source"),
            })

        # Opposing captures close in time are a possible map trade, never intent proof.
        for index, first in enumerate(objectives):
            if first.get("team") not in {"Equipo aliado", "Equipo rival"}:
                continue
            for second in objectives[index + 1:]:
                gap = float(second.get("time_seconds") or 0) - float(first.get("time_seconds") or 0)
                if gap > 120:
                    break
                if second.get("team") not in {"Equipo aliado", "Equipo rival"} or second.get("team") == first.get("team"):
                    continue
                candidates.append({
                    "candidate_type": "objective_trade_candidate",
                    "event_ids": [first.get("event_id"), second.get("event_id")],
                    "start_time": first.get("time"), "end_time": second.get("time"),
                    "objectives": [first.get("objective"), second.get("objective")],
                    "teams": [first.get("team"), second.get("team")],
                    "seconds_apart": round(gap),
                    "interpretation_limit": "Capturas cercanas de equipos distintos; no confirma un intercambio intencional.",
                })

        structures = [item for item in objectives if item.get("type") == "structure"]
        for index, first in enumerate(structures):
            group = [first]
            for second in structures[index + 1:]:
                if float(second.get("time_seconds") or 0) - float(group[-1].get("time_seconds") or 0) > 120:
                    break
                group.append(second)
            if len(group) > 1:
                candidates.append({
                    "candidate_type": "consecutive_structure_captures",
                    "event_ids": [item.get("event_id") for item in group],
                    "start_time": group[0].get("time"), "end_time": group[-1].get("time"),
                    "structure_count": len(group), "teams": [item.get("team") for item in group],
                    "interpretation_limit": "Estructuras registradas en 120 s; no confirma una causa compartida.",
                })

        for fight in teamfights:
            refs = [str(ref) for ref in fight.get("event_ids", []) if str(ref) in event_by_id]
            if len(refs) < 4 or not fight.get("local_player_involved"):
                continue
            allied_kills = sum(
                str(event_by_id[ref].get("killer_team") or "").upper() == str(local_team or "").upper()
                for ref in refs
            ) if local_team else None
            candidates.append({
                "candidate_type": "teamfight_cluster",
                "event_ids": refs,
                "start_time": fight.get("start_time"),
                "end_time": fight.get("end_time"),
                "combat_kill_count": len(refs),
                "classification": fight.get("classification"),
                "allied_deaths": fight.get("allied_deaths"),
                "enemy_deaths": fight.get("enemy_deaths"),
                "participants": fight.get("participants", []),
                "local_player_involved": fight.get("local_player_involved"),
                "player_kills": fight.get("player_kills", 0),
                "player_assists": fight.get("player_assists", 0),
                "player_deaths": fight.get("player_deaths", 0),
                "team_kill_counts": {
                    "local": allied_kills,
                    "enemy": len(refs) - allied_kills if allied_kills is not None else None,
                },
                "interpretation_limit": "Cuatro o mas bajas con intervalos consecutivos menores de 30 s y duracion maxima de 120 s; es un combate agrupado, no prueba por si solo una pelea de equipo ni causalidad posterior.",
            })

        candidates.sort(key=lambda item: (
            0 if item.get("candidate_type") == "teamfight_cluster" else
            1 if item.get("candidate_type") in {"combat_then_objective", "single_kill_before_objective", "validated_kills_before_objective"} else
            2 if item.get("candidate_type") == "player_death_to_enemy_objective" else
            3 if item.get("candidate_type") in {"objective_trade_candidate", "consecutive_structure_captures"} else 4,
            float(event_by_id.get(str((item.get("event_ids") or [None])[0]), {}).get("time_seconds") or 0),
        ))
        for candidate in candidates:
            kind = candidate.get("candidate_type")
            refs = [str(ref) for ref in candidate.get("event_ids", [])]
            objective_names = " ".join(
                str(event_by_id.get(ref, {}).get("objective") or "") for ref in refs
            ).casefold()
            important_objective = any(
                token in objective_names
                for token in ("baron", "elder", "nashor", "inhibitor", "nexus", "barón")
            )
            count = int(candidate.get("combat_kill_count") or 0)
            if important_objective or (
                kind == "teamfight_cluster" and count >= 5
                and isinstance(candidate.get("allied_deaths"), int)
                and isinstance(candidate.get("enemy_deaths"), int)
                and abs(candidate["allied_deaths"] - candidate["enemy_deaths"]) >= 2
            ) or "recorded_shutdown_or_bounty" in candidate.get("recorded_signals", []):
                candidate["relevance"] = "high"
            elif kind in {
                "teamfight_cluster", "combat_then_objective", "single_kill_before_objective", "validated_kills_before_objective",
                "objective_trade_candidate", "consecutive_structure_captures",
            } or kind == "objective_capture" and any(
                token in objective_names for token in ("dragon", "herald", "horde", "rift")
            ):
                candidate["relevance"] = "medium"
            else:
                candidate["relevance"] = "low"
        return candidates[:120]

    def _threat_indicators(
        self,
        enemies: list[dict[str, Any]],
        events: list[dict[str, Any]],
        local_key: str,
    ) -> list[dict[str, Any]]:
        """Calcula indicadores relativos usando KDA y eventos del jugador local."""
        resultado = []
        for enemy in enemies:
            champion = enemy.get("champion_name")
            interacciones = [
                evento
                for evento in events
                if evento.get("killer_champion") == champion
                and evento.get("victim_key") == "player_local"
            ]
            resultado.append(
                {
                    "champion_id": enemy.get("champion_id"),
                    "champion_name": champion,
                    "role": enemy.get("role"),
                    "kills": enemy.get("kda", {}).get("kills"),
                    "deaths": enemy.get("kda", {}).get("deaths"),
                    "assists": enemy.get("kda", {}).get("assists"),
                    "kills_on_player": len(interacciones),
                    "evidence_type": "derived",
                }
            )
        return resultado

    def _ability_catalog(
        self, enemies: list[dict[str, Any]], game_version: str
    ) -> list[dict[str, Any]]:
        """Incluye habilidades del catálogo local con parche y descripción."""
        catalog = []
        for enemy in enemies:
            champion_id = enemy.get("champion_id")
            if not champion_id:
                continue
            path = DATA_DIR / "champion_abilities" / f"{champion_id}.json"
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            champion = document.get("data", {}).get(champion_id, {})
            spells = champion.get("spells", [])
            catalog.append(
                {
                    "champion_id": champion_id,
                    "champion_name": enemy.get("champion_name"),
                    "catalog_patch": document.get("version"),
                    "compatible_with_match_patch": (
                        not game_version or game_version == document.get("version")
                    ),
                    "abilities": [
                        {
                            "slot": "QWER"[index],
                            "name": spell.get("name"),
                            "description": re.sub(
                                r"<[^>]+>",
                                " ",
                                str(spell.get("description") or ""),
                            ).replace("\n", " ")[:1400],
                            "image": spell.get("image", {}).get("full"),
                        }
                        for index, spell in enumerate(spells[:4])
                        if isinstance(spell, dict)
                    ],
                }
            )
        return catalog

    @staticmethod
    def _load_item_catalog() -> dict[str, Any]:
        """Lee el catálogo Data Dragon local sin realizar peticiones de red."""
        try:
            return json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _item_catalog(items: Any) -> list[dict[str, Any]]:
        """Resuelve nombres, efectos, precio y estadísticas del catálogo local."""
        catalog = MatchAnalysisEvidenceService._load_item_catalog()
        catalog_items = catalog.get("items", {})
        resultado = []
        for raw_id in items if isinstance(items, list) else []:
            item_id = str(raw_id)
            item = catalog_items.get(item_id)
            if not isinstance(item, dict):
                continue
            resultado.append(
                {
                    "item_id": item_id,
                    "name": item.get("name_es") or item.get("name"),
                    "description": re.sub(
                        r"<[^>]+>",
                        " ",
                        str(
                            item.get("description_es") or item.get("description") or ""
                        ),
                    ),
                    "stats": item.get("stats", {}),
                    "tags": item.get("tags", []),
                    "gold_total": item.get("gold", {}).get("total"),
                    "purchasable": item.get("gold", {}).get("purchasable"),
                    "available_on_summoners_rift": item.get("maps", {}).get("11"),
                }
            )
        return resultado

    @staticmethod
    def _item_option_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
        """Expose a bounded, patch-local pool of legal SR items for matchup advice."""
        items = catalog.get("items", {}) if isinstance(catalog, dict) else {}
        if not isinstance(items, dict):
            return []
        useful_tags = {
            "Damage", "CriticalStrike", "Lethality", "ArmorPenetration", "AttackSpeed",
            "LifeSteal", "Health", "Armor", "SpellBlock", "MagicResist", "Tenacity",
        }
        options = []
        for item_id, item in items.items():
            if not isinstance(item, dict):
                continue
            gold = item.get("gold", {})
            maps = item.get("maps", {})
            tags = item.get("tags", [])
            if not (
                isinstance(gold, dict) and gold.get("purchasable") is True
                and isinstance(gold.get("total"), (int, float)) and gold.get("total", 0) > 0
                and isinstance(maps, dict) and maps.get("11") is True
                and useful_tags.intersection(tags if isinstance(tags, list) else [])
            ):
                continue
            options.append({
                "item_id": str(item_id),
                "name": item.get("name_es") or item.get("name"),
                "stats": item.get("stats", {}),
                "tags": tags,
                "gold_total": gold.get("total"),
                "recipe_from": item.get("from", []),
            })
        return sorted(options, key=lambda entry: int(entry["item_id"]))[:200]

    @staticmethod
    def _item_id_from_event(evento: dict[str, Any]) -> str | None:
        """Extrae el identificador de objeto si el evento lo contiene."""
        for campo in ("item_id", "itemId", "item"):
            valor = evento.get(campo)
            if isinstance(valor, (int, str)) and str(valor).isdigit():
                return str(valor)
        coincidencia = re.search(
            r"\b(?:Objeto|Item)\s+(\d+)\b",
            str(evento.get("label") or ""),
            re.IGNORECASE,
        )
        return coincidencia.group(1) if coincidencia else None

    @staticmethod
    @lru_cache(maxsize=256)
    def _canonical_champion_id(champion_name: str) -> str | None:
        """Resuelve el nombre mostrado al identificador canónico local."""
        from app.services.identidad_campeon import cargar_indice_campeones
        return cargar_indice_campeones().resolve(champion_name)
