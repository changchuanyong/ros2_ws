# 双手《两只老虎》40 音原速复验

此目录保存已通过联合仿真的固定曲目基准，不依赖 `.validation/` 或 Jetson 临时目录。
`score.yaml` 是冻结的 32 音右手、8 音左手输入；`performance.yaml` 包含完整腕部路径、
20 通道手形、预备/抬指状态和逐音命令时刻。原谱时间不变，仅统一增加 1 秒准备时间。
候选搜索的最终结果已展开到这个计划中，回放过程中没有分段复位。

使用 Ubuntu 22.04、Python 3.10 及现有 MuJoCo 3.3.7、NumPy、PyYAML 环境。
在工作空间根目录运行（输出目录必须尚不存在）：

```bash
package="$PWD/src/ros2_rm_robot/rm_mujoco"
export PYTHONPATH="$package:$package/scripts${PYTHONPATH:+:$PYTHONPATH}"
export MUJOCO_GL=egl OPENBLAS_NUM_THREADS=1
python3 "$package/scripts/verify_two_tigers.py" --package "$package" \
  --output .validation/two_tigers_verified_40
python3 -m pytest "$package/test/test_two_tigers.py" -q
```

入口先校验 `manifest.json` 中的输入、模型、配置、网格和回放实现身份，再核对 40 音的
音高、手别、固定指法及 onset/end。文本 hash 统一 LF，允许 Git 换行转换。
随后调用生产 `run_performance.py` 在同一次 MuJoCo 仿真中执行双手。
模型或实现变化时应重新验收，不能只改 hash 来宣称旧结论仍有效。

成功要求退出码 0 且 `playback/report.json` 的 `passed=true`。输出包括：

- `plan.yaml`：本次实际回放计划。
- `run.json`、`run.log`：命令、退出码、耗时和冻结身份。
- `playback/report.json`：逐音触发、释放、时序误差、指法、错键和角度检查。
- `playback/key_edges.json`、`key_angle_track.json`、`tracking.jsonl`、
  `raw_contacts.json`、`played_keys.mid`：实际仿真证据。

验收条件保持 1×、30 ms 时序容差、默认 0.55/0.30 行程事件阈值及现有角度/回弹容差。
首次联合结果为 40/40、80 个按下/释放边沿，最大落键误差 30 ms、释放误差 18 ms；
无缺音、多余音、错误指法、角度违规和结束残留。复验以新生成的报告为准。

当前计划匹配 `piano_frame.y = 0.15 m` 的默认场景。Jetson 上通过 40/40 联合回放和
8 项输入检查。最大落键、释放、时长误差分别为 20、20、23 ms。计划包含第 32、35 音
换键期间的短时手指补偿，正式回放器按普通手形状态连续执行。

这是固定曲目的标定计划回放入口，不是任意曲谱自动规划器，也没有进行真机验证。
通用规划仍使用 `plan_performance.py`；不要把此基准移用到其他曲谱。
构建并加载 ROS 2 工作空间后，也可直接运行
`ros2 run rm_mujoco verify_two_tigers.py --output .validation/two_tigers_verified_40_ros`，
无需传 `--package`；两种方式都校验同一份冻结清单。
