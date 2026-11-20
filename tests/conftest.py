"""Release tests must close every recording monitor they create."""

import pytest

from backend.recordings import RecordingRuntime


@pytest.fixture(autouse=True)
def close_recording_runtimes(monkeypatch):
    runtimes = []
    original_init = RecordingRuntime.__init__

    def tracked_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        runtimes.append(self)

    monkeypatch.setattr(RecordingRuntime, "__init__", tracked_init)
    yield
    for runtime in reversed(runtimes):
        runtime.close()
