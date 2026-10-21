# L20 RS485 driver

本包内置 L20-11/L20-10 的 RS485 协议与 ROS 2 节点，不需要安装或 source
外部 `linker_hand_ros2_sdk`。协议来源和本地修改见 `THIRD_PARTY.md`。

在 Ubuntu 22.04 / ROS 2 Humble 工作空间根目录执行：

```bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

依赖清单包含手部通信库和 MIDI 反馈库。`pymodbus==3.5.1` 是通信 API 的版本要求；
仅安装系统的 `python3-pymodbus` 不能保证符合该版本。节点不会在运行时安装依赖。

先只解析参数（不连接硬件）：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py --show-args
```

确认设备和工作区域后，单独启动左手或右手：

```bash
ros2 run rm_l20_driver l20_rs485_driver --ros-args \
  -p hand_type:=left -p hand_joint:=L20-11 -p modbus:=/dev/ttyUSB0
ros2 run rm_l20_driver l20_rs485_driver --ros-args \
  -p hand_type:=right -p hand_joint:=L20-11 -p modbus:=/dev/ttyUSB1
```

双手入口：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py
```

默认每条独立串口使用 115200、8N1、从站地址 1，反馈轮询频率为 20 Hz。
节点启动后会连接串口、读取位置与速度；只有收到有效命令才写位置。

| 接口 | 类型 | 内容 |
| --- | --- | --- |
| `/cb_left_hand_control_cmd` | `sensor_msgs/msg/JointState` | 左手 `position` 命令 |
| `/cb_right_hand_control_cmd` | `sensor_msgs/msg/JointState` | 右手 `position` 命令 |
| `/cb_left_hand_state` | `sensor_msgs/msg/JointState` | 左手位置和速度反馈 |
| `/cb_right_hand_state` | `sensor_msgs/msg/JointState` | 右手位置和速度反馈 |

命令恰好包含 20 个有限的 `0..255` 值，顺序为 ROOT1×5、YAW×5、ROLL×5、TIP×5；
每组按拇指、食指、中指、无名指、小指排列。四指 ROLL 是协议预留占位。
反馈保留 20 个原始 uint16 寄存器值，预留位和速度可大于 255；位置不转换成弧度。
`effort` 为占位零，不代表力反馈。通信失败后本节点关闭串口并拒绝后续命令，
每 0.5 秒向 `/robopianist/feedback_abort` 发布停止通知；故障排除后需重新启动节点。

离线测试使用假 Modbus 客户端、ROS 测试节点和 Linux `/dev/pts` 虚拟串口，
不连接物理设备：

```bash
colcon test --packages-select rm_l20_driver
colcon test-result --verbose
```

编译和离线测试不替代真机左右手通信、实际动作与钢琴按键验收。

2026-10-21 在 Jetson ARM64 / Humble 中验证：仅加载 Humble 构建全部 10 个包通过；
新终端加载工作空间后，外部 SDK 的 ROS 包和 Python 模块均不可见，仓内驱动可正常导入。
本包 94 项测试通过，包含真实 pymodbus/pyserial 的虚拟串口写入与反馈读取、
左右手话题、非法命令、断连、晚加入播放器的停止通知以及资源清理。
