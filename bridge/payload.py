"""Turn a Discord message into the JSON event sent to the processing program."""

from __future__ import annotations

from typing import Any

from .config import Config


def should_forward(message: Any, config: Config) -> bool:
    """Decide whether a message should be forwarded."""
    if message.guild is None:  # direct messages are out of scope
        return False
    if message.author.bot and not config.include_bots:
        return False
    if config.guild_ids and message.guild.id not in config.guild_ids:
        return False
    if config.channel_ids:
        channel = message.channel
        # Messages in a thread match when either the thread or its parent channel is listed.
        parent_id = getattr(channel, "parent_id", None)
        if channel.id not in config.channel_ids and parent_id not in config.channel_ids:
            return False
    return True


def build_event(message: Any, event_type: str = "message_create") -> dict[str, Any]:
    """Build a plain JSON-serialisable dict describing the message."""
    channel = message.channel
    reference = message.reference
    return {
        "type": event_type,
        "message_id": str(message.id),
        "guild": {"id": str(message.guild.id), "name": message.guild.name},
        "channel": {
            "id": str(channel.id),
            "name": getattr(channel, "name", None),
            "parent_id": str(channel.parent_id) if getattr(channel, "parent_id", None) else None,
        },
        "author": {
            "id": str(message.author.id),
            "username": message.author.name,
            "display_name": message.author.display_name,
            "bot": message.author.bot,
        },
        "content": message.content,
        "attachments": [
            {
                "filename": a.filename,
                "url": a.url,
                "content_type": a.content_type,
                "size": a.size,
            }
            for a in message.attachments
        ],
        "reply_to_message_id": (
            str(reference.message_id) if reference is not None and reference.message_id else None
        ),
        "created_at": message.created_at.isoformat(),
        "jump_url": message.jump_url,
    }
