"""Run or inspect the T-0055 single-note simulation baseline."""

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
ROBOPIANIST = WORKSPACE / "third_party" / "robopianist"
MESH_ROOT = WORKSPACE / "src/ros2_rm_robot/rm_mujoco/meshes"
MESH_PREFIX = "robopianist/models/hands/third_party/rm75_l20/meshes/"
TASK = "robopianist/suite/tasks/piano_with_rm75_l20.py"
WORKSPACE_ADAPTERS = {
    "robopianist/__init__.py", "robopianist/models/hands/rm75_l20.py", TASK,
}
STEPS = 20_000
HOLDOUT_SEED = 202
PITCH = 72


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def stage_sources(robopianist, training, destination=None):
    """Check content pins, including local changes over the upstream commits."""
    lock = read_json(HERE / "sources.json")
    for name, source, prefix in (
        ("robopianist", robopianist, ""),
        ("training", training, "training"),
    ):
        for relative, expected in lock[name]["files"].items():
            path = source / relative
            if name == "robopianist":
                if relative in WORKSPACE_ADAPTERS:
                    path = ROBOPIANIST / relative
                elif relative.startswith(MESH_PREFIX) and not path.is_file():
                    path = MESH_ROOT / relative.removeprefix(MESH_PREFIX)
            data = path.read_bytes()
            if path.suffix in {".py", ".xml", ".json"}:
                data = data.replace(b"\r\n", b"\n")
            if hashlib.sha256(data).hexdigest() != expected:
                base = lock[name]["base_commit"]
                raise ValueError(f"Source differs from lock: {path} (upstream base {base})")
            if destination is not None:
                target = destination / prefix / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)


def check_result(run, evaluation, *, smoke=False, reload_path=None):
    reload = read_json(reload_path or evaluation / "reload_check.json")
    if reload["deterministic_actions_equal"] is not True or reload["max_abs_error"] != 0:
        raise ValueError("Deterministic actions differ after checkpoint reload")
    summary = read_json(run / "training_summary.json")
    if (summary["physics_invalid_steps"] != 0 or summary["updates"] < 1
            or summary["initial_actor_sha256"] == summary["final_actor_sha256"]):
        raise ValueError("Training did not produce an updated policy with zero physics failures")
    report = read_json(evaluation / "evaluation.json")
    if (report["termination_reason"] != "score_complete"
            or report["executed_steps"] != report["score_steps"]):
        raise ValueError("Evaluation did not finish the score")
    if smoke:
        return {"steps": summary["steps"], "updates": summary["updates"], "reload_equal": True}

    if summary["steps"] != STEPS or summary["updates"] != 19_500:
        raise ValueError("Expected the 20,000-step baseline with 19,500 updates")
    if (report["f1"] != 1 or report["onset_recall"] != 1 or report["missed_notes"] != 0
            or report["false_positive_key_frames"] != 0 or report["collision_frames"] != 0
            or report["joint_limit_frames"] != 0):
        raise ValueError("The policy failed the held-out single-note performance gate")
    notes = report["notes"]
    if len(notes) != 1 or notes[0]["pitch"] != PITCH:
        raise ValueError(f"Expected a single note at MIDI {PITCH}")
    events = read_json(evaluation / "midi_events.json")
    if [(event["type"], event["note"]) for event in events] != [
        ("NoteOn", PITCH), ("NoteOff", PITCH),
    ]:
        raise ValueError("Expected a single physical press and release with no extra notes")
    onset = events[0]["time"] - notes[0]["start"]
    release = events[1]["time"] - notes[0]["end"]
    if not (abs(onset) <= .020 and abs(release) <= .075):
        raise ValueError(f"Physical MIDI timing outside T-0055 bounds: {onset=:.4f}s {release=:.4f}s")
    return {"f1": report["f1"], "onset_ms": round(onset * 1000, 3),
            "release_ms": round(release * 1000, 3), "collision_frames": 0,
            "joint_limit_frames": 0, "reload_equal": True}


def check_archived_result(run):
    report = run / "evaluations" / f"holdout_seed{HOLDOUT_SEED}"
    # This historical run wrote the reload result at the run root.
    return check_result(run, report, reload_path=run / "reload_check.json")


def check_dependencies():
    requirements = (HERE / "requirements.txt").read_text(encoding="utf-8")
    mismatches = []
    for line in requirements.splitlines():
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==", 1)
        try:
            installed = version(name)
        except PackageNotFoundError:
            installed = "missing"
        if installed != expected:
            mismatches.append(f"{name}=={expected} (installed: {installed})")
    if mismatches:
        raise ValueError("Use the pinned Python environment. " + ", ".join(mismatches))


def run_experiment(args):
    if sys.platform != "linux" or sys.version_info[:2] != (3, 10):
        raise ValueError("Training and replay require Linux with Python 3.10")
    check_dependencies()
    soundfont = args.soundfont or (
        args.robopianist / "robopianist/soundfonts/TimGM6mb.sf2"
    )
    if args.soundfont is not None and not soundfont.is_file():
        raise ValueError(f"SoundFont missing: {soundfont}")

    with TemporaryDirectory(prefix="droq-single-note-") as temp:
        stage = Path(temp)
        stage_sources(args.robopianist, args.training, stage)
        env = os.environ.copy()
        if soundfont.is_file():
            soundfont_target = stage / "robopianist/soundfonts/TimGM6mb.sf2"
            soundfont_target.parent.mkdir()
            soundfont_target.write_bytes(soundfont.read_bytes())
            env["ROBOPIANIST_SOUNDFONT"] = str(soundfont_target)
        env.update(PYTHONPATH=os.pathsep.join((str(stage), str(stage / "training"))),
                   JAX_PLATFORMS="cpu", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")

        run = args.run.resolve()
        if args.command == "train":
            steps = 600 if args.smoke else STEPS
            subprocess.run([
                sys.executable, "-B", str(HERE / "train_hierarchical.py"),
                "--output", str(run), "--steps", str(steps),
                "--eval-interval", str(steps if args.smoke else 1000),
            ], env=env, cwd=stage, check=True)
            evaluation = run / f"reloaded_seed{HOLDOUT_SEED}"
        else:
            evaluation = args.output.resolve()
        subprocess.run([
            sys.executable, "-B", str(HERE / "verify_checkpoint.py"),
            str(run), str(evaluation), str(HOLDOUT_SEED),
        ], env=env, cwd=stage, check=True)
        return check_result(run, evaluation, smoke=args.smoke)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--robopianist", type=Path, default=ROBOPIANIST,
        help="Override the bundled runtime with compatible sources",
    )
    parser.add_argument(
        "--training", type=Path, default=HERE.parent / "robopianist_rl",
        help="Override the training sources shipped in the workspace",
    )
    parser.add_argument("--soundfont", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-sources", help="Check the pinned source files without importing MuJoCo")
    train = commands.add_parser("train", help="Train and replay the checkpoint in a fresh process")
    replay = commands.add_parser("replay", help="Replay a run into a new output directory")
    report = commands.add_parser("check-result", help="Check existing result JSON without running MuJoCo")
    for command in (train, replay, report):
        command.add_argument("run", type=Path)
        command.add_argument("--smoke", action="store_true", help="Check plumbing without an F1 or MIDI timing gate")
    replay.add_argument("--output", type=Path, required=True)
    report.add_argument("--archived", action="store_true", help="Use the T-0055 archival report layout")
    args = parser.parse_args()
    try:
        if args.command == "check-sources":
            stage_sources(args.robopianist, args.training)
            print("Source locks verified")
        elif args.command == "check-result":
            if args.archived:
                if args.smoke:
                    parser.error("--archived is for the complete T-0055 baseline")
                result = check_archived_result(args.run)
            else:
                evaluation = args.run / f"reloaded_seed{HOLDOUT_SEED}"
                result = check_result(args.run, evaluation, smoke=args.smoke)
            print(json.dumps(result))
        else:
            print(json.dumps(run_experiment(args)))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
