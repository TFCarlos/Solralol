"""Persistencia versionada por campeón, consultas locales y migración verificable."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

from _paths import DATA_DIR
from app.services.rangos_campeones import CLAVES_RANGOS as RANGOS
from app.services.rangos_campeones import normalizar_rango

VERSION_ESQUEMA = 2

LINEAS = frozenset(("top", "jungle", "mid", "adc", "support"))
CERROJO_ALMACEN = threading.RLock()


class EstadoDatos(StrEnum):
    """Distingue ausencia, falta de muestra, incompatibilidad y fallo de actualización."""

    DISPONIBLE = "AVAILABLE"
    SIN_DATOS_LOCALES = "NO_LOCAL_DATA"
    SIN_DATOS_FUENTE = "NO_SOURCE_DATA"
    NO_COMPATIBLE = "UNSUPPORTED"
    ACTUALIZACION_FALLIDA = "UPDATE_FAILED"
    CORRUPTOS = "CORRUPTED_DATA"
    ESQUEMA_INCOMPATIBLE = "SCHEMA_MISMATCH"


@dataclass(frozen=True)
class ConsultaCampeon:
    """Resultado explícito de una consulta local con datos y estado independiente."""

    estado: EstadoDatos
    datos: dict[str, Any] | None = None
    actualizacion: str = ""
    perfil: dict[str, Any] | None = None
    revision: tuple[int, int] = (0, 0)
    lineas: dict[str, Any] | None = None


def identificador_campeon(nombre: str) -> str:
    """Normaliza nombre a identificador seguro y devuelve su clave de archivo."""
    clave = re.sub(r"[^a-z0-9]+", "", nombre.strip().casefold())
    if not clave:
        raise ValueError("Identidad de campeón vacía")
    return clave


def rechazar_constante_json(valor: str) -> NoReturn:
    """Rechaza constante JSON no finita recibida y lanza ValueError sin devolver datos."""
    raise ValueError(f"Constante JSON no válida: {valor}")


class RepositorioCampeones:
    """Lee un campeón por consulta y reemplaza documentos completos atómicamente."""

    def __init__(self, raiz: Path | None = None) -> None:
        """Inicializa raíz y caché limitada a ocho campeones, sin descargas."""
        self.raiz = raiz or DATA_DIR / "champion_data"
        self.raiz.mkdir(parents=True, exist_ok=True)
        self._cache: OrderedDict[str, tuple[tuple[int, int], dict[str, Any]]] = (
            OrderedDict()
        )
        self._cerrojo = CERROJO_ALMACEN

    def ruta(self, campeon: str) -> Path:
        """Devuelve ruta canónica del campeón recibido, sin abrir archivos."""
        return self.raiz / f"{identificador_campeon(campeon)}.json"

    @staticmethod
    def depurar_rangos(documento: dict[str, Any]) -> dict[str, Any]:
        """Normaliza matriz recibida y elimina rangos obsoletos sin alterar variantes canónicas."""
        resultado = copy.deepcopy(documento)
        matriz = resultado.get("ranks")
        if not isinstance(matriz, dict):
            return resultado
        compatibles: dict[str, Any] = {}
        for anterior, bloque in matriz.items():
            clave = normalizar_rango(anterior)
            if clave is None:
                continue
            if not isinstance(bloque, dict):
                raise TypeError("Rango compatible mal formado")
            destino = compatibles.setdefault(clave, {})
            for linea, variante in bloque.items():
                if isinstance(variante, dict):
                    if "rank" in variante:
                        if normalizar_rango(str(variante["rank"])) != clave:
                            raise ValueError("Identidad de rango contradictoria")
                        variante["rank"] = clave
                    resumen = variante.get("lane_stats")
                    if isinstance(resumen, dict) and "rank" in resumen:
                        if normalizar_rango(str(resumen["rank"])) != clave:
                            raise ValueError("Resumen de rango contradictorio")
                        resumen["rank"] = clave
                if linea in destino and destino[linea] != variante:
                    raise ValueError("Alias de rango con datos contradictorios")
                destino[linea] = variante
        resultado["ranks"] = compatibles
        perfil = resultado.get("profile")
        resumen = perfil.get("lane_stats") if isinstance(perfil, dict) else None
        if isinstance(resumen, dict) and "rank" in resumen:
            clave = normalizar_rango(str(resumen["rank"]))
            if clave is None:
                resultado["profile"].pop("lane_stats")
            else:
                resumen["rank"] = clave
        return resultado

    @staticmethod
    def validar(documento: dict[str, Any], campeon: str) -> None:
        """Valida identidad, esquema, perfil y combinaciones; retorna None o lanza ValueError."""
        if (
            not isinstance(documento, dict)
            or documento.get("schema_version") != VERSION_ESQUEMA
        ):
            raise ValueError("Esquema incompatible")
        if identificador_campeon(
            str(documento.get("champion", ""))
        ) != identificador_campeon(campeon):
            raise ValueError("Identidad incompatible")
        perfil = documento.get("profile")
        if (
            not isinstance(perfil, dict)
            or identificador_campeon(str(perfil.get("character", "")))
            != identificador_campeon(campeon)
            or not isinstance(perfil.get("basic_info"), dict)
        ):
            raise ValueError("Perfil incompleto")
        if not isinstance(documento.get("updated_at"), str) or not isinstance(
            documento.get("ranks"), dict
        ):
            raise TypeError("Metadatos o rangos inválidos")
        for campo in (
            "power_curve_and_scaling",
            "combat_attributes",
            "map_and_control",
            "resistances_and_survivability",
        ):
            if campo in perfil and not isinstance(perfil[campo], dict):
                raise ValueError(f"Sección global inválida: {campo}")
        resumen_global = perfil.get("lane_stats")
        if (
            isinstance(resumen_global, dict)
            and "rank" in resumen_global
            and resumen_global["rank"] not in RANGOS
        ):
            raise ValueError("Rango global obsoleto")
        for rango, bloque in documento["ranks"].items():
            if rango not in RANGOS or not isinstance(bloque, dict):
                raise ValueError("Rango inválido")
            for linea, variante in bloque.items():
                if linea == "__lane_stats__":
                    if not isinstance(variante, dict) or not isinstance(
                        variante.get("lanes"), dict
                    ):
                        raise ValueError("Resumen de líneas inválido")
                    if variante.get("rank", rango) != rango:
                        raise ValueError("Rango del resumen incompatible")
                    continue
                if (
                    linea not in LINEAS
                    or not isinstance(variante, dict)
                    or not variante
                ):
                    raise ValueError("Variante inválida")
                if not any(
                    campo in variante
                    for campo in ("runes", "most_played_build", "matchups")
                ):
                    raise ValueError("Variante sin campos esenciales")
                if (
                    variante.get("role", linea) != linea
                    or variante.get("rank", rango) != rango
                    or variante.get("updated") is False
                ):
                    raise ValueError("Filtros o actualización inválidos")
                for campo, tipo in (
                    ("runes", list),
                    ("most_played_build", list),
                    ("matchups", dict),
                    ("skill_order", (list, dict)),
                    ("lane_stats", dict),
                ):
                    if campo in variante and not isinstance(variante[campo], tipo):
                        raise ValueError(f"Campo inválido: {campo}")
                for grupo in ("counters", "good_against"):
                    enfrentamientos = variante.get("matchups", {}).get(grupo, [])
                    if not isinstance(enfrentamientos, list) or any(
                        not isinstance(valor, dict)
                        or not isinstance(valor.get("champion"), str)
                        for valor in enfrentamientos
                    ):
                        raise ValueError("Enfrentamientos inválidos")
                recomendaciones = variante.get("recommendations", [])
                if not isinstance(recomendaciones, list):
                    raise TypeError("Recomendaciones inválidas")
                for recomendacion in recomendaciones:
                    if (
                        not isinstance(recomendacion, dict)
                        or not isinstance(recomendacion.get("item_id"), str)
                        or not isinstance(recomendacion.get("name"), str)
                        or not isinstance(recomendacion.get("score"), (int, float))
                        or not isinstance(recomendacion.get("reasons"), list)
                        or not isinstance(recomendacion.get("counter_reasons"), list)
                    ):
                        raise TypeError("Recomendación incompleta")

    def _leer_campeon(self, campeon: str) -> ConsultaCampeon:
        """Lee únicamente campeón solicitado, detecta cambios externos y devuelve estado tipado."""
        ruta = self.ruta(campeon)
        with self._cerrojo:
            try:
                marca = ruta.stat()
                firma = (marca.st_mtime_ns, marca.st_size)
                clave = identificador_campeon(campeon)
                anterior = self._cache.get(clave)
                if anterior and anterior[0] == firma:
                    self._cache.move_to_end(clave)
                    return ConsultaCampeon(
                        EstadoDatos.DISPONIBLE, anterior[1], revision=firma
                    )
                documento = json.loads(
                    ruta.read_text(encoding="utf-8"),
                    parse_constant=rechazar_constante_json,
                )
                if not isinstance(documento, dict):
                    return ConsultaCampeon(EstadoDatos.CORRUPTOS)
                if documento.get("schema_version") != VERSION_ESQUEMA:
                    return ConsultaCampeon(EstadoDatos.ESQUEMA_INCOMPATIBLE)
                depurado = self.depurar_rangos(documento)
                self.validar(depurado, campeon)
                if depurado != documento:
                    self.guardar(campeon, depurado)
                    marca = ruta.stat()
                    firma = (marca.st_mtime_ns, marca.st_size)
                    documento = depurado
                self.validar(documento, campeon)
                self._cache[clave] = (firma, documento)
                while len(self._cache) > 8:
                    self._cache.popitem(last=False)
                return ConsultaCampeon(
                    EstadoDatos.DISPONIBLE, documento, revision=firma
                )
            except FileNotFoundError:
                return ConsultaCampeon(EstadoDatos.SIN_DATOS_LOCALES)
            except (OSError, ValueError, TypeError):
                return ConsultaCampeon(EstadoDatos.CORRUPTOS)

    def obtener_campeon(self, campeon: str) -> ConsultaCampeon:
        """Devuelve copia aislada del documento del campeón recibido y su estado local."""
        consulta = self._leer_campeon(campeon)
        return ConsultaCampeon(
            consulta.estado, copy.deepcopy(consulta.datos), revision=consulta.revision
        )

    def consultar(self, campeon: str, linea: str, rango: str) -> ConsultaCampeon:
        """Busca campeón/línea/rango mediante diccionarios, sin red ni otros campeones."""
        rango = normalizar_rango(rango) or ""
        if linea not in LINEAS or rango not in RANGOS:
            return ConsultaCampeon(EstadoDatos.NO_COMPATIBLE)
        consulta = self._leer_campeon(campeon)
        if consulta.estado != EstadoDatos.DISPONIBLE:
            return consulta
        documento = consulta.datos or {}
        bloque = documento["ranks"].get(rango, {})
        variante = bloque.get(linea)
        estado = (
            EstadoDatos.DISPONIBLE
            if variante
            else EstadoDatos.SIN_DATOS_FUENTE
            if documento.get("coverage") == "complete"
            or documento.get("update_status") == EstadoDatos.SIN_DATOS_FUENTE.value
            else EstadoDatos.SIN_DATOS_LOCALES
        )
        return ConsultaCampeon(
            estado,
            copy.deepcopy(variante),
            str(documento.get("update_status", "")),
            copy.deepcopy(documento["profile"]),
            consulta.revision,
            copy.deepcopy(bloque.get("__lane_stats__", {}).get("lanes", {})),
        )

    def guardar(self, campeon: str, documento: dict[str, Any]) -> None:
        """Valida documento, sincroniza archivo temporal y reemplaza destino; conserva anterior ante fallos."""
        self.validar(documento, campeon)
        contenido = json.dumps(
            documento, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        self.validar(json.loads(contenido), campeon)
        with self._cerrojo:
            descriptor, nombre = tempfile.mkstemp(
                prefix=self.ruta(campeon).stem, suffix=".tmp", dir=self.raiz
            )
            temporal = Path(nombre)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
                    archivo.write(contenido)
                    archivo.flush()
                    os.fsync(archivo.fileno())
                os.replace(temporal, self.ruta(campeon))
                self.invalidar(campeon)
            finally:
                temporal.unlink(missing_ok=True)

    def guardar_perfil(self, perfil: dict[str, Any]) -> None:
        """Guarda perfil recibido conservando matriz existente; retorna None."""
        campeon = str(perfil.get("character", ""))
        consulta = self.obtener_campeon(campeon)
        if consulta.estado not in (
            EstadoDatos.DISPONIBLE,
            EstadoDatos.SIN_DATOS_LOCALES,
        ):
            raise ValueError("No se puede sobrescribir un documento incompatible")
        documento = consulta.datos or self.documento(perfil, {}, "partial")
        documento["profile"] = copy.deepcopy(perfil)
        self.guardar(campeon, documento)

    @staticmethod
    def documento(
        perfil: dict[str, Any], matriz: dict[str, Any], cobertura: str = "complete"
    ) -> dict[str, Any]:
        """Construye documento con perfil global y matriz recibidos; devuelve esquema versionado."""
        return {
            "schema_version": VERSION_ESQUEMA,
            "champion": perfil["character"],
            "profile": copy.deepcopy(perfil),
            "ranks": copy.deepcopy(matriz),
            "updated_at": datetime.now(UTC).isoformat(),
            "source": "U.GG / OP.GG / Lolalytics",
            "update_status": "SUCCESS",
            "coverage": cobertura,
        }

    def perfiles(self) -> list[dict[str, Any]]:
        """Devuelve perfiles globales para catálogo, draft y live, sin cargar matrices en memoria simultáneamente."""
        perfiles = []
        for ruta in sorted(self.raiz.glob("*.json")):
            consulta = self.obtener_campeon(ruta.stem)
            if consulta.estado == EstadoDatos.DISPONIBLE:
                perfiles.append((consulta.datos or {})["profile"])
        catalogo = self.raiz.parent / "champion_catalog.json"
        if catalogo.exists():
            try:
                datos = json.loads(catalogo.read_text(encoding="utf-8"))
                conocidos = {
                    identificador_campeon(perfil["character"]) for perfil in perfiles
                }
                for entrada in datos.get("data", {}).values():
                    nombre = entrada.get("name")
                    if (
                        isinstance(nombre, str)
                        and identificador_campeon(nombre) not in conocidos
                    ):
                        perfiles.append({"character": nombre, "basic_info": {}})
            except (OSError, ValueError, AttributeError):
                pass
        return sorted(perfiles, key=lambda perfil: str(perfil["character"]).casefold())

    def invalidar(self, campeon: str) -> None:
        """Elimina campeón recibido de la caché; retorna None."""
        with self._cerrojo:
            self._cache.pop(identificador_campeon(campeon), None)

    def migrar(
        self,
        origen: Path,
        preparar: Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]
        | None = None,
    ) -> int:
        """Migra perfiles y matrices antiguos, verifica todos antes de eliminar origen; devuelve cantidad."""
        if not origen.exists():
            return 0
        perfiles = json.loads(origen.read_text(encoding="utf-8"))
        if not isinstance(perfiles, list) or not perfiles:
            raise ValueError("Almacén antiguo vacío o inválido")
        for ruta in self.raiz.glob("*.json"):
            anterior = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(anterior, dict) and "data" in anterior:
                destino = self.raiz.parent / "champion_metadata" / ruta.name
                destino.parent.mkdir(parents=True, exist_ok=True)
                if destino.exists() and destino.read_bytes() != ruta.read_bytes():
                    raise ValueError("Colisión de metadatos estáticos")
                destino.write_bytes(ruta.read_bytes())
                if destino.read_bytes() != ruta.read_bytes():
                    raise ValueError("Verificación de metadatos fallida")
                ruta.unlink()
        for perfil in perfiles:
            campeon = str(perfil.get("character", ""))
            consulta = self.obtener_campeon(campeon)
            if consulta.estado == EstadoDatos.DISPONIBLE:
                if (consulta.datos or {}).get("profile") != perfil:
                    raise ValueError("Migración pendiente: perfil existente diferente")
                continue
            matriz = {}
            ruta = self.ruta(campeon)
            if ruta.exists():
                anterior = json.loads(ruta.read_text(encoding="utf-8"))
                if anterior.get("version") == 1 and isinstance(
                    anterior.get("ranks"), dict
                ):
                    matriz = anterior["ranks"]
                elif "data" in anterior:
                    destino = self.raiz.parent / "champion_metadata" / ruta.name
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    if destino.exists() and destino.read_bytes() != ruta.read_bytes():
                        raise ValueError("Colisión de metadatos estáticos")
                    destino.write_bytes(ruta.read_bytes())
                else:
                    raise ValueError("Datos antiguos no reconocidos")
            documento = (
                preparar(perfil, matriz, "partial")
                if preparar
                else self.documento(perfil, matriz, "partial")
            )
            documento["source"] = "legacy_migration"
            self.guardar(campeon, documento)
        for perfil in perfiles:
            consulta = self.obtener_campeon(perfil["character"])
            if (
                consulta.estado != EstadoDatos.DISPONIBLE
                or (consulta.datos or {})["profile"] != perfil
            ):
                raise ValueError("Verificación de migración fallida")
        origen.unlink()
        return len(perfiles)
