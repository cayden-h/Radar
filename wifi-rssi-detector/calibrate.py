"""Labeled RSSI capture and still-vs-walk comparison, so classifier
thresholds come from data instead of a guess."""

import argparse
import json
import time

from collector import MacWifiCollector
from features import sliding_window_features


def capture(seconds, label, poll_hz=3.0):
    collector = MacWifiCollector(poll_hz=poll_hz, buffer_seconds=seconds + 5.0)
    collector.start()
    time.sleep(seconds)
    collector.stop()
    samples = collector.snapshot()
    return {"label": label, "samples": [[ts, rssi] for ts, rssi in samples]}


def summarize(samples, window_seconds=12.0):
    windows = sliding_window_features(samples, window_seconds=window_seconds, step_seconds=1.0)
    windows = [w for w in windows if w["n"] >= 2]

    def stats(key):
        values = [w[key] for w in windows]
        if not values:
            return {"min": 0.0, "mean": 0.0, "max": 0.0}
        return {"min": min(values), "mean": sum(values) / len(values), "max": max(values)}

    return {"variance": stats("variance"), "motion_energy": stats("motion_energy")}


def suggest_thresholds(still_summary, walk_summary):
    return {
        "present_variance_ratio": (still_summary["variance"]["mean"] + walk_summary["variance"]["mean"]) / 2,
        "active_motion_ratio": (still_summary["motion_energy"]["mean"] + walk_summary["motion_energy"]["mean"]) / 2,
    }


def _cmd_capture(args):
    result = capture(seconds=args.seconds, label=args.label, poll_hz=args.poll_hz)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Captured {len(result['samples'])} samples labeled '{args.label}' -> {args.out}")


def _cmd_compare(args):
    with open(args.still) as f:
        still = json.load(f)
    with open(args.walk) as f:
        walk = json.load(f)

    still_summary = summarize([tuple(s) for s in still["samples"]])
    walk_summary = summarize([tuple(s) for s in walk["samples"]])

    print("=== still ===")
    print(json.dumps(still_summary, indent=2))
    print("=== walk ===")
    print(json.dumps(walk_summary, indent=2))

    thresholds = suggest_thresholds(still_summary, walk_summary)
    print("=== suggested thresholds (paste into classifier.py) ===")
    print(json.dumps(thresholds, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Labeled RSSI calibration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--label", required=True)
    capture_parser.add_argument("--seconds", type=float, default=10.0)
    capture_parser.add_argument("--poll-hz", type=float, default=3.0)
    capture_parser.add_argument("--out", required=True)
    capture_parser.set_defaults(func=_cmd_capture)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("still")
    compare_parser.add_argument("walk")
    compare_parser.set_defaults(func=_cmd_compare)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
