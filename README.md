# Rain Warner 🌧️

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/nodomain/ha-rain-warner)](https://github.com/nodomain/ha-rain-warner/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nodomain&repository=ha-rain-warner&category=integration)

High-precision rain radar integration for Home Assistant. Uses DWD (Deutscher Wetterdienst) radar data to provide hyperlocal precipitation nowcasting with 1.1 km spatial and 5-minute temporal resolution.

## Features

- **Real-time precipitation** — Current rain intensity at your exact location from radar data
- **2-hour nowcast** — 5-minute resolution precipitation forecast using DWD RADVOR extrapolation
- **Custom 6-hour optical-flow extension** — Pysteps-inspired stdlib motion estimation extends the forecast beyond DWD's 2 h horizon
- **Smart rain end estimate** — Tracks rain field movement to predict when rain stops
- **Hyperlocal** — 1.1 km grid resolution via polar stereographic projection, not just the nearest weather station
- **Precipitation type detection** — Distinguishes rain, sleet, freezing rain, snow and likely hail using temperature
- **Persistent statistics** — Today/yesterday rainfall, dry streak, last rain timestamp and a 30-day history ring buffer
- **Multiple sensors** — Current rate, intensity class, type, rain start/end timing, totals, maximums, daily aggregates
- **Four data sources** — Auto (default), DWD raw radar, Bright Sky API, or Open-Meteo (global)
- **No API key needed** — All backends are free; DWD Open Data is unlimited
- **No external dependencies** — Pure Python stdlib parsing (no numpy/h5py/pysteps required)
- **Custom Lovelace card** — Vanilla-JS card with bar chart, status banner and 6 h tail
- **Dashboard included** — Interactive radar map (RainViewer) + sensor tiles + history

## Sensors

| Sensor | Type | Description |
|--------|------|-------------|
| Current precipitation | `sensor` | Current precipitation rate (mm/h) |
| Precipitation intensity | `sensor` | Classification: none / light / moderate / heavy / violent |
| Precipitation type | `sensor` | rain / sleet / freezing_rain / snow / hail_likely / unknown |
| Rain starts in | `sensor` | Minutes until rain begins (null if dry forecast) |
| Rain ends in | `sensor` | Minutes until rain stops — extrapolates beyond 2h via movement tracking |
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
- **Data Source** — DWD Radar (raw, highest precision) or Bright Sky (JSON API)
- **Radius** — Monitoring area around your location (1-50 km)

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
    trigger:
      - platform: state
        entity_id: binary_sensor.rain_warner_rain_expected
        to: "on"
    condition:
      - condition: numeric_state
        entity_id: sensor.rain_warner_rain_starts_in
        below: 15
    action:
      - service: cover.close_cover
        target:
          entity_id: cover.awning
```

### Send notification when rain starts

```yaml
automation:
  - alias: "Rain notification"
    trigger:
      - platform: state
        entity_id: binary_sensor.rain_warner_raining
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          title: "🌧️ It's raining!"
          message: >
            Precipitation: {{ state_attr('binary_sensor.rain_warner_raining', 'precipitation_mm_h') }} mm/h
            ({{ state_attr('binary_sensor.rain_warner_raining', 'intensity') }})
```

### Activate irrigation only if no rain expected

```yaml
automation:
  - alias: "Smart irrigation"
    trigger:
      - platform: time
        at: "06:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.rain_warner_total_precipitation_2h
        below: 2
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.irrigation
```

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

### RADVOR Nowcasting

DWD RADVOR provides extrapolation-based nowcasting — it takes the current radar image and projects precipitation movement forward using optical flow algorithms. A single archive download contains both the current observation and the full 2-hour forecast. Accuracy decreases with forecast time (best within 30 minutes).

### Rain End Extrapolation

When rain doesn't end within the 2h RADVOR window, the integration extrapolates:
1. **Centroid tracking**: Calculates the weighted centroid of the rain field (55 km radius) in the first and last frames to determine movement vector
2. **Speed calculation**: Derives rain field speed in cells/minute from centroid displacement
3. **Trailing edge scan**: Starting from the user's location, scans in the opposite direction of movement to find where the rain field ends (tolerating small gaps of up to 3 cells)
4. **Duration estimate**: `trailing_edge_distance / speed = extra_minutes` beyond the 2h window
5. **Capped at 6h**: Estimates beyond 360 minutes are shown as ">6h" due to high uncertainty

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
./deploy.sh              # Sync code to HA config mount
./deploy.sh --restart    # Sync + restart HA (~60s downtime)
./deploy.sh --force      # Force restart even if unchanged
```

## Nowcast Engines

The forecast extension beyond DWD's 2 h RADVOR horizon (up to 6 h) is
produced by one of two engines, selectable in the config flow:

### Simple (default)

Stdlib cross-correlation + semi-Lagrangian advection. No extra
dependencies, runs comfortably on a Raspberry Pi 4. Estimates a single
global motion vector for the rain field around your location. Best
for frontal weather; less accurate for rotating convective storms.

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
keep the integration lightweight by default. Install it manually:

```bash
# In your Home Assistant Python environment (Container/Core/Supervised)
pip install pysteps
```

Then pick "pysteps" in the integration's setup form. If pysteps
can't be imported at runtime, the integration logs a warning and
falls back to the simple engine — your sensors keep working.

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

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [DWD Open Data](https://opendata.dwd.de/) for free radar data
- [Bright Sky](https://brightsky.dev/) for the excellent DWD API wrapper
- [RainViewer](https://www.rainviewer.com/) for the embedded radar map
- Home Assistant community for inspiration and existing weather integrations
