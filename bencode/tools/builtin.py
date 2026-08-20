"""六个核心内置工具

- read_file: 读文件（支持行区间分段）
- write_file: 写文件（覆盖）
- edit_file: 改文件（原文唯一匹配替换）
- run_command: 执行命令（stdout/stderr/退出码，超时保护）
- glob_files: 按 glob 模式查找文件
- grep_search: 按正则搜索代码内容
"""

import asyncio
import fnmatch
import locale
import os
import re
from pathlib import Path
from typing import Any, Optional

from bencode.tools.base import BaseTool, ToolError

# 查找/搜索类工具默认忽略的目录
DEFAULT_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "node_modules",
    ".idea",
    ".vscode",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}


def _decode_bytes(data: bytes) -> str:
    """按 utf-8 → 本地编码顺序解码子进程输出，失败则容错替换"""
    encodings = ["utf-8", locale.getpreferredencoding(False) or "utf-8"]
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


class ReadFileTool(BaseTool):
    """读取本地文本文件内容"""

    name = "read_file"
    description = (
        "读取指定路径的文本文件内容并返回原文。"
        "可用 offset（起始行号，1 起始）和 limit（行数）分段读取大文件。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对或绝对）"},
            "offset": {"type": "integer", "description": "起始行号（1 起始，可选）"},
            "limit": {"type": "integer", "description": "读取的行数（可选）"},
        },
        "required": ["path"],
    }

    async def execute(
        self,
        path: str = "",
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        **_: Any,
    ) -> str:
        if not path:
            raise ToolError("缺少必填参数: path")
        p = Path(path)
        if not p.exists():
            raise ToolError(f"文件不存在: {path}")
        if not p.is_file():
            raise ToolError(f"路径不是文件: {path}")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ToolError(f"读取文件失败: {e}") from e

        lines = text.splitlines()
        total = len(lines)
        # 全量读取：原文返回，仅附一行统计头
        if offset is None and limit is None:
            return f"[文件 {path} 共 {total} 行]\n{text}"

        # 分段读取
        start = max(1, int(offset or 1)) - 1
        end = total if limit is None else start + int(limit)
        selected = lines[start:end]
        if not selected:
            raise ToolError(
                f"指定行区间为空: 起始第 {start + 1} 行，文件共 {total} 行"
            )
        header = f"[文件 {path} 共 {total} 行，返回第 {start + 1}-{start + len(selected)} 行]\n"
        return header + "\n".join(selected)


class WriteFileTool(BaseTool):
    """写入文件（覆盖已有内容）"""

    requires_confirmation = True
    name = "write_file"
    description = (
        "将完整内容写入指定文件；文件已存在时覆盖，父目录不存在时自动创建。"
        "注意：是全量覆盖而非追加。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "content": {"type": "string", "description": "要写入的完整内容"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str = "", content: Optional[str] = None, **_: Any) -> str:
        if not path:
            raise ToolError("缺少必填参数: path")
        if content is None:
            raise ToolError("缺少必填参数: content")
        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as e:
            raise ToolError(f"写入文件失败: {e}") from e
        return f"已写入 {path}（{len(content)} 字符）"


class EditFileTool(BaseTool):
    """精确修改文件：原文唯一匹配替换"""

    requires_confirmation = True
    name = "edit_file"
    description = (
        "精确修改文件：将文件中唯一匹配的 old_string 原文替换为 new_string。"
        "匹配 0 处或匹配多处都会失败并说明原因；"
        "失败时请调整 old_string（扩大上下文使其唯一）后重试。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目标文件路径"},
            "old_string": {"type": "string", "description": "要替换的原文（必须在文件中唯一）"},
            "new_string": {"type": "string", "description": "替换后的新文本"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def execute(
        self,
        path: str = "",
        old_string: Optional[str] = None,
        new_string: Optional[str] = None,
        **_: Any,
    ) -> str:
        if not path:
            raise ToolError("缺少必填参数: path")
        if old_string is None:
            raise ToolError("缺少必填参数: old_string")
        if new_string is None:
            raise ToolError("缺少必填参数: new_string")
        if old_string == "":
            raise ToolError("old_string 不能为空字符串")

        p = Path(path)
        if not p.exists():
            raise ToolError(f"文件不存在: {path}")
        if not p.is_file():
            raise ToolError(f"路径不是文件: {path}")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise ToolError(f"读取文件失败: {e}") from e

        count = text.count(old_string)
        if count == 0:
            raise ToolError(
                f"未找到匹配: 在 {path} 中未找到要替换的原文，"
                f"请核对 old_string 与文件内容（含缩进、空行）是否完全一致"
            )
        if count > 1:
            raise ToolError(
                f"匹配多处: 在 {path} 中找到 {count} 处相同原文，"
                f"请在 old_string 中扩大上下文使匹配唯一后重试"
            )

        new_text = text.replace(old_string, new_string, 1)
        try:
            p.write_text(new_text, encoding="utf-8")
        except OSError as e:
            raise ToolError(f"写入文件失败: {e}") from e
        return f"已在 {path} 完成 1 处替换"


class RunCommandTool(BaseTool):
    """执行 shell 命令"""

    requires_confirmation = True
    timeout_seconds = 60.0
    name = "run_command"
    description = (
        "在当前工作目录执行命令，返回 stdout、stderr 与退出码。\n"
        "重要：当前运行在 Windows 系统，命令通过 cmd.exe 执行，必须使用 Windows 语法：\n"
        "  - 列目录用 dir，不要用 ls\n"
        "  - 用户主目录是 %USERPROFILE%（桌面路径为 %USERPROFILE%\\Desktop）\n"
        "  - 路径分隔符用反斜杠 \\，不要用 ~\n"
        "  - 不支持 Unix 重定向（如 2>/dev/null）\n"
        "默认 60 秒超时，超时后进程被终止。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的命令（Windows cmd 语法，如 dir /b）",
            },
            "timeout": {"type": "integer", "description": "超时秒数（可选，默认 60）"},
        },
        "required": ["command"],
    }

    async def execute(self, command: str = "", timeout: Optional[int] = None, **_: Any) -> str:
        if not command:
            raise ToolError("缺少必填参数: command")
        effective_timeout = float(timeout or self.timeout_seconds)

        # Windows 下 CREATE_NO_WINDOW 避免闪黑窗
        creationflags = 0x08000000 if os.name == "nt" else 0
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=creationflags,
            )
        except OSError as e:
            raise ToolError(f"启动命令失败: {e}") from e

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ToolError(
                f"命令执行超时（{int(effective_timeout)} 秒），进程已终止: {command}"
            ) from None

        stdout = _decode_bytes(stdout_b or b"").strip()
        stderr = _decode_bytes(stderr_b or b"").strip()

        parts: list[str] = []
        if stdout:
            parts.append(f"[stdout]\n{stdout}")
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        output = "\n".join(parts) if parts else "[无输出]"

        if proc.returncode != 0:
            raise ToolError(f"命令退出码 {proc.returncode}\n{output}")
        return output


class GlobFilesTool(BaseTool):
    """按 glob 模式查找文件"""

    name = "glob_files"
    description = (
        "按 glob 模式查找文件（如 **/*.py、*.toml），返回匹配的相对路径列表，"
        "自动忽略 .git/__pycache__/.venv/node_modules 等目录。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
            "path": {"type": "string", "description": "查找的根目录（默认当前目录）"},
            "ignore": {
                "type": "array",
                "items": {"type": "string"},
                "description": "额外忽略的目录名列表（可选）",
            },
        },
        "required": ["pattern"],
    }
    MAX_RESULTS = 200

    async def execute(
        self,
        pattern: str = "",
        path: str = ".",
        ignore: Optional[list] = None,
        **_: Any,
    ) -> str:
        if not pattern:
            raise ToolError("缺少必填参数: pattern")
        root = Path(path or ".").resolve()
        if not root.is_dir():
            raise ToolError(f"目录不存在: {path}")

        ignored = DEFAULT_IGNORE_DIRS | set(ignore or [])
        # 兼容 "**/*.py" 与 "*.py" 两种写法
        variants = [pattern, f"./{pattern}"]
        if pattern.startswith("**/"):
            variants.insert(0, pattern[3:])

        matches: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            rel_dir = os.path.relpath(dirpath, root)
            for fname in filenames:
                rel_file = fname if rel_dir == "." else f"{rel_dir}{os.sep}{fname}"
                rel_file = rel_file.replace(os.sep, "/")
                if any(fnmatch.fnmatch(rel_file, v) for v in variants):
                    matches.append(rel_file)
                    if len(matches) > self.MAX_RESULTS:
                        matches.pop()
                        break

        matches.sort()
        if not matches:
            return f"未找到匹配文件: {pattern}"
        header = f"[模式 {pattern} 共匹配 {len(matches)} 个文件"
        if len(matches) >= self.MAX_RESULTS:
            header += f"（已达上限 {self.MAX_RESULTS}，结果可能不全）"
        header += "]"
        return header + "\n" + "\n".join(matches)


class GrepSearchTool(BaseTool):
    """按正则搜索代码内容"""

    name = "grep_search"
    description = (
        "按正则表达式在文本文件中搜索内容，"
        "返回每处匹配的 文件路径:行号:该行内容。"
        "可用 include 参数按文件名过滤（如 *.py）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "搜索根目录（默认当前目录）"},
            "include": {"type": "string", "description": "文件名 glob 过滤，如 *.py（可选）"},
            "ignore": {
                "type": "array",
                "items": {"type": "string"},
                "description": "额外忽略的目录名列表（可选）",
            },
        },
        "required": ["pattern"],
    }
    MAX_MATCHES = 100
    MAX_FILE_SIZE = 2 * 1024 * 1024  # 跳过超过 2MB 的文件

    async def execute(
        self,
        pattern: str = "",
        path: str = ".",
        include: Optional[str] = None,
        ignore: Optional[list] = None,
        **_: Any,
    ) -> str:
        if not pattern:
            raise ToolError("缺少必填参数: pattern")
        try:
            regex = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"无效的正则表达式: {e}") from e

        root = Path(path or ".").resolve()
        if not root.is_dir():
            raise ToolError(f"目录不存在: {path}")

        ignored = DEFAULT_IGNORE_DIRS | set(ignore or [])
        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            for fname in filenames:
                if include and not fnmatch.fnmatch(fname, include):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    if fpath.stat().st_size > self.MAX_FILE_SIZE:
                        continue
                    # strict 解码失败（二进制文件）直接跳过
                    content = fpath.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                rel = os.path.relpath(fpath, root).replace(os.sep, "/")
                for lineno, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{rel}:{lineno}:{line.strip()}")
                        if len(results) >= self.MAX_MATCHES:
                            break
                if len(results) >= self.MAX_MATCHES:
                    break

        if not results:
            return f"未找到匹配: {pattern}"
        header = f"[共 {len(results)} 处匹配"
        if len(results) >= self.MAX_MATCHES:
            header += f"（已达上限 {self.MAX_MATCHES}，结果可能不全）"
        header += "]"
        return header + "\n" + "\n".join(results)
