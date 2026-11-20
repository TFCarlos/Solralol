# Architecture

## Runtime

- `frontend/electron/main/` creates application and overlay windows, owns the Python child process, validates renderer IPC, and coordinates shutdown.
- `frontend/electron/preload/` exposes the bounded `window.solralol` API. The renderer uses context isolation and sandboxing with Node integration disabled.
- `frontend/src/` contains React pages, presentation state, shared overlay views, and TypeScript contracts.
- `backend/protocol.py` handles JSON Lines on stdin/stdout. `backend/application.py` validates and dispatches operations; feature modules own live match, Draft, saved match, recording, analysis, assets, and settings behavior.
- `app.bootstrap` is a transport and core-contract health response served by the protocol reader before optional services are constructed. Its additive `serviceState` field reports `loading`, `ready`, or `error`; feature requests initialize `Application` once in a bounded worker. Timestamped `[BOOT]` stages go to stderr and the Electron diagnostic log, never JSONL stdout. A failed optional initialization returns `service_unavailable` while the health endpoint remains responsive.
- `app/services/` contains reusable domain logic and repositories used by the backend. It has no Qt workers or UI adapters.
- `data/` contains bundled catalogs and assets. User history, settings, sessions, caches, and recordings stay in the configured Solralol data directory.

## Contracts and ownership

Renderer operations pass through the preload and Electron main allowlists before reaching Python. Python validates operation parameters and keeps diagnostics on stderr; stdout is reserved for protocol responses. Secrets and raw LCU credentials remain in the backend. Additive protocol changes keep the current contract version; incompatible changes require an explicit version change or compatibility path.

React owns presentation and navigation. Python owns Riot/LCU and Live Client access, data normalization, recommendations, persistence, analysis, and recording lifecycle. Electron owns windows, IPC, child processes, resource protocols, and application shutdown.

Riot artwork is resolved by `backend/assets.py` through the bounded `meta.assets` operation. Saved-match analysis passes its recorded game patch so item, rune, and summoner-spell icons use the matching Data Dragon version; the backend maps numeric spell IDs and rune IDs and caches downloads in the configured user data directory. The renderer requests unique IDs in bounded batches and applies successful batches independently. Empty item IDs are omitted, and missing artwork remains unavailable without modifying saved match records.

Champion identity resolution lives in `app/services/identidad_campeon.py`. Its indexed Data Dragon catalog maps numeric keys, Riot IDs, display names, and documented aliases to one canonical ID. Draft, Champion Analysis, the versioned champion repository, assets, live recommendations, and match analysis use this mapping; the repository reads legacy display-name or internal-ID filenames without renaming user files. The active cached catalog is preferred when available. Draft reads a saved role variant when the global profile lacks an available field, including role-specific damage percentages. `python -m scripts.audit_draft_champions` reports ambiguous aliases, duplicate local records, missing records, import/schema errors, and source-specific data gaps.

## Development and packaging

`npm run dev` starts Vite and Electron from the repository root. Electron starts `python -m backend.protocol` using the project environment. `npm run build` builds the renderer; `npm run dist:win` builds the Python backend with PyInstaller and packages the desktop application with electron-builder.

The optional `solralol_dev.py` development panel is separate tooling. It uses PySide6 from `requirements-dev.txt`; the product application and backend do not import Qt.

## Verification boundaries

Automated tests use local fixtures for service and contract behavior. They do not establish compatibility with an active Riot client, DXGI capture hardware, audio devices, or exclusive fullscreen. Verify those against the intended Windows/game setup before making runtime compatibility claims.
