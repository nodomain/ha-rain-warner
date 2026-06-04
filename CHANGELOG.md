# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [0.6.0] - 2026-06-04 - Alert binary sensors, walldisplay cards, iPhone push, mDNS deploy fix

### Added

- Four derived alert binary sensors that pre-compute the conditions
  users actually want to react to:
  - `binary_sensor.rain_warner_rain_imminent` — dry now, rain in
    ≤ 30 min
  - `binary_sensor.rain_warner_severe_weather` — heavy / violent
    precipitation or hail likelihood
  - `binary_sensor.rain_warner_winter_weather` — snow / sleet /
    freezing rain
  - `binary_sensor.rain_warner_extended_dry_spell` — ≥ 7 d dry and
    no rain in the 6 h forecast
- New `alerts.py` module with the pure-stdlib flag logic, separated
  from the coordinator so it's unit-testable without mocking HA.
- `automations/rain-warner-push.yaml` — reference iOS push
  automations for `rain_imminent` and `severe_weather`. Both use
  `interruption-level: time-sensitive`, share a `rain-warner` tag
  group so iOS stacks notifications, and are gated to 07:00–22:00
  local time so nothing wakes you up at night.
- `dashboard/notification-cards.yaml` — four conditional markdown
  cards (🌧️ rain coming / ⛈️ severe / ❄️ winter / 🌵 dry spell) that
  slot into any walldisplay notification stack. Each card stays
  invisible until its alert flag flips on.
- Coordinator data now also exposes `max_precipitation_next_6h` as a
  side product of the dry-spell check.

### Fixed

- `deploy.sh --restart` no longer falsely reports a recovery timeout
  on macOS hosts where mDNS lookups for `.local` names go flaky
  during long script runs. The script now resolves `$HA_URL`'s
  hostname to an IP once at startup and uses that for every
  subsequent probe, dashboard push and cache-bust. Falls back to the
  original hostname if the lookup fails.

## [0.5.1] - 2026-06-04 - Hide rain-start/-end tiles when irrelevant

### Fixed

- The 'Regen ab' tile no longer shows 'Unbekannt' while it's already
  raining — it's now hidden via a `visibility` condition (raining ==
  off). Symmetric treatment for 'Regen endet' (visible only when
  raining == on). Cleaner than chasing sentinel values in the sensor.

## [0.5.0] - 2026-06-04 - Reproducible dashboard, axis fix, rain-start bug, card cache-bust

### Added

- `dashboard/rain-warner-dashboard.yaml` is now tracked in git as the
  canonical dashboard definition. `deploy.sh` pushes it to HA via the
  WebSocket API when `HA_URL` / `HA_TOKEN` are set, so the dashboard
  is fully reproducible from a fresh checkout.
- `tools/ha_update_card_resource.py` rewrites the Lovelace JS resource
  URL to `/local/rain-warner-card.js?v=<sha>` whenever the card file
  changes, so browsers reliably pick up new card versions instead of
  serving the cached copy until manual hard-reload. Helper is
  idempotent (no-op when the hash already matches) and called from
  `deploy.sh` automatically.
- `scripts/seed-dashboard-yaml.py` — one-shot helper used to bootstrap
  the YAML file from the live HA storage. Useful for future re-seeds.

### Changed

- The bundled dashboard no longer ships the RainViewer iframe. The
  Rain Warner Card's bar chart visualizes the same information at
  higher fidelity, so the duplicate map only added visual noise.
- The card's axis labels (jetzt / +1h / +2h / +6h) are now placed at
  the actual bar positions instead of evenly spaced. With the 6 h
  extension active that means '+2h' sits above bar 24 (≈33 % of the
  chart width) instead of bar 48, matching the visible RADVOR
  section.
- The extension half of the chart now has a subtle background band so
  users can see at a glance where RADVOR ends and the optical-flow
  extrapolation begins.

### Fixed

- The 'Regen ab' tile and `rain_starts_at` sensor no longer report a
  positive value while it's already raining. The question 'when does
  rain start?' is meaningless once it's already raining, so the
  sensor now returns Unknown in that case. `rain_ends_at` continues
  to be exposed.

## [0.4.1] - 2026-06-04 - Configurable restart recovery timeout

### Changed

- `deploy.sh` recovery timeout bumped from 180 s to 300 s by default,
  and now overridable via `HA_RECOVERY_TIMEOUT_S` in `.env`. Hosts
  with lots of integrations legitimately need longer than 3 min to
  fully boot.

## [0.4.0] - 2026-06-04 - Absolute clock times + deploy polish

### Added

- New `rain_starts_at` and `rain_ends_at` timestamp sensors that show
  the absolute clock time when rain begins or stops, so users don't
  have to mentally add minutes to the current time. `rain_ends_at`
  also incorporates the optical-flow extrapolation, capped at 6 h.
- The Lovelace card now uses these timestamps in its status banner:
  "Es regnet jetzt (0.2 mm/h), endet um 18:42" instead of "endet in
  250 min". Falls back to the relative duration when the timestamp
  sensors aren't configured.

### Changed

- `deploy.sh` now also syncs `dashboard/rain-warner-card.js` to
  `<config>/www/rain-warner-card.js` so the card and the integration
  stay in lock-step on every deploy.
- `deploy.sh --restart` now treats HTTP 502/503/504 from
  `homeassistant.restart` as "restart accepted" instead of failing.
  These are normal during a restart because HA shuts down before it
  can fully respond. After the restart call the script polls
  `/api/config` for up to 3 minutes until HA is back online.
- `deploy.sh` triggers a restart when *either* the integration code
  *or* the Lovelace card changed, not just code.

## [0.3.0] - 2026-06-04 - Optional pysteps engine

### Added

- Optional `pysteps` nowcast engine (`nowcast_pysteps.py`) wrapping
  Lucas-Kanade optical flow + S-PROG cascade decomposition with AR(2)
  lifecycle modelling. Selectable in the config flow; falls back to
  the stdlib simple engine when `pysteps` cannot be imported or fails
  at runtime, so behaviour is never worse than the baseline.
- New `nowcast_engine` config option (`simple` default, `pysteps` opt-in).
- pysteps stays out of `manifest.json` requirements — power users
  install it manually with `pip install pysteps` in their HA Python
  environment, keeping the integration lightweight on Pi-class
  hardware.
- German and English translations for the new engine selector and
  install hint.
- Documentation block in README explaining both engines, their
  trade-offs and the manual install path for pysteps.

## [0.2.0] - 2026-06-04 - Roadmap completion: optical flow, global coverage, types, stats and Lovelace card

### Added

- Custom Lovelace card (`dashboard/rain-warner-card.js`) — a single
  vanilla-JS file (no build step) that visualizes the integration's
  full nowcast in one card: status banner, 2 h precipitation bar
  chart, optional 6 h extended-forecast tail (greyed out), current
  type, temperature and today's accumulated rain.
- The `binary_sensor.rain_expected` entity now exposes `forecast` and
  `forecast_extended` as attributes so cards can render the bar chart
  without extra calls.
- Persistent rain statistics (`stats.py`) accumulated across HA
  restarts via the HA Storage helper:
  - `precipitation_today` / `precipitation_yesterday` (mm)
  - `dry_streak` (hours since the last rain >= 0.1 mm/h)
  - `last_rain_at` (timestamp)
  - 30-day daily-total ring buffer exposed as an attribute for
    sparkline cards.
- The accumulator clamps unusually long gaps between updates (e.g. an
  HA restart) to a single 5-min interval so totals never spike from
  bookkeeping anomalies.
- New `precipitation_type` sensor classifying the current precipitation
  as one of `none`, `rain`, `sleet`, `freezing_rain`, `snow`,
  `hail_likely`, or `unknown`. Uses radar intensity plus 2 m air
  temperature (NOAA/DWD-style thresholds at −1 / 0.5 / 1.5 °C).
- Air-temperature provider with 30 min cache that fills in temperature
  for the DWD and Bright Sky data sources via Open-Meteo, so the
  classifier works regardless of which radar backend is selected.
- German and English translations for the new sensor states.
- Open-Meteo data source for global coverage outside Germany
  (`open_meteo.py`). Fulfills the "RainViewer fallback" roadmap item:
  RainViewer only serves rendered tiles, Open-Meteo gives us numeric
  precipitation values world-wide with no API key.
- New `auto` data source mode (now the default) — picks DWD inside the
  DE1200 coverage bounding box and falls back to Open-Meteo elsewhere.
- Custom optical-flow nowcasting (`nowcast.py`) extending the RADVOR
  forecast beyond the 2 h DWD horizon up to 6 h. Estimates a global
  motion vector via cross-correlation on a sub-window around the user's
  location and advects the latest known frame semi-Lagrangian for
  synthetic frames at t+125 … t+360 in 5-min steps.
- Coordinator now exposes the extended forecast dict and motion metadata
  (speed in km/h, dr/dc per minute) for diagnostics.
- Coordinator now passes through air temperature (`temperature_c`) when
  the data source provides it.

### Changed

- Default data source switched from `dwd` to `auto`. Existing
  installations are unaffected; the change only takes effect for new
  config entries.
- Replaced the centroid + trailing-edge heuristic for rain-end
  extrapolation with the proper optical-flow advection pipeline. Same
  6 h cap, but more accurate when the rain field has internal
  structure (not just a single blob).

## [0.1.0] - 2026-06-04

### Added

- Full RADOLAN binary radar composite parsing (no external deps)
- DWD polar stereographic projection for accurate coordinate mapping
- RADVOR 2h nowcast integration (25 frames: t+0 through t+120 in 5-min steps)
- Area averaging over configurable radius (box filter)
- Rain end extrapolation beyond 2h window via centroid tracking + trailing edge measurement
- HACS integration with UI config flow (location, data source, radius)
- Sensors: current precipitation, intensity, rain start/end timing, max/total forecasts
- Binary sensors: is raining, rain expected (with forecast attributes)
- Rain end sensor shows extrapolated estimate when rain extends beyond 2h forecast
- Bright Sky API client as alternative JSON-based data source
- Dashboard with RainViewer radar map, sensor tiles, and history graphs
- Local test suite (unit tests + live DWD download tests, no HA dependency)
- Deploy script with rsync (SMB-compatible) + optional HA restart
- Dashboard push tool via WebSocket API
- German and English translations
- Automation examples in README
