# BenCode LLM TUI Client - 开发任务

## 任务总览

共 12 个任务，按依赖顺序排列。

---

### T01：项目骨架与包结构初始化

**描述**：创建 Python 包目录结构、`pyproject.toml`、入口模块，确保 `python -m bencode` 可运行。  
**影响文件**：`pyproject.toml`、`bencode/__init__.py`、`bencode/__main__.py`  
**前置依赖**：无  
**参考资料**：Python 包规范、Textual 项目模板

---

### T02：YAML 配置加载与校验

**描述**：实现 YAML 配置文件的读取、解析、字段校验。支持多个 provider 配置项，校验必填字段（name、protocol、model、base_url、api_key），可选字段（thinking）。配置不存在时生成模板文件并提示用户。  
**影响文件**：`bencode/config/__init__.py`、`bencode/config/loader.py`、`bencode/config/schema.py`  
**前置依赖**：T01  
**参考资料**：PyYAML 文档、Python dataclasses / pydantic

---

### T03：CLI 参数解析

**描述**：使用 argparse 解析命令行参数 `--provider <name>` 和 `--session <id>`，与配置加载联动：根据参数决定是否需要展示选择界面或直接进入对话。  
**影响文件**：`bencode/cli.py`  
**前置依赖**：T02  
**参考资料**：Python argparse 文档

---

### T04：Provider 抽象接口定义

**描述**：定义统一的 Provider 抽象基类，核心方法包括：发送消息（流式）、获取模型信息。所有后端适配器必须实现该接口。定义统一的消息数据结构（角色、内容、thinking 区块等）。  
**影响文件**：`bencode/provider/__init__.py`、`bencode/provider/base.py`  
**前置依赖**：T01  
**参考资料**：Python ABC 文档

---

### T05：Anthropic Claude 适配器实现

**描述**：基于 Provider 抽象接口，实现 Anthropic Claude 后端适配器。处理 SSE 流式响应解析，支持 extended thinking（启用时从响应中提取 thinking 块），处理 Anthropic 特有的消息格式和错误码。  
**影响文件**：`bencode/provider/anthropic.py`  
**前置依赖**：T04  
**参考资料**：Anthropic Messages API 文档（SSE streaming、extended thinking）

---

### T06：OpenAI 适配器实现

**描述**：基于 Provider 抽象接口，实现 OpenAI 后端适配器。处理 SSE 流式响应解析（与 Anthropic 的 SSE 格式不同），处理 OpenAI 特有的消息格式和错误码。OpenAI 无 thinking 功能，对应字段始终为空。  
**影响文件**：`bencode/provider/openai.py`  
**前置依赖**：T04  
**参考资料**：OpenAI Chat Completions API 文档（SSE streaming）

---

### T07：Provider 工厂与注册机制

**描述**：实现工厂函数，根据配置中的 protocol 字段自动创建对应的 Provider 实例。协议字符串与适配器类的映射可扩展，新增后端只需注册即可。  
**影响文件**：`bencode/provider/factory.py`  
**前置依赖**：T05、T06  
**参考资料**：工厂模式

---

### T08：会话管理（持久化与加载）

**描述**：实现会话的创建、持久化、加载、列表查询。每个会话包含唯一 ID、创建时间、provider 信息、消息列表。会话文件存储为 JSON 格式。实现 `/history` 命令的数据查询逻辑。  
**影响文件**：`bencode/session/__init__.py`、`bencode/session/manager.py`、`bencode/session/models.py`  
**前置依赖**：T04（消息数据结构）  
**参考资料**：Python json 模块

---

### T09：Textual TUI 主应用框架

**描述**：搭建 Textual App 主类，定义应用生命周期（启动、挂载组件、退出）。实现 Provider 选择界面（列表展示配置中所有 provider，用户选择后进入对话）。实现状态栏（显示当前 provider、模型名、会话 ID）。  
**影响文件**：`bencode/tui/__init__.py`、`bencode/tui/app.py`、`bencode/tui/screens/provider_select.py`、`bencode/tui/styles.tcss`  
**前置依赖**：T02、T03、T07  
**参考资料**：Textual 官方文档（App、Screen、Widget 生命周期）

---

### T10：对话界面与消息渲染

**描述**：实现主对话界面：用户输入区、消息列表展示区。AI 回复使用 Textual 的 Markdown 组件渲染富文本。实现流式逐字追加显示效果。实现用户输入的 `/history` 命令拦截与响应。  
**影响文件**：`bencode/tui/screens/chat.py`、`bencode/tui/widgets/message_list.py`、`bencode/tui/widgets/input_area.py`  
**前置依赖**：T08、T09  
**参考资料**：Textual Markdown 组件文档、Static Widget 动态更新

---

### T11：Thinking 折叠区块组件

**描述**：实现可折叠的 thinking 展示组件：默认折叠状态，显示"💭 Thinking..."摘要行；用户按快捷键展开查看完整 thinking 内容；折叠/展开状态切换有视觉动画反馈。当 AI 回复包含 thinking 块时，自动插入该组件。  
**影响文件**：`bencode/tui/widgets/thinking_block.py`  
**前置依赖**：T10  
**参考资料**：Textual Collapsible 组件文档

---

### T12：接入主流程与端到端验证

**描述**：串联所有模块：CLI 入口 → 配置加载 → Provider 选择/指定 → 会话初始化 → TUI 启动 → 用户对话 → 流式响应 → 持久化。在 tmux 环境中启动 BenCode，执行真实对话，验证全链路通畅。对照 checklist.md 逐项验收。  
**影响文件**：`bencode/__main__.py`（最终串联调整）  
**前置依赖**：T11  
**参考资料**：checklist.md
