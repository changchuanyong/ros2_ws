# 通用换曲与评分框架

本框架复用 `rm_mujoco` 的逐音符规划器和被动琴键执行器，将 MIDI 或
`piano_fingering/1` 乐谱转换成 `piano_performance/1` 计划，再从实际琴键边沿评分。
入口 `piano_performance.py` 在离线进程内运行，可供后续指法、多指与学习控制扩展。

## Jetson 构建与运行

在 Jetson 的工作空间根目录、已有 ROS 2 Humble 和 MuJoCo 环境中执行。
下面的 Python 模块需要能被该环境的 `python3` 导入。

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-up-to rm_piano_player
source install/setup.bash
ros2 run rm_piano_player piano_performance.py --help
```

运行一个完整片段。每次输出目录须为新目录，`mktemp` 建立的父目录下面使用
尚未存在的 `run` 子目录。

```bash
player_share="$(ros2 pkg prefix rm_piano_player)/share/rm_piano_player"
run_root="$(mktemp -d /tmp/piano-pipeline.XXXXXX)"
ros2 run rm_piano_player piano_performance.py \
  --score "$player_share/examples/performance_pipeline/repeated_g.yaml" \
  --beam-width 2 --candidate-limit 2 \
  --output "$run_root/run"
cat "$run_root/run/status.json"
```

换曲时替换 `--score`。输入支持 `.mid`、`.midi` 和已有指法 YAML。
`--tempo-scale 2` 将乐谱时间放大两倍，播放速度减半。
默认手为右手，默认手态来自 `rm_mujoco/config/right_hand_piano_sim.yaml`。
通过 `--pose-file`、`--scene-config`、`--package` 指定不同标定或场景。
每次重新规划时都会使用同一套现有规划逻辑生成动作。规划日志按起音组输出进度，
`status.json` 的每个子步骤记录 `wall_seconds`。快速试曲可显式添加
`--beam-width 2 --candidate-limit 2` 缩小搜索；默认值仍为 `8` 和 `3`，
最终动力学、接触和时序验收标准不变。缩小搜索可能找不到可行计划，失败时应恢复默认值。

### 三组 Jetson 验收片段

这些是人工构造的短练习，均使用已有 E4/G4 标定，并已用于 Jetson MuJoCo 验收。

| 文件 | 覆盖行为 | 音符数 |
| --- | --- | --- |
| `repeated_g.yaml` | 同音重复，0.4 秒音长 | 3 |
| `rhythm_g.yaml` | 同音的 0.4、0.8、0.3 秒音长 | 3 |
| `rest_eg.yaml` | E4 到 G4、1.4 秒休止、重复 G4 | 3 |

在同一个已加载环境的终端中运行全部片段。

```bash
player_share="$(ros2 pkg prefix rm_piano_player)/share/rm_piano_player"
run_root="$(mktemp -d /tmp/piano-suite.XXXXXX)"
for song in repeated_g rhythm_g rest_eg; do
  ros2 run rm_piano_player piano_performance.py \
    --score "$player_share/examples/performance_pipeline/$song.yaml" \
    --beam-width 2 --candidate-limit 2 \
    --output "$run_root/$song"
  result=$?
  printf '%s exit=%s\n' "$song" "$result"
done
printf 'Reports saved under %s\n' "$run_root"
```

通过条件为 `status.json` 的 `state=completed`、`simulation_passed=true`、
`evaluation_passed=true`。逐音误差与失败原因在 `evaluation.json` 中。
动力学、接触、手指归属等原有约束以 `simulation/report.json` 为准。
出现失败时保留整个输出目录，供 Sol 排查。

## 分阶段运行

所有阶段都要求新的 `--output` 目录。重试使用新目录，可明确区分各次执行的数据。

| `--stage` | 必需输入 | 作用 |
| --- | --- | --- |
| `prepare` | `--score` | 读取、校验并导出规范乐谱 |
| `plan` | `--score` | 准备乐谱并调用现有规划器 |
| `simulate` | `--plan` | 执行已有计划并评分 |
| `evaluate` | `--plan --edges --source` | 仅比较已有原始事件和计划 |
| `all`，默认值 | `--score` | 准备、规划、仿真、评分 |

例如，分阶段复用上一阶段的结果。

```bash
run_root="$(mktemp -d /tmp/piano-stages.XXXXXX)"
ros2 run rm_piano_player piano_performance.py --stage plan \
  --score "$player_share/examples/performance_pipeline/repeated_g.yaml" \
  --output "$run_root/planning"
ros2 run rm_piano_player piano_performance.py --stage simulate \
  --plan "$run_root/planning/performance.yaml" --output "$run_root/playback"
ros2 run rm_piano_player piano_performance.py --stage evaluate \
  --plan "$run_root/planning/performance.yaml" \
  --edges "$run_root/playback/simulation/key_edges.json" \
  --source simulation --output "$run_root/rescore"
```

`simulate` 和 `evaluate` 使用计划中记录的速度倍率和时序容差。
`--tempo-scale`、`--timing-tolerance` 在生成计划时生效。
计划中的 `start_sec/end_sec` 已包含起始等待，评分时仅应用一次速度倍率。
复用计划时需要使用生成该计划的场景、机器人模型及标定条件。

源码运行方式如下。工作目录为工作空间根目录。

```bash
export PYTHONPATH="$PWD/src/ros2_rm_robot/rm_piano_player:$PWD/src/ros2_rm_robot/rm_mujoco${PYTHONPATH:+:$PYTHONPATH}"
python3 -m rm_piano_player.performance_pipeline --help
```

## 数据与评分约定

- 乐谱沿用 `piano_fingering/1`，含音高、起止时间、力度和可选手/指法。
  MIDI 复用现有解析器，支持格式 0/1、PPQN 和速度变化，以 Note Off 为松键时间。
  MIDI 踏板和其他控制事件由当前解析器忽略，力度作为目标元数据保存。
- MIDI 使用 `--hand right/left` 时全部分给指定手，使用 `both` 时按
  `--left-max-note` 划分，默认 59。MIDI 通道和轨道不参与手别推断。
  指法设为未知，由规划器选择。YAML 保留原有手别和指法，未知手别沿用音高划分。
  单手模式遇到属于另一手的事件会报错，避免漏掉整段乐谱。
- 原始边沿是 JSON 数组，每项为 `[time_sec, "on"或"off", MIDI音高]`。
  时间须单调非降且与计划的执行时钟对齐。同一物理键的重叠目标会被拒绝。
  真机录制适配器需要自行建立录制时钟与演奏计划的对应关系。
- `--source` 为 `simulation`、`recorded` 或 `synthetic`。该字段记录调用方声明的
  数据来源；仅凭此标签不能验证数据的采集过程。
- 按音高分别进行保持时间顺序的一对一匹配。先最大化起音匹配窗内的匹配数量，
  再最小化起音绝对误差之和。默认匹配窗为 150 ms，可通过 `--match-window` 调整。
  超窗事件分别计入缺失和额外音。相邻重复音时间窗重叠时，匹配属于确定性的时间归因。
- `matched` 表示匹配到同音高事件。`correct` 还要求起音、松键均在计划容差内，
  默认 30 ms。误差为实际时间减期望时间，正值表示迟到。
- 未松开的 Note On 计入实际音符数，松键时间和误差为 `null`。
  重复 Note On、孤立 Note Off、零时长按键会记录为 `edge_anomalies` 并导致失败。
- 错音保留为一个缺失目标和一个额外实际音，不猜测错误的手指意图。
  `precision=correct/observed`，无实际音时为 0；`recall=correct/expected`；
  `f1=2*correct/(expected+observed)`。这是同时要求起音及松键正确的事件指标。
- 评分的 `id` 是跨手唯一的评估编号，`hand` 与 `plan_event_id` 对应原计划事件。
  原计划中左右手各自使用相同编号也能区分。
- `evaluation.json` 的 `passed` 要求全部期望音正确，且无额外音、尾部按键或边沿异常。
  完整流程还要求原仿真报告通过，包括接触、错指和关节/琴键行程检查。

输出文件包括规范乐谱、计划、规划诊断、分阶段日志、`simulation/` 原始数据、
`evaluation.json` 和 `status.json`。状态文件记录输入路径及 SHA256、子进程命令、
实际耗时与返回码。`simulation/played_keys.mid` 保留全部实际琴键事件，包括额外音。
目录独占创建，状态文件采用临时文件替换，避免重试覆盖旧结果。
退出码为 0（所选阶段成功）、1（运行错误）、2（命令行参数错误）、3（验收失败），
Ctrl+C 中断记录为 130；强制终止时状态可能停留在 `running`。

## 给 Sol 的扩展任务

| 扩展位置 | 当前职责 | 下一步 |
| --- | --- | --- |
| `rm_piano_player/score_io.py` | 乐谱适配与预检 | 增加真实录制适配时保留来源和时钟关系 |
| `rm_piano_player/performance_evaluation.py` | 无硬件依赖的事件评分 | 补充实际演奏数据回归；新增指标保留版本兼容 |
| `rm_piano_player/performance_pipeline.py` | 阶段编排、日志、状态 | 依据 Jetson 失败报告完善运行流程 |
| `rm_mujoco/rm_mujoco/fingering.py` | 现有指法、腕位和手态规划 | 扩展受支持指法与键位，并通过原始键事件验收 |
| `rm_mujoco/scripts/run_performance.py` | 现有动力学执行与接触检查 | 扩展双手、多指时继续输出原始边沿 |

Sol 首先在 Jetson 执行三组验收，逐项记录结果。随后扩大至现有 E4+G4 和弦与
换位片段。学习控制可在演奏计划和实际执行之间加入状态反馈修正，继续复用评分器。
真机控制接入需要单独设计时钟、数据适配和授权流程。

## 验证记录

离线输入、评分、CLI、失败传播和中断清理均有回归测试；完整流程测试中的规划/仿真
返回值使用受控替身，其中的 `synthetic` 事件只用于检查软件行为。

2026-11-08 在 Jetson 的独立工作区完成实际 MuJoCo 验收。三组均使用
`--beam-width 2 --candidate-limit 2`，状态为 `completed`，仿真与评分均通过，
每组 3/3 音符正确，无错指或尾部按键：

| 片段 | 规划耗时 | 仿真耗时 | 最大起音误差 | 最大松键误差 |
| --- | ---: | ---: | ---: | ---: |
| `repeated_g` | 14.5 s | 6.6 s | 约 0 ms | 6 ms |
| `rhythm_g` | 17.9 s | 7.0 s | 约 0 ms | 12 ms |
| `rest_eg` | 38.3 s | 7.6 s | 4 ms | 10 ms |

同一版本的单音、同手和弦、宽换位和双手指法动力学回归共 14 项通过，耗时 277.9 秒。
默认 `8 / 3` 搜索曾使 `rhythm_g` 在 300 秒预算内未完成最后一组，因此短练习示例
显式采用上述 `2 / 2` 参数；这不是放宽验收阈值。标准双包测试命令仍为：

```bash
colcon test --packages-select rm_piano_player rm_mujoco
colcon test-result --verbose
```

这些结果只验证离线 MuJoCo，未操作真实机械臂或灵巧手。
