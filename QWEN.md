# QWEN.md

本文件为后续交互提供指令性上下文。

## 项目概述

这是一个面向 **Ubuntu 22.04 / ROS 2 Humble / Python 3.10+** 的 **ROS 2 工作空间**
（`ros2_ws`）。`src/` 下集成了三套厂商机器人代码库，核心目标是将 RealMan（RM）7 自由度
机械臂与 LinkerHand L20 灵巧手组合使用——其中新增了一套将两者耦合起来的 **MuJoCo**
仿真：

- **`src/ros2_rm_robot/`** — RealMan 机械臂 ROS 2 支持包（RM65、RM75、ECO62/63/65、
  RML63、GEN72、RX75 系列）。上游版本 V1.7.0，控制器版本 1.7.3。
- **`src/linkerhand-ros2-sdk/`** — LinkerHand 灵巧手 ROS 2 SDK（O6/L6/L7/O7/L10/L20/
  G20/L21/L25）。基于 Python，支持 CAN / RS485-MODBUS / 透传 CAN 三种通信方式。SDK V3.x。
- **`src/linkerhand-sim/`** — LinkerHand 仿真示例，覆盖 MuJoCo、PyBullet、Isaac-Gym
  （其中混合了 ROS 1 Noetic 与 ROS 2 Jazzy 两种目标环境）。

当前工作分支为 `humble`。`src/RM75-L20转接法兰(3).stp` 是 RM75→L20 转接法兰（机械臂与
手之间的机械接口）的 STEP 三维模型。

### 包结构一览（`ros2_rm_robot`）

| 包名 | build_type | 作用 |
|---|---|---|
| `rm_ros_interfaces` | ament_cmake | 自定义控制/状态消息与服务（**必须最先编译**） |
| `rm_driver` | ament_cmake | 底层硬件驱动（与机械臂控制器建立 TCP 连接，`config/*.yaml`） |
| `rm_description` | ament_cmake | URDF/xacro 模型、网格（mesh）、关节状态 |
| `rm_bringup` | ament_cmake | 各机型 launch 文件（`*_bringup.launch.py`、`*_gazebo.launch.py`） |
| `rm_control` | ament_cmake | MoveIt2 规划与 `rm_driver` 之间的桥接 |
| `rm_moveit2` / `rm_moveit2_config` | ament_cmake | MoveIt2 示例 + 各机型 MoveIt 配置包 |
| `rm_gazebo` | ament_cmake | Gazebo 仿真（gz_ros2_control） |
| `rm_mujoco` | ament_cmake | **MuJoCo（`mujoco_ros2_control`）仿真——仅支持 RM75-6FB-V** |
| `rm_piano_player` | ament_cmake | RM75-6FB 基于 MoveIt 的弹钢琴 C++ 示例 |
| `rm_example` / `rm_arm_examples` | ament_cmake | 基础控制/运动示例 |
| `rm_install` | ament_cmake | 环境安装脚本（`ros2_install.sh`、`moveit2_install.sh`） |
| `rm_doc` | ament_cmake | 文档 |

## 构建与运行

以下命令以 Bash/Linux 为准；该工作空间需在 Ubuntu 上用 ROS 2 Humble 构建，目前是在
Windows 上检出用于编辑。

### 构建整个工作空间

```bash
cd ~/ros2_ws            # 本仓库根目录本身就是一个含 src/ 的工作空间
colcon build --packages-select rm_ros_interfaces   # 先编译消息包
source ./install/setup.bash
colcon build            # 再编译其余部分
source ./install/setup.bash
```

### 环境前置条件（`ros2_rm_robot`）

```bash
sudo bash src/ros2_rm_robot/rm_install/scripts/ros2_install.sh      # ROS 2 Humble
sudo bash src/ros2_rm_robot/rm_install/scripts/moveit2_install.sh   # MoveIt2
sudo bash src/ros2_rm_robot/rm_driver/lib/lib_install.sh            # 驱动库
```

### 运行机械臂

```bash
source ./install/setup.bash
ros2 launch rm_bringup rm_<arm_type>_gazebo.launch.py   # 仿真机械臂（Gazebo）
ros2 launch rm_bringup rm_<arm_type>_bringup.launch.py  # 真实机械臂
```

`<arm_type>` 取值 ∈ `65`、`75`、`63`、`63_III`、`eco62`、`eco63`、`eco65`、`gen72`、
`gen72_II`，以及双臂 `rx75_6fb` / `rx75_6fb_v`。RM75-6FB-V 使用
`rm_75_6fb_v_bringup.launch.py`。

### 运行 MuJoCo RM75 + L20 手仿真（`rm_mujoco`）

```bash
ros2 launch rm_mujoco rm_75_6fb_v_l20_right_mujoco.launch.py
```

该 launch 会启动 `robot_state_publisher`、`mujoco_ros2_control`（`ros2_control_node`），
延时 2 秒后 spawn `joint_state_broadcaster` + `rm_group_controller`（手臂，7 个关节）+
`l20_hand_controller`（手，20 个关节），并运行 `l20_right_command_bridge.py`，它会把手指
令重新发布到 `/l20_hand_controller/joint_trajectory`。需要外部 `mujoco_ros2_control`
包可用。另有仅机械臂版本（`rm_75_6fb_v_mujoco.launch.py`）。

### 运行 LinkerHand SDK

```bash
sudo apt install python3-can python3-pyqtgraph
pip install -r src/linkerhand-ros2-sdk/requirements.txt
# 先使能 CAN 口：
sudo /usr/sbin/ip link set can0 up type can bitrate 1000000
cd src/linkerhand-ros2-sdk
colcon build --symlink-install && source ./install/setup.bash
ros2 launch linker_hand_ros2_sdk linker_hand.launch.py         # 单手
ros2 launch linker_hand_ros2_sdk linker_hand_double.launch.py  # 双手
```

## 开发约定

- **语言：** 以 Python（`rclpy`）和 C++（`rclcpp`）为主；用 `colcon` 构建。
- **Python 风格（linkerhand-ros2-sdk）：** `ruff.toml` 配置了 Ruff linter，选择
  `E4, E7, E9, F, I, B`（pyflakes、pycodestyle 子集、import 排序、bugbear）。提交 SDK
  的 Python 改动前先运行 `ruff check`。
- **可执行脚本：** 入口脚本安装到 `share/${PROJECT_NAME}` 下，可执行文件安装到
  `lib/${PROJECT_NAME}` 下（参见 `rm_mujoco/CMakeLists.txt`、`setup.cfg`）。
- **launch 文件：** 使用 `launch` / `launch_ros` 的 Python launch（`*.launch.py`）；
  机器人描述用 xacro。
- **包清单：** ROS 包使用 `ament_cmake`；linkerhand Python 包使用 `setup.py` +
  `pyproject.toml` + `setup.cfg`。
- **README 中的注释/配置**中英混杂；编辑已有配置（如 `rm_driver/config/*.yaml`）时
  保留双语注释。

## 重要配置说明

- **`rm_driver/config/rm_75_config.yaml`** — `arm_ip` 决定物理控制器的 TCP 地址，当前
  设为 `192.168.1.18`（原为 `192.168.1.19`）。运行真机 bringup 前务必确认 IP 与目标
  机械臂一致；每台机器都可能需要修改。
- **LinkerHand `setting.yaml`** — 默认系统 PASSWORD 为 `12345678`（SDK 用它自动使能
  CAN 口）；`MODBUS` 字段选择 RS485 设备（如 `/dev/ttyUSB0`）或 `"None"`。
- **MuJoCo 模型**仅针对 RM75-6FB-V；手部 mesh 位于 `rm_mujoco/meshes/l20_right/`，
  臂部 mesh 位于 `rm_mujoco/meshes/rm_75_6fb_v/`。MuJoCo XML 模型为
  `rm_mujoco/models/rm_75_6fb_v_l20_right.xml`。

## 安全

RealMan 机械臂操作守则：每次使用前检查安装/螺丝是否紧固，机械臂工作范围和倾倒范围内
不得有人或物体，闲置时将机械臂停到安全位置，不用时及时断电。

## 参考

- 上游：`RealManRobot/ros2_rm_robot`（`humble` 分支）、`linker-bot/linkerhand-ros2-sdk`。
- 各包详细文档位于 `src/ros2_rm_robot/rm_doc/`。
