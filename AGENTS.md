# AGENTS

## 文件用途

本文件用于约束 AI Coding Agent 在本仓库中的工作方式。

Agent 在开始任何实现任务前，必须先阅读：

- README.md
- docs/design_brief.md
- SKILL.md
- docs/failed_examples.md

如果这些文件之间存在冲突，应优先遵循 docs/design_brief.md 中对项目目标和输出形态的定义。

## 项目核心目标

本项目的目标是构建一个“公开视频转课程讲义”的 workflow。

输入是一个公开视频链接。

最终学习产物是：

- outputs/<run_id>/lecture_handout.md

lecture_handout.md 必须是一份可以直接阅读和学习的课程讲义，而不是逐字稿、时间线切片、普通视频摘要或工程日志。

lecture_handout.md 中必须嵌入从视频中提取的关键画面截图。

工程验收信息、对齐数据、中间过程数据应放入 audit 目录，不应污染最终讲义。

## 禁止事项

Agent 不得：

- 一次性实现完整 pipeline
- 把项目做成普通视频总结工具
- 把最终学习产物拆成 notes.md 和 transcript_by_slide.md 两个入口
- 把逐段 transcript 当成最终讲义
- 在 lecture_handout.md 中写入 low-confidence、review_required、alignment confidence 等工程验收信息
- 在 lecture_handout.md 中写入运行日志、调试信息或 Agent 自我评价
- 假设用户会提前提供 slides.pdf
- 假设用户会提前提供字幕文件
- 只因为输出文件存在就声称任务成功
- 让实现功能的同一个 Agent 自证整体正确

## 输出边界

最终输出目录应遵循以下结构：

- outputs/<run_id>/lecture_handout.md
- outputs/<run_id>/assets/keyframes/
- outputs/<run_id>/audit/alignment.json
- outputs/<run_id>/audit/review_report.md
- outputs/<run_id>/audit/content_map.json
- outputs/<run_id>/audit/raw_transcript.json
- outputs/<run_id>/audit/visual_segments.json

其中：

lecture_handout.md 是最终学习产物。

assets/keyframes/ 存放讲义中引用的视频关键画面截图。

audit/ 存放工程验收、中间数据、对齐数据和调试信息。

## 工作方式

Agent 不应一次性实现完整 pipeline。

每次任务必须遵循以下流程：

1. 先阅读相关文档和当前代码
2. 给出简短计划
3. 只实现当前阶段要求的最小功能
4. 提供可手动验证的命令
5. 说明改动了哪些文件
6. 停止，等待人工检查

不要在没有明确要求的情况下主动进入下一阶段。

## 分阶段实现原则

本项目应按阶段推进。

推荐阶段包括：

1. 配置读取与 run_id 输出目录创建
2. 视频下载
3. 字幕获取
4. Whisper 或 faster-whisper fallback
5. FFmpeg 抽帧
6. 关键画面识别
7. 字幕与视觉段落对齐
8. 内容索引生成
9. 讲义大纲生成
10. lecture_handout.md 生成
11. audit/review_report.md 生成
12. 人工验收与失败案例写回

每一阶段都应有明确输入、输出和验收方式。

## 讲义生成要求

lecture_handout.md 应按知识结构组织，而不是机械按视频时间线组织。

讲义可以包含：

- 课程标题
- 课程概览
- 核心概念
- 方法流程
- 示例分析
- 关键结论
- 本节总结
- 必要的视频时间范围
- 对应关键画面截图

讲义不应包含：

- 工程验收标签
- 低置信度提示
- debug 信息
- 原始运行日志
- Agent 的自我评价

如果某些内容存在不确定性，应写入 audit/review_report.md，而不是写入 lecture_handout.md。

## 内容索引要求

在生成 lecture_handout.md 之前，应尽量先生成内容索引。

内容索引用于把视频时间线转化为知识结构。

内容索引应记录：

- 主题
- 相关视觉段落
- 相关字幕片段
- 相关关键画面
- 来源时间范围
- 核心观点
- 示例
- 可合并内容
- 可省略内容

内容索引应保存到：

- outputs/<run_id>/audit/content_map.json

## 验收要求

Agent 不能只说“已完成”。

每个阶段完成后，必须提供人工可执行的验证方法。

示例：

- 配置读取阶段：说明如何检查 run_id 输出目录是否创建
- 视频下载阶段：说明如何检查视频文件路径和下载日志
- 字幕阶段：说明如何检查字幕来源和字幕段数量
- 抽帧阶段：说明如何检查 frame 数量和文件名时间戳
- 关键画面阶段：说明如何查看 keyframes 目录
- 对齐阶段：说明如何抽查 alignment.json
- 讲义阶段：说明如何检查 lecture_handout.md 是否包含关键截图和知识结构章节
- 验收阶段：说明 review_report.md 中记录了哪些工程风险

## 失败写回规则

如果人工验收发现问题，Agent 应协助把问题写回项目文档。

可写入的位置包括：

- SKILL.md
- docs/failed_examples.md
- outputs/<run_id>/audit/review_report.md

不要只在聊天中口头记住失败案例。

## Validation Agent Problem Handling Policy

独立验收 Agent 的职责是验证已实现内容是否符合批准的边界和验收标准，而不是继续开发新功能，也不是替实现 Agent 自证成功。

验收 Agent 遇到问题时，应先判断问题属于被验收对象本身不合格，还是验收过程受环境、素材、权限或历史产物影响。

验收结论和动作应区分为五类：

- FAIL：被验收对象本身违反验收标准，应交回实现 Agent 修复。典型情况包括 JSON 非法、旧字段被删除、Batch 4/5 越界产物被生成、运行产物进入 Git、报告字段为空壳、或功能结果与批准目标不一致。
- AGENT_FIX_AND_CONTINUE：验收过程被可安全处理的问题阻塞或污染，且验收 Agent 能在权限范围内修复后继续。典型情况包括清理旧报告、清理旧图片、重建临时 config、补跑只读检查或重新执行批准范围内的 smoke 验证。
- AGENT_RECORD_AND_CONTINUE：问题不阻塞验收，但应记录为风险或后续改进项。典型情况包括 CRLF warning、非阻塞 deprecation warning、字段命名语义小问题。
- HUMAN_REVIEW_REQUIRED：自动检查无法判断主观质量，需要人工决策。典型情况包括 keyframe 是否有学习价值、是否重复过多、是否漏掉重要视觉变化、是否值得进入下一阶段。
- BLOCKED：验收环境、素材、权限或系统依赖不足，导致验收无法继续，需要用户处理。典型情况包括 FFmpeg 不在 PATH、视频文件缺失、权限不足、需要用户安装系统工具或重启 shell。

FAIL 和 BLOCKED 不应混用。FAIL 表示实现不合格；BLOCKED 表示验收条件不足。

HUMAN_REVIEW_REQUIRED 不应阻止自动检查继续执行。自动检查完成后，再把主观判断点交给人工确认。
