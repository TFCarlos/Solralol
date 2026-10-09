"""Clasifica resultados finales como coaching sin generar puntos nuevos.

Umbrales sobre las referencias de las categorías vigentes: A+ desde 115 %; A/A-/B+
desde 105/95/85 %; B/B-/C+ desde 75/65/55 %; C/C-/D+ desde 45/35/25 %;
D/D-/F+ desde 15/5/0 %. Las notas solo orientan la presentación.
"""

from __future__ import annotations

from typing import Any

ESCALA_GRADOS = (
    (1.15, "A+"),
    (1.05, "A"),
    (0.95, "A-"),
    (0.85, "B+"),
    (0.75, "B"),
    (0.65, "B-"),
    (0.55, "C+"),
    (0.45, "C"),
    (0.35, "C-"),
    (0.25, "D+"),
    (0.15, "D"),
    (0.05, "D-"),
    (0.0, "F+"),
)


def grado_desde_proporcion(proporcion: float) -> str:
    """Convierte una proporción de referencia en un grado estable.

    Args:
        proporcion: puntos normalizados respecto a la referencia oficial.

    Returns:
        Grado de coaching entre A+ y F-; conserva puntuaciones superiores al 100 %.
    """
    for umbral, grado in ESCALA_GRADOS:
        if proporcion >= umbral:
            return grado
    return "F-"


def calcular_grados_rendimiento(puntuacion: Any) -> dict[str, Any] | None:
    """Deriva grados solo de puntuaciones finales oficiales suficientemente completas.

    Args:
        puntuacion: bloque `performance_scoring` persistido por SOLRALOL.

    Returns:
        Grado general y grados por categoría, o `None` si faltan datos fiables.
    """
    if not isinstance(puntuacion, dict) or puntuacion.get("state") != "POSTGAME_FINAL":
        return None
    jugador = puntuacion.get("local_player")
    if not isinstance(jugador, dict):
        return None
    try:
        _ = float(jugador["total"])
        completitud = float(jugador["completeness"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if completitud < 0.5:
        return None
    categorias = jugador.get("categories")
    if not isinstance(categorias, dict):
        return None
    valores_categoria: dict[str, tuple[float, float]] = {}
    for clave, datos in categorias.items():
        if not isinstance(datos, dict):
            continue
        try:
            referencia = float(datos["reference"])
            final = float(datos["final"])
            cobertura_categoria = float(datos.get("completeness", 0))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if referencia > 0 and cobertura_categoria >= 0.5:
            valores_categoria[str(clave)] = (final, referencia)
    if len(valores_categoria) < 4:
        return None
    return {
        "overall": grado_desde_proporcion(
            sum(final for final, _ in valores_categoria.values())
            / sum(referencia for _, referencia in valores_categoria.values())
        ),
        "categories": {
            clave: grado_desde_proporcion(final / referencia)
            for clave, (final, referencia) in valores_categoria.items()
        },
        "source": "official_performance_scoring",
        "threshold_scale": "SOLRALOL-reference-v1",
    }
