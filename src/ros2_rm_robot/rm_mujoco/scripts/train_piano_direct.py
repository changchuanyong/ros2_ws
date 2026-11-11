#!/usr/bin/env python3
"""Train and evaluate PPO on fixed-wrist direct-control piano tasks."""

import argparse
from collections import defaultdict
import importlib.metadata
import json
import math
from pathlib import Path
import sys

import numpy as np

def _package_root():
    root = Path(__file__).resolve().parents[1]
    if (root / "models").is_dir():
        return root
    from ament_index_python.packages import get_package_share_directory
    return Path(get_package_share_directory("rm_mujoco"))


PACKAGE = _package_root()
sys.path.insert(0, str(PACKAGE))

from rm_mujoco.piano_direct import PianoDirectEnv, OBSERVATION_SIZE  # noqa: E402
from rm_mujoco.piano_direct_eval import evaluate_edges, single_note_success  # noqa: E402
from rm_mujoco.pianovam_corpus import load_corpus_manifest, sha256  # noqa: E402
from rm_mujoco.pianovam_tasks import HAND_ORDER, load_task_set  # noqa: E402


def make_env(task_path, package, *, task_index, hand, action_scale, channels,
             reward_weights, observation_lead, initial_jitter=0.0, task_indices=None):
    return PianoDirectEnv.from_config(
        task_path, package, task_index=task_index,
        active_hands=HAND_ORDER if hand == "both" else (hand,), action_scale=action_scale,
        active_channels=channels, reward_weights=reward_weights,
        observation_lead_sec=observation_lead, initial_jitter=initial_jitter,
        task_indices=task_indices)


def evaluate(model, task_path, package, *, task_index, hand, action_scale,
             channels, reward_weights, observation_lead, episodes, seed_start,
             random_policy=False, initial_jitter=0.0, all_tasks=False):
    env = make_env(task_path, package, task_index=task_index, hand=hand,
                   action_scale=action_scale, channels=channels,
                   reward_weights=reward_weights,
                   observation_lead=observation_lead, initial_jitter=initial_jitter)
    rows = []
    enabled_hands = {side for i, side in enumerate(HAND_ORDER)
                     if np.any((env.action_mask * env.channel_mask)[10 * i:10 * (i + 1)])}
    try:
        task_indices = (range(env.task_count) if all_tasks else (task_index,))
        for episode in range(episodes):
            seed = seed_start + episode
            env.action_space.seed(seed)
            index = task_indices[episode % len(task_indices)]
            observation, reset_info = env.reset(seed=seed, options={"task_index": index})
            edges = []
            other_contacts = []
            onset_contacts = {}
            total_reward = 0.0
            terminated = truncated = False
            steps = 0
            while True:
                if random_policy:
                    action = env.action_space.sample()
                else:
                    action, _ = model.predict(observation, deterministic=True)
                observation, reward, terminated, truncated, info = env.step(action)
                total_reward += float(reward)
                edges.extend(info["edges"])
                other_contacts.extend(info["other_contacts"])
                onset_contacts.update({(time, note): owners
                                       for time, note, owners in info["onset_contacts"]})
                steps += 1
                if terminated or truncated:
                    break
            safety = {"key_violations": env.key_travel.violations(),
                      "other_contacts": other_contacts, "terminated": terminated}
            report = evaluate_edges(
                env.task, edges, timestep=env.model.opt.timestep,
                onset_contacts=onset_contacts, **safety)
            row = {
                "seed": seed,
                "task": env.task.id,
                "task_index": index,
                "success": report["success"],
                "report": report,
                "reward": total_reward,
                "steps": steps,
                "terminated": bool(terminated),
                "truncated": bool(truncated),
                "edges": edges,
                "coverage": {
                    "score_events": len(env.task.events),
                    "active_hand_events": sum(event.hand in enabled_hands
                                              for event in env.task.events),
                    "nominal_band_events": sum(
                        event.hand in enabled_hands
                        and event.note in env.reachable_notes[event.hand]
                        for event in env.task.events),
                },
            }
            for name in ("recording", "composer", "piece", "source_split"):
                if name in reset_info:
                    row[name] = reset_info[name]
            if len(env.task.events) == 1:
                result = single_note_success(
                    env.task, edges, timestep=env.model.opt.timestep, **safety)
                row.update(reason=result.reason, note=result.note,
                           observed_on=result.observed_on, observed_off=result.observed_off,
                           onset_error=result.onset_error, release_error=result.release_error)
            rows.append(row)
    finally:
        env.close()
    return rows


def summarize(rows):
    reports = [row["report"] for row in rows]
    timed = sum(report["timed_notes"] for report in reports)
    expected = sum(report["expected_notes"] for report in reports)
    observed = sum(edge[1] == "on" for row in rows for edge in row["edges"])
    matches = [event for report in reports for event in report["matched"]]
    safe = [report for report in reports if not (
        report["key_violations"] or report["other_contacts"] or report["terminated"])]
    coverage = {name: sum(row["coverage"][name] for row in rows)
                for name in ("score_events", "active_hand_events", "nominal_band_events")}
    successes = sum(row["success"] for row in rows)
    result = {
        "samples": len(rows),
        "successes": successes,
        "success_rate": successes / len(rows),
        "timed_note_precision": timed / max(1, observed),
        "timed_note_recall": timed / max(1, expected),
        "timed_note_f1": 2 * timed / max(1, expected + observed),
        "missed_notes": sum(len(report["missing"]) for report in reports),
        "extra_presses": sum(event["kind"] == "extra press" for report in reports
                             for event in report["extra"]),
        "collision_episodes": sum(bool(report["other_contacts"]) for report in reports),
        "key_violation_episodes": sum(bool(report["key_violations"]) for report in reports),
        "mean_reward": float(np.mean([row["reward"] for row in rows])),
        "coverage": {
            **coverage,
            "nominal_band_fraction": coverage["nominal_band_events"] / max(1, expected),
            "timed_events_in_safe_episodes": sum(report["timed_notes"] for report in safe),
        },
    }
    for name in ("onset", "release", "duration"):
        errors = [event[f"{name}_error"] for event in matches]
        result[f"mean_{name}_error"] = float(np.mean(errors)) if errors else None
        result[f"p95_absolute_{name}_error"] = (
            float(np.percentile(np.abs(errors), 95)) if errors else None)
    return result


def summarize_by_piece(rows):
    groups = defaultdict(list)
    for row in rows:
        if "piece" in row:
            groups[(row["composer"], row["piece"])].append(row)
    return [
        {"composer": composer, "piece": piece,
         "recordings": sorted({row["recording"] for row in group}), **summarize(group)}
        for (composer, piece), group in sorted(groups.items())
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--tasks", type=Path)
    inputs.add_argument("--manifest", type=Path, help="frozen PianoVAM corpus manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--sample-tasks", action="store_true",
                        help="sample a training task from the input file each episode")
    parser.add_argument("--eval-tasks", type=Path,
                        help="cycle through this separate task set during evaluation")
    parser.add_argument("--initial-jitter", type=float, default=0.0,
                        help="initial L20 command perturbation in [0, 1] units")
    parser.add_argument("--hand", choices=("left", "right", "both"))
    parser.add_argument("--channels",
                        help="comma-separated global action channels, 0..19")
    parser.add_argument("--action-scale", type=float, default=80.0)
    parser.add_argument("--safety-weight", type=float, default=2.0,
                        help="training safety penalty; evaluation stays strict")
    parser.add_argument("--observation-lead", type=float, default=0.0,
                        help="fixed score-clock phase advance for hand latency")
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--final-test", action="store_true",
                        help="evaluate a frozen checkpoint on the manifest test phase")
    parser.add_argument("--steps", type=int, default=30000,
                        help="additional training steps when --resume is used")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--n-steps", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--n-epochs", type=int, default=5)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--ent-coef", type=float, default=0.01)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--eval-episodes", type=int,
                        help="default: one full manifest pass, or 20 single-file episodes")
    parser.add_argument("--eval-seed-start", type=int, default=10000)
    args = parser.parse_args(argv)
    if args.steps < 1 or (args.eval_episodes is not None and args.eval_episodes < 1):
        parser.error("--steps and --eval-episodes must be positive")
    args.hand = args.hand or ("both" if args.manifest else "left")
    hands = HAND_ORDER if args.hand == "both" else (args.hand,)
    if args.channels is None:
        args.channels = (",".join(str(i) for i in range(20) if HAND_ORDER[i // 10] in hands)
                         if args.manifest else "1")
    try:
        channels = tuple(int(value) for value in args.channels.split(",") if value.strip())
    except ValueError:
        parser.error("--channels must be comma-separated integers")
    if (not channels or len(set(channels)) != len(channels)
            or any(not 0 <= value < 20 for value in channels)):
        parser.error("--channels must be a non-empty subset of 0..19")
    if not math.isfinite(args.safety_weight) or args.safety_weight < 0:
        parser.error("--safety-weight must be finite and non-negative")
    if not math.isfinite(args.observation_lead) or args.observation_lead < 0:
        parser.error("--observation-lead must be finite and non-negative")
    if args.evaluate_only and args.resume is None:
        parser.error("--evaluate-only requires --resume")
    if args.final_test and (not args.evaluate_only or not args.manifest):
        parser.error("--final-test requires --manifest, --evaluate-only and --resume")
    if not math.isfinite(args.initial_jitter) or not 0 <= args.initial_jitter <= 1:
        parser.error("--initial-jitter must be between 0 and 1")
    if args.manifest:
        if args.eval_tasks or args.task_index:
            parser.error("--manifest selects evaluation tasks and does not use --task-index")
        try:
            corpus = load_corpus_manifest(args.manifest)
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(str(error))
        if any(not split.task_count for split in corpus.values()):
            parser.error("manifest must contain train, valid and test tasks")
        train_tasks = corpus["train"]
        eval_phase = "test" if args.final_test else "valid"
        eval_tasks = corpus[eval_phase]
        eval_episodes = args.eval_episodes or eval_tasks.task_count
        if eval_episodes % eval_tasks.task_count:
            parser.error("--eval-episodes must be a multiple of the manifest evaluation task count")
        if not args.evaluate_only:
            enabled_hands = {HAND_ORDER[channel // 10] for channel in channels} & set(hands)
            if any(event.hand not in enabled_hands
                   for task in train_tasks.tasks for event in task.events):
                parser.error("manifest training targets require active channels for their hands")
        task_indices = None
        provenance = {
            "manifest": str(args.manifest.resolve()), "manifest_sha256": sha256(args.manifest),
            "evaluation_scope": f"piece_disjoint_{eval_phase}",
            "phase_recordings": {key: len(value.recordings) for key, value in corpus.items()},
            "phase_tasks": {key: value.task_count for key, value in corpus.items()},
        }
    else:
        train_tasks = args.tasks
        training_tasks = load_task_set(train_tasks)
        if not args.evaluate_only and training_tasks.split not in ("train", "ext-train"):
            parser.error("training tasks must use the train or ext-train split")
        eval_tasks = args.eval_tasks or train_tasks
        eval_episodes = args.eval_episodes or 20
        if args.eval_tasks:
            evaluation_tasks = load_task_set(eval_tasks)
            if eval_episodes < evaluation_tasks.task_count:
                parser.error("--eval-episodes must cover every task in --eval-tasks")
            if not args.evaluate_only and evaluation_tasks.split == "test":
                parser.error("evaluate a frozen model on test tasks with --evaluate-only")
        task_indices = range(training_tasks.task_count) if args.sample_tasks else None
        provenance = {
            "task": str(train_tasks.resolve()), "task_sha256": sha256(train_tasks),
            "eval_tasks": str(eval_tasks.resolve()), "eval_tasks_sha256": sha256(eval_tasks),
            "evaluation_scope": ("same_recording" if not args.eval_tasks else "separate_task_file"),
        }
    reward_weights = {"safety": args.safety_weight}
    if args.output.exists():
        parser.error("--output must not exist")
    args.output.mkdir(parents=True)
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.vec_env import DummyVecEnv, VecMonitor

    torch.set_num_threads(2)
    def training_env():
        return make_env(
            train_tasks, args.package, task_index=args.task_index,
            hand=args.hand, action_scale=args.action_scale,
            channels=channels, reward_weights=reward_weights,
            observation_lead=args.observation_lead, initial_jitter=args.initial_jitter,
            task_indices=task_indices)

    vector = None
    if not args.evaluate_only:
        check = training_env()
        try:
            check_env(check, warn=True, skip_render_check=True)
        finally:
            check.close()
        vector = VecMonitor(DummyVecEnv([training_env]))
    if args.resume:
        model = PPO.load(args.resume, env=vector, device="cpu", seed=args.seed)
    else:
        model = PPO(
            "MlpPolicy", vector, n_steps=args.n_steps, batch_size=args.batch_size,
            n_epochs=args.n_epochs, learning_rate=args.learning_rate,
            gamma=args.gamma, gae_lambda=0.95, clip_range=0.2,
            ent_coef=args.ent_coef, policy_kwargs={"net_arch": [128, 128]},
            seed=args.seed, device="cpu", verbose=1)
    config = {
        "seed": args.seed, "steps": args.steps,
        "resume": str(args.resume.resolve()) if args.resume else None,
        "resume_sha256": sha256(args.resume) if args.resume else None,
        **provenance,
        "task_index": args.task_index, "hand": args.hand,
        "sample_tasks": bool(args.manifest or args.sample_tasks),
        "initial_jitter": args.initial_jitter,
        "eval_episodes": eval_episodes,
        "action_scale": args.action_scale, "active_channels": list(channels),
        "reward_weights": reward_weights,
        "observation_lead_sec": args.observation_lead,
        "observation_size": OBSERVATION_SIZE, "action_size": 20,
        "ppo": {"n_steps": model.n_steps, "batch_size": model.batch_size,
                "n_epochs": model.n_epochs, "learning_rate": model.lr_schedule(1.0),
                "ent_coef": model.ent_coef, "gamma": model.gamma,
                "net_arch": model.policy.net_arch},
        "eval_seed_start": args.eval_seed_start,
        "versions": {name: importlib.metadata.version(name) for name in
                     ("numpy", "mujoco", "torch", "gymnasium",
                      "stable-baselines3")},
    }
    (args.output / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if not args.evaluate_only:
        model.learn(total_timesteps=args.steps, reset_num_timesteps=args.resume is None)
        model.save(args.output / "model.zip")
        if args.manifest:
            config["training_recording_resets"] = dict(vector.get_attr("recording_resets")[0])
    config["model_timesteps"] = model.num_timesteps
    (args.output / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if vector is not None:
        vector.close()

    trained = evaluate(model, eval_tasks, args.package,
                       task_index=args.task_index, hand=args.hand,
                       action_scale=args.action_scale, channels=channels,
                       reward_weights=reward_weights,
                       observation_lead=args.observation_lead,
                       episodes=eval_episodes,
                       seed_start=args.eval_seed_start, initial_jitter=args.initial_jitter,
                       all_tasks=bool(args.manifest or args.eval_tasks))
    baseline = evaluate(None, eval_tasks, args.package,
                        task_index=args.task_index, hand=args.hand,
                        action_scale=args.action_scale, channels=channels,
                        reward_weights=reward_weights,
                        observation_lead=args.observation_lead,
                        episodes=eval_episodes,
                        seed_start=args.eval_seed_start,
                        random_policy=True, initial_jitter=args.initial_jitter,
                        all_tasks=bool(args.manifest or args.eval_tasks))
    summary = summarize(trained)
    summary["random_success_rate"] = sum(row["success"] for row in baseline) / len(baseline)
    by_piece = summarize_by_piece(trained)
    if by_piece:
        summary["piece_macro_timed_note_f1"] = float(np.mean(
            [piece["timed_note_f1"] for piece in by_piece]))
    (args.output / "evaluation.json").write_text(
        json.dumps({"summary": summary, "trained": trained,
                    "by_piece": by_piece, "random": baseline,
                    "random_by_piece": summarize_by_piece(baseline)},
                   indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["success_rate"] >= 0.9 else 2


if __name__ == "__main__":
    sys.exit(main())
