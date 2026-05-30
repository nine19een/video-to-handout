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
- Batch 3 重新处理某个 run 时，应清理该 run 下由本流程生成的旧候选帧和旧 keyframe 文件。否则 FFmpeg 缺失或抽帧失败后，目录中的历史图片可能被误认为本轮成功产物。
- 失败路径下可以创建空目录，但不能生成或保留会被误判为本轮成功产物的伪 keyframe，不能过度声称视觉证据已提取成功。

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

### Batch 3 旧视觉产物污染验收

failure name: Batch 3 validation must not trust stale visual artifacts

stage: Batch 3 / Batch 3.x 视觉证据提取验收

risk:

- 同一个 `run_id` 重复执行 smoke 或失败路径验证时，目录中可能残留旧 `frame_report.json`、`visual_segments.json`、候选帧或 keyframe。
- 如果验收 Agent 只读取历史报告或历史图片，可能把旧产物误判为新代码通过。

wrong behavior to avoid:

- 没有清理旧报告和旧图片就直接检查结果。
- FFmpeg 缺失、抽帧失败或筛选失败后，仍用历史 keyframe 证明本轮成功。
- 只因为目录存在或图片存在就判定 Batch 3 通过。

prevention rule:

- 重新验收某个 `run_id` 前，应清理该 run 的旧视觉报告和旧视觉图片，或确认本轮实现会清理自身生成的旧 frame/keyframe。
- smoke 后应检查报告 `created_at`、`status`、`error`、`frame_count`、`keyframe_count` 和实际目录内容是否一致。
- 验收 Agent 不得使用历史报告证明新代码通过。

### Batch 3 all-rejected 失败路径必须保留 rejected stats

failure name: all-rejected quality filtering must remain diagnosable

stage: Batch 3.x keyframe selection

risk:

- 所有候选帧都被质量过滤拒绝时，Batch 3.x 应失败。
- 但失败报告如果丢失 `rejected_frame_count`、`rejected_reasons`、`quality_checks` 或 `keyframe_selection`，人工无法判断失败是合理过滤、阈值过严，还是实现 bug。

wrong behavior to avoid:

- `NoAcceptableKeyframes` 抛出后只写空 summary。
- `frame_report.json` 显示 failed，但 rejected stats 全为 0 或空对象。
- `visual_segments.json` 伪装成成功，或生成空壳 segments。

expected behavior:

- `frame_report.json` 必须保持 `status: failed`。
- `keyframe_count` 必须为 0。
- `rejected_frame_count` 必须反映真实被拒绝帧数。
- `rejected_reasons`、`quality_checks` 和 `keyframe_selection` 必须保留可诊断信息。
- `visual_segments.json` 如写出，应为 failed + `segments: []`，并尽量带上同一批 quality / selection summary。

### Batch 4 smoke visual evidence 不得作为正式 alignment 输入

failure name: smoke visual evidence must not be used for full transcript alignment

stage: Batch 4 transcript ↔ visual alignment

risk:

- Batch 3 smoke visual evidence 只覆盖视频前若干秒，用于验证视觉证据提取链路。
- 如果 Batch 4 把 `status: smoke_success` 的 `visual_segments.json` 或 `smoke_test: true` 的 `frame_report.json` 当作整节课正式输入，大部分 transcript 会被错误对齐、低质量对齐或静默丢弃。
- coverage 明显短于 transcript coverage 时，即使文件存在，也不能判定 alignment 成功。

wrong behavior to avoid:

- 只因为 `raw_transcript.json`、`visual_segments.json` 和 keyframe 文件存在就生成 `status: success` 的 `alignment.json`。
- 用 180 秒 smoke visual segments 对齐完整长视频 transcript。
- 对 coverage 不足的 transcript segment 静默丢弃。
- 生成 content_map、review_report 或 lecture_handout 来掩盖 alignment 输入不合格。

expected behavior:

- Batch 4 必须检查 `frame_report.json` 中的 `smoke_test`。
- Batch 4 必须检查 `visual_segments.json` 中的 `status`。
- Batch 4 必须比较 visual coverage 与 transcript coverage。
- 如果发现 smoke visual evidence 或 coverage 明显不足，应写出可诊断的 `alignment.json`：
  - `status: failed`
  - `alignments: []`
  - `errors` 包含 `VisualEvidenceIsSmoke` 或 `VisualCoverageTooShort`
  - 错误信息说明需要先生成 full-video visual evidence
- 失败 JSON 必须能通过 `python -m json.tool` 验证。

future rule:

- Batch 4 只做可审计时间轴 alignment，不做语义理解。
- Batch 4 不得自动调用 Batch 3.x full-video extraction；full-video visual evidence 是 Batch 4 的前置材料。
- 无法匹配或低置信度的 transcript segment 必须在 `alignment.json` 中保留，不能静默丢弃。

### Batch 4.5A 低分辨率视频不得作为讲义视觉证据

failure name: Batch 4.5A visual evidence resolution below handout target

stage: Batch 4.5A full-video visual evidence human gate

run_id: batch2_test

symptom:

- full-run visual extraction 已生成 keyframes。
- 人工看图发现 keyframe 文字明显模糊，不适合作为讲义视觉证据。
- 只读诊断确认 raw video 为 `640x360`，keyframes 也为 `640x360`。
- 旧 `download_report.json` 未记录 format id、width、height、resolution 或 requested format。

why this is a problem:

- 课程讲义中的截图需要支持学习者阅读画面文字。
- 720p 或 360p 不能作为默认合格目标；当前项目固定以 1080p 作为视觉证据质量目标。
- 如果下载报告不记录实际分辨率，后续 Batch 3/4 可能把低清素材误判为合格输入。

root cause:

- Batch 2 使用了容易选中低清 progressive stream 的 `best[ext=mp4]/best` selector。
- 下载报告缺少 resolution diagnostics。
- Batch 3 报告缺少 raw video、extracted frame 和 keyframe resolution 字段。

fix:

- Batch 2 默认使用 best video + best audio merge，优先满足 `target_video_height: 1080` 和 `min_video_height: 1080`。
- 默认 `allow_video_resolution_fallback: false`。
- 低于 `min_video_height` 的下载必须失败或标记为不可接受降级，不得伪装成功。
- `download_report.json` 必须记录格式选择和实际下载分辨率。
- `frame_report.json` 必须记录 raw video、extracted frame 和 keyframe resolution，并暴露 keyframe height 是否低于最低要求。

future rule:

- 讲义视觉证据默认目标是 1080p。
- 不得为了 mp4 progressive stream 牺牲分辨率。
- 分辨率不可确认时必须记录 unknown/warning/error，不得声称合格。
- 全时段覆盖和过程性动画重复属于后续修复阶段，不应混入 resolution repair。

### Batch 4.5A 过程态重复不得污染关键画面集合

failure name: Batch 4.5A process-state duplicate keyframes after full-video extraction

stage: Batch 4.5A full-video visual evidence human gate

run_id: batch2_test

symptom:

- full-video visual extraction 已通过自动检查。
- raw video、extracted frames 和 keyframes 均达到 1080p 目标。
- tail coverage 已覆盖到视频尾段。
- 人工查看 keyframes 时，发现同一 slide 或同一讲解阶段的逐步构建中间态被保留过多。

why this is a problem:

- 讲义需要引用稳定、信息完整、适合学习的关键画面，而不是每一个动画构建中间态。
- 过程态重复会增加后续 alignment、content_map 和 lecture_handout 的噪声。
- 自动检查只验证分辨率、数量和覆盖范围，不足以证明关键画面集合适合人工学习材料。

root cause:

- 基础 keyframe selection 采用前向贪心去重，只和上一张已接受 keyframe 比较。
- 当逐步构建画面每一步都有中等视觉差异时，单步差异足以通过阈值，但整体上仍属于同一页面或同一讲解阶段。
- 旧报告没有记录过程态 collapse 的行为，人工无法快速判断哪些中间态被保留或压缩。

fix:

- 在 accepted keyframes 之后增加 conservative post-selection collapse。
- 只在时间接近、视觉差异未达到 scene change、hash/layout guardrail 未越界时，把 keyframes 归入同一 build group。
- 同一 build group 默认保留最后稳定态或配置指定代表帧，压缩中间态。
- 在 `frame_report.json` 和 `visual_segments.json` 中记录 collapse 是否启用、压缩前后数量、压缩 group 数和被压缩的中间态时间。

future rule:

- Batch 4.5A 自动检查通过后，仍必须进行人工 keyframe review。
- 过程态重复抑制属于 visual evidence 后处理，不等同于语义级 slide understanding。
- 不得为了减少数量合并明显不同 slide、明显 scene change 或重要 demo 状态。
- 过程态 collapse 的统计和代表帧选择原因必须写入 audit，不得写入最终讲义。

### Batch 4.5A 过程态 collapse 不得保留早期不完整代表帧

failure name: Batch 4.5A process-state collapse under-collapse and wrong representative

stage: Batch 4.5A full-video visual evidence human gate

run_id: batch2_test

symptom:

- 1080p full visual extraction 自动检查通过。
- tail coverage 自动检查通过。
- process-state duplicate suppression 自动检查通过。
- 人工 keyframe review 发现两类问题同时存在：
  - 同一 build-up 序列仍保留多个过程态。
  - 某些页面删掉了后续完整态，只保留较早不完整态。

why this is a problem:

- 过程态没有充分压缩会让后续视觉段落和讲义结构重复。
- 代表帧选错会让讲义引用不完整截图，削弱学习价值。
- 自动指标中的 keyframe 数量减少不能证明代表帧选择正确。

root cause:

- same-group boundary 只做局部相邻判断，容易被 gap、span 或单步差异切裂。
- representative selection 只偏向 latest stable 或简单质量指标，没有明确比较 final/fuller state。
- duplicate 或 low-difference 路径中的后续完整候选可能只被记入 covered time，而不会替换早期代表帧。
- report 缺少 boundary decision 和 representative ranking，人工难以追踪为什么删除了后续帧。

fix:

- same-group boundary 同时比较相邻帧、group anchor 和当前代表候选。
- 用标题/布局区域连续性作为 conservative guardrail，避免把真正不同页面合并。
- 对相邻 group 做保守 merge pass，减少 build-up chain 被切裂。
- 引入不依赖 OCR 的 fuller/final state score，使用非背景内容面积、细节密度、布局丰富度和时间偏好。
- duplicate / low-difference 路径中，如果后续候选更完整且仍属于同页，允许替换早期代表帧。
- report 记录 boundary decisions、representative candidates、score details、candidate replacement history 和 tail collapse check。

future rule:

- 过程态 collapse 的验收必须包含人工 keyframe review。
- 如果完整态存在于 candidate pool 但未成为代表帧，应优先修 selection/collapse，而不是归因于采样。
- 如果完整态不在 candidate pool，应在 audit diagnostics 中暴露采样覆盖风险。
- 不得为了减少 keyframe 数量跨越明显标题变化或 scene change 合并页面。

### Batch 4.5A 最终态存在但 early state 仍被保留

failure name: Batch 4.5A final-state trace exposes retained early state

stage: Batch 4.5A full-video visual evidence human gate

run_id: batch2_test

symptom:

- 同页逐步构建序列中，后续 fuller state 已被采样，甚至已进入最终输出，但较早的低内容状态仍被保留。
- 部分 build-up sequence 被 hash 或 gap guardrail 切裂，普通组内 representative ranking 无法覆盖整个序列。
- 部分连续页面又可能被链式合并，导致代表帧被后续不同页面替换。

why this is a problem:

- early state 会继续污染后续视觉段落和讲义截图。
- 单纯调低 collapse 阈值会扩大跨页面误合并风险。
- 如果报告只展示最终 keyframe，人工无法判断断点发生在采样、初筛、分组还是代表帧选择。

root cause:

- 最终态缺失不能只归因于 representative selection。必须按 candidate frame、initial accepted keyframe、collapse group、representative selection 和 final keyframe 逐层追踪。
- 低内容 early state 缺少 same-context fuller candidate lookahead。
- build group 缺少 fullness reset 断点，允许跨页面链式 over-collapse。

fix:

- 报告输出 `final_state_trace`、`low_content_lookahead`、boundary override、fullness reset 和 sampling warning。
- 对低内容 early state，在保守 lookahead 窗口内查找 same-context fuller candidate。找到时压掉 early state，并在需要时补入后续 candidate。
- 对明显 fullness reset 断开 build group。
- 对标题区域高度连续且 fuller score 上升的序列，有限覆盖 gap 或 hash guardrail。
- adaptive local rescan 默认关闭，只作为后续明确批准后的 hook。

future rule:

- 自动验收需要同时检查 under-collapse 和 over-collapse。
- 没有找到后续 fuller candidate 时，应保留标题页并报告 ambiguity，不得伪装成 final-state success。
- dense interval review 与人工 keyframe review 继续作为进入下一阶段前的 gate。
