from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest


def test_backend_shutdown_is_idempotent_rejects_new_operations_and_drains_owned_resources():
    from backend.application import Application
    from backend.contracts import BackendOperationError

    class Resource:
        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

    class Executor:
        def __init__(self):
            self.calls = []

        def shutdown(self, **kwargs):
            self.calls.append(kwargs)

    app = Application.__new__(Application)
    app._shutdown_lock = threading.Lock()
    app._closing = False
    app._closed = False
    app._analysis_update_stop = threading.Event()
    app._analysis_update_thread = None
    app._analysis_recalculation_lock = threading.RLock()
    app._analysis_recalculation = {"state": "idle"}
    app._live_match = Resource()
    app._recordings = Resource()
    app._soloq_executor = Executor()
    app._analysis_recalculation_executor = Executor()
    app._storage_executor = Executor()
    app._lcu_service = SimpleNamespace(session=SimpleNamespace(close=lambda: None))

    app.request_shutdown()
    with pytest.raises(BackendOperationError, match="cerrando"):
        app.dispatch("app.bootstrap")
    app.close()
    app.close()

    assert app._live_match.closed == 1
    assert app._recordings.closed == 1
    assert app._analysis_update_stop.is_set()
    assert app._soloq_executor.calls == [{"wait": True, "cancel_futures": True}]
    assert app._analysis_recalculation_executor.calls == [{"wait": True, "cancel_futures": True}]
    assert app._storage_executor.calls == [{"wait": True, "cancel_futures": True}]
