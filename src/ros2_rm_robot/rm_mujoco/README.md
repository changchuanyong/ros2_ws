# RM75 双臂双 L20 桌面钢琴场景

默认场景参照实验室照片：两台 RM75-6FB-V 直立固定在木桌上，弯臂朝向木色
88 键电钢琴，L20 指尖向下悬停。包含桌腿、底板、琴架、谱架、踏板和简化背景。

## 启动与预览

在 Ubuntu 22.04 / ROS 2 Humble 工作空间中：

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py
```

SSH 中检查控制器使用 `headless:=true use_rviz:=false`。离屏渲染不启动 ROS
控制器或硬件，使用实际 MuJoCo 模型和 `piano_ready` 初始姿态：

```bash
MUJOCO_GL=egl python3 -m rm_mujoco.render --output /tmp/piano_scene.png
MUJOCO_GL=egl python3 -m rm_mujoco.render --camera front --output /tmp/piano_front.png
```

交互窗口默认聚焦桌琴区域，另有 `overview` 和 `front` 固定相机。
这两个观察相机不自动发布 ROS 图像流，避免无头运行时额外启动 EGL 相机线程。

## 调整尺寸

`config/piano_scene.yaml` 是仿真布局的共同来源。坐标约定为 x 沿低音到高音、
y 从机械臂朝向钢琴、z 向上；尺寸单位为米，关节角为弧度。

| 项目 | 默认近似值 |
| --- | --- |
| 桌面 | 1.75 × 0.80 m，高 0.75 m |
| 底座中心间距 | 0.64 m |
| 两臂底座 | x=±0.32、y=-0.28、z=0.76 m，直立安装 |
| 白键表面 | z=0.74 m |
| 白键宽度节距 | 23.6 mm |
| 黑键高度 | 高出白键 12 mm |

这些数值是照片布局的近似值，不是实机测量结果。改变桌高/底座位置后应同步
调整 `initial_positions` 并重新检查可达性和碰撞；姿态不会自动求逆运动学。
可复制 YAML 后通过参数选择：

```bash
ros2 launch rm_mujoco rm_75_dual_l20_mujoco.launch.py scene_config:=/absolute/path/piano_scene.yaml
```

启动时从模板生成临时 MJCF 和木纹贴图，退出时清理。相同配置生成 MoveIt/RViz
的桌琴可视与碰撞几何，底板作为固定安装件仅显示。`piano_ready` 同时用于
MuJoCo/ros2_control 的初始关节位置和 MoveIt 的命名姿态。模板 XML 中的旧安装
位置由生成器覆盖，不是默认启动后的布局。

生成场景为机械臂和手部启用重力补偿，以模拟位置伺服保持弯臂姿态；质量、
惯量和接触仍参与动力学。这是场景控制近似，不作为真实电机力矩验证。

键盘按 52 白键、36 黑键构造，黑键位于对应白键之间。仿真 MIDI 入口读取同一
配置生成 88 个 `key_positions`，不采用按半音等距的近似位置：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid execute:=false
```

琴键目前是固定几何，没有琴键行程或 MIDI 接触反馈。MoveIt URDF 仍仅规划
双臂，L20 在 MuJoCo 中由手部控制器控制，未加入 MoveIt 的手部碰撞模型。
键位表提供琴键表面坐标，播放器仍使用机械臂工具端目标；实际按键还需要
指尖/工具坐标标定。场景与控制器验证不代表完整曲目已能演奏。

## Jetson 验证（2026-10-21）

在 `/home/dianjinglab/ros2_ws_rm75_02d70d1` 完成全部 10 个包构建。
11 项场景/键位几何/动力学测试、C++ 键位映射测试及 2 项 MIDI 反馈测试通过。
无头运行中 5 个控制器均为 `active`，发布 58 个关节状态；双臂启动姿态误差
小于 0.00001 rad，MoveIt 初始状态碰撞检查通过。左右臂、左右手各一次小幅
轨迹执行均返回 `error_code=0`；双手 MIDI 示例在 `execute=false` 下通过。

日志保存在该 Jetson 工作区 `.validation/photo_scene_build.log`、
`photo_scene_final_pytest.log`、`photo_scene_tests.log` 和
`photo_scene_verification.json`。预览使用实际 MuJoCo 模型离屏渲染。

已知退出限制：SIGINT 后五个控制器完成停用，但系统安装的 `ros2_control_node`
和 `move_group` 在 ROS 对象析构时仍出现段错误（`exit code=-11`）。当前日志
分别指向 `rclcpp::Executor` 和 `rclcpp::CallbackGroup` 析构；本次未修改系统库。
检查结束后确认没有遗留仿真进程或临时场景目录。运行通过不代表退出路径无错误。
