# Rain Warner 🌧️

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/nodomain/ha-rain-warner)](https://github.com/nodomain/ha-rain-warner/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nodomain&repository=ha-rain-warner&category=integration)

High-precision rain radar integration for Home Assistant. Uses DWD (Deutscher Wetterdienst) radar data to provide hyperlocal precipitation nowcasting with 1.1 km spatial and 5-minute temporal resolution.

## Features

- **Real-time precipitation** — Current rain intensity at your exact location from radar data
- **2-hour nowcast** — 5-minute resolution precipitation forecast using DWD RADVOR extrapolation
- **Custom 6-hour optical-flow extension** — Multi-pair TREC motion estimation with sub-pixel refinement extends the forecast beyond DWD's 2 h horizon
- **Smart rain end estimate** — Tracks rain field movement to predict when rain stops
- **Hyperlocal** — 1.1 km grid resolution via polar stereographic projection, not just the nearest weather station
- **Precipitation type detection** — Distinguishes rain, sleet, freezing rain, snow and likely hail using temperature
- **Alert sensors** — Rain imminent, severe weather, winter weather, and extended dry spell binary sensors for automations and push notifications
- **Persistent statistics** — Today/yesterday rainfall, dry streak, last rain timestamp and a 30-day history ring buffer
- **Camera entity** — Native HA camera showing a rendered radar crop around your location with motion arrow overlay
- **Interactive radar map** — Leaflet-based dark map with DWD WMS radar overlay, geo-scaled motion arrow showing 6 h rain field trajectory with hour ticks
- **Custom Lovelace card** — Vanilla-JS card with bar chart, status banner and 6 h tail
- **Multiple sensors** — Current rate, intensity class, type, rain start/end timing, totals, maximums, daily aggregates
- **Four data sources** — Auto (default), DWD raw radar, Bright Sky API, or Open-Meteo (global)
- **No API key needed** — All backends are free; DWD Open Data is unlimited
- **No external dependencies** — Pure Python stdlib parsing (no numpy/h5py/pysteps required)
- **Robust motion tracking** — Multi-pair averaged TREC estimation with parabolic sub-pixel interpolation and temporal EMA smoothing — the arrow doesn't jitter between updates

## Sensors

| Sensor | Type | Description |
|--------|------|-------------|
| Current precipitation | `sensor` | Current precipitation rate (mm/h) |
| Precipitation intensity | `sensor` | Classification: none / light / moderate / heavy / violent |
| Precipitation type | `sensor` | rain / sleet / freezing_rain / snow / hail_likely / unknown |
| Rain starts in | `sensor` | Minutes until rain begins (null if dry forecast) |
| Rain ends in | `sensor` | Minutes until rain stops — extrapolates beyond 2h via movement tracking |
| Rain starts at | `sensor` | Absolute clock time when rain is expected to start (timestamp) |
| Rain ends at | `sensor` | Absolute clock time when rain is expected to stop (timestamp) |
| Max precipitation (1h) | `sensor` | Peak precipitation rate in next 60 minutes |
| Max precipitation (2h) | `sensor` | Peak precipitation rate in next 120 minutes |
| Total precipitation (1h) | `sensor` | Accumulated precipitation in next 60 minutes (mm) |
| Total precipitation (2h) | `sensor` | Accumulated precipitation in next 120 minutes (mm) |
| Precipitation today | `sensor` | Accumulated precipitation since UTC midnight (mm) |
| Precipitation yesterday | `sensor` | Total precipitation on the previous UTC day (mm) |
| Dry streak | `sensor` | Hours since the last rain >= 0.1 mm/h |
| Last rain at | `sensor` | Timestamp of the most recent rainy update |
| Raining | `binary_sensor` | Whether it's currently raining |
| Rain expected | `binary_sensor` | Whether rain is expected in the next 2 hours |
| Rain imminent | `binary_sensor` | Rain expected within 30 minutes (alert trigger) |
| Severe weather | `binary_sensor` | Heavy/violent rain or hail expected |
| Winter weather | `binary_sensor` | Snow, sleet, or freezing rain detected |
| Extended dry spell | `binary_sensor` | No rain for 7+ days |
| Radar image | `camera` | Rendered radar crop with motion arrow overlay |

### Alert Sensors

The four alert binary sensors are designed for wall display notifications and push automations. Each carries relevant attributes (e.g., `rain_starts_in_minutes`, `max_precipitation_mm_h`, `precipitation_type`) so notification templates stay self-contained. Reference notification card YAML is included in `dashboard/notification-cards.yaml`.

### Rain End Sensor Details

The "Rain ends in" sensor uses a multi-tier approach:

| Situation | Display | Source |
|-----------|---------|--------|
| Rain stops within 2h | `45 min` | RADVOR nowcast (exact) |
| Rain stops soon after 2h | `150 min` | Extrapolated (confidence: medium) |
| Large front (>4h) | `320 min` | Extrapolated (confidence: low) |
| Massive front (>6h) | `>6h` | Capped estimate |
| Stationary / can't estimate | `>120` | Fallback |
| Not raining | — | Sensor shows unknown |

Extrapolation works by:
1. Tracking the rain field centroid across 25 radar frames to determine speed and direction
2. Measuring the trailing edge distance behind your location (opposite to movement direction)
3. Dividing distance by speed to estimate remaining duration

## Interactive Radar Map

The integration ships an interactive Leaflet map (`dashboard/rain-warner-map.html`) that renders inside an iframe card on any HA dashboard:

- **Dark basemap** (CartoDB Dark Matter) optimized for radar overlay visibility
- **DWD WMS radar layer** served through a same-origin proxy (no CORS issues, no API key)
- **Geo-scaled motion arrow** — a polyline placed on real geographic coordinates showing the rain field's 6-hour trajectory with:
  - Hour tick marks at the actual distance the front travels per hour
  - Timestamp labels showing when rain at that distance reaches you
  - Speed indicator positioned off to the side
  - Automatic label hiding at low zoom levels to prevent overlap
  - Redraws on zoom so it always matches the map scale
- **Location marker** at your configured coordinates
- **Auto-refresh** every 5 minutes + on tab focus

The motion arrow reads its data from the `camera.radarbild` entity attributes (`motion_dr_per_min`, `motion_dc_per_min`, `motion_speed_kmh`), which the coordinator populates from the multi-pair TREC estimator.

## Camera Entity

The `camera.radarbild` entity provides a rendered PNG of the local radar field:

- Cropped to a configurable radius around your location
- Color-coded precipitation intensity (blue → green → yellow → red → purple)
- Motion arrow overlay showing rain field direction
- 300-second frame interval (matches the radar update cadence)
- Attributes expose motion vector data for the interactive map

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant
2. Click "Integrations"
3. Click the three dots menu → "Custom repositories"
4. Add `https://github.com/nodomain/ha-rain-warner` with category "Integration"
5. Search for "Rain Warner" and install
6. Restart Home Assistant
7. Go to Settings → Integrations → Add Integration → "Rain Warner"

### Manual

1. Copy `custom_components/rain_warner` to your `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Integrations → Add Integration → "Rain Warner"

## Configuration

During setup you can configure:

- **Location** — Defaults to your HA home coordinates
- **Data Source** — Auto (recommended), DWD Radar, Bright Sky, or Open-Meteo
- **Radius** — Monitoring area around your location (1-50 km)
- **Nowcast Engine** — Simple (default, stdlib) or pysteps (advanced, opt-in)

## Data Sources

The integration ships four data source modes; pick one in the config flow.

### Auto (default)

Picks **DWD Radar** when your location is inside the DE1200 coverage box
(Germany + ~150 km of border regions) and **Open-Meteo** elsewhere. The
recommended default for most users.

### DWD Radar (Germany, highest precision)

Uses raw DWD RADOLAN/RADVOR radar composites:
- **Resolution**: 1.1 km × 1.1 km grid (polar stereographic projection)
- **Update interval**: Every 5 minutes
- **Forecast**: 2 hours from RADVOR + up to 6 h from custom optical-flow extension
- **Coverage**: Germany + border regions (~150 km beyond borders)
- **Cost**: Free (DWD Open Data, no API key)
- **Format**: Binary RADOLAN (parsed with stdlib, no external deps)

### Bright Sky API (Germany)

JSON wrapper around DWD data:
- **Resolution**: ~1 km (same underlying DWD data)
- **Update interval**: Every 5 minutes
- **Forecast**: Current weather + precipitation
- **Coverage**: Germany
- **Cost**: Free

### Open-Meteo (global)

Fulfills the "RainViewer fallback" use case for non-German locations:
- **Resolution**: 15-minute precipitation forecast (resampled to 5-min buckets)
- **Update interval**: Every 5 minutes
- **Forecast**: 6 hours
- **Coverage**: Worldwide
- **Cost**: Free, no API key

## Automation Examples

### Close awning when rain approaches

```yaml
automation:
  - alias: "Close awning before rain"
    triggers:
      - trigger: state
        entity_id: binary_sensor.rain_warner_rain_imminent
        to: "on"
    actions:
      - action: cover.close_cover
        target:
          entity_id: cover.awning
```

### Send notification when rain starts

```yaml
automation:
  - alias: "Rain notification"
    triggers:
      - trigger: state
        entity_id: binary_sensor.rain_warner_raining
        to: "on"
    actions:
      - action: notify.mobile_app
        data:
          title: "🌧️ It's raining!"
          message: >
            Precipitation: {{ states('sensor.rain_warner_current_precipitation') }} mm/h
            ({{ states('sensor.rain_warner_precipitation_intensity') }})
```

### Severe weather push alert

```yaml
automation:
  - alias: "Severe weather alert"
    triggers:
      - trigger: state
        entity_id: binary_sensor.rain_warner_severe_weather
        to: "on"
    actions:
      - action: notify.mobile_app
        data:
          title: "⛈️ Severe weather!"
          message: >
            {% set rate = state_attr('binary_sensor.rain_warner_severe_weather', 'max_precipitation_mm_h') %}
            {% set ptype = state_attr('binary_sensor.rain_warner_severe_weather', 'precipitation_type') %}
            Expected: {{ rate }} mm/h ({{ ptype }})
          data:
            priority: high
```

### Activate irrigation only if no rain expected

```yaml
automation:
  - alias: "Smart irrigation"
    triggers:
      - trigger: time
        at: "06:00:00"
    conditions:
      - condition: numeric_state
        entity_id: sensor.rain_warner_total_precipitation_2h
        below: 2
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.irrigation
```

## Nowcast Engines

The forecast extension beyond DWD's 2 h RADVOR horizon (up to 6 h) is
produced by one of two engines, selectable in the config flow:

### Simple (default)

Multi-pair TREC cross-correlation + semi-Lagrangian advection. No extra
dependencies, runs comfortably on a Raspberry Pi 4.

The motion estimator:
1. Computes TREC vectors across several ~30 min frame pairs (not just one pair)
2. Applies parabolic sub-pixel refinement to get continuous direction
3. Rejects vectors that rail at the search boundary (unreliable)
4. Averages surviving pairs with outlier rejection (median-magnitude filter)
5. Smooths the result across updates with an EMA (α=0.4) for temporal continuity

Best for frontal weather; less accurate for rotating convective storms.

### pysteps (advanced, opt-in)

Wraps the [pysteps](https://pysteps.github.io/) library for
state-of-the-art radar nowcasting:

- **Lucas-Kanade per-pixel optical flow** — captures rotation,
  divergence and locally varying winds instead of one global vector.
- **Cascade decomposition** — separates large-scale fronts from
  small-scale cells and predicts them with different decay rates,
  staying accurate at 1–3 h where simple advection has degraded.
- **S-PROG lifecycle modelling** — AR(2) autoregression so cells can
  grow, intensify, weaken and dissipate.

**Hardware requirement.** pysteps pulls in numpy + scipy and is
heavyweight on Pi-class hardware. Recommended for x86 / Intel NUC
class HA hosts.

**Installation.** pysteps is *not* listed as a manifest requirement to
keep the integration lightweight by default. The integration installs
it on demand the first time you pick "pysteps" in the config flow:

- **HA OS / Supervised / Container:** nothing to do. When you select
  the pysteps engine, the integration calls Home Assistant's built-in
  `async_process_requirements` API and HA installs pysteps into its
  managed Python environment automatically. The first install takes
  30–60 s on x86 (numpy + scipy + opencv wheels download). Subsequent
  restarts reuse the installed package.
- **HA Core (manual venv):** the auto-install also works, or you can
  pre-install: `source /srv/homeassistant/bin/activate && pip install pysteps`

If the auto-install fails (e.g. missing wheel for an unusual
architecture), the wrapper falls back to the simple engine and logs a
warning — your sensors keep working. Check
*Settings → System → Logs* and filter for `rain_warner` to see what
happened.

**Known incompatibility.** As of mid-2026 pysteps does not ship
musllinux wheels for Python 3.14 (the interpreter used by current HA
OS releases), and HA OS mounts `/tmp` with `noexec` so source builds
fail when Cython tries to load its compiled `.so` files. If your HA OS
host runs Python 3.14, the auto-install will fail until pysteps
publishes 3.14 musllinux wheels — stick with the simple engine on this
platform. The integration remembers a failed install and skips the
30 s retry on every subsequent boot; re-submit the Configure dialog to
ask it to try again (e.g. after a HA OS or pysteps update).

To switch engines later: *Settings → Devices & Services → Rain Warner → Configure*
and pick a different engine.

## Technical Details

### DWD Radar Composite (DE1200)

The DWD publishes 5-minute radar composites as `DE1200_RV_LATEST.tar.bz2`:
- **Archive contents**: 25 RADOLAN binary files (`_000` to `_120` in 5-min steps)
- **Grid**: 1200 rows × 1100 columns = 1,320,000 pixels
- **Cell size**: 1.1 km × 1.1 km
- **File format**: ASCII header (~195 bytes, ending with ETX `0x03`) + uint16 LE binary data
- **Value encoding**: Bits 0-11 = precipitation, Bit 13 = clutter flag, Bit 14 = no-data flag
- **Precision**: Header field `PR E-02` → values in 0.01 mm/5min → multiply by 12 for mm/h

### Polar Stereographic Projection

The DE1200 grid uses a polar stereographic projection with these parameters:
- **Earth radius**: 6370.04 km (DWD-specific)
- **Standard parallel**: 60°N
- **Central meridian**: 10°E
- **Grid origin** (lower-left corner of cell [0,0]): x=-523.462 km, y=-4808.645 km

This gives sub-km accuracy when mapping GPS coordinates to grid cells.

### Motion Estimation (TREC)

The simple engine uses a TREC-based (Tracking Radar Echoes by Correlation) approach:
1. **Multi-pair estimation** — Instead of one frame pair, estimates motion from many overlapping ~30 min pairs across the full 2 h window
2. **L1 block matching** — Brute-force minimum-L1 search over ±15 cell shifts on a decimated 300×300 sub-window
3. **Railing rejection** — Discards vectors where the minimum sits at the search boundary (the true shift exceeds the search range)
4. **Sub-pixel refinement** — Parabolic interpolation around the cost minimum yields continuous direction (not quantized to integer cells)
5. **Outlier rejection** — Pairs with magnitude >2.5× the median are dropped
6. **Temporal EMA** — A running exponential moving average (α=0.4) across 5-min updates smooths jitter while tracking genuine direction changes within ~15 min

### Precipitation Classification

| Intensity | Rate (mm/h) |
|-----------|-------------|
| None | 0.0 |
| Light | 0.1 – 2.5 |
| Moderate | 2.5 – 7.6 |
| Heavy | 7.6 – 50.0 |
| Violent | > 50.0 |

## Development

### Run Tests Locally

```bash
# All tests (requires network for live DWD download)
uv run pytest tests/ -v -s

# Unit tests only (no network required)
uv run pytest tests/ -v -k "not network"
```

### Deploy to Home Assistant

```bash
./deploy.sh              # Sync code + map + card to HA config mount
./deploy.sh --restart    # Sync + restart HA (~60s downtime)
./deploy.sh --force      # Force restart even if unchanged
```

## Roadmap

- [x] Full DWD RADOLAN binary radar composite parsing
- [x] RADVOR nowcast integration (2h forecast in 5-min steps)
- [x] Area averaging (configurable radius)
- [x] Polar stereographic coordinate projection
- [x] Dashboard with interactive radar map
- [x] Rain end extrapolation beyond 2h via movement tracking
- [x] Custom nowcasting with optical flow (stdlib, pysteps-inspired)
- [x] Optional pysteps engine for advanced 2–6 h nowcasting (Lucas-Kanade + S-PROG)
- [x] RainViewer / Open-Meteo fallback for non-German locations
- [x] Precipitation type detection (rain vs snow vs sleet vs hail)
- [x] Historical data / statistics (today, yesterday, dry streak, 30-day history)
- [x] Custom Lovelace card with precipitation graph
- [x] Native camera entity with rendered radar crop
- [x] Interactive Leaflet map with geo-scaled motion arrow (6 h projection)
- [x] DWD WMS proxy and XYZ tile server (same-origin, no CORS)
- [x] Alert binary sensors (imminent rain, severe weather, winter weather, dry spell)
- [x] Multi-pair TREC estimation with sub-pixel refinement and EMA smoothing
- [x] Walldisplay notification card templates

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [DWD Open Data](https://opendata.dwd.de/) for free radar data
- [Bright Sky](https://brightsky.dev/) for the excellent DWD API wrapper
- [RainViewer](https://www.rainviewer.com/) for the embedded radar map tiles
- [Leaflet](https://leafletjs.com/) for the interactive map framework
- [CartoDB](https://carto.com/basemaps/) for the dark basemap tiles
- Home Assistant community for inspiration and existing weather integrations
