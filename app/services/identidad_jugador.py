"""Resolución segura de nombres visibles para participantes de una partida."""

from __future__ import annotations

from typing import Any


def nombre_riot_visible(jugador: dict[str, Any]) -> str:
    """Devuelve el Riot ID o alias visible sin revelar claves internas."""
    final = jugador.get("final")
    datos = {**jugador, **final} if isinstance(final, dict) else jugador
    campos_juego = ("riot_id_game_name", "riotIdGameName", "game_name", "gameName")
    campos_etiqueta = (
        "riot_id_tag_line",
        "riot_id_tagline",
        "riotIdTagLine",
        "riotIdTagline",
        "tag_line",
        "tagLine",
    )
    nombre = next(
        (
            str(datos.get(campo) or "").strip()
            for campo in campos_juego
            if datos.get(campo)
        ),
        "",
    )
    etiqueta = next(
        (
            str(datos.get(campo) or "").strip()
            for campo in campos_etiqueta
            if datos.get(campo)
        ),
        "",
    )
    if nombre and etiqueta and not _es_clave_interna(nombre):
        return f"{nombre}#{etiqueta}"
    for campo in (
        "riot_id",
        "riotId",
        "display_name",
        "summoner_name",
        "summonerName",
        "riot_id_game_name",
        "riotIdGameName",
        "game_name",
        "gameName",
    ):
        valor = str(datos.get(campo) or "").strip()
        if valor and not _es_clave_interna(valor):
            return valor
    return ""


def _es_clave_interna(valor: str) -> bool:
    """Identifica prefijos de equipo, claves técnicas y PUUID largos."""
    normalizado = valor.strip().casefold()
    prefijo = normalizado.split(":", 1)[0]
    if ":" in normalizado and prefijo in {
        "chaos",
        "order",
        "blue",
        "red",
        "ally",
        "enemy",
    }:
        return True
    return (
        normalizado.startswith(("participant_", "participant:", "puuid:"))
        or len(normalizado) >= 50
    )
