# T-0055 DroQ 单音仿真基线

该入口独立于 `colcon`。策略每 50 ms 输出一个目标键角，MuJoCo 内环每 1 ms 更新，右手食指按放 MIDI 72。训练种子为 7，周期评估种子为 101，保留种子 202 用于最终复验。默认训练 20,000 步，前 500 步为随机预热。

## 环境准备

使用 Ubuntu 22.04 或 Jetson Linux、Python 3.10。训练和重放默认使用仓内的 [RoboPianist 仿真运行时](../../third_party/robopianist/README.md) 和 [训练源码](../robopianist_rl/README.md)。

- [源码清单](sources.json)按文件内容固定运行时和训练版本。入口校验仓内 Python 源码、历史 Composer 任务及 `rm_mujoco` 的 37 个网格，再在临时目录组装运行副本。
- 无音频仿真无需 SoundFont。复验兼容的隔离快照时，可通过全局参数 `--robopianist` 和 `--training` 指定源码目录；`--soundfont` 可指定音色文件。
- 在独立环境安装 [Python 依赖](requirements.txt)。RoboPianist 运行环境需有 FluidSynth、PortAudio 及 MuJoCo 可用的 EGL。已有 Jetson CPU 环境可直接复用。

```bash
python3.10 -m venv .validation/droq-single-note-venv
source .validation/droq-single-note-venv/bin/activate
python -m pip install -r experiments/droq_single_note/requirements.txt
python -m pip check
python experiments/droq_single_note/reproduce.py check-sources
```

## 训练、重载与验收

在工作空间根目录运行，输出目录应尚未存在。600 步冒烟检查训练更新、完整回合和独立进程重载。完整命令额外检验单音成绩，历史 Jetson CPU 用时约 94 分钟。

```bash
python experiments/droq_single_note/reproduce.py train .validation/droq-single-note-smoke --smoke
python experiments/droq_single_note/reproduce.py train .validation/droq-single-note-20k
python experiments/droq_single_note/reproduce.py replay .validation/droq-single-note-20k --output .validation/droq-single-note-replay
```

完整训练会保存探针观测与动作，并由另一个 Python 进程从 Flax 检查点恢复策略。验收要求探针动作逐位一致、19,500 次更新、零训练物理失稳、评估完整结束、琴键帧 F1=1、零误触、碰撞帧和关节限位帧均为零。原始 MIDI 事件里须只有一次 NoteOn 与 NoteOff，起音和释放误差分别在 ±20 ms 和 ±75 ms 内。这两个时序阈值用于复验 T-0055 的名义单音，其冻结报告的实际 MIDI 起音晚 12.0 ms、释放晚 62.792 ms。后续 T-0057/T-0058 的亚栅格释放属于另一组实验。

已拉取 T-0055 历史报告时，可在 Windows 核对指标，无需 MuJoCo。

```powershell
python experiments/droq_single_note/reproduce.py check-result .validation/rm75_contact_feedback_20261113/hierarchical_droq/remote_evidence/run20k --archived
```

分层环境和训练循环来自 T-0055 Jetson 归档；初始姿态为接触诊断 `wrist_mesh/candidates.json` 的第 4 个候选。历史任务来自接触反馈的源码快照。模型、检查点和评估结果保存在各自的实验输出目录。
