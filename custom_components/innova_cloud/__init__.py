"""Innova Cloud: control new-generation Innova air conditioners and fan coils through the
Solution Tech cloud used by the official Innova app."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InnovaApiError, InnovaGrpcClient, InnovaRestClient
from .api.rest import DEFAULT_GRPC_HOST, DEFAULT_REST_BASE
from .const import CONF_GRPC_HOST, CONF_REST_BASE, CONF_TOKEN, PLATFORMS
from .coordinator import InnovaCoordinator

_LOGGER = logging.getLogger(__name__)

type InnovaConfigEntry = ConfigEntry[InnovaCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: InnovaConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    rest = InnovaRestClient(session, token=entry.data.get(CONF_TOKEN), base_url=entry.data.get(CONF_REST_BASE, DEFAULT_REST_BASE))
    grpc_client = InnovaGrpcClient(lambda: rest.token, host=entry.data.get(CONF_GRPC_HOST, DEFAULT_GRPC_HOST))
    coordinator = InnovaCoordinator(hass, entry, rest, grpc_client)

    try:
        await coordinator.async_initialize()
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed:
        await coordinator.async_shutdown()
        raise
    except InnovaApiError as err:
        await coordinator.async_shutdown()
        raise ConfigEntryNotReady(str(err)) from err
    except Exception:
        # ConfigEntryNotReady from the first refresh, or anything unexpected: never leak the channel.
        await coordinator.async_shutdown()
        raise

    entry.runtime_data = coordinator
    coordinator.start_event_stream()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload only when the *options* change. The coordinator rewrites entry.data when it renews the
    # session token, and that must not reload the entry, so the listener compares options.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: InnovaConfigEntry) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data
    if coordinator.applied_options != dict(entry.options):
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: InnovaConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
