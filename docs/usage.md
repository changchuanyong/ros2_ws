# RM75-6FB-V 双臂双 L20 使用指南

[返回首页](../README.md)

以下命令均在仓库根目录执行。本页保留完整操作说明、标定细节、排障和历史验证记录。

本仓库是面向双 RM75-6FB-V 机械臂、双 L20 灵巧手和 88 键 MIDI 数字钢琴的 ROS 2 工作空间。开发环境为 Ubuntu 22.04 / ROS 2 Humble，包含 MuJoCo 仿真、MoveIt 2 / RViz 双臂规划、L20 RS485 驱动和 MIDI 播放器。

**当前进展（2026-10-23）：仿真控制链路、真机双臂关节反馈已验证；右手《欢乐颂》15 音符片段已完成一次真机指令播放，最终 READY 写入确认、程序正常退出。琴键发声与音高仍需现场听音验收，机械臂运动和真实钢琴 MIDI 闭环尚未验收。** 真机 RViz 模型已改为直立安装、底座中心相距 70 cm；这项模型修改完成了离线检查，仍需根据实物校准。

## 使用导航

| 要做什么 | 从哪里开始 |
| --- | --- |
| 已编译机器：选择仿真、双臂、双手、联合连接或右手演奏 | [五种启动方式](#五种启动方式) |
| 打开新终端 | [每个终端先加载环境](#每个终端先加载环境) |
| 首次安装或更新后构建 | [环境与编译](#环境与编译) |
| 用 MoveIt 控制 MuJoCo，查看 `piano_ready` | [仿真与 RViz 操作](#仿真与-rviz-操作) |
| 连接真机，先查看双臂状态 | [真机双臂连接](#真机双臂连接) |
| 检查 L20 身份、串口和状态 | [L20 双手连接](#l20-双手连接) |
| 用 GUI 调节双手并保存标定姿态 | [L20 双手调试 GUI](#l20-双手调试-gui) |
| 只用右手演奏《欢乐颂》 | [右手固定姿态演奏](#右手固定姿态演奏) |
| 运行 MIDI 文件和双臂双手完整入口 | [MIDI 播放与反馈](#midi-播放与反馈) |
| 排查无反馈、不同步或执行不动 | [常见问题](#常见问题) |
| 查找功能包和验证范围 | [工程结构](#工程结构)、[验证记录与限制](#验证记录与限制) |

## 每个终端先加载环境

以下命令用于已经完成编译的当前机器；首次安装或源码更新后先完成[环境与编译](#环境与编译)。**每打开一个终端，先执行下面四行，再执行对应的启动或检查命令：**

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
source install/setup.bash
unset ROS_DOMAIN_ID
```

下面统一使用默认 ROS 域。仿真和真机分开运行；切换方案时先用 `Ctrl+C` 停止上一套入口。联合连接时，按下文第 4 项保留双手和双臂两个终端。右手播放器自带右手驱动，播放前关闭双手驱动和调试 GUI。

## 五种启动方式

按需求选择一种入口。命令中的绝对路径用于当前机器，换机器时替换为实际工作空间路径。

### 1. 启动 MuJoCo 仿真

无需连接真实机械臂和灵巧手。在桌面终端执行：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

此命令一起启动 **MuJoCo + 双臂双手仿真控制器 + MoveIt + RViz**。另开终端加载环境后检查：

```bash
ros2 control list_controllers
ros2 topic echo /joint_states --once
```

预期五个控制器均为 `active`，关节状态包含 58 个关节。RViz 中选择规划组，Start State 选 `<current>`，设置目标后先 **Plan** 再 **Execute**；MuJoCo 应随执行运动。无显示环境的启动方式见[仿真与 RViz 操作](#仿真与-rviz-操作)。

### 2. 连接真实机械臂

给两台机械臂按设备要求供电，将上位机与两台机械臂通过网线接入同一局域网。当前配置为：**上位机 `192.168.1.100/24`、左臂 `192.168.1.18`、右臂 `192.168.1.19`**。先确认地址和连通性：

```bash
ip -4 addr show eno1
ping -c 3 192.168.1.18
ping -c 3 192.168.1.19
```

确认没有其他驱动连接这两台机械臂后，启动双臂、MoveIt 和 RViz，先关闭 MoveIt 运动执行：

```bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=192.168.1.100 right_udp_ip:=192.168.1.100 \
  left_udp_port:=8089 right_udp_port:=8090 \
  use_rviz:=true allow_trajectory_execution:=false
```

另开终端加载环境后检查：

```bash
ros2 topic echo /left_arm/joint_states --once
ros2 topic echo /right_arm/joint_states --once
ros2 topic echo /joint_states --once
```

预期左右臂各 7 个关节、合并共 14 个关节，RViz 显示反馈姿态。该入口**不连接灵巧手**。需要实际运动时，先完成[真机双臂连接](#真机双臂连接)中的反馈、模型和规划检查，再重新启动并将 `allow_trajectory_execution` 改为 `true`；连接成功不等于已通过运动验收。

### 3. 连接真实 L20 灵巧手

按设备要求给灵巧手供电，两只手分别通过独立的 USB-RS485 转接器连接上位机。当前驱动采用两条串口，默认波特率 `115200`、8N1、从站地址 `1`。关闭直接占用串口的厂商工具或其他驱动，并确认当前用户对串口有读写权限；下文仓内 ROS 调试 GUI 由本驱动统一管理串口。

启动前直接给当前两个串口添加读写权限：

```bash
sudo chmod 777 /dev/ttyUSB0 /dev/ttyUSB1
ls -l /dev/ttyUSB0 /dev/ttyUSB1
```

预期权限为 `crwxrwxrwx`，在当前终端即可启动驱动。重新插拔或重启后权限可能恢复，届时重新执行 `chmod`；若串口编号变化，改成实际设备路径。该操作只解决 `Permission denied`；若出现 `Input/output error`，应继续检查 USB 连接和内核日志。

先核对 [hand_identity.yaml](../src/ros2_rm_robot/rm_l20_driver/config/hand_identity.yaml) 中的左右手 UID 与实物标签一致，再启动：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py \
  left_hand_port:=auto right_hand_port:=auto hand_joint:=L20-11
```

默认自动扫描 `1a86:7523` 转接器并按完整 UID 识别左右手。若转接器型号不同或需要指定端口，停止上一条命令后使用以下方式；端口须换成实际设备，仍会检查 UID：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py \
  left_hand_port:=/dev/ttyUSB0 right_hand_port:=/dev/ttyUSB1 \
  hand_joint:=L20-11
```

另开终端加载环境后检查：

```bash
ros2 topic echo /l20/hands_ready --once
ros2 topic echo /cb_left_hand_state --once
ros2 topic echo /cb_right_hand_state --once
```

预期就绪状态为 `data: true`，左右手均有状态反馈。此入口不启动机械臂，不自动发送位置命令；任一只手缺失或 UID 不符会拒绝启动。不要把手部原始寄存器反馈当作弧度关节角度。命令话题与协议见 [L20 双手连接](#l20-双手连接)。

### 4. 真机双臂与双手联合启动

**只连接设备、查看反馈，不播放 MIDI：使用两个终端。**

1. 终端 A 加载环境，执行第 3 项的双手启动命令，保持运行。
2. 在检查终端确认 `/l20/hands_ready` 为 `true`，左右手均有反馈。
3. 终端 B 加载环境，执行第 2 项的双臂启动命令，保持 `allow_trajectory_execution:=false`。
4. 在检查终端分别读取 `/joint_states`、`/cb_left_hand_state`、`/cb_right_hand_state`，确认双臂与双手都在线。

这时双臂和双手同时连接，同属默认 ROS 域；双臂由 MoveIt / `rm_control` 控制，手部使用独立命令话题。真机 `/joint_states` 仍是双臂的 14 个关节，不会因为连接双手就变成仿真的 58 个关节。这种分开启动方式没有统一的故障退出管理，停止时需要分别在终端 A、B 按 `Ctrl+C`。

**需要一条命令启动完整钢琴链路：先停止上述两个独立入口，再使用下面的现有联合入口。** 它会先连接双手，通过身份和首帧状态检查后启动双臂、MoveIt、RViz 及播放器。必须把 `/absolute/path/song.mid` 换成实际存在的 MIDI 文件：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=192.168.1.100 right_udp_ip:=192.168.1.100 \
  left_udp_port:=8089 right_udp_port:=8090 \
  left_hand_port:=auto right_hand_port:=auto \
  hand_joint:=L20-11 use_rviz:=true execute:=false
```

`execute:=false` 表示播放器只检查 MIDI、不执行演奏，但仍会连接硬件，也不禁止其他客户端发起运动。此入口的双手启动就绪检查使用本次运行独立的内部话题；查看双手是否有反馈可使用 `/cb_left_hand_state` 和 `/cb_right_hand_state`。不要再同时启动独立的双臂或双手入口。

**当前没有独立的“无 MIDI、单命令、双臂双手联合连接”启动文件。** 只查看设备状态时采用上面的两个终端方式；完整钢琴入口不能省略 MIDI 文件来代替它。标定、播放器参数和演奏验收见 [MIDI 播放与反馈](#midi-播放与反馈)。

### 5. 右手真机播放《欢乐颂》

先加载上面的终端环境，关闭双手驱动和手部调试 GUI，确认右手已定位于琴键上方。下面命令会自动连接右手，核验 UID，并实际播放一次 15 音符片段；不启动机械臂、左手或 MIDI 反馈：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=melody \
  press_duration:=0.15 release_duration:=0.15 ready_settle:=1.0
```

正常完成后发送 `READY` 并自动退出。配置路径、单键测试和停止方式见[右手固定姿态演奏](#右手固定姿态演奏)。

## 环境与编译

当前机器工作空间为 `/home/dianjinglab/ros2_ws_full_20261022`。其他机器请换成自己的仓库根目录。

需要 ROS 2 Humble、`colcon`、MoveIt 2、RViz 2、`xacro`、ROS 2 控制器、`mujoco_ros2_control` 和 `python3-yaml`。ROS 依赖以各包的 `package.xml` 为准；通信与 MIDI 的 Python 依赖见 [requirements-hardware.txt](../src/ros2_rm_robot/requirements-hardware.txt)。

使用 L20 调试 GUI 时，还需系统的 PyQt5 和 PyYAML。首次安装命令如下；程序不会自行安装依赖：

```bash
sudo apt install python3-pyqt5 python3-yaml
```

已安装 ROS 依赖后，首次构建执行：

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
python3 -m pip install --user -r src/ros2_rm_robot/requirements-hardware.txt
colcon build --symlink-install
source install/setup.bash
```

后续每个新终端都需要加载环境：

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
source install/setup.bash
```

### ROS 通信域

默认域即可使用，不要求设置 `ROS_DOMAIN_ID=42`。启动、查看状态和发送规划请求的终端必须使用相同的域；如果此前设置过其他域，可以在各终端统一恢复默认值：

```bash
unset ROS_DOMAIN_ID
```

需要单独隔离测试时，在所有相关终端使用 `export ROS_DOMAIN_ID=42`（注意是 `export`）。域不同会导致节点互相不可见，但**不同域不能防止两个驱动同时连接同一台机械臂**。日常测试一次启动一套完整入口，切换仿真与真机前停止上一套进程。

## 仿真与 RViz 操作

### 启动与状态检查

桌面图形环境启动：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

SSH 或无显示环境启动：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py \
  headless:=true use_rviz:=false
```

入口包含 MuJoCo、双臂双手控制器、关节状态发布和 MoveIt；默认还启动 RViz。另开一个已加载相同环境的终端检查：

```bash
ros2 control list_controllers
ros2 topic echo /joint_states --once
```

| 检查项 | 含义与预期 |
| --- | --- |
| `ros2 control list_controllers` | 查询仿真的控制器管理器；五个控制器应为 `active` |
| `ros2 topic echo /joint_states --once` | 打印一条实际发布的关节状态后退出；用于确认反馈链路有数据，不会发送运动命令 |
| 五个控制器 | `left_arm_controller`、`right_arm_controller`、`left_l20_hand_controller`、`right_l20_hand_controller`、`joint_state_broadcaster` |
| 仿真关节状态 | 当前完整模型包含 58 个关节；控制器 `active` 本身不保证状态已正常发布 |

### 在 RViz 中规划与执行

1. 在 MotionPlanning 面板中选择 `left_arm`、`right_arm` 或 `dual_arms`。
2. 将 **Start State** 设为 `<current>`，从当前反馈状态规划。
3. 将 **Goal State** 设为 `piano_ready`，或用交互标记设置一个可达的小幅目标。
4. 先点击 **Plan** 查看轨迹，再点击 **Execute** 执行；只看到规划动画不能说明 MuJoCo 已运动。
5. 执行时同时观察 MuJoCo 与 `/joint_states`，确认反馈随动作变化。

`piano_ready` 是仿真启动文件根据 [piano_scene.yaml](../src/ros2_rm_robot/rm_mujoco/config/piano_scene.yaml) 注入 SRDF 的命名关节姿态，表示场景中的准备姿态。它不是通用的真机安全姿态，也不表示已完成琴键或指尖标定。如果当前状态已经等于目标，执行时可能没有明显运动。

### 场景布局

[piano_scene.yaml](../src/ros2_rm_robot/rm_mujoco/config/piano_scene.yaml) 配置桌高、底座位置、初始姿态、88 键坐标和相机。默认桌面约 1.75 × 0.80 m、高 0.75 m，两臂底座中心相距 **0.64 m**。这些是实验室照片近似值，与下文真机模型的 **0.70 m** 布局尚未统一。

使用自定义布局：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py \
  scene_config:=/absolute/path/piano_scene.yaml
```

仅渲染模型预览，不启动 ROS 控制器：

```bash
MUJOCO_GL=egl python3 -m rm_mujoco.render --output /tmp/piano_scene.png
```

更多尺寸、相机和动力学说明见 [MuJoCo 场景说明](../src/ros2_rm_robot/rm_mujoco/README.md)。修改布局后需重新检查可达性和碰撞。

## 真机双臂连接

### 网络与安装配置

启动前核对 [rm_75_config.yaml](../src/ros2_rm_robot/rm_driver/config/rm_75_config.yaml) 和设备实际地址。当前机器配置如下：

| 设备 | IP 地址 | 通信端口 |
| --- | --- | --- |
| 上位机 `eno1` | `192.168.1.100/24` | 接收两臂 UDP 状态 |
| 左 RM75 | `192.168.1.18` | TCP `8080`，UDP 回传到上位机 `8089` |
| 右 RM75 | `192.168.1.19` | TCP `8080`，UDP 回传到上位机 `8090` |

`udp_ip` 指向**上位机**，不是机械臂。`192.168.1.10` 是部分旧代码的默认值，不是 SDK 强制要求。单独双臂入口当前默认使用 `.100`；完整钢琴入口仍有 `.10` 默认值，下文命令显式覆盖。

可先检查网卡和网络连通性；ping 成功还不能证明 TCP 驱动和 UDP 反馈正常：

```bash
ip -4 addr show eno1
ping -c 3 192.168.1.18
ping -c 3 192.168.1.19
```

真机启动入口与 MoveIt 使用相同的安装变换：

| 底座 | `xyz`（米） | `rpy`（弧度） |
| --- | --- | --- |
| 左臂 | `0 -0.35 0.5` | `0 0 0` |
| 右臂 | `0 0.35 0.5` | `0 0 0` |

两臂直立安装，沿模型 Y 轴分开，底座中心间距 70 cm。这里的“直立”指底座安装方向，关节角度仍来自真机反馈；不会命令机械臂伸直。Z 高度 `0.5 m` 尚未按实物标定。修改这些变换后，需要重启启动入口，RViz 与 MoveIt 才会加载新模型。

### 先检查反馈和规划

停止其他机械臂驱动，确认设备地址对应左右臂。首次连接使用下列命令，关闭 MoveIt 的轨迹执行：

```bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=192.168.1.100 right_udp_ip:=192.168.1.100 \
  use_rviz:=true allow_trajectory_execution:=false
```

该入口启动双臂驱动、轨迹转发、关节状态合并、MoveIt 和 RViz，不启动 L20。`allow_trajectory_execution:=false` 只关闭 MoveIt 执行，并不将底层驱动变成只读接口；此阶段只检查状态和规划。

另开终端检查：

```bash
ros2 topic echo /left_arm/joint_states --once
ros2 topic echo /right_arm/joint_states --once
ros2 topic echo /joint_states --once
ros2 action list -t
```

左右臂各应有 7 个关节，合并后的 `/joint_states` 应包含 `left_joint1`～`left_joint7`、`right_joint1`～`right_joint7` 共 14 个关节。真机轨迹由 `rm_control` 转发，其动作接口为：

```text
/left_arm/rm_group_controller/follow_joint_trajectory
/right_arm/rm_group_controller/follow_joint_trajectory
```

**真机这条链路不使用仿真的五个 ros2_control 控制器，因此不要用 `ros2 control list_controllers` 判断真机是否连接成功。** 应检查左右臂状态、合并状态、动作接口以及驱动日志。

确认反馈、模型安装变换、碰撞环境和小幅规划都正确后，才进入真机运动测试：工作范围内无人、急停可达，重新启动时将 `allow_trajectory_execution` 改为 `true`，从当前状态规划小幅目标，先 Plan 再 Execute。不要直接套用仿真的 `piano_ready` 或未标定的钢琴目标。当前尚未完成真机运动验收。

## L20 双手连接

左右手默认型号为 `L20-11`，使用 RS485。串口默认 `auto`，根据 [hand_identity.yaml](../src/ros2_rm_robot/rm_l20_driver/config/hand_identity.yaml) 中的完整 UID 匹配左右手，不固定依赖 `ttyUSB` 编号。首次使用须核对 UID 与实物标签。

独立检查双手通信和身份：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py
```

自动扫描只考虑指定 USB 转接器型号。也可指定 `left_hand_port:=/dev/ttyUSB0 right_hand_port:=/dev/ttyUSB1`，仍须通过 UID 检查。详细配置见 [L20 RS485 驱动说明](../src/ros2_rm_robot/rm_l20_driver/README.md)。

| 用途 | 左手 | 右手 |
| --- | --- | --- |
| 命令话题 | `/cb_left_hand_control_cmd` | `/cb_right_hand_control_cmd` |
| 状态话题 | `/cb_left_hand_state` | `/cb_right_hand_state` |

以上话题类型均为 `sensor_msgs/msg/JointState`，真机位置命令须恰好包含 20 个有限的 `0–255` 值。双手就绪状态发布到 `/l20/hands_ready`。使用下文单手或完整钢琴入口前，先停止独立双手驱动，避免重复占用串口。

### L20 双手调试 GUI

在 Jetson 桌面终端中启动双手驱动和调试窗口：

```bash
ros2 launch rm_l20_driver l20_dual_rs485.launch.py use_gui:=true
```

`use_gui` 默认 `false`，SSH 或无显示环境继续使用原命令即可。界面在仓内独立实现，参考 SDK 的关节布局，不依赖外部 SDK，也不会再次打开串口。GUI 模式仍要求两只配置中的手均通过 UID 校验。

左右手各有独立页面，显示位置滑块、目标值、实际反馈和状态更新时间。ROOT、YAW、ROLL、TIP 四组共 20 个槽位，每组按拇指到小指排列；非拇指 ROLL 四项为预留，禁用调节。原始反馈单独显示，不截断。只有 16 个有效关节反馈均为有限的 `0–255` 值时，才允许用当前位置初始化目标；预留反馈不代表真实关节位置。

打开窗口后，滑块自动对齐有效的当前反馈，此过程不发送命令。双手就绪后，拖动滑块会直接控制对应手；拖动期间反馈不会拉回滑块，松开后保留最终目标，随后继续显示实际位置。每次开始拖动以最新有效反馈作为其他关节的基线，避免把尚未发送的文件姿态一并执行。数值框保留待发或最近的目标，反馈更新不覆盖已编辑、加载的目标，也不会触发循环发送。

拖动发送上限为 10 Hz，每只手最多有一条等待串口写入确认的命令，其间仅保留最新目标。写入确认不表示手指已到位，10 Hz 也不是手指限速或限力。手动输入数值、加载和保存均不触发动作；需要发送完整编辑姿态时，点击对应手的“发送一次”。首版仅控制位置，不提供速度、力矩或压力控制，也不提供预设动作或自动循环。调试时不要同时运行其他手部命令发布器或播放器。

左右手分别选择自己的 YAML 文件。文件沿用 `poses → 姿态名称 → positions / verified` 格式，支持自定义名称和 `READY`、`PRESS_C`～`PRESS_G`；右手文件可直接用于下文《欢乐颂》播放器。空模板可以加载，但未填写完整的姿态不能发送或保存为有效目标。新增或修改目标后 `verified` 为 `false`，只有完成实机验证后才人工勾选“已实机验证”。保存保留文件内其他姿态，覆盖同名姿态会提示确认；保存到你明确选择的文件路径；右手播放器的 `pose_config` 必须指向同一份文件。

GUI 仅在本次启动就绪、双手反馈均在最近 0.5 秒内更新且命令订阅已建立时允许发送。就绪丢失、就绪心跳超过 2.5 秒未更新、任一手反馈过期、有效位置越界或写入确认超时后，两侧均禁止发送并清除待发目标，排除故障后需要重新启动，不会补发或自动重试。切换页面时也会丢弃尚未发送的拖动目标。

关闭窗口会结束本次启动入口并正常释放串口；驱动退出也会关闭窗口。退出不发送额外姿态，因此不保证自动松键，也不等同于机械急停。切换到单手播放器前先关闭此窗口，避免重复连接右手。

首次实机使用需远离琴键，按设备支持的设置限制速度和输出，再逐关节小范围拖动，核对左右手、运动方向、滑块与实际位置的对应，以及松开后的最终目标。软件测试不能代替这项运动验收；停止后续发送也不能撤销已下发的动作。

## 右手固定姿态演奏

### 当前配置和文件路径

本节记录 2026-10-23 的 Jetson 本地配置。下述已填充姿态未发布到仓库；仓库中的 `right_hand_ode_to_joy.yaml` 仍为六组空数组、`verified: false` 的模板。新克隆需先按[标定流程](#调整姿态与重新标定)填写自己的姿态，不能直接按下文记录认定配置已可执行。

此入口仅控制右手 L20-11。RM75 由操作者使用示教器定位并保持不动；程序不启动机械臂、MoveIt、左手或 MIDI 反馈。当前是等时值的《欢乐颂》简化片段，共 15 音，播放一次：

```text
E E F G · G F E D · C C D E · E D D
```

本机当前编辑的源码文件如下；2026-10-23 的真机播放记录使用的是更新准备姿态之前的版本：

```text
/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml
```

下文统一显式传入这个路径，读取文件当前内容。修改这份 YAML 的数值后无需仅为配置变更重新构建；修改播放器或驱动源码则需重新构建相应功能包。

当前准备、拇指和食指姿态分别取自 `/home/dianjinglab/ready.yaml`、`/home/dianjinglab/muzhi.yaml`、`/home/dianjinglab/shizhi.yaml`，均读取其中的 `poses.READY.positions`。文件中的旧 `PRESS_C` 条目不参与本次更新。准备和拇指姿态保持原始数据；食指、中指、无名指和小指的全部 20 项相对 READY 的变化量缩小到导入或推算值的 50%。

| 姿态 | 手指 / 作用 | 数据来源 | 主要槽位：准备 → 按压（从 00 编号） |
| --- | --- | --- | --- |
| `READY` | 准备、松键 | `ready.yaml / READY`，全部 20 项 | — |
| `PRESS_C` | 拇指 C4（60） | `muzhi.yaml / READY`，全部 20 项 | YAW `05`：`251 → 178` |
| `PRESS_D` | 食指 D4（62） | `shizhi.yaml / READY`，相对变化减半 | ROOT `01`：`183 → 124.5`；TIP `16`：`85 → 122` |
| `PRESS_E` | 中指 E4（64） | 按食指相对变化推算并减半 | ROOT `02`：`182 → 123.5`；TIP `17`：`86 → 123` |
| `PRESS_F` | 无名指 F4（65） | 按食指相对变化推算并减半 | ROOT `03`：`182 → 123.5`；TIP `18`：`87 → 124` |
| `PRESS_G` | 小指 G4（67） | 按食指相对变化推算并减半 | ROOT `04`：`181 → 122.5`；TIP `19`：`88 → 125` |

后三指的推算方法：先计算食指按压姿态相对 READY 的全部 20 项变化量，再在 ROOT、YAW、ROLL、TIP 各组内交换食指与目标手指的变化量，将变化量乘以 0.5 后加回 READY。因此四指的目标 ROOT 变化为 `−58.5`、TIP 变化为 `+37`；其他槽位的配合变化也同步减半。这里的比例指命令位置差，实际指尖行程仍需现场确认。后三组属于待现场调整的推算姿态，并非独立采集的标定数据。

六组姿态的 `verified: true` 按操作者此前要求保留，未采用导入文件的 `verified: false`。这组更新尚未进行真机动作和听音验证，标记不代表新增验证结果。此前真机播放记录使用的是旧版配置。

**不要混淆三个配置位置：**

| 写法 | 实际读取位置 |
| --- | --- |
| 下文显式指定源码绝对路径 | 当前修改与校验使用的文件；历史真机播放使用其旧版本 |
| 省略 `pose_config` | ROS 当前环境找到的 `rm_piano_player` 安装包 `share/rm_piano_player/config/right_hand_ode_to_joy.yaml`，不保证始终与源码文件相同 |
| `pose_config:=$HOME/right_hand_ode_to_joy.yaml` | 主目录中的另一份文件；仅在你有意保存、核对这份副本时使用，源码修改不会自动同步到它 |

### 真机播放一次

先按[每个终端先加载环境](#每个终端先加载环境)加载环境。退出独立双手驱动、调试 GUI 和其他手部命令发布器，释放串口。核对右手 UID 与 [hand_identity.yaml](../src/ros2_rm_robot/rm_l20_driver/config/hand_identity.yaml) 一致，确认手腕位置和键位覆盖正确、手指附近无人接触，然后执行：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=melody \
  press_duration:=0.15 release_duration:=0.15 ready_settle:=1.0
```

这条命令自带右手驱动，不需要先启动双手入口，也不要求左手在线。默认扫描 `1a86:7523` 转接器，按完整 UID 选择右手；串口编号变化不改变左右归属。需要指定端口时添加 `hand_port:=/dev/ttyUSB0`（替换为实际端口），仍会校验 UID。

执行顺序是 `READY → 15 个按压/松键周期 → 结束`，每个音之后都回 `READY`，重复音也完整释放。正常完成应看到 `phase: completed`、`note_index: 15`、`target_pose: READY`、`awaiting_write: false`，随后播放器和右手驱动正常退出。

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `execute` | `false` | `true` 才连接右手并发送位置命令 |
| `mode` | `pose_test` | `melody` 播放上述片段，`pose_test` 测试指定姿态 |
| `pose` | `READY` | 单姿态模式的目标，支持 `READY`、`PRESS_C`～`PRESS_G` |
| `hand_port` | `auto` | 自动扫描并校验右手 UID |
| `press_duration` | `0.5` | 按压指令写入确认后的保持时间，秒 |
| `release_duration` | `0.5` | READY 写入确认后的释放等待时间，秒 |
| `ready_settle` | `1.0` | 首次 READY 写入确认后的等待时间，秒 |

上面的整段播放示例显式使用 `press_duration:=0.15 release_duration:=0.15 ready_settle:=1.0`：每音按压、释放等待合计约 `0.3 s`，开始前准备等待 `1.0 s`。这只缩短等待时间，不提高电机本身的运动速度；该节奏尚未完成真机验证，若出现漏音或松键不完整，可将按压、释放时间调回各 `0.2 s`。

三个时间参数均须大于零；省略时使用表中默认值。时序从串口写入确认后计时，因此实际总耗时会包含通信和调度延迟。每次仅允许一条待确认命令，不会集中补发；写入确认超过 0.5 秒未到达会停止后续动作。

程序最多等待右手就绪 10 秒；状态超过 0.5 秒未更新、驱动故障或失去就绪时终止后续命令。就绪通道每次启动独立，身份识别后复用同一已验证串口连接。

### 单独测试准备姿态或一个音

同样先退出双手 GUI 及其驱动。下面两条命令分别执行，均会发送真机位置命令：

```bash
# 只发送 READY，等待 ready_settle 后结束
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=pose_test pose:=READY

# READY → PRESS_C → READY；测试其他手指时修改 pose
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=pose_test pose:=PRESS_C
```

### 查看进度与停止

另一个已加载环境的终端可查看状态和主动停止：

```bash
ros2 topic echo /single_hand_piano/status
ros2 service call /single_hand_piano/stop std_srvs/srv/Trigger '{}'
```

状态为 JSON，含阶段、音符序号、目标姿态、单调时钟发送时间和失败原因；`awaiting_write` 表示等待串口写入确认，`written_at` 是收到确认的单调时钟时间。这些仅表示位置命令进度，不表示琴键已经发声。正常结束保持 READY；主动停止且通信健康时等待当前写入确认，最多再发一次 READY，确认该次写入后结束。通信故障时不继续发送位置命令，断连或强制退出不能保证自动松键。软件停止不等同于机械急停。

实机验收须逐项记录：远离琴键核对方向和 READY；定位后 C4～G4 各连续按下、发声、抬起三次且无相邻键误触；单独验证 E/E 和 C/C；运行上述整段命令三次，人工确认均无漏音、串键、持续压键；验证主动停止和驱动故障后不再继续演奏。只有全部完成才记录“单手《欢乐颂》人工听音验收通过”。当前 YAML 的 `verified` 标记与一次指令播放记录不能替代上述听音验收，MIDI 自动闭环留待下一阶段。


### 调整姿态与重新标定

1. 先远离琴键，用设备实际支持的工具确认低速和输出约束，核对运动方向。仓内调试 GUI 和 ROS 播放器都只发位置，`JointState.velocity/effort` 不提供限速或限力；若使用直接占用串口的厂商工具，完成设置后关闭它，再启动仓内 GUI。
2. 用示教器固定手腕，检查五指能否同时覆盖五个白键。候选对应是拇指 C、食指 D、中指 E、无名指 F、小指 G；实际映射须按安装朝向和指尖位置确认。不能覆盖时先调整安装或示教姿态。
3. 在仓内 GUI 的右手页面加载需要编辑的姿态文件，记录并保存 `READY` 与 `PRESS_C`～`PRESS_G` 六组完整**目标命令值**。每组 `positions` 必须恰好 20 个有限的 `0–255` 数值，顺序为 ROOT × 5、YAW × 5、ROLL × 5、TIP × 5，各组从拇指到小指。不要手工复制未经校验的原始反馈或 30 寄存器数组，不要截断越界值；GUI 自动对齐只采用校验后的有效位置，预留槽位填 0，仍需逐键验证后保存并标记。
4. 仓内 GUI 通过 ROS 控制，可与其启动的驱动同时使用；直接占用串口的厂商 GUI 必须与 ROS 驱动交替使用。先填入 READY 和一个 PRESS，保存后关闭双手 GUI 及其驱动，再用上文单键模式验证。已填写但 `verified: false` 的姿态可用于单键测试；逐键验证后人工标记相应 `verified: true`，整段演奏要求六组全部有效且已确认。

## MIDI 播放与反馈

### 仿真 MIDI 与反馈


目标链路为：MIDI 文件 → 音符调度与左右分配 → 双臂 MoveIt 轨迹 → L20 手指命令 → 数字钢琴 MIDI 反馈。

第一阶段将 MIDI 音符 `21–59` 分给左手、`60–108` 分给右手，每只手同时只允许一个活动音符；同手和弦在执行前拒绝。默认 `execute=false`，先在仿真中检查 MIDI 文件与配置：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid \
  headless:=true use_rviz:=false execute:=false
```

此入口已包含 MuJoCo 场景，使用前停止单独运行的场景入口，避免重复启动控制器。仿真使用 [piano_midi_sim.yaml](../src/ros2_rm_robot/rm_piano_player/config/piano_midi_sim.yaml)，并从场景配置生成 52 白键、36 黑键对应的位置表。确认坐标与单键动作后才使用 `execute:=true`；`tempo_scale` 是时间倍率，数值越大播放越慢。

数字钢琴反馈通过 `midi_input:=<端口名称>`、`feedback_enabled:=true` 启用，默认时间容差 `feedback_tolerance_sec:=0.15`。反馈状态发布到 `/robopianist/feedback_status`；发现漏键、错键或超时后停止后续动作。实现与参数见 [MIDI 播放器说明](../src/ros2_rm_robot/rm_piano_player/README_CN.md)。

### 完整真机入口

仅查看启动参数、不连接设备：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py --show-args
```

停止独立双臂、双手入口后，启动完整链路。此入口仍默认 UDP 上位机为 `.10`，必须为当前主机显式传入 `.100`：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=192.168.1.100 right_udp_ip:=192.168.1.100 \
  left_hand_port:=auto right_hand_port:=auto \
  hand_joint:=L20-11 execute:=false
```

**此处 `execute:=false` 只禁止播放器动作，仍会连接硬件，也不禁止从 RViz 等其他客户端发起运动。** 两手身份与首帧状态均通过后才启动双臂；10 秒未就绪或双手进程退出会终止启动。真机使用 [piano_midi.yaml](../src/ros2_rm_robot/rm_piano_player/config/piano_midi.yaml)，琴键、工具和指尖坐标必须根据实物标定。

完整实机验收顺序：核对手部 UID 与标签 → 停止驱动、交换 USB 插入顺序后确认归属不变 → 验证缺手时拒绝启动和双手状态 → 双臂单键接近 → 双手单音阶 → 低速曲目 → MIDI 反馈。软件停止后续命令不等同于机械急停。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| `/joint_states` 提示未发布，无法判断类型 | 先确认已加载正确工作空间且各终端 ROS 域一致；仿真检查状态广播器和仿真进程；真机分别查看两臂话题，若两臂都有数据而合并话题没有，再查合并节点 |
| 控制器都是 `active`，但 RViz / MuJoCo 不同步 | 检查 `/joint_states` 是否持续更新、是否误启多套入口；RViz 的轨迹预览与当前状态要分开判断 |
| 点击执行没有动作 | 确认先从 `<current>` 成功规划，目标与当前姿态不同，再看执行结果；真机若设置了 `allow_trajectory_execution:=false`，执行被主动关闭 |
| 直接启动右手播放器，手没有动 | 默认 `execute:=false`、`mode:=pose_test`；真机演奏需显式传入 `execute:=true mode:=melody` |
| 修改了姿态，但播放器仍使用旧数值 | 将 `pose_config` 指向本文给出的源码绝对路径；主目录副本和安装目录文件可能不同 |
| 单手播放提示串口占用或驱动来源不唯一 | 先退出双手驱动、调试 GUI 和其他手部播放器；单手入口会自行启动右手驱动 |
| L20 报 `Permission denied`，随后提示缺少左右手 | 执行 `sudo chmod 777 /dev/ttyUSB0 /dev/ttyUSB1` 后重新启动；重新插拔或重启后可能需要再次设置。串口尚未打开时，不能据此判断手部 UID 错误 |
| L20 报 `Input/output error`，内核同时出现 `ch341` / USB 控制传输失败 | 先查看 `sudo dmesg --ctime`；本机曾出现两个转接器同一 Hub 下控制传输 `-110`。停止驱动后重新插拔，优先使用主机直连 USB 口，核对新的串口编号并重新设置权限。该错误不能仅靠 `chmod` 解决，也不能据此认定 UID 错误 |
| 真机连接不上或只有一侧反馈 | 核对机械臂 IP、上位机 `.100`、UDP `8089/8090` 与网卡配置，确认没有其他驱动占用设备；保留 TCP/UDP 错误日志 |
| `Node() got multiple values for keyword argument 'condition'` | 当前源码已修复 RViz 启动条件重复传参；重新构建 `rm_75_config rm_bringup`，加载当前 `install/setup.bash` |
| 合并节点退出码 `127` 或出现 `python3\r` | 当前源码已将桥接脚本改为 LF 换行；重新构建 `rm_description` 并加载安装环境 |
| RViz 中底座仍横放或间距未更新 | 确认使用当前真机入口并重新加载构建环境、重启；仿真布局由独立场景配置决定 |
| 退出时出现 `move_group` / 控制器进程段错误 | 仍有退出路径问题，不能据此认定整套链路稳定；保留日志并确认进程已经退出后再重启 |

### L20 第一次启动成功，退出后再次启动报 I/O 错误

2026-10-22 在本机复现：双手首次 UID 和状态读取正常，驱动正常退出且没有串口占用后，第二次打开两路串口均报 `Errno 5`。内核同时记录 `ch341` 控制传输超时 `-110`。不运行 ROS、不发送 Modbus 数据，仅用 pyserial 打开、关闭串口也能复现。因此不能把这次故障归为 ROS 残留或 UID 配置错误；具体是 Hub、转接器还是主机 USB 驱动的问题仍待排查。取消串口 `HUPCL` 和关闭该 Hub 自动省电均未解决问题，自动省电已恢复原设置。

实机只读验证：每次启动前重置上述 Hub，连续 3 轮、每轮观察 25 秒均通过；左手分别收到 128/130/130 帧，右手 129/131/131 帧，启动就绪后未丢失就绪状态，三次均正常退出。测试未发送位置或配置命令，不代表实际运动验收通过。

临时恢复步骤：

1. 在启动窗口按 `Ctrl+C`，等驱动退出。执行 `sudo fuser -v /dev/ttyUSB0 /dev/ttyUSB1`，确认没有占用进程；设备编号变化时替换为当前路径。
2. 执行 `lsusb -t`，确认双手转接器所在 Hub。仅当该 Hub 下只有两只手的转接器、所有相关程序均已停止时，重置该 Hub。2026-10-22 的验证使用 Bus `001`、Hub Dev `019`，这是历史地址，不能直接沿用。确认当前地址后使用 `sudo usbreset BUS/DEV`（将 `BUS/DEV` 替换为实际值）。**2026-10-23 检查时 USB 拓扑已变化；每次都须重新确认，不要重置键鼠或其他设备所在 Hub。** 不确定拓扑时，停止驱动后手动拔插双手转接器。
3. 等待两个串口重新出现，执行 `sudo chmod 777 /dev/ttyUSB0 /dev/ttyUSB1`，再启动：

   ```bash
   ros2 launch rm_l20_driver l20_dual_rs485.launch.py \
     left_hand_port:=auto right_hand_port:=auto hand_joint:=L20-11
   ```

4. 保持启动终端运行，在另一终端加载相同 ROS 环境和域后，检查 `/l20/hands_ready` 为 `true`，且 `/cb_left_hand_state`、`/cb_right_hand_state` 持续更新。按 `Ctrl+C` 退出驱动后，这些话题便不再由它发布。

重置后串口编号可能交换，继续使用 `auto` 按完整 UID 识别左右手。此流程是通信恢复办法，不能视为重连故障已根治；下一步应将转接器接到主机直连 USB 口，避开当前外置 Hub，再重复退出、重启验证。

## 工程结构

源码位于 `src/ros2_rm_robot/`，在仓库根目录构建。

| 功能包 | 源码位置 | 用途 |
| --- | --- | --- |
| `rm_description` | [rm_description](../src/ros2_rm_robot/rm_description/) | RM75-6FB-V 网格、URDF 和双臂描述 |
| `rm_75_config` | [rm_moveit2_config/rm_75_config](../src/ros2_rm_robot/rm_moveit2_config/rm_75_config/) | `left_arm`、`right_arm`、`dual_arms` 的 MoveIt 配置 |
| `rm_mujoco` | [rm_mujoco](../src/ros2_rm_robot/rm_mujoco/) | 双臂双手模型、桌琴场景、仿真控制器 |
| `rm_driver` | [rm_driver](../src/ros2_rm_robot/rm_driver/) | 睿尔曼真机驱动 |
| `rm_control` | [rm_control](../src/ros2_rm_robot/rm_control/) | MoveIt 到机械臂驱动的轨迹转发 |
| `rm_bringup` | [rm_bringup](../src/ros2_rm_robot/rm_bringup/) | 双 RM75 真机启动入口 |
| `rm_l20_driver` | [rm_l20_driver](../src/ros2_rm_robot/rm_l20_driver/) | L20-11/L20-10 RS485 协议、身份识别和 ROS 节点 |
| `rm_piano_player` | [rm_piano_player](../src/ros2_rm_robot/rm_piano_player/) | MIDI 调度、双臂规划、双手命令、MIDI 反馈 |
| `rm_ros_interfaces` | [rm_ros_interfaces](../src/ros2_rm_robot/rm_ros_interfaces/) | ROS 消息和服务 |
| `rm_moveit2` | [rm_moveit2](../src/ros2_rm_robot/rm_moveit2/) | MoveIt 示例节点 |

标有 `COLCON_IGNORE` 的历史示例、Gazebo 和旧安装目录不进入当前构建。仿真使用 `rm_mujoco` 自带的 L20 模型；真机使用仓内 `rm_l20_driver`，无需外部灵心巧手 SDK。

## 验证记录与限制

### 复现软件检查

在工作空间根目录加载环境后执行：

```bash
colcon test
colcon test-result --verbose
```

仅检查最近修改的真机启动描述和安装变换：

```bash
colcon build --packages-select rm_75_config rm_bringup
colcon test --packages-select rm_75_config
colcon test-result --test-result-base build/rm_75_config --verbose
```

这组测试只构造启动描述和机器人模型，不连接硬件。

### 2026-10-23 右手《欢乐颂》真机指令播放

- 使用当时版本的源码 YAML（更新 `new.yaml` 准备姿态和缩小幅度之前），六组姿态 `verified: true`，拇指 `PRESS_C` 的 `05` 槽位为 `113.0`。先完成不连接硬件的预览，再正常退出双手驱动和调试 GUI，启动单手入口。
- 识别右手 UID `LHT20-011-266-R-B-1-D`，本次端口为 `/dev/ttyUSB0`。依次完成 `E E F G G F E D C C D E E D D`，15 次按压均收到写入确认，最终 READY 写入确认，状态为 `completed`，播放器和驱动均正常退出。
- 时间参数为按压 `0.5 s`、释放 `0.5 s`、准备等待 `1.0 s`。本次未发送机械臂或左手运动命令，未采集钢琴 MIDI 或音频；不能据此认定琴键全部发声或听音验收通过。
- 本机日志：`.validation/ode_to_joy_real_20261023.log`。这是本机验证产物，新克隆仓库不保证包含。该记录证明一次执行完成，不代表串口反复启动和整个系统稳定性已验收。

### 2026-10-22 双臂反馈与安装模型

- 真机双臂反馈测试通过：左右臂分别收到 2780、2783 条关节消息，合并收到 5556 条，含完整 14 个关节；MoveIt 与反馈的最大关节差约 `5.23e-5 rad`。测试未发送运动轨迹。
- 上述反馈验证使用无界面模式，发生在直立安装和 70 cm 间距修改之前。之后的模型与启动条件检查共 5 个 Pytest 用例通过，未进行新的真机运动验证。
- 本机记录位于 `.validation/dual_bringup_feedback_results.json`、`.validation/dual_bringup_feedback.log`；离线测试日志为 `build/rm_75_config/ament_cmake_pytest/test_real_moveit_launch.txt`。这些是本机验证产物，新克隆仓库不保证包含。
- 单臂诊断曾出现间歇性 TCP `-2` 接收/响应超时；后续有限时长双臂反馈测试未复现，仍需继续观察。GUI 稳定性尚未完整验证。

### 历史仿真与单手软件验证

2026-10-21 的 Jetson 桌琴场景验证记录：全部 10 个包构建通过；11 项场景/几何/动力学测试、C++ 键位映射测试和 2 项 MIDI 反馈测试通过。无头运行中五个控制器为 `active`，发布 58 个关节状态；双臂初始状态碰撞检查通过，左右臂和左右手各一次小幅轨迹返回 `error_code=0`，MIDI 干运行通过。详细日志位置见 [场景验证记录](../src/ros2_rm_robot/rm_mujoco/README.md#jetson-验证2026-10-21)。

上述桌琴场景结果属于对应版本。2026-10-22，右手《欢乐颂》功能及 L20 UID 驱动在 Jetson（aarch64 / ROS 2 Humble）的独立目录 `/home/dianjinglab/ros2_ws_single_hand_test_20261022_WQ2CLp` 验证：`rm_l20_driver`、`rm_piano_player` 两包构建通过，最终 `colcon test-result` 为 277 tests、0 errors、0 failures、0 skipped。测试覆盖原双手回归、真实 ROS 假驱动通信，以及安装后 launch 与 Linux PTY 的完整链路；0.1 秒按下/释放配置下实际收到全部 31 条位置写入，末条为 READY，释放间隔完整。

本次测试修复了 Windows 源码复制后脚本缺少执行权限的问题，并确认退出后释放虚拟串口。Jetson 独立目录保留 `build.log`、`build-piano-final.log`、`test.log`、`test-piano-final.log` 和最终 `test-result.log`；前两轮日志保留了发现问题的过程。验证使用假驱动和 `/dev/pts/*`，没有操作真实机械臂或灵巧手，不能代替实机标定、运动和听音验收。

### 当前限制

- 仿真与真机安装坐标尚未统一，真机底座高度、工具、指尖和琴键坐标仍需标定。
- 琴键为固定几何，尚无按键行程、接触传感器或仿真接触 MIDI 反馈。
- MoveIt 当前只规划双臂，未包含 L20 手部碰撞模型；手部在 MuJoCo 中独立控制。
- 键位表提供键面坐标，播放器仍使用机械臂工具端目标；完整曲目执行尚未验证。
- 场景使用重力补偿近似位置伺服保持，不代表真实电机力矩验证。
- SIGINT 后控制器已停用，但系统安装的 `ros2_control_node`、`move_group` 仍有 ROS 对象析构段错误；运行测试通过不代表退出路径无错误。
- 右手已完成一次真机指令播放；尚未完成机械臂真机运动验收、单手听音验收、真实 MIDI 按键闭环或官方 RoboPianist RL 策略迁移；同手多指和弦、力反馈和接触奖励属于后续阶段。

快速启动见[根目录 README](../README.md)；协议、实现和完整参数请继续查看各功能包的 README。
