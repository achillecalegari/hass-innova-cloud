"""Encoders and decoders for the Innova app gRPC messages.

Field numbers and types were recovered from the official app binary (SwiftProtobuf name maps
and Swift reflection metadata). See ``proto/innova_app.proto`` and ``docs/PROTOCOL.md``.

Service: ``services.app.AppService`` on ``v2.grpc.innova.solutiontech.tech:443``
  * ``SendDevice(SendDeviceRequest) -> DeviceMessage.Response`` (unary)
  * ``SubscribeEvents(SubscribeEventsRequest) -> stream Event``
"""

from __future__ import annotations

from .models import (
    ClimaticCurve,
    HeatPumpDhw,
    HeatPumpState,
    HeatPumpZone,
    LoadType,
    SilentLevel,
    DEVICE_KIND_AC,
    DEVICE_KIND_BUTLER,
    DEVICE_KIND_FANCOIL,
    DEVICE_KIND_HEATPUMP,
    DEVICE_KIND_THERMOSTAT,
    DEVICE_KIND_UNKNOWN,
    CalendarPreset,
    DeviceState,
    FanSpeed,
    GatewayState,
    HvacMode,
    NodeError,
    OperationMode,
    OperationModeType,
    ResponseErrorCode,
    Setpoint,
)
import logging

from .protobuf import Message, Writer

_LOGGER = logging.getLogger(__name__)


def _debug(msg: Message) -> dict | None:
    """Generic rendering of a payload, only when debug logging is on (it costs a second decode)."""
    return msg.to_debug() if _LOGGER.isEnabledFor(logging.DEBUG) else None

SERVICE = "services.app.AppService"
METHOD_SEND_DEVICE = f"/{SERVICE}/SendDevice"
METHOD_SUBSCRIBE_EVENTS = f"/{SERVICE}/SubscribeEvents"

# --------------------------------------------------------------------------------------
# Encoders
# --------------------------------------------------------------------------------------


def subscribe_events_request(home_id: bytes) -> bytes:
    """services.app.SubscribeEventsRequest { bytes home_id = 1; }"""
    return Writer().bytes(1, home_id).finish()


def send_device_request(mac: bytes, node_id: int, request: bytes) -> bytes:
    """services.app.SendDeviceRequest { bytes mac_address = 1; uint32 node_id = 2; CloudMessage.Request request = 3; }"""
    return Writer().bytes(1, mac).varint(2, node_id).message(3, request).finish()


# messages.CloudMessage.Request oneof type
_REQ_SYSTEM = 1
_REQ_SHARED = 2
_REQ_AC = 3
_REQ_BUTLER = 4
_REQ_FANCOIL = 5
_REQ_THERMOSTAT = 6
_REQ_HEATPUMP = 7

_KIND_TO_REQ = {
    DEVICE_KIND_AC: _REQ_AC,
    DEVICE_KIND_FANCOIL: _REQ_FANCOIL,
    DEVICE_KIND_THERMOSTAT: _REQ_THERMOSTAT,
}


def request_get_state() -> bytes:
    """CloudMessage.Request { shared = 2: shared.Request { get_state = 1: GetState {} } }"""
    shared = Writer().message(1, b"")
    return Writer().message(_REQ_SHARED, shared).finish()


def request_set_state(
    kind: str,
    *,
    power: bool | None = None,
    temperature_setpoint: float | None = None,
    hvac_mode: HvacMode | int | None = None,
    fan_speed: FanSpeed | int | None = None,
    flap_swing: bool | None = None,
    erv: bool | None = None,
    silent_mode: bool | None = None,
) -> bytes:
    """Build a ``SetState`` request for an AC, fan coil or thermostat node.

    ``ac.Request.SetState`` has: power=1, temperature_setpoint=2, hvac_mode=3, fan_speed=4,
    flap_swing=5, erv=6, silent_mode=7 (all proto3 ``optional``). Fan coil and thermostat share
    the first five fields.
    """
    if kind not in _KIND_TO_REQ:
        raise ValueError(f"set_state not supported for device kind {kind!r}")
    set_state = (
        Writer()
        .bool(1, power)
        .float32(2, temperature_setpoint)
        .varint(3, None if hvac_mode is None else int(hvac_mode))
        .varint(4, None if fan_speed is None else int(fan_speed))
        .bool(5, flap_swing)
    )
    if kind == DEVICE_KIND_AC:
        set_state.bool(6, erv).bool(7, silent_mode)
    device_request = Writer().message(1, set_state)  # oneof type { SetState set_state = 1; }
    return Writer().message(_KIND_TO_REQ[kind], device_request).finish()


def request_system_reboot() -> bytes:
    """CloudMessage.Request { system = 1: System { reboot = 1: Reboot {} } }"""
    return Writer().message(_REQ_SYSTEM, Writer().message(1, b"")).finish()


def request_heatpump_set_state(
    *,
    dhw_power: bool | None = None,
    dhw_setpoint: float | None = None,
    dhw_boost: bool | None = None,
    zone1_power: bool | None = None,
    zone1_heating_setpoint: float | None = None,
    zone1_cooling_setpoint: float | None = None,
    zone2_power: bool | None = None,
    zone2_heating_setpoint: float | None = None,
    zone2_cooling_setpoint: float | None = None,
    hvac_mode: HvacMode | int | None = None,
    silent_level: SilentLevel | int | None = None,
    load_priority: LoadType | int | None = None,
) -> bytes:
    """CloudMessage.Request { heatpump = 7: heatpump.Request { set_state = 1: SetState {...} } }

    ``SetState { Dhw dhw=1; Zone zone1=2; Zone zone2=3; HvacMode.Type hvac_mode=4; SilentMode.Level silent_mode=5; LoadType load_priority=6 }``
    ``Dhw { bool power=1; float setpoint=2; bool boost=3 }``  ``Zone { bool power=1; float heating_setpoint=2; float cooling_setpoint=3 }``
    Reconstructed from the app schema; not yet verified on real heat pump hardware.
    """
    set_state = Writer()
    if any(v is not None for v in (dhw_power, dhw_setpoint, dhw_boost)):
        set_state.message(1, Writer().bool(1, dhw_power).float32(2, dhw_setpoint).bool(3, dhw_boost))
    if any(v is not None for v in (zone1_power, zone1_heating_setpoint, zone1_cooling_setpoint)):
        set_state.message(2, Writer().bool(1, zone1_power).float32(2, zone1_heating_setpoint).float32(3, zone1_cooling_setpoint))
    if any(v is not None for v in (zone2_power, zone2_heating_setpoint, zone2_cooling_setpoint)):
        set_state.message(3, Writer().bool(1, zone2_power).float32(2, zone2_heating_setpoint).float32(3, zone2_cooling_setpoint))
    set_state.varint(4, None if hvac_mode is None else int(hvac_mode))
    set_state.varint(5, None if silent_level is None else int(silent_level))
    set_state.varint(6, None if load_priority is None else int(load_priority))
    device_request = Writer().message(1, set_state)
    return Writer().message(_REQ_HEATPUMP, device_request).finish()


def request_set_manual_mode(node_id: int, enabled: bool, until_minutes: int | None = None) -> bytes:
    """CloudMessage.Request { shared.Request { set_operation_mode = 3: { manual = 2: { nodes = 1 (map<uint32, Manual.Configuration>) } } } }

    ``Manual.Configuration { bool enabled = 1; shared.Timestamp until = 2; }`` where
    ``Timestamp { uint32 minutes = 1; uint32 seconds = 2; }``.
    """
    config = Writer().bool(1, enabled)
    if until_minutes is not None:
        config.message(2, Writer().varint(1, until_minutes).varint(2, 0))
    entry = Writer().varint(1, node_id).message(2, config)  # map entry key=1, value=2
    manual = Writer().message(1, entry)
    set_operation_mode = Writer().message(2, manual)
    shared = Writer().message(3, set_operation_mode)
    return Writer().message(_REQ_SHARED, shared).finish()


def request_set_antifreeze(node_id: int, enabled: bool, threshold: float | None = None) -> bytes:
    """Same shape as manual mode with ``antifreeze = 3`` and ``Antifreeze.Configuration { bool enabled = 1; float air_temperature_threshold = 2; }``."""
    config = Writer().bool(1, enabled).float32(2, threshold)
    entry = Writer().varint(1, node_id).message(2, config)
    antifreeze = Writer().message(1, entry)
    set_operation_mode = Writer().message(3, antifreeze)
    shared = Writer().message(3, set_operation_mode)
    return Writer().message(_REQ_SHARED, shared).finish()


# --------------------------------------------------------------------------------------
# Decoders: shared building blocks
# --------------------------------------------------------------------------------------


def _enum(cls, value: int | None):
    if value is None:
        return None
    try:
        return cls(value)
    except ValueError:
        return None


def _setpoint(msg: Message | None) -> Setpoint:
    """shared.setpoint.State/Event { float value = 1; float min = 2; float max = 3; float step = 4; }"""
    if msg is None:
        return Setpoint()
    return Setpoint(value=msg.float(1), min=msg.float(2), max=msg.float(3), step=msg.float(4))


def _operation_mode_state(msg: Message | None) -> OperationMode:
    """shared.operation_mode.State/Event { Type active = 1; Calendar.State calendar = 2; Manual.State manual = 3; Antifreeze.State antifreeze = 4; }"""
    out = OperationMode()
    if msg is None:
        return out
    out.active = _enum(OperationModeType, msg.int(1))
    calendar = msg.message(2)
    if calendar is not None:
        out.calendar_preset = _enum(CalendarPreset, calendar.int(1))
    manual = msg.message(3)
    if manual is not None:
        config = manual.message(1)
        if config is not None:
            out.manual_enabled = config.bool(1)
            until = config.message(2)
            if until is not None:
                out.manual_until_minutes = until.int(1)
    antifreeze = msg.message(4)
    if antifreeze is not None:
        config = antifreeze.message(1)
        if config is not None:
            out.antifreeze_enabled = config.bool(1)
            out.antifreeze_threshold = config.float(2)
    return out


def _gateway_state(msg: Message | None) -> GatewayState | None:
    """shared.gateway.State { repeated Alarm alarms = 1; uint32 firmware_version_code = 2; string serial_number = 3; Connection connection = 4; map interfaces = 5; }"""
    if msg is None:
        return None
    out = GatewayState()
    out.alarms = msg.varints(1) if msg.wires.get(1) != 2 or not msg.messages(1) else []
    out.firmware_version_code = msg.int(2)
    out.serial_number = msg.string(3)
    connection = msg.message(4)
    if connection is not None:
        wifi = connection.message(2)
        if wifi is not None:
            network = wifi.message(1)
            if network is not None:
                out.wifi_ssid = network.string(1)
                out.wifi_rssi = network.sint32(2)
                out.wifi_snr = network.int(3)
    return out


# --------------------------------------------------------------------------------------
# Decoders: full states (from SendDevice(get_state) responses)
# --------------------------------------------------------------------------------------


def parse_ac_state(msg: Message) -> DeviceState:
    """ac.State { uint32 alarms=1; bool power=2; Setpoint.State temperature_setpoint=3; HvacMode hvac_mode=4;
    FanSpeed fan_speed=5; bool flap_swing=6; float air_temperature=7; float air_humidity=8; bool erv=9;
    OperationMode.State operation_mode=10; bool silent_mode=11; }"""
    state = _parse_common_state(msg, DEVICE_KIND_AC)
    state.erv = msg.bool(9)
    state.has_erv = msg.has(9)
    state.operation_mode = _operation_mode_state(msg.message(10))
    state.silent_mode = msg.bool(11)
    state.has_silent_mode = msg.has(11)
    return state


def parse_fancoil_state(msg: Message) -> DeviceState:
    """fancoil.State / thermostat.State { alarms=1; power=2; temperature_setpoint=3; hvac_mode=4; fan_speed=5;
    flap_swing=6; air_temperature=7; air_humidity=8; operation_mode=9; }"""
    state = _parse_common_state(msg, DEVICE_KIND_FANCOIL)
    state.operation_mode = _operation_mode_state(msg.message(9))
    return state


def parse_thermostat_state(msg: Message) -> DeviceState:
    state = parse_fancoil_state(msg)
    state.kind = DEVICE_KIND_THERMOSTAT
    return state


def _parse_common_state(msg: Message, kind: str) -> DeviceState:
    state = DeviceState(kind=kind)
    state.alarms = msg.int(1, 0)
    state.power = msg.bool(2, False)
    state.setpoint = _setpoint(msg.message(3))
    hvac = msg.message(4)
    if hvac is not None:
        state.hvac_mode = _enum(HvacMode, hvac.int(1))
        state.hvac_actual = _enum(HvacMode, hvac.int(2))
        state.hvac_capabilities = [m for m in (_enum(HvacMode, v) for v in hvac.varints(3)) if m]
    fan = msg.message(5)
    if fan is not None:
        state.fan_speed = _enum(FanSpeed, fan.int(1))
        state.fan_capabilities = [f for f in (_enum(FanSpeed, v) for v in fan.varints(2)) if f]
    state.flap_swing = msg.bool(6)
    state.has_flap_swing = msg.has(6)
    state.air_temperature = msg.float(7)
    state.air_humidity = msg.float(8)
    state.has_humidity = msg.has(8)
    state.last_raw = _debug(msg)
    return state


def _hp_dhw(msg: Message | None) -> HeatPumpDhw | None:
    """heatpump.State.Dhw { bool power=1; float setpoint=2; float current_setpoint=3; float water_temperature=4; DhwBoost boost=5 }
    DhwBoost { State state=1 { uint32 duration_minutes=1; Timestamp activated_at=2 }; Capabilities capabilities=2 }"""
    if msg is None:
        return None
    dhw = HeatPumpDhw(power=msg.bool(1), setpoint=msg.float(2), current_setpoint=msg.float(3), water_temperature=msg.float(4))
    boost = msg.message(5)
    if boost is not None:
        state = boost.message(1)
        if state is not None:
            dhw.boost_minutes = state.int(1)
            dhw.boost_active = bool(state.int(1)) and state.has(2)
        else:
            dhw.boost_active = False
    return dhw


def _hp_zone(msg: Message | None) -> HeatPumpZone | None:
    """heatpump.State.Zone { bool power=1; float heating_setpoint=2; float cooling_setpoint=3; float current_setpoint=4; float water_temperature=5 }"""
    if msg is None:
        return None
    return HeatPumpZone(power=msg.bool(1), heating_setpoint=msg.float(2), cooling_setpoint=msg.float(3), current_setpoint=msg.float(4), water_temperature=msg.float(5))


def _hp_common(msg: Message, hp: HeatPumpState) -> None:
    hp.dhw = _hp_dhw(msg.message(2))
    hp.zone1 = _hp_zone(msg.message(3))
    hp.zone2 = _hp_zone(msg.message(4))
    hp.heating_curve = _enum(ClimaticCurve, msg.int(5))
    hp.cooling_curve = _enum(ClimaticCurve, msg.int(6))
    hp.active_load = _enum(LoadType, msg.int(8))
    hp.outdoor_temperature = msg.float(9)
    hp.water_pressure = msg.float(10)
    hp.load_priority = _enum(LoadType, msg.int(12))


def parse_heatpump_state(msg: Message) -> DeviceState:
    """heatpump.State { uint64 alarms=1; Dhw dhw=2; Zone zone1=3; Zone zone2=4; ClimaticCurve heating_curve=5; ClimaticCurve cooling_curve=6;
    HvacMode hvac_mode=7; LoadType active_load=8; float outdoor_temperature=9; float water_pressure=10; SilentMode silent_mode=11;
    LoadType load_priority=12; OperationMode.State operation_mode=13 }"""
    state = DeviceState(kind=DEVICE_KIND_HEATPUMP)
    state.alarms = msg.int(1, 0)
    hp = HeatPumpState()
    _hp_common(msg, hp)
    hvac = msg.message(7)
    if hvac is not None:
        state.hvac_mode = _enum(HvacMode, hvac.int(1))
        state.hvac_actual = _enum(HvacMode, hvac.int(2))
        state.hvac_capabilities = [m for m in (_enum(HvacMode, v) for v in hvac.varints(3)) if m]
    silent = msg.message(11)
    if silent is not None:
        hp.silent_level = _enum(SilentLevel, silent.int(1))
        hp.silent_capabilities = [l for l in (_enum(SilentLevel, v) for v in silent.varints(2)) if l]
    state.heatpump = hp
    state.air_temperature = hp.outdoor_temperature
    state.power = bool((hp.zone1 and hp.zone1.power) or (hp.zone2 and hp.zone2.power) or (hp.dhw and hp.dhw.power))
    state.operation_mode = _operation_mode_state(msg.message(13))
    state.last_raw = _debug(msg)
    return state


# --------------------------------------------------------------------------------------
# Decoders: partial events (from SubscribeEvents)
# --------------------------------------------------------------------------------------


def parse_ac_event(msg: Message) -> DeviceState:
    """ac.Event { alarms=1; power=2; Setpoint.Event temperature_setpoint=3; float air_temperature=4; HvacMode.Type hvac_mode=5;
    FanSpeed.Type fan_speed=6; bool flap_swing=7; bool erv=8; OperationMode.Event operation_mode=9; float air_humidity=10; bool silent_mode=11; }"""
    patch = _parse_common_event(msg, DEVICE_KIND_AC)
    patch.erv = msg.bool(8)
    patch.has_erv = msg.has(8)
    patch.operation_mode = _operation_mode_state(msg.message(9))
    patch.air_humidity = msg.float(10)
    patch.has_humidity = msg.has(10)
    patch.silent_mode = msg.bool(11)
    patch.has_silent_mode = msg.has(11)
    return patch


def parse_fancoil_event(msg: Message) -> DeviceState:
    """fancoil.Event / thermostat.Event { alarms=1; power=2; temperature_setpoint=3; air_temperature=4; hvac_mode=5;
    fan_speed=6; flap_swing=7; operation_mode=8; air_humidity=9; }"""
    patch = _parse_common_event(msg, DEVICE_KIND_FANCOIL)
    patch.operation_mode = _operation_mode_state(msg.message(8))
    patch.air_humidity = msg.float(9)
    patch.has_humidity = msg.has(9)
    return patch


def parse_thermostat_event(msg: Message) -> DeviceState:
    patch = parse_fancoil_event(msg)
    patch.kind = DEVICE_KIND_THERMOSTAT
    return patch


def _parse_common_event(msg: Message, kind: str) -> DeviceState:
    patch = DeviceState(kind=kind)
    patch.alarms = msg.int(1)
    patch.power = msg.bool(2)
    patch.setpoint = _setpoint(msg.message(3))
    patch.air_temperature = msg.float(4)
    patch.hvac_mode = _enum(HvacMode, msg.int(5))
    patch.fan_speed = _enum(FanSpeed, msg.int(6))
    patch.flap_swing = msg.bool(7)
    patch.has_flap_swing = msg.has(7)
    patch.last_raw = _debug(msg)
    return patch


def parse_heatpump_event(msg: Message) -> DeviceState:
    """heatpump.Event: same numbering as heatpump.State, with scalar enums: alarms=1; Dhw dhw=2; Zone zone1=3; Zone zone2=4;
    heating_curve=5; cooling_curve=6; HvacMode.Type hvac_mode=7; active_load=8; outdoor_temperature=9; water_pressure=10;
    SilentMode.Level silent_mode=11; load_priority=12; OperationMode.Event operation_mode=13 (all optional)."""
    patch = DeviceState(kind=DEVICE_KIND_HEATPUMP)
    patch.alarms = msg.int(1)
    hp = HeatPumpState()
    _hp_common(msg, hp)
    hp.silent_level = _enum(SilentLevel, msg.int(11))
    patch.hvac_mode = _enum(HvacMode, msg.int(7))
    patch.heatpump = hp
    patch.air_temperature = hp.outdoor_temperature
    patch.operation_mode = _operation_mode_state(msg.message(13))
    patch.last_raw = _debug(msg)
    return patch


# --------------------------------------------------------------------------------------
# Top-level envelopes
# --------------------------------------------------------------------------------------


class DeviceEvent:
    """One decoded ``services.app.Event``."""

    __slots__ = ("mac", "node_id", "kind", "patch", "connection", "raw")

    def __init__(self, mac: bytes, node_id: int | None) -> None:
        self.mac = mac
        self.node_id = node_id
        self.kind: str = DEVICE_KIND_UNKNOWN
        self.patch: DeviceState | None = None
        self.connection: bool | None = None  # True = established, False = lost
        self.raw: dict | None = None


_EVENT_DEVICE_PARSERS = {
    2: (DEVICE_KIND_AC, parse_ac_event),
    3: (DEVICE_KIND_FANCOIL, parse_fancoil_event),
    5: (DEVICE_KIND_THERMOSTAT, parse_thermostat_event),
    6: (DEVICE_KIND_HEATPUMP, parse_heatpump_event),
}


def parse_event(buf: bytes) -> DeviceEvent | None:
    """services.app.Event { oneof type { Device device = 1; } }
    Event.Device { bytes mac_address = 1; uint32 node_id = 2; DeviceMessage.Event event = 3; }
    DeviceMessage.Event { oneof type { System system = 1; Diagnostic diagnostic = 2; Device device = 3; } }
    DeviceMessage.Event.System { oneof { ConnectionEstablished = 1; ConnectionLost = 2; ProvisioningCompleted = 3; } }
    DeviceMessage.Event.Device { oneof { gateway = 1; ac = 2; fancoil = 3; butler = 4; thermostat = 5; heatpump = 6; } }
    """
    outer = Message(buf)
    device = outer.message(1)
    if device is None:
        return None
    event = DeviceEvent(device.bytes(1, b""), device.int(2))
    event.raw = _debug(outer)
    payload = device.message(3)
    if payload is None:
        return event
    system = payload.message(1)
    if system is not None:
        if system.has(1):
            event.connection = True
        elif system.has(2):
            event.connection = False
        return event
    dev = payload.message(3)
    if dev is None:
        return event
    for field, (kind, parser) in _EVENT_DEVICE_PARSERS.items():
        sub = dev.message(field)
        if sub is not None:
            event.kind = kind
            event.patch = parser(sub)
            return event
    if dev.has(1):
        event.kind = "gateway"
    elif dev.has(4):
        event.kind = DEVICE_KIND_BUTLER
    return event


class StateResponse:
    """Decoded ``SendDevice`` reply for a ``get_state`` request."""

    __slots__ = ("nodes", "gateway", "error_code", "error_message", "raw")

    def __init__(self) -> None:
        self.nodes: dict[int, DeviceState] = {}
        self.gateway: GatewayState | None = None
        self.error_code: ResponseErrorCode | None = None
        self.error_message: str | None = None
        self.raw: dict | None = None


_NODE_PARSERS = {
    1: parse_ac_state,
    2: parse_fancoil_state,
    3: parse_thermostat_state,
    4: parse_heatpump_state,
}


def parse_state_response(buf: bytes) -> StateResponse:
    """DeviceMessage.Response { oneof { Error error = 1; Device device = 2; Service service = 3; } }
    Response.Error { Code code = 1; string message = 2; }
    Response.Device { oneof { shared.Response shared = 1; ac.Response ac = 2; ... } }
    shared.Response { oneof { State state = 1; } }
    shared.Response.State { gateway.State gateway = 1; map<uint32, Node> nodes = 2; }
    shared.Response.State.Node { oneof { ac.State ac = 1; fancoil.State fancoil = 2; thermostat.State thermostat = 3;
                                        heatpump.State heatpump = 4; butler.State butler = 5; NodeError error = 6; } }

    The server may wrap the response in a ``DeviceMessage { uint32 node_id = 1; ... Response response = 3; }``;
    both shapes are handled.
    """
    out = StateResponse()
    if not buf:
        return out
    msg = Message(buf)
    out.raw = _debug(msg)
    # Unwrap a DeviceMessage envelope if present: there field 1 is a varint node_id (omitted when 0)
    # and field 3 is the Response; in a bare Response field 1 is the Error submessage and 3 the Service.
    if msg.has(3) and msg.wires.get(1) != 2 and not msg.has(2):
        inner = msg.message(3)
        if inner is not None:
            msg = inner
    error = msg.message(1) if msg.wires.get(1) == 2 else None
    if error is not None and not msg.has(2):
        out.error_code = _enum(ResponseErrorCode, error.int(1)) or ResponseErrorCode.UNSPECIFIED
        out.error_message = error.string(2)
        return out
    device = msg.message(2)
    if device is None:
        return out
    shared = device.message(1)
    if shared is None:
        return out
    state = shared.message(1)
    if state is None:
        return out
    for entry in state.messages(2):
        node_id = entry.int(1, 0) or 0
        node = entry.message(2)
        if node is None:
            continue
        parsed: DeviceState | None = None
        for field, parser in _NODE_PARSERS.items():
            sub = node.message(field)
            if sub is not None:
                parsed = parser(sub)
                break
        if parsed is None:
            parsed = DeviceState(kind=DEVICE_KIND_BUTLER if node.has(5) else DEVICE_KIND_UNKNOWN)
            if node.wires.get(6) == 0:
                parsed.node_error = _enum(NodeError, node.int(6))
                parsed.online = parsed.node_error != NodeError.OFFLINE
        out.nodes[node_id] = parsed
    out.gateway = _gateway_state(state.message(1))
    return out
