from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.services.storage_manager import StorageWriteError, atomic_update_json, get_storage_manager

_CACHE_FILE_LOCK = threading.RLock()


class MatchHistoryCache:
    """Caché local para minimizar solicitudes a Riot API."""

    CACHE_VERSION = 2
    RATE_LIMIT_COOLDOWN_SECONDS = 120

    def __init__(self) -> None:
        self.cache_path = get_storage_manager().match_history_cache_path
        self.data = self._load()

    def _default_data(self) -> dict[str, Any]:
        return {
            "version": self.CACHE_VERSION,
            "accounts": {},
            "matches": {},
            "raw_matches": {},
            "timelines": {},
            "rate_limit_until": None,
        }

    def _load(self) -> dict[str, Any]:
        with _CACHE_FILE_LOCK:
            return self._load_unlocked()

    def _load_unlocked(self) -> dict[str, Any]:
        try:
            with self.cache_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)
        except (
            FileNotFoundError,
            OSError,
            json.JSONDecodeError,
        ):
            return self._default_data()

        if not isinstance(data, dict):
            return self._default_data()

        # Invalidate legacy version cache to purge un-keyed cross-player match entries
        if data.get("version", 0) < self.CACHE_VERSION:
            data["matches"] = {}
            data["version"] = self.CACHE_VERSION

        default_data = self._default_data()

        for key, value in default_data.items():
            data.setdefault(key, value)

        if not isinstance(data["accounts"], dict):
            data["accounts"] = {}

        if not isinstance(data["matches"], dict):
            data["matches"] = {}
        if not isinstance(data.get("raw_matches"), dict):
            data["raw_matches"] = {}
        if not isinstance(data["timelines"], dict):
            data["timelines"] = {}

        return data

    def _save(self, *, clear_rate_limit: bool = False) -> None:
        with _CACHE_FILE_LOCK:
            try:
                def merge(current: Any) -> dict[str, Any]:
                    if not isinstance(current, dict):
                        current = self._default_data()
                    for key in ("accounts", "matches", "raw_matches", "timelines"):
                        if not isinstance(current.get(key), dict):
                            current[key] = {}
                        current[key].update(self.data.get(key, {}))
                    cooldowns = [value for value in (current.get("rate_limit_until"), self.data.get("rate_limit_until")) if value]
                    current["rate_limit_until"] = None if clear_rate_limit else max(cooldowns) if cooldowns else None
                    timelines = current.get("timelines", {})
                    if len(timelines) > 50:
                        ordered = sorted(timelines.items(), key=lambda item: str(item[1].get("cached_at", "")))
                        for key, _value in ordered[:len(timelines) - 50]:
                            timelines.pop(key, None)
                    current["version"] = self.CACHE_VERSION
                    return current
                self.data = atomic_update_json(self.cache_path, merge, default=self._default_data())
            except OSError as error:
                logging.getLogger(__name__).exception("No se pudo actualizar la caché local de Riot")
                raise StorageWriteError("No se pudo actualizar el historial local. Comprueba los permisos del directorio de datos.") from error

    @staticmethod
    def account_key(
        game_name: str,
        tag_line: str,
        account_region: str,
    ) -> str:
        return (
            f"{game_name.strip().casefold()}"
            f"#{tag_line.strip().casefold()}"
            f"@{account_region.strip().casefold()}"
        )

    def get_account(
        self,
        game_name: str,
        tag_line: str,
        account_region: str,
    ) -> dict[str, Any] | None:
        key = self.account_key(
            game_name,
            tag_line,
            account_region,
        )
        account = self.data["accounts"].get(key)

        if not isinstance(account, dict):
            return None

        return account.copy()

    def save_account(
        self,
        game_name: str,
        tag_line: str,
        account_region: str,
        account: dict[str, Any],
    ) -> None:
        key = self.account_key(
            game_name,
            tag_line,
            account_region,
        )

        self.data["accounts"][key] = {
            "puuid": account.get("puuid", ""),
            "game_name": account.get(
                "gameName",
                game_name,
            ),
            "tag_line": account.get(
                "tagLine",
                tag_line,
            ),
            "updated_at": self._now_iso(),
        }
        self._save()

    def get_match(
        self,
        match_id: str,
        puuid: str = "",
    ) -> dict[str, Any] | None:
        with _CACHE_FILE_LOCK:
            self.data = self._load_unlocked()
        if puuid:
            key = f"{match_id}:{puuid.strip()}"
            match = self.data["matches"].get(key)
            if isinstance(match, dict):
                return match.copy()
            return None

        match = self.data["matches"].get(match_id)

        if not isinstance(match, dict):
            return None

        return match.copy()

    def save_match(
        self,
        match: dict[str, Any],
        puuid: str = "",
    ) -> None:
        match_id = str(match.get("match_id", ""))

        if not match_id:
            return

        target_puuid = puuid or str(match.get("player_puuid", ""))
        if target_puuid:
            match["player_puuid"] = target_puuid
            key = f"{match_id}:{target_puuid.strip()}"
            self.data["matches"][key] = match.copy()
        else:
            self.data["matches"][match_id] = match.copy()
        self._save()

    def get_raw_match(self, match_id: str) -> dict[str, Any] | None:
        """Return a raw Match-V5 response retained for safe reprocessing."""
        with _CACHE_FILE_LOCK:
            self.data = self._load_unlocked()
        entry = self.data.get("raw_matches", {}).get(str(match_id))
        raw = entry.get("match") if isinstance(entry, dict) else None
        return raw.copy() if isinstance(raw, dict) else None

    def save_raw_match(self, match_id: str, match: dict[str, Any]) -> None:
        """Cache a successful Match-V5 payload without marking processing complete."""
        if not match_id or not isinstance(match, dict):
            return
        raw_matches = self.data.setdefault("raw_matches", {})
        raw_matches[str(match_id)] = {"match": match.copy(), "cached_at": self._now_iso()}
        if len(raw_matches) > 50:
            ordered = sorted(raw_matches.items(), key=lambda item: str(item[1].get("cached_at", "")))
            for key, _value in ordered[:len(raw_matches) - 50]:
                raw_matches.pop(key, None)
        self._save()

    def get_timeline(self, match_id: str) -> dict[str, Any] | None:
        with _CACHE_FILE_LOCK:
            self.data = self._load_unlocked()
        entry = self.data.get("timelines", {}).get(str(match_id))
        if isinstance(entry, dict) and isinstance(entry.get("timeline"), dict):
            return entry["timeline"].copy()
        # Accept timeline entries written by the first cache format.
        return entry.copy() if isinstance(entry, dict) else None

    def save_timeline(self, match_id: str, timeline: dict[str, Any]) -> None:
        if match_id and isinstance(timeline, dict):
            timelines = self.data.setdefault("timelines", {})
            timelines[str(match_id)] = {"timeline": timeline.copy(), "cached_at": self._now_iso()}
            if len(timelines) > 50:
                ordered = sorted(timelines.items(), key=lambda item: str(item[1].get("cached_at", "")))
                for key, _value in ordered[:len(timelines) - 50]:
                    timelines.pop(key, None)
            self._save()

    def delete_match_data(self, match_id: str) -> bool:
        """Remove only Riot payloads and processed cache entries for one match."""
        target = str(match_id or "").strip()
        if not target:
            return False
        with _CACHE_FILE_LOCK:
            changed = False
            def remove(data: Any) -> dict[str, Any]:
                nonlocal changed
                if not isinstance(data, dict):
                    data = self._default_data()
                matches = data.get("matches", {})
                if isinstance(matches, dict):
                    for key in list(matches):
                        if key == target or key.startswith(f"{target}:"):
                            matches.pop(key, None)
                            changed = True
                for collection in ("raw_matches", "timelines"):
                    values = data.get(collection, {})
                    if isinstance(values, dict) and target in values:
                        values.pop(target, None)
                        changed = True
                return data
            try:
                data = atomic_update_json(self.cache_path, remove, default=self._default_data(),
                                          should_write=lambda _value, _previous: changed)
            except OSError as error:
                logging.getLogger(__name__).exception("No se pudo actualizar la caché local de Riot")
                raise StorageWriteError("No se pudo actualizar el historial local. Comprueba los permisos del directorio de datos.") from error
            self.data = data
            return changed

    def get_matches(
        self,
        match_ids: list[str],
        puuid: str = "",
    ) -> list[dict[str, Any]]:
        matches = []

        for match_id in match_ids:
            match = self.get_match(match_id, puuid=puuid)

            if match:
                matches.append(match)

        return matches

    def rate_limit_remaining_seconds(self) -> int:
        with _CACHE_FILE_LOCK:
            self.data = self._load_unlocked()
        value = self.data.get("rate_limit_until")

        if not value:
            return 0

        try:
            limit_until = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            self.data["rate_limit_until"] = None
            self._save()
            return 0

        now = datetime.now(UTC)

        if limit_until <= now:
            self.data["rate_limit_until"] = None
            self._save()
            return 0

        return max(
            1,
            int((limit_until - now).total_seconds()),
        )

    def activate_rate_limit_cooldown(
        self,
        seconds: int | None = None,
    ) -> None:
        cooldown = (
            seconds
            if seconds is not None
            else self.RATE_LIMIT_COOLDOWN_SECONDS
        )

        until = datetime.now(UTC) + timedelta(
            seconds=max(1, cooldown)
        )

        self.data["rate_limit_until"] = until.isoformat()
        self._save()

    def clear_rate_limit_cooldown(self) -> None:
        if self.data.get("rate_limit_until") is None:
            return

        self.data["rate_limit_until"] = None
        self._save(clear_rate_limit=True)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()
