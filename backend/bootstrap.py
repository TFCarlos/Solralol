"""Small, side-effect-free response for the JSONL transport health check."""

from __future__ import annotations

from app.services.rangos_campeones import OPCIONES_RANGO
from backend.contracts import PROTOCOL_VERSION


FEATURES = [
    {"id": "home", "label": "Inicio", "status": "available"},
    {"id": "analysis", "label": "Análisis local", "status": "available"},
    {"id": "draft", "label": "Draft", "status": "available"},
    {"id": "live", "label": "Partida en vivo", "status": "available"},
    {"id": "saved-matches", "label": "Partidas guardadas", "status": "available"},
    {"id": "recordings", "label": "Grabaciones", "status": "available"},
    {"id": "meta", "label": "Meta y notas", "status": "available"},
    {"id": "settings", "label": "Ajustes", "status": "available"},
]


def bootstrap_payload(service_state: str = "ready") -> dict:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "product": "Solralol",
        "serviceState": service_state,
        "features": FEATURES,
        "ranges": [{"id": key, "label": label} for key, label in OPCIONES_RANGO],
    }
