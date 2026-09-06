"""Base entity."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo as HaDeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import DeviceInfo, DeviceState
from .const import DOMAIN, MANUFACTURER
from .coordinator import InnovaCoordinator

_KIND_MODEL = {
    "ac": "Air conditioner",
    "fancoil": "Fan coil",
    "thermostat": "Thermostat",
    "heatpump": "Heat pump",
    "butler": "Butler gateway",
    "unknown": "Device",
}


@callback
def async_setup_discovery(
    entry: ConfigEntry,
    coordinator: InnovaCoordinator,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[DeviceInfo, DeviceState], Iterable[tuple[str, Entity]]],
) -> None:
    """Create entities lazily: a node's kind and capabilities are only known once its state arrives.

    ``factory`` returns (slot, entity) pairs for one device; each slot is created at most once.
    Runs now and again after every coordinator update until every slot exists.
    """
    known: set[tuple[str, str]] = set()

    @callback
    def _discover() -> None:
        new = []
        for key, device in coordinator.devices.items():
            state = coordinator.get_state(key)
            if state is None or state.kind == "unknown":
                continue
            for slot, entity in factory(device, state):
                if (key, slot) in known:
                    continue
                known.add((key, slot))
                new.append(entity)
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class InnovaEntity(CoordinatorEntity[InnovaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: InnovaCoordinator, device: DeviceInfo) -> None:
        super().__init__(coordinator)
        self._device = device
        self._key = device.key

    @property
    def device_state(self) -> DeviceState | None:
        return self.coordinator.get_state(self._key)

    @property
    def available(self) -> bool:
        state = self.device_state
        return super().available and state is not None and state.online

    @property
    def device_info(self) -> HaDeviceInfo:
        state = self.device_state
        kind = state.kind if state else "unknown"
        model = _KIND_MODEL.get(kind, "Device")
        if self._device.product_id is not None:
            model = f"{model} (product {self._device.vendor_id}.{self._device.product_id}.{self._device.hw_revision})"
        info = HaDeviceInfo(
            identifiers={(DOMAIN, self._key)},
            manufacturer=MANUFACTURER,
            model=model,
            name=self._device.name,
            serial_number=self._device.serial_number,
            suggested_area=self._device.room_name,
        )
        if self._device.node_id == 0:
            info["connections"] = {(CONNECTION_NETWORK_MAC, self._device.mac.lower())}
        if state and state.gateway.firmware_version_code is not None:
            info["sw_version"] = str(state.gateway.firmware_version_code)
        return info
