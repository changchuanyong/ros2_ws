# 架构改造前存档（2026-11-10）

在大改架构前，冻结旧姿势参考轨迹、PPO 两只老虎证据/模型和新静态姿势。
原始文件未改动；存档是副本，位于 git 忽略的 `.validation/`。

## 位置

- 目录：`.validation/architecture_archive_20261110/`
- 单文件：`.validation/architecture_archive_20261110.tar.gz`
  - SHA256：`f6f6eb9375f89b150e66211c26517b08393645b36cdae8aafb46aa78c8507931`
  - 大小：约 52.1 MB
- 目录内 `README.md`：完整说明
- 目录内 `MANIFEST.sha256`：393 个文件的 SHA256
- 目录内 `archive_manifest.json`：时间、commit、文件数与总字节数

## 内容

| 目录 | 内容 |
| --- | --- |
| `old_reference/` | 当前 `verified_40` 全量副本、钢琴后移前旧计划、默认场景、旧 READY/PRESS 配置 |
| `ppo/` | 旧 PPO 两只老虎模型（selected/last）、完整 replay 视频与报告、`dual_seed7` 对照、两套旧接口冻结源码 |
| `new_posture/` | 最终手贴键姿态（`static_pose_reference.yaml`、`piano_scene_static5.yaml`、三视图）、高肘悬手对比版、场景变体、静态脚本、当前布局 80/88 首轮覆盖、旧 88 键布局 88/88 结果 |
| `code_snapshot/` | 当前 `rm_mujoco` 源码 tar、`docs` tar、`git_diff.patch`、`git status`、HEAD |

关键哈希：

- 旧 40 音计划 `old_reference/verified_40/performance.yaml`：
  `0f6c9130bfb6f420b7e31754213e080524770479d6e1beacd5f787ae893c72a3`
- PPO 两只老虎选中模型 `ppo/ppo_two_tigers_dual_smoke_seed7/best_model.zip`：
  `e9738a8aed78d02990b2870753e44a96d17d3ba93e64a14b097320518421512e`
- 最终静态姿势 `new_posture/static_pose_reference.yaml`：
  `b1cec5bd630600ffef52299da1293397ebb5417da1830cf4dc6b0d2f1bf8f2b2`

## 恢复

```bash
# 查看存档
tar -tzf .validation/architecture_archive_20261110.tar.gz | head

# 解压到独立目录（不要覆盖当前工作区）
mkdir -p /tmp/archive_20261110
tar -xzf .validation/architecture_archive_20261110.tar.gz -C /tmp/archive_20261110
```

旧 PPO 模型有接口/源码哈希限制；`dual_smoke_seed7` 的精确 `piano_rl.py` 快照
（哈希 `6f4b2452...`）已不在现有冻结包中，模型不保证能直接重载。视频与物理证据
可正常回放。旧 40 音计划绑定旧基座 `x=±0.32 m`，不能直接用于新内收布局。

新姿势的 40 音 PPO 仍未完成：当前内收布局在原始 1× 节奏下无法生成合格的
79→81 参考，需先改布局/时序/指法再训练；此结论不能写成已通过。
