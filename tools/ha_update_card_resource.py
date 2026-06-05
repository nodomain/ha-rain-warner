#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "websockets>=12",
# ]
# ///
"""Path-based cache-busting for a Lovelace JS resource.

Computes a short content hash from a local card file and rewrites the
matching Lovelace resource URL to `<stem>.<hash>.js`. Path-based cache
busting beats `?v=<hash>` query strings because aggressive PWA / mobile
app caches (notably the HA Companion on iOS) sometimes ignore query
parameters when matching cached responses, so the *only* thing they
reliably treat as a fresh resource is a different filename.

The helper is idempotent: when the hash already matches what's
registered it makes no changes. It also handles the legacy URL shapes
(unhashed `/local/foo.js`, query-string `/local/foo.js?v=abc`) so the
first run after switching to path-based cache busting just bumps the
existing entry instead of leaving a duplicate behind.

Usage:
    HA_URL=http://ha.local:8123 HA_TOKEN=<long-lived> \\
        ./tools/ha_update_card_resource.py /local/<stem> <local_path>

Where `<stem>` is the URL without the hash or extension, e.g.:
    /local/rain-warner-card

The resulting target URL is `/local/rain-warner-card.<hash>.js`.

Environment:
    HA_URL    Base URL of Home Assistant (http:// or https://).
    HA_TOKEN  Long-lived access token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import websockets

CONNECT_TIMEOUT_S = 10.0
OPERATION_TIMEOUT_S = 20.0


async def _send(ws, request: dict) -> dict:
    """Send a request and return the parsed response."""
    await ws.send(json.dumps(request))
    return json.loads(await ws.recv())


def _matcher(stem_url: str) -> re.Pattern:
    """Match any URL that points at the same logical card.

    Accepts the legacy unhashed URL (`<stem>.js`), the old query-string
    cache-bust (`<stem>.js?v=...`) and the new hashed path
    (`<stem>.<hash>.js`). The trailing query string is optional so a
    user who manually appended one still matches.
    """
    escaped = re.escape(stem_url)
    return re.compile(rf"^{escaped}(?:\.[0-9a-f]+)?\.js(?:\?.*)?$")


async def update_card_resource(ws_url: str, token: str, stem_url: str, content_hash: str) -> str:
    """Update (or insert) a Lovelace JS resource so its URL ends with the hash.

    Returns a human-readable status string.
    """
    target_url = f"{stem_url}.{content_hash}.js"
    pattern = _matcher(stem_url)

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

            existing = next(
                (r for r in list_response["result"] if pattern.match(r["url"])),
                None,
            )

            if existing is None:
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

    stem_url, file_path = sys.argv[1], sys.argv[2]

    if stem_url.endswith(".js"):
        print(
            f"\u274c <stem-url> must NOT end in .js (got: {stem_url!r}). "
            "Pass the URL prefix without extension, e.g. '/local/rain-warner-card'.",
            file=sys.stderr,
        )
        return 2

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
        status = asyncio.run(update_card_resource(ws_url, token, stem_url, content_hash))
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
