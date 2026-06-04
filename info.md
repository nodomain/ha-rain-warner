# Rain Warner 🌧️

High-precision rain radar integration for Home Assistant using DWD (Deutscher Wetterdienst) radar data.

## What it does

- **Real-time precipitation** at your exact location from DWD radar (1.1 km grid)
- **2-hour nowcast** in 5-minute steps using RADVOR extrapolation
- **Rain end estimation** beyond 2h via movement tracking and trailing edge extrapolation
- **No API key needed** — free DWD Open Data
- **No external dependencies** — pure Python stdlib parsing

## Sensors

| Sensor | Description |
|--------|-------------|
| Current precipitation | mm/h at your location |
| Rain starts/ends in | Minutes until change (extrapolates beyond 2h) |
| Max/Total precipitation | Peak rate and accumulated totals for 1h/2h |
| Raining / Rain expected | Binary sensors for automations |

## Data Source

Uses the DWD DE1200 radar composite — the same data that powers commercial weather apps in Germany, parsed directly from the binary RADOLAN format with proper polar stereographic projection.
