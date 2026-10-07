"""Adaptador de variantes locales sobre el repositorio versionado por campeón."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.rangos_campeones import normalizar_rango
from app.services.repositorio_campeones import RepositorioCampeones

LANE_STATS_KEY = "__lane_stats__"
STORE_VERSION = 2


class ChampionVariantService:
    """Conserva el contrato de variantes para los consumidores existentes sin acceso remoto."""

    CACHE_VERSION = STORE_VERSION

    def __init__(self, root: Path | None = None) -> None:
        """Recibe raíz opcional y crea repositorio local; retorna None."""
        self.repositorio = RepositorioCampeones(root)
        self.root = self.repositorio.raiz

    def path_for(self, champion: str) -> Path:
        """Devuelve ruta del campeón recibido sin I/O."""
        return self.repositorio.ruta(champion)

    @staticmethod
    def key(champion: str, role: str, rank: str) -> str:
        """Devuelve clave estable de campeón, línea y rango recibidos."""
        return f"{champion.strip().casefold()}|{role.strip().casefold()}|{normalizar_rango(rank) or 'unsupported'}"

    def get(self, champion: str, role: str, rank: str) -> dict[str, Any] | None:
        """Devuelve variante local recibida o None sin descargar datos ausentes."""
        return self.repositorio.consultar(champion, role, rank).datos

    def lane_stats(self, champion: str, rank: str) -> dict[str, Any]:
        """Devuelve resumen local de líneas del campeón y rango recibidos."""
        consulta = self.repositorio.obtener_campeon(champion)
        bloque = (consulta.datos or {}).get("ranks", {}).get(normalizar_rango(rank), {})
        resumen = bloque.get(LANE_STATS_KEY, {}).get("lanes", {})
        if resumen:
            return resumen
        for linea, variante in bloque.items():
            if linea != LANE_STATS_KEY and isinstance(variante, dict):
                resumen = variante.get("lane_stats", {}).get("lanes", {})
                if resumen:
                    return resumen
        return {}

    def available_ranks(self, champion: str) -> list[str]:
        """Devuelve rangos locales del campeón recibido."""
        return sorted(
            (self.repositorio.obtener_campeon(champion).datos or {}).get("ranks", {})
        )

    def available_lanes(self, champion: str, rank: str) -> list[str]:
        """Devuelve líneas locales del campeón y rango recibidos."""
        return [
            linea
            for linea in (self.repositorio.obtener_campeon(champion).datos or {})
            .get("ranks", {})
            .get(normalizar_rango(rank), {})
            if linea != LANE_STATS_KEY
        ]
