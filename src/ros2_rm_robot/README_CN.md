# ros2_rm_robot：RM75-6FB-V 双臂双 L20 仿真

> 本工作区已精简为 RM75-6FB-V 机械臂模型，以及 MuJoCo 双臂双 L20 灵巧手仿真。支持的开发环境为 Ubuntu 22.04 和 ROS 2 Humble。

当前目标功能路径包括：

- MuJoCo 中的两台 RM75-6FB-V 机械臂；
- MoveIt 2 和 RViz 的 `left_arm`、`right_arm`、`dual_arms` 规划组；
- MuJoCo 中的左右 L20 手控制器，以及双手命令桥接节点。

真机目标同样是双臂。仓库中没有 L20 的 RS485 真机驱动，下面的 L20 桥接节点用于 MuJoCo 控制器。真机入口会分别启动左右 RM75 驱动、控制节点、双臂状态桥接和双臂 MoveIt/RViz。

## 功能包

| 功能包 | 用途 |
| --- | --- |
| `rm_description` | RM75-6FB-V URDF、网格和双臂描述 |
| `rm_75_config` | RM75-6FB-V MoveIt 配置和双臂 SRDF |
| `rm_mujoco` | 双 RM75、双 L20 的 MuJoCo 模型、控制器和启动文件 |
| `rm_driver` | 睿尔曼机械臂驱动 |
| `rm_control` | MoveIt 到机械臂驱动的轨迹转发 |
| `rm_bringup` | RM75-6FB-V 真机启动入口 |
| `rm_moveit2` | MoveIt 示例节点 |
| `rm_ros_interfaces` | ROS 消息和服务 |
| `rm_piano_player` | MIDI 曲目、双臂规划、双 L20 命令和 MIDI 反馈 |

带有 `COLCON_IGNORE` 的历史示例和 Gazebo 源码不属于当前构建路径。

## 编译

在 Ubuntu 22.04、ROS 2 Humble 环境中执行：

```bash
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

MuJoCo 启动依赖外部的 `mujoco_ros2_control`，以及 MoveIt 2、RViz 2、`xacro` 和 ROS 2 控制器相关功能包。

## 启动双臂双手 MuJoCo

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

常用启动参数：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py headless:=true
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py use_rviz:=false
```

> 启动文件会启动 robot_state_publisher、MuJoCo ROS 2 control、左右机械臂控制器、左右 L20 控制器、MoveIt 2 和 RViz。MoveIt SRDF 提供 `left_arm`、`right_arm`、`dual_arms` 三个规划组。L20 关节目前通过轨迹控制器仿真和控制，尚未加入 MoveIt SRDF 规划组。

## 发送 L20 手命令

`l20_dual_command_bridge.py` 订阅：

- `/cb_left_hand_control_cmd`
- `/cb_right_hand_control_cmd`

两个话题都使用 `sensor_msgs/msg/JointState`，`position` 至少包含 20 个值，取值范围为 `0` 到 `255`。桥接节点将命令转换为 L20 关节轨迹并发布到：

- `/left_l20_hand_controller/joint_trajectory`
- `/right_l20_hand_controller/joint_trajectory`

MuJoCo 模型中包含左右两只 L20 手。MoveIt 使用的双臂 URDF 当前只包含两条机械臂，不包含 L20 的 link，因此 RViz 显示和规划的是双臂，手部通过桥接节点单独控制。

## RoboPianist 风格 MIDI 播放

当前第一阶段目标是使用 88 键 MIDI 数字钢琴播放固定曲目：MIDI 文件按 `21–59` 分给左手、`60–108` 分给右手，双 RM75 使用 `left_arm` 和 `right_arm` 规划组，L20 通过 20 值控制话题发送指法。第一阶段每只手只允许一个活动音符，同手和弦会在启动前拒绝。

MuJoCo 播放入口：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid headless:=true use_rviz:=false execute:=false
```

真机入口默认使用左臂 `192.168.1.18`、右臂 `192.168.1.19`，左手 `/dev/ttyUSB0`、右手 `/dev/ttyUSB1`，L20 参数为 `L20-11`：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid execute:=false
```

数字钢琴 MIDI 输入端口通过 `midi_input:=<port-name>` 指定，`feedback_enabled:=true` 后会检查漏键、错键和超时；`tempo_scale` 是时间倍率，数值越大播放越慢。当前方案是 RoboPianist 风格的硬件行为复现，尚未直接迁移 Shadow Hand RL 策略，也尚未加入琴键接触奖励和力反馈。

## 双臂真机启动

默认按左臂 `192.168.1.18`、右臂 `192.168.1.19` 配置；如果现场地址不同，请在启动时覆盖：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19
```

默认 UDP 回传端口为左臂 `8089`、右臂 `8090`，本机回传地址默认为 `192.168.1.10`。如果机械臂控制器中的 UDP 配置不同，请在启动时覆盖：

```bash
ros2 launch rm_bringup rm_75_6fb_v_bringup.launch.py \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_udp_ip:=<上位机IP> right_udp_ip:=<上位机IP> \
  left_udp_port:=<左臂UDP端口> right_udp_port:=<右臂UDP端口>
```

启动流程使用 `left_arm` 和 `right_arm` 命名空间隔离两套 driver/control，并将两路 `joint_states` 合并到 `/joint_states` 供双臂 URDF、MoveIt 和 RViz 使用。L20 的 RS485 真机驱动仍不在本仓库中，需要单独接入 `/dev/ttyUSB0` 和 `/dev/ttyUSB1`。

使用真机前，请先在 Ubuntu/ROS 2 Humble 上编译并检查两台机械臂的 IP、UDP 回传地址和端口；当前工作区只能完成静态检查，尚未进行真机运动验证。

## 验证

Windows 工作区无法运行 ROS 2 和 `colcon`。在 Ubuntu 上部署前执行：

```bash
colcon test
colcon test-result --verbose
```

建议先关闭 RViz 启动 MuJoCo，确认左右机械臂控制器和左右手控制器正常，再启用 RViz。
