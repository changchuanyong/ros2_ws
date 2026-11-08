#!/usr/bin/env python3
"""Plan per-note fingering, arm waypoints and full L20 hand states in MuJoCo.

Input is the canonical `piano_fingering/1` event file produced by
`import_pianovam.py` or `pig_score.py`.  Output is `piano_performance/1`,
played by `run_performance.py`.  This is an offline simulation planner; it does
not use MoveIt or the real robot.

Usage:
    python3 plan_performance.py --score song.fingering.yaml \
        --output song.performance.yaml
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:  # source-tree use before sourcing an install
    get_package_share_directory = None

from rm_mujoco.fingering import FingeringPlanner, PianoHandModel
from rm_mujoco.performance import load_events, summarize_plan, write_plan


def _default_package():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_mujoco"))
        except Exception:
            pass
    return Path(__file__).resolve().parents[1]


def _default_pose_file():
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("rm_piano_player")) / \
                "config/right_hand_ode_to_joy.yaml"
        except Exception:
            pass
    return Path(__file__).resolve().parents[2] / \
        "rm_piano_player/config/right_hand_ode_to_joy.yaml"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--score", type=Path, required=True,
                        help="piano_fingering/1 event YAML")
    parser.add_argument("--output", type=Path, required=True,
                        help="piano_performance/1 output YAML")
    parser.add_argument("--package", type=Path, default=None,
                        help="rm_mujoco source or share directory")
    parser.add_argument("--scene-config", type=Path, default=None)
    parser.add_argument("--pose-file", type=Path, default=None,
                        help="right-hand READY/PRESS calibration YAML")
    parser.add_argument("--hand", choices=("left", "right"), default="right")
    parser.add_argument("--fingering-mode", choices=("auto", "fixed"), default="auto")
    parser.add_argument("--left-max-note", type=int, default=59)
    parser.add_argument("--beam-width", type=int, default=8)
    parser.add_argument("--candidate-limit", type=int, default=3)
    parser.add_argument("--prior-weight", type=float, default=2.0)
    parser.add_argument("--travel-weight", type=float, default=1.0)
    parser.add_argument("--tempo-scale", type=float, default=1.0)
    parser.add_argument("--start-padding", type=float, default=1.0)
    parser.add_argument("--arm-lead", type=float, default=0.10)
    parser.add_argument("--press-lead", type=float, default=0.05)
    parser.add_argument("--release-lead", type=float, default=0.07)
    parser.add_argument("--hand-transition", type=float, default=0.04)
    parser.add_argument("--min-hand-interval", type=float, default=0.04)
    parser.add_argument("--timing-tolerance", type=float, default=0.03)
    args = parser.parse_args(argv)
    for name in ("tempo_scale", "start_padding", "arm_lead", "press_lead",
                 "release_lead", "hand_transition", "min_hand_interval",
                 "timing_tolerance", "prior_weight", "travel_weight"):
        value = getattr(args, name)
        if not math.isfinite(value) or value < 0:
            parser.error(f"{name} must be finite and non-negative")
    if args.tempo_scale <= 0:
        parser.error("tempo_scale must be positive")
    if args.beam_width <= 0 or args.candidate_limit <= 0:
        parser.error("beam_width and candidate_limit must be positive")
    model = planner = None
    scene_config = pose_file = None
    status = 1
    failure = None
    started = time.monotonic()
    try:
        events = load_events(args.score)
        package = args.package or _default_package()
        scene_config = args.scene_config or package / "config/piano_scene.yaml"
        pose_file = args.pose_file or _default_pose_file()
        model = PianoHandModel(package, scene_config, pose_file)
        planner = FingeringPlanner(
            model, beam_width=args.beam_width,
            candidate_limit=args.candidate_limit,
            prior_weight=args.prior_weight,
            travel_weight=args.travel_weight,
            start_padding=args.start_padding,
            arm_lead=args.arm_lead,
            press_lead=args.press_lead,
            release_lead=args.release_lead,
            hand_transition=args.hand_transition,
            min_hand_interval=args.min_hand_interval,
            timing_tolerance=args.timing_tolerance,
            tempo_scale=args.tempo_scale, fingering_mode=args.fingering_mode)
        plan = planner.plan(
            events["events"], hand=args.hand, left_max_note=args.left_max_note,
            source=args.score)
        write_plan(args.output, plan)
        status = 0
    except (OSError, RuntimeError, ValueError) as error:
        failure = str(error)
    try:
        diagnostics_path = args.output.with_suffix(".diagnostics.json")
        diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        identity_paths = (args.score, scene_config, pose_file, Path(__file__),
                          Path(sys.modules[PianoHandModel.__module__].__file__))
        diagnostics_path.write_text(json.dumps({
            "arguments": sys.argv if argv is None else list(argv),
            "score_sha256": hashlib.sha256(args.score.read_bytes()).hexdigest()
            if args.score.is_file() else None,
            "sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in identity_paths if path is not None and path.is_file()},
            "wall_seconds": time.monotonic() - started,
            "exit_code": status, "failure": failure,
            "geometry": model.geometry_diagnostics if model else [],
            "trials": planner.diagnostics if planner else [],
        }, indent=2), encoding="utf-8")
    except OSError as error:
        print(f"ERROR saving diagnostics: {error}", file=sys.stderr)
        return 1
    if failure is not None:
        print(f"ERROR {failure}", file=sys.stderr)
        return status
    print(f"WROTE {args.output} {json.dumps(summarize_plan(plan), sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
