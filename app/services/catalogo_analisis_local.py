"""Catálogo reutilizable de objetos para el análisis local, sin widgets."""

from typing import Any


class CatalogoAnalisisLocal:
    """Reutiliza resolución de nombres y objetos durante una sesión de análisis."""

    def __init__(
        self,
        catalogo: dict[str, Any],
        objetos: list[dict[str, Any]],
        alias: dict[str, str],
    ) -> None:
        """Recibe catálogo, objetos y alias; inicializa sus cachés sin retornar datos."""
        self.catalogo = catalogo
        self.objetos = objetos
        self.alias = alias
        self._identificadores: dict[str, str] = {}
        self._recomendables: dict[str, dict[str, Any]] | None = None

    def normalizar_nombre(self, nombre: Any) -> str:
        """Normaliza nombre usando los alias recibidos y devuelve su clave."""
        valor = str(nombre).casefold().strip()
        return str(self.alias.get(valor, valor)).casefold()

    def objetos_recomendables(self) -> dict[str, dict[str, Any]]:
        """Resuelve datos del catálogo recibido y devuelve objetos o su identificador."""
        if self._recomendables is not None:
            return self._recomendables
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
                result[item_id] = item
                if norm_name:
                    seen_names.add(norm_name)

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
                    result[cid] = {
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
                        "synergy_multipliers": {},
                    }
        self._recomendables = result
        return result

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

        for catalog_id, catalog_item in catalog.items():
            if not isinstance(catalog_item, dict):
                continue
            cat_name = self.normalizar_nombre(catalog_item.get("name", ""))
            cat_es = self.normalizar_nombre(catalog_item.get("name_es", ""))
            cat_en = str(catalog_item.get("name_en", "")).casefold().strip()

            if wanted in (cat_name, cat_es) or raw_wanted in (cat_name, cat_es, cat_en):
                return str(catalog_id)

        for catalog_id, catalog_item in catalog.items():
            if not isinstance(catalog_item, dict):
                continue
            colloq = str(catalog_item.get("colloq", "")).casefold()
            if wanted and wanted in colloq:
                return str(catalog_id)
            if raw_wanted and raw_wanted in colloq:
                return str(catalog_id)

        return ""
