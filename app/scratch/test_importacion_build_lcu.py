"""Regresiones para importar builds con cinco objetos principales y botas."""

from __future__ import annotations

from typing import Any

from app.services.lcu_service import LCUService


class RespuestaLCU:
    """Respuesta mínima que cubre el contrato usado por el importador."""

    def __init__(self, estado: int, contenido: Any = None) -> None:
        self.status_code = estado
        self.contenido = contenido

    def json(self) -> Any:
        return self.contenido


class SesionBuildFalsa:
    """Registra solicitudes de item sets sin conectar al cliente de League."""

    def __init__(self) -> None:
        self.solicitudes: list[tuple[str, str, Any]] = []

    def get(self, url: str, timeout: int) -> RespuestaLCU:
        self.solicitudes.append(("GET", url, timeout))
        if url.endswith("/lol-summoner/v1/current-summoner"):
            return RespuestaLCU(200, {"summonerId": 123})
        return RespuestaLCU(
            200,
            {
                "accountId": 7,
                "timestamp": 10,
                "itemSets": [
                    {"uid": "player-build", "title": "Build personal", "blocks": []}
                ],
            },
        )

    def put(self, url: str, json: dict[str, Any], timeout: int) -> RespuestaLCU:
        self.solicitudes.append(("PUT", url, json))
        return RespuestaLCU(204)


def test_importa_build_de_cinco_objetos_con_botas_y_situacionales(
    monkeypatch,
) -> None:
    """Un build válido de cinco objetos más botas llega a la petición LCU."""
    servicio = LCUService.__new__(LCUService)
    servicio.session = SesionBuildFalsa()
    servicio.port = 2999
    monkeypatch.setattr(servicio, "is_connected", lambda: True)

    ids = ["6692", "3142", "6691", "3071", "6333"]
    exito, mensaje = servicio.import_item_set(
        champion_id=141,
        champion_name="Kayn",
        role="Jungle",
        item_ids=ids,
        boots_id="3111",
        situational=[{"label": "Tanque / Resistencias", "items": [{"id": "3157"}]}],
    )

    assert exito, mensaje
    solicitudes = servicio.session.solicitudes
    guardado = next(solicitud[2] for solicitud in solicitudes if solicitud[0] == "PUT")
    build_solralol = next(
        item_set
        for item_set in guardado["itemSets"]
        if item_set["uid"].startswith(LCUService.ITEM_SET_UID_PREFIX)
    )
    assert guardado["itemSets"][0]["uid"] == "player-build"
    inicial, principales, botas, situacional = build_solralol["blocks"]
    assert [item["id"] for item in inicial["items"]] == ["1101", "1102", "1103"]
    assert [item["id"] for item in principales["items"]] == ids
    assert "5" in principales["type"]
    assert [item["id"] for item in botas["items"]] == ["3111"]
    assert [item["id"] for item in situacional["items"]] == ["3157"]


def test_rechaza_build_vacia_o_con_objetos_duplicados_antes_de_lcu(monkeypatch) -> None:
    """No crea sets inválidos ni consulta al cliente para entradas mal formadas."""
    servicio = LCUService.__new__(LCUService)
    servicio.session = SesionBuildFalsa()
    servicio.port = 2999
    monkeypatch.setattr(servicio, "is_connected", lambda: True)

    vacia = servicio.import_item_set(141, "Kayn", "Jungle", [])
    duplicada = servicio.import_item_set(141, "Kayn", "Jungle", ["6692", "6692"])
    demasiadas = servicio.import_item_set(
        141,
        "Kayn",
        "Jungle",
        ["6692", "3142", "6691", "3071", "6333", "3157", "3031"],
    )

    assert not vacia[0]
    assert not duplicada[0]
    assert not demasiadas[0]
    assert servicio.session.solicitudes == []
