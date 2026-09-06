"""Selects for heat pumps: silent level and load priority (from the app schema, untested on hardware)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaApiError, messages
from .api.models import DEVICE_KIND_HEATPUMP, LoadType, SilentLevel
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity, async_setup_discovery

_SILENT_OPTIONS = {SilentLevel.LEVEL_OFF: "off", SilentLevel.LEVEL_AUTO: "auto", SilentLevel.LEVEL_1: "level_1", SilentLevel.LEVEL_2: "level_2", SilentLevel.LEVEL_3: "level_3", SilentLevel.LEVEL_4: "level_4"}
_LOAD_OPTIONS = {LoadType.LOAD_TYPE_DHW: "dhw", LoadType.LOAD_TYPE_ZONE: "zone"}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data

    def _factory(device, state):
        if state.kind != DEVICE_KIND_HEATPUMP or state.heatpump is None:
            return
        if state.heatpump.silent_level is not None:
            yield "silent_level", InnovaHeatPumpSelect(coordinator, device, "silent_level")
        if state.heatpump.load_priority is not None:
            yield "load_priority", InnovaHeatPumpSelect(coordinator, device, "load_priority")

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)


class InnovaHeatPumpSelect(InnovaEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: InnovaCoordinator, device, feature: str) -> None:
        super().__init__(coordinator, device)
        self._feature = feature
        self._attr_translation_key = feature
        self._attr_unique_id = f"{device.key}-{feature}"

    @property
    def options(self) -> list[str]:
        state = self.device_state
        if self._feature == "silent_level":
            caps = state.heatpump.silent_capabilities if state and state.heatpump and state.heatpump.silent_capabilities else list(_SILENT_OPTIONS)
            return [_SILENT_OPTIONS[c] for c in caps if c in _SILENT_OPTIONS]
        return list(_LOAD_OPTIONS.values())

    @property
    def current_option(self) -> str | None:
        state = self.device_state
        if not state or not state.heatpump:
            return None
        if self._feature == "silent_level":
            return _SILENT_OPTIONS.get(state.heatpump.silent_level)
        return _LOAD_OPTIONS.get(state.heatpump.load_priority)

    async def async_select_option(self, option: str) -> None:
        if self._feature == "silent_level":
            value = next(k for k, v in _SILENT_OPTIONS.items() if v == option)
            request = messages.request_heatpump_set_state(silent_level=value)
        else:
            value = next(k for k, v in _LOAD_OPTIONS.items() if v == option)
            request = messages.request_heatpump_set_state(load_priority=value)
        try:
            await self.coordinator.async_send_request(self._key, request)
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
        state = self.device_state
        if state and state.heatpump:
            if self._feature == "silent_level":
                state.heatpump.silent_level = value
            else:
                state.heatpump.load_priority = value
            self.coordinator.notify_optimistic_update()
