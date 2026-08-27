# File RAG Regression Contract

File RAG 的稳定行为由 `tests/test_file_rag.py`、`tests/test_file_content_tool.py` 和轻量回归测试覆盖。

核心约束：

- 默认 chunk size 为 500，overlap 为 50；
- chunk metadata 保留 `fileid` 与 `chunkId`；
- embedding 输入与 chunk 文本一致；
- Query Rewrite 生成压缩 query，并最多扩展 3 个查询；
- 每个查询默认 `topK=5`；
- 检索结果按 document identity 去重并保持首次命中顺序；
- PgVector 不可用时允许回退已持久化的 direct text；
- 大文件向量化失败保持文件上传可用，并保留可重试状态；
- 删除已向量化文件时先处理向量状态，再处理对象存储。

`file-rag-v2.schema.json` 仅作为可选离线回归 fixture 的数据格式，不要求外部系统参与。
