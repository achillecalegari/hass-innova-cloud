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

MAC = "AA:BB:CC:11:22:33"


def test_mac_and_uuid_helpers():
    raw = mac_to_bytes(MAC)
    assert raw == b"\xaa\xbb\xcc\x11\x22\x33"
    assert mac_to_str(raw) == MAC
    assert len(uuid_to_bytes("0f1e2d3c-4b5a-4697-8877-665544332211")) == 16


def test_subscribe_events_request():
    home = uuid_to_bytes("0f1e2d3c-4b5a-4697-8877-665544332211")
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
    gateway = Writer().varint(2, 1234).string(3, "IN00000001").message(
        4, Writer().message(2, Writer().message(1, Writer().string(1, "MyWifi").varint(2, -61).varint(3, 30)))
    )
    state = Writer().message(1, gateway).message(2, entry)
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
    assert parsed.gateway.serial_number == "IN00000001"
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
    raw = Writer().message(2, Writer().message(1, Writer().message(1, Writer().message(2, entry)))).finish()
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


def test_state_response_without_gateway_block_keeps_gateway_none():
    node = Writer().message(1, _ac_state_bytes())
    entry = Writer().varint(1, 0).message(2, node)
    raw = Writer().message(2, Writer().message(1, Writer().message(1, Writer().message(2, entry)))).finish()
    parsed = messages.parse_state_response(raw)
    assert parsed.gateway is None
    assert parsed.nodes[0].kind == DEVICE_KIND_AC


def test_state_response_wrapped_in_device_message_with_node_id_zero_omitted():
    # A real serializer omits node_id = 0, so the envelope has only field 3.
    inner = _state_response_bytes(0, _ac_state_bytes())
    raw = Writer().message(3, inner).finish()
    parsed = messages.parse_state_response(raw)
    assert parsed.nodes[0].kind == DEVICE_KIND_AC


def test_live_reply_from_real_unit_decodes():
    # Captured from a real unit (serial and SSID replaced): Response.device.shared.state{gateway=1, nodes=2}
    raw = bytes.fromhex(
        "12710a6f0a6d0a3010361a0a494e30303030303030312220"
        "0a0101121b0a190a0a57616e6465726c75737410c4ffffffffffffffff012001"
        "123912370a3510011a140d0000c04115000080411d0000f841250000003f"
        "220908031a0501020304052a0908011205020304050130003d9a99c541"
    )
    parsed = messages.parse_state_response(raw)
    assert parsed.gateway.firmware_version_code == 54
    assert parsed.gateway.serial_number == "IN00000001"
    assert parsed.gateway.wifi_rssi == -60
    node = parsed.nodes[0]
    assert node.kind == DEVICE_KIND_AC and node.power is True
    assert node.setpoint.value == 24.0 and node.hvac_mode == HvacMode.COOL and node.fan_speed == FanSpeed.AUTO
    assert node.fan_capabilities == [FanSpeed.MIN, FanSpeed.MID, FanSpeed.MAX, FanSpeed.BOOST, FanSpeed.AUTO]
    assert abs(node.air_temperature - 24.7) < 1e-5
    assert node.flap_swing is False and node.has_flap_swing
    assert not node.has_humidity and not node.has_erv and not node.has_silent_mode


def test_carry_over_keeps_capabilities_and_gateway():
    pass
    old = messages.parse_state_response(_state_response_bytes(0, _ac_state_bytes())).nodes[0]
    old.gateway.firmware_version_code = 54
    new = messages.parse_state_response(_state_response_bytes(0, Writer().bool(2, True).float32(7, 20.0).finish())).nodes[0]
    assert not new.has_humidity
    new.carry_over(old)
    assert new.has_humidity and new.has_erv and new.has_silent_mode and new.has_flap_swing
    assert new.gateway.firmware_version_code == 54


def test_truncated_payload_raises():
    import pytest

    with pytest.raises(ValueError):
        Message(b"\x0a\x10\x01")


def _heatpump_state_bytes() -> bytes:
    from api.models import LoadType, SilentLevel

    dhw = Writer().bool(1, True).float32(2, 48.0).float32(3, 48.0).float32(4, 45.5).message(5, Writer().message(1, Writer().varint(1, 30).message(2, Writer().varint(1, 100).varint(2, 0))))
    zone1 = Writer().bool(1, True).float32(2, 35.0).float32(3, 18.0).float32(4, 35.0).float32(5, 33.2)
    hvac = Writer().varint(1, HvacMode.HEAT).bytes(3, encode_varint(HvacMode.HEAT) + encode_varint(HvacMode.COOL) + encode_varint(HvacMode.AUTO))
    silent = Writer().varint(1, SilentLevel.LEVEL_AUTO).bytes(2, b"".join(encode_varint(v) for v in (1, 2, 3, 4)))
    return (
        Writer().varint(1, 0).message(2, dhw).message(3, zone1).varint(5, 1).varint(6, 2).message(7, hvac).varint(8, LoadType.LOAD_TYPE_ZONE)
        .float32(9, 7.5).float32(10, 1.8).message(11, silent).varint(12, LoadType.LOAD_TYPE_DHW).finish()
    )


def test_parse_heatpump_state():
    from api.models import DEVICE_KIND_HEATPUMP, LoadType, SilentLevel

    node = Writer().message(4, _heatpump_state_bytes())  # Node.heatpump = 4
    entry = Writer().varint(1, 0).message(2, node)
    raw = Writer().message(2, Writer().message(1, Writer().message(1, Writer().message(2, entry)))).finish()
    st = messages.parse_state_response(raw).nodes[0]
    assert st.kind == DEVICE_KIND_HEATPUMP and st.power is True
    hp = st.heatpump
    assert hp.dhw.power is True and hp.dhw.setpoint == 48.0 and abs(hp.dhw.water_temperature - 45.5) < 1e-5
    assert hp.dhw.boost_active is True and hp.dhw.boost_minutes == 30
    assert hp.zone1.heating_setpoint == 35.0 and hp.zone1.cooling_setpoint == 18.0 and abs(hp.zone1.water_temperature - 33.2) < 1e-5
    assert hp.zone2 is None
    assert st.hvac_mode == HvacMode.HEAT and st.hvac_capabilities == [HvacMode.HEAT, HvacMode.COOL, HvacMode.AUTO]
    assert hp.active_load == LoadType.LOAD_TYPE_ZONE and hp.load_priority == LoadType.LOAD_TYPE_DHW
    assert abs(hp.outdoor_temperature - 7.5) < 1e-5 and abs(hp.water_pressure - 1.8) < 1e-5
    assert hp.silent_level == SilentLevel.LEVEL_AUTO and hp.silent_capabilities == [SilentLevel.LEVEL_OFF, SilentLevel.LEVEL_AUTO, SilentLevel.LEVEL_1, SilentLevel.LEVEL_2]
    assert st.air_temperature == hp.outdoor_temperature


def test_heatpump_event_merges_into_state():
    from api.models import SilentLevel

    node = Writer().message(4, _heatpump_state_bytes())
    entry = Writer().varint(1, 0).message(2, node)
    raw = Writer().message(2, Writer().message(1, Writer().message(1, Writer().message(2, entry)))).finish()
    st = messages.parse_state_response(raw).nodes[0]
    # event: zone1 heating setpoint 36, silent level off, outdoor temp 6
    ev = Writer().message(3, Writer().float32(2, 36.0)).varint(11, SilentLevel.LEVEL_OFF).float32(9, 6.0).finish()
    patch = messages.parse_heatpump_event(Message(ev))
    st.apply_event(patch)
    assert st.heatpump.zone1.heating_setpoint == 36.0 and st.heatpump.zone1.cooling_setpoint == 18.0
    assert st.heatpump.silent_level == SilentLevel.LEVEL_OFF
    assert st.heatpump.outdoor_temperature == 6.0 and st.heatpump.dhw.setpoint == 48.0


def test_heatpump_set_state_request():
    from api.models import LoadType, SilentLevel

    raw = messages.request_heatpump_set_state(dhw_setpoint=50.0, zone1_power=True, zone1_heating_setpoint=34.5, hvac_mode=HvacMode.HEAT, silent_level=SilentLevel.LEVEL_1, load_priority=LoadType.LOAD_TYPE_DHW)
    hp = Message(raw).message(7)  # CloudMessage.Request.heatpump = 7
    set_state = hp.message(1)
    assert abs(set_state.message(1).float(2) - 50.0) < 1e-6 and not set_state.message(1).has(1)
    zone1 = set_state.message(2)
    assert zone1.bool(1) is True and abs(zone1.float(2) - 34.5) < 1e-6 and not zone1.has(3)
    assert not set_state.has(3)
    assert set_state.int(4) == HvacMode.HEAT and set_state.int(5) == SilentLevel.LEVEL_1 and set_state.int(6) == LoadType.LOAD_TYPE_DHW


def test_alarm_descriptions():
    from api.alarms import describe_alarms

    assert describe_alarms("ac", 0) == []
    assert describe_alarms("ac", (1 << 0) | (1 << 9), "en") == ["Room probe failure (display E1)", "Condensate water alarm (display F2)"]
    assert describe_alarms("fancoil", 1 << 10, "it")[0].startswith("Manutenzione filtro")
    assert describe_alarms("ac", 1 << 40) == ["Alarm 40"]


def test_system_reboot_request():
    raw = messages.request_system_reboot()
    assert Message(raw).message(1).has(1)
