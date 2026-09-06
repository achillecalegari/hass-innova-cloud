"""Buttons: reboot the unit's Wi-Fi/control board (CloudMessage.Request.System.Reboot)."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaApiError, messages
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity, async_setup_discovery


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data

    def _factory(device, state):
        if device.node_id == 0:  # the gateway itself, not a sub-node behind a Butler
            yield "reboot", InnovaRebootButton(coordinator, device)

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)


class InnovaRebootButton(InnovaEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reboot"

    def __init__(self, coordinator: InnovaCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.key}-reboot"

    async def async_press(self) -> None:
        try:
            await self.coordinator.async_send_request(self._key, messages.request_system_reboot())
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
