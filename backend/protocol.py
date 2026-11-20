"""JSON-lines RPC protocol managed by Electron over child-process stdio."""

from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from backend.bootstrap import bootstrap_payload
from backend.contracts import BackendOperationError, failure, success


def main() -> int:
    # Electron consumes JSON Lines as UTF-8 regardless of the Windows
    # console code page. Explicitly configure the streams before emitting any
    # localized text or reading requests from the child-process pipes.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")

    started = time.perf_counter()

    def boot_log(stage: str, *, elapsed: float | None = None, detail: str = "") -> None:
        duration = f" duration_ms={elapsed * 1000:.1f}" if elapsed is not None else ""
        suffix = f" detail={detail}" if detail else ""
        print(f"[BOOT] time={datetime.now(UTC).isoformat()} stage={stage} uptime_ms={(time.perf_counter() - started) * 1000:.1f}{duration}{suffix}",
              file=sys.stderr, flush=True)

    boot_log("module_imports_complete")
    output_lock = threading.Lock()
    request_slots = threading.BoundedSemaphore(16)
    # Bounded workers keep slow LCU synchronization off the protocol reader so
    # bootstrap/status and other requests remain serviceable.
    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="solralol-rpc")
    app_lock = threading.Lock()
    app = None
    app_error: BackendOperationError | None = None
    health_logged = False

    def application():
        nonlocal app, app_error
        if app is not None:
            return app
        with app_lock:
            if app is not None:
                return app
            if app_error is not None:
                raise app_error
            stage_started = time.perf_counter()
            boot_log("services_import_started")
            try:
                from backend.application import Application
                boot_log("services_import_complete", elapsed=time.perf_counter() - stage_started)
                stage_started = time.perf_counter()
                boot_log("services_initialization_started")
                app = Application()
                boot_log("services_ready", elapsed=time.perf_counter() - stage_started)
            except Exception as error:
                boot_log("services_initialization_failed", elapsed=time.perf_counter() - stage_started,
                         detail=type(error).__name__)
                traceback.print_exc(file=sys.stderr)
                app_error = BackendOperationError("service_unavailable", "No se pudieron iniciar los servicios del backend")
                raise app_error from error
            return app

    def write_response(response: dict) -> None:
        with output_lock:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def process(request_id: str, method: str, params: dict) -> None:
        try:
            write_response(success(request_id, application().dispatch(method, params)))
        except KeyError as error:
            write_response(failure(request_id, "not_found", str(error).strip("'")))
        except ValueError as error:
            write_response(failure(request_id, "invalid_argument", str(error)))
        except BackendOperationError as error:
            write_response(failure(request_id, error.code, str(error)))
        except Exception as error:  # Keep diagnostics out of the renderer.
            print(f"Backend request failed: {error}\n{traceback.format_exc()}", file=sys.stderr, flush=True)
            write_response(failure(request_id, "internal_error", "Error interno del backend"))
        finally:
            request_slots.release()

    try:
        boot_log("ipc_transport_ready")
        for line in sys.stdin:
            try:
                request = json.loads(line)
                request_id = str(request.get("id", ""))
                if request.get("protocol") != 1:
                    response = failure(request_id, "protocol_mismatch", "Versión de protocolo incompatible")
                elif not isinstance(request.get("method"), str) or not isinstance(request.get("params", {}), dict):
                    response = failure(request_id, "invalid_request", "Solicitud no válida")
                else:
                    if request["method"] == "app.bootstrap":
                        # Health reports the transport and core contract only.
                        # Optional services initialize on their first request.
                        if not health_logged:
                            boot_log("health_request_received")
                        service_state = "ready" if app is not None else "error" if app_error is not None else "loading"
                        write_response(success(request_id, bootstrap_payload(service_state)))
                        if not health_logged:
                            boot_log("health_response_sent")
                            health_logged = True
                        continue
                    if not request_slots.acquire(blocking=False):
                        write_response(failure(request_id, "busy", "El backend tiene demasiadas solicitudes pendientes"))
                        continue
                    executor.submit(process, request_id, request["method"], request.get("params", {}))
                    continue
            except (json.JSONDecodeError, AttributeError, TypeError):
                response = failure("", "invalid_json", "Mensaje JSON no válido")
            write_response(response)
    finally:
        if app is not None:
            app.request_shutdown()
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        finally:
            if app is not None:
                app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
