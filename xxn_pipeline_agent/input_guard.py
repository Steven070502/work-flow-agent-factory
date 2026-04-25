"""
InputGuard - 输入守卫

三级分类（与 research_agent 一致，但描述更精准）：
  LEVEL1 → 闲聊/问候 → 直接回复，不进 Agent
  LEVEL2 → 单步可解决的简单问题 → 单个 Agent 处理
  LEVEL3 → 需要多步骤、多角度分析的复杂问题 → 流水线 Pipeline 处理
"""

import re
from llm import LLM


class InputGuard:

    def __init__(self, llm: LLM):
        self.llm = llm

    def check(self, user_input: str) -> dict:
        """
        Returns:
            {
                "pass":            bool,    # False → 直接回复，不进 Agent
                "level":           str,     # "chat" | "simple" | "complex"
                "direct_response": str|None # 仅 pass=False 时有值
            }
        """
        user_input = user_input.strip()

        if not user_input or len(user_input) < 2:
            return {
                "pass":            False,
                "level":           "empty",
                "direct_response": "请输入具体的问题。",
            }

        prompt = f"""判断用户输入属于哪个级别：

LEVEL1（纯闲聊/问候，无需 Agent）：你好、再见、谢谢、你是谁、今天天气
LEVEL2（单步可解决的问题）：查价格、搜信息、写代码、做计算、翻译、简单问答
LEVEL3（需要多步骤协作分析）：市场策略、风险评估、竞品分析、研究报告、多因素决策

用户输入：{user_input}

只输出 LEVEL1、LEVEL2 或 LEVEL3，不要其他内容："""

        messages = [
            {"role": "system", "content": "你是输入分类器，只输出LEVEL1、LEVEL2或LEVEL3。"},
            {"role": "user",   "content": prompt},
        ]

        try:
            raw = self.llm.chat(messages).strip().upper()

            if "LEVEL1" in raw:
                answer = self.llm.chat([
                    {"role": "system", "content": "你是智能助手，简洁回答用户。"},
                    {"role": "user",   "content": user_input},
                ])
                print("  [Guard] LEVEL1 → 闲聊，直接回复")
                return {
                    "pass":            False,
                    "level":           "chat",
                    "direct_response": answer,
                }

            elif "LEVEL2" in raw:
                print("  [Guard] LEVEL2 → 简单问题，单 Agent")
                return {
                    "pass":            True,
                    "level":           "simple",
                    "direct_response": None,
                }

            else:
                print("  [Guard] LEVEL3 → 复杂问题，流水线")
                return {
                    "pass":            True,
                    "level":           "complex",
                    "direct_response": None,
                }

        except Exception:
            return {
                "pass":            True,
                "level":           "complex",
                "direct_response": None,
            }
