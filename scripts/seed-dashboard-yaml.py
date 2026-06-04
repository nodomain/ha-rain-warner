#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "PyYAML>=6",
# ]
# ///
"""Convert the JSON dashboard dump from /tmp/rw-dashboard.json into the
canonical YAML form, drop the RainViewer radar iframe (now superseded by
the Rain Warner Card), and write the result to dashboard/rain-warner-dashboard.yaml.

This is a one-shot helper used to seed the repo with the current
dashboard. After this, edits should happen in the YAML file and be
deployed via `tools/ha_update_dashboard.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

SRC = Path("/tmp/rw-dashboard.json")
DEST = Path("dashboard/rain-warner-dashboard.yaml")


def _strip_radar_iframe(config: dict) -> dict:
    """Remove the rainviewer iframe and its preceding 'Radarkarte' heading.

    The radar map duplicates information now visualized in the
    Rain Warner Card's bar chart, so we drop it from the dashboard.
    """
    for view in config.get("views", []):
        for section in view.get("sections", []):
            cards = section.get("cards", [])
            kept = []
            skip_next_iframe_radar = False
            for card in cards:
                # Drop the "Radarkarte" heading...
                if card.get("type") == "heading" and card.get("heading") == "Radarkarte":
                    skip_next_iframe_radar = True
                    continue
                # ...and the rainviewer iframe that follows it.
                if (
                    skip_next_iframe_radar
                    and card.get("type") == "iframe"
                    and "rainviewer.com" in (card.get("url") or "")
                ):
                    skip_next_iframe_radar = False
                    continue
                # Defensive: drop any rainviewer iframe even without a
                # preceding heading.
                if card.get("type") == "iframe" and "rainviewer.com" in (card.get("url") or ""):
                    continue
                kept.append(card)
                skip_next_iframe_radar = False
            section["cards"] = kept
    return config


def main() -> int:
    raw = SRC.read_text(encoding="utf-8")
    # The DevTools script wrapped the value in another JSON string layer.
    if raw.startswith('"'):
        raw = json.loads(raw)
    config = json.loads(raw)

    config = _strip_radar_iframe(config)

    DEST.parent.mkdir(parents=True, exist_ok=True)
    with DEST.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False, allow_unicode=True, default_flow_style=False)
    print(f"\u2705 wrote {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
