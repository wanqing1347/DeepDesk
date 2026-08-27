# DeepDesk Web 前端完善计划

> 状态日期：2026-08-26  
> 目标：在不推翻现有 UI / 架构的前提下，把 `DeepDesk/web` 从“核心 Chat 已可用”完善为可稳定演示、可持续迭代的多 Agent 工作台。

---

## 1. 后续实现时必须遵守的约束

1. 默认只修改 `DeepDesk/web`。
2. 只有当真实 API contract 无法满足功能时，才允许在明确说明后修改 `DeepDesk/backend`。
3. 不重写已经完成的 Vue / Pinia / SSE 架构。
4. 所有 Agent 流事件继续走统一链路：

   ```text
   SSE -> parser -> event reducer -> conversation store -> UI
   ```

5. Vue Component 中不要直接写后端 URL 或自行处理 SSE。
6. 不伪造后端不存在的数据、Plan、PPT 页面预览、文件 URL 或工具状态。
7. 保持当前视觉方向：Minimal / Calm / Clean / Focused / Soft / Professional。
8. 不引入 Element Plus、Ant Design 等大型后台 UI 框架。
9. 保持 Light / Dark、响应式、键盘操作和 Accessibility。
10. UI 修改继续参考并遵循：
    - `frontend-design`
    - `ui-design`
11. 每个阶段完成后至少运行：

   ```bash
   npm run test
   npm run typecheck
   npm run lint
   npm run build
   ```

---

# 2. 当前已经完成，不要重复设计

## 2.1 工程基础

已完成：

- Vue 3
- Vite
- TypeScript
- Composition API
- Pinia
- Vue Router
- Tailwind CSS
- Lucide icons
- Light / Dark / System theme
- API client 分层
- Bearer API Key 设置入口
- Desktop / Tablet / Mobile 基础响应式

## 2.2 Chat Agent

已完成并真实验证：

- `/agent/chat/stream`
- thinking streaming
- text streaming
- tool_start
- tool_end
- reference
- recommend
- error
- complete
- `/agent/stop`
- Markdown
- code syntax highlight
- Thinking 折叠
- Tool Timeline
- Sources
- 推荐问题
- Stop generation

真实联调已验证：

```text
thinking -> text -> recommend -> complete
```

以及联网工具链：

```text
tool_start -> tool_end -> text -> reference -> recommend -> complete
```

Chat 后端现在已经是“通用 AI 助手 + 按需联网”，不要再恢复成特定企业查询助手人设。

## 2.3 当前 SSE 回归测试

已有：

- `src/stream/parser.test.ts`
- `src/stream/reducer.test.ts`

当前覆盖：

- arbitrary SSE chunk splitting
- 无 trailing blank line
- unknown event type
- thinking/text reducer
- tool_start/tool_end
- reference normalize / dedupe
- recommendation normalize / dedupe
- transient error
- terminal error + complete

当前基线：

```text
7 tests passed
```

## 2.4 已存在但尚未完整真实验收的 UI

已经存在代码，不要重新从零设计：

- Session Sidebar
- File upload UI
- File attachment state
- Skills mode
- Deep Research progress
- PPT progress
- PPT Open / Download

后续重点是“真实接通与完善状态”，不是重做 UI。

---

# 3. 推荐实施顺序

建议后续模型严格按以下优先级推进：

```text
Phase A  Chat UX 完善
Phase B  Session 真持久化
Phase C  File Agent 真闭环
Phase D  Deep Research / Skills 完善
Phase E  PPT 真闭环
Phase F  Browser E2E + Mobile / Accessibility QA
Phase G  最终视觉 polish
```

不要为了同时完成所有 Agent 而降低 Chat 和基础交互质量。

---

# 4. Phase A — Chat UX 完善

这一阶段不依赖 Docker，应优先完成。

## A1. 智能 Auto-scroll

### 当前问题

当前 streaming 时每次内容变化都会自动滚到底部。

用户如果正在向上查看旧内容，新 token 可能把页面重新拉回底部。

### 目标行为

```text
用户当前接近底部
    -> streaming 自动跟随

用户主动向上滚动
    -> 暂停自动跟随

有新内容
    -> 显示 “回到最新” 控件

用户点击“回到最新”
    -> 滚到底部并重新开启自动跟随
```

### 验收

- 长回答 streaming 时可自由向上浏览。
- 用户离开底部后不再被强制拉回。
- 回到底部后自动恢复 follow mode。
- Mobile 同样可用。
- `prefers-reduced-motion` 时避免强制 smooth animation。

---

## A2. Retry / Regenerate

### 目标

AI 请求失败后，不要求用户重新输入整个问题。

建议 AI 消息支持：

```text
Copy
Regenerate
```

失败状态支持：

```text
Generation failed
[ Try again ]
```

### 实现要求

- Retry 必须复用原用户问题。
- 不复制一条假的用户消息。
- streaming 中禁止重复 retry。
- Retry 仍然走统一 SSE reducer。
- 若当前后端不支持删除/覆盖上一轮历史，应先明确会话语义，不要假装是真正“覆盖回答”。

### 验收

- 网络错误后可一键重新执行。
- UI 不出现重复 loading / 多个并发请求。
- Stop 后是否允许 Regenerate 要有明确行为。

---

## A3. 用户消息操作

建议增加轻量 hover / focus actions：

- Copy
- Resend

“Edit and resend”可以作为后续增强，不是第一优先级。

不要在每条消息旁永久展示一排按钮。

---

## A4. Code block Copy

当前 Markdown 已支持代码高亮，但代码块缺少独立 Copy。

### 目标

代码块右上角轻量展示：

```text
python     Copy
```

### 验收

- 不影响横向滚动。
- Copy 复制纯代码文本，不包含 Markdown fence。
- 支持键盘 focus。
- Mobile 可点击。
- 不破坏 DOMPurify 安全策略。

---

## A5. Better Error UX

统一错误分层：

### Composer-level

用于：

- 文件类型错误
- 上传错误
- 当前模式不允许发送
- Stop API 失败

### Assistant-level

用于：

- Agent error event
- stream connection error
- provider failure
- terminal failure

### 要求

- 不只显示“Something went wrong”。
- 优先展示后端稳定 `message` / `code`。
- `detail` 默认折叠。
- transient retry error 不应提前终止 streaming。

---

# 5. Phase B — Session 真持久化

> 状态（2026-08-26）：前端完善与 MySQL 数据库模式真实契约验收已完成。已验证 Chat 写入、Session List/Detail、后端重启后恢复、删除后持久消失；浏览器级点击/刷新 E2E 仍统一放在 Phase F。

## 当前状态

前端已经实现：

- `/session/list`
- `/session/{conversationId}`
- DELETE session
- Sidebar history
- route `/c/:conversationId`
- restore agent type
- restore messages

但当前本地后端运行：

```text
PERSISTENCE_MODE=memory
```

因此 `/session/list` 返回 503。

## 后续目标

在数据库模式下完成真实验收。

### 必验流程

```text
新建 Chat
-> 发送 2~3 轮
-> 刷新浏览器
-> Sidebar 出现会话
-> 点击会话
-> 恢复 user / answer / thinking / reference / recommend
-> 删除会话
-> Sidebar 立即更新
-> 刷新后确认确实删除
```

### 还应完善

- Sidebar loading skeleton 或更自然的 loading 状态。
- Session load failure 提供 retry。
- 空历史保持极简，不增加空状态大卡片。
- 超长标题正确 truncate。
- 当前 Session 删除后安全回到 New Chat。

### 可选增强

如果后端未来支持，再增加：

- rename conversation
- search history
- pagination / infinite loading

当前后端没有 API 时不要伪实现。

---

# 6. Phase C — File Agent 真闭环

> 状态（2026-08-27）：前端完善与真实 File Agent 闭环已完成。已验证小 TXT 直读、PNG Vision、大文本 PgVector RAG、MinIO 对象存储、File Session 持久化与文件元数据恢复；浏览器级上传/拖拽 E2E 仍统一放在 Phase F。

## 当前前端已有

- drag & drop
- file picker
- upload progress
- file name
- file size
- upload state
- remove
- 50 MB client validation
- File Agent mode
- `fileId`
- `/agent/file/stream`

当前支持前端限制：

- PDF
- DOCX
- TXT
- PNG
- JPG/JPEG

后端 contract 当前一次 File Agent 请求只接受一个 `fileId`，不要在前端伪造多文件问答。

## 后端依赖

最少：

```text
Database + MinIO
```

大文件 RAG：

```text
Database + MinIO + PgVector
```

## 必验流程

### 小文本文件

```text
上传 TXT/PDF
-> 进度完成
-> ready
-> 发送问题
-> thinking
-> tool timeline
-> answer
-> complete
```

### 图片

```text
上传 PNG/JPG
-> Vision 处理成功
-> 进入 File 问答
-> 返回基于图片内容的回答
```

### 大文件

```text
上传大文件
-> embedding / RAG 链路成功
-> 问文件中的局部信息
-> 返回正确片段相关答案
```

## UI 仍需完善

- 上传失败 Retry。
- 文件处理阶段和纯上传阶段如果后端能区分，应展示真实状态。
- 删除失败需要保留附件而不是 UI 先消失。
- 上传中的取消操作需要明确状态。
- File Agent 历史会话恢复附件名称，而不是只显示 fileId。

---

# 7. Phase D — Skills Agent 完善

> 状态（2026-08-27）：Phase D 前端实现已完成。Tool Timeline 已覆盖 Skills Agent 当前真实工具名、并发工具顺序、重试中状态和长 JSON/长结果滚动；已通过 `/agent/skills/stream` 做真实 SSE 联调。运行环境仍未安装可成功读取的 Skill，且 `agent-workspace` 目录当前不存在，因此 `read_skill` 与 filesystem 成功态的业务演示仍受环境数据限制，不属于前端阻断项。

## 当前状态

`/agent/skills/stream` 已真实请求成功，并已验证：

- `web_search`：真实产生配对的 `tool_start/tool_end`；当前 provider 返回 demo source。
- `loadContent`：通过临时上传文件真实产生配对的 `tool_start/tool_end`，联调文件已清理。
- `list_files + grep`：真实在同一轮并发发出多个 `tool_start`，callId 与对应 `tool_end` 可正确追踪；当前 workspace 根目录不存在，后端返回受控错误。
- `read_skill`：真实产生配对事件；当前 `SKILLS_DIRECTORIES=./skills` 下没有已安装 Skill，因此返回“未找到技能”的受控结果。

前端不伪造 Skill、filesystem 或 provider 成功态；待运行环境补齐真实 Skill/workspace 后只需复跑业务验收，不需要重新设计 Tool Timeline。

## 目标

至少选择 2~3 个真实 Skill 场景验证：

- read_skill
- web search
- file content
- grep / filesystem（如果环境允许）

## UI 要求

仍然使用普通 Chat UI，不做复杂技能控制台。

主要通过 Tool Timeline 展示：

```text
Reading skill instructions
Searching the web
Reading file
Searching workspace text
```

### 待完善

- Tool name 映射覆盖真实后端工具名称。
- transient retry error 保持 running。
- 同一轮多个工具调用顺序正确。
- 展开参数/结果时长 JSON 不撑破布局。
- Tool result 超长内容做 max-height + scroll。

---

# 8. Phase D2 — Deep Research 完善

> 状态（2026-08-27）：前端 Research progress 完善已完成，并已真实验证 clarification/pause、第一轮完整研究阶段和多轮迭代进入下一轮。当前运行环境 `SEARCH_MODE=demo`，真实完整流会因 Demo 搜索结果被 critique 拒绝并继续迭代，因此 Tavily Sources 与本轮最终报告仍需在真实搜索 provider 配置后补做验收；不得将其标记为已通过。

## 当前状态

Deep Research 后端 contract 已具备最终报告与 reference 输出能力；前端仍只根据真实 `thinking` 文本保守识别阶段，不依赖不存在的结构化 Plan 数据。

前端目前通过真实 `thinking` 文本保守识别：

- Understand the question
- Build the research plan
- Research the topic
- Review the findings
- Final synthesis

不要把它升级成后端不存在的结构化 Plan 数据。

## 待完善

### Research progress

- streaming 时当前阶段明确。
- 已完成阶段使用弱化 check。
- 最终报告出现后 progress 自动弱化。
- clarification / pause 状态要正确展示。

### Sources

Deep Research 尤其需要验证真实 Tavily Sources：

- title
- domain
- URL
- dedupe
- large source count
- mobile layout

### 最终报告

- 长报告阅读宽度保持 60~75ch。
- heading hierarchy 清晰。
- table / code / blockquote 不横向撑破页面。

---

# 9. Phase E — PPT Agent 真闭环

> 状态（2026-08-27）：前端状态闭环与真实后端验收已完成。已验证 Requirement clarification pause、stage failure、CREATE/RESUME、MODIFY、真实 MinIO `.pptx` URL、Open/Download 数据来源，以及下载后的 `.pptx` 可被 `python-pptx` 重新打开。浏览器级点击 Open/Download 仍统一放在 Phase F。
>
> 本阶段新增 PPT progress 单测，覆盖 CREATE、pause、failure、stop、transport error、MODIFY、RESUME 和 `.pptx` URL/文件名提取。真实验收中 RESUME 可从 `SCHEMA` / `RENDER` 状态继续，MODIFY 复用同一 PPT 实例并生成新的文件 URL；Requirement 信息不足时保持 `REQUIREMENT`，不会假显示后续阶段。
>
> 后端质量收尾（2026-08-27）已完成：显式页数现在是 Schema 硬约束，首次输出不满足时会自动 repair，repair 后仍不满足则停在 `SCHEMA` 而不会进入 Render；真实集成已验证数据库 Schema 与下载后的 `.pptx` 都严格为 5 slides。MODIFY 对明确文本替换增加语义校验，并确保 `fontLimit` 不会截断必须逐字生效的目标文本；真实修改后数据库封面标题和最终 `.pptx` 均精确命中 `Transformer Attention Verified`。renderer 同时兼容模板 Schema 的 `pageIndex` 与 `templatePageIndex`，真实 5 页文件已验证分别使用封面 / 目录 / 对比 / 内容 / 结束页模板。

## 当前前端已有

基于真实 thinking 文本保守识别：

- Requirement
- Research
- Template
- Outline
- Slides
- Images
- Render

并且只有回答中真实存在 URL 时才显示：

```text
Presentation ready
[ Open PPT ] [ Download ]
```

不要伪造 PPT slide preview。

## 后端依赖

完整 PPT 需要至少：

- Database
- PPT templates
- MinIO
- renderer
- 图片生成 provider（需要生成图片时）

## 必验流程

```text
输入 PPT 需求
-> Requirement
-> Research
-> Template
-> Outline
-> Slides
-> Images（若需要）
-> Render
-> final file URL
-> Open PPT
-> Download
-> 实际 .pptx 可被 PowerPoint 打开
```

## UI / 验收已完成

- Failure stage 明确展示。
- Requirement 需要补充信息时停在当前阶段，不假显示后续步骤。
- MODIFY / RESUME 已完成真实场景验证。
- 下载链接只来自真实后端结果。
- 文件名展示可读，不直接把超长 URL 当主要文本。
- 显式页数约束与 MODIFY 最终文件语义已完成真实后端验证。

---

# 10. Phase F — Browser E2E

> 状态（2026-08-27）：已完成。已引入 Playwright，并以真实浏览器 + 真实前端 SSE/Pinia/Router 链路、网络边界确定性 mock 的方式覆盖 Chat smoke、Stop、Tool + Sources、1440/1024/768/390 响应式与 Light/Dark/System theme persistence。当前 `e2e/browser.spec.ts` 共 8 个浏览器测试通过；真实后端业务闭环继续由 Phase B–E 的联调验收负责。

当前 unit test 不能代替真正浏览器验收。

建议引入 Playwright，保持测试数量少而关键。

## 第一组：Chat smoke

```text
打开 /
-> 输入消息
-> Enter
-> user message 出现
-> Thinking 出现
-> AI text 出现
-> complete
```

## 第二组：Stop

```text
发送长请求
-> streaming
-> 点击 Stop
-> 停止状态稳定
```

## 第三组：Tool + Sources

```text
触发联网
-> tool timeline
-> tool complete
-> sources 出现
-> source 可点击
```

## 第四组：Responsive

至少验证：

- 1440px
- 1024px
- 768px
- 390px

检查：

- no horizontal body overflow
- Mobile sidebar drawer
- Composer 不遮挡最后消息
- code block 自己横向滚动
- Sources 自适应
- touch target

## 第五组：Theme

- Light
- Dark
- System

刷新后 theme persistence 正常。

---

# 11. Phase F2 — Accessibility QA

> 状态（2026-08-27）：已完成。新增 `e2e/accessibility.spec.ts`，覆盖键盘可达性与 focus-visible、Agent mode `aria-pressed` 状态、Tool Details / Sources 键盘访问、Settings 与 Mobile Sidebar modal focus containment、ESC 关闭与焦点恢复、移动 Sidebar → Settings 焦点回归、streaming/complete/stopped/error live semantics、`prefers-reduced-motion`、Light/Dark 关键文本 token 对比度。Mobile Sidebar 已改为原生 modal `<dialog>`；Chat/PPT 状态补充 live region；Light/Dark 低对比度辅助文字 token 已修正。当前 Playwright 总计 13 tests passed（Phase F 8 + Phase F2 5）。

必须检查：

- semantic HTML
- `button` 不使用 clickable div
- icon-only buttons 有 aria-label
- mode selector 有正确 selected semantics
- focus-visible 清晰
- keyboard 可进入 Sidebar / Composer / Sources / Tool Details
- dialogs focus behavior
- ESC 关闭 Settings / Mobile drawer（建议补）
- screen reader 可感知 streaming status
- error 使用 `role="alert"` / 合理 live region
- `prefers-reduced-motion`
- color contrast

特别注意：

Composer textarea 不应再次出现被裁切成横线的 focus outline。Composer 可通过整个容器提供中性 focus-within 反馈。

---

# 12. Phase G — 最终视觉 Polish

> 状态（2026-08-27）：已完成。保持既有 Minimal / Calm / Clean / Focused / Soft / Professional 方向，仅做减法式视觉收尾：收紧 Sidebar 宽度与分组节奏、优化 Composer 高度比例与辅助提示、重排一问一答的垂直节奏、细化 Markdown heading 间距、弱化 Thinking 与 Sources 层级、压缩 Tool Timeline 密度，并将移动端底部留白调整为基础间距 + `safe-area-inset-bottom`。未新增 dashboard cards、gradient、glassmorphism、AI glow、装饰 widget、额外 badge 或大面积品牌色。
>
> 回归结果：`npm run test` 33 tests passed；`npm run typecheck`、`npm run lint`、`npm run build` 全部通过；Playwright 使用本机 Edge channel 运行 13 tests passed，覆盖 1440/1024/768/390、Light/Dark/System、键盘可达性、dialogs、Tool/Sources 与 reduced motion。

此阶段最后做，不应早于真实业务闭环。

重点只精修：

- Sidebar spacing
- Composer proportion
- message rhythm
- Markdown heading spacing
- Thinking hierarchy
- Tool Timeline density
- Sources hierarchy
- empty/new chat spacing
- Dark mode contrast
- Mobile bottom safe area

不要增加：

- dashboard cards
- gradients
- glassmorphism
- AI glow
- decorative widgets
- 多余 badge
- 大面积品牌色

原则：

> 优先删除和减弱，而不是继续添加装饰。

---

# 13. 真实联网配置验收

当前开发阶段曾使用：

```text
SEARCH_MODE=demo
```

因此正式演示前必须切换真实搜索 provider，例如 Tavily，并重新验证：

```text
Chat Search
Deep Research
Sources
```

不能让正式演示中的 Sources 指向：

```text
example.com/demo-search
```

---

# 14. 建议后续模型的第一轮任务

如果下一位模型开始实现前端完善，推荐直接使用下面的任务范围：

```text
只修改 DeepDesk/web。
先读取 FRONTEND_IMPROVEMENT_PLAN.md 和当前代码。
不要重构 SSE / Pinia / API 架构。

第一轮只完成 Phase A：
1. 智能 auto-scroll
2. scroll-to-latest
3. Retry / Regenerate
4. Code block Copy
5. Error UX

完成后运行：
npm run test
npm run typecheck
npm run lint
npm run build

不要提前实现 Session/File/PPT，除非本轮基础 UX 已完整通过。
```

---

# 15. Definition of Done

前端最终可以认为完成，需要满足：

- Chat Agent 真连接稳定。
- SSE 8 类事件 reducer 稳定。
- Stop 稳定。
- Markdown / code / sources 可读。
- Streaming 不干扰用户手动浏览历史内容。
- Retry/Regenerate 有明确恢复路径。
- Session 刷新后可恢复。
- File upload + File Agent 真闭环。
- Skills 有至少 2 个真实工具场景。
- Deep Research 真搜索 + Final Report + Sources。
- PPT 真生成 + Open + Download。
- Desktop / Tablet / Mobile 无主要布局问题。
- Light / Dark 正常。
- Playwright 核心 E2E 通过。
- Accessibility 无明显阻断问题。
- `npm run test` / `typecheck` / `lint` / `build` 全部通过。

完成这些以后，再考虑非必要增强功能。