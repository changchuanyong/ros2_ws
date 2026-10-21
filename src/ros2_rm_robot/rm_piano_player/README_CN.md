# RM75-6FB-V 双臂双 L20 MIDI 钢琴播放器

该功能包实现 RoboPianist 风格的第一阶段实机链路：88 键 MIDI 曲目、左右 RM75 MoveIt 规划、左右 L20 手指命令和数字钢琴 MIDI 反馈。官方 RoboPianist 的 Shadow Hand RL 策略不直接适用于 RM75+L20，本包先实现固定 MIDI 曲目播放。

## 构建

本包已进入默认构建。`rm_l20_driver` 已将 L20-11 RS485 协议和 ROS 节点移入本仓库，无需安装或 source 外部灵心巧手 SDK。仍需基础 Python 通信库和 MIDI 库；版本记录在工作空间的 `src/ros2_rm_robot/requirements-hardware.txt`。

在 Ubuntu 22.04 / ROS 2 Humble 的新终端中，从工作空间根目录执行：

```bash
source /opt/ros/humble/setup.bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
```

清单包含 `pymodbus`、`pyserial`、`numpy`、`mido` 和 `python-rtmidi`。ROS 包依赖由各包的 `package.xml` 声明；MIDI Python 包通过上述清单安装。

## MuJoCo 双臂双手播放

先使用干运行检查 MIDI 文件、左右分配和坐标：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid \
  headless:=true use_rviz:=false execute:=false
```

确认坐标后再执行；`tempo_scale` 是时间倍率，数值越大播放越慢：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid \
  execute:=true tempo_scale:=2.0
```

第一阶段按 MIDI 音域分配：`21–59` 为左手，`60–108` 为右手；每只手同时只允许一个音符。同手和弦会在执行前被拒绝。

## 双臂双手真机

真机入口启动本仓库 `rm_l20_driver` 的两个 `l20_rs485_driver` 节点，默认 `hand_joint=L20-11`，只保留 L20 RS485 通信；仿真入口仍使用原有命令桥。仅查看参数、无需连接硬件时使用：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py --show-args
```

下列启动命令会连接双臂和两个串口，`execute=false` 只禁用播放器动作，不能作为离线检查：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_hand_port:=/dev/ttyUSB0 right_hand_port:=/dev/ttyUSB1 \
  hand_joint:=L20-11 execute:=false
```

确认左右手状态、双臂控制器和 MIDI 输入后，再将 `execute` 改为 `true`，并保持较慢的 `tempo_scale`。数字钢琴 MIDI 输入端口通过 `midi_input:=<port-name>` 指定，并用 `feedback_enabled:=true` 开启漏键、错键和超时检查：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid midi_input:=<port-name> \
  feedback_enabled:=true execute:=true tempo_scale:=4.0
```

## 配置与安全

- `config/piano_midi.yaml` 保存琴键坐标、`piano_frame`、按压深度、速度和 L20 开手姿态。
- `piano_frame` 已加入双臂 URDF；琴键坐标必须根据实际钢琴位置重新标定。
- L20 命令话题使用 20 个 `position` 值，范围 `0–255`。
- 真机左右手命令话题为 `/cb_left_hand_control_cmd`、`/cb_right_hand_control_cmd`，状态话题为 `/cb_left_hand_state`、`/cb_right_hand_state`，均使用 `sensor_msgs/msg/JointState`。
- MIDI 反馈状态发布在 `/robopianist/feedback_status`，包含期望音符、实际音符和 `time_error_sec`。
- 默认 `execute=false`，先完成 MuJoCo 干运行和单键验证，再接触真机。
- 当前 MuJoCo 场景包含 88 键几何模型，但尚未实现 RoboPianist 的琴键接触奖励和力反馈。

真机按以下顺序验收：左手 `/dev/ttyUSB0` 单独通信 → 右手 `/dev/ttyUSB1` 单独通信 → 检查 `/cb_left_hand_state` 和 `/cb_right_hand_state` → 双臂单键接近 → 双手单音阶 → 低速 MIDI 曲目 → 开启 MIDI 反馈。出现漏键、错键或超时后，播放器会停止后续动作；机械臂工作范围内不得有人，并保留急停可达。

## Jetson 验证记录（2026-10-21）

验证环境为 Ubuntu 22.04 / ARM64 / ROS 2 Humble，工作目录为
`/home/dianjinglab/ros2_ws_rm75_02d70d1`。原 `/home/dianjinglab/ros2_ws` 保留。

- `rm_description`、`rm_75_config`、`rm_mujoco`、`rm_piano_player` 构建通过；
  `colcon test-result --verbose` 返回 `16 tests, 0 errors, 0 failures, 0 skipped`。
  按项目要求，仅未声明许可的 `rm_description` 版权检查不参与测试。
- 无头仿真中五个控制器全部为 `active`，`/joint_states` 包含 56 个关节。
  双臂、双手的四个 `FollowJointTrajectory` 动作均返回 `error_code=0`；
  左右手 20 值命令均转换为 21 关节轨迹，检查期间没有仿真时钟重置。
- 默认 YAML 下双手 MIDI 干运行通过，同手和弦被拒绝。
  新增模型稳定性测试运行 5 秒；另完成 10 秒双手全范围平滑往返检查。
  MIDI 反馈节点测试使用假 MIDI 端口，仅验证初始化和事件处理，不代表硬件反馈通过。
- 两个 Python 节点在 SIGINT 后正常退出。系统安装的 `move_group` 曾在退出时出现
  `rclcpp::CallbackGroup` 析构段错误，该系统组件的退出问题仍需单独定位。

原始日志保存在该远端目录的 `.validation/`：`final_test_result.log`、
`simulation_motion_check.log`、`simulation_runtime_fixed.log` 和 `clean_shutdown.json`。
后续已完成原有 9 个包的 Jetson 全量编译和基础通信/MIDI Python 依赖检查；
上述 `16 tests` 只对应此前四个包的测试，不代表本次 L20 驱动移植通过验证。
本次 L20 驱动移植在仅加载 Humble 的环境中完成全部 10 个包构建；新终端中
外部 `linker_hand_ros2_sdk` 的 ROS 包和 Python 模块均不可见，仓内驱动可导入。
`rm_l20_driver` 的 94 项测试全部通过，包含假 Modbus 客户端、实际 ROS 通信和
真实 pymodbus/pyserial 经 Linux 虚拟串口的往返测试；本包原有 2 项 MIDI 测试再次通过。
日志：`.validation/l20_standalone_build_20261021_141053.log` 和
`.validation/l20_standalone_tests_20261021_141459.log`。
本次未启动真机或验证数字钢琴反馈，也未验证完整 MIDI 曲目的 MoveIt 按键执行。
