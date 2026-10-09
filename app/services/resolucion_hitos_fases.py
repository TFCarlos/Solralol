"""Resuelve hitos de informes contra la cronología confirmada de la partida."""

from __future__ import annotations

import re
from typing import Any


def resolver_hito_fase(
    referencia: dict[str, Any], contexto: dict[str, Any]
) -> dict[str, Any]:
    """Convierte una referencia de informe en un evento factual de la cronología.

    Args:
        referencia: Hito estructurado o antiguo con hora y/o identificador.
        contexto: Registro de partida con participantes y eventos cronológicos.

    Returns:
        Evento listo para presentar sin confiar en descripciones del modelo.
    """
    eventos = contexto.get("events_chronology", [])
    eventos = [evento for evento in eventos if isinstance(evento, dict)]
    identificador = str(referencia.get("event_id") or "")
    coincidencia_id = re.fullmatch(r"event-(\d+)", identificador)
    if coincidencia_id:
        orden = int(coincidencia_id.group(1))
        encontrados = [evento for evento in eventos if evento.get("order") == orden]
        if len(encontrados) == 1:
            return _evento_presentable(encontrados[0], contexto, "confirmed")
    segundos = _segundos_referencia(referencia)
    if segundos is not None:
        encontrados = [
            evento
            for evento in eventos
            if _segundos_evento(evento) == segundos and _es_relevante(evento)
        ]
        if len(encontrados) == 1:
            return _evento_presentable(encontrados[0], contexto, "confirmed")
        if len(encontrados) > 1:
            return {
                "time_label": _hora(segundos),
                "timestamp_seconds": segundos,
                "title": f"Evento registrado a las {_hora(segundos)} · varios eventos coinciden",
                "description": "La hora coincide con más de un evento; no se atribuye uno concreto.",
                "category": "ambiguous",
                "icon_type": "event",
                "champion_ids": [],
                "event_id": "",
                "evidence_status": "ambiguous",
            }
    hora = str(referencia.get("time_label") or "Tiempo no disponible")
    return {
        "time_label": hora,
        "timestamp_seconds": segundos if segundos is not None else 0,
        "title": f"Evento registrado a las {hora} · Detalles no disponibles",
        "description": "La telemetría guardada no permite identificar este hito.",
        "category": "unknown",
        "icon_type": "event",
        "champion_ids": [],
        "event_id": "",
        "evidence_status": "unknown",
    }


def hitos_relevantes_fase(
    fase: dict[str, Any], clave_fase: str, contexto: dict[str, Any]
) -> list[dict[str, Any]]:
    """Resuelve hitos guardados y completa hitos con eventos significativos.

    Args:
        fase: Datos estructurados de una fase del informe.
        clave_fase: Clave ``early``, ``mid`` o ``late``.
        contexto: Registro factual de la partida.

    Returns:
        Lista cronológica curada de eventos resueltos para la fase.
    """
    referencias = fase.get("evidence_events", [])
    resultado = [
        resolver_hito_fase(evento, contexto)
        for evento in referencias
        if isinstance(evento, dict)
    ]
    if resultado:
        return _deduplicar_hitos(resultado)
    limites = {"early": (0, 900), "mid": (900, 1500), "late": (1500, float("inf"))}
    inicio, fin = limites.get(clave_fase, (0, float("inf")))
    eventos = contexto.get("events_chronology", [])
    candidatos = [
        _evento_presentable(evento, contexto, "confirmed")
        for evento in eventos
        if isinstance(evento, dict)
        and inicio <= _segundos_evento(evento) < fin
        and _es_relevante(evento)
    ]
    prioridad = {"kill": 0, "objective": 1, "structure": 2, "purchase": 3, "other": 4}
    candidatos.sort(
        key=lambda evento: (
            0 if evento.get("involves_local") else 1,
            prioridad.get(str(evento.get("category")), 5),
            _segundos_evento(evento.get("source", {})),
        )
    )
    seleccionados = candidatos[:6]
    resultado = _deduplicar_hitos(seleccionados)
    for evento in resultado:
        evento.pop("involves_local", None)
        evento.pop("source", None)
    return resultado


def _evento_presentable(
    evento: dict[str, Any], contexto: dict[str, Any], estado: str
) -> dict[str, Any]:
    """Compone título, categoría e iconos desde los campos de telemetría."""
    jugadores = contexto.get("all_players", [])
    nombres = {
        str(jugador.get("player_key")): jugador
        for jugador in jugadores
        if isinstance(jugador, dict)
    }
    asesino = nombres.get(str(evento.get("killer_key") or ""), {})
    victima = nombres.get(str(evento.get("victim_key") or ""), {})
    participante = nombres.get(str(evento.get("player_key") or ""), {})
    metadata = contexto.get("metadata", {})
    equipo_local = str(metadata.get("local_team") or "").upper()
    equipo_evento = str(evento.get("team") or "").upper()
    equipo = "Equipo aliado" if equipo_evento == equipo_local else "Equipo rival"
    categoria = _categoria_evento(evento)
    ids = [
        _id_campeon(valor.get("champion"))
        for valor in (asesino, victima, participante)
        if valor.get("champion")
    ]
    ids = list(dict.fromkeys(valor for valor in ids if valor))
    if categoria == "kill":
        titulo = f"{_nombre(asesino)} eliminó a {_nombre(victima)}"
        iconos = [
            valor
            for valor in (
                _id_campeon(asesino.get("champion")),
                _id_campeon(victima.get("champion")),
            )
            if valor
        ]
    elif categoria == "objective":
        objetivo = _nombre_objetivo(evento.get("objective") or evento.get("label"))
        titulo = f"{equipo} consiguió {objetivo}"
        iconos = []
    elif categoria == "structure":
        objetivo = _nombre_objetivo(evento.get("objective") or evento.get("label"))
        titulo = f"{equipo} destruyó {objetivo}"
        iconos = []
    elif categoria == "purchase":
        objeto = str(evento.get("item_name") or evento.get("item_id") or "un objeto")
        titulo = f"{_nombre(participante)} compró {objeto}"
        iconos = ids[:1]
    else:
        titulo = str(evento.get("label") or "Evento registrado sin detalle adicional")
        iconos = ids[:2]
    hora = str(evento.get("time_label") or _hora(_segundos_evento(evento)))
    return {
        "event_id": f"event-{evento.get('order')}"
        if evento.get("order") is not None
        else "",
        "time_label": hora,
        "timestamp_seconds": _segundos_evento(evento),
        "title": titulo,
        "description": str(evento.get("label") or titulo),
        "category": categoria,
        "icon_type": "champion" if iconos else "event",
        "champion_ids": iconos,
        "item_id": evento.get("item_id"),
        "item_name": evento.get("item_name"),
        "objective": evento.get("objective"),
        "evidence_status": estado,
        "involves_local": str(contexto.get("local_player_key") or "")
        in {
            str(evento.get("killer_key") or ""),
            str(evento.get("victim_key") or ""),
            str(evento.get("player_key") or ""),
            *(str(valor) for valor in evento.get("assister_keys", [])),
        },
        "source": evento,
    }


def _categoria_evento(evento: dict[str, Any]) -> str:
    """Clasifica eventos de combate, objetivos, estructuras y compras."""
    tipo = str(evento.get("type") or "").casefold()
    objetivo = str(evento.get("objective") or "").casefold()
    if "kill" in tipo or "death" in tipo:
        return "kill"
    if "purchase" in tipo or "item_purchased" in tipo:
        return "purchase"
    if any(
        valor in tipo or valor in objetivo
        for valor in ("tower", "inhibitor", "structure", "inhibidor", "torre", "nexus")
    ):
        return "structure"
    if "objective" in tipo or objetivo:
        return "objective"
    return "other"


def _es_relevante(evento: dict[str, Any]) -> bool:
    """Filtra compras y eventos menores para priorizar hitos estratégicos."""
    categoria = _categoria_evento(evento)
    return categoria in {"kill", "objective", "structure"} or (
        categoria == "purchase" and bool(evento.get("important"))
    )


def _segundos_referencia(referencia: dict[str, Any]) -> int | None:
    """Obtiene segundos de una referencia antigua expresada como mm:ss."""
    valor = referencia.get("timestamp_seconds", referencia.get("time_seconds"))
    if isinstance(valor, (int, float)):
        return round(float(valor))
    coincidencia = re.fullmatch(
        r"\s*(\d+):(\d{2})\s*", str(referencia.get("time_label") or "")
    )
    return (
        int(coincidencia.group(1)) * 60 + int(coincidencia.group(2))
        if coincidencia
        else None
    )


def _segundos_evento(evento: dict[str, Any]) -> int:
    """Devuelve el tiempo entero del evento para comparación determinista."""
    try:
        return round(float(evento.get("time_seconds") or 0))
    except (TypeError, ValueError):
        return 0


def _hora(segundos: int) -> str:
    """Formatea segundos de partida como minutos y segundos."""
    return f"{max(0, segundos) // 60:02d}:{max(0, segundos) % 60:02d}"


def _nombre(jugador: dict[str, Any]) -> str:
    """Obtiene nombre de campeón legible con fallback neutral."""
    return str(jugador.get("champion") or "Campeón no identificado")


def _id_campeon(nombre: Any) -> str:
    """Resuelve identificadores Data Dragon canónicos para retratos."""
    if not nombre:
        return ""
    try:
        from app.services.match_analysis_evidence_service import (
            MatchAnalysisEvidenceService,
        )

        return MatchAnalysisEvidenceService._canonical_champion_id(str(nombre))
    except (ImportError, TypeError, ValueError):
        return str(nombre).replace(" ", "")


def _nombre_objetivo(valor: Any) -> str:
    """Normaliza nombres de objetivos y estructuras registrados."""
    texto = str(valor or "objetivo")
    normalizado = texto.casefold()
    if "bar" in normalizado:
        return "el Barón Nashor"
    if "drag" in normalizado:
        return "el dragón"
    if "herald" in normalizado or "heraldo" in normalizado:
        return "el Heraldo de la Grieta"
    if "grub" in normalizado or "grum" in normalizado:
        return "los Void Grubs"
    if "inhib" in normalizado:
        return "el inhibidor" + (
            f" {texto.split('·', 1)[1].strip().lower()}" if "·" in texto else ""
        )
    if "tower" in normalizado or "torre" in normalizado:
        return "la torre"
    return texto[:1].lower() + texto[1:] if texto else "un objetivo"


def _deduplicar_hitos(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Elimina referencias duplicadas y conserva orden cronológico."""
    unicos: dict[str, dict[str, Any]] = {}
    for evento in eventos:
        clave = str(
            evento.get("event_id")
            or f"{evento.get('time_label')}|{evento.get('title')}"
        )
        unicos.setdefault(clave, evento)
    return sorted(
        unicos.values(), key=lambda evento: evento.get("timestamp_seconds", 0)
    )
