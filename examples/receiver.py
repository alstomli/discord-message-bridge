"""Example "other program": receives forwarded Discord messages and processes them.

Run:  python examples/receiver.py   (listens on http://127.0.0.1:8000/discord)

Replace `process()` with your own logic.
"""

from __future__ import annotations

import hmac
import json
import os

from aiohttp import web
from dotenv import load_dotenv

load_dotenv()
SECRET = os.environ.get("FORWARD_SECRET", "").strip()


async def process(event: dict) -> None:
    """Your processing goes here. This example just prints the message."""
    print(
        f"[{event['guild']['name']} #{event['channel']['name']}] "
        f"{event['author']['display_name']}: {event['content']}"
    )
    for att in event["attachments"]:
        print(f"    attachment: {att['filename']} {att['url']}")


async def handle(request: web.Request) -> web.Response:
    if SECRET and not hmac.compare_digest(request.headers.get("X-Bridge-Secret", ""), SECRET):
        return web.Response(status=401, text="bad secret")
    try:
        event = await request.json()
    except json.JSONDecodeError:
        return web.Response(status=400, text="invalid JSON")
    await process(event)
    return web.json_response({"ok": True})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/discord", handle)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="127.0.0.1", port=int(os.environ.get("RECEIVER_PORT", "8000")))
