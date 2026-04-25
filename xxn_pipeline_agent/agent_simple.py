"""
SimpleAgent - 单步执行 Agent（用于 LEVEL2 简单问题）

直接继承 research_agent 的 Agent 逻辑，无需修改。
"""

import re
import json
from llm import LLM
from memory import Memory
from tools import TOOL


def _build_system_prompt() -> str:
    tool_desc = "\n".join(
        f"- {name}: {tool.description}" for name, tool in TOOL.items()
    )
    return f"""你是任务执行Agent，职责是直接完成任务，输出有价值的结果。

【可用工具】
{tool_desc}

【输出格式 - 严格JSON】
使用工具时：{{"type": "action", "action": "工具名", "action_input": "输入内容"}}
任务完成时：{{"type": "final_answer", "answer": "最终结果"}}

【硬性规则】
1. 只输出一个JSON，外面无其他文字
2. 用户要求保存文件时，必须先调用 write_file，再输出 final_answer 告知路径
3. 禁止把文件内容直接放在 final_answer 里
"""


def _parse_response(text: str) -> dict:
    text = text.strip()
    matches = re.findall(r"```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL)
    if matches:
        try:
            r = json.loads(matches[-1])
            if "type" in r:
                return r
        except Exception:
            pass
    try:
        start = text.find('{')
        if start != -1:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        r = json.loads(text[start:i + 1])
                        if "type" in r:
                            return r
                        break
    except Exception:
        pass
    return {"type": "error", "raw": text[:200]}


class SimpleAgent:
    def __init__(self, llm: LLM, max_steps: int = 8):
        self.llm       = llm
        self.max_steps = max_steps

    def run(self, task: str) -> str:
        mem = Memory(_build_system_prompt())
        mem.add("user", task)

        for _ in range(self.max_steps):
            raw    = self.llm.chat(mem.get())
            mem.add("assistant", raw)
            parsed = _parse_response(raw)

            if parsed["type"] == "final_answer":
                return parsed.get("answer", "").strip() or "无结果"

            elif parsed["type"] == "action":
                tool_name  = parsed.get("action", "")
                tool_input = parsed.get("action_input", "")
                print(f"  🔧 {tool_name} | {str(tool_input)[:60]}")
                obs = TOOL[tool_name].run(tool_input) if tool_name in TOOL else f"工具 '{tool_name}' 不存在"
                if len(str(obs)) > 1500:
                    obs = str(obs)[:1500] + "...(已截断)"
                mem.add("user", f"Observation: {obs}")

            else:
                mem.add("user", "格式错误，只输出JSON")

        return "执行失败：超过最大步数"
