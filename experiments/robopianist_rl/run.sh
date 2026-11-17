#!/bin/bash

WANDB_DIR=/tmp/robopianist/ MUJOCO_GL=egl XLA_PYTHON_CLIENT_PREALLOCATE=false CUDA_VISIBLE_DEVICES=0 MUJOCO_EGL_DEVICE_ID=0 python "$(dirname -- "${BASH_SOURCE[0]}")/train.py" \
    --root-dir /tmp/robopianist/rl/ \
    --warmstart-steps 5000 \
    --max-steps 5000000 \
    --discount 0.8 \
    --agent-config.critic-dropout-rate 0.01 \
    --agent-config.critic-layer-norm \
    --agent-config.hidden-dims 256 256 256 \
    --trim-silence \
    --gravity-compensation \
    --control-timestep 0.05 \
    --n-steps-lookahead 10 \
    --environment-name "RoboPianist-debug-TwinkleTwinkleLittleStar-v0" \
    --robot rm75_l20 \
    --action-reward-observation \
    --eval-episodes 1 \
    --camera-id "rm75_overview" \
    --tqdm-bar
