"""
Pipeline - 流水线编排器

负责：
1. 调用 PipelineLeader 制定计划
2. 按序驱动每个 PipelineAgent 执行
3. 把每步结果写入 SharedMemory（agent 内部完成）
4. 执行完毕后汇总并封存到历史
"""

from llm import LLM
from lead_agent import PipelineLeader
from pipeline_agent import PipelineAgent
from shared_memory import SharedMemory


class Pipeline:
    """
    流水线编排器

    用法：
        pipeline = Pipeline(llm)
        final = pipeline.run(issue, shared_memory)
        print(final)
    """

    def __init__(self, llm: LLM):
        self.llm    = llm
        self.leader = PipelineLeader(llm)

    def run(self, issue: str, shared_memory: SharedMemory) -> str:
        """
        执行一次完整的流水线任务。

        Args:
            issue:         用户问题（已拼接历史上下文的 full_input）
            shared_memory: 全局共享记忆

        Returns:
            最终步骤的输出字符串
        """
        print(f"\n{'='*65}")
        print(f"[Pipeline] 任务：{issue[:80]}{'...' if len(issue) > 80 else ''}")
        print(f"{'='*65}")

        # ── Step 1: Lead 制定流水线计划 ──────────────────────────
        print("\n[1/N] Lead Agent 规划流水线...")

        conv_ctx      = shared_memory.get_conversation_summary()
        pipe_history  = shared_memory.get_pipeline_history()

        plan = self.leader.plan(issue, conv_ctx, pipe_history)

        analysis  = plan.get("analysis", "")
        steps     = plan.get("pipeline", [])

        print(f"  核心分析：{analysis}")
        print(f"  流水线共 {len(steps)} 步：")
        for s in steps:
            arrow = "→" if s.get("pass_to_next") else "✓"
            print(f"    步骤{s['step']} [{s['role']}] {arrow}  {s['task'][:50]}")

        if not steps:
            print("  [警告] 流水线为空，任务终止")
            return "流水线规划失败，无可执行步骤"

        # 初始化当前流水线的共享记忆槽
        plan_summary = f"分析：{analysis} | 步骤：" + " → ".join(
            f"{s['role']}" for s in steps
        )
        shared_memory.start_new_pipeline(issue, plan_summary)

        # ── Step 2: 顺序执行每个子 Agent ─────────────────────────
        print(f"\n[2/N] 顺序执行 {len(steps)} 个子 Agent...")

        final_result = ""
        for step_info in steps:
            step_num = step_info["step"]
            role     = step_info["role"]

            print(f"\n  ── 步骤 {step_num} / {len(steps)} [{role}] ──")
            print(f"     任务：{step_info['task'][:70]}")

            agent  = PipelineAgent(self.llm, step_info, shared_memory)
            result = agent.run()

            # 预览输出
            preview = result[:120].replace('\n', ' ')
            print(f"     输出：{preview}{'...' if len(result) > 120 else ''}")
            print(f"     状态：✓ 完成，已写入共享记忆")

            final_result = result

        # ── Step 3: 封存本轮流水线到历史 ─────────────────────────
        shared_memory.finish_pipeline(final_result)

        # ── 打印最终结果 ──────────────────────────────────────────
        print(f"\n{'='*65}")
        print("[Pipeline] 最终结果")
        print(f"{'='*65}")
        if len(final_result) > 800:
            print(final_result[:800] + "\n...(已截断，完整结果见上方步骤输出)")
        else:
            print(final_result)

        return final_result
