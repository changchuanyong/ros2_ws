# RM75-6FB-V 双臂双 L20 钢琴工程

本仓库是 ROS 2 工作空间，面向双 RM75-6FB-V 机械臂、双 L20 灵巧手和 88 键 MIDI 数字钢琴。开发环境为 Ubuntu 22.04 / ROS 2 Humble，包含 MuJoCo 仿真、MoveIt 2 / RViz 双臂规划、仓内 L20 RS485 驱动和固定 MIDI 曲目播放器。

当前 MuJoCo 场景参照实验室照片：两台机械臂直立安装在木桌上，双手指尖向下，面对木色电钢琴。场景与控制器已完成 Jetson 验证；完整曲目演奏、真机运动和真实钢琴 MIDI 反馈尚未验收。

## 工程结构

源码位于 `src/ros2_rm_robot/`，在本 README 所在的工作空间根目录构建。

| 功能包 | 源码位置 | 用途 |
| --- | --- | --- |
| `rm_description` | [rm_description](src/ros2_rm_robot/rm_description/) | RM75-6FB-V 网格、URDF 和双臂描述 |
| `rm_75_config` | [rm_moveit2_config/rm_75_config](src/ros2_rm_robot/rm_moveit2_config/rm_75_config/) | `left_arm`、`right_arm`、`dual_arms` 的 MoveIt 配置 |
| `rm_mujoco` | [rm_mujoco](src/ros2_rm_robot/rm_mujoco/) | 双臂双手模型、桌琴场景、仿真控制器 |
| `rm_driver` | [rm_driver](src/ros2_rm_robot/rm_driver/) | 睿尔曼真机驱动 |
| `rm_control` | [rm_control](src/ros2_rm_robot/rm_control/) | MoveIt 到机械臂驱动的轨迹转发 |
| `rm_bringup` | [rm_bringup](src/ros2_rm_robot/rm_bringup/) | 双 RM75 真机启动入口 |
| `rm_l20_driver` | [rm_l20_driver](src/ros2_rm_robot/rm_l20_driver/) | L20-11/L20-10 RS485 协议、身份识别和 ROS 节点 |
| `rm_piano_player` | [rm_piano_player](src/ros2_rm_robot/rm_piano_player/) | MIDI 调度、双臂规划、双手命令、MIDI 反馈 |
| `rm_ros_interfaces` | [rm_ros_interfaces](src/ros2_rm_robot/rm_ros_interfaces/) | ROS 消息和服务 |
| `rm_moveit2` | [rm_moveit2](src/ros2_rm_robot/rm_moveit2/) | MoveIt 示例节点 |

标有 `COLCON_IGNORE` 的历史示例、Gazebo 和旧安装目录不进入当前构建。仿真使用 `rm_mujoco` 自带的 L20 模型；真机使用仓内 `rm_l20_driver`，无需外部灵心巧手 SDK。

## 依赖与编译

需要 ROS 2 Humble、`colcon`、MoveIt 2、RViz 2、`xacro`、ROS 2 控制器、`mujoco_ros2_control` 和 `python3-yaml` 等依赖。各功能包的 `package.xml` 声明 ROS 依赖；[requirements-hardware.txt](src/ros2_rm_robot/requirements-hardware.txt) 声明通信与 MIDI Python 依赖，两者均需满足。

Python 清单包含 `pymodbus==3.5.1`、`pyserial==3.5`、`numpy>=1.21,<2`、`mido==1.3.3`、`python-rtmidi==1.5.8`。移植 SDK 后仍需要这些基础库，节点不会自行安装依赖。

在已安装 ROS 依赖的 Ubuntu 新终端中，从工作空间根目录执行：

```bash
source /opt/ros/humble/setup.bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
```

当前 Jetson 的场景验证工作空间为 `/home/dianjinglab/ros2_ws_rm75_02d70d1`；在该机器上先进入此目录。其他机器进入自己的仓库根目录。后续新终端需要重新加载 Humble 和 `install/setup.bash`。

## MuJoCo 双臂双手场景

桌面图形环境启动：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

SSH 或无显示环境启动：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py \
  headless:=true use_rviz:=false
```

入口同时启动双臂、双手控制器、关节状态发布和 MoveIt；图形模式还启动 RViz。另开一个已加载环境的终端检查：

```bash
ros2 control list_controllers
ros2 topic echo /joint_states --once
```

应有五个 `active` 控制器：`left_arm_controller`、`right_arm_controller`、`left_l20_hand_controller`、`right_l20_hand_controller`、`joint_state_broadcaster`。

[piano_scene.yaml](src/ros2_rm_robot/rm_mujoco/config/piano_scene.yaml) 统一配置桌高、底座位置、初始姿态、88 键坐标和相机。默认桌面约 1.75 × 0.80 m、高 0.75 m，两臂底座间距 0.64 m；这些是照片近似值，不能代替真机标定。修改布局后需重新检查姿态、可达性和碰撞。

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py \
  scene_config:=/absolute/path/piano_scene.yaml
```

仅渲染模型预览，不启动 ROS 控制器：

```bash
MUJOCO_GL=egl python3 -m rm_mujoco.render --output /tmp/piano_scene.png
```

更多尺寸、相机和动力学说明见 [MuJoCo 场景说明](src/ros2_rm_robot/rm_mujoco/README.md)。

## MIDI 播放与反馈

目标链路为：MIDI 文件 → 音符调度与左右分配 → 双臂 MoveIt 轨迹 → L20 手指命令 → 数字钢琴 MIDI 反馈。

第一阶段将 MIDI 音符 `21–59` 分给左手、`60–108` 分给右手，每只手同时只允许一个活动音符；同手和弦在执行前拒绝。默认 `execute=false`，先在仿真中检查 MIDI 文件与配置：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid \
  headless:=true use_rviz:=false execute:=false
```

此入口已包含 MuJoCo 场景，使用前停止单独运行的场景入口，避免重复启动控制器。仿真使用 [piano_midi_sim.yaml](src/ros2_rm_robot/rm_piano_player/config/piano_midi_sim.yaml)，并从场景配置生成 52 白键、36 黑键对应的位置表。确认坐标与单键动作后才使用 `execute:=true`；`tempo_scale` 是时间倍率，数值越大播放越慢。

数字钢琴反馈通过 `midi_input:=<端口名称>`、`feedback_enabled:=true` 启用，默认时间容差 `feedback_tolerance_sec:=0.15`。反馈状态发布到 `/robopianist/feedback_status`；发现漏键、错键或超时后停止后续动作。实现与参数见 [MIDI 播放器说明](src/ros2_rm_robot/rm_piano_player/README_CN.md)。

## 双臂双手真机

| 项目 | 当前配置 |
| --- | --- |
| 左 RM75 | `192.168.1.18`，UDP 回传端口 `8089` |
| 右 RM75 | `192.168.1.19`，UDP 回传端口 `8090` |
| UDP 回传上位机地址 | 默认 `192.168.1.10`，须与实际网卡和机械臂配置一致 |
| 左右 L20 型号 | 默认 `L20-11`，使用 RS485 |
| 左右手串口 | 当前源码默认 `auto`，按完整 UID 匹配，不固定依赖 `ttyUSB` 编号 |
| 双手身份配置 | [hand_identity.yaml](src/ros2_rm_robot/rm_l20_driver/config/hand_identity.yaml) |

首次使用须将配置中的 UID 与实物左右手标签核对。自动扫描只考虑指定 USB 转接器型号；也可显式传入 `left_hand_port:=/dev/ttyUSB0 right_hand_port:=/dev/ttyUSB1`，但仍须通过 UID 检查。更换转接器或机械手时参阅 [L20 RS485 驱动说明](src/ros2_rm_robot/rm_l20_driver/README.md)。

仅查看启动参数、不连接设备：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py --show-args
```

先独立检查双手通信和身份：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py
```

双手命令话题为 `/cb_left_hand_control_cmd`、`/cb_right_hand_control_cmd`，真机状态话题为 `/cb_left_hand_state`、`/cb_right_hand_state`，类型均为 `sensor_msgs/msg/JointState`。真机命令须恰好包含 20 个有限的 `0–255` 值；就绪状态为 `/l20/hands_ready`。

停止独立双手驱动后，可使用完整真机入口，避免重复占用串口：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_hand_port:=auto right_hand_port:=auto \
  hand_joint:=L20-11 execute:=false
```

**真机入口的 `execute=false` 只禁止播放器动作，仍会连接硬件。** 两手身份与首帧状态均通过后才启动双臂；10 秒未就绪或双手进程退出会终止启动。真机使用 [piano_midi.yaml](src/ros2_rm_robot/rm_piano_player/config/piano_midi.yaml)，其琴键、工具和指尖坐标必须根据实物标定。

只启动双臂时使用以下入口；此入口不启动 L20：

```bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19
```

上位机地址或端口不同时，通过 `left_udp_ip`、`right_udp_ip`、`left_udp_port`、`right_udp_port` 覆盖。完整真机入口已包含双臂驱动，不要与此入口同时运行。

真机验收顺序为：核对手部 UID 与标签 → 停止驱动后交换 USB 插入顺序并重启，确认归属不变 → 检查缺手时拒绝启动和双手状态 → 双臂单键接近 → 双手单音阶 → 低速曲目 → MIDI 反馈。运动前确认工作区域无人且急停可达；软件停止后续命令不等同于机械急停。

## 验证记录与限制

构建后在工作空间根目录运行：

```bash
colcon test
colcon test-result --verbose
```

2026-10-21 的 Jetson 桌琴场景验证记录：全部 10 个包构建通过；11 项场景/几何/动力学测试、C++ 键位映射测试和 2 项 MIDI 反馈测试通过。无头运行中五个控制器为 `active`，发布 58 个关节状态；双臂初始状态碰撞检查通过，左右臂和左右手各一次小幅轨迹返回 `error_code=0`，MIDI 干运行通过。详细日志位置见 [场景验证记录](src/ros2_rm_robot/rm_mujoco/README.md#jetson-验证2026-10-21)。

这些是对应版本的验证记录。当前新增的 L20 UID 自动识别改动另在 WSL 做离线验证，尚未部署至 Jetson；不能用此前的 Jetson 构建或驱动测试代替本次 UID 改动的真机验收。

当前边界：

- 琴键为固定几何，尚无按键行程、接触传感器或仿真接触 MIDI 反馈。
- MoveIt 当前只规划双臂，未包含 L20 手部碰撞模型；手部在 MuJoCo 中独立控制。
- 键位表提供键面坐标，播放器仍使用机械臂工具端目标，指尖/工具标定及完整曲目执行尚未验证。
- 场景使用重力补偿近似位置伺服保持，不代表真实电机力矩验证。
- SIGINT 后控制器已停用，但系统安装的 `ros2_control_node`、`move_group` 仍有 ROS 对象析构段错误；运行测试通过不代表退出路径无错误。
- 尚未完成真机运动、真实 MIDI 按键闭环或官方 RoboPianist RL 策略迁移；同手多指和弦、力反馈和接触奖励属于后续阶段。

各功能包的详细 README 保留在源码目录中。本文件作为工作空间根目录的中文主入口。
