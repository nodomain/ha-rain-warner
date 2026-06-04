"""Constants for Rain Warner."""

DOMAIN = "rain_warner"

# DWD Open Data endpoints
DWD_RADAR_BASE_URL = "https://opendata.dwd.de/weather/radar/composite/rv/"

# Bright Sky API (JSON wrapper for DWD data)
BRIGHT_SKY_BASE_URL = "https://api.brightsky.dev"

# Update interval in minutes
DEFAULT_UPDATE_INTERVAL = 5

# DWD grid parameters (DE1200 projection)
# The DE1200 grid covers Germany at 1.1km resolution
DE1200_ROWS = 1200
DE1200_COLS = 1100
DE1200_RESOLUTION_KM = 1.1

# Precipitation thresholds (mm/h)
PRECIP_THRESHOLD_LIGHT = 0.1
PRECIP_THRESHOLD_MODERATE = 2.5
PRECIP_THRESHOLD_HEAVY = 7.6
PRECIP_THRESHOLD_VIOLENT = 50.0

# Configuration keys
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS = "radius"
CONF_DATA_SOURCE = "data_source"
CONF_NOWCAST_ENGINE = "nowcast_engine"

# Data source options
DATA_SOURCE_DWD = "dwd"
DATA_SOURCE_BRIGHT_SKY = "bright_sky"
DATA_SOURCE_OPEN_METEO = "open_meteo"
DATA_SOURCE_AUTO = "auto"  # DWD when in coverage, else Open-Meteo

# Nowcast engine options for forecast extension beyond the 2 h DWD horizon.
#   simple : stdlib cross-correlation + semi-Lagrangian advection (default)
#   pysteps: Lucas-Kanade + S-PROG cascade decomposition with lifecycle
#            modelling. Requires `pip install pysteps` in the HA Python env.
NOWCAST_ENGINE_SIMPLE = "simple"
NOWCAST_ENGINE_PYSTEPS = "pysteps"
