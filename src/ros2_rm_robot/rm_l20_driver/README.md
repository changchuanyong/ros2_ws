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
  -p hand_type:=left -p hand_joint:=L20-11 -p modbus:=/dev/ttyUSB0 \
  -p expected_uid:=LHT20-011-260-L-B-1-D
ros2 run rm_l20_driver l20_rs485_driver --ros-args \
  -p hand_type:=right -p hand_joint:=L20-11 -p modbus:=/dev/ttyUSB1 \
  -p expected_uid:=LHT20-011-266-R-B-1-D
```

双手入口：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py
```

默认每条独立串口使用 115200、8N1、从站地址 1，反馈轮询频率为 20 Hz。
双手入口运行 `l20_dual_rs485_driver`，在同一进程中保留左右两个 ROS 节点。
`config/hand_identity.yaml` 集中保存完整 UID；首次运动前须与实物标签核对左右归属。
可以用 `hand_identity_config:=/absolute/path/hand_identity.yaml` 指定更换设备后的配置，
保留文件中的 `l20_dual_rs485_driver/ros__parameters` 层级。

左右串口默认均为 `auto`，只扫描 USB VID/PID 为 `1a86:7523` 的候选设备，
按实际设备去重。每个端口连续读取两次输入寄存器 212～222，按每字低字节字符在前
解析 UID；每次超时 0.25 秒、不自动重试。匹配的串口保持打开，其他串口立即关闭。
手动设置 `left_hand_port` / `right_hand_port` 时仍校验对应 UID，不按串口编号猜左右。
更换 USB 转接器型号时，可显式指定端口；更换机械手时需更新 UID 配置。

两只指定手均识别成功并读到首帧位置、速度后才允许控制。缺手、重复 UID、
不稳定或非法 UID、反向指定端口均拒绝启动，已打开的连接全部关闭。
无响应或未配置 UID 的额外候选设备会记录并跳过。
串口要求当前用户具有读写权限，采用 Linux 独占访问；程序不自动提权或修改权限。
单手入口的 `expected_uid` 必填，身份错误时不读取状态或接受控制。
启动、识别和关闭均不发送位置或配置写入；只有就绪后收到有效命令才写位置。

| 接口 | 类型 | 内容 |
| --- | --- | --- |
| `/cb_left_hand_control_cmd` | `sensor_msgs/msg/JointState` | 左手 `position` 命令 |
| `/cb_right_hand_control_cmd` | `sensor_msgs/msg/JointState` | 右手 `position` 命令 |
| `/cb_left_hand_state` | `sensor_msgs/msg/JointState` | 左手位置和速度反馈 |
| `/cb_right_hand_state` | `sensor_msgs/msg/JointState` | 右手位置和速度反馈 |
| `/l20/hands_ready` | `std_msgs/msg/Bool` | 双手共同就绪；可靠、保留最新值、1 Hz 心跳 |

命令恰好包含 20 个有限的 `0..255` 值，顺序为 ROOT1×5、YAW×5、ROLL×5、TIP×5；
每组按拇指、食指、中指、无名指、小指排列。四指 ROLL 是协议预留占位。
反馈保留 20 个原始 uint16 寄存器值，预留位和速度可大于 255；位置不转换成弧度。
`effort` 为占位零，不代表力反馈。通信失败后本节点关闭串口并拒绝后续命令，
每 0.5 秒向 `/robopianist/feedback_abort` 发布停止通知；故障排除后需重新启动节点。
双手模式下任一只手故障会同步禁止两侧后续命令、发布就绪 `false` 并关闭两侧串口。
不会自动重连或替换设备；该软件行为不等同于机械急停。

钢琴真机入口最多等待 10 秒，收到本次运行的实时就绪通知后才启动机械臂入口，
再保留原有 8 秒播放器延时。超时或双手进程退出会终止启动。

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

本次 UID 改动在本机 WSL / Ubuntu 22.04 / ROS 2 Humble 进行离线验证，
`rm_l20_driver` 构建通过，`colcon test-result` 为 144 项通过、0 失败、0 跳过。
覆盖实测 UID 字节序、端口交换、缺手、重复 UID、双手故障联动、启动就绪检查、
Linux PTY 的真实 Modbus UID 往返、CRC 错误与独占锁释放。
尚未部署本次改动到 Jetson；真机验收需先仅启动手部入口，核对标签，并在停止驱动后
交换 USB 插入顺序再启动，确认身份不变及缺手时拒绝启动，不启动机械臂或播放器。
