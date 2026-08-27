# Deep Research Regression Contract

Deep Research 的稳定外层事件契约由 `tests/test_deep_research_agent.py` 与 `tests/test_deep_research_golden.py` 覆盖。

核心约束：

- 研究过程可以输出 `thinking`；
- 最终报告通过 `text` 流式输出；
- 搜索来源在最终文本后通过 `reference` 输出；
- nested task-agent 工具调用保持内部实现细节，不暴露为外层 `tool_start/tool_end`；
- 正常结束必须发送 Canonical `complete`；
- 搜索失败不能被记录为成功工具执行；
- 会话结果必须持久化完整 user/assistant turn。

真实 provider 验收与普通单元测试分开执行，避免测试套件依赖外部网络。
