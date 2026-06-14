"""WMS proxy for DWD radar tiles.

Serves DWD WMS tiles through Home Assistant's HTTP server, avoiding
browser CORS restrictions. Uses stdlib urllib (not aiohttp) for outbound
requests to guarantee clean headers without HA session interference.
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DWD_WMS_BASE = "https://maps.dwd.de/geoserver/dwd/wms"


class DWDWMSProxyView(HomeAssistantView):
    """Proxy view for DWD WMS tiles."""

    url = "/api/rain_warner/wms"
    name = "api:rain_warner:wms"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Proxy a WMS GetMap request to DWD."""
        params = dict(request.query)
        url = f"{DWD_WMS_BASE}?{urlencode(params)}"

        try:
            data, content_type = await self._hass.async_add_executor_job(_fetch_dwd_tile, url)
            if data is None:
                return web.Response(status=502)

            return web.Response(
                body=data,
                content_type=content_type,
                headers={"Cache-Control": "public, max-age=300"},
            )

        except Exception as err:
            _LOGGER.error("DWD WMS proxy error: %s", err)
            return web.Response(status=502, text=str(err))


def _fetch_dwd_tile(url: str) -> tuple[bytes | None, str]:
    """Fetch a tile from DWD using stdlib urllib (clean headers, no HA baggage)."""
    try:
        req = Request(url)
        with urlopen(req, timeout=15) as resp:
            if resp.status != 200:
                _LOGGER.warning("DWD WMS returned %d", resp.status)
                return None, "image/png"
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "image/png")
            # aiohttp's web.Response rejects charset in content_type arg —
            # strip it and pass only the MIME type.
            if ";" in content_type:
                content_type = content_type.split(";")[0].strip()
            return data, content_type
    except Exception as err:
        _LOGGER.warning("DWD WMS fetch failed: %s", err)
        return None, "image/png"


def async_register_proxy(hass: HomeAssistant) -> None:
    """Register the WMS proxy view."""
    hass.http.register_view(DWDWMSProxyView(hass))
