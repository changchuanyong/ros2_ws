# Repository Guidelines

## AI 协作（必读）

多个 AI 会在同一工作区并行修改。开工前先读 [AI 协作台账](docs/ai_worklog.md)，按其中的协议认领任务与文件，再动手。

- 开工：在台账「任务看板」认领任务、在「文件占用表」登记要改的路径；同一文件同一时间只允许一个 AI 修改。
- 收工：在「修改记录」追加一行，写清文件、改动和验证程度（静态检查 / 单元测试 / 仿真 / 真机 / 未验证），然后释放占用。
- `git status` 有变动但台账没有对应记录，视为漏记录；不要覆盖其他 AI 未登记的改动。
- 台账只追加，不改写其他 AI 的条目；进度以台账为准，不要另建临时进度文件。

## 项目结构

本仓库是 ROS 2 工作空间，所有功能包源码放在 `src/ros2_rm_robot/` 下，构建目标是 RM75-6FB-V 双臂、L20 双手和 MIDI 钢琴演奏。

进入默认构建的功能包：

| 功能包 | 职责 |
| --- | --- |
| `rm_ros_interfaces` | 控制/状态消息与服务 |
| `rm_description` | URDF/xacro 模型、mesh 与关节状态 |
| `rm_moveit2` / `rm_moveit2_config`（含 `rm_75_config`） | MoveIt 2 示例与 RM75 配置 |
| `rm_driver` / `rm_control` / `rm_bringup` | 真机驱动、轨迹转发与启动入口 |
| `rm_mujoco` | 双臂双手 MuJoCo 场景、控制器与钢琴仿真工具 |
| `rm_piano_player` | 演奏、MIDI 输入、传感记录与测速 |
| `rm_l20_driver` | L20 RS485 驱动、身份识别与 GUI，构建类型为 `ament_python` |

`COLCON_IGNORE` 排除：`rm_gazebo`、`rm_example`、`rm_arm_examples`、`rm_install`、`rm_doc`，以及 `rm_description/model_sources/rm_models/RM75/urdf/RM75-6FB-V`。其他型号源码保留但不进入构建；L20 MuJoCo 资源由 `rm_mujoco` 自带。增删功能包时同步更新本清单。

## 钢琴流水线

- 仿真与数据脚本位于 `rm_mujoco/scripts/`：`pig_score.py`、`plan_performance.py`、`run_performance.py`、`import_pianovam.py`、`select_pianovam_window.py`、`calibrate_piano_chord.py`、`l20_dual_command_bridge.py`；运行时代码位于 `rm_mujoco/rm_mujoco/`。
- 场景与参数：模型在 `rm_mujoco/models/`（`rm_75_6fb_v_dual_l20.xml`、`piano_keyboard.xml`），参数在 `rm_mujoco/config/`（`piano_scene.yaml`、`right_hand_piano_sim.yaml`）。
- 真机演奏、MIDI 录制与测速在 `rm_piano_player`，姿态与 MIDI 参数在 `rm_piano_player/config/`。
- 文档入口：`docs/usage.md`（环境、仿真、真机、验证记录）、`docs/piano_workflow.md`（演奏与录制流程）、`docs/speed_test.md`（MIDI 测速）。改动相关行为时同步更新对应文档。
- 实验产物放在 `.validation/`，该目录默认被 `.gitignore` 忽略；录制输出默认在 `~/l20_recordings/`。大体积模型、视频和 MIDI 结果不要提交进仓库。

## 构建、测试与运行

使用 Ubuntu 22.04、ROS 2 Humble 和 Bash。在工作空间根目录执行：

```bash
source /opt/ros/humble/setup.bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
colcon test
colcon test-result --verbose
```

`requirements-hardware.txt` 只在首次搭建或硬件依赖变更时安装。只改动 `rm_mujoco` 时用 `colcon test --packages-select rm_mujoco` 缩短反馈；其中 `model_stability` 与 `fingering` 的超时为 180 秒，其余为 60 秒。

使用 `ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py` 启动 RM75-6FB-V 双臂双 L20 MuJoCo、MoveIt 和 RViz；Gazebo 已从当前构建路径排除。

## 环境边界

本仓库当前在 Windows 上检出，只用于编辑与阅读，无法运行 `colcon`、ROS 2 或 MuJoCo。构建、测试和仿真必须在 Ubuntu 22.04 环境执行；在 Windows 上只做了静态检查时，不得声称构建或测试通过。

## 编码风格与命名

遵循现有 C++ `rclcpp` 和 Python `rclpy` 风格。Python 使用四个空格缩进，C++ 使用项目已有格式；Python 标识符采用 `snake_case`，功能包和节点使用清晰名称。ROS 启动文件必须使用 `*.launch.py` 后缀，功能包名称使用小写下划线格式，并保留既有的 `rm_*` 前缀。URDF/xacro、YAML 和双语注释应与相邻文件保持一致，不要格式化无关代码。

## 测试规范

Python 测试放在各功能包的 `test/` 目录中，并使用 `test_*.py` 命名。以 `package.xml` 声明为准，ROS 功能包使用 `ament_lint_auto`，或使用 `ament_flake8`、`ament_pep257` 与 Pytest。为修改的行为添加针对性测试；仅完成仿真运行时，不得声称已通过真机验证。

## 提交与 Pull Request

提交标题应简洁、使用祈使语气，并遵循仓库已有前缀，例如 `feat:`、`chore:` 或 `fix:`。Pull Request 应说明受影响的功能包，关联相关 issue，列出执行过的构建和测试命令，并注明验证使用的是仿真还是真机。GUI、启动流程或仿真行为发生变化时，应附截图或日志。

## 安全与配置

启动真机前检查 `rm_driver/config` 中的 IP 设置，并确认目标机械臂与配置地址一致。启动文件应先在仿真环境中测试；机械臂工作范围内不得有人；L20 仿真使用 `rm_mujoco` 内置模型；提交改动时保留已有未提交内容。
