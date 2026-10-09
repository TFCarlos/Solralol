"""Prepara variantes, recomendaciones y recursos fuera del hilo gráfico."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any

import data_dragon
from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.champion_variant_service import ChampionVariantService
from app.services.elegibilidad_objetos import MODO_SOLOQ
from app.services.preparador_datos_campeon import combinar_perfil
from app.services.rangos_campeones import normalizar_rango
from app.services.repositorio_campeones import EstadoDatos
from app.services.synergy_recommendation_service import ItemRecommendation

REGISTRO = logging.getLogger(__name__)


class AnalisisLocalService:
    """Mantiene cachés acotadas dentro de una cola secuencial de trabajos Qt."""

    def __init__(
        self, catalogo: CatalogoAnalisisLocal, ruta_campeones: Path, version: str
    ) -> None:
        """Recibe catálogo, ruta y versión; inicializa almacén y cachés sin acceso remoto."""
        self.catalogo = catalogo
        self.ruta_campeones = ruta_campeones
        self.version = version
        self.variantes = ChampionVariantService(ruta_campeones)
        self.recursos: dict[tuple[str, str, str], tuple[Path | None, bytes, float]] = {}
        self.metadatos: dict[str, dict[str, Any]] = {}
        self._preparados: dict[
            tuple[str, str, str, tuple[int, int], str], dict[str, Any]
        ] = {}

    @staticmethod
    def textos(valor: Any) -> set[str]:
        """Extrae las cadenas de valor anidado y devuelve un conjunto sin duplicados."""
        if isinstance(valor, str):
            return {valor}
        if isinstance(valor, dict):
            return set().union(
                *(AnalisisLocalService.textos(v) for v in valor.values())
            )
        if isinstance(valor, list):
            return set().union(*(AnalisisLocalService.textos(v) for v in valor))
        return set()

    def recurso(
        self, tipo: str, nombre: str, cancelado: Callable[[], bool]
    ) -> tuple[Path | None, bytes]:
        """Carga recurso por tipo/nombre/versión; retorna ruta y bytes, respetando cancelación."""
        clave = (tipo, str(nombre), self.version)
        anterior = self.recursos.get(clave)
        if anterior is not None and (
            anterior[0] is not None or perf_counter() - anterior[2] < 30
        ):
            return anterior[0], anterior[1]
        if cancelado():
            raise InterruptedError("Análisis sustituido")
        if tipo == "item":
            ruta = data_dragon.get_item_icon_path(
                nombre, self.catalogo.catalogo, self.version, download=False
            )
        elif tipo == "ability":
            campeon, habilidad = nombre.rsplit("|", 1)
            ruta = data_dragon.get_ability_icon_path(
                campeon, habilidad, self.version, download=False
            )
        elif tipo == "splash":
            identificador = "".join(
                caracter
                for caracter in data_dragon.champion_asset_name(nombre)
                if caracter.isalnum()
            )
            ruta = next(
                (
                    candidata
                    for extension in ("jpg", "png", "webp")
                    if (
                        candidata := data_dragon.DATA_DIR
                        / "champion_splashes"
                        / f"{identificador}_0.{extension}"
                    ).is_file()
                ),
                None,
            )
        else:
            funcion = {
                "champion": data_dragon.get_champion_icon_path,
                "rune": data_dragon.get_rune_icon_path,
                "spell": data_dragon.get_spell_icon_path,
            }[tipo]
            ruta = funcion(nombre, self.version, download=False)
        try:
            contenido = ruta.read_bytes() if ruta is not None else b""
        except OSError:
            if tipo != "splash":
                raise
            ruta, contenido = None, b""
        if len(self.recursos) >= 1024:
            self.recursos.pop(next(iter(self.recursos)))
        self.recursos[clave] = (ruta, contenido, perf_counter())
        return ruta, contenido

    def cargar(
        self,
        perfil: dict[str, Any],
        linea: str,
        rango: str,
        pagina_defecto: dict[str, Any],
        cancelado: Callable[[], bool],
    ) -> dict[str, Any]:
        """Prepara perfil/línea/rango y runas por defecto; devuelve datos, recursos y tiempos."""
        inicio = perf_counter()
        rango = normalizar_rango(rango) or rango
        campeon = str(perfil.get("character", ""))
        consulta = self.variantes.repositorio.consultar(campeon, linea, rango)
        variante = copy.deepcopy(consulta.datos)
        if consulta.estado != EstadoDatos.DISPONIBLE:
            return {
                "estado": consulta.estado.value,
                "actualizacion": consulta.actualizacion,
                "perfil": {},
                "variante": None,
                "recomendaciones": [],
                "candidatos_afinidad": [],
                "objetos": {},
                "metadatos": {},
                "rutas": {},
                "imagenes": {},
                "tiempos": {"total_ms": (perf_counter() - inicio) * 1000},
            }
        if cancelado():
            raise InterruptedError("Análisis sustituido")
        variante = self._filtrar_recomendaciones_ilegales(variante, campeon)
        clave_preparacion = (campeon, linea, rango, consulta.revision, self.version)
        anterior = self._preparados.get(clave_preparacion)
        if anterior is not None:
            return dict(
                anterior,
                actualizacion=consulta.actualizacion,
                perfil=copy.deepcopy(anterior["perfil"]),
                variante=copy.deepcopy(anterior["variante"]),
                tiempos={
                    "variante_ms": (perf_counter() - inicio) * 1000,
                    "calculo_ms": 0.0,
                    "recursos_ms": 0.0,
                    "total_ms": (perf_counter() - inicio) * 1000,
                },
            )
        combinado = self._filtrar_recomendaciones_ilegales(
            combinar_perfil(consulta.perfil or perfil, variante), campeon
        )
        estadisticas = variante.get("lane_stats")
        if not isinstance(estadisticas, dict):
            variante = dict(
                variante,
                lane_stats={
                    "rank": rango,
                    "lanes": consulta.lineas or {},
                },
            )
        fin_variante = perf_counter()
        objetos = self.catalogo.objetos_recomendables()
        candidatos_guardados = variante.get("item_candidates")
        fuente_recomendaciones = (
            candidatos_guardados
            if isinstance(candidatos_guardados, list) and candidatos_guardados
            else variante.get("recommendations", [])
        )
        candidatos_afinidad = [
            ItemRecommendation(
                str(valor["item_id"]),
                str(valor["name"]),
                float(valor["score"]),
                tuple(valor["reasons"]),
                tuple(valor["counter_reasons"]),
                str(valor.get("compatibility_label", "Situacional")),
                tuple(valor.get("compatibility_reasons", [])),
                float(valor.get("compatibility_score", 0.0)),
                float(valor.get("matchup_score", 0.0)),
                float(valor.get("build_synergy_score", 0.0)),
            )
            for valor in fuente_recomendaciones
        ]
        recomendaciones = candidatos_afinidad[:30]
        fin_calculo = perf_counter()
        if campeon not in self.metadatos:
            self.metadatos[campeon] = data_dragon.get_champion_data(
                campeon, self.version, download=False
            )
        referencias: set[tuple[str, str]] = {("champion", campeon), ("splash", campeon)}
        referencias.update(
            ("ability", f"{campeon}|{habilidad}") for habilidad in ("Q", "W", "E", "R")
        )
        for grupo in ("counters", "good_against"):
            enfrentamientos = combinado.get("matchups", {}).get(grupo, [])
            referencias.update(
                ("champion", str(v["champion"]))
                for v in enfrentamientos[:5]
                if isinstance(v, dict) and v.get("champion")
            )
        paginas = (
            combinado.get("runes") or combinado.get("common_runes") or [pagina_defecto]
        )
        if isinstance(paginas, list):
            for pagina in paginas[:2] + [pagina_defecto]:
                if isinstance(pagina, dict):
                    for campo in (
                        "keystone",
                        "primary_tree",
                        "secondary_tree",
                        "slots",
                        "secondary_slots",
                        "shards",
                    ):
                        referencias.update(
                            ("rune", nombre)
                            for nombre in self.textos(pagina.get(campo))
                        )
        referencias.update(
            ("spell", nombre)
            for nombre in self.textos(combinado.get("summoner_spells"))
        )
        referencias.update(("item", str(r.item_id)) for r in recomendaciones)
        nombres_objetos = set()
        for campo in (
            "runes",
            "common_runes",
            "most_played_build",
            "starter_items",
            "situational_items",
            "situational_item_candidates",
            "item_candidates",
            "recommended_build",
            "power_curve_and_scaling",
        ):
            nombres_objetos.update(self.textos(combinado.get(campo)))
        for nombre in nombres_objetos:
            identificador = self.catalogo.id_por_nombre(nombre, self.catalogo.catalogo)
            if identificador:
                referencias.add(("item", identificador))
        rutas: dict[tuple[str, str], Path] = {}
        imagenes: dict[str, bytes] = {}
        for tipo, nombre in sorted(referencias):
            ruta, contenido = self.recurso(tipo, nombre, cancelado)
            if ruta is not None:
                rutas[tipo, nombre] = ruta
                imagenes[str(ruta)] = contenido
        fin = perf_counter()
        tiempos = {
            "variante_ms": (fin_variante - inicio) * 1000,
            "calculo_ms": (fin_calculo - fin_variante) * 1000,
            "recursos_ms": (fin - fin_calculo) * 1000,
            "total_ms": (fin - inicio) * 1000,
        }
        REGISTRO.debug("Análisis %s/%s/%s: %s", campeon, linea, rango, tiempos)
        preparado = {
            "actualizacion": consulta.actualizacion,
            "perfil": combinado,
            "variante": variante,
            "recomendaciones": recomendaciones,
            "candidatos_afinidad": candidatos_afinidad,
            "objetos": objetos,
            "metadatos": self.metadatos[campeon],
            "rutas": rutas,
            "imagenes": imagenes,
            "tiempos": tiempos,
        }
        if len(self._preparados) >= 16:
            self._preparados.pop(next(iter(self._preparados)))
        self._preparados[clave_preparacion] = preparado
        return preparado

    def _filtrar_recomendaciones_ilegales(
        self, variante: dict[str, Any], campeon: str
    ) -> dict[str, Any]:
        """Filtra recomendaciones históricas que no son legales en SoloQ.

        Parámetros:
            variante: Datos locales de una línea y un rango.
            campeon: Identificador canónico del campeón seleccionado.

        Retorna:
            Una copia con referencias de objetos no elegibles retiradas.
        """
        objetos_legales = self.catalogo.objetos_recomendables()
        ids_legales = {str(identificador) for identificador in objetos_legales}
        campos_lista = {
            "most_played_build",
            "power_spike_items",
            "core_items",
            "boots",
            "later_item_options",
            "recommended_build",
            "recommended_build_details",
            "situational_item_candidates",
            "item_candidates",
            "recommendations",
        }

        def referencia_legal(valor: Any) -> bool:
            """Comprueba la elegibilidad SoloQ de una referencia de objeto."""
            if isinstance(valor, dict):
                identificador = str(valor.get("item_id") or valor.get("id") or "")
                nombre = str(
                    valor.get("name")
                    or valor.get("item")
                    or (valor.get("basic_info") or {}).get("name", "")
                )
            else:
                identificador = str(valor)
                nombre = str(valor)
            if identificador not in ids_legales:
                identificador = self.catalogo.id_por_nombre(
                    nombre, self.catalogo.catalogo
                )
            if not identificador:
                return False
            return (
                identificador in ids_legales
                and self.catalogo.validar_elegibilidad(
                    identificador,
                    objetos_legales[identificador],
                    campeon,
                    MODO_SOLOQ,
                ).elegible
            )

        def filtrar(valor: Any) -> Any:
            """Conserva solo referencias elegibles en listas o grupos."""
            if isinstance(valor, list):
                return [elemento for elemento in valor if referencia_legal(elemento)]
            if isinstance(valor, dict):
                return {
                    clave: filtrar(elementos)
                    for clave, elementos in valor.items()
                    if isinstance(elementos, list)
                }
            return valor

        resultado = copy.deepcopy(variante)
        for campo in campos_lista:
            if campo in resultado:
                resultado[campo] = filtrar(resultado[campo])
        entradas_iniciales = resultado.get("starter_item_entries")
        if isinstance(entradas_iniciales, list) and entradas_iniciales:
            resultado["starter_item_entries"] = [
                entrada
                for entrada in entradas_iniciales
                if isinstance(entrada, dict)
                and self.catalogo.validar_objeto_inicial(
                    str(entrada.get("item_id", "")), campeon, MODO_SOLOQ
                ).elegible
            ]
            ids_iniciales = [
                str(entrada["item_id"])
                for entrada in resultado["starter_item_entries"]
                for _ in range(max(1, int(entrada.get("quantity", 1) or 1)))
            ]
            resultado["starter_item_ids"] = [int(item_id) for item_id in ids_iniciales]
            resultado["starter_items"] = [
                str(self.catalogo.catalogo[item_id].get("name", item_id))
                for item_id in ids_iniciales
                if isinstance(self.catalogo.catalogo.get(item_id), dict)
            ]
        elif isinstance(resultado.get("starter_item_ids"), list):
            ids_iniciales = [
                str(item_id)
                for item_id in resultado["starter_item_ids"]
                if self.catalogo.validar_objeto_inicial(
                    str(item_id), campeon, MODO_SOLOQ
                ).elegible
            ]
            resultado["starter_item_ids"] = [int(item_id) for item_id in ids_iniciales]
            resultado["starter_items"] = [
                str(self.catalogo.catalogo[item_id].get("name", item_id))
                for item_id in ids_iniciales
                if isinstance(self.catalogo.catalogo.get(item_id), dict)
            ]
        if isinstance(resultado.get("situational_items"), dict):
            resultado["situational_items"] = filtrar(resultado["situational_items"])
        return resultado
