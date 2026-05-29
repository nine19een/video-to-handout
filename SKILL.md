## Batch 2 字幕获取与 transcript 质量规则

Batch 2 的目标是获取原始视频、字幕和可追溯的 `raw_transcript.json`，不是生成讲义，也不是做内容索引。

必须遵守以下规则：

1. 下载成功不等于 Batch 2 通过。即使 `download_report.json` 和 `subtitle_report.json` 显示成功，也必须抽查 `raw_transcript.json` 的前若干 segment，确认字幕文本可用于后续内容索引。
2. 字幕选择必须优先 platform subtitles，再考虑 automatic captions。
3. 字幕语言匹配必须支持 prefix-compatible match。例如 `preferred_subtitle_languages` 包含 `en` 时，平台返回的 `en-j3PyPqV-e1s` 必须视为可选 platform subtitle，而不是直接退回 automatic captions。
4. 字幕选择优先级必须是：
   - platform subtitles exact match
   - platform subtitles prefix-compatible match
   - automatic captions exact match
   - automatic captions prefix-compatible match
5. `subtitle_report.json` 中的 `selected_language` 必须记录实际使用的字幕 language key。
6. `raw_transcript.json` 的 `source.language` 必须记录实际使用的字幕 language key。
7. YouTube VTT parser 必须清理 rolling caption 重复，包括 inline timestamp tags、极短重复 cue、相邻完全重复 cue 和相邻包含关系 cue。
8. parser 不得总结、翻译或改写字幕含义。`raw_transcript.json` 必须保留平台字幕或自动字幕的原始语言。
9. 无论视频原始语言是英文、中文还是中英混合，最终 `lecture_handout.md` 必须是中文讲义；但 Batch 2 不生成 `lecture_handout.md`，也不负责中文化表达。
10. 字幕不可用时，Batch 2 只记录 `fallback_required` 和 `fallback_reason`，不调用 Whisper 或 faster-whisper。

## Batch 3 视觉证据提取验收规则

Batch 3 的目标是建立一个 minimal verifiable visual evidence extraction loop。它只负责把已下载视频转换成可检查、可回溯的候选帧、keyframe 和视觉段落，不负责理解课程语义，不负责字幕对齐，不负责内容索引，也不负责生成讲义。

Batch 3 只有显式使用以下参数时才运行：

```bash
python -m src.run_pipeline --config configs/sample_config.yaml --extract-visuals-only --frame-smoke-seconds 180 --frame-interval-seconds 10 --max-keyframes 12
```

普通命令仍然只运行前面的视频和字幕获取流程，不应自动抽帧。

Batch 3 的正式输出边界是：

- `data/frames/<run_id>/`
- `outputs/<run_id>/assets/keyframes/`
- `outputs/<run_id>/audit/frame_report.json`
- `outputs/<run_id>/audit/visual_segments.json`

Batch 3 不使用 `data/keyframes/<run_id>/`，也不得生成：

- `outputs/<run_id>/audit/alignment.json`
- `outputs/<run_id>/audit/content_map.json`
- `outputs/<run_id>/audit/review_report.md`
- `outputs/<run_id>/lecture_handout.md`

### Smoke 验收 checklist

Batch 3 首次验收应优先使用 smoke mode，避免第一次就处理完整长视频。推荐检查：

```powershell
Get-Content outputs\batch2_test\audit\frame_report.json
Get-Content outputs\batch2_test\audit\visual_segments.json
Get-ChildItem data\frames\batch2_test | Measure-Object
Get-ChildItem outputs\batch2_test\assets\keyframes | Measure-Object
Test-Path outputs\batch2_test\audit\alignment.json
Test-Path outputs\batch2_test\audit\content_map.json
Test-Path outputs\batch2_test\audit\review_report.md
Test-Path outputs\batch2_test\lecture_handout.md
```

使用 `--frame-smoke-seconds 180 --frame-interval-seconds 10` 时，候选帧数量大约应为 18 张。keyframe 数量必须不超过 `--max-keyframes`，但 keyframe 数量本身不是质量指标；更多 keyframe 可能意味着重复、转场或噪声进入结果。

### `frame_report.json` 成功标准

smoke 成功时，`frame_report.json` 至少应记录：

- `status: smoke_success`
- `ffmpeg_available: true`
- `frame_interval_seconds`
- `smoke_test: true`
- `smoke_seconds`
- `frame_count`
- `keyframe_count`
- `max_keyframes`
- `duration_seconds`
- `method: ffmpeg_interval_plus_pillow_difference_v1`
- `error: null`

失败时也必须写入 `frame_report.json`，且不得伪装成功。典型失败包括 FFmpeg 不存在、下载报告缺失、视频文件不存在、FFmpeg 执行失败、Pillow 无法读取图片、没有可接受 keyframe。

### `visual_segments.json` 成功标准

smoke 成功时，`visual_segments.json` 至少应记录：

- `status: smoke_success`
- `segment_count`
- `keyframe_dir`
- `segments`

每个 segment 至少包含：

- `id`
- `start`
- `end`
- `keyframe_path`
- `source_frame_path`
- `source_frame_time`
- `reason`
- `visual_difference_score`

`visual_segments.json` 是后续 Batch 4 对齐的视觉输入准备，不应包含字幕片段、主题归纳、知识结构或讲义内容。

### 人工看图验收规则

Batch 3 不能只凭 JSON 成功判定通过。人工必须打开 `outputs/<run_id>/assets/keyframes/` 中的图片并检查：

- keyframes 确实来自输入视频。
- 没有明显黑屏、白屏、噪声帧、转场帧或模糊帧。
- 没有大量重复。
- smoke 时间范围内的代表性视觉变化基本被覆盖。
- 每个 keyframe 可以通过 `source_frame_time` 回溯到视频时间。

需要明确的是，`visual_difference_score` 只是低层视觉差异分数，不等于语义级 slide understanding。smoke success 也不等于全视频视觉质量已经可靠，它只证明当前抽帧、筛选、报告和回溯链路跑通。

### 后续 Batch 3.x 改进候选

后续可以在 Batch 3.x 中改进：

- 重复 slide 抑制
- 黑屏、白屏、转场、模糊帧过滤
- 讲者动作导致的误切抑制
- slide-aware crop / region comparison
- OCR 或 slide title 辅助
- 多视频类型 profile 支持

这些方向不是当前 Batch 3 已完成能力，不应在验收报告或讲义生成前过度声称。

### Batch 3.x 增强实现规则

Batch 3.x 可以在不进入 Batch 4 的前提下增强视觉证据质量。增强后的定位仍然是视觉证据提取，不是语义级视觉理解。

当前 Batch 3.x 增强重点：

- 3.1 坏帧过滤：基于亮度、方差、清晰度/边缘近似强度过滤明显黑屏、白屏、近似纯色帧、低信息量帧和明显模糊帧。
- 3.2 重复抑制与稳定段合并：连续相似候选帧不应反复生成 keyframe；重复抑制和稳定段合并应记录到报告中。
- 3.3 区域比较：默认仍使用 full frame；可配置 center crop 或 manual crop；非法 crop 必须回退 full frame 并记录 warning。
- 3.4 OCR / 文字线索：默认 `ocr_backend: "none"`，OCR 只是安全降级 hook，不作为 Batch 3.x 成功条件。

Batch 3.x 新增配置必须保持保守默认值。旧配置缺失时仍应能运行。`configs/sample_config.yaml` 必须保留 placeholder URL 和 `sample_run`，不得写入真实验收视频作为默认配置。

Batch 3.x 报告字段应向后兼容，只能新增字段，不得删除 Batch 3 已有字段。`frame_report.json` 可以新增：

- `quality_checks`
- `accepted_frame_count`
- `rejected_frame_count`
- `rejected_reasons`
- `quality_thresholds`
- `frame_quality_checks`
- `keyframe_selection`
- `duplicate_suppressed_count`
- `duplicate_rejected_count`
- `difference_accepted_count`
- `quality_rejected_count`
- `first_valid_frame_count`
- `stable_segment_count`
- `comparison_region`
- `ocr`
- `warnings`

`visual_segments.json` 可以新增：

- 顶层 `quality_summary`
- 顶层 `comparison_region`
- 顶层 `ocr`
- segment 内 `quality_metrics`
- segment 内 `merged_source_frame_count`
- segment 内 `covered_source_frame_times`
- segment 内 `duplicate_suppressed_count`
- segment 内 `comparison_region_mode`
- segment 内 `ocr_available`
- segment 内 `ocr_text`
- segment 内 `title_hint`
- segment 内 `title_extraction_status`

OCR 不可用、未安装或关闭时，不得导致 Batch 3.x 失败。合理输出是 `ocr.available: false`、`ocr.status: skipped` 或 `unavailable`，segment 内 `title_extraction_status: skipped` 或 `unavailable`。

Batch 3.x smoke success 仍不等于完整视频质量可靠。keyframe 数量减少不一定失败，可能是重复抑制生效；但必须通过报告字段和人工看图确认没有漏掉重要视觉变化。

Batch 3.x 开始处理某个 run 时，应清理该 run 下由本流程生成的旧候选帧和旧 keyframe 文件，避免 FFmpeg 缺失、抽帧失败或筛选失败后，目录中的历史图片被误认为本轮成功产物。

# SKILL

## 技能名称

公开视频转课程讲义 workflow

## 文件用途

本文件用于沉淀本项目在“公开视频转课程讲义”过程中的可复用规则。

AGENTS.md 约束 Agent 的工作方式。

SKILL.md 约束 workflow 本身应该如何处理视频、字幕、画面、内容结构和最终讲义。

## 核心目标

本 workflow 的最终目标不是生成逐字稿，也不是生成普通视频摘要，而是生成一份可以直接阅读和学习的课程讲义。

最终学习产物是：

- outputs/<run_id>/lecture_handout.md

lecture_handout.md 必须嵌入从视频中提取的关键画面截图。

工程验收信息、中间过程数据、对齐数据和低置信度提示应放入 audit 目录，不应写入 lecture_handout.md。

## 输入规则

第一版只处理一个公开视频链接。

输入应来自配置文件。

配置文件至少应支持：

- video_url
- run_id
- output_dir

后续可以扩展支持：

- preferred_subtitle_languages
- frame_interval_seconds
- min_stable_duration_seconds
- title_override
- whisper_model
- max_handout_sections

不得将测试视频链接硬编码到实现代码中。

## 输出规则

每次运行应创建独立输出目录：

- outputs/<run_id>/

最终学习产物：

- outputs/<run_id>/lecture_handout.md

讲义图片资源：

- outputs/<run_id>/assets/keyframes/

工程验收与中间结构：

- outputs/<run_id>/audit/alignment.json
- outputs/<run_id>/audit/review_report.md
- outputs/<run_id>/audit/content_map.json
- outputs/<run_id>/audit/raw_transcript.json
- outputs/<run_id>/audit/visual_segments.json

原始材料和中间材料可以保存在：

- data/raw/videos/
- data/raw/subtitles/
- data/frames/<run_id>/
- data/keyframes/<run_id>/

## 总体流程

workflow 应按以下逻辑推进：

1. 读取配置文件
2. 创建 run_id 输出目录
3. 下载视频
4. 获取平台字幕或自动字幕
5. 字幕不可用时使用 Whisper 或 faster-whisper 转写
6. 使用 FFmpeg 抽帧
7. 识别稳定关键画面
8. 建立视觉段落
9. 将字幕片段与视觉段落对齐
10. 生成 alignment.json
11. 基于字幕、关键画面和对齐信息构建内容索引
12. 生成 content_map.json
13. 根据内容索引生成讲义大纲
14. 生成 lecture_handout.md
15. 生成 review_report.md
16. 人工验收
17. 将问题和修复规则写回文档

## 阶段规则

### 配置读取阶段

目标：

- 从配置文件读取 video_url 和 run_id
- 创建 outputs/<run_id>/ 目录
- 创建 assets/keyframes/ 和 audit/ 子目录
- 写入基础运行元信息

不得：

- 下载视频
- 调用 FFmpeg
- 调用 Whisper
- 生成最终讲义

### 视频下载阶段

目标：

- 使用 yt-dlp 下载公开视频
- 保存视频文件路径
- 保存下载日志或下载摘要
- 失败时给出明确错误原因

不得：

- 将下载失败当成成功
- 将视频 URL 硬编码到脚本中
- 删除下载日志

### 字幕获取阶段

目标：

- 优先尝试获取平台字幕
- 其次尝试获取自动字幕
- 字幕结果必须包含时间戳
- 记录字幕来源

不得：

- 使用没有时间戳的纯文本字幕作为对齐依据
- 字幕为空时继续假装成功

### Whisper fallback 阶段

目标：

- 仅在平台字幕不可用或不可用质量过低时触发
- 输出带时间戳的 transcript segment
- 记录 fallback 触发原因

不得：

- 无条件调用 Whisper
- 丢失 segment 的 start 和 end 时间
- 混淆平台字幕和转写字幕来源
- 覆盖已经由平台字幕或自动字幕生成的正式 `raw_transcript.json`
- 把 smoke test 产物作为后续 Batch 4 / Batch 5 的正式输入

Batch 2.5 规则：

1. Batch 2.5 默认只处理 `subtitle_report.json` 中 `fallback_required == true` 的情况。
2. 正式 fallback 只应在 Batch 2 下载成功、正式 `raw_transcript.json` 不存在、且 `download_report.json` 中 `video_path` 可用或 `data/raw/videos/<run_id>/` 中存在可用视频时触发。
3. 如果正式 `outputs/<run_id>/audit/raw_transcript.json` 已存在，必须 skip，写入 `transcription_report.json` 记录 `status: skipped` 和 `skip_reason: raw_transcript_exists`。
4. `--force-transcription` 只能用于 smoke test，不得覆盖正式 `raw_transcript.json`。
5. smoke test 必须输出独立产物：
   - `outputs/<run_id>/audit/raw_transcript.smoke.json`
   - `outputs/<run_id>/audit/transcription_report.smoke.json`
6. smoke 产物只用于验证转写链路，不得作为后续 Batch 4 / Batch 5 的正式输入。
7. faster-whisper fallback 的质量只用于补无字幕场景；如果平台字幕可用，应优先使用平台字幕。
8. `base + cpu + int8` 是本地 smoke 验证默认配置，正式长视频可根据质量和耗时调整模型。
9. Batch 2.5 不做翻译、不生成讲义、不抽帧、不生成 alignment、不生成 content_map。
10. `raw_transcript.json` 或 `raw_transcript.smoke.json` 都应保留原始转写语言；最终 `lecture_handout.md` 必须是中文讲义，但这是后续 Batch 5 的任务。

### 抽帧阶段

目标：

- 使用 FFmpeg 按配置间隔抽帧
- 文件名应能反推出时间戳或索引
- 输出抽帧数量和抽帧设置

不得：

- 抽帧间隔写死且不可配置
- 文件名无序或无法追踪时间
- 抽帧成功但没有报告

### 关键画面识别阶段

目标：

- 从抽帧结果中识别稳定出现的关键画面
- 对近似重复画面去重
- 过滤转场帧、动画帧、短暂闪现画面
- 将被接受的关键画面复制到 outputs/<run_id>/assets/keyframes/

不得：

- 把短暂动画状态当成独立核心页面
- 把转场帧当成稳定页面
- 只凭单帧差异直接切分讲义章节

### 视觉段落阶段

目标：

- 根据关键画面出现时间建立视觉段落
- 每个视觉段落应包含 start_time、end_time、keyframe_path
- 视觉段落数据写入 audit/visual_segments.json

不得：

- 只按固定时间均分
- 让视觉段落缺少关键画面引用
- 让视觉段落无法回放检查

### 字幕对齐阶段

目标：

- 将字幕片段分配到视觉段落中
- 生成 audit/alignment.json
- alignment.json 应保留时间戳、关键画面路径、字幕片段和来源信息

不得：

- 只因为页数接近就认为对齐正确
- 让 alignment.json 缺少回溯字段
- 将工程置信度写入最终讲义

### 内容索引阶段

目标：

- 将时间线材料转换为知识结构
- 识别主题、概念、例子、流程、总结和过渡内容
- 合并属于同一主题的多个视觉段落
- 丢弃或弱化无学习价值的过渡内容
- 生成 audit/content_map.json

不得：

- 直接把 transcript 按时间顺序粘贴成讲义
- 机械地一个视觉段落对应一个讲义章节
- 把内容索引省略掉，直接生成最终讲义

### 讲义生成阶段

目标：

- 生成 outputs/<run_id>/lecture_handout.md
- 讲义按知识结构组织
- 讲义中嵌入关键画面截图
- 讲义语言应自然、清晰、适合学习
- 保留必要的视频时间范围，方便回看

lecture_handout.md 可以包含：

- 课程标题
- 课程概览
- 核心概念
- 方法流程
- 示例分析
- 关键结论
- 本节总结
- 对应关键画面截图
- 必要的视频时间范围

lecture_handout.md 不应包含：

- low-confidence
- review_required
- alignment confidence
- debug 信息
- 运行日志
- Agent 自我评价
- 工程验收说明

### review_report 阶段

目标：

- 生成 outputs/<run_id>/audit/review_report.md
- 记录工程风险
- 记录低置信度段落
- 记录建议人工检查的位置
- 记录字幕来源、抽帧设置、关键画面数量、内容索引概况

不得：

- 在 lecture_handout.md 中暴露工程验收信息
- 只写“运行成功”
- 让实现 Agent 自证整体正确

## 讲义质量标准

lecture_handout.md 应满足以下标准：

1. 像讲义，而不是逐字稿
2. 像课程材料，而不是视频摘要
3. 有清晰标题和章节结构
4. 关键画面截图嵌入到对应章节
5. 截图和文字内容能互相支撑
6. 章节顺序符合学习逻辑
7. 必要时保留视频时间范围
8. 不出现工程调试信息
9. 不出现 Agent 自我评价
10. 可以被人直接用来学习

## 人工验收标准

人工验收时应重点检查：

- 讲义标题是否合理
- 讲义是否包含关键截图
- 截图是否来自视频
- 截图是否对应当前章节内容
- 讲义是否按知识结构组织
- 是否只是机械复制 transcript
- 是否只是普通视频摘要
- 是否遗漏重要主题
- 是否把工程验收信息写进 lecture_handout.md
- audit/review_report.md 是否记录不确定性

## 修复写回规则

如果发现问题，不应只修一次性 bug。

需要判断是否应该更新：

- AGENTS.md
- SKILL.md
- docs/failed_examples.md
- outputs/<run_id>/audit/review_report.md

典型写回场景：

- 讲义缺少关键截图
- 讲义像逐字稿
- 讲义像普通摘要
- 内容索引没有合并同类主题
- 工程验收信息污染 lecture_handout.md
- 关键画面与讲义章节不匹配
- 字幕与视觉段落错位
- 标题识别失败
- fallback 逻辑不清晰
- Agent 一次性实现过多阶段

## 当前约束

当前阶段仍处于项目地基阶段。

在进入实现前，必须保证：

- docs/design_brief.md 已定义“视频转讲义”目标
- AGENTS.md 已定义 Agent 执行边界
- SKILL.md 已定义 workflow 规则
- README.md 与当前目标一致
- docs/failed_examples.md 可用于记录失败案例
