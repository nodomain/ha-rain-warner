#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "websockets>=12",
#     "PyYAML>=6",
# ]
# ///
"""Update a Home Assistant storage-mode Lovelace dashboard via WebSocket API.

This avoids the manual "paste YAML into raw dashboard" step. The target
dashboard must already exist (create it once via the HA UI, then let this
tool keep it in sync).

Usage:
    HA_URL=http://ha.local:8123 HA_TOKEN=<long-lived> \
        ./tools/ha_update_dashboard.py <url_path> <config.yaml>

Example:
    ./tools/ha_update_dashboard.py rain-warner \
        dashboard/rain-warner-dashboard.yaml

Environment:
    HA_URL    Base URL of Home Assistant (http:// or https://).
    HA_TOKEN  Long-lived access token
              (Profile → Security → Long-Lived Access Tokens).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import websockets
import yaml

CONNECT_TIMEOUT_S = 10.0
SAVE_TIMEOUT_S = 30.0
MAX_MESSAGE_BYTES = 10 * 1024 * 1024  # dashboards can be large


async def update_dashboard(ws_url: str, token: str, url_path: str, config: dict) -> None:
    async with asyncio.timeout(CONNECT_TIMEOUT_S + SAVE_TIMEOUT_S):
        async with websockets.connect(ws_url, max_size=MAX_MESSAGE_BYTES) as ws:
            # 1. Server greets with auth_required.
            greeting = json.loads(await ws.recv())
            if greeting.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected greeting: {greeting!r}")

            # 2. Authenticate with the long-lived access token.
            await ws.send(json.dumps({"type": "auth", "access_token": token}))
            auth_result = json.loads(await ws.recv())
            if auth_result.get("type") != "auth_ok":
                raise RuntimeError(
                    f"Authentication failed: {auth_result.get('message', auth_result)}"
                )

            # 3. Save the dashboard config.
            request = {
                "id": 1,
                "type": "lovelace/config/save",
                "url_path": url_path,
                "config": config,
            }
            await ws.send(json.dumps(request))
            response = json.loads(await ws.recv())
            if not response.get("success", False):
                error = response.get("error", response)
                raise RuntimeError(f"Save failed: {error}")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2

    url_path, config_path = sys.argv[1], sys.argv[2]

    ha_url = os.environ.get("HA_URL", "").rstrip("/")
    token = os.environ.get("HA_TOKEN", "")
    if not ha_url or not token:
        print(
            "\u274c HA_URL and HA_TOKEN must be set in the environment.",
            file=sys.stderr,
        )
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

    config_file = Path(config_path)
    if not config_file.is_file():
        print(f"\u274c Config file not found: {config_path}", file=sys.stderr)
        return 2

    with config_file.open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    if not isinstance(config, dict):
        print(
            f"\u274c Expected a YAML mapping at the top level, got {type(config).__name__}",
            file=sys.stderr,
        )
        return 2

    try:
        asyncio.run(update_dashboard(ws_url, token, url_path, config))
    except asyncio.TimeoutError:
        print(
            f"\u274c Timed out talking to {ha_url} (\u2265 "
            f"{CONNECT_TIMEOUT_S + SAVE_TIMEOUT_S:.0f}s).",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 -- top-level CLI boundary
        print(f"\u274c Dashboard update failed: {exc}", file=sys.stderr)
        return 1

    print(f"\u2705 Dashboard '{url_path}' updated via {ha_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
