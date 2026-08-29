from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class MatchHistoryCache:
    """Caché local para minimizar solicitudes a Riot API."""

    CACHE_VERSION = 1
    RATE_LIMIT_COOLDOWN_SECONDS = 120

    def __init__(self) -> None:
        self.cache_path = (
            Path.home()
            / ".solralol"
            / "match_history_cache.json"
        )
        self.data = self._load()

    def _default_data(self) -> dict[str, Any]:
        return {
            "version": self.CACHE_VERSION,
            "accounts": {},
            "matches": {},
            "rate_limit_until": None,
        }

    def _load(self) -> dict[str, Any]:
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

        default_data = self._default_data()

        for key, value in default_data.items():
            data.setdefault(key, value)

        if not isinstance(data["accounts"], dict):
            data["accounts"] = {}

        if not isinstance(data["matches"], dict):
            data["matches"] = {}

        return data

    def _save(self) -> None:
        self.cache_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.cache_path.with_suffix(
            ".tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self.data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temporary_path.replace(self.cache_path)

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
    ) -> dict[str, Any] | None:
        match = self.data["matches"].get(match_id)

        if not isinstance(match, dict):
            return None

        return match.copy()

    def save_match(
        self,
        match: dict[str, Any],
    ) -> None:
        match_id = str(match.get("match_id", ""))

        if not match_id:
            return

        self.data["matches"][match_id] = match.copy()
        self._save()

    def get_matches(
        self,
        match_ids: list[str],
    ) -> list[dict[str, Any]]:
        matches = []

        for match_id in match_ids:
            match = self.get_match(match_id)

            if match:
                matches.append(match)

        return matches

    def rate_limit_remaining_seconds(self) -> int:
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
        self._save()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()
