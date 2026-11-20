"""Versioned JSON contracts used by the desktop IPC bridge."""

from __future__ import annotations

PROTOCOL_VERSION = 1


class BackendOperationError(Exception):
    """Error funcional seguro para una operación RPC concreta."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def success(request_id: str, result: object) -> dict:
    return {"protocol": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": result}


def failure(request_id: str, code: str, message: str) -> dict:
    return {
        "protocol": PROTOCOL_VERSION,
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }
