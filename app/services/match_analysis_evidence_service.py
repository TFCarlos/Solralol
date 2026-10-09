"""Extrae evidencia reproducible de una partida guardada para el análisis IA."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from _paths import DATA_DIR


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
        eventos = match_log.get("events_chronology", [])
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
        return {
            "evidence_version": 1,
            "source": "SOLRALOL_match_log",
            "coverage": {
                "participants": len(participantes),
                "events": len(hechos_eventos),
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
                        "damage_taken",
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
            "enemy_threat_indicators": amenazas,
            "ability_catalog": self._ability_catalog(
                enemigos, str(metadata.get("game_version") or "")
            ),
            "item_catalog": self._item_catalog(usuario.get("items", [])),
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
        categoria = (
            "kill"
            if "kill" in tipo or "death" in tipo
            else "purchase"
            if "item_purchased" in tipo or "purchase" in tipo
            else "structure"
            if any(
                texto in tipo or texto in str(evento.get("objective") or "").casefold()
                for texto in ("tower", "inhibitor", "structure", "inhibidor", "torre")
            )
            else "objective"
            if "objective" in tipo or evento.get("objective")
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
                "label",
                "objective",
                "item_name",
            )
            if evento.get(clave) is not None
        }
        resultado["category"] = categoria
        resultado["event_id"] = f"event-{evento.get('order', 'unknown')}"
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
        asistentes_origen = [str(clave) for clave in evento.get("assister_keys", [])]
        asistentes = [aliases.get(clave, "") for clave in asistentes_origen]
        asistentes = [clave for clave in asistentes if clave]
        resultado["assister_keys"] = asistentes
        resultado["assister_champions"] = [
            jugadores.get(clave, {}).get("champion")
            for clave in asistentes_origen
            if jugadores.get(clave, {}).get("champion")
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
            objetivo = evento.get("objective") or "objetivo no especificado"
            return f"El {evento.get('team_label') or 'equipo no identificado'} aseguró {objetivo}."
        if categoria == "structure":
            return f"El {evento.get('team_label') or 'equipo no identificado'} destruyó una estructura."
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
    def _resumen_puntuacion(puntuacion: Any, clave_local: str) -> dict[str, Any] | None:
        """Conserva el resultado oficial local sin incluir identidades ajenas."""
        if not isinstance(puntuacion, dict):
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
        return [
            evento
            for evento in eventos
            if evento.get("category") in {"kill", "objective", "structure"}
            or (
                evento.get("category") == "purchase"
                and evento.get("player_key") == clave_local
            )
        ]

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
        if not champion_name:
            return None
        normalizar = lambda valor: re.sub(
            r"[^a-z0-9]", "", valor.casefold().encode("ascii", "ignore").decode()
        )
        buscado = normalizar(champion_name)
        carpeta = DATA_DIR / "champion_abilities"
        for ruta in carpeta.glob("*.json"):
            if normalizar(ruta.stem) == buscado:
                return ruta.stem
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            campeones = datos.get("data", {})
            if isinstance(campeones, dict):
                for clave, campeon in campeones.items():
                    if normalizar(str(campeon.get("name") or "")) == buscado:
                        return str(campeon.get("id") or clave)
        return None
