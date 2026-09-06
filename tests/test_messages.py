"""Schema-level tests: encoders produce the expected wire bytes and decoders read them back."""

from api import messages
from api.models import (
    DEVICE_KIND_AC,
    DEVICE_KIND_FANCOIL,
    FanSpeed,
    HvacMode,
    NodeError,
    OperationModeType,
    ResponseErrorCode,
    mac_to_bytes,
    mac_to_str,
    uuid_to_bytes,
)
from api.protobuf import Message, Writer, encode_varint

MAC = "F0:F5:BD:09:38:F8"


def test_mac_and_uuid_helpers():
    raw = mac_to_bytes(MAC)
    assert raw == b"\xf0\xf5\xbd\x09\x38\xf8"
    assert mac_to_str(raw) == MAC
    assert len(uuid_to_bytes("68fb3356-85cf-42f3-a7f5-1693eb0691d7")) == 16


def test_subscribe_events_request():
    home = uuid_to_bytes("68fb3356-85cf-42f3-a7f5-1693eb0691d7")
    assert messages.subscribe_events_request(home) == b"\x0a\x10" + home


def test_get_state_request_shape():
    # SendDeviceRequest{mac=1, node_id=2, request=3: CloudMessage.Request{shared=2: {get_state=1: {}}}}
    payload = messages.send_device_request(mac_to_bytes(MAC), 0, messages.request_get_state())
    msg = Message(payload)
    assert msg.bytes(1) == mac_to_bytes(MAC)
    assert msg.int(2) == 0
    request = msg.message(3)
    shared = request.message(2)
    assert shared.has(1) and shared.bytes(1) == b""
    assert payload == b"\x0a\x06" + mac_to_bytes(MAC) + b"\x10\x00" + b"\x1a\x04" + b"\x12\x02" + b"\x0a\x00"


def test_ac_set_state_request():
    raw = messages.request_set_state(
        DEVICE_KIND_AC, power=True, temperature_setpoint=22.5, hvac_mode=HvacMode.COOL, fan_speed=FanSpeed.MAX,
        flap_swing=False, erv=None, silent_mode=True,
    )
    request = Message(raw)
    ac = request.message(3)  # CloudMessage.Request.ac = 3
    set_state = ac.message(1)  # ac.Request.set_state = 1
    assert set_state.bool(1) is True
    assert abs(set_state.float(2) - 22.5) < 1e-6
    assert set_state.int(3) == HvacMode.COOL
    assert set_state.int(4) == FanSpeed.MAX
    assert set_state.bool(5) is False
    assert not set_state.has(6)
    assert set_state.bool(7) is True


def test_fancoil_set_state_has_no_ac_only_fields():
    raw = messages.request_set_state(DEVICE_KIND_FANCOIL, power=False, erv=True, silent_mode=True)
    request = Message(raw)
    fancoil = request.message(5)  # CloudMessage.Request.fancoil = 5
    set_state = fancoil.message(1)
    assert set_state.bool(1) is False
    assert not set_state.has(6) and not set_state.has(7)


def test_manual_mode_request():
    raw = messages.request_set_manual_mode(0, True, until_minutes=120)
    shared = Message(raw).message(2)
    set_op = shared.message(3)
    manual = set_op.message(2)
    entry = manual.message(1)
    assert entry.int(1) == 0
    config = entry.message(2)
    assert config.bool(1) is True
    assert config.message(2).int(1) == 120


def _ac_state_bytes(**overrides) -> bytes:
    setpoint = Writer().float32(1, 23.0).float32(2, 16.0).float32(3, 31.0).float32(4, 0.5)
    hvac = Writer().varint(1, HvacMode.COOL).varint(2, HvacMode.COOL).bytes(3, b"".join(encode_varint(v) for v in (1, 2, 3, 4, 5)))
    fan = Writer().varint(1, FanSpeed.AUTO).bytes(2, b"".join(encode_varint(v) for v in (1, 2, 3, 4)))
    manual_cfg = Writer().bool(1, True)
    op = Writer().varint(1, OperationModeType.MANUAL).message(3, Writer().message(1, manual_cfg))
    return (
        Writer()
        .varint(1, overrides.get("alarms", 0))
        .bool(2, overrides.get("power", True))
        .message(3, setpoint)
        .message(4, hvac)
        .message(5, fan)
        .bool(6, True)
        .float32(7, 25.3)
        .float32(8, 48.0)
        .bool(9, False)
        .message(10, op)
        .bool(11, True)
        .finish()
    )


def _state_response_bytes(node_id: int, ac_state: bytes, wrap_in_device_message: bool = False) -> bytes:
    node = Writer().message(1, ac_state)  # Node.ac = 1
    entry = Writer().varint(1, node_id).message(2, node)
    gateway = Writer().varint(2, 1234).string(3, "IN25015684").message(
        4, Writer().message(2, Writer().message(1, Writer().string(1, "MyWifi").varint(2, -61).varint(3, 30)))
    )
    state = Writer().message(1, entry).message(2, gateway)
    shared = Writer().message(1, state)
    device = Writer().message(1, shared)
    response = Writer().message(2, device).finish()
    if wrap_in_device_message:
        return Writer().varint(1, node_id).message(3, response).finish()
    return response


def test_parse_state_response_ac():
    raw = _state_response_bytes(0, _ac_state_bytes())
    parsed = messages.parse_state_response(raw)
    assert parsed.error_code is None
    node = parsed.nodes[0]
    assert node.kind == DEVICE_KIND_AC
    assert node.power is True
    assert node.setpoint.value == 23.0 and node.setpoint.min == 16.0 and node.setpoint.max == 31.0 and node.setpoint.step == 0.5
    assert node.hvac_mode == HvacMode.COOL and node.hvac_actual == HvacMode.COOL
    assert node.hvac_capabilities == [HvacMode.AUTO, HvacMode.HEAT, HvacMode.COOL, HvacMode.DRY, HvacMode.FAN]
    assert node.fan_speed == FanSpeed.AUTO
    assert node.fan_capabilities == [FanSpeed.AUTO, FanSpeed.MIN, FanSpeed.MID, FanSpeed.MAX]
    assert node.flap_swing is True and node.has_flap_swing
    assert abs(node.air_temperature - 25.3) < 1e-5
    assert node.air_humidity == 48.0 and node.has_humidity
    assert node.erv is False and node.has_erv
    assert node.silent_mode is True and node.has_silent_mode
    assert node.operation_mode.active == OperationModeType.MANUAL
    assert node.operation_mode.manual_enabled is True
    assert parsed.gateway.firmware_version_code == 1234
    assert parsed.gateway.serial_number == "IN25015684"
    assert parsed.gateway.wifi_ssid == "MyWifi" and parsed.gateway.wifi_rssi == -61


def test_parse_state_response_wrapped_in_device_message():
    raw = _state_response_bytes(0, _ac_state_bytes(), wrap_in_device_message=True)
    parsed = messages.parse_state_response(raw)
    assert parsed.nodes[0].kind == DEVICE_KIND_AC


def test_parse_state_response_error():
    raw = Writer().message(1, Writer().varint(1, ResponseErrorCode.CACHE_NOT_READY).string(2, "cache")).finish()
    parsed = messages.parse_state_response(raw)
    assert parsed.error_code == ResponseErrorCode.CACHE_NOT_READY
    assert parsed.error_message == "cache"
    assert parsed.nodes == {}


def test_parse_state_response_node_error():
    node = Writer().varint(6, NodeError.OFFLINE)
    entry = Writer().varint(1, 0).message(2, node)
    raw = Writer().message(2, Writer().message(1, Writer().message(1, Writer().message(1, entry)))).finish()
    parsed = messages.parse_state_response(raw)
    assert parsed.nodes[0].node_error == NodeError.OFFLINE
    assert parsed.nodes[0].online is False


def test_parse_state_response_empty():
    parsed = messages.parse_state_response(b"")
    assert parsed.nodes == {} and parsed.error_code is None


def test_parse_ac_event():
    # Event{device=1: {mac=1, node_id=2, event=3: DeviceMessage.Event{device=3: {ac=2: ac.Event{...}}}}}
    ac_event = Writer().bool(2, False).message(3, Writer().float32(1, 21.0)).float32(4, 24.1).varint(5, HvacMode.HEAT).varint(6, FanSpeed.MID)
    dev_event = Writer().message(3, Writer().message(2, ac_event))
    device = Writer().bytes(1, mac_to_bytes(MAC)).varint(2, 0).message(3, dev_event)
    raw = Writer().message(1, device).finish()
    event = messages.parse_event(raw)
    assert mac_to_str(event.mac) == MAC
    assert event.node_id == 0
    assert event.kind == DEVICE_KIND_AC
    assert event.patch.power is False
    assert event.patch.setpoint.value == 21.0
    assert abs(event.patch.air_temperature - 24.1) < 1e-5
    assert event.patch.hvac_mode == HvacMode.HEAT
    assert event.patch.fan_speed == FanSpeed.MID
    assert event.patch.alarms is None  # not present in the patch


def test_parse_connection_events():
    lost = Writer().message(1, Writer().bytes(1, mac_to_bytes(MAC)).message(3, Writer().message(1, Writer().message(2, b"")))).finish()
    assert messages.parse_event(lost).connection is False
    established = Writer().message(1, Writer().bytes(1, mac_to_bytes(MAC)).message(3, Writer().message(1, Writer().message(1, b"")))).finish()
    assert messages.parse_event(established).connection is True


def test_apply_event_merges_partial_update():
    full = messages.parse_state_response(_state_response_bytes(0, _ac_state_bytes())).nodes[0]
    patch = messages.parse_ac_event(Message(Writer().bool(2, False).message(3, Writer().float32(1, 19.5)).finish()))
    full.apply_event(patch)
    assert full.power is False
    assert full.setpoint.value == 19.5
    assert full.setpoint.min == 16.0  # untouched
    assert full.hvac_mode == HvacMode.COOL  # untouched
