"""Sensors: temperature, humidity, Wi-Fi signal, alarms, firmware."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.models import DEVICE_KIND_HEATPUMP, DeviceState
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity, async_setup_discovery


@dataclass(frozen=True, kw_only=True)
class InnovaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[DeviceState], float | int | str | None]
    exists_fn: Callable[[DeviceState], bool] = lambda state: True


SENSORS: tuple[InnovaSensorDescription, ...] = (
    InnovaSensorDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda s: s.air_temperature,
        exists_fn=lambda s: s.kind != DEVICE_KIND_HEATPUMP,
    ),
    InnovaSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda s: s.air_temperature,
        exists_fn=lambda s: s.kind == DEVICE_KIND_HEATPUMP,
    ),
    InnovaSensorDescription(
        key="air_humidity",
        translation_key="air_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda s: s.air_humidity,
        exists_fn=lambda s: s.has_humidity,
    ),
    InnovaSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.gateway.wifi_rssi,
        exists_fn=lambda s: s.gateway.wifi_rssi is not None,
    ),
    InnovaSensorDescription(
        key="alarms",
        translation_key="alarms",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.alarms,
        exists_fn=lambda s: s.alarms is not None,
    ),
    InnovaSensorDescription(
        key="operation_mode",
        translation_key="operation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["calendar", "manual", "antifreeze", "unspecified"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.operation_mode.active.name.lower() if s.operation_mode.active is not None else None,
        exists_fn=lambda s: s.operation_mode.active is not None,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data

    def _factory(device, state):
        for description in SENSORS:
            if description.exists_fn(state):
                yield description.key, InnovaSensor(coordinator, device, description)

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)


class InnovaSensor(InnovaEntity, SensorEntity):
    entity_description: InnovaSensorDescription

    def __init__(self, coordinator: InnovaCoordinator, device, description: InnovaSensorDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device.key}-{description.key}"

    @property
    def native_value(self):
        state = self.device_state
        return self.entity_description.value_fn(state) if state else None
