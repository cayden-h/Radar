"""A small websocket client for WS /v1/stream.

Prints one line per event, so you can watch the scripted incident from a
terminal without the iOS app. Used by scripts/demo.sh.

    uv run python tools/ws_probe.py --url ws://127.0.0.1:8787/v1/stream --seconds 60
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import websockets

# ANSI, for the demo. Verification results are the point of the stream, so they
# get colour; state ticks are noise and are summarised to one line.
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"


def _fmt(envelope: dict[str, Any], show_state: bool) -> str | None:
    payload = envelope["payload"]
    kind = payload["kind"]
    seq = envelope["seq"]
    prefix = f"{DIM}[{seq:04d}]{RESET} "

    if kind == "hello":
        return (
            prefix
            + f"{BOLD}hello{RESET} {payload['hub_name']} ({payload['hub_ansname']}) "
            + f"mode={payload['mode']} protocol=v{payload['stream_protocol_version']}"
        )

    if kind == "state":
        if not show_state:
            return None
        state = payload["state"]
        people = ", ".join(
            f"{p['presence_id']}:{p['state']}@{p['position']['zone']}" for p in state["presences"]
        )
        env = state.get("environment") or {}
        co = env.get("co_ppm")
        src = (env.get("provenance") or {}).get("source")
        return prefix + f"{DIM}state{RESET} {people} | CO {co} ppm (source={src})"

    if kind == "incident":
        inc = payload["incident"]
        line = (
            prefix
            + f"{YELLOW}{BOLD}incident{RESET} {payload['phase']} "
            + f"{inc['incident_type']} status={inc['status']} raised_by={inc['raised_by']}"
        )
        if inc.get("classification"):
            line += f"\n        {YELLOW}why:{RESET} {inc['classification']['reasoning']}"
        return line

    if kind == "verification":
        result = payload["result"]
        decision = result["decision"]
        colour = RED if decision == "DISCARDED" else GREEN
        agent = result["agent"]
        out = [
            prefix
            + f"{colour}{BOLD}verification {decision}{RESET} "
            + f"{agent['name']} <{agent['ansname']}> profile={agent['recommended_profile']}",
            f"        claim: {result['claim']['statement']}",
            f"        reason: {result['reason']}",
        ]
        for check in result["checks"]:
            mark = f"{GREEN}pass{RESET}" if check["passed"] else f"{RED}FAIL{RESET}"
            out.append(f"          {mark} {check['name']}: {check['detail']}")
        return "\n".join(out)

    if kind == "transcript":
        line = payload["line"]
        colour = CYAN if line["speaker"] == "caller" else BOLD
        claims = f" {DIM}claims={','.join(line['claim_ids'])}{RESET}" if line["claim_ids"] else ""
        return prefix + f"{colour}{line['speaker']}{RESET}: {line['text']}{claims}"

    if kind == "instruction":
        ins = payload["instruction"]
        urgent = f"{RED}!{RESET} " if ins["urgent"] else ""
        return prefix + f"{YELLOW}guidance{RESET} ({ins['origin']}) {urgent}{ins['text']}"

    if kind == "context":
        return prefix + f"{BOLD}context{RESET} resident: {payload['note']['text']}"

    if kind == "error":
        return prefix + f"{RED}error{RESET} {payload['code']}: {payload['message']}"

    return prefix + f"{kind} {json.dumps(payload)[:160]}"


async def run(url: str, seconds: float, show_state: bool) -> int:
    seen: dict[str, int] = {}
    try:
        async with websockets.connect(url) as socket:
            print(f"{DIM}connected to {url}{RESET}", flush=True)
            deadline = asyncio.get_running_loop().time() + seconds
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                except TimeoutError:
                    break
                envelope = json.loads(raw)
                seen[envelope["payload"]["kind"]] = seen.get(envelope["payload"]["kind"], 0) + 1
                rendered = _fmt(envelope, show_state)
                if rendered:
                    print(rendered, flush=True)
    except OSError as exc:
        print(f"{RED}could not connect: {exc}{RESET}", file=sys.stderr)
        return 1

    print(f"\n{BOLD}event counts by kind:{RESET} {json.dumps(seen, sort_keys=True)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch the Hawk Eye hub event stream.")
    parser.add_argument("--url", default="ws://127.0.0.1:8787/v1/stream")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument(
        "--show-state",
        action="store_true",
        help="Print interior state ticks too. Off by default; they arrive at 2 Hz.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.url, args.seconds, args.show_state)))


if __name__ == "__main__":
    main()
