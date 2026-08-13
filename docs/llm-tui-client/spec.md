 # BenCode LLM TUI Client - 需求规格

## 背景

BenCode 定位为终端 AI 编程助手（对标 Claude Code）。本项目为 BenCode 的第一个里程碑：实现一个可用的交互式对话 TUI，用户在终端中与 AI 进行多轮流式对话。本阶段为纯对话，不涉及 tool use、文件操作、代码执行等 Agent 能力。

## 目标用户

- 希望在终端环境中与 LLM 进行对话交互的开发者
- 需要在 Anthropic Claude 与 OpenAI 之间切换使用的用户
- 追求轻量、快捷命令行 AI 体验的技术人员

## 能力清单

1. 用户在终端启动 BenCode 后，进入 Textual 构建的交互式 TUI 界面
2. 用户输入问题后，调用配置指定的 LLM 后端，将回复以 SSE 流式方式逐字打印到界面
3. 支持多轮对话，AI 能感知之前所有轮次的上下文
4. 对话历史持久化到本地文件，退出后不丢失
5. 支持 Anthropic Claude 和 OpenAI 两种 API 协议后端，通过 YAML 配置切换
6. Provider 层抽象为统一接口，新增后端只需实现该接口，无需修改上层逻辑
7. 支持 Claude extended thinking，thinking 内容以可折叠区块展示，默认折叠，快捷键展开
8. YAML 配置文件支持写入多条 provider 配置
9. 默认启动时展示 provider 选择列表界面
10. 支持命令行参数 `--provider` 指定配置名称，直接跳过选择界面
11. 支持命令行参数 `--session` 恢复指定历史会话继续对话
12. TUI 内提供 `/history` 命令列出最近会话
13. AI 回复中的 Markdown 内容在终端中做富文本渲染（代码高亮、列表、表格、加粗等）
14. 每次启动默认开启新会话，自动生成唯一会话 ID

## 非功能要求

| 维度 | 要求 |
|------|------|
| 配置路径 | `~/.bencode/config.yaml` |
| 会话存储路径 | `~/.bencode/sessions/<session_id>.json` |
| 流式协议 | SSE（Server-Sent Events），逐 token 输出 |
| TUI 框架 | Textual |
| Python 版本 | ≥ 3.10 |
| 配置字段 | 每个 provider 包含：name、protocol、model、base_url、api_key、thinking（可选） |
| 首次启动 | 若配置文件不存在，应引导用户创建初始配置 |
| 网络异常 | 流式请求中断时给出可读提示，不崩溃 |

## 整体设计骨架

```
用户终端输入
     │
     ▼
  CLI 入口（解析参数：--provider, --session）
     │
     ▼
  配置加载层（读取 YAML → 校验 → 生成配置对象）
     │
     ├── 无 --provider → 展示 Provider 选择界面
     └── 有 --provider → 直接匹配配置
     │
     ▼
  Textual TUI 主界面
     │
     ├── 用户输入区
     ├── 消息展示区（Markdown 渲染 + Thinking 折叠区块）
     └── 状态栏（当前 provider、模型、会话 ID）
     │
     ▼
  Provider 抽象层（统一接口：发送消息、流式接收）
     │
     ├── Anthropic 适配器（SSE → 统一流）
     └── OpenAI 适配器（SSE → 统一流）
     │
     ▼
  会话管理层（上下文拼接、持久化读写）
```

## Out of Scope（本期不做）

- Tool use / Function calling
- 文件读写、代码编辑操作
- 代码沙箱执行
- 多模型并发对话
- 插件/扩展系统
- 联网搜索
- 图片输入/输出
- Token 计费统计
- 对话导出为文件
