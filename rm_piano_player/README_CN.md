# RM75-6FB 钢琴控制示例

该功能包是基于当前 RM75-6FB MoveIt 仿真的第一版钢琴任务程序。它先使用 YAML 中的琴键坐标和音符序列，依次执行“琴键上方 → 下压 → 保持 → 抬起”。

## 运行

也可以用一个命令同时启动 RM75-6FB 仿真、MoveIt、RViz、8 键模型和钢琴节点：

```bash
ros2 launch rm_piano_player piano_demo.launch.py
```

这个命令默认 `execute=false`，会显示键盘并进行干运行。确认坐标后才使用：

```bash
ros2 launch rm_piano_player piano_demo.launch.py execute:=true
```

先启动官方 RM75-6FB Gazebo 与 MoveIt：

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_bringup rm_75_6fb_gazebo.launch.py
```

另开终端，先做干运行检查：

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 launch rm_piano_player piano_player.launch.py
```

干运行默认 `execute=false`，只打印音符和目标坐标。确认 `config/piano.yaml` 中的琴键坐标、姿态和按压深度后，显式执行：

```bash
ros2 launch rm_piano_player piano_player.launch.py execute:=true
```

## 坐标和安全

- 坐标单位是米，参考系默认是 `base_link`。
- `key_z` 是琴键表面高度；`approach_height` 是上方等待高度；`press_depth` 是下压深度。
- 当前示例坐标只是模板，必须根据钢琴实际位置和末端工具姿态重新标定。
- 这版仿真使用位置轨迹，不模拟真实琴键的六维力反馈。
- 真实 RM75-6FB 使用前应增加力传感器接触检测、最大力保护、急停和柔性末端。
