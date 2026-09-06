#!/usr/bin/env python3
"""Command-line tester for the Innova cloud API (no Home Assistant needed).

    pip install grpcio aiohttp
    export INNOVA_TOKEN=eyJ...          # or: --email you@example.com --password ...
    python scripts/innova_cli.py homes
    python scripts/innova_cli.py state F0:F5:BD:09:38:F8
    python scripts/innova_cli.py watch                # live events (Ctrl-C to stop)
    python scripts/innova_cli.py set F0:F5:BD:09:38:F8 --power on --mode cool --temp 24 --fan auto
    python scripts/innova_cli.py raw F0:F5:BD:09:38:F8  # undecoded get_state reply, for debugging
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp  # noqa: E402

from custom_components.innova_cloud.api import InnovaGrpcClient, InnovaRestClient, messages  # noqa: E402
from custom_components.innova_cloud.api.models import FanSpeed, HvacMode, mac_to_bytes, mac_to_str, uuid_to_bytes  # noqa: E402
from custom_components.innova_cloud.api.protobuf import Message  # noqa: E402


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, default=lambda o: getattr(o, "name", None) or getattr(o, "__dict__", str(o)))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--token", default=os.environ.get("INNOVA_TOKEN"))
    parser.add_argument("--token-file")
    parser.add_argument("--email")
    parser.add_argument("--password")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="log in with --email/--password and print the token")
    sub.add_parser("homes", help="list homes, rooms and devices")
    p_state = sub.add_parser("state", help="decoded state of a gateway")
    p_state.add_argument("mac")
    p_raw = sub.add_parser("raw", help="raw get_state reply")
    p_raw.add_argument("mac")
    p_watch = sub.add_parser("watch", help="stream live events")
    p_watch.add_argument("--home", help="home id (default: first home)")
    p_set = sub.add_parser("set", help="send a SetState command")
    p_set.add_argument("mac")
    p_set.add_argument("--node", type=int, default=0)
    p_set.add_argument("--kind", default="ac", choices=["ac", "fancoil", "thermostat"])
    p_set.add_argument("--power", choices=["on", "off"])
    p_set.add_argument("--mode", choices=[m.name.lower() for m in HvacMode if m])
    p_set.add_argument("--fan", choices=[f.name.lower() for f in FanSpeed if f])
    p_set.add_argument("--temp", type=float)
    p_set.add_argument("--swing", choices=["on", "off"])
    p_set.add_argument("--erv", choices=["on", "off"])
    p_set.add_argument("--silent", choices=["on", "off"])
    p_manual = sub.add_parser("manual", help="enable/disable manual override for a node")
    p_manual.add_argument("mac")
    p_manual.add_argument("enabled", choices=["on", "off"])
    p_manual.add_argument("--node", type=int, default=0)
    args = parser.parse_args()

    token = args.token
    if args.token_file:
        token = Path(args.token_file).read_text().strip()

    async with aiohttp.ClientSession() as session:
        rest = InnovaRestClient(session, token=token)
        if args.cmd == "login" or (not token and args.email and args.password):
            token = await rest.login(args.email, args.password)
            if args.cmd == "login":
                print(token)
                return 0
        if not rest.token:
            parser.error("a token (INNOVA_TOKEN / --token / --token-file) or --email/--password is required")

        grpc_client = InnovaGrpcClient(lambda: rest.token)
        try:
            if args.cmd == "homes":
                print(_dump(await rest.get_homes_raw()))
            elif args.cmd == "raw":
                raw = await grpc_client.send_device(mac_to_bytes(args.mac), 0, messages.request_get_state())
                print("hex:", raw.hex())
                print(_dump(Message(raw).to_debug() if raw else {}))
            elif args.cmd == "state":
                response = await grpc_client.get_state(mac_to_bytes(args.mac))
                print(_dump({"error": response.error_code, "message": response.error_message, "gateway": response.gateway, "nodes": response.nodes}))
            elif args.cmd == "watch":
                homes = await rest.get_homes()
                home_id = args.home or homes[0].id
                print(f"watching home {home_id} ... Ctrl-C to stop", file=sys.stderr)
                async for event in grpc_client.subscribe_events(uuid_to_bytes(home_id)):
                    print(_dump({"mac": mac_to_str(event.mac), "node": event.node_id, "kind": event.kind, "connection": event.connection, "patch": event.patch, "raw": event.raw}))
            elif args.cmd == "set":
                on = lambda v: None if v is None else v == "on"  # noqa: E731
                request = messages.request_set_state(
                    args.kind,
                    power=on(args.power),
                    temperature_setpoint=args.temp,
                    hvac_mode=HvacMode[args.mode.upper()] if args.mode else None,
                    fan_speed=FanSpeed[args.fan.upper()] if args.fan else None,
                    flap_swing=on(args.swing),
                    erv=on(args.erv),
                    silent_mode=on(args.silent),
                )
                raw = await grpc_client.send_device(mac_to_bytes(args.mac), args.node, request)
                print("reply hex:", raw.hex() if raw else "<empty>")
                if raw:
                    print(_dump(Message(raw).to_debug()))
            elif args.cmd == "manual":
                raw = await grpc_client.send_device(mac_to_bytes(args.mac), args.node, messages.request_set_manual_mode(args.node, args.enabled == "on"))
                print("reply hex:", raw.hex() if raw else "<empty>")
        finally:
            await grpc_client.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
