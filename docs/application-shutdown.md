# Application shutdown

## Electron desktop

The Electron main process owns the close sequence. Closing the main window starts one idempotent coordinator. `before-quit` prevents Electron from exiting early, stops health checks and development watchers, closes overlay/review/analysis windows, then sends EOF to the owned Python backend and waits for its `close` event. The backend is allowed up to 90 seconds to flush a recording and drain work. On timeout, Windows `taskkill /PID <backend-pid> /T /F` targets only the backend process tree; it does not search by executable name.

The JSONL protocol stops accepting operations when stdin closes, cancels queued RPCs, waits for active RPC handlers, then closes the application facade. The facade rejects new operations, signals analysis cancellation, stops Live Client/LCU polling, finalizes FFmpeg through its `q` input, joins the FFmpeg finalization worker and recording monitor, drains owned executors, and closes its LCU HTTP session. The recording monitor and FFmpeg watcher are non-daemon threads with explicit join paths.

## Validation

- `node --test tests/electron_shutdown_coordinator.test.cjs` covers idempotence, cleanup despite a failed component, graceful exit of an owned child while an unrelated child remains alive, and timeout escalation on the owned child handle.
- `python -m pytest tests/test_application_shutdown.py -q` covers backend draining, rejection of new operations, and idempotent shutdown.
- A real `backend.protocol` child process completed the bootstrap JSONL request, received stdin EOF, and exited with code 0 on Windows.
- Closing the interactive Electron window while a recording or game is active remains a manual runtime check; an existing Solralol development stack was left open during this validation.
