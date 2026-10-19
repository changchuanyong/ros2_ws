# QWEN.md

本文件为后续交互提供指令性上下文。

## 项目概述

这是一个面向 **Ubuntu 22.04 / ROS 2 Humble / Python 3.10+** 的 **ROS 2 工作空间**
（`ros2_ws`）。`src/` 下保留 RealMan 机器人代码库，核心目标是运行 RM75-6FB-V 机械臂与
L20 灵巧手组合的 **MuJoCo** 仿真：

- **`src/ros2_rm_robot/`** — 当前只构建 RM75-6FB-V 双臂相关功能；其他型号源码保留但不进入默认构建。

当前工作分支为 `humble`。`src/RM75-L20转接法兰(3).stp` 是 RM75→L20 转接法兰（机械臂与
手之间的机械接口）的 STEP 三维模型。

### 包结构一览（`ros2_rm_robot`）

| 包名 | build_type | 作用 |
|---|---|---|
| `rm_ros_interfaces` | ament_cmake | 自定义控制/状态消息与服务（**必须最先编译**） |
| `rm_driver` | ament_cmake | 底层硬件驱动（与机械臂控制器建立 TCP 连接，`config/*.yaml`） |
| `rm_description` | ament_cmake | URDF/xacro 模型、网格（mesh）、关节状态 |
| `rm_bringup` | ament_cmake | RM75-6FB-V 真机启动入口 |
| `rm_control` | ament_cmake | MoveIt2 规划与 `rm_driver` 之间的桥接 |
| `rm_moveit2` / `rm_moveit2_config` | ament_cmake | MoveIt2 示例 + 各机型 MoveIt 配置包 |
| `rm_gazebo` | — | 当前通过 `COLCON_IGNORE` 排除 |
| `rm_mujoco` | ament_cmake | **MuJoCo（`mujoco_ros2_control`）仿真——仅支持 RM75-6FB-V** |
| `rm_piano_player` / `rm_example` / `rm_arm_examples` | — | 当前通过 `COLCON_IGNORE` 排除 |
| `rm_install` / `rm_doc` | — | 当前通过 `COLCON_IGNORE` 排除 |

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
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py  # RM75-6FB-V 真机
```

当前默认只保留 RM75-6FB-V 入口：`rm_75_6fb_v_bringup.launch.py`。

### 运行 MuJoCo RM75-6FB-V + L20 手仿真（`rm_mujoco`）

```bash
# 双臂双手和 MoveIt/RViz
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py headless:=true
```

双臂入口启动左右两套 RM75-6FB-V、左右 L20、
MoveIt 和可选 RViz。L20 网格、MuJoCo XML 和控制桥接均位于 `rm_mujoco` 内。

## 开发约定

- **语言：** 以 Python（`rclpy`）和 C++（`rclcpp`）为主；用 `colcon` 构建。
- **可执行脚本：** 入口脚本安装到 `share/${PROJECT_NAME}` 下，可执行文件安装到
  `lib/${PROJECT_NAME}` 下（参见 `rm_mujoco/CMakeLists.txt`、`setup.cfg`）。
- **launch 文件：** 使用 `launch` / `launch_ros` 的 Python launch（`*.launch.py`）；
  机器人描述用 xacro。
- **包清单：** ROS 包使用 `ament_cmake`。
- **README 中的注释/配置**中英混杂；编辑已有配置（如 `rm_driver/config/*.yaml`）时
  保留双语注释。

## 重要配置说明

- **`rm_driver/config/rm_75_config.yaml`** — `arm_ip` 决定物理控制器的 TCP 地址，当前
  设为 `192.168.1.18`（原为 `192.168.1.19`）。运行真机 bringup 前务必确认 IP 与目标
  机械臂一致；每台机器都可能需要修改。
- **MuJoCo 模型**仅针对 RM75-6FB-V 双臂双 L20；手部 mesh 位于
  `rm_mujoco/meshes/l20_right/`，臂部 mesh 位于 `rm_mujoco/meshes/rm_75_6fb_v/`。
  MuJoCo XML 模型为 `rm_mujoco/models/rm_75_6fb_v_dual_l20.xml`。

## 安全

RealMan 机械臂操作守则：每次使用前检查安装/螺丝是否紧固，机械臂工作范围和倾倒范围内
不得有人或物体，闲置时将机械臂停到安全位置，不用时及时断电。

## 参考

- 上游：`RealManRobot/ros2_rm_robot`（`humble` 分支）。
- 各包详细文档位于 `src/ros2_rm_robot/rm_doc/`。
