#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets"]
# ///
"""Fetch recent system errors from Home Assistant via WebSocket API.

Filters for messages mentioning rain_warner / config_flow / options.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from urllib.parse import urlparse

import websockets


async def main() -> None:
    url = os.environ["HA_URL"]
    token = os.environ["HA_TOKEN"]

    parsed = urlparse(url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = f"{scheme}://{parsed.netloc}/api/websocket"

    async with websockets.connect(ws_url) as ws:
        # auth handshake
        hello = json.loads(await ws.recv())
        assert hello["type"] == "auth_required", hello
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_ok = json.loads(await ws.recv())
        assert auth_ok["type"] == "auth_ok", auth_ok

        # request system_log
        await ws.send(json.dumps({"id": 1, "type": "system_log/list"}))
        resp = json.loads(await ws.recv())

    if not resp.get("success"):
        print(json.dumps(resp, indent=2), file=sys.stderr)
        sys.exit(1)

    needle = sys.argv[1] if len(sys.argv) > 1 else "rain_warner"
    matches = []
    for entry in resp.get("result", []):
        haystack = " ".join(
            [
                entry.get("name", ""),
                entry.get("source", [""])[0] if isinstance(entry.get("source"), list) else "",
                entry.get("message", [""])[0] if isinstance(entry.get("message"), list) else "",
                entry.get("exception", "") or "",
            ]
        ).lower()
        if needle.lower() in haystack:
            matches.append(entry)

    if not matches:
        print(f"No log entries matching '{needle}' found in {len(resp['result'])} entries.")
        # show last 5 errors as a hint
        recent = sorted(resp["result"], key=lambda e: e.get("timestamp", 0), reverse=True)[:5]
        print("\nMost recent system_log entries (any):")
        for e in recent:
            msg = e.get("message", [""])
            msg = msg[0] if isinstance(msg, list) and msg else ""
            print(f"  [{e.get('level')}] {e.get('name')}: {msg[:200]}")
        return

    print(f"Found {len(matches)} entries matching '{needle}':\n")
    for e in matches:
        print("=" * 80)
        print(f"level:     {e.get('level')}")
        print(f"timestamp: {e.get('timestamp')}")
        print(f"name:      {e.get('name')}")
        src = e.get("source")
        if isinstance(src, list):
            print(f"source:    {src[0]}:{src[1] if len(src) > 1 else ''}")
        msg = e.get("message")
        if isinstance(msg, list):
            for line in msg:
                print(f"message:   {line}")
        if e.get("exception"):
            print("exception:")
            print(e["exception"])


if __name__ == "__main__":
    asyncio.run(main())
