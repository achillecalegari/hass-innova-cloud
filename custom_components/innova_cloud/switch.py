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
from .entity import InnovaEntity, async_setup_discovery


@dataclass(frozen=True, kw_only=True)
class InnovaSwitchDescription(SwitchEntityDescription):
    is_on_fn: Callable[[DeviceState], bool | None]
    exists_fn: Callable[[DeviceState], bool]
    request_fn: Callable[[DeviceInfo, DeviceState, bool], bytes]
    optimistic_fn: Callable[[DeviceState, bool], None]


def _set_manual(state: DeviceState, value: bool) -> None:
    # The device reports which mode wins (calendar / antifreeze) after a switch-off: only claim MANUAL.
    state.operation_mode.manual_enabled = value
    state.operation_mode.active = OperationModeType.MANUAL if value else None


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
        is_on_fn=lambda s: (s.operation_mode.active == OperationModeType.MANUAL) if s.operation_mode.active is not None else None,
        exists_fn=lambda s: s.kind in CLIMATE_KINDS and s.operation_mode.active is not None,
        request_fn=lambda d, s, v: messages.request_set_manual_mode(d.node_id, v),
        optimistic_fn=_set_manual,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: InnovaCoordinator = entry.runtime_data

    def _factory(device, state):
        for description in SWITCHES:
            if description.exists_fn(state):
                yield description.key, InnovaSwitch(coordinator, device, description)

    async_setup_discovery(entry, coordinator, async_add_entities, _factory)


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
        self.coordinator.notify_optimistic_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
