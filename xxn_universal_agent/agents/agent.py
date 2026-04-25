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
from typing import List, Dict, Optional

from core.llm import LLM
from core.memory import Memory
from tools.tools import ToolRegistry


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
        self.original_task: str = ""           # 用户原始需求
        self.leader_analysis: str = ""         # Leader的核心分析
        self.pipeline: List[Dict] = []         # 流水线任务定义
        self.results: Dict[int, str] = {}      # 每个节点的执行结果 {task_id: result}
        self.agent_histories: Dict[int, List] = {}  # 每个Agent的对话历史
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

    def plan(self, task: str) -> Dict:
        """
        接收原始任务，输出流水线计划
        
        Returns:
            {"analysis": str, "pipeline": List[Dict]}
        """
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"请拆解以下任务:\n\n{task}"},
        ]

        raw = self.llm.chat(messages)

        # 清理并解析JSON
        raw = raw.strip()
        raw = re.sub(r'^```\w*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        try:
            match = re.search(r'\{[\s\S]+\}', raw)
            if match:
                result = json.loads(match.group())

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
# SubAgent —— 流水线中的执行节点
# ═══════════════════════════════════════════════

class SubAgent:
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
        self.llm = llm
        self.tools = tools
        self.global_memory = global_memory
        self.max_steps = 10

    def run(self, task_def: Dict) -> str:
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

        # ReAct循环
        for step in range(self.max_steps):
            raw = self.llm.chat(memory.get())
            memory.add("assistant", raw)

            parsed = self._parse_json(raw)

            if parsed.get("type") == "final_answer":
                answer = parsed.get("answer", "")
                # 保存到自己的历史
                self.global_memory.agent_histories[task_id] = memory.get()
                return answer

            elif parsed.get("type") == "action":
                tool_name = parsed.get("action", "")
                tool_input = parsed.get("action_input", "")

                if tool_name in self.tools:
                    observation = self.tools.run(tool_name, tool_input)
                    # 截断过长结果
                    if len(str(observation)) > 2000:
                        observation = str(observation)[:2000] + "\n...(已截断)"
                    # 如果工具返回错误或空，提示LLM基于知识继续
                    if "错误" in str(observation) or "失败" in str(observation) or "未找到" in str(observation):
                        observation = str(observation) + "\n[提示] 工具未返回有效数据，请基于你的知识和已有上下文继续推理并给出答案，不要放弃。"
                else:
                    observation = f"[错误] 工具 '{tool_name}' 不存在。请直接基于已有知识回答。"

                memory.add("user", f"Observation: {observation}")

            else:
                memory.add("user", "格式错误，请严格输出JSON代码块")

        return "[失败] 超过最大步数限制"

    def _parse_json(self, text: str) -> Dict:
        """从文本中提取JSON"""
        text = text.strip()
        matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        for raw in matches:
            try:
                result = json.loads(raw)
                if "type" in result:
                    return result
            except:
                continue

        try:
            start = text.find("{")
            if start != -1:
                depth = 0
                for i, ch in enumerate(text[start:], start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            result = json.loads(text[start:i+1])
                            if "type" in result:
                                return result
                            break
        except:
            pass

        return {"type": "error", "raw": text[:300]}


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

    def __init__(self, llm: LLM, tools: ToolRegistry):
        self.llm = llm
        self.tools = tools
        self.global_memory = GlobalMemory()
        self.leader = LeaderAgent(llm)

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

        # Step 0: 保存原始任务
        self.global_memory.set_task(task)

        # Step 1: Leader拆解任务
        print("\n[Step 0] Leader分析并拆解任务...")
        plan = self.leader.plan(task)

        analysis = plan["analysis"]
        pipeline = plan["pipeline"]

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
            result = agent.run(task_def)

            # 保存结果
            self.global_memory.save_result(tid, result)

            print(f"📤 输出结果: {result[:120]}{'...' if len(result) > 120 else ''}")

        # Step 3: 最终汇总
        print(f"\n{'='*60}")
        print("流水线执行完毕，生成最终报告...")
        print(f"{'='*60}")

        report = self.global_memory.build_final_report()
        return report


# ═══════════════════════════════════════════════
# 单Agent（保留，用于InputGuard的LEVEL2）
# ═══════════════════════════════════════════════

class SingleAgent:
    """
    单Agent模式（ReAct循环）
    用于处理简单任务，不走流水线
    """

    def __init__(self, llm: LLM, tools: ToolRegistry):
        self.llm = llm
        self.tools = tools
        self.max_steps = 12

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

        for step in range(self.max_steps):
            raw = self.llm.chat(memory.get())
            memory.add("assistant", raw)

            parsed = self._parse_json(raw)

            if parsed.get("type") == "final_answer":
                return parsed.get("answer", "")

            elif parsed.get("type") == "action":
                tool_name = parsed.get("action", "")
                tool_input = parsed.get("action_input", "")

                if tool_name in self.tools:
                    obs = self.tools.run(tool_name, tool_input)
                    if len(str(obs)) > 2000:
                        obs = str(obs)[:2000] + "\n...(已截断)"
                else:
                    obs = f"[错误] 工具'{tool_name}'不存在"

                memory.add("user", f"Observation: {obs}")

            else:
                memory.add("user", "格式错误，请只输出JSON代码块")

        return "[失败] 超过最大步数限制"

    def _parse_json(self, text: str) -> Dict:
        text = text.strip()
        matches = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
        for raw in matches:
            try:
                result = json.loads(raw)
                if "type" in result:
                    return result
            except:
                continue

        try:
            start = text.find("{")
            if start != -1:
                depth = 0
                for i, ch in enumerate(text[start:], start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            result = json.loads(text[start:i+1])
                            if "type" in result:
                                return result
                            break
        except:
            pass

        return {"type": "error", "raw": text[:300]}
