# RoboPianist 仿真运行时

RoboPianist 源码来自上游提交 `0d9736c64eba5faafdf214ed7d38d648ffbd5c7f`，采用 [Apache-2.0](LICENSE)。本目录提供 RM75/L20 仿真所需的 Python 包、Composer 任务和两侧 MJCF 模型。

37 个 RM75/L20 网格由 [ros2_ws 的 rm_mujoco 模型目录](../../src/ros2_rm_robot/rm_mujoco/meshes/)提供，单音入口按 [源码清单](../../experiments/droq_single_note/sources.json)逐一校验。无音频仿真可直接加载此包。需要合成音频时，通过 `ROBOPIANIST_SOUNDFONT` 指定 SoundFont。

自带测试谱由代码生成。跑其他乐曲时，可用 [RM75 训练入口](../../experiments/robopianist_rl/rm75.py) 的 `--midi-file` 传入乐谱。
