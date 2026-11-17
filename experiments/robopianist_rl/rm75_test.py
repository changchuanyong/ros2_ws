import argparse

from rm75 import evaluation_rank, restore_arguments, reward_kwargs


def metrics(f1, onset_recall, collision_frames, joint_limit_frames=0, false_positive=0):
    return {
        'f1':f1,
        'onset_recall':onset_recall,
        'collision_frames':collision_frames,
        'joint_limit_frames':joint_limit_frames,
        'false_positive_key_frames':false_positive,
    }


def test_safety_gate_precedes_f1_for_best_checkpoint():
    risky = metrics(.5,.8,20)
    safe = metrics(.1,.2,0)
    assert evaluation_rank(safe,max_collision_frames=0) > evaluation_rank(risky,max_collision_frames=0)
    assert evaluation_rank(risky) > evaluation_rank(safe)


def test_equal_f1_prefers_less_collision_and_false_positive():
    clean = metrics(.1,.2,2,joint_limit_frames=1,false_positive=0)
    dirty = metrics(.1,.2,3,joint_limit_frames=0,false_positive=0)
    assert evaluation_rank(clean) > evaluation_rank(dirty)


def test_restore_arguments_preserves_training_and_curriculum_config():
    config = {
        'seed':11,
        'robot':'rm75_l20',
        'environment':'RoboPianist-debug-TwinkleTwinkleRousseau-v0',
        'midi_file':None,
        'algorithm':'droq',
        'discount':.8,
        'batch_size':256,
        'warmup_steps':5000,
        'checkpoint_interval':5000,
        'eval_interval':10000,
        'eval_seed':1007,
        'onset_tolerance_steps':1,
        'max_collision_frames':0,
        'max_joint_limit_frames':0,
        'task_kwargs':{
            'fingering_margin_m':.01,
            'energy_penalty_coef':.005,
            'safety_penalty':.5,
            'trim_silence':True,
            'initial_buffer_time':.5,
            'trailing_silence':.5,
            'note_offset':2,
            'note_limit':8,
        },
    }
    args = argparse.Namespace()
    restore_arguments(args,config)
    assert args.seed == 11
    assert args.warmup == 5000
    assert args.max_collision_frames == 0
    assert reward_kwargs(args) == config['task_kwargs']
