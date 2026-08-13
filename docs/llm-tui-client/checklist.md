# BenCode LLM TUI Client - 验收清单

## 配置管理

- [ ] `python -m bencode --help` 正常输出帮助信息，包含 `--provider` 和 `--session` 参数说明
- [ ] `~/.bencode/config.yaml` 不存在时首次启动，自动生成含注释模板的配置文件，终端给出提示
- [ ] 配置文件中写入 2 条不同 provider（1 条 Anthropic、1 条 OpenAI），启动后选择列表正确展示 2 个选项
- [ ] 配置文件缺少必填字段（如缺少 api_key）时，启动报错并提示具体缺失字段名
- [ ] `python -m bencode --provider <name>` 指定一个已配置的 provider 名称，跳过选择界面直接进入对话

## Provider 适配

- [ ] 选用 Anthropic provider，发送一条消息，AI 回复以 SSE 流式逐字显示，非一次性返回
- [ ] 选用 OpenAI provider，发送一条消息，AI 回复以 SSE 流式逐字显示，非一次性返回
- [ ] Anthropic provider 的 thinking 字段设为启用时，AI 回复中出现可折叠的 thinking 区块
- [ ] Anthropic provider 的 thinking 字段未设置或设为禁用时，AI 回复中不出现 thinking 区块
- [ ] OpenAI provider 发送消息正常，不出现 thinking 相关区块（OpenAI 无此功能）
- [ ] Provider 接口定义文件中包含抽象基类，新增后端只需继承实现，无需修改工厂以外代码

## 会话与多轮对话

- [ ] 启动新会话后发送 2 轮对话，第 2 轮 AI 回复能引用/感知第 1 轮的内容
- [ ] 退出 BenCode 后，`~/.bencode/sessions/` 下存在对应的 `.json` 文件
- [ ] `python -m bencode --session <id>` 可恢复指定历史会话，继续对话，AI 能感知历史上下文
- [ ] TUI 内输入 `/history` 命令，展示最近会话列表（包含会话 ID、创建时间、provider 名称）

## TUI 交互

- [ ] 默认启动（无 `--provider` 参数）展示 provider 选择界面，键盘上下键选择，回车确认
- [ ] AI 回复中的 Markdown 内容正确渲染：代码块有语法高亮、列表有序/无序、加粗文本、表格对齐
- [ ] Thinking 折叠区块默认显示为折叠状态，仅展示"💭 Thinking..."摘要行
- [ ] 按 Tab 键（或其他指定快捷键）可展开 thinking 区块查看完整内容，再按可折叠回去
- [ ] 状态栏正确显示当前 provider 名称、模型名称、会话 ID
- [ ] 网络断开或 API 返回错误时，TUI 显示可读错误提示，程序不崩溃

## 端到端验收

- [ ] 在 tmux 中启动 BenCode → 选择 Anthropic provider → 输入"请用 Python 写一个快速排序" → 观测流式回复逐字出现、代码块有语法高亮 → 输入"加一下注释" → AI 回复能基于上一轮代码添加注释 → 输入 `/history` → 看到当前会话 → 退出 → 用 `--session` 恢复该会话 → 继续对话正常
