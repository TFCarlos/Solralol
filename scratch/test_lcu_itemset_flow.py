"""Prueba el flujo HTTP de LCUService.import_item_set con sesión simulada.

Verifica:
1. PUT al endpoint correcto (item-sets/{summonerId}/sets).
2. Los conjuntos propios del jugador se conservan intactos.
3. La página es general y se llama «Solralol - <Campeón> Build».
4. Lleva 6 objetos + bloque de botas.
5. Reimportar no duplica la página: la anterior de Solralol se sustituye.
6. Se admite que el cliente devuelva el contenedor {itemSets} o una lista suelta.
7. Un error HTTP se comunica sin lanzar excepciones.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.lcu_service import LCUService  # noqa: E402


class FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | list | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict | list:
        return self._payload


DEFAULT_WRAPPER = {
    "accountId": 99,
    "itemSets": [
        {"uid": "user-own", "title": "Mi build"},
        # Página de una versión anterior de Solralol: debe desaparecer.
        {"uid": "solralol-draft-266-top", "title": "Solralol - Aatrox (Top)"},
    ],
    "timestamp": 7,
}


class FakeSession:
    def __init__(self, sets_payload: dict | list | None = None) -> None:
        self.puts: list[tuple[str, dict]] = []
        self._sets_payload = DEFAULT_WRAPPER if sets_payload is None else sets_payload

    def get(self, url: str, timeout: float = 0) -> FakeResp:
        if "current-summoner" in url:
            return FakeResp(200, {"summonerId": "sum-1"})
        if "item-sets" in url:
            return FakeResp(200, self._sets_payload)
        return FakeResp(404)

    def put(self, url: str, json: dict | None = None, timeout: float = 0) -> FakeResp:
        self.puts.append((url, json or {}))
        return FakeResp(204)


class BadSession(FakeSession):
    def put(self, url: str, json: dict | None = None, timeout: float = 0) -> FakeResp:
        return FakeResp(500)


def build_service(session: FakeSession) -> LCUService:
    service = LCUService()
    service.session = session
    service.port = 1234
    service.auth_token = "x"
    return service


failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


ITEMS = ["6692", "6610", "6333", "3161", "3071", "3033"]

fake = FakeSession()
lcu = build_service(fake)

ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ITEMS, boots_id="3111")
check("import ok", ok, msg)
check("un solo PUT", len(fake.puts) == 1)
url, payload = fake.puts[0]
check("endpoint correcto", "item-sets/sum-1/sets" in url, url)
check("payload con itemSets", isinstance(payload.get("itemSets"), list))
check("accountId preservado", payload.get("accountId") == 99, str(payload.get("accountId")))
check("timestamp preservado", payload.get("timestamp") == 7, str(payload.get("timestamp")))
sets = payload["itemSets"]
check("conjunto del jugador preservado", any(s["uid"] == "user-own" for s in sets))
check("página antigua de Solralol eliminada",
      not any(s["uid"] == "solralol-draft-266-top" for s in sets),
      str([s["uid"] for s in sets]))
mine = next(s for s in sets if str(s["uid"]).startswith("solralol-build-"))
check("título de la página general", mine["title"] == "Solralol - Aatrox Build", mine["title"])
check("página general sin campeón asociado", mine["associatedChampions"] == [],
      str(mine["associatedChampions"]))
check("mapa y modo abiertos", mine["map"] == "any" and mine["mode"] == "any",
      f"{mine['map']}/{mine['mode']}")
check("mapas asociados SR + ARAM", mine["associatedMaps"] == [11, 12],
      str(mine["associatedMaps"]))
check("tipo custom", mine["type"] == "custom", mine["type"])
check("bloque con 6 objetos",
      mine["blocks"][0]["items"] == [{"id": i, "count": 1} for i in ITEMS])
check("bloque de botas", mine["blocks"][1]["items"] == [{"id": "3111", "count": 1}])
check("uid determinista", mine["uid"] == "solralol-build-266-top", str(mine["uid"]))

ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ITEMS, boots_id="3111")
check("reimportación idempotente", ok, msg)
sets = fake.puts[-1][1]["itemSets"]
check("una sola página de Solralol",
      sum(1 for s in sets if str(s["uid"]).startswith("solralol-")) == 1,
      str([s["uid"] for s in sets]))

ok, msg = lcu.import_item_set(233, "Briar", "Jungle", ITEMS, boots_id="3047")
check("página de otro campeón reemplaza a la anterior", ok, msg)
sets = fake.puts[-1][1]["itemSets"]
briar = next(s for s in sets if str(s["uid"]).startswith("solralol-build-"))
check("nuevo título con el campeón actual", briar["title"] == "Solralol - Briar Build",
      briar["title"])
check("sin páginas huérfanas de Solralol",
      sum(1 for s in sets if str(s["uid"]).startswith("solralol-")) == 1)
check("el conjunto del jugador sigue ahí", any(s["uid"] == "user-own" for s in sets))

loose = FakeSession([{"uid": "user-own", "title": "Mi build"}])
ok, msg = build_service(loose).import_item_set(266, "Aatrox", "Top", ITEMS)
check("lista suelta admitida", ok, msg)
check("wrapper reconstruido en la escritura",
      isinstance(loose.puts[0][1].get("itemSets"), list) and "accountId" in loose.puts[0][1])

unexpected = FakeSession({"foo": 1})
ok, msg = build_service(unexpected).import_item_set(266, "Aatrox", "Top", ITEMS)
check("contenedor inesperado no sobrescribe nada",
      not ok and "inesperado" in msg and not unexpected.puts, msg)

bad = BadSession()
ok, msg = build_service(bad).import_item_set(266, "Aatrox", "Top", ITEMS)
check("error HTTP comunicado sin excepción", not ok and "500" in msg, msg)

ok, msg = build_service(FakeSession()).import_item_set(0, "Aatrox", "Top", ITEMS)
check("champion_id inválido rechazado", not ok and "campeón" in msg, msg)
ok, msg = build_service(FakeSession()).import_item_set(266, "Aatrox", "Top",
                                                       ["1", "2", "3", "4", "5", "5"])
check("objetos duplicados rechazados", not ok and "seis objetos" in msg, msg)
ok, msg = build_service(FakeSession()).import_item_set(266, "Aatrox", "Top",
                                                       ["1", "2", "3", "4", "5", "x"])
check("IDs inválidos rechazados", not ok and "inválidos" in msg, msg)

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("FLUJO LCU ITEM-SET VERIFICADO")