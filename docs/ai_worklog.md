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
| Kimi Code | Windows 编辑 + Jetson Conda / MuJoCo | 双手残差 PPO 正式化、安装入口与仿真验收 | 2026-11-09 12:46 | T-0010 收尾；25 项专项测试、安装版 40 音及 512 步训练闭环已验证，仅仿真 |
| DeepSeek Harness | Windows 编辑 + Jetson 验证 | 文档、协作台账、`rm_mujoco` 右手尾段、提交与推送 | 2026-11-09 16:39 | 2026-11-08 建立本台账并拉回右手尾段 v29；2026-11-09 按用户要求提交并推送钢琴 RL 与双手 40 音改动（`2354b80`） |

## 4. 任务看板

状态取值：待办 / 进行中 / 待验证 / 完成 / 阻塞 / 已搁置。

| 任务号 | 任务 | 负责人 | 状态 | 涉及文件 / 包 | 开始 | 最近更新 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-0015 | MuJoCo 钢琴整体后移，扩大机械臂工作空间 | Kimi Code | 进行中 | `src/ros2_rm_robot/rm_mujoco/config/piano_scene.yaml`、本台账、`.validation/piano_offset_sweep_20261109/` | 2026-11-09 16:39 | 2026-11-09 16:39 | 用户确认"远离"：piano_frame y 0.00→0.10，附 0.00~0.20 扫距变体与 Jetson 跑测说明；冻结的 40 音清单/尾段/RL 参考在新几何下需重标定 |
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

采样时间 2026-11-09 12:44，命令 `git status --porcelain`。本节允许整体替换：任何 AI 开工时重新采样后覆盖下表，不算改写他人条目；知道来源的行请把「认领」改成自己的名字，并在「修改记录」补条目。

| 路径 | 状态 | 说明 | 认领 |
| --- | --- | --- | --- |
| `AGENTS.md` | 已修改 | 项目结构、钢琴流水线、构建测试、环境边界与 AI 协作入口 | DeepSeek Harness |
| `.gitattributes` | 已修改 | 为 `verify_right_tail.py` 增加 `eol=lf` | DeepSeek Harness |
| `QWEN.md` | 已删除 | 旧入口文件，用户确认删除（C-20261108-02） | DeepSeek Harness |
| `docs/ai_worklog.md` | 新增（未跟踪） | AI 协作台账；最新进展见任务看板和修改记录 | 多 AI（见台账） |
| `docs/piano_rl.md` | 新增（未跟踪） | 残差 PPO 环境、训练、选模、安装入口和验证记录 | Codex Desktop、Kimi Code |
| `docs/piano_workflow.md` | 已修改 | 既有钢琴流程改动，原样保留 | 既有未提交改动 |
| `docs/usage.md` | 已修改 | 双手 40 音连续规划及源码/安装复验说明 | Codex Desktop / 40-note、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/CMakeLists.txt` | 已修改 | 尾段、RL、40 音资源与专项测试安装注册 | DeepSeek Harness、Codex Desktop、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/config/piano_rl_environment.yaml` | 新增 | Conda RL 环境配置 | Codex Desktop / piano-rl |
| `src/ros2_rm_robot/rm_mujoco/config/right_hand_piano_sim.yaml` | 已修改 | 右手仿真参数与连续规划配置 | Codex Desktop / 40-note |
| `src/ros2_rm_robot/rm_mujoco/config/right_tail_v29.yaml` | 新增 | 右手尾段标定：two_tigers 右手事件 33–40 | DeepSeek Harness |
| `src/ros2_rm_robot/rm_mujoco/examples/two_tigers_flat_palms/verified_40/` | 新增 | 冻结 40 音曲谱、计划、身份清单与复验说明 | Codex Desktop / 40-note、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/rm_mujoco/fingering.py` | 已修改 | 抬指、预备动作与连续规划 | Codex Desktop / 40-note |
| `src/ros2_rm_robot/rm_mujoco/rm_mujoco/piano_rl.py` | 新增 | 单/双手残差环境、事件奖励与 RoboPianist 式奖励 | Codex Desktop、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/scripts/evaluate_piano_robustness.py` | 新增 | 同曲配对扰动评估及安装入口 | Codex Desktop、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/scripts/train_piano_rl.py` | 新增 | 训练、评估、物理选模与 manifest 校验入口 | Codex Desktop、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/scripts/verify_right_tail.py` | 新增 | 用生产调度器复现右手尾段 | DeepSeek Harness |
| `src/ros2_rm_robot/rm_mujoco/scripts/verify_two_tigers.py` | 新增 | 冻结 40 音源码/安装复验入口 | Codex Desktop / 40-note、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/test/test_fingering.py` | 已修改 | 抬指、预备态与连续规划测试 | Codex Desktop / 40-note |
| `src/ros2_rm_robot/rm_mujoco/test/test_piano_rl.py` | 新增 | 17 项 RL 单元与 MuJoCo 测试 | Codex Desktop、Kimi Code |
| `src/ros2_rm_robot/rm_mujoco/test/test_right_tail.py` | 新增 | 尾段回归测试，由 CMake 注册为 `right_tail` | DeepSeek Harness |
| `src/ros2_rm_robot/rm_mujoco/test/test_two_tigers.py` | 新增 | 8 项冻结输入检查，由 CMake 注册为 `two_tigers` | Codex Desktop / 40-note |

2026-11-09 16:39 提交并推送后（`2354b80` 与随后记录本条 C-20261109-17 的台账提交），上表条目全部进入历史；此后 `git status` 只应显示本台账自身的改动。

`.validation/` 是被 git 忽略的实验产物目录，引用它时写清子目录名。Kimi 的 RL 实验产物位于 Jetson 远端 `.validation/kimi_piano_rl_20261109/`、`.validation/kimi_piano_rl_reward_20261109/` 和 `.validation/kimi_rl_formal_20261109/`。

## 9. 附录：编号与维护

- 记录号格式 `C-YYYYMMDD-NN`，按天递增，不复用；任务号格式 `T-NNNN`，四位递增。
- 本文件自身的改动同样要写进「修改记录」，否则下一个 AI 会以为表格是自动生成的。
- 本台账只解决「谁在做什么、做过什么」，不替代 `docs/usage.md`、`docs/piano_workflow.md`、`docs/speed_test.md`；行为改动仍要同步更新对应文档。
- 表格超过 200 行时把已完成的修改记录归档到 `docs/ai_worklog_archive.md`，本文件只留最近的部分。
