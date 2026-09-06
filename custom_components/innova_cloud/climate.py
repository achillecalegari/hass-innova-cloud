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
from homeassistant.util import dt as dt_util
import voluptuous as vol

from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaApiError, messages
from .api.models import CLIMATE_KINDS, DEVICE_KIND_HEATPUMP, DeviceState, FanSpeed, HvacMode
from .const import ATTR_ALARMS, ATTR_ENABLED, ATTR_HOURS, SERVICE_SET_MANUAL_MODE, ATTR_CALENDAR_PRESET, ATTR_HVAC_ACTUAL, ATTR_MANUAL_UNTIL, ATTR_NODE_ID, ATTR_OPERATION_MODE
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity, async_setup_discovery

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

    def _factory(device, state):
        if state.kind in CLIMATE_KINDS:
            yield "climate", InnovaClimate(coordinator, device)
        elif state.kind == DEVICE_KIND_HEATPUMP and state.heatpump is not None:
            for zone in ("zone1", "zone2"):
                if getattr(state.heatpump, zone) is not None:
                    yield zone, InnovaHeatPumpZone(coordinator, device, zone)

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_MANUAL_MODE,
        {vol.Required(ATTR_ENABLED): cv.boolean, vol.Optional(ATTR_HOURS): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=168))},
        "async_set_manual_mode",
    )


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
        # AUTO without a reported actual mode: the unit does not say whether it heats or cools.
        return None

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
        # Optimistic update until the event / refresh arrives, pushed to every entity of the node.
        if state is not None:
            patch = DeviceState(kind=state.kind)
            for name, value in kwargs.items():
                if value is None:
                    continue
                if name == "temperature_setpoint":
                    patch.setpoint.value = value
                else:
                    setattr(patch, name, value)
            state.apply_event(patch)
            self.coordinator.notify_optimistic_update()

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
                mode = _HA_TO_HVAC.get(hvac_mode)
                if mode is None:
                    raise HomeAssistantError(f"Unsupported HVAC mode {hvac_mode}")
                payload["power"] = True
                payload["hvac_mode"] = mode
        if payload:
            await self._send(**payload)

    async def async_set_manual_mode(self, enabled: bool, hours: float | None = None) -> None:
        """Service: override the calendar (manual mode) for ``hours`` hours, or forever, or go back to the calendar."""
        until = None
        if enabled and hours:
            until = int(dt_util.utcnow().timestamp() // 60) + int(hours * 60)
        try:
            await self.coordinator.async_send_request(self._key, messages.request_set_manual_mode(self._device.node_id, enabled, until))
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        speed = _HA_TO_FAN.get(fan_mode)
        if speed is None:
            raise HomeAssistantError(f"Unsupported fan mode {fan_mode}")
        await self._send(fan_speed=speed)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._send(flap_swing=swing_mode == SWING_ON)


class InnovaHeatPumpZone(InnovaEntity, ClimateEntity):
    """One heating/cooling zone of a heat pump (from the app schema, untested on hardware).

    The heat pump has a single hvac mode (heat / cool / auto); each zone has its own power and its
    heating and cooling setpoints. The zone shows the setpoint of the active mode.
    """

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_target_temperature_step = 0.5
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
    _attr_min_temp = 5.0
    _attr_max_temp = 60.0

    def __init__(self, coordinator: InnovaCoordinator, device, zone: str) -> None:
        super().__init__(coordinator, device)
        self._zone = zone
        self._attr_translation_key = zone
        self._attr_unique_id = f"{device.key}-{zone}"

    @property
    def _zone_state(self):
        state = self.device_state
        return getattr(state.heatpump, self._zone) if state and state.heatpump else None

    @property
    def hvac_modes(self) -> list[HVACMode]:
        state = self.device_state
        caps = state.hvac_capabilities if state and state.hvac_capabilities else [HvacMode.HEAT, HvacMode.COOL, HvacMode.AUTO]
        modes = [HVACMode.OFF]
        for cap in caps:
            ha_mode = _HVAC_TO_HA.get(cap)
            if ha_mode and ha_mode not in modes:
                modes.append(ha_mode)
        return modes

    @property
    def hvac_mode(self) -> HVACMode | None:
        state = self.device_state
        zone = self._zone_state
        if state is None or zone is None:
            return None
        if not zone.power:
            return HVACMode.OFF
        return _HVAC_TO_HA.get(state.hvac_mode) if state.hvac_mode else None

    @property
    def current_temperature(self) -> float | None:
        zone = self._zone_state
        return zone.water_temperature if zone else None

    @property
    def target_temperature(self) -> float | None:
        state = self.device_state
        zone = self._zone_state
        if zone is None:
            return None
        if zone.current_setpoint is not None:
            return zone.current_setpoint
        if state and state.hvac_mode == HvacMode.COOL:
            return zone.cooling_setpoint
        return zone.heating_setpoint

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone_state
        state = self.device_state
        attrs: dict[str, Any] = {ATTR_NODE_ID: self._device.node_id}
        if zone:
            attrs["heating_setpoint"] = zone.heating_setpoint
            attrs["cooling_setpoint"] = zone.cooling_setpoint
            attrs["water_temperature"] = zone.water_temperature
        if state and state.heatpump:
            attrs["outdoor_temperature"] = state.heatpump.outdoor_temperature
            attrs["active_load"] = state.heatpump.active_load.name.lower() if state.heatpump.active_load else None
        return attrs

    async def _send(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.async_send_request(self._key, messages.request_heatpump_set_state(**kwargs))
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
        zone = self._zone_state
        state = self.device_state
        if zone is not None:
            if f"{self._zone}_power" in kwargs:
                zone.power = kwargs[f"{self._zone}_power"]
            if f"{self._zone}_heating_setpoint" in kwargs:
                zone.heating_setpoint = kwargs[f"{self._zone}_heating_setpoint"]
                zone.current_setpoint = zone.heating_setpoint
            if f"{self._zone}_cooling_setpoint" in kwargs:
                zone.cooling_setpoint = kwargs[f"{self._zone}_cooling_setpoint"]
                zone.current_setpoint = zone.cooling_setpoint
        if state is not None and "hvac_mode" in kwargs:
            state.hvac_mode = kwargs["hvac_mode"]
        self.coordinator.notify_optimistic_update()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._send(**{f"{self._zone}_power": False})
            return
        mode = _HA_TO_HVAC.get(hvac_mode)
        if mode is None:
            raise HomeAssistantError(f"Unsupported HVAC mode {hvac_mode}")
        await self._send(**{f"{self._zone}_power": True, "hvac_mode": mode})

    async def async_turn_on(self) -> None:
        await self._send(**{f"{self._zone}_power": True})

    async def async_turn_off(self) -> None:
        await self._send(**{f"{self._zone}_power": False})

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        state = self.device_state
        key = f"{self._zone}_cooling_setpoint" if state and state.hvac_mode == HvacMode.COOL else f"{self._zone}_heating_setpoint"
        await self._send(**{key: float(temperature)})
