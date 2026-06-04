# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
