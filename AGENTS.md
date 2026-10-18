# Repository Guidelines

## 项目结构

本仓库是 ROS 2 工作空间，所有功能包源码放在 `src/` 下：

- `src/ros2_rm_robot/`：RealMan 机械臂驱动、接口、模型描述、MoveIt、Gazebo、MuJoCo、示例和启动文件。
- `src/linkerhand-ros2-sdk/`：Python 版 LinkerHand SDK、ROS 功能包、GUI 工具和硬件示例。
- `src/linkerhand-sim/`：LinkerHand 的 MuJoCo、PyBullet 和 Isaac Gym 仿真。
- 共享模型与资源包括 URDF/xacro、网格、YAML 配置、启动文件和 RM75–L20 STEP 模型。

## 构建、测试与运行

使用 Ubuntu 22.04、ROS 2 Humble 和 Bash。在工作空间根目录执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
colcon test
colcon test-result --verbose
```

使用 `ros2 launch rm_bringup rm_75_gazebo.launch.py` 启动集成机械臂仿真；使用 `ros2 launch rm_mujoco rm_75_6fb_v_l20_right_mujoco.launch.py` 启动 RM75-6FB-V MuJoCo 模型。修改 LinkerHand Python 代码后，应先在 `src/linkerhand-ros2-sdk/` 执行 `ruff check`，再构建。

## 编码风格与命名

遵循现有 C++ `rclcpp` 和 Python `rclpy` 风格。Python 使用四个空格缩进，C++ 使用项目已有格式；Python 标识符采用 `snake_case`，功能包和节点使用清晰名称。ROS 启动文件必须使用 `*.launch.py` 后缀，功能包名称使用小写下划线格式，并保留既有的 `rm_*` 与 `linker_hand_*` 前缀。URDF/xacro、YAML 和双语注释应与相邻文件保持一致，不要格式化无关代码。

## 测试规范

Python 测试放在各功能包的 `test/` 目录中，并使用 `test_*.py` 命名。以 `package.xml` 声明为准，ROS 功能包使用 `ament_lint_auto`，或使用 `ament_flake8`、`ament_pep257` 与 Pytest。为修改的行为添加针对性测试；仅完成仿真运行时，不得声称已通过真机验证。

## 提交与 Pull Request

提交标题应简洁、使用祈使语气，并遵循仓库已有前缀，例如 `feat:`、`chore:` 或 `fix:`。Pull Request 应说明受影响的功能包，关联相关 issue，列出执行过的构建和测试命令，并注明验证使用的是仿真还是真机。GUI、启动流程或仿真行为发生变化时，应附截图或日志。

## 安全与配置

启动真机前检查 `rm_driver/config` 中的 IP 设置，并确认目标机械臂与配置地址一致。启用 LinkerHand 硬件前确认 CAN 接口名称。启动文件应先在仿真环境中测试；机械臂工作范围内不得有人；提交改动时保留已有未提交内容。
