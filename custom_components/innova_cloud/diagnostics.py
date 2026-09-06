"""Diagnostics with secrets redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN

TO_REDACT = {CONF_TOKEN, CONF_PASSWORD, CONF_EMAIL, "mac", "serial_number", "wifi_ssid", "id", "home_id"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    devices = {key: asdict(dev) for key, dev in coordinator.devices.items()}
    states = {key: asdict(state) for key, state in (coordinator.data or {}).items()}
    return async_redact_data(
        {
            "entry": dict(entry.data),
            "stream_connected": coordinator.stream_connected,
            "devices": devices,
            "states": states,
        },
        TO_REDACT,
    )
