from __future__ import annotations

import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from bridge.config import Config, ConfigError
from bridge.forwarder import Forwarder
from bridge.payload import build_event, should_forward

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))


def make_message(
    *, bot=False, guild_id=1, channel_id=10, parent_id=None, guild=True, role_ids=(300, 301)
):
    author = SimpleNamespace(id=5, name="alice", display_name="Alice", bot=bot)
    if role_ids is not None:  # None: a plain User with no guild membership data
        # Like discord.py's Member.roles: @everyone (id == guild id) comes first.
        author.roles = [SimpleNamespace(id=r) for r in (guild_id, *role_ids)]
    return SimpleNamespace(
        id=999,
        guild=SimpleNamespace(id=guild_id, name="My Server") if guild else None,
        channel=SimpleNamespace(id=channel_id, name="general", parent_id=parent_id),
        author=author,
        content="hello world",
        attachments=[
            SimpleNamespace(
                filename="a.png", url="https://cdn/a.png", content_type="image/png", size=12
            )
        ],
        reference=SimpleNamespace(message_id=123),
        created_at=datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc),
        jump_url="https://discord.com/channels/1/10/999",
    )


def cfg(**kw):
    return Config(discord_token="t", forward_url="http://x", **kw)


# --- config ---------------------------------------------------------------

def test_config_from_env_parses_lists_and_flags():
    c = Config.from_env(
        {
            "DISCORD_TOKEN": "tok",
            "FORWARD_URL": "http://localhost:8000/discord",
            "CHANNEL_IDS": "10, 20,",
            "INCLUDE_BOTS": "yes",
        }
    )
    assert c.channel_ids == {10, 20}
    assert c.include_bots is True
    assert c.forward_secret is None


@pytest.mark.parametrize(
    "env",
    [
        {"FORWARD_URL": "http://x"},
        {"DISCORD_TOKEN": "t", "FORWARD_URL": "localhost:8000"},
        {"DISCORD_TOKEN": "t", "FORWARD_URL": "http://x", "CHANNEL_IDS": "abc"},
    ],
)
def test_config_rejects_bad_env(env):
    with pytest.raises(ConfigError):
        Config.from_env(env)


# --- filtering --------------------------------------------------------------

def test_forwards_normal_message():
    assert should_forward(make_message(), cfg())


def test_skips_dms_and_bots():
    assert not should_forward(make_message(guild=False), cfg())
    assert not should_forward(make_message(bot=True), cfg())
    assert should_forward(make_message(bot=True), cfg(include_bots=True))


def test_channel_allowlist_includes_threads_of_listed_channel():
    c = cfg(channel_ids=frozenset({10}))
    assert should_forward(make_message(channel_id=10), c)
    assert should_forward(make_message(channel_id=77, parent_id=10), c)
    assert not should_forward(make_message(channel_id=11), c)


def test_guild_allowlist():
    c = cfg(guild_ids=frozenset({1}))
    assert should_forward(make_message(guild_id=1), c)
    assert not should_forward(make_message(guild_id=2), c)


def test_build_event_shape():
    e = build_event(make_message())
    assert e["type"] == "message_create"
    assert e["message_id"] == "999"
    assert e["channel"] == {"id": "10", "name": "general", "parent_id": None}
    assert e["author"]["display_name"] == "Alice"
    assert e["author"]["role_ids"] == ["300", "301"]
    assert e["content"] == "hello world"
    assert e["attachments"][0]["url"] == "https://cdn/a.png"
    assert e["reply_to_message_id"] == "123"
    assert e["created_at"] == "2026-11-21T12:00:00+00:00"


def test_build_event_author_without_membership_has_no_role_ids():
    e = build_event(make_message(role_ids=None))
    assert e["author"]["role_ids"] == []


# --- forwarder against a real HTTP server -------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    port = free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    return runner, f"http://127.0.0.1:{port}/discord"


async def test_forwarder_delivers_and_sends_secret():
    received = []

    async def handler(request):
        received.append((request.headers.get("X-Bridge-Secret"), await request.json()))
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/discord", handler)
    runner, url = await serve(app)
    fwd = Forwarder(url, secret="s3cret", base_delay=0)
    await fwd.start()
    try:
        fwd.submit(build_event(make_message()))
        await fwd.queue.join()
    finally:
        await fwd.close()
        await runner.cleanup()

    assert len(received) == 1
    assert received[0][0] == "s3cret"
    assert received[0][1]["content"] == "hello world"


async def test_forwarder_retries_on_5xx_then_succeeds():
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        return web.Response(status=503) if calls["n"] < 3 else web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/discord", handler)
    runner, url = await serve(app)
    fwd = Forwarder(url, base_delay=0, max_retries=5)
    await fwd.start()
    try:
        assert await fwd.send({"message_id": "1"}) is True
    finally:
        await fwd.close()
        await runner.cleanup()
    assert calls["n"] == 3


async def test_forwarder_does_not_retry_4xx():
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        return web.Response(status=400, text="nope")

    app = web.Application()
    app.router.add_post("/discord", handler)
    runner, url = await serve(app)
    fwd = Forwarder(url, base_delay=0)
    await fwd.start()
    try:
        assert await fwd.send({"message_id": "1"}) is False
    finally:
        await fwd.close()
        await runner.cleanup()
    assert calls["n"] == 1


async def test_forwarder_gives_up_when_receiver_down():
    fwd = Forwarder(f"http://127.0.0.1:{free_port()}/discord", base_delay=0, max_retries=2)
    await fwd.start()
    try:
        assert await fwd.send({"message_id": "1"}) is False
    finally:
        await fwd.close()


async def test_example_receiver_accepts_forwarded_event(monkeypatch, capsys):
    import receiver

    monkeypatch.setattr(receiver, "SECRET", "s3cret")
    runner, url = await serve(receiver.make_app())
    good = Forwarder(url, secret="s3cret", base_delay=0)
    bad = Forwarder(url, secret="wrong", base_delay=0, max_retries=0)
    await good.start()
    await bad.start()
    try:
        assert await good.send(build_event(make_message())) is True
        assert await bad.send(build_event(make_message())) is False
    finally:
        await good.close()
        await bad.close()
        await runner.cleanup()
    assert "[My Server #general] Alice: hello world" in capsys.readouterr().out
