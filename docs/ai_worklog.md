# AI 协作台账

本文件记录多个 AI 在同一工作区的任务、进度和改动，避免重复劳动与文件冲突。

- 时区 Asia/Shanghai（UTC+8），时间精确到分钟。
- 各表按时间倒序，最新的在最上面。
- 只追加、只改自己名下的行；只有「当前快照」允许整体替换。
- 入口：[`AGENTS.md`](../AGENTS.md) 顶部的「AI 协作（必读）」。

## 1. 使用协议

**开工三步**

1. 读第 3～6 节，确认任务不在「已完成」里，也没有别人在做。
2. 认领：在「任务看板」登记任务并把状态改为「进行中」，把要改的路径登记到「文件占用表」。
3. 跑一次 `git status`，确认工作区没有未登记的改动；有就先在「交接与阻塞」记录，不要覆盖。

**收工三步**

1. 在「修改记录」追加一行：改了哪些文件、改了什么、验证到什么程度、留了什么。
2. 把任务状态改为「待验证」或「完成」，释放占用表中的行。
3. 更新「AI 花名册」的最近同步时间。

**硬规则**

- 同一文件同一时间只允许一个 AI 修改；要动别人占用的文件，先在「交接与阻塞」留言，等对方释放。
- 不改写、不删除其他 AI 的条目；发现过期内容只在「交接与阻塞」记录。
- `git status` 有变动而本台账没有对应记录，视为漏记录：补记后再继续。
- 验证程度必须如实填写。Windows 上只能做静态检查，构建、仿真、真机在 Ubuntu 22.04 上做，不能混写。
- 本台账是唯一进度来源，不要另建临时进度文件或 TODO 列表。

## 2. 验证程度

| 标记 | 含义 |
| --- | --- |
| 静态检查 | 只读代码、语法、结构、链接检查，未运行 |
| 单元测试 | `colcon test --packages-select <pkg>` 通过，注明执行环境 |
| 仿真 | MuJoCo 仿真跑通，注明场景与操作 |
| 真机 | 真机执行过，注明机型与安全条件 |
| 未验证 | 只改了代码或文档，没有做任何运行验证 |

没跑过的不能写「通过」；只在仿真里验证过的，不能写成真机通过。

## 3. AI 花名册

| AI / 工具 | 运行环境 | 主要负责 | 最近同步 | 备注 |
| --- | --- | --- | --- | --- |
| Codex Desktop / piano-validation | Windows 编辑 + Jetson / MuJoCo | 同时按键、双手、跨曲及真机前置验证 | 2026-11-11 15:44 | T-0031 仿真验证结束，真机网络和串口待接通 |
| Codex Desktop / right-warm-ppo | Windows 编辑 + Jetson / MuJoCo | 固定腕 70/73 动作初始化与 PPO 迁移 | 2026-11-11 15:23 | T-0030 留出原谱 5/5，PPO 未改变边沿 |
| Codex Desktop / right-key-switch | Windows 编辑 + Jetson / MuJoCo | 右手高位固定腕异键原谱验收 | 2026-11-11 15:05 | T-0029 70→73 物理通过，PPO 仍待验证 |
| Codex Desktop / right-fixed-wrist | Windows 编辑 + Ubuntu WSL / Jetson | 右手固定腕原时序物理复验 | 2026-11-11 14:39 | T-0028 两段同键短音原谱物理验收通过 |
| Codex Desktop / direct-corpus | Windows 编辑 + Ubuntu WSL / Jetson | 直接 PPO 跨曲数据和评估入口 | 2026-11-10 16:48 | T-0027 数据和评估入口完成，基准已归档 |
| Codex Desktop / middle-finger | Windows 编辑 + Jetson / MuJoCo | 中指 MIDI 54 独立 PPO 与合并准入 | 2026-11-10 15:33 | T-0026 物理预检通过，PPO 未达到合并门槛 |
| Codex Desktop / fixed-wrist-pair | Windows 编辑 + Jetson / MuJoCo | 双键共同可达的高位固定腕标定 | 2026-11-10 14:56 | T-0025 双键标定通过，两组 PPO 均未通过验证 |
| Codex Desktop / direct-multifinger | Windows 编辑 + Ubuntu WSL / Jetson | 直接控制 PPO 单音复验与固定腕多指 | 2026-11-10 14:36 | T-0024 复核、续训和可达性试验已归档；第 05 批待准入 |
| Codex Desktop / y015-40-fix | Windows 编辑 + Jetson Conda / MuJoCo | 修复 y=0.15 原速双手整曲 | 2026-11-09 21:11 | T-0018 完成，双手 40/40 严格通过、输入专项 8/8、零残差回放 40/40，计划和清单已合入工作区 |
| Codex Desktop / y015-recovery | Windows 编辑 + Jetson Conda / MuJoCo | y=0.15 下恢复传统轨迹、复验短片段及 PPO 对照 | 2026-11-09 20:02 | T-0017 短片段 8/8 和双手 24 音通过，40 音仍待严格验收；证据取回且占用释放 |
| Codex Desktop / new-music | Windows 编辑 + Jetson Conda / MuJoCo | 新曲连续乐句参考与冻结模型迁移对照 | 2026-11-09 16:30 | T-0014 完成 26 次参考规划尝试，尚无合格连续 8 音参考，策略对照及微调未运行；证据本地校验通过、占用释放，任务待验证 |
| Codex Desktop / rl-continue | Windows 编辑 + Jetson Conda / MuJoCo | 三种子混合课程长程续训与新噪声对照 | 2026-11-09 16:27 | T-0013 三组仍在真实 PPO 采样，观察到累计 44544/45056/45568 步；后台 supervisor 3678650、训练 PID 3678651/52/53，目标各 73728；最终验收待完成 |
| Codex Desktop / rl-generalization | Windows 编辑 + Jetson Conda / MuJoCo | 完整回合训练、共享接口、PianoVAM 多录音训练与独立测试 | 2026-11-09 15:21 | T-0012 修复和独立对照完成；证据已取回并校验，全部后台进程结束，占用已释放；未证明泛化收益 |
| Codex Desktop / effect-demo | Windows 展示 + Jetson Conda / MuJoCo | 复验并展示 Kimi 当前双手模型与训练后模型 | 2026-11-09 13:49 | T-0011 完成；两个模型重新回放及 32.28 秒对比视频通过检查；保留既有源码与实验 |
| Codex Desktop / rl-followup | Windows 编辑 + Jetson Conda / MuJoCo | 接续 Kimi 的奖励诊断、最小修复及三种子验证 | 2026-11-09 08:46 | 用户在本聊天明确回复“执行”，授权接管 Kimi 的 RL 文件占用；仅仿真 |
| Codex Desktop / piano-rl | Windows 编辑 + Jetson Conda / MuJoCo | PianoVAM 右手残差 PPO 首轮训练与独立录音评估 | 2026-11-09 02:47 | 用户已确认执行；仅仿真，独立 Conda 环境 |
| Codex Desktop / 40-note | Windows 编辑 + Jetson 仿真 | 双手《两只老虎》40 音连续调度与验收 | 2026-11-09 08:42 | 正式源码复验入口已合入；8 个输入检查测试和双手 40 音联合仿真通过 |
| Claude Code | 待登记 | 待登记 | — | |
| Codex CLI | 待登记 | 待登记 | — | |
| Qwen Code | 待登记 | 待登记 | — | 旧入口 `QWEN.md` 在工作区已删除，按 `AGENTS.md` 与本台账工作 |
| Kimi Code | Windows 编辑 + Jetson Conda / MuJoCo | 多曲目 RL 泛化、稳定性与 RoboPianist 对齐 | 2026-11-09 21:27 | T-0019 已合入新观测、F1、等步数课程和最差任务选模；仅 Windows 静态检查，待 Ubuntu/Conda 验证 |
| DeepSeek Harness | Windows 编辑 + Jetson 验证 | 文档、协作台账、`rm_mujoco` 右手尾段、提交与推送 | 2026-11-09 16:39 | 2026-11-08 建立本台账并拉回右手尾段 v29；2026-11-09 按用户要求提交并推送钢琴 RL 与双手 40 音改动（`2354b80`） |

## 4. 任务看板

状态取值：待办 / 进行中 / 待验证 / 完成 / 阻塞 / 已搁置。

| 任务号 | 任务 | 负责人 | 状态 | 涉及文件 / 包 | 开始 | 最近更新 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-0031 | 同时按键、双手、跨曲和真机条件验证 | Codex Desktop / piano-validation | 待验证 | 本台账、`docs/piano_direct_rl.md`、本地及 Jetson 隔离验证目录 | 2026-11-11 15:36 | 2026-11-11 15:44 | 仿真和整曲覆盖核验完成，真机未枚举 L20 串口，RM75 地址未响应 |
| T-0030 | 右手 70/73 动作初始化与 PPO 原谱迁移对照 | Codex Desktop / right-warm-ppo | 完成 | 本台账、`docs/piano_direct_rl.md`、本地与 Jetson 隔离实验目录 | 2026-11-11 15:13 | 2026-11-11 15:23 | 规则、行为克隆、PPO 均通过合成留出 15/16 和单片段原谱 5/5 |
| T-0029 | 右手固定腕的原谱异键和多指训练准入 | Codex Desktop / right-key-switch | 待验证 | 本台账、`docs/piano_direct_rl.md`、本地与 Jetson 隔离实验目录 | 2026-11-11 14:44 | 2026-11-11 15:05 | 70→73 原谱脚本 5/5；75 干净按放最长 74 ms；两组 PPO 各 4,096 步，原谱均 0/5 |
| T-0028 | 右手高位固定腕 PianoVAM 原时序按放 | Codex Desktop / right-fixed-wrist | 完成 | `docs/piano_direct_rl.md`、本台账、隔离实验目录 | 2026-11-11 09:28 | 2026-11-11 14:39 | 2 音和 12 音连续按原谱通过，最短原谱 29.167 ms 实测 36 ms；仅固定腕同键物理基准 |
| T-0027 | PianoVAM 完整乐句、多录音直接 PPO 与跨曲基准 | Codex Desktop / direct-corpus | 完成 | 直接任务生成、环境、训练入口及专项测试、`docs/piano_direct_rl.md`、本台账、隔离实验目录 | 2026-11-10 15:57 | 2026-11-10 16:48 | 33/33 完整乐句逐事件核对；Jetson 79 项回归，1,024 步冒烟覆盖 6 份训练录音；同一冻结模型完成两曲 6 段评估 |
| T-0026 | MIDI 54 中指单音 PPO 与双指合并准入 | Codex Desktop / middle-finger | 待验证 | 本台账、`docs/piano_direct_rl.md`、独立仿真目录 | 2026-11-10 15:09 | 2026-11-10 15:33 | 20 ms 平滑松键物理预检 18/18；中指 PPO 最好 8/9，与窗口固定触发对照边沿完全相同，未进入双指 |
| T-0025 | 高位固定腕双键标定及多指训练准入 | Codex Desktop / fixed-wrist-pair | 待验证 | `docs/piano_direct_rl.md`、本台账、本地与 Jetson 隔离实验子目录 | 2026-11-10 14:37 | 2026-11-10 14:56 | 原高位参考姿态左手 53/54 单键、换键及重叠通过，实际重叠 296 ms；两组 PPO 均 0/8，真实 PianoVAM 快换投影全部键角越界 |
| T-0024 | 直接控制 PPO 严格单音验收与固定腕多指（第 04 批复验、第 05 批） | Codex Desktop / direct-multifinger | 待验证 | 直接控制环境、奖励、验收、训练入口及其专项测试、`docs/piano_direct_rl.md`、本台账、独立实验目录 | 2026-11-10 12:51 | 2026-11-10 14:36 | Jetson 74 项回归通过，F3 脚本 9/9、四组续训 0/9、1/9、1/9、3/9；237 组固定腕探测未找到可干净持续保持的第二键 |
| T-0023 | PianoDirectEnv 单音 PPO 训练（第 04 批） | DeepSeek Harness | 完成 | `rm_mujoco/piano_direct.py`、`piano_direct_reward.py`、`piano_direct_eval.py`、`scripts/train_piano_direct.py`、`test/test_piano_direct.py`、`test/test_piano_direct_reward.py`、`test/test_piano_direct_eval.py`、`CMakeLists.txt`、`docs/piano_direct_rl.md`、本台账、Jetson `.validation/piano_direct_f3_delivery/` | 2026-11-10 07:48 | 2026-11-10 12:30 | 左手 F3（MIDI 53）、固定高位双臂、单通道 1、action_scale=80、lead-in 0.2 s；PPO 40,960 步后加 20 ms 观测相位补偿；独立 20/20 通过（onset +20 ms、release -16 ms、无键越限/其他接触），随机基线 0/20 |
| T-0022 | PianoDirectEnv 物理奖励（第 03 批） | DeepSeek Harness | 待验证 | `rm_mujoco/piano_direct_reward.py`、`rm_mujoco/piano_direct.py`、`config/piano_direct_env.yaml`、`test/test_piano_direct_reward.py`、`test/test_piano_direct.py`、`CMakeLists.txt`、`docs/piano_direct_rl.md`、本台账 | 2026-11-10 01:47 | 2026-11-10 01:55 | 奖励按真实键角/指尖距离/动作/安全分量计算；正确 2.2 > 静止 -1.0、漏按 -2.5、错按 -3.0、持续压住 -1.0；Jetson 奖励+环境 14 项测试通过；未训练 PPO |
| T-0021 | PianoVAM 直接控制 RL 第 00–02 批：审计、任务生成器、无参考轨迹环境 | DeepSeek Harness | 待验证 | `docs/piano_direct_rl.md`、`rm_mujoco/pianovam_tasks.py`、`piano_direct.py`、`config/piano_direct_env.yaml`、`scripts/prepare_pianovam_tasks.py`、`scripts/check_piano_direct_env.py`、`test/test_pianovam_tasks.py`、`test/test_piano_direct.py`、`CMakeLists.txt`、`docs/piano_rl.md`、本台账 | 2026-11-10 00:45 | 2026-11-10 01:20 | 旧残差 PPO 未改；新增 `piano_rl_tasks/1`、PianoVAM 任务生成器和固定双臂 `PianoDirectEnv`；Jetson Conda 上 14 项新测试 + 7 项导入回归 + 34 项旧 `piano_rl` 回归通过；仅仿真、无 PPO 训练 |
| T-0020 | RM75 双臂静态高肘姿态（原 88 键任务暂停） | DeepSeek Harness | 待验证 | `rm_mujoco/rm_mujoco/fingering.py`、`scripts/analyze_88_keys.py`、`optimize_88key_layout.py`、`retry_dynamic_failures.py`、`render_key_postures.py`、`render_performance_video.py`、`config/piano_scene_88key.yaml`、`test/test_fingering.py`、`CMakeLists.txt`、`docs/piano_88key.md`、本台账、本地与 Jetson `.validation/arm_posture_20261109/` | 2026-11-09 22:28 | 2026-11-09 23:35 | 用户 23:2x 改为仅静态姿势：按实拍参考抬高肘部、保存默认场景左右 7 关节角并生成三视图；88/40 规划已停止，等待用户确认姿势前不继续 |
| T-0019 | 多曲目强化学习的泛化与稳定性对齐 | Kimi Code | 进行中 | RL 环境、训练/鲁棒性入口、专项测试、RL 文档、本台账 | 2026-11-09 21:16 | 2026-11-09 21:30 | 用户要求 Jetson 验证；已确认 `piano_rl` Conda 和远端工作区可用，将在独立目录部署并先跑专项测试与最小 PPO 闭环 |
| T-0018 | 修复 y=0.15 下双手《两只老虎》40 音 | Codex Desktop / y015-40-fix | 完成 | 本台账、实验目录、`rm_mujoco/examples/two_tigers_flat_palms/verified_40/`、`docs/usage.md` | 2026-11-09 20:05 | 2026-11-09 21:11 | 默认场景正式整曲 40/40，原速、固定指法及 30 ms 容差；专项 8/8，零残差回放 40/40。已合入计划与清单，证据取回，占用释放 |
| T-0017 | 钢琴后移后的传统轨迹恢复及强化学习对照 | Codex Desktop / y015-recovery | 待验证 | 本台账、本地与 Jetson `.validation/piano_y015_recovery_20261109/` | 2026-11-09 19:31 | 2026-11-09 20:02 | 同场景 8 个短片段通过，双手原速连续前 24 音通过。整曲候选匹配 40/40，仍有两个邻键、两处键角及两个提前落键。冻结 PPO 在独立片段及 24 音的配对对照未显示稳定通过率收益。仅 MuJoCo |
| T-0016 | 适配强化学习参考谱子到钢琴 y=0.15 | Kimi Code | 进行中 | 本台账、Jetson fix 工作区新增 `.validation/piano_rl_y015_adaptation_20261109/`；只读使用既有 RL 数据与源码 | 2026-11-09 17:30 | 2026-11-09 17:30 | T-0015 已定 y=0.15，RL 参考（PianoVAM 短片段 + 40 音双手）绑旧几何需重规划；T-0013 后台训练仍跑，仅新增目录、不改正式源码与其冻结快照 |
| T-0015 | MuJoCo 钢琴整体后移，扩大机械臂工作空间 | Kimi Code | 待验证 | `src/ros2_rm_robot/rm_mujoco/config/piano_scene.yaml`、本台账、`.validation/piano_offset_sweep_20261109/` | 2026-11-09 16:39 | 2026-11-09 17:24 | 默认定为 y=0.15：13 偏移扫 0.00~0.60 按最大化最差关节余量选定（C-18/C-19/C-20）；覆盖率 0.00~0.20 持平 20/22，60/64 与距离无关，0.55 起超出臂展；待 y=0.15 下整曲重标定（40 音/RL 参考） |
| T-0014 | 三首新曲的连续乐句与迁移试验 | Codex Desktop / new-music | 待验证 | 本台账、RL 文档、本地及远端 `.validation/piano_rl_new_music_20261109/` | 2026-11-09 16:14 | 2026-11-09 16:30 | 原配置 18 次、姿态覆盖 6 次、Home 加时 2 次，均在规划阶段失败，无完整 8 音参考，故冻结策略对照和微调未运行。Home 已推进到第五音，后续仍受换腕、超行程和误触限制；127 份证据 SHA256 通过，结果见实验 RESULTS.md；未降低原速/指法/30ms 门槛，已释放占用 |
| T-0013 | 混合课程三种子长程续训 | Codex Desktop / rl-continue | 待验证 | 本台账、RL 文档、本地及远端 `.validation/piano_rl_continue_20261109/` | 2026-11-09 15:51 | 2026-11-09 16:27 | 后台续训运行中；观察到三组真实累计 44544/45056/45568，目标各 73728，保留权重和优化器。参考和恢复策略均通过 48 训练音及 1 验证音的无扰动验收；最终训练及新噪声 3001/3003/3007 对照待完成。旧测试录音只作回归 |
| T-0012 | 修复残差 RL 覆盖并验证跨片段泛化 | Codex Desktop / rl-generalization | 完成 | RL 环境、训练/鲁棒性入口、准备数据新入口、专项测试、CMake 和 RL 文档 | 2026-11-09 13:59 | 2026-11-09 15:21 | 修复及六组 8192 步对照完成；36 项测试、隔离构建、安装入口及无扰动完整 40 音通过。独立扰动整曲各 0/3；新曲参考 5/6，三模型 5/6、5/6、4/6，无可靠学习增益。证据本地已校验；仅仿真，未提交 |
| T-0011 | 展示 Kimi 双手 PPO 工程效果 | Codex Desktop / effect-demo | 完成 | 本台账；本地与 Jetson fix 工作区 `.validation/kimi_effect_demo_20261109/` | 2026-11-09 13:42 | 2026-11-09 13:49 | 独立复验：选中第 0 步模型 40/40 通过；最后 512 步模型匹配 40 音但事件 28 时长偏差 31ms，容差 30ms，验收失败。32.28 秒原速对比视频、原始物理状态/报告已取回本地；仅仿真，未证明 RL 改善 |
| T-0010 | 接管并复核当前双手残差 PPO 工程 | Kimi Code | 完成 | 当前 RL 环境、训练/评估入口、专项测试、RL 文档及 Codex 后续实验目录 | 2026-11-09 12:25 | 2026-11-09 12:47 | 保留 Codex 双手/事件奖励/选模实现，补齐安装资源与入口；Jetson 专项 25/25、安装版 40/40、512 步闭环完成；最后模型有 1 个时长异常，选中第 0 步基线；扰动 seed 101 参考与基线均 39/40，未证明训练改善 |
| T-0009 | 接续 Kimi：修复残差 PPO 的验收退化 | Codex Desktop / rl-followup | 已搁置 | RL 环境、训练入口、专项测试、RL 文档、本台账；新实验目录 `.validation/piano_rl_followup_20261109/` | 2026-11-09 08:46 | 2026-11-09 12:25 | 用户最新指令由 Kimi 接管并释放 Codex；现有未验证修改全部保留，由 T-0010 复核 |
| T-0008 | 将验证后的 RL 合入正式工程 | Kimi Code | 完成 | `piano_rl.py`、训练入口、测试、CMake 与 RL 文档 | 2026-11-09 06:43 | 2026-11-09 07:01 | 单右手版本正式合入；源码/安装入口及专项 6/6 通过，后续双手修改由 T-0010 复核 |
| T-0007 | RoboPianist 式奖励与短步数多 seed 对照 | Kimi Code | 完成 | 远端 `.validation/kimi_piano_rl_reward_20261109/` 独立包副本与实验输出 | 2026-11-09 06:39 | 2026-11-09 07:01 | 两种奖励各三个 seed、4,096 步完成；训练后均未通过 11 音物理验收，独立验证均 3/3，未优于参考 |
| T-0006 | RoboPianist 参照的 PianoVAM RL 独立验证 | Kimi Code | 完成 | 远端 `.validation/kimi_piano_rl_20261109/`；只读使用 `rm_mujoco` 现有源码 | 2026-11-09 02:56 | 2026-11-09 06:36 | Conda `piano_rl` 完成 16,384 步 PPO；训练 11 音参考 11/11、学习后 10/11 且有 1 个角度违规，独立验证 3 音保持 3/3；训练未优于参考 |
| T-0005 | PianoVAM 右手残差 PPO 首轮训练 | Codex Desktop / piano-rl | 已搁置 | 原占用的 RL 源码、测试、配置、CMake 与文档 | 2026-11-09 02:47 | 2026-11-09 06:47 | 用户于 06:47 明确授权解除占用，正式工程由 Kimi 的 T-0008 接续；已有文件保留并在此基础上合入 |
| T-0004 | 打通双手 40 音原速整曲 | Codex Desktop / 40-note | 完成 | `rm_mujoco/scripts/verify_two_tigers.py`、`test/test_two_tigers.py`、`examples/two_tigers_flat_palms/verified_40/`、原连续调度文件及 `docs/usage.md` | 2026-11-09 02:20 | 2026-11-09 08:42 | 正式输入/完整计划/身份清单/源码入口合入，Jetson Pytest 8/8、联合回放 40/40，证据 `.validation/dual_two_tigers_1x_20261108/formal40_merged/`。固定曲目已验证，非任意曲谱自动规划，非真机 |
| T-0003 | 把右手尾段 v29 结果拉回正式工程 | DeepSeek Harness | 完成 | `src/ros2_rm_robot/rm_mujoco/`：`config/right_tail_v29.yaml`、`scripts/verify_right_tail.py`、`test/test_right_tail.py`、`CMakeLists.txt` | 2026-11-08 22:20 | 2026-11-08 22:34 | 标定取自 `.validation/dual_two_tigers_1x_20261108/final_tail_v29`；Jetson 上 ctest 与 MuJoCo 回放均通过 |
| T-0002 | 认领并登记工作区现有未提交改动 | DeepSeek Harness | 完成 | `rm_mujoco/rm_mujoco/fingering.py`、`rm_mujoco/config/right_hand_piano_sim.yaml`、`rm_mujoco/test/test_fingering.py` | 2026-11-08 22:34 | 2026-11-08 22:34 | 三处均为开工前已有的未提交改动，按原样登记，未改动其内容 |
| T-0001 | 建立 AI 协作台账 | DeepSeek Harness | 完成 | `docs/ai_worklog.md`、`AGENTS.md` | 2026-11-08 22:25 | 2026-11-08 22:25 | 首版：协议、空表、当前快照 |

## 5. 文件占用表

路径写相对仓库根的路径；目录级占用用前缀，例如 `src/ros2_rm_robot/rm_mujoco/`。占用前先和自己要改的路径求交集，父子路径重叠也要当成冲突。无占用时保留表头即可，不要写占位行。

| 路径 | 占用者 | 开始 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| 本台账、`docs/piano_direct_rl.md`、本地 `.validation/piano_validation_20261111/` 与 Jetson `~/arm_posture_20261109/piano_validation_20261111/` | Codex Desktop / piano-validation | 2026-11-11 15:36 | 已释放 | T-0031 报告已取回，进程已结束 |
| 本台账、`docs/piano_direct_rl.md`、本地 `.validation/piano_right_warm_ppo_20261111/` 与 Jetson `~/arm_posture_20261109/piano_right_warm_ppo_20261111/` | Codex Desktop / right-warm-ppo | 2026-11-11 15:13 | 已释放 | T-0030 评估完成，取回报告与检查点 |
| 本台账、`docs/piano_direct_rl.md`、本地 `.validation/piano_right_key_switch_20261111/` 与 Jetson `~/arm_posture_20261109/piano_right_key_switch_20261111/` | Codex Desktop / right-key-switch | 2026-11-11 14:44 | 已释放 | T-0029 已取回输入、物理报告和模型，相关进程已结束 |
| `docs/piano_direct_rl.md`、本台账、T-0028 本地与 Jetson 隔离实验目录 | Codex Desktop / right-fixed-wrist | 2026-11-11 14:24 | 已释放 | T-0028 取回并核对 3 份物理报告，独立复播通过 |
| `docs/piano_direct_rl.md`、本台账、本地 `.validation/piano_right_fixed_wrist_20261111/` 与 Jetson `~/arm_posture_20261109/piano_right_fixed_wrist_20261111/` | Codex Desktop / right-fixed-wrist | 2026-11-11 14:03 | 已释放 | T-0028 物理报告已取回并校验，进程已结束 |
| `docs/piano_direct_rl.md`、本台账、本地 `.validation/piano_right_fixed_wrist_20261111/` | Codex Desktop / right-fixed-wrist | 2026-11-11 09:28 | 已释放 | T-0028 离线工作完成，恢复仿真前重新认领 |
| `rm_mujoco/pianovam_tasks.py`、`rm_mujoco/piano_direct.py`、`rm_mujoco/pianovam_corpus.py`、`scripts/prepare_pianovam_tasks.py`、`scripts/train_piano_direct.py`、`test/test_pianovam_tasks.py`、`test/test_piano_direct.py`、`docs/piano_direct_rl.md`、本地和 Jetson 隔离 `piano_direct_corpus_20261110/` | Codex Desktop / direct-corpus | 2026-11-10 15:57 | 已释放 | T-0027 专项回归与基准验证完成，证据已取回 |
| `docs/piano_direct_rl.md`，本地与 Jetson `piano_direct_multifinger_20261110/middle_finger/` | Codex Desktop / middle-finger | 2026-11-10 15:09 | 已释放 | T-0026 仿真结束，模型和数据已取回，合并准入待验证 |
| `docs/piano_direct_rl.md`，本地与 Jetson `piano_direct_multifinger_20261110/fixed_wrist_pair/` 实验子目录 | Codex Desktop / fixed-wrist-pair | 2026-11-10 14:37 | 已释放 | T-0025 仿真结束，证据已归档；第 05 批策略验收待完成 |
| T-0024 的直接控制环境、奖励、验收、训练入口、专项测试、`docs/piano_direct_rl.md` 及本地和 Jetson 隔离实验目录 | Codex Desktop / direct-multifinger | 2026-11-10 14:21 | 已释放 | 实验结束并取回证据；第 05 批的训练准入待解决 |
| `src/ros2_rm_robot/rm_mujoco/` 下 `rm_mujoco/piano_direct.py`、`piano_direct_reward.py`、`piano_direct_eval.py`、`scripts/train_piano_direct.py`、`test/test_piano_direct*.py`，`docs/piano_direct_rl.md`，本地 `.validation/piano_direct_multifinger_20261110/` 与 Jetson `~/arm_posture_20261109/piano_direct_multifinger_20261110/` | Codex Desktop / direct-multifinger | 2026-11-10 12:51 | 已释放 | T-0024 等待 Jetson 源码上传授权；恢复执行前重新认领 |
| `src/ros2_rm_robot/rm_mujoco/rm_mujoco/fingering.py`、`src/ros2_rm_robot/rm_mujoco/scripts/analyze_88_keys.py`、`optimize_88key_layout.py`、`retry_dynamic_failures.py`、`render_key_postures.py`、`render_performance_video.py`、`config/piano_scene_88key.yaml`、`test/test_fingering.py`、`CMakeLists.txt`、`docs/piano_88key.md`、本台账、本地与 Jetson `.validation/arm_posture_20261109/` | DeepSeek Harness | 2026-11-09 22:28 | 占用中 | T-0020 88 键可达性、布局与 IK 姿态；不改 `verified_40`、乐谱、指法、RL 源码 |
| `docs/piano_direct_rl.md`、`docs/piano_rl.md`、`src/ros2_rm_robot/rm_mujoco/rm_mujoco/pianovam_tasks.py`、`piano_direct.py`、`config/piano_direct_env.yaml`、`scripts/prepare_pianovam_tasks.py`、`scripts/check_piano_direct_env.py`、`test/test_pianovam_tasks.py`、`test/test_piano_direct.py`、`CMakeLists.txt`、本台账 | DeepSeek Harness | 2026-11-10 00:45 | 已释放 | T-0021 直接控制 RL 00–02 批；只追加 CMake 新配置/脚本/测试，不改 T-0020 的 fingering/88 键内容；Jetson 55 项测试通过、冒烟完成，源码未提交；未改旧 `piano_rl.py`/`train_piano_rl.py` |
| `rm_mujoco/piano_direct_reward.py`、`rm_mujoco/piano_direct.py`、`config/piano_direct_env.yaml`、`test/test_piano_direct_reward.py`、`test/test_piano_direct.py`、`CMakeLists.txt`、`docs/piano_direct_rl.md`、本台账 | DeepSeek Harness | 2026-11-10 01:47 | 已释放 | T-0022 第 03 批奖励；只改直接控制模块/配置/测试和文档，不改旧残差 PPO；Jetson 奖励+环境 14 项通过，源码未提交 |
| `rm_mujoco/piano_direct.py`、`piano_direct_reward.py`、`piano_direct_eval.py`、`scripts/train_piano_direct.py`、`test/test_piano_direct.py`、`test/test_piano_direct_reward.py`、`test/test_piano_direct_eval.py`、`CMakeLists.txt`、`docs/piano_direct_rl.md`、本台账、Jetson `.validation/piano_direct_f3_delivery/` | DeepSeek Harness | 2026-11-10 07:48 | 已释放 | T-0023 第 04 批单音 PPO 完成；20/20 通过，模型/配置/评估在 Jetson `piano_direct_f3_delivery/`，本地 `.validation/piano_direct_f3_delivery/`；未改旧残差 PPO；训练进程结束 |
| `docs/ai_worklog.md`、`docs/piano_rl.md`、`src/ros2_rm_robot/rm_mujoco/rm_mujoco/piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/scripts/evaluate_piano_robustness.py`、`src/ros2_rm_robot/rm_mujoco/test/test_piano_rl.py`、本地与 Jetson `.validation/piano_rl_multisong_stability_20261109/` | Kimi Code | 2026-11-09 21:30 | 占用中 | T-0019 Jetson 独立目录验证；不改正式远端源码、既有模型或实验输出 |
| `src/ros2_rm_robot/rm_mujoco/examples/two_tigers_flat_palms/verified_40/`、`docs/usage.md` | Codex Desktop / y015-40-fix | 2026-11-09 21:08 | 已释放 | y=0.15 计划、清单及验证说明已合入 |
| `docs/ai_worklog.md`、本地与 Jetson `.validation/piano_y015_40_fix_20261109/` | Codex Desktop / y015-40-fix | 2026-11-09 20:05 | 已释放 | 原始报告已取回并验摘要，本轮所有进程结束 |
| `docs/ai_worklog.md`、本地与 Jetson `.validation/piano_y015_recovery_20261109/` | Codex Desktop / y015-recovery | 2026-11-09 19:31 | 已释放 | T-0017 结果和原始报告已取回并验 SHA256；本轮仿真进程结束 |
| 本台账、Jetson fix 工作区 `.validation/piano_rl_y015_adaptation_20261109/` | Kimi Code | 2026-11-09 17:30 | 占用中 | T-0016 RL 谱子适配；只新增该目录，不改正式源码与既有实验目录 |
| `src/ros2_rm_robot/rm_mujoco/config/piano_scene.yaml`、`docs/ai_worklog.md`、`.validation/piano_offset_sweep_20261109/` | Kimi Code | 2026-11-09 16:39 | 已释放 | T-0015 钢琴后移已完成待 Jetson 验证；实验目录在 .validation 下，git 忽略 |
| `docs/ai_worklog.md`、`docs/piano_rl.md`、本地及远端 `.validation/piano_rl_new_music_20261109/` | Codex Desktop / new-music | 2026-11-09 16:14 | 已释放 | 26 次尝试和证据取回完成，无新曲仿真进程遗留；连续参考仍待解决，策略对照未运行；正式源码及现有后台训练保持原样 |
| `docs/ai_worklog.md`、`docs/piano_rl.md` | Codex Desktop / rl-continue | 2026-11-09 15:51 | 已释放 | 续训启动记录和操作说明已写入；T-0013 后台任务仍运行，最终结果待验证 |
| 本地及远端 `.validation/piano_rl_continue_20261109/` | Codex Desktop / rl-continue（后台训练） | 2026-11-09 15:51 | 占用中 | supervisor 3678650 管理训练与后续配对测试；可读日志，禁止覆盖源码/输入快照和运行输出，进程完成后再收尾释放；正式运行时代码未占用 |
| `docs/ai_worklog.md`、`docs/piano_rl.md`、`src/ros2_rm_robot/rm_mujoco/rm_mujoco/piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/scripts/evaluate_piano_robustness.py`、`src/ros2_rm_robot/rm_mujoco/scripts/prepare_piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/test/test_piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/CMakeLists.txt`、本地及远端 `.validation/piano_rl_generalization_20261109/` | Codex Desktop / rl-generalization | 2026-11-09 13:59 | 已释放 | T-0012 收尾完成；原始失败、旧源码与模型保留；未改冻结曲谱、验收器、机器人模型或规划器；全部训练/测试进程已结束 |
| `docs/ai_worklog.md`、本地及远端 `.validation/kimi_effect_demo_20261109/` | Codex Desktop / effect-demo | 2026-11-09 13:42 | 已释放 | T-0011 演示完成；未修改 RL、规划器、模型或旧实验；仅登记复验和生成展示视频/报告 |
| `docs/ai_worklog.md`、`docs/piano_rl.md`、`docs/piano_workflow.md`、`docs/usage.md`、`src/ros2_rm_robot/rm_mujoco/rm_mujoco/piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/scripts/evaluate_piano_robustness.py`、`src/ros2_rm_robot/rm_mujoco/scripts/verify_two_tigers.py`、`src/ros2_rm_robot/rm_mujoco/test/test_piano_rl.py`、`src/ros2_rm_robot/rm_mujoco/test/test_two_tigers.py`、`src/ros2_rm_robot/rm_mujoco/config/piano_rl_environment.yaml`、`src/ros2_rm_robot/rm_mujoco/CMakeLists.txt`、`src/ros2_rm_robot/rm_mujoco/examples/two_tigers_flat_palms/verified_40/README.md`、本地及远端 `.validation/piano_rl_followup_20261109/`、`.validation/piano_rl_dual_20261109/`、`.validation/kimi_piano_rl_reward_20261109/`、远端 `.validation/kimi_rl_formal_20261109/` | Kimi Code | 2026-11-09 12:25 | 已释放 | T-0010 正式化与验证完成，详见 C-20261109-06；源文件、模型和报告保留，无后台训练/评估进程 |
| `docs/ai_worklog.md`、`src/ros2_rm_robot/rm_mujoco/scripts/verify_two_tigers.py`、`src/ros2_rm_robot/rm_mujoco/test/test_two_tigers.py`、`src/ros2_rm_robot/rm_mujoco/examples/two_tigers_flat_palms/verified_40/` | Codex Desktop / 40-note | 2026-11-09 08:38 | 已释放 | 用户确认释放后合入完成；新入口、完整动作参数及曲谱已通过 Jetson 联合复验；未修改 RL/CMake |
| `src/ros2_rm_robot/rm_mujoco/rm_mujoco/fingering.py`、`src/ros2_rm_robot/rm_mujoco/config/right_hand_piano_sim.yaml`、`src/ros2_rm_robot/rm_mujoco/test/test_fingering.py`、`docs/usage.md` | Codex Desktop / 40-note | 2026-11-09 02:20 | 已释放 | 40 音联合复验完成；保留既有调度、配置、测试改动，更新正式复验文档 |
| `docs/ai_worklog.md`、`AGENTS.md` | DeepSeek Harness | 2026-11-08 22:25 | 已释放 | 建立台账与入口 |
| `src/ros2_rm_robot/rm_mujoco/config/right_tail_v29.yaml`、`src/ros2_rm_robot/rm_mujoco/scripts/verify_right_tail.py`、`src/ros2_rm_robot/rm_mujoco/test/test_right_tail.py`、`src/ros2_rm_robot/rm_mujoco/CMakeLists.txt`、`.gitattributes` | DeepSeek Harness | 2026-11-08 22:20 | 已释放 | 新增尾段标定、复现工具与回归测试并完成注册 |

## 6. 修改记录

类型取值：`feat` / `fix` / `docs` / `test` / `chore`。

| 记录号 | 时间 | AI | 类型 | 涉及文件 | 改了什么 | 验证 | commit | 遗留 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C-20261111-06 | 2026-11-11 15:44 | Codex Desktop / piano-validation | test | T-0031 登记路径 | 复验同手并按、双手固定腕合奏、跨录音和快速重击，核算官方整曲音符覆盖，检查真机连接条件 | Jetson MuJoCo：左手脚本并按 2/3，右手脚本 0/81、PPO 0/3；双手脚本 3/3、独立策略 0/3；四份录音六个单音片段 18/18，快重复音 0/6。9 份整曲两键覆盖上限 2.71%–10.28%；只读核验真机无 L20 USB 串口，两臂配置 IP 均未回复 ping | 未提交 | 右手并按时序、左手双手场景短 36 ms、跨曲整曲和真机仍待解决 |
| C-20261111-05 | 2026-11-11 15:23 | Codex Desktop / right-warm-ppo | test | T-0030 登记路径 | 已验证动作库、48 段合成课程、行为克隆初始化和 3,072 步 PPO，比较原谱留出与合成留出 | Jetson MuJoCo：训练预检 48/48，三组留出 15/16 与原谱 5/5，初始化和 PPO 共 21 个配对回合边沿相同；重载模型原谱 5/5 边沿一致，取回五个文件哈希匹配 | 未提交 | 一段原谱和两个已标定键；未测出 PPO 收益，双音并按和跨曲仍待验证 |
| C-20261111-04 | 2026-11-11 15:05 | Codex Desktop / right-key-switch | test | T-0029 登记路径 | 提取两份录音的原谱异键，筛查固定腕食指、无名指、小指，运行四通道 PPO 对照 | Jetson MuJoCo 3.3.7：70→73 脚本 5/5，75 两种状态各补测 1,458 组仍最长 74 ms；两组 PPO 各 4,096 步，原谱 0/5，训练课程回查 0/16；输入原时序逐事件核对，报告和模型 SHA256 匹配 | 未提交 | 70→73 物理基准已建立，多指策略及跨曲泛化待验证 |
| C-20261111-03 | 2026-11-11 14:39 | Codex Desktop / right-fixed-wrist | test | T-0028 登记路径 | 在原高位固定腕筛查 2 ms 食指短击，按连续状态标定原谱重击 | Jetson MuJoCo 3.3.7：2/2、12/12 严格通过，原谱 29.167 ms 音实测 36 ms，无多余音、角度违规或其他碰撞；独立复播物理边沿与接触记录一致，专项 28/28，3 份报告 SHA256 一致 | 未提交 | 单键脚本物理基准。第 05 批 PPO、其他琴键和跨曲泛化另待验证 |
| C-20261111-02 | 2026-11-11 14:10 | Codex Desktop / right-fixed-wrist | test | T-0028 登记路径 | Jetson 恢复后执行默认高位固定腕筛查与食指渐进松键补测 | Jetson MuJoCo 3.3.7：基线 121 组，10 组触发 MIDI 70 且均越界；渐进松键保持试验 15/27 干净，追加 90 组宽度探测，首音按原时序通过，最短干净保持 74 ms；报告 SHA256 一致、进程已结束 | 未提交 | 原谱第二音时长 33.334 ms，2 音和 12 音均无通过预筛的时序方案；PPO 多指和泛化仍待验证 |
| C-20261111-01 | 2026-11-11 09:35 | Codex Desktop / right-fixed-wrist | test | T-0028 登记路径 | 审计右手冻结乐句，准备当前高位固定腕的物理脉冲筛查和原时序回放入口 | Ubuntu 22.04 WSL 数据及边沿评分 Pytest 17/17；复核任务 SHA256、重复音配对、接触归属及键角拒绝；Jetson SSH 两次超时，WSL 缺 MuJoCo/Gymnasium | 未提交 | 右手物理实测待运行；PPO 多指、换键与跨曲能力仍待验证 |
| C-20261110-09 | 2026-11-10 16:48 | Codex Desktop / direct-corpus | feat | T-0027 登记路径 | 完整乐句切片、曲目隔离与哈希清单、同环境按录音轮换、逐曲时序 F1 和独立覆盖报告 | Ubuntu WSL 34 项、Jetson 79 项通过；11 份录音 33 段逐事件核对；1,024 步冒烟轮换 6 份；同一冻结 F3 模型读两曲，全通道冒烟模型 0/6；34 个取回文件 SHA256 相同，本地清单重载通过 | 未提交 | 历史测试只做工程基准；名义音域不是可达证明，当前没有跨曲演奏证据 |
| C-20261110-08 | 2026-11-10 15:33 | Codex Desktop / middle-finger | test | T-0026 隔离目录、`docs/piano_direct_rl.md`、本台账 | 标定中指平滑松键，运行独立单周期 PPO、乐谱窗口和概率解码对照 | Jetson MuJoCo，物理预检 18/18；两组 8,192 步各 0/9，概率中位解码 7/9；95 ms 窗口续训到 12,288 步最好 8/9，固定规则同样 8/9 且边沿完全一致；77 文件 SHA256 一致，无遗留进程 | 未提交 | 唯一剩余失败松键早 32 ms；无已证实的时序学习收益，留出集未用，双指未合并 |
| C-20261110-07 | 2026-11-10 14:56 | Codex Desktop / fixed-wrist-pair | test | T-0025 隔离目录、`docs/piano_direct_rl.md`、本台账 | 复用高位 IK 标定左手 53/54，启动两组两维独立按放 PPO，复测原时序 PianoVAM 两音投影 | Jetson MuJoCo 3.3.7，分别按放、换音及重叠通过，重叠 296 ms，8/8 合成任务物理预检通过；PPO 8,192/6,144 步，两组均 0/8；PianoVAM 56/81 时序匹配、81/81 键角越界；40 项文件哈希匹配，进程均结束 | 未提交 | 仅仿真；两策略验证时均未驱动中指，留出集未启用 |
| C-20261110-06 | 2026-11-10 14:36 | Codex Desktop / direct-multifinger | test | T-0024 隔离实验目录、`docs/piano_direct_rl.md`、本台账 | 用户确认后同步 7 个源码和测试文件及合成任务；运行 F3 脉冲、三组连续动作 PPO、一组两档 PPO、237 组固定腕探测 | Jetson Ubuntu 22.04.5 / MuJoCo 3.3.7，74 项回归通过；F3 物理对照 9/9，PPO 最好续训 3/9，54/56/58 最长干净保持 74/76/76 ms；28 个输入及产物 SHA256 匹配，实验进程均结束 | 未提交 | 90% 单音门槛与第二键持续可达性均未通过；留出测试集未运行，第 05 批未进入 PPO 多指训练 |
| C-20261110-05 | 2026-11-10 13:02 | Codex Desktop / direct-multifinger | fix | T-0024 登记路径 | 配对物理键边沿并检查时长、重触发、残留和重叠；接入奖励及多任务训练评估；准备 F3 train/valid/test 各 9 个互异时序任务 | Ubuntu 22.04 WSL Pytest 31/31，8 个 Python 文件 AST 检查；交付报告的 20 条键边沿按新时长门槛重算均失败 | 未提交 | WSL 缺 MuJoCo/PPO 依赖；Jetson 隔离目录已建立，自动审批拒绝上传源码归档；没有新版仿真结果或训练模型 |
| C-20261110-04 | 2026-11-10 12:30 | DeepSeek Harness | feat | `rm_mujoco/piano_direct_eval.py`、`scripts/train_piano_direct.py`、`test/test_piano_direct_eval.py`、`rm_mujoco/piano_direct.py`、`piano_direct_reward.py`、`test/test_piano_direct.py`、`test/test_piano_direct_reward.py`、`CMakeLists.txt`、`docs/piano_direct_rl.md`、本台账、Jetson `.validation/piano_direct_f3_delivery/` | 第 04 批：固定左手 F3（MIDI 53），lead-in 0.2 s；单通道动作 1、action_scale=80、训练 safety=0.05；新增单音真实边沿验收、PPO 训练/独立评估入口、30 ms 硬时序/终局奖励和 20 ms 观测相位补偿；交付模型 40,960 步 | Jetson Conda/MuJoCo 3.3.7：40,960 策略加 20 ms 观测相位补偿后独立 20/20 通过（on .220 s、off .484 s，onset +20 ms、release -16 ms，mean reward 21.18），随机基线 0/20；全量 70 项测试通过；模型/配置/评估在 `piano_direct_f3_delivery/`，模型 SHA256 `a5bddf00…`；未训练第 05 批 | 未提交 | 观测相位补偿是低层手部延迟校准，不是放宽 30 ms 验收；训练时 lead=0、评估 lead=.02 已写入配置；仅仿真，未做真机 |
| C-20261110-03 | 2026-11-10 01:55 | DeepSeek Harness | feat | `rm_mujoco/piano_direct_reward.py`、`rm_mujoco/piano_direct.py`、`config/piano_direct_env.yaml`、`test/test_piano_direct_reward.py`、`test/test_piano_direct.py`、`CMakeLists.txt`、`docs/piano_direct_rl.md`、本台账 | 第 03 批：新增 `DirectReward`，按真实 MuJoCo 键角/指尖距离/动作/能耗/安全计算 key/finger/timing/energy/action/safety；`PianoDirectEnv.step` 返回物理奖励和独立分量，新增 `reward_details`；配置默认权重；新增 7 项奖励场景测试 | Jetson Conda/MuJoCo 3.3.7：奖励+环境 14/14，全套 62/62；纯函数场景正确 2.2、静止 -1.0、漏按 -2.5、错按 -3.0、持续压住 -1.0、正确但动作/安全违规 -6.37；随机 12 步 env 奖励约 -1.82，分量为 key -1.0、finger 0、timing 0、energy -0.006、action -0.008、safety -0.805；未训练 PPO | 未提交 | 未做 PPO 训练或策略收敛验证；安全投影、机械臂动作仍在后续批次；仅仿真 |
| C-20261110-02 | 2026-11-10 01:20 | DeepSeek Harness | feat | `docs/piano_direct_rl.md`、`docs/piano_rl.md`、`rm_mujoco/pianovam_tasks.py`、`piano_direct.py`、`config/piano_direct_env.yaml`、`scripts/prepare_pianovam_tasks.py`、`scripts/check_piano_direct_env.py`、`test/test_pianovam_tasks.py`、`test/test_piano_direct.py`、`CMakeLists.txt`、本台账 | 第 00–02 批：新增 `piano_rl_tasks/1`（绝对事件时间、相对帧、88 键目标、指法缺失标记）、PianoVAM 窗口生成器和 CLI；新增固定高位双臂、20 维 L20 直接控制 `PianoDirectEnv`（777 维观测、无 plan/PlanRunner/arm/hand tracks、奖励暂为 0）；安装 static5/static_pose_reference/direct config、两个入口和两个测试 | Jetson Conda/MuJoCo 3.3.7：14 项新测试 + 7 项导入回归 + 旧 `test_piano_rl.py` 34/34；真实 PianoVAM TSV 单文件生成 4 个任务；随机 12 步 env（action_scale=8）观测有限、双手/单手动作改变 L20 qpos、固定臂误差约 0.002–0.01 rad、无 other contacts；随机动作仍可能有 1 个轻度过行程，已在 `info.key_violations` 记录，未作为通过证据 | 未提交 | 未训练 PPO、未实现正式奖励/机械臂动作；固定臂只覆盖手附近音符；大动作安全投影留待第 03–06 批；Windows 未运行 MuJoCo |
| C-20261110-01 | 2026-11-10 00:25 | DeepSeek Harness | chore | `.validation/architecture_archive_20261110/`、`.validation/architecture_archive_20261110.tar.gz`、`docs/architecture_archive_20261110.md`、本台账 | 大改架构前冻结：旧 40 音参考与旧计划、PPO 两只老虎模型/回放证据/两套旧接口源码、新静态姿势与场景/三视图/覆盖结果、当前源码与文档快照；生成 393 文件 SHA256 清单和 52.1 MB tar | 静态核对：tar 477 项、MANIFEST 393 文件、关键哈希（旧 plan 0f6c…、PPO best e973…、新姿势 b1ce…）一致；未重新运行旧 PPO/仿真 | 未提交 | 精确 `dual_smoke_seed7` 源码快照缺失，模型不保证重载；归档不改变任何原始文件 |
| C-20261109-29 | 2026-11-09 23:48 | DeepSeek Harness | docs | `docs/static_pose.md`、`config/static_pose_reference.yaml`、`config/piano_scene_static5.yaml`、本台账 | 用户确认静态高肘姿态后，把布局、左右 7 关节角、60% 手型、弹奏前抬手规则和“不得冻结整曲/不得放松验收”的约束写成参考文档；记录当前布局几何预筛 88/88 与手贴键导致肘部只能保持肩高的限制 | 仿真（Jetson MuJoCo 3.3.7）：静态姿态无关节超限；指尖接触键面且键角 0；无桌面/键床/琴体/双臂互碰。当前布局完整 88 键动态覆盖仍在跑，未写成已通过 | 未提交 | 现有演奏规划器尚未强制读取该参考姿态；实际 88 键动态验收以单独报告为准 |
| C-20261109-28 | 2026-11-09 23:00 | DeepSeek Harness | feat | `fingering.py`、`analyze_88_keys.py`、`optimize_88key_layout.py`、`retry_dynamic_failures.py`、`render_key_postures.py`、`render_performance_video.py`、`piano_scene_88key.yaml`、`test_fingering.py`、`CMakeLists.txt`、`docs/piano_88key.md`、本台账 | 增加姿态代价（肘下垂/侧向/后撤、限位裕度、桌面净空）、多初值/零空间 IK、候选评分与连续性；新增 88 键布局预筛、全键 IK/动态验收、失败重试、姿态截图与分屏视频入口；新增 7.5 mm 新布局按键深度和 88 键候选场景 | 进行中：Windows 静态编译；Jetson MuJoCo 3.3.7 上 88 键分析与 40 音重规划运行中，尚未收工 | 未提交 | 待全 88 键覆盖、40 音回归、跨音区/双手测试和视频完成；仅仿真 |
| C-20261109-27 | 2026-11-09 21:30 | Kimi Code | test | 本台账、Jetson `.validation/piano_rl_multisong_stability_20261109/` | 用户要求 Jetson 验证；恢复 T-0019，确认 Conda 依赖和远端工作区，准备独立部署当前源码与测试 | Jetson 只读检查：NumPy 1.26.4、MuJoCo 3.3.7、Gymnasium 1.0.0、SB3 2.4.1、Pytest 8.4.2；未发现续训进程，磁盘约 3.5T 可用 | 未提交 | 部署、专项测试、最小 PPO 闭环及多曲对照待执行 |
| C-20261109-26 | 2026-11-09 21:27 | Kimi Code | feat | `piano_rl.py`、`train_piano_rl.py`、`evaluate_piano_robustness.py`、`test_piano_rl.py`、`docs/piano_rl.md`、本台账 | 新 `piano_shared_hands/3` 增加前臂位置和五时点指法标签；加入逐帧 F1、等 episode/控制步课程、RoboPianist 3×256 PPO 配置和最差任务优先选模；新增 6 项测试及本地 PianoVAM 三种子复现实验说明，旧测试集只作回归 | 静态检查（Windows）：4 个 Python 文件 AST 和 `git diff --check` 通过；本机无 NumPy/MuJoCo/Gymnasium/SB3/Pytest，未运行单元测试、构建、训练或仿真 | 未提交 | T-0019 待 Ubuntu/Conda 运行专项测试和三种子训练；尚未证明泛化或稳定性提升，旧 v2 模型不能直接加载 |
| C-20261109-25 | 2026-11-09 21:16 | Kimi Code | docs | 本台账 | 认领 T-0019：对齐 RoboPianist 多曲目观测与稳定选模，使用本地 PianoVAM 严格数据划分；登记正式 RL 源码、测试、文档和独立新实验目录占用 | 只读核对现有 v5 实现、T-0012 独立对照和 T-0013 占用；旧训练产物不覆盖，Windows 尚未运行仿真 | 未提交 | 实现、针对性测试和 Ubuntu/Conda 复验待执行 |
| C-20261109-24 | 2026-11-09 21:11 | Codex Desktop / y015-40-fix | fix | `verified_40/performance.yaml`、`manifest.json`、`README.md`、`docs/usage.md`、本台账 | 完成 y=0.15 下的原速整曲重标定，调整局部换腕、抬指及击键指令；在正式入口更新计划和两个身份摘要，冻结曲谱不变 | Jetson Conda / MuJoCo 3.3.7：校准场景与工作区默认场景均严格通过 40/40、80 边沿、最大落键/释放/时长误差 20/20/23 ms；零残差 40/40；专项 Pytest 8/8。证据归档 SHA256 通过；本地 51 项冻结身份及 git diff 检查通过 | 未提交 | 仅 MuJoCo。报告 `.validation/piano_y015_40_fix_20261109/formal_verified/playback/report.json` |
| C-20261109-23 | 2026-11-09 20:05 | Codex Desktop / y015-40-fix | docs | 本台账 | 认领 T-0018，接续用户要求修好 40 音 | 只读确认 T-0017 已释放占用，原报告匹配 40 音且严格验收未通过 | 未提交 | 逐段校准并正式整曲复验 |
| C-20261109-22 | 2026-11-09 20:02 | Codex Desktop / y015-recovery | test | 本台账、本地与 Jetson `.validation/piano_y015_recovery_20261109/` | 冻结 y=0.15 及 Kimi 最后初始姿态；修正验证片段前置等待元数据；重定位传统轨迹并局部标定；比较三个旧几何 PPO 最终检查点 | Jetson MuJoCo 3.3.7：PianoVAM 8/8，双手 24/24 原速严格通过，最大落键/释放/时长误差 20/20/22 ms。完整候选匹配 40/40，严格验收失败。独立扰动录音零残差 3/6，PPO 1/6、3/6、3/6；双手 24 音各 0/3，所有无扰动参考及模型通过。原始证据 SHA256 通过；Windows 脚本 AST 和 diff 检查通过 | 未提交 | 40 音仍需解决邻键触发、键角和提前落键，整曲 PPO 对照待有效参考；仿真产物见实验 RESULTS.md |
| C-20261109-21 | 2026-11-09 19:31 | Codex Desktop / y015-recovery | docs | 本台账 | 认领 T-0017；用户确认执行，独立实验目录接续 T-0016 | 只读核对本地 git status、Jetson Kimi 进程和 8 份历史回放；未发现运行中的 Kimi 规划进程 | 未提交 | 在统一 y=0.15 场景复验和配对对照 |
| C-20261109-20 | 2026-11-09 17:24 | Kimi Code | feat | `rm_mujoco/config/piano_scene.yaml`、本台账、`.validation/piano_offset_sweep_20261109/`（Jetson 同名目录） | 应用户要求扫到 0.6 并选位姿最优距离：13 个 y 偏移 × 右手 22 音平腕 IK+接触检查，记录每关节最小/平均余量；按最大化最小余量选定 **y=0.15**（20/22，最差 0.292 rad），已改默认 `piano_frame` y=0.10→0.15、相机 target 同步；0.55 起全音 IK 失败证实臂展边界；渲染 y=0.15 侧视/俯视确认 | 仿真（Jetson MuJoCo 3.3.7，EGL）：286 音次 IK 完成；新默认 YAML 经 Windows load_layout 复核并同步 Jetson，从其渲染两图拉回本地；未跑 colcon/整曲规划/真机 | 未提交 | 60/64 两失败音与距离无关（横向/手姿另行处理）；冻结的 40 音/RL 参考仍待在新默认 y=0.15 下重标定 |
| C-20261109-19 | 2026-11-09 17:02 | Kimi Code | test | 本台账、`.validation/piano_offset_sweep_20261109/`（Jetson 同名目录） | 平腕按压研究：右手 60–81 逐音强制 PLAY_R 平腕 IK + 严格接触检查，扫 piano y=0.00~0.30；结论：0.00→0.20 平腕可弹均为 20/22 且失败音相同（60 拇指跨身 IK 无解、64 小指节蹭 67 键，均与距离无关），y≥0.25 高音 77–81 超伸恶化；默认维持 y=0.10；产出 y=0.00/0.10 对比截图与 note72 平腕按压特写 | 仿真（Jetson MuJoCo 3.3.7，EGL 无头渲染）：7 偏移 × 22 音 IK+接触检查全部完成，20/22 处最小关节余量 0.18–0.29 rad；证据 `flat_wrist_study*.json`、`render/*.png` 已拉回本地 | 未提交 | 两个距离无关的失败音需另行处理：60 用横向手段（基座外移/偏航/换左手），64 调 PRESS_E 小指抬升标定；扫距未跑整曲规划，只验证单音按压几何 |
| C-20261109-18 | 2026-11-09 16:39 | Kimi Code | feat | `rm_mujoco/config/piano_scene.yaml`、本台账、`.validation/piano_offset_sweep_20261109/` | T-0015 MuJoCo 钢琴整体后移：`piano_frame.position` y 0.00→0.10，三个相机 target y 同步 +0.10 保持构图；新增 0.00~0.20 五份扫距变体与 Jetson 跑测 README（默认即 y=0.10） | 静态检查（Windows）：`load_layout`/`key_positions`/`build_model`（含可动键）通过；同侧基座→C4 距离 0.42→0.50 m、→G5 0.34→0.44 m；5 份变体 load_layout 全过；未跑 colcon/仿真/真机 | 未提交 | 与 DeepSeek 的 C-20261109-17 同分钟并行，本条用下一编号；冻结的 verified_40 manifest、尾段 v29、RL 参考与残差模型在新几何下失效，待 Jetson 扫距后重标定；test_two_tigers 哈希检查失败属预期 |
| C-20261109-17 | 2026-11-09 16:39 | DeepSeek Harness | chore | `AGENTS.md`、`docs/piano_rl.md`、`docs/piano_workflow.md`、`docs/usage.md`、`rm_mujoco/` 的 13 个源文件/配置/示例/测试；本台账 | 用户要求“提交并推送”后清点工作区：`2354b80` 收录 17 个文件（+5139/−4），覆盖 T-0004、T-0006～T-0008、T-0010～T-0012 的已登记改动和协作文档；本条只追加台账记录并单独提交，不改任何源码 | 静态检查（Windows）：冻结清单 51/51 文件哈希匹配、7 个新 Python 文件 `py_compile` 通过、暂存区换行均为 `i/lf`；未在 Windows 运行 colcon、MuJoCo 或 pytest，构建与仿真结论仍取 T-0004～T-0012 的 Jetson 记录 | `2354b80`、本条 | 同一操作推送到 `ros2_ws/humble`；T-0013 的后台续训在 Jetson 运行，与本仓库提交无关，源码和实验目录未改动 |
| C-20261109-16 | 2026-11-09 16:30 | Codex Desktop / new-music | test | 新曲实验目录、`docs/piano_rl.md`、本台账 | 审计自动标注并保留连续 8 音完整时序和固定指法；冻结三份 20480 步模型，执行原配置 18 次、独立姿态覆盖 6 次、Home 加时 2 次；记录全部失败并取回证据 | Jetson Conda 实际搜索 26 次，均在规划阶段失败，无完整参考通过，未运行策略迁移或微调；Home 覆盖后推进到第五音仍有后续换腕/角度/误触失败。Windows 两脚本 AST 和 5 项纯数据边界检查通过；127 份证据及压缩包 SHA256 通过；正式 6 个部署文件哈希不变 | 未提交 | T-0014 待验证、占用释放；非双手/整曲/真机通过，不能判断 PPO 泛化。T-0013 在 16:27 仍运行，观察步数 44544/45056/45568，未改训练课程；后续需先获得可行连续参考 |
| C-20261109-15 | 2026-11-09 16:14 | Codex Desktop / new-music | chore | 本台账 | 用户确认后认领 T-0014；核对三首新曲自动指法源及原 train/ext-train/test 划分，固定右手连续 8 音与来源完整性检查；统一使用三种子 20480 步稳定检查点，独立目录评估 | 只读：三首存在含未知标注或延音边界不完整的区域；完整且音域 60–81 的 8 音候选初筛分别 20/34/32。现有三种子已达 24576 步，20480 检查点 ZIP 完整性通过，原训练继续 | 未提交 | 只进行右手声部试验，不宣称双手整曲；参考规划、完整物理验收及策略直接迁移待运行 |
| C-20261109-14 | 2026-11-09 16:00 | Codex Desktop / rl-continue | chore | `docs/piano_rl.md`、本台账；`.validation/piano_rl_continue_20261109/run_continuation.py`、协议、快照、运行状态及日志 | 冻结正式源码和三份最后/最佳模型作为输入，恢复各最后模型权重/优化器，启动可脱离 SSH 的三种子续训；各追加 65536 至 73728，4096 步检查点附配置；完成后冻结哈希并对新旧模型运行新噪声对照 | Windows 仅 AST/diff 检查；Jetson Conda：三组参考与恢复策略的 48 训练音及 1 验证音无扰动回放通过，已进入真实 PPO 采样，累计 10240/10752/10752。独立会话 PID/命令行和心跳已核验；正式 RL 源码未修改，未安装依赖或运行真机 | 未提交 | 长程任务仍在后台运行，最终收敛/物理收益未知；T-0013 待验证，文档释放、实验目录保留占用。3001/3003/3007 在本轮训练前固定，旧测试曲目仅作回归，不能宣称新曲独立验证 |
| C-20261109-13 | 2026-11-09 15:51 | Codex Desktop / rl-continue | chore | 本台账；拟新增续训实验编排脚本 | 用户“继续强化训练”后认领 T-0013，核对三份最后模型真实累计 8192 步、10 次 PPO epoch 计数、rollout 4096，规划每模型追加 65536 步并保留优化器；冻结新噪声测试方案 | 只读：正式远端源码与最终部署清单一致；Conda 依赖版本不变，当前无训练进程、磁盘空闲充足；未启动新训练 | 未提交 | 将创建隔离源码/输入快照和可脱离 SSH 的后台编排，先确认进入实际采样；旧 test 不能再宣称新曲独立证据 |
| C-20261109-12 | 2026-11-09 15:21 | Codex Desktop / rl-generalization | fix | T-0012 占用文件；实验 `RESULTS.md`、`results.json`、`paired_results.csv`、原始报告/动作/MIDI/最终与所选模型 | 修正新门控下默认零偏置缺少训练偏差的问题，默认改为 ±0.5、保留显式 0 对照；六组实验原本均显式 0.5，未改变冻结实验。完成独立配对测试、最终文档、部署哈希核对、证据回收，释放占用 | Jetson Conda：最终版本再次 36/36、构建和安装帮助通过；无扰动均保持参考。独立整曲扰动参考/策略各 0/3；新曲参考 5/6，三策略分别 5/6、5/6、4/6。1472 份证据及六个冻结模型本地 SHA256 校验通过，报告链接检查通过；后台进程为零 | 未提交 | 无可靠学习增益；混合 seed 19 在 Scarlatti/2007 新增 −30.75ms 时长失败，原 30ms 门槛保留。当前基准仍是参考轨迹；未声称整首 PianoVAM、任意曲目或真机能力；完整结果见 `.validation/piano_rl_generalization_20261109/RESULTS.md` |
| C-20261109-11 | 2026-11-09 15:07 | Codex Desktop / rl-generalization | test | T-0012 占用文件及实验目录 | 完成 v5 单曲与混合课程各 3 seed、每模型 8192 步；命名路径备份后部署正式远端源码，与本地和已测快照 SHA256 一致；独立测试前冻结所有最佳模型哈希 | Jetson Conda：六组退出 0，最后/所选策略均通过全部训练及验证无扰动验收；单曲各 5 回合、40/40，混合每片段至少 3 回合且 48 音全覆盖、独立验证 1/1。专项 CTest 28+8 全过；首次 ROS 插件误收集失败及隔离后成功日志均保留 | 未提交 | 同曲 seed 7/11 与混合 seed 7 选中第 0 步；开发扰动尚有失败。独立测试自动运行中，不据此提前声称泛化或鲁棒性收益 |
| C-20261109-10 | 2026-11-09 14:51 | Codex Desktop / rl-generalization | fix | T-0012 占用的 RL 环境、训练/鲁棒性/数据准备入口、专项测试、CMake、RL 文档；`.validation/piano_rl_generalization_20261109/` | 全课程首轮采样、20 动作/1281 观测共享接口、指法时钟、时序及安全代价、无真值偏置的名义状态反馈门控、训练参考示范回放、三阶段来源/曲目隔离与完整片段边界检查；保留旧源码快照及所有拒绝样本 | Jetson Conda：36 项专项测试通过；隔离 rm_mujoco 构建通过，安装入口原速 40/40。严格数据为 5 train / 1 valid / 2 test；验证 Bb4 经现有标定器和原完整验收器通过。v4 单曲 4096 步覆盖全部 40 音但末轮仍失败，故继续 v5 | 未提交 | v5 同曲与跨录音三种子训练进行中，测试噪声种子冻结为 2001/2003/2007；尚未声称学习增益、任意曲谱能力或真机通过 |
| C-20261109-09 | 2026-11-09 13:59 | Codex Desktop / rl-generalization | docs | 本台账 | 用户确认后认领 T-0012；完整读取当前实现、测试和文档，登记文件占用，保留所有未提交内容 | 只读诊断：512 步仅 10.24s；事件 28 在 20.816s；基线/末轮时长误差分别 -25/-31ms；人工 GT 数据为 train 6、ext-train 2、valid 1、test 2 | 未提交 | 实现、回归和独立实验待执行；发现旧 C-20261109-08 编号重复，原条目保持不动 |
| C-20261109-08 | 2026-11-09 13:49 | Codex Desktop / effect-demo | test | 本台账；`.validation/kimi_effect_demo_20261109/show_kimi.py` 与 `replay/` | 严格核对冻结资源和训练源码哈希，重新加载 Kimi 两个模型回放；记录完整 qpos、动作、原始验收报告和 MIDI，生成并取回双栏原速视频，声音由左侧实际键事件合成 | 仿真（Jetson Conda / MuJoCo 3.3.7）：选中模型 `passed=true`、40/40、落键/释放最大 30/18ms；最后模型 `passed=false`、40 音匹配且事件 28 时长短 31ms（容差 30ms）。视频 H.264/AAC、1280×720、25fps、807 帧、32.28 秒；完整解码、两处画面检查和本地 SHA256 一致 | 未提交 | 展示的是选中零残差基线和最后 512 步模型；不代表 RL 提升、跨曲泛化或真机；视频 `replay/kimi_dual_comparison.mp4` |
| C-20261109-08 | 2026-11-09 13:48 | DeepSeek Harness | feat | `.gitattributes`、`rm_mujoco/CMakeLists.txt`、`rm_mujoco/config/right_hand_piano_sim.yaml`、`rm_mujoco/config/right_tail_v29.yaml`、`rm_mujoco/rm_mujoco/fingering.py`、`rm_mujoco/scripts/verify_right_tail.py`、`rm_mujoco/test/test_fingering.py`、`rm_mujoco/test/test_right_tail.py`、`QWEN.md` | 提交并推送 C-20261108-02/-03 的内容：`6a26b39` 尾段功能（8 文件，+480/−10）；`b3ebdb6` 删除 `QWEN.md`。`CMakeLists.txt` 只提交 `right_tail` 三行，RL 相关行留在工作区 | 远端已更新：`ros2_ws/humble` 由 `b7e368c` 推到 `b3ebdb6` | `6a26b39`、`b3ebdb6` | 他人未提交改动（RL、two_tigers、docs）保持原样；台账期间由 Codex Desktop 占用，本条为追加记录 |
| C-20261109-07 | 2026-11-09 13:42 | Codex Desktop / effect-demo | docs | 本台账 | 认领 T-0011；核对 Kimi 已释放占用及远端真实目录（fix 工作区的 `src/src/ros2_rm_robot/rm_mujoco`） | 只读检查最新源码、summary 和 config；已确认选模保留第 0 步、512 步模型有 1 个 duration 异常 | 未提交 | 本次实时复验及视频待生成 |
| C-20261109-06 | 2026-11-09 12:47 | Kimi Code | fix | `rm_mujoco/CMakeLists.txt`、`scripts/verify_two_tigers.py`、`scripts/evaluate_piano_robustness.py`、`docs/piano_rl.md`、`docs/usage.md`、`verified_40/README.md`、本台账 | 接管并保留 Codex 的 `piano_residual/3` 双手、事件奖励、零残差与物理选模实现；安装两个新入口、冻结资源和清单所需 Python 文件，注册 `two_tigers`；修复安装后的包路径解析，同步文档与验证边界 | Jetson Conda / ROS 2 Humble：`rm_mujoco` 构建通过；直接 Pytest 25/25，`piano_rl` + `two_tigers` CTest 25/25；安装入口 40/40，最大落键/释放误差 30/18 ms；真实 PPO 512 步参考与选中模型 40/40，最后模型事件 28 时长短 1 ms，按设计退出 2，选模保留第 0 步；安装鲁棒性入口无扰动 40/40，bias=0.5/seed=101 时参考和零残差均 39/40（漏音 1、timing 1、duration 2） | 未提交 | 只证明同曲 MuJoCo 工程闭环；训练未优于参考、未获得扰动鲁棒性，未做全包测试或真机验证；证据在远端 `.validation/kimi_rl_formal_20261109/` |
| C-20261109-05 | 2026-11-09 08:46 | Codex Desktop / rl-followup | docs | 本台账 | 用户确认后接管 Kimi 的 RL 路径，登记 T-0009；核对远端正式源码与本地五个文件哈希一致。Kimi 六组 4096 步对照已完成、训练验收全部失败，独立验证均 3/3；原 `unexpected` 包含 timing/duration，不全是额外音 | 只读核验 Jetson 原始 summary/report 及测试 XML：RL 专项 6/6；全包另有 model_stability 失败、fingering 超时；本轮尚未修改 RL 或重跑测试 | 未提交 | 继续诊断与最小修复；原实验目录保持原样 |
| C-20261109-04 | 2026-11-09 08:42 | Codex Desktop / 40-note | feat | `scripts/verify_two_tigers.py`、`test/test_two_tigers.py`、`examples/two_tigers_flat_palms/verified_40/`、`docs/usage.md`、本台账 | 合入冻结 40 音曲谱、完整双手动作参数计划、51 文件身份清单、源码复验入口、输入检查测试和说明；保护旧输出，保留原模型/指法/运行时代码；旧候选搜索结果已展开到完整计划 | 静态 diff 检查；Jetson Ubuntu 22.04 / MuJoCo 3.3.7：Pytest 8/8；正式入口联合回放 40/40，最大落键 30 ms、释放 18 ms，无错指、角度违规、缺音、多余音或残留；证据 `formal40_merged/` | 未提交 | 固定曲目标定回放；未声称任意曲谱自动规划或真机通过；源码调用，未改他人占用的 CMake/RL |
| C-20261109-03 | 2026-11-09 06:36 | Kimi Code | test | `docs/ai_worklog.md`、远端 `.validation/kimi_piano_rl_20261109/ppo_16k_seed7/` | 完成 P0 残差 PPO 首轮 16,384 步训练，保存模型、4 个 checkpoint、progress 与 summary；未改本地 T-0005 源文件 | 仿真（Jetson Conda）：训练 11 音参考 11/11、回报 111.178；学习后 10/11、漏按/误触各 1、角度违规 1、回报 98.950；独立验证 3 音学习后 3/3、无漏按/误触、回报 98.553 | 未提交 | 首轮训练未优于参考；尚无 RoboPianist 指尖距离与能耗奖励；仅 MuJoCo，未做真机验证 |
| C-20261109-02 | 2026-11-09 03:31 | Kimi Code | docs | `docs/ai_worklog.md`、远端 `.validation/kimi_piano_rl_20261109/` | 用户要求转 RL；登记 T-0006。只读使用 T-0005 代码，在 Jetson Conda `piano_rl` 复制 PianoVAM `Fingering_GT/Fingering` 数据，生成训练 11 音与独立验证 3 音参考计划、metadata/manifest；1-step PPO 闭环通过，16k PPO 首轮训练中 | 仿真（Jetson Conda）：3 音 smoke `passed=True`；训练 11 音零动作基线 `passed=True`（11/11）；1-step 训练/评估闭环通过 | 未提交 | 正式 16k 训练未结束；不改 T-0005 占用源文件 |
| C-20261109-01 | 2026-11-09 02:47 | Codex Desktop / piano-rl | docs | `docs/ai_worklog.md` | 认领 T-0005 与文件；登记用户确认的 Conda 安装、仿真训练范围 | 静态检查：已读 AGENTS、台账及 git status，现有改动有记录 | 未提交 | 安装、实现、测试和训练待执行 |
| C-20261108-03 | 2026-11-08 22:34 | DeepSeek Harness | feat | `rm_mujoco/config/right_tail_v29.yaml`、`rm_mujoco/scripts/verify_right_tail.py`、`rm_mujoco/test/test_right_tail.py`、`rm_mujoco/CMakeLists.txt`、`.gitattributes` | 新增右手尾段标定（事件 33–40，lift 30，逐事件 leads 与预备时序）、无 monkey patch 的复现工具、5 个回归用例；CMake 安装配置与脚本并注册 `right_tail`；脚本加 `eol=lf` | 单元测试 + 仿真（Jetson，Ubuntu 22.04 / ROS 2 Humble）：`colcon test --packages-select rm_mujoco --ctest-args -R right_tail` 5/5 通过；`PlanRunner` MuJoCo 回放 `passed=True`，6 音全中、无漏音/多余音/压键残留 | 未提交 | 仅右手、仅仿真；真机未验证 |
| C-20261108-02 | 2026-11-08 22:30 | DeepSeek Harness | chore | `QWEN.md` | 按用户要求删除旧入口文件（101 行），内容已由 `AGENTS.md` 与本台账覆盖 | 静态检查：全仓库无引用、无断链 | 未提交 | 需要时用 `git checkout -- QWEN.md` 恢复 |
| C-20261108-01 | 2026-11-08 22:25 | DeepSeek Harness | docs | `docs/ai_worklog.md`（新建）、`AGENTS.md` | 建立 AI 协作台账；`AGENTS.md` 顶部增加「AI 协作（必读）」入口 | 静态检查 | 未提交 | 未提交前请勿把他人的改动一起带进 commit |

## 7. 交接与阻塞

状态取值：待处理 / 已回复 / 已解决。

| 时间 | 来自 | 给谁 | 内容 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-11-09 09:01 | Codex Desktop / 40-note RL takeover | 所有 AI | 用户授权本聊天接管另一对话的 RL 工作；另一对话已中断。T-0009 的 event reward、零动作初始化、失败退出及测试保留并验证；旧占用行作为历史，当前占用以上方本次记录为准。后续按奖励诊断→双手→扰动对照执行 | 已回复 |
| 2026-11-09 08:46 | Codex Desktop / rl-followup | Kimi Code、所有 AI | 用户明确回复“执行”，确认接管 Kimi 的 RL 文件占用并续接 T-0007/T-0008。旧行不改写；T-0009 记录当前工作，原始六组实验与模型只读保留。开工 git status 中所有现有改动均按原样保留，新增 RL 文件及测试来自 Kimi 已验证工程 | 已回复 |
| 2026-11-09 08:38 | Codex Desktop / 40-note | 所有 AI | 用户回复“kimi 释放”，据此接续本聊天合并授权。旧台账占用行保留作为历史；本次仅追加自身记录，不解除或修改 RL/CMake 占用。双手完整 40 音已联合通过，证据 `.validation/dual_two_tigers_1x_20261108/dual_full_v40/playback/report.json`，现合入可复验基准 | 已回复 |
| 2026-11-09 06:43 | Kimi Code | Codex Desktop / piano-rl | 用户进一步明确“强化学习落成正式工程”，已登记 T-0008。请释放或交接 T-0005 的 `piano_rl.py`、训练入口、测试、CMake 与 RL 文档；Kimi 将在独立副本完成奖励验证和对照后合入，未释放前不改这些正式文件 | 待处理 |
| 2026-11-09 06:36 | Kimi Code | Codex Desktop / piano-rl、所有 AI | T-0006 首轮 16k PPO 已完成但未优于参考：训练 11 音学习后 10/11 且有 1 个角度违规，独立验证 3 音保持 3/3。下一轮不建议直接加步数，应先补 RoboPianist 式主动指尖距离与力矩能耗奖励并做短步数对照；正式合入仍需 T-0005 文件交接 | 待处理 |
| 2026-11-09 03:31 | Kimi Code | Codex Desktop / piano-rl、所有 AI | 用户要求先停整曲衔接并转 RL；因 T-0005 已占用，Kimi 只在远端 `.validation/kimi_piano_rl_20261109/` 做 Conda 独立验证，不修改本地 T-0005 源文件。若需合并实现，请先交接占用 | 待处理 |
| 2026-11-09 02:40 | Codex Desktop / 40-note | 所有 AI | 只读核对发现 `fingering.py` 开工前还已有 `_plan_hand(initial_beam, group_offset)` 修改（文件时间 2026-11-08 21:00），原台账未单列；保留原样，本轮连续诊断直接继承 MuJoCo checkpoint，不依赖该新增入口 | 待处理 |
| 2026-11-09 02:20 | Codex Desktop / 40-note | 所有 AI | 确认 T-0002 登记的 `fingering.py` 抬指/预备动作和 `test_fingering.py` 两个对应测试源于本聊天上一轮；当前文件含其他新增测试与配置，继续保留，不回滚。Jetson 连接现已恢复；复用 T-0003 尾段工具，仅继续整曲衔接 | 已回复 |
| 2026-11-08 22:25 | DeepSeek Harness | Qwen Code | `QWEN.md` 在工作区处于已删除状态（`D QWEN.md`）。是否恢复待用户确认，在此之前按 `AGENTS.md` 与本台账工作；2026-11-08 22:30 用户确认删除，保持现状 | 已解决 |
| 2026-11-08 22:25 | DeepSeek Harness | 所有 AI | 台账首版已建立。请按第 1 节认领任务、登记占用、补修改记录 | 待处理 |

## 8. 当前快照

采样时间 2026-11-09 21:27（T-0019 收工时重新采样 `git status --short`）。当前工作区六个改动均属于本轮 T-0019，占用已释放：

| 路径 | 状态 | 说明 | 认领 |
| --- | --- | --- | --- |
| `docs/ai_worklog.md` | 已修改 | T-0019 认领、验证边界与收工记录 | Kimi Code |
| `docs/piano_rl.md` | 已修改 | 新接口、F1、课程平衡、RoboPianist 配置及三种子命令 | Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/rm_mujoco/piano_rl.py` | 已修改 | 1337 维观测、逐帧计数和等步数课程 | Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py` | 已修改 | F1 输出、PPO 配置、最差任务选模和覆盖统计 | Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/scripts/evaluate_piano_robustness.py` | 已修改 | 配对评估入口说明 | Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/test/test_piano_rl.py` | 已修改 | 6 项新回归测试，尚未在 Ubuntu/Conda 执行 | Kimi Code |

本轮未创建 `.validation/piano_rl_multisong_stability_20261109/` 训练输出；已有实验目录均未修改。`.validation/` 默认被 git 忽略，引用时须写清子目录名。

## 9. 附录：编号与维护

- 记录号格式 `C-YYYYMMDD-NN`，按天递增，不复用；任务号格式 `T-NNNN`，四位递增。
- 本文件自身的改动同样要写进「修改记录」，否则下一个 AI 会以为表格是自动生成的。
- 本台账只解决「谁在做什么、做过什么」，不替代 `docs/usage.md`、`docs/piano_workflow.md`、`docs/speed_test.md`；行为改动仍要同步更新对应文档。
- 表格超过 200 行时把已完成的修改记录归档到 `docs/ai_worklog_archive.md`，本文件只留最近的部分。
