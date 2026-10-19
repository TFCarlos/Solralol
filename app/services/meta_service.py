"""Adquisición y caché local de estadísticas públicas de Meta."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from _paths import DATA_DIR

_REGISTRO = logging.getLogger(__name__)


class ServicioMeta:
    """Obtiene estadísticas Emerald+ de LoLalytics y notas oficiales de Riot."""

    URL_TIER = "https://lolalytics.com/es/lol/tierlist/"
    PROVEEDOR_TIER = "lolalytics"
    RANGO_TIER = "emerald_plus"
    COLA_TIER = "ranked_solo_duo"
    ROLES_TIER = {
        "top": "top",
        "jungle": "jungle",
        "mid": "middle",
        "adc": "bottom",
        "support": "support",
    }
    REGIONES_TIER = frozenset({"all", "na", "euw", "kr"})
    URL_NOTAS = "https://www.leagueoflegends.com/es-es/news/game-updates/"
    TTL_SEGUNDOS = 21600
    VERSION_ESQUEMA_NOTAS = 4

    def __init__(self, directorio: Path | None = None) -> None:
        """Prepara rutas persistentes; recibe directorio opcional y retorna None."""
        self.directorio = directorio or Path.home() / ".solralol" / "meta"
        self.directorio.mkdir(parents=True, exist_ok=True)
        self.sesion = requests.Session()
        self.sesion.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.7",
            }
        )
        self._campeones = self._cargar_catalogo_campeones()
        self._objetos = self._cargar_catalogo_objetos()

    def cargar_cache(self, nombre: str) -> dict[str, Any] | None:
        """Lee un documento JSON de caché validado; recibe nombre y retorna objeto o None."""
        try:
            datos = json.loads((self.directorio / nombre).read_text(encoding="utf-8"))
            return datos if isinstance(datos, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def guardar_cache(self, nombre: str, datos: dict[str, Any]) -> None:
        """Escribe caché JSON mediante reemplazo atómico; recibe nombre y datos, retorna None."""
        destino = self.directorio / nombre
        temporal = destino.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        temporal.replace(destino)

    def obtener_lista_niveles(
        self, filtros: dict[str, str], forzar: bool = False
    ) -> dict[str, Any]:
        """Obtiene la tabla Emerald+ de LoLalytics o reutiliza su caché contextual."""
        normalizados = self._normalizar_filtros_tier(filtros)
        indice = self._clave_indice_tier(normalizados)
        cache = self._leer_cache_tier(indice, normalizados)
        if cache and not forzar and self._cache_vigente(cache):
            return {**cache, "cached": True, "stale": False}
        try:
            parametros = {
                "lane": self.ROLES_TIER[normalizados["role"]],
                "tier": self.RANGO_TIER,
                "region": normalizados["region"],
            }
            respuesta_lista = self.sesion.get(
                self.URL_TIER,
                params={**parametros, "view": "list"},
                timeout=(5, 20),
            )
            self._validar_respuesta_http(respuesta_lista)
            detallados, parche = self._extraer_lista_niveles(
                respuesta_lista.text, normalizados
            )
            respuesta_grid = self.sesion.get(
                self.URL_TIER,
                params={**parametros, "view": "grid"},
                timeout=(5, 20),
            )
            self._validar_respuesta_http(respuesta_grid)
            campeones_grid, parche_grid = self._extraer_campeones_cuadricula(
                respuesta_grid.text, normalizados
            )
            if not parche or parche != parche_grid:
                raise RuntimeError("LoLalytics devolvió vistas con parches distintos.")
            campeones = self._combinar_vistas(campeones_grid, detallados)
            self._validar_ranking(campeones, normalizados, parche, len(campeones))
            datos = {
                "provider": self.PROVEEDOR_TIER,
                "filters": normalizados,
                "rank": self.RANGO_TIER,
                "queue": self.COLA_TIER,
                "patch": parche,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source_url": respuesta_grid.url,
                "champions": campeones,
                "source_count": len(campeones),
            }
            nombre_cache = self._clave_cache_tier(normalizados, parche)
            self.guardar_cache(nombre_cache, datos)
            self.guardar_cache(
                indice, {"cache_file": nombre_cache, "filters": normalizados}
            )
            return {**datos, "cached": False, "stale": False}
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            TypeError,
        ) as error:
            if cache:
                return {
                    **cache,
                    "cached": True,
                    "stale": True,
                    "cache_error": str(error),
                }
            raise

    @classmethod
    def _normalizar_filtros_tier(cls, filtros: dict[str, str]) -> dict[str, str]:
        """Fija rango y cola y valida rol/región antes de formar URL o caché."""
        rol = str(filtros.get("role", "top")).casefold()
        region = str(filtros.get("region", "all")).casefold()
        if rol not in cls.ROLES_TIER:
            raise ValueError("Rol LoLalytics no compatible.")
        if region not in cls.REGIONES_TIER:
            raise ValueError("Región LoLalytics no compatible.")
        return {
            "role": rol,
            "rank": cls.RANGO_TIER,
            "region": region,
            "mode": cls.COLA_TIER,
        }

    @classmethod
    def _clave_indice_tier(cls, filtros: dict[str, str]) -> str:
        """Forma índice de caché independiente por proveedor, rango, rol y región."""
        return (
            "tier_lolalytics_index_"
            + "_".join(filtros[key] for key in ("rank", "role", "region", "mode"))
            + ".json"
        )

    @classmethod
    def _clave_cache_tier(cls, filtros: dict[str, str], parche: str) -> str:
        """Forma nombre de caché exitoso que incluye proveedor, parche y contexto."""
        return (
            "tier_lolalytics_"
            + "_".join(
                (
                    parche,
                    filtros["rank"],
                    filtros["role"],
                    filtros["region"],
                    filtros["mode"],
                )
            )
            + ".json"
        )

    def _leer_cache_tier(
        self, indice: str, filtros: dict[str, str]
    ) -> dict[str, Any] | None:
        """Lee solo la última caché LoLalytics que coincide con todos los filtros."""
        documento = self.cargar_cache(indice)
        if not documento or documento.get("filters") != filtros:
            return None
        nombre = documento.get("cache_file")
        if (
            not isinstance(nombre, str)
            or Path(nombre).name != nombre
            or not nombre.startswith("tier_lolalytics_")
        ):
            return None
        cache = self.cargar_cache(nombre)
        if not cache or cache.get("provider") != self.PROVEEDOR_TIER:
            return None
        if cache.get("filters") != filtros or cache.get("rank") != self.RANGO_TIER:
            return None
        try:
            self._validar_ranking(
                cache.get("champions"),
                filtros,
                str(cache.get("patch") or ""),
                cache.get("source_count"),
            )
        except (RuntimeError, TypeError, ValueError):
            _REGISTRO.warning(
                "Se descarta caché LoLalytics incompleta o inconsistente: %s", nombre
            )
            return None
        return cache

    @classmethod
    def _validar_ranking(
        cls,
        campeones: Any,
        filtros: dict[str, str],
        parche: str,
        cantidad_esperada: Any,
    ) -> None:
        """Comprueba integridad y contexto de todas las posiciones recibidas."""
        if not isinstance(campeones, list) or not campeones:
            _REGISTRO.error("LoLalytics: la fuente no devolvio posiciones validas.")
            raise RuntimeError(
                "LoLalytics no devolvio posiciones de campeones validas."
            )
        if len(campeones) < 50:
            _REGISTRO.warning(
                "LoLalytics publico %s posiciones; se conserva todo el ranking recibido.",
                len(campeones),
            )
        if (
            isinstance(cantidad_esperada, bool)
            or not isinstance(cantidad_esperada, int)
            or cantidad_esperada != len(campeones)
        ):
            raise RuntimeError("El conjunto no declara una cantidad de filas integra.")
        posiciones: list[int] = []
        identidades: set[str] = set()
        for campeon in campeones:
            if not isinstance(campeon, dict):
                raise RuntimeError(
                    "La tier list contiene una fila de campeón inválida."
                )
            identificador = str(campeon.get("champion_id") or "").casefold()
            posicion = campeon.get("position")
            if not identificador or identificador in identidades:
                raise RuntimeError(
                    "La tier list contiene campeones ausentes o duplicados."
                )
            if isinstance(posicion, bool) or not isinstance(posicion, int):
                raise RuntimeError("La tier list contiene una posición inválida.")
            if (
                campeon.get("role") != filtros["role"]
                or campeon.get("region") != filtros["region"]
                or campeon.get("rank") != cls.RANGO_TIER
                or campeon.get("queue") != cls.COLA_TIER
                or campeon.get("patch") != parche
            ):
                raise RuntimeError("La tier list mezcla filtros o parches distintos.")
            for metrica in ("win_rate", "pick_rate", "ban_rate"):
                valor = campeon.get(metrica)
                if (
                    isinstance(valor, bool)
                    or not isinstance(valor, (int, float))
                    or not 0 <= valor <= 100
                ):
                    raise RuntimeError(
                        f"La tier list contiene una métrica inválida: {metrica}."
                    )
            identidades.add(identificador)
            posiciones.append(posicion)
        if sorted(posiciones) != list(range(1, len(campeones) + 1)):
            _REGISTRO.error(
                "LoLalytics: posiciones duplicadas o huecos en el ranking: %s",
                posiciones,
            )
            raise RuntimeError(
                "La tier list tiene posiciones duplicadas o huecos desde #1."
            )

    @classmethod
    def _cache_vigente(cls, cache: dict[str, Any]) -> bool:
        """Indica si la última descarga LoLalytics aún está dentro de seis horas."""
        try:
            edad = (
                datetime.now(timezone.utc).timestamp()
                - datetime.fromisoformat(cache["retrieved_at"]).timestamp()
            )
            return 0 <= edad < cls.TTL_SEGUNDOS
        except (KeyError, ValueError, TypeError):
            return False

    @staticmethod
    def _validar_respuesta_http(respuesta: requests.Response) -> None:
        """Rechaza errores HTTP y páginas de verificación antes de analizar HTML."""
        respuesta.raise_for_status()
        html = respuesta.text
        if any(
            marca in html.casefold()
            for marca in (
                "just a moment",
                "verify you are human",
                "cf-chl-",
                "cf_chl_opt",
                "challenge-form",
                "cf-browser-verification",
                "attention required",
            )
        ):
            raise RuntimeError(
                "LoLalytics devolvió una página de verificación; no se intenta sortearla."
            )
        if "lol tier list" not in html.casefold() or "emerald+" not in html.casefold():
            raise RuntimeError(
                "La respuesta no parece una tier list LoLalytics Emerald+ válida."
            )

    def _extraer_lista_niveles(
        self, html: str, filtros: dict[str, str], vista: str = "list"
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Extrae filas LoLalytics SSR y valida parche, rango, región, cola y rol."""
        sopa = BeautifulSoup(html, "html.parser")
        titulo = sopa.title.get_text(" ", strip=True) if sopa.title else ""
        parche_match = re.search(r"Patch\s+(\d+\.\d+)", titulo, re.I)
        if not parche_match:
            raise RuntimeError(
                "La tier list de LoLalytics no declara su parche en el título."
            )
        parche = parche_match.group(1)
        lane = self.ROLES_TIER[filtros["role"]]
        estado = re.compile(
            rf"tb_tl_[^\"]*_{re.escape(lane)}_ranked_{re.escape(vista)}_emerald_plus_"
            rf"{re.escape(parche)}_{re.escape(filtros['region'])}__"
        )
        if not estado.search(html):
            raise RuntimeError(
                "La respuesta LoLalytics no coincide con rol, región, cola, parche y Emerald+."
            )
        filas: list[dict[str, Any]] = []
        for fila in sopa.find_all(
            "div", class_=lambda clases: clases and "h-[52px]" in clases
        ):
            celdas = fila.find_all("div", recursive=False)
            if len(celdas) < 10:
                continue
            posicion = self._entero(celdas[0].get_text(" ", strip=True))
            imagen = celdas[1].find("img")
            nombre = celdas[2].get_text(" ", strip=True)
            nombre_fuente = celdas[1].get_text(" ", strip=True)
            id_fuente = str(imagen.get("alt", "")).strip() if imagen else ""
            identificador = self._resolver_campeon(id_fuente or nombre)
            tier = celdas[3].get_text(" ", strip=True)
            tier_valido = re.fullmatch(r"[SABCD][+-]?", tier, re.I)
            win_texto = celdas[5].select_one("span")
            win_rate = self._porcentaje(
                win_texto.get_text(" ", strip=True) if win_texto else ""
            )
            pick_rate = self._porcentaje(celdas[6].get_text(" ", strip=True))
            ban_rate = self._porcentaje(celdas[7].get_text(" ", strip=True))
            muestra = self._entero(celdas[9].get_text(" ", strip=True))
            if not identificador:
                _REGISTRO.warning(
                    "LoLalytics incluyó una fila no reconocida: %s", id_fuente or nombre
                )
                continue
            if (
                posicion is None
                or not tier_valido
                or win_rate is None
                or pick_rate is None
                or ban_rate is None
            ):
                _REGISTRO.warning(
                    "LoLalytics incluyó una fila incompleta para %s en %s.",
                    identificador,
                    filtros,
                )
                continue
            filas.append(
                {
                    "champion_id": identificador,
                    "name": self._campeones[identificador.casefold()]["name"],
                    "source_name": nombre_fuente,
                    "role": filtros["role"],
                    "tier": tier.upper(),
                    "position": posicion,
                    "win_rate": win_rate,
                    "pick_rate": pick_rate,
                    "ban_rate": ban_rate,
                    "sample_size": muestra,
                    "patch": parche,
                    "region": filtros["region"],
                    "rank": self.RANGO_TIER,
                    "queue": self.COLA_TIER,
                }
            )
        filas.sort(key=lambda campeon: int(campeon["position"]))
        return filas, parche

    def _extraer_campeones_cuadricula(
        self, html: str, filtros: dict[str, str]
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Extrae posiciones Emerald+ de la vista pública de cuadrícula LoLalytics."""
        sopa = BeautifulSoup(html, "html.parser")
        titulo = sopa.title.get_text(" ", strip=True) if sopa.title else ""
        parche_match = re.search(r"Patch\s+(\d+\.\d+)", titulo, re.I)
        if not parche_match:
            raise RuntimeError("La cuadrícula LoLalytics no declara su parche.")
        parche = parche_match.group(1)
        lane = self.ROLES_TIER[filtros["role"]]
        estado = re.compile(
            rf"tb_tl_[^\"]*_{re.escape(lane)}_ranked_grid_emerald_plus_"
            rf"{re.escape(parche)}_{re.escape(filtros['region'])}__"
        )
        if not estado.search(html):
            raise RuntimeError(
                "La cuadrícula LoLalytics no coincide con rol, región, parche y Emerald+."
            )
        tarjetas = sopa.find_all(
            "div",
            class_=lambda clases: (
                clases and "h-[151px]" in clases and "min-w-[150px]" in clases
            ),
        )
        filas: list[dict[str, Any]] = []
        tarjetas_con_datos = 0
        for tarjeta in tarjetas:
            imagen = tarjeta.find("img", alt=True)
            columna = next(
                (
                    bloque
                    for bloque in tarjeta.find_all("div")
                    if "w-[48px]" in bloque.get("class", [])
                    and "m-auto" in bloque.get("class", [])
                ),
                None,
            )
            if imagen is None and not tarjeta.get_text(" ", strip=True):
                continue
            tarjetas_con_datos += 1
            if imagen is None or columna is None:
                _REGISTRO.warning(
                    "LoLalytics devolvio una tarjeta sin identidad o estadisticas."
                )
                raise RuntimeError(
                    "La tarjeta de la cuadricula no tiene estructura reconocible."
                )
            nombre_fuente = str(imagen.get("alt", "")).strip()
            identificador = self._resolver_campeon(nombre_fuente)
            if not identificador:
                _REGISTRO.warning(
                    "LoLalytics incluyo un campeon no reconocido en la cuadricula: %s",
                    nombre_fuente,
                )
                raise RuntimeError(
                    f"No se pudo resolver el campeon LoLalytics: {nombre_fuente}"
                )
            valores = columna.find_all("div", recursive=False)
            tier = valores[0].get_text(" ", strip=True) if len(valores) >= 4 else ""
            posicion_bloque = tarjeta.find(
                "div", class_=lambda clases: clases and "rounded-full" in clases
            )
            posicion = self._entero(
                posicion_bloque.get_text(" ", strip=True) if posicion_bloque else ""
            )
            porcentaje_win = (
                self._porcentaje(valores[1].get_text(" ", strip=True))
                if len(valores) >= 4
                else None
            )
            porcentaje_pick = (
                self._porcentaje(valores[2].get_text(" ", strip=True))
                if len(valores) >= 4
                else None
            )
            porcentaje_ban = (
                self._porcentaje(valores[3].get_text(" ", strip=True))
                if len(valores) >= 4
                else None
            )
            if (
                posicion is None
                or not re.fullmatch(r"[SABCD][+-]?", tier, re.I)
                or any(
                    valor is None
                    for valor in (porcentaje_win, porcentaje_pick, porcentaje_ban)
                )
            ):
                _REGISTRO.warning(
                    "LoLalytics devolvio una tarjeta incompleta: %s (#%s).",
                    nombre_fuente,
                    posicion,
                )
                raise RuntimeError(
                    f"La tarjeta de {nombre_fuente} no contiene ranking y metricas validas."
                )
            filas.append(
                {
                    "champion_id": identificador,
                    "name": self._campeones[identificador.casefold()]["name"],
                    "source_name": nombre_fuente,
                    "role": filtros["role"],
                    "tier": tier.upper(),
                    "position": posicion,
                    "win_rate": porcentaje_win,
                    "pick_rate": porcentaje_pick,
                    "ban_rate": porcentaje_ban,
                    "sample_size": None,
                    "patch": parche,
                    "region": filtros["region"],
                    "rank": self.RANGO_TIER,
                    "queue": self.COLA_TIER,
                }
            )
        filas.sort(key=lambda campeon: int(campeon["position"]))
        if len(filas) != tarjetas_con_datos:
            _REGISTRO.error(
                "LoLalytics devolvio %s filas validas de %s tarjetas con datos; el parseo esta incompleto.",
                len(filas),
                tarjetas_con_datos,
            )
            raise RuntimeError(
                "No se pudieron interpretar todas las tarjetas de LoLalytics."
            )
        elif len(filas) < 50:
            _REGISTRO.warning(
                "La fuente LoLalytics publico solo %s posiciones para estos filtros.",
                len(filas),
            )
        return filas, parche

    @staticmethod
    def _combinar_vistas(
        cuadricula: list[dict[str, Any]], detallados: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Completa la vista extensa con cifras exactas y muestras de la lista detallada."""
        por_campeon = {fila["champion_id"].casefold(): fila for fila in detallados}
        resultado: list[dict[str, Any]] = []
        for fila in cuadricula:
            detallado = por_campeon.get(fila["champion_id"].casefold())
            if detallado:
                fila = {
                    **fila,
                    **detallado,
                    "position": fila["position"],
                    "champion_id": fila["champion_id"],
                    "name": fila["name"],
                }
            resultado.append(fila)
        return resultado

    @staticmethod
    def _normalizar_nombre(nombre: str) -> str:
        """Normaliza nombre/ID de Data Dragon para resolver alias sin depender de idioma."""
        texto = unicodedata.normalize("NFKD", str(nombre))
        return re.sub(
            r"[^a-z0-9]", "", texto.encode("ascii", "ignore").decode().casefold()
        )

    @classmethod
    def _cargar_catalogo_campeones(cls) -> dict[str, dict[str, str]]:
        """Carga nombres e identificadores del catálogo Data Dragon local sin acceder a red."""
        try:
            catalogo = json.loads(
                (DATA_DIR / "champion_catalog.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        resultado: dict[str, dict[str, str]] = {}
        for entrada in catalogo.get("data", {}).values():
            if not isinstance(entrada, dict):
                continue
            identificador = str(entrada.get("id") or "").strip()
            nombre = str(entrada.get("name") or "").strip()
            if identificador and nombre:
                valor = {"id": identificador, "name": nombre}
                clave_riot = str(entrada.get("key") or "").strip()
                resultado[identificador.casefold()] = valor
                if clave_riot:
                    resultado[cls._normalizar_nombre(clave_riot)] = valor
                resultado[cls._normalizar_nombre(nombre)] = valor
                resultado[cls._normalizar_nombre(identificador)] = valor
        return resultado

    def _resolver_campeon(self, nombre: str) -> str | None:
        """Devuelve ID canónico Data Dragon para nombre visible o alt de retrato."""
        nombre_normalizado = self._normalizar_nombre(nombre)
        alias = {
            "maestroyi": "masteryi",
            "nunuywillump": "nunu",
            "nunu": "nunu",
        }.get(nombre_normalizado, nombre_normalizado)
        valor = self._campeones.get(alias)
        return valor["id"] if valor else None

    @staticmethod
    def _porcentaje(valor: str) -> float | None:
        """Interpreta porcentaje numérico y descarta valores ausentes o fuera de 0–100."""
        coincidencia = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*%?\s*", valor)
        if not coincidencia:
            return None
        numero = float(coincidencia.group(1).replace(",", "."))
        return numero if 0 <= numero <= 100 else None

    @staticmethod
    def _entero(valor: str) -> int | None:
        """Interpreta enteros con separadores de miles o devuelve None si no son válidos."""
        limpio = re.sub(r"[^0-9]", "", valor)
        return int(limpio) if limpio else None

    def obtener_notas(self, forzar: bool = False) -> dict[str, Any]:
        """Detecta y extrae resumen de la última nota oficial publicada; retorna datos o caché."""
        cache = self.cargar_cache("patch_notes.json")
        if (
            cache
            and cache.get("schema_version") == self.VERSION_ESQUEMA_NOTAS
            and not forzar
        ):
            try:
                edad = (
                    datetime.now(timezone.utc).timestamp()
                    - datetime.fromisoformat(cache["checked_at"]).timestamp()
                )
                if edad < 21600:
                    return {**cache, "cached": True}
            except (KeyError, ValueError, TypeError):
                pass
        respuesta = self.sesion.get(self.URL_NOTAS, timeout=20)
        respuesta.raise_for_status()
        sopa = BeautifulSoup(respuesta.text, "html.parser")
        candidato = None
        for enlace in sopa.select("a[href]"):
            titulo = enlace.get_text(" ", strip=True)
            coincidencia = re.search(
                r"notas (?:del parche|de la versi[oó]n)(?: de [^0-9]+)?\s*(\d+\.\d+)",
                titulo,
                re.I,
            )
            href = urljoin(self.URL_NOTAS, enlace.get("href", ""))
            if coincidencia and "/game-updates/" in href:
                candidato = (coincidencia.group(1), titulo, href)
                break
        if not candidato:
            raise RuntimeError(
                "No se encontró una nota de parche de League of Legends en el índice oficial español."
            )
        version, titulo, url = candidato
        if (
            cache
            and cache.get("schema_version") == self.VERSION_ESQUEMA_NOTAS
            and cache.get("version") == version
        ):
            cache["checked_at"] = datetime.now(timezone.utc).isoformat()
            self.guardar_cache("patch_notes.json", cache)
            return {**cache, "cached": True}
        articulo = self.sesion.get(url, timeout=20)
        articulo.raise_for_status()
        documento = BeautifulSoup(articulo.text, "html.parser")
        contenido = documento.select_one("article") or documento
        titulo_articulo = documento.select_one("h1")
        if titulo_articulo:
            titulo = titulo_articulo.get_text(" ", strip=True)
        secciones = self._estructurar_nota(contenido, url)
        imagen_url = self._buscar_imagen_resumen(contenido, url)
        imagen_local = (
            self._guardar_imagen_resumen(imagen_url, version) if imagen_url else None
        )
        ahora = datetime.now(timezone.utc).isoformat()
        resultado = {
            "schema_version": self.VERSION_ESQUEMA_NOTAS,
            "version": version,
            "title": titulo,
            "url": url,
            "published": self._fecha_articulo(articulo.text),
            "game_version": self._version_data_dragon(),
            "checked_at": ahora,
            "retrieved_at": ahora,
            "hero_image_url": imagen_url,
            "hero_image_path": imagen_local,
            "sections": secciones,
        }
        self.guardar_cache("patch_notes.json", resultado)
        return {**resultado, "cached": False}

    def _estructurar_nota(
        self, contenido: Any, url_articulo: str = ""
    ) -> list[dict[str, Any]]:
        """Convierte encabezados y bloques del artículo en una jerarquía de secciones y entradas."""
        secciones: list[dict[str, Any]] = []
        seccion_actual: dict[str, Any] | None = None
        pila: list[tuple[int, dict[str, Any]]] = []
        entrada_actual: dict[str, Any] | None = None
        grupo_campeones: dict[str, Any] | None = None
        grupo_objetos: dict[str, Any] | None = None

        def crear_nodo(titulo: str, tipo: str = "section") -> dict[str, Any]:
            """Crea un nodo uniforme para encabezados, campeones, objetos y habilidades."""
            campeon_id = self._resolver_campeon(titulo) if tipo == "champion" else None
            return {
                "title": titulo,
                "kind": tipo,
                "champion_id": campeon_id,
                "item_id": self._resolver_objeto(titulo) if tipo == "item" else None,
                "change_type": self._clasificar_cambio(titulo),
                "blocks": [],
                "children": [],
            }

        def agregar_unico(
            destino: list[dict[str, Any]], nodo: dict[str, Any]
        ) -> dict[str, Any]:
            """Evita entradas duplicadas en un mismo grupo y conserva el orden de origen."""
            clave = self._clave_texto(nodo["title"])
            existente = next(
                (
                    item
                    for item in destino
                    if self._clave_texto(item["title"]) == clave
                    and item["kind"] == nodo["kind"]
                ),
                None,
            )
            if existente is not None:
                return existente
            destino.append(nodo)
            return nodo

        def asociar_icono_objeto(nodo: dict[str, Any], elemento: Any) -> None:
            """Obtiene el identificador del icono Data Dragon adyacente al encabezado del objeto."""
            imagen = elemento.find_previous("img", src=True)
            fuente = str(imagen.get("src", "")) if imagen else ""
            coincidencia = re.search(r"/item/(\d+)\.png", fuente)
            if coincidencia:
                nodo["item_id"] = coincidencia.group(1)

        for elemento in contenido.select("h2,h3,h4,h5,blockquote,p,li,img"):
            nombre_tag = elemento.name or ""
            if nombre_tag == "img":
                if elemento.find_parent(["p", "li"]) is None:
                    continue
                fuente = str(elemento.get("src") or elemento.get("data-src") or "")
                url_imagen = urljoin(url_articulo, fuente) if fuente else ""
                if (
                    url_imagen.startswith(("https://", "http://"))
                    and entrada_actual
                    and not self._es_icono_data_dragon(url_imagen)
                ):
                    entrada_actual["blocks"].append(
                        {
                            "type": "image",
                            "url": url_imagen,
                            "alt": str(elemento.get("alt") or "Imagen de las notas"),
                        }
                    )
                continue
            if elemento.find_parent(["blockquote", "li"]) is not None:
                continue
            texto = elemento.get_text(" ", strip=True)
            if not texto:
                continue
            if nombre_tag in {"h2", "h3", "h4", "h5"}:
                nivel = {"h2": 2, "h3": 3, "h4": 4, "h5": 5}[nombre_tag]
                if nivel == 2:
                    seccion_actual = crear_nodo(texto)
                    if self._clave_texto(texto) != "articulosrelacionados":
                        secciones.append(seccion_actual)
                    pila = [(2, seccion_actual)]
                    entrada_actual = None
                    grupo_campeones = None
                    grupo_objetos = None
                    continue
                if seccion_actual is None:
                    seccion_actual = crear_nodo("Introducción")
                    secciones.append(seccion_actual)
                    pila = [(2, seccion_actual)]
                padre = next(
                    (
                        nodo
                        for profundidad, nodo in reversed(pila)
                        if profundidad < nivel
                    ),
                    seccion_actual,
                )
                clave_seccion = self._clave_texto(seccion_actual["title"])
                clave_texto = self._clave_texto(texto)
                es_grupo = clave_texto in {
                    "campeones",
                    "objetos",
                    "correccion de errores",
                    "aumentos",
                    "runas",
                    "sistemas",
                }
                campeon_id = self._resolver_campeon(texto)
                if campeon_id and clave_seccion in {
                    "campeones",
                    "classic",
                    "clasico",
                    "aram",
                    "aram caos",
                }:
                    nodo = crear_nodo(texto, "champion")
                    entrada_actual = agregar_unico(padre["children"], nodo)
                elif clave_seccion == "objetos" and nivel == 3:
                    nodo = crear_nodo(texto, "item")
                    asociar_icono_objeto(nodo, elemento)
                    entrada_actual = agregar_unico(padre["children"], nodo)
                elif clave_texto == "campeones":
                    nodo = crear_nodo(texto, "group")
                    grupo_campeones = agregar_unico(padre["children"], nodo)
                    entrada_actual = grupo_campeones
                    grupo_objetos = None
                elif clave_texto == "objetos":
                    nodo = crear_nodo(texto, "group")
                    grupo_objetos = agregar_unico(padre["children"], nodo)
                    entrada_actual = grupo_objetos
                    grupo_campeones = None
                elif nivel >= 4 and grupo_campeones is not None and campeon_id:
                    nodo = crear_nodo(texto, "champion")
                    entrada_actual = agregar_unico(grupo_campeones["children"], nodo)
                elif nivel >= 4 and grupo_objetos is not None and not es_grupo:
                    nodo = crear_nodo(texto, "item")
                    entrada_actual = agregar_unico(grupo_objetos["children"], nodo)
                elif (
                    nivel >= 4
                    and entrada_actual
                    and entrada_actual.get("kind") in {"champion", "item"}
                ):
                    nodo = crear_nodo(texto, "detail")
                    entrada_actual = agregar_unico(entrada_actual["children"], nodo)
                elif nivel > 2 and padre.get("kind") in {"champion", "item"}:
                    nodo = crear_nodo(texto, "detail")
                    entrada_actual = agregar_unico(padre["children"], nodo)
                elif nivel > 2:
                    nodo = crear_nodo(texto, "group" if es_grupo else "section")
                    entrada_actual = agregar_unico(padre["children"], nodo)
                    if clave_texto == "campeones":
                        grupo_campeones = entrada_actual
                    if clave_texto == "objetos":
                        grupo_objetos = entrada_actual
                else:
                    entrada_actual = seccion_actual
                pila = [
                    (profundidad, nodo)
                    for profundidad, nodo in pila
                    if profundidad < nivel
                ]
                pila.append((nivel, entrada_actual or seccion_actual))
                continue

            if seccion_actual is None:
                seccion_actual = crear_nodo("Introducción")
                secciones.append(seccion_actual)
                pila = [(2, seccion_actual)]
            contenedor = entrada_actual or seccion_actual
            if nombre_tag == "p" and grupo_campeones is not None:
                campeon_inline = self._detectar_campeon_inline(texto)
                if campeon_inline:
                    campeon_id, nombre = campeon_inline
                    titulo_limpio = re.sub(
                        r"^(?:NOVEDAD|ACTUALIZACIÓN|ACTUALIZACION|MEJORA|DEBILITACIÓN|DEBILITACION)\s+",
                        "",
                        texto,
                        flags=re.I,
                    ).strip()
                    candidato_actual = (
                        self._resolver_campeon(entrada_actual.get("title", ""))
                        if entrada_actual and entrada_actual.get("kind") == "champion"
                        else None
                    )
                    parece_encabezado = (
                        titulo_limpio.casefold() == nombre.casefold()
                        or texto.upper().startswith(
                            (
                                "NOVEDAD ",
                                "ACTUALIZACIÓN ",
                                "ACTUALIZACION ",
                                "MEJORA ",
                                "DEBILITACIÓN ",
                                "DEBILITACION ",
                            )
                        )
                        or candidato_actual != campeon_id
                    )
                    if parece_encabezado:
                        entrada_actual = agregar_unico(
                            grupo_campeones["children"], crear_nodo(nombre, "champion")
                        )
                        contenedor = entrada_actual
                        texto = re.sub(
                            r"^(?:NOVEDAD|ACTUALIZACIÓN|ACTUALIZACION|MEJORA|DEBILITACIÓN|DEBILITACION)\s+",
                            "",
                            texto,
                            flags=re.I,
                        )
            if nombre_tag == "p" and contenedor.get("kind") == "group":
                if grupo_objetos is not None and len(texto) < 90:
                    entrada_actual = agregar_unico(
                        grupo_objetos["children"], crear_nodo(texto, "item")
                    )
                    contenedor = entrada_actual
                    continue
            if nombre_tag == "li" and contenedor.get("kind") == "champion":
                habilidad = re.match(
                    r"^(Pasiva|[QWER]|Estadísticas básicas|Atributos base)\s*[-–:]\s*([^:–]+?)(?:\s*[:–]\s*(.*))?$",
                    texto,
                    re.I,
                )
                if habilidad:
                    titulo_habilidad = (
                        f"{habilidad.group(1).title()} – {habilidad.group(2).strip()}"
                        if habilidad.group(2).strip()
                        else habilidad.group(1)
                    )
                    detalle = (habilidad.group(3) or "").strip()
                    nodo_habilidad = agregar_unico(
                        contenedor["children"], crear_nodo(titulo_habilidad, "detail")
                    )
                    ranura = habilidad.group(1).casefold()
                    if ranura in {"pasiva", "q", "w", "e", "r"}:
                        nodo_habilidad["ability_slot"] = (
                            "passive" if ranura == "pasiva" else ranura
                        )
                        nodo_habilidad["champion_id"] = contenedor.get("champion_id")
                    if detalle:
                        nodo_habilidad["blocks"].append(
                            {
                                "type": "change",
                                "text": detalle,
                                "change_type": self._clasificar_cambio(detalle),
                            }
                        )
                    continue
            tipo_bloque = "change" if nombre_tag == "li" else "paragraph"
            contenedor["blocks"].append(
                {
                    "type": tipo_bloque,
                    "text": texto,
                    "change_type": self._clasificar_cambio(texto),
                }
            )
        return [
            seccion for seccion in secciones if seccion["blocks"] or seccion["children"]
        ]

    @staticmethod
    def _es_icono_data_dragon(url: str) -> bool:
        """Identifica iconos Data Dragon incluso detrás de un proxy de imágenes Riot."""
        pendiente = [str(url)]
        visitadas: set[str] = set()
        while pendiente:
            actual = unquote(pendiente.pop())
            if actual in visitadas:
                continue
            visitadas.add(actual)
            ruta = urlparse(actual).path.casefold()
            if re.search(r"/img/(?:champion|passive|spell|item)/", ruta):
                return True
            pendiente.extend(parse_qs(urlparse(actual).query).get("f", []))
        return False

    def _detectar_campeon_inline(self, texto: str) -> tuple[str, str] | None:
        """Resuelve un campeón al inicio de encabezados integrados en párrafos del artículo."""
        limpio = re.sub(
            r"^(?:NOVEDAD|ACTUALIZACIÓN|ACTUALIZACION|MEJORA|DEBILITACIÓN|DEBILITACION)\s+",
            "",
            texto,
            flags=re.I,
        )
        palabras = limpio.split()
        for cantidad in range(min(4, len(palabras)), 0, -1):
            nombre = " ".join(palabras[:cantidad]).strip(" :-–")
            identificador = self._resolver_campeon(nombre)
            if identificador:
                return identificador, self._campeones.get(
                    self._normalizar_nombre(identificador), {}
                ).get("name", nombre)
        return None

    @classmethod
    def _cargar_catalogo_objetos(cls) -> dict[str, str]:
        """Carga nombres e identificadores de objetos desde el catálogo Data Dragon local."""
        try:
            documento = json.loads(
                (DATA_DIR / "items.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}
        resultado: dict[str, str] = {}
        for identificador, objeto in documento.get("items", {}).items():
            if not isinstance(objeto, dict):
                continue
            mapas = objeto.get("maps")
            if isinstance(mapas, dict) and mapas.get("11") is False:
                continue
            for nombre in (
                objeto.get("name"),
                objeto.get("name_es"),
                objeto.get("name_en"),
            ):
                if nombre:
                    resultado[cls._normalizar_nombre(str(nombre))] = str(identificador)
        return resultado

    def _resolver_objeto(self, nombre: str) -> str | None:
        """Resuelve un nombre localizado de objeto al identificador de Data Dragon."""
        return self._objetos.get(self._normalizar_nombre(nombre))

    @staticmethod
    def _clave_texto(texto: str) -> str:
        """Normaliza títulos para fusionar menciones repetidas de una misma entidad."""
        return re.sub(
            r"[^a-z0-9]",
            "",
            unicodedata.normalize("NFKD", texto)
            .encode("ascii", "ignore")
            .decode()
            .casefold(),
        )

    @staticmethod
    def _buscar_imagen_resumen(contenido: Any, url_articulo: str) -> str | None:
        """Selecciona la primera imagen horizontal de alta resolución del artículo oficial."""
        for imagen in contenido.select("img[src], img[data-src]"):
            fuente = str(imagen.get("src") or imagen.get("data-src") or "")
            if not fuente or fuente.startswith("data:"):
                continue
            fuente = urljoin(url_articulo, fuente)
            coincidencia = re.search(r"(\d{3,4})x(\d{3,4})", urlparse(fuente).path)
            if (
                coincidencia
                and int(coincidencia.group(1)) >= 1200
                and int(coincidencia.group(1)) / max(1, int(coincidencia.group(2)))
                > 1.25
            ):
                return fuente
        return None

    def _guardar_imagen_resumen(self, url: str | None, version: str) -> str | None:
        """Descarga con límites la imagen oficial y la guarda en caché de forma atómica."""
        if not url:
            return None
        try:
            respuesta = self.sesion.get(url, timeout=(5, 15), stream=True)
            respuesta.raise_for_status()
            tipo = respuesta.headers.get("Content-Type", "").split(";", 1)[0].casefold()
            extensiones = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
            }
            if tipo not in extensiones:
                return None
            datos = respuesta.content
            if not datos or len(datos) > 8 * 1024 * 1024:
                return None
            base = re.sub(r"[^0-9.]", "_", version)
            destino = self.directorio / f"patch_{base}_hero{extensiones[tipo]}"
            temporal = destino.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporal.write_bytes(datos)
            temporal.replace(destino)
            return str(destino)
        except (requests.RequestException, OSError):
            return None

    @staticmethod
    def _clasificar_cambio(texto: str) -> str | None:
        """Clasifica solo cuando Riot nombra explícitamente una mejora o debilitación."""
        normalizado = texto.casefold()
        debilitacion = any(
            termino in normalizado
            for termino in (
                "debilitación",
                "debilitaciones",
                "debilitamos",
                "debilitar",
            )
        )
        mejora = any(
            termino in normalizado
            for termino in ("mejora", "mejoras", "mejoramos", "potenciamos")
        )
        if debilitacion and not mejora:
            return "Nerf"
        if mejora and not debilitacion:
            return "Buff"
        if mejora and debilitacion:
            return None
        if "ajuste" in normalizado or "ajustamos" in normalizado:
            return "Adjustment"
        return None

    @staticmethod
    def _fecha_articulo(html: str) -> str | None:
        """Lee fecha de publicación JSON-LD o metadatos; recibe HTML, retorna ISO o None."""
        sopa = BeautifulSoup(html, "html.parser")
        meta = sopa.select_one(
            'meta[property="article:published_time"], meta[name="date"], time[datetime]'
        )
        return str(meta.get("content") or meta.get("datetime")) if meta else None

    def _version_data_dragon(self) -> str | None:
        """Lee versión actual de Data Dragon para contexto de numeración; retorna versión o None."""
        try:
            respuesta = self.sesion.get(
                "https://ddragon.leagueoflegends.com/api/versions.json", timeout=8
            )
            respuesta.raise_for_status()
            versiones = respuesta.json()
            return (
                str(versiones[0]) if isinstance(versiones, list) and versiones else None
            )
        except (requests.RequestException, ValueError, TypeError):
            return None
