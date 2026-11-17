"""T-0055 restricted DroQ training on the hierarchical interface.

Policy outputs target key angle (1-dim) every 50 ms; the task's 1 kHz inner loop
does IK + force feedback. Reuses the upstream SAC/DroQ learner (sac.py/replay.py)
and rm75 evaluation helpers. Run through reproduce.py to use the pinned sources.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

os.environ.setdefault('JAX_PLATFORMS', 'cpu')
os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares

import dm_env_wrappers as wrappers
from dm_control.rl.control import PhysicsError
from mujoco_utils import composer_utils
from note_seq.protobuf import music_pb2
import sac
import replay
import rm75
from robopianist.suite.tasks.piano_with_rm75_l20 import RM75MidiFile
from hierarchical_env import HierarchicalPianoTask


def make_hier_env(seed, end=.7552083333333339, task_kwargs=None):
    pose_file = Path(__file__).with_name('initial_action.json')
    init = np.asarray(json.loads(pose_file.read_text(encoding='utf-8')))
    seq = music_pb2.NoteSequence(total_time=end + .5)
    seq.notes.add(pitch=72, velocity=80, start_time=.5, end_time=end, part=1)
    task = HierarchicalPianoTask(midi=RM75MidiFile(seq=seq, annotated=True),
        initial_action=init.tolist(), physics_timestep=.001, **(task_kwargs or {}))
    task.piano.mjcf_model.default.geom.solref = (.004, 1.)
    task.right_hand.mjcf_model.find('geom', 'right_collision_22').solref = (.004, 1.)
    raw = composer_utils.Environment(task=task, random_state=seed,
        strip_singleton_obs_buffer_dim=True, legacy_step=True)
    raw.reset(); ph = raw.physics
    hand = task.right_hand; kin = ph.copy(share_model=True)
    target = ph.bind(hand.fingertip_sites[1]).xpos.copy() + [.03, 0., 0.]
    desired_rot = ph.bind(hand.fingertip_sites[1]).xmat.reshape(3, 3).copy()
    ranges = ph.bind(hand.joints[:7]).range.copy()
    def residual(arm):
        action = init.copy(); action[:7] = arm
        kin.bind(hand.joints).qpos = hand.targets(action[:23]); kin.forward()
        b = kin.bind(hand.fingertip_sites[1])
        return np.r_[(b.xpos-target)*1000,
            Rotation.from_matrix(desired_rot@b.xmat.reshape(3, 3).T).as_rotvec()*100, (arm-init[:7])*.02]
    fit = least_squares(residual, init[:7], bounds=(ranges[:, 0]+.002, ranges[:, 1]-.002), diff_step=1e-4, max_nfev=200)
    init[:7] = fit.x; hand.home_action = init[:23].copy()
    raw.reset()
    env = wrappers.ObservationActionRewardWrapper(raw)
    env = wrappers.ConcatObservationWrapper(env)
    env = wrappers.CanonicalSpecWrapper(env, clip=True)
    env = wrappers.SinglePrecisionWrapper(env)
    return raw, env


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=3000)
    p.add_argument('--warmup', type=int, default=500)
    p.add_argument('--batch-size', type=int, default=256)
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--eval-seed', type=int, default=101)
    p.add_argument('--discount', type=float, default=.8)
    p.add_argument('--eval-interval', type=int, default=1000)
    p.add_argument('--milestones', type=str, default='2000,5000,10000,20000')
    p.add_argument('--holdout-seed', type=int, default=202)
    p.add_argument('--safety-penalty', type=float, default=1.)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    milestones = set(int(x) for x in args.milestones.split(','))
    np.random.seed(args.seed)
    task_kwargs = {'safety_penalty': args.safety_penalty}
    raw, env = make_hier_env(args.seed, task_kwargs=task_kwargs)
    eval_raw, eval_env = make_hier_env(args.eval_seed, task_kwargs=task_kwargs)
    config = asdict(sac.SACConfig(critic_dropout_rate=.01, critic_layer_norm=True))  # DroQ
    agent = rm75.initialize_agent(env, config, args.seed, args.discount)
    spec = env.action_spec()
    rng = np.random.RandomState(args.seed)
    ts = env.reset()
    buffer = replay.Buffer(ts.observation.size, int(np.prod(spec.shape)), max(args.steps, 256), args.batch_size)
    buffer.insert(ts, None)
    initial_hash = rm75.fingerprint(agent.actor.params)
    updates = 0; episodes = 0; physics_invalid = 0
    training_safety = {'collision_frames': 0, 'joint_limit_frames': 0}
    reasons = {}
    start = time.monotonic()
    import jax
    metadata = dict(seed=args.seed, algorithm='droq', agent_config=config, steps=args.steps,
        warmup_steps=args.warmup, batch_size=args.batch_size, discount=args.discount,
        interface='hierarchical_50ms_target_1khz_inner', action_shape=list(spec.shape),
        observation_shape=list(ts.observation.shape), jax_backend=jax.default_backend(),
        physics_timestep=.001, control_timestep=.05, initial_actor_sha256=initial_hash,
        safety_penalty=args.safety_penalty, holdout_seed=args.holdout_seed)
    rm75.write_json(args.output / 'config.json', metadata)
    # Untrained (random) baseline eval for the policy-contribution comparison.
    rand_rng = np.random.RandomState(args.eval_seed)
    def random_action(obs):
        return rand_rng.uniform(spec.minimum, spec.maximum).astype(np.float32)
    try:
        rm75.evaluate(eval_raw, eval_env, random_action,
            args.output / 'evaluations' / 'untrained', record_video=False)
    except PhysicsError:
        rm75.write_json(args.output / 'evaluations' / 'untrained' / 'failed.json', {'reason': 'physics_invalid'})
    with (args.output / 'training.jsonl').open('w', buffering=1) as log:
        for step in range(1, args.steps + 1):
            if step <= args.warmup:
                action = rng.uniform(spec.minimum, spec.maximum).astype(np.float32)
            else:
                agent, action = agent.sample_actions(ts.observation)
            try:
                ts = env.step(np.asarray(action))
            except PhysicsError:
                physics_invalid += 1; ts = env.reset(); buffer.insert(ts, None); continue
            if not np.isfinite(ts.observation).all() or not np.isfinite(ts.reward).all():
                raise FloatingPointError(f'Nonfinite transition at {step}')
            buffer.insert(ts, action)
            components = raw.task.reward_components(raw.physics)
            ss = raw.task.step_safety_metrics()
            training_safety['collision_frames'] += int(ss['collision'])
            training_safety['joint_limit_frames'] += int(ss['joint_limit'])
            if ts.last():
                episodes += 1; reason = raw.task.termination_reason
                reasons[reason] = reasons.get(reason, 0) + 1
                ts = env.reset(); buffer.insert(ts, None)
            metrics = {}
            if step > args.warmup and buffer.is_ready():
                agent, values = agent.update(buffer.sample())
                metrics = {k: float(v) for k, v in values.items()}; updates += 1
            if step % 100 == 0 or step == args.steps:
                row = dict(step=step, updates=updates, episodes=episodes,
                    seconds=time.monotonic()-start, physics_invalid=physics_invalid,
                    training_collision_frames=training_safety['collision_frames'],
                    training_joint_limit_frames=training_safety['joint_limit_frames'],
                    **{'component_'+k: float(v) for k, v in components.items()}, **metrics)
                log.write(json.dumps(row, allow_nan=False)+'\n'); print(json.dumps(row), flush=True)
            if step % args.eval_interval == 0 or step == args.steps:
                try:
                    ev = rm75.evaluate(eval_raw, eval_env, agent.eval_actions,
                        args.output / 'evaluations' / f'step_{step:07d}', record_video=False)
                    rm75.write_json(args.output / 'evaluations' / f'step_{step:07d}' / 'rank.json',
                        {'rank': list(rm75.evaluation_rank(ev))})
                except PhysicsError:
                    rm75.write_json(args.output / 'evaluations' / f'step_{step:07d}' / 'failed.json',
                        {'step': step, 'reason': 'physics_invalid'})
            if step in milestones or step == args.steps:
                state = dict(step=step, updates=updates, episodes=episodes, reasons=reasons,
                    initial_hash=initial_hash, best_rank=None, seconds=time.monotonic()-start,
                    training_safety=training_safety, physics_invalid=physics_invalid,
                    rng_state=rng.get_state(), np_random_state=np.random.get_state(), buffer=buffer)
                rm75.save_checkpoint(args.output, agent, buffer, state, ts.observation.copy())
    final_hash = rm75.fingerprint(agent.actor.params)
    rm75.write_json(args.output / 'training_summary.json', dict(steps=args.steps, updates=updates,
        initial_actor_sha256=initial_hash, final_actor_sha256=final_hash, termination_counts=reasons,
        training_safety=training_safety, physics_invalid_steps=physics_invalid, seconds=time.monotonic()-start))
    # Held-out seed comprehensive acceptance eval (seed not used in training).
    hold_raw, hold_env = make_hier_env(args.holdout_seed, task_kwargs=task_kwargs)
    try:
        rm75.evaluate(hold_raw, hold_env, agent.eval_actions,
            args.output / 'evaluations' / f'holdout_seed{args.holdout_seed}', record_video=False)
    except PhysicsError:
        rm75.write_json(args.output / 'evaluations' / f'holdout_seed{args.holdout_seed}' / 'failed.json',
            {'reason': 'physics_invalid'})
    hold_raw.close()
    eval_raw.close(); raw.close()
    print('SMOKE_DONE', json.dumps(dict(updates=updates, episodes=episodes,
        physics_invalid=physics_invalid, final_hash=final_hash)), flush=True)


if __name__ == '__main__':
    main()
