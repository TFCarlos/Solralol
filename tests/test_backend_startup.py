"""The JSONL health path must stay responsive while optional services start."""

from __future__ import annotations

import json
import os
import subprocess
import sys


HEALTH = {"protocol": 1, "id": "health", "method": "app.bootstrap", "params": {}}
SETTINGS = {"protocol": 1, "id": "settings", "method": "settings.load", "params": {}}


def _run_backend(tmp_path, requests, prelude=""):
    script = prelude + "\nfrom backend.protocol import main\nraise SystemExit(main())\n"
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        input="".join(json.dumps(request) + "\n" for request in requests),
        text=True, capture_output=True, timeout=15, check=True,
        env={**os.environ, "SOLRALOL_DATA_DIR": str(tmp_path), "PYTHONUTF8": "1"},
    )
    return [json.loads(line) for line in result.stdout.splitlines()], result.stderr


def test_health_does_not_initialize_optional_services(tmp_path):
    responses, diagnostics = _run_backend(tmp_path, [HEALTH])
    assert [response["id"] for response in responses] == ["health"]
    assert responses[0]["ok"] is True
    assert responses[0]["result"]["serviceState"] == "loading"
    assert "stage=ipc_transport_ready" in diagnostics
    assert "stage=health_response_sent" in diagnostics
    assert "stage=services_initialization_started" not in diagnostics


def test_health_overtakes_delayed_service_initialization(tmp_path):
    prelude = """
import time
import backend.application as module
Base = module.Application
class SlowApplication(Base):
    def __init__(self):
        time.sleep(1.1)
        super().__init__()
module.Application = SlowApplication
"""
    responses, diagnostics = _run_backend(tmp_path, [SETTINGS, HEALTH], prelude)
    assert [response["id"] for response in responses] == ["health", "settings"]
    assert all(response["ok"] for response in responses)
    assert diagnostics.index("stage=health_response_sent") < diagnostics.index("stage=services_ready")


def test_optional_service_failure_preserves_core_health(tmp_path):
    prelude = """
import backend.application as module
class BrokenApplication:
    def __init__(self):
        raise RuntimeError('fixture initialization failure')
module.Application = BrokenApplication
"""
    responses, diagnostics = _run_backend(tmp_path, [SETTINGS, HEALTH, SETTINGS], prelude)
    assert responses[0]["id"] == "health" and responses[0]["ok"] is True
    assert responses[0]["result"]["serviceState"] == "loading"
    failures = [response for response in responses if response["id"] == "settings"]
    assert len(failures) == 2
    assert all(response["error"]["code"] == "service_unavailable" for response in failures)
    assert diagnostics.count("stage=services_initialization_failed") == 1
    assert "RuntimeError" in diagnostics
