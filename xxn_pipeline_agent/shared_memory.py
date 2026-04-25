"""
SharedMemory - 全局共享记忆系统

解决痛点：
1. subagent 互相不知道对方做了什么
2. 跨轮对话记忆丢失
3. 整体任务背景对子agent不可见

设计：
- conversation_history: 用户与系统的全部对话（跨轮持久）
- pipeline_log: 历史流水线执行摘要（跨轮持久）
- current_steps: 当前流水线各步骤已完成记录（轮内共享）
- step_outputs: 当前流水线各步骤输出，供下一步直接取用
"""

from typing import Optional
import datetime


class SharedMemory:
    """
    全局共享记忆 —— 所有 Agent 均可读写

    生命周期：随 main.py 存活，贯穿所有轮次对话和所有流水线执行。
    """

    def __init__(self, system_context: str):
        self.system_context = system_context

        # ── 跨轮持久 ─────────────────────────────────────────────
        self._conversation: list[dict] = []   # 用户 ↔ 系统 对话历史
        self._pipeline_log: list[dict] = []   # 历次流水线执行摘要

        # ── 轮内共享（每次 start_new_pipeline 重置）──────────────
        self._current_issue: str = ""
        self._current_plan_summary: str = ""
        self._current_steps: list[dict] = []  # 已完成步骤列表
        self._step_outputs: dict[int, str] = {}  # step_id → output

    # ═══════════════════════════════════════════════════════════════
    #  对话历史
    # ═══════════════════════════════════════════════════════════════

    def add_conversation(self, role: str, content: str):
        self._conversation.append({
            "role": role,
            "content": content,
            "time": datetime.datetime.now().strftime("%H:%M"),
        })

    def get_conversation_summary(self, max_chars: int = 2000) -> str:
        """返回最近的对话历史（供 Lead 和 Agent 读取）"""
        if not self._conversation:
            return "（无历史对话）"
        lines = [
            f"[{m['time']}] {m['role']}: {m['content'][:300]}"
            for m in self._conversation
        ]
        text = "\n".join(lines)
        # 只取最近 max_chars 字符，防止 context 爆炸
        return text[-max_chars:] if len(text) > max_chars else text

    # ═══════════════════════════════════════════════════════════════
    #  历史流水线记录
    # ═══════════════════════════════════════════════════════════════

    def get_pipeline_history(self, max_entries: int = 3) -> str:
        """返回最近几次流水线执行摘要（供 Lead 参考，避免重复）"""
        if not self._pipeline_log:
            return "（无历史任务执行记录）"
        recent = self._pipeline_log[-max_entries:]
        blocks = []
        for i, run in enumerate(recent, 1):
            step_summary = " → ".join(
                f"步骤{s['step']}[{s['role']}]" for s in run.get("steps", [])
            )
            blocks.append(
                f"=== 历史任务 {i} ===\n"
                f"问题：{run['issue'][:120]}\n"
                f"流程：{step_summary}\n"
                f"结论：{run['summary'][:300]}"
            )
        return "\n\n".join(blocks)

    # ═══════════════════════════════════════════════════════════════
    #  当前流水线（轮内）
    # ═══════════════════════════════════════════════════════════════

    def start_new_pipeline(self, issue: str, plan_summary: str):
        """每轮复杂任务开始前调用，重置轮内状态"""
        self._current_issue = issue
        self._current_plan_summary = plan_summary
        self._current_steps = []
        self._step_outputs = {}

    def record_step(self, step: int, role: str, task: str, output: str):
        """子 Agent 完成后调用，将结果写入共享记忆"""
        self._current_steps.append({
            "step": step,
            "role": role,
            "task": task,
            "output": output,
        })
        self._step_outputs[step] = output

    def get_previous_output(self, step: int) -> Optional[str]:
        """获取上一步 Agent 的输出（直接接力内容）"""
        return self._step_outputs.get(step - 1)

    def get_current_pipeline_context(self) -> str:
        """
        返回当前流水线中 **已完成步骤** 的完整记录。
        每个后续 Agent 调用此方法，即可知道前面所有 Agent 做了什么。
        """
        if not self._current_steps:
            return "（当前流水线尚未完成任何步骤）"
        blocks = []
        for s in self._current_steps:
            blocks.append(
                f"【步骤 {s['step']} · {s['role']}】\n"
                f"任务：{s['task']}\n"
                f"完成结果：\n{s['output'][:800]}"
            )
        return "\n\n".join(blocks)

    def finish_pipeline(self, final_summary: str):
        """流水线全部完成后调用，把本轮记录存入历史"""
        self._pipeline_log.append({
            "issue":   self._current_issue,
            "plan":    self._current_plan_summary,
            "steps":   list(self._current_steps),  # 快照
            "summary": final_summary,
        })

    # ═══════════════════════════════════════════════════════════════
    #  调试用
    # ═══════════════════════════════════════════════════════════════

    def debug_dump(self):
        print(f"\n[SharedMemory] 对话轮数={len(self._conversation)}, "
              f"历史流水线={len(self._pipeline_log)}, "
              f"当前步骤={len(self._current_steps)}")
