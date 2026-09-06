"""Switches: silent mode, ERV (air exchange), manual mode override."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import InnovaApiError, messages
from .api.models import CLIMATE_KINDS, DEVICE_KIND_AC, DeviceInfo, DeviceState, OperationModeType
from .coordinator import InnovaCoordinator
from .entity import InnovaEntity


@dataclass(frozen=True, kw_only=True)
class InnovaSwitchDescription(SwitchEntityDescription):
    is_on_fn: Callable[[DeviceState], bool | None]
    exists_fn: Callable[[DeviceState], bool]
    request_fn: Callable[[DeviceInfo, DeviceState, bool], bytes]
    optimistic_fn: Callable[[DeviceState, bool], None]


def _set_manual(state: DeviceState, value: bool) -> None:
    state.operation_mode.manual_enabled = value
    state.operation_mode.active = OperationModeType.MANUAL if value else OperationModeType.CALENDAR


SWITCHES: tuple[InnovaSwitchDescription, ...] = (
    InnovaSwitchDescription(
        key="silent_mode",
        translation_key="silent_mode",
        is_on_fn=lambda s: s.silent_mode,
        exists_fn=lambda s: s.kind == DEVICE_KIND_AC and s.has_silent_mode,
        request_fn=lambda d, s, v: messages.request_set_state(s.kind, silent_mode=v),
        optimistic_fn=lambda s, v: setattr(s, "silent_mode", v),
    ),
    InnovaSwitchDescription(
        key="erv",
        translation_key="erv",
        is_on_fn=lambda s: s.erv,
        exists_fn=lambda s: s.kind == DEVICE_KIND_AC and s.has_erv,
        request_fn=lambda d, s, v: messages.request_set_state(s.kind, erv=v),
        optimistic_fn=lambda s, v: setattr(s, "erv", v),
    ),
    InnovaSwitchDescription(
        key="manual_mode",
        translation_key="manual_mode",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda s: s.operation_mode.active == OperationModeType.MANUAL if s.operation_mode.active is not None else s.operation_mode.manual_enabled,
        exists_fn=lambda s: s.kind in CLIMATE_KINDS and s.operation_mode.active is not None,
        request_fn=lambda d, s, v: messages.request_set_manual_mode(d.node_id, v),
        optimistic_fn=_set_manual,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    def _discover() -> None:
        new = []
        for key, device in coordinator.devices.items():
            state = coordinator.get_state(key)
            if state is None:
                continue
            for description in SWITCHES:
                if (key, description.key) in known or not description.exists_fn(state):
                    continue
                known.add((key, description.key))
                new.append(InnovaSwitch(coordinator, device, description))
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class InnovaSwitch(InnovaEntity, SwitchEntity):
    entity_description: InnovaSwitchDescription

    def __init__(self, coordinator: InnovaCoordinator, device: DeviceInfo, description: InnovaSwitchDescription) -> None:
        super().__init__(coordinator, device)
        self.entity_description = description
        self._attr_unique_id = f"{device.key}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        state = self.device_state
        return self.entity_description.is_on_fn(state) if state else None

    async def _set(self, value: bool) -> None:
        state = self.device_state
        if state is None:
            raise HomeAssistantError("Device state unknown")
        try:
            await self.coordinator.async_send_request(self._key, self.entity_description.request_fn(self._device, state, value))
        except InnovaApiError as err:
            raise HomeAssistantError(f"Innova command failed: {err}") from err
        self.entity_description.optimistic_fn(state, value)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
