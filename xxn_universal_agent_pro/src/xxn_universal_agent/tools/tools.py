"""
工具系统
职责: 封装Agent可调用的外部能力
设计: 基类+注册表，新工具继承Tool即可自动注册
"""

import os
import re
import ast
import json
import time
import subprocess
import tempfile
import ssl
import operator
import urllib.parse
import urllib.request
from html import unescape
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

    ALLOWED_BIN_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    ALLOWED_UNARY_OPS = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    ALLOWED_FUNCS = {
        "abs": abs,
        "max": max,
        "min": min,
        "sum": sum,
        "pow": pow,
        "round": round,
    }

    def run(self, input: str) -> str:
        try:
            tree = ast.parse(input.strip(), mode="eval")
            result = self._eval_node(tree.body)
            return str(result)
        except Exception as e:
            return f"[计算错误] {e}"

    def _eval_node(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value

        if isinstance(node, ast.BinOp) and type(node.op) in self.ALLOWED_BIN_OPS:
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self.ALLOWED_BIN_OPS[type(node.op)](left, right)

        if isinstance(node, ast.UnaryOp) and type(node.op) in self.ALLOWED_UNARY_OPS:
            return self.ALLOWED_UNARY_OPS[type(node.op)](self._eval_node(node.operand))

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in self.ALLOWED_FUNCS:
                raise ValueError("只允许调用 abs/max/min/sum/pow/round")
            args = [self._eval_node(arg) for arg in node.args]
            if node.keywords:
                raise ValueError("不支持关键字参数")
            return self.ALLOWED_FUNCS[node.func.id](*args)

        if isinstance(node, (ast.List, ast.Tuple)):
            return [self._eval_node(item) for item in node.elts]

        raise ValueError(f"不允许的表达式: {type(node).__name__}")


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
        "注意: 5秒超时；仅适合执行可信的小段本地代码。"
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

        temp_file = None
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
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass


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
    """网络搜索。优先使用稳定搜索API，未配置时回退到HTML搜索。"""
    name = "search"
    description = (
        "搜索网络信息。输入: 搜索关键词。"
        "可配置 TAVILY_API_KEY / BRAVE_SEARCH_API_KEY / SERPAPI_API_KEY 获得稳定联网搜索。"
    )

    _ssl_context = None

    def _urlopen(self, req, timeout: int):
        """统一打开URL；优先使用certifi证书，避免macOS/Python证书链问题。"""
        if self._ssl_context is None:
            try:
                import certifi
                self._ssl_context = ssl.create_default_context(cafile=certifi.where())
            except Exception:
                self._ssl_context = ssl.create_default_context()
        return urllib.request.urlopen(req, timeout=timeout, context=self._ssl_context)

    def run(self, input: str) -> str:
        query = input.strip()
        if not query:
            return "[搜索失败] 查询词为空"
        errors = []

        backend = os.environ.get("SEARCH_BACKEND", "auto").strip().lower()
        api_backends = []
        if backend in ("auto", "tavily"):
            api_backends.append(("Tavily", self._search_tavily))
        if backend in ("auto", "brave"):
            api_backends.append(("Brave", self._search_brave))
        if backend in ("auto", "serpapi", "google"):
            api_backends.append(("SerpAPI", self._search_serpapi))

        for name, fn in api_backends:
            try:
                result = fn(query)
                if result:
                    return result
            except RuntimeError as e:
                # 未配置key时不算真正错误，继续尝试下一个后端
                errors.append(f"{name}: {e}")
            except Exception as e:
                errors.append(f"{name}: {type(e).__name__}: {e}")

        if backend not in ("auto", "html", "duckduckgo", "bing"):
            return (
                f"[搜索失败] SEARCH_BACKEND={backend} 不可用。"
                + ("\n" + "\n".join(errors) if errors else "")
                + "\n请改为 auto/tavily/brave/serpapi/html，或配置对应API Key。"
            )

        try:
            return self._search_duckduckgo(query)
        except Exception as e:
            errors.append(f"DuckDuckGo: {type(e).__name__}: {e}")

        try:
            return self._search_bing(query)
        except Exception as e:
            errors.append(f"Bing: {type(e).__name__}: {e}")

        return (
            "[搜索失败] 所有搜索后端均不可用。\n"
            + "\n".join(errors)
            + "\n可能原因：当前网络/DNS不可用、搜索引擎被阻断，或需要代理。"
        )

    def _search_tavily(self, query: str) -> str:
        key = os.environ.get("TAVILY_API_KEY", "").strip()
        if not key:
            raise RuntimeError("未配置 TAVILY_API_KEY")

        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps({
                "api_key": key,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        rows = []
        for i, r in enumerate(data.get("results", [])[:5], start=1):
            rows.append(
                f"{i}. {r.get('title', '').strip()}\n"
                f"{r.get('url', '').strip()}\n"
                f"{r.get('content', '').strip()}"
            )
        return "\n\n".join(rows) if rows else "未找到相关结果"

    def _search_brave(self, query: str) -> str:
        key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
        if not key:
            raise RuntimeError("未配置 BRAVE_SEARCH_API_KEY")

        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({
            "q": query,
            "count": 5,
        })
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": key,
            },
        )
        with self._urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        rows = []
        for i, r in enumerate(data.get("web", {}).get("results", [])[:5], start=1):
            rows.append(
                f"{i}. {r.get('title', '').strip()}\n"
                f"{r.get('url', '').strip()}\n"
                f"{r.get('description', '').strip()}"
            )
        return "\n\n".join(rows) if rows else "未找到相关结果"

    def _search_serpapi(self, query: str) -> str:
        key = os.environ.get("SERPAPI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("未配置 SERPAPI_API_KEY")

        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode({
            "engine": "google",
            "q": query,
            "api_key": key,
            "num": 5,
        })
        req = urllib.request.Request(url, headers={"User-Agent": "XXN-Agent/0.1"})
        with self._urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        rows = []
        for i, r in enumerate(data.get("organic_results", [])[:5], start=1):
            rows.append(
                f"{i}. {r.get('title', '').strip()}\n"
                f"{r.get('link', '').strip()}\n"
                f"{r.get('snippet', '').strip()}"
            )
        return "\n\n".join(rows) if rows else "未找到相关结果"

    def _search_duckduckgo(self, query: str) -> str:
            url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) XXN-Agent/0.1",
                },
            )
            with self._urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            title_matches = re.findall(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                html,
                flags=re.S,
            )
            snippet_matches = re.findall(
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|'
                r'<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
                html,
                flags=re.S,
            )

            rows = []
            for i, (href, title_html) in enumerate(title_matches[:5], start=1):
                title = self._clean_html(title_html)
                href = self._normalize_duckduckgo_url(unescape(href))
                snippet = ""
                if i - 1 < len(snippet_matches):
                    parts = snippet_matches[i - 1]
                    snippet = self._clean_html(next((p for p in parts if p), ""))
                rows.append(f"{i}. {title}\n{href}\n{snippet}".strip())

            return "\n\n".join(rows[:5]) if rows else "未找到相关结果"

    def _search_bing(self, query: str) -> str:
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) XXN-Agent/0.1",
            },
        )
        with self._urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, flags=re.S)
        rows = []
        for i, block in enumerate(blocks[:5], start=1):
            title_match = re.search(r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>', block, flags=re.S)
            if not title_match:
                continue
            href = unescape(title_match.group(1))
            title = self._clean_html(title_match.group(2))
            snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.S)
            snippet = self._clean_html(snippet_match.group(1)) if snippet_match else ""
            rows.append(f"{i}. {title}\n{href}\n{snippet}".strip())

        return "\n\n".join(rows[:5]) if rows else "未找到相关结果"

    def _clean_html(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def _normalize_duckduckgo_url(self, href: str) -> str:
        if href.startswith("//"):
            href = "https:" + href
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return qs["uddg"][0]
        return href


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
