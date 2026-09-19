"""Pretty-print one API response read from stdin. Used by scripts/demo.sh.

    curl -s localhost:8787/v1/hub | python tools/summarize.py hub
"""

from __future__ import annotations

import json
import sys
from typing import Any

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
RESET = "\033[0m"


def show_hub(h: dict[str, Any]) -> None:
    print(f"  {BOLD}{h['hub_name']}{RESET}  mode={h['mode']}  healthy={h['healthy']}")
    print(f"  anchored to {h['hub_ansname']}   (master {h['master_ansname']})")
    print(f"  site {h['site_id']} at {h['site_address']}")
    s = h["sensor"]
    print(
        f"  sensor: source={s['source']} simulated={s['simulated']} live={s['live']} "
        f"rate={s['frame_rate_hz']}Hz baseline_healthy={s['baseline_healthy']}"
    )
    print(f"  {DIM}{s['detail']}{RESET}")
    states = sorted({a["reachability"] for a in h["agents"]})
    print(f"  agents: {len(h['agents'])} in roster, reachability {states}")
    for a in h["agents"]:
        print(f"    tier {a['tier']}  {a['name']:20s} {a['ansname']:34s} {a['reachability']}")


def show_state(s: dict[str, Any]) -> None:
    print(f"  site {s['site_id']} captured_at {s['captured_at']}")
    cal = s["calibration"]
    print(f"  calibration: healthy={cal['healthy']} baseline_age_s={cal['baseline_age_s']}")
    for p in s["presences"]:
        v = p["vitals"]
        print(
            f"  {p['presence_id']}: {p['state']:18s} zone={p['position']['zone']:13s} "
            f"moving={str(p['moving']):5s} resp={v['respiration']:13s} "
            f"bpm={v['breathing_bpm']} class={p['presence_class']} "
            f"source={p['provenance']['source']} simulated={p['provenance']['simulated']}"
        )
    e = s.get("environment")
    if e:
        pr = e["provenance"]
        print(
            f"  environment: CO {e['co_ppm']} ppm smoke={e['smoke_detected']} "
            f"source={pr['source']} source_class={pr['source_class']} simulated={pr['simulated']}"
        )
    print(f"  floorplan: {len(s['floorplan']['rooms'])} rooms, "
          f"{s['floorplan']['width_m']}m x {s['floorplan']['depth_m']}m")


def show_replay(r: dict[str, Any]) -> None:
    print(
        f"  incident {r['incident_id']}  sealed={r['sealed']}  "
        f"entries={len(r['entries'])}  verifications={len(r['verifications'])}"
    )
    print(f"  caller {r['caller_ansname']} at {r['site_address']}")
    print(f"  hash chain: {r['hash_algorithm']}, root_hash={r['root_hash']}")
    print(
        f"  scitt_receipt={r['scitt_receipt']}  "
        f"{DIM}(null until the SCITT submit path exists; see TODO(ans) in models/incident.py){RESET}"
    )
    discarded = [v for v in r["verifications"] if v["decision"] == "DISCARDED"]
    print(f"  {RED}{BOLD}discarded claims preserved in the record: {len(discarded)}{RESET}")
    for v in discarded:
        print(f"    - \"{v['claim']['statement']}\"")
        print(f"      from {v['agent']['ansname']} ({v['agent']['recommended_profile']})")
        print(f"      {v['reason']}")
    print(f"  first three entries:")
    for e in r["entries"][:3]:
        print(f"    #{e['seq']} {e['kind']:13s} {e['summary'][:78]}")
        print(f"       hash {e['entry_hash'][:24]}...  prev {str(e['prev_hash'])[:24]}")


def show_incident_id(h: dict[str, Any]) -> None:
    print(h.get("active_incident_id") or "")


def main() -> None:
    what = sys.argv[1] if len(sys.argv) > 1 else "hub"
    body = json.load(sys.stdin)
    {
        "hub": show_hub,
        "state": show_state,
        "replay": show_replay,
        "incident_id": show_incident_id,
    }[what](body)


if __name__ == "__main__":
    main()
