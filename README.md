# RM75-6FB-V 双臂双 L20 钢琴工程

基于 ROS 2 Humble 的机器人钢琴工作空间，面向双 RM75-6FB-V 机械臂、双 L20 灵巧手和 MIDI 数字钢琴。支持 MuJoCo 仿真、MoveIt / RViz 规划、真机连接、右手固定姿态演奏及 MIDI / 压力同步录制。

[使用指南](docs/usage.md) · [欢乐颂操作流程](docs/piano_workflow.md) · [MIDI 测速](docs/speed_test.md) · [故障排查](docs/usage.md#常见问题)

## 环境与构建

Ubuntu 22.04、ROS 2 Humble、Python 3、Bash。ROS 依赖包括 MoveIt 2、RViz 2、ros2_control 和 mujoco_ros2_control，详见各包 `package.xml` 及[安装说明](docs/usage.md#环境与编译)。

在工作空间根目录执行：

```bash
source /opt/ros/humble/setup.bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
```

每个新终端都需重新加载两份 `setup.bash`。各终端使用相同的 `ROS_DOMAIN_ID`，默认域即可。

## 快速开始

### MuJoCo 仿真

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

一起启动双臂双手仿真、MoveIt 和 RViz。在 RViz 中从 `<current>` 规划，再执行。另开已加载环境的终端检查：

```bash
ros2 control list_controllers
ros2 topic echo /joint_states --once
```

预期五个控制器为 `active`，关节状态共 58 个关节。无头模式、场景布局与规划操作见[仿真指南](docs/usage.md#仿真与-rviz-操作)。

### 真机连接

当前网络配置：主机 `192.168.1.100`，左臂 `192.168.1.18`，右臂 `192.168.1.19`。启动前核对实物地址；仿真与真机分开运行，同一设备仅使用一个驱动。

| 场景 | 启动入口 | 操作说明 |
| --- | --- | --- |
| 双臂 + MoveIt / RViz | `rm_bringup rm_75_6fb_v_bringup.launch.py` | [网络、反馈与执行开关](docs/usage.md#真机双臂连接) |
| L20 双手 | `rm_l20_driver l20_dual_rs485.launch.py` | [串口权限、UID 与 GUI](docs/usage.md#l20-双手连接) |
| 双臂与双手联合连接 | 双手与双臂分别启动 | [联合启动步骤](docs/usage.md#4-真机双臂与双手联合启动) |

### 右手欢乐颂与同步录制

按 **READY → 示教器调整机械臂 → 演奏并录制** 的顺序操作。播放器自带右手驱动，先关闭双手驱动、手部 GUI 和其他手部命令发布器。

先发送准备手势；命令完成并退出后，用示教器调整机械臂，确认手指覆盖目标琴键、READY 时琴键释放：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:="$PWD/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml" \
  execute:=true mode:=pose_test pose:=READY ready_settle:=1.0
```

查询 MIDI 输入，将下一条命令中的 `/dev/snd/midiC2D0` 替换为本次查询结果：

```bash
ros2 run rm_piano_player l20_right_hand_speed_test.py --list-midi-inputs
```

机械臂定位完成、单指按压与释放检查通过后，播放 15 音欢乐颂并录制：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:="$PWD/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml" \
  execute:=true mode:=melody \
  press_duration:=0.15 release_duration:=0.15 ready_settle:=1.0 \
  record:=true record_dir:="$HOME/l20_recordings" \
  midi_input:=/dev/snd/midiC2D0 \
  telemetry_rate:=10.0 matrix_rate:=5.0
```

调速时修改 `press_duration` / `release_duration`：慢速检查用 `0.5 / 0.5`，较快用 `0.2 / 0.2`，上例用 `0.15 / 0.15` 秒。实际音间隔还包括串口写入耗时。停止演奏：

```bash
ros2 service call /single_hand_piano/stop std_srvs/srv/Trigger '{}'
```

每次录制在 `~/l20_recordings/` 创建独立目录，包含实际输入的 `performance.mid`、压力反馈 `feedback.csv`、触觉矩阵 `touch.jsonl`、事件和元数据。压力为原始读数；触觉默认五指合计 5 帧/秒，不能保证捕获快速按压峰值。单键测试、速度表、数据含义及停止行为见[完整演奏流程](docs/piano_workflow.md)。

## 工程结构

源码位于 `src/ros2_rm_robot/`：

| 功能包 | 用途 |
| --- | --- |
| `rm_description` / `rm_moveit2_config` | 机器人模型与 MoveIt 配置 |
| `rm_mujoco` | 双臂双手 MuJoCo 场景和控制器 |
| `rm_driver` / `rm_control` / `rm_bringup` | 真机驱动、轨迹转发与启动 |
| `rm_l20_driver` | L20 RS485 驱动、身份识别和 GUI |
| `rm_piano_player` | 演奏、MIDI 输入、传感记录与测速 |

协议与参数见 [L20 驱动文档](src/ros2_rm_robot/rm_l20_driver/README.md)和 [MIDI 播放器文档](src/ros2_rm_robot/rm_piano_player/README_CN.md)。

## 验证与开发

已验证仿真控制链路、真机双臂关节反馈，并完成一次右手 15 音位置指令播放。**机械臂真机运动、当前手势与速度下的听音验收、MIDI / 压力同步录制的真机有效性仍需现场验证。** `completed` 仅表示指令流程完成。详细范围与历史记录见[验证记录](docs/usage.md#验证记录与限制)。

```bash
colcon test
colcon test-result --verbose
```

修改与验证约定见 [AGENTS.md](AGENTS.md)。
