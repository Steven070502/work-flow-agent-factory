"""
PipelineLeader - 流水线领导者

职责：
1. 像真正的领导一样，把任务拆成「有序、可传递」的子任务流水线
2. 为每个子 Agent 分配明确角色
3. 指定每步需要向下传递的信息类型
4. 利用共享记忆（历史对话 + 历史流水线）避免重复，做出更优规划

输出结构：
{
  "analysis": "核心分析（一句话）",
  "pipeline": [
    {
      "step": 1,
      "role": "信息收集专家",
      "task": "具体可执行的任务描述",
      "pass_to_next": "需要传给下一步的内容说明（最后一步为 null）"
    },
    ...
  ]
}
"""

import re
import json
from llm import LLM


class PipelineLeader:

    def __init__(self, llm: LLM):
        self.llm = llm

    def plan(
        self,
        issue: str,
        conversation_context: str,
        pipeline_history: str,
    ) -> dict:
        """
        制定流水线执行计划。

        Args:
            issue:                当前用户问题（带历史上下文的完整输入）
            conversation_context: SharedMemory.get_conversation_summary()
            pipeline_history:     SharedMemory.get_pipeline_history()

        Returns:
            dict with keys: analysis, pipeline (list of step dicts)
        """

        system_prompt = """你是多Agent流水线系统的 Lead Agent（领导者）。

【你的核心职责】
把复杂任务设计成「顺序执行、逐步传递」的子任务流水线。
前一个子Agent的输出会作为下一个子Agent的直接输入。
你必须像真正的领导一样思考：谁先做、做什么、把什么传下去。

【流水线设计原则】
1. 每步有明确的逻辑依赖关系（后步依赖前步的输出）
2. 每个agent有清晰的角色定位（不能都叫"分析师"）
3. task 字段必须具体可执行，包含：做什么 + 怎么做 + 输出格式要求
4. pass_to_next 说明该步需要传递哪些具体信息给下一步
5. 最后一步负责整合所有前序结果，给出最终结论
6. 参考历史任务，避免重复相同分析

【输出格式 - 严格JSON，无其他文字】
{
  "analysis": "一句话核心分析（≤60字）",
  "pipeline": [
    {
      "step": 1,
      "role": "具体角色名（如：市场调研员、数据分析师、风险评估师）",
      "task": "详细任务描述，包括要做什么、用什么工具、输出什么格式（≤100字）",
      "pass_to_next": "传递给下一步的内容说明（如：原始数据、分析结论、关键指标）"
    },
    {
      "step": 2,
      "role": "...",
      "task": "...",
      "pass_to_next": "..."
    },
    {
      "step": 3,
      "role": "...",
      "task": "...",
      "pass_to_next": null
    }
  ]
}

【规则】
- 只输出JSON，无markdown代码块，无解释
- pipeline步骤数：2到5个
- 禁止废话和客套话"""

        user_content = f"""【用户历史对话】
{conversation_context}

【历史任务执行记录（参考，避免重复）】
{pipeline_history}

【当前待处理任务】
{issue}

请为此任务设计流水线执行计划。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        raw = self.llm.chat(messages)
        return self._parse(raw, issue)

    # ── 解析 ─────────────────────────────────────────────────────

    def _parse(self, raw: str, issue: str) -> dict:
        raw = raw.strip()
        raw = re.sub(r'^```\w*\s*', '', raw)
        raw = re.sub(r'\s*```$', '',  raw)

        try:
            match = re.search(r'\{.+\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                analysis = data.get("analysis", "").strip()
                pipeline  = data.get("pipeline", [])

                # 校验并清理
                valid_steps = []
                for s in pipeline:
                    if not isinstance(s, dict):
                        continue
                    step = {
                        "step":         int(s.get("step", len(valid_steps) + 1)),
                        "role":         str(s.get("role", "执行者")).strip(),
                        "task":         str(s.get("task", "")).strip(),
                        "pass_to_next": s.get("pass_to_next"),  # None or str
                    }
                    if step["task"]:
                        valid_steps.append(step)

                if valid_steps:
                    # 保证最后一步 pass_to_next 为 None
                    valid_steps[-1]["pass_to_next"] = None
                    return {"analysis": analysis, "pipeline": valid_steps}

        except Exception:
            pass

        # 兜底：默认三步流水线
        return {
            "analysis": "任务规划解析失败，使用默认流水线",
            "pipeline": [
                {"step": 1, "role": "信息收集员",
                 "task": f"搜索与「{issue[:40]}」相关的背景信息和关键数据",
                 "pass_to_next": "搜集到的原始信息和数据"},
                {"step": 2, "role": "分析师",
                 "task": "基于收集的信息，分析核心问题，提炼关键结论",
                 "pass_to_next": "分析结论和关键发现"},
                {"step": 3, "role": "报告撰写者",
                 "task": "综合所有分析，给出完整的结论和建议",
                 "pass_to_next": None},
            ],
        }
