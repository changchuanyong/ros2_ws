#!/usr/bin/env python3
"""Verify the frozen dual-hand 40-note performance in one continuous simulation.

This replays a calibrated performance, not a planner for arbitrary scores.
All outputs must go to a new directory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from rm_mujoco.performance import load_events, load_plan, write_plan


PACKAGE = Path(__file__).resolve().parents[1]
BASELINE = Path("examples/two_tigers_flat_palms/verified_40")


def default_package():
    if (PACKAGE / "models").is_dir():
        return PACKAGE
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory("rm_mujoco"))


def file_hash(path):
    """Ignore checkout newline conversion in text; keep binary assets exact."""
    raw = path.read_bytes()
    if path.suffix in (".py", ".yaml", ".xml"):
        raw = raw.replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def check_score(score, plan):
    """Reject dropped notes, finger changes and any nonuniform retiming."""
    metadata = plan["metadata"]
    if (metadata.get("tempo_scale") != 1.0
            or metadata.get("fingering_mode") != "fixed"
            or metadata.get("start_padding_sec") != 1.0
            or metadata.get("timing_tolerance_sec") != 0.03):
        raise ValueError("baseline requires fixed fingers, 1x, 1s padding and 30ms tolerance")
    hands = plan["hands"]
    if set(hands) != {"right", "left"}:
        raise ValueError("both hands are required")
    events = score["events"]
    actual = {}
    for side, hand in hands.items():
        for event in hand["events"]:
            key = (side, event["id"])
            if key in actual:
                raise ValueError(f"duplicate planned event {key}")
            actual[key] = event
    if (len(events) != 40 or len(actual) != 40
            or len(hands["right"]["events"]) != 32
            or len(hands["left"]["events"]) != 8):
        raise ValueError("expected exactly 32 right and 8 left notes")
    for event in events:
        planned = actual.get((event["hand"], event["id"]))
        if (planned is None or planned["note"] != event["note"]
                or planned["finger"] != event["finger"]
                or planned["prior_finger"] != event["finger"]
                or abs(planned["start_sec"] - event["start"] - 1.0) > 1e-9
                or abs(planned["end_sec"] - event["end"] - 1.0) > 1e-9):
            raise ValueError(f"score mismatch at event {event['id']}")


def load_baseline(package):
    baseline = package / BASELINE
    manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "two_tigers_verified/1":
        raise ValueError("unsupported baseline manifest")
    for name, expected in manifest["files"].items():
        path = package / name
        if not path.is_relative_to(package) or ".." in Path(name).parts:
            raise ValueError("manifest path must stay in package")
        if file_hash(path) != expected:
            raise ValueError(f"baseline file changed: {name}; revalidate before updating manifest")
    score = load_events(baseline / "score.yaml")
    plan = load_plan(baseline / "performance.yaml")
    check_score(score, plan)
    return plan, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="new output directory")
    args = parser.parse_args(argv)
    package = (args.package or default_package()).resolve()
    output = args.output.resolve()
    try:
        plan, manifest = load_baseline(package)
        output.mkdir(parents=True, exist_ok=False)
        plan["metadata"]["score"] = str(package / BASELINE / "score.yaml")
        plan["metadata"]["layout"] = str(package / "config/piano_scene.yaml")
        write_plan(output / "plan.yaml", plan)
        command = [sys.executable, str(package / "scripts/run_performance.py"),
                   "--package", str(package), "--plan", str(output / "plan.yaml"),
                   "--output", str(output / "playback")]
        started = time.monotonic()
        with (output / "run.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        evidence = {"command": command, "exit_code": result.returncode,
                    "elapsed_sec": time.monotonic() - started, "baseline": manifest}
        (output / "run.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print((output / "run.log").read_text(encoding="utf-8"), end="")
        if result.returncode:
            return result.returncode
        report = json.loads((output / "playback/report.json").read_text(encoding="utf-8"))
        if not report["passed"] or len(report["observed"]) != 40:
            raise ValueError("joint playback did not pass all 40 notes")
        print(f"VERIFIED 40/40: {output / 'playback/report.json'}")
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f"ERROR {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
