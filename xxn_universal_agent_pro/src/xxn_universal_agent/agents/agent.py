"""
Pipeline Multi-Agent System

架构:
    User → InputGuard → LeaderAgent（拆解流水线）→ PipelineExecutor → Final Answer
                                        ↓
                            SubAgent-1 → SubAgent-2 → SubAgent-3 ...
                              ↓            ↓            ↓
                         结果存全局    读取前结果    读取前结果
                         记忆共享      +全局上下文    +全局上下文

核心设计:
1. GlobalMemory: 所有Agent共享的上下文池
2. LeaderAgent: 像真正的领导，拆任务时明确角色、依赖、传递关系
3. SubAgent: 每个节点拿到完整的上下文（自己任务+前置结果+全局记忆）
4. PipelineExecutor: 按顺序执行，保证数据流不中断
"""

import re
import json
import os
from typing import List, Dict, Optional

from ..core.llm import LLM
from ..core.memory import Memory
from ..core.state import AgentState, StateMachine
from ..tools.tools import ToolRegistry


def extract_json_object(text: str) -> Dict:
    """从LLM输出中提取第一个JSON对象。"""
    text = text.strip()
    matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    for raw in matches:
        try:
            return json.loads(raw)
        except Exception:
            continue

    start = text.find("{")
    if start == -1:
        raise ValueError("未找到JSON对象")

    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("JSON对象不完整")


# ═══════════════════════════════════════════════
# 全局共享记忆
# ═══════════════════════════════════════════════

class GlobalMemory:
    """
    全局共享记忆池
    
    解决痛点: 所有SubAgent都能访问到
    - 原始任务
    - Leader的分析和规划
    - 每个前置Agent的执行结果
    - 整个流水线的执行状态
    """

    def __init__(self):
        self.reset()

    def reset(self):
        """清空一次流水线运行产生的状态。"""
        self.original_task: str = ""           # 用户原始需求
        self.leader_analysis: str = ""         # Leader的核心分析
        self.pipeline: List[Dict] = []         # 流水线任务定义
        self.results: Dict[int, str] = {}      # 每个节点的执行结果 {task_id: result}
        self.agent_histories: Dict[int, List] = {}  # 每个Agent的对话历史
        self.verifier_records: List[Dict] = []  # Verifier检查记录
        self.final_answer: str = ""            # FinalSynthesisAgent生成的最终答案
        self.current_step: int = 0             # 当前执行到第几步
        self.status: str = "idle"              # idle / running / completed / error

    def set_task(self, task: str):
        self.original_task = task

    def set_leader_plan(self, analysis: str, pipeline: List[Dict]):
        self.leader_analysis = analysis
        self.pipeline = pipeline

    def save_result(self, task_id: int, result: str):
        self.results[task_id] = result
        self.current_step = task_id

    def add_verifier_record(self, stage: str, verdict: Dict):
        record = {"stage": stage, **verdict}
        self.verifier_records.append(record)

    def get_result(self, task_id: int) -> str:
        return self.results.get(task_id, "")

    def get_previous_result(self, current_id: int) -> str:
        """获取当前任务的前置结果"""
        current_task = self._find_task(current_id)
        if not current_task:
            return ""
        prev_id = current_task.get("input_from")
        if prev_id is None:
            return ""
        return self.results.get(prev_id, "")

    def get_global_context(self, current_id: int) -> str:
        """构建当前Agent能看到的全局上下文"""
        current_task = self._find_task(current_id)
        current_role = current_task["role"] if current_task else "未知"

        lines = [
            "═══ 全局上下文 ═══",
            f"【原始任务】{self.original_task}",
            f"【Leader分析】{self.leader_analysis}",
            "",
            "【流水线进度】",
        ]

        for task in self.pipeline:
            tid = task["id"]
            status = "✅" if tid in self.results else "⏳" if tid < current_id else "🔜"
            lines.append(f"  {status} Step {tid}: [{task['role']}] {task['task'][:40]}")

        # 前置结果 - 强调这是上游的具体交付物
        prev_result = self.get_previous_result(current_id)
        if prev_result:
            lines.extend([
                "",
                f"═══ 上游Agent交付给你的具体输入（你是【{current_role}】，必须基于此工作）═══",
                prev_result[:1500],  # 截断防止过长
                "",
                "⚠️ 重要：上面的内容是上游同事的具体交付物，不是状态描述。",
                "⚠️ 你必须基于上面的具体内容进行分析/加工，输出你的具体交付物给下游。",
            ])
        else:
            lines.extend([
                "",
                f"═══ 你是第一步（{current_role}），没有上游输入 ═══",
                "⚠️ 你必须输出具体的数据/事实/信息，作为下游Agent的输入。",
            ])

        lines.append(f"═══ 现在请执行你的任务：作为【{current_role}】，输出具体交付物 ═══")
        return "\n".join(lines)

    def _find_task(self, task_id: int) -> Optional[Dict]:
        for t in self.pipeline:
            if t["id"] == task_id:
                return t
        return None

    def build_final_report(self) -> str:
        """构建最终汇总报告"""
        lines = [
            f"# 任务完成报告",
            f"",
            f"**原始需求**: {self.original_task}",
            f"",
            f"**Leader分析**: {self.leader_analysis}",
            f"",
            f"---",
            f"",
        ]
        for task in self.pipeline:
            tid = task["id"]
            result = self.results.get(tid, "*未执行*")
            lines.extend([
                f"## Step {tid}: [{task['role']}] {task['task']}",
                f"",
                f"{result}",
                f"",
                f"---",
                f"",
            ])
        return "\n".join(lines)

    def export(self) -> Dict:
        return {
            "original_task": self.original_task,
            "leader_analysis": self.leader_analysis,
            "pipeline": self.pipeline,
            "results": self.results,
            "verifier_records": self.verifier_records,
            "final_answer": self.final_answer,
            "current_step": self.current_step,
            "status": self.status,
        }


# ═══════════════════════════════════════════════
# LeaderAgent —— 真正的领导
# ═══════════════════════════════════════════════

class LeaderAgent:
    """
    领导Agent
    
    职责:
    1. 理解整体任务
    2. 拆解为可串行执行的子任务
    3. 为每个子任务分配角色
    4. 明确任务间的输入/输出依赖关系
    
    输出格式（严格JSON）:
    {
        "analysis": "一句话核心分析",
        "pipeline": [
            {
                "id": 1,
                "role": "研究员",
                "task": "搜索最新市场数据",
                "input_from": null,
                "output_to": 2
            },
            {
                "id": 2,
                "role": "分析师",
                "task": "分析数据趋势并提炼关键洞察",
                "input_from": 1,
                "output_to": 3
            },
            {
                "id": 3,
                "role": "撰写员",
                "task": "基于分析结果撰写最终报告",
                "input_from": 2,
                "output_to": null
            }
        ]
    }
    """

    SYSTEM_PROMPT = """你是团队Leader，负责将复杂任务拆解为可执行的流水线。

【你的职责】
1. 分析任务核心本质（≤50字）
2. 拆解为2-5个串行子任务，每个任务必须明确：
   - id: 步骤编号（1,2,3...）
   - role: 执行者的角色定位（如"研究员"、"分析师"、"撰写员"）
   - task: 具体任务描述（一句话，≤50字）
   - input_from: 前置任务id（第一个任务填null）
   - output_to: 下游任务id（最后一个任务填null）

【拆解原则 - 关键】
- 任务之间必须有明确的数据传递关系
- 每个任务的输出必须是"具体交付物"，不能是状态描述（如"已完成"）
- 第一个任务（研究员）必须输出：具体数据、事实、原始信息
- 中间任务（分析师）必须输出：基于上游数据的具体分析、对比、洞察
- 最后一个任务（撰写员）必须输出：基于上游分析的完整结论和建议
- 每个任务描述中必须暗示"你需要输出什么具体内容供下游使用"

【输出格式 - 严格JSON】
{"analysis": "核心分析", "pipeline": [{"id": 1, "role": "...", "task": "...", "input_from": null, "output_to": 2}]}

【硬性规则】
1. 只输出纯JSON，无其他文字
2. 不要markdown代码块标记
3. 禁止废话、禁止解释、禁止过渡句
4. 确保任务描述暗示了具体的输出交付物
"""

    def __init__(self, llm: LLM):
        self.llm = llm

    def plan(self, task: str, feedback: str = "") -> Dict:
        """
        接收原始任务，输出流水线计划
        
        Returns:
            {"analysis": str, "pipeline": List[Dict]}
        """
        user_content = f"请拆解以下任务:\n\n{task}"
        if feedback:
            user_content += (
                "\n\n【上一次计划的Verifier反馈】\n"
                f"{feedback}\n"
                "请根据反馈重新拆解，仍然只输出严格JSON。"
            )

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        raw = self.llm.chat(messages)

        # 清理并解析JSON
        raw = raw.strip()
        raw = re.sub(r'^```\w*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        try:
            result = extract_json_object(raw)

            # 验证结构
            if "analysis" in result and "pipeline" in result:
                pipeline = result["pipeline"]
                # 验证每个任务有完整字段
                for p in pipeline:
                    p.setdefault("input_from", None)
                    p.setdefault("output_to", None)

                return {
                    "analysis": result["analysis"].strip(),
                    "pipeline": pipeline,
                }
        except Exception:
            pass

        # 解析失败，返回默认流水线
        return {
            "analysis": "任务需要分步骤执行",
            "pipeline": [
                {"id": 1, "role": "研究员", "task": "收集相关信息和数据", "input_from": None, "output_to": 2},
                {"id": 2, "role": "分析师", "task": "分析收集到的信息并提炼要点", "input_from": 1, "output_to": 3},
                {"id": 3, "role": "撰写员", "task": "基于分析结果输出最终答案", "input_from": 2, "output_to": None},
            ]
        }


# ═══════════════════════════════════════════════
# BaseReActAgent —— 统一ReAct循环
# ═══════════════════════════════════════════════

class BaseReActAgent:
    """SingleAgent和SubAgent共享的ReAct执行骨架。"""

    def __init__(self, llm: LLM, tools: ToolRegistry, max_steps: int = 10):
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.state_machine = StateMachine()

    def run_react_loop(
        self,
        memory: Memory,
        *,
        empty_answer_message: str = "[失败] Agent返回了空结果",
        format_error_message: str = "格式错误，请只输出JSON代码块",
    ) -> tuple[str, Memory]:
        """执行通用ReAct循环，并显式记录状态转换。"""
        self.state_machine = StateMachine()
        self._transition(AgentState.THINKING)

        for _ in range(self.max_steps):
            raw = self.llm.chat(memory.get())
            memory.add("assistant", raw)
            parsed = self._parse_json(raw)

            if parsed.get("type") == "final_answer":
                answer = str(parsed.get("answer", ""))
                if not answer.strip():
                    self._transition(AgentState.ERROR)
                    return empty_answer_message, memory
                self._transition(AgentState.FINISHED)
                return answer, memory

            if parsed.get("type") == "action":
                self._transition(AgentState.ACTING)
                tool_name = parsed.get("action", "")
                tool_input = parsed.get("action_input", "")
                observation = self._run_tool(tool_name, tool_input)
                self._transition(AgentState.OBSERVING)
                memory.add("user", f"Observation: {observation}")
                self._transition(AgentState.THINKING)
                continue

            memory.add("user", format_error_message)

        self._transition(AgentState.ERROR)
        return "[失败] 超过最大步数限制", memory

    def _run_tool(self, tool_name: str, tool_input: str) -> str:
        if tool_name in self.tools:
            observation = self.tools.run(tool_name, tool_input)
            if len(str(observation)) > 2000:
                observation = str(observation)[:2000] + "\n...(已截断)"
            if self._is_bad_observation(str(observation)):
                observation = (
                    str(observation)
                    + "\n[提示] 工具未返回有效数据。最终答案必须明确说明工具调用失败；"
                    + "如果继续回答，只能标注为基于已有知识的推断。"
                )
            return str(observation)
        return f"[错误] 工具 '{tool_name}' 不存在。请直接基于已有知识回答。"

    def _is_bad_observation(self, observation: str) -> bool:
        return any(keyword in observation for keyword in ("错误", "失败", "未找到"))

    def _parse_json(self, text: str) -> Dict:
        """从文本中提取JSON。兼容代码块和前后夹杂文字。"""
        try:
            result = extract_json_object(text)
            if "type" in result:
                return result
        except Exception:
            pass

        return {"type": "error", "raw": text[:300]}

    def _transition(self, state: AgentState):
        if not self.state_machine.transition(state):
            raise RuntimeError(f"非法Agent状态转换: {self.state_machine.state.name} -> {state.name}")


# ═══════════════════════════════════════════════
# VerifierAgent —— 质量检查闭环
# ═══════════════════════════════════════════════

class VerifierAgent:
    """Plan/Step/Final共用质量检查器。"""

    SCHEMA_HINT = """只输出严格JSON:
{
  "verdict": "pass" | "revise" | "fail",
  "score": 0-100,
  "issues": ["问题1", "问题2"],
  "required_fixes": ["必须修改点1"],
  "feedback": "给执行Agent的具体返工意见"
}
"""

    PROMPTS = {
        "plan": """你是PlanVerifier，负责审查Leader拆出的流水线计划。
检查:
1. pipeline是否覆盖用户原始需求
2. 每个步骤是否有明确输入输出
3. 是否存在无意义步骤或空泛步骤
4. 最后一步是否能产出用户真正想要的结果
如果小修可解决，verdict=revise；如果计划不可救，verdict=fail；否则pass。""",
        "step": """你是StepVerifier，负责审查流水线中单个SubAgent的交付物。
检查:
1. 是否完成当前task
2. 是否基于上游结果
3. 是否输出具体交付物，而不是“已完成”等状态描述
4. 是否有明显幻觉、空话、缺数据
5. 是否足够给下游使用
如果需要返工，verdict=revise并给出具体feedback；无法修复则fail；否则pass。""",
        "final": """你是FinalVerifier，负责审查最终答案。
检查:
1. 是否直接满足原始需求
2. 是否遗漏关键约束
3. 是否自相矛盾
4. 是否只是机械拼接而非综合回答
如果需要重写，verdict=revise并给出具体feedback；无法修复则fail；否则pass。""",
    }

    def __init__(self, llm: LLM, kind: str):
        if kind not in self.PROMPTS:
            raise ValueError(f"未知Verifier类型: {kind}")
        self.llm = llm
        self.kind = kind

    def verify(
        self,
        *,
        original_task: str,
        leader_analysis: str = "",
        pipeline: Optional[List[Dict]] = None,
        current_step: Optional[Dict] = None,
        upstream_result: str = "",
        current_output: str = "",
        final_answer: str = "",
    ) -> Dict:
        payload = {
            "original_task": original_task,
            "leader_analysis": leader_analysis,
            "pipeline": pipeline or [],
            "current_step": current_step or {},
            "upstream_result": upstream_result,
            "current_output": current_output,
            "final_answer": final_answer,
        }
        messages = [
            {
                "role": "system",
                "content": f"{self.PROMPTS[self.kind]}\n\n{self.SCHEMA_HINT}",
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]
        raw = self.llm.chat(messages)
        try:
            verdict = extract_json_object(raw)
        except Exception as exc:
            raise ValueError(f"{self.kind} verifier未返回有效JSON: {raw[:300]}") from exc
        return self._normalize(verdict)

    def _normalize(self, verdict: Dict) -> Dict:
        value = str(verdict.get("verdict", "")).lower()
        if value not in ("pass", "revise", "fail"):
            value = "fail"
        try:
            score = int(verdict.get("score", 0))
        except Exception:
            score = 0
        score = max(0, min(100, score))
        issues = verdict.get("issues", [])
        required_fixes = verdict.get("required_fixes", [])
        if not isinstance(issues, list):
            issues = [str(issues)]
        if not isinstance(required_fixes, list):
            required_fixes = [str(required_fixes)]
        return {
            "verdict": value,
            "score": score,
            "issues": [str(x) for x in issues],
            "required_fixes": [str(x) for x in required_fixes],
            "feedback": str(verdict.get("feedback", "")),
        }


class FinalSynthesisAgent:
    """基于全部Step结果重新综合最终答案，而不是机械拼接报告。"""

    SYSTEM_PROMPT = """你是FinalSynthesisAgent，负责把多Agent流水线结果综合成最终答案。
要求:
1. 必须直接回答用户原始问题
2. 保留关键证据、数据、结论和必要风险
3. 不要机械拼接每个Step全文
4. 结构清晰，语言自然
5. 只输出严格JSON: {"type": "final_answer", "answer": "最终答案"}"""

    def __init__(self, llm: LLM):
        self.llm = llm

    def synthesize(
        self,
        *,
        original_task: str,
        leader_analysis: str,
        pipeline: List[Dict],
        results: Dict[int, str],
        feedback: str = "",
    ) -> str:
        payload = {
            "original_task": original_task,
            "leader_analysis": leader_analysis,
            "pipeline": pipeline,
            "step_results": results,
            "verifier_feedback": feedback,
        }
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]
        raw = self.llm.chat(messages)
        try:
            parsed = extract_json_object(raw)
            if parsed.get("type") == "final_answer" and str(parsed.get("answer", "")).strip():
                return str(parsed["answer"])
        except Exception:
            pass
        return raw.strip()


# ═══════════════════════════════════════════════
# SubAgent —— 流水线中的执行节点
# ═══════════════════════════════════════════════

class SubAgent(BaseReActAgent):
    """
    流水线执行节点
    
    每个SubAgent:
    1. 知道自己扮演的角色
    2. 知道自己的具体任务
    3. 能读取前置Agent的结果
    4. 能读取全局上下文（原始任务+Leader分析+执行进度）
    5. 有自己的对话历史（用于多轮思考）
    6. 执行完毕后把结果写回GlobalMemory
    """

    def __init__(self, llm: LLM, tools: ToolRegistry, global_memory: GlobalMemory):
        super().__init__(llm, tools, max_steps=10)
        self.global_memory = global_memory

    def run(self, task_def: Dict, feedback: str = "", previous_output: str = "") -> str:
        """
        执行一个子任务
        
        Args:
            task_def: {"id", "role", "task", "input_from", "output_to"}
        
        Returns:
            执行结果字符串
        """
        task_id = task_def["id"]
        role = task_def["role"]
        task_desc = task_def["task"]

        # 构建完整的上下文输入
        global_ctx = self.global_memory.get_global_context(task_id)

        # 计算上下游信息
        total_steps = len(self.global_memory.pipeline)
        upstream = self.global_memory._find_task(task_def.get("input_from")) if task_def.get("input_from") else None
        downstream = self.global_memory._find_task(task_def.get("output_to")) if task_def.get("output_to") else None
        upstream_role = upstream["role"] if upstream else "无（你是第一个）"
        downstream_role = downstream["role"] if downstream else "无（你是最后一个）"

        # 构建System Prompt（注入角色和约束）
        system_prompt = f"""你是团队中的【{role}】。

{self.tools.build_prompt()}

【你的角色定位】
- 你在流水线中的位置：第 {task_id} 步 / 共 {total_steps} 步
- 你的上游（给你输入）：{upstream_role}
- 你的下游（消费你的输出）：{downstream_role}
- 你的使命：输出具体、结构化、可消费的交付物，让下游拿到就能继续工作

【你的职责】
{task_desc}

【核心红线 - 违反则任务失败】
1. **禁止输出状态描述**：绝不输出"已完成""无法完成""缺少工具"等废话
2. **必须输出具体交付物**：数据、事实、分析、对比、结论——要具体到下游能直接用
3. **你的输出质量决定流水线成败**：如果输出是垃圾，下游就会崩溃
4. **工具是手段不是目的**：如果工具搜不到，基于你的知识也要给出详细回答
5. **输出要像"交接文档"**：下一个同事拿到你的输出，不需要再问任何问题就能继续

【输出质量标准】
- 研究员：必须输出具体数据点（数字、来源、时间、样本量）
- 分析师：必须输出结构化对比（表格/分点/趋势/原因）
- 撰写员：必须输出完整结论（建议+理由+风险提示）

【格式规则】
- 如果需要使用工具，输出JSON: {{"type": "action", "action": "工具名", "action_input": "输入"}}
- 完成时输出JSON: {{"type": "final_answer", "answer": "你的具体交付物"}}
- 禁止废话、禁止过渡句、禁止状态描述
"""

        # 初始化记忆（包含全局上下文）
        memory = Memory(system_prompt=system_prompt, max_messages=15)
        memory.add("user", global_ctx)
        if feedback:
            retry_prompt = [
                "【Verifier返工意见】",
                feedback,
            ]
            if previous_output:
                retry_prompt.extend([
                    "",
                    "【上一次不合格输出】",
                    previous_output[:2000],
                ])
            retry_prompt.append("请根据返工意见重新执行当前任务，输出更具体、可验证、可交付的结果。")
            memory.add("user", "\n".join(retry_prompt))

        answer, memory = self.run_react_loop(
            memory,
            empty_answer_message="[失败] Agent返回了空交付物",
            format_error_message="格式错误，请严格输出JSON代码块",
        )
        self.global_memory.agent_histories[task_id] = memory.get()
        return answer


# ═══════════════════════════════════════════════
# PipelineExecutor —— 流水线执行器
# ═══════════════════════════════════════════════

class PipelineExecutor:
    """
    流水线执行器
    
    职责:
    1. 按顺序执行Leader规划的子任务
    2. 保证数据流：前置结果 → 当前Agent
    3. 管理全局记忆
    4. 输出最终汇总报告
    """

    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        *,
        enable_plan_verifier: Optional[bool] = None,
        enable_step_verifier: Optional[bool] = None,
        enable_final_verifier: Optional[bool] = None,
        max_verify_retries: Optional[int] = None,
    ):
        self.llm = llm
        self.tools = tools
        self.global_memory = GlobalMemory()
        self.leader = LeaderAgent(llm)
        self.plan_verifier = VerifierAgent(llm, "plan")
        self.step_verifier = VerifierAgent(llm, "step")
        self.final_synthesis = FinalSynthesisAgent(llm)
        self.final_verifier = VerifierAgent(llm, "final")
        mode = os.environ.get("VERIFY_MODE", "off").strip().lower()
        defaults = {
            "off": (False, False, False),
            "final": (False, False, True),
            "full": (True, True, True),
        }.get(mode, (False, False, False))
        self.enable_plan_verifier = self._env_bool("ENABLE_PLAN_VERIFIER", defaults[0], enable_plan_verifier)
        self.enable_step_verifier = self._env_bool("ENABLE_STEP_VERIFIER", defaults[1], enable_step_verifier)
        self.enable_final_verifier = self._env_bool("ENABLE_FINAL_VERIFIER", defaults[2], enable_final_verifier)
        self.max_verify_retries = self._env_int("VERIFY_MAX_RETRIES", 1, max_verify_retries)

    def _env_bool(self, name: str, default: bool, explicit: Optional[bool]) -> bool:
        if explicit is not None:
            return explicit
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "on")

    def _env_int(self, name: str, default: int, explicit: Optional[int]) -> int:
        if explicit is not None:
            return max(0, int(explicit))
        value = os.environ.get(name)
        if value is None or not value.strip():
            return default
        try:
            return max(0, int(value))
        except ValueError:
            return default

    def validate_pipeline(self, pipeline: List[Dict]) -> List[Dict]:
        """验证并规范化Leader给出的线性流水线计划。"""
        if not isinstance(pipeline, list) or not pipeline:
            raise ValueError("Leader未返回有效pipeline")

        ids = []
        normalized = []
        for idx, task in enumerate(pipeline, start=1):
            if not isinstance(task, dict):
                raise ValueError(f"Step {idx} 不是dict")
            for field in ("id", "role", "task"):
                if field not in task or task[field] in ("", None):
                    raise ValueError(f"Step {idx} 缺少必要字段: {field}")
            try:
                tid = int(task["id"])
            except Exception as exc:
                raise ValueError(f"Step {idx} 的id不是整数") from exc
            ids.append(tid)
            normalized.append({
                "id": tid,
                "role": str(task["role"]),
                "task": str(task["task"]),
                "input_from": task.get("input_from"),
                "output_to": task.get("output_to"),
            })

        if len(ids) != len(set(ids)):
            raise ValueError("pipeline中存在重复id")

        id_set = set(ids)
        for task in normalized:
            for edge_name in ("input_from", "output_to"):
                edge = task.get(edge_name)
                if edge is None:
                    continue
                try:
                    edge = int(edge)
                except Exception as exc:
                    raise ValueError(f"Step {task['id']} 的 {edge_name} 不是整数或null") from exc
                if edge not in id_set:
                    raise ValueError(f"Step {task['id']} 的 {edge_name} 指向不存在的Step {edge}")
                task[edge_name] = edge

        # 当前版本是线性流水线：按id升序执行，并要求每步依赖已完成节点。
        normalized.sort(key=lambda x: x["id"])
        completed = set()
        for pos, task in enumerate(normalized):
            prev = task.get("input_from")
            if pos == 0 and prev is not None:
                raise ValueError("第一个Step不应依赖上游")
            if pos > 0 and prev not in completed:
                raise ValueError(f"Step {task['id']} 依赖尚未执行的Step {prev}")
            completed.add(task["id"])

        return normalized

    def run(self, task: str) -> str:
        """
        执行完整流水线
        
        Args:
            task: 用户原始任务
        
        Returns:
            最终汇总结果
        """
        print(f"\n{'='*60}")
        print(f"🎯 原始任务: {task[:80]}{'...' if len(task) > 80 else ''}")
        print(f"{'='*60}")

        # Step 0: 每次运行使用干净状态，避免多轮任务互相污染
        self.global_memory.reset()
        self.global_memory.status = "running"
        self.global_memory.set_task(task)

        # Step 1: Leader拆解任务 + PlanVerifier检查
        print("\n[Step 0] Leader分析并拆解任务...")
        plan_feedback = ""
        plan = None
        if self.enable_plan_verifier:
            for attempt in range(self.max_verify_retries + 1):
                plan = self.leader.plan(task, feedback=plan_feedback)
                plan_verdict = self.plan_verifier.verify(
                    original_task=task,
                    leader_analysis=plan.get("analysis", ""),
                    pipeline=plan.get("pipeline", []),
                )
                self.global_memory.add_verifier_record("plan", plan_verdict)
                if plan_verdict["verdict"] == "pass":
                    break
                if plan_verdict["verdict"] == "fail":
                    self.global_memory.status = "error"
                    raise RuntimeError(f"PlanVerifier判定失败: {plan_verdict['issues']}")
                if attempt >= self.max_verify_retries:
                    self.global_memory.status = "error"
                    raise RuntimeError(f"PlanVerifier多次要求修改仍未通过: {plan_verdict['feedback']}")
                plan_feedback = plan_verdict["feedback"] or "请补全计划覆盖范围、输入输出和最终交付物。"
                print(f"  🔎 PlanVerifier要求重规划: {plan_feedback}")
        else:
            plan = self.leader.plan(task)

        analysis = plan["analysis"]
        try:
            pipeline = self.validate_pipeline(plan["pipeline"])
        except Exception as exc:
            self.global_memory.status = "error"
            raise ValueError(f"Leader流水线计划无效: {exc}") from exc

        self.global_memory.set_leader_plan(analysis, pipeline)

        print(f"  📋 核心分析: {analysis}")
        print(f"  📊 拆解为 {len(pipeline)} 个串行任务:")
        for p in pipeline:
            arrow = "→" if p.get("output_to") else "→[终]"
            prev = f"(接Step{p['input_from']})" if p.get("input_from") else "(起点)"
            print(f"     Step {p['id']}: [{p['role']}] {p['task'][:40]} {prev} {arrow}")

        # Step 2: 按顺序执行每个子任务
        print(f"\n{'='*60}")
        print("开始流水线执行...")
        print(f"{'='*60}")

        try:
            for task_def in pipeline:
                tid = task_def["id"]
                role = task_def["role"]

                print(f"\n--- Step {tid}/{len(pipeline)} ---")
                print(f"🎭 角色: {role}")
                print(f"📝 任务: {task_def['task']}")

                # 获取前置结果提示
                prev_id = task_def.get("input_from")
                if prev_id:
                    prev_result = self.global_memory.get_result(prev_id)
                    print(f"📥 前置输入: {prev_result[:80]}{'...' if len(prev_result) > 80 else ''}")
                else:
                    print(f"📥 前置输入: (无，这是第一个任务)")

                # 执行
                agent = SubAgent(self.llm, self.tools, self.global_memory)
                feedback = ""
                previous_output = ""
                result = ""
                for attempt in range(self.max_verify_retries + 1):
                    result = agent.run(task_def, feedback=feedback, previous_output=previous_output)
                    if result.startswith("[失败]"):
                        raise RuntimeError(f"Step {tid} 执行失败: {result}")

                    if not self.enable_step_verifier:
                        break

                    step_verdict = self.step_verifier.verify(
                        original_task=task,
                        leader_analysis=analysis,
                        pipeline=pipeline,
                        current_step=task_def,
                        upstream_result=self.global_memory.get_previous_result(tid),
                        current_output=result,
                    )
                    self.global_memory.add_verifier_record(f"step_{tid}", step_verdict)
                    if step_verdict["verdict"] == "pass":
                        break
                    if step_verdict["verdict"] == "fail":
                        raise RuntimeError(f"StepVerifier判定Step {tid} 失败: {step_verdict['issues']}")
                    if attempt >= self.max_verify_retries:
                        raise RuntimeError(f"Step {tid} 多次返工仍未通过: {step_verdict['feedback']}")
                    feedback = step_verdict["feedback"] or "请补充具体交付物，并显式基于上游结果。"
                    previous_output = result
                    print(f"🔎 StepVerifier要求Step {tid}返工: {feedback}")

                # 保存结果
                self.global_memory.save_result(tid, result)

                print(f"📤 输出结果: {result[:120]}{'...' if len(result) > 120 else ''}")
        except Exception:
            self.global_memory.status = "error"
            raise

        # Step 3: 最终综合 + FinalVerifier检查
        print(f"\n{'='*60}")
        print("流水线执行完毕，综合最终答案...")
        print(f"{'='*60}")

        final_feedback = ""
        report = ""
        for attempt in range(self.max_verify_retries + 1):
            report = self.final_synthesis.synthesize(
                original_task=task,
                leader_analysis=analysis,
                pipeline=pipeline,
                results=self.global_memory.results,
                feedback=final_feedback,
            )
            if not self.enable_final_verifier:
                break
            final_verdict = self.final_verifier.verify(
                original_task=task,
                leader_analysis=analysis,
                pipeline=pipeline,
                final_answer=report,
            )
            self.global_memory.add_verifier_record("final", final_verdict)
            if final_verdict["verdict"] == "pass":
                break
            if final_verdict["verdict"] == "fail":
                self.global_memory.status = "error"
                raise RuntimeError(f"FinalVerifier判定失败: {final_verdict['issues']}")
            if attempt >= self.max_verify_retries:
                self.global_memory.status = "error"
                raise RuntimeError(f"FinalVerifier多次要求修改仍未通过: {final_verdict['feedback']}")
            final_feedback = final_verdict["feedback"] or "请直接回答原始需求，补充遗漏约束并消除矛盾。"
            print(f"  🔎 FinalVerifier要求重写最终答案: {final_feedback}")

        self.global_memory.final_answer = report
        self.global_memory.status = "completed"
        return report


# ═══════════════════════════════════════════════
# 单Agent（保留，用于InputGuard的LEVEL2）
# ═══════════════════════════════════════════════

class SingleAgent(BaseReActAgent):
    """
    单Agent模式（ReAct循环）
    用于处理简单任务，不走流水线
    """

    def __init__(self, llm: LLM, tools: ToolRegistry):
        super().__init__(llm, tools, max_steps=12)

    def run(self, task: str) -> str:
        system_prompt = f"""你是任务执行Agent。

{self.tools.build_prompt()}

## 输出格式（严格JSON）
使用工具: {{"type": "action", "action": "工具名", "action_input": "输入"}}
任务完成: {{"type": "final_answer", "answer": "结果"}}

## 规则
1. 只输出一个JSON代码块
2. 禁止废话
"""
        memory = Memory(system_prompt=system_prompt, max_messages=20)
        memory.add("user", task)

        answer, _ = self.run_react_loop(memory)
        return answer
