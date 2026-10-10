"""Pruebas de validación, persistencia y lectura posterior de páginas LCU."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.lcu_service import LCUService

ARBOL_IDS = (8000, 8100, 8200, 8300, 8400)
FRAGMENTOS = (5005, 5008, 5001)


class RespuestaFalsa:
    """Respuesta mínima compatible con requests.Response."""

    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = "respuesta de prueba"

    def json(self) -> Any:
        """Devuelve el cuerpo simulado de la respuesta.

        Parámetros: ninguno.
        Retorno: objeto JSON de la fixture.
        """
        return self._payload


class SesionLCUFalsa:
    """Simula los endpoints de runas sin modificar el cliente real."""

    def __init__(self) -> None:
        self.perks, self.styles = crear_definiciones()
        self.pages: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_get = False
        self.fail_write_status = 0
        self.mismatch_after_write = False
        self.next_id = 1

    def get(self, url: str, timeout: int) -> RespuestaFalsa:
        """Devuelve definiciones o páginas simuladas.

        Parámetros: ruta HTTP y tiempo de espera.
        Retorno: respuesta LCU simulada.
        """
        endpoint = url.rsplit("/lol-perks/v1/", 1)[-1]
        self.calls.append(("GET", endpoint, timeout))
        if self.fail_get:
            return RespuestaFalsa(503, {"error": "no disponible"})
        payload = {
            "perks": self.perks,
            "styles": self.styles,
            "pages": self.pages,
        }.get(endpoint)
        return RespuestaFalsa(200 if payload is not None else 404, payload)

    def post(self, url: str, json: dict[str, Any], timeout: int) -> RespuestaFalsa:
        """Añade una página nueva a la respuesta simulada.

        Parámetros: ruta, payload y tiempo de espera.
        Retorno: respuesta de creación.
        """
        self.calls.append(("POST", url.rsplit("/", 1)[-1], json))
        if self.fail_write_status:
            return RespuestaFalsa(self.fail_write_status, {"error": "write rejected"})
        guardada = {**json, "id": self.next_id, "isEditable": True}
        self.next_id += 1
        self.pages.append(guardada)
        if self.mismatch_after_write:
            guardada["selectedPerkIds"] = list(json["selectedPerkIds"][:-1]) + [5002]
        return RespuestaFalsa(201, guardada)

    def put(self, url: str, json: dict[str, Any], timeout: int) -> RespuestaFalsa:
        """Actualiza la página editables indicada.

        Parámetros: ruta, payload y tiempo de espera.
        Retorno: respuesta de actualización.
        """
        page_id = int(url.rsplit("/", 1)[-1])
        self.calls.append(("PUT", str(page_id), json))
        for indice, page in enumerate(self.pages):
            if page.get("id") == page_id:
                self.pages[indice] = {**json, "id": page_id, "isEditable": True}
                if self.mismatch_after_write:
                    self.pages[indice]["selectedPerkIds"][-1] = 5002
                return RespuestaFalsa(200, self.pages[indice])
        return RespuestaFalsa(404)


def crear_definiciones() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Crea árboles y runas sintéticos con filas explícitas.

    Parámetros: ninguno.
    Retorno: listas de perks y estilos con el esquema actual de LCU.
    """
    perks: list[dict[str, Any]] = []
    styles: list[dict[str, Any]] = []
    por_arbol: dict[int, list[list[int]]] = {}
    for indice, style_id in enumerate(ARBOL_IDS):
        base = 10000 + indice * 100
        filas = [
            [base + fila * 10 + opcion for opcion in range(3)] for fila in range(4)
        ]
        por_arbol[style_id] = filas
        for fila_indice, fila in enumerate(filas):
            for opcion, perk_id in enumerate(fila):
                perks.append(
                    {
                        "id": perk_id,
                        "name": f"Perk {perk_id}",
                        "styleId": style_id,
                        "slotType": "kKeyStone"
                        if fila_indice == 0
                        else "kMixedRegularSplashable",
                    }
                )
        styles.append(
            {
                "id": style_id,
                "idName": f"tree{indice}",
                "name": f"Tree {indice}",
                "allowedSubStyles": [other for other in ARBOL_IDS if other != style_id],
                "slots": [
                    {
                        "type": "kKeyStone" if row == 0 else "kMixedRegularSplashable",
                        "perks": values,
                    }
                    for row, values in enumerate(filas)
                ]
                + [
                    {"type": "kStatMod", "perks": [5005, 5008, 5007]},
                    {"type": "kStatMod", "perks": [5008, 5010, 5001]},
                    {"type": "kStatMod", "perks": [5011, 5013, 5001]},
                ],
            }
        )
    for perk_id in (5005, 5008, 5007, 5010, 5001, 5011, 5013, 5002):
        perks.append(
            {
                "id": perk_id,
                "name": f"Shard {perk_id}",
                "styleId": 8400,
                "slotType": "kStatMod",
            }
        )
    return perks, styles


def seleccion_valida(primary: int, secondary: int, *, opcion: int = 0) -> list[int]:
    """Compone nueve IDs conforme a las filas definidas por los árboles.

    Parámetros: árboles principal y secundario y variante de opciones.
    Retorno: lista ordenada para el formato de página LCU.
    """
    _, styles = crear_definiciones()
    primary_style = next(style for style in styles if style["id"] == primary)
    secondary_style = next(style for style in styles if style["id"] == secondary)
    primary_rows = primary_style["slots"]
    secondary_rows = secondary_style["slots"]
    return [
        primary_rows[0]["perks"][opcion % 3],
        primary_rows[1]["perks"][opcion % 3],
        primary_rows[2]["perks"][(opcion + 1) % 3],
        primary_rows[3]["perks"][(opcion + 2) % 3],
        secondary_rows[1]["perks"][(opcion + 1) % 3],
        secondary_rows[2]["perks"][(opcion + 2) % 3],
        *FRAGMENTOS,
    ]


def crear_servicio(sesion: SesionLCUFalsa) -> LCUService:
    """Prepara LCUService con transporte simulado y estado conectado.

    Parámetros: sesión falsa configurada.
    Retorno: servicio apto para probar el flujo de importación.
    """
    servicio = LCUService()
    servicio.port = 12345
    servicio.session = sesion
    servicio.is_connected = lambda: True
    return servicio


def importar(
    servicio: LCUService, primary: int, secondary: int, perks: list[int]
) -> tuple[bool, str]:
    """Invoca el importador con IDs recomendados, no nombres aproximados.

    Parámetros: servicio y selección ordenada de nueve perks.
    Retorno: estado y mensaje del importador.
    """
    return servicio.import_rune_page(
        "Prueba",
        primary,
        secondary,
        perks[0],
        perks[1:4],
        perks[4:6],
        perks[6:9],
    )


@pytest.mark.parametrize("primary", ARBOL_IDS)
@pytest.mark.parametrize("secondary", ARBOL_IDS)
def test_validacion_admite_los_arboles_y_combinaciones_permitidas(
    primary: int, secondary: int
) -> None:
    """Cada árbol admite combinaciones secundarias distintas según LCU."""
    if primary == secondary:
        return
    perks, styles = crear_definiciones()
    by_id = {perk["id"]: perk for perk in perks}
    styles_by_id = {style["id"]: style for style in styles}
    for opcion in range(3):
        assert (
            LCUService._validate_rune_selection(
                primary,
                secondary,
                seleccion_valida(primary, secondary, opcion=opcion),
                by_id,
                styles_by_id,
            )
            == ""
        )


def test_importacion_crea_payload_completo_y_verifica_lectura() -> None:
    """Envía nueve selecciones ordenadas y solo confirma tras la lectura."""
    sesion = SesionLCUFalsa()
    servicio = crear_servicio(sesion)
    ids = seleccion_valida(8100, 8300)

    exito, mensaje = importar(servicio, 8100, 8300, ids)

    assert exito, mensaje
    assert sesion.pages[0]["selectedPerkIds"] == ids
    assert sesion.pages[0]["primaryStyleId"] == 8100
    assert sesion.pages[0]["subStyleId"] == 8300
    assert [call[0] for call in sesion.calls].count("POST") == 1
    assert [call[0] for call in sesion.calls].count("GET") == 4


def test_importacion_reordena_runas_sin_cambiar_la_recomendacion() -> None:
    """Asigna los IDs recomendados a las filas LCU sin alterar su conjunto."""
    sesion = SesionLCUFalsa()
    servicio = crear_servicio(sesion)
    ordenadas = seleccion_valida(8100, 8300)
    desordenadas = [
        ordenadas[0],
        ordenadas[3],
        ordenadas[1],
        ordenadas[2],
        ordenadas[5],
        ordenadas[4],
        5001,
        5008,
        5005,
    ]

    exito, mensaje = importar(servicio, 8100, 8300, desordenadas)

    assert exito, mensaje
    assert sesion.pages[0]["selectedPerkIds"] == ordenadas
    assert sorted(sesion.pages[0]["selectedPerkIds"]) == sorted(desordenadas)


def test_fragamento_repetido_se_acepta_solo_si_las_dos_filas_lo_permiten() -> None:
    """Preserva el doble fragmento adaptable que permite la definición LCU."""
    perks, styles = crear_definiciones()
    by_id = {perk["id"]: perk for perk in perks}
    styles_by_id = {style["id"]: style for style in styles}
    ids = seleccion_valida(8000, 8200)
    ids[6:9] = [5008, 5008, 5001]

    assert (
        LCUService._validate_rune_selection(8000, 8200, ids, by_id, styles_by_id) == ""
    )

    sesion = SesionLCUFalsa()
    servicio = crear_servicio(sesion)
    assert importar(servicio, 8000, 8200, ids)[0]


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (None, "9 selecciones"),
        (1, "runa principal 1"),
        (2, "fila correspondiente"),
        (4, "runa secundaria"),
        (6, "fragmento de estadísticas"),
    ],
)
def test_validador_rechaza_paginas_incompletas_o_fuera_de_fila(
    offset: int | None, expected: str
) -> None:
    """No permite omisiones ni IDs asignados a una posición distinta."""
    perks, styles = crear_definiciones()
    by_id = {perk["id"]: perk for perk in perks}
    styles_by_id = {style["id"]: style for style in styles}
    ids = seleccion_valida(8100, 8300)
    if offset is None:
        ids = ids[:-1]
    elif offset == 1:
        ids[offset] = seleccion_valida(8000, 8200)[0]
    elif offset == 2:
        ids[offset] = seleccion_valida(8000, 8200)[2]
    elif offset == 4:
        primary_style = next(style for style in styles if style["id"] == 8100)
        ids[offset] = primary_style["slots"][1]["perks"][2]
    else:
        ids[offset] = 5010

    resultado = LCUService._validate_rune_selection(
        8100, 8300, ids, by_id, styles_by_id
    )

    assert expected in resultado.casefold()


def test_importacion_rechaza_duplicados_y_ids_que_no_existen() -> None:
    """El importador no desplaza silenciosamente posiciones inválidas."""
    sesion = SesionLCUFalsa()
    servicio = crear_servicio(sesion)
    ids = seleccion_valida(8100, 8300)
    ids[2] = ids[1]
    assert not importar(servicio, 8100, 8300, ids)[0]

    ids = seleccion_valida(8100, 8300)
    ids[0] = 999999
    exito, mensaje = importar(servicio, 8100, 8300, ids)
    assert not exito
    assert "no se reconocieron" in mensaje.casefold()
    assert not any(call[0] in {"POST", "PUT"} for call in sesion.calls)


def test_importacion_rechaza_segunda_seleccion_secundaria_ausente() -> None:
    """No completa silenciosamente una página con una secundaria ausente."""
    sesion = SesionLCUFalsa()
    servicio = crear_servicio(sesion)
    ids = seleccion_valida(8100, 8300)
    exito, mensaje = servicio.import_rune_page(
        "Prueba", 8100, 8300, ids[0], ids[1:4], ids[4:5], ids[6:9]
    )
    assert not exito
    assert "9 selecciones" in mensaje
    assert not any(call[0] in {"POST", "PUT"} for call in sesion.calls)


def test_importacion_repetida_actualiza_su_pagina_sin_duplicarla() -> None:
    """La segunda importación actualiza la página Solralol existente."""
    sesion = SesionLCUFalsa()
    servicio = crear_servicio(sesion)
    ids = seleccion_valida(8100, 8300)

    assert importar(servicio, 8100, 8300, ids)[0]
    assert importar(servicio, 8100, 8300, ids)[0]

    assert len(sesion.pages) == 1
    assert [call[0] for call in sesion.calls].count("POST") == 1
    assert [call[0] for call in sesion.calls].count("PUT") == 1


def test_importacion_informa_fallo_lcu_y_discrepancia_al_guardar() -> None:
    """Los fallos HTTP y las lecturas distintas no se presentan como éxito."""
    sesion = SesionLCUFalsa()
    sesion.fail_get = True
    servicio = crear_servicio(sesion)
    ids = seleccion_valida(8100, 8300)
    exito, mensaje = importar(servicio, 8100, 8300, ids)
    assert not exito
    assert "definiciones" in mensaje

    sesion = SesionLCUFalsa()
    sesion.fail_write_status = 400
    servicio = crear_servicio(sesion)
    exito, mensaje = importar(servicio, 8100, 8300, ids)
    assert not exito
    assert "HTTP 400" in mensaje

    sesion = SesionLCUFalsa()
    sesion.mismatch_after_write = True
    servicio = crear_servicio(sesion)
    exito, mensaje = importar(servicio, 8100, 8300, ids)
    assert not exito
    assert "configuración distinta" in mensaje
