"""Load the saved policy in a clean process and evaluate a held-out seed."""

import argparse
from pathlib import Path

from train_hierarchical import make_hier_env

from flax import serialization
import numpy as np
import rm75

from reproduce import read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("seed", type=int)
    args = parser.parse_args()

    metadata = read_json(args.run / "config.json")
    raw, env = make_hier_env(
        args.seed, task_kwargs={"safety_penalty": metadata.get("safety_penalty", 1.0)},
    )
    try:
        template = rm75.initialize_agent(
            env, metadata["agent_config"], metadata["seed"], metadata["discount"],
        )
        agent = serialization.from_bytes(template, (args.run / "checkpoint.msgpack").read_bytes())
        with np.load(args.run / "reload_probe.npz", allow_pickle=False) as probe:
            expected = probe["action"]
            actual = np.asarray(agent.eval_actions(probe["observation"]))
        same = bool(np.array_equal(expected, actual))
        args.output.mkdir(parents=True, exist_ok=False)
        rm75.write_json(args.output / "reload_check.json", {
            "deterministic_actions_equal": same,
            "max_abs_error": float(np.max(np.abs(actual - expected))),
        })
        if not same:
            raise ValueError("Checkpoint action does not match the saved deterministic probe")
        rm75.evaluate(raw, env, agent.eval_actions, args.output, record_video=False)
    finally:
        raw.close()


if __name__ == "__main__":
    main()
