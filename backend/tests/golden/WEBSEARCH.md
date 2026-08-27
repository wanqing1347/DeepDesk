# WebSearch Regression Contract

WebSearch 的稳定行为由普通 contract tests 覆盖，不依赖外部实现基线。

核心约束：

- `/agent/chat/stream` 使用 Canonical SSE；
- 工具调用使用 `tool_start/tool_end`，并保持相同 `toolCallId`；
- 多工具调用允许并发，但结果注入顺序必须稳定；
- 达到最大工具轮次后进入 force-final，不再继续调用工具；
- 搜索来源通过 `reference` 输出；
- recommendation 为 best-effort，不得阻断主回答；
- 正常结束必须发送 `complete`。

真实 Tavily 与模型调用属于独立 integration/smoke 验收。
