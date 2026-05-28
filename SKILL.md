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