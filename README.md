# RM75-6FB-V 双臂双 L20 钢琴工程

基于 Ubuntu 22.04 / ROS 2 Humble，面向双 RM75-6FB-V、双 L20-11 和 88 键 MIDI 数字钢琴。
包含 MuJoCo 仿真、MoveIt / RViz 双臂规划、仓内 L20 RS485 驱动、双手调试 GUI 和钢琴播放器，无需外部灵心巧手 SDK。

详细标定、参数、排障和历史验证记录见 [使用指南](docs/usage.md)。

## 环境与编译

需要 ROS 2 Humble、colcon、MoveIt 2、RViz 2、xacro、ROS 2 控制器及 `mujoco_ros2_control`，ROS 依赖以各包 `package.xml` 为准。
以下使用当前 Jetson 工作空间路径；其他机器请替换为实际仓库根目录。

安装好 ROS 依赖后，首次构建：

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
sudo apt install python3-pyqt5 python3-yaml
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
```

每个新终端启动前加载环境，统一使用默认 ROS 域：

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
source install/setup.bash
unset ROS_DOMAIN_ID
```

源码更新后重新构建并加载环境；软件检查使用 `colcon test`、`colcon test-result --verbose`。

## 常用启动

切换仿真、真机或播放器前，先停止上一套入口，避免重复连接设备。

### 1. MuJoCo 双臂双手仿真

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

包含双臂双手控制器、MoveIt 和 RViz。SSH / 无显示环境添加 `headless:=true use_rviz:=false`。
RViz 选择 `left_arm`、`right_arm` 或 `dual_arms`，从 `<current>` 规划，先 Plan 再 Execute。
检查：`ros2 control list_controllers` 应有五个 `active` 控制器，`/joint_states` 应持续发布 58 个关节。

### 2. 真机双臂

上位机为 `192.168.1.100/24`，左臂 `.18`、右臂 `.19`。确认网络、设备地址和安装模型后，先关闭 MoveIt 执行：

```bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=192.168.1.100 right_udp_ip:=192.168.1.100 \
  left_udp_port:=8089 right_udp_port:=8090 \
  use_rviz:=true allow_trajectory_execution:=false
```

该入口连接双臂，不启动灵巧手。检查 `/left_arm/joint_states`、`/right_arm/joint_states` 各 7 个关节，合并 `/joint_states` 共 14 个。
`allow_trajectory_execution:=false` 只关闭 MoveIt 执行，底层驱动仍可接收命令；运动前完成[反馈、模型与规划检查](docs/usage.md#真机双臂连接)。

### 3. L20 双手 RS485 与 GUI

核对串口权限及 [hand_identity.yaml](src/ros2_rm_robot/rm_l20_driver/config/hand_identity.yaml) 中的 UID，然后在桌面终端启动：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py use_gui:=true
```

默认 `L20-11`、串口 `auto`，按完整 UID 识别左右手；两只手均须在线。去掉 `use_gui:=true` 可无界面运行，该入口不启动机械臂。
**打开窗口会将滑块对齐当前有效反馈；就绪后拖动滑块会直接运动。** 数值输入、加载和保存不自动发送；“发送一次”执行完整目标。
GUI 只提供位置控制。关闭窗口会结束驱动并释放串口，退出不保证自动松键。标定与保存流程见 [GUI 操作](docs/usage.md#l20-双手调试-gui)。

只需同时连接双臂和双手时，分别在两个终端运行第 2、3 项，停止时分别退出。完整 MIDI 联合入口见 [MIDI 播放与反馈](docs/usage.md#midi-播放与反馈)；该入口即使 `execute:=false` 也会连接硬件。

### 4. 右手《欢乐颂》

RM75 用示教器定位并保持不动，仅控制右手 L20-11，播放 C4～G4 范围内的 15 音简化片段：

```text
E E F G · G F E D · C C D E · E D D
```

先完成[逐键标定](docs/usage.md#调整姿态与重新标定)，关闭双手 GUI、独立驱动及其他手部命令发布器，确认右手已定位于琴键上方，再执行真机播放：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=melody \
  press_duration:=0.15 release_duration:=0.15 ready_settle:=1.0
```

该命令自带右手驱动，播放一次后回到 READY 并退出；不启动机械臂、左手或 MIDI 反馈。
按压和释放各等待 `0.15 s`，初始 READY 等待 `1.0 s`；单键测试与时序说明见[右手固定姿态演奏](docs/usage.md#右手固定姿态演奏)。

播放期间另开已加载环境的终端查看状态或停止：

```bash
ros2 topic echo /single_hand_piano/status
ros2 service call /single_hand_piano/stop std_srvs/srv/Trigger '{}'
```

状态表示命令进度，不能证明琴键发声。主动停止且通信健康时最多补发一次 READY；断连或强制退出不能保证松键，软件停止不等同于机械急停。

## 当前进展与限制

- 已有历史记录：MuJoCo 控制链路、真机双臂反馈通过验证；旧姿态配置完成过一次右手 15 音指令播放。具体版本与范围见[验证记录](docs/usage.md#验证记录与限制)。
- **2026-10-23 的 Jetson 本地姿态含推算数据，更新后尚未完成动作和听音验收；`verified: true` 不代表已通过验收。** 这份本地配置未发布，仓库 YAML 仍为空模板，新克隆需先标定。
- 仿真与真机安装坐标尚未统一，工具、指尖和琴键位置仍需标定；MoveIt 尚未包含 L20 手部碰撞模型。
- 机械臂真机运动、单手听音和完整 MIDI 按键闭环仍待验收。RoboPianist RL 策略迁移、同手和弦、力反馈和仿真琴键接触尚未实现。
- 已知 USB Hub 重启连接问题及部分 ROS 进程退出异常仍需排查，处理记录见[常见问题](docs/usage.md#常见问题)。

## 详细文档

- [完整使用指南](docs/usage.md)：标定、参数、联合启动、排障与验收。
- [工程结构](docs/usage.md#工程结构)：源码位于 `src/ros2_rm_robot/`，按功能包说明用途。
- [MuJoCo 场景](src/ros2_rm_robot/rm_mujoco/README.md)
- [L20 RS485 驱动与 GUI](src/ros2_rm_robot/rm_l20_driver/README.md)
- [MIDI 播放器](src/ros2_rm_robot/rm_piano_player/README_CN.md)
