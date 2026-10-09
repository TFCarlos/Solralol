"""Catálogo reutilizable de objetos para el análisis local, sin widgets."""

from typing import Any

from app.services.elegibilidad_objetos import (
    MODO_SOLOQ,
    ResultadoElegibilidadObjeto,
    ValidadorElegibilidadObjetos,
)


class CatalogoAnalisisLocal:
    """Reutiliza resolución de nombres y objetos durante una sesión de análisis."""

    def __init__(
        self,
        catalogo: dict[str, Any],
        objetos: list[dict[str, Any]],
        alias: dict[str, str],
        parche_catalogo: str = "",
    ) -> None:
        """Recibe catálogo, objetos y alias; inicializa sus cachés sin retornar datos."""
        self.catalogo = catalogo
        self.objetos = objetos
        self.alias = alias
        self._parche = str(parche_catalogo)
        self._identificadores: dict[str, str] = {}
        self._recomendables: dict[str, dict[str, Any]] = {}

    def normalizar_nombre(self, nombre: Any) -> str:
        """Normaliza nombre usando los alias recibidos y devuelve su clave."""
        valor = str(nombre).casefold().strip()
        return str(self.alias.get(valor, valor)).casefold()

    def validar_elegibilidad(
        self,
        identificador: str,
        objeto: dict[str, Any],
        campeon: str | None,
        modo: str,
    ) -> ResultadoElegibilidadObjeto:
        """Valida el objeto con los metadatos y parche de este catálogo."""
        datos_fuente = self.catalogo.get(str(identificador))
        if not isinstance(datos_fuente, dict):
            return ResultadoElegibilidadObjeto(False, "objeto_ausente_del_catalogo")
        combinado = dict(datos_fuente)
        combinado.update(objeto)
        combinado["id"] = str(identificador)
        return ValidadorElegibilidadObjetos.validar(
            str(identificador), combinado, campeon, modo, self.parche
        )

    def validar_objeto_inicial(
        self,
        identificador: str,
        campeon: str | None,
        modo: str = MODO_SOLOQ,
    ) -> ResultadoElegibilidadObjeto:
        """Valida objetos iniciales sin exigir atributos de objeto completo.

        Parámetros:
            identificador: ID canónico del objeto inicial.
            campeon: Campeón asociado a la recomendación.
            modo: Modo explícito de juego.

        Retorna:
            El resultado de elegibilidad inicial con metadatos del catálogo.
        """
        datos = self.catalogo.get(str(identificador))
        if not isinstance(datos, dict):
            return ResultadoElegibilidadObjeto(False, "objeto_ausente_del_catalogo")
        return ValidadorElegibilidadObjetos.validar_compra_inicial(
            str(identificador), datos, campeon, modo, self.parche
        )

    @property
    def parche(self) -> str:
        """Devuelve la versión del catálogo local de objetos."""
        return str(getattr(self, "_parche", ""))

    @parche.setter
    def parche(self, valor: str) -> None:
        """Asigna la versión de catálogo que limita las reglas de elegibilidad."""
        self._parche = str(valor)
        if hasattr(self, "_recomendables"):
            self._recomendables.clear()

    def objetos_recomendables(
        self, modo: str = MODO_SOLOQ
    ) -> dict[str, dict[str, Any]]:
        """Resuelve datos del catálogo recibido y devuelve objetos o su identificador."""
        if modo in self._recomendables:
            return self._recomendables[modo]
        catalog = self.catalogo
        result: dict[str, dict[str, Any]] = {}
        seen_names: set[str] = set()
        for item in self.objetos:
            basic = item.get("basic_info", {})
            name = str(basic.get("name", item.get("item", "")))
            norm_name = self.normalizar_nombre(name)
            item_id = str(item.get("id") or basic.get("id") or "")
            if not item_id or item_id not in catalog:
                item_id = self.id_por_nombre(name, catalog)
                if not item_id and "name_en" in basic:
                    item_id = self.id_por_nombre(basic["name_en"], catalog)
            if item_id:
                item_data = catalog.get(item_id, {})
                if not isinstance(item_data, dict):
                    continue
                item = dict(item)
                item.update(
                    {
                        field: item_data[field]
                        for field in (
                            "maps",
                            "gold",
                            "inStore",
                            "hideFromAll",
                            "requiredAlly",
                            "requiredEnemy",
                            "consumed",
                            "specialRecipe",
                            "from",
                            "into",
                        )
                        if field in item_data
                    }
                )
                item["id"] = item_id
                if not self.validar_elegibilidad(item_id, item, None, modo).elegible:
                    continue
                for field in ("description", "plaintext"):
                    if not item.get(field) and item_data.get(field):
                        item[field] = item_data[field]
                tags_estrictas = item.get("tags", [])
                tags_fuente = item_data.get("tags", [])
                tags_combinadas = set()
                for values in (tags_estrictas, tags_fuente):
                    if isinstance(values, list):
                        tags_combinadas.update(
                            str(value) for value in values if isinstance(value, str)
                        )
                item["tags"] = sorted(tags_combinadas)
                if norm_name:
                    seen_names.add(norm_name)
                result[item_id] = item

        for cid, cat_item in catalog.items():
            if cid not in result and isinstance(cat_item, dict):
                gold = cat_item.get("gold", {})
                cost = int(gold.get("total", 0)) if isinstance(gold, dict) else 0
                if cost >= 2200 and not cat_item.get("into"):
                    display_name = (
                        cat_item.get("name_es") or cat_item.get("name") or str(cid)
                    )
                    norm_display = self.normalizar_nombre(display_name)
                    if norm_display and norm_display in seen_names:
                        continue
                    if norm_display:
                        seen_names.add(norm_display)
                    candidato = {
                        "id": str(cid),
                        "item": display_name,
                        "name_en": cat_item.get("name_en", display_name),
                        "basic_info": {
                            "id": str(cid),
                            "name": display_name,
                            "name_en": cat_item.get("name_en", display_name),
                            "tier": "Legendary",
                            "gold_cost": cost,
                        },
                        "stats": cat_item.get("stats", {}),
                        "tags": cat_item.get("tags", []),
                        "description": cat_item.get("description", ""),
                        "synergy_multipliers": {},
                    }
                    if self.validar_elegibilidad(
                        str(cid), candidato, None, modo
                    ).elegible:
                        result[cid] = candidato
        self._recomendables[modo] = result
        return self._recomendables[modo]

    def id_por_nombre(
        self,
        name: str,
        catalog: dict[str, Any],
    ) -> str:
        """Resuelve datos del catálogo recibido y devuelve objetos o su identificador."""
        if not name or not catalog:
            return ""
        name_str = str(name).strip()
        if name_str in catalog:
            return name_str

        wanted = self.normalizar_nombre(name_str)
        raw_wanted = name_str.casefold()

        coincidencias: list[tuple[int, str]] = []
        for catalog_id, catalog_item in catalog.items():
            if not isinstance(catalog_item, dict):
                continue
            cat_name = self.normalizar_nombre(catalog_item.get("name", ""))
            cat_es = self.normalizar_nombre(catalog_item.get("name_es", ""))
            cat_en = self.normalizar_nombre(catalog_item.get("name_en", ""))
            if wanted in (cat_es, cat_name, cat_en) or raw_wanted in (
                cat_es,
                cat_name,
                cat_en,
            ):
                identificador = str(catalog_id)
                prioridad = 1 if len(identificador) >= 6 else 0
                coincidencias.append((prioridad, identificador))
        if coincidencias:
            return min(coincidencias)[1]

        for catalog_id, catalog_item in catalog.items():
            if not isinstance(catalog_item, dict):
                continue
            colloq = str(catalog_item.get("colloq", "")).casefold()
            if wanted and wanted in colloq:
                return str(catalog_id)
            if raw_wanted and raw_wanted in colloq:
                return str(catalog_id)

        return ""
