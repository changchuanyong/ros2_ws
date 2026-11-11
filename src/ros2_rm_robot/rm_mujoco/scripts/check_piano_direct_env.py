#!/usr/bin/env python3
"""Run random legal L20 actions through `PianoDirectEnv` without training."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

def _package_root():
    root = Path(__file__).resolve().parents[1]
    if (root / "models").is_dir():
        return root
    try:
        from ament_index_python.packages import get_package_share_directory
        return Path(get_package_share_directory("rm_mujoco"))
    except Exception:
        return root


PACKAGE = _package_root()
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.piano_direct import PianoDirectEnv  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    if args.steps < 1:
        parser.error("--steps must be positive")
    env = PianoDirectEnv.from_config(
        args.tasks, args.package, config_path=args.config,
        task_index=args.task_index)
    try:
        observation, info = env.reset(seed=args.seed)
        initial = {side: env.data.qpos[env.hand_model.hand_qpos[side]].copy()
                   for side in env.active_hands}
        last = {}
        edges = []
        for _ in range(args.steps):
            action = env.action_space.sample()
            observation, reward, terminated, truncated, last = env.step(action)
            edges.extend(last["edges"])
            if terminated or truncated:
                break
        change = {
            side: float(np.max(np.abs(
                env.data.qpos[env.hand_model.hand_qpos[side]] - initial[side])))
            for side in env.active_hands
        }
        result = {
            "task": info["task"],
            "observation_shape": list(observation.shape),
            "observation_finite": bool(np.isfinite(observation).all()),
            "action_scale": float(env.action_scale),
            "reward": float(reward),
            "reward_components": last.get("reward_components", {}),
            "reward_details": last.get("reward_details", {}),
            "hand_qpos_change": change,
            "arm_error_rad": float(last.get("arm_error_rad", 0.0)),
            "other_contacts": last.get("other_contacts", []),
            "key_violations": last.get("key_violations", []),
            "edges": edges,
            "terminated": bool(terminated),
            "truncated": bool(truncated),
        }
        print(json.dumps(result, indent=2))
        return 0
    finally:
        env.close()


if __name__ == "__main__":
    sys.exit(main())
