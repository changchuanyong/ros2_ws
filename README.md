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

## 右手固定姿态演奏《欢乐颂》

此入口仅控制右手 L20-11。RM75 由操作者使用示教器定位并保持不动；程序不启动机械臂、MoveIt、左手或 MIDI 反馈。目标为 C4、D4、E4、F4、G4（MIDI 60、62、64、65、67），演奏一次以下 15 音，按人工听音验收：

```text
E E F G · G F E D · C C D E · E D D
```

先构建并加载工作空间环境。默认干运行不启动串口驱动、不连接硬件、不发送位置命令：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py
ros2 launch rm_piano_player l20_right_hand_piano.launch.py mode:=melody execute:=false
```

日志输出标定完整性和预计命令时间表。默认的 [right_hand_ode_to_joy.yaml](src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml) 中六组姿态都是空数组、`verified: false`，因此可以预览，但不能执行。将模板复制到自己的标定文件，避免重新构建时覆盖实机记录：

```bash
cp src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  ~/right_hand_ode_to_joy.yaml
```

GUI 标定顺序：

1. 先远离琴键，在设备实际支持的 GUI 设置中确认低速和输出约束，核对运动方向。ROS 播放器只发位置，`JointState.velocity/effort` 不提供限速或限力。
2. 用示教器固定手腕，检查五指能否同时覆盖五个白键。候选对应是拇指 C、食指 D、中指 E、无名指 F、小指 G；实际映射须按安装朝向和指尖位置确认。不能覆盖时先调整安装或示教姿态。
3. 在 GUI 中记录 `READY` 与 `PRESS_C`～`PRESS_G` 六组完整**目标命令值**。每组 `positions` 必须恰好 20 个有限的 `0–255` 数值，顺序为 ROOT × 5、YAW × 5、ROLL × 5、TIP × 5，各组从拇指到小指。不要复制状态反馈或 30 寄存器数组，不要截断越界值；非拇指 ROLL 槽位是保留位，按 GUI 命令格式保留。
4. GUI 与 ROS 交替使用，启动 ROS 前关闭 GUI 串口。先填入 READY 和一个 PRESS，用下列单键模式验证；已填写但 `verified: false` 的姿态可用于单键测试。逐键验证后再将相应 `verified` 改为 `true`，整段演奏要求六组全部有效且已确认。

单键测试会连接右手并核验 [hand_identity.yaml](src/ros2_rm_robot/rm_l20_driver/config/hand_identity.yaml) 中的完整右手 UID，不要求左手在线。先核对配置与实物标签；自动发现仅扫描 `1a86:7523` 转接器，指定 `hand_port:=/dev/ttyUSB1` 时仍会校验身份。不要同时运行双手驱动、其他手部命令发布器或另一个单手播放器。

```bash
# 只发送 READY，等待 ready_settle 后结束
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=$HOME/right_hand_ode_to_joy.yaml execute:=true \
  mode:=pose_test pose:=READY hand_port:=auto

# READY → PRESS_C → READY；依次将 pose 改为 PRESS_D、PRESS_E、PRESS_F、PRESS_G
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=$HOME/right_hand_ode_to_joy.yaml execute:=true \
  mode:=pose_test pose:=PRESS_C hand_port:=auto

# 六组姿态确认后，15 音播放一次；每音之后回 READY，重复音也完整释放
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=$HOME/right_hand_ode_to_joy.yaml execute:=true mode:=melody \
  press_duration:=0.5 release_duration:=0.5 ready_settle:=1.0
```

`execute` 默认 `false`，`mode` 默认 `pose_test`，`pose` 默认 `READY`，`hand_port` 默认 `auto`。三个时间参数单位为秒，必须有限且大于零。时序使用单调时钟；每次仅允许一条待确认命令，收到驱动串口写入成功的确认后才开始完整的保持/释放间隔，调度延迟不会触发集中补发。写入确认超过 0.5 秒未到达会停止后续动作。当前是等时值的简化旋律，并非完整乐谱节奏。

程序最多等待 10 秒，要求本次启动的右手驱动就绪、状态新鲜且命令订阅建立。就绪通道每次启动独立，状态超过 0.5 秒未更新、驱动故障或失去就绪都会终止后续命令；身份识别后复用同一已验证串口连接。单手入口会在播放器结束时关闭此次驱动。

另一个已加载环境的终端可查看状态和主动停止：

```bash
ros2 topic echo /single_hand_piano/status
ros2 service call /single_hand_piano/stop std_srvs/srv/Trigger '{}'
```

状态为 JSON，含阶段、音符序号、目标姿态、单调时钟发送时间和失败原因；`awaiting_write` 表示等待串口写入确认，`written_at` 是收到确认的单调时钟时间。这些仅表示位置命令进度，不表示琴键已经发声。正常结束保持 READY；主动停止且通信健康时等待当前写入确认，最多再发一次 READY，确认该次写入后结束。通信故障时不继续发送位置命令，断连或强制退出不能保证自动松键。软件停止不等同于机械急停。

实机验收须逐项记录：远离琴键核对方向和 READY；定位后 C4～G4 各连续按下、发声、抬起三次且无相邻键误触；单独验证 E/E 和 C/C；运行上述整段命令三次，人工确认均无漏音、串键、持续压键；验证主动停止和驱动故障后不再继续演奏。只有全部完成才记录“单手《欢乐颂》人工听音验收通过”。仓库模板未标定，软件测试不能代替这项实机验收，MIDI 自动闭环留待下一阶段。

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

上述桌琴场景结果属于对应版本。2026-10-22，右手《欢乐颂》功能及 L20 UID 驱动在 Jetson（aarch64 / ROS 2 Humble）的独立目录 `/home/dianjinglab/ros2_ws_single_hand_test_20261022_WQ2CLp` 验证：`rm_l20_driver`、`rm_piano_player` 两包构建通过，最终 `colcon test-result` 为 277 tests、0 errors、0 failures、0 skipped。测试覆盖原双手回归、真实 ROS 假驱动通信，以及安装后 launch 与 Linux PTY 的完整链路；0.1 秒按下/释放配置下实际收到全部 31 条位置写入，末条为 READY，释放间隔完整。

本次测试修复了 Windows 源码复制后脚本缺少执行权限的问题，并确认退出后释放虚拟串口。Jetson 独立目录保留 `build.log`、`build-piano-final.log`、`test.log`、`test-piano-final.log` 和最终 `test-result.log`；前两轮日志保留了发现问题的过程。验证使用假驱动和 `/dev/pts/*`，没有操作真实机械臂或灵巧手，不能代替实机标定、运动和听音验收。

当前边界：

- 琴键为固定几何，尚无按键行程、接触传感器或仿真接触 MIDI 反馈。
- MoveIt 当前只规划双臂，未包含 L20 手部碰撞模型；手部在 MuJoCo 中独立控制。
- 键位表提供键面坐标，播放器仍使用机械臂工具端目标，指尖/工具标定及完整曲目执行尚未验证。
- 场景使用重力补偿近似位置伺服保持，不代表真实电机力矩验证。
- SIGINT 后控制器已停用，但系统安装的 `ros2_control_node`、`move_group` 仍有 ROS 对象析构段错误；运行测试通过不代表退出路径无错误。
- 尚未完成真机运动、真实 MIDI 按键闭环或官方 RoboPianist RL 策略迁移；同手多指和弦、力反馈和接触奖励属于后续阶段。

各功能包的详细 README 保留在源码目录中。本文件作为工作空间根目录的中文主入口。
