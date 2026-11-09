#!/usr/bin/env python3
"""Paired reference/policy robustness with frame-level F1 and physical acceptance."""

import argparse
import json
from pathlib import Path

from stable_baselines3 import PPO

from train_piano_rl import default_package, evaluate, sha256, load_experiment
from rm_mujoco.piano_rl import PianoResidualEnv, INTERFACE_VERSION
from verify_two_tigers import BASELINE, load_baseline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--manifest", type=Path,
                        help="evaluate the sealed test recordings instead of the fixed song")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bias", type=float, default=0.5)
    parser.add_argument("--seeds", type=int, nargs="+", default=[101, 102, 103])
    args = parser.parse_args()
    package = (args.package or default_package()).resolve()
    if args.manifest is None:
        load_baseline(package)
        plans = [package / BASELINE / "performance.yaml"]
    else:
        plans = load_experiment(args.manifest)["test"]
        if not plans:
            parser.error("manifest must contain held-out test recordings")
    config = json.loads((args.model.parent / "config.json").read_text())
    if config.get("interface_version") != INTERFACE_VERSION:
        parser.error("model interface changed; use its original frozen source for old models")
    if args.manifest is not None and config["manifest_sha256"] != sha256(args.manifest):
        parser.error("test manifest differs from the training manifest")
    args.output.mkdir(parents=True, exist_ok=False)
    model = PPO.load(args.model, device="cpu")
    spec = {"scope": ("held_out_recordings_actuator_bias" if args.manifest
                      else "same_song_actuator_bias_only"), "bias_units": args.bias,
            "seeds": args.seeds, "model_sha256": sha256(args.model),
            "note": "synthetic command offset, not a measured hardware uncertainty"}
    (args.output / "protocol.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    rows = []
    nominal_by_plan = {}
    for bias, seeds in ((0.0, [0]), (args.bias, args.seeds)):
        for seed in seeds:
            for index, plan in enumerate(plans):
                env = PianoResidualEnv(plan, package,
                                       control_dt=config["control_dt"], residual=config["residual"],
                                       robopianist_reward=config["robopianist_reward"], command_bias=bias)
                env.threshold_wrong = config.get("threshold_wrong", False)
                try:
                    if bias:
                        env.reset(seed=seed)
                        env.set_nominal_trace(nominal_by_plan[str(plan)])
                    folder = args.output / f"task{index}_bias_{bias}_seed_{seed}"
                    row = {"task": str(plan), "bias": bias, "seed": seed}
                    for label, policy in (("reference", None), ("policy", model)):
                        row[label] = evaluate(env, policy, folder / label, seed=seed)
                    if not bias:
                        nominal_by_plan[str(plan)] = env.nominal_qpos
                    rows.append(row)
                    (args.output / "comparison.json").write_text(
                        json.dumps({"protocol": spec, "pairs": rows}, indent=2), encoding="utf-8")
                    print(json.dumps({"bias": bias, "seed": seed,
                                      "reference_passed": row["reference"]["passed"],
                                      "policy_passed": row["policy"]["passed"]}), flush=True)
                finally:
                    env.close()


if __name__ == "__main__":
    main()
