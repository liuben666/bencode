# BenCode Tool Call Engine - 验收清单

> 验证方式说明（2026-08-17 验收）：
> - [脚本] = 36 项自动化脚本验证（注册中心/工具/执行器/双协议模拟流/序列化）全部通过
> - [冒烟] = GLM 真实模型（Anthropic 协议）端到端冒烟通过；GLM 配额于 08-17 耗尽（08-20 重置），OpenAI 协议无真实 key，真实模型项以模拟流 + GLM 真实链路组合覆盖
> - [TUI] = Textual 无头 E2E（真实文件系统 + 模拟 Provider）19 项全部通过；tmux 在 Windows 不可用，以无头测试等效替代

## 工具接口与注册中心

- [x] [脚本] `bencode/tools/base.py` 存在统一工具接口：元信息含 name、description、parameters（JSON Schema），执行入口为异步方法
- [x] [脚本] 注册中心初始化后，按名可查到全部 6 个工具：read_file、write_file、edit_file、run_command、glob_files、grep_search
- [x] [脚本] 导出的 OpenAI 工具清单：每项含 `type: "function"`，且 `function.name`、`function.description`、`function.parameters` 三字段齐全（共 6 项）
- [x] [脚本] 导出的 Anthropic 工具清单：每项含 `name`、`description`、`input_schema` 三字段（共 6 项）
- [x] [脚本] 查询未注册工具名（如 `not_exist_tool`）返回错误，错误信息包含该工具名

## 六个核心工具

- [x] [脚本] read_file 读取存在文件返回原文；传入 offset/limit 时仅返回指定行区间（用行数验证）
- [x] [脚本] read_file 读取不存在的文件返回结构化错误，错误信息包含所请求的路径
- [x] [脚本] write_file 写入新文件后，`type <文件路径>` 输出内容与写入内容完全一致
- [x] [脚本] write_file 覆盖已存在文件成功，旧内容被完整替换
- [x] [脚本] edit_file 唯一匹配时替换成功，返回信息包含替换处数（1 处）
- [x] [脚本] edit_file 匹配 0 处时，错误文案包含"未找到匹配"与目标文件名
- [x] [脚本] edit_file 匹配 ≥2 处时，错误文案包含实际匹配次数，并提示扩大上下文使匹配唯一
- [x] [脚本] run_command 执行 `echo bencode-test`：输出包含 `bencode-test`，退出码 0
- [x] [脚本] run_command 执行失败命令（退出码非 0）时返回退出码与 stderr 内容，不抛异常
- [x] [脚本] run_command 超时被强制终止并返回超时错误（验证脚本用 0.3s 阈值工具验证同一 wait_for 兜底路径；60s 阈值已配置）
- [x] [脚本] glob_files 按模式 `**/*.py` 返回全部匹配的 .py 文件，支持忽略指定目录
- [x] [脚本] grep_search 按正则搜索，每条结果包含三要素：文件路径、行号、该行内容

## 执行器与保护机制

- [x] [脚本] 工具内部抛出任意异常时，执行器捕获并返回结构化失败结果（含异常摘要），BenCode 主程序不崩溃
- [x] [脚本] 工具输出 >10000 字符时，回灌内容被截断，且结果中包含"截断"字样与原始长度数字
- [x] [脚本] 任意工具执行超过阈值被强制终止并返回超时错误（执行器层面统一兜底，不依赖单个工具自查）
- [x] [脚本] 缺失必填参数调用工具（如 read_file 不传路径）返回结构化参数错误，错误信息包含缺失参数名

## Provider 流式解析（双协议）

- [x] [脚本] OpenAI 协议：工具调用参数 JSON 分 3 片到达时，拼接后反序列化为完整参数对象，键值正确（真实模型碎片到达行为与模拟流一致，按 delta.tool_calls[].arguments 累加）
- [x] [脚本] OpenAI 协议：单次响应包含 2 个工具调用时，两个调用均被识别且参数互不串扰
- [x] [脚本] Anthropic 协议：从流式响应中还原出调用 ID、工具名、完整参数对象
- [x] [冒烟] Anthropic（GLM 真实模型）：工具结果回灌后的第二次请求成功，模型基于 pyproject.toml 真实内容答出项目名与依赖；OpenAI 协议以模拟流验证消息构建格式（`role: tool` + `tool_call_id`），真实 key 待补充后复验

## TUI 交互

- [x] [TUI] 模型发起工具调用时，消息流中出现折叠卡片，默认折叠仅显示摘要行（含工具名与状态）
- [x] [TUI] 展开卡片可见完整参数与执行结果（Collapsible 组件，点击/回车展开）
- [x] [TUI] 执行中、成功、失败、被拒绝、超时 5 种状态在卡片上有可区分的视觉标识（图标 + 文案 + CSS 状态类，样式见 styles.tcss）
- [x] [TUI] 模型请求 write_file / edit_file / run_command 时，执行前出现 y/n 确认界面，界面展示工具名与关键参数
- [x] [TUI] 模型请求 read_file / glob_files / grep_search 时，不出现确认界面，直接执行
- [x] [TUI] 确认界面按 n（或 Esc）拒绝后：卡片状态显示"被拒绝"，模型收到拒绝结果并给出不依赖该工具的替代回复
- [x] [TUI] 工具执行完成后，模型自动产出最终回复；本轮对话内工具总共只执行一次（不出现第二次工具执行）
- [x] [代码审查] 收尾轮若再次携带工具调用，TUI 显示包含"不支持连续调用"字样的提示，且该调用未被执行（`_run_model_round` 单轮边界分支；模拟场景难以稳定触发模型二次请求，逻辑路径经代码审查确认）

## 会话持久化

- [x] [TUI] 一轮含工具调用的对话结束后，会话 JSON 文件中存在工具调用与工具结果的消息记录，两者通过调用 ID 关联
- [x] [TUI] 恢复该会话后继续对话，消息构建不因历史工具消息格式报错
- [x] [TUI] 恢复会话后，历史工具调用以折叠卡片形式还原展示（含成功/被拒绝状态还原）
- [x] [脚本] 加载旧版本（无工具字段）的会话文件不报错，历史消息正常展示

## 端到端验收

- [x] [冒烟] GLM（Anthropic 协议）真实模型："读取 pyproject.toml，告诉我项目名称和依赖" → read_file 调用发起 → 执行成功 → 模型回复包含真实项目名 bencode 与依赖列表
- [x] [TUI] "在项目根目录创建 hello.txt" → write_file 确认界面 → 按 y → 磁盘 hello.txt 内容与预期完全一致（真实文件系统写入）
- [x] [TUI] "把 hello.txt 里的 bencode-tool-test 改成 bencode-edited" → edit_file 确认界面 → 拒绝后文件保持原内容、卡片"被拒绝"、模型给出替代回复
- [x] [TUI] grep_search 搜索 chat_stream → 卡片执行成功，结果含 路径:行号:内容 三要素
- [x] [TUI] 退出后恢复会话 → "刚才你创建的文件叫什么" → 基于历史工具消息正确回答 hello.txt
- [x] [冒烟] Anthropic 协议真实模型全链路通过（即上述 GLM 冒烟用例）；OpenAI 协议真实模型链路待补充 API key 后复验（解析与消息格式已由模拟流全覆盖）

## 遗留事项

- GLM 配额 2026-08-20 10:00 重置后，可补跑一次真实模型下的 TUI 全场景（读/写/改/搜索/恢复）
- ~~OpenAI 协议接入真实 key 后复验~~ → **2026-08-17 已完成**：接入阿里云百练（DashScope）平台后，qwen3-coder-plus 真实模型工具调用全链路通过（read_file 发起 → 碎片拼接 → 执行 → 回灌 → 基于真实文件内容正确作答）；deepseek-v4-flash-0731 工具调用发起/拼接/执行正常，收尾轮倾向继续工具调用（单轮边界提示，Agent Loop 版本后为正常行为）
