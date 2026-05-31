# 执行计划

## 文件用途

本文件用于记录本项目的 Codex App 批次调度计划。

本项目不采用“一步一修”的微步骤推进方式，也不把完整项目一次性交给 Agent 实现。

正确推进方式是：

1. Thinking 模型先定义任务边界、验收标准和失败风险。
2. Codex App 每次处理一个边界清楚的批次任务。
3. 每个批次开始前，Codex 必须先给计划，不得直接改代码。
4. 人工审查计划后，再批准 Codex 执行。
5. 每个批次结束后，人工验收关键产物。
6. 验收通过后再 commit。
7. 发现问题后，将经验写回 SKILL.md 或 docs/failed_examples.md。
8. 关键验收阶段使用新的 Agent / 新上下文，避免实现者自证成功。

## 总体目标

本项目最终生成一份由公开视频转换而来的课程讲义：

- outputs/<run_id>/lecture_handout.md

lecture_handout.md 是最终学习产物，必须适合直接阅读和学习。

讲义中应嵌入从视频中提取的关键画面截图。

工程验收信息、中间过程数据、对齐数据和调试信息应放入：

- outputs/<run_id>/audit/

## 角色分工

### 人类操作者

负责：

- 判断项目目标是否正确
- 审查 Codex 的计划
- 批准或拒绝 Codex 执行
- 运行本地验收命令
- 判断产物是否真的可用
- 决定是否 commit
- 发现失败后要求写回规则

### Thinking 模型

负责：

- 设计任务边界
- 拆分批次
- 编写 Codex prompt
- 设计验收标准
- 发现 Codex plan 是否越界
- 帮助总结失败并固化规则

### Codex App

负责：

- 阅读仓库文档
- 给出阶段计划
- 按批准后的计划实现代码
- 运行或提供验证命令
- 汇报修改了哪些文件
- 停止在当前批次边界内

Codex 不负责最终自证成功。

## 批次推进规则

每个批次都采用以下流程：

1. 新建或继续一个合适的 Codex App thread。
2. 发送阶段 prompt，要求 Codex 先读文档并给计划。
3. Codex 只给计划，不改代码。
4. 人工审查计划。
5. 计划通过后，批准 Codex 实现。
6. Codex 实现当前批次。
7. 人工运行验收命令。
8. 验收通过后 commit。
9. 需要时更新 SKILL.md 或 docs/failed_examples.md。
10. 进入下一批次。

## 何时换新 Agent

以下情况应新开 Codex App thread：

- 进入新的大批次任务
- 当前 thread 上下文过长
- Codex 开始混淆项目目标
- Codex 越界实现了未批准内容
- 需要独立验收已有结果
- 需要对上一轮失败进行复盘

最终验收必须使用新的 Agent / 新上下文，不能让原实现 Agent 自证成功。

## Batch 0：项目地基

### 目标

建立项目方向、输出形态、Agent 规则和 workflow 规则。

### 内容

- README.md
- docs/design_brief.md
- AGENTS.md
- SKILL.md
- docs/failed_examples.md
- docs/execution_plan.md
- 基础目录结构

### 验收门

- 最终产物明确为 lecture_handout.md
- 讲义必须嵌入视频关键画面截图
- 工程验收数据必须放入 audit 目录
- 文档不把项目写成普通视频摘要工具
- 文档不把最终产物拆成 notes.md 和 transcript_by_slide.md
- git working tree clean

### 状态

正在完成。

## Batch 1：最小运行骨架

### 目标

建立最小可运行 pipeline 外壳。

### 包含内容

- configs/sample_config.yaml
- 命令行入口
- 配置读取
- run_id 读取
- outputs/<run_id>/ 创建
- outputs/<run_id>/assets/keyframes/ 创建
- outputs/<run_id>/audit/ 创建
- audit/run_metadata.json 写入

### 不包含内容

- 不下载视频
- 不获取字幕
- 不调用 Whisper
- 不调用 FFmpeg
- 不识别关键画面
- 不生成 lecture_handout.md

### 验收门

- 能通过命令读取 sample_config.yaml
- 能创建 run_id 输出目录
- 能创建 assets/keyframes 和 audit
- 能写 run_metadata.json
- video_url 不硬编码在代码中
- 重复运行不会破坏已有结构

### Agent 使用

使用一个 Codex App thread。

该 thread 只负责 Batch 1。

## Batch 2：原始材料获取

### 目标

获取视频和字幕材料，为后续处理提供原始证据。

### 包含内容

- yt-dlp 下载视频
- 尝试下载平台字幕
- 尝试下载自动字幕
- 生成 download_report.json
- 生成 subtitle_report.json
- 生成 raw_transcript.json
- 字幕不可用时记录 fallback 原因
- 预留 Whisper / faster-whisper fallback 路径

### 不包含内容

- 不抽帧
- 不识别关键画面
- 不生成讲义
- 不做内容索引

### 验收门

- 视频文件路径可追溯
- 字幕来源被记录
- transcript segment 包含 start、end、text
- 字幕不可用时有明确原因
- 下载失败不会被当成成功

### Agent 使用

建议新开 Codex App thread。

## Batch 3：视觉证据提取

### 目标

把视频转换成可检查的视觉证据。

### 包含内容

- FFmpeg 抽帧
- frame_report.json
- 关键画面初筛
- 相似画面去重
- 明显转场帧过滤
- 短暂闪现画面过滤
- 关键截图复制到 outputs/<run_id>/assets/keyframes/
- visual_segments.json

### 不包含内容

- 不生成最终讲义
- 不做内容索引
- 不把每一帧变化都当成新章节

### 验收门

- 抽帧数量合理
- 关键截图确实来自视频
- 关键截图不大量重复
- 明显转场帧没有被当成关键画面
- 每个视觉段落能回溯到视频时间
- 首次验收应优先使用 smoke mode，例如：

```bash
python -m src.run_pipeline --config configs/sample_config.yaml --extract-visuals-only --frame-smoke-seconds 180 --frame-interval-seconds 10 --max-keyframes 12
```

- smoke 验收应检查 `outputs/<run_id>/audit/frame_report.json`：
  - `status` 为 `smoke_success`
  - `ffmpeg_available` 为 `true`
  - `frame_count` 与 smoke 时长和抽帧间隔大致匹配
  - `keyframe_count` 不超过 `max_keyframes`
  - `error` 为 `null`
- smoke 验收应检查 `outputs/<run_id>/audit/visual_segments.json`：
  - `status` 为 `smoke_success`
  - `segment_count` 等于 keyframe 数量
  - 每个 segment 包含 `id`、`start`、`end`、`keyframe_path`、`source_frame_path`、`source_frame_time`、`reason` 和 `visual_difference_score`
- 文件数量 sanity check：

```powershell
Get-ChildItem data\frames\<run_id> | Measure-Object
Get-ChildItem outputs\<run_id>\assets\keyframes | Measure-Object
```

- Batch 3 不得越界生成 Batch 4 / Batch 5 产物：

```powershell
Test-Path outputs\<run_id>\audit\alignment.json
Test-Path outputs\<run_id>\audit\content_map.json
Test-Path outputs\<run_id>\audit\review_report.md
Test-Path outputs\<run_id>\lecture_handout.md
```

这些检查应返回 `False`。
- Batch 3 不使用 `data/keyframes/<run_id>/`。
- 人工必须打开 `outputs/<run_id>/assets/keyframes/` 中的图片检查：是否来自视频、是否无明显黑屏/白屏/噪声/转场/模糊帧、是否无大量重复、是否覆盖 smoke 范围内的代表性视觉变化。
- `visual_difference_score` 不是语义级 slide understanding；keyframe 数量也不是质量指标。smoke success 只证明 minimal verifiable visual evidence extraction loop 跑通，不代表完整视频质量可靠。

### Batch 3.1 / 3.x 候选方向

Batch 3.x 的目标是在不进入 Batch 4 的前提下提升视觉证据质量。它仍然只是视觉证据提取，不是语义级视觉理解。

Batch 3.x 可以包含：

- 重复 slide 抑制
- 黑屏、白屏、转场、模糊帧过滤增强
- 讲者动作导致的误切抑制
- slide-aware crop / region comparison
- OCR 或 slide title 辅助
- 多视频类型 profile 支持

Batch 3.x 的当前可验收范围：

- 3.1 坏帧过滤：记录 `quality_checks`、`accepted_frame_count`、`rejected_frame_count`、`rejected_reasons` 和质量阈值。所有候选帧都被拒绝时必须失败，不得伪造 keyframe。
- 3.2 重复抑制与稳定段合并：记录 `keyframe_selection`、`duplicate_suppressed_count`、`duplicate_rejected_count`、`difference_accepted_count`、`quality_rejected_count`、`stable_segment_count`。keyframe 数量变少不是单独失败依据，但必须可解释。
- 3.3 区域比较：默认 `comparison_region_mode: "full_frame"`；center crop 或 manual crop 只影响差异评分区域，输出 keyframe 仍是完整原图；非法 crop 回退 full frame 并记录 warning。
- 3.4 OCR / 文字线索：默认 `ocr_backend: "none"`；OCR 只是安全降级 hook，不是成功条件，不应引入必需系统依赖，也不应污染讲义。

Batch 3.x 验收时仍需检查 Batch 4 / Batch 5 产物不存在，并确认 `configs/sample_config.yaml` 保持 placeholder：

- `video_url: "https://example.com/public-lecture-video"`
- `run_id: "sample_run"`

### Agent 使用

建议新开 Codex App thread。

## Batch 4：Transcript ↔ Visual Alignment

### 状态

已进入实现阶段，完成后等待独立验收 Agent 复核。

### 目标

把正式 `raw_transcript.json` 中的字幕时间轴，与正式 `visual_segments.json` / keyframes 中的视觉时间轴对齐，生成可审计的：

- `outputs/<run_id>/audit/alignment.json`

### 包含内容

- alignment.json
- transcript segment 与 visual segment 的时间重叠匹配
- 无重叠时的最近 visual segment 低置信度匹配
- unaligned transcript segment 记录
- coverage、gap、warnings 和 errors 统计

### 不包含内容

- 不生成 content_map.json
- 不生成 review_report.md
- 不生成 lecture_handout.md
- 不做中文讲义或最终学习笔记
- 不声称完成语义理解

### 前置条件

- `outputs/<run_id>/audit/raw_transcript.json` 必须存在且包含带 `start`、`end`、`text` 的 segments。
- `outputs/<run_id>/audit/visual_segments.json` 必须存在且为正式 `status: success`。
- `outputs/<run_id>/audit/frame_report.json` 必须存在且 `smoke_test` 不得为 `true`。
- `outputs/<run_id>/assets/keyframes/` 中被 visual segment 引用的 keyframe 文件必须存在。
- visual coverage 必须足够接近 transcript coverage；180 秒 smoke visual evidence 不得用于整节课正式 alignment。

### 验收门

- 字幕片段能回溯到视频时间
- 关键画面能回溯到视频时间
- `alignment.json` 是合法 JSON
- 每个 alignment item 包含 transcript id / index、transcript start/end/text、matched visual id、visual start/end、keyframe_path、source_frame_time、match_reason、overlap_seconds 或 distance_seconds、confidence 和 quality_flags
- smoke visual evidence 会被拒绝，且失败报告可诊断
- visual coverage 明显不足时不得伪装成功
- unaligned transcript segment 不被静默丢弃
- Batch 4 不得生成 Batch 5 产物：
  - `outputs/<run_id>/audit/content_map.json`
  - `outputs/<run_id>/audit/review_report.md`
  - `outputs/<run_id>/lecture_handout.md`

### Agent 使用

建议新开 Codex App thread。

## Batch 5：内容索引、讲义生成与工程报告

### 目标

生成最终讲义和工程验收报告。

### 包含内容

- audit/content_map.json
- lecture_handout.md
- audit/review_report.md

### 输出隔离原则

lecture_handout.md 是学习产物。

review_report.md 是工程验收产物。

两者不能混。

### lecture_handout.md 验收门

- 有课程标题
- 有课程概览
- 有知识结构章节
- 有关键画面截图
- 截图与章节内容匹配
- 语言像课程讲义
- 不像逐字稿
- 不像普通视频摘要
- 不包含 low-confidence、review_required、debug、运行日志或 Agent 自我评价

### review_report.md 验收门

- 记录视频下载状态
- 记录字幕来源
- 记录是否触发 fallback
- 记录抽帧设置
- 记录关键画面数量
- 记录内容索引概况
- 记录低置信度或不确定区域
- 给出人工复查建议

### Agent 使用

建议新开 Codex App thread。

## Batch 6：独立验收与规则写回

### 目标

使用新的 Agent / 新上下文验收结果，避免实现 Agent 自证成功。

### 包含内容

- 独立阅读 lecture_handout.md
- 独立阅读 audit 文件
- 检查讲义是否可学习
- 检查截图和内容是否匹配
- 检查工程信息是否污染讲义
- 检查 audit 是否可追溯
- 发现问题后写入 docs/failed_examples.md
- 必要时更新 SKILL.md

### 验收门

- 验收 Agent 没有参与原实现
- 验收不是只看文件是否存在
- 验收必须抽查讲义、截图和 audit
- 发现问题后必须写回规则
- 不只在聊天中口头记住失败

### Agent 使用

必须新开 Codex App thread。
## Batch 2.5：Whisper / faster-whisper fallback

### 触发条件

Batch 2.5 只能在以下条件同时成立时触发：

- Batch 2 视频下载成功。
- `outputs/<run_id>/audit/subtitle_report.json` 中 `fallback_required` 为 `true`。
- 没有可用平台字幕或自动字幕。
- `outputs/<run_id>/audit/raw_transcript.json` 尚未生成。
- `outputs/<run_id>/audit/download_report.json` 中 `video_path` 可用，或 `data/raw/videos/<run_id>/` 中存在可用视频。

如果 Batch 2 已经成功生成可用的 `raw_transcript.json`，不得进入 Batch 2.5。

### 目标

基于 Batch 2 已下载的视频执行语音转写，为后续对齐和内容索引提供带时间戳的原始 transcript。

Batch 2.5 应生成：

- `outputs/<run_id>/audit/transcription_report.json`
- `outputs/<run_id>/audit/raw_transcript.json`

`raw_transcript.json` 仍然是原始材料，不是讲义，不应做总结、翻译或知识结构整理。

如果使用 force smoke test 验证已有字幕视频的转写链路，只能生成：

- `outputs/<run_id>/audit/transcription_report.smoke.json`
- `outputs/<run_id>/audit/raw_transcript.smoke.json`

smoke 产物不得覆盖正式 `raw_transcript.json`，也不得作为后续 Batch 4 / Batch 5 的正式输入。

### 不包含内容

Batch 2.5 不得执行：

- FFmpeg 抽帧
- keyframe 识别
- `visual_segments.json`
- `alignment.json`
- `content_map.json`
- `review_report.md`
- `lecture_handout.md`

### 验收重点

- `transcription_report.json` 记录使用的转写引擎、模型、输入视频路径、状态和错误信息。
- `raw_transcript.json` 的 segments 必须包含 `id`、`start`、`end`、`text`。
- 转写失败不能伪装成成功。
- Batch 2.5 只解决字幕 fallback，不进入视觉证据、对齐、内容索引或讲义生成阶段。

### 验收标准

skip test：

- 当正式 `raw_transcript.json` 已存在时，Batch 2.5 默认必须跳过。
- `transcription_report.json` 应记录：
  - `status: skipped`
  - `skip_reason: raw_transcript_exists`
- 跳过时不得修改正式 `raw_transcript.json`。

smoke test：

- force transcription 只能用于 smoke test。
- smoke test 应写入独立产物：
  - `outputs/<run_id>/audit/transcription_report.smoke.json`
  - `outputs/<run_id>/audit/raw_transcript.smoke.json`
- 本地 smoke test 验收结果应能记录：
  - `status: smoke_success`
  - `backend: faster-whisper`
  - `model: base`
  - `device: cpu`
  - `compute_type: int8`
  - `detected_language: en`
  - `segment_count: 10`
  - `smoke_test: true`
  - `smoke_seconds: 60.0`
  - `error: null`

正式 transcript 不覆盖检查：

- smoke test 后，正式 `raw_transcript.json` 必须仍保持平台字幕来源。
- 已验收的正式 transcript 特征包括：
  - `source.type: platform_subtitle`
  - `language: en-j3PyPqV-e1s`
  - `segment_count: 2293`
  - first segment text: `YANN DUBOIS: OK.`

smoke 输出隔离检查：

- `raw_transcript.smoke.json` 只能用于验证转写链路。
- Batch 4 / Batch 5 不得读取 `raw_transcript.smoke.json` 作为正式输入。
- `raw_transcript.json` 和 `raw_transcript.smoke.json` 都保留原始语言，不做翻译。
- 最终 `lecture_handout.md` 必须是中文讲义，但这是后续 Batch 5 的任务。

Batch 3/4/5 越界检查：

- Batch 2.5 不得调用 FFmpeg 抽帧。
- Batch 2.5 不得创建 `data/frames/<run_id>/` 或 `data/keyframes/<run_id>/`。
- Batch 2.5 不得生成 `visual_segments.json`、`alignment.json`、`content_map.json`、`review_report.md` 或 `lecture_handout.md`。

## Batch 3.x Solidify 状态

Batch 3.x 已完成并通过独立验收 Agent 和人工看图验收。该结论只覆盖视觉证据提取链路，不代表语义级视觉理解已经完成。

已验收能力包括：

- 坏帧过滤
- 重复抑制与稳定段合并
- full frame / center crop / invalid manual crop fallback 的区域比较行为
- OCR `none/skipped` 和 tesseract 不可用时的安全降级 hook
- all-rejected quality filtering 失败路径保留 rejected stats
- JSON 合法性、Batch 4/5 越界检查、sample config placeholder 和 Git hygiene

Batch 4 的代码能力前置条件已满足：后续可以使用已验收的 `outputs/<run_id>/audit/visual_segments.json` 和 `outputs/<run_id>/assets/keyframes/` 作为视觉输入。但具体 run 仍必须通过 Batch 4 preflight；smoke visual evidence 或 coverage 明显不足的 run 不得作为正式 alignment 输入。

Batch 4 尚未开始。Batch 3.x Solidify 不得生成：

- `outputs/<run_id>/audit/alignment.json`
- `outputs/<run_id>/audit/content_map.json`
- `outputs/<run_id>/audit/review_report.md`
- `outputs/<run_id>/lecture_handout.md`

Batch 4 应基于 Batch 3.x 已验收的 visual segments 和 keyframes 进行字幕对齐与内容索引准备，不应把 Batch 3.x 误写成语义理解模块。

## Batch 4.5A-fix-1：Resolution Diagnosis / 1080p Acquisition Repair

### 目标

修复课程视觉证据的分辨率链路，只处理下载格式选择和分辨率报告，不处理 keyframe 全时段覆盖，也不处理过程性动画中间态 collapse。

### 包含内容

- Batch 2 yt-dlp format selection 默认优先 1080p；1080p 不可用时选择最高可用分辨率。
- 默认 `preferred_video_height: 1080`、`min_video_height: 1080`、`allow_video_resolution_fallback: true`、`resolution_fallback_strategy: "best_available"`。
- `target_video_height` 作为旧配置兼容字段继续可读；strict mode 需要显式关闭 fallback。
- `download_report.json` 记录格式选择、实际 format id、width、height、resolution、codec、filesize、`resolution_check`、fallback 状态和 environment warnings。
- 低于 1080p 的下载可以继续 Batch 2，但必须标记 quality warning，并进入后续人工截图质量检查。
- JavaScript runtime 缺失属于 environment warning；不得直接断言视频本身没有 1080p。
- Batch 3 `frame_report.json` 记录 raw video / extracted frame / keyframe resolution。
- keyframe height 低于 `min_keyframe_height` 时必须可诊断，不得伪装为合格视觉证据。

### 不包含内容

- 不实现时间分桶 keyframe selection。
- 不实现 tail coverage guarantee。
- 不实现 animation intermediate collapse。
- 不运行 Batch 4 alignment。
- 不进入 Batch 5。
- 不生成 `content_map.json`、`review_report.md` 或 `lecture_handout.md`。

### 验收门

- 当前低清历史产物能被诊断为 `640x360`。
- `configs/sample_config.yaml` 保持 placeholder URL 和 `sample_run`。
- `python -m py_compile src/run_pipeline.py` 通过。
- `python -m src.run_pipeline --help` 通过。
- `git diff --check` 通过。
- 没有运行 full-video visual extraction。
- 没有运行 Batch 4 alignment。
- 没有 commit。

## Batch 4.5A-fix：Process-state Duplicate Suppression

### 目标

减少同一 slide 或同一讲解阶段中的逐步动画中间态 keyframes，优先保留稳定态、最终态或信息更完整的代表帧。

### 包含内容

- 在现有 keyframe selection 之后执行 conservative post-selection collapse。
- 通过时间窗口、scene-change score、hash/layout similarity guardrails 判断同一 build group。
- 同一 group 中压缩中间态，默认保留最后稳定态。
- 在 `frame_report.json` 和 `visual_segments.json` 中记录 animation collapse summary。

### 不包含内容

- 不修改 1080p acquisition 逻辑。
- 不修改 yt-dlp selector。
- 不运行 Batch 4 alignment。
- 不进入 Batch 5。
- 不生成 `content_map.json`、`review_report.md` 或 `lecture_handout.md`。
- 不声称实现语义级 slide understanding。

### 验收门

- `python -m py_compile src/run_pipeline.py` 通过。
- `python -m src.run_pipeline --help` 通过。
- `git diff --check` 通过。
- focused synthetic / small test 能证明同组中间态会被 collapse，gap 过大和 scene-change 过大不会误合并。
- full 1080p visual extraction rerun 后 resolution 仍为 `1920x1080`。
- tail coverage 不回退。
- Batch 4/5 禁区产物不存在。
- 人工 keyframe review 确认过程态重复减少且未误删重要视觉变化。

## Batch 4.5A-fix：Process-state Collapse Failure Repair

### 目标

修复上一轮 process-state collapse 的人工验收失败：同一 build-up 序列未充分压缩，以及错误保留早期不完整态、删除后续完整态。

### 包含内容

- 改进 same build group boundary，不只依赖相邻一跳和硬 gap/span 阈值。
- 使用 group anchor、当前代表候选和标题/布局区域连续性判断 build-up chain。
- 增加 conservative adjacent group merge pass。
- 增加不依赖 OCR 的 fuller/final state score。
- 允许 duplicate / low-difference 路径中的后续更完整候选替换早期不完整 keyframe。
- 增强 `frame_report.json` 与 `visual_segments.json` 的 collapse diagnostics。

### 不包含内容

- 不修改 1080p acquisition 或 yt-dlp selector。
- 不把 720p 当作合格目标。
- 不运行 Batch 4 alignment。
- 不进入 Batch 5。
- 不生成 `content_map.json`、`review_report.md` 或 `lecture_handout.md`。
- 不声称实现了语义级 slide understanding。
- 不引入 OCR 硬依赖或外部服务。

### 验收门

- `python -m py_compile src/run_pipeline.py` 通过。
- `python -m src.run_pipeline --help` 通过。
- `git diff --check` 通过。
- focused synthetic tests 覆盖 build-up under-collapse、wrong representative、不同 slide guardrail、tail guard 和 later-state rejection diagnostic。
- full 1080p visual extraction rerun 后仍为 `1920x1080`。
- last keyframe/source_frame_time 不明显回退。
- Batch 4/5 禁区产物不存在。
- 重点人工复查 early build-up 区间、operator fusion 区间和其他 dense intervals。

## Batch 4.5A-fix：Final-state Missing Root-cause Repair

### 目标

本轮继续修复 Batch 4.5A-fix 的 process-state collapse，不进入后续阶段。重点不是继续泛化调参，而是把最终态缺失按 candidate frame、initial accepted keyframe、collapse group、representative selection 和 final keyframe 的顺序追踪清楚，并针对已确认的断点做窄范围修复。

### 包含内容

- 新增 `final_state_trace`，记录低内容 early state 和 boundary override 的决策路径。
- 对低内容、标题占比高、大面积空白的 early state 增加保守 lookahead。在同一视觉上下文中找到更完整状态时，压掉 early state，并在需要时补入后续 candidate。
- 对标题区域高度连续、scene-change risk 低、fuller score 上升的 build-up sequence，允许有限覆盖 gap 或 hash guardrail。
- 对明显 fullness reset 增加新 sequence 断点，避免链式合并跨越真正不同页面。
- 保留默认关闭的 adaptive local rescan hook。本轮不降低全局抽帧间隔。
- 报告中记录 `low_content_lookahead`、boundary override、fullness reset、sampling warning 和 final-state trace。

### 不包含内容

- 不修改 1080p acquisition 或下载选择器。
- 不运行 Batch 4 alignment。
- 不进入 Batch 5。
- 不生成讲义、内容索引或 review report。
- 不引入 OCR 硬依赖，不依赖外部服务。
- 不对生产逻辑写入案例时间戳或页面名称。

### 验收门

- `python -m py_compile src/run_pipeline.py`
- `python -m src.run_pipeline --help`
- `git diff --check`
- focused synthetic tests：candidate-only 补入、错误分组修复、组内 fuller representative、真实标题页保留、sampling warning、fullness reset 断组。
- full 1080p visual rerun，并使用 `python -m json.tool` 检查 JSON。
- 复核 1080p、tail coverage、path consistency 和禁止产物边界。
- dense interval review、独立 Validation Agent 复核和人工 keyframe review。

## Batch 5A：Content Map / Review Scaffold / Handout Skeleton / Prompt Pack

### 目标

基于已验收的正式 transcript-visual alignment，生成可审计的内容结构、工程审查材料、讲义骨架和可选 prompt pack。该阶段只提供 deterministic scaffold，不生成最终润色后的中文讲义。

### 显式入口

```bash
python -m src.run_pipeline --config <config> --generate-content-map-only
```

### 包含内容

- 正式 Batch 4.5A/B 输入 preflight。
- 源 artifact SHA-256 前后保护。
- 连续 teaching unit 聚合。
- 超长 unit 按 transcript cue 边界拆分。
- 讲义层 representative keyframe 选择。
- 连续近重复和 rapid visual burst 的讲义层压缩。
- `audit/content_map.json`
- `audit/review_report.md`
- `lecture_handout.md` skeleton / excerpt-based draft
- 可选 `audit/handout_prompt_pack.jsonl`
- `ContentGenerationBackend` interface、`NoneBackend` 和 fail-closed registry。

### 不包含内容

- 不重新下载视频。
- 不重新生成 transcript。
- 不重新运行视觉提取。
- 不重新运行 alignment。
- 不修改底层 keyframe 或已验收 audit 输入。
- 不发送 HTTP 请求。
- 不读取 API key。
- 不新增 LLM SDK 依赖。
- 不生成最终自然语言讲义。

### Backend 边界

Batch 5A 默认配置：

```yaml
content_generation_backend: "none"
content_generation_backend_mode: "skeleton"
llm_allow_network_calls: false
```

任意非 `none` backend 在 Batch 5A 中必须 fail closed。OpenAI-compatible、DeepSeek、OpenRouter、Anthropic 和 local adapter 仅作为 Batch 5B 的扩展方向，不属于当前已实现能力。

### 验收门

- `python -m py_compile src/run_pipeline.py src/batch5_generation.py`
- `python -m src.run_pipeline --help`
- `python -m unittest tests.test_batch5_generation`
- `git diff --check`
- `content_map.json` 合法、非空、时间单调、引用 ID 和 keyframe 路径有效。
- `review_report.md` 包含 source hashes、近重复组、known issues、prompt pack 摘要和人工检查清单。
- `lecture_handout.md` 明确标记为 skeleton，包含时间范围和代表截图，不复制完整 transcript，不声称人工审核通过。
- `handout_prompt_pack.jsonl` 每行合法、长度受限、引用有效，不包含 secret 或完整 transcript dump。
- 源 artifact hash 在运行前后保持一致。
- 实现后必须由新的 Validation Agent 和人工抽查继续验收。

### Batch 5A-fix：Prompt Pack Path Containment Repair

`llm_prompt_pack_path` 是相对于 `outputs/<run_id>/` 的 audit artifact 路径。实现必须在任何 clear、unlink、mkdir 或 write 之前，把 configured path 解析为 resolved path，并使用 `Path.relative_to()` 确认它位于 resolved `outputs/<run_id>/audit/` 内。

必须 fail closed 的输入包括：

- absolute path
- Windows drive-like path
- `..` traversal
- 反斜杠或混合分隔符 traversal
- symlink escape
- directory path
- 非 `.jsonl` 文件

不得只检查 `Path.is_absolute()`，也不得使用字符串 `startswith()` 代替路径 containment。

### Batch 5A Solidify 状态

Batch 5A 已完成实现、独立验收和最低限度人工抽查。

- Validation verdict：`PASS with HUMAN_REVIEW_REQUIRED`
- Manual review conclusion：`PASS with known limitations`
- prompt pack path containment 自动复验通过；Windows symlink escape 测试因权限限制 skip，作为 non-blocking risk 记录。
- `1640/1650/1660/1680` 附近的连续教学示例只在 handout layer 保留一张代表图。
- `4520/4530` 附近保留 fuller representative。
- `5690` 附近的 partial content missing 作为 known issue 记录。
- 当前 handout skeleton 仍然细碎、机械，缺少 LLM 总结提炼。这是 Batch 5B 的目标，不阻塞 Batch 5A。

下一阶段只能是单独规划的 Batch 5B LLM-backed summarization / restructuring / polishing。本轮不得直接实现 Batch 5B。

## Batch 5B：Real LLM-backed Handout Generation

Batch 5B 尚未批准实现。后续可在 Batch 5A 已验收的 content map 和 prompt pack 之上增加 provider adapter、结构化响应校验、usage metadata、失败降级和最终中文讲义渲染。

Batch 5B 仍必须保持 grounding、secret 隔离、工程报告隔离和人工验收边界。
