# 设计简报

## 项目目标

本项目旨在构建一个课程视频转讲义 workflow。

输入是一个公开视频链接，输出是一份可以直接阅读和学习的课程讲义。

最终学习产物不是逐段字幕稿，也不是普通视频摘要，而是一份经过整理、归并和结构化后的讲义文件：

- lecture_handout.md

讲义中应包含从视频中提取出的关键画面截图，并将截图嵌入到对应的讲义章节中。

工程验收信息、对齐数据、中间过程数据不应污染最终讲义，而应单独保存在 audit 目录中。

## 项目定位

本项目不是一个聊天 Agent，也不是单个脚本工具。

它是一个由多个阶段组成的 workflow，包括：

- 视频下载
- 字幕获取
- 字幕 fallback 转写
- 视频抽帧
- 关键画面识别
- 字幕与画面对齐
- 内容结构理解
- 讲义大纲生成
- 最终讲义生成
- 工程验收与失败案例沉淀

本项目的核心难点不是把视频简单切成若干时间段，而是先从完整视频中提取可追溯证据，再基于证据整理出符合学习逻辑的讲义。

## 输入

第一版只处理一个公开视频链接。

输入应来自配置文件，而不是写死在代码里。

配置文件中可以包含：

- video_url
- run_id
- preferred_subtitle_languages
- frame_interval_seconds
- min_stable_duration_seconds
- output_dir

第一版不要求用户提前提供字幕文件，也不要求用户提前提供 slides.pdf。

## 最终学习产物

每次运行应在 outputs/<run_id>/ 目录下生成最终讲义：

- lecture_handout.md

lecture_handout.md 是最终给学习者阅读的主文件。

它应包含：

- 自动识别或推断出的课程标题
- 课程概览
- 按知识结构组织的章节
- 从视频中提取的关键画面截图
- 对关键概念、流程、例子和结论的整理
- 必要的视频时间范围，方便回看原视频

lecture_handout.md 不应包含：

- low-confidence
- review_required
- alignment confidence
- 疑似误判提示
- 工程调试信息
- Agent 自我评价
- 运行日志

如果存在不确定性，应在 audit/review_report.md 中记录，而不是写进最终讲义。

## 最终输出结构

每次运行的输出目录应大致如下：

outputs/<run_id>/
- lecture_handout.md
- assets/keyframes/
- audit/alignment.json
- audit/review_report.md
- audit/content_map.json
- audit/raw_transcript.json
- audit/visual_segments.json

其中：

lecture_handout.md 是最终学习产物。

assets/keyframes/ 用于存放讲义中引用的视频关键画面截图。

audit/ 用于保存工程验收、对齐数据、中间结构和调试信息。

## 中间产物

workflow 应保留必要的中间产物，方便人工检查和问题定位。

可能包括：

- data/raw/videos/
- data/raw/subtitles/
- data/frames/<run_id>/
- data/keyframes/<run_id>/

这些中间产物用于证明最终讲义可以被回放、检查和追溯。

## 预期流程

整体流程如下：

1. 从配置文件读取公开视频链接
2. 使用 yt-dlp 下载视频
3. 优先尝试下载平台字幕或自动字幕
4. 如果字幕不可用，则使用 Whisper 或 faster-whisper 进行转写
5. 使用 FFmpeg 从视频中抽帧
6. 从抽帧结果中识别稳定出现的关键画面
7. 对相似画面去重
8. 过滤转场帧、动画帧和短暂闪现画面
9. 根据关键画面出现时间建立视觉段落
10. 将字幕片段与视觉段落对齐
11. 生成 audit/alignment.json
12. 基于字幕、关键画面和对齐信息构建内容索引
13. 生成 audit/content_map.json
14. 根据内容索引生成讲义大纲
15. 根据讲义大纲生成 lecture_handout.md
16. 生成 audit/review_report.md
17. 人工验收讲义质量和证据可追溯性
18. 将失败案例和修复规则写回项目文档

## 内容结构理解

本项目不应直接把 transcript 按时间顺序粘贴成讲义。

在生成最终讲义前，需要先构建内容索引。

内容索引用于回答：

- 这节课主要讲了哪些主题
- 哪些字幕片段属于同一个主题
- 哪些关键画面支撑同一个主题
- 哪些内容是定义
- 哪些内容是例子
- 哪些内容是过渡
- 哪些内容适合合并
- 哪些内容可以省略
- 最终讲义应如何组织章节顺序

内容索引可以保存在：

- audit/content_map.json

## 讲义生成原则

最终讲义应按知识结构组织，而不是机械按时间段组织。

讲义章节可以包括：

- 课程概览
- 核心概念
- 方法流程
- 示例分析
- 关键结论
- 本节总结

讲义应尽量像正常课程讲义，而不是视频逐字稿。

讲义可以保留必要的视频时间范围，但时间戳只用于辅助回看，不应让讲义呈现出工程日志风格。

## 课程标题识别

workflow 应尽量自动识别课程标题。

标题识别优先级：

1. 视频开头标题页中的文字
2. 视频平台标题
3. 配置文件中用户提供的标题
4. fallback 到 run_id

一般情况下，视频开头的 slide 或片头画面包含课程标题，应优先使用视觉识别结果。

## 非目标

第一版不做以下内容：

- 不处理整门课的所有视频
- 不要求用户提前提供 slides.pdf
- 不要求用户提前提供字幕文件
- 不做复杂前端界面
- 不生成无法追溯来源的普通视频摘要
- 不把逐段 transcript 当成最终讲义
- 不把 notes.md 和 transcript_by_slide.md 拆成两个学习入口
- 不因为输出文件存在就宣称 workflow 成功
- 不把页数接近当成对齐正确的证据

## 工程验收重点

工程验收信息不应出现在 lecture_handout.md 中。

人工验收时需要检查：

- 关键画面是否真的来自视频
- 时间戳是否可以回放
- 字幕片段是否分配到了正确的视觉段落
- 是否误把动画帧、转场帧、短暂闪现画面当成新页面
- 是否漏掉重要画面变化
- 内容索引是否正确归并主题
- 最终讲义是否按知识结构组织，而不是机械复制时间线
- 讲义中的截图是否和对应讲解内容匹配
- 讲义是否能支持实际学习
- 工程不确定性是否被记录到 audit/review_report.md

## 开发方法

本项目采用以下循环：

Plan → Execute → Verify → Fix → Solidify

每个实现阶段都应该足够小，方便人工检查。

当发现失败案例后，应将经验写回项目文档，例如：

- AGENTS.md
- SKILL.md
- docs/failed_examples.md
- audit/review_report.md

## 当前地基结论

本项目最终产物是一份由视频转换而成的课程讲义：

- lecture_handout.md

讲义中必须嵌入对应的视频关键画面截图。

工程验收数据和中间过程数据统一放入 audit 目录。

项目后续实现必须围绕“视频转讲义”推进，而不是围绕“视频转 transcript 和 notes”推进。
## 语言输出原则

无论视频原始语言是英文、中文还是中英混合，最终学习产物 `outputs/<run_id>/lecture_handout.md` 必须是中文讲义。

`raw_transcript.json` 应保留平台字幕或转写结果的原始语言，并记录其来源语言。Batch 2 和 Batch 2.5 不负责把 transcript 翻译成中文，也不负责生成中文讲义。

中文化表达发生在后续讲义生成阶段。后续生成 `lecture_handout.md` 时，应基于 transcript、keyframes、alignment 和 content_map，把课程内容整理成适合中文读者直接学习的中文讲义，而不是把 `raw_transcript.json` 直接当作最终输出。
