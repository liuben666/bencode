# BenCode Tool Call Engine - 开发任务

## 任务总览

共 12 个任务，按依赖顺序排列。涉及外部 API（OpenAI / Anthropic 工具调用协议）的任务，编码前必须通过 context7 MCP 查询最新官方文档确认参数格式。

---

### T01：工具接口与结构化结果模型

**描述**：新建 tools 包，定义统一工具抽象：元信息（名称、描述、参数 JSON Schema）+ 异步执行入口；定义结构化工具结果模型（成功/失败标记、输出内容、错误信息、是否被截断等）。风格对齐现有 provider/base.py 的抽象方式。  
**影响文件**：`bencode/tools/__init__.py`、`bencode/tools/base.py`  
**前置依赖**：无  
**参考资料**：`bencode/provider/base.py`（抽象基类与 dataclass 风格）、JSON Schema 规范

---

### T02：六个核心工具实现

**描述**：实现六个内置工具。读文件（支持行区间读取，便于大文件分段）；写文件（新建/覆盖）；改文件（原文唯一匹配替换，匹配 0 处或 ≥2 处时返回含原因与匹配数的错误，供模型修正重试）；执行命令（异步子进程，合并 stdout/stderr，返回退出码，默认超时 60 秒）；按模式查找文件（glob 语法，支持忽略目录）；按内容搜索（正则匹配，返回文件路径+行号+该行内容）。  
**影响文件**：`bencode/tools/builtin.py`  
**前置依赖**：T01  
**参考资料**：pathlib、fnmatch、re、asyncio.subprocess 标准库文档

---

### T03：工具注册中心

**描述**：集中登记六个内置工具；按名查找（未注册时报错并含工具名）；分别导出 OpenAI 协议格式（`type: "function"` + `function.name/description/parameters`）与 Anthropic 协议格式（`name/description/input_schema`）的工具清单。  
**影响文件**：`bencode/tools/registry.py`  
**前置依赖**：T02  
**参考资料**：context7 查询 OpenAI Chat Completions tools 参数格式、Anthropic Messages API tools 参数格式

---

### T04：消息模型与流式块扩展

**描述**：扩展统一消息结构：assistant 消息可携带工具调用列表（调用 ID、工具名、参数对象）；新增工具角色消息（关联调用 ID、结果内容）。扩展流式块类型：新增完整工具调用事件（携带调用 ID、工具名、已拼装参数）。会话序列化/反序列化覆盖新字段，旧会话文件（无新字段）加载不报错。  
**影响文件**：`bencode/provider/base.py`、`bencode/session/models.py`  
**前置依赖**：无  
**参考资料**：`bencode/provider/base.py`（MessageContent/StreamChunk 定义，L20-L37）、`bencode/session/models.py`（to_dict/from_dict，L24-L61）

---

### T05：OpenAI 适配器工具调用支持

**描述**：请求携带工具清单（工具存在时）；流式解析增量中的工具调用：按调用 ID 聚合多个工具调用槽位，参数 JSON 字符串碎片拼接，流结束时整体反序列化校验并产出统一工具调用事件；消息构建支持回传 assistant 工具调用消息（tool_calls 数组）与 tool 角色结果消息（tool_call_id + content）。  
**影响文件**：`bencode/provider/openai.py`  
**前置依赖**：T03、T04  
**参考资料**：context7 查询 OpenAI Chat Completions 流式 function calling（delta.tool_calls 结构、finish_reason="tool_calls"、tool 角色消息格式）

---

### T06：Anthropic 适配器工具调用支持

**描述**：请求携带工具清单（工具存在时）；流式解析 tool_use 内容块（input_json_delta 增量拼接、content_block_stop 收尾取调用 ID 与工具名）；消息构建：历史 assistant 工具调用还原为 tool_use 块，工具结果还原为 user 消息内的 tool_result 块（含 tool_use_id），满足 API 对工具结果必须紧跟对应调用的要求。与 thinking 块共存时保持现有 signature 逻辑不变。  
**影响文件**：`bencode/provider/anthropic.py`  
**前置依赖**：T03、T04  
**参考资料**：context7 查询 Anthropic Messages API tool use（流式事件 input_json_delta、tool_result 块格式、thinking 与 tool use 共存约束）

---

### T07：工具执行器

**描述**：接收工具名与参数：按名查找（未注册返回结构化错误）→ 参数校验（缺失/类型错误返回结构化错误）→ 异步执行并施加统一超时（asyncio 超时控制，默认 60 秒，超时返回超时错误）→ 捕获一切异常包装为失败结果 → 输出超过 10000 字符时截断并在结果中标注截断与原始长度。全程不向调用方抛异常。  
**影响文件**：`bencode/tools/executor.py`  
**前置依赖**：T03  
**参考资料**：asyncio.wait_for 文档、T01 的结果模型

---

### T08：工具折叠卡片组件

**描述**：新建工具调用折叠卡片组件，交互风格对齐现有 thinking 折叠区块：默认折叠仅显示摘要行（图标+工具名+状态+耗时）；展开显示参数（键值/JSON 形式）与结果内容；状态覆盖：执行中、成功、失败、被拒绝、超时，有可区分的视觉标识（颜色/图标）。  
**影响文件**：`bencode/tui/widgets/tool_block.py`、`bencode/tui/widgets/__init__.py`  
**前置依赖**：无  
**参考资料**：`bencode/tui/widgets/thinking_block.py`（折叠交互实现）

---

### T09：危险操作确认界面

**描述**：新建模态确认界面：展示工具名、关键参数摘要，键盘 y/Enter 确认、n/Esc 拒绝；异步等待用户选择并把结果（允许/拒绝）交回调用方。仅写文件、改文件、执行命令三类工具触发；读文件、查找、搜索跳过确认。  
**影响文件**：`bencode/tui/screens/confirm.py`（新建）、`bencode/tui/screens/__init__.py`  
**前置依赖**：无  
**参考资料**：Textual 官方文档 ModalScreen / push_screen(await_modal) 用法（context7 查询）

---

### T10：ChatScreen 工具调用主流程接入

**描述**：改造现有流式回复 worker（`_stream_ai_response`，chat.py L254-L328）：识别流式块中的工具调用事件 → 渲染折叠卡片（执行中）→ 危险操作走确认界面（拒绝则产生拒绝结果）→ 交执行器执行 → 更新卡片（结果/状态/耗时）→ 工具调用与结果写入会话并持久化 → 用更新后的历史自动发起第二次模型请求，产出最终回复 → 本轮结束。单轮边界：收尾回复若再次携带工具调用，则不执行，卡片/错误区显示明确提示（含"不支持连续调用"字样）。  
**影响文件**：`bencode/tui/screens/chat.py`  
**前置依赖**：T04、T05、T06、T07、T08、T09  
**参考资料**：`bencode/tui/screens/chat.py`（现有 worker 与消息保存逻辑）

---

### T11：接入主流程与持久化联动

**描述**：全链路串联：应用启动时初始化注册中心并注入对话链路；工具调用/结果消息持久化到会话 JSON；`--session` 恢复会话时历史工具消息正确回传 API，TUI 以折叠卡片还原历史工具调用；/help 帮助文本补充工具系统说明。  
**影响文件**：`bencode/tui/app.py`、`bencode/tui/screens/chat.py`、`bencode/session/manager.py`（如需）  
**前置依赖**：T10  
**参考资料**：`bencode/tui/app.py`、`bencode/session/manager.py`

---

### T12：端到端验证

**描述**：在 tmux 环境中启动 BenCode，输入真实业务请求（读文件、写文件、改文件、执行命令、搜索代码），观测：模型工具识别是否准确、确认交互是否符合预期、工具执行与卡片展示、结果回灌后的最终回复质量；对照 checklist.md 逐项完成验收，双协议（OpenAI / Anthropic）各跑一遍核心用例。  
**影响文件**：无新增（纯验证任务）  
**前置依赖**：T11  
**参考资料**：`docs/tool-call-engine/checklist.md`
