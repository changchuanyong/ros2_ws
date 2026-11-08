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
MUJOCO_GL=egl python3 -m rm_mujoco.render --press-notes 60,61,64,67 --output /tmp/piano_pressed.png
```

交互窗口默认聚焦桌琴区域，另有 `overview`、`front` 和 `keys` 固定相机。
这些观察相机不自动发布 ROS 图像流，避免无头运行时额外启动 EGL 相机线程。

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
| 白键厚度 | 22 mm，键间 1 mm 缝 |
| 黑键高度 | 顶面高出白键 12.5 mm，键体嵌入白键顶面以下 |

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

默认 MoveIt 场景用固定琴键规划双臂。平掌演奏入口用同一布局生成 88 个被动
铰链琴键，由指尖压下并由弹簧回位。白键的前后两段随同一个铰链运动。
MIDI 按下和松开事件由琴键角度触发，指尖接触另外记录。
琴键质量按 RoboPianist 取白键 40 g、黑键 20 g；钢琴 geom 统一用
`contype=0`、`conaffinity=1`，琴键之间及琴键与琴体之间不产生接触，机械臂和
手部默认的 1/1 geom 仍能触键，不再改写机械臂的 `contype`。

每个琴键另有一个不可见 site（`piano_key_<MIDI>_site`，group 4），位于琴键
表面的按压点并随琴键一起运动，可用于指尖目标或接触奖励。`KeyHighlight` 按
RoboPianist 的做法把按下的琴键染成绿色，未按下的键恢复模型编译时的颜色；
`--press-notes` 会生成被动铰链琴键场景、用固定测试力矩压下这些键再渲染，
展示下键、变色和 site 跟随，不代表标定过的指尖力。

从工作空间根目录运行独立仿真，使用能导入 MuJoCo、NumPy 和 PyYAML 的 Python：

```bash
demo=src/ros2_rm_robot/rm_mujoco/examples/two_tigers_flat_palms
python3 "$demo/run_flat_palms.py" src/ros2_rm_robot/rm_mujoco /tmp/two_tigers_keys \
  --score "$demo/two_tigers_original_pose_score.mid"
```

构建并加载工作空间后，也可从 ROS 2 启动同一无头仿真：

```bash
ros2 launch rm_piano_player rm_75_dual_l20_piano_mujoco.launch.py \
  flat_palms:=true output_dir:=/tmp/two_tigers_ros
ros2 topic echo /sim_piano/key_event std_msgs/msg/String --qos-durability transient_local
```

平掌入口用 MuJoCo 仿真时钟安排左右手，直接在该仿真进程内驱动模型。ROS 2
入口发布 JSON 格式的实际键事件，字段为 `sim_time_sec`、`type` 和 `note`。
报告与 MIDI 分别保存到 `report.json` 和 `played_keys.mid`，原始触键记录另存
`raw_contacts.json`。复跑时使用新的输出目录。

当前示例支持 MIDI 通道 0（右手）和 1（左手），每手同一时刻一个音、两手使用
不同的键位，并需要相应的指法表。导出 MIDI 使用固定力度，踏板动作暂未实现。
《两只老虎》的默认演奏时钟放慢 12 倍。同音连击保持腕位，相邻键可共用腕位换指，
或在短间隔内缩短平移时间。平移须通过动力学检查，其他换位优先试短抬腕，
触键预检失败时试完整抬腕。
可通过 `--tempo-scale` 或 `flat_tempo_scale:=` 调整速度，间隔不足时会报错。
报告中的 `wrist_transitions` 记录了两手各自采用的换位方式。

用标定轨迹按原速运行带左手伴奏的 C5→G5 片段。腕部平移和两指的松键、
落指分别计时，最终仍按 MuJoCo 的琴键实际事件判定，时间容差为 25 毫秒。

```bash
demo=src/ros2_rm_robot/rm_mujoco/examples/two_tigers_flat_palms
python3 "$demo/run_flat_palms.py" src/ros2_rm_robot/rm_mujoco /tmp/two_tigers_c5_g5 \
  --score "$demo/two_tigers_c5_g5_1x.mid" --tempo-scale 1 \
  --motion-plan "$demo/two_tigers_c5_g5_1x.json"
```

ROS 2 平掌入口可通过 `flat_motion_plan:=` 传入标定轨迹，同时指定对应的
`midi_file:=` 和 `flat_tempo_scale:=1`。轨迹与乐谱、场景、机械臂模型、
手型和指法绑定。

## PianoVAM 逐音符指法与多指执行（仿真）

新增一条与平掌演示并列的仿真管线，不改变 `run_flat_palms.py`/`fast_score.py`
的既有行为：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash

# 1. PianoVAM Fingering（或 Fingering_GT）→ 逐音符事件
ros2 run rm_mujoco import_pianovam.py \
  --fingering /path/to/PianoVAM_v1.2/Fingering/2024-09-04_17-02-04.tsv \
  --output /tmp/song.fingering.yaml --hand right --limit 30

# 2. 逐音符事件 → 指法/腕位/20 值手态计划
ros2 run rm_mujoco plan_performance.py \
  --score /tmp/song.fingering.yaml \
  --output /tmp/song.performance.yaml

# 2.5 可选：用执行器真实回放标定一个两音和弦的 20 值手态
#     （只写仿真 pose，不修改真机 right_hand_ode_to_joy.yaml）
ros2 run rm_mujoco calibrate_piano_chord.py \
  --score /tmp/chord_melody.fingering.yaml \
  --plan /tmp/chord_melody.performance.yaml \
  --base-pose src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  --output-pose src/ros2_rm_robot/rm_mujoco/config/right_hand_piano_sim.yaml \
  --output-dir /tmp/chord_cal

# 3. 在被动琴键 MuJoCo 场景中播放并校验实际键事件
ros2 run rm_mujoco run_performance.py \
  --plan /tmp/song.performance.yaml --output /tmp/song_sim
```

- **结束时间用 `key_offset`**（手指物理离键），不要用 `frame_offset`
  （含踏板的发声结束）。
- `Fingering/*.tsv` 的 `hand/finger` 作为软先验；`Noinfo` 写成
  `hand: null, finger: null`，规划器按 `left_max_note` 分左右手并自行选择手指。
- 规划器使用平掌标定的腕部朝向、候选手指枚举、MuJoCo IK/接触检查、
  短时按弦动力学探针和 beam search；优先复用上一音的腕位，只有
  `move_after` 到 `time_sec` 的空隙才安排手臂换位。
- 计划中的 `hand_states` 是完整 20 值命令，仿真端用
  `l20_joint_mapping.command_positions()` 映射到 21 个手部关节；多个手指
  可以同时按下，松键时只改对应手指。
- `run_performance.py` 输出 `report.json`（含实测 `key_angles`、
  `same_hand_chords`、`missing`/`unexpected`、错指/意外接触、
  `arm_moves_over_held_notes`）、`played_keys.mid` 和
  `raw_contacts.json`；`passed` 只在所有期望键事件都在容差内且无错键时成立。
- 当前验收范围是右手。左手没有独立标定，暂不用于真机或正式验收。
- 单音、E4+G4 两音和弦 + 重复 G4 短旋律、以及更宽的
  C4→D4→E4→G4 换位旋律都已通过 MuJoCo 回放（`test_fingering.py`）。
  宽旋律是 6 个音、13 条手臂轨迹、11 个手态；`report.passed=true`，
  最大起音误差 0.012 s，C4 只有一对 on/off，F4 峰值低于触发阈值。
- 仿真相手态标定输出在 `config/right_hand_piano_sim.yaml`：
  `chords: middle+little`（middle ROOT −12、TIP −6）解决和弦，`notes: '60'`
  解决 C4 单音保持；单音标定由同一个 `calibrate_piano_chord.py` 完成。
  它不改 `rm_piano_player/config/right_hand_ode_to_joy.yaml`，真机仍用原标定。
- `run_performance.py` 额外保存 `key_edges.json`、88 键
  `key_angle_track.json`、`tracking.jsonl`（arm/hand 目标与 qpos）和
  `active_keys_at_end`；`passed` 现在要求尾部没有仍按下的键。
- 宽旋律换位使用“释放→源侧 hover→高位平移→目标 hover→下降”，
  换位首音的 press 状态不早于 arm waypoint + 0.03 s settle；这是修好
  C4 起音的关键，不再靠加大 `move_extra`。
- 旧 `test_model_stability` 的 lookahead 子进程仍有 55 s 内部超时，
  与上述新链路无关，单独保留失败记录。
- 远端验证：
  ```bash
  ssh jetson_dianjinglab
  cd /home/dianjinglab/ros2_ws_full_20261022
  source /opt/ros/humble/setup.bash
  colcon build --symlink-install --packages-select rm_mujoco
  source install/setup.bash
  colcon test --packages-select rm_mujoco
  colcon test-result --verbose
  ```

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
