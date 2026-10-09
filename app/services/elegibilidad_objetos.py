"""Valida compras recomendadas para modos concretos antes de puntuarlas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MODO_SOLOQ = "SR_RANKED_SOLO_DUO"
MAPAS_POR_MODO = {MODO_SOLOQ: "11", "ARAM": "12"}


@dataclass(frozen=True)
class ResultadoElegibilidadObjeto:
    """Describe si un objeto puede recomendarse y por qué."""

    elegible: bool
    motivo: str


class ValidadorElegibilidadObjetos:
    """Aplica las restricciones de compra del catálogo de un parche."""

    @staticmethod
    def validar(
        identificador: str,
        objeto: dict[str, Any],
        campeon: str | None,
        modo: str,
        parche_catalogo: str,
    ) -> ResultadoElegibilidadObjeto:
        """Valida ID, modo, parche, tienda y restricciones de campeón."""
        return ValidadorElegibilidadObjetos._validar_compra(
            identificador, objeto, campeon, modo, parche_catalogo, False
        )

    @staticmethod
    def validar_compra_inicial(
        identificador: str,
        objeto: dict[str, Any],
        campeon: str | None,
        modo: str,
        parche_catalogo: str,
    ) -> ResultadoElegibilidadObjeto:
        """Valida un objeto inicial, permitiendo consumibles comprables.

        Parámetros:
            identificador: ID canónico del objeto inicial.
            objeto: Metadatos del objeto para el parche seleccionado.
            campeon: Campeón asociado a la selección local.
            modo: Modo explícito de la recomendación.
            parche_catalogo: Versión del catálogo empleado.

        Retorna:
            El resultado de validar la compra inicial en la tienda del modo.
        """
        return ValidadorElegibilidadObjetos._validar_compra(
            identificador, objeto, campeon, modo, parche_catalogo, True
        )

    @staticmethod
    def _validar_compra(
        identificador: str,
        objeto: dict[str, Any],
        campeon: str | None,
        modo: str,
        parche_catalogo: str,
        permitir_consumible: bool,
    ) -> ResultadoElegibilidadObjeto:
        """Aplica reglas compartidas de compra con política de consumibles.

        Parámetros:
            identificador: ID canónico del objeto.
            objeto: Metadatos del objeto.
            campeon: Campeón asociado.
            modo: Modo de juego explícito.
            parche_catalogo: Parche del catálogo.
            permitir_consumible: Indica si el objeto puede ser consumible.

        Retorna:
            El resultado de las reglas comunes de disponibilidad y compra.
        """
        mapa = MAPAS_POR_MODO.get(modo)
        if mapa is None:
            return ResultadoElegibilidadObjeto(False, "modo_no_admitido")
        if (
            not identificador.isdigit()
            or str(objeto.get("id", identificador)) != identificador
        ):
            return ResultadoElegibilidadObjeto(False, "id_canonico_no_coincide")
        if len(identificador) >= 6:
            return ResultadoElegibilidadObjeto(False, "id_de_variante_de_modo")
        parche_objeto = objeto.get("patch")
        if parche_objeto and str(parche_objeto) != parche_catalogo:
            return ResultadoElegibilidadObjeto(False, "parche_incompatible")
        mapas = objeto.get("maps")
        if not isinstance(mapas, dict) or mapas.get(mapa) is not True:
            motivo = (
                "mapa_no_disponible" if isinstance(mapas, dict) else "mapa_desconocido"
            )
            return ResultadoElegibilidadObjeto(False, motivo)
        oro = objeto.get("gold")
        if not isinstance(oro, dict) or oro.get("purchasable") is not True:
            return ResultadoElegibilidadObjeto(False, "no_comprable")
        if objeto.get("inStore") is False or objeto.get("hideFromAll") is True:
            return ResultadoElegibilidadObjeto(False, "fuera_de_tienda")
        if objeto.get("consumed") is True and not permitir_consumible:
            return ResultadoElegibilidadObjeto(False, "consumible_no_recomendable")
        requerido = objeto.get("requiredAlly")
        if (
            requerido
            and campeon is not None
            and str(campeon).casefold()
            not in {
                str(requerido).casefold(),
                str(objeto.get("requiredAllyId", "")).casefold(),
            }
        ):
            return ResultadoElegibilidadObjeto(False, "restriccion_de_campeon")
        if objeto.get("requiredEnemy"):
            return ResultadoElegibilidadObjeto(False, "requiere_composicion_enemiga")
        try:
            coste_total = int(oro.get("total", 0) or 0)
        except (TypeError, ValueError):
            return ResultadoElegibilidadObjeto(False, "coste_no_valido")
        if coste_total <= 0:
            return ResultadoElegibilidadObjeto(False, "coste_no_valido")
        return ResultadoElegibilidadObjeto(True, "disponible_en_mapa")

    @staticmethod
    def diagnosticar_catalogo(
        catalogo: dict[str, dict[str, Any]],
        campeon: str | None,
        modo: str,
        parche_catalogo: str,
    ) -> dict[str, Any]:
        """Resume el catálogo elegible y conserva el motivo de cada rechazo."""
        rechazos: dict[str, str] = {}
        en_mapa = 0
        en_summoners_rift = 0
        comprables = 0
        parche_actual = 0
        for identificador, objeto in catalogo.items():
            mapas = objeto.get("maps")
            mapa = MAPAS_POR_MODO.get(modo)
            if isinstance(mapas, dict) and mapa and mapas.get(mapa) is True:
                en_mapa += 1
            if isinstance(mapas, dict) and mapas.get("11") is True:
                en_summoners_rift += 1
            oro = objeto.get("gold")
            if isinstance(oro, dict) and oro.get("purchasable") is True:
                comprables += 1
            if not objeto.get("patch") or str(objeto.get("patch")) == parche_catalogo:
                parche_actual += 1
            resultado = ValidadorElegibilidadObjetos.validar(
                str(identificador), objeto, campeon, modo, parche_catalogo
            )
            if not resultado.elegible:
                rechazos[str(identificador)] = resultado.motivo
        return {
            "catalog_entries": len(catalogo),
            "current_patch_entries": parche_actual,
            "mode_map_entries": en_mapa,
            "summoners_rift_entries": en_summoners_rift,
            "purchasable_entries": comprables,
            "champion_eligible_entries": len(catalogo) - len(rechazos),
            "rejected_items": rechazos,
        }
