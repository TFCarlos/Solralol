"""Configuración única de filtros de rango, etiquetas y contratos de proveedores."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RangoCampeon:
    """Describe clave local, etiqueta y parámetros propios de cada proveedor."""

    clave: str
    etiqueta: str
    ugg: str
    opgg: str
    lolalytics: str


RANGOS_COMPATIBLES = (
    RangoCampeon("emerald", "Esmeralda", "16", "EMERALD", "emerald"),
    RangoCampeon("emerald_plus", "Esmeralda+", "17", "EMERALD_PLUS", "emerald_plus"),
    RangoCampeon("diamond", "Diamante", "3", "DIAMOND", "diamond"),
    RangoCampeon("diamond_plus", "Diamante+", "11", "DIAMOND_PLUS", "diamond_plus"),
    RangoCampeon("master", "Master", "2", "MASTER", "master"),
    RangoCampeon("master_plus", "Master+", "14", "MASTER_PLUS", "master_plus"),
)
POR_CLAVE = {rango.clave: rango for rango in RANGOS_COMPATIBLES}
CLAVES_RANGOS = frozenset(POR_CLAVE)
OPCIONES_RANGO = tuple((rango.clave, rango.etiqueta) for rango in RANGOS_COMPATIBLES)
RANGO_PREDETERMINADO = "emerald_plus"


def normalizar_rango(valor: str) -> str | None:
    """Devuelve clave compatible normalizada del valor recibido o None si es obsoleto."""
    clave = valor.strip().casefold().replace("+", "_plus").replace(" ", "_")
    return clave if clave in CLAVES_RANGOS else None
