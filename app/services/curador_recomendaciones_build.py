"""Selecciona builds coherentes y alternativas situacionales con evidencia."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Iterable
from typing import Any

from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
from app.services.synergy_recommendation_service import SynergyRecommendationService


class CuradorRecomendacionesBuild:
    """Normaliza las recomendaciones visibles sin modificar los datos fuente."""

    LIMITE_SITUACIONAL = 5
    MINIMO_SITUACIONAL = 2
    OBJETIVO_SITUACIONAL = 3
    CATEGORIAS = ("corta_curas", "tanque", "asesino", "utilidad_y_defensa")
    VERSION_ALGORITMO = "rune-build-v1"

    def __init__(
        self,
        catalogo: CatalogoAnalisisLocal,
        objetos_estrictos: dict[str, dict[str, Any]],
    ) -> None:
        """Prepara el curador con el catálogo y las clases estrictas.


        Parámetros: catálogo de objetos y metadatos de clasificación.
        Retorno: None; conserva las referencias para validar recomendaciones.
        """
        self.catalogo = catalogo
        self.objetos_estrictos = objetos_estrictos
        self.motor_sinergia = SynergyRecommendationService()

    def curar(
        self,
        variante: dict[str, Any],
        perfil: dict[str, Any],
        candidatos: Iterable[Any],
        pagina_runas: dict[str, Any] | None = None,
        candidatos_preparados: bool = False,
    ) -> dict[str, Any]:
        """Cura una build contextual para la p?gina de runas seleccionada.

        Par?metros:
            variante: estad?sticas de campe?n, l?nea y rango.
            perfil: identidad y mec?nicas del campe?n.
            candidatos: recomendaciones puntuadas disponibles.
            pagina_runas: p?gina activa con build y estad?sticas propias.
            candidatos_preparados: indica que el pool com?n ya fue calculado.

        Retorna:
            Copia curada con n?cleo, progresi?n y alternativas situacionales."""
        resultado = copy.deepcopy(variante)
        if pagina_runas is not None:
            resultado = self._aplicar_contexto_runas(resultado, pagina_runas)
        lista_candidatos = list(candidatos)
        if not candidatos_preparados:
            lista_candidatos = self._completar_candidatos(perfil, lista_candidatos)
        build, nucleo = self._seleccionar_build(
            resultado, perfil, lista_candidatos, pagina_runas
        )
        resultado["recommended_core_items"] = nucleo
        resultado["recommended_build"] = build
        resultado["recommended_build_details"] = copy.deepcopy(build)
        self._seleccionar_situacionales(
            resultado, perfil, lista_candidatos, build, pagina_runas
        )
        diagnosticos = resultado.get("recommendation_diagnostics")
        diagnosticos = dict(diagnosticos) if isinstance(diagnosticos, dict) else {}
        diagnosticos["curated_core_items"] = len(nucleo)
        diagnosticos["curated_build_items"] = len(build)
        diagnosticos["synergy_candidate_count"] = len(lista_candidatos)
        diagnosticos["situational_coverage_failures"] = list(
            resultado.get("situational_coverage_failures", [])
        )
        diagnosticos["displayed_situational_candidates"] = sum(
            len(valores) for valores in resultado["situational_items"].values()
        )
        resultado["recommendation_diagnostics"] = diagnosticos
        return resultado

    def preparar_candidatos(
        self, perfil: dict[str, Any], candidatos: Iterable[Any]
    ) -> list[Any]:
        """Completa una sola vez el catálogo de candidatos para páginas hermanas.

        Parámetros:
            perfil: perfil mecánico del campeón.
            candidatos: recomendaciones estadísticas o previamente puntuadas.

        Retorna:
            Candidatos únicos ordenados por afinidad, listos para curar varias páginas.
        """
        return self._completar_candidatos(perfil, list(candidatos))

    @staticmethod
    def clave_pagina_runas(
        pagina: dict[str, Any],
        parche: str,
        campeon: str = "",
        linea: str = "",
        rango: str = "",
        contexto: str = "",
    ) -> str:
        """Genera una clave estable según parche, versión del algoritmo y runas.

        Parámetros:
            pagina: configuración seleccionable de runas.
            parche: versión de catálogo usada para validar la build.
            campeon: identificador del campeón.
            linea: línea seleccionada.
            rango: rango estadístico activo.
            contexto: revisión del perfil u otra entrada contextual.

        Retorna:
            Huella SHA-256 opaca de la configuración estratégica.
        """
        datos = {
            campo: pagina.get(campo)
            for campo in (
                "primary_tree",
                "primary_tree_id",
                "keystone",
                "keystone_id",
                "slots",
                "slot_ids",
                "secondary_tree",
                "secondary_tree_id",
                "secondary_slots",
                "secondary_slot_ids",
                "shards",
                "shard_ids",
                "build",
            )
        }
        serializado = json.dumps(
            {
                "patch": parche,
                "champion": campeon,
                "role": linea,
                "rank": rango,
                "context": contexto,
                "algorithm": CuradorRecomendacionesBuild.VERSION_ALGORITMO,
                "runes": datos,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serializado.encode("utf-8")).hexdigest()

    @staticmethod
    def _aplicar_contexto_runas(
        variante: dict[str, Any], pagina: dict[str, Any]
    ) -> dict[str, Any]:
        """Aísla la build y las estadísticas asociadas a una página concreta.

        Parámetros:
            variante: datos generales de campeón, línea y rango.
            pagina: página seleccionada, con build y opciones si existen.

        Retorna:
            Copia de la variante cuyos datos de objetos corresponden a esa página.
        """
        resultado = copy.deepcopy(variante)
        build = pagina.get("build")
        if isinstance(build, list) and build:
            entradas = [
                {"name": str(nombre), "slot": posicion}
                for posicion, nombre in enumerate(build, start=1)
                if nombre
            ]
            resultado["core_build"] = entradas[:3]
            resultado["most_played_build"] = build
        opciones = pagina.get("item_options")
        if isinstance(opciones, dict) and opciones:
            resultado["item_options"] = copy.deepcopy(opciones)
            resultado["source_situational_items"] = {}
            resultado["situational_items"] = {}
        return resultado

    def _completar_candidatos(
        self, perfil: dict[str, Any], candidatos: list[Any]
    ) -> list[Any]:
        """Amplía la cobertura con afinidad local calculada sobre el catálogo legal.

        Parámetros:
            perfil: datos globales del campeón y del arquetipo.
            candidatos: recomendaciones estadísticas o de afinidad persistidas.

        Retorna:
            Candidatos únicos ordenados por la mejor puntuación disponible.
        """
        basic_info = perfil.get("basic_info", {})
        estilo = (
            str(basic_info.get("play_style", "Adaptable"))
            if isinstance(basic_info, dict)
            else "Adaptable"
        )
        nuevos = self.motor_sinergia.rank_candidates(
            perfil,
            estilo,
            self.catalogo.objetos_recomendables(),
            [],
            catalog_patch=self.catalogo.parche,
        )
        por_id: dict[str, Any] = {str(valor.item_id): valor for valor in nuevos}
        for candidato in candidatos:
            identificador = str(self._valor(candidato, "item_id", ""))
            if not identificador:
                continue
            existente = por_id.get(identificador)
            if existente is None or self._numero(
                self._valor(candidato, "score", 0.0)
            ) > self._numero(self._valor(existente, "score", 0.0)):
                por_id[identificador] = candidato
        return list(por_id.values())

    def _seleccionar_build(
        self,
        variante: dict[str, Any],
        perfil: dict[str, Any],
        candidatos: list[Any],
        pagina_runas: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Selecciona n?cleo y progresi?n con estad?sticas condicionadas a las runas.

        Par?metros:
            variante: variante general o adaptada a la p?gina activa.
            perfil: identidad y estilo del campe?n.
            candidatos: afinidades indexables para puntuar opciones.
            pagina_runas: configuraci?n de runas que condiciona build y ranking.

        Retorna:
            Build de hasta seis objetos y su n?cleo inicial de tres."""
        campeon = str(perfil.get("character") or "")
        candidatos_por_id = {
            str(self._valor(candidato, "item_id", "")): candidato
            for candidato in candidatos
            if self._valor(candidato, "item_id", "")
        }
        iniciales = {str(valor) for valor in variante.get("starter_item_ids", [])}
        iniciales.update(
            str(valor.get("item_id"))
            for valor in variante.get("starter_item_entries", [])
            if isinstance(valor, dict) and valor.get("item_id")
        )
        usados: set[str] = set()
        nucleo: list[dict[str, Any]] = []
        secuencia: list[tuple[Any, str]] = []
        for valor in self._ordenar_por_puesto(variante.get("core_build")):
            secuencia.append((valor, "core"))
        for valor in self._lista(variante.get("most_played_build")):
            secuencia.append((valor, "U.GG"))
        for valor, origen in secuencia:
            entrada = self._entrada_objeto(valor, origen, campeon)
            if not entrada or self._es_bota(entrada["item_id"]):
                continue
            identificador = entrada["item_id"]
            if identificador in usados or identificador in iniciales:
                continue
            if len(nucleo) < 3:
                nucleo.append(
                    self._anotar_candidato(
                        entrada, candidatos_por_id.get(identificador)
                    )
                )
                usados.add(identificador)
        opciones = self._opciones_estadisticas(variante)
        opciones.sort(
            key=lambda opcion: (
                self._puntuacion(opcion, candidatos_por_id)
                + self._bonificacion_runas(
                    str(opcion.get("item_id") or ""), pagina_runas
                )
            ),
            reverse=True,
        )
        if len(nucleo) < 3:
            for opcion in opciones:
                entrada = self._entrada_objeto(opcion, "U.GG", campeon)
                if not entrada:
                    continue
                identificador = entrada["item_id"]
                if (
                    identificador in usados
                    or identificador in iniciales
                    or self._es_bota(identificador)
                    or not self._compatible(
                        str(perfil.get("basic_info", {}).get("play_style", "")),
                        identificador,
                    )
                    or not self._tiene_muestra(opcion)
                    or self._grupo_duplicado(identificador, usados)
                ):
                    continue
                nucleo.append(
                    self._anotar_candidato(
                        entrada, candidatos_por_id.get(identificador), opcion
                    )
                )
                usados.add(identificador)
                if len(nucleo) == 3:
                    break
        build = copy.deepcopy(nucleo)
        seleccion_bota = self._seleccionar_bota(variante, perfil, campeon, usados)
        if seleccion_bota and len(build) < 6:
            build.append(seleccion_bota)
            usados.add(seleccion_bota["item_id"])
        for valor in self._lista(variante.get("most_played_build")):
            entrada = self._entrada_objeto(valor, "U.GG", campeon)
            if not entrada or self._es_bota(entrada["item_id"]):
                continue
            identificador = entrada["item_id"]
            if identificador in usados or identificador in iniciales:
                continue
            build.append(
                self._anotar_candidato(entrada, candidatos_por_id.get(identificador))
            )
            usados.add(identificador)
            if len(build) == 6:
                break
        if len(build) < 6:
            for opcion in opciones:
                entrada = self._entrada_objeto(opcion, "U.GG", campeon)
                if not entrada:
                    continue
                identificador = entrada["item_id"]
                if (
                    identificador in usados
                    or identificador in iniciales
                    or (seleccion_bota and self._es_bota(identificador))
                    or not self._compatible(
                        str(perfil.get("basic_info", {}).get("play_style", "")),
                        identificador,
                    )
                    or not self._tiene_muestra(opcion)
                ):
                    continue
                if self._grupo_duplicado(identificador, usados):
                    continue
                build.append(
                    self._anotar_candidato(
                        entrada, candidatos_por_id.get(identificador), opcion
                    )
                )
                usados.add(identificador)
                if len(build) == 6:
                    break
        return build[:6], nucleo[:3]

    def _seleccionar_situacionales(
        self,
        variante: dict[str, Any],
        perfil: dict[str, Any],
        candidatos: list[Any],
        build: list[dict[str, Any]],
        pagina_runas: dict[str, Any] | None = None,
    ) -> None:
        """Selecciona alternativas coherentes con el n?cleo y las runas activas.

        Par?metros:
            variante: variante con opciones estad?sticas.
            perfil: perfil del campe?n.
            candidatos: pool validado de afinidad y estad?sticas.
            build: progresi?n ya seleccionada.
            pagina_runas: p?gina que modifica arquetipo y orden situacional.

        Retorna:
            None; guarda las categor?as y diagn?sticos en la variante."""
        campeon = str(perfil.get("character") or "")
        ids_build = {str(item["item_id"]) for item in build[:3]}
        opciones = {
            str(option.get("item_id") or ""): option
            for option in self._opciones_estadisticas(variante)
        }
        pool_estadistico = self._pool_situacional(variante, campeon)
        arquetipo = self._arquetipo_build(perfil, build[:3], pagina_runas)
        grupos: dict[str, list[dict[str, Any]]] = {
            categoria: [] for categoria in self.CATEGORIAS
        }
        vistos: set[str] = set(ids_build)
        for candidato in candidatos:
            identificador = str(self._valor(candidato, "item_id", ""))
            if not identificador or identificador in vistos:
                continue
            if self._grupo_duplicado(identificador, ids_build):
                continue
            entrada = self._entrada_objeto(
                {"item_id": identificador, "name": self._valor(candidato, "name", "")},
                "SOLRALOL",
                campeon,
            )
            if not entrada:
                continue
            compatibilidad = self._numero(
                self._valor(candidato, "compatibility_score", 0.0)
            )
            if compatibilidad <= -12:
                continue
            categoria = self._categoria_situacional(identificador, arquetipo)
            if not categoria:
                continue
            puntuacion_afinidad = self._numero(self._valor(candidato, "score", 0.0))
            if not self._compatible_situacional(
                perfil,
                identificador,
                categoria,
                puntuacion_afinidad,
                arquetipo,
                opciones.get(identificador, {}),
                identificador in pool_estadistico,
            ):
                continue
            opcion = opciones.get(identificador, {})
            entrada.update(
                {
                    "score": round(
                        self._puntuacion(opcion, {identificador: candidato})
                        + self._bonificacion_runas(identificador, pagina_runas),
                        2,
                    ),
                    "category": categoria,
                    "origin": "U.GG"
                    if identificador in pool_estadistico
                    else "SOLRALOL",
                    "recommendation_source": (
                        "statistical"
                        if identificador in pool_estadistico
                        and self._tiene_muestra(opcion)
                        else "champion_synergy"
                    ),
                    "has_statistical_evidence": self._tiene_muestra(opcion),
                    "reasons": list(self._valor(candidato, "reasons", ())),
                    "compatibility_label": str(
                        self._valor(candidato, "compatibility_label", "Situacional")
                    ),
                    "compatibility_reasons": list(
                        self._valor(candidato, "compatibility_reasons", ())
                    ),
                    "compatibility_score": self._numero(
                        self._valor(candidato, "compatibility_score", 0.0)
                    ),
                    "matchup_score": self._numero(
                        self._valor(candidato, "matchup_score", 0.0)
                    ),
                    "build_synergy_score": self._numero(
                        self._valor(candidato, "build_synergy_score", 0.0)
                    ),
                    "situational_reason": {
                        "corta_curas": "Considerar cuando la curación rival sea una amenaza relevante.",
                        "tanque": "Elegir frente al tipo de daño que realmente deba resistirse.",
                        "asesino": "Priorizar si la penetración o el remate encajan con el plan de daño.",
                        "utilidad_y_defensa": "Reservar para una amenaza o necesidad defensiva concreta.",
                    }[categoria],
                }
            )
            for campo in ("games", "wins", "win_rate", "sample_status", "source"):
                if campo in opcion:
                    entrada[campo] = opcion[campo]
            grupos[categoria].append(entrada)
            vistos.add(identificador)
        situacionales: dict[str, list[str]] = {}
        seleccionados: set[str] = set()
        curados: list[dict[str, Any]] = []
        for categoria, entradas in grupos.items():
            entradas.sort(
                key=lambda entrada: (
                    self._numero(entrada.get("score")),
                    self._numero(entrada.get("compatibility_score")),
                    self._numero(entrada.get("matchup_score")),
                ),
                reverse=True,
            )
            evidenciados = [
                entrada for entrada in entradas if entrada["has_statistical_evidence"]
            ]
            afinidad = [
                entrada
                for entrada in entradas
                if not entrada["has_statistical_evidence"]
            ]
            elegidos = self._elegir_categoria(evidenciados, afinidad, seleccionados)
            curados.extend(elegidos)
            seleccionados.update(str(entrada["item_id"]) for entrada in elegidos)
            situacionales[categoria] = [str(entrada["name"]) for entrada in elegidos]
        variante["situational_item_candidates"] = curados
        variante["situational_items"] = situacionales
        faltantes = [
            categoria
            for categoria, valores in situacionales.items()
            if len(valores) < self.MINIMO_SITUACIONAL
        ]
        variante["situational_coverage_failures"] = faltantes

    def _compatible_situacional(
        self,
        perfil: dict[str, Any],
        item_id: str,
        categoria: str,
        puntuacion: float,
        arquetipo: str,
        opcion: dict[str, Any],
        fuente_estadistica: bool,
    ) -> bool:
        """Valida estadísticas, arquetipo y afinidad táctica de una alternativa.

        Parámetros:
            perfil: identidad mecánica y estilo del campeón.
            item_id: ID del objeto en el catálogo actual.
            categoria: propósito situacional verificado del objeto.
            puntuacion: afinidad calculada por el motor del campeón.
            arquetipo: patrón de build derivado de los tres objetos de núcleo.
            opcion: muestra estadística auténtica si está disponible.
            fuente_estadistica: indica que el objeto procede de datos del proveedor.

        Retorna:
            True si supera los requisitos duros de uso de estadísticas y clase.
        """
        datos = self._estadisticas_objeto(item_id)
        etiquetas = set(datos["tags"])
        stats = datos["stats"]
        basic_info = perfil.get("basic_info", {})
        estilo = (
            str(basic_info.get("play_style", ""))
            if isinstance(basic_info, dict)
            else ""
        )
        attrs = perfil.get("combat_attributes", {})
        attrs = attrs if isinstance(attrs, dict) else {}
        dano = str(basic_info.get("damage_type", "")).casefold()
        poder_ap = self._numero(attrs.get("attack_power", 0))
        daño_ap = self._numero(stats.get("ability_power", 0)) or self._numero(
            stats.get("FlatMagicDamageMod", 0)
        )
        daño_ad = self._numero(stats.get("attack_damage", 0)) or self._numero(
            stats.get("FlatPhysicalDamageMod", 0)
        )
        critico = self._numero(stats.get("critical_strike_chance_percent", 0)) or (
            self._numero(stats.get("FlatCritChanceMod", 0)) * 100
        )
        letalidad = self._numero(stats.get("lethality", 0))
        if (
            daño_ap
            and not (
                arquetipo.startswith("ap_")
                or arquetipo == "hibrido_ap"
                or ("ap" in dano and poder_ap >= 6)
            )
            and not self._evidencia_fuerte(opcion, fuente_estadistica, arquetipo)
        ):
            return False
        if daño_ad and arquetipo.startswith("ap_") and not daño_ap:
            return False
        if (
            critico
            and arquetipo != "ad_crit"
            and self._numero(attrs.get("critic", 0)) < 7
            and not self._evidencia_fuerte(opcion, fuente_estadistica, arquetipo)
        ):
            return False
        if (
            letalidad
            and arquetipo != "ad_letalidad"
            and not self._evidencia_fuerte(opcion, fuente_estadistica, arquetipo)
        ):
            return False
        if not self._compatible(estilo, item_id):
            if categoria == "corta_curas":
                return True
            if categoria == "tanque":
                return puntuacion >= 15 and bool(
                    etiquetas & {"Health", "Armor", "SpellBlock"}
                )
            return False
        if categoria == "tanque" and not etiquetas.intersection(
            {"Health", "Armor", "SpellBlock"}
        ):
            return False
        if categoria == "utilidad_y_defensa":
            return bool(
                etiquetas.intersection({"Health", "Armor", "SpellBlock", "Active"})
                or datos["functionality"].get("has_active")
            )
        return True

    def _categoria_situacional(self, item_id: str, arquetipo: str) -> str:
        """Adapta la categoría ofensiva al patrón de daño del núcleo elegido.

        Parámetros:
            item_id: objeto que ya existe y está clasificado en el catálogo.
            arquetipo: estilo inferido del núcleo activo.

        Retorna:
            Categoría primaria basada en efectos o daño útil para ese arquetipo.
        """
        categoria = self._categoria(item_id)
        if categoria:
            return categoria
        if arquetipo not in {"ad_bruiser", "ad_on_hit", "ad_crit", "ap_mage"}:
            return ""
        datos = self._estadisticas_objeto(item_id)
        stats = datos["stats"]
        etiquetas = datos["tags"]
        if arquetipo == "ap_mage":
            ofensivo = bool(
                self._numero(stats.get("ability_power", 0))
                or self._numero(stats.get("FlatMagicDamageMod", 0))
            )
        else:
            ofensivo = bool(
                self._numero(stats.get("attack_damage", 0))
                or self._numero(stats.get("FlatPhysicalDamageMod", 0))
            )
        pasiva = datos["functionality"]
        if ofensivo and (
            etiquetas.intersection({"AbilityHaste", "Active", "OnHit"})
            or self._numero(stats.get("ability_haste", 0)) >= 10
            or pasiva.get("has_active") is True
        ):
            return "asesino"
        return ""

    def _arquetipo_build(
        self,
        perfil: dict[str, Any],
        nucleo: list[dict[str, Any]],
        pagina_runas: dict[str, Any] | None = None,
    ) -> str:
        """Infiere el arquetipo combinando mec?nicas, n?cleo y p?gina de runas.

        Par?metros:
            perfil: escalados primarios y estilo del campe?n.
            nucleo: objetos centrales elegidos para la build.
            pagina_runas: keystone y runas menores activas.

        Retorna:
            Clave estable de arquetipo para validar candidatos situacionales."""
        basic_info = perfil.get("basic_info", {})
        basic_info = basic_info if isinstance(basic_info, dict) else {}
        atributos = perfil.get("combat_attributes", {})
        atributos = atributos if isinstance(atributos, dict) else {}
        dano = str(basic_info.get("damage_type", "")).casefold()
        estilo = str(basic_info.get("play_style", "")).casefold()
        conteos = {"ap": 0, "crit": 0, "letalidad": 0, "on_hit": 0}
        for entrada in nucleo:
            datos = self._estadisticas_objeto(str(entrada.get("item_id", "")))
            stats = datos["stats"]
            etiquetas = datos["tags"]
            conteos["ap"] += int(
                bool(
                    self._numero(stats.get("ability_power", 0))
                    or self._numero(stats.get("FlatMagicDamageMod", 0))
                )
            )
            conteos["crit"] += int(
                bool(
                    self._numero(stats.get("critical_strike_chance_percent", 0))
                    or self._numero(stats.get("FlatCritChanceMod", 0))
                    or "CriticalStrike" in etiquetas
                )
            )
            conteos["letalidad"] += int(bool(self._numero(stats.get("lethality", 0))))
            conteos["on_hit"] += int(
                bool({"OnHit", "AttackSpeed"}.intersection(etiquetas))
            )
        modo_runa = self._modo_runa(pagina_runas)
        poder_ap = self._numero(atributos.get("attack_power", 0))
        if conteos["ap"] >= 2 or (conteos["ap"] >= 1 and poder_ap >= 6):
            return "ap_mage"
        if conteos["letalidad"] >= 2 or (
            conteos["letalidad"] >= 1 and modo_runa == "burst"
        ):
            return "ad_letalidad"
        if conteos["crit"] >= 2 and (
            "marksman" in estilo or self._numero(atributos.get("critic", 0)) >= 5
        ):
            return "ad_crit"
        if conteos["on_hit"] >= 2:
            return "ad_on_hit"
        if (
            "ap" in dano
            and poder_ap >= 6
            and estilo in {"mage", "assassin", "enchanter", "support"}
        ):
            return "ap_enchanter" if estilo in {"enchanter", "support"} else "ap_mage"
        if (
            ("hybrid" in dano or "hibrid" in dano)
            and poder_ap >= 5
            and self._numero(atributos.get("attack_damage", 0)) >= 5
        ):
            return "hibrido_ap"
        if (
            "ad" in dano
            or "physical" in dano
            or "fisic" in dano
            or self._numero(atributos.get("attack_damage", 0)) > poder_ap
        ):
            return (
                "ad_bruiser"
                if estilo in {"diver", "fighter", "juggernaut", "tank", "bruiser"}
                else "ad_fisico"
            )
        if estilo in {"vanguard", "warden", "tank"}:
            return "tank"
        if estilo in {"enchanter", "support"}:
            return "ap_enchanter" if poder_ap >= 5 else "support"
        return "adaptable"

    def _modo_runa(self, pagina: dict[str, Any] | None) -> str:
        """Traduce keystone y árbol a una tendencia de combate general.

        Parámetros:
            pagina: página que aporta keystone, árboles y runas menores.

        Retorna:
            Tendencia `burst`, `sostenido`, `durabilidad` o cadena vacía.
        """
        if not isinstance(pagina, dict):
            return ""
        keystone = str(pagina.get("keystone", "")).casefold()
        if any(
            nombre in keystone
            for nombre in (
                "hail of blades",
                "electrocute",
                "first strike",
                "dark harvest",
            )
        ):
            return "burst"
        if any(
            nombre in keystone
            for nombre in ("press the attack", "lethal tempo", "conqueror")
        ):
            return "sostenido"
        if any(nombre in keystone for nombre in ("grasp", "aftershock", "guardian")):
            return "durabilidad"
        runas_menores = " ".join(
            str(valor).casefold()
            for campo in ("slots", "runes", "secondary_slots", "shards")
            for valor in (
                pagina.get(campo) if isinstance(pagina.get(campo), list) else []
            )
        )
        if any(
            nombre in runas_menores
            for nombre in (
                "sudden impact",
                "cheap shot",
                "first strike",
                "scorch",
                "coup de grace",
                "impacto repentino",
            )
        ):
            return "burst"
        if any(
            nombre in runas_menores
            for nombre in (
                "alacrity",
                "triumph",
                "last stand",
                "legend: haste",
                "celeridad",
            )
        ):
            return "sostenido"
        if any(
            nombre in runas_menores
            for nombre in (
                "conditioning",
                "bone plating",
                "second wind",
                "overgrowth",
                "revitalize",
                "acondicionamiento",
                "crecimiento excesivo",
            )
        ):
            return "durabilidad"
        return ""

    def _bonificacion_runas(self, item_id: str, pagina: dict[str, Any] | None) -> float:
        """Ajusta afinidad solo por estadísticas y efectos verificables del objeto.

        Parámetros:
            item_id: objeto evaluado en el catálogo del parche.
            pagina: página activa, si existe.

        Retorna:
            Ajuste acotado al ranking, sin crear evidencia estadística.
        """
        modo = self._modo_runa(pagina)
        if not modo:
            return 0.0
        datos = self._estadisticas_objeto(item_id)
        stats = datos["stats"]
        etiquetas = datos["tags"]
        daño_fisico = bool(
            self._numero(stats.get("attack_damage", 0))
            or self._numero(stats.get("FlatPhysicalDamageMod", 0))
        )
        daño_ap = bool(
            self._numero(stats.get("ability_power", 0))
            or self._numero(stats.get("FlatMagicDamageMod", 0))
        )
        letalidad = bool(self._numero(stats.get("lethality", 0)))
        velocidad = bool({"AttackSpeed", "OnHit"}.intersection(etiquetas))
        haste = bool(
            self._numero(stats.get("ability_haste", 0)) >= 10
            or "AbilityHaste" in etiquetas
        )
        salud = bool(self._numero(stats.get("health", 0)) or "Health" in etiquetas)
        if modo == "burst":
            return (
                3.0
                if daño_fisico and letalidad
                else 1.0
                if daño_fisico or daño_ap
                else 0.0
            )
        if modo == "sostenido":
            return (
                2.0
                if daño_fisico and (velocidad or haste)
                else 1.0
                if daño_fisico and salud
                else 0.0
            )
        return (
            1.5 if salud or "Armor" in etiquetas or "SpellBlock" in etiquetas else 0.0
        )

    def _estadisticas_objeto(self, item_id: str) -> dict[str, Any]:
        """Combina estadísticas y efectos estrictos con el catálogo del parche.

        Parámetros:
            item_id: ID canónico del objeto legal.

        Retorna:
            Metadatos unificados sin descartar los efectos estructurados estrictos.
        """
        item = self.catalogo.catalogo.get(item_id, {})
        estricto = self.objetos_estrictos.get(item_id, {})
        stats = dict(item.get("stats", {})) if isinstance(item, dict) else {}
        stats.update(
            estricto.get("stats", {}) if isinstance(estricto.get("stats"), dict) else {}
        )
        funcionalidad = estricto.get("functionality", {})
        return {
            "stats": stats,
            "tags": set(item.get("tags", [])) | set(estricto.get("tags", [])),
            "description": " ".join(
                str(item.get(campo, ""))
                for campo in (
                    "description",
                    "description_en",
                    "description_es",
                    "plaintext",
                )
            ),
            "functionality": (funcionalidad if isinstance(funcionalidad, dict) else {}),
        }

    @staticmethod
    def _evidencia_fuerte(opcion: dict[str, Any], fuente: bool, arquetipo: str) -> bool:
        """Reconoce una excepción de itemización solo con evidencia amplia.

        Parámetros:
            opcion: registro estadístico del campeón y rol.
            fuente: confirma que el objeto procede de una referencia estadística.
            arquetipo: patrón de la build que se pretende justificar.

        Retorna:
            True si la muestra declara el mismo arquetipo y lo sustenta ampliamente.
        """
        if not fuente or str(opcion.get("build_archetype", "")) != arquetipo:
            return False
        try:
            partidas = int(opcion.get("games", 0) or 0)
            win_rate = float(opcion.get("win_rate", 0) or 0)
        except (TypeError, ValueError):
            return False
        return partidas >= 300 and 0.52 <= win_rate <= 1.0

    def _elegir_categoria(
        self,
        evidenciados: list[dict[str, Any]],
        afinidad: list[dict[str, Any]],
        seleccionados: set[str],
    ) -> list[dict[str, Any]]:
        """Selecciona opciones únicas y relaja grupos exclusivos si falta cobertura.

        Parámetros:
            evidenciados: candidatos con muestra real, ordenados por puntuación.
            afinidad: candidatos locales sin muestra estadística.
            seleccionados: IDs elegidos en categorías anteriores.

        Retorna:
            Hasta el máximo permitido, priorizando IDs y grupos distintos.
        """
        elegidos: list[dict[str, Any]] = []
        pool = evidenciados + afinidad
        for permitir_grupo_repetido, objetivo in (
            (False, self.OBJETIVO_SITUACIONAL),
            (True, self.MINIMO_SITUACIONAL),
        ):
            for entrada in pool:
                identificador = str(entrada["item_id"])
                if identificador in seleccionados or any(
                    identificador == str(item["item_id"]) for item in elegidos
                ):
                    continue
                if not permitir_grupo_repetido and self._grupo_duplicado(
                    identificador,
                    seleccionados | {str(item["item_id"]) for item in elegidos},
                ):
                    continue
                elegidos.append(entrada)
                if len(elegidos) >= min(objetivo, self.LIMITE_SITUACIONAL):
                    return elegidos
            if len(elegidos) >= objetivo:
                break
        return elegidos

    def _pool_situacional(self, variante: dict[str, Any], campeon: str) -> set[str]:
        """Obtiene solo referencias que aparecen en las opciones de la fuente.


        Parámetros: variante y campeón para validar elegibilidad.
        Retorno: conjunto de IDs estadísticamente respaldados y legales.
        """
        origen = variante.get("source_situational_items")
        if not isinstance(origen, dict) or not any(
            isinstance(valores, list) and valores for valores in origen.values()
        ):
            origen = variante.get("situational_items", {})
            if isinstance(origen, dict):
                variante["source_situational_items"] = copy.deepcopy(origen)
        referencias = (
            [
                valor
                for valores in origen.values()
                if isinstance(valores, list)
                for valor in valores
            ]
            if isinstance(origen, dict)
            else []
        )
        referencias.extend(self._opciones_estadisticas(variante))
        return {
            entrada["item_id"]
            for valor in referencias
            if (entrada := self._entrada_objeto(valor, "U.GG", campeon))
        }

    def _entrada_objeto(
        self, valor: Any, origen: str, campeon: str
    ) -> dict[str, Any] | None:
        """Normaliza una referencia y comprueba disponibilidad y coste.


        Parámetros: referencia, procedencia y campeón asociado.
        Retorno: datos canónicos del objeto o None si no es elegible.
        """
        item_id = str(self._valor(valor, "item_id", "") or self._valor(valor, "id", ""))
        nombre = str(
            self._valor(valor, "name", "") or valor if isinstance(valor, str) else ""
        )
        if not item_id or item_id not in self.catalogo.catalogo:
            item_id = self.catalogo.id_por_nombre(nombre, self.catalogo.catalogo)
        objeto = self.catalogo.catalogo.get(item_id)
        if not item_id or not isinstance(objeto, dict):
            return None
        if not self.catalogo.validar_elegibilidad(
            item_id, objeto, campeon, "SR_RANKED_SOLO_DUO"
        ).elegible:
            return None
        oro = objeto.get("gold", {})
        if not isinstance(oro, dict) or not oro.get("purchasable"):
            return None
        try:
            coste = int(oro.get("total", 0) or 0)
        except (TypeError, ValueError):
            return None
        if coste < 1000 and "Boots" not in objeto.get("tags", []):
            return None
        return {
            "item_id": item_id,
            "name": str(
                objeto.get("name_es") or objeto.get("name") or nombre or item_id
            ),
            "origin": origen,
        }

    def _seleccionar_bota(
        self,
        variante: dict[str, Any],
        perfil: dict[str, Any],
        campeon: str,
        usados: set[str],
    ) -> dict[str, Any] | None:
        """Selecciona botas observadas o compatibles con el estilo.


        Parámetros: variante, perfil, campeón y objetos ya seleccionados.
        Retorno: la mejor bota legal o None si no hay una disponible.
        """
        for valor in self._lista(variante.get("most_played_build")):
            entrada = self._entrada_objeto(valor, "U.GG", campeon)
            if (
                entrada
                and self._es_bota(entrada["item_id"])
                and entrada["item_id"] not in usados
            ):
                return entrada
        for valor in self._lista(variante.get("boots")):
            entrada = self._entrada_objeto(valor, "U.GG", campeon)
            if (
                entrada
                and self._es_bota(entrada["item_id"])
                and entrada["item_id"] not in usados
            ):
                return entrada
        estilo = str(perfil.get("basic_info", {}).get("play_style", "")).casefold()
        elegibles: list[tuple[int, str, dict[str, Any]]] = []
        for item_id, objeto in self.catalogo.catalogo.items():
            if "Boots" not in objeto.get("tags", []):
                continue
            entrada = self._entrada_objeto(
                {"item_id": str(item_id)}, "SOLRALOL", campeon
            )
            if not entrada or entrada["item_id"] in usados:
                continue
            etiquetas = set(objeto.get("tags", []))
            try:
                coste = int(objeto.get("gold", {}).get("total", 0) or 0)
            except (TypeError, ValueError):
                continue
            if coste < 1000:
                continue
            prioridad = (
                3
                if any(clase in estilo for clase in ("juggernaut", "fighter", "diver"))
                and "CooldownReduction" in etiquetas
                else 0
            )
            prioridad += (
                3
                if any(clase in estilo for clase in ("marksman", "adc"))
                and "AttackSpeed" in etiquetas
                else 0
            )
            prioridad += (
                2
                if any(clase in estilo for clase in ("mage", "assassin"))
                and "MagicPenetration" in etiquetas
                else 0
            )
            prioridad += (
                2
                if any(clase in estilo for clase in ("tank", "support", "vanguard"))
                and etiquetas.intersection({"Armor", "SpellBlock", "Tenacity"})
                else 0
            )
            elegibles.append((prioridad, entrada["item_id"], entrada))
        return (
            max(elegibles, key=lambda valor: (valor[0], valor[1]))[2]
            if elegibles
            else None
        )

    def _opciones_estadisticas(self, variante: dict[str, Any]) -> list[dict[str, Any]]:
        """Aplana las opciones por puesto sin perder los datos de muestra.


        Parámetros: variante con opciones estadísticas del proveedor.
        Retorno: lista de opciones con ID y datos originales.
        """
        opciones = variante.get("item_options", {})
        if not isinstance(opciones, dict):
            return []
        return [
            entrada
            for valores in opciones.values()
            if isinstance(valores, list)
            for entrada in valores
            if isinstance(entrada, dict) and entrada.get("item_id")
        ]

    @staticmethod
    def _tiene_muestra(opcion: dict[str, Any]) -> bool:
        """Comprueba que la opción disponga de una muestra estadística positiva.

        Parámetros: opción de objeto del proveedor.
        Retorno: True si el número de partidas puede convertirse y es mayor que cero.
        """
        try:
            return int(opcion.get("games", 0) or 0) > 0
        except (TypeError, ValueError):
            return False

    def _puntuacion(self, opcion: dict[str, Any], candidatos: dict[str, Any]) -> float:
        """Combina afinidad y tasa de victoria suavizada por tamaño de muestra.


        Parámetros: opción estadística y candidatos de afinidad indexados.
        Retorno: puntuación comparable para ordenar opciones.
        """
        item_id = str(opcion.get("item_id") or "")
        candidato = candidatos.get(item_id)
        afinidad = self._numero(self._valor(candidato, "score", 0.0))
        try:
            partidas = max(0, int(opcion.get("games", 0) or 0))
            tasa = float(opcion.get("win_rate", 0.5) or 0.5)
        except (TypeError, ValueError):
            partidas, tasa = 0, 0.5
        tasa = tasa if 0 <= tasa <= 1 else 0.5
        victorias = opcion.get("wins")
        try:
            ganadas = float(victorias) if victorias is not None else tasa * partidas
        except (TypeError, ValueError):
            ganadas = tasa * partidas
        if not math.isfinite(ganadas):
            ganadas = tasa * partidas
        posterior = (ganadas + 50.0) / (partidas + 100.0)
        confianza = partidas / (partidas + 50.0) if partidas else 0.0
        ajuste_estadistico = 20.0 * (posterior - 0.5) * confianza
        return afinidad + ajuste_estadistico

    def _categoria(self, item_id: str) -> str:
        """Clasifica el propósito del objeto usando efectos y atributos.


        Parámetros: ID de objeto del catálogo local.
        Retorno: clave de categoría o cadena vacía si no aplica.
        """
        item = self.catalogo.catalogo.get(item_id, {})
        estricto = self.objetos_estrictos.get(item_id, {})
        descripciones = " ".join(
            str(item.get(campo, ""))
            for campo in (
                "description",
                "description_es",
                "description_en",
                "plaintext",
            )
        ).casefold()
        funcion = estricto.get("functionality", {})
        pasivas = (
            " ".join(
                str(valor) for valor in funcion.get("passive_names", [])
            ).casefold()
            if isinstance(funcion, dict)
            else ""
        )
        texto = re.sub(r"<[^>]+>", " ", f"{descripciones} {pasivas}")
        if any(
            palabra in texto
            for palabra in ("grievous wounds", "heridas graves", "wounds")
        ):
            return "corta_curas"
        tags = set(item.get("tags", []))
        clasificaciones = estricto.get("classifications", {})
        mecanicas = (
            {
                str(valor).casefold()
                for valor in clasificaciones.get("counter_mechanics", [])
            }
            if isinstance(clasificaciones, dict)
            else set()
        )
        if mecanicas.intersection({"shields", "crowd_control", "cleanse"}) or any(
            palabra in texto
            for palabra in (
                "spell shield",
                "escudo de hechizos",
                "cleanse",
                "limpia",
                "stasis",
                "estasis",
                "revive",
                "resucita",
            )
        ):
            return "utilidad_y_defensa"
        if tags.intersection({"Armor", "SpellBlock"}) or (
            "Health" in tags
            and not tags.intersection(
                {
                    "Damage",
                    "SpellDamage",
                    "AttackSpeed",
                    "CriticalStrike",
                    "ArmorPenetration",
                    "MagicPenetration",
                }
            )
        ):
            return "tanque"
        if tags.intersection(
            {"ArmorPenetration", "MagicPenetration", "CriticalStrike"}
        ) or any(
            palabra in texto
            for palabra in ("lethality", "letalidad", "penetration", "penetración")
        ):
            return "asesino"
        return ""

    def _compatible(self, estilo: str, item_id: str) -> bool:
        """Comprueba que las clases del objeto encajen con el estilo.


        Parámetros: estilo del campeón e ID de objeto.
        Retorno: True si la combinación es compatible.
        """
        estricto = self.objetos_estrictos.get(item_id, {})
        clasificaciones = estricto.get("classifications", {})
        previstas = (
            {
                str(valor).casefold()
                for valor in clasificaciones.get("intended_classes", [])
            }
            if isinstance(clasificaciones, dict)
            else set()
        )
        if not previstas:
            return True
        clases_estilo = {
            "juggernaut": {"fighter", "juggernaut", "bruiser", "tank"},
            "diver": {
                "fighter",
                "juggernaut",
                "bruiser",
                "skirmisher",
                "assassin",
                "tank",
            },
            "fighter": {"fighter", "juggernaut", "bruiser", "tank"},
            "marksman": {"marksman", "fighter"},
            "mage": {"mage", "support", "assassin"},
            "assassin": {"assassin", "fighter", "marksman"},
            "vanguard": {"tank", "fighter", "support"},
            "warden": {"tank", "support", "fighter"},
            "tank": {"tank", "fighter", "support"},
            "enchanter": {"support", "mage", "tank"},
            "support": {"support", "tank", "mage"},
        }.get(estilo.casefold(), set())
        return not clases_estilo or bool(previstas.intersection(clases_estilo))

    def _grupo_duplicado(self, item_id: str, seleccionados: set[str]) -> bool:
        """Detecta restricciones compartidas de grupo de objeto.


        Parámetros: ID candidato y conjunto de IDs seleccionados.
        Retorno: True si la build ya contiene el mismo grupo exclusivo.
        """
        grupo = str(
            self.objetos_estrictos.get(item_id, {})
            .get("basic_info", {})
            .get("item_group", "None")
        )
        if not grupo or grupo.casefold() in {"none", "annul"}:
            return False
        return any(
            str(
                self.objetos_estrictos.get(otro, {})
                .get("basic_info", {})
                .get("item_group", "None")
            )
            == grupo
            for otro in seleccionados
        )

    def _es_bota(self, item_id: str) -> bool:
        """Comprueba la etiqueta de botas en el catálogo actual.


        Parámetros: ID de objeto.
        Retorno: True si el objeto es una bota.
        """
        return "Boots" in self.catalogo.catalogo.get(item_id, {}).get("tags", [])

    def _anotar_candidato(
        self,
        entrada: dict[str, Any],
        candidato: Any,
        opcion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Añade afinidad y estadísticas a una selección de build.


        Parámetros: objeto normalizado, candidato tipado y opción estadística opcional.
        Retorno: copia de la selección con sus metadatos de evidencia.
        """
        resultado = dict(entrada)
        if candidato is not None:
            for campo in (
                "score",
                "reasons",
                "compatibility_label",
                "compatibility_reasons",
                "compatibility_score",
                "matchup_score",
                "build_synergy_score",
            ):
                valor = self._valor(candidato, campo, None)
                if valor is not None:
                    resultado[campo] = (
                        list(valor)
                        if campo in {"reasons", "compatibility_reasons"}
                        else valor
                    )
        if opcion:
            for campo in ("games", "wins", "win_rate", "sample_status", "source"):
                if campo in opcion:
                    resultado[campo] = opcion[campo]
            resultado["score"] = self._puntuacion(
                opcion,
                {str(resultado["item_id"]): candidato} if candidato is not None else {},
            )
        return resultado

    @staticmethod
    def _valor(objeto: Any, campo: str, defecto: Any) -> Any:
        """Lee un campo de un mapeo o de una recomendación tipada.


        Parámetros: objeto, nombre del campo y valor alternativo.
        Retorno: valor encontrado o alternativa solicitada.
        """
        return (
            objeto.get(campo, defecto)
            if isinstance(objeto, dict)
            else getattr(objeto, campo, defecto)
        )

    @staticmethod
    def _numero(valor: Any) -> float:
        """Convierte puntuaciones finitas y rechaza valores malformados.


        Parámetros: valor de entrada.
        Retorno: número real finito o cero para entradas inválidas.
        """
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            return 0.0
        return numero if math.isfinite(numero) and not isinstance(valor, bool) else 0.0

    @staticmethod
    def _lista(valor: Any) -> list[Any]:
        """Normaliza una entrada sin tratar cadenas como listas.


        Parámetros: valor que podría ser una lista.
        Retorno: la lista recibida o una lista vacía.
        """
        return valor if isinstance(valor, list) else []

    @staticmethod
    def _ordenar_por_puesto(valor: Any) -> list[Any]:
        """Ordena las entradas del núcleo por su ranura de compra.


        Parámetros: lista de objetos con ranura opcional.
        Retorno: lista ordenada de forma estable.
        """
        entradas = CuradorRecomendacionesBuild._lista(valor)
        return sorted(
            entradas,
            key=lambda entrada: (
                CuradorRecomendacionesBuild._numero(
                    CuradorRecomendacionesBuild._valor(entrada, "slot", 0)
                )
                or float(entradas.index(entrada))
            ),
        )
