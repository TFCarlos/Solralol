"""Prueba el flujo HTTP de LCUService.import_item_set con sesión simulada.

Verifica:
1. PUT al endpoint correcto (item-sets/{summonerId}/sets).
2. Los conjuntos existentes del usuario se conservan.
3. El conjunto Solralol lleva 6 objetos + bloque de botas.
4. Reimportar no duplica el conjunto (uid determinista).
5. Un error HTTP se comunica sin lanzar excepciones.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.lcu_service import LCUService  # noqa: E402


class FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.puts: list[tuple[str, dict]] = []

    def get(self, url: str, timeout: float = 0) -> FakeResp:
        if "current-summoner" in url:
            return FakeResp(200, {"summonerId": "sum-1"})
        if "item-sets" in url:
            return FakeResp(200, {"itemSets": [{"uid": "user-own", "title": "Mi build"}]})
        return FakeResp(404)

    def put(self, url: str, json: dict | None = None, timeout: float = 0) -> FakeResp:
        self.puts.append((url, json or {}))
        return FakeResp(204)


class BadSession(FakeSession):
    def put(self, url: str, json: dict | None = None, timeout: float = 0) -> FakeResp:
        return FakeResp(500)


failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {name}{(' -> ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


ITEMS = ["6692", "6610", "6333", "3161", "3071", "3033"]

lcu = LCUService()
fake = FakeSession()
lcu.session = fake
lcu.port = 1234
lcu.auth_token = "x"

ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ITEMS, boots_id="3111")
check("import ok", ok, msg)
check("un solo PUT", len(fake.puts) == 1)
url, payload = fake.puts[0]
check("endpoint correcto", "item-sets/sum-1/sets" in url, url)
sets = payload["itemSets"]
check("conjunto del usuario preservado", any(s["uid"] == "user-own" for s in sets))
mine = next(s for s in sets if s["uid"] == "solralol-draft-266-top")
check("asociado a Aatrox", mine["associatedChampions"] == [266])
check("mapa y modo correctos", mine["map"] == "SR" and mine["mode"] == "CLASSIC")
check("bloque con 6 objetos", mine["blocks"][0]["items"] == [{"id": i, "count": 1} for i in ITEMS])
check("bloque de botas", mine["blocks"][1]["items"] == [{"id": "3111", "count": 1}])

ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ITEMS, boots_id="3111")
check("reimportación idempotente", ok, msg)
sets = fake.puts[-1][1]["itemSets"]
check("sin duplicados tras reimportar", sum(1 for s in sets if s["uid"] == "solralol-draft-266-top") == 1)

lcu.session = BadSession()
ok, msg = lcu.import_item_set(266, "Aatrox", "Top", ITEMS)
check("error HTTP comunicado sin excepción", not ok and "500" in msg, msg)

print()
if failures:
    print(f"PRUEBAS FALLIDAS: {len(failures)} -> {failures}")
    sys.exit(1)
print("FLUJO LCU ITEM-SET VERIFICADO")