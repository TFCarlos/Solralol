from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests

from _paths import DATA_DIR
from app.services.lcu_service import LCUService
from app.services.live_player_metrics_service import ROLE_ALIASES

logger = logging.getLogger(__name__)


def _log_home_history_summary(matches: list[dict[str, Any]]) -> None:
    """Registra cobertura agregada del historial sin datos personales."""
    states = Counter(
        str(
            match.get("opponent_state")
            or (match.get("opponent_resolution") or {}).get("state")
            or ("exact" if _opponent_confidence(match) >= 0.75 else "unavailable")
        )
        for match in matches
    )
    resolved = [match for match in matches if _opponent_confidence(match) >= 0.75]
    teammate_matches = [match for match in matches if match.get("teammates")]
    teammate_ids = {
        str(teammate.get("stable_player_id") or "")
        for match in teammate_matches
        for teammate in match.get("teammates", [])
        if teammate.get("stable_player_id")
    }
    matchup_ids = {
        str(
            (match.get("opponent_resolution") or {}).get("champion_id")
            or (match.get("opponent") or {}).get("champion_id")
            or match.get("opponent_champion_id")
        )
        for match in resolved
        if (match.get("opponent_resolution") or {}).get("champion_id")
        or (match.get("opponent") or {}).get("champion_id")
        or match.get("opponent_champion_id")
    }
    logger.info("[home] history=%s", len(matches))
    logger.info(
        "[home] opponent coverage: total=%s exact=%s probable=%s ambiguous=%s unavailable=%s",
        len(matches),
        states["exact"],
        states["probable"],
        states["ambiguous"],
        states["unavailable"],
    )
    logger.info("[home] teammate matches=%s", len(teammate_matches))
    logger.info("[home] unique teammates=%s", len(teammate_ids))
    logger.info("[home] matchup champions=%s", len(matchup_ids))


def _response_shape(payload: Any) -> str:
    """Resume el tipo y las claves de una respuesta sin registrar datos personales."""
    if isinstance(payload, dict):
        return f"object:{','.join(sorted(str(key) for key in payload)[:12])}"
    if isinstance(payload, list):
        return f"array:{len(payload)}"
    return type(payload).__name__


def _sanitize_lcu_route(endpoint: str) -> str:
    """Oculta identificadores variables al registrar una ruta local."""
    route = re.sub(r"/inventories/[^/]+", "/inventories/{summonerId}", endpoint)
    route = re.sub(
        r"/products/lol/[^/]+/matches", "/products/lol/{puuid}/matches", route
    )
    return re.sub(r"/games/[^/?]+", "/games/{gameId}", route)


class HomeHistoryRepository:
    """Persiste perfiles locales y su historial recordado por cuenta."""

    SCHEMA_VERSION = 1

    def __init__(self, root: Path | None = None) -> None:
        """Inicializa el almacén; root permite aislar datos en pruebas."""
        self.root = root or (Path.home() / ".solralol" / "profiles")

    @staticmethod
    def account_key(profile: dict[str, Any]) -> str:
        """Devuelve una clave estable derivada del identificador local de cuenta."""
        stable_id = str(profile.get("puuid") or profile.get("summonerId") or "").strip()
        if not stable_id:
            raise ValueError("El cliente no proporcionó un identificador estable.")
        return hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:24]

    def load(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Lee el historial de una cuenta o devuelve un documento vacío."""
        key = self.account_key(profile)
        path = self.root / key / "match_history.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "schema_version": self.SCHEMA_VERSION,
                "profile_id": key,
                "last_sync": None,
                "matches": [],
            }
        if not isinstance(data, dict):
            raise TypeError("El historial local tiene un formato incompatible.")
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(
                "La versión del historial local no es compatible; se conserva intacto."
            )
        matches = data.get("matches", [])
        if not isinstance(matches, list) or any(
            not isinstance(match, dict) for match in matches
        ):
            raise TypeError(
                "La lista de partidas local está dañada; se conserva intacta."
            )
        return {
            "schema_version": self.SCHEMA_VERSION,
            "profile_id": key,
            "last_sync": data.get("last_sync"),
            "matches": matches,
        }

    def load_last_profile(self) -> dict[str, Any] | None:
        """Devuelve el perfil de la última cuenta sincronizada localmente."""
        try:
            roots = sorted(
                self.root.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True
            )
        except OSError:
            return None
        for directory in roots:
            path = directory / "profile.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and (data.get("puuid") or data.get("summonerId")):
                return data
        return None

    def merge(
        self, profile: dict[str, Any], matches: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Fusiona partidas por ID o huella y guarda el resultado atómicamente."""
        data = self.load(profile)
        index = {
            m.get("stable_match_id"): m
            for m in data["matches"]
            if m.get("stable_match_id")
        }
        for match in matches:
            match_id = str(match.get("stable_match_id") or "").strip()
            if not match_id:
                continue
            previous = index.get(match_id)
            if previous is None:
                data["matches"].append(match)
                index[match_id] = match
            else:
                incoming_enrichment = match.get("enrichment") or {}
                previous_enrichment = previous.get("enrichment") or {}
                incoming_participants = match.get("participants") or []
                previous_participants = previous.get("participants") or []
                detalle_autoritativo = bool(
                    incoming_enrichment.get("detail_attempted")
                    and len(incoming_participants) > 1
                    and len(incoming_participants) >= len(previous_participants)
                )
                resolucion_actualizada = bool(
                    int(incoming_enrichment.get("opponent_resolver_version") or 0) >= 3
                    and incoming_participants
                )
                campos_detalle = {
                    "participants",
                    "teammates",
                }
                campos_rival = {
                    "opponent",
                    "enemy_team",
                    "opponent_resolution",
                    "opponent_state",
                    "opponent_champion_id",
                    "opponent_champion_name",
                }
                for key, value in match.items():
                    if value in (None, "", [], {}):
                        continue
                    if (
                        key in campos_detalle
                        and (
                            len(previous_participants) > len(incoming_participants)
                            or previous_enrichment.get("participants_complete")
                            or previous_enrichment.get("detail_attempted")
                        )
                        and not detalle_autoritativo
                    ):
                        continue
                    if (
                        key in campos_rival
                        and not detalle_autoritativo
                        and not resolucion_actualizada
                    ):
                        continue
                    if key == "enrichment":
                        if (
                            detalle_autoritativo
                            or resolucion_actualizada
                            or not previous_enrichment
                        ):
                            previous[key] = {
                                **previous_enrichment,
                                **incoming_enrichment,
                            }
                        continue
                    previous[key] = value
        data["matches"].sort(
            key=lambda match: str(match.get("started_at") or ""), reverse=True
        )
        data["last_sync"] = datetime.now(UTC).isoformat()
        path = self.root / data["profile_id"] / "match_history.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        profile_path = path.parent / "profile.json"
        profile_temporal = profile_path.with_name(
            f".{profile_path.name}.{os.getpid()}.tmp"
        )
        profile_temporal.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(profile_temporal, profile_path)
        temporal = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temporal.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporal, path)
        return data

    def clear(self, profile: dict[str, Any]) -> None:
        """Elimina exclusivamente el historial recordado de la cuenta indicada."""
        path = self.root / self.account_key(profile) / "match_history.json"
        try:
            path.unlink()
        except FileNotFoundError:
            pass


class LCUHomeProvider:
    """Lee y normaliza cuenta e historial recientes desde el League Client."""

    def __init__(self, cliente: LCUService | None = None) -> None:
        """Usa el cliente LCU existente o crea una instancia propia."""
        self.cliente = cliente or LCUService()

    def synchronize(
        self, repository: HomeHistoryRepository, on_progress: Any = None
    ) -> dict[str, Any]:
        """Lee cuenta e historial LCU y los fusiona con el historial local."""
        if not self.cliente.refresh_connection():
            raise ConnectionError("League no está conectado.")
        profile = self._get("/lol-summoner/v1/current-summoner")
        if not isinstance(profile, dict) or not (
            profile.get("puuid") or profile.get("summonerId")
        ):
            raise ValueError("El cliente no devolvió un perfil reconocible.")
        profile = {
            "puuid": str(profile.get("puuid") or ""),
            "summonerId": str(profile.get("summonerId") or ""),
            "accountId": str(profile.get("accountId") or ""),
            "gameName": str(
                profile.get("gameName") or profile.get("displayName") or "Invocador"
            ),
            "tagLine": str(profile.get("tagLine") or ""),
            "summonerLevel": profile.get("summonerLevel"),
            "profileIconId": profile.get("profileIconId"),
            "region": str(profile.get("region") or profile.get("platformId") or ""),
        }
        try:
            ranked = self._get("/lol-ranked/v1/current-ranked-stats")
        except RuntimeError:
            ranked = None
        profile["ranked"] = self._ranked_snapshot(ranked)
        account = profile.get("puuid") or profile["summonerId"]
        history = self._get(
            f"/lol-match-history/v1/products/lol/{account}/matches?begIndex=0&endIndex=100"
        )
        games = (
            history.get("games", {}).get("games", [])
            if isinstance(history, dict)
            else []
        )
        previous = {
            str(match.get("game_id") or match.get("stable_match_id")): match
            for match in repository.load(profile)["matches"]
        }
        matches = []
        for old_match in previous.values():
            refreshed = self._refresh_stored_opponent(old_match, profile)
            if refreshed:
                matches.append(old_match)
        matches = [
            *matches,
            *[
                self._normalize(
                    game,
                    profile,
                    previous.get(str(game.get("gameId") or game.get("gameID") or "")),
                )
                for game in games
                if isinstance(game, dict)
            ],
        ]
        matches = [match for match in matches if match]
        pending = []
        summary_by_id = {str(match.get("game_id") or ""): match for match in matches}
        for game in games:
            if not isinstance(game, dict):
                continue
            game_id = str(game.get("gameId") or game.get("gameID") or "")
            if not game_id:
                continue
            old_match = previous.get(game_id) or summary_by_id.get(game_id, {})
            enrichment = old_match.get("enrichment") or {}
            summary_match = summary_by_id.get(game_id, {})
            has_complete_participants = bool(
                enrichment.get("participants_complete")
                or (summary_match.get("enrichment") or {}).get("participants_complete")
            )
            has_resolved_opponent = _opponent_confidence(old_match) >= 0.75 or (
                _opponent_confidence(summary_match) >= 0.75
            )
            if has_complete_participants and has_resolved_opponent:
                continue
            migrated_resolver = (
                int(enrichment.get("opponent_resolver_version") or 0) >= 4
            )
            requires_resolver_migration = (
                not has_resolved_opponent and not migrated_resolver
            )
            if (
                enrichment.get("detail_attempted")
                and not requires_resolver_migration
                and not self._retry_enrichment(enrichment)
            ):
                continue
            pending.append((game, game_id))
        for index, (game, game_id) in enumerate(pending, 1):
            old_match = previous.get(game_id) or summary_by_id.get(game_id, {})
            if callable(on_progress):
                on_progress(
                    index,
                    len(pending),
                    f"Enriqueciendo historial · {index}/{len(pending)}",
                )
            try:
                detail = self._get(f"/lol-match-history/v1/games/{game_id}")
            except (RuntimeError, ConnectionError):
                logger.debug(
                    "[home] el detalle ampliado de una partida no está disponible"
                )
                normalized = self._normalize(game, profile, old_match)
                if normalized:
                    normalized["enrichment"] = {
                        "detail_attempted": True,
                        "participants_complete": False,
                        "opponent_resolver_version": 4,
                        "teammates_resolved": len(normalized.get("teammates", [])) == 4,
                        "opponent_resolved": bool(normalized.get("opponent")),
                        "checked_at": datetime.now(UTC).isoformat(),
                    }
                    matches.append(normalized)
                continue
            normalized = self._normalize(detail, profile, old_match)
            if normalized:
                normalized["enrichment"] = {
                    "detail_attempted": True,
                    "participants_complete": len(normalized.get("participants", []))
                    == 10,
                    "opponent_resolver_version": 4,
                    "teammates_resolved": len(normalized.get("teammates", [])) == 4,
                    "opponent_resolved": bool(normalized.get("opponent")),
                    "checked_at": datetime.now(UTC).isoformat(),
                }
                matches.append(normalized)
        try:
            stored_profile = json.loads(
                (
                    repository.root / repository.account_key(profile) / "profile.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            stored_profile = {}
        cached_collection = (
            stored_profile.get("collection", {})
            if isinstance(stored_profile, dict)
            else {}
        )
        collection = cached_collection if isinstance(cached_collection, dict) else {}
        profile["collection"] = collection
        merged_history = repository.merge(profile, matches)
        _log_home_history_summary(merged_history.get("matches", []))
        return {
            "profile": profile,
            "history": merged_history,
            "collection": collection,
            "connection": "conectado",
        }

    @classmethod
    def _refresh_stored_opponent(
        cls, match: dict[str, Any], profile: dict[str, Any]
    ) -> bool:
        """Resuelve localmente rivales heredados a partir de participantes guardados."""
        participants = match.get("participants")
        if not isinstance(participants, list) or not participants:
            return False
        local = None
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            if any(
                participant.get(key)
                and str(participant.get(key)) == str(profile.get(profile_key) or "")
                for key, profile_key in (
                    ("puuid", "puuid"),
                    ("account_id", "accountId"),
                    ("summoner_id", "summonerId"),
                )
            ):
                local = participant
                break
        if local is None and match.get("champion_id") is not None:
            local_candidates = [
                participant
                for participant in participants
                if isinstance(participant, dict)
                and str(participant.get("champion_id")) == str(match.get("champion_id"))
                and participant.get("team_id") is not None
            ]
            if len(local_candidates) == 1:
                local = local_candidates[0]
        if local is None:
            return False
        resolution = cls._resolve_opponent(
            [item for item in participants if isinstance(item, dict)],
            local,
            match,
            str(match.get("game_id") or ""),
        )
        match["enemy_team"] = cls._enemy_team(participants, local.get("team_id"))
        match["opponent_state"] = resolution.get("state", "unavailable")
        if resolution.get("confidence", 0) >= 0.55:
            cls._store_opponent_resolution(match, resolution)
        else:
            match["opponent_resolution"] = resolution
            match["opponent"] = None
            match["opponent_champion_id"] = None
            match["opponent_champion_name"] = ""
        enrichment = match.setdefault("enrichment", {})
        if resolution.get("confidence", 0) >= 0.75 or len(participants) >= 10:
            enrichment["opponent_resolver_version"] = 4
        enrichment["opponent_resolved"] = resolution.get("confidence", 0) >= 0.75
        return True

    @staticmethod
    def _enemy_team(
        participants: list[dict[str, Any]], local_team: Any
    ) -> list[dict[str, Any]]:
        """Resume campeones del equipo contrario sin asignarles rival directo."""
        metadatos = _local_champion_metadata()
        rivales = [
            participante
            for participante in participants
            if isinstance(participante, dict)
            and local_team is not None
            and participante.get("team_id") not in (None, local_team)
            and participante.get("champion_id") is not None
        ]
        rivales.sort(
            key=lambda participante: (
                participante.get("participant_id") is None,
                LCUHomeProvider._integer(participante.get("participant_id")),
            )
        )
        return [
            {
                "champion_id": participante.get("champion_id"),
                "champion_name": str(
                    participante.get("champion_name")
                    or metadatos.get(str(participante.get("champion_id")), {}).get(
                        "name"
                    )
                    or ""
                ),
            }
            for participante in rivales
        ]

    @staticmethod
    def _store_opponent_resolution(
        match: dict[str, Any], resolution: dict[str, Any]
    ) -> None:
        """Actualiza campos compatibles del rival y persiste la confianza obtenida."""
        match["opponent_resolution"] = resolution
        match["opponent"] = {
            "champion_id": resolution.get("champion_id"),
            "champion_name": resolution.get("champion_name") or "",
            "lane": resolution.get("lane") or match.get("lane"),
            "puuid": resolution.get("puuid"),
        }
        match["opponent_champion_id"] = resolution.get("champion_id")
        match["opponent_champion_name"] = resolution.get("champion_name") or ""

    @staticmethod
    def _retry_enrichment(enrichment: dict[str, Any]) -> bool:
        """Permite reintentar detalles incompletos después de siete días."""
        try:
            checked = datetime.fromisoformat(
                str(enrichment.get("checked_at", "")).replace("Z", "+00:00")
            )
        except ValueError:
            return True
        return (datetime.now(UTC) - checked).days >= 7

    def synchronize_collection(
        self, profile: dict[str, Any], repository: HomeHistoryRepository
    ) -> dict[str, Any]:
        """Actualiza módulos opcionales y conserva la última respuesta válida."""
        collection = (
            self._load_collection(profile)
            if self.cliente.refresh_connection()
            else {
                "masteries": None,
                "champions": None,
                "skins": None,
                "challenges": None,
                "titles": None,
            }
        )
        try:
            stored_profile = json.loads(
                (
                    repository.root / repository.account_key(profile) / "profile.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            stored_profile = {}
        cached = (
            stored_profile.get("collection", {})
            if isinstance(stored_profile, dict)
            else {}
        )
        if isinstance(cached, dict):
            for category, value in collection.items():
                if value is None and cached.get(category) is not None:
                    collection[category] = cached[category]
        updated_profile = dict(profile)
        updated_profile["collection"] = collection
        repository.merge(updated_profile, [])
        return collection

    def _load_collection(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Consulta por separado maestría, campeones, skins y desafíos locales."""
        summoner_id = str(profile.get("summonerId") or "")
        routes = {
            "masteries": [
                f"/lol-collections/v1/inventories/{summoner_id}/champion-mastery/top?limit=3",
                "/lol-champion-mastery/v1/local-player/champion-mastery",
            ],
            "champions": [
                f"/lol-champions/v1/inventories/{summoner_id}/champions",
                f"/lol-champions/v1/inventories/{summoner_id}/champions-minimal",
                "/lol-champions/v1/owned-champions-minimal",
            ],
            "skins": [f"/lol-champions/v1/inventories/{summoner_id}/skins-minimal"],
            "challenges": [
                "/lol-challenges/v1/summary-player-data/local-player",
                "/lol-challenges/v1/challenges/local-player",
                "/lol-challenges/v1/level-points",
            ],
            "titles": ["/lol-challenges/v2/titles/local-player"],
        }
        output: dict[str, Any] = {}
        for category, endpoints in routes.items():
            output[category] = None
            for endpoint in endpoints:
                if "{summonerId}" in endpoint or (
                    "/inventories/" in endpoint and not summoner_id
                ):
                    continue
                try:
                    payload = self._get(endpoint)
                except (RuntimeError, ConnectionError):
                    continue
                normalized = self._normalize_collection(category, payload)
                if normalized is not None:
                    output[category] = normalized
                    break
        challenge_data = output.get("challenges")
        if (
            isinstance(challenge_data, dict)
            and isinstance(output.get("titles"), dict)
            and not output["titles"].get("selected")
        ):
            output["titles"]["selected"] = challenge_data.get("title")
        total = None
        if summoner_id:
            try:
                total = self._normalize_collection(
                    "champion_total",
                    self._get(
                        f"/lol-champions/v1/inventories/{summoner_id}/champions-playable-count"
                    ),
                )
            except (RuntimeError, ConnectionError):
                pass
        if isinstance(output.get("champions"), dict):
            output["champions"]["total_count"] = total or output["champions"].get(
                "total_count"
            )
        return output

    @staticmethod
    def _normalize_collection(category: str, payload: Any) -> Any:
        """Reduce las respuestas variables de colección a datos presentables."""
        if category == "masteries":
            entries = (
                payload.get("championMasteries", payload)
                if isinstance(payload, dict)
                else payload
            )
            if not isinstance(entries, list):
                return None
            if not entries:
                return []
            return sorted(
                [
                    {
                        "champion_id": item.get("championId"),
                        "points": LCUHomeProvider._ranked_integer(
                            item.get("championPoints")
                        )
                        or 0,
                        "level": LCUHomeProvider._ranked_integer(
                            item.get("championLevel")
                        ),
                    }
                    for item in entries
                    if isinstance(item, dict) and item.get("championId") is not None
                ],
                key=lambda item: item["points"],
                reverse=True,
            )[:3]
        if category in {"champions", "skins"}:
            entries = (
                payload
                if isinstance(payload, list)
                else payload.get("champions", payload.get("skins", []))
                if isinstance(payload, dict)
                else []
            )
            if not isinstance(entries, list):
                return None
            owned = []
            has_ownership = False
            for item in entries:
                if not isinstance(item, dict):
                    continue
                ownership = item.get("ownership")
                is_owned = item.get(
                    "owned",
                    ownership.get("owned", False)
                    if isinstance(ownership, dict)
                    else False,
                )
                has_ownership = (
                    has_ownership
                    or isinstance(item.get("owned"), bool)
                    or isinstance(ownership, dict)
                    and isinstance(ownership.get("owned"), bool)
                )
                excluded = any(
                    item.get(key) is True
                    for key in (
                        "isBase",
                        "isBaseSkin",
                        "isRental",
                        "rental",
                        "isPreview",
                        "isChroma",
                    )
                )
                if is_owned and not excluded:
                    owned.append(item)
            if entries and not has_ownership:
                return None
            return {
                "owned_count": len(owned),
                "total_count": len(entries) if category == "champions" else None,
            }
        if category == "champion_total":
            if isinstance(payload, dict):
                payload = payload.get("count") or payload.get("playableChampionCount")
            return LCUHomeProvider._ranked_integer(payload)
        if category == "challenges" and isinstance(payload, (int, float)):
            return {"count": None, "points": int(payload)}
        if category == "challenges" and isinstance(payload, dict):
            challenges = payload.get("challenges")
            total_points = payload.get("totalPoints") or payload.get("challengePoints")
            category_progress = payload.get("categoryProgress")
            score = payload.get("totalChallengeScore")
            title = payload.get("title")
            if isinstance(title, dict):
                title = title.get("name")
            if (
                isinstance(challenges, list)
                or isinstance(total_points, dict)
                or score is not None
                or payload.get("overallChallengeLevel")
            ):
                return {
                    "count": len(challenges)
                    if isinstance(challenges, list)
                    else len(category_progress)
                    if isinstance(category_progress, list)
                    else None,
                    "points": total_points.get(
                        "current", total_points.get("totalPoints")
                    )
                    if isinstance(total_points, dict)
                    else score,
                    "tier": payload.get("overallChallengeLevel")
                    or payload.get("tier")
                    or payload.get("challengeLevel")
                    or payload.get("level"),
                    "title": title,
                }
        if category == "titles" and isinstance(payload, list):
            titles = [
                str(item.get("name") or item.get("title") or "")
                for item in payload
                if isinstance(item, dict)
                and (item.get("selected") or item.get("isSelected"))
            ]
            return {"selected": titles[0]} if titles else {"selected": None}
        return None

    def _get(self, endpoint: str) -> Any:
        """Solicita y valida una respuesta JSON del endpoint LCU indicado."""
        if not self.cliente.port or not self.cliente.auth_token:
            raise ConnectionError("League no está conectado.")
        try:
            response = self.cliente.session.get(
                f"https://127.0.0.1:{self.cliente.port}{endpoint}", timeout=4
            )
            response.raise_for_status()
            payload = response.json()
            ruta = _sanitize_lcu_route(endpoint)
            logger.info(
                "[home-lcu] endpoint=%s status=%s shape=%s",
                ruta.split("?")[0],
                response.status_code,
                _response_shape(payload),
            )
            return payload
        except (requests.RequestException, ValueError) as error:
            status = getattr(getattr(error, "response", None), "status_code", "error")
            ruta = _sanitize_lcu_route(endpoint)
            logger.info(
                "[home-lcu] endpoint=%s status=%s unavailable",
                ruta.split("?")[0],
                status,
            )
            raise RuntimeError(
                "El cliente local no pudo devolver los datos solicitados."
            ) from error

    @staticmethod
    def _ranked_snapshot(payload: Any) -> list[dict[str, Any]]:
        """Extrae colas clasificatorias reconocibles sin conservar el JSON crudo."""
        queues = payload.get("queues", []) if isinstance(payload, dict) else []
        if isinstance(queues, dict):
            queues = list(queues.values())
        if not isinstance(queues, list):
            return []
        output = []
        for queue in queues:
            if not isinstance(queue, dict):
                continue
            queue_type = str(queue.get("queueType") or queue.get("queue") or "")
            tier = str(queue.get("tier") or queue.get("rankedLeagueTier") or "")
            division = str(
                queue.get("division") or queue.get("rankedLeagueDivision") or ""
            )
            if "RANKED" not in queue_type.upper() or not tier:
                continue
            output.append(
                {
                    "queue": queue_type,
                    "tier": tier,
                    "division": division,
                    "league_points": LCUHomeProvider._ranked_integer(
                        queue.get("leaguePoints", queue.get("rankedLeaguePoints"))
                    ),
                    "wins": LCUHomeProvider._ranked_integer(queue.get("wins")),
                    "losses": LCUHomeProvider._ranked_integer(queue.get("losses")),
                }
            )
        return output

    @staticmethod
    def _ranked_integer(value: Any) -> int | None:
        """Convierte una cifra de clasificación si el cliente la proporciona."""
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _normalize(
        cls,
        game: dict[str, Any],
        profile: dict[str, Any],
        existing_match: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Convierte un registro LCU a los campos analíticos disponibles."""
        if isinstance(game, dict) and isinstance(game.get("game"), dict):
            game = game["game"]
        participants = game.get("participants") or []
        participants = (
            [
                participant
                for participant in participants
                if isinstance(participant, dict)
            ]
            if isinstance(participants, list)
            else []
        )
        identities = game.get("participantIdentities") or []
        identities = identities if isinstance(identities, list) else []
        identity_by_participant = {
            str(identity.get("participantId")): identity.get("player")
            for identity in identities
            if isinstance(identity, dict) and isinstance(identity.get("player"), dict)
        }
        puuid = profile.get("puuid")
        player = next(
            (
                participant
                for participant in participants
                if participant.get("puuid") == puuid
                or identity_by_participant.get(
                    str(participant.get("participantId")), {}
                ).get("puuid")
                == puuid
            ),
            None,
        )
        if player is None:
            player = next(
                (
                    participant
                    for participant in participants
                    if str(
                        participant.get("accountId")
                        or identity_by_participant.get(
                            str(participant.get("participantId")), {}
                        ).get("accountId")
                    )
                    == profile.get("accountId")
                ),
                None,
            )
        if player is None:
            player = next(
                (
                    p
                    for p in participants
                    if str(
                        p.get("summonerId")
                        or identity_by_participant.get(
                            str(p.get("participantId")), {}
                        ).get("summonerId")
                    )
                    == profile.get("summonerId")
                ),
                None,
            )
        if player is None:
            player = next(
                (
                    participant
                    for participant in participants
                    if str(participant.get("summonerName") or "").casefold()
                    == str(profile.get("gameName") or "").casefold()
                ),
                None,
            )
        if player is None:
            return None
        stats = player.get("stats") or {}
        stats = stats if isinstance(stats, dict) else {}
        timeline = player.get("timeline") or {}
        timeline = timeline if isinstance(timeline, dict) else {}
        champ_id = player.get("championId")
        champion = _local_champion_metadata().get(str(champ_id), {})
        game_id = game.get("gameId") or game.get("gameID")
        timestamp = (
            game.get("gameCreation")
            or game.get("gameStartTime")
            or game.get("gameCreationDate")
        )
        try:
            started = (
                datetime.fromtimestamp(
                    float(timestamp) / (1000 if float(timestamp) > 10**11 else 1), UTC
                ).isoformat()
                if timestamp
                else ""
            )
        except (TypeError, ValueError, OSError):
            started = ""
        duration = cls._integer(game.get("gameDuration"))
        kills, deaths, assists = (
            cls._integer(stats.get(key)) for key in ("kills", "deaths", "assists")
        )
        cs = cls._integer(stats.get("minionsKilled")) + cls._integer(
            stats.get("neutralMinionsKilled")
        )
        items = [cls._integer(stats.get(f"item{i}")) for i in range(7)]
        lane = cls._participant_lane(player)
        normalized_participants = [
            cls._normalize_participant(
                item,
                identity_by_participant.get(str(item.get("participantId")), {}),
            )
            for item in participants
        ]
        normalized_participants = [item for item in normalized_participants if item]
        local_record = next(
            (
                item
                for item in normalized_participants
                if (
                    player.get("participantId") is not None
                    and str(item.get("participant_id"))
                    == str(player.get("participantId"))
                )
                or any(
                    item.get(key)
                    and str(item.get(key)) == str(profile.get(profile_key) or "")
                    for key, profile_key in (
                        ("puuid", "puuid"),
                        ("account_id", "accountId"),
                        ("summoner_id", "summonerId"),
                    )
                )
            ),
            {},
        )
        local_team = local_record.get("team_id")
        teammates = []
        teammate_ids: set[str] = set()
        for participant in normalized_participants:
            stable_player_id = (
                participant.get("puuid")
                or participant.get("account_id")
                or participant.get("summoner_id")
            )
            is_self = any(
                participant.get(key)
                and str(participant.get(key)) == str(profile.get(profile_key) or "")
                for key, profile_key in (
                    ("puuid", "puuid"),
                    ("account_id", "accountId"),
                    ("summoner_id", "summonerId"),
                )
            )
            stable_player_id = str(stable_player_id or "")
            if (
                participant.get("team_id") == local_team
                and not is_self
                and stable_player_id
                and not participant.get("is_bot")
                and stable_player_id not in teammate_ids
            ):
                teammate_ids.add(stable_player_id)
                teammates.append(
                    {
                        **participant,
                        "stable_player_id": str(stable_player_id),
                        "result": "victory"
                        if participant.get("win") is True
                        else "defeat"
                        if participant.get("win") is False
                        else "victory"
                        if stats.get("win") is True
                        else "defeat"
                        if stats.get("win") is False
                        else "unknown",
                    }
                )
        resolution = cls._resolve_opponent(
            normalized_participants,
            local_record,
            existing_match,
            str(game_id or ""),
        )
        opponent = resolution if resolution.get("confidence", 0) >= 0.55 else None
        enemy_team = cls._enemy_team(normalized_participants, local_team)
        logger.debug(
            "[home] partida procesada con %s aliados identificables", len(teammates)
        )
        stable_id = str(
            game_id
            or hashlib.sha256(
                f"{started}|{duration}|{champ_id}|{kills}|{deaths}|{assists}|{cs}".encode()
            ).hexdigest()
        )
        return {
            "stable_match_id": stable_id,
            "game_id": str(game_id or ""),
            "queue_id": game.get("queueId"),
            "mode": str(game.get("gameMode") or game.get("gameType") or ""),
            "started_at": started,
            "duration_seconds": duration,
            "result": "victory"
            if stats.get("win") is True
            else "defeat"
            if stats.get("win") is False
            else "unknown",
            "champion_id": champ_id,
            "champion_name": str(
                player.get("championName") or champion.get("name") or ""
            ),
            "champion_classes": list(champion.get("tags") or []),
            "lane": lane,
            "participants": normalized_participants,
            "enemy_team": enemy_team,
            "opponent_state": resolution.get("state", "unavailable"),
            "opponent": {
                "champion_id": opponent.get("champion_id"),
                "champion_name": opponent.get("champion_name"),
                "lane": opponent.get("lane"),
                "puuid": opponent.get("puuid"),
            }
            if opponent
            else None,
            "opponent_resolution": resolution,
            "opponent_champion_id": opponent.get("champion_id") if opponent else None,
            "opponent_champion_name": str(
                opponent.get("champion_name")
                or _local_champion_metadata()
                .get(str(opponent.get("champion_id")), {})
                .get("name")
                or ""
            )
            if opponent
            else "",
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "cs": cs,
            "cs_per_min": round(cs / (duration / 60), 1) if duration > 0 else None,
            "items": [item for item in items[:6] if item],
            "trinket": items[6] or None,
            "summoner_spells": [player.get("spell1Id"), player.get("spell2Id")],
            "runes": [
                cls._integer(stats.get(f"perk{indice}"))
                for indice in range(6)
                if cls._integer(stats.get(f"perk{indice}"))
            ],
            "teammates": teammates,
            "enrichment": {
                "participants_complete": len(normalized_participants) == 10,
                "teammates_resolved": local_team is not None and len(teammates) == 4,
                "opponent_resolved": opponent is not None,
                "detail_attempted": False,
            },
            "analyzable": False,
            "data_quality": {"complete": bool(game_id and timestamp), "source": "LCU"},
        }

    @classmethod
    def _resolve_opponent(
        cls,
        participants: list[dict[str, Any]],
        local_player: dict[str, Any],
        existing_match: dict[str, Any] | None = None,
        game_id: str = "",
    ) -> dict[str, Any]:
        """Elige rival de línea por evidencia de rol y conserva una resolución válida."""
        player_lane, player_method, player_confidence = (
            cls._participant_position_evidence(local_player)
        )
        stored_lane = cls._normalize_position((existing_match or {}).get("lane"))
        if player_lane == "unknown" and stored_lane != "unknown":
            player_lane, player_method, player_confidence = (
                stored_lane,
                "inferred",
                0.78,
            )
        local_team = local_player.get("team_id")
        enemies = [
            participant
            for participant in participants
            if local_team is not None and participant.get("team_id") != local_team
        ]
        enemy_evidence = [
            (
                participant,
                *cls._participant_position_evidence(participant),
            )
            for participant in enemies
        ]
        roles = ", ".join(
            f"{item.get('champion_name') or item.get('champion_id')} -> {lane.upper()}"
            for item, lane, _method, _confidence in enemy_evidence
        )
        logger.debug("[home] game=%s playerRole=%s", game_id, player_lane)
        logger.debug("[home] enemy roles: %s", roles or "sin datos")
        candidates = [
            (participant, method, min(player_confidence, confidence))
            for participant, lane, method, confidence in enemy_evidence
            if player_lane != "unknown"
            and lane == player_lane
            and min(player_confidence, confidence) >= 0.55
        ]
        position_candidates = [
            candidate
            for candidate in candidates
            if candidate[1] in {"teamPosition", "individualPosition"}
        ]
        selected = cls._select_opponent_candidate(
            position_candidates,
            player_lane,
            player_method,
            player_confidence,
            game_id,
        )
        if selected is not None and selected.get("confidence", 0) >= 0.75:
            return cls._set_opponent_state(selected)
        stored = cls._stored_opponent_resolution(existing_match)
        if stored is not None:
            return cls._set_opponent_state(stored)
        ordered = cls._candidato_rival_por_orden(enemies, player_lane)
        if ordered is not None:
            logger.debug(
                "[home] game=%s opponent resolved: %s method=team_order confidence=%.2f",
                game_id,
                ordered["champion_name"] or ordered["champion_id"],
                ordered["confidence"],
            )
            return cls._set_opponent_state(ordered)
        if selected is not None:
            return cls._set_opponent_state(selected)
        selected = cls._select_opponent_candidate(
            [candidate for candidate in candidates if candidate[1] == "lane_role"],
            player_lane,
            player_method,
            player_confidence,
            game_id,
        )
        if selected is not None:
            return cls._set_opponent_state(selected)
        selected = cls._select_opponent_candidate(
            [candidate for candidate in candidates if candidate[1] == "inferred"],
            player_lane,
            player_method,
            player_confidence,
            game_id,
        )
        if selected is not None:
            return cls._set_opponent_state(selected)
        state = "ambiguous" if enemies else "unavailable"
        logger.info(
            "[home] opponent unresolved game=%s state=%s reason=no-compatible-position-data",
            game_id,
            state,
        )
        return {
            "champion_id": None,
            "champion_name": "",
            "lane": player_lane,
            "puuid": None,
            "confidence": 0.0,
            "method": "unknown",
            "state": state,
        }

    @classmethod
    def _candidato_rival_por_orden(
        cls, enemies: list[dict[str, Any]], player_lane: str
    ) -> dict[str, Any] | None:
        """Obtiene el pick rival del mismo índice posicional del equipo contrario."""
        lane_indices = {
            "top": 0,
            "jungle": 1,
            "mid": 2,
            "bot": 3,
            "support": 4,
        }
        index = lane_indices.get(player_lane)
        rivales_ordenados = sorted(
            enemies,
            key=lambda participant: (
                participant.get("participant_id") is None,
                cls._integer(participant.get("participant_id")),
            ),
        )
        if index is None or len(rivales_ordenados) != 5:
            return None
        participante = rivales_ordenados[index]
        champion_id = participante.get("champion_id")
        if champion_id is None:
            return None
        return {
            "champion_id": champion_id,
            "champion_name": str(participante.get("champion_name") or ""),
            "lane": player_lane,
            "puuid": participante.get("puuid"),
            "confidence": 0.9,
            "method": "team_order",
        }

    @staticmethod
    def _set_opponent_state(resolution: dict[str, Any]) -> dict[str, Any]:
        """Clasifica la presentación sin relajar el umbral analítico."""
        confidence = float(resolution.get("confidence") or 0.0)
        resolution["state"] = (
            "exact"
            if confidence >= 0.75
            else "probable"
            if confidence >= 0.55
            else "ambiguous"
        )
        return resolution

    @staticmethod
    def _select_opponent_candidate(
        candidates: list[tuple[dict[str, Any], str, float]],
        player_lane: str,
        player_method: str,
        player_confidence: float,
        game_id: str,
    ) -> dict[str, Any] | None:
        """Selecciona un rival único entre candidatos con la misma fuerza probatoria."""
        rank = {
            "teamPosition": 4,
            "individualPosition": 3,
            "lane_role": 2,
            "inferred": 1,
        }
        candidates.sort(
            key=lambda candidate: (candidate[2], rank.get(candidate[1], 0)),
            reverse=True,
        )
        if not candidates:
            return None
        winner = candidates[0]
        tied = [
            candidate
            for candidate in candidates
            if candidate[2] == winner[2]
            and rank.get(candidate[1], 0) == rank.get(winner[1], 0)
        ]
        if len(tied) != 1:
            return None
        participant, method, confidence = winner
        evidence_confidence = {
            "teamPosition": 1.0,
            "individualPosition": 0.95,
            "lane_role": 0.88,
            "inferred": 0.78,
        }.get(method, 0.0)
        if player_confidence < evidence_confidence:
            method = player_method
        result = {
            "champion_id": participant.get("champion_id"),
            "champion_name": participant.get("champion_name") or "",
            "lane": player_lane,
            "puuid": participant.get("puuid"),
            "confidence": confidence,
            "method": method,
        }
        logger.debug(
            "[home] game=%s opponent resolved: %s method=%s confidence=%.2f",
            game_id,
            result["champion_name"] or result["champion_id"],
            method,
            confidence,
        )
        return result

    @staticmethod
    def _stored_opponent_resolution(
        match: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Convierte una referencia de rival anterior en respaldo conservador."""
        if not isinstance(match, dict):
            return None
        resolution = match.get("opponent_resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        opponent = match.get("opponent")
        opponent = opponent if isinstance(opponent, dict) else {}
        champion_id = (
            resolution.get("champion_id")
            or opponent.get("champion_id")
            or match.get("opponent_champion_id")
        )
        champion_name = (
            resolution.get("champion_name")
            or opponent.get("champion_name")
            or match.get("opponent_champion_name")
        )
        if champion_id is None and not champion_name:
            return None
        try:
            confidence = float(resolution.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.8
        if confidence > 1:
            confidence = round(confidence / 100, 2)
        if confidence < 0.75:
            return None
        method = str(resolution.get("method") or "stored")
        if method not in {
            "teamPosition",
            "individualPosition",
            "lane_role",
            "stored",
            "inferred",
            "team_order",
        }:
            method = "stored"
        return {
            "champion_id": champion_id,
            "champion_name": str(champion_name or ""),
            "lane": resolution.get("lane") or opponent.get("lane") or match.get("lane"),
            "puuid": resolution.get("puuid") or opponent.get("puuid"),
            "confidence": confidence,
            "method": method,
        }

    @staticmethod
    def _lane(value: Any) -> str:
        """Normaliza variantes de carril y rol a los cinco valores canónicos."""
        return LCUHomeProvider._normalize_position(value)

    @staticmethod
    def _normalize_position(value: Any, role: Any = None) -> str:
        """Normaliza una posición LCU teniendo en cuenta el rol de dúo."""
        raw = re.sub(r"[^A-Z]", "", str(value or "").upper())
        raw_role = re.sub(r"[^A-Z]", "", str(role or "").upper())
        if raw_role in {"DUOSUPPORT", "SUPPORT", "SUP", "UTILITY"}:
            return "support"
        if raw_role in {"DUOCARRY", "ADC", "APC", "CARRY"}:
            return "bot"
        aliases = {
            "TOP": "top",
            "TOPLANE": "top",
            "JUNG": "jungle",
            "JGL": "jungle",
            "JUNGLE": "jungle",
            "JUNGLELANE": "jungle",
            "MID": "mid",
            "MIDDLE": "mid",
            "MIDLANE": "mid",
            "MIDDLELANE": "mid",
            "BOT": "bot",
            "BOTTOM": "bot",
            "BOTLANE": "bot",
            "BOTTOMLANE": "bot",
            "ADC": "bot",
            "APC": "bot",
            "CARRY": "bot",
            "DUOCARRY": "bot",
            "UTILITY": "support",
            "SUPPORT": "support",
            "SUP": "support",
            "DUOSUPPORT": "support",
        }
        role_alias = ROLE_ALIASES.get(raw)
        if role_alias and role_alias != "UNKNOWN":
            return {
                "TOP": "top",
                "JUNGLE": "jungle",
                "MIDDLE": "mid",
                "BOTTOM": "bot",
                "UTILITY": "support",
            }.get(role_alias, "unknown")
        return aliases.get(raw, "unknown")

    @classmethod
    def _participant_lane(cls, participant: dict[str, Any]) -> str:
        """Resuelve la posición de un participante siguiendo prioridad LCU estable."""
        return cls._participant_position_evidence(participant)[0]

    @classmethod
    def _participant_position_evidence(
        cls, participant: dict[str, Any]
    ) -> tuple[str, str, float]:
        """Devuelve carril, origen y confianza de la evidencia de posición."""
        stats = (
            participant.get("stats")
            if isinstance(participant.get("stats"), dict)
            else {}
        )
        timeline = (
            participant.get("timeline")
            if isinstance(participant.get("timeline"), dict)
            else {}
        )
        timeline_role = timeline.get("role") or participant.get("timeline_role")
        explicit_role = stats.get("role") or participant.get("role")
        role = timeline_role or explicit_role
        for value in (
            stats.get("teamPosition"),
            participant.get("teamPosition"),
            participant.get("team_position"),
        ):
            if value is None or str(value).strip().upper() in {"", "NONE"}:
                continue
            lane = cls._normalize_position(value, role)
            if lane != "unknown":
                return lane, "teamPosition", 1.0
        for value in (
            stats.get("individualPosition"),
            participant.get("individualPosition"),
            participant.get("individual_position"),
        ):
            if value is None or str(value).strip().upper() in {"", "NONE"}:
                continue
            lane = cls._normalize_position(value, role)
            if lane != "unknown":
                return lane, "individualPosition", 0.95
        lane_raw = (
            timeline.get("lane")
            or participant.get("lane_raw")
            or participant.get("lane")
        )
        if (
            lane_raw is not None
            and role
            and cls._normalize_position(lane_raw) != "unknown"
        ):
            lane = cls._normalize_position(lane_raw, role)
            role_lane = cls._normalize_position(role)
            if lane != "unknown" and role_lane != "unknown":
                return lane, "lane_role", 0.88
        lane = cls._normalize_position(explicit_role)
        if lane != "unknown":
            return lane, "lane_role", 0.88
        for value in (lane_raw, participant.get("position")):
            lane = cls._normalize_position(value)
            if lane != "unknown":
                return lane, "inferred", 0.78
        if timeline_role in {"UTILITY", "DUO_SUPPORT", "DUO_CARRY"}:
            lane = cls._normalize_position(timeline_role)
            if lane != "unknown":
                return lane, "lane_role", 0.88
        spells = participant.get("summoner_spells") or [
            participant.get("spell1Id"),
            participant.get("spell2Id"),
        ]
        if any(str(spell) == "11" for spell in spells):
            return "jungle", "inferred", 0.76
        return "unknown", "unknown", 0.0

    @classmethod
    def _normalize_participant(
        cls, participant: dict[str, Any], identity: dict[str, Any]
    ) -> dict[str, Any]:
        """Normaliza identidad, posición y estadísticas de un jugador LCU."""
        stats = (
            participant.get("stats")
            if isinstance(participant.get("stats"), dict)
            else {}
        )
        timeline = (
            participant.get("timeline")
            if isinstance(participant.get("timeline"), dict)
            else {}
        )
        player = (
            identity.get("player")
            if isinstance(identity.get("player"), dict)
            else identity
        )
        champion_id = participant.get("championId")
        metadata = _local_champion_metadata().get(str(champion_id), {})
        return {
            "participant_id": participant.get("participantId"),
            "team_id": participant.get("teamId")
            if participant.get("teamId") is not None
            else stats.get("teamId"),
            "puuid": participant.get("puuid") or player.get("puuid"),
            "account_id": participant.get("accountId") or player.get("accountId"),
            "summoner_id": participant.get("summonerId") or player.get("summonerId"),
            "game_name": participant.get("gameName") or player.get("gameName"),
            "tag_line": participant.get("tagLine") or player.get("tagLine"),
            "summoner_name": participant.get("summonerName")
            or player.get("summonerName"),
            "profile_icon_id": participant.get("profileIconId")
            or player.get("profileIconId"),
            "champion_id": champion_id,
            "champion_name": participant.get("championName") or metadata.get("name"),
            "lane": cls._participant_lane(participant),
            "lane_raw": timeline.get("lane") or participant.get("lane"),
            "role": stats.get("role") or participant.get("role"),
            "timeline_role": timeline.get("role"),
            "team_position": stats.get("teamPosition")
            or participant.get("teamPosition"),
            "individual_position": stats.get("individualPosition")
            or participant.get("individualPosition"),
            "win": stats.get("win"),
            "kills": cls._integer(stats.get("kills")),
            "deaths": cls._integer(stats.get("deaths")),
            "assists": cls._integer(stats.get("assists")),
            "cs": cls._integer(stats.get("minionsKilled"))
            + cls._integer(stats.get("neutralMinionsKilled")),
            "items": [cls._integer(stats.get(f"item{i}")) for i in range(7)],
            "summoner_spells": [
                participant.get("spell1Id"),
                participant.get("spell2Id"),
            ],
            "is_bot": bool(
                participant.get("isBot") or player.get("isBot") or player.get("bot")
            ),
        }

    @staticmethod
    def _integer(value: Any) -> int:
        """Convierte valores numéricos incompletos del cliente con fallback seguro."""
        try:
            return int(value or 0)
        except (TypeError, ValueError, OverflowError):
            return 0


def analyze_home_history(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula KPIs y distribuciones usando únicamente partidas conocidas."""
    played = [
        match for match in matches if match.get("result") in {"victory", "defeat"}
    ]
    wins = sum(match.get("result") == "victory" for match in played)
    champions = Counter(
        str(match.get("champion_name") or "")
        for match in played
        if match.get("champion_name")
    )
    lanes = Counter(
        str(match.get("lane") or "unknown")
        for match in played
        if str(match.get("lane") or "unknown") != "unknown"
    )
    classes = Counter(
        str(champion_class)
        for match in played
        for champion_class in match.get("champion_classes", [])
        if champion_class
    )
    racha_actual = 0
    mejor_racha = 0
    racha_temporal = 0
    for match in matches:
        if match.get("result") == "victory":
            racha_temporal += 1
            mejor_racha = max(mejor_racha, racha_temporal)
        else:
            racha_temporal = 0
    for match in matches:
        if match.get("result") != "victory":
            break
        racha_actual += 1
    hours: Counter[int] = Counter()
    weekdays: Counter[int] = Counter()
    for match in played:
        try:
            fecha = datetime.fromisoformat(
                str(match.get("started_at")).replace("Z", "+00:00")
            )
            hours[fecha.astimezone().hour] += 1
            weekdays[fecha.astimezone().weekday()] += 1
        except (TypeError, ValueError):
            pass
    teammates = _teammate_summary(played)
    matchups, hardest_matchups = _matchup_summary(played)
    opponent_states: Counter[str] = Counter()
    for match in matches:
        state = str(match.get("opponent_state") or "")
        if state not in {"exact", "probable", "ambiguous", "unavailable"}:
            confidence = _opponent_confidence(match)
            state = (
                "exact"
                if confidence >= 0.75
                else "probable"
                if confidence >= 0.55
                else "ambiguous"
                if match.get("enemy_team")
                else "unavailable"
            )
        opponent_states[state] += 1
    return {
        "total": len(matches),
        "played": len(played),
        "wins": wins,
        "current_win_streak": racha_actual,
        "longest_win_streak": mejor_racha,
        "winrate": round(wins * 100 / len(played)) if played else None,
        "top_champion": champions.most_common(1)[0][0] if champions else None,
        "champions": champions.most_common(3),
        "lanes": lanes.most_common(),
        "classes": classes.most_common(),
        "hours": sorted(hours.items()),
        "weekdays": sorted(weekdays.items()),
        "peak_hour": hours.most_common(1)[0][0] if hours else None,
        "best_hour": _sampled_hour(played, best=True),
        "worst_hour": _sampled_hour(played, best=False),
        "teammates": teammates,
        "modes": Counter(_friendly_mode(match) for match in matches).most_common(),
        "matchups": matchups,
        "hardest_matchups": hardest_matchups,
        "team_data_matches": sum(bool(match.get("teammates")) for match in played),
        "opponent_data_matches": opponent_states["exact"],
        "opponent_exact": opponent_states["exact"],
        "opponent_probable": opponent_states["probable"],
        "opponent_ambiguous": opponent_states["ambiguous"],
        "opponent_unavailable": opponent_states["unavailable"],
    }


def _friendly_mode(match: dict[str, Any]) -> str:
    """Devuelve una etiqueta de cola legible usando el modo y el ID conocidos."""
    queue_id = str(match.get("queue_id") or "")
    mode = str(match.get("mode") or "").upper()
    queue_names = {
        "420": "Clasificatoria Solo/Dúo",
        "440": "Clasificatoria Flexible",
        "450": "ARAM",
        "400": "Normal",
        "430": "Normal",
        "700": "Clash",
    }
    if queue_id in queue_names:
        return queue_names[queue_id]
    if mode == "ARAM":
        return "ARAM"
    if mode == "PRACTICETOOL":
        return "Herramienta de práctica"
    if mode == "CLASSIC":
        return "Grieta del Invocador"
    return mode.replace("_", " ").title() if mode else "Desconocido"


@lru_cache(maxsize=4)
def _local_champion_metadata(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Lee nombres y clases desde los metadatos locales sin acceder a la red."""
    directory = root or (DATA_DIR / "champion_metadata")
    champions: dict[str, dict[str, Any]] = {}
    try:
        paths = tuple(directory.glob("*.json"))
    except OSError:
        return champions
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records = data.get("data", {}) if isinstance(data, dict) else {}
        if not isinstance(records, dict):
            continue
        for record in records.values():
            if not isinstance(record, dict) or record.get("key") is None:
                continue
            champion_id = str(record["key"])
            champions[champion_id] = {
                "name": str(record.get("name") or ""),
                "tags": [tag for tag in record.get("tags", []) if isinstance(tag, str)]
                if isinstance(record.get("tags"), list)
                else [],
            }
    return champions


def cross_reference_saved_matches(
    matches: list[dict[str, Any]], sessions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Marca partidas guardadas usando ID exacto o coincidencia compuesta fuerte."""
    saved_ids = set()
    for session in sessions:
        if not isinstance(session, dict):
            continue
        final_sync = session.get("final_sync") or {}
        final_sync = final_sync if isinstance(final_sync, dict) else {}
        match_id = str(final_sync.get("match_id") or session.get("match_id") or "")
        if match_id:
            saved_ids.add(match_id.rsplit("_", 1)[-1])
    indexed_sessions = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        scoreboard = session.get("final_scoreboard")
        indexed_sessions.append(
            (session, scoreboard if isinstance(scoreboard, dict) else {})
        )
    result = []
    for source in matches:
        match = dict(source)
        game_id = str(match.get("game_id") or "")
        matched_session = next(
            (
                session
                for session, _ in indexed_sessions
                if game_id
                and _session_match_id(session).rsplit("_", 1)[-1]
                == game_id.rsplit("_", 1)[-1]
            ),
            None,
        )
        confidence = 100 if matched_session else 0
        if not confidence:
            for session, scoreboard in indexed_sessions:
                candidate = _saved_match_confidence(match, session, scoreboard)
                if candidate > confidence:
                    confidence, matched_session = candidate, session
        match["analyzable"] = confidence >= 85
        match["saved_match_confidence"] = confidence
        session_id = str((matched_session or {}).get("session_id") or "")
        match["saved_match_link"] = {
            "matched": bool(session_id and confidence >= 85),
            "saved_match_id": session_id if confidence >= 85 else "",
            "confidence": round(confidence / 100, 2),
        }
        result.append(match)
    return result


def _session_match_id(session: dict[str, Any]) -> str:
    """Obtiene el ID de partida desde una sesión guardada con forma validada."""
    final_sync = session.get("final_sync")
    final_sync = final_sync if isinstance(final_sync, dict) else {}
    return str(final_sync.get("match_id") or session.get("match_id") or "")


def _saved_match_confidence(
    match: dict[str, Any], session: dict[str, Any], scoreboard: dict[str, Any]
) -> int:
    """Calcula confianza compuesta sin decidir por campos débiles aislados."""
    score = 0
    final_sync = session.get("final_sync") or {}
    final_sync = final_sync if isinstance(final_sync, dict) else {}
    session_id = str(final_sync.get("match_id") or "")
    game_id = str(match.get("game_id") or "")
    if session_id and game_id and session_id.endswith(game_id):
        return 100
    if str(session.get("champion_name") or "").casefold() == str(
        match.get("champion_name") or ""
    ).casefold() and match.get("champion_name"):
        score += 24
    duration = LCUHomeProvider._integer(session.get("duration"))
    match_duration = LCUHomeProvider._integer(match.get("duration_seconds"))
    if duration and match_duration and abs(duration - match_duration) <= 90:
        score += 20
    if (
        session.get("game_mode")
        and match.get("mode")
        and str(session["game_mode"]).casefold() == str(match["mode"]).casefold()
    ):
        score += 12
    local = scoreboard.get("local_player") or {}
    local = local if isinstance(local, dict) else {}
    if all(
        match.get(key) is not None for key in ("kills", "deaths", "assists")
    ) and tuple(match[key] for key in ("kills", "deaths", "assists")) == tuple(
        LCUHomeProvider._integer(local.get(key))
        for key in ("kills", "deaths", "assists")
    ):
        score += 24
    if match.get("lane") and match.get("lane") != "unknown":
        score += (
            10 if match.get("lane") == LCUHomeProvider._lane(local.get("role")) else 0
        )
    try:
        local_start = datetime.fromisoformat(
            str(session.get("started_at")).replace("Z", "+00:00")
        )
        match_start = datetime.fromisoformat(
            str(match.get("started_at")).replace("Z", "+00:00")
        )
        if abs((local_start - match_start).total_seconds()) <= 180:
            score += 20
    except (TypeError, ValueError):
        pass
    return score


def _sampled_hour(
    matches: list[dict[str, Any]], best: bool
) -> tuple[int, int, int] | None:
    """Selecciona hora favorable o desfavorable solo con cinco partidas válidas."""
    counts: Counter[int] = Counter()
    victories: Counter[int] = Counter()
    for match in matches:
        try:
            hour = (
                datetime.fromisoformat(
                    str(match.get("started_at")).replace("Z", "+00:00")
                )
                .astimezone()
                .hour
            )
        except (TypeError, ValueError):
            continue
        counts[hour] += 1
        victories[hour] += match.get("result") == "victory"
    candidates = [hour for hour, count in counts.items() if count >= 5]
    if not candidates:
        return None
    selected = (
        max(candidates, key=lambda hour: victories[hour] / counts[hour])
        if best
        else min(candidates, key=lambda hour: victories[hour] / counts[hour])
    )
    return (
        selected,
        round(100 * victories[selected] / counts[selected]),
        counts[selected],
    )


def _teammate_summary(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resume compañeros identificados con al menos dos partidas compartidas."""
    matches = _unique_match_records(matches)
    stats: dict[str, Counter[str]] = {}
    display: dict[str, tuple[str, str]] = {}
    matches_by_player: dict[str, set[str]] = {}
    champions_by_player: dict[str, Counter[tuple[str, str]]] = {}
    last_played_by_player: dict[str, str] = {}
    for match in matches:
        match_id = str(
            match.get("game_id") or match.get("stable_match_id") or id(match)
        )
        seen_in_match: set[str] = set()
        for teammate in match.get("teammates", []):
            if match.get("result") not in {"victory", "defeat"}:
                continue
            stable_id = str(
                teammate.get("stable_player_id")
                or f"{teammate.get('game_name', '')}#{teammate.get('tag_line', '')}"
            ).strip()
            if not stable_id or stable_id in seen_in_match:
                continue
            seen_in_match.add(stable_id)
            stats.setdefault(stable_id, Counter())[
                str(teammate.get("result") or "unknown")
            ] += 1
            display[stable_id] = (
                str(teammate.get("game_name") or teammate.get("name") or "Jugador"),
                str(teammate.get("tag_line") or ""),
            )
            matches_by_player.setdefault(stable_id, set()).add(match_id)
            champion_id = str(teammate.get("champion_id") or "")
            champion_name = str(teammate.get("champion_name") or "")
            if champion_id:
                champions_by_player.setdefault(stable_id, Counter())[
                    (champion_id, champion_name)
                ] += 1
            last_played_by_player[stable_id] = max(
                last_played_by_player.get(stable_id, ""),
                str(match.get("started_at") or ""),
            )
    summaries = []
    for stable_id, outcomes in stats.items():
        games = sum(outcomes.values())
        if games < 2:
            continue
        wins = outcomes["victory"]
        without = [
            match
            for match in matches
            if str(match.get("game_id") or match.get("stable_match_id") or id(match))
            not in matches_by_player[stable_id]
        ]
        without_valid = [
            match for match in without if match.get("result") in {"victory", "defeat"}
        ]
        without_wr = (
            round(
                100
                * sum(match.get("result") == "victory" for match in without_valid)
                / len(without_valid)
            )
            if without_valid
            else None
        )
        summaries.append(
            {
                "stable_player_id": stable_id,
                "name": display[stable_id][0],
                "tag_line": display[stable_id][1],
                "games": games,
                "matches_together": games,
                "wins": wins,
                "wins_together": wins,
                "losses": outcomes["defeat"],
                "winrate": round(wins * 100 / games),
                "winrate_without": without_wr,
                "winrate_delta": round(wins * 100 / games - without_wr)
                if without_wr is not None
                else None,
                "last_played_at": last_played_by_player.get(stable_id, ""),
                "profile_icon_id": next(
                    (
                        teammate.get("profile_icon_id")
                        for match in matches
                        for teammate in match.get("teammates", [])
                        if str(teammate.get("stable_player_id") or "") == stable_id
                        and teammate.get("profile_icon_id") is not None
                    ),
                    None,
                ),
                "champion_id": champions_by_player[stable_id].most_common(1)[0][0][0]
                if champions_by_player.get(stable_id)
                else None,
                "champion_name": champions_by_player[stable_id].most_common(1)[0][0][1]
                if champions_by_player.get(stable_id)
                else "",
            }
        )
        logger.debug("[home] teammate aggregate: matches=%s wins=%s", games, wins)
    return sorted(
        summaries,
        key=lambda item: (item["games"], item["last_played_at"]),
        reverse=True,
    )[:3]


def _matchup_summary(
    matches: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Agrega rivales por ID único y devuelve listas exclusivas y ordenadas."""
    unique_matches = _unique_match_records(matches)
    outcomes: dict[str, Counter[str]] = {}
    champion_names: dict[str, str] = {}
    original_ids: dict[str, Any] = {}
    for match in unique_matches:
        if match.get("result") not in {"victory", "defeat"}:
            continue
        if _opponent_confidence(match) < 0.75:
            continue
        resolution = match.get("opponent_resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        opponent = match.get("opponent")
        opponent = opponent if isinstance(opponent, dict) else {}
        champion_id = (
            resolution.get("champion_id")
            or opponent.get("champion_id")
            or match.get("opponent_champion_id")
        )
        if champion_id is None:
            continue
        key = str(champion_id)
        champion_names[key] = str(
            resolution.get("champion_name")
            or opponent.get("champion_name")
            or match.get("opponent_champion_name")
            or _local_champion_metadata().get(key, {}).get("name")
            or f"Campeón {key}"
        )
        original_ids[key] = champion_id
        outcomes.setdefault(key, Counter())[str(match["result"])] += 1
    summaries = []
    muestras_altas = sum(
        results["victory"] + results["defeat"] >= 3 for results in outcomes.values()
    )
    minimum_games = 3 if muestras_altas >= 6 else 2
    for champion_id, results in outcomes.items():
        games = results["victory"] + results["defeat"]
        if games < minimum_games:
            continue
        wins = results["victory"]
        summaries.append(
            {
                "champion": champion_names[champion_id],
                "champion_id": original_ids[champion_id],
                "games": games,
                "wins": wins,
                "losses": results["defeat"],
                "winrate": round(wins * 100 / games),
            }
        )
    difficult = sorted(
        summaries,
        key=lambda entry: (
            entry["winrate"],
            -entry["games"],
            str(entry["champion_id"]),
        ),
    )[:3]
    used_ids = {str(entry["champion_id"]) for entry in difficult}
    favorable = sorted(
        (entry for entry in summaries if str(entry["champion_id"]) not in used_ids),
        key=lambda entry: (
            -entry["winrate"],
            -entry["games"],
            str(entry["champion_id"]),
        ),
    )[:3]
    return favorable, difficult


def _opponent_confidence(match: dict[str, Any]) -> float:
    """Devuelve la confianza fiable de una resolución, incluida historia heredada."""
    resolution = match.get("opponent_resolution")
    resolution = resolution if isinstance(resolution, dict) else {}
    try:
        confidence = float(resolution.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence > 1:
        confidence /= 100
    if confidence:
        return confidence
    opponent = match.get("opponent")
    if isinstance(opponent, dict) and opponent.get("champion_id") is not None:
        return 0.8
    return 0.8 if match.get("opponent_champion_id") is not None else 0.0


def _unique_match_records(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Elige una versión por partida y prefiere los registros enriquecidos."""
    unique: dict[str, dict[str, Any]] = {}
    for index, match in enumerate(matches):
        game_id = str(match.get("game_id") or match.get("stable_match_id") or "")
        if not game_id:
            game_id = (
                "|".join(
                    str(match.get(key) or "")
                    for key in (
                        "started_at",
                        "champion_id",
                        "result",
                        "duration_seconds",
                    )
                )
                or f"row:{index}"
            )
        previous = unique.get(game_id)
        if previous is None:
            unique[game_id] = match
            continue
        score = len(match.get("teammates") or []) + len(match.get("participants") or [])
        previous_score = len(previous.get("teammates") or []) + len(
            previous.get("participants") or []
        )
        score += 10 if _opponent_confidence(match) >= 0.75 else 0
        previous_score += 10 if _opponent_confidence(previous) >= 0.75 else 0
        if score > previous_score:
            unique[game_id] = match
    return list(unique.values())
