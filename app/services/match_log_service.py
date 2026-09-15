from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class MatchLogService:
    """
    Servicio para generar, estructurar y guardar ficheros de logs de partidas.
    Guarda los eventos y estadísticas de telemetría de una partida en ~/.solralol/match_logs/
    en formatos .json y .log.
    """

    def __init__(self) -> None:
        self.logs_dir = Path.home() / ".solralol" / "match_logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def save_match_log(self, session: dict[str, Any]) -> tuple[Path, Path]:
        """
        Genera y guarda los ficheros .json y .log para la sesión de partida.
        Devuelve la tupla de rutas (path_json, path_log).
        """
        log_data = self.build_match_log(session)
        session_id = log_data["metadata"]["session_id"]

        json_path = self.logs_dir / f"match_{session_id}.json"
        log_path = self.logs_dir / f"match_{session_id}.log"

        # Guardar JSON estructurado
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        # Guardar archivo de texto plano .log
        with log_path.open("w", encoding="utf-8") as f:
            f.write(log_data["formatted_log_text"])

        # Actualizar sesión con la ruta del log
        session["match_log_json_path"] = str(json_path)
        session["match_log_txt_path"] = str(log_path)

        return json_path, log_path

    def get_match_log(self, session: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """
        Obtiene el log de la partida. Si ya existe en disco lo carga;
        si no existe, lo genera y guarda.
        """
        session_id = session.get("session_id")
        if not session_id:
            champion = session.get("champion_name", "match")
            started = session.get("started_at", datetime.now().isoformat())
            safe_started = str(started).replace(":", "-").replace(".", "-")
            session_id = f"{safe_started}_{champion}"
            session["session_id"] = session_id

        json_path = self.logs_dir / f"match_{session_id}.json"
        log_path = self.logs_dir / f"match_{session_id}.log"

        # Siempre regeneramos el log si la partida ahora tiene datos postgame completos
        if session.get("postgame") or session.get("final_scoreboard"):
            self.save_match_log(session)

        if json_path.exists() and log_path.exists():
            try:
                with json_path.open("r", encoding="utf-8") as f:
                    log_data = json.load(f)
                with log_path.open("r", encoding="utf-8") as f:
                    formatted_text = f.read()
                return log_data, formatted_text
            except Exception:
                pass

        # Generar y guardar si no existía o falló la lectura
        self.save_match_log(session)
        with json_path.open("r", encoding="utf-8") as f:
            log_data = json.load(f)
        with log_path.open("r", encoding="utf-8") as f:
            formatted_text = f.read()

        return log_data, formatted_text

    def build_match_log(self, session: dict[str, Any]) -> dict[str, Any]:
        """
        Construye una estructura de datos completa con todos los eventos y estadísticas de la partida.
        """
        champion_name = str(session.get("champion_name", "Desconocido"))
        started_at = str(session.get("started_at", ""))
        ended_at = str(session.get("ended_at", ""))
        duration = float(session.get("duration", 0.0) or 0.0)
        game_mode = str(session.get("game_mode", "UNKNOWN"))

        session_id = str(session.get("session_id") or "")
        if not session_id:
            safe_time = started_at.replace(":", "-").replace(".", "-")
            safe_champion = "".join(c for c in champion_name if c.isalnum() or c in "_-")
            session_id = f"{safe_time}_{safe_champion or 'match'}"

        players = session.get("players", {})
        local_key = str(session.get("local_player_key", ""))
        local_player = players.get(local_key, {})
        local_team = str(session.get("local_team", "")).upper()

        # Determinar equipo ganador
        winning_team = str(session.get("winning_team", "")).upper()
        if not winning_team and local_player.get("win") is not None:
            local_win = bool(local_player.get("win"))
            if local_team:
                winning_team = local_team if local_win else ("CHAOS" if local_team == "ORDER" else "ORDER")

        user_win = self._determine_player_win(local_key, local_player, session, winning_team)

        # 1. Metadatos principales
        metadata = {
            "session_id": session_id,
            "champion_name": champion_name,
            "player_riot_id": session.get("player_riot_id", local_player.get("riot_id", "Desconocido")),
            "game_mode": game_mode,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": round(duration, 1),
            "duration_formatted": self._format_time(duration),
            "result": "VICTORIA" if user_win else "DERROTA",
            "winning_team": winning_team or "DESCONOCIDO",
            "local_team": local_team,
        }

        # 2. Resumen del jugador local
        user_stats_dict = self._extract_player_stats(local_key, local_player, session)
        user_stats = {
            "champion": champion_name,
            "role": local_player.get("role", "UNKNOWN"),
            "team": local_team,
            "win": user_win,
            **user_stats_dict,
            "cs_per_min": round(user_stats_dict["cs"] / max(1.0, duration / 60.0), 1),
        }

        # 3. Lista estructurada de todos los jugadores (Aliados y Enemigos)
        all_players_summary = []
        for key, p_meta in players.items():
            p_stats = self._extract_player_stats(key, p_meta, session)
            p_win = self._determine_player_win(key, p_meta, session, winning_team)
            p_team = str(p_meta.get("team", "")).upper()
            is_ally = bool(local_team and p_team == local_team) or (key == local_key)

            all_players_summary.append({
                "player_key": key,
                "champion": p_meta.get("champion_name", "Desconocido"),
                "riot_id": p_meta.get("riot_id", "Desconocido"),
                "team": p_team,
                "is_ally": is_ally,
                "role": p_meta.get("role", "UNKNOWN"),
                "win": p_win,
                "result": "VICTORIA" if p_win else "DERROTA",
                "cs_per_min": round(p_stats["cs"] / max(1.0, duration / 60.0), 1),
                **p_stats,
            })

        # 4. Cronología de eventos registrados (Aliados y Enemigos)
        events_raw = session.get("events", [])
        events_chronology = []
        for index, ev in enumerate(events_raw):
            if not isinstance(ev, dict):
                continue
            t = float(ev.get("time", 0.0) or 0.0)
            events_chronology.append({
                "order": ev.get("order", index),
                "time_seconds": t,
                "time_label": ev.get("time_label", self._format_time(t)),
                "type": ev.get("type", "unknown"),
                "player_key": ev.get("player_key", ""),
                "team": ev.get("team", ""),
                "label": ev.get("label", ""),
                "killer_key": ev.get("killer_key"),
                "victim_key": ev.get("victim_key"),
                "assister_keys": ev.get("assister_keys", []),
                "item_name": ev.get("item_name"),
                "objective": ev.get("objective"),
            })

        events_chronology.sort(key=lambda x: (x["time_seconds"], x["order"]))

        # 5. Formatear texto del log en formato plano comprensible por IA y humanos
        formatted_log_text = self._generate_formatted_log_text(metadata, user_stats, all_players_summary, events_chronology, players, local_team)

        return {
            "metadata": metadata,
            "user_stats": user_stats,
            "all_players": all_players_summary,
            "events_count": len(events_chronology),
            "events_chronology": events_chronology,
            "formatted_log_text": formatted_log_text,
        }

    def _extract_player_stats(
        self,
        key: str,
        p_meta: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any]:
        final_scoreboard = session.get("final_scoreboard", {})
        p_final = final_scoreboard.get(key) or p_meta.get("final") or {}

        latest_snapshot_point: dict[str, Any] = {}
        for snap in reversed(session.get("snapshots", [])):
            pt = snap.get("players", {}).get(key)
            if isinstance(pt, dict):
                latest_snapshot_point = pt
                break

        def _val(*sources: Any, keys: tuple[str, ...], default: int = 0) -> int:
            for src in sources:
                if not isinstance(src, dict):
                    continue
                for k in keys:
                    if k in src and src[k] is not None:
                        try:
                            return int(src[k])
                        except (TypeError, ValueError):
                            pass
            return default

        snap_stats = latest_snapshot_point.get("stats", {})

        kills = _val(p_final, p_meta, latest_snapshot_point, keys=("kills",))
        deaths = _val(p_final, p_meta, latest_snapshot_point, keys=("deaths",))
        assists = _val(p_final, p_meta, latest_snapshot_point, keys=("assists",))

        cs = _val(p_final, p_meta, latest_snapshot_point, keys=("cs_total", "minions_killed", "cs"))
        gold = _val(p_final, p_meta, latest_snapshot_point, keys=("gold_earned", "estimated_gold", "gold"))

        dmg_champs = _val(p_final, snap_stats, latest_snapshot_point, keys=("total_damage_dealt_to_champions", "damage_dealt_to_champions", "damage_to_champions"))
        dmg_objs = _val(p_final, snap_stats, latest_snapshot_point, keys=("damage_dealt_to_objectives", "damage_to_structures"))
        dmg_taken = _val(p_final, snap_stats, latest_snapshot_point, keys=("total_damage_taken", "damage_taken"))
        vision = _val(p_final, snap_stats, latest_snapshot_point, keys=("vision_score",))

        items = p_final.get("items") or p_meta.get("items") or latest_snapshot_point.get("items") or []
        if isinstance(items, list):
            clean_items = [int(x) for x in items if isinstance(x, (int, float, str)) and str(x).isdigit() and int(x) > 0]
        else:
            clean_items = []

        return {
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "cs": cs,
            "gold": gold,
            "damage_to_champions": dmg_champs,
            "damage_to_objectives": dmg_objs,
            "damage_taken": dmg_taken,
            "vision_score": vision,
            "items": clean_items,
        }

    def _determine_player_win(
        self,
        key: str,
        p_meta: dict[str, Any],
        session: dict[str, Any],
        winning_team: str,
    ) -> bool:
        final_scoreboard = session.get("final_scoreboard", {})
        p_final = final_scoreboard.get(key) or p_meta.get("final") or {}

        if "win" in p_final and isinstance(p_final["win"], bool):
            return p_final["win"]
        if "win" in p_meta and isinstance(p_meta["win"], bool):
            return p_meta["win"]

        player_team = str(p_meta.get("team", "")).upper()
        if winning_team and player_team:
            return player_team == winning_team

        return False

    def _generate_formatted_log_text(
        self,
        metadata: dict[str, Any],
        user_stats: dict[str, Any],
        all_players: list[dict[str, Any]],
        events: list[dict[str, Any]],
        players_meta: dict[str, Any],
        local_team: str,
    ) -> str:
        lines = []
        lines.append("================================================================================")
        lines.append(f"SOLRALOL - REGISTRO COMPLETO DE LOG DE PARTIDA ({metadata['session_id']})")
        lines.append("================================================================================")
        lines.append(f"Jugador Analizado: {metadata['champion_name']} (Riot ID: {metadata['player_riot_id']})")
        lines.append(f"Modo: {metadata['game_mode']} | Resultado: {metadata['result']} | Duración: {metadata['duration_formatted']}")
        lines.append(f"Equipo Jugador: {metadata['local_team']} | Equipo Ganador: {metadata['winning_team']}")
        lines.append(f"Fecha Inicio: {metadata['started_at']}")
        lines.append("--------------------------------------------------------------------------------")
        lines.append("ESTADÍSTICAS FINALES DEL JUGADOR:")
        lines.append(f"  - KDA: {user_stats['kills']} / {user_stats['deaths']} / {user_stats['assists']}")
        lines.append(f"  - Farmeo: {user_stats['cs']} CS ({user_stats['cs_per_min']} CS/min)")
        lines.append(f"  - Oro Ganado: {user_stats['gold']:,} oro")
        lines.append(f"  - Daño a Campeones: {user_stats['damage_to_champions']:,}")
        lines.append(f"  - Daño a Objetivos: {user_stats['damage_to_objectives']:,}")
        lines.append(f"  - Daño Recibido: {user_stats['damage_taken']:,}")
        lines.append(f"  - Puntuación de Visión: {user_stats['vision_score']}")
        lines.append(f"  - Objetos Finales (IDs): {user_stats['items']}")
        lines.append("--------------------------------------------------------------------------------")
        lines.append("RESUMEN DE EQUIPOS Y JUGADORES (ALIADOS Y ENEMIGOS):")

        allies = [p for p in all_players if p["is_ally"]]
        enemies = [p for p in all_players if not p["is_ally"]]

        lines.append("  [EQUIPO ALIADO]:")
        for p in allies:
            lines.append(f"    - {p['champion']} ({p['role']}) - Invocador: {p['riot_id']} | KDA: {p['kills']}/{p['deaths']}/{p['assists']} | {p['cs']} CS ({p['cs_per_min']} CS/m) | Oro: {p['gold']:,} | Daño: {p['damage_to_champions']:,} | [{p['result']}] | Build: {p['items']}")

        lines.append("  [EQUIPO ENEMIGO]:")
        for p in enemies:
            lines.append(f"    - {p['champion']} ({p['role']}) - Invocador: {p['riot_id']} | KDA: {p['kills']}/{p['deaths']}/{p['assists']} | {p['cs']} CS ({p['cs_per_min']} CS/m) | Oro: {p['gold']:,} | Daño: {p['damage_to_champions']:,} | [{p['result']}] | Build: {p['items']}")

        lines.append("--------------------------------------------------------------------------------")
        lines.append("CRONOLOGÍA COMPLETA DE EVENTOS (AMBOS EQUIPOS):")

        if not events:
            lines.append("  (No hay eventos detallados registrados en esta partida)")
        else:
            for ev in events:
                time_str = ev["time_label"]
                ev_type = str(ev["type"]).upper()
                p_key = ev.get("player_key")
                k_key = ev.get("killer_key")
                v_key = ev.get("victim_key")

                formatted_label = self._format_event_label(ev, players_meta, local_team)
                lines.append(f"  [{time_str}] [{ev_type}] {formatted_label}")

        lines.append("================================================================================")
        lines.append("FIN DEL REGISTRO DE LOG DE PARTIDA")
        lines.append("================================================================================")
        return "\n".join(lines)

    def _format_event_label(
        self,
        ev: dict[str, Any],
        players: dict[str, Any],
        local_team: str,
    ) -> str:
        label = str(ev.get("label", ""))
        k_key = ev.get("killer_key")
        v_key = ev.get("victim_key")
        p_key = ev.get("player_key")

        def p_info(key: str | None) -> str:
            if not key or key not in players:
                return ""
            meta = players[key]
            champ = meta.get("champion_name", "Campeón")
            role = meta.get("role", "")
            team = str(meta.get("team", "")).upper()
            side = "[ALIADO]" if (local_team and team == local_team) else "[ENEMIGO]"
            return f"{side} {champ} ({role})" if role else f"{side} {champ}"

        if k_key and v_key:
            killer_str = p_info(k_key)
            victim_str = p_info(v_key)
            assister_keys = ev.get("assister_keys", [])
            assisters_str = ""
            if assister_keys:
                ast_names = [players[ak].get("champion_name") for ak in assister_keys if ak in players]
                ast_names = [n for n in ast_names if n]
                if ast_names:
                    assisters_str = f" [Asistencias: {', '.join(ast_names)}]"
            if killer_str and victim_str:
                return f"{killer_str} asesinó a {victim_str}{assisters_str}"

        if p_key and p_key in players:
            p_str = p_info(p_key)
            return f"{p_str}: {label}"

        return label

    @staticmethod
    def _format_time(seconds: float) -> str:
        minutes, secs = divmod(max(0, int(seconds)), 60)
        return f"{minutes:02d}:{secs:02d}"
