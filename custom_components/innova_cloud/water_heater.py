"""Water heater entity for the domestic hot water of Innova heat pumps (from the app schema, untested on hardware)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import STATE_OFF, STATE_PERFORMANCE, WaterHeaterEntity, WaterHeaterEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, STATE_ON, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaApiError, messages
from .api.models import DEVICE_KIND_HEATPUMP
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity, async_setup_discovery


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data

    def _factory(device, state):
        if state.kind == DEVICE_KIND_HEATPUMP and state.heatpump is not None and state.heatpump.dhw is not None:
            yield "dhw", InnovaDhw(coordinator, device)

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)


class InnovaDhw(InnovaEntity, WaterHeaterEntity):
    _attr_translation_key = "dhw"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE | WaterHeaterEntityFeature.OPERATION_MODE | WaterHeaterEntityFeature.ON_OFF
    _attr_operation_list = [STATE_OFF, STATE_ON, STATE_PERFORMANCE]
    _attr_min_temp = 30.0
    _attr_max_temp = 65.0

    def __init__(self, coordinator: InnovaCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.key}-dhw"

    @property
    def _dhw(self):
        state = self.device_state
        return state.heatpump.dhw if state and state.heatpump else None

    @property
    def current_operation(self) -> str | None:
        dhw = self._dhw
        if dhw is None or dhw.power is None:
            return None
        if not dhw.power:
            return STATE_OFF
        return STATE_PERFORMANCE if dhw.boost_active else STATE_ON

    @property
    def current_temperature(self) -> float | None:
        dhw = self._dhw
        return dhw.water_temperature if dhw else None

    @property
    def target_temperature(self) -> float | None:
        dhw = self._dhw
        return dhw.setpoint if dhw else None

    async def _send(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_send_request(self._key, messages.request_heatpump_set_state(**kwargs))
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
        dhw = self._dhw
        if dhw is not None:
            if "dhw_power" in kwargs:
                dhw.power = kwargs["dhw_power"]
            if "dhw_setpoint" in kwargs:
                dhw.setpoint = kwargs["dhw_setpoint"]
            if "dhw_boost" in kwargs:
                dhw.boost_active = kwargs["dhw_boost"]
            self.coordinator.notify_optimistic_update()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self._send(dhw_setpoint=float(temperature))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == STATE_OFF:
            await self._send(dhw_power=False)
        elif operation_mode == STATE_PERFORMANCE:
            await self._send(dhw_power=True, dhw_boost=True)
        else:
            await self._send(dhw_power=True, dhw_boost=False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(dhw_power=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(dhw_power=False)
