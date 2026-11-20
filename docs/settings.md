# Settings and persistence

The Electron Settings page loads a redacted snapshot with `settings.load` and writes validated partial updates with `settings.update`. Riot and Gemini key values stay in the Python backend; the renderer receives configured/not-configured flags. Saving a key replaces only that credential, and a failed validation leaves any existing saved key intact.

Settings remain in the existing JSON format under the configured Solralol data directory. Recording and overlay maps retain their existing keys so current preferences survive updates. Directory selection and opening the recordings directory are narrow Electron main-process operations; the renderer receives no generic filesystem or shell access.

The overlay page has previews for all six panels. Preview samples are presentation-only and never enter the live snapshot, analytics, recording metadata, or recommendation service. Ability overlay settings include a persistent HUD anchor and slot spacing; the ability window remains contextual and click-through regardless of its enabled setting.
