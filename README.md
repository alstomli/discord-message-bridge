# discord-message-bridge

A Discord bot that reads messages from the channels in your server and forwards each one, as JSON, to another program over HTTP.

```
Discord server ──(gateway)──▶ bridge bot ──HTTP POST JSON──▶ your program (FORWARD_URL)
```

The bot queues messages in memory and sends them from a background worker. If your program is slow or offline, the Discord connection is not blocked. The bot retries on network errors and on HTTP 408, 429 and 5xx, using exponential backoff. Other 4xx responses are logged and dropped.

## 1. Discord setup (one time)

1. Open https://discord.com/developers/applications, then your app, then **Bot**.
2. Under **Privileged Gateway Intents**, turn on **Message Content Intent**. Without it, `content` arrives empty.
3. Copy the bot token (**Reset Token** if you don't have it).
4. Make sure the bot has **View Channels** and **Read Message History** in the channels you want to forward. You can set this with the bot's role or with per-channel permissions.

## 2. Install and configure

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then edit .env
```

| Variable | Required | Meaning |
| --- | --- | --- |
| `DISCORD_TOKEN` | yes | Bot token |
| `FORWARD_URL` | yes | Where to POST each message |
| `FORWARD_SECRET` | no | Sent as the `X-Bridge-Secret` header so your program can reject other callers |
| `CHANNEL_IDS` | no | Comma-separated channel IDs to forward. Threads under those channels are included. If empty, every channel the bot can see is forwarded |
| `GUILD_IDS` | no | Comma-separated server IDs. If empty, all servers are forwarded |
| `INCLUDE_BOTS` | no | `true` also forwards messages from other bots (default `false`) |
| `MAX_RETRIES`, `QUEUE_SIZE` | no | Delivery tuning (defaults 5, 1000) |

To get channel and server IDs, turn on Developer Mode in Discord (User Settings, then Advanced). Then right-click a channel or server and choose **Copy ID**.

## 3. Run

In one terminal, start the example receiver (or your own program):

```powershell
.\.venv\Scripts\python examples\receiver.py
```

In another terminal, start the bot:

```powershell
.\.venv\Scripts\python -m bridge.bot
```

Post a message in a channel, and the receiver prints it.

## Event format

Each message is POSTed as `application/json`:

```json
{
  "type": "message_create",
  "message_id": "1310000000000000000",
  "guild":   { "id": "1300000000000000000", "name": "My Server" },
  "channel": { "id": "1300000000000000001", "name": "general", "parent_id": null },
  "author":  { "id": "1200000000000000000", "username": "alice", "display_name": "Alice", "bot": false },
  "content": "hello world",
  "attachments": [
    { "filename": "a.png", "url": "https://cdn.discordapp.com/...", "content_type": "image/png", "size": 12345 }
  ],
  "reply_to_message_id": null,
  "created_at": "2026-11-21T12:00:00+00:00",
  "jump_url": "https://discord.com/channels/.../.../..."
}
```

IDs are strings because Discord snowflakes are too large for a JavaScript number. `channel.parent_id` is set when the message is in a thread.

Your program should return any 2xx status to acknowledge the message. Return 5xx if you want the bot to retry.

## Writing your own receiver

[`examples/receiver.py`](examples/receiver.py) is a minimal aiohttp server. Replace its `process()` function with your own logic, or write the receiver in any language that can accept an HTTP POST.

## Tests

```powershell
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest
```

## Limitations

- Only new messages are forwarded. Edits, deletes and history from before the bot started are not.
- The queue lives in memory. Messages still waiting when the bot stops are lost.
- Direct messages to the bot are ignored.
