# Agent Instructions for ha-rain-warner

## Architecture

This project is a **HACS custom_component** (Python integration) for Home Assistant.

```
custom_components/rain_warner/   ← SOURCE CODE (edit this!)
dashboard/                       ← Dashboard YAML (optional)
tools/                           ← Deploy helpers
tests/                           ← Local tests (run without HA)
        │
        │  ./deploy.sh (rsync)
        ▼
/Volumes/config/custom_components/rain_warner/  ← DEPLOYED (never edit!)
```

## Critical Rules

1. **NEVER edit files in `/Volumes/config/`** — they are synced output and
   will be overwritten on the next deploy.

2. **Always edit source files** in `custom_components/rain_warner/` and
   `dashboard/`.

3. **Custom components require a full HA restart** to pick up code changes
   (unlike YAML packages which can be soft-reloaded).

## Deploy Commands

```bash
./deploy.sh              # Sync code to config mount (no restart)
./deploy.sh --restart    # Sync + restart HA (~60s downtime)
./deploy.sh --force      # Force restart even if unchanged
```

## Testing

```bash
uv run pytest tests/ -v          # All tests (unit + live network)
uv run pytest tests/ -v -k "not network"  # Unit tests only (no network)
uv run pytest tests/ -v -m network -s     # Live DWD tests with output
```

Tests mock `homeassistant` modules via `tests/conftest.py` so they run
without HA installed. The `.env` file provides `LATITUDE`/`LONGITUDE` for
live tests.

## Environment Variables

All connection values are in `.env` (gitignored). See `.env.example` for
the full list:

| Variable | Purpose |
|----------|---------|
| `HA_URL` | Home Assistant base URL |
| `HA_TOKEN` | Long-lived access token |
| `HA_CONFIG_MOUNT` | Config volume mount point (default: /Volumes/config) |
| `HA_CONFIG_SMB_URL` | SMB URL for auto-mount (optional) |
| `HA_DASHBOARD_URL_PATH` | Dashboard URL path for API push |
| `LATITUDE` | Test location latitude (from HA zone.home) |
| `LONGITUDE` | Test location longitude (from HA zone.home) |

## File Structure

```
ha-rain-warner/
├── custom_components/rain_warner/
│   ├── __init__.py              # Integration setup (async_setup_entry)
│   ├── manifest.json            # HA integration manifest (no external deps!)
│   ├── const.py                 # Constants (URLs, grid params, thresholds)
│   ├── config_flow.py           # UI config flow (location, source, radius)
│   ├── coordinator.py           # DataUpdateCoordinator (5-min polling)
│   ├── dwd_radar.py             # DWD RADOLAN binary parser + polar stereographic projection
│   ├── bright_sky.py            # Bright Sky JSON API client (fallback)
│   ├── sensor.py                # 8 sensor entities
│   ├── binary_sensor.py         # 2 binary sensor entities
│   ├── strings.json             # Default UI strings
│   └── translations/            # i18n
│       ├── en.json
│       └── de.json
├── tests/
│   ├── conftest.py              # Mocks homeassistant modules for local testing
│   └── test_dwd_radar.py        # Unit tests + live DWD download tests
├── dashboard/
│   └── .gitkeep
├── tools/
│   └── ha_update_dashboard.py   # Dashboard WebSocket push helper (uv script)
├── deploy.sh                    # Sync & restart script (rsync + --inplace for SMB)
├── .env.example                 # Environment variable template
├── .env                         # Local config (gitignored)
├── hacs.json                    # HACS metadata
├── pyproject.toml               # Python project config + test deps
├── AGENTS.md                    # This file
├── README.md                    # Project documentation
├── CHANGELOG.md                 # Release history
└── LICENSE                      # MIT License
```

## Release Workflow

1. Update `CHANGELOG.md`: Move items from `[Unreleased]` to a new
   `[X.Y.Z] - YYYY-MM-DD` section.
2. Update `version` in `custom_components/rain_warner/manifest.json`.
3. Commit: `chore: release vX.Y.Z`
4. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z — Short description"`
5. Push: `git push && git push origin vX.Y.Z`
6. Create GitHub Release: `gh release create vX.Y.Z --title "vX.Y.Z — Title" --notes-file -`
7. For minor/major bumps with user-visible features: post a reply to
   the community announcement thread (see "Community Announcements"
   below). Patch releases skip this step.

**Important**: The CHANGELOG must always reflect the current release state.
`[Unreleased]` is for work-in-progress between releases. When cutting a
release, ALL unreleased items move to the new version section.

## Development Workflow

1. Edit Python code in `custom_components/rain_warner/`
2. Run `uv run pytest tests/ -v` to verify locally
3. Run `./deploy.sh` to sync to HA config volume
4. Run `./deploy.sh --restart` to apply changes (requires HA restart)
5. Check HA logs: Settings → System → Logs → filter "rain_warner"

## Data Sources

- **DWD Radar** (`dwd_radar.py`): Raw RADOLAN binary composites from
  `DE1200_RV_LATEST.tar.bz2`. One archive contains current observation
  (`_000`) plus 2h RADVOR nowcast (`_005` through `_120`) in 5-min steps.
  Uses polar stereographic projection (60°N, 10°E) for coordinate mapping.

- **Bright Sky** (`bright_sky.py`): JSON API wrapping DWD data, easier but
  less precise. Falls back to current weather endpoint.

## Key Technical Details

- **Grid**: DE1200 = 1200×1100 cells, 1.1 km resolution
- **Projection**: Polar stereographic (true at 60°N, central meridian 10°E,
  earth radius 6370.04 km, grid origin at -523.462, -4808.645 km)
- **Data format**: RADOLAN binary (ASCII header + uint16 LE grid data)
- **Bit flags**: Bits 0-11 = value, bit 13 = clutter, bit 14 = no-data
- **Precision**: `E-02` = 0.01 mm/5min, multiply by 12 for mm/h
- **No external Python deps**: Uses only stdlib (`array`, `bz2`, `tarfile`, `math`)
- **Extrapolation**: When rain doesn't end within 2h, estimates duration by
  tracking rain field centroid movement and trailing edge distance (capped at 6h)

## Community Announcements

The project has a single canonical announcement thread on the
official Home Assistant Community forum. Don't open new threads for
updates — reply to the existing one so the discussion stays in one
place and the topic gets bumped to the top of the category.

- **Topic:** [Rain Warner — Hyperlocal DWD radar nowcasting](https://community.home-assistant.io/t/rain-warner-hyperlocal-dwd-radar-nowcasting-2-6-h-forecast-alert-sensors-lovelace-card/1012836)
- **Category:** `Share your Projects! / Custom Integrations`
- **Tag:** `weather` (the forum's create-new-tag perm requires higher
  trust level; `rain` / `forecast` / `integration` weren't accepted at
  posting time)
- **Author:** `nodomain`

### When to post a reply

| Event | Reply? |
|-------|--------|
| Patch release (vX.Y.Z) | No |
| Minor release with new sensors / features (vX.Y.0) | Yes |
| Major release (vX.0.0) | Yes |
| Bug fixes only | No |
| Breaking changes | Yes — prominently |

### Reply template (minor / major release)

```markdown
## v0.X.0 — short headline

**Highlights**

- New sensor / feature one-liner
- Another one-liner
- Bug-fix highlight if relevant

Full changelog: <https://github.com/nodomain/ha-rain-warner/releases/tag/v0.X.0>
```

Keep the reply tight — the full notes already live in the GitHub
release, the forum reply only needs to surface what would make a
reader bother updating.

### Posting style guide (for the OP and any future thread)

- Tone: confident but not salesy. Lead with what makes the integration
  different (no external deps, hyperlocal radar grid, optical-flow
  extension, alert flags).
- Length: medium — long enough to communicate value, short enough that
  someone can decide to install in 30 seconds. The current OP is a
  good reference length.
- Structure: Problem statement → Sensors → Engines → Reference YAMLs
  → Architecture (for the curious) → Status & call for feedback.
- Always include the GitHub repo link near the top — Discourse expands
  it into a rich onebox automatically.
- Emojis: sparingly, matching the existing top-posts in the category
  (one in the heading, one in the closing line).
