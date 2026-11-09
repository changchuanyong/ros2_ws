#!/usr/bin/env python3
"""Train/evaluate a simulation-only PianoVAM residual PPO policy in Conda."""

import argparse
from collections import Counter
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.performance import load_plan  # noqa: E402
from rm_mujoco.piano_rl import (  # noqa: E402
    PianoResidualEnv, PianoTaskCycle, REWARD_VERSION, INTERFACE_VERSION, episode_steps,
)


def default_package():
    if (PACKAGE / "models").is_dir():
        return PACKAGE
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory("rm_mujoco"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_experiment(path):
    """Fail closed on changed sources, cross-recording leakage, or altered timing."""
    path = Path(path).resolve()
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("format") not in {"piano_rl_dataset/1", "piano_rl_dataset/2"}:
        raise ValueError("expected piano_rl_dataset/1 or /2 manifest")
    dataset = (path.parent / spec["dataset"]).resolve()
    metadata = dataset / "metadata.json"
    if sha256(metadata) != spec["metadata_sha256"]:
        raise ValueError("dataset metadata checksum changed")
    records = json.loads(metadata.read_text(encoding="utf-8"))
    recordings = {row["record_time"]: row for row in records.values()}
    splits = {name: row["split"] for name, row in recordings.items()}
    result = {}
    used = set()
    used_pieces = set()
    for phase, allowed in (("train", {"train", "ext-train"}),
                           ("validation", {"valid"}), ("test", {"test"})):
        result[phase] = []
        sources = set()
        pieces = set()
        for entry in spec.get(phase, []):
            source = (dataset / entry["source"]).resolve()
            if not source.is_relative_to(dataset):
                raise ValueError("source must be inside the dataset")
            if sha256(source) != entry["source_sha256"]:
                raise ValueError("fingering source checksum changed")
            if splits.get(source.stem) not in allowed:
                raise ValueError(f"{source.name} is not in the {phase} split")
            source_id = (source.stem, entry["source_sha256"])
            if source_id in used:
                raise ValueError("training/validation recordings must be disjoint")
            row = recordings[source.stem]
            piece = (row.get("composer", ""), row.get("piece", source.stem))
            if piece in used_pieces:
                raise ValueError("training/validation/test pieces must be disjoint")
            pieces.add(piece)
            sources.add(source_id)
            plan_path = (path.parent / entry["plan"]).resolve()
            if sha256(plan_path) != entry["plan_sha256"]:
                raise ValueError("reference plan checksum changed")
            plan = load_plan(plan_path)
            with source.open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream, delimiter="\t"))
            origin = float(entry["origin_sec"])
            padding = float(plan["metadata"]["start_padding_sec"])
            fingers = {str(i + 1): name for i, name in enumerate(
                ["thumb", "index", "middle", "ring", "little"])}
            for side, hand in plan["hands"].items():
                first = min(event["start_sec"] for event in hand["events"]) + origin - padding
                last = max(event["end_sec"] for event in hand["events"]) + origin - padding
                source_hand = [row for row in rows if row["hand"] == ("R" if side == "right" else "L")]
                inside = [row for row in source_hand
                          if first - 1e-6 <= float(row["onset"]) < last - 1e-6]
                if len(inside) != len(hand["events"]) or any(
                        float(row["onset"]) < first - 1e-6
                        and float(row["key_offset"]) > first + 1e-6 for row in source_hand):
                    raise ValueError("excerpt boundary drops source notes or begins over held notes")
                for event in hand["events"]:
                    candidates = [row for row in rows
                                  if row["hand"] == ("R" if side == "right" else "L")
                                  and int(row["note"]) == event["note"]
                                  and abs(float(row["onset"]) - origin + padding
                                          - event["start_sec"]) < 2e-6
                                  and abs(float(row["key_offset"]) - origin + padding
                                          - event["end_sec"]) < 2e-6]
                    if len(candidates) != 1:
                        raise ValueError("plan events must preserve source onset and key_offset")
                    if fingers.get(candidates[0]["finger"]) != event.get("prior_finger"):
                        raise ValueError("plan finger prior differs from source annotation")
            result[phase].append(plan_path)
        if not result[phase] and (phase != "test" or spec["format"] == "piano_rl_dataset/2"):
            raise ValueError(f"{phase} needs at least one reference plan")
        used.update(sources)
        used_pieces.update(pieces)
    return result


def evaluate(env, policy, output, *, seed=0):
    """Save the unchanged physical acceptance report, all key edges and MIDI."""
    output.mkdir(parents=True, exist_ok=False)
    obs, _ = env.reset(seed=seed)
    if policy is not None and env.nominal_qpos is None:
        raise RuntimeError("validate an unperturbed reference before evaluating a policy")
    done = False
    demonstrations = []
    nominal = [env.runner.data.qpos.copy()] if policy is None and env.command_bias == 0 else None
    while not done:
        if policy is None and len(env.action_trace) % 4 == 0:
            demonstrations.append(obs.copy())
        action = np.zeros(env.action_space.shape, np.float32) if policy is None else policy.predict(
            obs, deterministic=True)[0]
        obs, _, done, _, info = env.step(action)
        if nominal is not None:
            nominal.append(env.runner.data.qpos.copy())
    report = info["report"]
    if policy is None and report["passed"]:
        env.reference_observations = np.asarray(demonstrations, dtype=np.float32)
        np.savez_compressed(output / "demonstrations.npz",
                            observations=env.reference_observations,
                            actions=np.zeros((len(demonstrations), 20), np.float32))
        if nominal is not None:
            env.set_nominal_trace(nominal)
            np.savez_compressed(output / "nominal_states.npz", qpos=env.nominal_qpos)
    report["rl"] = {"episode_return": env.episode_return,
                    "reward_version": REWARD_VERSION,
                    "residual_command_units": env.residual,
                    "control_dt_sec": env.control_dt,
                    "command_bias_units": env.bias.tolist(),
                    "evaluation_seed": seed,
                    "hand_order": list(env.sides),
                    "feedback": "nominal_joint_tracking_gate",
                    "robopianist_reward": env.robopianist_reward,
                    "threshold_wrong": env.threshold_wrong,
                    "reward_components": env.reward_components,
                    "mean_fingertip_distance_m": (
                        env.fingertip_distance_total / env.fingertip_distance_samples
                        if env.fingertip_distance_samples else None),
                    "mean_hand_power_w": (
                        env.energy_total / env.energy_samples
                        if env.energy_samples else None),
                    "reference_plan_sha256": sha256(env.plan_path)}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "key_edges.json").write_text(
        json.dumps(env.runner.edges), encoding="utf-8")
    (output / "actions.json").write_text(
        json.dumps(env.action_trace), encoding="utf-8")
    env.replay.write_observed_midi(
        output / "played_keys.mid",
        env.replay.observed_note_spans(env.runner.edges, env.runner.data.time))
    matched = len(report["expected_events"]) - len(report["missing"])
    return {"passed": report["passed"], "matched": matched,
            "expected": len(report["expected_events"]),
            "missing": len(report["missing"]), "unexpected": len(report["unexpected"]),
            "unexpected_by_kind": dict(Counter(
                event["kind"] for event in report["unexpected"])),
            "angle_violations": report["angle_violations"],
            "active_keys_at_end": report["active_keys_at_end"],
            "wrong_finger_contacts": len(report["wrong_finger_contacts"]),
            "unexpected_contacts": len(report["unexpected_contacts"]),
            "max_onset_error_sec": report["max_onset_error_sec"],
            "max_release_error_sec": report["max_release_error_sec"],
            "episode_return": env.episode_return,
            "reward_components": env.reward_components,
            "mean_fingertip_distance_m": report["rl"]["mean_fingertip_distance_m"],
            "mean_hand_power_w": report["rl"]["mean_hand_power_w"]}


def rollout_length(lengths):
    """The first PPO update must see a complete longest training episode."""
    return 1 << (max(512, max(lengths)) - 1).bit_length()


def training_tasks(env):
    if hasattr(env, "envs"):
        return [task for child in env.envs for task in training_tasks(child)]
    return env.tasks if isinstance(env, PianoTaskCycle) else [env]


def reuse_zero_reference(source, target, metrics):
    """Label reused measured physics for the exactly-zero initialized actor."""
    shutil.copytree(source, target)
    path = target / "report.json"
    if path.is_file():
        report = json.loads(path.read_text())
        report.setdefault("rl", {})["evidence_reuse"] = "exact_zero_action_initialization"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return dict(metrics, evidence_reuse="exact_zero_action_initialization")


def create_policy(env, seed):
    """Start a residual policy at the physically validated zero-action reference."""
    from stable_baselines3 import PPO
    import torch

    tasks = training_tasks(env)
    model = PPO(
        "MlpPolicy", env, seed=seed, device="cpu", verbose=1,
        n_steps=rollout_length([sum(episode_steps(task.plan, task.control_dt) for task in tasks)]),
        batch_size=64, n_epochs=5, learning_rate=1e-4,
        policy_kwargs={"net_arch": {"pi": [64, 64], "vf": [64, 64]},
                       "log_std_init": -1.5})
    torch.nn.init.zeros_(model.policy.action_net.weight)
    torch.nn.init.zeros_(model.policy.action_net.bias)
    return model


def physical_rank(results):
    """Rank physical correctness before timing; never use shaped return."""
    errors = sum(result["missing"] + result["unexpected"]
                 + len(result["angle_violations"]) + len(result["active_keys_at_end"])
                 + result["wrong_finger_contacts"] + result["unexpected_contacts"]
                 for result in results)
    timing = sum((result["max_onset_error_sec"] or 0.0)
                 + (result["max_release_error_sec"] or 0.0) for result in results)
    return (sum(not result["passed"] for result in results), errors, timing)


def selection_rank(clean, perturbed):
    clean_rank, perturbed_rank = physical_rank(clean), physical_rank(perturbed)
    return (*clean_rank[:2], *perturbed_rank[:2], clean_rank[2] + perturbed_rank[2])


def main(argv=None):
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.logger import configure
    from stable_baselines3.common.vec_env import DummyVecEnv
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--manifest", type=Path)
    inputs.add_argument("--verified-two-tigers", action="store_true",
                        help="train the frozen dual 40-note song; no cross-song validation claim")
    parser.add_argument("--include-two-tigers", action="store_true",
                        help="include the frozen dual song in a multi-recording training curriculum")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--steps", type=int, default=16384)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--residual", type=float, default=6.0)
    parser.add_argument("--control-dt", type=float, default=0.02)
    parser.add_argument("--robopianist-reward", action="store_true")
    parser.add_argument("--threshold-wrong", action="store_true",
                        help="ablate a constant penalty for any sounding non-target key")
    parser.add_argument("--command-bias", type=float, default=0.5,
                        help="training-only uniform actuator bias (default 0.5 L20 units; 0 is an ablation)")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--final-test", action="store_true",
                        help="unseal held-out recordings only after training/model decisions are frozen")
    args = parser.parse_args(argv)
    args.package = (args.package or default_package()).resolve()
    if args.steps < 1 or (args.evaluate_only and args.resume is None):
        parser.error("positive steps required; evaluation requires --resume")
    if args.verified_two_tigers:
        from verify_two_tigers import BASELINE, load_baseline
        load_baseline(args.package)
        args.manifest = args.package / BASELINE / "manifest.json"
        plans = {"train": [args.package / BASELINE / "performance.yaml"], "validation": []}
    else:
        plans = load_experiment(args.manifest)
        if args.include_two_tigers:
            from verify_two_tigers import BASELINE, load_baseline
            load_baseline(args.package)
            plans["train"].insert(0, args.package / BASELINE / "performance.yaml")
    if args.resume is not None:
        previous = json.loads((args.resume.parent / "config.json").read_text())
        if previous.get("interface_version") != INTERFACE_VERSION:
            parser.error("model interface changed; evaluate old models with their frozen source snapshot")
        if (not args.evaluate_only
                and previous.get("reward_version") != REWARD_VERSION):
            parser.error("resume reward_version differs; use --evaluate-only for old models")
        for key, value in (("residual", args.residual), ("control_dt", args.control_dt),
                           ("command_bias", args.command_bias),
                           ("include_two_tigers", args.include_two_tigers),
                           ("threshold_wrong", args.threshold_wrong),
                           ("robopianist_reward", args.robopianist_reward),
                           ("manifest_sha256", sha256(args.manifest))):
            default = False if key in ("robopianist_reward", "threshold_wrong", "include_two_tigers") else (
                0.0 if key == "command_bias" else None)
            if previous.get(key, default) != value:
                parser.error(f"resume {key} differs from the saved experiment")
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    config = {"seed": args.seed, "steps_requested": args.steps,
              "residual": args.residual, "control_dt": args.control_dt,
              "robopianist_reward": args.robopianist_reward,
              "threshold_wrong": args.threshold_wrong,
              "command_bias": args.command_bias,
              "include_two_tigers": args.include_two_tigers,
              "final_test_requested": args.final_test,
              "validation_scope": "same_song_only" if args.verified_two_tigers else "held_out_recording",
              "reward_version": REWARD_VERSION,
              "interface_version": INTERFACE_VERSION,
              "selection_bias_seeds": [31, 37] if args.command_bias else [],
              "policy_initialization": "resumed" if args.resume else "zero_residual",
              "manifest_sha256": sha256(args.manifest), "device": "cpu",
              "versions": {name: importlib.metadata.version(name) for name in
                           ("numpy", "mujoco", "torch", "gymnasium", "stable-baselines3")},
              "python": sys.version,
              "source_sha256": {str(path.relative_to(args.package)): sha256(path)
                                for folder in ("rm_mujoco", "scripts", "config", "models")
                                for path in (args.package / folder).glob("*")
                                if path.is_file()}}
    (args.output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    def make_env(path, bias=0.0):
        return PianoResidualEnv(path, args.package, control_dt=args.control_dt,
                                residual=args.residual,
                                robopianist_reward=args.robopianist_reward, command_bias=bias,
                                threshold_wrong=args.threshold_wrong)

    environments = {phase: [make_env(path) for path in plans.get(phase, [])
                            if phase != "test" or args.final_test]
                    for phase in ("train", "validation", "test")}
    collected_tasks = [make_env(path, args.command_bias) for path in plans["train"]]
    vector = DummyVecEnv([lambda: PianoTaskCycle(collected_tasks)])
    selection_envs = [make_env(path) for path in plans["train"]]
    biased_selection = [make_env(path, args.command_bias) for path in plans["train"]]
    try:
        check_env(environments["train"][0], warn=True, skip_render_check=True)
        if args.resume:
            model = PPO.load(args.resume, env=vector, device="cpu")
        else:
            model = create_policy(vector, args.seed)
        summary = {}
        config["rollout_steps"] = int(getattr(model, "n_steps", 512))
        (args.output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        for phase in ("train", "validation"):
            envs = environments[phase]
            summary[phase] = []
            for index, env in enumerate(envs):
                result = {"reference": evaluate(env, None, args.output / phase
                                                / str(index) / "reference")}
                if not args.evaluate_only and result["reference"]["passed"]:
                    if args.resume is None:
                        # The action layer is exactly zero for every observation.
                        # Reuse measured physics; label the reuse explicitly.
                        result["before_training"] = reuse_zero_reference(
                            args.output / phase / str(index) / "reference",
                            args.output / phase / str(index) / "before_training", result["reference"])
                    else:
                        result["before_training"] = evaluate(
                            env, model, args.output / phase / str(index) / "before_training")
                summary[phase].append(result)
                print("BASELINE", phase, index, json.dumps(result), flush=True)
        summary["acceptance"] = {"reference_passed": all(
            result["reference"]["passed"]
            for phase in ("train", "validation") for result in summary[phase])}
        if not summary["acceptance"]["reference_passed"]:
            (args.output / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8")
            print("RESULT reference failed physical acceptance; training skipped", flush=True)
            return 2
        nominal_by_plan = {str(env.plan_path): env.nominal_qpos
                           for phase in ("train", "validation") for env in environments[phase]}
        for env in collected_tasks + selection_envs + biased_selection:
            env.reset(seed=0)
            env.set_nominal_trace(nominal_by_plan[str(env.plan_path)])
        if not args.evaluate_only:
            started = time.monotonic()
            initial = []
            for index, env in enumerate(selection_envs):
                if args.resume is None:
                    initial.append(reuse_zero_reference(
                        args.output / "train" / str(index) / "reference",
                        args.output / "selection" / "0" / str(index),
                        summary["train"][index]["reference"]))
                else:
                    initial.append(evaluate(env, model, args.output / "selection" / "0" / str(index)))
            def evaluate_bias(policy, label):
                return [evaluate(env, policy, args.output / "selection" / label
                                 / f"bias_seed{seed}_{index}", seed=seed)
                        for index, env in enumerate(biased_selection)
                        for seed in config["selection_bias_seeds"]]

            initial_bias = evaluate_bias(model, "0")
            best = {"step": int(model.num_timesteps), "rank": selection_rank(initial, initial_bias)}
            model.save(args.output / "best_model")
            selection = [{**best, "results": initial, "perturbed": initial_bias}]
            demonstration_arrays = [env.reference_observations for env in environments["train"]
                                    if hasattr(env, "reference_observations")]
            demonstrations = (torch.as_tensor(np.concatenate(demonstration_arrays), dtype=torch.float32)
                              if demonstration_arrays else None)
            rehearsal_rng = np.random.default_rng(args.seed)
            rehearsal_updates = []

            class Progress(BaseCallback):
                def rehearse(self):
                    if demonstrations is None:
                        return
                    for _ in range(4):
                        indices = rehearsal_rng.integers(0, len(demonstrations), size=64)
                        mean = self.model.policy.get_distribution(
                            demonstrations[indices]).distribution.mean
                        loss = (mean ** 2).mean()
                        self.model.policy.optimizer.zero_grad()
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_(self.model.policy.parameters(), 0.5)
                        self.model.policy.optimizer.step()
                    rehearsal_updates.append({"step": int(self.model.num_timesteps),
                                              "loss": float(loss.detach())})

                def _on_rollout_start(self):
                    if self.model.num_timesteps > best.get("initial_step", 0):
                        self.rehearse()

                def _on_step(self):
                    if self.n_calls % 512 == 0:
                        print(f"TRAIN steps={self.num_timesteps} "
                              f"wall_sec={time.monotonic() - started:.1f}", flush=True)
                    if self.n_calls % max(4096, 4 * self.model.n_steps) == 0:
                        self.select()
                    return True

                def select(self, final=False):
                    step = int(self.model.num_timesteps)
                    label = f"{step}_final" if final else str(step)
                    results = [evaluate(env, self.model,
                                        args.output / "selection" / label / str(index))
                               for index, env in enumerate(selection_envs)]
                    biased = evaluate_bias(self.model, label)
                    rank = selection_rank(results, biased)
                    selection.append({"step": step, "final_update": final,
                                      "rank": rank, "results": results, "perturbed": biased})
                    if rank < best["rank"]:
                        best.update(step=step, rank=rank)
                        self.model.save(args.output / "best_model")

                def _on_training_end(self):
                    self.rehearse()
                    self.select(final=True)

            model.set_logger(configure(str(args.output / "progress"), ["csv"]))
            model.learn(total_timesteps=args.steps, reset_num_timesteps=not bool(args.resume),
                        callback=[Progress(), CheckpointCallback(
                            save_freq=4096, save_path=str(args.output / "checkpoints"),
                            name_prefix="ppo")])
            model.save(args.output / "model")
            summary["training"] = {"timesteps": model.num_timesteps,
                                   "wall_seconds": time.monotonic() - started,
                                   "reference_rehearsal": rehearsal_updates,
                                   "coverage": [{"plan": str(task.plan_path),
                                                 "completed_episodes": task.completed_episodes,
                                                 "seen_events": len(task.seen_events),
                                                 "expected_events": sum(len(hand["events"])
                                                     for hand in task.plan["hands"].values())}
                                                for task in collected_tasks]}
            summary["selection"] = {"best": best, "candidates": selection,
                                    "uses_validation_recordings": False}
            selected = PPO.load(args.output / "best_model", device="cpu")
        for phase, envs in environments.items():
            if phase == "test":
                summary[phase] = [{"reference": evaluate(
                    env, None, args.output / phase / str(index) / "reference")}
                    for index, env in enumerate(envs)]
                if any(not row["reference"]["passed"] for row in summary[phase]):
                    summary["acceptance"]["reference_passed"] = False
                    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
                    print("RESULT test reference failed; policy test skipped", flush=True)
                    return 2
            for index, env in enumerate(envs):
                summary[phase][index]["learned"] = evaluate(
                    env, model, args.output / phase / str(index) / "learned")
                print("LEARNED", phase, index,
                      json.dumps(summary[phase][index]["learned"]), flush=True)
                if not args.evaluate_only:
                    summary[phase][index]["selected"] = evaluate(
                        env, selected, args.output / phase / str(index) / "selected")
        summary["acceptance"]["learned_passed"] = all(
            result["learned"]["passed"]
            for phase in ("train", "validation", "test") for result in summary[phase])
        summary["acceptance"]["reference_passed"] = all(
            result["reference"]["passed"]
            for phase in ("train", "validation", "test") for result in summary[phase])
        if not args.evaluate_only:
            summary["acceptance"]["selected_passed"] = all(
                result["selected"]["passed"]
                for phase in ("train", "validation", "test") for result in summary[phase])
        (args.output / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        print("RESULT", json.dumps(summary["acceptance"]), flush=True)
        return 0 if summary["acceptance"]["learned_passed"] else 2
    finally:
        vector.close()
        for env in selection_envs:
            env.close()
        for env in biased_selection:
            env.close()
        for envs in environments.values():
            for env in envs:
                env.close()


if __name__ == "__main__":
    sys.exit(main())
