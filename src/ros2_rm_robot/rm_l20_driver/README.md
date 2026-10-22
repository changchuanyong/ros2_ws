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

桌面调试 GUI 使用系统的 PyQt5 和 PyYAML，首次使用前安装：

```bash
sudo apt install python3-pyqt5 python3-yaml
```

GUI 为仓内独立实现，参考 SDK 的关节布局，不需要外部 SDK。无界面模式不加载 Qt。

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

在有显示环境的桌面终端显式开启 GUI：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py use_gui:=true
```

`use_gui` 默认 `false`，SSH 或无桌面环境保留原命令。缺少 GUI 依赖或显示环境时，
按错误提示补齐环境或使用 `use_gui:=false`，程序不会自行安装依赖。

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

## GUI 调试与姿态文件

左右手使用两个独立页面，位置滑块、目标值与原始反馈分开显示，并显示反馈更新时间。
20 个槽位按 ROOT、YAW、ROLL、TIP 分组，每组按拇指到小指排列；四个非拇指 ROLL
槽位标为预留并禁用调节。反馈保留原始 uint16 值，不截断；仅在 16 个有效关节均为
有限的 `0–255` 值时，用当前位置初始化目标，四个预留槽位填 0。

打开窗口后，滑块自动对齐有效的位置反馈，此过程只更新显示，不发送动作。
双手就绪后拖动滑块直接控制对应手；拖动期间反馈不会抢占滑块，松开后保留最终
目标，随后继续显示实际位置。每次开始拖动，以最新有效反馈作为其余关节的基线，
不会顺带执行已加载但未发送的文件姿态。数值框保留待发或最近的目标，后续反馈
不会覆盖已编辑、加载的目标，也不会触发发布。

拖动发送上限为 10 Hz，每只手最多一条命令等待串口写入确认，期间只保留最新目标，
不累积旧目标。确认消息仅证明串口写入完成，不代表手指到位；发送频率也不是
手指限速或限力。数值输入、加载和保存不触发动作，完整 20 值目标仍可通过对应手的
“发送一次”按钮下发。打开、关闭窗口均不自动发送姿态。
本 GUI 不直接打开串口，也不提供速度、力矩、压力设置、预设动作或自动循环。
不要同时运行其他手部命令发布器或播放器。

左右手分别选择 YAML 文件；姿态采用以下结构，其中空数组仅为不可执行模板：

```yaml
poses:
  READY:
    positions: []
    verified: false
```

支持自定义姿态名称，并提供 `READY`、`PRESS_C`～`PRESS_G` 名称，右手文件与
`rm_piano_player` 的《欢乐颂》播放器兼容。每次保存的是当前编辑的完整目标命令，
后续原始反馈不会自动改写保存内容。空模板可以加载，但不完整、非有限或越界目标
不能发送或保存。
新增或修改目标自动取消已验证标记；只有完成实机验证后才人工勾选“已实机验证”。
保存保留文件内其他姿态，覆盖同名姿态前提示确认，写入失败保留原文件。
选择自己的标定文件路径，不覆盖仓库或安装目录中的模板。

界面通过本次启动独立的就绪通道确认驱动就绪。双手状态必须在最近 0.5 秒内更新，
且命令订阅已建立，才能发送。就绪丢失、就绪心跳超过 2.5 秒未更新或任一手状态
过期、有效位置越界或写入确认超时时，两侧均禁止发送、清除待发目标并显示原因；
排除故障后重新启动，不自动重试或补发。切换页面也会丢弃尚未发送的拖动目标。

关闭窗口会结束本次启动入口，正常关闭驱动、释放串口；驱动退出也会关闭 GUI。
退出不发送额外姿态，不保证自动松键，不等同于机械急停。切换到单手播放器前，
先关闭此双手入口。只有直接占用串口的厂商工具需要与 ROS 驱动交替使用；
本 GUI 使用现有 ROS 话题，与其启动的驱动配套运行。

首次实机使用应远离琴键，先按设备实际支持的设置限制速度和输出，再逐关节小范围
拖动，核对左右手、运动方向、滑块与实际位置的对应及松开后的最终目标。
软件测试不代表已通过这项运动验收；停止后续发送不能撤销已经下发的动作。

## 测试与验证范围

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
