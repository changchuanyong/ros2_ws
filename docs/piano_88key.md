# RM75 双臂 88 键可达性与姿态优化

本页记录 88 键（MIDI 21–108）布局、可达性验收和双臂姿态优化的方法、命令与结果。
原有 40 音 `verified_40` 保持不变；新布局的轨迹与证据写入
`.validation/arm_posture_20261109/`，不覆盖原始参考。

## 1. 候选布局

`config/piano_scene_88key.yaml` 是第一组 88 键候选：

- 工作台：`y = -0.38 m`，台面 `1.75 × 0.80 × 0.05 m`。
- 双机械臂基座：`x = ±0.22 m`，`y = -0.08 m`，`z = 0.76 m`，零偏航。
- 钢琴整体：`y = 0.45 m`，`z = 0.74 m`。
- 与原始 40 音场景相比：钢琴后移 0.30 m，双基座中心距 0.64 → 0.44 m，
  双臂底座前移 0.20 m，工作台同步前移 0.20 m。

钢琴尺寸、52 白键/36 黑键、键距、键深、键高和碰撞几何均沿用
`piano_keyboard.xml` 与 `scene.py` 的实际定义，没有缩小钢琴或碰撞体。

## 2. 方法

1. **几何预筛**：`optimize_88key_layout.py` 用真实 88 个按键点和肩关节位置
   计算最近肩距、左右手覆盖与中音区重叠，先淘汰明显超出臂展的布局。
2. **逐键 IK**：`analyze_88_keys.py` 对每个 MIDI 音符、左右臂和五个手指，
   在平腕与有限腕倾角/前后键位偏移下求 IK；硬性检查目标接触、非目标键、
   错误手指、关节限位和最小限位裕度。
3. **动态按键**：对静态通过的候选执行真实被动键下压/释放，检查 on/off
   边沿、键角上限、残留按键和额外键；失败时依次尝试下一个姿态。
4. **姿态评分**：`PianoHandModel.solve_arm_solutions()` 返回多初值、零空间
   偏置和无偏置解；评分包含肘部下垂量、肘部相对肩的侧向位置、肘部前后位置、
   关节限位裕度、桌面/键床净空、与上一位姿的连续性。
5. **双层规划**：`FingeringPlanner` 将姿态代价和连续性代价加入候选总代价；
   双手配对时附加肘部分离代价；实际碰撞和按键时序仍由连续 MuJoCo 回放硬性
   验收。

姿态代价是软约束；关节限位、碰撞、目标键接触、非目标键和键行程保持硬性
验收。新布局的默认命令深度为 **7.5 mm**（白键行程约 10 mm，黑键约 8 mm），
用于给被动键止挡留出约 0.5 mm 命令余量；验收阈值未改动。

## 3. 命令

在 Ubuntu 22.04 / MuJoCo 3.3.7 环境、`rm_mujoco` 源码目录执行：

```bash
export PYTHONPATH="$PWD:$PWD/scripts"
export MUJOCO_GL=egl

# 1) 布局预筛（不需要 MuJoCo）
python3 scripts/optimize_88key_layout.py \
  --base-scene config/piano_scene_88key.yaml \
  --output .validation/arm_posture_20261109/layout_search

# 2) 全 88 键静态 + 动态可达性
python3 scripts/analyze_88_keys.py \
  --scene-config config/piano_scene_88key.yaml \
  --output .validation/arm_posture_20261109/reach_full_88 \
  --notes 21-108 --press-depth 0.0075 --dynamic

# 3) 对首轮动态失败键重试全部静态候选
python3 scripts/retry_dynamic_failures.py \
  --scene-config config/piano_scene_88key.yaml \
  --reachability .validation/arm_posture_20261109/reach_full_88/reachability.json \
  --output .validation/arm_posture_20261109/reach_full_88_retry \
  --primary-depth 0.0075 --fallback-depth 0.0070

# 4) A0/C4/C8 姿态截图
python3 scripts/render_key_postures.py \
  --scene-config config/piano_scene_88key.yaml \
  --reachability .validation/arm_posture_20261109/reach_full_88_retry/reachability.json \
  --output .validation/arm_posture_20261109/postures --notes 21,60,108

# 5) 新布局下重规划 40 音并回归
python3 scripts/plan_performance.py \
  --package "$PWD" \
  --score examples/two_tigers_flat_palms/verified_40/score.yaml \
  --scene-config config/piano_scene_88key.yaml --press-depth 0.0075 \
  --output .validation/arm_posture_20261109/verified_40_new_layout/plan.yaml \
  --hand both --fingering-mode fixed \
  --beam-width 8 --candidate-limit 3 --ik-candidate-limit 2 \
  --posture-weight 2.0 --continuity-weight 0.5 --planning-budget-sec 7200
python3 scripts/run_performance.py \
  --package "$PWD" --scene-config config/piano_scene_88key.yaml \
  --plan .validation/arm_posture_20261109/verified_40_new_layout/plan.yaml \
  --output .validation/arm_posture_20261109/verified_40_new_layout/playback

# 6) 分屏演奏视频（左：总览，右：侧视）
python3 scripts/render_performance_video.py \
  --package "$PWD" --scene-config config/piano_scene_88key.yaml \
  --plan .validation/arm_posture_20261109/verified_40_new_layout/plan.yaml \
  --output .validation/arm_posture_20261109/two_tigers_88key_side.mp4
```

## 4. 验收标准

- 88/88 单键至少一只手静态可达且动态下压/释放通过。
- 左右手覆盖并集 88 键；中音区存在共同可达区。
- 无目标键缺失、额外键、错误手指、关节限位、键角超限和结束残留。
- 原始 40 音重规划在 1×、30 ms 时序容差和原行程阈值下 `passed=true`。
- 所有结论仅来自 MuJoCo 仿真，未做真机验证。

## 5. 结果

本节由 `.validation/arm_posture_20261109/RESULTS.md` 的最终报告补充；数值以
重试后的 88 键 JSON 和 40 音 `playback/report.json` 为准。

## 6. 已知限制

- 88 键覆盖是单键能力，不等于任意复杂乐谱、任意速度和任意同时按键都可演奏。
- A0/C8 等边缘键接近臂展边界，实际姿态会更接近伸直；必须保留关节限位和
  碰撞硬约束。
- 当前验证是仿真，没有真机标定、负载、柔顺控制或安全急停验证。
