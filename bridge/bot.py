"""Discord bot entry point: `python -m bridge.bot`."""

from __future__ import annotations

import logging
import sys

import discord
from dotenv import load_dotenv

from .config import Config, ConfigError
from .forwarder import Forwarder
from .payload import build_event, should_forward

log = logging.getLogger("bridge")


class BridgeClient(discord.Client):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        # Privileged intent: must also be enabled in the Developer Portal
        # (Bot -> Privileged Gateway Intents -> Message Content Intent).
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.forwarder = Forwarder(
            config.forward_url,
            secret=config.forward_secret,
            max_retries=config.max_retries,
            queue_size=config.queue_size,
        )

    async def setup_hook(self) -> None:
        await self.forwarder.start()

    async def close(self) -> None:
        await self.forwarder.close()
        await super().close()

    async def on_ready(self) -> None:
        guilds = ", ".join(f"{g.name} ({g.id})" for g in self.guilds) or "none"
        log.info("Logged in as %s; servers: %s", self.user, guilds)
        log.info("Forwarding messages to %s", self.config.forward_url)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        if should_forward(message, self.config):
            self.forwarder.submit(build_event(message))


def main() -> None:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        config = Config.from_env()
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")

    client = BridgeClient(config)
    client.run(config.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
