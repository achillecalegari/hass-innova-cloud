"""Plain data models shared by the client and the Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class HvacMode(IntEnum):
    UNSPECIFIED = 0
    AUTO = 1
    HEAT = 2
    COOL = 3
    DRY = 4
    FAN = 5


class FanSpeed(IntEnum):
    UNSPECIFIED = 0
    AUTO = 1
    MIN = 2
    MID = 3
    MAX = 4
    BOOST = 5


class OperationModeType(IntEnum):
    UNSPECIFIED = 0
    CALENDAR = 1
    MANUAL = 2
    ANTIFREEZE = 3


class CalendarPreset(IntEnum):
    UNSPECIFIED = 0
    NIGHT = 1
    ECO = 2
    COMFORT = 3
    AWAY = 4
    FREEZE = 5


class NodeError(IntEnum):
    UNSPECIFIED = 0
    OFFLINE = 1
    CACHE_NOT_READY = 2
    INTERNAL = 3


class ResponseErrorCode(IntEnum):
    UNSPECIFIED = 0
    RESPONSE_TIMEOUT = 1
    CACHE_NOT_READY = 2


DEVICE_KIND_AC = "ac"
DEVICE_KIND_FANCOIL = "fancoil"
DEVICE_KIND_THERMOSTAT = "thermostat"
DEVICE_KIND_HEATPUMP = "heatpump"
DEVICE_KIND_BUTLER = "butler"
DEVICE_KIND_UNKNOWN = "unknown"

CLIMATE_KINDS = (DEVICE_KIND_AC, DEVICE_KIND_FANCOIL, DEVICE_KIND_THERMOSTAT)


def mac_to_bytes(mac: str) -> bytes:
    return bytes.fromhex(mac.replace(":", "").replace("-", ""))


def mac_to_str(raw: bytes) -> str:
    return ":".join(f"{b:02X}" for b in raw)


def uuid_to_bytes(value: str) -> bytes:
    return bytes.fromhex(value.replace("-", ""))


@dataclass
class DeviceInfo:
    """A device as listed by the REST API (``GET /app/homes``)."""

    home_id: str
    mac: str
    node_id: int
    name: str
    vendor_id: int | None
    product_id: int | None
    hw_revision: int | None
    serial_number: str | None
    room_id: str | None
    room_name: str | None

    @property
    def key(self) -> str:
        return f"{self.mac}/{self.node_id}"


@dataclass
class HomeInfo:
    id: str
    name: str
    timezone: str | None
    devices: list[DeviceInfo] = field(default_factory=list)


@dataclass
class Setpoint:
    value: float | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None

    def merge(self, other: "Setpoint") -> None:
        for name in ("value", "min", "max", "step"):
            new = getattr(other, name)
            if new is not None:
                setattr(self, name, new)


@dataclass
class OperationMode:
    active: OperationModeType | None = None
    manual_enabled: bool | None = None
    manual_until_minutes: int | None = None
    calendar_preset: CalendarPreset | None = None
    antifreeze_enabled: bool | None = None
    antifreeze_threshold: float | None = None

    def merge(self, other: "OperationMode") -> None:
        for name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            new = getattr(other, name)
            if new is not None:
                setattr(self, name, new)


@dataclass
class GatewayState:
    firmware_version_code: int | None = None
    serial_number: str | None = None
    wifi_ssid: str | None = None
    wifi_rssi: int | None = None
    wifi_snr: int | None = None
    alarms: list[int] = field(default_factory=list)


@dataclass
class DeviceState:
    """Runtime state of one node (AC, fan coil, thermostat...)."""

    kind: str = DEVICE_KIND_UNKNOWN
    online: bool = True
    node_error: NodeError | None = None
    alarms: int | None = None
    power: bool | None = None
    setpoint: Setpoint = field(default_factory=Setpoint)
    hvac_mode: HvacMode | None = None
    hvac_actual: HvacMode | None = None
    hvac_capabilities: list[HvacMode] = field(default_factory=list)
    fan_speed: FanSpeed | None = None
    fan_capabilities: list[FanSpeed] = field(default_factory=list)
    flap_swing: bool | None = None
    air_temperature: float | None = None
    air_humidity: float | None = None
    erv: bool | None = None
    silent_mode: bool | None = None
    operation_mode: OperationMode = field(default_factory=OperationMode)
    has_flap_swing: bool = False
    has_erv: bool = False
    has_silent_mode: bool = False
    has_humidity: bool = False
    gateway: GatewayState = field(default_factory=GatewayState)
    last_raw: dict | None = None

    def apply_event(self, patch: "DeviceState") -> None:
        """Merge a partial update (an ``Event``) into the full state."""
        for name in (
            "alarms",
            "power",
            "hvac_mode",
            "hvac_actual",
            "fan_speed",
            "flap_swing",
            "air_temperature",
            "air_humidity",
            "erv",
            "silent_mode",
            "node_error",
        ):
            new = getattr(patch, name)
            if new is not None:
                setattr(self, name, new)
        if patch.hvac_capabilities:
            self.hvac_capabilities = patch.hvac_capabilities
        if patch.fan_capabilities:
            self.fan_capabilities = patch.fan_capabilities
        self.setpoint.merge(patch.setpoint)
        self.operation_mode.merge(patch.operation_mode)
        for flag in ("has_flap_swing", "has_erv", "has_silent_mode", "has_humidity"):
            if getattr(patch, flag):
                setattr(self, flag, True)
        if patch.kind != DEVICE_KIND_UNKNOWN:
            self.kind = patch.kind
        if patch.last_raw is not None:
            self.last_raw = patch.last_raw
