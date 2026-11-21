"""Settings read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    pass


def _parse_ids(raw: str, name: str) -> frozenset[int]:
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ConfigError(f"{name} must be a comma-separated list of numeric IDs, got {part!r}")
        ids.add(int(part))
    return frozenset(ids)


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    discord_token: str
    forward_url: str
    forward_secret: str | None = None
    # Empty set means "every channel the bot can see".
    channel_ids: frozenset[int] = frozenset()
    guild_ids: frozenset[int] = frozenset()
    include_bots: bool = False
    max_retries: int = 5
    queue_size: int = 1000

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ) if env is None else env

        token = env.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError("DISCORD_TOKEN is not set")
        url = env.get("FORWARD_URL", "").strip()
        if not url.startswith(("http://", "https://")):
            raise ConfigError("FORWARD_URL must be an http:// or https:// URL")

        return cls(
            discord_token=token,
            forward_url=url,
            forward_secret=env.get("FORWARD_SECRET", "").strip() or None,
            channel_ids=_parse_ids(env.get("CHANNEL_IDS", ""), "CHANNEL_IDS"),
            guild_ids=_parse_ids(env.get("GUILD_IDS", ""), "GUILD_IDS"),
            include_bots=_parse_bool(env.get("INCLUDE_BOTS", "false")),
            max_retries=int(env.get("MAX_RETRIES", "5")),
            queue_size=int(env.get("QUEUE_SIZE", "1000")),
        )
