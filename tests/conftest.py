"""Pytest conftest — mock Home Assistant modules for local testing."""

import sys
from unittest.mock import MagicMock

# Mock all homeassistant modules that our code imports.
# This allows running tests without installing homeassistant.
_MOCK_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.requirements",
    "homeassistant.components",
    "homeassistant.components.http",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.camera",
    "homeassistant.helpers.entity_platform",
    "aiohttp",
]

for mod_name in _MOCK_MODULES:
    sys.modules.setdefault(mod_name, MagicMock())
