"""Regresiones del pipeline de tier list de Meta."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from bs4 import BeautifulSoup
from PySide6.QtWidgets import QApplication

from _paths import DATA_DIR
from app.services.data_dragon_assets import DataDragonAssetService
from app.services.meta_service import ServicioMeta
from app.ui.meta_page import PaginaMeta


class ServicioMetaPruebas(unittest.TestCase):
    """Verifica identidades, rangos contiguos y caché de LoLalytics."""

    def setUp(self) -> None:
        """Prepara filtros y servicio sin realizar peticiones de red."""
        self.filtros = ServicioMeta._normalizar_filtros_tier(
            {"role": "jungle", "region": "all"}
        )
        self.servicio = ServicioMeta.__new__(ServicioMeta)
        self.servicio._campeones = ServicioMeta._cargar_catalogo_campeones()
        self.servicio._objetos = ServicioMeta._cargar_catalogo_objetos()

    def _leer_fixture(self, nombre: str) -> str:
        """Lee una respuesta LoLalytics guardada junto a estas pruebas."""
        ruta = Path(__file__).parent / "fixtures" / nombre
        return ruta.read_text(encoding="utf-8")

    def test_respuestas_reales_completan_pipeline_y_cache(self) -> None:
        """Parsea grid/list SSR, une estadisticas y serializa las 60 posiciones."""
        html_lista = self._leer_fixture("lolalytics_top_euw_list.html")
        html_cuadricula = self._leer_fixture("lolalytics_top_euw_grid.html")
        respuesta_lista = Mock()
        respuesta_lista.text = html_lista
        respuesta_lista.url = (
            "https://lolalytics.com/es/lol/tierlist/?lane=top&region=euw&view=list"
        )
        respuesta_lista.raise_for_status.return_value = None
        respuesta_cuadricula = Mock()
        respuesta_cuadricula.text = html_cuadricula
        respuesta_cuadricula.url = (
            "https://lolalytics.com/es/lol/tierlist/?lane=top&region=euw&view=grid"
        )
        respuesta_cuadricula.raise_for_status.return_value = None
        sesion = Mock()
        sesion.get.side_effect = [respuesta_lista, respuesta_cuadricula]
        self.servicio.sesion = sesion
        with tempfile.TemporaryDirectory() as directorio:
            self.servicio.directorio = Path(directorio)
            datos = self.servicio.obtener_lista_niveles(
                {"role": "top", "region": "euw"}, forzar=True
            )
            self.assertEqual(len(datos["champions"]), 60)
            self.assertEqual(datos["source_count"], 60)
            self.assertEqual(
                [
                    (fila["position"], fila["champion_id"])
                    for fila in datos["champions"][:3]
                ],
                [(1, "Qiyana"), (2, "Yone"), (3, "Zed")],
            )
            primera = datos["champions"][0]
            self.assertEqual(primera["sample_size"], 648)
            self.assertEqual(primera["win_rate"], 60.8)
            filtros = ServicioMeta._normalizar_filtros_tier(
                {"role": "top", "region": "euw"}
            )
            indice = ServicioMeta._clave_indice_tier(filtros)
            cache = self.servicio._leer_cache_tier(indice, filtros)
            self.assertEqual(cache["source_count"], 60)
            self.assertEqual(cache["champions"][0]["champion_id"], "Qiyana")

    def _crear_ranking(
        self, inicio: int = 1, filtros: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """Genera filas sint?ticas completas para probar la integridad del ranking."""
        contexto = filtros or self.filtros
        filas: list[dict[str, Any]] = []
        for posicion in range(inicio, inicio + 50):
            filas.append(
                {
                    "champion_id": f"Campeon{posicion}",
                    "name": f"Campeon {posicion}",
                    "role": contexto["role"],
                    "region": contexto["region"],
                    "rank": ServicioMeta.RANGO_TIER,
                    "queue": ServicioMeta.COLA_TIER,
                    "patch": "16.20",
                    "position": posicion,
                    "tier": "A",
                    "win_rate": 50.0,
                    "pick_rate": 1.0,
                    "ban_rate": 1.0,
                    "sample_size": 1000,
                }
            )
        return filas

    def test_alias_espanol_y_clave_riot_resuelven_master_yi(self) -> None:
        """Resuelve el nombre localizado, el nombre visible y el ID Riot al mismo ID."""
        self.assertEqual(self.servicio._resolver_campeon("Maestro Yi"), "MasterYi")
        self.assertEqual(self.servicio._resolver_campeon("Master Yi"), "MasterYi")
        self.assertEqual(self.servicio._resolver_campeon("11"), "MasterYi")

    def test_parser_asocia_pasiva_habilidades_y_objeto_a_iconos_estables(self) -> None:
        """Añade slots de habilidad y resuelve ítems de la Grieta por catálogo."""
        html = BeautifulSoup(
            """
            <article>
              <h2>Actualizaciones</h2><h3>Campeones</h3><h4>Ambessa</h4>
              <ul><li>Pasiva - Caza del perrodraco: daño reducido.</li>
                  <li>Q - Golpe volcánico: enfriamiento aumentado.</li>
                  <li>R - Juicio de los lobos.</li></ul>
              <p><img src="https://am-a.akamaihd.net/image?f=https%3A%2F%2Fddragon.leagueoflegends.com%2Fcdn%2F16.17.1%2Fimg%2Fchampion%2FAshe.png"></p>
              <p><img src="/cdn/img/patch-media.jpg" alt="Arte del cambio"></p>
              <h2>Objetos</h2><h3>Experimento de hexarmadura</h3>
            </article>
            """,
            "html.parser",
        )

        secciones = self.servicio._estructurar_nota(
            html,
            "https://www.leagueoflegends.com/es-es/news/game-updates/patch-16-20-notes/",
        )
        campeon = secciones[0]["children"][0]["children"][0]
        pasiva, habilidad_q, habilidad_r = campeon["children"][:3]
        objeto = secciones[1]["children"][0]

        self.assertEqual(campeon["champion_id"], "Ambessa")
        self.assertEqual(pasiva["ability_slot"], "passive")
        self.assertEqual(pasiva["champion_id"], "Ambessa")
        self.assertEqual(habilidad_q["ability_slot"], "q")
        self.assertEqual(habilidad_r["ability_slot"], "r")
        self.assertEqual(objeto["item_id"], "3073")

        def recorrer(nodos: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """Recoge recursivamente los bloques de imagen de la estructura."""
            return [
                bloque
                for nodo in nodos
                for bloque in nodo.get("blocks", [])
                if bloque.get("type") == "image"
            ] + [
                bloque
                for nodo in nodos
                for bloque in recorrer(nodo.get("children", []))
            ]

        media = recorrer(secciones)
        self.assertEqual(len(media), 1)
        self.assertEqual(
            media[0]["url"], "https://www.leagueoflegends.com/cdn/img/patch-media.jpg"
        )

    def test_iconos_locales_resuelven_pasiva_y_slots_qwer(self) -> None:
        """Usa la imagen de pasiva y las cuatro posiciones spells de Data Dragon."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        aplicacion = QApplication.instance() or QApplication([])
        self.assertIsNotNone(aplicacion)
        from unittest.mock import patch

        with patch.object(DataDragonAssetService, "_load_catalogs"):
            assets = DataDragonAssetService()
        assets.champions["Ambessa"] = "Ambessa"

        urls = {
            slot: assets.champion_ability_url("Ambessa", slot)
            for slot in ("passive", "q", "w", "e", "r")
        }

        self.assertTrue(
            urls["passive"].endswith("/img/passive/Icon_Ambessa_Passive.png")
        )
        self.assertTrue(urls["q"].endswith("/img/spell/AmbessaQ.png"))
        self.assertTrue(urls["w"].endswith("/img/spell/AmbessaW.png"))
        self.assertTrue(urls["e"].endswith("/img/spell/AmbessaE.png"))
        self.assertTrue(urls["r"].endswith("/img/spell/AmbessaR.png"))
        self.assertEqual(assets._cache_path(urls["passive"]).parent.name, "abilities")
        campeon = json.loads(
            (DATA_DIR / "champion_abilities" / "Ambessa.json").read_text(
                encoding="utf-8"
            )
        )["data"]["Ambessa"]
        self.assertEqual(campeon["passive"]["name"], "Caza del perrodraco")

    def test_cache_estructurada_anterior_conserva_arbol_y_completa_iconos(self) -> None:
        """Migra cachés con jerarquía sin perder secciones ni texto existentes."""
        cache = {
            "schema_version": 3,
            "sections": [
                {
                    "title": "Campeones",
                    "kind": "section",
                    "blocks": [],
                    "children": [
                        {
                            "title": "Ambessa",
                            "kind": "champion",
                            "champion_id": "Ambessa",
                            "blocks": [],
                            "children": [
                                {
                                    "title": "Pasiva - Caza del perrodraco",
                                    "kind": "detail",
                                    "blocks": [
                                        {"type": "change", "text": "daño"},
                                        {
                                            "type": "image",
                                            "url": "https://am-a.akamaihd.net/image?f=https%3A%2F%2Fddragon.leagueoflegends.com%2Fcdn%2F16.17.1%2Fimg%2Fchampion%2FAshe.png",
                                            "alt": "Ashe",
                                        },
                                    ],
                                    "children": [],
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "Objetos",
                    "kind": "section",
                    "blocks": [],
                    "children": [
                        {
                            "title": "Experimento de hexarmadura",
                            "kind": "item",
                            "blocks": [],
                            "children": [],
                        }
                    ],
                },
            ],
        }

        adaptada = PaginaMeta._adaptar_cache_notas_antigua(cache)

        self.assertEqual(adaptada["schema_version"], ServicioMeta.VERSION_ESQUEMA_NOTAS)
        self.assertEqual(
            adaptada["sections"][0]["children"][0]["children"][0]["ability_slot"],
            "passive",
        )
        pasiva = adaptada["sections"][0]["children"][0]["children"][0]
        self.assertEqual(pasiva["champion_id"], "Ambessa")
        self.assertEqual([bloque["type"] for bloque in pasiva["blocks"]], ["change"])
        self.assertEqual(adaptada["sections"][1]["children"][0]["item_id"], "3073")
        self.assertEqual(
            cache["sections"][0]["children"][0]["children"][0].get("ability_slot"), None
        )

    def test_identidad_canonica_cubre_nombres_compuestos(self) -> None:
        """Normaliza ap?strofes, espacios e identificadores Data Dragon conocidos."""
        for nombre, identificador in (
            ("Cho'Gath", "Chogath"),
            ("Rek'Sai", "RekSai"),
            ("Master Yi", "MasterYi"),
            ("Maestro Yi", "MasterYi"),
            ("Nunu y Willump", "Nunu"),
            ("Nunu", "Nunu"),
        ):
            self.assertEqual(self.servicio._resolver_campeon(nombre), identificador)

    def test_filtros_validan_roles_y_regiones_soportados(self) -> None:
        """Comprueba integridad con cada rol y region admitidos por el proveedor."""
        for rol in ServicioMeta.ROLES_TIER:
            for region in ServicioMeta.REGIONES_TIER:
                filtros = ServicioMeta._normalizar_filtros_tier(
                    {"role": rol, "region": region}
                )
                ServicioMeta._validar_ranking(
                    self._crear_ranking(filtros=filtros), filtros, "16.20", 50
                )

    def test_ranking_completo_acepta_posicion_uno(self) -> None:
        """Acepta un ranking cuya primera fila conserva la posición de origen #1."""
        ServicioMeta._validar_ranking(self._crear_ranking(), self.filtros, "16.20", 50)

    def test_rechaza_primera_posicion_ausente(self) -> None:
        """Rechaza 50 filas que empiezan en #2, aunque el recuento sea suficiente."""
        with self.assertRaisesRegex(RuntimeError, "huecos"):
            ServicioMeta._validar_ranking(
                self._crear_ranking(2), self.filtros, "16.20", 50
            )

    def test_rechaza_campeon_duplicado(self) -> None:
        """Rechaza dos posiciones que apunten a la misma identidad canonica."""
        filas = self._crear_ranking()
        filas[1]["champion_id"] = filas[0]["champion_id"]
        with self.assertRaisesRegex(RuntimeError, "duplicados"):
            ServicioMeta._validar_ranking(filas, self.filtros, "16.20", 50)

    def test_rechaza_hueco_interior_y_duplicado(self) -> None:
        """Detecta huecos y puestos repetidos en los datos de origen."""
        filas = self._crear_ranking()
        filas[10]["position"] = 12
        with self.assertRaisesRegex(RuntimeError, "huecos"):
            ServicioMeta._validar_ranking(filas, self.filtros, "16.20", 50)

    def test_rechaza_cache_incompleta(self) -> None:
        """No devuelve como válida una caché cuyo puesto #1 desapareció."""
        with tempfile.TemporaryDirectory() as directorio:
            self.servicio.directorio = Path(directorio)
            nombre = ServicioMeta._clave_cache_tier(self.filtros, "16.20")
            indice = ServicioMeta._clave_indice_tier(self.filtros)
            cache = {
                "provider": ServicioMeta.PROVEEDOR_TIER,
                "filters": self.filtros,
                "rank": ServicioMeta.RANGO_TIER,
                "patch": "16.20",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "champions": self._crear_ranking(2),
                "source_count": 50,
            }
            self.servicio.guardar_cache(nombre, cache)
            self.servicio.guardar_cache(
                indice, {"cache_file": nombre, "filters": self.filtros}
            )
            self.assertIsNone(self.servicio._leer_cache_tier(indice, self.filtros))

    def test_cache_completa_se_reutiliza_sin_red(self) -> None:
        """Reutiliza una cache integra vigente sin invocar el cliente HTTP."""

        class SesionSinRed:
            """Falla si el camino de cache intenta iniciar una peticion."""

            def get(self, *args: Any, **kwargs: Any) -> Any:
                """Impide accidentalmente acceder a la red durante esta prueba."""
                raise AssertionError("No se esperaba ninguna peticion HTTP")

        with tempfile.TemporaryDirectory() as directorio:
            self.servicio.directorio = Path(directorio)
            self.servicio.sesion = SesionSinRed()
            nombre = ServicioMeta._clave_cache_tier(self.filtros, "16.20")
            indice = ServicioMeta._clave_indice_tier(self.filtros)
            cache = {
                "provider": ServicioMeta.PROVEEDOR_TIER,
                "filters": self.filtros,
                "rank": ServicioMeta.RANGO_TIER,
                "queue": ServicioMeta.COLA_TIER,
                "patch": "16.20",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "champions": self._crear_ranking(),
                "source_count": 50,
            }
            self.servicio.guardar_cache(nombre, cache)
            self.servicio.guardar_cache(
                indice, {"cache_file": nombre, "filters": self.filtros}
            )
            resultado = self.servicio.obtener_lista_niveles(self.filtros)
            self.assertTrue(resultado["cached"])
            self.assertEqual(resultado["champions"][0]["position"], 1)

    def test_descarta_cache_heredada_sin_conteo_fuente(self) -> None:
        """Fuerza refresco de caches previas que no acreditan el total de filas."""
        with tempfile.TemporaryDirectory() as directorio:
            self.servicio.directorio = Path(directorio)
            nombre = ServicioMeta._clave_cache_tier(self.filtros, "16.20")
            indice = ServicioMeta._clave_indice_tier(self.filtros)
            cache = {
                "provider": ServicioMeta.PROVEEDOR_TIER,
                "filters": self.filtros,
                "rank": ServicioMeta.RANGO_TIER,
                "queue": ServicioMeta.COLA_TIER,
                "patch": "16.20",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "champions": self._crear_ranking(),
            }
            self.servicio.guardar_cache(nombre, cache)
            self.servicio.guardar_cache(
                indice, {"cache_file": nombre, "filters": self.filtros}
            )
            self.assertIsNone(self.servicio._leer_cache_tier(indice, self.filtros))

    def test_combinar_vistas_conserva_posicion_de_cuadricula(self) -> None:
        """Enriquece métricas sin reemplazar posición ni identidad de la cuadrícula."""
        cuadrilla = self._crear_ranking()[:1]
        detallado = [dict(cuadrilla[0], position=9, win_rate=53.2, sample_size=900)]
        combinados = ServicioMeta._combinar_vistas(cuadrilla, detallado)
        self.assertEqual(combinados[0]["position"], 1)
        self.assertEqual(combinados[0]["win_rate"], 53.2)
        self.assertEqual(combinados[0]["sample_size"], 900)


if __name__ == "__main__":
    unittest.main()
