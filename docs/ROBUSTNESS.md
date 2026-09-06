# Robustness: what happens when things go wrong

The units are cloud-only, so Home Assistant never talks to them directly: every scenario below is
about the path *unit ⇄ Innova cloud ⇄ Home Assistant*. Two channels are always in play:

* **push**: one `SubscribeEvents` gRPC stream per home (live changes, connection events);
* **poll**: a full `get_state` per unit every 10 minutes (`POLL_INTERVAL`), plus a targeted
  re-read 3 seconds after every command and after every reconnection.

| Scenario | What the cloud does | What the integration does | What you see |
| --- | --- | --- | --- |
| Unit loses Wi‑Fi | Emits `connection_lost`; later `get_state` answers `RESPONSE_TIMEOUT` / `CACHE_NOT_READY` | Marks the unit offline (keeps last values in memory), keeps polling | Entities **unavailable** until it is back |
| Unit reconnects, same or **different IP** | Emits `connection_established` | Marks online, re-reads the state after 3 s | Entities back with fresh values. The IP is irrelevant: the unit is identified by MAC on the cloud side |
| Unit rebooted (power cut) | `CACHE_NOT_READY` until the unit pushes its state | Offline, then online on the next event/poll | Short unavailability |
| Cloud restarts / stream dropped / DNS blip | gRPC `UNAVAILABLE`, stream ends | Reconnects with backoff 5 s → 300 s (reset to 5 s as soon as a connection is accepted), then re-reads every unit to catch what was missed | At worst a few minutes without live updates; polling continues meanwhile |
| Cloud completely down | REST and gRPC fail | Poll fails → entities unavailable; stream keeps retrying; setup retries with HA's own backoff if HA starts during the outage | Unavailable until the cloud returns, then self-heals |
| Home Assistant restarts while units are off | First `get_state` fails for those units | Entry loads anyway; entities are created as soon as a unit reports its type | Entities appear when the unit is back |
| Session token expires (about one year) | REST/gRPC answer 401 / `UNAUTHENTICATED` | Re-login with stored email+password (rate limited, once a minute), token saved without reloading the entry. Without stored credentials: reauth prompt, started once | Nothing, or a "re-authenticate" notification |
| Cloud rejects the stream even with a fresh token | `UNAUTHENTICATED` repeatedly | After 3 attempts the stream stops and a reauth is requested (no login storm) | Reauth notification, polling keeps working if REST accepts the token |
| A unit is renamed / moved to another room in the app | `/app/homes` changes | Home layout re-read every 6 hours (and at every restart) | Device name/area update after the next refresh or a reload |
| A unit is added in the app | New device in `/app/homes` | Picked up at the next layout refresh; entities created | New device appears within 6 hours, or immediately after a reload |
| A unit or a home is removed in the app | Missing from `/app/homes` | State dropped, stream for the home stopped, device detached from the registry | Entities disappear / become unavailable |
| Firmware update adds fields the codec does not know | Extra protobuf fields | Unknown fields are skipped; an undecodable reply only affects that unit and is logged | Other units unaffected |
| Command fails (unit offline, timeout) | gRPC error | The service call raises an error shown in the UI; no optimistic change is kept | Error toast |
| Schedule (calendar) active on the unit | Manual changes may be reverted at the next slot | Exposed as the `operation_mode` sensor and the "Manual override" switch | You can force manual mode from HA |
| HA reload / shutdown | – | Every stream task and timer is owned by the config entry and cancelled; the gRPC channel is closed and refuses reuse | Clean restarts |

## Things the integration deliberately does not do

* No local fallback: this generation has no LAN interface (see PROTOCOL.md). If Innova ever ships one,
  it can be added as a second transport behind the same coordinator.
* No aggressive polling: 10 minutes is a safety net, the stream is the primary source. Lowering it
  only adds load on the vendor's cloud.
* No token sharing: the JWT stays in the config entry (redacted in diagnostics).

## Debugging

```yaml
logger:
  logs:
    custom_components.innova_cloud: debug
```

With debug on, every event and reply is logged decoded (`Event AA:BB:…/0: {...}`, `SendDevice … -> hex`)
and the diagnostics download shows `stream_connected` and the raw state of each node.
