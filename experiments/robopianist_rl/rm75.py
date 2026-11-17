"""Reproducible RM75 integration runner using the upstream SAC/DroQ learner."""
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import time

os.environ.setdefault('JAX_PLATFORMS', 'cpu')
os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')

import numpy as np
import dm_env_wrappers as wrappers
from dm_control.rl.control import PhysicsError
from robopianist import suite

ENVIRONMENT = 'RoboPianist-debug-RM75TwoNotes-v0'


def make_env(seed=7, robot='rm75_l20', task_kwargs=None, environment=ENVIRONMENT, midi_file=None):
    raw = suite.load(environment, robot=robot, seed=seed, task_kwargs=task_kwargs or {}, midi_file=midi_file)
    env = wrappers.ObservationActionRewardWrapper(raw)
    env = wrappers.ConcatObservationWrapper(env)
    env = wrappers.CanonicalSpecWrapper(env, clip=True)
    env = wrappers.SinglePrecisionWrapper(env)
    return raw, env


def reward_kwargs(args):
    kwargs = {}
    fields = (
        ('fingering_margin', 'fingering_margin_m'),
        ('energy_coef', 'energy_penalty_coef'),
        ('safety_penalty', 'safety_penalty'),
        ('trim_silence', 'trim_silence'),
        ('initial_buffer_time', 'initial_buffer_time'),
        ('trailing_silence', 'trailing_silence'),
        ('note_offset', 'note_offset'),
        ('note_limit', 'note_limit'),
    )
    for argument, key in fields:
        value = getattr(args, argument, None)
        if value is not None:
            kwargs[key] = value
    return kwargs


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Not JSON serializable: {type(value).__name__}')


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False, default=_json_default)+'\n')


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def write_npz(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    with temporary.open('wb') as stream:
        np.savez(stream, **arrays)
    os.replace(temporary, path)


def fingerprint(tree):
    import jax
    h = hashlib.sha256()
    for leaf in jax.tree_util.tree_leaves(tree):
        h.update(np.asarray(leaf).tobytes())
    return h.hexdigest()


def evaluation_rank(metrics, max_collision_frames=None, max_joint_limit_frames=None):
    collision_frames = metrics['collision_frames']
    joint_limit_frames = metrics['joint_limit_frames']
    safe = ((max_collision_frames is None or collision_frames <= max_collision_frames) and
            (max_joint_limit_frames is None or joint_limit_frames <= max_joint_limit_frames))
    return (
        int(safe),
        float(metrics['f1']),
        float(metrics['onset_recall']),
        -int(collision_frames),
        -int(joint_limit_frames),
        -int(metrics['false_positive_key_frames']),
    )


def evaluate(raw, env, action_fn, output, record_video=True, onset_tolerance_steps=1):
    """Score actual keys against the entire score, including silence after failures."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if record_video:
        import imageio.v2 as imageio
    ts = env.reset()
    goals = np.zeros((len(raw.task._notes),88),bool)
    for i, notes in enumerate(raw.task._notes):
        goals[i,[note.key for note in notes]] = True
    actual = np.zeros_like(goals)
    qpos, actions, rewards = [], [], []
    component_rows = []
    collision_mask, joint_limit_mask, penetration = [], [], []
    frames = [raw.physics.render(height=480,width=640,camera_id='rm75_overview')] if record_video else []
    i = 0
    while not ts.last():
        action = np.asarray(action_fn(ts.observation),dtype=np.float32)
        ts = env.step(action)
        actual[i] = raw.task.piano.activation
        actions.append(action)
        qpos.append(raw.physics.data.qpos.copy())
        rewards.append(float(ts.reward))
        component_rows.append(raw.task.reward_components(raw.physics))
        safety = raw.task.step_safety_metrics()
        collision_mask.append(safety['collision'])
        joint_limit_mask.append(safety['joint_limit'])
        penetration.append(safety['max_penetration_m'])
        if record_video:
            frames.append(raw.physics.render(height=480,width=640,camera_id='rm75_overview'))
        i += 1
    tp = int(np.sum(actual & goals))
    fp = int(np.sum(actual & ~goals))
    fn = int(np.sum(~actual & goals))
    precision = tp/(tp+fp) if tp+fp else 0.
    recall = tp/(tp+fn) if tp+fn else 0.
    onsets = np.zeros_like(actual)
    if len(actual):
        onsets[0] = actual[0]
        onsets[1:] = actual[1:] & ~actual[:-1]
    note_events = []
    onset_errors = []
    buffer_steps = int(round(raw.task._initial_buffer_time/raw.task.control_timestep))
    for note in raw.task.midi.seq.notes:
        key = note.pitch-21
        a = buffer_steps + int(np.floor(note.start_time/raw.task.control_timestep))
        b = buffer_steps + int(np.ceil(note.end_time/raw.task.control_timestep))
        a = min(max(a,0),len(actual))
        b = min(max(b,0),len(actual))
        candidates = np.flatnonzero(onsets[:,key] & (np.abs(np.arange(len(actual))-a) <= onset_tolerance_steps))
        onset_frame = int(candidates[np.argmin(np.abs(candidates-a))]) if len(candidates) else None
        error = None if onset_frame is None else (onset_frame-a)*raw.task.control_timestep
        if error is not None:
            onset_errors.append(abs(error))
        note_events.append({
            'pitch':note.pitch,
            'start':note.start_time,
            'end':note.end_time,
            'expected_start_with_buffer':note.start_time+buffer_steps*raw.task.control_timestep,
            'hit':bool(actual[a:b,key].any()) if a < b else False,
            'onset_hit':onset_frame is not None,
            'onset_frame':onset_frame,
            'expected_onset_frame':a,
            'onset_error_seconds':error,
        })
    violation_counts = {}
    for violation in raw.task.physical_violations:
        violation_counts[violation['kind']] = violation_counts.get(violation['kind'],0)+1
    component_names = sorted({name for row in component_rows for name in row})
    component_totals = {
        name:float(sum(row[name] for row in component_rows if name in row))
        for name in component_names
    }
    metrics = {
        'precision':precision,
        'recall':recall,
        'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
        'true_positive_key_frames':tp,
        'false_positive_key_frames':fp,
        'missed_key_frames':fn,
        'missed_notes':sum(not event['hit'] for event in note_events),
        'onset_recall':sum(event['onset_hit'] for event in note_events)/len(note_events) if note_events else 0.,
        'missed_onsets':sum(not event['onset_hit'] for event in note_events),
        'onset_mae_seconds':float(np.mean(onset_errors)) if onset_errors else None,
        'onset_tolerance_steps':onset_tolerance_steps,
        'notes':note_events,
        'executed_steps':i,
        'score_steps':len(goals),
        'control_timestep':raw.task.control_timestep,
        'return':float(sum(rewards)),
        'reward_components':component_totals,
        'termination_reason':raw.task.termination_reason,
        'violation_counts':violation_counts,
        'physical_violations':raw.task.physical_violations,
        **raw.task.safety_metrics(),
        'early_termination_scoring':'remaining score counted as no keys pressed',
        'video':'evaluation.mp4' if record_video else None,
        'video_frames':len(frames),
    }
    arrays = {
        'goal':goals,
        'actual':actual,
        'actions':actions,
        'qpos':qpos,
        'rewards':rewards,
        'collision_frames':collision_mask,
        'joint_limit_frames':joint_limit_mask,
        'penetration_m':penetration,
    }
    arrays.update({
        'component_'+name:np.asarray([row.get(name,0.) for row in component_rows],dtype=np.float64)
        for name in component_names
    })
    np.savez_compressed(output/'rollout.npz',**arrays)
    midi_events = raw.task.piano.midi_module.get_all_midi_messages()
    write_json(output/'midi_events.json',[{'type':type(event).__name__,**asdict(event)} for event in midi_events])
    if record_video:
        imageio.mimwrite(output/'evaluation.mp4',frames,fps=20,codec='libx264',macro_block_size=16)
    write_json(output/'evaluation.json',metrics)
    return metrics


def initialize_agent(env, config, seed, discount):
    import sac
    import specs
    config = dict(config)
    config['hidden_dims'] = tuple(config['hidden_dims'])
    return sac.SAC.initialize(specs.EnvironmentSpec.make(env),sac.SACConfig(**config),seed=seed,discount=discount)


def save_checkpoint(output, agent, buffer, state, probe):
    from flax import serialization
    output = Path(output)
    agent_bytes = serialization.to_bytes(agent)
    atomic_write(output/'checkpoint.msgpack',agent_bytes)
    write_npz(output/'reload_probe.npz',observation=probe,action=np.asarray(agent.eval_actions(probe)))
    atomic_write(output/'resume_state.pkl',pickle.dumps(state,protocol=pickle.HIGHEST_PROTOCOL))
    archive = output/'checkpoints'/f"step_{state['step']:07d}"
    atomic_write(archive/'checkpoint.msgpack',agent_bytes)
    write_npz(archive/'reload_probe.npz',observation=probe,action=np.asarray(agent.eval_actions(probe)))
    write_json(archive/'checkpoint.json',{
        'step':state['step'],
        'updates':state['updates'],
        'episodes':state['episodes'],
        'seconds':state['seconds'],
    })


def save_best(output, agent, probe, step, metrics, rank):
    from flax import serialization
    output = Path(output)
    atomic_write(output/'best_checkpoint.msgpack',serialization.to_bytes(agent))
    write_npz(output/'best_reload_probe.npz',observation=probe,action=np.asarray(agent.eval_actions(probe)))
    write_json(output/'best_evaluation.json',metrics)
    write_json(output/'best_checkpoint.json',{'step':step,'rank':list(rank)})


def restore_arguments(args, config):
    fields = (
        'seed','robot','environment','algorithm','discount','batch_size',
        'checkpoint_interval','eval_interval','eval_seed','onset_tolerance_steps',
        'max_collision_frames','max_joint_limit_frames',
    )
    for field in fields:
        if field in config:
            setattr(args,field,config[field])
    args.warmup = config['warmup_steps']
    args.midi_file = Path(config['midi_file']) if config.get('midi_file') else None
    kwargs = config.get('task_kwargs',{})
    mapping = {
        'fingering_margin':'fingering_margin_m',
        'energy_coef':'energy_penalty_coef',
        'safety_penalty':'safety_penalty',
        'trim_silence':'trim_silence',
        'initial_buffer_time':'initial_buffer_time',
        'trailing_silence':'trailing_silence',
        'note_offset':'note_offset',
        'note_limit':'note_limit',
    }
    defaults = {
        'trim_silence':False,
        'initial_buffer_time':0.,
        'trailing_silence':0.,
        'note_offset':0,
        'safety_penalty':0.,
    }
    for argument,key in mapping.items():
        setattr(args,argument,kwargs.get(key,defaults.get(argument)))


def train(args):
    import jax
    from flax import serialization
    import sac
    import replay
    resuming = args.resume is not None
    if resuming and args.output.resolve() != args.resume.resolve():
        raise ValueError('--output and --resume must name the same run directory')
    output = args.output
    output.mkdir(parents=True, exist_ok=resuming)
    saved_config = json.loads((output/'config.json').read_text()) if resuming else None
    if resuming:
        restore_arguments(args,saved_config)
    np.random.seed(args.seed)
    task_kwargs = reward_kwargs(args)
    raw, env = make_env(args.seed,args.robot,task_kwargs,args.environment,args.midi_file)
    config = asdict(sac.SACConfig(critic_dropout_rate=.01,critic_layer_norm=True)) if args.algorithm == 'droq' else asdict(sac.SACConfig())
    template = initialize_agent(env,config,args.seed,args.discount)
    spec = env.action_spec()
    if resuming:
        agent = serialization.from_bytes(template,(output/'checkpoint.msgpack').read_bytes())
        with (output/'resume_state.pkl').open('rb') as stream:
            state = pickle.load(stream)
        buffer = state['buffer']
        start_step = state['step']
        if args.steps <= start_step:
            raise ValueError(f'--steps must exceed the resumed step {start_step}')
        updates = state['updates']
        episodes = state['episodes']
        reasons = state['reasons']
        initial_hash = state['initial_hash']
        best_rank = tuple(state['best_rank']) if state['best_rank'] is not None else None
        elapsed = state['seconds']
        training_safety = state['training_safety']
        physics_invalid = state.get('physics_invalid',0)
        rng = np.random.RandomState()
        rng.set_state(state['rng_state'])
        np.random.set_state(state['np_random_state'])
        ts = env.reset()
        buffer._prev = None
        buffer._action = None
        buffer._latest = ts
    else:
        agent = template
        if args.init_from is not None:
            source_name = 'best_checkpoint.msgpack' if args.init_best else 'checkpoint.msgpack'
            source = args.init_from/source_name
            agent = serialization.from_bytes(template,source.read_bytes())
        start_step = 0
        updates = 0
        episodes = 0
        physics_invalid = 0
        reasons = {}
        best_rank = None
        elapsed = 0.
        training_safety = {'collision_frames':0,'joint_limit_frames':0}
        rng = np.random.RandomState(args.seed)
        ts = env.reset()
        buffer = replay.Buffer(ts.observation.size,int(np.prod(spec.shape)),max(args.steps,256),args.batch_size)
        buffer.insert(ts,None)
    probe = ts.observation.copy()
    if not resuming:
        initial_hash = fingerprint(agent.actor.params)
    metadata = dict(saved_config) if resuming else {
        'seed':args.seed,
        'robot':args.robot,
        'environment':args.environment,
        'midi_file':str(args.midi_file) if args.midi_file else None,
        'algorithm':args.algorithm,
        'agent_config':config,
        'warmup_steps':args.warmup,
        'batch_size':args.batch_size,
        'discount':args.discount,
        'action_reward_observation':True,
        'violation_termination':False,
        'task_kwargs':task_kwargs,
        'jax_backend':jax.default_backend(),
        'action_shape':list(spec.shape),
        'observation_shape':list(probe.shape),
        'physics_timestep':.002,
        'control_timestep':.05,
        'learner_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parent,text=True).strip(),
        'checkpoint_interval':args.checkpoint_interval,
        'eval_interval':args.eval_interval,
        'eval_seed':args.eval_seed,
        'onset_tolerance_steps':args.onset_tolerance_steps,
        'max_collision_frames':args.max_collision_frames,
        'max_joint_limit_frames':args.max_joint_limit_frames,
    }
    metadata['steps'] = args.steps
    metadata['resumed_from_step'] = start_step if resuming else None
    metadata['resume_count'] = int(metadata.get('resume_count',0))+int(resuming)
    if not resuming:
        metadata['initialized_from'] = str(args.init_from) if args.init_from is not None else None
        metadata['initialized_from_best'] = bool(args.init_from is not None and args.init_best)
    write_json(output/'config.json',metadata)
    (output/'dependencies.txt').write_text(subprocess.check_output([os.sys.executable,'-m','pip','freeze'],text=True))
    eval_raw, eval_env = make_env(args.eval_seed,args.robot,task_kwargs,args.environment,args.midi_file)
    start = time.monotonic()
    try:
        with (output/'training.jsonl').open('a' if resuming else 'w',buffering=1) as log:
            for step in range(start_step+1,args.steps+1):
                if step <= args.warmup:
                    action = rng.uniform(spec.minimum,spec.maximum).astype(np.float32)
                else:
                    agent,action = agent.sample_actions(ts.observation)
                try:
                    ts = env.step(np.asarray(action))
                except PhysicsError:
                    # An early policy can drive the arms into an invalid physics
                    # state; drop the transition, reset, and keep training.
                    physics_invalid += 1
                    ts = env.reset()
                    buffer.insert(ts,None)
                    continue
                if (not np.isfinite(ts.observation).all() or not np.isfinite(ts.reward) or
                        not np.isfinite(raw.physics.data.qacc).all()):
                    raise FloatingPointError(f'Nonfinite transition or qacc at step {step}; resume from the latest checkpoint')
                buffer.insert(ts,action)
                components = raw.task.reward_components(raw.physics)
                step_safety = raw.task.step_safety_metrics()
                training_safety['collision_frames'] += int(step_safety['collision'])
                training_safety['joint_limit_frames'] += int(step_safety['joint_limit'])
                if ts.last():
                    episodes += 1
                    reason = raw.task.termination_reason
                    reasons[reason] = reasons.get(reason,0)+1
                    ts = env.reset()
                    buffer.insert(ts,None)
                metrics = {}
                if step > args.warmup and buffer.is_ready():
                    agent, values = agent.update(buffer.sample())
                    metrics = {k:float(v) for k,v in values.items()}
                    if not all(np.isfinite(v) for v in metrics.values()):
                        raise FloatingPointError(f'Nonfinite learner metrics at step {step}; resume from the latest checkpoint')
                    updates += 1
                current_seconds = elapsed+time.monotonic()-start
                if step % 100 == 0 or step in (args.warmup+1,args.steps):
                    row = {
                        'step':step,
                        'updates':updates,
                        'episodes':episodes,
                        'seconds':current_seconds,
                        'training_collision_frames':training_safety['collision_frames'],
                        'training_joint_limit_frames':training_safety['joint_limit_frames'],
                        **{'component_'+k:float(v) for k,v in components.items()},
                        **metrics,
                    }
                    log.write(json.dumps(row,allow_nan=False)+'\n')
                    print(json.dumps(row),flush=True)
                probe = ts.observation.copy()
                if step % args.eval_interval == 0 or step == args.steps:
                    try:
                        evaluation = evaluate(
                            eval_raw,eval_env,agent.eval_actions,
                            output/'evaluations'/f'step_{step:07d}',
                            record_video=False,
                            onset_tolerance_steps=args.onset_tolerance_steps,
                        )
                    except PhysicsError:
                        # An untrained policy can drive the arms into an invalid
                        # physics state; record the failed eval and keep training.
                        write_json(output/'evaluations'/f'step_{step:07d}'/'failed.json',
                                   {'step':step,'reason':'physics_invalid'})
                        evaluation = None
                    if evaluation is not None:
                        rank = evaluation_rank(evaluation,args.max_collision_frames,args.max_joint_limit_frames)
                        write_json(output/'evaluations'/f'step_{step:07d}'/'rank.json',{'rank':list(rank)})
                        if best_rank is None or rank > best_rank:
                            best_rank = rank
                            save_best(output,agent,probe,step,evaluation,rank)
                if step % args.checkpoint_interval == 0 or step == args.steps:
                    state = {
                        'step':step,
                        'updates':updates,
                        'episodes':episodes,
                        'reasons':reasons,
                        'initial_hash':initial_hash,
                        'best_rank':best_rank,
                        'seconds':current_seconds,
                        'training_safety':training_safety,
                        'physics_invalid':physics_invalid,
                        'rng_state':rng.get_state(),
                        'np_random_state':np.random.get_state(),
                        'buffer':buffer,
                    }
                    save_checkpoint(output,agent,buffer,state,probe)
    finally:
        eval_raw.close()
        raw.close()
    final_hash = fingerprint(agent.actor.params)
    if args.steps > args.warmup and (not updates or initial_hash == final_hash):
        raise RuntimeError('Learner did not update actor parameters')
    write_json(output/'training_summary.json',{
        'steps':args.steps,
        'resumed_from_step':start_step if resuming else None,
        'random_steps':min(args.warmup,args.steps),
        'updates':updates,
        'initial_actor_sha256':initial_hash,
        'final_actor_sha256':final_hash,
        'termination_counts':reasons,
        'training_safety':training_safety,
        'physics_invalid_steps':physics_invalid,
        'seconds':elapsed+time.monotonic()-start,
    })
    subprocess.run([os.sys.executable,'-B',str(Path(__file__).resolve()),'evaluate','--output',str(output)],check=True)


def reload_and_evaluate(args):
    from flax import serialization
    config = json.loads((args.output/'config.json').read_text())
    raw, env = make_env(config.get('eval_seed',config['seed']),config['robot'],config.get('task_kwargs'),config['environment'],config.get('midi_file'))
    template = initialize_agent(env,config['agent_config'],config['seed'],config['discount'])
    prefix = 'best_' if args.best else ''
    agent = serialization.from_bytes(template,(args.output/(prefix+'checkpoint.msgpack')).read_bytes())
    probe = np.load(args.output/(prefix+'reload_probe.npz'))
    restored = np.asarray(agent.eval_actions(probe['observation']))
    error = float(np.max(np.abs(restored-probe['action'])))
    if not np.array_equal(restored,probe['action']):
        raise AssertionError(f'Restored action differs: {error}')
    metrics = evaluate(
        raw,env,agent.eval_actions,args.output/(prefix+'evaluation'),
        onset_tolerance_steps=config.get('onset_tolerance_steps',1),
    )
    write_json(args.output/(prefix+'reload_verification.json'),{
        'fresh_process':True,
        'deterministic_actions_equal':True,
        'maximum_absolute_error':error,
        'actor_step':int(agent.actor.step),
        'episode_finished':True,
        'termination_reason':metrics['termination_reason'],
    })
    print(json.dumps(metrics,ensure_ascii=False),flush=True)
    raw.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['env','train','evaluate'])
    parser.add_argument('--robot',default='rm75_l20',choices=['rm75_l20'])
    parser.add_argument('--environment',default=ENVIRONMENT,
                        help='suite environment name; real scores e.g. RoboPianist-debug-TwinkleTwinkleRousseau-v0')
    parser.add_argument('--midi-file',type=Path,default=None,
                        help='optional MIDI path overriding --environment (e.g. PianoVAM/SkyPiano derived)')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--steps',type=int,default=6000)
    parser.add_argument('--warmup',type=int,default=5000)
    parser.add_argument('--batch-size',type=int,default=256)
    parser.add_argument('--discount',type=float,default=.8)
    parser.add_argument('--fingering-margin',type=float,default=None,
                        help='fingertip-to-key tolerance in metres; default keeps official 0.01')
    parser.add_argument('--energy-coef',type=float,default=None,
                        help='energy penalty coefficient; default keeps official 0.005')
    parser.add_argument('--safety-penalty',type=float,default=0.,
                        help='negative forearm reward on a control step with collision or joint-limit violation')
    parser.add_argument('--trim-silence',action=argparse.BooleanOptionalAction,default=True,
                        help='trim leading/trailing MIDI silence; use --no-trim-silence for legacy runs')
    parser.add_argument('--initial-buffer-time',type=float,default=.5,
                        help='preparation silence in seconds after trimming')
    parser.add_argument('--trailing-silence',type=float,default=.5,
                        help='explicit trailing silence in seconds for release evaluation')
    parser.add_argument('--note-offset',type=int,default=0,
                        help='zero-based offset in the chronologically sorted score')
    parser.add_argument('--note-limit',type=int,default=None,
                        help='curriculum window size; omit for the full score')
    parser.add_argument('--checkpoint-interval',type=int,default=5000)
    parser.add_argument('--eval-interval',type=int,default=10000)
    parser.add_argument('--eval-seed',type=int,default=1007)
    parser.add_argument('--onset-tolerance-steps',type=int,default=1)
    parser.add_argument('--max-collision-frames',type=int,default=None,
                        help='optional safety gate for best-checkpoint selection')
    parser.add_argument('--max-joint-limit-frames',type=int,default=None,
                        help='optional safety gate for best-checkpoint selection')
    parser.add_argument('--resume',type=Path,default=None,
                        help='resume this run from its latest checkpoint; --output must be the same directory and --steps is the total target')
    parser.add_argument('--init-from',type=Path,default=None,
                        help='initialize a new curriculum stage from another run directory without restoring its task or replay')
    parser.add_argument('--init-best',action='store_true',help='use best_checkpoint.msgpack with --init-from')
    parser.add_argument('--best',action='store_true',help='evaluate best_checkpoint.msgpack instead of the final checkpoint')
    parser.add_argument('--algorithm',choices=['sac','droq'],default='droq')
    args = parser.parse_args()
    if args.checkpoint_interval <= 0 or args.eval_interval <= 0:
        parser.error('checkpoint and evaluation intervals must be positive')
    if args.onset_tolerance_steps < 0:
        parser.error('onset tolerance must be nonnegative')
    if args.safety_penalty < 0 or args.initial_buffer_time < 0 or args.trailing_silence < 0:
        parser.error('safety penalty and silence buffers must be nonnegative')
    if args.note_offset < 0 or (args.note_limit is not None and args.note_limit <= 0):
        parser.error('note offset must be nonnegative and note limit must be positive')
    if args.resume is not None and args.init_from is not None:
        parser.error('--resume and --init-from are mutually exclusive')
    if args.init_best and args.init_from is None:
        parser.error('--init-best requires --init-from')
    if args.mode == 'train':
        train(args)
    elif args.mode == 'evaluate':
        reload_and_evaluate(args)
    else:
        raw,env=make_env(args.seed,args.robot,reward_kwargs(args),args.environment,args.midi_file)
        spec=raw.action_spec()
        canonical=(2*(raw.task.home_action-spec.minimum)/(spec.maximum-spec.minimum)-1).astype(np.float32)
        print(json.dumps(evaluate(raw,env,lambda _:canonical,args.output,onset_tolerance_steps=args.onset_tolerance_steps)),flush=True)
        raw.close()


if __name__ == '__main__':
    main()
