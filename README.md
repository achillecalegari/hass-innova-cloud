# Innova Cloud for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz)
[![Validate](https://github.com/achillecalegari/hass-innova-cloud/actions/workflows/validate.yml/badge.svg)](https://github.com/achillecalegari/hass-innova-cloud/actions/workflows/validate.yml)

Home Assistant integration for the **new generation of Innova air conditioners and fan coils**
(2024+ units such as the FÄRNA series and the 2.0 units with the ESP32 Wi‑Fi module) that are
controlled by the **"Innova" app by Solution Tech** and have **no local API**.

Older Innova 2.0 / AirLeaf units with the local REST API (`http://<ip>/api/v/1/status`) are
covered by [danielrivard/homeassistant-innova](https://github.com/danielrivard/homeassistant-innova),
not by this integration. Quick check: if your unit answers on `http://<ip>/api/v/1/status`, use that
one; if it only works through the cloud app (and its Bluetooth pairing flow), use this one.

*Leggi le istruzioni in italiano: [README.it.md](README.it.md).*

## Why this exists (a note to Innova)

Let's be blunt: it is indecent that an air conditioner in this price range ships with no
documented API, no local interface and no integration with Home Assistant, Alexa or HomeKit,
and that the only way to operate it is a closed, cloud-only app. Owners should not have to
reverse-engineer a mobile app to switch on their own unit. But that is where we are, so this
integration exists.

It will be maintained. If future app or firmware releases change the protocol or try to lock
control behind proprietary gateways, the protocol will be reverse-engineered again and this
integration updated. Innova and Solution Tech: the better path is to publish the API. The door
is open, and this repository already documents most of what such a document would contain.

## How it works

The app talks to `v2.api.innova.solutiontech.tech` (REST, JSON) and `v2.grpc.innova.solutiontech.tech`
(gRPC, protobuf). Both were reverse‑engineered from the app binary (see [docs/PROTOCOL.md](docs/PROTOCOL.md)
and [proto/innova_app.proto](proto/innova_app.proto)). The integration:

* lists your homes, rooms and devices from the REST API;
* reads the full state of each unit with a `get_state` request;
* keeps a **live gRPC event stream** open, so changes made from the app, the remote or the
  touch panel appear in Home Assistant within a second (`cloud_push`);
* sends commands with `SendDevice` (power, mode, setpoint, fan, flap swing, ERV, silent mode,
  manual override).

Everything goes through Innova's cloud: no LAN access to the units is possible with this generation.

## Entities

| Entity | Notes |
| --- | --- |
| `climate.<name>` | Modes off / auto (heat_cool) / heat / cool / dry / fan_only, fan auto / low / medium / high / boost (only the ones the unit reports), target temperature with the unit's min/max/step, swing on/off, current temperature and humidity. Attributes: operation mode (schedule / manual / antifreeze), active calendar preset, actual HVAC mode, alarm bitmask. |
| `sensor.<name>_room_temperature` | Room temperature (°C). |
| `sensor.<name>_humidity` | Only when the unit has a humidity sensor. |
| `sensor.<name>_operation_mode` | schedule / manual / antifreeze (diagnostic). |
| `sensor.<name>_alarms` | Raw alarm bitmask (diagnostic). |
| `sensor.<name>_wi_fi_signal` | RSSI of the unit (diagnostic, disabled by default). |
| `switch.<name>_silent_mode` | Air conditioners only. |
| `switch.<name>_air_exchange` | ERV, only if the unit has it. |
| `switch.<name>_manual_override` | Turns the schedule off (manual) or on again. When a schedule is active the unit may revert manual changes at the next schedule slot. |

Heat pumps are detected but only exposed as sensors (outdoor temperature, operation mode) for now.

## Installation

### HACS (recommended)

1. In HACS open **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/achillecalegari/hass-innova-cloud` with category **Integration**.
3. Search for **Innova Cloud**, click **Download**, then **restart Home Assistant**.

### Manual

Copy `custom_components/innova_cloud` into `<config>/custom_components/` and restart.

## Configuration

**Settings → Devices & services → Add integration → Innova Cloud**, then choose:

* **Email and password**: the credentials of your Innova app account. The integration logs in
  itself and renews the session when it expires.
  If you created the account with **Google** or **Apple** sign‑in, set a password first: in the app
  choose *Forgot password* with the same email, follow the email and pick a password. Google/Apple
  login keeps working alongside.
* **Session token (advanced)**: paste the JWT the app uses. Tokens last about one year; when it
  expires Home Assistant asks you to re‑authenticate.

The integration creates one device per unit, named as in the app, with the room as suggested area.

## Getting a session token (optional)

Only needed if you prefer not to set a password. The token is the `Authorization: Bearer …`
header the app sends; any HTTPS proxy on your phone can show it, or on a Mac with the iPad app
installed:

```bash
sqlite3 ~/Library/Containers/tech.solutiontech.Innova/Data/Library/Caches/tech.solutiontech.Innova/Cache.db \
  "select request_key from cfurl_cache_response" | grep app/homes
```

then read the request headers of that cache entry (they contain the bearer token). Keep the token
private: it grants full control of your units.

## Command line tester

`scripts/innova_cli.py` exercises the API without Home Assistant (needs `pip install grpcio aiohttp`):

```bash
export INNOVA_TOKEN=eyJ...           # or --email/--password
python scripts/innova_cli.py homes
python scripts/innova_cli.py state AA:BB:CC:11:22:33
python scripts/innova_cli.py watch
python scripts/innova_cli.py set AA:BB:CC:11:22:33 --power on --mode cool --temp 24 --fan auto
```

If something is decoded wrongly, `python scripts/innova_cli.py raw <mac>` prints the undecoded
reply; please attach it to a GitHub issue.

## Robustness

What happens when a unit drops off Wi‑Fi, the cloud restarts, the token expires or a unit is added/removed in the app is documented scenario by scenario in [docs/ROBUSTNESS.md](docs/ROBUSTNESS.md).

## Debug logging

```yaml
logger:
  logs:
    custom_components.innova_cloud: debug
```

## Supported / tested

Developed on two Innova units (vendor 1, product 1, hw 1, serials `IN…`) paired with app 3.2.3.
Fan coils and thermostats share the same message layout and should work; heat pumps are read‑only.
The same cloud platform is white‑labelled for other brands (Panasonic Aquarea Home, Rhoss Tema,
Etherma FireIce 2, Immergas, Diffus App): the REST base URL and gRPC host are configurable in the
config entry data (`rest_base`, `grpc_host`) should you want to try them.

## Disclaimer

This is an independent project, not affiliated with Innova or Solution Tech. It uses the same
cloud endpoints as the official app; use at your own risk. MIT licensed.
