# PPT Builder Regression Contract

PPT Builder 的稳定行为由 `tests/test_ppt_agent.py`、`tests/test_ppt_repository_intent.py` 与 renderer 测试覆盖。

核心约束：

- 支持 CREATE / MODIFY / RESUME；
- 状态流转覆盖 REQUIREMENT、SEARCH、OUTLINE、TEMPLATE、SCHEMA、RENDER、SUCCESS/FAILED；
- MODIFY/RESUME 必须复用正确实例；
- 图片生成是 best-effort，单图失败不应破坏整个演示文稿；
- renderer 子进程必须支持 timeout/cancel；
- 成功状态必须持久化 schema、模板和文件 URL；
- Agent stream 使用 Canonical SSE 并以 `complete` 结束。

真实模板、图片 provider 与 MinIO 文件链路作为独立 integration/smoke 验收执行。
