#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "websockets>=12",
# ]
# ///
"""Cache-bust a Lovelace JS resource by hashing its content into the URL.

Browsers cache `/local/foo.js` aggressively because Home Assistant doesn't
emit useful cache headers. After deploying a new version of a custom card,
clients keep running the old JS until they hard-reload. This tool reads
the card file, computes a short content hash, and rewrites the matching
Lovelace resource URL to `/local/foo.js?v=<hash>` — but only when the
hash actually changed, so it's a safe no-op on repeat runs.

Usage:
    HA_URL=http://ha.local:8123 HA_TOKEN=<long-lived> \\
        ./tools/ha_update_card_resource.py /local/<file>.js <local_path>

Example:
    ./tools/ha_update_card_resource.py /local/rain-warner-card.js \\
        dashboard/rain-warner-card.js

Environment:
    HA_URL    Base URL of Home Assistant (http:// or https://).
    HA_TOKEN  Long-lived access token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

import websockets

CONNECT_TIMEOUT_S = 10.0
OPERATION_TIMEOUT_S = 20.0


async def _send(ws, request: dict) -> dict:
    """Send a request and return the parsed response."""
    await ws.send(json.dumps(request))
    return json.loads(await ws.recv())


async def update_card_resource(ws_url: str, token: str, base_url: str, content_hash: str) -> str:
    """Update (or insert) a Lovelace JS resource so its URL ends with the hash.

    Returns a human-readable status string.
    """
    async with asyncio.timeout(CONNECT_TIMEOUT_S + OPERATION_TIMEOUT_S):
        async with websockets.connect(ws_url) as ws:
            greeting = json.loads(await ws.recv())
            if greeting.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected greeting: {greeting!r}")
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            auth_result = json.loads(await ws.recv())
            if auth_result.get("type") != "auth_ok":
                raise RuntimeError(
                    f"Authentication failed: {auth_result.get('message', auth_result)}"
                )

            list_response = await _send(ws, {"id": 1, "type": "lovelace/resources"})
            if not list_response.get("success", False):
                raise RuntimeError(f"Couldn't list resources: {list_response}")

            target_url = f"{base_url}?v={content_hash}"
            existing = next(
                (r for r in list_response["result"] if r["url"].split("?", 1)[0] == base_url),
                None,
            )

            if existing is None:
                # Resource doesn't exist yet — create it.
                create_response = await _send(
                    ws,
                    {
                        "id": 2,
                        "type": "lovelace/resources/create",
                        "url": target_url,
                        "res_type": "module",
                    },
                )
                if not create_response.get("success", False):
                    raise RuntimeError(f"Create failed: {create_response}")
                return f"created {target_url}"

            if existing["url"] == target_url:
                return f"already up-to-date ({target_url})"

            update_response = await _send(
                ws,
                {
                    "id": 3,
                    "type": "lovelace/resources/update",
                    "resource_id": existing["id"],
                    "url": target_url,
                    "res_type": existing.get("type", "module"),
                },
            )
            if not update_response.get("success", False):
                raise RuntimeError(f"Update failed: {update_response}")
            return f"bumped {existing['url']} -> {target_url}"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    base_url, file_path = sys.argv[1], sys.argv[2]

    ha_url = os.environ.get("HA_URL", "").rstrip("/")
    token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not token:
        print("\u274c HA_URL and HA_TOKEN must be set in the environment.", file=sys.stderr)
        return 2

    if ha_url.startswith("https://"):
        ws_url = "wss://" + ha_url[len("https://") :] + "/api/websocket"
    elif ha_url.startswith("http://"):
        ws_url = "ws://" + ha_url[len("http://") :] + "/api/websocket"
    else:
        print(
            f"\u274c HA_URL must start with http:// or https:// (got: {ha_url!r})",
            file=sys.stderr,
        )
        return 2

    file = Path(file_path)
    if not file.is_file():
        print(f"\u274c Card file not found: {file_path}", file=sys.stderr)
        return 2

    # Short hash — 8 hex chars is plenty for cache busting.
    content_hash = hashlib.sha256(file.read_bytes()).hexdigest()[:8]

    try:
        status = asyncio.run(update_card_resource(ws_url, token, base_url, content_hash))
    except asyncio.TimeoutError:
        print(
            f"\u274c Timed out talking to {ha_url} (\u2265 "
            f"{CONNECT_TIMEOUT_S + OPERATION_TIMEOUT_S:.0f}s).",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 -- top-level CLI boundary
        print(f"\u274c Resource update failed: {exc}", file=sys.stderr)
        return 1

    print(f"\u2705 {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
