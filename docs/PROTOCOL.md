# Innova app cloud protocol (reverse engineering notes)

Source: the iOS/iPadOS app **"Innova" 3.2.3** by Solution Tech Srl (bundle `tech.solutiontech.Innova`,
released 2024‑05, built with SwiftUI, SwiftProtobuf 1.30+, grpc‑swift 2, Firebase, Google Sign‑In).
Running the iPad build on an Apple‑silicon Mac leaves the binary almost entirely unencrypted
(FairPlay covers 4 KB out of 24 MB), so everything below was recovered **statically**:

* gRPC service/method names and `.proto` message names from the string table;
* field **numbers** from the SwiftProtobuf `_NameMap(bytecode:)` programs (format 0: opcode,
  null‑terminated name; `*Next` opcodes mean "previous number + 1");
* field **types** from the Swift reflection metadata (`__swift5_fieldmd`), including chained‑fixup
  binds to resolve `Foundation.Data`, `UInt32`, `Float`, etc.;
* REST endpoints from the app's URL cache on disk and from Codable type names.

Hostnames are not present as literals in the binary: they are assembled at runtime from a
per‑brand `BrandConfiguration { restBaseURL, grpcHost }`. The app is white‑labelled
(`BrandOEMID`: innova, aquareaHome, diffusApp, ethermaFireIce2, rhossTema, immergas).

## Devices

Units are ESP32 based (Espressif MAC prefixes), provisioned over BLE (ESP "security 1" style
key exchange, `messages.ble.*`). Once on Wi‑Fi they keep an outbound TLS connection to the cloud
and expose **no local ports** (full TCP scan: everything filtered). Control is cloud‑only.

Device identity: `mac_address` (6 bytes) + `node_id` (0 for the unit itself; gateways such as the
"Butler" RS‑485 bridge expose several nodes) + `DeviceUid { vendor_id, product_id, hw_revision }`.
Product categories known to the app: airconditioner, fancoil, thermostat, heatpump, bms, energymonitor.

## REST API

Base: `https://v2.api.innova.solutiontech.tech/app/` (nginx in front of a Rust/axum service).
Errors: `{"code": 1302, "message": "Authentication token is missing or invalid"}` (HTTP 401),
`1304 Invalid credentials`, `1200` deserialisation errors.

| Method | Path | Body / notes |
| --- | --- | --- |
| POST | `users/login` | `{"email","password"}` → JSON with the JWT |
| POST | `users/login-google`, `users/login-google/nonce` | Google Sign‑In (nonce + id token) |
| POST | `users/login-apple`, `users/login-apple/nonce` | Sign in with Apple |
| POST | `users/send-reset-password/{email}`, `users/reset-password`, `users/change-password`, `users/verify-email`, `users/send-email-confirmation` | account management |
| POST | `users/logout` | |
| GET | `homes` | homes with `rooms`, `devices`, `members`, `invites`, `calendars` |
| … | `homes/{id}`, `rooms`, `devices`, `members`, `invites`, `calendars`, `nodes` | CRUD used by the app (not needed here) |

Authentication: `Authorization: Bearer <JWT>`. The JWT is signed with PS256 by the Innova API,
`aud: "user-api"`, `sub: <member uuid>`, `state: "active"`, and is valid for **one year**.

`GET /app/homes` example (trimmed):

```json
[{"id":"<uuid>","name":"Casa","calendarId":null,"timezone":"Europe/Rome",
  "members":[{"id":"<uuid>","firstname":"…","lastname":"…","email":"…","role":"owner"}],
  "devices":[{"macAddress":"F0:F5:BD:09:38:F8","nodeId":0,"name":"Salotto",
              "uid":{"vendorId":1,"productId":1,"hwRevision":1},"serialNumber":"IN25…","roomId":"<uuid>"}],
  "rooms":[{"id":"<uuid>","name":"Salotto","orderIndex":null}],"calendars":[]}]
```

## gRPC API

Host `v2.grpc.innova.solutiontech.tech:443`, TLS, HTTP/2, `content-type: application/grpc`,
metadata `authorization: Bearer <same JWT>`. Server is tonic‑like: unknown paths → `UNIMPLEMENTED`,
missing token → `UNAUTHENTICATED "Authentication token is missing or invalid"`.
(The older host `grpc.innova.solutiontech.tech` answers `UNIMPLEMENTED` for everything.)

```
service services.app.AppService {
  rpc SendDevice(SendDeviceRequest) returns (DeviceMessage.Response);
  rpc SubscribeEvents(SubscribeEventsRequest) returns (stream Event);
}
```

* `SubscribeEventsRequest { bytes home_id = 1 }` — 16 raw UUID bytes of the home.
* `SendDeviceRequest { bytes mac_address = 1; uint32 node_id = 2; CloudMessage.Request request = 3 }`.
* `Event { Device device = 1 }`, `Event.Device { bytes mac_address = 1; uint32 node_id = 2; DeviceMessage.Event event = 3 }`.

The app keeps one `SubscribeEvents` stream per home open in the background (with reconnect) and a
`DeviceMutationQueue` that serialises `SendDevice` calls.

### Requests (`messages.CloudMessage.Request`)

`oneof { system=1, shared=2, ac=3, butler=4, fancoil=5, thermostat=6, heatpump=7 }`

* `shared.Request.get_state = 1` (empty) → full state of every node behind the gateway.
* `shared.Request.set_operation_mode = 3` → `{ calendar=1 | manual=2 | antifreeze=3 }`, each a
  `map<uint32 node_id, Configuration>`; `Manual.Configuration { bool enabled=1; Timestamp until=2 }`.
* `ac.Request.set_state = 1` → `SetState { bool power=1; float temperature_setpoint=2; HvacMode.Type hvac_mode=3;
  FanSpeed.Type fan_speed=4; bool flap_swing=5; bool erv=6; bool silent_mode=7 }` (all `optional`, send only
  what changes). Fan coil / thermostat: same without 6 and 7.
* `system.Request { reboot=1, update_firmware=2 }`.

### Responses (`messages.DeviceMessage.Response`)

`oneof { error=1 {code, message}, device=2, service=3 }`; `device.shared.Response.state.nodes` is a
`map<uint32, Node>` where `Node` is `oneof { ac.State=1, fancoil.State=2, thermostat.State=3,
heatpump.State=4, butler.State=5, NodeError error=6 }`, plus `gateway.State` (firmware version code,
serial number, Wi‑Fi SSID/RSSI/SNR, interfaces). Error codes: `RESPONSE_TIMEOUT`, `CACHE_NOT_READY`;
node errors: `OFFLINE`, `CACHE_NOT_READY`, `INTERNAL`.

### States and events

`ac.State` (full) vs `ac.Event` (partial patch, different numbering!):

| Field | State # | Event # | Type |
| --- | --- | --- | --- |
| alarms | 1 | 1 | uint32 bitmask |
| power | 2 | 2 | bool |
| temperature_setpoint | 3 | 3 | `setpoint.State/Event { float value=1,min=2,max=3,step=4 }` |
| hvac_mode | 4 | 5 | State: `HvacMode { Type value=1; Type actual_value=2; repeated Type capabilities=3 }`; Event: `Type` |
| fan_speed | 5 | 6 | State: `FanSpeed { Type value=1; repeated Type capabilities=2 }`; Event: `Type` |
| flap_swing | 6 | 7 | bool |
| air_temperature | 7 | 4 | float |
| air_humidity | 8 | 10 | float |
| erv | 9 | 8 | bool |
| operation_mode | 10 | 9 | `operation_mode.State/Event { Type active=1; calendar=2; manual=3; antifreeze=4 }` |
| silent_mode | 11 | 11 | bool |

Enums: `HvacMode.Type { AUTO=1, HEAT=2, COOL=3, DRY=4, FAN=5 }`, `FanSpeed.Type { AUTO=1, MIN=2, MID=3, MAX=4, BOOST=5 }`,
`operation_mode.Type { CALENDAR=1, MANUAL=2, ANTIFREEZE=3 }`, `Calendar.PresetType { NIGHT=1, ECO=2, COMFORT=3, AWAY=4, FREEZE=5 }`.

Fan coil and thermostat `State`: 1 alarms, 2 power, 3 setpoint, 4 hvac_mode, 5 fan_speed, 6 flap_swing,
7 air_temperature, 8 air_humidity, 9 operation_mode; `Event`: 1 alarms, 2 power, 3 setpoint,
4 air_temperature, 5 hvac_mode, 6 fan_speed, 7 flap_swing, 8 operation_mode, 9 air_humidity.

Heat pump `State`: 1 alarms (uint64), 2 dhw, 3 zone1, 4 zone2, 5 heating_curve, 6 cooling_curve,
7 hvac_mode, 8 active_load, 9 outdoor_temperature, 10 water_pressure, 11 silent_mode, 12 load_priority,
13 operation_mode.

System events: `DeviceMessage.Event.System { connection_established=1, connection_lost=2, provisioning_completed=3 }`.

The complete reconstructed schema is in [`../proto/innova_app.proto`](../proto/innova_app.proto).

## Telemetry

Units also push `ContinuousTelemetryLogs` / `DiscreteTelemetryLogs` / `EventTelemetryLogs` with a very
rich `TelemetryType` enum (287 values: compressor speed, EEV opening, inverter voltages, CO2/TVOC/IAQ,
Wi‑Fi chip temperature, …). They are not decoded by the integration but the enum is in the app
binary should someone want energy/diagnostic sensors.

## Things not verified on the wire

The schema was reconstructed statically; encoders follow the recovered types exactly, and the
integration logs raw payloads at debug level. If a device family answers with something unexpected,
`scripts/innova_cli.py raw <mac>` prints the undecoded reply.
