"""
PipelineAgent - 流水线子 Agent

每个 PipelineAgent 拥有完整的「记忆视野」：

  1. system_context     → 整个系统是干什么的
  2. conversation_summary → 用户说过的所有话（跨轮）
  3. pipeline_context   → 当前流水线中，前面所有步骤做了什么
  4. previous_output    → 上一个 Agent 的直接输出（最直接的接力内容）
  5. own_task          → Lead 给自己的具体任务
  6. own_role          → 自己在整个协作中的角色
  7. pass_to_next      → 需要传递给下一步的内容说明

这样彻底解决了「subagent 互相不知道对方在做什么」的痛点。
"""

import re
import json
from typing import Optional
from llm import LLM
from memory import Memory
from tools import TOOL
from shared_memory import SharedMemory


# ── ReAct 响应解析（复用 research_agent 的逻辑）─────────────────

def _parse_response(text: str) -> dict:
    text = text.strip()

    # 先尝试代码块
    matches = re.findall(r"```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL)
    if matches:
        try:
            result = json.loads(matches[-1])
            if "type" in result:
                return result
        except Exception:
            pass

    # 直接提取 JSON
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
                        json_str = text[start:i + 1]
                        result = json.loads(json_str)
                        if "type" in result:
                            return result
                        break
    except Exception:
        pass

    return {"type": "error", "raw": text[:200]}


# ── PipelineAgent ────────────────────────────────────────────────

class PipelineAgent:
    """
    流水线中的单个子 Agent。

    Args:
        llm:           LLM 实例
        step_info:     Lead 规划的本步信息 {step, role, task, pass_to_next}
        shared_memory: 全局共享记忆实例
        max_steps:     ReAct 最大循环轮数
    """

    def __init__(
        self,
        llm: LLM,
        step_info: dict,
        shared_memory: SharedMemory,
        max_steps: int = 10,
    ):
        self.llm           = llm
        self.step          = step_info["step"]
        self.role          = step_info["role"]
        self.task          = step_info["task"]
        self.pass_to_next  = step_info.get("pass_to_next")   # None → 最后一步
        self.shared_memory = shared_memory
        self.max_steps     = max_steps

    # ── 主入口 ───────────────────────────────────────────────────

    def run(self) -> str:
        """执行本步任务，结果自动写入 SharedMemory"""

        system_prompt = self._build_system_prompt()
        user_message  = self._build_user_message()

        mem = Memory(system_prompt)
        mem.add("user", user_message)

        result = "步骤执行失败：超过最大步数"

        for _ in range(self.max_steps):
            raw = self.llm.chat(mem.get())
            mem.add("assistant", raw)

            parsed = _parse_response(raw)

            if parsed["type"] == "final_answer":
                answer = parsed.get("answer", "").strip()
                result = self._clean(answer) or "（无有效输出）"
                break

            elif parsed["type"] == "action":
                tool_name  = parsed.get("action", "")
                tool_input = parsed.get("action_input", "")

                print(f"      🔧 [{self.role}] 调用工具: {tool_name} | 输入: {str(tool_input)[:60]}")

                if tool_name in TOOL:
                    obs = TOOL[tool_name].run(tool_input)
                    if len(str(obs)) > 1500:
                        obs = str(obs)[:1500] + "\n...(已截断)"
                else:
                    obs = f"工具 '{tool_name}' 不存在，可用工具: {', '.join(TOOL.keys())}"

                mem.add("user", f"Observation: {obs}")

            else:
                mem.add(
                    "user",
                    "输出格式错误，请只输出一个JSON：\n"
                    '{"type": "action", "action": "工具名", "action_input": "输入"}\n'
                    '或 {"type": "final_answer", "answer": "结果"}',
                )

        # 写入共享记忆（无论成功失败）
        self.shared_memory.record_step(self.step, self.role, self.task, result)
        return result

    # ── 构建系统提示词 ────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        tool_desc = "\n".join(
            f"- {name}: {tool.description}" for name, tool in TOOL.items()
        )

        # 最后一步 vs 中间步骤的提示差异
        if self.pass_to_next is None:
            pass_hint = (
                "\n【注意】你是流水线的 **最后一步**，"
                "请整合所有前序信息，给出完整、深入的最终结论。"
            )
        else:
            pass_hint = (
                f"\n【传递要求】完成任务后，你的输出必须包含以下内容供下一步使用：\n"
                f"  {self.pass_to_next}"
            )

        return f"""你是多Agent协作流水线中的第 {self.step} 步执行者，角色：{self.role}。

【系统背景】
你属于一个有序传递结果的流水线系统。每个Agent完成自己的任务后，
把结果传递给下一个Agent，共同完成复杂任务。
你的前任Agent已经在共享记忆中留下了执行记录，你的结果也会被后续Agent读取。
{pass_hint}

【可用工具】
{tool_desc}

【输出格式 - 严格JSON，只输出一个】
使用工具：{{"type": "action", "action": "工具名", "action_input": "输入内容"}}
完成任务：{{"type": "final_answer", "answer": "结果内容"}}

【执行规则】
1. 只输出一个JSON，外面无其他文字
2. 充分使用工具获取信息，不要凭空捏造数据
3. 用户要保存文件时，先调用 write_file，再输出 final_answer 告知路径
4. 禁止废话、问候语、解释说明"""

    # ── 构建用户消息（核心：注入完整记忆上下文）─────────────────

    def _build_user_message(self) -> str:
        # 从共享记忆取各层上下文
        conversation_ctx  = self.shared_memory.get_conversation_summary(max_chars=1500)
        pipeline_done_ctx = self.shared_memory.get_current_pipeline_context()
        previous_output   = self.shared_memory.get_previous_output(self.step)

        parts = []

        # 1. 系统级背景
        parts.append(
            f"【系统全局背景】\n{self.shared_memory.system_context}"
        )

        # 2. 用户对话历史（让 agent 知道用户的完整意图）
        parts.append(
            f"【用户历史对话（跨轮记忆）】\n{conversation_ctx}"
        )

        # 3. 当前流水线已完成步骤（让 agent 知道前面的同伴做了什么）
        if pipeline_done_ctx != "（当前流水线尚未完成任何步骤）":
            parts.append(
                f"【当前流水线·前序步骤记录】\n{pipeline_done_ctx}"
            )

        # 4. 上一步的直接输出（最直接的接力内容）
        if previous_output:
            parts.append(
                f"【上一步Agent的直接输出（你的起点）】\n{previous_output}"
            )

        # 5. 自己的任务
        parts.append(
            f"【你的任务（Lead Agent 分配）】\n{self.task}"
        )

        # 6. 传递提示
        if self.pass_to_next:
            parts.append(
                f"【你完成后需要传递给下一步的内容】\n{self.pass_to_next}"
            )

        return "\n\n".join(parts)

    # ── 清理废话 ─────────────────────────────────────────────────

    @staticmethod
    def _clean(answer: str) -> str:
        waste = [
            r"让我.*?(?:来|为你|帮您)",
            r"我将.*?(?:来|为你|帮您)",
            r"根据.*?要求",
            r"综上所述.*?(?:可以|得出)",
            r"总的来说",
            r"任务完成[，。]",
            r"经过.*?分析",
        ]
        for p in waste:
            answer = re.sub(p, "", answer, flags=re.IGNORECASE)
        return answer.strip()
