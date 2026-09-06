"""Climate entity for Innova AC / fan coil / thermostat nodes."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
    SWING_OFF,
    SWING_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaApiError, messages
from .api.models import CLIMATE_KINDS, FanSpeed, HvacMode
from .const import ATTR_ALARMS, ATTR_CALENDAR_PRESET, ATTR_HVAC_ACTUAL, ATTR_MANUAL_UNTIL, ATTR_NODE_ID, ATTR_OPERATION_MODE
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity

_LOGGER = logging.getLogger(__name__)

FAN_BOOST = "boost"

_HVAC_TO_HA = {
    HvacMode.AUTO: HVACMode.HEAT_COOL,
    HvacMode.HEAT: HVACMode.HEAT,
    HvacMode.COOL: HVACMode.COOL,
    HvacMode.DRY: HVACMode.DRY,
    HvacMode.FAN: HVACMode.FAN_ONLY,
}
_HA_TO_HVAC = {value: key for key, value in _HVAC_TO_HA.items()}

_ACTION = {
    HvacMode.HEAT: HVACAction.HEATING,
    HvacMode.COOL: HVACAction.COOLING,
    HvacMode.DRY: HVACAction.DRYING,
    HvacMode.FAN: HVACAction.FAN,
}

_FAN_TO_HA = {
    FanSpeed.AUTO: FAN_AUTO,
    FanSpeed.MIN: FAN_LOW,
    FanSpeed.MID: FAN_MEDIUM,
    FanSpeed.MAX: FAN_HIGH,
    FanSpeed.BOOST: FAN_BOOST,
}
_HA_TO_FAN = {value: key for key, value in _FAN_TO_HA.items()}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data
    known: set[str] = set()

    def _discover() -> None:
        new = []
        for key, device in coordinator.devices.items():
            if key in known:
                continue
            state = coordinator.get_state(key)
            # Only create the climate entity once we know the node kind (AC / fan coil / thermostat).
            if state is None or state.kind not in CLIMATE_KINDS:
                continue
            known.add(key)
            new.append(InnovaClimate(coordinator, device))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class InnovaClimate(InnovaEntity, ClimateEntity):
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_translation_key = "innova"

    def __init__(self, coordinator: InnovaCoordinator, device) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.key}-climate"

    # ------------------------------------------------------------------ capabilities

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        state = self.device_state
        if state and (state.fan_speed is not None or state.fan_capabilities):
            features |= ClimateEntityFeature.FAN_MODE
        if state and state.has_flap_swing:
            features |= ClimateEntityFeature.SWING_MODE
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        state = self.device_state
        caps = state.hvac_capabilities if state and state.hvac_capabilities else list(_HVAC_TO_HA)
        modes = [HVACMode.OFF]
        for cap in caps:
            ha_mode = _HVAC_TO_HA.get(cap)
            if ha_mode and ha_mode not in modes:
                modes.append(ha_mode)
        return modes

    @property
    def fan_modes(self) -> list[str] | None:
        state = self.device_state
        if not state:
            return None
        caps = state.fan_capabilities or list(_FAN_TO_HA)
        return [_FAN_TO_HA[c] for c in caps if c in _FAN_TO_HA]

    @property
    def swing_modes(self) -> list[str] | None:
        state = self.device_state
        return [SWING_ON, SWING_OFF] if state and state.has_flap_swing else None

    # ------------------------------------------------------------------ state

    @property
    def hvac_mode(self) -> HVACMode | None:
        state = self.device_state
        if not state:
            return None
        if not state.power:
            return HVACMode.OFF
        return _HVAC_TO_HA.get(state.hvac_mode) if state.hvac_mode else None

    @property
    def hvac_action(self) -> HVACAction | None:
        state = self.device_state
        if not state:
            return None
        if not state.power:
            return HVACAction.OFF
        actual = state.hvac_actual if state.hvac_actual not in (None, HvacMode.UNSPECIFIED, HvacMode.AUTO) else state.hvac_mode
        if actual in _ACTION:
            return _ACTION[actual]
        return HVACAction.IDLE if actual == HvacMode.AUTO else None

    @property
    def fan_mode(self) -> str | None:
        state = self.device_state
        return _FAN_TO_HA.get(state.fan_speed) if state and state.fan_speed else None

    @property
    def swing_mode(self) -> str | None:
        state = self.device_state
        if not state or state.flap_swing is None:
            return None
        return SWING_ON if state.flap_swing else SWING_OFF

    @property
    def current_temperature(self) -> float | None:
        state = self.device_state
        return state.air_temperature if state else None

    @property
    def current_humidity(self) -> float | None:
        state = self.device_state
        return state.air_humidity if state and state.has_humidity else None

    @property
    def target_temperature(self) -> float | None:
        state = self.device_state
        return state.setpoint.value if state else None

    @property
    def target_temperature_step(self) -> float | None:
        state = self.device_state
        return state.setpoint.step or 0.5 if state else None

    @property
    def min_temp(self) -> float:
        state = self.device_state
        return state.setpoint.min if state and state.setpoint.min is not None else 16.0

    @property
    def max_temp(self) -> float:
        state = self.device_state
        return state.setpoint.max if state and state.setpoint.max is not None else 31.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.device_state
        if not state:
            return {}
        attrs: dict[str, Any] = {ATTR_NODE_ID: self._device.node_id}
        if state.operation_mode.active is not None:
            attrs[ATTR_OPERATION_MODE] = state.operation_mode.active.name.lower()
        if state.operation_mode.calendar_preset is not None:
            attrs[ATTR_CALENDAR_PRESET] = state.operation_mode.calendar_preset.name.lower()
        if state.operation_mode.manual_until_minutes:
            attrs[ATTR_MANUAL_UNTIL] = state.operation_mode.manual_until_minutes
        if state.hvac_actual is not None:
            attrs[ATTR_HVAC_ACTUAL] = state.hvac_actual.name.lower()
        if state.alarms is not None:
            attrs[ATTR_ALARMS] = state.alarms
        return attrs

    # ------------------------------------------------------------------ commands

    async def _send(self, **kwargs: Any) -> None:
        state = self.device_state
        kind = state.kind if state else "ac"
        try:
            await self.coordinator.async_send_request(self._key, messages.request_set_state(kind, **kwargs))
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
        # Optimistic update until the event / refresh arrives.
        if state is not None:
            for name, value in kwargs.items():
                if value is None:
                    continue
                if name == "temperature_setpoint":
                    state.setpoint.value = value
                elif hasattr(state, name):
                    setattr(state, name, value)
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._send(power=False)
            return
        mode = _HA_TO_HVAC.get(hvac_mode)
        if mode is None:
            raise HomeAssistantError(f"Unsupported HVAC mode {hvac_mode}")
        await self._send(power=True, hvac_mode=mode)

    async def async_turn_on(self) -> None:
        await self._send(power=True)

    async def async_turn_off(self) -> None:
        await self._send(power=False)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        payload: dict[str, Any] = {}
        if temperature is not None:
            payload["temperature_setpoint"] = float(temperature)
        if (hvac_mode := kwargs.get("hvac_mode")) is not None:
            if hvac_mode == HVACMode.OFF:
                payload["power"] = False
            else:
                payload["power"] = True
                payload["hvac_mode"] = _HA_TO_HVAC.get(hvac_mode)
        if payload:
            await self._send(**payload)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed = _HA_TO_FAN.get(fan_mode)
        if speed is None:
            raise HomeAssistantError(f"Unsupported fan mode {fan_mode}")
        await self._send(fan_speed=speed)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._send(flap_swing=swing_mode == SWING_ON)
