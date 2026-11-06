# 右手钢琴测速方法

[返回根目录 README](../README.md)

本测试测量固定腕位下，右手 L20-11 使用已标定完整姿态和现有 RS485 链路的最高通过速度。RM75 由示教器定位并保持不动；每次 PRESS 后发送 READY。三种模式分别报告，不将结果外推为任意曲谱、同手和弦、跨键移动或独立多指重叠演奏能力。

## 1. 准备和逐键标定

1. 完成[环境加载与编译](usage.md#环境与编译)，更新源码后构建 `rm_l20_driver rm_piano_player`，重新加载 `install/setup.bash`。
2. 先在离开琴键的位置低速核对运动方向，再用示教器将右手定位到 C4～G4 上方，固定机械臂。
3. 用[仓内 GUI](usage.md#l20-双手调试-gui)标定 READY、PRESS_C～PRESS_G，逐键按下、发声、松开各三次，无邻键误触；再验证 E/E、C/C 的重复击键。保存自己的完整 20 值命令姿态，并逐项确认 `verified: true`。
4. 仓库姿态仍包含推算值；已有 `verified: true` 不能代替现场验收。只有完成上述步骤，才使用 `calibration_confirmed:=true`。
5. 关闭其他手部驱动、GUI 和命令发布器，钢琴不踩延音踏板，测试时不要人工弹键或播放钢琴内置曲目。测速入口自带右手驱动，按 UID 校验串口。

本入口不调整设备的电机速度或力矩设置。使用设备实际支持并已验证的设置；不同设置下的测试结果应分别记录。

## 2. 接通钢琴 MIDI

将钢琴 USB MIDI 数据接口连接 Jetson，打开钢琴电源，查询原始 MIDI 输入设备路径：

```bash
cd /home/dianjinglab/ros2_ws_full_20261022
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run rm_piano_player l20_right_hand_speed_test.py --list-midi-inputs
```

将返回的完整设备路径原样填入 `midi_input`，例如 `midi_input:=/dev/snd/midiC2D0`。设备编号可能随重新插拔变化，每次启动前重新列举；路径不是设备身份校验，需要确认它对应当前钢琴。程序只打开 MIDI 输入，不向钢琴发送 MIDI 音符。收到的 note-on/note-off 用来判断机器人是否实际触发了钢琴的按键事件，velocity 保留为 MIDI 原始值，并不等于机械按压力或声压。

当前输入后端直接以只读、非阻塞方式读取 Linux 原始 MIDI 设备，测速与双臂 MIDI 反馈监听均不再使用 Mido/python-rtmidi 或 `/dev/snd/seq`。收到的 MIDI 字节流支持跨读取分包、running status 和交错实时消息，解析 note-on、note-off 及延音踏板事件；设备读取失败或断开会触发采集错误并终止后续测速命令。

2026-11-04 主机检查：内核为 `5.15.199-tegra`，已识别 `MLT-10 MIDI Device`，存在 `/dev/snd/midiC2D0`；`/dev/snd/seq` 和 `snd_seq` 模块缺失。当前后端不需要补装 Sequencer 模块。设备存在和成功打开不等于已收到钢琴按键事件，仍需通过实际按键验证连接。

如果没有列出设备或无法打开，检查：

```bash
lsusb
ls -l /dev/snd/midi*
cat /proc/asound/cards
ros2 run rm_piano_player l20_right_hand_speed_test.py --list-midi-inputs
```

确认钢琴/转接器供电和 MIDI 接线、当前用户具有输入设备读取权限，并关闭占用同一原始 MIDI 输入的其他程序。不要用 CH340 手部串口路径代替 MIDI 设备路径。设备缺失时不会回退到旧 Sequencer 后端。

## 3. 预览与实机启动

默认仅预览，不启动串口驱动、不打开 MIDI、不发送命令或创建记录目录：

```bash
ros2 launch rm_piano_player l20_right_hand_speed_test.launch.py pattern:=repeat
```

完成定位、逐键标定和 MIDI 输入检查后，在已加载环境的终端执行：

```bash
ros2 launch rm_piano_player l20_right_hand_speed_test.launch.py \
  execute:=true calibration_confirmed:=true \
  pattern:=repeat rates:="2,4,6,8,10,12,16" \
  notes_per_trial:=20 repeats:=3 \
  ready_settle:=1.0 trial_rest:=1.0 \
  midi_input:=/dev/snd/midiC2D0 \
  pose_config:=/home/dianjinglab/ros2_ws_full_20261022/src/ros2_rm_robot/rm_piano_player/config/right_hand_ode_to_joy.yaml \
  hand_port:=auto record_dir:=/home/dianjinglab/l20_speed_tests
```

三种模式分别运行：

- `repeat`：E4 连续复击，测同键完整释放后再次触发的能力。
- `alternate`：C4、D4 交替，测当前两组完整姿态之间的切换。
- `scale`：C4、D4、E4、F4、G4 循环，测五键姿态序列。

默认每档 20 音、连续三轮，每轮前保留 READY 等待。`rates` 必须递增且不超过 16 音/秒，可先用 `rates:="2"` 做低速检查。更改音数、轮数或休息时间后，报告会记录实际设置；不同设置不能直接比较。

目标单位是每秒音符起音数，不是串口命令数。每音至少包含 PRESS 与 READY 两次位置命令。以四分音符为一拍，连续十六分音符的击键率为 `BPM × 4 / 60`：120 BPM 对应 8 音/秒，240 BPM 对应 16 音/秒。这些是测试目标，不能当作 L20 已验证的性能。

## 4. 时序与通过标准

每轮在开始时固定整段目标时间轴；目标起音相隔 `1 / rate` 秒，释放目标在半个周期处。采集线程记录 MIDI 回调到达的主机单调时间，另记录计划、命令发送和串口写入确认时间。

本轮采用的工程验收标准为：

- 每个计划音符和释放事件均对应正确的 MIDI note-on/note-off，无漏音、额外音、错音或未释放。
- 起音和释放相对各自计划时间的误差均不超过一个音符周期的 20%。该阈值是本项目测试标准，不是设备厂家指标。
- 当前命令确认完成后才允许发送下一命令；若赶不上固定时间窗，则判该轮失败，不补发已错过时间窗的命令、不集中追赶、不平移整段时间轴。实际按下与释放间隔会受允许范围内的调度和通信抖动影响，报告保留时间误差；不会在每笔确认后额外叠加半个周期来放慢曲谱。
- 每档全部三轮通过才计为通过；首个失败档位后不继续升速。全部档位通过时只能说“达到本次测试上限”，不能说测得了物理极限。

MIDI 按事件顺序和限定时间窗匹配，同键迟到事件不会自动配给下一次同音。MIDI 时间仍包含钢琴、USB 和主机回调的传输延迟；本测试量测整条链路，不是直接测量指尖接触时刻。

## 5. 数据、状态与停止

启动日志与状态给出本次独立记录目录：

```bash
ros2 topic echo /single_hand_piano/speed_status
ros2 service call /single_hand_piano/speed_stop std_srvs/srv/Trigger '{}'
```

目录包含：

- `speed_report.json`：测试模式、目标档位、各轮结果、最高通过档位、实际起音频率、时间误差和失败原因。
- `events.jsonl`：固定计划、命令发送、写入确认、原始 MIDI 输入、评分和停止事件。
- `feedback.csv`、`touch.jsonl`：原始关节、力、电流和触觉矩阵数据。
- `metadata.json`：UID、姿态快照、实际采样统计和录制完整性。串口写入确认缺失或文件写入失败时，录制不能标记完整成功。

出现 MIDI 评分失败或主动停止后不再发后续音符；通信和记录健康时，最多补发一次 READY，并等待当前写入完成。通信、状态或录制故障时不再发送位置命令；强制退出和断连不能保证自动松键。软件停止不等同于机械急停。

记录的是原始寄存器，未标定为 N、N·m、A。2026-10-30 右手静态采集实测常规数据约 4.24 Hz、五指矩阵合计约 2.8 帧/秒，力和矩阵均为零；尚未确认受力响应。这些低频数据不能判断高速按压峰值，测速以实际 MIDI 事件为准，同时保留原始传感记录供后续分析。

## 6. 软件与真机验收边界

```bash
colcon build --packages-select rm_l20_driver rm_piano_player --symlink-install
source install/setup.bash
colcon test --packages-select rm_l20_driver rm_piano_player
colcon test-result --verbose
```

假 MIDI 和 Linux 虚拟串口测试用于验证固定时序、异常停止、记录完整性及资源释放，不代表真机高速演奏成功。真实最高通过速度必须在完成现场标定、MIDI 接入和上述三类分档测试之后填写。
