# RM75-6FB-V 双臂双 L20 MIDI 钢琴播放器

该功能包实现 RoboPianist 风格的第一阶段实机链路：88 键 MIDI 曲目、左右 RM75 MoveIt 规划、左右 L20 手指命令和数字钢琴 MIDI 反馈。官方 RoboPianist 的 Shadow Hand RL 策略不直接适用于 RM75+L20，本包先实现固定 MIDI 曲目播放。

## 构建

删除包内 `COLCON_IGNORE` 后，在 Ubuntu 22.04 / ROS 2 Humble 中执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select rm_piano_player
source install/setup.bash
```

MIDI 反馈节点需要 `mido` 和 `python-rtmidi`。执行安装前先检查系统中是否已有这两个包。

## MuJoCo 双臂双手播放

先使用干运行检查 MIDI 文件、左右分配和坐标：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid \
  headless:=true use_rviz:=false execute:=false
```

确认坐标后再执行；`tempo_scale` 是时间倍率，数值越大播放越慢：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  midi_file:=/absolute/path/song.mid \
  execute:=true tempo_scale:=2.0
```

第一阶段按 MIDI 音域分配：`21–59` 为左手，`60–108` 为右手；每只手同时只允许一个音符。同手和弦会在执行前被拒绝。

## 双臂双手真机

外部 `linkerhand-ros2-sdk` 必须先安装并 source。当前 RS485 路径使用 `L20-11` 参数，普通 `L20` 参数会进入 SDK 的 CAN 分支：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid \
  left_arm_ip:=192.168.1.18 right_arm_ip:=192.168.1.19 \
  left_hand_port:=/dev/ttyUSB0 right_hand_port:=/dev/ttyUSB1 \
  execute:=false
```

确认左右手状态、双臂控制器和 MIDI 输入后，再将 `execute` 改为 `true`，并保持较慢的 `tempo_scale`。数字钢琴 MIDI 输入端口通过 `midi_input:=<port-name>` 指定，并用 `feedback_enabled:=true` 开启漏键、错键和超时检查：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_real.launch.py \
  midi_file:=/absolute/path/song.mid midi_input:=<port-name> \
  feedback_enabled:=true execute:=true tempo_scale:=4.0
```

## 配置与安全

- `config/piano_midi.yaml` 保存琴键坐标、`piano_frame`、按压深度、速度和 L20 开手姿态。
- `piano_frame` 已加入双臂 URDF；琴键坐标必须根据实际钢琴位置重新标定。
- L20 命令话题使用 20 个 `position` 值，范围 `0–255`。
- MIDI 反馈状态发布在 `/robopianist/feedback_status`，包含期望音符、实际音符和 `time_error_sec`。
- 默认 `execute=false`，先完成 MuJoCo 干运行和单键验证，再接触真机。
- 当前 MuJoCo 场景包含 88 键几何模型，但尚未实现 RoboPianist 的琴键接触奖励和力反馈。

真机按以下顺序验收：左手 `/dev/ttyUSB0` 单独通信 → 右手 `/dev/ttyUSB1` 单独通信 → 检查 `/cb_left_hand_state` 和 `/cb_right_hand_state` → 双臂单键接近 → 双手单音阶 → 低速 MIDI 曲目 → 开启 MIDI 反馈。出现漏键、错键或超时后，播放器会停止后续动作；机械臂工作范围内不得有人，并保留急停可达。
