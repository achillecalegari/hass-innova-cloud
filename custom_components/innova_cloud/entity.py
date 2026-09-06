"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo as HaDeviceInfo
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
