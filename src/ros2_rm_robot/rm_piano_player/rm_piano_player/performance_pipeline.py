"""Run the existing offline planner and simulator through one staged entry point."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import yaml

from rm_mujoco.performance import load_plan

from .performance_evaluation import evaluate_events, expected_from_plan
from .score_io import load_score


def _write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False),
                         encoding="utf-8")
    temporary.replace(path)


def _package_path():
    source = Path(__file__).resolve().parents[2] / "rm_mujoco"
    if (source / "scripts/plan_performance.py").is_file():
        return source
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory("rm_mujoco"))


def _script(package, name):
    for directory in (package / "scripts", package.parent.parent / "lib/rm_mujoco"):
        path = directory / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"cannot find {name} for package {package}")


def _input(status, name, path):
    path = path.resolve()
    status["inputs"][name] = {"path": str(path),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _child(name, command, output, status):
    log = output / f"{name}.log"
    entry = {"stage": name, "command": command, "log": str(log), "exit_code": None}
    status["steps"].append(entry)
    _write_json(output / "status.json", status)
    print(f"Running {name}; log={log}", flush=True)
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as stream:
        with subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1) as process:
            try:
                for line in process.stdout:
                    stream.write(line)
                    print(line, end="", flush=True)
                returncode = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
    entry["wall_seconds"] = time.monotonic() - started
    entry["exit_code"] = returncode
    _write_json(output / "status.json", status)
    print(f"Finished {name} in {entry['wall_seconds']:.1f}s; exit={returncode}", flush=True)
    return returncode


def _run(args, output, status):
    stage = args.stage
    plan_path = args.plan
    edges_path = args.edges
    if stage in ("prepare", "plan", "all"):
        status["stage"] = "prepare"
        _input(status, "score", args.score)
        score = load_score(args.score, args.hand, args.left_max_note)
        normalized = output / "score.fingering.yaml"
        normalized.write_text(yaml.safe_dump(score, sort_keys=False, allow_unicode=True),
                              encoding="utf-8")
        status["score_events"] = len(score["events"])
        if stage == "prepare":
            return 0
    if stage in ("plan", "all", "simulate"):
        package = (args.package or _package_path()).resolve()
        scene = (args.scene_config or package / "config/piano_scene.yaml").resolve()
        _input(status, "scene", scene)
        _input(status, "model", package / "models/rm_75_6fb_v_dual_l20.xml")
    if stage in ("plan", "all"):
        status["stage"] = "plan"
        pose = (args.pose_file or package / "config/right_hand_piano_sim.yaml").resolve()
        _input(status, "pose", pose)
        plan_path = output / "performance.yaml"
        command = [sys.executable, str(_script(package, "plan_performance.py")),
                   "--score", str(normalized), "--output", str(plan_path),
                   "--package", str(package), "--scene-config", str(scene),
                   "--pose-file", str(pose), "--hand", args.hand,
                   "--left-max-note", str(args.left_max_note),
                   "--fingering-mode", args.fingering_mode,
                   "--tempo-scale", str(args.tempo_scale),
                   "--timing-tolerance", str(args.timing_tolerance),
                   "--planning-budget-sec", str(args.planning_budget_sec),
                   "--beam-width", str(args.beam_width),
                   "--candidate-limit", str(args.candidate_limit)]
        code = _child("plan", command, output, status)
        if code:
            raise RuntimeError(f"planning failed (exit {code}); see plan.log and "
                               "performance.diagnostics.json")
        if stage == "plan":
            load_plan(plan_path)
            _input(status, "plan", plan_path)
            return 0
    _input(status, "plan", plan_path)
    plan = load_plan(plan_path)
    tolerance = plan["metadata"].get("timing_tolerance_sec", 0.03)
    if tolerance <= 0 or args.match_window < tolerance:
        raise ValueError("require 0 < plan timing tolerance <= match window")
    simulation_passed = None
    if stage in ("all", "simulate"):
        status["stage"] = "simulate"
        simulation = output / "simulation"
        command = [sys.executable, str(_script(package, "run_performance.py")),
                   "--plan", str(plan_path.resolve()), "--output", str(simulation),
                   "--package", str(package), "--scene-config", str(scene)]
        code = _child("simulate", command, output, status)
        if code not in (0, 3):
            raise RuntimeError(f"simulation failed (exit {code}); see simulate.log")
        report = json.loads((simulation / "report.json").read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(report.get("passed"), bool):
            raise ValueError("simulation report must contain a boolean passed field")
        simulation_passed = code == 0 and report["passed"] is True
        edges_path = simulation / "key_edges.json"
    status["stage"] = "evaluate"
    _input(status, "edges", edges_path)
    edges = json.loads(edges_path.read_text(encoding="utf-8"))
    if not isinstance(edges, list):
        raise ValueError("edges file must contain a JSON list")
    source = args.source if stage == "evaluate" else "simulation"
    evaluation = evaluate_events(expected_from_plan(plan), edges, source=source,
                                 tolerance=tolerance, match_window=args.match_window)
    _write_json(output / "evaluation.json", evaluation)
    status["evaluation_passed"] = evaluation["passed"]
    status["simulation_passed"] = simulation_passed
    return 0 if evaluation["passed"] and simulation_passed is not False else 3


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("prepare", "plan", "simulate", "evaluate", "all"),
                        default="all")
    parser.add_argument("--output", type=Path, required=True, help="new, exclusive run directory")
    parser.add_argument("--score", type=Path, help="MIDI or piano_fingering/1 YAML")
    parser.add_argument("--plan", type=Path, help="existing plan for simulate/evaluate")
    parser.add_argument("--edges", type=Path, help="raw key edges for evaluate")
    parser.add_argument("--source", choices=("simulation", "recorded", "synthetic"),
                        help="required provenance label for evaluate")
    parser.add_argument("--package", type=Path, help="rm_mujoco source or installed share path")
    parser.add_argument("--scene-config", type=Path)
    parser.add_argument("--pose-file", type=Path)
    parser.add_argument("--hand", choices=("left", "right", "both"), default="right")
    parser.add_argument("--left-max-note", type=int, default=59)
    parser.add_argument("--fingering-mode", choices=("auto", "fixed"), default="auto")
    parser.add_argument("--tempo-scale", type=float, default=1.0,
                        help="planning time multiplier; larger means slower")
    parser.add_argument("--planning-budget-sec", type=float, default=300.0)
    parser.add_argument("--beam-width", type=int, default=8,
                        help="number of candidate prefixes retained per onset")
    parser.add_argument("--candidate-limit", type=int, default=3,
                        help="finger choices considered per note")
    parser.add_argument("--timing-tolerance", type=float, default=0.03,
                        help="planning tolerance; existing plans retain their own value")
    parser.add_argument("--match-window", type=float, default=0.15)
    args = parser.parse_args(argv)
    required = {"prepare": ("score",), "plan": ("score",), "all": ("score",),
                "simulate": ("plan",), "evaluate": ("plan", "edges", "source")}
    for name in required[args.stage]:
        if getattr(args, name) is None:
            parser.error(f"--{name} is required for {args.stage}")
    for name in ("tempo_scale", "planning_budget_sec", "timing_tolerance", "match_window"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"{name} must be finite and positive")
    if args.beam_width <= 0 or args.candidate_limit <= 0:
        parser.error("beam-width and candidate-limit must be positive")
    if not 21 <= args.left_max_note <= 108:
        parser.error("left-max-note must be 21..108")
    if args.stage in ("plan", "all") and args.match_window < args.timing_tolerance:
        parser.error("match-window must be at least timing-tolerance")
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        print(f"ERROR creating new output directory: {error}", file=sys.stderr)
        return 1
    status = {"format": "piano_pipeline/1", "state": "running", "stage": args.stage,
              "inputs": {}, "steps": [], "exit_code": None,
              "arguments": {key: str(value) if isinstance(value, Path) else value
                            for key, value in vars(args).items()}}
    code = 1
    try:
        _write_json(output / "status.json", status)
        code = _run(args, output, status)
        status["state"] = "completed" if code == 0 else "failed_validation"
    except (OSError, ValueError, RuntimeError, ImportError, yaml.YAMLError) as error:
        status.update(state="failed", error=str(error))
        print(f"ERROR during {status['stage']}: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        code = 130
        status.update(state="interrupted", error="interrupted by user")
    finally:
        status["exit_code"] = code
        _write_json(output / "status.json", status)
    print(f"RESULT state={status['state']} status={output / 'status.json'}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
