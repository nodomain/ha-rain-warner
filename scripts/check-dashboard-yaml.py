#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["PyYAML>=6"]
# ///
"""Sanity-check the dashboard YAML: parse it, verify both visibility
conditions are correctly attached to the rain_starts_at and rain_ends_at
tiles."""

import sys
from pathlib import Path

import yaml

cfg = yaml.safe_load(Path("dashboard/rain-warner-dashboard.yaml").read_text())

found_starts = False
found_ends = False
for view in cfg["views"]:
    for section in view["sections"]:
        for card in section.get("cards", []):
            if card.get("entity") == "sensor.rain_warner_rain_starts_at":
                vis = card.get("visibility")
                if vis and vis[0]["state"] == "off":
                    found_starts = True
                    print(f"✅ rain_starts_at tile: visibility={vis}")
            if card.get("entity") == "sensor.rain_warner_rain_ends_at":
                vis = card.get("visibility")
                if vis and vis[0]["state"] == "on":
                    found_ends = True
                    print(f"✅ rain_ends_at tile: visibility={vis}")

if not (found_starts and found_ends):
    print("❌ visibility conditions missing", file=sys.stderr)
    sys.exit(1)
print("✅ dashboard YAML looks good")
