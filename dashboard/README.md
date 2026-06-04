# Rain Warner Card

A custom Lovelace card for the Rain Warner integration with a precipitation
bar chart, status banner, current type and 6 h extended forecast tail.

## Installation

1. Copy `rain-warner-card.js` to `<config>/www/rain-warner-card.js`
   (one level above the `custom_components/` folder).
2. Add the file as a Lovelace resource:
   - Open Settings → Dashboards → Resources → ➕ Add Resource
   - URL: `/local/rain-warner-card.js`
   - Resource type: **JavaScript Module**
3. Add the card to a dashboard via the visual editor (search "Rain Warner Card")
   or in YAML:

```yaml
type: custom:rain-warner-card
title: Rain Warner
precipitation_entity: sensor.rain_warner_current_precipitation
forecast_entity: binary_sensor.rain_warner_rain_expected
type_entity: sensor.rain_warner_precipitation_type
rain_end_entity: sensor.rain_warner_rain_ends_in
rain_start_entity: sensor.rain_warner_rain_starts_in
today_entity: sensor.rain_warner_precipitation_today
```

All entity options are optional, but at least one of `precipitation_entity`
or `forecast_entity` is required.

## Configuration

| Key | Required | Description |
|-----|----------|-------------|
| `title` | optional | Card heading |
| `precipitation_entity` | one of these two | Current precipitation rate sensor |
| `forecast_entity` | one of these two | Rain expected binary sensor (carries the forecast attribute) |
| `type_entity` | optional | Precipitation type sensor (rain/snow/sleet/hail) |
| `rain_start_entity` | optional | Minutes-until-rain sensor |
| `rain_end_entity` | optional | Minutes-until-rain-ends sensor |
| `today_entity` | optional | Today's accumulated precipitation sensor |

## Visualization

- The colored status banner shows the most relevant nowcast headline
  (raining / rain in X min / dry).
- Each bar represents a 5-min slot in mm/h. The first 24 bars cover the
  next 2 hours from RADVOR; the dimmed bars after the divider are the
  optical-flow-extended forecast (up to 6 h).
- Bar colors follow the standard intensity classification (light → blue,
  violent → purple).

## No build step

The card is a single ~6 KB JavaScript file that registers a vanilla
`HTMLElement`. No bundlers, no Lit, no dependencies — open the file
to see how it works.
