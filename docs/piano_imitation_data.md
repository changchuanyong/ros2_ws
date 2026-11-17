# 外部钢琴示范数据：公开样例接入

本入口把 SkyPiano 的人体动作变成可追溯的动作先验，把 MIDI/指法变成现有训练程序能读取的乐谱目标。当前没有产生 RM75/L20 专家控制动作，没有运行 BC、RL 或机器人仿真。

入口：[`prepare_skypiano.py`](../src/ros2_rm_robot/rm_mujoco/scripts/prepare_skypiano.py)；实现：[`skypiano.py`](../src/ros2_rm_robot/rm_mujoco/rm_mujoco/skypiano.py)。本轮不改既有训练器、机器人模型及其他 AI 的接触实验。`CMakeLists.txt` 有既有占用，新增 CLI 暂从源码运行。

## 已验证的数据

2026-11-13，在 Ubuntu 22.04 WSL / Python 3.10 上执行导入和数据检查。原始数据、哈希清单、产物和审计结果在 `.validation/skypiano_20261113/`，未提交大文件。

| 数据 | 原始音符 | 有指法 | 动作帧 | 腕部、掌面参考与目标指尖全程可见的音符窗口 | 完整指法课程片段 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SkyPiano C 大调音阶，240828_C0_N4 | 272 | 206 | 709 | 62 | 18 |
| SkyPiano 技巧练习，240828_C0_N5 | 66 | 56 | 359 | 56 | 2 |
| PianoVAM `2024-02-15_21-40-43` GT | 150 | 150 | 本轮未导入 | 不适用 | 9 个 `piano_rl_tasks/1` 任务 |

SkyPiano 的 338 个音符均与配套原始 MIDI 一一匹配；输出直接采用 MIDI 的精确起止时间和力度。118 个完整可见窗口可能重叠，不是 118 条独立机器人示范。两个样例在预备和释放各 0.2 秒的窗口内，都没有同手完全孤立的单音；音阶包含重叠音，技巧练习包含和弦，没有删掉其他音符来制造单音成功。

音阶标记为 `train`，技巧练习标记为 `valid`，按演奏者、曲目、输入哈希检查隔离。这只是接入冒烟划分，任务类别不同，不能用来声称跨演奏者泛化。PianoVAM 沿用本地 `metadata.json` 的官方 `train`，GT 的 150 音不代表整曲全部人工标注。

审计：`.validation/skypiano_20261113/audit.json`。专项回归：`tests.xml`，41 项 Pytest 通过；不是 `colcon` 构建、MuJoCo 或真机验证。

## 来源和已发现的问题

- [SkyPiano 官方仓库](https://github.com/joonhyungbae/skypiano) 的公开样例固定在提交 `fded7d7c36f393eec42607820b5ab8aba2a08a9b`，位置是 `web/explorer/public/samples/`。下载清单和每个文件 SHA256 在 `raw/sources.json`，导入时重新核验。
- [官方浏览器解析器](https://github.com/joonhyungbae/skypiano/blob/fded7d7c36f393eec42607820b5ab8aba2a08a9b/web/explorer/src/data/parsers/handBodyMotionParser.ts) 明确：浏览器 CSV 是 **30 Hz**。附带 `fingering.json` 仍可能描述源数据的 120 Hz。CLI 要求显式指定 `--fps`；指定详情 JSON 时也核对完整时长。
- 技巧样例的 `fingering.json` 是 805 音、10459 帧/120 Hz，起始音为 36/24；配套 CSV/MIDI 是 66 音，动作为 359 帧/30 Hz，起始和弦含 48/52/55/60/64/67。它们不匹配。保留原文件，默认不自动读这个可选详情文件；显式指定它会报错。CSV 的未知标签仍未知，不根据 `finger_name` 猜出手指，也不制造置信度。
- 当前本地 RoboPianist 的 `_update_fingering_state()` 对 `finger < 5` 直接作为右手索引，`-1` 会落到右小指。因此只把**整段全部有指法**的课程导出为 `.proto`，不将混有未知指法的整曲直接接入该奖励。该现有源码本轮只读。
- 用户选择本轮只使用公开样例。[完整发布数据](https://huggingface.co/datasets/SKY-Piano/SKY-Piano) 仍需账户获准访问。完整发布文件名/掩码与浏览器样例不同，本入口没有宣称支持未取得的文件。

## 复现样例导入

在工作空间根目录、现有 Ubuntu Python 环境执行。需要 NumPy、PyYAML；MIDI 解析复用 `rm_piano_player.midi_file`，没有安装新依赖。

```bash
python3 src/ros2_rm_robot/rm_mujoco/scripts/prepare_skypiano.py \
  --sample .validation/skypiano_20261113/raw/240828_C0_N4_T1_Scale_CMajor \
  --output .validation/skypiano_20261113/recheck/scale \
  --fps 30 --subject 240828_C0_N4 --piece Scale_CMajor --split train \
  --fingering-details .validation/skypiano_20261113/raw/240828_C0_N4_T1_Scale_CMajor/fingering.json

python3 src/ros2_rm_robot/rm_mujoco/scripts/prepare_skypiano.py \
  --sample .validation/skypiano_20261113/raw/240828_C0_N5_T0_Technique1 \
  --output .validation/skypiano_20261113/recheck/technique \
  --fps 30 --subject 240828_C0_N5 --piece Technique1 --split valid
```

输出目录必须不存在，防止覆盖实验。此次实际产物在 `prepared_v2/scale/` 和 `prepared_v2/technique/`；较早 `prepared/` 是开发中间结果，保留溯源。

| 文件 | 用途 |
| --- | --- |
| `score.fingering.yaml` | 现有 `piano_fingering/1`，保留所有音符、精确 MIDI 时序、力度、未知指法 |
| `labels.json` | 每音 pseudo 标签来源、候选、可用的原始置信度；未知不填 1 |
| `motion.npz` | 秒级时间、米制键盘坐标、原始观测掩码、腕部/五指/掌面参考，以及独立的补全流 |
| `windows.json` | 每音窗口及同时/交叠音 ID、观测覆盖率，不标记为机器人专家示范 |
| `curriculum.json`、`curriculum/*.proto` | 全部有指法的小型时间重叠连通段，最多 8 音，完整保留和弦与持音，记录源事件 ID 和平移的时间原点 |
| `report.json` | 分组、输入哈希、源版本、坐标定义、质量统计和验证边界 |

`.proto` 遵循 [note-seq NoteSequence](https://github.com/magenta/note-seq/blob/main/note_seq/protobuf/music.proto)，右手 `part=0..4`、左手 `5..9`，从拇指到小指。已用现有 PIG 解析器回读 20 个文件，校验时序/力度/指法。仓内 [RM75 训练入口](../experiments/robopianist_rl/rm75.py) 的 `--midi-file` 接口可接收该格式；尚未在该 Composer 环境实际加载或训练，不将文件回读称作训练通过。

## 坐标、掩码与重定向边界

输入位置是毫米，输出是米。优先使用实际观测的 `LEnd1/REnd1`，否则使用 `LEnd/REnd`。沿用上游键盘几何约定：52 白键、23.5 mm 白键间距、对称琴壳边距，主参考点相对辅助参考线校正 78 mm。参考点运动超过 5 mm、跨度或水平度明显异常时拒绝转换。

输出键盘坐标为右手系：X 从低音到高音、Y 远离演奏者、Z 向上；原点位于 A0 横向中心的白键参考线上。掌面是通过腕部、食指/小指 MCP 定义的人体标记坐标系，**不是 L20 法兰坐标系**。

`positions_keyboard_m` 只含实测值，缺失为 NaN；`observed_mask` 指示可用性。补全流单独保存，`inferred_filled_mask` 由原始缺失推断，`changed_observed_mask` 标出补全流对已观测值的改动。这不是完整发布版的官方插值掩码，不把补全结果伪装成实测。

`--world-from-keyboard` 可接收 JSON 4×4 刚体变换（平移单位米），输出 `human_world_targets.npz`。会拒绝缩放、反射及非法矩阵。真实仿真场景的变换必须由该场景的键盘位置建立，不能把人体座位或臂长复制给 RM75。本轮未提供虚构的场景标定，也没有求解机械臂/手指 IK。

后续重定向需同时处理：RM75 关节裕量、L20 关节/执行器耦合、人体皮肤标记到机器人指腹的偏移、手掌方向、避碰和连续速度。只有仿真得到原谱时序内的目标按下/保持/释放，且实际键角/MIDI 无误触、限位和碰撞，才能保存 `(observation, applied_action)` 为 BC 标签。本入口的 `robot_expert_eligible` 固定为 `false`；后续准入需要独立仿真证据。

## PianoVAM 接入和训练顺序

继续复用 `import_pianovam.py` 和 `prepare_pianovam_tasks.py`，按键结束用 `key_offset`，不是含踏板的 `frame_offset`。本轮实际输出：

- `.validation/skypiano_20261113/pianovam/clair.fingering.yaml`：完整 150 音 GT，54 左手、96 右手。
- `.validation/skypiano_20261113/pianovam/clair.tasks.json`：`--window-notes 1,4,8 --complete-phrases --max-tasks 10` 得到 9 个完整课程任务，沿用官方 train 划分。

训练使用顺序：先用人体轨迹约束候选初始手势/腕部路径，再做机器人重定向和动态接触验证；合格动作做 BC；随后在相同课程、种子和步数下比较随机初始化 RL 与 BC 初始化 RL。评价使用实际物理按放，不把指尖贴近目标、文件转换成功或监督损失下降视为演奏成功。本数据入口不包含重定向器或策略训练器，后续独立实验见下节。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  src/ros2_rm_robot/rm_mujoco/test/test_skypiano.py \
  src/ros2_rm_robot/rm_mujoco/test/test_import_pianovam.py \
  src/ros2_rm_robot/rm_mujoco/test/test_pig_score.py -q
```

## 同日独立实验的后续证据

14:42 只读复核另一聊天的 `.validation/rm75_skypiano_chain_20261113/`。它已复用本轮数据做转换、开环标定和 RL 对照；这些不是本入口的测试，也不应再写成整个项目尚未运行 RL。

`convert/win_000/validation_report.json` 记录保持 1/4 目标帧、6 碰撞帧、0 限位，`clean_press_release=false`。现有 `actions.npz` 只存动作，RL 的 `rollout.npz` 有请求/实际动作、qpos、激活与奖励，但没有逐物理步的 qvel、执行器力和接触力。它证明该动作没有持续保持，尚不足以唯一锁定键盘回弹参数为根因。

本地 RoboPianist 基线 `piano_constants.py` 已配置白/黑键刚度 2 Nm/rad、阻尼 0.05；实际隔离运行模型还需核验。优先诊断固定目标下的实际手指跟踪、接触点滑移和力平衡，再按证据调整控制/几何/数值参数。单种子且同时改变可达初始化与距离 shaping 的对照，也不能独立量化人体数据的因果收益。原始门槛及不同碰撞统计口径应保留。
