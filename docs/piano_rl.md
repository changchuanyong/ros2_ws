# PianoVAM 残差强化学习（MuJoCo）

[返回首页](../README.md) · [钢琴演奏流程](piano_workflow.md)

本入口在已验证的 `piano_performance/1` 参考轨迹上学习 L20 ROOT/TIP 残差。支持原 PianoVAM 右手数据路径，以及冻结《两只老虎》双手 40 音路径。机械臂仍跟随参考轨迹，物理验收仍由原有 `PlanRunner` 完成；不是完整复现 RoboPianist，也不会连接或控制真机。

## 1. Conda 环境

在工作空间根目录执行：

```bash
conda env create -f src/ros2_rm_robot/rm_mujoco/config/piano_rl_environment.yaml
conda activate piano_rl
```

环境固定 Python、MuJoCo、PyTorch、Gymnasium、Stable-Baselines3 和测试依赖。训练只需 MuJoCo/Conda；若使用安装后的 `ros2 run` 入口，还需先构建并加载 ROS 2 工作空间。

## 2. 数据与实验清单

训练脚本接收 `piano_rl_dataset/1` 或 `/2` JSON manifest。每个训练、验证或测试条目包含：

- `source`：相对数据集目录的 PianoVAM 指法 TSV。
- `source_sha256`、`plan_sha256`、`metadata_sha256`：防止训练后数据或参考计划被静默替换。
- `plan`：单手或双手 `piano_performance/1` 参考计划，必须先通过 MuJoCo 物理验收。
- `origin_sec`：TSV 录音时间与计划片段的时间原点。

`metadata.json` 顶层直接是 `录音名 -> {record_time, split}`，不要增加 `records` 外层。`record_time` 与 TSV 文件名主干一致；训练只允许 `train` / `ext-train`，验证只允许 `valid`，最终测试只允许 `test`。不同阶段的录音与作曲家/曲目组合必须互不重叠。脚本逐事件核对 onset、key_offset 和原始指法标注，同时拒绝删掉窗口内其他起音或从延续音中间开始的片段。`/2` 要求三个阶段均有数据。默认不运行测试策略；完成训练和选模后，显式使用 `--final-test` 或独立鲁棒性入口解封测试。

## 3. 训练与评估

使用源码入口：

```bash
python src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py \
  --manifest /path/to/experiment/manifest.json \
  --output /path/to/experiment/ppo_seed7 \
  --steps 4096 --seed 7 --residual 6 --control-dt 0.02 \
  --robopianist-reward
```

去掉 `--robopianist-reward` 即关闭指尖距离与能耗两项，用于同种子对照。两种模式均包含下述事件反馈。新策略的确定性输出从零残差起步，完整保留参考控制指令。单个环境按课程顺序先遍历全部训练任务，再按轮打乱；首个 rollout 长度按全部训练任务的回合步数之和向上取 2 的整数次幂，至少 512 步。单独完整 40 音在 20ms 控制周期下使用 2048 步，避免首轮仅覆盖前 10.24 秒。即使 `--steps` 更小也会收集完整 rollout。输出目录必须不存在，避免覆盖已有实验。

脚本会先验收所有训练及验证参考轨迹，任一失败则保存汇总并跳过训练，退出码为 `2`。训练完成不等于物理验收通过：学习策略在任一片段失败时，模型与报告仍保留供诊断，退出码同样为 `2`；全部通过才返回 `0`。

构建并 `source install/setup.bash` 后，也可使用：

```bash
ros2 run rm_mujoco train_piano_rl.py \
  --manifest /path/to/experiment/manifest.json \
  --output /path/to/experiment/ppo_seed7 \
  --steps 4096 --seed 7 --robopianist-reward
```

从已有模型继续训练或只评估：

```bash
python src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py \
  --manifest /path/to/experiment/manifest.json \
  --output /path/to/experiment/ppo_seed7_continued \
  --resume /path/to/experiment/ppo_seed7/model.zip \
  --steps 4096 --seed 7 --robopianist-reward
```

只评估时把 `--steps` 换成 `--evaluate-only`。恢复训练会检查 residual、控制周期、奖励模式、PPO 配置、课程平衡、奖励版本、接口版本和 manifest；同时保持 `--include-two-tigers` 等原配置。当前为 `piano_residual/5`、`piano_shared_hands/3`。新接口与旧 v2/v3/v4 网络尺寸不同；旧模型需要使用其保留的原源码快照评估，不能直接载入新接口续训。

## 4. 奖励与验收

默认模式保留原有的正确按键压力、漏按、误触、超行程、动作平滑和终端物理验收奖励，并增加 `event` 反馈：

- 每个音符的原始释放时刻加既有时间容差之后，调用原 `PlanRunner` 匹配器核对已经观察到的完整按键区间，提前反馈时序与时长结果。
- 累计事件分为 `5 × (已到截止时间的匹配音数 − 2 × 漏音数 − 2 × 异常条目数)`，每个控制步只加入累计分的变化量。未到截止时间的未来音符不算漏音；无法匹配的额外音在出现完整区间时扣分。
- 异常条目使用原验收的 `timing`、`duration`、`extra` 等分类；同一音符可能同时触发时序和时长异常。验收阈值、原始乐谱时序和物理门槛保持原样。

启用 `--robopianist-reward` 后增加：

- `finger`：当前活跃音符标注指尖到对应琴键 site 的容差奖励，`bounds=0.01 m`、`margin=0.1 m`。
- `energy`：受控双手关节 `|qfrc_actuator|ᵀ|qvel|`，以 `0.005` 权重惩罚；单手模式只统计受控右手。

这两项参照 [RoboPianist 论文附录 B](https://arxiv.org/html/2304.04150v3)，但按键项和残差动作空间仍是本项目的 P0 设计，不能直接比较论文回报数值。

每次训练分别保存 `reference`、训练前策略和训练后策略的物理评估。主要比较：

- `matched / expected`、`missing`、`unexpected` 与 `unexpected_by_kind`。`matched` 只表示找到了对应的按键区间，不能代替 `passed`；`unexpected` 也不能直接当作额外音数量，额外音应读取 `unexpected_by_kind.extra`（缺省为零）。
- `angle_violations`、`active_keys_at_end`、错误手指接触。
- onset/release 时间误差。
- `reward_components`、平均指尖距离和平均手部功率。

不同奖励模式的回报不可直接横向比较；是否改善以相同物理验收指标为准。

v4 在原事件反馈之外，对已到释放验收期限的匹配事件增加连续时序反馈：
`-2 × sum(min(4, (error/tolerance)^2))`，分别统计 onset、release、duration。
每步只加入累计值的变化量，让尚在门槛内的时长误差也有改进方向。原匹配器、
30ms 容差、错指、超行程和尾部残留检查不变。

v5 进一步惩罚接近行程上限的目标键压力，并对已出现的行程违规、错指和非目标
接触增加累计安全代价的变化量。它们提供训练信号，最终通过条件仍由原验收器决定。

当前工程不附带预训练模型。首轮 16,384 步和两种奖励各三个 seed 的 4,096 步对照均未超过零动作参考轨迹；训练后模型必须通过上述物理指标重新验收，不能仅根据训练回报选用。

## 5. 输出与验证边界

奖励版本 `piano_residual/3` 保留接管时新增的逐音事件反馈：音符释放验收期限到达后，
按原回放器的 onset/release/duration 检查结算，未降低任何验收阈值。新策略的动作输出层
从零初始化，确定性评估首先复现参考。随机探索仍然存在，不能把初始化通过当作学习成功。

新增 `best_model.zip` 和 `selection/`：每 `max(4096, 4 × n_steps)` 次环境调用及最后一次优化后，使用单独
的评估环境比较物理通过数、错误数和时序误差；不使用独立验证录音选模型。
第 0 步模型参与比较，`summary.selection.best.step=0` 表示保留初始化，不能宣称 RL 改善。
`model.zip` 始终保存最后训练模型，`learned` 与 `selected` 分别报告，避免隐藏退化。
若最后模型未通过，命令仍返回 2，即使选中的基准通过也不会冒充训练成功。

双手模式按 `right,left` 顺序分配 20 个残差动作；观测包含两手状态和各自未来目标。
冻结双手曲目不要求重新规划或读取旧实验目录。构建并加载工作空间后，先通过安装入口
独立复验完整参考轨迹（所有输出目录都必须不存在）：

```bash
ros2 run rm_mujoco verify_two_tigers.py --output .validation/two_tigers_verify
```

训练可直接使用源码入口：

```bash
package="$PWD/src/ros2_rm_robot/rm_mujoco"
python "$package/scripts/train_piano_rl.py" --package "$package" \
  --verified-two-tigers --output .validation/dual_ppo_seed7 \
  --steps 4096 --seed 7 --robopianist-reward
```

也可改用安装入口，无需传 `--package`：

```bash
ros2 run rm_mujoco train_piano_rl.py \
  --verified-two-tigers --output .validation/dual_ppo_installed_seed7 \
  --steps 4096 --seed 7 --robopianist-reward
```

该模式没有独立新曲验证集，`config.validation_scope=same_song_only`；不能宣称跨曲泛化。
`--command-bias 0.5` 可在训练每个 episode 的手指指令中施加固定的均匀偏置，范围
为 ±0.5 L20 指令单位。这是合成扰动实验，不是测得的硬件误差，模型物理参数保持不变。
正常基准不施加偏置。启用训练偏置时，选模额外使用开发 seed 31、37；排序先比较
无扰动验收，再比较开发扰动的验收和错误数，最后比较时间误差。最终测试 seed 单独冻结，
不参与选模。恢复训练要求奖励版本和偏置配置一致。

冻结测试 seed 的配对鲁棒性评估（同一 seed 的参考和策略使用完全相同的偏置）：

```bash
python "$package/scripts/evaluate_piano_robustness.py" --package "$package" \
  --model .validation/dual_ppo_seed7/best_model.zip \
  --output .validation/dual_ppo_seed7_robustness --bias 0.5 --seeds 101 102 103
```

构建后也可运行 `ros2 run rm_mujoco evaluate_piano_robustness.py`，参数相同但无需
`--package`。该入口另含无扰动检查，输出 `protocol.json`、`comparison.json` 和每次回放证据。
测试 seed 不参与选模；对其结果反复调参后必须另留未见测试，不能继续称为独立测试。

输出目录包含：

- `model.zip` 和 `checkpoints/`：PPO 模型。
- `config.json`：参数、依赖版本、manifest 和源码哈希、奖励版本、策略初始化方式。
- `progress/progress.csv`：训练过程指标。
- `summary.json`：训练/验证的参考、训练前和训练后汇总，以及 `acceptance.reference_passed` / `acceptance.learned_passed`。参考失败而跳过训练时没有 `learned_passed`。
- 每次评估的 `report.json`、`key_edges.json`、`actions.json` 和实际按键 `played_keys.mid`。

2026-11-09 在 Jetson Conda `piano_rl` 完成安装版闭环：`rm_mujoco` 构建通过，
`piano_rl` 17 项与 `two_tigers` 8 项 CTest 通过，独立安装入口回放 40/40。
以 `--steps 1 --seed 7 --robopianist-reward` 实际收集 512 步后，最后模型仍匹配
40 音，但事件 28（MIDI 81）时长短于允许值 1 ms，`learned_passed=false`；
选模保留第 0 步零残差模型，`selected_passed=true`。因此该次运行只证明工程闭环，
不证明训练改善。证据在 Jetson `.validation/kimi_rl_formal_20261109/dual_smoke_seed7/`。
同一最佳模型的安装版鲁棒性入口已跑通：无扰动时参考和策略均为 40/40；
`bias=0.5、seed=101` 时两者均为 39/40，均有 1 个漏音、1 个时序异常和
2 个时长异常。两者指标一致是因为最佳模型仍为零残差，不能据此声称训练提高了
鲁棒性。配对证据在 `.validation/kimi_rl_formal_20261109/dual_smoke_seed7_robustness/`。

本入口只证明 MuJoCo 仿真结果。真机需要独立的安全检查、低速验证和验收，不得把仿真 `passed=True` 写成真机通过。

## 6. 共享接口、多录音与参考反馈（v5）

动作始终为 20 维，顺序为右手 10 维、左手 10 维；不存在的手用掩码屏蔽。`piano_shared_hands/3`
观测为 1337 维，包含两手状态/参考误差、相对钢琴的前臂笛卡尔位置、五个时点的未来键目标和
active-finger 标签、每根手指的下一目标音与起音/松键倒计时、有效手掩码和上一动作。
新增项对应 RoboPianist 表 1 的前臂位置与 `L × 10` 指法标签；本项目仍保留自身残差误差和
指法时钟。单手片段与双手曲目使用同一网络接口。腕部仍由输入参考轨迹控制；新片段必须有
可行的腕位和手态参考。

每个新参考先完整无扰动回放，通过后保存逐控制步 `nominal_states.npz`。策略读取
实际手部/机械臂关节与同一步名义状态的 56 维差值；残差乘以跟踪误差门控，最大误差
不超过 `1e-9 rad` 时为零，达到 `0.002 rad` 时完全启用。门控和观测均不读取注入偏置
的真值。这样相同仿真状态下的正常轨迹受到保护；无扰动通过本身是控制结构的性质，
不能作为学习有效的证据。直接调用 `evaluate` 时，必须先提供通过验收的完整名义轨迹；
训练与鲁棒性入口会完成这一步。该逐步参考目前依赖相同仿真模型和控制周期。
默认训练偏置为 ±0.5 L20 单位，为反馈学习提供可观测偏差；显式
`--command-bias 0` 用于无偏差对照，此时完全匹配名义状态的门控会始终抑制残差，
不能把这类运行当作有效的残差学习。参考、验证和测试的无扰动回放始终使用零偏置。

通过物理验收的零残差回放每四个控制步保存一份状态与示范动作到
`reference/demonstrations.npz`。训练输入只使用训练片段的示范；每轮 PPO 更新后执行
四个 64 样本的小批量动作均值 MSE 回放约束。零残差已经是正确的初始策略，
无需重复拟合全零标签来冒充预训练进展；这些示范在策略更新后用于约束正常演奏退化。
`summary.training.reference_rehearsal` 记录实际执行的回放约束，`coverage` 记录各训练
片段完成的回合数和已覆盖音符数。
初始化模型的动作层严格为零，因此训练前与第 0 步选模可以复用已测得的参考回放；
这些副本在报告中标为 `evidence_reuse=exact_zero_action_initialization`，不算新增仿真。

在 Jetson Bash 中准备新的数据清单（输出目录须不存在）：

```bash
cd /home/dianjinglab/ros2_ws_piano_fix_20261108
conda=/home/dianjinglab/miniforge3/bin/conda
package="$PWD/src/src/ros2_rm_robot/rm_mujoco"
"$conda" run --no-capture-output -n piano_rl python "$package/scripts/prepare_piano_rl.py" \
  --package "$package" --dataset .validation/piano_rl_generalization_20261109/data \
  --output .validation/piano_rl_dataset
"$conda" run --no-capture-output -n piano_rl python "$package/scripts/train_piano_rl.py" \
  --package "$package" --manifest .validation/piano_rl_dataset/manifest.json \
  --output .validation/multisong_seed7 --steps 16384 --seed 7 \
  --include-two-tigers --residual 6 --command-bias 0.5 --robopianist-reward
```

数据准备扫描人工标注 GT；按相同规则尝试每份录音的连续 3/2/1 音原速右手片段，
保留原始指法与 onset/key_offset，先规划再用原验收器复验。每份录音的尝试预算固定，
失败记录保存在 `attempts.json`，已接受和无法覆盖的录音汇总在 `coverage.json`。
只有可行短片段进入训练清单；这不代表该录音整曲、全音域或任意曲谱都能演奏。
人工 GT 的 8 份训练/扩展训练、1 份验证、2 份测试是扫描目标，最终覆盖率以产物为准。
最终测试的通过率还必须与同一片段的零残差参考比较，单纯跟随参考成功不能证明学习增益。

强化学习不会自动获得跨曲泛化。[RoboPianist 的多曲实验](https://arxiv.org/html/2304.04150v3#S5.SS2)
中，多任务 RL 未表现出正迁移；蒸馏专家策略的行为克隆有所改善，但未达到单曲专家的
未见曲表现。因此本入口保留参考规划，学习局部残差，并分别检验无扰动保持、未见偏置
和独立录音；PianoVAM 的人类指法标注不能直接当作机器人关节动作标签。

本轮严格自动准备得到 5 份训练、0 份验证、2 份测试参考；原验证录音的单音 Bb4
另经现有 `calibrate_piano_chord.py` 标定，以 `press_depth=0.007 m`、原起止时间、
原中指指法及不变的 30ms 门槛通过完整回放后，纳入 `excerpts_ready/manifest.json`。
复现脚本及全部失败尝试位于 `.validation/piano_rl_generalization_20261109/`。
最终覆盖是训练 5 份/8 音、验证 1 份/1 音、测试 2 份/3 音；其余 3 份训练录音缺少
符合当前候选规则的片段，未改标签或删音来补齐。混合课程还包含双手完整 40 音。

## 7. 2026-11-09 修复复验

实验根目录为 Jetson 工作空间下的 `.validation/piano_rl_generalization_20261109/`。
`feedback_package/` 是不可变的 v5 源码快照，`baseline_package/` 保留接管时的代码；
6 个变更路径已备份后同步到正式源码 `src/src/ros2_rm_robot/rm_mujoco`，
`deployment.json` 记录初次部署，`deployment_cli.json` 记录默认训练偏置修正后的
最终 SHA256，本地与正式源码逐文件一致。`cli_package/` 仅在训练默认值和对应测试上
更新；实验显式使用 `--command-bias 0.5`，其不可变快照和模型不变。最终默认值版本
再次通过 36 项 Pytest、隔离构建和安装入口检查。

Jetson Ubuntu 22.04 / Conda 上直接 Pytest 36 项通过；`rm_mujoco` 隔离构建通过，
CTest 的 `piano_rl` 28 项和 `two_tigers` 8 项通过。CTest 使用 Conda 依赖路径，
并以 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 避免 ROS launch 插件收集无关包；首次
未隔离插件的收集错误保留在 `ctest_feedback.log`，成功日志是
`ctest_feedback_isolated.log`。安装后的准备、训练、鲁棒性入口帮助检查通过，
安装后的冻结参考入口再次原速通过 40/40，最大落键/释放误差为 30/18ms。

两种课程均固定训练种子 7/11/19、每模型 8192 步、残差幅度 6、训练命令偏置
±0.5 L20 单位及 RoboPianist 指尖/能耗项。单曲 `n_steps=2048`，混合课程
`n_steps=4096`；这是短程对照，并非收敛或广泛泛化的证明。单曲各完成 5 个完整
回合，覆盖全部 40 音，最后和选中模型均保持无扰动 40/40。选择结果允许保留第 0 步。

所有最佳模型 SHA256 冻结后，使用未参与选模的偏置种子 2001/2003/2007，参考与策略
逐案例配对回放。下表通过率指完整物理验收；新曲测试是官方 `test` 的两份短片段，
每片段三个扰动种子，共六个案例。

| 课程 / seed | 选中步数 | 无扰动通过案例 | 独立扰动参考 | 独立扰动策略 |
| --- | ---: | ---: | ---: | ---: |
| 40 音 / 7 | 0 | 1/1 | 0/3 | 0/3 |
| 40 音 / 11 | 0 | 1/1 | 0/3 | 0/3 |
| 40 音 / 19 | 8192 | 1/1 | 0/3 | 0/3 |
| 混合 / 7（新曲测试） | 0 | 2/2 | 5/6 | 5/6 |
| 混合 / 11（新曲测试） | 8192 | 2/2 | 5/6 | 5/6 |
| 混合 / 19（新曲测试） | 8192 | 2/2 | 5/6 | 4/6 |

本轮尚无可靠学习增益。混合 seed 19 的开发异常计数从 39 降至 23，但未减少开发失败
片段，且在 Scarlatti 测试片段、扰动 seed 2007 新增一个时长误差 −30.75ms 的失败，
原 30ms 门槛照常保留。同曲 seed 19 将独立扰动的角度违规项从 8 减到 5，同时异常
条目从 15 增到 18，缺音仍为 3，不能当作总体改善。原始门控、实际动作、按键事件、
MIDI、报告和模型均保留；`results.json` 与 `paired_results.csv` 提供汇总。

无扰动的实际残差均为零，是参考门控保护的结果；非零模型在扰动中确实执行了残差。
本轮完成了训练链路和小规模泛化对照，当前演奏仍以冻结参考为可用基准。它没有证明
更高跨曲泛用性，也没有覆盖整首 PianoVAM、未知腕位、质量/摩擦变化或真机。

复用本轮通过验收的数据清单开始新的混合实验（输出目录须不存在）：

```bash
cd /home/dianjinglab/ros2_ws_piano_fix_20261108
conda=/home/dianjinglab/miniforge3/bin/conda
package="$PWD/src/src/ros2_rm_robot/rm_mujoco"
artifact="$PWD/.validation/piano_rl_generalization_20261109"
"$conda" run --no-capture-output -n piano_rl python "$package/scripts/train_piano_rl.py" \
  --package "$package" --manifest "$artifact/excerpts_ready/manifest.json" \
  --include-two-tigers --output "$artifact/repeat_seed7" --steps 8192 --seed 7 \
  --residual 6 --command-bias 0.5 --robopianist-reward
```

## 8. 长程续训

用户确认继续后，T-0013 在 Jetson 启动独立目录
`.validation/piano_rl_continue_20261109/`。三组 seed 7/11/19 从上一轮混合课程的
最后 `model.zip`（8192 步）恢复权重与优化器，各追加 65536 步，目标累计 73728 步。
训练配置、数据、原速、指法及物理门槛沿用上一轮，检查点仍每 4096 步保存。

编排脚本 `run_continuation.py` 运行在独立会话，SSH 断开后继续执行；每组日志在
`logs/train_seed7.log` 等文件，检查点和最终模型在 `runs/seed7/` 等目录。
检查点目录已附原 `config.json`，供现有 `--resume` 校验配置；恢复时保持原参数，
并用新的输出目录保存后续结果。
`runner_state.json` 是进程运行产物，记录 PID、阶段、退出码和观察到的累计步数；
不能把 `phase=training` 当作已经完成 PPO 采样或通过物理验收。
AI 任务进度和文件占用仍以 `docs/ai_worklog.md` 为准。

三组训练结束后，编排器仅对所选模型通过无扰动验收的组冻结哈希，再运行新噪声种子
3001/3003/3007。新旧最佳模型分别与零残差参考配对比较完整 40 音和原测试录音；
这些曲目上一轮已经查看，本轮只能报告回归与新噪声鲁棒性，不能重新称为未见曲测试。
`phase=finished` 只表示编排正常结束，策略是否提升要读取物理比较报告。

在 Jetson Bash 中查看运行产物：

```bash
artifact=/home/dianjinglab/ros2_ws_piano_fix_20261108/.validation/piano_rl_continue_20261109
cat "$artifact/runner_state.json"
tail -n 8 "$artifact/logs/train_seed7.log"
```

## 9. 新曲连续乐句试验

2026-11-09，T-0014 使用 Jetson 既有 Conda 环境尝试 Home, Sweet Home、Für Elise
及 Hanon Exercises No.1。首轮仅右手连续 8 音，保留窗口内全部右手起音、完整
`key_offset` 和原指法，原速与 30ms 验收门槛不变。自动指法来源不等同人工确认；
未知标注重叠、遗留延音边界和同指同时持音均排除，最终候选分别 18/29/32 个。

共运行 26 次参考规划：原配置各 6 次，独立姿态覆盖各 2 次，另为 Home 的两个窗口
将搜索预算从 45 增至 180 秒。Home 从首音不可达推进到前五音可规划，但后续仍有
换腕时间不足、超行程和误触；Elise/Hanon 仍受延音接触和快速换指限制。全部尝试
在规划阶段失败，尚无完整 8 音参考通过回放验收，故未运行新曲策略对照或微调。
这些结果不能判断 PPO 跨曲能力，也不是双手或整曲演奏成功的证据。

三种子 20480 步检查点已在新曲策略评估前冻结；预定扰动种子为 4001/4003/4007，
新曲没有加入现有后台课程。实验仅新增独立姿态文件与辅助脚本，正式规划器、模型
和验收器未修改。当前策略修正手指命令，腕部仍依赖参考；后续需先解决连续参考。

完整结果、候选、曲谱、参数来源和 26 次失败日志见
[新曲试验报告](../.validation/piano_rl_new_music_20261109/RESULTS.md)。127 份取回证据
逐文件 SHA256 校验通过；Windows 仅语法及 5 项纯数据边界检查通过。

## 10. 多曲目稳定性与 RoboPianist 对齐（当前接口）

本轮针对多曲课程的三个混淆来源增加了明确约束和指标：

- `--task-balance episode` 保持原来的每轮每曲一次；`--task-balance step` 在第一轮完整覆盖后，
  按 `ceil(最长回合步数 / 当前回合步数)` 重复短片段，避免长曲仅因回合更长而占据大部分 PPO
  样本。`summary.training.coverage` 同时记录选中回合、完成回合、实际控制步和音符覆盖。
- 每次评估按物理步累计琴键发声状态的 TP/FP/FN，输出 `precision`、`recall`、`f1` 和原始计数。
  发声阈值与按键奖励相同，为归一化行程 `0.55`；空分母定义 precision/recall 为 1。
  这与 [RoboPianist 的逐时刻 F1](https://arxiv.org/html/2304.04150v3#S3) 可比地反映多曲表现，
  但不替代原有事件级 30ms、错指、超行程和尾部残留验收。
- 选模先比较最差无扰动片段是否失败，再比较失败片段总数、最差/总物理错误；随后才对开发扰动
  做同样比较，最后比较最差/平均 F1 和时序误差。不能用一个简单片段的改善抵消另一个片段的
  物理退化，也不能用 shaping return 或独立测试集选模。

`--robopianist-profile` 将 PPO 网络设为 3×256 ReLU、学习率 `3e-4`、minibatch 256，并启用
非目标发声键的恒定惩罚；折扣默认仍是论文附录的 0.99。可用 `--gamma 0.9` 复现论文第 5.3 节
建议的 0.84–0.92 范围对照。该选项只对齐观测、奖励和网络/优化参数，优化器仍是 PPO，不是论文的
DroQ，也不能直接比较回报数值。恢复训练必须保持完整 PPO 和课程配置一致。

使用本地已准备的 PianoVAM 清单开始新接口的三种子对照（仅在 Ubuntu/Conda 仿真环境执行）：

```bash
package="$PWD/src/ros2_rm_robot/rm_mujoco"
manifest="$PWD/.validation/piano_rl_generalization_20261109/excerpts_ready/manifest.json"
for seed in 7 11 19; do
  python "$package/scripts/train_piano_rl.py" --package "$package" \
    --manifest "$manifest" --include-two-tigers \
    --output "$PWD/.validation/piano_rl_multisong_stability_20261109/seed$seed" \
    --steps 32768 --seed "$seed" --residual 6 --control-dt 0.02 \
    --command-bias 0.5 --task-balance step --robopianist-reward \
    --robopianist-profile --gamma 0.9
done
```

先在训练/开发扰动上冻结模型及哈希，再运行 `evaluate_piano_robustness.py`。注意上述清单的两份
PianoVAM `test` 已在 T-0012 查看，本轮只能作为旧测试回归；要声称新的跨曲泛化，必须加入此前
未参与准备、选模或调参的录音，并保持作曲家/曲目隔离。当前改动本身不等于训练收敛或泛化提升，
需以三种子的逐曲物理验收和配对 F1 结果为准。
