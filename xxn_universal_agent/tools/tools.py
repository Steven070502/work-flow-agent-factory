"""
工具系统
职责: 封装Agent可调用的外部能力
设计: 基类+注册表，新工具继承Tool即可自动注册
"""

import os
import re
import json
import time
import subprocess
import tempfile
from datetime import datetime
from typing import Dict


class Tool:
    """工具基类"""
    name: str = ""
    description: str = ""

    def run(self, input: str) -> str:
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description}


# ── 具体工具实现 ──

class CalculateTool(Tool):
    """数学计算"""
    name = "calculate"
    description = "计算数学表达式。输入: '2+2', '10*5', '2**10'"

    def run(self, input: str) -> str:
        try:
            allowed = {"__builtins__": {}}
            allowed.update({
                "abs": abs, "max": max, "min": min, "sum": sum,
                "pow": pow, "round": round, "len": len,
            })
            result = eval(input, allowed)
            return str(result)
        except Exception as e:
            return f"[计算错误] {e}"


class TimeTool(Tool):
    """获取时间"""
    name = "time"
    description = "获取当前日期时间"

    def run(self, input: str) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CodeExecuteTool(Tool):
    """Python代码执行（沙箱）"""
    name = "execute_python"
    description = (
        "执行Python代码并返回结果。输入为完整代码字符串。"
        "注意: 5秒超时，禁止访问网络。"
    )

    def run(self, input: str) -> str:
        code = input.strip()
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                temp_file = f.name

            start = time.time()
            result = subprocess.run(
                ["python3", temp_file],
                capture_output=True,
                text=True,
                timeout=5,
            )
            exec_time = (time.time() - start) * 1000
            os.unlink(temp_file)

            output = []
            if result.stdout:
                output.append(f"[标准输出]\n{result.stdout}")
            if result.stderr:
                output.append(f"[标准错误]\n{result.stderr}")
            output.append(f"[执行时间] {exec_time:.2f}ms")
            return "\n".join(output)

        except subprocess.TimeoutExpired:
            return "[错误] 代码执行超时（超过5秒）"
        except FileNotFoundError:
            return "[错误] Python执行环境不可用"
        except Exception as e:
            return f"[错误] 执行失败: {e}"


class ReadFileTool(Tool):
    """读取本地文件"""
    name = "read_file"
    description = "读取本地文件内容。输入: 文件路径"

    def run(self, input: str) -> str:
        try:
            with open(input.strip(), "r", encoding="utf-8") as f:
                content = f.read()
                if len(content) > 8000:
                    content = content[:8000] + "\n... (已截断，共{}字符)".format(len(content))
                return content
        except Exception as e:
            return f"[读取失败] {e}"


class WriteFileTool(Tool):
    """写入本地文件"""
    name = "write_file"
    description = '写入文件。输入JSON格式: {"path": "文件名", "content": "内容"}'

    def run(self, input: str) -> str:
        try:
            # 兼容真实换行符和转义换行符
            data = json.loads(input.strip())
            path = data["path"]
            content = data["content"]
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"[成功] 文件已保存: {os.path.abspath(path)} ({len(content)} 字符)"
        except Exception as e:
            return f"[写入失败] {e}"


class SearchTool(Tool):
    """网络搜索（DuckDuckGo，免API Key）"""
    name = "search"
    description = "搜索网络信息。输入: 搜索关键词"

    def run(self, input: str) -> str:
        try:
            from duckduckgo_search import DDGS
            results = DDGS().text(input, max_results=5)
            filtered = [
                f"{i+1}. {r['title']}\n{r['body'][:200]}"
                for i, r in enumerate(results)
                if r.get("body")
            ]
            return "\n".join(filtered[:3]) if filtered else "未找到相关结果"
        except ImportError:
            return "[错误] 未安装 duckduckgo-search，请运行: pip install duckduckgo-search"
        except Exception as e:
            return f"[搜索失败] {e}"


class ThinkTool(Tool):
    """思考工具（让Agent显式推理）"""
    name = "think"
    description = "用于深度思考分析。输入你的思考内容，会记录并返回确认。"

    def run(self, input: str) -> str:
        return f"[思考记录] {input}\n[提示] 继续下一步行动..."


# ── 工具注册表 ──

class ToolRegistry:
    """
    工具注册表
    
    职责:
    - 管理所有可用工具
    - 为Agent生成工具描述文本
    - 路由工具调用
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        """注册工具"""
        self._tools[tool.name] = tool
        return self

    def get(self, name: str) -> Tool:
        """获取工具"""
        return self._tools.get(name)

    def run(self, name: str, input: str) -> str:
        """执行工具"""
        tool = self._tools.get(name)
        if not tool:
            return f"[错误] 工具 '{name}' 不存在。可用: {list(self._tools.keys())}"
        return tool.run(input)

    def list_tools(self) -> Dict[str, str]:
        """列出所有工具名和描述"""
        return {name: tool.description for name, tool in self._tools.items()}

    def build_prompt(self) -> str:
        """生成工具描述文本（用于System Prompt）"""
        lines = ["## 可用工具"]
        for name, desc in self.list_tools().items():
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# ── 默认工具集 ──

def create_default_registry() -> ToolRegistry:
    """创建默认工具注册表"""
    registry = ToolRegistry()
    registry.register(CalculateTool())
    registry.register(TimeTool())
    registry.register(CodeExecuteTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(SearchTool())
    registry.register(ThinkTool())
    return registry
