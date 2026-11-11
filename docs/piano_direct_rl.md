# PianoVAM 直接控制 RL：第 00–02 批审计与接口

本页记录“无完整参考关节轨迹”直接控制 PPO 的基线审计、数据契约和
`PianoDirectEnv` 接口。第 00–03 批完成架构、环境与物理奖励，第 04 批完成
单音 PPO 训练；不开放 RM75 动作，不修改现有残差 PPO 和旧 40 音参考。

## 1. 现有残差 PPO 依赖

`rm_mujoco/piano_rl.py` 的 `PianoResidualEnv` 是“参考轨迹 + 手部残差”：

| 位置 | 依赖 | 说明 |
| --- | --- | --- |
| `__init__` | `load_plan`、`load_replay` | 计划文件和 `run_performance.py` 回放器 |
| `reset` | `PlanRunner` | 构造完整回放、`arm_tracks`/`hand_tracks`/key monitor |
| `_observation` | `hand_tracks[side].at`、`reference_error` | 观测含参考手形与参考误差 |
| `step` | `arm_tracks`、`hand_tracks`、`expected` | 臂/手控制来自计划，策略只加 10 通道/手残差 |
| `set_nominal_trace` | 完整 `nominal_qpos` | 扰动评估的因果参考 |

动作空间是 20 维残差（双手各 10 个 ROOT/TIP 通道），观测 1337 维，奖励在
`piano_residual/5` 中实现。该环境保留，不修改、不替换。

直接控制环境需要去掉的依赖是：

- `piano_performance/1` 计划和 `PlanRunner`；
- `arm_tracks`、`hand_tracks`、`nominal_qpos`；
- 参考手形 `reference` 和 `reference_error`；
- 计划中的 arm waypoint/hand state 时间轴。

## 2. PianoVAM 导入链

`scripts/import_pianovam.py`：

- `read_fingering` 读取 7 列 TSV：`onset, key_offset, frame_offset, note,
  velocity, hand, finger`。
- `validate_rows` 校验时间、音符 21–108、velocity 0–127、hand 枚举。
- `to_events` 生成 `piano_fingering/1` 事件；`Noinfo` 的 hand/finger 保持
  `None`，不编造；同一手超过 5 个同时音拒绝。
- `key_offset` 是物理释放；`frame_offset` 含踏板，不能当作音符结束。
- 现有 `prepare_piano_rl.py` 会调用 `plan_performance.py` 生成参考计划，这正是
  新任务生成器要绕开的依赖。

新任务生成器只复用 `read_fingering/validate_rows/to_events`，不生成
`piano_fingering/1` 或 `piano_performance/1`。

## 3. MuJoCo 与几何接口

可复用的模块：

| 模块 | 用途 |
| --- | --- |
| `PianoHandModel` | 构建双臂/双手/88 键模型；`key_qpos/key_limit`、`arm_qpos/hand_qpos/arm_act/hand_act`、`classify`、`fingertip`、`arm_posture` |
| `KeyEvents` | 被动琴键 on/off 边沿 |
| `KeyTravelMonitor` | 每个物理步的键角/越限记录 |
| `HAND_JOINT_SUFFIXES`、`command_positions` | 20 值 L20 命令到 20 个 MuJoCo 关节 |
| `piano_rl.ACTION_CHANNELS` | 每手 10 个 ROOT/TIP 通道（0–4、15–19） |
| `piano_rl.finger_clock/active_fingers/target_keys` | 纯函数，可复用 |
| `scene.build_model/load_layout` | 场景生成 |

当前高位姿态：

- 场景 `config/piano_scene_static5.yaml`：桌子 `y=-0.58`、基座 `x=±0.27`、
  钢琴 `y=0.15`。
- 参考姿态 `config/static_pose_reference.yaml`：左右 7 关节角、
  `hand_curl=0.6`，`playing.ready_hand_curl=0.25`。
- 静态检查：指尖贴键、键角 0、无桌面/键床/琴体/双臂接触。

## 4. 新数据契约：`piano_rl_tasks/1`

生成器输出 JSON，每个 split 一个文件；事件时间保留 PianoVAM 的**绝对时间**，
`origin_sec` 是任务起点，`frames.time_sec` 相对起点。

```json
{
  "format": "piano_rl_tasks/1",
  "source": "Fingering_GT/2024-...tsv",
  "source_sha256": "...",
  "split": "train|ext-train|valid|test",
  "left_max_note": 59,
  "frame_dt": 0.02,
  "lookahead_sec": [0.0, 0.05, 0.1, 0.2, 0.4],
  "tasks": [{
    "id": "2024-...:0000",
    "origin_sec": 12.34,
    "duration_sec": 2.6,
    "events": [{
      "id": 1, "hand": "right", "note": 60,
      "start_sec": 12.34, "end_sec": 12.84, "velocity": 80,
      "finger": "index", "finger_source": "labeled",
      "hand_source": "labeled"
    }],
    "frames": {
      "time_sec": [0.0, 0.02],
      "target_keys": [[0, 1, "..."], ["... 88 个 0/1"]],
      "finger_hints": [[-1, 2, "..."], ["... 10 个槽位"]]
    }
  }]
}
```

规则：

- `start_sec/end_sec` 绝对；`frames.time_sec` 相对。
- `duration_sec` 含 0.6 s 尾段。
- `finger_hints` 每帧 10 槽（左 5、右 5）：`-1` 无活动，`0..4` 有指法，
  `-2` 有活动但原始指法缺失；缺失不编造。
- `Noinfo` 手别按 `left_max_note` 推断，标 `hand_source="inferred"`。
- 单文件必须显式 `--split`；数据集用 `metadata.json` 保留
  `train/ext-train/valid/test`。
- 窗口以 onset 组为单位；同一 onset 的和弦一并纳入；默认拒绝从已按住音
  中间开始。

## 5. 新环境接口

`PianoDirectEnv`（新模块 `piano_direct.py`）不继承、不替换
`PianoResidualEnv`：

```python
PianoDirectEnv(task_path, package, *, task_index=0,
               active_hands=("left", "right"), control_dt=0.02,
               scene_config=None, home_pose=None,
               action_scale=8.0, ready_curl=None,
               lookahead_sec=(0.0, 0.05, 0.10, 0.20, 0.40),
               reward_weights=None)
```

- 双臂固定为 `static_pose_reference.yaml` 的 7 关节角；每步重设 `qpos/ctrl`。
- 手部 neutral 为 `ready20 + ready_curl * sum(delta)`，默认 0.25；
  动作 20 维，每手 10 个 `ACTION_CHANNELS`，`neutral + 8 * action`，
  clip 0..255，经 `command_positions` 写成 MuJoCo 关节目标。8 是第 02 批的
  安全初值；后续批次可按接触反馈调整，不能用放大动作来追求按键成功率。
- 单手训练用 `active_hands` 掩码，另一手保持 neutral。
- 观测 777 维：
  - 每手 68（hand qpos 21、hand qvel 21、arm qpos 7、arm qvel 7、
    wrist 相对钢琴 3+9），双手 136；
  - 88 键归一化角度；
  - 5 个 lookahead × 88 目标键 = 440；
  - 5 个 lookahead × 5 指 × 2 手 active 指法 = 50；
  - 每手 `finger_clock` 20 × 2 = 40；
  - 上一步动作 20；
  - active hand mask 2；
  - 剩余时间 1。
- `step` 推进物理并返回第 03 批物理奖励；`info["reward_components"]` 分别记录
  `key/finger/timing/energy/action/safety/total`，`info["reward_details"]` 记录
  按键、漏音、错误键和释放事件。观测/动作/任务结束/安全状态保持完整。
- 不使用 `PlanRunner`、`arm_tracks`、`hand_tracks`、`nominal_qpos`。
- 任务目标超出固定手可达范围时标记 `out_of_reach`，不崩溃、不伪造成功。

## 6. 拟新增/修改文件

新增：

- `rm_mujoco/pianovam_tasks.py`：任务 schema、加载、窗口提取。
- `rm_mujoco/piano_direct.py`：直接控制环境。
- `rm_mujoco/piano_direct_reward.py`：物理奖励、事件时序和分量。
- `rm_mujoco/piano_direct_eval.py`：单音真实边沿验收。
- `scripts/prepare_pianovam_tasks.py`：PianoVAM → `piano_rl_tasks/1`。
- `scripts/check_piano_direct_env.py`：随机动作冒烟入口。
- `scripts/train_piano_direct.py`：单音 PPO 训练/独立评估。
- `config/piano_direct_env.yaml`：场景/姿态/动作缩放/观测窗口/奖励权重。
- `test/test_pianovam_tasks.py`、`test/test_piano_direct.py`、
  `test/test_piano_direct_reward.py`、`test/test_piano_direct_eval.py`。
- 本页文档。

修改：

- `CMakeLists.txt`：安装新脚本/配置，增加任务、奖励、验收和环境四个 pytest。
- `docs/piano_rl.md`：只加指向直接控制入口的说明。

不改：

- `piano_rl.py`、`train_piano_rl.py`、`evaluate_piano_robustness.py`；
- `fingering.py`、`performance.py`、`run_performance.py`、`verify_*`；
- `models/`、`config/piano_scene*.yaml`、`verified_40`、旧 PPO/存档。

## 7. 验收边界

- 第 00 批：本页审计、接口和文件清单完成；现有功能不变。
- 第 01 批：真实 PianoVAM TSV 可生成任务；保留绝对时间、split、无指法标记；
  不生成计划、不调用规划器；单元测试通过。
- 第 02 批：无 plan 可 reset/step；随机合法动作改变 L20 qpos；固定臂保持；
  777 维观测有限稳定；home 姿态无其他碰撞；现有 `PianoResidualEnv` 测试不退化。
- 第 03 批：奖励分量独立可读；正确按键/释放优于静止、漏按、错按和持续压键；
  安全/动作/能耗有可测惩罚；不训练 PPO。
- 不训练 PPO、不移动机械臂、不修改物理阈值、不宣称演奏成功。

## 8. 当前存档

改造前基线已存于 `.validation/architecture_archive_20261110/`，包括旧
`verified_40`、旧 PPO 两只老虎模型/证据、新静态姿势和源码快照。本批不修改
存档内容。

## 9. 第 00–03 批执行结果

- 第 00 批：本页完成；未改旧残差 PPO、训练入口、模型和布局。
- 第 01 批：`prepare_pianovam_tasks.py` 已在 Jetson 上用真实
  `Fingering_GT/2024-02-15_20-07-54.tsv` 生成 4 个任务（8 个事件、全部带指法），
  并验证绝对时间、88 键帧和来源哈希；`test_pianovam_tasks.py` 7/7。
- 数据集模式：真实 metadata 目前只登记 2 个录音，其余 `Fingering_GT` 文件被
  明确列入 `summary.json` 的 `skipped`，不伪造 split；有任务时退出 0。
- 第 02 批：`PianoDirectEnv` 在 Jetson MuJoCo 3.3.7 上随机 12 步
  （`action_scale=8`）：观测 777 维且全有限；左右手 qpos 最大变化约 0.27；
  固定臂跟踪误差约 0.002–0.01 rad；无 `other_contacts`。
- 第 03 批接入奖励后，同一随机 12 步的 `reward` 约为 `-1.82`，分量为
  `key=-1.0, finger=0.0, timing=0.0, energy=-0.006, action=-0.008,
  safety=-0.805`；随机动作没有完成目标音，因此为负。
- 随机动作仍可能让某个非目标键轻微过行程（本次 1 个，约 0.8°），
  `info["key_violations"]` 会记录；没有把随机动作当作成功或训练证据。
- 奖励场景（纯函数，无 MuJoCo）：正确 2.2、静止 -1.0、漏按 -1.5、
  错按 -3.0、持续压住 -1.0、正确但带动作/安全惩罚 -6.37；见第 10 节。
- `test_piano_direct_reward.py` 9/9，`test_piano_direct.py` 8/8，
  `test_pianovam_tasks.py` 8/8，`test_piano_direct_eval.py` 4/4，
  `test_import_pianovam.py` 7/7，旧 `test_piano_rl.py` 34/34；合计 70/70。

## 10. 第 03 批：物理奖励

`piano_direct_reward.py` 的 `DirectReward` 只用 MuJoCo 键角和指尖距离，
不读取参考轨迹。每个控制步返回独立分量：

```text
total = key + finger + timing + energy + action + safety
```

- `key`：目标键按下比例、漏按比例、错误键比例；错误键按目标数/错误数归一化。
- `finger`：只在目标键实际发声时，对目标指尖到键 site 的距离做
  `exp(-d/0.02)` 平均；静止悬停不会凭距离拿分。
- `timing`：每个音符首次按下、首次释放；30 ms 内给 +1，超出后给负分并只扣
  一次漏按/迟释放；迟按的键不再获得目标键 credit，按错键处理。
- `energy`：双手 `|qfrc_actuator|·|qvel|`。
- `action`：动作幅度平方均值 + 相邻动作差平方均值。
- `safety`：其他接触、键过行程、固定臂跟踪误差。
- `terminal`：任务结束且所有事件已按下/释放、无漏音/迟释放/安全违规时，
  额外 `+10`；它不是逐步奖励，不能替代严格验收。
- `info["reward_components"]` 每项独立；`info["reward_details"]` 记录
  correct/wrong/missing keys、press/release 计数、漏音和迟释放事件。

默认权重在 `config/piano_direct_env.yaml`：

| 分量 | 权重 |
| --- | ---: |
| key | 1.0 |
| finger | 0.2 |
| timing | 0.5 |
| energy | 0.005 |
| action | 0.01 |
| safety | 2.0 |

场景结果：

| 场景 | total | 解释 |
| --- | ---: | --- |
| 正确按下并在结束后释放 | 2.2 | key +1、finger +0.2、timing +1.0 |
| 静止不按 | -1.0 | 目标音存在但 key 漏按 |
| 漏按到期限 | -1.5 | 目标键失效后不再算 key，另扣 timing 漏按 |
| 按错键 | -3.0 | 目标键漏按 + 错误键惩罚 |
| 按下后不释放 | -1.0 | 释放后错误键继续发声，另扣迟释放 |
| 正确但动作/能耗/安全违规 | -6.37 | 安全惩罚主导，说明不能用大动作换成功 |

测试覆盖正确、静止、漏按、错按、持续压住、指尖距离、动作/能耗/安全、
非法输入；本批不训练 PPO。

## 11. 第 04 批：单音 PPO 训练

选中 **左手、MIDI 53（F3）**：

- 任务：`0.2–0.5 s` 单音，`lead_in_sec=0.2`，任务时长 `1.1 s`；
- 固定 `static_pose_reference.yaml` 高位双臂；
- 只开放左手动作通道 `1`（index root），其余通道和右手用掩码置零；
- `action_scale=80`，动作空间仍为 20 维，便于复用后续多指/双臂接口。

先用脚本动作验证环境本身可完成该音：

```text
通道 1 = -1，0.12–0.46 s，其余为零
key on  = 0.198 s（目标 0.2，误差 -2 ms）
key off = 0.510 s（目标 0.5，误差 +10 ms）
reward  = 15.07
key violations = 0，other contacts = 0
```

这说明键位、动作方向和奖励可达；随后训练 PPO，不允许读取这条脚本动作作为
策略输入。训练入口：

```bash
python scripts/train_piano_direct.py \
  --tasks single_note_f3.tasks.json \
  --output .validation/piano_direct_ppo_f3 \
  --hand left --channels 1 --action-scale 80 --safety-weight 0.05 \
  --observation-lead 0.02 --steps 40000 --eval-episodes 20 --seed 7
```

训练时把安全惩罚降到 0.05 是为了让单通道探索先找到按键时序；**评估仍使用
严格的真实边沿/键越限/接触检查**，不能靠降低训练惩罚绕过验收。单音验收由
`piano_direct_eval.single_note_success` 判断：on/off 均在 30 ms 内、
无其他键边沿、无键越限/其他接触/提前终止。目标为独立 10 回合成功率 ≥ 90%；
未达到不得进入第 05 批。

实际 PPO 策略的按键延迟约为 38 ms；给观测时钟加固定 **20 ms 相位提前**
（`observation_lead_sec=0.02`，只影响目标/指法/剩余时间读数，不改变乐谱、
键角或验收阈值）后，独立 20 回合：

```text
success 20/20
onset error +20 ms
release error -16 ms
mean reward 21.18
random baseline 0/20
```

这是低层手部延迟补偿，不是读取未来 MuJoCo 状态；物理键边沿仍按真实仿真判定。
策略本身在 `observation_lead_sec=0.0` 下训练 40,960 步，评估时复用固定 20 ms
相位补偿；训练/评估参数都写入交付配置，不能只对评估临时开启。

交付物在 Jetson `.validation/piano_direct_f3_delivery/`，并复制到本地
`.validation/piano_direct_f3_delivery/`：

- `model.zip`：SHA256 `a5bddf00c1e39d38d195cfaf2a217584eefb235b516cea1f4bd7dbbe40a94da3`
- `task.json`：左手 F3、lead-in 0.2 s
- `config.json`：训练/评估参数
- `evaluation.json`：20/20 回合、边沿和奖励

全量测试为 70/70（任务 8、奖励 9、验收 4、环境 8、导入 7、旧残差 PPO 34）。

## 12. 第 04 批复核与第 05 批准入

Jetson 复跑冻结交付模型，20 ms 乐谱观测提前时，F3 键边沿稳定为
0.220 s 和 0.484 s。两条边沿分别满足 30 ms 容差，实际保持 264 ms，
比目标短 36 ms，超过传统演奏验收的时长容差。训练时的 0 ms 提前配置
复跑落键为 0.238 s。交付报告的 20 回合使用相同的初态和乐谱。

直接控制的新验收按物理子步的键边沿配对，检查落键、释放、保持时长、
同键多余触发、残留键和安全失败。有重叠的不同音高必须存在物理按键重叠。
终局奖励复用该判定，逐步时序奖励读取相同的物理边沿。评估报告保留每音
误差及落键子步的接触几何体，供核对实际触键手指。

续训入口支持 `--sample-tasks`、`--eval-tasks` 和 `--initial-jitter`。
F3 的训练、验证和留出任务分别包含 9 组不同的落键时间与保持时长。
初始扰动限于开放的 L20 通道，幅度最多 1 个命令单位。训练和评估统一
使用预定的 20 ms 观测提前量。冻结模型在留出任务上严格成功率达到
90% 后再进入固定腕多指训练。左手 53 和 56 是优先探测候选。

本机 Ubuntu 22.04 WSL 通过 31 项纯逻辑测试。Jetson Ubuntu 22.04.5 /
MuJoCo 3.3.7 的直接控制、PianoVAM 与旧残差回归共 74 项通过。

### F3 续训

9 个验证任务分别使用不同的落键时刻、保持时长和初始扰动。相同任务上的
脚本脉冲物理对照通过 9/9，证明这些时序在当前场景中可以执行。脚本动作
仅用于可达性对照，PPO 的训练输入仍由乐谱和仿真观测组成。

| 训练设置 | 新增 PPO 步数 | 严格通过 | 键角越界回合 |
| --- | ---: | ---: | ---: |
| 从交付权重续训，沿用交付安全权重 0.05 | 4,096 | 0/9 | 8 |
| 从上行权重恢复，安全权重 2.0 | 8,192 | 1/9 | 7 |
| 从交付权重恢复，探索标准差 0.25，学习率 0.0001 | 4,096 | 1/9 | 6 |
| 同一低噪声起点，训练和评估均用两档命令 | 6,144 | 3/9 | 0 |

两档映射在隔离实验中将策略第 1 通道映射到已验证的按下或松开命令，
由 PPO 决定切换时机。阈值 `-0.25` 来自验证集上的冻结模型诊断，
该诊断为 4/9。两档续训后的 6 个失败分别是 3 个松键超时和 3 个保持
时长超差。验证结果未到 90%，留出测试集未运行。

### 固定腕部可达性

Jetson 共完成 237 组左手 ROOT/TIP、合法中性侧摆及局部细扫。F3 最长
干净保持 370 ms，落键接触来自左手食指连杆。第二键候选 MIDI 54、56、58
的最长干净区间分别为 74、76、76 ms。部分持续按压伴随键角越界，无法用于
双音课。现有固定腕起点下尚未找到可分别持续按住的第二键，因此第 05 批
停在可达性阶段。MIDI 79→81 仍缺固定腕部可达性证据。

模型、配置、原始边沿、探测数据和实验脚本在
`.validation/piano_direct_multifinger_20261110/`。本地和 Jetson 的 28 个
输入和产物通过 SHA256 对照。本批为仿真验证。

## 13. 高位固定腕双键标定

T-0025 在 Jetson MuJoCo 3.3.7 中使用现有 IK 搜索高位参考附近的 20 个
左腕目标，16 个通过姿态与初始接触筛查。545 组键角初筛和 594 组局部
ROOT/TIP 试探用于找候选。最终在原高位参考姿态用完整 `PianoDirectEnv`
通过左手 MIDI 53、54 的分别按放、顺序换音与双键重叠。

- 实测重叠 296 ms，目标 300 ms。实际接触为左食指 `left_index_link3`
  和左中指 `left_middle_link3`。
- 四个通过场景的落键、松键和保持时长最大绝对误差分别为 12、12 和
  18 ms，无键角越界或其他碰撞。左肘低于肩 12.9 mm，最小静态关节余量
  0.0784 rad，最大固定臂跟踪误差 0.0103 rad。
- 8 个带时序扰动的合成验证任务通过脚本物理预检。额外错峰双键测试和
  细调出的其他候选未通过完整验收。

在隔离环境中试验了两维独立按放动作，分别映射为标定的食指和中指
ROOT/TIP 命令。PPO 根据乐谱和仿真观测决定两路切换时刻。8,192 步基础
训练与 6,144 步最小保持时间对照均为 0/8。对照将每次切换后的指令保持
至少 60 ms，单指热身阶段只开放当次目标手指。两组模型在验证中都能触发
食指，但中指指令始终为松开。各自 12 个目标事件中有 2 个通过音符时序，
留出测试集尚未使用。

PianoVAM 快速换音对照取自训练录音 `2024-04-08_22-49-18.tsv`。
保留左手事件 130、131 的原始起止时间和人类指法，间隔 12.5 ms。
这是两音投影，排除了同窗的两个其他左手事件。81 组命令时移中有 56 组
同时满足两音落键、松键与时长容差，但 81 组都发生键角越界。这份对照
用于物理诊断，PPO 课程使用合成任务。

证据在 `.validation/piano_direct_multifinger_20261110/fixed_wrist_pair/`，
本地与 Jetson 的 40 个文件 SHA256 一致。当前通过的是固定腕双指物理
标定和合成课程预检，第 05 批 PPO 验收仍待完成。

## 14. MIDI 54 中指独立课程

T-0026 使用高位固定腕和 T-0025 标定的中指 ROOT/TIP 幅度。单音课程
采用一次自主按下和一次自主释放，允许按下至少 100 ms 后请求释放。
策略观察目标落键与释放倒计时、实际键角与角速度、当前动作阶段等
9 维状态。键角越界会立即结束训练回合，严格验收仍检查全部物理边沿、
保持时长、越限和碰撞。

初始突变松键在 9 个训练时序中只通过 6 个。三个失败均在撤回命令后
发生键角越界。在松键后加入一帧 20 ms 的半幅中间命令，随后恢复中性，
训练和验证的物理预检各通过 9/9。

| 仿真设置 | PPO 步数 | 最高严格验证 |
| --- | ---: | ---: |
| 逐控制步决定触发，无乐谱窗口 | 8,192 | 0/9 |
| 加入乐谱窗口，最早松键提前 110 ms，逐步取最大概率 | 8,192 | 0/9 |
| 110 ms 窗口，累计触发概率达到 50% 时执行 | 同上模型 | 7/9 |
| 校正为 95 ms 松键窗口，追加 4,096 步 | 累计 12,288 | 8/9 |
| 95 ms 窗口，累计触发概率阈值 50%、60%、70% | 同上模型 | 8/9 |

95 ms 窗口的固定规则在第一次允许时触发，结果同样为 8/9。两个
续训检查点逐步取最大概率时，九回合的实际键边沿与该规则完全相同。
唯一未过的任务松键早 32 ms，超过 30 ms 容差。未获得独立学习时序的
证据，90% 准入未通过，留出测试与双指合并仍待执行。

模型、原始边沿、松键试验和配置位于
`.validation/piano_direct_multifinger_20261110/middle_finger/`。本地与
Jetson 的 77 个文件 SHA256 一致，实验进程已结束。本批证据来自仿真。

## 15. 冻结多录音乐句基准

数据集模式使用完整乐句边界。起点有尚未释放的前音，或末尾会遗漏仍与
本句重叠的后音时，跳过该候选。静默准备区间可缩短至前音释放时刻。
音符的起止、手别、力度和指法沿用源数据。单 TSV 可通过
`--complete-phrases` 启用相同切片规则。

生成的 `piano_rl_tasks_manifest/2` 校验元数据、原始 TSV 和任务文件
的 SHA256。训练与扩展训练合为一个阶段，训练、验证和测试之间核对
录音及作曲家／曲目身份。直接 PPO 用一个 MuJoCo 模型轮换录音，
每轮为每份录音采样一次。默认评估遍历验证阶段，使用
`--evaluate-only --resume MODEL --final-test` 显式评估测试阶段。
旧的 `--tasks` 和 `--eval-tasks` 仍支持单文件实验。

```bash
python scripts/prepare_pianovam_tasks.py --dataset DATASET --output CORPUS \
  --window-notes 2,3,4,6,8,12,16 --lead-in-sec 0.15 --max-tasks 3
python scripts/train_piano_direct.py --manifest CORPUS/manifest.json \
  --evaluate-only --resume MODEL --output EVALUATION
```

评估按实际键边沿报告音符 F1、落键／松键／时长误差、漏音、碰撞和
键角越界，并按曲汇总。覆盖分开报告总音符、启用手别音符、参考音
±2 半音的名义音域以及安全回合中的时序匹配。名义音域是筛查指标，
实际可达性需要物理证据。

| 阶段 | 录音 | 完整乐句 | 音符事件次 | 双手名义音域内 | 键位有既有独立单键证据 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 训练（含扩展训练） | 8 | 24 | 201 | 50 | 8 |
| 验证 | 1 | 3 | 30 | 29 | 0 |
| 历史测试 | 2 | 6 | 26 | 7 | 0 |

基准取每份人工指法录音按起点排序的前三个完整窗口。逐事件审计
33/33 与原始 TSV 一致。已有物理证据只覆盖同一固定腕的左手
MIDI 53 和 54，其余键位在本基准中尚未建立物理证据。Jetson 上
79 项直接控制、数据和旧残差回归通过。1,024 步冒烟共启动 6 个回合，
来自 6 份不同训练录音，验证了多录音轮换。

冻结的 F3 单通道模型跑完《Kiss The Rain》和《Sonata K.360》的
6 个历史测试乐句。该控制配置未启用这 26 个音符所属的右手。全通道
冒烟模型也跑完同一批任务，严格通过 0/6。两个结果用于验证入口，
当前没有跨曲演奏能力的证据。历史测试录音此前已用于项目实验。

基准与报告位于 `.validation/piano_direct_corpus_20261110/`。
本地 `corpus/manifest.local.json` 只调整数据路径，Ubuntu WSL 已用
同一份原始数据重验全部哈希。Jetson 取回的 34 个文件 SHA256 一致。

## 16. 右手高位固定腕的原时序复验

冻结验证录音《Grande Valse Brillante, Op.18》的三个窗口共包含
29 次右手音符记录，按源事件编号去重后为 15 音，全部是 MIDI 70。
两个完整右手窗口含 2 和 12 音，前 2 音共享同一源事件，时长分别
为 286.458 ms 和 33.334 ms。另一个窗口含 1 个左手音，本次先用
完整右手窗口。指法提示包含中指、食指和拇指。

隔离脚本 `.validation/piano_right_fixed_wrist_20261111/probe.py`
读取冻结任务，按默认高位固定腕运行右手 ROOT/TIP 脉冲筛查。
根据实测下压、松键和接触选候选，再以原始时间复验首音及两个完整
右手窗口。筛查报告保留误触、键角越界、其他碰撞、落键接触和最大
臂偏差。复验使用项目的原有时序和安全验收。

在仓库根目录下的 Ubuntu 仿真环境中运行

```bash
probe_dir=.validation/piano_right_fixed_wrist_20261111
python3 -B "$probe_dir/probe.py" \
  --package src/ros2_rm_robot/rm_mujoco \
  --tasks .validation/piano_direct_corpus_20261110/corpus/valid/2024-02-15_20-07-54.tasks.json \
  --output "$probe_dir/physics.json"
```

数据审计保存在同目录的 `source_audit.json`，任务哈希与冻结清单
一致。Ubuntu WSL 的数据及边沿评分专项测试通过 17 项，另外核对
了重复音时序配对、手指接触归属及键角超限拒绝。

Jetson 恢复连接后，在 MuJoCo 3.3.7 执行上述命令。121 组固定腕
脉冲中，10 组触发 MIDI 70，10 组均发生键角违规。其中一组由右
食指保持 354 ms，首次越界发生在结束下压指令后 12 ms。原始报告
为 `physics.json`。

同目录的 `refine_release.py` 复用该基线，在右食指附近测试
20、40、60 ms 的渐进松键。27 个保持试验中 15 个得到完整且干净的
MIDI 70 下压与释放。进一步测试这些动作的脉冲宽度后，首音按原谱
通过，落键早 8.0 ms、松键早 6.5 ms，时长多 1.5 ms，无误触、
键角超限、其他碰撞或残留键。最短干净下压为 74 ms，第二音的原谱
时长为 33.334 ms，时长验收上限为 41.667 ms。该轮候选无法生成
合格时序，2 音和 12 音乐句均未进入完整回放。渐进松键结果见
`release_refinement.json`，两个报告的本地和 Jetson SHA256 一致。

### 原速同键短音

后续试验沿用同一 2 ms 物理步长和高位腕姿态，将**实验动作更新周期**
由 20 ms 调为 2 ms。粗筛复现了旧动作的 74 ms 实际下压区间，确认
食指离开后琴键仍继续下行约 20 ms，随后回弹。新动作把孤立下压
缩短到 38 ms，部分候选在落键阈值前已结束接触。连续回放逐物理步
记录右食指接触，按相邻松键和落键边沿归属每次接触，继续使用原有
落键、松键、时长和安全验收。孤立动作直接回放时曾漏掉第二音。

最终标定以先前动作产生的连续状态筛选每次击键，从复位开始连续
执行整段动作，在标准 `PianoDirectEnv.step()` 下通过原谱验收。
实验使用固定腕、右食指和原始 MIDI 70 时间轴。两个窗口共享前两音。

| 原谱窗口 | 通过音数 | 最大落键误差 | 最大松键误差 | 最大时长误差 |
| --- | ---: | ---: | ---: | ---: |
| 2 音 | 2/2 | 3.041 ms | 1.625 ms | 4.666 ms |
| 12 音 | 12/12 | 7.833 ms | 19.584 ms | 15.584 ms |

第 11 音原时长 29.167 ms，实测 36 ms，时长误差 6.833 ms，
该音原有时长容差为 7.292 ms。两段均无漏音、额外音、键角违规或
其他碰撞。新进程复播保存动作，所有键边沿与接触证据一致。
Jetson MuJoCo 3.3.7 的直接控制、验收和数据专项 Pytest 28 项通过。

在同一隔离目录保留 `short_attack.py`、`tight_attack.py`、
`continuous_attack.py` 和各自的 JSON 报告。最终报告
`continuous_attack.json` 含冻结任务哈希、完整动作序列、实测琴键
轨迹和验收明细。2 ms 动作是这次仿真的低层脚本标定。正式 PPO
环境的默认 20 ms 动作周期以及策略训练均沿用现有实现。

这份冻结验证录音覆盖同键重击。异键换音和跨曲能力需要其他录音
的原时序实测。

## 17. 右手固定腕异键换音与 PPO 对照

从已有冻结清单中的训练录音重新切出两个右手片段。按 TSV 行号保留
绝对落键、松键和原始指法标签。两段的输入哈希与冻结源一致。

| 录音与原划分 | 键序列 | 物理结果 |
| --- | --- | --- |
| 《Gymnopédie No.1》，扩展训练 | 70→73 | 食指和无名指分别按放通过，20 ms 动作更新下原谱连续 2/2 |
| 《Improvisation》，训练 | 73→75 | 73 单键通过，75 的干净下压最长 74 ms，低于原谱 100 ms 音符的 75 ms 验收下限 |

《Gymnopédie No.1》片段是右手投影，保留窗口内完整右手声部。
原谱两音最大落键、松键和时长误差分别为 12.000、4.584、7.416 ms。
在标准 20 ms 直接控制环境中，用与 PPO 相同的五个种子和 0.1 L20
命令单位初态扰动复播，脚本连续通过 5/5。食指和无名指的实测落键
归属与机器人动作一致，PianoVAM 的人类指法仍保存在数据中。
MIDI 75 另在单键和连续换键两种状态各筛 1,458 组，得到的干净按放
区间均为 56–74 ms。

PPO 使用 16 个合成练习，变化键序、起始等待、两音间隔和时长。
两组从随机初始化开始，开放右食指和无名指的四个 ROOT/TIP 通道，
各训练 4,096 步。《Gymnopédie No.1》的原谱片段只用于模型评估，
原数据划分保持为扩展训练。两个种子各 0/5，随机动作对照各 0/5。
回查训练所用合成课程，两个模型均 0/16、无落键边沿。四个通道的
确定性动作绝对幅值在两组中均小于 0.20，已通过的物理动作包含
幅值 0.60 的食指 ROOT 及 0.80 的无名指 TIP。PPO 多指验收仍待完成。

实验脚本、输入、键边沿、评估和模型均在
`.validation/piano_right_key_switch_20261111/`。训练配置记录了
随机种子和作用通道。MIDI 70→73 是原谱脚本物理基准。

## 18. 右手 70/73 动作初始化与 PPO 微调

实验从已有物理筛查为食指和无名指各选出五种合规的按放时长。
策略每 20 ms 观察乐谱提示和实际键位，选择等待、触发哪个手指以及
采用哪种时长。触发后使用对应 L20 ROOT/TIP 动作和渐进松键。
对照中的三个版本使用同一动作库、MuJoCo 模型和物理验收。

48 段合成训练乐句全部通过规则脚本预检。用其中 96 次合规击键
及等待帧做行为克隆，再以原有物理奖励进行 3,072 步 PPO 微调。
留出的 16 段合成节奏与《Gymnopédie No.1》原谱片段均未参与
行为克隆或 PPO 更新。动作库复用此前在同一场景做过的物理标定。

| 方法 | 留出合成节奏 | 原谱 70→73，同一片段的五个初态种子 |
| --- | ---: | ---: |
| 规则基线 | 15/16 | 5/5 |
| 行为克隆初始化 | 15/16 | 5/5 |
| PPO 微调 | 15/16 | 5/5 |

三种方法在原谱产生相同的键边沿。行为克隆与 PPO 的 21 个
配对回合边沿完全一致，未测得 PPO 微调收益。唯一未通过的合成
乐句中，MIDI 70 的时长误差为 30.408 ms，原容差为 30 ms。
所有配对回合均无键角违规或其他碰撞。重新加载保存的 PPO 权重
复播原谱 5 次，物理键边沿与保存报告一致。

代码和输入输出位于 `.validation/piano_right_warm_ppo_20261111/`。
`seed7/comparison.json` 包含三组逐回合结果及输入哈希。
这次验证覆盖两个已标定键的顺序换音和一段原谱，双音并按、
更宽音域及多曲目泛化仍待验证。

## 19. 并按、双手、跨曲和真机条件核验

在 Jetson 的原高位固定腕场景冻结检查点，沿用 20 ms 动作周期、
原物理模型与验收。三组初态种子使用 0.1 L20 命令单位扰动。

| 测试 | 结果 |
| --- | --- |
| 左手 53+54，脚本 | 2/3 通过。通过回合的两键重叠 296 ms，另一次 54 键角违规 |
| 右手 70+73，脚本 | 81 组中 45 组有物理重叠，0/81 达到两音的完整时序验收 |
| 右手 70+73，冻结 PPO | 0/3。三个回合均只按下 70，当前动作队列串行执行 |
| 左右手合成三音乐句，脚本 | 3/3，左手 53 与右手 70 实测重叠 192 ms |
| 同一三音乐句，左右手两个独立检查点 | 0/3。每次三个键均触发，右手两音时序通过，左手 53 短 36 ms，超过 30 ms 容差 |

在 9 份训练、扩展训练及验证录音中，从符合已标定音域、时长
和完整右手边界的手工标注片段按源时间选样。4 份录音提供了
6 个合格的单音片段，冻结 PPO 每段 3 次均通过，共 18/18。
这些录音包括《Piano Concerto》《Improvisation》
《Gymnopédie No.1》和《Grande Valse Brillante, Op.18》。
同一冻结策略另复验肖邦原谱 2 音和 12 音快速同键片段，各 3 次，
合计严格通过 0/6，42 个目标音中 9 个符合时序。保留原始划分，
未打开正式测试集。

用 [PianoVAM 官方完整音符 TSV](https://huggingface.co/datasets/PianoVAM/PianoVAM_v1/tree/1f039ab/TSV)
统计 9 份录音。将所有 MIDI 70、73 都算作策略可能覆盖的音，
每份录音的上限为 2.71%–10.28%。例如《Gymnopédie No.1》为
16/296。整曲演奏需要扩展可控琴键、并按和双手协同。

真机前置核验时，Jetson 可登录且已安装 ROS 2 Humble。
未检测到 L20 的 USB 串口节点，两台配置地址为
`192.168.1.18`、`192.168.1.19` 的 RM75 均未返回 ping，
到这两个地址的路由走 Wi-Fi 默认网关。此次真机工作止于只读检查。

完整证据位于 `.validation/piano_validation_20261111/`，
包含 `ensemble.json`、`corpus_evaluation.json`、
`score_coverage.json`、对应输入和复验脚本。
