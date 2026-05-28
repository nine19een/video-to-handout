# 失败案例记录

## 文件用途

本文件用于记录 workflow 在真实运行、人工验收和修复过程中发现的问题。

当前文件不用于预设已经发生的失败，而用于规定未来如何记录失败案例、如何分析原因、如何把修复经验写回项目规则。

当某次运行出现问题时，应将问题记录到本文件中，并根据影响范围同步更新：

- AGENTS.md
- SKILL.md
- outputs/<run_id>/audit/review_report.md

不要只在聊天或临时笔记中口头记住失败。

## 记录原则

每个失败案例都应该包含：

- 发生在哪个 run_id
- 输入视频是什么
- 发生在哪个阶段
- 现象是什么
- 为什么这是问题
- 初步原因是什么
- 如何修复
- 是否需要更新 AGENTS.md 或 SKILL.md
- 是否有对应的人工验收证据

失败案例应尽量具体，不要只写“效果不好”。

## 失败案例模板

### 案例编号：待填写

日期：

run_id：

输入视频：

发生阶段：

问题现象：

为什么这是问题：

初步原因：

修复方式：

需要更新的规则文件：

- AGENTS.md：
- SKILL.md：
- review_report.md：

人工验收证据：

后续状态：

## 常见问题分类

后续失败案例可以按以下类别归档。

### 输入与下载问题

可能包括：

- 视频链接无法下载
- 视频平台限制访问
- 下载文件路径混乱
- 下载失败但 workflow 没有正确终止
- 下载日志缺失，无法追溯

### 字幕问题

可能包括：

- 平台字幕不存在
- 自动字幕语言错误
- 字幕没有时间戳
- 字幕为空但 workflow 继续执行
- Whisper fallback 没有被触发
- Whisper fallback 生成的时间戳不稳定

### 抽帧问题

可能包括：

- 抽帧间隔过大，漏掉重要画面变化
- 抽帧间隔过小，产生过多冗余帧
- 帧文件名无法反推出时间
- 抽帧结果没有记录到报告中

### 关键画面识别问题

可能包括：

- 把转场帧识别为关键画面
- 把短暂动画状态识别为独立页面
- 漏掉重要 slide 或 demo 画面
- 多张近似重复画面没有去重
- 关键画面和视频时间戳无法对应

### 对齐问题

可能包括：

- 字幕片段被分配到错误的视觉段落
- 视觉段落边界不合理
- alignment.json 缺少可回溯字段
- 只因为页面数量接近就认为对齐正确

### 内容索引问题

可能包括：

- 没有把时间线内容转换成知识结构
- 一个视觉段落机械对应一个讲义章节
- 同一主题被拆散到多个章节
- 过渡内容被写成正式知识点
- 示例、定义、结论没有区分

### 讲义生成问题

可能包括：

- lecture_handout.md 像逐字稿
- lecture_handout.md 像普通视频摘要
- 讲义缺少关键画面截图
- 截图和章节内容不匹配
- 讲义章节顺序不符合学习逻辑
- 工程验收信息污染最终讲义
- 讲义里出现 low-confidence、review_required、debug 信息或运行日志

### 验收问题

可能包括：

- review_report.md 只写运行成功
- 没有标出需要人工检查的片段
- 没有记录字幕来源
- 没有记录抽帧设置
- 没有记录关键画面数量
- 实现 Agent 自己证明自己正确，缺少独立验收

## 写回规则

发现失败后，应判断是否需要更新规则。

如果问题属于 Agent 执行边界，应更新：

- AGENTS.md

如果问题属于 workflow 处理经验，应更新：

- SKILL.md

如果问题属于某次运行的具体结果，应更新：

- outputs/<run_id>/audit/review_report.md

如果问题具有复用价值，应记录到：

- docs/failed_examples.md

## 当前状态

当前项目尚未开始真实视频处理运行。

本文件目前只提供失败案例记录模板和分类规则。

真实失败案例将在后续运行和人工验收后追加。
## 真实失败样例

### Batch 2 字幕选择和 YouTube rolling captions 污染 raw_transcript

failure name: Batch 2 subtitle source fallback and rolling caption duplication

stage: Batch 2 原始材料获取

input video: https://www.youtube.com/watch?v=r1qZpYAmqmg

symptom:

- 视频下载成功。
- 字幕下载成功。
- 但 `raw_transcript.json` 质量不合格，连续 segment 大量重叠。
- `subtitle_report.json` 中 `available_platform_subtitles` 包含 `en-j3PyPqV-e1s`。
- `preferred_subtitle_languages` 中包含 `en`。
- 旧逻辑选择了 `selected_source: automatic` 和 `selected_language: en`，而不是可用的平台字幕。

wrong behavior:

- 旧字幕选择逻辑只做精确语言匹配。
- 当平台字幕 language key 为 `en-j3PyPqV-e1s` 时，`preferred=en` 没有命中平台字幕。
- workflow 退而选择 YouTube automatic captions。
- automatic captions 的 VTT 被直接解析后，产生 rolling caption 重复，例如：
  - `Okay, let's get started. So, hi`
  - `Okay, let's get started. So, hi everyone. My name is Yan. I'm a`
  - `everyone. My name is Yan. I'm a`

root cause:

- 字幕选择没有支持 prefix-compatible language key。
- VTT parser 没有针对 YouTube automatic captions 中的 inline timestamp tags 和 rolling captions 做清理。
- Batch 2 验收只看“字幕文件是否存在”不足以判断 transcript 是否可用于后续 `content_map` 和 `lecture_handout`。

fix:

- 字幕选择优先级固定为：
  1. platform subtitles exact match
  2. platform subtitles prefix-compatible match
  3. automatic captions exact match
  4. automatic captions prefix-compatible match
- 当 `preferred=en` 且平台字幕存在 `en-j3PyPqV-e1s` 时，必须选择该 platform subtitle。
- `subtitle_report.json` 的 `selected_language` 必须记录实际传给 yt-dlp 的 language key，例如 `en-j3PyPqV-e1s`。
- `raw_transcript.json` 的 `source.language` 必须记录实际使用的 language key。
- VTT parser 必须清理：
  - YouTube inline timestamp tags
  - rolling caption 重复
  - 极短重复 cue
  - 相邻完全重复 cue
  - 相邻包含关系 cue
- parser 不得总结、翻译或改写字幕含义。

verification:

- 修复后 `subtitle_report.json` 记录：
  - `selected_source: platform`
  - `selected_language: en-j3PyPqV-e1s`
  - `segment_count: 2293`
  - `fallback_required: false`
- 修复后 `raw_transcript.json` 的 source 记录：
  - `type: platform_subtitle`
  - `language: en-j3PyPqV-e1s`
  - `is_auto_generated: false`
- 修复后 transcript 开头不再出现 rolling captions 的连续重叠，前几个 segment 类似：
  - `YANN DUBOIS: OK.`
  - `Let's get started.`
  - `So hi, everyone.`
  - `My name is Yann.`
  - `I'm a researcher at OpenAI.`

future rule:

- Batch 2 不能只因为视频和字幕文件下载成功就判定通过。
- Batch 2 验收必须抽查 `raw_transcript.json` 的前若干 segment，确认它不是 rolling captions、空字幕、无时间戳文本或重复污染文本。
- 字幕选择必须优先平台字幕，再考虑自动字幕。
- 语言匹配必须支持 prefix-compatible match。
- YouTube VTT parser 必须处理 rolling caption 重复。
- `raw_transcript.json` 保留原始字幕语言，不负责翻译。
- 最终 `lecture_handout.md` 必须是中文讲义，但中文化表达发生在后续讲义生成阶段，不在 Batch 2 完成。

### Batch 2.5 强制转写不得覆盖已有平台字幕 transcript

failure name: Batch 2.5 must not overwrite existing platform transcript during forced transcription

stage: Batch 2.5 Whisper / faster-whisper fallback

risk:

- Batch 2.5 的目标是字幕不可用时的 Whisper / faster-whisper fallback。
- 如果 Batch 2 已经通过平台字幕生成正式 `raw_transcript.json`，后续强制转写验证可能误覆盖正式 transcript。
- 一旦正式 transcript 被 smoke 转写结果覆盖，Batch 4 / Batch 5 可能误把不完整 smoke transcript 当作正式输入，导致内容索引和讲义生成缺失大量课程内容。

wrong behavior:

- 在 `raw_transcript.json` 已存在时仍执行正式 fallback。
- 使用 `--force-transcription` 覆盖正式 `outputs/<run_id>/audit/raw_transcript.json`。
- 将 smoke test 结果写入正式 `raw_transcript.json`。
- 后续 Batch 4 / Batch 5 读取 `raw_transcript.smoke.json` 作为正式 transcript。

prevention rule:

- Batch 2.5 默认只应在以下条件同时满足时正式触发：
  - Batch 2 下载成功。
  - `subtitle_report.json` 中 `fallback_required` 为 `true`。
  - 正式 `raw_transcript.json` 不存在。
  - `download_report.json` 中 `video_path` 可用，或 `data/raw/videos/<run_id>/` 中存在可用视频。
- 如果正式 `raw_transcript.json` 已存在，Batch 2.5 默认必须跳过，写入 `transcription_report.json`，且不得覆盖正式 transcript。
- `--force-transcription` 只能配合 `--transcription-smoke-seconds` 用于 smoke test。
- smoke test 必须写入独立产物：
  - `outputs/<run_id>/audit/transcription_report.smoke.json`
  - `outputs/<run_id>/audit/raw_transcript.smoke.json`
- smoke transcript 只能用于验证转写链路，不得作为 Batch 4 / Batch 5 的正式输入。

verification:

- 本地 skip 验收结果：
  - `status: skipped`
  - `skip_reason: raw_transcript_exists`
- 本地 smoke test 验收结果：
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
- smoke test 后，正式 `raw_transcript.json` 仍保持：
  - `source.type: platform_subtitle`
  - `language: en-j3PyPqV-e1s`
  - `segment_count: 2293`
  - first segment text: `YANN DUBOIS: OK.`
- 这说明 smoke fallback 路径能跑通，但没有污染正式 transcript。

future rule:

- faster-whisper fallback 的质量只用于补无字幕场景；如果平台字幕可用，应优先使用平台字幕。
- `raw_transcript.json` 和 `raw_transcript.smoke.json` 都必须保留原始转写语言，不负责翻译。
- 最终 `lecture_handout.md` 必须是中文讲义，但中文化表达发生在后续 Batch 5，不在 Batch 2.5 完成。

### Batch 3 FFmpeg 缺失不得伪装为视觉提取成功

failure name: Batch 3 must fail explicitly when FFmpeg is unavailable

stage: Batch 3 视觉证据提取

input video: Batch 2 已下载的公开视频验收样例

trigger command:

```bash
python -m src.run_pipeline --config configs/sample_config.yaml --extract-visuals-only --frame-smoke-seconds 180 --frame-interval-seconds 10 --max-keyframes 12
```

symptom:

- 当前环境 PATH 上没有 FFmpeg。
- Batch 3 无法执行候选帧抽取。
- 运行后可能已经创建空的 frame 或 keyframe 目录。

wrong behavior to avoid:

- 只因为目录存在就声称 Batch 3 成功。
- 生成伪 keyframe 或伪 visual segment。
- 静默跳过 FFmpeg preflight。
- 不写失败报告。

expected failure report:

- `outputs/<run_id>/audit/frame_report.json` 必须写入：
  - `status: failed`
  - `ffmpeg_available: false`
  - `ffmpeg_path: null`
  - `ffmpeg_version: null`
  - `frame_count: 0`
  - `keyframe_count: 0`
  - `error.type: FFmpegNotFound`
  - `error.message: ffmpeg was not found on PATH.`
  - `smoke_test: true`
  - `smoke_seconds: 180.0`
- `outputs/<run_id>/audit/visual_segments.json` 可以写入失败状态，但必须：
  - `status: failed`
  - `segments: []`
  - `segment_count: 0`
  - `error.type: FFmpegNotFound`

verification:

```bash
python -m json.tool outputs/<run_id>/audit/frame_report.json
python -m json.tool outputs/<run_id>/audit/visual_segments.json
```

future rule:

- FFmpeg 是系统依赖，必须通过 preflight 检查。
- FFmpeg 缺失是明确失败，不是 skip，也不是 smoke success。
- 失败路径下可以创建空目录，但不能生成伪 keyframe，不能过度声称视觉证据已提取成功。

### Batch 3 Pillow 未安装导致 keyframe 选择失败

failure name: Batch 3 requires Pillow in the current Python environment

stage: Batch 3 视觉证据提取

input video: Batch 2 已下载的公开视频验收样例

symptom:

- FFmpeg 已安装并可用。
- 候选帧可以抽出。
- keyframe 选择阶段失败，因为当前运行 `python` 环境中没有安装 Pillow。

wrong behavior to avoid:

- 只因为 `requirements.txt` 写了 `Pillow` 就假设当前环境已经安装。
- 候选帧已生成就声称 Batch 3 成功。
- 在没有 keyframe 的情况下生成伪成功 `visual_segments.json`。

expected failure report:

- `outputs/<run_id>/audit/frame_report.json` 应记录：
  - `status: failed`
  - `ffmpeg_available: true`
  - `frame_count` 大于 0
  - `keyframe_count: 0`
  - `error.type: RuntimeError`
  - `error.message` 包含 `Pillow is not installed. Install dependencies with: pip install -r requirements.txt`

fix:

```bash
python -m pip install -r requirements.txt
```

verification after fix:

- smoke run 后 `frame_report.json` 应记录：
  - `status: smoke_success`
  - `ffmpeg_available: true`
  - `frame_interval_seconds: 10.0`
  - `smoke_test: true`
  - `smoke_seconds: 180.0`
  - `frame_count` 约为 18
  - `keyframe_count` 不超过 `--max-keyframes`
  - `method: ffmpeg_interval_plus_pillow_difference_v1`
  - `error: null`
- `visual_segments.json` 应记录：
  - `status: smoke_success`
  - `segment_count` 等于 keyframe 数量
  - 每个 segment 包含 `id`、`start`、`end`、`keyframe_path`、`source_frame_path`、`source_frame_time`、`reason`、`visual_difference_score`

future rule:

- 验收时必须确认依赖真的安装在当前运行的 Python 环境中。
- `requirements.txt` 是依赖声明，不是环境状态证明。
- Batch 3 smoke success 只证明视觉证据提取链路跑通，不等于全视频视觉质量已经可靠。
