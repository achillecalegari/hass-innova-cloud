"""Binary sensors: alarm (problem) per node."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.alarms import describe_alarms
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity, async_setup_discovery


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data

    def _factory(device, state):
        if state.alarms is not None:
            yield "alarm", InnovaAlarmSensor(coordinator, device)

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)


class InnovaAlarmSensor(InnovaEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "alarm"

    def __init__(self, coordinator: InnovaCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.key}-alarm"

    @property
    def is_on(self) -> bool | None:
        state = self.device_state
        if state is None or state.alarms is None:
            return None
        return state.alarms != 0

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        state = self.device_state
        if not state or state.alarms is None:
            return {}
        lang = (self.hass.config.language or "en").split("-")[0]
        return {"alarm_bitmask": state.alarms, "alarms": describe_alarms(state.kind, state.alarms, lang)}
