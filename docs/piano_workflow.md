# 右手欢乐颂：准备、定位、演奏与录制

[返回首页](../README.md) · [完整使用指南](usage.md) · [MIDI 测速](speed_test.md) · [PianoVAM 残差强化学习](piano_rl.md)

按这个顺序操作：**右手 READY → 用示教器调整机械臂 → 播放欢乐颂并记录实际 MIDI、压力 → 调整等待时间再录一遍**。此流程使用右手固定姿态播放器，曲目是 `E E F G G F E D C C D E E D D` 共 15 音，不是读取 MIDI 文件来驱动机械臂。

## 1. 更新后构建并加载环境

首次使用下面新增的 MIDI 录制参数，先在工作空间执行一次：

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select rm_l20_driver rm_piano_player
source install/setup.bash
```

以后每个新终端只需切到此工作空间并加载两份 `setup.bash`。各终端的 `ROS_DOMAIN_ID` 保持一致。关闭占用右手串口的双手驱动、手部 GUI、测速程序和其他手部命令发布器；以下 READY 和演奏命令都会自动启动自己的右手驱动，按 UID 选右手。不要同时启动联合双手入口。若串口明确报 `Permission denied`，对实际设备执行 `sudo chmod 777 /dev/ttyUSB0 /dev/ttyUSB1`；重新插拔后权限可能重置，`Input/output error` 不能靠改权限解决。

## 2. 先让右手进入准备手势

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=pose_test pose:=READY ready_settle:=1.0
```

只发送 YAML 中的 `READY`，收到串口写入确认后等待 1 秒，然后程序正常退出。此命令不控制机械臂。程序退出不会主动发送另一种手势；保持供电时手部仍以最后的位置指令为目标，但这不代表闭环保压，也不保证实际已经到位。先目视确认手势。

## 3. 用示教器调整机械臂，确认键位

用机械臂示教器缓慢调整腕部位置，让拇指、食指、中指、无名指、小指分别覆盖 C、D、E、F、G 对应的琴键，READY 时各键应已释放。先确认工作范围内无人，调整完成后停止机械臂运动，再启动手指演奏。这里没有预设机械臂移动命令，`READY` 是手部姿态，与 MoveIt 的 `piano_ready` 不是同一个配置。

可先测试一个手指，确认按得下也松得开；测试其他手指将 `PRESS_C` 改为 `PRESS_D`～`PRESS_G`：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=pose_test pose:=PRESS_C \
  press_duration:=0.5 release_duration:=0.5 ready_settle:=1.0
```

## 4. 确认数字钢琴的 MIDI 输入

钢琴通过 USB MIDI 接到主机后，执行只列设备的命令：

```bash
ros2 run rm_piano_player l20_right_hand_speed_test.py --list-midi-inputs
```

使用输出中的设备路径。此前这台机器可用的是 `/dev/snd/midiC2D0`；重新插拔后编号可能变化，以下命令中的路径须按本次输出替换。当前使用原始 MIDI 设备，不需要 `/dev/snd/seq`。关闭其他读取同一 MIDI 输入的程序，避免设备被占用。

## 5. 播放欢乐颂，同时录制 MIDI 和压力

以下沿用之前选定的 `0.15 / 0.15` 秒等待时间。位置或手势改变后，先用上面的慢速单指测试确认释放，再执行整曲：

```bash
ros2 launch rm_piano_player l20_right_hand_piano.launch.py \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  execute:=true mode:=melody \
  press_duration:=0.15 release_duration:=0.15 ready_settle:=1.0 \
  record:=true record_dir:=/home/dianjinglab/l20_recordings \
  midi_input:=/dev/snd/midiC2D0 \
  telemetry_rate:=10.0 matrix_rate:=5.0
```

此命令再次发送 READY，然后播放 15 音，每音后回 READY。录制开启时，程序会先等待手部状态、五类反馈和五指触觉数据有效，再开始动作。`midi_input` 必须配合 `record:=true`；不填 `midi_input` 则只录手部数据，不打开 MIDI。`execute:=false` 可预览而不连接设备、不创建录制文件。

MIDI 录的是钢琴实际输入的音符开/关、力度、通道和延音踏板，不会把预定乐谱冒充实际演奏。当前普通欢乐颂入口只录制 MIDI，不会因错音或没有收到音符自动纠正动作；MIDI 设备断连或录制故障会停止后续音符。`completed` 表示位置指令流程完成，仍需检查 MIDI、听音和抬键情况。

## 6. 调整演奏速度

修改上面同一条录制命令的两个参数，其他参数保持不变：

| 节奏选择 | `press_duration` | `release_duration` | 每音等待时间之和 |
| --- | --- | --- | --- |
| 慢速检查 | `0.5` | `0.5` | 1.0 秒 |
| 中速 | `0.3` | `0.3` | 0.6 秒 |
| 较快 | `0.2` | `0.2` | 0.4 秒 |
| 当前使用 | `0.15` | `0.15` | 0.3 秒 |

例如回到较快节奏，将命令中的一行改为 `press_duration:=0.2 release_duration:=0.2 ready_settle:=1.0`。两段时间均从对应指令的串口写入确认后计时，所以实际音间隔还包括两次写入和调度耗时；不能把 `0.15 + 0.15` 当作精确的每秒 3.33 音。参数缩短等待，不改变电机速度或按压幅度。漏音或回弹不充分时先加长等待，尤其是释放时间；本次新增的同步录制流程尚未完成真机演奏验证。

## 7. 查看录制结果和停止演奏

每次执行自动创建独立目录，终端会打印 `Recording directory:`。输出位于 `/home/dianjinglab/l20_recordings/<本次会话>/`：

| 文件 | 内容 |
| --- | --- |
| `performance.mid` | 指定 MIDI 输入时，退出录制后导出的实际 MIDI；第一条输入事件为时间零，1 ms 时间精度。没有输入音符时可能为空曲目，不会自动生成欢乐颂 |
| `events.jsonl` | 指令、写入确认、状态与实际 MIDI 事件；MIDI 保留主机单调时钟纳秒时间戳，可与压力数据对齐 |
| `feedback.csv` | 位置、速度、力矩、电流和 `field=force` 的原始读数；force 的 20 值按法向力、切向力、方向、接近量各 5 值排列 |
| `touch.jsonl` | 五指完整触觉矩阵；传感器 1～5 对应拇指到小指 |
| `metadata.json` | 配置、参数、UID、实际采样统计、结束状态；指定 MIDI 输入时 `recording.statistics.midi_events` 是收到的 MIDI 事件数 |

压力/力矩/电流是**原始寄存器读数**，尚未转换为 N、N·m、A；这里是记录压力，不是根据压力自动调节力度。`matrix_rate:=5.0` 是五指合计约 5 帧/秒，轮询每指约 1 帧/秒，不能保证捕获每次 0.15 秒按压的峰值。实际采样率和间隔以 metadata 为准；比较不同速度时保留完整会话目录。

另开已加载环境且 ROS 通信域一致的终端，可查看进度或请求停止：

```bash
ros2 topic echo /single_hand_piano/status
```

```bash
ros2 service call /single_hand_piano/stop std_srvs/srv/Trigger '{}'
```

停止服务在通信健康时停止后续音符，并在待确认写入完成后最多发送一次 READY；它不是机械急停。Ctrl+C 中断也不保证释放手指。正常结束后检查 `metadata.json` 的 `recording.outcome`，不要仅凭文件存在就认定录制完整。

