# lecture-slide-transcript-agent

一个用于将公开视频转换为课程讲义的 workflow 项目。

本项目的目标不是生成普通视频摘要，也不是简单导出逐字稿，而是把课程视频中的字幕、关键画面和时间信息整理成一份可以直接阅读和学习的课程讲义。

## 项目目标

输入一个公开视频链接，workflow 会尝试完成：

- 下载视频
- 获取平台字幕或自动字幕
- 在字幕不可用时使用 Whisper 或 faster-whisper 转写
- 使用 FFmpeg 从视频中抽帧
- 识别稳定出现的关键画面
- 将字幕片段与视觉段落对齐
- 构建内容索引
- 生成最终课程讲义
- 生成工程验收报告

最终学习产物是：

- outputs/<run_id>/lecture_handout.md

## 最终输出结构

一次运行的输出目录计划如下：

outputs/<run_id>/
- lecture_handout.md
- assets/keyframes/
- audit/alignment.json
- audit/review_report.md
- audit/content_map.json
- audit/raw_transcript.json
- audit/visual_segments.json

其中：

lecture_handout.md 是最终给学习者阅读的课程讲义。

assets/keyframes/ 存放讲义中引用的视频关键画面截图。

audit/ 存放对齐数据、中间结构、验收报告和调试信息。

## 设计原则

最终讲义应按知识结构组织，而不是机械按视频时间线组织。

lecture_handout.md 应尽量像正常课程讲义，可以包含：

- 课程标题
- 课程概览
- 核心概念
- 方法流程
- 示例分析
- 关键结论
- 本节总结
- 对应关键画面截图
- 必要的视频时间范围

工程验收信息不应写入最终讲义。

如果存在低置信度、可疑切分、字幕对齐风险或其他不确定性，应记录到 audit/review_report.md 中。

## 非目标

本项目第一版不做：

- 整门课批处理
- 复杂前端界面
- 依赖提前提供的 slides.pdf
- 依赖提前提供的字幕文件
- 普通视频摘要生成
- 逐字稿导出工具
- 无法追溯来源的学习笔记

## 当前状态

当前项目处于地基阶段。

已完成：

- 公开设计文档
- Agent 执行规则
- workflow 规则
- 失败案例记录模板
- 基础目录结构

下一步将进入最小可运行骨架阶段：

- 读取配置文件
- 创建 run_id 输出目录
- 写入运行元信息
- 暂不下载视频
- 暂不调用 FFmpeg
- 暂不调用 Whisper

## 相关文档

- docs/design_brief.md：项目设计简报
- AGENTS.md：Agent 执行规则
- SKILL.md：workflow 规则沉淀
- docs/failed_examples.md：失败案例记录模板