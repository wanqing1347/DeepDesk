# Skills Agent Regression Contract

Skills Agent 的稳定行为由 `tests/test_skills_agent.py` 和轻量 contract regression 覆盖。

核心约束：

- 支持 skill discovery 与 `read_skill`；
- 支持 WebSearch、FileContent、受限 FileSystem/Grep/Bash；
- 工具调用必须输出成对的 `tool_start/tool_end`；
- `toolName/toolCallId/arguments/result` 保持可追踪；
- 本地工具只能访问配置的 workspace root；
- Bash 默认关闭，并受命令白名单与超时限制；
- context compaction、模型重试和 stop 必须保持可用；
- 正常结束必须发送 `complete`。

真实模型多轮工具测试作为独立 smoke/integration 验收执行。
