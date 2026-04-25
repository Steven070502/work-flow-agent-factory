import subprocess
import sys

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])

try:
    from langchain_community.tools import DuckDuckGoSearchRun
except ImportError:
    install("duckduckgo-search langchain-community")
    from langchain_community.tools import DuckDuckGoSearchRun

from langchain_community.utilities import RequestsWrapper


class Tool:
    name: str        = ""
    description: str = ""
    def run(self, input: str) -> str:
        raise NotImplementedError


class SearchTool(Tool):
    name        = "search"
    description = "搜索网络信息。输入: 搜索关键词"

    def __init__(self):
        self._tool = DuckDuckGoSearchRun()

    def run(self, input: str) -> str:
        try:
            from ddgs import DDGS
            results = DDGS().text(input, max_results=5)
        # 过滤掉明显无关的结果
            filtered = [
                f"{r['title']}: {r['body']}"
                for r in results
                if r.get('body') and len(r['body']) > 20
            ]
            return "\n".join(filtered[:3]) if filtered else "未找到相关结果"
        except Exception as e:
            return f"搜索失败: {e}"


class FetchWebTool(Tool):
    name        = "fetch_web"
    description = "访问网页获取内容。输入: 完整URL"

    def __init__(self):
        self._tool = RequestsWrapper()

    def run(self, input: str) -> str:
        if not input.startswith("http"):
            input = "https://" + input
        try:
            return self._tool.get(input)[:2000]
        except Exception as e:
            return f"访问失败: {e}"


class ReadFileTool(Tool):
    name        = "read_file"
    description = "读取本地文件内容。输入: 文件路径"

    def run(self, input: str) -> str:
        try:
            with open(input, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"读取失败: {e}"


class WriteFileTool(Tool):
    name        = "write_file"
    description = "写入文件。输入JSON格式：{\"path\": \"文件名\", \"content\": \"内容\"}"

    def run(self, input: str) -> str:
        import json
        import os
        try:
            # 先把真实换行符替换成 \n，防止 json.loads 报错
            input_clean = input.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            data    = json.loads(input_clean)
            path    = data["path"]
            # content 里的 \n 还原成真实换行
            content = data["content"].replace('\\n', '\n').replace('\\t', '\t')
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            abs_path = os.path.abspath(path)
            print(f"    ✅ 文件写入成功: {abs_path}")
            return f"文件写入成功，路径：{abs_path}"
        except Exception as e:
            print(f"    ❌ 写入失败: {e}")
            return f"写入失败: {e}"


class PythonREPLTool(Tool):
    name        = "execute_python"
    description = "执行Python代码。输入: 合法的Python代码字符串"

    def run(self, input: str) -> str:
        import io
        from contextlib import redirect_stdout
        try:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exec(input, {})
            output = buffer.getvalue()
            return output if output else "执行成功，无输出"
        except Exception as e:
            return f"执行失败: {e}"


class CalculatorTool(Tool):
    name        = "calculator"
    description = "计算数学表达式。输入: 合法的Python数学表达式，如 '2 + 3 * 4'"

    def run(self, input: str) -> str:
        try:
            result = eval(input, {"__builtins__": {}})
            return str(result)
        except Exception as e:
            return f"计算失败: {e}"


class TimeTool(Tool):
    name        = "get_time"
    description = "获取当前日期和时间。输入: 任意字符串"

    def run(self, input: str) -> str:
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


TOOL = {
    tool.name: tool
    for tool in [
        SearchTool(),
        FetchWebTool(),
        ReadFileTool(),
        WriteFileTool(),
        PythonREPLTool(),
        CalculatorTool(),
        TimeTool(),
    ]
}